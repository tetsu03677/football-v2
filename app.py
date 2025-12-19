import streamlit as st
import pandas as pd
from supabase import create_client
import datetime

st.set_page_config(page_title="Data Repair", layout="centered")

# --- 接続 ---
try:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    supabase = create_client(url, key)
except:
    st.error("Supabase接続エラー")
    st.stop()

st.title("🛠 データベース整合性修復ツール")
st.warning("このツールは、ベット履歴から所持金を再計算し、Google Sheetsの状態と一致させます。")

if st.button("実行: 所持金再計算 & GW自動設定", type="primary"):
    log = st.empty()
    
    with st.spinner("計算中..."):
        # 1. ユーザー全員のバランスをリセット
        users = supabase.table("users").select("user_id, username").execute().data
        
        # 2. 全ベット履歴を取得 (WON/LOSTのみ)
        all_bets = supabase.table("bets").select("user_id, stake, odds_at_bet, status, choice").execute().data
        
        # 集計ロジック
        balance_map = {u['user_id']: 0 for u in users} # 初期値0（または10000などルールによるが、履歴が全てあるなら0スタートで積み上げ）
        
        # もし「初期所持金 10,000円」などのルールがある場合はここで設定
        # balance_map = {u['user_id']: 10000 for u in users} 
        
        for b in all_bets:
            uid = b['user_id']
            if uid not in balance_map: continue
            
            status = b['status']
            if status == 'WON':
                # 利益 = (賭け金 * オッズ) - 賭け金
                profit = (b['stake'] * b['odds_at_bet']) - b['stake']
                balance_map[uid] += int(profit)
            elif status == 'LOST':
                # 損失 = 賭け金
                balance_map[uid] -= int(b['stake'])
        
        # 3. DB更新
        for uid, amount in balance_map.items():
            supabase.table("users").update({"balance": amount}).eq("user_id", uid).execute()
            
        log.write(f"✅ {len(users)}名の所持金を再計算しました。")
        
        # 4. GWの自動修正 (最も未来に近い未消化試合のGW)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        # これから行われる試合の最小GWを取得
        future_matches = supabase.table("matches").select("gameweek")\
            .gte("kickoff_time", now_iso)\
            .order("kickoff_time")\
            .limit(1)\
            .execute()
            
        target_gw = 1
        if future_matches.data:
            target_gw = future_matches.data[0]['gameweek']
        else:
            # 未来の試合がない＝最新の過去試合のGW
            last_match = supabase.table("matches").select("gameweek").order("kickoff_time", desc=True).limit(1).execute()
            if last_match.data:
                target_gw = last_match.data[0]['gameweek']
        
        supabase.table("app_config").upsert({"key": "current_gw", "value": str(target_gw)}).execute()
        log.write(f"✅ 現在のGWを「{target_gw}」に設定しました。")
        
        # 確認用表示
        st.success("完了しました。以下の数値が正しいか確認してください。")
        
        # 最新データを表示
        updated_users = supabase.table("users").select("username, balance").execute().data
        st.table(updated_users)
