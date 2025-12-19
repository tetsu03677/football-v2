import streamlit as st
import pandas as pd
import requests
import datetime
from datetime import timedelta, timezone
from supabase import create_client

# -------------------------------------------------------------------
# 1. 初期設定 & 定数
# -------------------------------------------------------------------
st.set_page_config(page_title="Premier Picks V2", page_icon="⚽", layout="wide")
JST = timezone(timedelta(hours=9), 'JST')

# スタイル定義（旧 ui_parts.py の雰囲気を再現）
st.markdown("""
<style>
    .block-container {padding-top:2rem; padding-bottom:3rem;}
    .match-card {
        background-color: #1e1e1e; color: white; padding: 15px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #333;
    }
    .team-label { font-size: 1.1em; font-weight: bold; }
    .odds-tag { background: #333; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; margin-left: 5px; color: #ddd; }
    .status-badge { font-size: 0.8em; padding: 3px 8px; border-radius: 10px; background: #555; color: white; }
    .profit-box { background: #dcfce7; color: #166534; padding: 10px; border-radius: 8px; font-weight: bold; text-align: center; }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------------
# 2. データベース & 設定読み込み
# -------------------------------------------------------------------
@st.cache_resource
def init_db():
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except:
        return None

supabase = init_db()

def get_app_config():
    """DBのapp_configテーブルから設定をロード"""
    try:
        rows = supabase.table("app_config").select("*").execute().data
        conf = {r['key']: r['value'] for r in rows}
        return conf
    except:
        return {}

CONFIG = get_app_config()
API_TOKEN = CONFIG.get("FOOTBALL_DATA_API_TOKEN") or st.secrets.get("api_token")
API_URL = 'https://api.football-data.org/v4/competitions/PL/matches'

# -------------------------------------------------------------------
# 3. ビジネスロジック (Sync, Settlement, Odds)
# -------------------------------------------------------------------
def sync_data_logic():
    """
    APIからデータを取得し、以下の処理を一括で行う
    1. 試合日程・スコアの更新
    2. オッズの更新 (キックオフ1時間前まで)
    3. 終了した試合のベット精算 (Settlement)
    """
    if not API_TOKEN:
        return False, "APIトークンが設定されていません"

    headers = {'X-Auth-Token': API_TOKEN}
    
    # 前後2週間の試合を取得（範囲は適宜調整）
    d_now = datetime.datetime.now()
    d_from = (d_now - timedelta(days=14)).strftime('%Y-%m-%d')
    d_to = (d_now + timedelta(days=14)).strftime('%Y-%m-%d')
    
    try:
        res = requests.get(f"{API_URL}?dateFrom={d_from}&dateTo={d_to}", headers=headers)
        if res.status_code != 200:
            return False, f"API Error: {res.status_code}"
        
        matches = res.json().get('matches', [])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        upsert_matches = []
        settle_targets = [] # 終了した試合のID

        for m in matches:
            mid = m['id']
            status = m['status'] # SCHEDULED, TIMED, IN_PLAY, PAUSED, FINISHED
            
            # --- A. オッズ更新判断 ---
            # キックオフ時間をパース
            kickoff_str = m['utcDate']
            kickoff_dt = datetime.datetime.fromisoformat(kickoff_str.replace('Z', '+00:00'))
            
            # 残り時間(時間単位)
            hours_left = (kickoff_dt - now_utc).total_seconds() / 3600
            
            # DB更新用データ作成
            record = {
                "match_id": mid,
                "season": "2024-2025", # APIから取れるならそちらを優先推奨
                "gameweek": m['matchday'],
                "home_team": m['homeTeam']['name'],
                "away_team": m['awayTeam']['name'],
                "kickoff_time": kickoff_str,
                "status": status,
                "home_score": m['score']['fullTime']['home'],
                "away_score": m['score']['fullTime']['away'],
                "last_updated": datetime.datetime.now().isoformat()
            }

            # ★ オッズ更新ロジック: 「1時間以上前」かつ「APIにオッズがある」場合のみ更新
            # APIの無料プラン等でoddsが取れない場合を考慮し、Noneチェックを行う
            api_odds = m.get('odds', {})
            # homeWinなどが取れる場合のみ
            if api_odds.get('homeWin') and hours_left > 1.0:
                record["odds_home"] = api_odds.get('homeWin')
                record["odds_draw"] = api_odds.get('draw')
                record["odds_away"] = api_odds.get('awayWin')
            
            upsert_matches.append(record)
            
            # --- B. 精算対象リストアップ ---
            if status == "FINISHED":
                settle_targets.append({
                    "id": mid,
                    "h_score": m['score']['fullTime']['home'],
                    "a_score": m['score']['fullTime']['away']
                })

        # 1. 試合データ一括更新
        if upsert_matches:
            supabase.table("matches").upsert(upsert_matches).execute()

        # 2. 自動精算 (Settlement)
        settled_count = 0
        for target in settle_targets:
            mid = target['id']
            hs = target['h_score']
            as_ = target['a_score']
            
            # 勝者判定
            result = "DRAW"
            if hs > as_: result = "HOME"
            elif as_ > hs: result = "AWAY"
            
            # この試合に対する PENDING のベットを取得
            pending_bets = supabase.table("bets").select("*").eq("match_id", mid).eq("status", "PENDING").execute().data
            
            for bet in pending_bets:
                user_id = bet['user_id']
                choice = bet['choice'] # HOME, DRAW, AWAY
                stake = bet['stake']
                odds = bet['odds_at_bet'] or 1.0
                
                new_status = "LOST"
                payout = 0
                
                if choice == result:
                    new_status = "WON"
                    payout = int(stake * odds)
                
                # ベット状態更新
                supabase.table("bets").update({"status": new_status}).eq("bet_id", bet['bet_id']).execute()
                
                # ユーザー残高更新 (配当がある場合のみ)
                if payout > 0:
                    # 現在の残高を取得して加算 (アトミック処理が理想だが、簡易的にRead->Update)
                    u_row = supabase.table("users").select("balance").eq("user_id", user_id).single().execute().data
                    if u_row:
                        new_bal = u_row['balance'] + payout
                        supabase.table("users").update({"balance": new_bal}).eq("user_id", user_id).execute()
                
                settled_count += 1
                
        return True, f"データ同期完了: {len(upsert_matches)}試合更新, {settled_count}件のベットを精算"

    except Exception as e:
        return False, str(e)

# -------------------------------------------------------------------
# 4. UIコンポーネント
# -------------------------------------------------------------------
def login_ui():
    """Configのusers_jsonではなくDBのusersテーブルで認証"""
    st.sidebar.header("Login")
    
    # ユーザーリスト取得
    users = supabase.table("users").select("username").execute().data
    if not users:
        st.error("ユーザーが見つかりません")
        return None

    usernames = [u['username'] for u in users]
    selected_user = st.sidebar.selectbox("Username", usernames)
    password = st.sidebar.text_input("Password", type="password")
    
    if st.sidebar.button("Login"):
        # パスワード照合
        res = supabase.table("users").select("*").eq("username", selected_user).single().execute()
        user_data = res.data
        if user_data and str(user_data.get('password')) == str(password):
            st.session_state['user'] = user_data
            st.rerun()
        else:
            st.error("パスワードが違います")
            
    return st.session_state.get('user')

# -------------------------------------------------------------------
# 5. メインアプリ
# -------------------------------------------------------------------
def main():
    if not supabase:
        st.error("DB接続に失敗しました")
        return

    # ログインチェック
    user = st.session_state.get('user')
    if not user:
        login_ui()
        st.stop()

    # --- ログイン後画面 ---
    
    # 最新ステータス再取得 (残高など)
    user = supabase.table("users").select("*").eq("user_id", user['user_id']).single().execute().data
    st.session_state['user'] = user # Session更新

    # サイドバー情報
    st.sidebar.markdown(f"### 👤 {user['username']}")
    st.sidebar.markdown(f"**Team:** {user.get('favorite_team','-')}")
    st.sidebar.markdown(f"**Balance:** ¥{user['balance']:,}")
    
    # 同期ボタン
    if st.sidebar.button("🔄 データ更新 & 精算"):
        with st.spinner("API問い合わせ中..."):
            success, msg = sync_data_logic()
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
    
    st.sidebar.divider()

    # --- ポテンシャル・プロフィット計算 (GW単位) ---
    # 現在PENDINGの自分のベットを取得
    my_pending = supabase.table("bets").select("*, matches(gameweek)")\
        .eq("user_id", user['user_id'])\
        .eq("status", "PENDING").execute().data
    
    potential_profit = 0
    # GWごとに集計も可能だが、まずは「現在賭けている全試合のポテンシャル」を表示
    for b in my_pending:
        stake = b['stake']
        odds = b['odds_at_bet'] or 1.0
        potential_profit += (stake * odds) - stake
    
    st.sidebar.markdown(f"""
    <div class="profit-box">
        <div>🚀 Potential Profit</div>
        <div style="font-size:1.5em">+¥{int(potential_profit):,}</div>
    </div>
    """, unsafe_allow_html=True)
    
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None
        st.rerun()

    # --- メインコンテンツ (タブ構成) ---
    tab1, tab2, tab3 = st.tabs(["📅 Matches & Bets", "📜 History", "📊 Dashboard"])

    with tab1:
        st.subheader("ベット対象試合 (Odds確定: Kickoff 1時間前)")
        
        # これから始まる試合を取得
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        matches_res = supabase.table("matches")\
            .select("*")\
            .gte("kickoff_time", now_iso)\
            .order("kickoff_time", desc=False)\
            .limit(20)\
            .execute()
            
        matches = matches_res.data
        if not matches:
            st.info("現在ベット可能な試合はありません。サイドバーの「データ更新」を押してみてください。")
        else:
            for m in matches:
                # 独自カードUI
                with st.container():
                    # 日時変換
                    ktime = m['kickoff_time']
                    try:
                        dt = pd.to_datetime(ktime).tz_convert('Asia/Tokyo')
                        date_str = dt.strftime('%m/%d %H:%M')
                    except:
                        date_str = str(ktime)

                    # オッズ表示 (NULLなら仮の値 1.0 か 非表示)
                    oh = m.get('odds_home') or '-'
                    od = m.get('odds_draw') or '-'
                    oa = m.get('odds_away') or '-'

                    st.markdown(f"""
                    <div class="match-card">
                        <div style="display:flex; justify-content:space-between; margin-bottom:5px; color:#aaa; font-size:0.9em">
                            <span>GW {m['gameweek']}</span>
                            <span>{date_str}</span>
                        </div>
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div style="text-align:center; flex:1">
                                <div class="team-label">{m['home_team']}</div>
                                <span class="odds-tag">{oh}</span>
                            </div>
                            <div style="padding:0 10px; color:#888;">vs</div>
                            <div style="text-align:center; flex:1">
                                <div class="team-label">{m['away_team']}</div>
                                <span class="odds-tag">{oa}</span>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    # ベットフォーム
                    with st.form(key=f"bet_{m['match_id']}"):
                        c1, c2, c3 = st.columns([3, 2, 1])
                        
                        # オッズ選択肢
                        opts = [f"HOME ({oh})", f"DRAW ({od})", f"AWAY ({oa})"]
                        choice_label = c1.radio("予想", opts, horizontal=True, label_visibility="collapsed")
                        stake = c2.number_input("Stake", min_value=100, step=100, value=1000, label_visibility="collapsed")
                        submit = c3.form_submit_button("BET")
                        
                        if submit:
                            # 選択肢から生データ復元
                            raw_choice = "HOME" if "HOME" in choice_label else ("DRAW" if "DRAW" in choice_label else "AWAY")
                            selected_odds = 1.0
                            if raw_choice == "HOME" and oh != '-': selected_odds = float(oh)
                            if raw_choice == "DRAW" and od != '-': selected_odds = float(od)
                            if raw_choice == "AWAY" and oa != '-': selected_odds = float(oa)
                            
                            # 残高チェック
                            if user['balance'] < stake:
                                st.error("残高不足です！")
                            elif selected_odds == 1.0:
                                st.error("オッズがまだ出ていません。")
                            else:
                                # DB更新
                                supabase.table("bets").insert({
                                    "user_id": user['user_id'],
                                    "match_id": m['match_id'],
                                    "choice": raw_choice,
                                    "stake": stake,
                                    "odds_at_bet": selected_odds,
                                    "status": "PENDING"
                                }).execute()
                                # 残高引き落とし
                                supabase.table("users").update({"balance": user['balance'] - stake}).eq("user_id", user['user_id']).execute()
                                
                                st.success("ベット完了！")
                                st.rerun()

    with tab2:
        st.subheader("ベット履歴")
        # 自分のベット
        my_bets = supabase.table("bets").select("*, matches(home_team, away_team, kickoff_time)")\
            .eq("user_id", user['user_id'])\
            .order("created_at", desc=True)\
            .limit(30)\
            .execute().data
            
        if my_bets:
            data_rows = []
            for b in my_bets:
                m = b['matches'] or {}
                # 結果に応じた色
                status = b['status']
                res_emoji = "⏳"
                if status == "WON": res_emoji = "✅ WIN"
                elif status == "LOST": res_emoji = "❌ LOSE"
                
                # 損益
                pnl = 0
                if status == "WON":
                    pnl = int((b['stake'] * b['odds_at_bet']) - b['stake'])
                elif status == "LOST":
                    pnl = -b['stake']
                
                data_rows.append({
                    "Date": pd.to_datetime(b['created_at']).tz_convert('Asia/Tokyo').strftime('%m/%d %H:%M'),
                    "Match": f"{m.get('home_team')} vs {m.get('away_team')}",
                    "Pick": b['choice'],
                    "Odds": b['odds_at_bet'],
                    "Stake": f"¥{b['stake']:,}",
                    "Status": res_emoji,
                    "P&L": f"¥{pnl:,}"
                })
            st.dataframe(pd.DataFrame(data_rows))
        else:
            st.info("履歴はありません")

    with tab3:
        st.subheader("ランキング (Balance)")
        all_users = supabase.table("users").select("username, balance, favorite_team").order("balance", desc=True).execute().data
        
        df_rank = pd.DataFrame(all_users)
        df_rank.columns = ["Player", "Balance", "Team"]
        st.dataframe(df_rank, use_container_width=True)

if __name__ == "__main__":
    main()
