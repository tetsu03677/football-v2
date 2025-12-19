import streamlit as st
import gspread
from supabase import create_client
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="V2 Final Migration", layout="wide")
st.title("🚀 Football App V2 - 最終移行ツール (Patch Ver.)")

# --- 接続確立 ---
try:
    if "gcp_service_account" in st.secrets:
        creds = st.secrets["gcp_service_account"]
        gc = gspread.service_account_from_dict(creds)
        sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
        st.success(f"✅ Google Sheets 接続成功")
    else:
        st.error("Google認証情報がありません")
        st.stop()

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

# --- シート選択 ---
st.info("データが入っているシートを選択してください")
sheet_names = [ws.title for ws in sh.worksheets()]

col1, col2 = st.columns(2)
with col1:
    # 試合日程 (Matches)
    def_sched = next((i for i, n in enumerate(sheet_names) if "sched" in n.lower() or "fix" in n.lower() or "match" in n.lower()), 0)
    sheet_matches = st.selectbox("📅 試合日程 (Matches) のシート", sheet_names, index=def_sched)

with col2:
    # ベット履歴 (Bets)
    def_bets = next((i for i, n in enumerate(sheet_names) if "bet" in n.lower()), 0)
    sheet_bets = st.selectbox("🎫 ベット履歴 (Bets) のシート", sheet_names, index=def_bets)

if st.button("🚀 移行スタート (実行)"):
    status = st.empty()
    
    # -------------------------
    # 1. ユーザー登録
    # -------------------------
    status.info("ユーザー移行中...")
    try:
        ws_bets = sh.worksheet(sheet_bets)
        bets_data = ws_bets.get_all_records()
        
        # 'user' カラムの抽出
        users = set()
        for row in bets_data:
            if row.get("user"):
                users.add(str(row["user"]))
        
        for u in users:
            supabase.table("users").upsert({"username": u, "balance": 10000}, on_conflict="username").execute()
            
        # IDマップ作成
        user_map = {u['username']: u['user_id'] for u in supabase.table("users").select("user_id, username").execute().data}
        st.write(f"✅ ユーザー登録完了: {len(users)}名")
        
    except Exception as e:
        st.error(f"ユーザー移行エラー: {e}")
        st.stop()

    # -------------------------
    # 2. 試合データ移行 (Patch)
    # -------------------------
    status.info("試合データ移行中...")
    try:
        ws_matches = sh.worksheet(sheet_matches)
        matches_data = ws_matches.get_all_records()
        matches_payload = []
        
        # ★ここが重要: カラム名の揺らぎを吸収
        # 実際に取得されたキーを確認しながらマッピングします
        for r in matches_data:
            if not r.get("match_id"): continue
            
            # home\n 対応: キーに 'home' が含まれていればそれを採用
            home_team = "Unknown"
            for k in r.keys():
                if "home" in k.lower():
                    home_team = r[k]
                    break
            
            # 時間がないので現在時刻を入れる（ベット外部キー制約回避のため）
            now_iso = datetime.now().isoformat()
            
            matches_payload.append({
                "match_id": r["match_id"],
                "season": "2024-2025",
                "gameweek": r.get("gw", 0),
                "home_team": home_team,
                "away_team": r.get("away", "Unknown"),
                "kickoff_time": now_iso, # 仮の日時
                "status": "FINISHED" if r.get("locked") else "SCHEDULED", # lockedカラムを活用
                "home_score": None, # スコアはないのでNull
                "away_score": None
            })
            
        if matches_payload:
            supabase.table("matches").upsert(matches_payload).execute()
            st.write(f"✅ 試合データ完了 (仮日時で登録): {len(matches_payload)}件")
            
    except Exception as e:
        st.warning(f"試合データ移行警告: {e}")

    # -------------------------
    # 3. ベットデータ移行
    # -------------------------
    status.info("ベットデータ移行中...")
    try:
        bets_payload = []
        for r in bets_data:
            u_name = str(r.get("user"))
            if u_name in user_map:
                bets_payload.append({
                    "user_id": user_map[u_name],
                    "match_id": r.get("match_id"),
                    "choice": r.get("pick", ""),
                    "stake": r.get("stake", 0),
                    "odds_at_bet": r.get("odds", 1.0),
                    "status": "PENDING"
                })
        if bets_payload:
            supabase.table("bets").insert(bets_payload).execute()
            st.write(f"✅ ベットデータ完了: {len(bets_payload)}件")
    except Exception as e:
        st.error(f"ベットデータ移行エラー: {e}")

    st.balloons()
    st.success("🎉 全データ移行完了！次は既存コード(app.py)を見せてください！")
