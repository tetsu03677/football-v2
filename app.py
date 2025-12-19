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
    # Secretsからトークン取得 (旧アプリの書き方に合わせる)
    token = st.secrets.get("api_token") or st.secrets.get("X-Auth-Token")
    
    if not token:
        st.warning("⚠️ APIトークンが見つかりません。Secretsに 'api_token' を設定すると、試合日程を自動更新できます。")
        return

    headers = {'X-Auth-Token': token}
    with st.spinner("APIから最新の試合情報を取得中..."):
        try:
            # 今シーズンの試合を取得
            response = requests.get(f"{API_URL}?season=2024", headers=headers)
            if response.status_code != 200:
                st.error(f"APIエラー: {response.status_code}")
                return
            
            data = response.json()
            matches = data.get('matches', [])
            
            upsert_list = []
            for m in matches:
                # 必要なデータだけ抽出
                upsert_list.append({
                    "match_id": m['id'],
                    "season": SEASON_STR,
                    "gameweek": m['matchday'],
                    "home_team": m['homeTeam']['name'],
                    "away_team": m['awayTeam']['name'],
                    "kickoff_time": m['utcDate'], # これで日時が入ります
                    "status": m['status'],        # SCHEDULED, FINISHED, IN_PLAY
                    "home_score": m['score']['fullTime']['home'],
                    "away_score": m['score']['fullTime']['away'],
                    "last_updated": datetime.datetime.now().isoformat()
                })
            
            if upsert_list:
                # Supabaseへ一括保存
                supabase.table("matches").upsert(upsert_list).execute()
                st.toast(f"✅ {len(upsert_list)} 件の試合データを更新しました！", icon="🔄")
            else:
                st.toast("更新データがありませんでした", icon="ℹ️")
                
        except Exception as e:
            st.error(f"同期エラー: {e}")

# --- 機能: ベット実行 ---
def place_bet(user_id, match_id, choice, stake, odds):
    # 残高チェック
    user = supabase.table("users").select("balance").eq("user_id", user_id).single().execute()
    if not user.data: return False, "ユーザーエラー"
    
    current_balance = user.data['balance']
    if current_balance < stake:
        return False, "残高不足です💸"

    # ベット記録
    bet_payload = {
        "user_id": user_id,
        "match_id": match_id,
        "choice": choice,
        "stake": stake,
        "odds_at_bet": odds,
        "status": "PENDING"
    }
    supabase.table("bets").insert(bet_payload).execute()
    
    # 残高引き落とし
    new_bal = current_balance - stake
    supabase.table("users").update({"balance": new_bal}).eq("user_id", user_id).execute()
    
    return True, new_bal

# --- UI構築 ---
def main():
    if not supabase: return

    # サイドバー: ユーザー選択
    st.sidebar.header("👤 プレイヤー選択")
    users_res = supabase.table("users").select("*").execute()
    
    if not users_res.data:
        st.warning("ユーザーデータがありません。移行ツールを実行してください。")
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
        
        # これから始まる試合を取得 (日時が入っていない場合も考慮して、とりあえず全SCHEDULEDを表示)
        # ※API同期後はkickoff_timeが入るので、日時順にソート可能
        now = datetime.datetime.utcnow().isoformat()
        
        matches_res = supabase.table("matches")\
            .select("*")\
            .eq("status", "SCHEDULED")\
            .order("kickoff_time", nulls_last=True)\
            .limit(20)\
            .execute()
            
        matches = matches_res.data
        if not matches:
            st.info("現在、ベット可能な試合が見つかりません。「試合データを更新」を押して日程を取得してください。")
        else:
            for m in matches:
                # 簡易カード表示
                with st.container(border=True):
                    # 日時フォーマット
                    ktime = m.get('kickoff_time')
                    date_str = "日時未定"
                    if ktime:
                        dt = pd.to_datetime(ktime).tz_convert('Asia/Tokyo')
                        date_str = dt.strftime('%m/%d %H:%M')
                    
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
                                # ※オッズは簡易的に2.0固定 (本来はOddsテーブル参照)
                                success, res = place_bet(current_user['user_id'], m['match_id'], choice, stake, 2.0)
                                if success:
                                    st.success(f"ベット完了！残高: ¥{res:,}")
                                    st.rerun()
                                else:
                                    st.error(res)

    with tab2:
        st.subheader(f"{current_user['username']} さんの履歴")
        
        # 自分の履歴を取得 (テーブル結合)
        # ※Supabaseのクライアントで結合クエリは少しコツがいるので、まずは単純取得
        my_bets = supabase.table("bets").select("*, matches(home_team, away_team, kickoff_time)")\
            .eq("user_id", current_user['user_id'])\
            .order("created_at", desc=True)\
            .limit(50)\
            .execute()
            
        if my_bets.data:
            # 表示用に整形
            display_data = []
            for b in my_bets.data:
                m = b['matches']
                match_label = f"{m['home_team']} vs {m['away_team']}" if m else f"Match ID: {b['match_id']}"
                display_data.append({
                    "試合": match_label,
                    "予想": b['choice'],
                    "金額": f"¥{b['stake']:,}",
                    "オッズ": b['odds_at_bet'],
                    "状態": b['status'],
                    "日付": pd.to_datetime(b['created_at']).tz_convert('Asia/Tokyo').strftime('%Y-%m-%d %H:%M')
                })
            st.dataframe(pd.DataFrame(display_data))
        else:
            st.info("まだ履歴がありません。")

if __name__ == "__main__":
    main()
