import streamlit as st
import gspread
import pandas as pd
from supabase import create_client

# --- 設定 ---
st.set_page_config(page_title="Data Migration Final", layout="wide")
st.title("🚀 Football App - データ移行 (完全版)")

# --- 接続確立 ---
try:
    if "supabase" in st.secrets:
        supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
        st.success("✅ Supabase 接続成功")
    else:
        st.error("Supabase secrets missing")
        st.stop()
        
    if "gcp_service_account" in st.secrets:
        gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
        st.success("✅ Google Sheets 接続成功")
    else:
        st.error("Google Sheets secrets missing")
        st.stop()
except Exception as e:
    st.error(f"接続エラー: {e}")
    st.stop()

# --- ユーティリティ関数 ---
def find_sheet_by_columns(sh, keywords):
    """指定したキーワードを含む列を持つシートを探す"""
    for ws in sh.worksheets():
        try:
            # ヘッダー行を取得して小文字化・空白除去
            headers = [str(h).lower().strip() for h in ws.row_values(1)]
            # 全キーワードが含まれているかチェック
            if all(any(k in h for h in headers) for k in keywords):
                return ws
        except:
            continue
    return None

def to_int_or_none(val):
    """空文字や不正な値を None に変換する安全装置"""
    if val == "" or val is None:
        return None
    try:
        # "1.0" のような文字列も一度floatにしてからintにする
        return int(float(val))
    except:
        return None

def to_float_or_default(val, default=1.0):
    try:
        return float(val)
    except:
        return default

# --- メイン移行処理 ---
if st.button("🚀 移行実行 (最終修正版)"):
    status_log = st.empty()
    
    # ---------------------------------------------------------
    # 1. 試合データ (oddsシート相当)
    # ---------------------------------------------------------
    status_log.info("1/4: 試合データ(odds)を処理中...")
    ws_odds = find_sheet_by_columns(sh, ["match_id", "home", "away"])
    
    if not ws_odds:
        st.error("❌ 'odds' 相当のシートが見つかりません (match_id, home, away)")
        st.stop()
        
    odds_data = ws_odds.get_all_records()
    matches_payload = {} 

    for row in odds_data:
        mid = to_int_or_none(row.get("match_id"))
        if not mid:
            continue # IDがない行はスキップ
        
        # 'home\n' など表記揺れ対応
        home = row.get("home") or row.get("home\n") or row.get("Home") or "Unknown"
        away = row.get("away") or row.get("Away") or "Unknown"
        
        matches_payload[mid] = {
            "match_id": mid,
            "season": "2024-2025",
            "gameweek": to_int_or_none(row.get("gw")),
            "home_team": str(home).strip(),
            "away_team": str(away).strip(),
            "status": "FINISHED", # 過去データは完了扱い
            "home_score": None,
            "away_score": None
        }

    # ---------------------------------------------------------
    # 2. 試合結果 (resultシート相当)
    # ---------------------------------------------------------
    status_log.info("2/4: 試合結果(result)をマージ中...")
    ws_result = find_sheet_by_columns(sh, ["match_id", "home_score", "away_score"])
    
    if ws_result:
        res_data = ws_result.get_all_records()
        for row in res_data:
            mid = to_int_or_none(row.get("match_id"))
            if mid in matches_payload:
                matches_payload[mid]["home_score"] = to_int_or_none(row.get("home_score"))
                matches_payload[mid]["away_score"] = to_int_or_none(row.get("away_score"))
    
    # 試合データ送信
    if matches_payload:
        data_list = list(matches_payload.values())
        chunk_size = 100
        for i in range(0, len(data_list), chunk_size):
            chunk = data_list[i:i + chunk_size]
            supabase.table("matches").upsert(chunk).execute()
        st.write(f"✅ 試合データ移行完了: {len(matches_payload)}件")
    
    # ---------------------------------------------------------
    # 3. ユーザー抽出 (betsシート相当)
    # ---------------------------------------------------------
    status_log.info("3/4: ユーザーを抽出中...")
    ws_bets = find_sheet_by_columns(sh, ["user", "pick", "stake"])
    
    if not ws_bets:
        st.error("❌ 'bets' 相当のシートが見つかりません")
        st.stop()
        
    bets_data = ws_bets.get_all_records()
    unique_users = set()
    
    for row in bets_data:
        u = row.get("user")
        if u:
            unique_users.add(str(u).strip())
        
    for u in unique_users:
        supabase.table("users").upsert({"username": u, "balance": 10000}, on_conflict="username").execute()
        
    # IDマップ作成
    db_users = supabase.table("users").select("user_id, username").execute().data
    user_map = {u['username']: u['user_id'] for u in db_users}
    st.write(f"✅ ユーザー登録完了: {len(unique_users)}名")

    # ---------------------------------------------------------
    # 4. ベット履歴 (betsシート相当)
    # ---------------------------------------------------------
    status_log.info("4/4: ベット履歴を移行中...")
    
    bets_payload = []
    for row in bets_data:
        u_name = str(row.get("user")).strip()
        mid = to_int_or_none(row.get("match_id"))
        
        if u_name in user_map and mid:
            # マッチIDが試合データに存在するものだけ対象
            if mid in matches_payload:
                bets_payload.append({
                    "user_id": user_map[u_name],
                    "match_id": mid,
                    "choice": str(row.get("pick", "")),
                    "stake": to_int_or_none(row.get("stake")),
                    "odds_at_bet": to_float_or_default(row.get("odds")),
                    "status": "PENDING"
                })
    
    if bets_payload:
        # 分割送信
        for i in range(0, len(bets_payload), chunk_size):
            chunk = bets_payload[i:i + chunk_size]
            supabase.table("bets").insert(chunk).execute()
        st.write(f"✅ ベット履歴移行完了: {len(bets_payload)}件")

    st.balloons()
    st.success("🎉 全データ移行プロセス完了！お疲れ様でした！")
