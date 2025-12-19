import streamlit as st
import gspread
from supabase import create_client
import pandas as pd

st.set_page_config(page_title="V2 Final Migration", layout="wide")
st.title("🚀 Football App V2 - 最終移行ツール")

# --- 接続確立 ---
try:
    # Google Sheets
    if "gcp_service_account" in st.secrets:
        creds = st.secrets["gcp_service_account"]
        gc = gspread.service_account_from_dict(creds)
        sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
        st.success(f"✅ Google Sheets 接続成功: {sh.title}")
    else:
        st.error("Google認証情報がありません")
        st.stop()

    # Supabase
    if "supabase" in st.secrets:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        supabase = create_client(url, key)
        st.success("✅ Supabase 接続成功")
    else:
        st.error("Supabase情報がありません")
        st.stop()
        
except Exception as e:
    st.error(f"接続エラー: {e}")
    st.stop()

st.divider()

# --- シート選択UI ---
st.subheader("1. シートの割り当て")
st.info("データが入っているシート名を選択してください。")

# 全シート名を取得
worksheet_list = sh.worksheets()
sheet_names = [ws.title for ws in worksheet_list]

col1, col2 = st.columns(2)
with col1:
    # 試合日程のシートを選ぶ
    # "schedule" や "fixture" が含まれるシートを初期値にする
    default_sched = 0
    for i, name in enumerate(sheet_names):
        if "schedule" in name.lower() or "fixture" in name.lower() or "match" in name.lower():
            default_sched = i
            break
    sheet_matches = st.selectbox("📅 試合日程 (Matches) のシート", sheet_names, index=default_sched)

with col2:
    # ベット履歴のシートを選ぶ
    # "bet" が含まれるシートを初期値にする
    default_bets = 0
    for i, name in enumerate(sheet_names):
        if "bet" in name.lower():
            default_bets = i
            break
    sheet_bets = st.selectbox("🎫 ベット履歴 (Bets) のシート", sheet_names, index=default_bets)

st.divider()

# --- 移行ロジック ---
st.subheader("2. データ移行の実行")

if st.button("🚀 移行スタート (確定版)"):
    status = st.empty()
    
    # -------------------------------------------------
    # 1. ユーザーの自動検出と登録
    # -------------------------------------------------
    status.info("ユーザーをスキャン中...")
    try:
        ws_bets = sh.worksheet(sheet_bets)
        bets_data = ws_bets.get_all_records()
        
        # あなたのカラム名 'user' を使用
        found_users = set()
        for row in bets_data:
            if row.get("user"): # 'user'列があるか確認
                found_users.add(str(row["user"])) # 文字列として取得
        
        if not found_users:
            st.error(f"シート '{sheet_bets}' に 'user' 列が見つからないか、データが空です。")
            st.stop()
            
        st.write(f"検出されたユーザー: {list(found_users)}")
        
        # Supabaseに登録
        for u in found_users:
            supabase.table("users").upsert({"username": u, "balance": 10000}, on_conflict="username").execute()
            
        # IDマップ作成 (username -> user_id)
        user_map = {}
        db_users = supabase.table("users").select("user_id, username").execute()
        for u in db_users.data:
            user_map[u['username']] = u['user_id']
            
        st.success(f"✅ ユーザー登録完了: {len(found_users)} 名")

    except Exception as e:
        st.error(f"ユーザー移行エラー: {e}")
        st.stop()

    # -------------------------------------------------
    # 2. 試合データの移行
    # -------------------------------------------------
    status.info("試合データを移行中...")
    try:
        ws_matches = sh.worksheet(sheet_matches)
        matches_data = ws_matches.get_all_records()
        
        matches_payload = []
        for r in matches_data:
            # match_id が空の行はスキップ
            if not r.get("match_id"): continue
            
            # 日付フォーマットの調整 (エラー回避のため文字列化)
            k_time = str(r.get("kickoff_time", "2024-01-01 00:00:00+00"))
            
            matches_payload.append({
                "match_id": r["match_id"],
                "season": "2024-2025",
                "gameweek": r.get("gameweek") or r.get("gw") or 0,
                "home_team": r.get("home_team", "Unknown"),
                "away_team": r.get("away_team", "Unknown"),
                "kickoff_time": k_time,
                "status": r.get("status", "SCHEDULED"),
                "home_score": r.get("home_score") if r.get("home_score") != "" else None,
                "away_score": r.get("away_score") if r.get("away_score") != "" else None
            })
            
        if matches_payload:
            # データが多い場合に備えて分割インサートなどはせず、今回は一括でトライ
            supabase.table("matches").upsert(matches_payload).execute()
            st.success(f"✅ 試合データ移行完了: {len(matches_payload)} 件")
        else:
            st.warning("試合データが見つかりませんでした (match_id列を確認してください)")

    except Exception as e:
        st.error(f"試合データ移行エラー: {e}")

    # -------------------------------------------------
    # 3. ベットデータの移行
    # -------------------------------------------------
    status.info("ベットデータを移行中...")
    try:
        bets_payload = []
        for r in bets_data:
            u_name = str(r.get("user"))
            if u_name in user_map:
                bets_payload.append({
                    "user_id": user_map[u_name],
                    "match_id": r.get("match_id"),
                    "choice": r.get("pick", ""),   # あなたのCSV通り 'pick'
                    "stake": r.get("stake", 0),    # あなたのCSV通り 'stake'
                    "odds_at_bet": r.get("odds", 1.0), # あなたのCSV通り 'odds'
                    "status": "PENDING" 
                    # resultやpayoutは一旦計算せず、まずはベット履歴として取り込みます
                })
                
        if bets_payload:
            supabase.table("bets").insert(bets_payload).execute()
            st.success(f"✅ ベットデータ移行完了: {len(bets_payload)} 件")
        else:
            st.warning("移行対象のベットデータがありませんでした")

    except Exception as e:
        st.error(f"ベットデータ移行エラー: {e}")

    st.balloons()
    st.success("🎉 全データ移行完了！")
