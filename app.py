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
st.set_page_config(page_title="Premier Picks V3.1", layout="wide", page_icon="⚽")
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
.form-icon { display: inline-block; width: 20px; text-align: center; }
.form-win { font-size: 1rem; } /* 🔵 */
.form-lose { font-size: 1rem; } /* ❌ */
.form-draw { font-size: 1.2rem; color: #111; text-shadow: 0 0 1px #888; line-height: 1; } /* ▲ (黒) */

/* --- BM表示 --- */
.bm-badge {
    background: #fbbf24; color: #000; padding: 4px 12px; border-radius: 99px;
    font-weight: bold; font-size: 0.9rem; display: inline-block; margin-bottom: 10px;
}

/* --- ベット状況リスト --- */
.bet-list-row {
    font-size: 0.85rem; padding: 4px 8px; border-radius: 4px; background: rgba(255,255,255,0.05); margin-top: 2px;
    display: flex; justify-content: space-between; align-items: center;
}
.bet-user { font-weight: bold; color: #ddd; }
.bet-pick { color: #a5b4fc; margin-left: 8px; }
.bet-amt { color: #aaa; font-family: monospace; }

/* --- その他 --- */
.match-time { font-family: monospace; color: #a5b4fc; font-size: 0.9rem; }
.team-name { font-weight: bold; font-size: 1.1rem; }
.vs { color: #888; font-size: 0.9rem; margin: 0 10px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. データアクセス (Safe Fetch)
# ==============================================================================
@st.cache_resource
def get_supabase():
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except: return None

supabase = get_supabase()

def fetch_all_data():
    """全データを一括取得 (カラム落ち防止)"""
    try:
        # DBから取得
        d_bets = supabase.table("bets").select("*").execute().data
        d_odds = supabase.table("odds").select("*").execute().data
        d_res = supabase.table("result").select("*").execute().data
        d_bm = supabase.table("bm_log").select("*").execute().data
        d_users = supabase.table("users").select("*").execute().data
        d_conf = supabase.table("config").select("*").execute().data
        
        # DataFrame化 (空でもカラム定義を維持)
        bets = pd.DataFrame(d_bets) if d_bets else pd.DataFrame(columns=['bet_id','user','match_id','pick','stake','odds','result','gw','placed_at'])
        odds = pd.DataFrame(d_odds) if d_odds else pd.DataFrame(columns=['match_id','home_win','draw','away_win','gw'])
        results = pd.DataFrame(d_res) if d_res else pd.DataFrame(columns=['match_id','gw','home','away','utc_kickoff','status','home_score','away_score'])
        bm_log = pd.DataFrame(d_bm) if d_bm else pd.DataFrame(columns=['gw','bookmaker'])
        users = pd.DataFrame(d_users) if d_users else pd.DataFrame(columns=['username','password','role','team','balance'])
        config = pd.DataFrame(d_conf) if d_conf else pd.DataFrame(columns=['key','value'])
        
        return bets, odds, results, bm_log, users, config
    except Exception as e:
        st.error(f"Data Load Error: {e}")
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
    """戦績アイコン生成 (🔵❌▲)"""
    if results_df.empty: return "-"
    if 'dt' not in results_df.columns:
        results_df['dt'] = pd.to_datetime(results_df['utc_kickoff'], errors='coerce', utc=True)
    
    past_games = results_df[
        (results_df['status'] == 'FINISHED') & 
        (results_df['dt'] < current_kickoff) &
        ((results_df['home'] == team_name) | (results_df['away'] == team_name))
    ].sort_values('dt', ascending=False).head(5)
    
    icons = []
    for _, g in past_games.iloc[::-1].iterrows():
        is_home = (g['home'] == team_name)
        h = int(g['home_score']) if pd.notna(g['home_score']) else 0
        a = int(g['away_score']) if pd.notna(g['away_score']) else 0
        
        if h == a:
            # 黒三角 (CSSクラスで色指定)
            icons.append('<span class="form-icon form-draw">▲</span>')
        elif (is_home and h > a) or (not is_home and a > h):
            icons.append('<span class="form-icon form-win">🔵</span>')
        else:
            icons.append('<span class="form-icon form-lose">❌</span>')
            
    return "".join(icons) if icons else "-"

def sync_incremental(api_token):
    """
    2025シーズンの差分更新
    """
    if not api_token: return False
    headers = {'X-Auth-Token': api_token}
    # ★ 強制的に2025を指定
    url = f"https://api.football-data.org/v4/competitions/PL/matches?season=2025"
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200: return False
        
        matches = res.json().get('matches', [])
        if not matches: return False
        
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
            
        return True
    except:
        return False

def determine_gw(results_df):
    """未来の試合がある直近のGWを判定"""
    if results_df.empty: return "GW1"
    
    results_df['dt'] = pd.to_datetime(results_df['utc_kickoff'], errors='coerce', utc=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # まだ始まっていない、または終わっていない試合 (4時間前以降)
    future = results_df[results_df['dt'] > (now - timedelta(hours=4))].sort_values('dt')
    if not future.empty:
        return future.iloc[0]['gw']
    
    # 全部過去なら最新のGW
    past = results_df[results_df['dt'] <= now].sort_values('dt', ascending=False)
    if not past.empty:
        return past.iloc[0]['gw']
        
    return "GW1"

# ==============================================================================
# 3. UIコンポーネント
# ==============================================================================

def render_match_card(m, odds_df, bets_df, user_name, is_bm, results_df):
    mid = m['match_id']
    kickoff_dt = pd.to_datetime(m['utc_kickoff'])
    kickoff_str = kickoff_dt.tz_convert(JST).strftime('%m/%d %H:%M')
    
    o_row = odds_df[odds_df['match_id'] == mid]
    oh = o_row.iloc[0]['home_win'] if not o_row.empty else 0
    od = o_row.iloc[0]['draw'] if not o_row.empty else 0
    oa = o_row.iloc[0]['away_win'] if not o_row.empty else 0
    
    form_h = get_recent_form(m['home'], results_df, kickoff_dt)
    form_a = get_recent_form(m['away'], results_df, kickoff_dt)
    
    # 全員のベット状況を取得
    match_bets = pd.DataFrame()
    if not bets_df.empty:
        match_bets = bets_df[bets_df['match_id'] == mid]
    
    my_bet_row = match_bets[match_bets['user'] == user_name] if not match_bets.empty else pd.DataFrame()
    has_bet = not my_bet_row.empty
    current_pick = my_bet_row.iloc[0]['pick'] if has_bet else None
    current_stake = my_bet_row.iloc[0]['stake'] if has_bet else 1000
    
    st.markdown(f"""
    <div class="app-card">
        <div style="display:flex; justify-content:space-between; margin-bottom:8px; color:#aaa; font-size:0.8rem">
            <span>{kickoff_str}</span>
            <span>{m['status']}</span>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 20px 1fr; align-items:center; text-align:center;">
            <div>
                <div class="team-name">{m['home']}</div>
                <div style="margin-top:2px">{form_h}</div>
                <div style="color:#4ade80; font-weight:bold; font-size:1.1rem; margin-top:4px">{oh if oh else '-'}</div>
            </div>
            <div class="vs">vs</div>
            <div>
                <div class="team-name">{m['away']}</div>
                <div style="margin-top:2px">{form_a}</div>
                <div style="color:#4ade80; font-weight:bold; font-size:1.1rem; margin-top:4px">{oa if oa else '-'}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    # ★ 誰が賭けているかを表示（BMも見れるように）
    if not match_bets.empty:
        st.markdown("<div style='margin-top:10px; border-top:1px solid #444; padding-top:5px'>", unsafe_allow_html=True)
        for _, b in match_bets.iterrows():
            # 自分のベットはフォームでわかるので、ここではシンプルに全員分出すか、他人だけ出すか。
            # 要望は「BMも誰がいくら賭けてるか見えるように」なので全員出すのが親切。
            u = b['user']
            p = b['pick']
            s = int(b['stake'])
            # アイコン色
            icon = "👤"
            if u == user_name: icon = "🟢" # 自分
            
            st.markdown(f"""
            <div class="bet-list-row">
                <span class="bet-user">{icon} {u}</span>
                <span>
                    <span class="bet-pick">{p}</span>
                    <span class="bet-amt">¥{s:,}</span>
                </span>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # フォーム制御
    is_open = m['status'] not in ['IN_PLAY', 'FINISHED', 'PAUSED'] and oh > 0
    
    if not is_open:
        st.markdown(f"<div style='text-align:center; padding:10px; color:#aaa'>受付終了</div></div>", unsafe_allow_html=True)
    elif is_bm:
        st.markdown(f"<div style='text-align:center; padding:10px; background:rgba(251,191,36,0.1); border-radius:8px; color:#fbbf24; font-weight:bold'>あなたはBMです (親)</div></div>", unsafe_allow_html=True)
    else:
        st.markdown("</div>", unsafe_allow_html=True) 
        
        with st.form(key=f"bet_{mid}"):
            c1, c2, c3 = st.columns([3, 2, 2])
            opts = [f"HOME ({oh})", f"DRAW ({od})", f"AWAY ({oa})"]
            
            def_idx = 0
            if current_pick == "HOME": def_idx = 0
            elif current_pick == "DRAW": def_idx = 1
            elif current_pick == "AWAY": def_idx = 2
            
            choice = c1.selectbox("Pick", opts, index=def_idx, label_visibility="collapsed")
            stake = c2.number_input("¥", 100, 20000, int(current_stake), 100, label_visibility="collapsed")
            btn_label = "Update" if has_bet else "BET"
            
            if c3.form_submit_button(btn_label, use_container_width=True):
                tgt = "HOME" if "HOME" in choice else ("DRAW" if "DRAW" in choice else "AWAY")
                oval = float(oh if tgt=="HOME" else (od if tgt=="DRAW" else oa))
                
                key = f"{m['gw']}:{user_name}:{mid}"
                supabase.table("bets").upsert({
                    "key": key, "gw": m['gw'], "user": user_name,
                    "match_id": mid, "match": f"{m['home']} vs {m['away']}",
                    "pick": tgt, "stake": stake, "odds": oval,
                    "placed_at": datetime.datetime.now().isoformat(),
                    "status": "OPEN", "result": ""
                }).execute()
                
                st.success("Saved!")
                time.sleep(0.5)
                st.rerun()

# ==============================================================================
# 4. メイン処理
# ==============================================================================
def main():
    if not supabase: st.error("DB Error"); st.stop()
    
    # Load Data (Safe)
    bets, odds, results, bm_log, users, config = fetch_all_data()
    
    # Usersが空ならエラー回避用のダミーまたは停止
    if users.empty:
        st.error("User data not found. Please run migration.")
        st.stop()

    # Login
    if 'user' not in st.session_state: st.session_state['user'] = None
    if not st.session_state['user']:
        st.sidebar.title("🔐 Login")
        u_list = users['username'].tolist()
        name = st.sidebar.selectbox("User", u_list)
        pw = st.sidebar.text_input("Pass", type="password")
        if st.sidebar.button("Login"):
            # 安全に取得
            u_rows = users[users['username'] == name]
            if not u_rows.empty and str(u_rows.iloc[0]['password']) == pw:
                st.session_state['user'] = u_rows.iloc[0].to_dict()
                st.rerun()
            else: st.error("NG")
        st.stop()
        
    me = st.session_state['user']
    token = get_config_value(config, 'FOOTBALL_DATA_API_TOKEN') or st.secrets.get("api_token")

    # Auto Sync (Season 2025)
    if 'synced_v3' not in st.session_state:
        with st.spinner("🔄 Checking Season 2025 matches..."):
            sync_incremental(token)
        st.session_state['synced_v3'] = True
        # リロードして最新反映
        st.rerun()

    # Determine GW
    current_gw = determine_gw(results)
    
    # Determine BM
    current_bm = "未定"
    if not bm_log.empty:
        # 数字抽出してマッチング
        target_num = "".join([c for c in current_gw if c.isdigit()])
        for _, row in bm_log.iterrows():
            row_gw = "".join([c for c in str(row['gw']) if c.isdigit()])
            if row_gw == target_num:
                current_bm = row['bookmaker']
                break
    
    is_bm = (me['username'] == current_bm)

    # --- UI ---
    st.sidebar.markdown(f"## 👤 {me['username']}")
    st.sidebar.info(f"Role: {me['role']}")
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None; st.rerun()

    tabs = st.tabs(["⚽ Matches", "📊 Dashboard", "📜 History"])

    # [1] Matches
    with tabs[0]:
        c1, c2 = st.columns([3, 1])
        c1.markdown(f"### {current_gw} Fixtures")
        if is_bm: c2.markdown(f"<div class='bm-badge'>👑 You are BM</div>", unsafe_allow_html=True)
        else: c2.markdown(f"<div class='bm-badge'>BM: {current_bm}</div>", unsafe_allow_html=True)

        if not results.empty:
            gw_opts = sorted(results['gw'].unique(), key=lambda x: int("".join([c for c in str(x) if c.isdigit()] or 0)))
            idx = gw_opts.index(current_gw) if current_gw in gw_opts else 0
            sel_gw = st.selectbox("GW", gw_opts, index=idx, label_visibility="collapsed")
            
            target_matches = results[results['gw'] == sel_gw].sort_values('utc_kickoff')
            
            if target_matches.empty:
                st.info("No matches found.")
            else:
                for _, m in target_matches.iterrows():
                    render_match_card(m, odds, bets, me['username'], is_bm, results)
        else:
            st.info("Match data is empty.")

    # [2] Dashboard (Simple)
    with tabs[1]:
        st.markdown("#### Stats (Under Construction)")
        st.info("詳しい集計機能は開発中です")

    # [3] History
    with tabs[2]:
        st.markdown("#### History")
        if not bets.empty:
            st.dataframe(bets[['gw', 'match', 'pick', 'stake', 'result', 'user']], use_container_width=True)

if __name__ == "__main__":
    main()
