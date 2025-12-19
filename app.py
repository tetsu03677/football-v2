import streamlit as st
import pandas as pd
import requests
import datetime
import time
import pytz
from datetime import timedelta
from supabase import create_client

# ==============================================================================
# 0. System Configuration & Styles (Mobile First)
# ==============================================================================
st.set_page_config(page_title="Football App V3", layout="wide", page_icon="⚽")
JST = pytz.timezone('Asia/Tokyo')

st.markdown("""
<style>
/* --- Layout --- */
.block-container { padding-top: 3.5rem; padding-bottom: 5rem; max-width: 800px; }

/* --- Cards --- */
.app-card {
    border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 16px;
    background: linear-gradient(145deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%);
    margin-bottom: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.2);
}

/* --- Form Icons (Recent Form) --- */
.form-icon { display: inline-block; width: 20px; text-align: center; font-weight: bold; }
.form-win { font-size: 1rem; } /* 🔵 */
.form-lose { font-size: 1rem; } /* ❌ */
.form-draw { font-size: 1.2rem; color: #111; text-shadow: 0 0 1px #888; line-height: 1; } /* ▲ */

/* --- Badges --- */
.bm-badge {
    background: #fbbf24; color: #000; padding: 4px 12px; border-radius: 99px;
    font-weight: bold; font-size: 0.8rem; display: inline-block; margin-bottom: 8px;
}
.gw-tag {
    background: rgba(255,255,255,0.1); color: #ddd; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;
}

/* --- Typography --- */
.match-time { font-family: monospace; color: #a5b4fc; font-size: 0.9rem; }
.team-name { font-weight: bold; font-size: 1.1rem; }
.vs { color: #888; font-size: 0.9rem; margin: 0 8px; }
.odds-val { color: #4ade80; font-weight: bold; font-size: 1.1rem; }

/* --- Bet List (Others) --- */
.bet-row {
    font-size: 0.8rem; padding: 4px 8px; border-radius: 4px; background: rgba(255,255,255,0.03); margin-top: 2px;
    display: flex; justify-content: space-between; align-items: center; color: #aaa;
}
.bet-hl { color: #fff; font-weight: bold; background: rgba(255,255,255,0.1); }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. Database & Config Access (Safe Fetch)
# ==============================================================================
@st.cache_resource
def get_supabase():
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except: return None

supabase = get_supabase()

def fetch_all_data():
    """Fetch all tables safely with schema validation to prevent KeyError"""
    try:
        def get_df_safe(table, expected_cols):
            try:
                res = supabase.table(table).select("*").execute()
                df = pd.DataFrame(res.data) if res.data else pd.DataFrame(columns=expected_cols)
                # Ensure all expected columns exist even if empty
                for col in expected_cols:
                    if col not in df.columns:
                        df[col] = None
                return df
            except:
                return pd.DataFrame(columns=expected_cols)

        bets = get_df_safe("bets", ['key','user','match_id','pick','stake','odds','status','result','gw','placed_at'])
        odds = get_df_safe("odds", ['match_id','home_win','draw','away_win'])
        results = get_df_safe("result", ['match_id','gw','home','away','utc_kickoff','status','home_score','away_score'])
        bm_log = get_df_safe("bm_log", ['gw','bookmaker'])
        users = get_df_safe("users", ['username','password','role','team'])
        config = get_df_safe("config", ['key','value'])
        
        return bets, odds, results, bm_log, users, config
    except Exception as e:
        st.error(f"Critical DB Error: {e}")
        return [pd.DataFrame()]*6

def get_api_token(config_df):
    # Secrets priority > Config Table
    token = st.secrets.get("api_token")
    if token: return token
    if not config_df.empty:
        row = config_df[config_df['key'] == 'FOOTBALL_DATA_API_TOKEN']
        if not row.empty: return row.iloc[0]['value']
    return ""

# ==============================================================================
# 2. Business Logic (JST, Zero-Sum, Form)
# ==============================================================================

def to_jst(iso_str):
    """Convert ISO UTC string to JST datetime object"""
    if not iso_str: return None
    try:
        dt = pd.to_datetime(iso_str)
        if dt.tz is None: dt = dt.tz_localize('UTC')
        return dt.tz_convert(JST)
    except: return None

def get_recent_form(team_name, results_df, current_kickoff_jst):
    """Generate Form Guide (🔵❌▲) based on finished matches before kickoff (JST)"""
    if results_df.empty: return "-"
    
    # Ensure JST column
    if 'dt_jst' not in results_df.columns:
        results_df['dt_jst'] = results_df['utc_kickoff'].apply(to_jst)
    
    # Filter past finished matches
    past = results_df[
        (results_df['status'] == 'FINISHED') & 
        (results_df['dt_jst'] < current_kickoff_jst) &
        ((results_df['home'] == team_name) | (results_df['away'] == team_name))
    ].sort_values('dt_jst', ascending=False).head(5)
    
    icons = []
    # Left = Newest
    for _, g in past.iterrows():
        is_home = (g['home'] == team_name)
        h = int(g['home_score']) if pd.notna(g['home_score']) else 0
        a = int(g['away_score']) if pd.notna(g['away_score']) else 0
        
        if h == a:
            icons.append('<span class="form-icon form-draw">▲</span>')
        elif (is_home and h > a) or (not is_home and a > h):
            icons.append('<span class="form-icon form-win">🔵</span>')
        else:
            icons.append('<span class="form-icon form-lose">❌</span>')
            
    return "".join(icons) if icons else "-"

def calculate_stats(bets_df, bm_log_df, users_df):
    """Zero-Sum P&L Calculation"""
    if users_df.empty: return {}
    
    # Init stats
    stats = {u: {'balance': 0, 'wins': 0, 'total': 0, 'potential': 0} for u in users_df['username'].unique()}
    
    # Build BM Map: "GW17" -> "Tetsu"
    bm_map = {}
    if not bm_log_df.empty:
        for _, r in bm_log_df.iterrows():
            # Normalize GW format (e.g. "GW7" or "7" -> "GW7")
            nums = "".join([c for c in str(r['gw']) if c.isdigit()])
            if nums: bm_map[f"GW{nums}"] = r['bookmaker']

    if bets_df.empty: return stats

    for _, b in bets_df.iterrows():
        user = b['user']
        if user not in stats: continue
        
        # Status normalization
        res = str(b.get('result', '')).upper()
        status = str(b.get('status', '')).upper()
        is_settled = (res in ['WIN', 'LOSE']) or (status == 'SETTLED' and res)
        
        # Values
        stake = float(b['stake']) if b['stake'] else 0
        odds = float(b['odds']) if b['odds'] else 1.0
        
        # Identify BM for this bet's GW
        nums = "".join([c for c in str(b['gw']) if c.isdigit()])
        gw_key = f"GW{nums}"
        bm = bm_map.get(gw_key)
        
        if is_settled:
            stats[user]['total'] += 1
            pnl = 0
            if res == 'WIN':
                stats[user]['wins'] += 1
                pnl = (stake * odds) - stake
            else:
                pnl = -stake
            
            # 1. Player Impact
            stats[user]['balance'] += int(pnl)
            
            # 2. BM Impact (Zero Sum)
            # BM takes opposite of Player P&L
            if bm and bm in stats and bm != user:
                stats[bm]['balance'] -= int(pnl)
        else:
            # Potential (Pending)
            pot = (stake * odds) - stake
            stats[user]['potential'] += int(pot)

    return stats

def determine_current_gw(results_df):
    """Find earliest GW with future matches (JST based)"""
    if results_df.empty: return "GW1"
    
    now_jst = datetime.datetime.now(JST)
    if 'dt_jst' not in results_df.columns:
        results_df['dt_jst'] = results_df['utc_kickoff'].apply(to_jst)
    
    # Matches starting > now - 4 hours
    active = results_df[results_df['dt_jst'] > (now_jst - timedelta(hours=4))].sort_values('dt_jst')
    
    if not active.empty:
        return active.iloc[0]['gw']
    
    # Fallback to last GW if season ended
    past = results_df[results_df['dt_jst'] <= now_jst].sort_values('dt_jst', ascending=False)
    if not past.empty:
        return past.iloc[0]['gw']
        
    return "GW1"

def sync_api(api_token):
    """Sync API (Season 2025 fixed, Upsert)"""
    if not api_token: return False
    # ★ Force Season 2025
    url = "https://api.football-data.org/v4/competitions/PL/matches?season=2025"
    headers = {'X-Auth-Token': api_token}
    
    try:
        r = requests.get(url, headers=headers)
        if r.status_code != 200: return False
        
        data = r.json().get('matches', [])
        upserts = []
        for m in data:
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
        
        # Batch Upsert
        for i in range(0, len(upserts), 100):
            supabase.table("result").upsert(upserts[i:i+100]).execute()
            
        return True
    except:
        return False

# ==============================================================================
# 3. UI Rendering Components
# ==============================================================================

def render_match_card(m, odds_df, bets_df, me, is_bm, results_df):
    """Render single match card with logic"""
    mid = m['match_id']
    dt_jst = to_jst(m['utc_kickoff'])
    dt_str = dt_jst.strftime('%m/%d %H:%M')
    
    # Odds
    o_row = odds_df[odds_df['match_id'] == mid]
    oh = o_row.iloc[0]['home_win'] if not o_row.empty else 0
    od = o_row.iloc[0]['draw'] if not o_row.empty else 0
    oa = o_row.iloc[0]['away_win'] if not o_row.empty else 0
    
    # Form
    form_h = get_recent_form(m['home'], results_df, dt_jst)
    form_a = get_recent_form(m['away'], results_df, dt_jst)
    
    # My Bet
    match_bets = bets_df[bets_df['match_id'] == mid] if not bets_df.empty else pd.DataFrame()
    my_bet = match_bets[match_bets['user'] == me] if not match_bets.empty else pd.DataFrame()
    has_bet = not my_bet.empty
    
    # --- UI ---
    st.markdown(f"""
    <div class="app-card">
        <div style="display:flex; justify-content:space-between; margin-bottom:8px; color:#aaa; font-size:0.8rem">
            <span class="match-time">⏱ {dt_str}</span>
            <span>{m['status']}</span>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 20px 1fr; align-items:center; text-align:center;">
            <div>
                <div class="team-name">{m['home']}</div>
                <div style="margin-top:2px">{form_h}</div>
                <div class="odds-val" style="margin-top:4px">{oh if oh else '-'}</div>
            </div>
            <div class="vs">vs</div>
            <div>
                <div class="team-name">{m['away']}</div>
                <div style="margin-top:2px">{form_a}</div>
                <div class="odds-val" style="margin-top:4px">{oa if oa else '-'}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    # Bet List (Who bet what)
    if not match_bets.empty:
        st.markdown("<div style='margin-top:10px; border-top:1px solid #444; padding-top:5px'>", unsafe_allow_html=True)
        for _, b in match_bets.iterrows():
            u_icon = "🟢" if b['user'] == me else "👤"
            hl_class = "bet-hl" if b['user'] == me else ""
            st.markdown(f"""
            <div class="bet-row {hl_class}">
                <span style="font-weight:bold">{u_icon} {b['user']}</span>
                <span>
                    <span style="color:#a5b4fc; margin-right:5px">{b['pick']}</span>
                    <span>¥{int(b['stake']):,}</span>
                </span>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # Input Form
    is_open = m['status'] not in ['IN_PLAY', 'FINISHED', 'PAUSED'] and oh > 0
    
    if not is_open:
        st.markdown(f"<div style='text-align:center; padding:10px; color:#aaa; font-size:0.8rem'>Betting Closed</div></div>", unsafe_allow_html=True)
    elif is_bm:
        st.markdown(f"<div style='text-align:center; padding:8px; background:rgba(251,191,36,0.15); border-radius:8px; color:#fbbf24; font-weight:bold; font-size:0.9rem; margin-top:10px'>👑 You are BM</div></div>", unsafe_allow_html=True)
    else:
        st.markdown("</div>", unsafe_allow_html=True) # Close card div
        
        # Form outside card to avoid Streamlit limitation
        with st.form(key=f"bform_{mid}"):
            c1, c2, c3 = st.columns([3, 2, 2])
            
            # Preset values
            cur_pick = my_bet.iloc[0]['pick'] if has_bet else "HOME"
            cur_stake = int(my_bet.iloc[0]['stake']) if has_bet else 1000
            
            # Pick Index
            opts = ["HOME", "DRAW", "AWAY"]
            try: p_idx = opts.index(cur_pick)
            except: p_idx = 0
            
            pick = c1.selectbox("Pick", opts, index=p_idx, label_visibility="collapsed")
            stake = c2.number_input("Stake", 100, 20000, cur_stake, 100, label_visibility="collapsed")
            btn_txt = "Update" if has_bet else "BET"
            
            if c3.form_submit_button(btn_txt, use_container_width=True):
                # Calc Odds
                target_odds = oh if pick=="HOME" else (od if pick=="DRAW" else oa)
                
                # Upsert Bet (JST time for display, but ISO format for DB)
                key = f"{m['gw']}:{me}:{mid}"
                payload = {
                    "key": key, "gw": m['gw'], "user": me, "match_id": mid,
                    "match": f"{m['home']} vs {m['away']}",
                    "pick": pick, "stake": stake, "odds": target_odds,
                    "placed_at": datetime.datetime.now(JST).isoformat(), # Use JST for record
                    "status": "OPEN", "result": ""
                }
                supabase.table("bets").upsert(payload).execute()
                st.toast(f"Bet {btn_txt} Success!", icon="✅")
                time.sleep(1)
                st.rerun()

# ==============================================================================
# 4. Main Application
# ==============================================================================
def main():
    if not supabase: st.error("Database Connection Failed"); st.stop()
    
    # 1. Load Data
    bets, odds, results, bm_log, users, config = fetch_all_data()
    
    # If users table is empty/failed, prevent crash
    if users.empty or 'username' not in users.columns:
        st.warning("User data is not available. Please run the sync script.")
        st.stop()

    # 2. Authentication
    if 'user' not in st.session_state: st.session_state['user'] = None
    
    if not st.session_state['user']:
        st.markdown("## 🔐 Login")
        u_name = st.selectbox("Username", users['username'].tolist())
        pw = st.text_input("Password", type="password")
        if st.button("Enter"):
            u_row = users[users['username'] == u_name]
            if not u_row.empty and str(u_row.iloc[0]['password']) == pw:
                st.session_state['user'] = u_name
                st.session_state['role'] = u_row.iloc[0]['role']
                st.session_state['team'] = u_row.iloc[0]['team']
                st.rerun()
            else:
                st.error("Invalid Password")
        st.stop()

    me = st.session_state['user']
    role = st.session_state.get('role', 'user')
    api_token = get_api_token(config)

    # 3. Auto Sync (Once per session)
    if 'v3_synced' not in st.session_state:
        with st.spinner("🚀 Syncing Season 2025 Data..."):
            sync_api(api_token)
        st.session_state['v3_synced'] = True
        st.rerun()

    # 4. Logic & Context
    current_gw = determine_current_gw(results)
    stats = calculate_stats(bets, bm_log, users)
    my_stat = stats.get(me, {'balance':0, 'wins':0, 'total':0, 'potential':0})
    
    # 5. UI Layout
    # Sidebar
    st.sidebar.markdown(f"## 👤 {me}")
    st.sidebar.caption(f"Team: {st.session_state.get('team')}")
    st.sidebar.divider()
    
    bal = my_stat['balance']
    color = "#4ade80" if bal >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:1.8rem; font-weight:800; color:{color}'>¥{bal:,}</div>", unsafe_allow_html=True)
    st.sidebar.caption("Total P&L")
    
    if my_stat['potential'] > 0:
        st.sidebar.markdown(f"""
        <div style='margin-top:10px; padding:10px; border:1px solid #4ade80; border-radius:8px; color:#4ade80; text-align:center;'>
            <div style='font-size:0.8rem'>PENDING</div>
            <div style='font-size:1.2rem; font-weight:bold'>+¥{my_stat['potential']:,}</div>
        </div>
        """, unsafe_allow_html=True)

    st.sidebar.divider()
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None; st.rerun()

    # Tabs
    t1, t2, t3, t4, t5 = st.tabs(["⚽ Matches", "📊 Dashboard", "📜 History", "🏆 Standings", "🛠 Admin"])

    # [TAB 1] Matches (Betting)
    with t1:
        # GW Selector (Sorted)
        gw_list = []
        if not results.empty:
            uniq = results['gw'].unique()
            gw_list = sorted(uniq, key=lambda x: int("".join([c for c in str(x) if c.isdigit()] or 0)))
        
        c_gw, c_bm = st.columns([2, 1])
        if gw_list:
            idx = gw_list.index(current_gw) if current_gw in gw_list else 0
            sel_gw = c_gw.selectbox("Gameweek", gw_list, index=idx, label_visibility="collapsed")
            
            # Determine BM for selected GW
            sel_gw_num = "".join([c for c in sel_gw if c.isdigit()])
            gw_bm_name = "Undecided"
            if not bm_log.empty:
                for _, r in bm_log.iterrows():
                    r_num = "".join([c for c in str(r['gw']) if c.isdigit()])
                    if r_num == sel_gw_num: gw_bm_name = r['bookmaker']; break
            
            is_bm = (me == gw_bm_name)
            bm_disp = f"👑 You are BM" if is_bm else f"BM: {gw_bm_name}"
            c_bm.markdown(f"<div class='bm-badge'>{bm_disp}</div>", unsafe_allow_html=True)

            # Filter Matches (Sort by Time JST)
            matches = results[results['gw'] == sel_gw].copy()
            if not matches.empty:
                matches['dt_jst'] = matches['utc_kickoff'].apply(to_jst)
                matches = matches.sort_values('dt_jst')
                
                for _, m in matches.iterrows():
                    render_match_card(m, odds, bets, me, is_bm, results)
            else:
                st.info("No matches found for this Gameweek.")
        else:
            st.info("No match data available.")

    # [TAB 2] Dashboard
    with t2:
        st.markdown(f"#### Performance")
        win_rate = (my_stat['wins'] / my_stat['total'] * 100) if my_stat['total'] else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Win Rate", f"{win_rate:.1f}%")
        c2.metric("Wins", f"{my_stat['wins']} / {my_stat['total']}")
        c3.metric("Current GW", current_gw)

    # [TAB 3] History
    with t3:
        st.markdown("#### Betting Logs")
        if not bets.empty:
            # Filter
            users_list = ["All"] + list(users['username'].unique())
            f_user = st.selectbox("User Filter", users_list)
            
            hist = bets.copy()
            if f_user != "All": hist = hist[hist['user'] == f_user]
            
            hist['placed_jst'] = hist['placed_at'].apply(lambda x: to_jst(x).strftime('%m/%d %H:%M') if x else "-")
            hist = hist.sort_values('placed_at', ascending=False)
            
            # Display Table
            st.dataframe(
                hist[['placed_jst', 'user', 'gw', 'match', 'pick', 'stake', 'result', 'odds']],
                column_config={
                    "stake": st.column_config.NumberColumn(format="¥%d"),
                    "odds": st.column_config.NumberColumn(format="%.2f")
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No bets found.")

    # [TAB 4] Standings
    with t4:
        st.markdown("#### Leaderboard")
        ranking = []
        for u, s in stats.items():
            ranking.append({'User': u, 'Balance': s['balance'], 'Wins': s['wins']})
        
        df_rank = pd.DataFrame(ranking).sort_values('Balance', ascending=False)
        st.dataframe(
            df_rank,
            column_config={"Balance": st.column_config.NumberColumn(format="¥%d")},
            use_container_width=True,
            hide_index=True
        )

    # [TAB 5] Admin
    with t5:
        if role == 'admin':
            st.markdown("#### 🛠 Admin Tools")
            with st.expander("Assign Bookmaker"):
                with st.form("bm_assign"):
                    # Use unique list for GW
                    t_gw = st.selectbox("GW", gw_list if gw_list else ["GW1"], key="admin_gw")
                    t_user = st.selectbox("User", users['username'].tolist(), key="admin_u")
                    if st.form_submit_button("Assign"):
                        supabase.table("bm_log").upsert({
                            "gw": t_gw, "bookmaker": t_user
                        }).execute()
                        st.success("Assigned.")
                        time.sleep(1); st.rerun()
                        
            with st.expander("Force Data Reset"):
                st.error("DANGER: This deletes all match data and re-syncs.")
                if st.button("💥 Reset Matches (Season 2025)"):
                    supabase.table("result").delete().neq("match_id", -1).execute()
                    sync_api(api_token)
                    st.success("Reset Complete.")
                    time.sleep(1); st.rerun()
        else:
            st.info("Admin only area.")

if __name__ == "__main__":
    main()
