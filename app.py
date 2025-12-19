import streamlit as st
import pandas as pd
import requests
import datetime
from supabase import create_client

# --- 基本設定 ---
st.set_page_config(page_title="Premier Picks V2", page_icon="⚽", layout="wide")

# API設定 (Football-Data.org)
API_URL = 'https://api.football-data.org/v4/competitions/PL/matches'
SEASON_STR = "2024-2025"

# --- データベース接続 ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Supabase接続エラー: {e}")
        return None

supabase = init_connection()

# --- 機能: APIから最新日程を取得してDB更新 ---
def sync_matches_from_api():
    token = st.secrets.get("api_token") or st.secrets.get("X-Auth-Token")
    
    if not token:
        st.warning("⚠️ Secretsに 'api_token' が設定されていません。")
        return

    headers = {'X-Auth-Token': token}
    with st.spinner("APIから最新の試合情報を取得中..."):
        try:
            response = requests.get(f"{API_URL}?season=2024", headers=headers)
            if response.status_code != 200:
                st.error(f"APIエラー: {response.status_code}")
                return
            
            data = response.json()
            matches = data.get('matches', [])
            
            upsert_list = []
            for m in matches:
                upsert_list.append({
                    "match_id": m['id'],
                    "season": SEASON_STR,
                    "gameweek": m['matchday'],
                    "home_team": m['homeTeam']['name'],
                    "away_team": m['awayTeam']['name'],
                    "kickoff_time": m['utcDate'],
                    "status": m['status'],
                    "home_score": m['score']['fullTime']['home'],
                    "away_score": m['score']['fullTime']['away'],
                    "last_updated": datetime.datetime.now().isoformat()
                })
            
            if upsert_list:
                supabase.table("matches").upsert(upsert_list).execute()
                st.toast(f"✅ {len(upsert_list)} 件の試合データを更新しました！", icon="🔄")
            else:
                st.toast("更新データがありませんでした", icon="ℹ️")
                
        except Exception as e:
            st.error(f"同期エラー: {e}")

# --- 機能: ベット実行 ---
def place_bet(user_id, match_id, choice, stake, odds):
    user = supabase.table("users").select("balance").eq("user_id", user_id).single().execute()
    if not user.data: return False, "ユーザーエラー"
    
    current_balance = user.data['balance']
    if current_balance < stake:
        return False, "残高不足です💸"

    bet_payload = {
        "user_id": user_id,
        "match_id": match_id,
        "choice": choice,
        "stake": stake,
        "odds_at_bet": odds,
        "status": "PENDING"
    }
    supabase.table("bets").insert(bet_payload).execute()
    
    new_bal = current_balance - stake
    supabase.table("users").update({"balance": new_bal}).eq("user_id", user_id).execute()
    
    return True, new_bal

# --- UI構築 ---
def main():
    if not supabase: return

    # サイドバー
    st.sidebar.header("👤 プレイヤー選択")
    try:
        users_res = supabase.table("users").select("*").execute()
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        return

    if not users_res.data:
        st.warning("ユーザーデータがありません。")
        return
        
    users_data = users_res.data
    user_names = [u['username'] for u in users_data]
    selected_name = st.sidebar.selectbox("ログイン", user_names)
    
    current_user = next(u for u in users_data if u['username'] == selected_name)
    
    st.sidebar.divider()
    st.sidebar.metric("所持金 (Balance)", f"¥{current_user['balance']:,}")
    
    st.sidebar.divider()
    if st.sidebar.button("🔄 試合データを更新 (API)"):
        sync_matches_from_api()

    # メイン画面
    st.title("⚽ Premier Picks V2")
    
    tab1, tab2 = st.tabs(["📅 ベットする", "📜 ベット履歴"])
    
    with tab1:
        st.subheader("今後の試合")
        
        # ★修正箇所: nulls_last を削除し、単純な昇順ソートに変更
        matches_res = supabase.table("matches")\
            .select("*")\
            .eq("status", "SCHEDULED")\
            .order("kickoff_time", desc=False)\
            .limit(20)\
            .execute()
            
        matches = matches_res.data
        if not matches:
            st.info("ベット可能な試合が見つかりません。「試合データを更新」を押してください。")
        else:
            for m in matches:
                with st.container(border=True):
                    ktime = m.get('kickoff_time')
                    date_str = "日時未定"
                    if ktime:
                        try:
                            dt = pd.to_datetime(ktime).tz_convert('Asia/Tokyo')
                            date_str = dt.strftime('%m/%d %H:%M')
                        except:
                            date_str = str(ktime)
                    
                    col_info, col_bet = st.columns([2, 3])
                    with col_info:
                        st.caption(f"GW {m['gameweek']} | {date_str}")
                        st.markdown(f"### {m['home_team']} vs {m['away_team']}")
                    
                    with col_bet:
                        with st.form(key=f"bet_form_{m['match_id']}"):
                            c1, c2, c3 = st.columns([2, 2, 1])
                            choice = c1.radio("予想", ["HOME", "DRAW", "AWAY"], key=f"rad_{m['match_id']}", label_visibility="collapsed", horizontal=True)
                            stake = c2.number_input("賭け金", min_value=100, step=100, value=1000, key=f"num_{m['match_id']}", label_visibility="collapsed")
                            submit = c3.form_submit_button("🔥 ベット")
                            
                            if submit:
                                success, res = place_bet(current_user['user_id'], m['match_id'], choice, stake, 2.0)
                                if success:
                                    st.success(f"ベット完了！残高: ¥{res:,}")
                                    st.rerun()
                                else:
                                    st.error(res)

    with tab2:
        st.subheader(f"{current_user['username']} さんの履歴")
        my_bets = supabase.table("bets").select("*, matches(home_team, away_team, kickoff_time)")\
            .eq("user_id", current_user['user_id'])\
            .order("created_at", desc=True)\
            .limit(50)\
            .execute()
            
        if my_bets.data:
            display_data = []
            for b in my_bets.data:
                m = b.get('matches') or {}
                match_label = f"{m.get('home_team','?')} vs {m.get('away_team','?')}"
                
                created_str = b['created_at']
                try:
                    created_str = pd.to_datetime(b['created_at']).tz_convert('Asia/Tokyo').strftime('%Y-%m-%d %H:%M')
                except: pass

                display_data.append({
                    "試合": match_label,
                    "予想": b['choice'],
                    "金額": f"¥{b['stake']:,}",
                    "オッズ": b['odds_at_bet'],
                    "状態": b['status'],
                    "日時": created_str
                })
            st.dataframe(pd.DataFrame(display_data))
        else:
            st.info("まだ履歴がありません。")

if __name__ == "__main__":
    main()
