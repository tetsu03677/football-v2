import streamlit as st
import pandas as pd
import datetime
from supabase import create_client

# --- 接続設定 ---
st.set_page_config(page_title="Data Repair", layout="centered")
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except:
    st.error("Supabase接続エラー")
    st.stop()

st.title("🛠 データ整合性 修復ツール")
st.info("ベット履歴から『現在の正しい所持金』を再計算し、現在日時から『正しいGW』を判定します。")

if st.button("🚀 修復実行 (Recalculate & Auto-GW)", type="primary"):
    log = st.empty()
    logs = []

    try:
        with st.spinner("データベースをスキャン中..."):
            # 1. 必要な全データを取得
            users = supabase.table("users").select("*").execute().data
            bets = supabase.table("bets").select("*, matches(gameweek)").execute().data
            bm_history = supabase.table("bm_history").select("*").execute().data
            
            # 2. バランスのリセット (全員0スタート)
            balance_map = {u['user_id']: 0 for u in users}
            logs.append("・全ユーザーの所持金を 0 にリセットしました。")

            # 3. BMマップ作成 (GW -> BMのUser ID)
            # { (season, gw): bm_user_id }
            bm_map = {}
            for h in bm_history:
                key = (str(h.get('season','2024')), int(h['gameweek']))
                bm_map[key] = h['user_id']

            # 4. 全ベット履歴を再演 (Replay) して計算
            for b in bets:
                if b['status'] not in ['WON', 'LOST']: continue
                
                player_id = b['user_id']
                gw = b['matches']['gameweek']
                season = "2024" # 仮固定（本来はbetsかmatchesから取得）
                
                # プレイヤーの損益計算
                pnl = 0
                stake = int(b['stake'])
                odds = float(b['odds_at_bet'])
                
                if b['status'] == 'WON':
                    pnl = int(stake * odds) - stake # 利益
                else:
                    pnl = -stake # 損失
                
                # Player反映
                if player_id in balance_map:
                    balance_map[player_id] += pnl
                
                # BM反映 (P2P: Playerの逆)
                bm_key = (season, gw)
                if bm_key in bm_map:
                    bm_id = bm_map[bm_key]
                    # 自分自身がBMで賭けているケース（通常ないが）は相殺
                    if bm_id != player_id and bm_id in balance_map:
                        balance_map[bm_id] -= pnl # Playerが勝てばBMは負ける

            # 5. DBへ書き込み (Balance)
            for uid, bal in balance_map.items():
                supabase.table("users").update({"balance": bal}).eq("user_id", uid).execute()
            logs.append(f"・ベット履歴 {len(bets)} 件から所持金を再計算しました。")

            # 6. GWの自動判定
            # 「まだ始まっていない（または終わっていない）試合」の中で、最も日時が古いもののGWを採用
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            
            future_match = supabase.table("matches").select("gameweek, kickoff_time")\
                .gt("kickoff_time", now_iso)\
                .order("kickoff_time")\
                .limit(1)\
                .execute()
            
            new_gw = 1
            if future_match.data:
                new_gw = future_match.data[0]['gameweek']
                logs.append(f"・未来の試合を検知: 次は GW{new_gw} です。")
            else:
                # 未来がないなら最新のGW
                last_match = supabase.table("matches").select("gameweek").order("kickoff_time", desc=True).limit(1).execute()
                if last_match.data:
                    new_gw = last_match.data[0]['gameweek']
                    logs.append(f"・全日程終了: 最新は GW{new_gw} です。")

            # Config更新
            supabase.table("app_config").upsert({"key": "current_gw", "value": str(new_gw)}).execute()
            
            # 結果表示
            st.success("✅ 修復完了！")
            for l in logs:
                st.write(l)
            
            st.markdown("### 📊 最新ステータス")
            new_users = supabase.table("users").select("username, balance").execute().data
            st.table(new_users)
            
    except Exception as e:
        st.error(f"エラー: {e}")
