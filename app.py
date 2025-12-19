import streamlit as st
import pandas as pd
import requests
import datetime
import time
import pytz
import random
import altair as alt
from datetime import timedelta
from supabase import create_client

# ==============================================================================
# 0. System Configuration & CSS (Ultimate Dark Mode)
# ==============================================================================
st.set_page_config(page_title="Football App V3.7", layout="wide", page_icon="⚽")
JST = pytz.timezone('Asia/Tokyo')

st.markdown("""
<style>
    /* --- Root Variables & Reset --- */
    :root {
        --bg-color: #0e1117;
        --card-bg: #1f2937; /* Slightly lighter dark */
        --input-bg: #262730;
        --text-color: #fafafa;
        --accent-color: #fbbf24;
        --win-color: #4ade80;
        --lose-color: #f87171;
    }
    
    .stApp {
        background-color: var(--bg-color);
        color: var(--text-color);
    }

    /* --- Overriding Streamlit Widgets (Dark Mode Enforcement) --- */
    /* Input fields background & text */
    .stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] {
        background-color: var(--input-bg) !important;
        color: var(--text-color) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
    }
    /* Selectbox dropdown options */
    ul[data-baseweb="menu"] {
        background-color: var(--input-bg) !important;
    }
    /* Secondary text */
    p, label, .stMarkdown {
        color: #e5e7eb !important;
    }

    /* --- Layout --- */
    .block-container {
        padding-top: 3.5rem;
        padding-bottom: 6rem;
        max-width: 100%;
        padding-left: 0.5rem;
        padding-right: 0.5rem;
    }

    /* --- Vertical Card Integration --- */
    /* Top HTML Part */
    .app-card-top {
        border: 1px solid rgba(255,255,255,0.08);
        border-bottom: none;
        border-radius: 12px 12px 0 0;
        padding: 16px;
        background: linear-gradient(180deg, rgba(30,30,30,1) 0%, rgba(20,20,20,1) 100%);
        margin-bottom: 0px;
    }
    /* Bottom Form Part */
    [data-testid="stForm"] {
        border: 1px solid rgba(255,255,255,0.08);
        border-top: none;
        border-radius: 0 0 12px 12px;
        padding: 0 16px 16px 16px;
        background: linear-gradient(180deg, rgba(20,20,20,1) 0%, rgba(15,15,15,1) 100%);
        margin-bottom: 24px; /* Space between matches */
    }

    /* --- Typography & Components --- */
    .card-header {
        display: flex; justify-content: space-between;
        font-family: 'Courier New', monospace; font-size: 0.8rem; color: #9ca3af;
        border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 8px; margin-bottom: 12px;
    }
    
    .matchup-grid {
        display: grid; grid-template-columns: 1fr auto 1fr;
        align-items: center; text-align: center; gap: 8px; margin-bottom: 12px;
    }
    .team-name { font-weight: 700; font-size: 1.0rem; line-height: 1.2; min-height: 2.4em; display:flex; align-items:center; justify-content:center; color: #fff; }
    .score-box { 
        font-family: 'Courier New', monospace; font-size: 1.6rem; font-weight: 800; 
        color: #fff; background: rgba(255,255,255,0.05); padding: 4px 12px; border-radius: 6px; letter-spacing: 2px;
    }
    
    .form-box { display: flex; gap: 4px; justify-content: center; margin-top: 6px; }
    .form-item { display: flex; flex-direction: column; align-items: center; line-height: 1; }
    .form-ha { font-size: 0.6rem; color: #6b7280; font-weight: bold; margin-bottom: 2px; }
    .form-icon { font-size: 0.85rem; } /* Minimalist sizing */
    
    .info-row {
        display: flex; justify-content: space-around; background: rgba(0,0,0,0.2);
        padding: 8px; border-radius: 6px; font-size: 0.85rem; margin-bottom: 8px;
    }
    .odds-label { font-size: 0.65rem; color: #6b7280; text-transform: uppercase; letter-spacing: 1px; }
    .odds-value { font-weight: bold; color: var(--win-color); font-family: monospace; font-size: 1rem; }

    /* Social Badges (Text Based, No Icons) */
    .social-bets-container { 
        display: flex; flex-wrap: wrap; gap: 6px; justify-content: center;
        padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.05);
    }
    .bet-badge {
        display: inline-flex; align-items: center; gap: 6px;
        background: rgba(0,0,0,0.3); padding: 4px 10px; border-radius: 4px;
        font-size: 0.7rem; color: #9ca3af; border: 1px solid rgba(255,255,255,0.05);
    }
    .bet-badge.me { 
        background: rgba(59, 130, 246, 0.1); border: 1px solid #3b82f6; color: #fff; 
    }
    .bb-pick { font-weight: bold; color: #a5b4fc; text-transform: uppercase; }

    /* Status Messages */
    .status-msg { text-align: center; color: #6b7280; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; margin-top: 10px; padding-bottom: 8px; }
    .bm-badge { background: var(--accent-color); color: #000; padding: 2px 8px; border-radius: 4px; font-weight: 800; font-size: 0.7rem; text-transform: uppercase; }

    /* Live Pulse Animation */
    @keyframes pulse-red { 0% { color: #fff; opacity: 1; } 50% { color: #f87171; opacity: 0.7; } 100% { color: #fff; opacity: 1; } }
    .live-inplay { animation: pulse-red 2s infinite; font-weight: bold; color: #f87171; }

    /* History Cards */
    .hist-card { background: rgba(255,255,255,0.02); border-radius: 6px; padding: 12px; margin-bottom: 8px; border-left: 3px solid #444; }
    .h-win { border-left-color: var(--win-color); }
    .h-lose { border-left-color: var(--lose-color); }

    /* Clean up Streamlit */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
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
    """Fetch all tables safely, ensuring no KeyError even if empty."""
    try:
        def get_df_safe(table, expected_cols):
            try:
                res = supabase.table(table).select("*").execute()
                df = pd.DataFrame(res.data) if res.data else pd.DataFrame(columns=expected_cols)
                for col in expected_cols:
                    if col not in df.columns: df[col] = None
                return df
            except:
                return pd.DataFrame(columns=expected_cols)

        # Bets: Added 'gw' just in case
        bets = get_df_safe("bets", ['key','user','match_id','pick','stake','odds','status','result','gw','placed_at'])
        odds = get_df_safe("odds", ['match_id','home_win','draw','away_win'])
        results = get_df_safe("result", ['match_id','gw','home','away','utc_kickoff','status','home_score','away_score'])
        bm_log = get_df_safe("bm_log", ['gw','bookmaker'])
        users = get_df_safe("users", ['username','password','role','team'])
        config = get_df_safe("config", ['key','value'])
        
        return bets, odds, results, bm_log, users, config
    except Exception as e:
        st.error(f"Critical System Error: {e}")
        return [pd.DataFrame()]*6

def get_api_token(config_df):
    token = st.secrets.get("api_token")
    if token: return token
    if not config_df.empty:
        row = config_df[config_df['key'] == 'FOOTBALL_DATA_API_TOKEN']
        if not row.empty: return row.iloc[0]['value']
    return ""

def get_config_value(config_df, key, default):
    if config_df.empty: return default
    row = config_df[config_df['key'] == key]
    if not row.empty: 
        try: return int(row.iloc[0]['value'])
        except: return row.iloc[0]['value']
    return default

# ==============================================================================
# 2. Business Logic (Robust & Strict)
# ==============================================================================

def to_jst(iso_str):
    if not iso_str: return None
    try:
        dt = pd.to_datetime(iso_str)
        if dt.tz is None: dt = dt.tz_localize('UTC')
        return dt.tz_convert(JST)
    except: return None

def get_recent_form_html(team_name, results_df, current_kickoff_jst):
    """
    Generate HTML Form Guide (Single Line String).
    Safe logic: Only 2025 season, finished matches.
    """
    if results_df.empty: return "-"
    if 'dt_jst' not in results_df.columns:
        results_df['dt_jst'] = results_df['utc_kickoff'].apply(to_jst)
    
    season_start = pd.Timestamp("2025-07-01", tz=JST)
    past = results_df[
        (results_df['dt_jst'] >= season_start) &
        (results_df['status'] == 'FINISHED') & 
        (results_df['dt_jst'] < current_kickoff_jst) &
        ((results_df['home'] == team_name) | (results_df['away'] == team_name))
    ].sort_values('dt_jst', ascending=False).head(5)
    
    if past.empty: return '<span style="color:#4b5563">-</span>'

    # Build HTML as a single concatenated string (NO NEWLINES)
    html_parts = ['<div class="form-box">']
    for _, g in past.iterrows():
        is_home = (g['home'] == team_name)
        ha_label = "H" if is_home else "A"
        
        # Safe score handling
        h = int(g['home_score']) if pd.notna(g['home_score']) else 0
        a = int(g['away_score']) if pd.notna(g['away_score']) else 0
        
        icon = '❌' # Default
        if h == a: icon = '<span style="color:#9ca3af">▲</span>'
        elif (is_home and h > a) or (not is_home and a > h): icon = '🔵'
        
        html_parts.append(f'<div class="form-item"><span class="form-ha">{ha_label}</span><span class="form-icon">{icon}</span></div>')
    
    html_parts.append('</div>')
    return "".join(html_parts)

def calculate_stats(bets_df, bm_log_df, users_df):
    """Zero-Sum P&L for settled bets"""
    if users_df.empty: return {}, {}
    stats = {u: {'balance': 0, 'wins': 0, 'total': 0, 'potential': 0} for u in users_df['username'].unique()}
    
    bm_map = {}
    if not bm_log_df.empty:
        for _, r in bm_log_df.iterrows():
            nums = "".join([c for c in str(r['gw']) if c.isdigit()])
            if nums: bm_map[f"GW{nums}"] = r['bookmaker']

    if bets_df.empty: return stats, bm_map

    for _, b in bets_df.iterrows():
        user = b['user']
        if user not in stats: continue
        res = str(b.get('result', '')).upper()
        status = str(b.get('status', '')).upper()
        is_settled = (res in ['WIN', 'LOSE']) or (status == 'SETTLED' and res)
        stake = float(b['stake']) if b['stake'] else 0
        odds = float(b['odds']) if b['odds'] else 1.0
        
        nums = "".join([c for c in str(b['gw']) if c.isdigit()])
        gw_key = f"GW{nums}"
        bm = bm_map.get(gw_key)
        
        if is_settled:
            stats[user]['total'] += 1
            pnl = (stake * odds) - stake if res == 'WIN' else -stake
            stats[user]['balance'] += int(pnl)
            if bm and bm in stats and bm != user:
                stats[bm]['balance'] -= int(pnl)
        else:
            stats[user]['potential'] += int((stake * odds) - stake)

    return stats, bm_map

def calculate_live_pnl(bets_df, results_df, bm_map, users_df, target_gw):
    """Live P&L with active match simulation"""
    base_stats, _ = calculate_stats(bets_df, pd.DataFrame(list(bm_map.items()), columns=['gw','bookmaker']), users_df)
    live_data = []

    target_bets = bets_df[(bets_df['gw'] == target_gw) & (bets_df['status'] == 'OPEN')].copy()
    sim_pnl = {u: 0 for u in users_df['username'].unique()}
    current_bm = bm_map.get(target_gw)
    
    if not target_bets.empty and not results_df.empty:
        for _, b in target_bets.iterrows():
            mid = b['match_id']
            m_row = results_df[results_df['match_id'] == mid]
            if m_row.empty: continue
            m = m_row.iloc[0]
            if m['status'] not in ['SCHEDULED', 'TIMED', 'POSTPONED']:
                # Safe Score Parsing
                h_sc = int(m['home_score']) if pd.notna(m['home_score']) else 0
                a_sc = int(m['away_score']) if pd.notna(m['away_score']) else 0
                
                outcome = "DRAW"
                if h_sc > a_sc: outcome = "HOME"
                elif a_sc > h_sc: outcome = "AWAY"
                
                pnl = ((float(b['stake']) * float(b['odds'])) - float(b['stake'])) if b['pick'] == outcome else -float(b['stake'])
                sim_pnl[b['user']] += int(pnl)
                if current_bm and current_bm in sim_pnl and current_bm != b['user']:
                    sim_pnl[current_bm] -= int(pnl)

    for u, s in base_stats.items():
        live_data.append({
            'User': u, 'Total': s['balance'] + sim_pnl.get(u, 0), 'LiveDiff': sim_pnl.get(u, 0)
        })
    return pd.DataFrame(live_data).sort_values('Total', ascending=False)

def get_strict_target_gw(results_df):
    """Find earliest GW with future matches (Season 2025)"""
    if results_df.empty: return "GW1"
    now_jst = datetime.datetime.now(JST)
    if 'dt_jst' not in results_df.columns: results_df['dt_jst'] = results_df['utc_kickoff'].apply(to_jst)
    
    season_start = pd.Timestamp("2025-07-01", tz=JST)
    current_season_matches = results_df[results_df['dt_jst'] >= season_start]
    if current_season_matches.empty: return "GW1"

    future_matches = current_season_matches[current_season_matches['dt_jst'] > (now_jst - timedelta(hours=4))].sort_values('dt_jst')
    if not future_matches.empty: return future_matches.iloc[0]['gw']
    
    past = current_season_matches.sort_values('dt_jst', ascending=False)
    if not past.empty: return past.iloc[0]['gw']
    return "GW1"

def check_and_assign_bm(target_gw, bm_log_df, users_df):
    """Fairness Algorithm for BM Assignment"""
    if users_df.empty: return
    nums = "".join([c for c in target_gw if c.isdigit()])
    existing = False
    if not bm_log_df.empty:
        for _, r in bm_log_df.iterrows():
            r_num = "".join([c for c in str(r['gw']) if c.isdigit()])
            if r_num == nums: existing = True; break
    if existing: return
    
    all_users = users_df['username'].tolist()
    counts = {u: 0 for u in all_users}
    last_bm = None
    if not bm_log_df.empty:
        for _, r in bm_log_df.iterrows():
            bm = r['bookmaker']
            if bm in counts: counts[bm] += 1
            last_bm = bm
            
    min_count = min(counts.values())
    candidates = [u for u, c in counts.items() if c == min_count]
    if len(candidates) > 1 and last_bm in candidates: candidates.remove(last_bm)
    elif len(candidates) == 1 and candidates[0] == last_bm:
        next_candidates = [u for u, c in counts.items() if c == min_count + 1]
        if next_candidates: candidates = next_candidates
    
    new_bm = random.choice(candidates)
    supabase.table("bm_log").upsert({"gw": target_gw, "bookmaker": new_bm}).execute()
    return new_bm

def sync_api(api_token):
    if not api_token: return False
    url = "https://api.football-data.org/v4/competitions/PL/matches?season=2025"
    headers = {'X-Auth-Token': api_token}
    try:
        r = requests.get(url, headers=headers)
        if r.status_code != 200: return False
        data = r.json().get('matches', [])
        upserts = []
        for m in data:
            # Upsert with NULL handling for scores
            upserts.append({
                "match_id": m['id'], "gw": f"GW{m['matchday']}",
                "home": m['homeTeam']['name'], "away": m['awayTeam']['name'],
                "utc_kickoff": m['utcDate'], "status": m['status'],
                "home_score": m['score']['fullTime']['home'], 
                "away_score": m['score']['fullTime']['away'],
                "updated_at": datetime.datetime.now().isoformat()
            })
        for i in range(0, len(upserts), 100):
            supabase.table("result").upsert(upserts[i:i+100]).execute()
        return True
    except: return False

# ==============================================================================
# 3. Main Application
# ==============================================================================
def main():
    if not supabase: st.error("DB Error"); st.stop()
    
    bets, odds, results, bm_log, users, config = fetch_all_data()
    if users.empty: st.warning("User data missing."); st.stop()

    # Login
    if 'user' not in st.session_state or not st.session_state['user']:
        st.markdown("<h2 style='text-align:center;'>🔐 LOGIN</h2>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1,2,1])
        with c2:
            u = st.selectbox("User", users['username'].tolist(), label_visibility="collapsed")
            p = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
            if st.button("ENTER", use_container_width=True):
                row = users[users['username'] == u]
                if not row.empty and str(row.iloc[0]['password']) == p:
                    st.session_state['user'] = u
                    st.session_state['role'] = row.iloc[0]['role']
                    st.session_state['team'] = row.iloc[0]['team']
                    st.rerun()
                else: st.error("Invalid")
        st.stop()

    me = st.session_state['user']
    role = st.session_state.get('role', 'user')
    token = get_api_token(config)

    # Auto Sync
    if 'v37_synced' not in st.session_state:
        with st.spinner("🚀 Syncing..."): sync_api(token)
        st.session_state['v37_synced'] = True; st.rerun()

    target_gw = get_strict_target_gw(results)
    check_and_assign_bm(target_gw, bm_log, users)
    
    bm_log_refresh = supabase.table("bm_log").select("*").execute()
    bm_log = pd.DataFrame(bm_log_refresh.data) if bm_log_refresh.data else bm_log

    stats, bm_map = calculate_stats(bets, bm_log, users)
    nums = "".join([c for c in target_gw if c.isdigit()])
    current_bm = bm_map.get(f"GW{nums}", "Undecided")
    is_bm = (me == current_bm)
    
    lock_mins = get_config_value(config, "lock_minutes_before_earliest", 60)
    gw_locked = False
    
    # Sidebar
    st.sidebar.markdown(f"## 👤 {me}")
    st.sidebar.caption(f"Team: {st.session_state.get('team')}")
    my_stat = stats.get(me, {'balance':0})
    bal = my_stat['balance']
    col = "#4ade80" if bal >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:1.8rem; font-weight:800; color:{col}; font-family:monospace'>¥{bal:,}</div>", unsafe_allow_html=True)
    if st.sidebar.button("Logout"): st.session_state['user'] = None; st.rerun()

    t1, t2, t3, t4, t5, t6 = st.tabs(["⚽ MATCHES", "⚡ LIVE", "📈 ANALYTICS", "📜 HISTORY", "🏆 DASHBOARD", "🛠 ADMIN"])

    # --- TAB 1: Matches ---
    with t1:
        c_h1, c_h2 = st.columns([3, 1])
        c_h1.markdown(f"### {target_gw}")
        if is_bm: c_h2.markdown(f"<span class='bm-badge'>👑 YOU ARE BM</span>", unsafe_allow_html=True)
        else: c_h2.markdown(f"<span class='bm-badge'>BM: {current_bm}</span>", unsafe_allow_html=True)

        if not results.empty:
            matches = results[results['gw'] == target_gw].copy()
            if not matches.empty:
                matches['dt_jst'] = matches['utc_kickoff'].apply(to_jst)
                matches = matches[matches['dt_jst'] >= pd.Timestamp("2025-07-01", tz=JST)].sort_values('dt_jst')
                
                if not matches.empty:
                    first_ko = matches.iloc[0]['dt_jst']
                    lock_time = first_ko - timedelta(minutes=lock_mins)
                    if datetime.datetime.now(JST) >= lock_time:
                        gw_locked = True
                        st.info(f"🔒 LOCKED")

                for _, m in matches.iterrows():
                    mid = m['match_id']
                    dt_str = m['dt_jst'].strftime('%m/%d %H:%M')
                    
                    o_row = odds[odds['match_id'] == mid]
                    oh = o_row.iloc[0]['home_win'] if not o_row.empty else 0
                    od = o_row.iloc[0]['draw'] if not o_row.empty else 0
                    oa = o_row.iloc[0]['away_win'] if not o_row.empty else 0
                    
                    form_h = get_recent_form_html(m['home'], results, m['dt_jst'])
                    form_a = get_recent_form_html(m['away'], results, m['dt_jst'])
                    
                    match_bets = bets[bets['match_id'] == mid] if not bets.empty else pd.DataFrame()
                    my_bet = match_bets[match_bets['user'] == me] if not match_bets.empty else pd.DataFrame()
                    
                    # Safe Score Display
                    h_s = int(m['home_score']) if pd.notna(m['home_score']) else 0
                    a_s = int(m['away_score']) if pd.notna(m['away_score']) else 0
                    score_disp = f"{h_s}-{a_s}" if m['status'] != 'SCHEDULED' else "vs"

                    # Card Top (HTML)
                    card_html = f"""<div class="app-card-top"><div class="card-header"><span>⏱ {dt_str}</span><span>{m['status']}</span></div><div class="matchup-grid"><div class="team-col"><span class="team-name">{m['home']}</span>{form_h}</div><div class="team-col"><span class="score-box">{score_disp}</span></div><div class="team-col"><span class="team-name">{m['away']}</span>{form_a}</div></div><div class="info-row"><div class="odds-item"><div class="odds-label">HOME</div><div class="odds-value">{oh if oh else '-'}</div></div><div class="odds-item"><div class="odds-label">DRAW</div><div class="odds-value">{od if od else '-'}</div></div><div class="odds-item"><div class="odds-label">AWAY</div><div class="odds-value">{oa if oa else '-'}</div></div></div>"""
                    if not match_bets.empty:
                        badges = ""
                        for _, b in match_bets.iterrows():
                            me_cls = "me" if b['user'] == me else ""
                            pick_txt = b['pick'][:4] # Shorten
                            badges += f"""<div class="bet-badge {me_cls}"><span>{b['user']}:</span><span class="bb-pick">{pick_txt}</span></div>"""
                        card_html += f"""<div class="social-bets-container">{badges}</div>"""
                    card_html += "</div>"
                    st.markdown(card_html, unsafe_allow_html=True)

                    # Card Bottom (Form)
                    is_open = m['status'] not in ['IN_PLAY', 'FINISHED', 'PAUSED'] and oh > 0 and not gw_locked
                    
                    if not is_open:
                        msg = "CLOSED"
                        if oh == 0: msg = "WAITING ODDS"
                        elif gw_locked: msg = "LOCKED"
                        st.markdown(f"<div class='status-msg'>{msg}</div>", unsafe_allow_html=True)
                    elif is_bm:
                         st.markdown("<div style='margin-bottom:16px'></div>", unsafe_allow_html=True)
                    else:
                        with st.form(key=f"bf_{mid}"):
                            c_p, c_s, c_b = st.columns([3, 2, 2])
                            cur_p = my_bet.iloc[0]['pick'] if not my_bet.empty else "HOME"
                            cur_s = int(my_bet.iloc[0]['stake']) if not my_bet.empty else 1000
                            
                            pick = c_p.selectbox("Pick", ["HOME", "DRAW", "AWAY"], index=["HOME", "DRAW", "AWAY"].index(cur_p), label_visibility="collapsed")
                            stake = c_s.number_input("Stake", 100, 20000, cur_s, 100, label_visibility="collapsed")
                            
                            if c_b.form_submit_button("BET", use_container_width=True):
                                to = oh if pick=="HOME" else (od if pick=="DRAW" else oa)
                                pl = {"key": f"{m['gw']}:{me}:{mid}", "gw": m['gw'], "user": me, "match_id": mid, "match": f"{m['home']} vs {m['away']}", "pick": pick, "stake": stake, "odds": to, "placed_at": datetime.datetime.now(JST).isoformat(), "status": "OPEN", "result": ""}
                                supabase.table("bets").upsert(pl).execute()
                                st.toast("Saved!", icon="✅"); time.sleep(1); st.rerun()
            else: st.info(f"No matches for {target_gw}")
        else: st.info("Loading...")

    # --- TAB 2: Live ---
    with t2:
        st.markdown(f"### ⚡ LIVE: {target_gw}")
        if st.button("🔄 REFRESH", use_container_width=True): sync_api(token); st.rerun()
        
        live_df = calculate_live_pnl(bets, results, bm_map, users, target_gw)
        if not live_df.empty:
            for i, r in live_df.iterrows():
                diff = r['LiveDiff']
                diff_str = f"+¥{diff:,}" if diff > 0 else (f"¥{diff:,}" if diff < 0 else "-")
                d_cls = "diff-plus" if diff > 0 else ("diff-minus" if diff < 0 else "")
                st.markdown(f"""<div style="display:flex; justify-content:space-between; padding:12px; background:rgba(255,255,255,0.03); margin-bottom:4px; border-radius:6px; align-items:center"><div style="font-weight:bold; font-size:1.1rem; color:#fbbf24; width:30px">{i+1}</div><div style="flex:1; font-weight:bold;">{r['User']}</div><div style="text-align:right;"><div style="font-weight:bold; font-family:monospace">¥{int(r['Total']):,}</div><div style="font-size:0.8rem; color:{'#4ade80' if diff>0 else '#f87171'}">({diff_str})</div></div></div>""", unsafe_allow_html=True)
        
        st.markdown("#### SCOREBOARD")
        if not results.empty:
            lm = results[results['gw'] == target_gw].copy()
            lm['dt_jst'] = lm['utc_kickoff'].apply(to_jst)
            lm = lm.sort_values('dt_jst')
            for _, m in lm.iterrows():
                h_s = int(m['home_score']) if pd.notna(m['home_score']) else 0
                a_s = int(m['away_score']) if pd.notna(m['away_score']) else 0
                sts_cls = "live-inplay" if m['status'] in ['IN_PLAY', 'PAUSED'] else ""
                
                mb = bets[bets['match_id'] == m['match_id']] if not bets.empty else pd.DataFrame()
                stake_str = ""
                if not mb.empty:
                    parts = []
                    for _, b in mb.iterrows(): parts.append(f"{b['user']}:{b['pick'][0]}")
                    stake_str = " ".join(parts)

                st.markdown(f"""
                <div style="padding:12px; background:rgba(255,255,255,0.02); margin-bottom:8px; border-radius:8px; border:1px solid rgba(255,255,255,0.05)">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <div style="flex:1; text-align:right; font-size:0.9rem; color:#ddd">{m['home']}</div>
                        <div style="padding:0 15px; font-weight:800; font-family:monospace; font-size:1.2rem">{h_s}-{a_s}</div>
                        <div style="flex:1; font-size:0.9rem; color:#ddd">{m['away']}</div>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-top:6px; font-size:0.7rem; color:#666; text-transform:uppercase">
                        <span class="{sts_cls}">{m['status']}</span>
                        <span>{stake_str}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

    # --- TAB 3: Analytics ---
    with t3:
        st.markdown("### 📈 ANALYTICS")
        if not bets.empty:
            settled_bets = bets[bets['result'].isin(['WIN', 'LOSE'])].copy()
            if not settled_bets.empty:
                st.markdown("#### Team Affinity")
                analysis_data = []
                for _, b in settled_bets.iterrows():
                    m_row = results[results['match_id'] == b['match_id']]
                    if not m_row.empty:
                        m = m_row.iloc[0]
                        target_team = m['home'] if b['pick'] == 'HOME' else (m['away'] if b['pick'] == 'AWAY' else 'Draw')
                        if target_team != 'Draw':
                            analysis_data.append({'User': b['user'], 'Team': target_team, 'Result': 1 if b['result'] == 'WIN' else 0})
                
                if analysis_data:
                    df_an = pd.DataFrame(analysis_data).groupby(['User', 'Team']).mean().reset_index()
                    chart = alt.Chart(df_an).mark_rect().encode(
                        x='User:N', y='Team:N',
                        color=alt.Color('Result:Q', scale=alt.Scale(scheme='darkgreen'), title='Win Rate'),
                        tooltip=['User', 'Team', alt.Tooltip('Result', format='.0%')]
                    ).properties(height=500).configure_view(stroke='transparent').configure_axis(labelColor='#aaa', titleColor='#aaa').configure_legend(labelColor='#aaa', titleColor='#aaa')
                    st.altair_chart(chart, use_container_width=True)
            else: st.info("Not enough data.")
        else: st.info("No data.")

    # --- TAB 4: History ---
    with t4:
        if not bets.empty:
            c1, c2 = st.columns(2)
            sel_u = c1.selectbox("Filter User", ["All"] + list(users['username'].unique()))
            sel_g = c2.selectbox("Filter GW", ["All"] + sorted(list(bets['gw'].unique()), key=lambda x: int("".join([c for c in str(x) if c.isdigit()] or 0)), reverse=True))
            hist = bets.copy()
            if sel_u != "All": hist = hist[hist['user'] == sel_u]
            if sel_g != "All": hist = hist[hist['gw'] == sel_g]
            hist['dt_jst'] = hist['placed_at'].apply(to_jst)
            hist = hist.sort_values('dt_jst', ascending=False)
            
            for _, b in hist.iterrows():
                res = b['result'] if b['result'] else "OPEN"
                cls = "h-win" if res == 'WIN' else ("h-lose" if res == 'LOSE' else "")
                pnl_val = (b['stake']*b['odds'])-b['stake'] if res == 'WIN' else -b['stake']
                pnl = f"+¥{int(pnl_val):,}" if res == 'WIN' else (f"-¥{int(b['stake']):,}" if res=='LOSE' else "PENDING")
                col = "#4ade80" if res=='WIN' else ("#f87171" if res=='LOSE' else "#aaa")
                
                st.markdown(f"""
                <div class="hist-card {cls}">
                    <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:#aaa; margin-bottom:4px; text-transform:uppercase">
                        <span>{b['user']} | {b['gw']}</span>
                        <span style="color:{col}; font-weight:bold; font-family:monospace">{pnl}</span>
                    </div>
                    <div style="font-weight:bold; font-size:0.95rem; margin-bottom:4px">{b['match']}</div>
                    <div style="font-size:0.8rem; color:#ddd">
                        <span style="color:#a5b4fc; font-weight:bold">{b['pick']}</span> 
                        <span style="color:#666">(@{b['odds']})</span>
                        <span style="margin-left:8px; font-family:monospace">¥{int(b['stake']):,}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else: st.info("No history.")

    # --- TAB 5: Dashboard ---
    with t5:
        st.markdown("#### BM Stats")
        if not bm_log.empty:
            bm_counts = bm_log['bookmaker'].value_counts().reset_index()
            bm_counts.columns = ['User', 'Count']
            st.bar_chart(bm_counts.set_index('User'))
        
        st.markdown("#### Leaderboard")
        ranking = []
        for u, s in stats.items(): ranking.append({'User': u, 'Balance': s['balance'], 'Wins': s['wins']})
        st.dataframe(pd.DataFrame(ranking).sort_values('Balance', ascending=False), use_container_width=True, hide_index=True)

    # --- TAB 6: Admin ---
    with t6:
        if role == 'admin':
            st.markdown("#### ODDS EDITOR")
            with st.expander("📝 Update Odds", expanded=True):
                if not results.empty:
                    matches = results[results['gw'] == target_gw].copy()
                    if not matches.empty:
                        matches['dt_jst'] = matches['utc_kickoff'].apply(to_jst)
                        matches = matches[matches['dt_jst'] >= pd.Timestamp("2025-07-01", tz=JST)].sort_values('dt_jst')
                        m_opts = {f"{m['home']} vs {m['away']}": m['match_id'] for _, m in matches.iterrows()}
                        sel_m_name = st.selectbox("Match", list(m_opts.keys()))
                        sel_m_id = m_opts[sel_m_name]
                        curr_o = odds[odds['match_id'] == sel_m_id]
                        
                        def_h = float(curr_o.iloc[0]['home_win']) if not curr_o.empty else 0.0
                        def_d = float(curr_o.iloc[0]['draw']) if not curr_o.empty else 0.0
                        def_a = float(curr_o.iloc[0]['away_win']) if not curr_o.empty else 0.0
                        
                        c1, c2, c3 = st.columns(3)
                        new_h = c1.number_input("H", 0.0, 100.0, def_h, 0.01)
                        new_d = c2.number_input("D", 0.0, 100.0, def_d, 0.01)
                        new_a = c3.number_input("A", 0.0, 100.0, def_a, 0.01)
                        
                        if st.button("SAVE ODDS", use_container_width=True):
                            supabase.table("odds").upsert({"match_id": sel_m_id, "home_win": new_h, "draw": new_d, "away_win": new_a}).execute()
                            st.success("Updated"); time.sleep(1); st.rerun()
                    else: st.warning("No matches.")

if __name__ == "__main__":
    main()
