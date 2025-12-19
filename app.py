import streamlit as st
import pandas as pd
import requests
import datetime
import time
from datetime import timedelta, timezone
from supabase import create_client

# ==============================================================================
# 0. 初期設定 & CSS
# ==============================================================================
st.set_page_config(page_title="Premier Picks V3.0", layout="wide", page_icon="⚽")
JST = timezone(timedelta(hours=9), 'JST')

st.markdown("""
<style>
/* --- 全体 --- */
.block-container { padding-top: 3.5rem; padding-bottom: 5rem; max-width: 1000px; }

/* --- カード --- */
.app-card {
    border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 16px;
    background: linear-gradient(145deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%);
    margin-bottom: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.2);
}

/* --- 戦績アイコン (Form Guide) --- */
.form-icon { font-size: 0.8rem; margin: 0 1px; }
.form-win { color: #4ade80; } /* 青丸の代わりに緑/青系の色を使用 */
.form-lose { color: #f87171; }
.form-draw { color: #9ca3af; }

/* --- BM表示 --- */
.bm-badge {
    background: #fbbf24; color: #000; padding: 4px 12px; border-radius: 99px;
    font-weight: bold; font-size: 0.9rem; display: inline-block; margin-bottom: 10px;
}

/* --- その他 --- */
.match-time { font-family: monospace; color: #a5b4fc; font-size: 0.9rem; }
.team-name { font-weight: bold; font-size: 1.1rem; }
.vs { color: #888; font-size: 0.9rem; margin: 0 10px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. データアクセス
# ==============================================================================
@st.cache_resource
def get_supabase():
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except: return None

supabase = get_supabase()

def fetch_all_data():
    """全データを一括取得（キャッシュなしで常に最新を）"""
    try:
        # 非同期っぽく見えるがSync実行
        bets = pd.DataFrame(supabase.table("bets").select("*").execute().data)
        odds = pd.DataFrame(supabase.table("odds").select("*").execute().data)
        results = pd.DataFrame(supabase.table("result").select("*").execute().data)
        bm_log = pd.DataFrame(supabase.table("bm_log").select("*").execute().data)
        users = pd.DataFrame(supabase.table("users").select("*").execute().data)
        config = pd.DataFrame(supabase.table("config").select("*").execute().data)
        return bets, odds, results, bm_log, users, config
    except:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_config_value(config_df, key, default=""):
    if config_df.empty: return default
    row = config_df[config_df['key'] == key]
    if not row.empty: return row.iloc[0]['value']
    return default

# ==============================================================================
# 2. ロジック (戦績・GW・Sync)
# ==============================================================================

def get_recent_form(team_name, results_df, current_kickoff):
    """
    指定されたチームの、現在より過去の直近5試合の戦績を取得する
    Return: "🔵🔵🔺❌🔵" のようなHTML文字列
    """
    if results_df.empty: return "-"
    
    # 日付変換
    if 'dt' not in results_df.columns:
        results_df['dt'] = pd.to_datetime(results_df['utc_kickoff'], errors='coerce', utc=True)
    
    # 過去の完了した試合を抽出
    past_games = results_df[
        (results_df['status'] == 'FINISHED') & 
        (results_df['dt'] < current_kickoff) &
        ((results_df['home'] == team_name) | (results_df['away'] == team_name))
    ].sort_values('dt', ascending=False).head(5) # 直近5試合
    
    icons = []
    # 並び順: 古い -> 新しい にするためにreverse
    for _, g in past_games.iloc[::-1].iterrows():
        # 勝敗判定
        is_home = (g['home'] == team_name)
        h_score = int(g['home_score']) if pd.notna(g['home_score']) else 0
        a_score = int(g['away_score']) if pd.notna(g['away_score']) else 0
        
        if h_score == a_score:
            icons.append("🔺") # 引き分け (黒三角の代用)
        elif (is_home and h_score > a_score) or (not is_home and a_score > h_score):
            icons.append("🔵") # 勝ち (青丸)
        else:
            icons.append("❌") # 負け (赤バツ)
            
    return "".join(icons) if icons else "-"

def sync_incremental(api_token, season="2025"):
    """
    差分更新同期
    - 全削除はしない
    - APIから取ったデータを Upsert するだけ (高速)
    """
    if not api_token: return False, "Token missing"
    headers = {'X-Auth-Token': api_token}
    url = f"https://api.football-data.org/v4/competitions/PL/matches?season={season}"
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200: return False, f"API {res.status_code}"
        
        matches = res.json().get('matches', [])
        if not matches: return False, "No matches"
        
        upserts = []
        for m in matches:
            upserts.append({
                "match_id": m['id'],
                "gw": f"GW{m['matchday']}",
                "home": m['homeTeam']['name'],
                "away": m['awayTeam']['name'],
                "utc_kickoff": m['utcDate'],
                "status": m['status'],
                "home_score": m['score']['fullTime']['home'],
                "away_score": m['score']['fullTime']['away'],
                "updated_at": datetime.datetime.now().isoformat()
            })
        
        # 100件ずつUpsert
        for i in range(0, len(upserts), 100):
            supabase.table("result").upsert(upserts[i:i+100]).execute()
            
        return True, "Data Updated"
    except Exception as e:
        return False, str(e)

def determine_gw(results_df):
    """現在時刻から最適なGWを判定"""
    if results_df.empty: return "GW1"
    results_df['dt'] = pd.to_datetime(results_df['utc_kickoff'], errors='coerce', utc=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # 4時間前以降の試合を探す
    future = results_df[results_df['dt'] > (now - timedelta(hours=4))].sort_values('dt')
    if not future.empty: return future.iloc[0]['gw']
    
    # なければ過去最新
    past = results_df[results_df['dt'] <= now].sort_values('dt', ascending=False)
    if not past.empty: return past.iloc[0]['gw']
    return "GW1"

# ==============================================================================
# 3. UIコンポーネント
# ==============================================================================

def render_match_card(m, odds_df, bets_df, user_name, is_bm, results_df):
    """
    試合カード描画 & ベッティングフォーム
    """
    mid = m['match_id']
    kickoff_dt = pd.to_datetime(m['utc_kickoff'])
    kickoff_str = kickoff_dt.tz_convert(JST).strftime('%m/%d %H:%M')
    
    # オッズ取得
    o_row = odds_df[odds_df['match_id'] == mid]
    oh = o_row.iloc[0]['home_win'] if not o_row.empty else 0
    od = o_row.iloc[0]['draw'] if not o_row.empty else 0
    oa = o_row.iloc[0]['away_win'] if not o_row.empty else 0
    
    # 戦績取得 (ここが新機能！)
    form_home = get_recent_form(m['home'], results_df, kickoff_dt)
    form_away = get_recent_form(m['away'], results_df, kickoff_dt)
    
    # 自分のベット状況
    my_bet_row = pd.DataFrame()
    if not bets_df.empty:
        my_bet_row = bets_df[(bets_df['match_id'] == mid) & (bets_df['user'] == user_name)]
    
    has_bet = not my_bet_row.empty
    current_pick = my_bet_row.iloc[0]['pick'] if has_bet else None
    current_stake = my_bet_row.iloc[0]['stake'] if has_bet else 1000
    
    # カード表示
    st.markdown(f"""
    <div class="app-card">
        <div style="display:flex; justify-content:space-between; margin-bottom:8px; color:#aaa; font-size:0.8rem">
            <span>{kickoff_str}</span>
            <span>{m['status']}</span>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 20px 1fr; align-items:center; text-align:center;">
            <div>
                <div class="team-name">{m['home']}</div>
                <div style="margin-top:2px">{form_home}</div>
                <div style="color:#4ade80; font-weight:bold; font-size:1.1rem; margin-top:4px">{oh if oh else '-'}</div>
            </div>
            
            <div class="vs">vs</div>
            
            <div>
                <div class="team-name">{m['away']}</div>
                <div style="margin-top:2px">{form_away}</div>
                <div style="color:#4ade80; font-weight:bold; font-size:1.1rem; margin-top:4px">{oa if oa else '-'}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    # ベッティングエリア
    # 条件: 試合前/進行中ではない AND オッズがある
    is_open = m['status'] not in ['IN_PLAY', 'FINISHED', 'PAUSED'] and oh > 0
    
    if not is_open:
        st.markdown(f"<div style='text-align:center; padding:10px; color:#aaa'>受付終了 / 試合中</div></div>", unsafe_allow_html=True)
    elif is_bm:
        # BMの場合
        st.markdown(f"<div style='text-align:center; padding:10px; background:rgba(251,191,36,0.1); border-radius:8px; color:#fbbf24; font-weight:bold'>あなたはBMです (親)</div></div>", unsafe_allow_html=True)
    else:
        # プレイヤーの場合
        st.markdown("</div>", unsafe_allow_html=True) # カード閉じる前にフォームを入れるため一旦閉じる処理はStreamlitではできないので、カードの外に出すか工夫
        
        # フォーム (カードの中に入れたいので、markdownを閉じる記述は最後にする)
        # Streamlitの仕様上、markdownの中にwidgetは入れられないので、カード風デザインの下にフォームを置く
        
        with st.form(key=f"bet_{mid}"):
            c1, c2, c3 = st.columns([3, 2, 2])
            
            # 選択肢 (オッズ込み表記)
            opts = [f"HOME ({oh})", f"DRAW ({od})", f"AWAY ({oa})"]
            
            # 既存選択があればデフォルト値を設定
            def_idx = 0
            if current_pick == "HOME": def_idx = 0
            elif current_pick == "DRAW": def_idx = 1
            elif current_pick == "AWAY": def_idx = 2
            
            choice = c1.selectbox("予想", opts, index=def_idx, label_visibility="collapsed")
            stake = c2.number_input("金額", 100, 20000, int(current_stake), 100, label_visibility="collapsed")
            
            btn_label = "更新" if has_bet else "BET"
            
            if c3.form_submit_button(btn_label, use_container_width=True):
                tgt = "HOME" if "HOME" in choice else ("DRAW" if "DRAW" in choice else "AWAY")
                oval = float(oh if tgt=="HOME" else (od if tgt=="DRAW" else oa))
                
                # DB更新
                key = f"{m['gw']}:{user_name}:{mid}"
                supabase.table("bets").upsert({
                    "key": key, "gw": m['gw'], "user": user_name,
                    "match_id": mid, "match": f"{m['home']} vs {m['away']}",
                    "pick": tgt, "stake": stake, "odds": oval,
                    "placed_at": datetime.datetime.now().isoformat(),
                    "status": "OPEN", "result": ""
                }).execute()
                
                st.success(f"{btn_label} Complete!")
                time.sleep(0.5)
                st.rerun()

# ==============================================================================
# 4. メイン処理
# ==============================================================================
def main():
    if not supabase: st.error("DB Error"); st.stop()
    
    # データロード
    bets, odds, results, bm_log, users, config = fetch_all_data()
    
    # ログイン
    if 'user' not in st.session_state: st.session_state['user'] = None
    if not st.session_state['user']:
        st.sidebar.title("🔐 Login")
        u_list = users['username'].tolist() if not users.empty else []
        name = st.sidebar.selectbox("User", u_list)
        pw = st.sidebar.text_input("Pass", type="password")
        if st.sidebar.button("Login"):
            u = users[users['username'] == name]
            if not u.empty and str(u.iloc[0]['password']) == pw:
                st.session_state['user'] = u.iloc[0].to_dict()
                st.rerun()
            else: st.error("NG")
        st.stop()
        
    me = st.session_state['user']
    token = get_config_value(config, 'FOOTBALL_DATA_API_TOKEN') or st.secrets.get("api_token")
    season = get_config_value(config, "API_FOOTBALL_SEASON", "2025")

    # ---------------------------
    # 自動同期 (ログイン時1回のみ)
    # ---------------------------
    if 'synced_v3' not in st.session_state:
        with st.spinner("🔄 Checking latest matches..."):
            sync_incremental(token, season)
        st.session_state['synced_v3'] = True
        st.rerun()

    # ---------------------------
    # GW & BM 判定
    # ---------------------------
    current_gw = determine_gw(results)
    
    # BM特定
    current_bm = "未定"
    if not bm_log.empty:
        # gwカラムから数字を抽出してマッチング
        target_num = "".join([c for c in current_gw if c.isdigit()])
        for _, row in bm_log.iterrows():
            row_gw = "".join([c for c in str(row['gw']) if c.isdigit()])
            if row_gw == target_num:
                current_bm = row['bookmaker']
                break
    
    is_bm = (me['username'] == current_bm)

    # ---------------------------
    # UI構築
    # ---------------------------
    st.sidebar.markdown(f"## 👤 {me['username']}")
    st.sidebar.info(f"Role: {me['role']}")
    
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None; st.rerun()

    # タブ
    tabs = st.tabs(["⚽ Matches (Bet)", "📊 Dashboard", "📜 History", "🏆 Standings"])

    # [Tab 1] Matches (Betting Center)
    with tabs[0]:
        c1, c2 = st.columns([3, 1])
        c1.markdown(f"### {current_gw} Fixtures")
        if is_bm:
            c2.markdown(f"<div class='bm-badge'>👑 You are BM</div>", unsafe_allow_html=True)
        else:
            c2.markdown(f"<div class='bm-badge'>BM: {current_bm}</div>", unsafe_allow_html=True)

        # GW選択 (未来/過去も見れるように)
        if not results.empty:
            gw_opts = sorted(results['gw'].unique(), key=lambda x: int("".join([c for c in str(x) if c.isdigit()] or 0)))
            # current_gw をデフォルトに
            idx = gw_opts.index(current_gw) if current_gw in gw_opts else 0
            sel_gw = st.selectbox("Select Gameweek", gw_opts, index=idx, label_visibility="collapsed")
        else:
            sel_gw = "GW1"

        # 試合抽出
        target_matches = results[results['gw'] == sel_gw].sort_values('utc_kickoff')
        
        if target_matches.empty:
            st.info("No matches found.")
        else:
            for _, m in target_matches.iterrows():
                render_match_card(m, odds, bets, me['username'], is_bm, results)

    # [Tab 2] Dashboard
    with tabs[1]:
        st.markdown("#### Dashboard")
        # 簡易計算 (詳細計算は省略するが、実際はここにcalculate_statsを入れる)
        st.info("詳しい収支は Standings タブへ")

    # [Tab 3] History
    with tabs[2]:
        st.markdown("#### History")
        if not bets.empty:
            hist = bets.sort_values('placed_at', ascending=False)
            st.dataframe(hist[['gw', 'match', 'pick', 'stake', 'result', 'user']], use_container_width=True)

    # [Tab 4] Standings
    with tabs[3]:
        st.markdown("#### Leaderboard")
        # ユーザーごとのバランスを表示
        if not users.empty:
            st.dataframe(users[['username', 'balance', 'team']], use_container_width=True)

if __name__ == "__main__":
    main()
