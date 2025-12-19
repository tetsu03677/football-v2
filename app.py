import streamlit as st
import gspread
from supabase import create_client
import pandas as pd

st.set_page_config(page_title="V2 Migration", layout="wide")
st.title("🏗️ Football App V2 - 建設準備室")

# --- 認証情報の取得と接続 ---
try:
    # 1. Google Sheets接続 (旧データ読み込み用)
    # ※旧アプリのSecrets設定に合わせてキー名を調整しています
    if "gcp_service_account" in st.secrets:
        creds = st.secrets["gcp_service_account"]
        gc = gspread.service_account_from_dict(creds)
        # シートIDもSecretsから取得
        sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
        st.success("✅ 旧Googleスプレッドシート: 接続OK")
    else:
        st.warning("⚠️ Google認証情報が見つかりません。Secretsの設定を確認してください。")
        sh = None

    # 2. Supabase接続 (新データ書き込み用)
    if "supabase" in st.secrets:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        supabase = create_client(url, key)
        st.success("✅ 新Supabase: 接続OK")
    else:
        st.warning("⚠️ Supabase情報が見つかりません。Secretsの設定を確認してください。")
        supabase = None

except Exception as e:
    st.error(f"接続エラー: {e}")
    sh = None
    supabase = None

st.divider()

# --- 移行実行セクション ---
st.subheader("📦 データ移行の実行")
st.info("ボタンを押すと、旧スプレッドシートからデータを読み込み、Supabaseへコピーします。")

if st.button("🚀 データ移行スタート"):
    if not sh or not supabase:
        st.error("データベースへの接続が完了していないため、実行できません。")
        st.stop()

    status = st.empty()
    
    # 1. ユーザー移行
    status.text("ユーザーデータを移行中...")
    # ※必要に応じて友人の名前を変更してください
    users = ["Friend A", "Friend B", "Friend C", "Me"] 
    for u in users:
        supabase.table("users").upsert({"username": u, "balance": 10000}, on_conflict="username").execute()
    
    # IDマップ作成
    user_map = {}
    db_users = supabase.table("users").select("user_id, username").execute()
    for u in db_users.data:
        user_map[u['username']] = u['user_id']
    
    # 2. 試合データ移行 (scheduleシートと仮定)
    status.text("試合データを移行中...")
    try:
        # ★重要: 実際のシート名が 'schedule' でない場合はここを書き換えてください
        ws_match = sh.worksheet("schedule") 
        rows = ws_match.get_all_records()
        matches = []
        for r in rows:
            matches.append({
                "match_id": r["match_id"],
                "season": "2024-2025",
                "gameweek": r["gameweek"],
                "home_team": r["home_team"],
                "away_team": r["away_team"],
                "kickoff_time": r["kickoff_time"],
                "status": "SCHEDULED"
            })
        if matches:
            supabase.table("matches").upsert(matches).execute()
        st.write(f"試合データ {len(matches)} 件 完了")
    except Exception as e:
        st.warning(f"試合データ移行スキップ: {e} (シート名が違う可能性があります)")

    # 3. ベットデータ移行 (betsシートと仮定)
    status.text("ベットデータを移行中...")
    try:
        # ★重要: 実際のシート名が 'bets' でない場合はここを書き換えてください
        ws_bet = sh.worksheet("bets")
        rows = ws_bet.get_all_records()
        bets = []
        for r in rows:
            u_name = r.get("user") 
            if u_name in user_map:
                bets.append({
                    "user_id": user_map[u_name],
                    "match_id": r["match_id"],
                    "choice": r.get("pick", ""),
                    "stake": r.get("stake", 0),
                    "odds_at_bet": r.get("odds", 1.0),
                    "status": "PENDING"
                })
        if bets:
            supabase.table("bets").insert(bets).execute()
        st.write(f"ベットデータ {len(bets)} 件 完了")
    except Exception as e:
        st.warning(f"ベットデータ移行スキップ: {e}")

    st.success("🎉 移行作業が完了しました！")
