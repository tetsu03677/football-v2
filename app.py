import streamlit as st
import pandas as pd
import requests
import datetime
import time
import pytz
import random
import re
from datetime import timedelta
from supabase import create_client

# ==============================================================================
# 0. System Configuration & CSS (Native Dark Mode via config.toml)
# ==============================================================================
st.set_page_config(page_title="Football App V4.8", layout="wide", page_icon="⚽")
JST = pytz.timezone('Asia/Tokyo')

# Clean CSS: Focus on Layout & Glassmorphism.
st.markdown("""
<style>
    /* --- Layout Fix: Mobile Header Safety (SSOT 4.3) --- */
    .block-container {
        padding-top: 4.5rem;
        padding-bottom: 6rem;
        max-width: 100%;
        padding-left: 0.5rem;
        padding-right: 0.5rem;
    }

    /* --- Vertical Card Integration --- */
    .app-card-top {
        border: 1px solid rgba(255,255,255,0.1);
        border-bottom: none;
        border-radius: 12px 12px 0 0;
        padding: 20px 16px 10px 16px;
        background: rgba(255,255,255,0.03); 
        margin-bottom: 0px;
    }
    
    [data-testid="stForm"] {
        border: 1px solid rgba(255,255,255,0.1);
        border-top: none;
        border-radius: 0 0 12px 12px;
        padding: 0 16px 20px 16px;
        background: rgba(255,255,255,0.015);
        margin-bottom: 24px;
    }

    /* --- Responsive Match Card --- */
    .card-header {
        display: flex; justify-content: space-between;
        font-family: 'Courier New', monospace; font-size: 0.75rem; opacity: 0.7;
        border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 8px; margin-bottom: 16px;
        letter-spacing: 1px;
    }
    
    .matchup-flex {
        display: flex; align-items: center; justify-content: space-between;
        text-align: center; gap: 8px; margin-bottom: 16px;
    }
    
    .team-col {
        flex: 1; width: 0; display: flex; flex-direction: column;
        align-items: center; justify-content: flex-start;
    }
    
    .team-name { 
        font-weight: 700; font-size: 1.0rem; line-height: 1.2; 
        min-height: 2.4em; display:flex; align-items:center; justify-content:center;
        word-wrap: break-word; overflow-wrap: break-word;
    }
    
    .score-col { flex: 0 0 auto; }
    .score-box { 
        font-family: 'Courier New', monospace; font-size: 1.6rem; font-weight: 800; 
        padding: 4px 10px; background: rgba(255,255,255,0.05); border-radius: 6px; letter-spacing: 2px;
    }
    
    @media (max-width: 600px) {
        .team-name { font-size: 0.9rem; }
        .score-box { font-size: 1.4rem; padding: 2px 8px; }
    }

    /* --- Form Guide --- */
    .form-container { display: flex; align-items: center; justify-content: center; gap: 4px; margin-top: 8px; opacity: 0.8; }
    .form-arrow { font-size: 0.5rem; opacity: 0.5; text-transform: uppercase; margin: 0 2px; letter-spacing: 1px; }
    .form-item { display: flex; flex-direction: column; align-items: center; line-height: 1; margin: 0 1px;}
    .form-ha { font-size: 0.5rem; opacity: 0.5; font-weight: bold; margin-bottom: 2px; }
    .form-mark { font-size: 0.7rem; font-weight: bold; } 
    
    /* --- Info & Badges --- */
    .info-row {
        display: flex; justify-content: space-around; background: rgba(0,0,0,0.2);
        padding: 10px; border-radius: 6px; font-size: 0.9rem; margin-bottom: 12px;
    }
    .odds-label { font-size: 0.6rem; opacity: 0.5; text-transform: uppercase; letter-spacing: 1px; }
    .odds-value { font-weight: bold; color: #4ade80; font-family: 'Courier New', monospace; font-size: 1.0rem; }

    .social-bets-container { 
        display: flex; flex-wrap: wrap; gap: 6px; justify-content: center;
        padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.05);
    }
    .bet-badge {
        display: inline-flex; align-items: center; gap: 6px;
        background: rgba(255,255,255,0.05); padding: 4px 8px; border-radius: 4px;
        font-size: 0.7rem; border: 1px solid rgba(255,255,255,0.05); color: #ccc;
    }
    .bet-badge.me { border: 1px solid rgba(59, 130, 246, 0.4); background: rgba(59, 130, 246, 0.1); color: #fff; }
    .bb-pick { font-weight: bold; color: #a5b4fc; text-transform: uppercase; }
    .bb-res-win { color: #4ade80; font-weight: bold; margin-left: 4px; }
    .bb-res-lose { color: #f87171; font-weight: bold; margin-left: 4px; }

    /* --- Dashboard & Status --- */
    .kpi-box { text-align: center; padding: 15px; background: rgba(255,255,255,0.02); border-radius: 8px; margin-bottom: 8px;}
    .kpi-label { font-size: 0.65rem; opacity: 0.5; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 4px;}
    .kpi-val { font-size: 2rem; font-weight: 800; font-family: 'Courier New', monospace; line-height: 1; }
    
    .rank-list-item { 
        display: flex; justify-content: space-between; padding: 12px 0; 
        border-bottom: 1px solid rgba(255,255,255,0.05); font-family: 'Courier New', monospace; font-size: 0.9rem;
    }
    .rank-pos { color: #fbbf24; font-weight: bold; margin-right: 12px; }
    .prof-amt { color: #4ade80; font-weight: bold; }

    .status-msg { text-align: center; opacity: 0.5; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; margin-top: 12px; }
    .bm-badge { background: #fbbf24; color: #000; padding: 2px 8px; border-radius: 4px; font-weight: 800; font-size: 0.65rem; text-transform: uppercase; letter-spacing: 1px; }

    /* --- Live Pulse --- */
    @keyframes pulse { 0% { opacity: 0.4; } 50% { opacity: 1; } 100% { opacity: 0.4; } }
    .live-dot { color: #f87171; animation: pulse 1.5s infinite; font-weight: bold; margin-right:4px; font-size: 1.2rem; line-height: 0; vertical-align: middle;}

    /* --- History --- */
    .hist-card { background: rgba(255,255,255,0.03); border-radius: 6px; padding: 12px; margin-bottom: 8px; border-left: 3px solid #444; }
    .h-win { border-left-color: #4ade80; }
    .h-lose { border-left-color: #f87171; }
    
    /* --- Budget Header --- */
    .budget-header {
        font-family: 'Courier New', monospace; text-align: center;
        margin-bottom: 20px; padding: 10px;
        background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05);
        border-radius: 8px; font-size: 0.9rem;
    }
    
    /* Clean up */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. Database & Config Access
# ==============================================================================
@st.cache_resource
def get_supabase():
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except: return None

supabase = get_supabase()

def fetch_all_data():
    """
    Fetch all tables safely and ENFORCE TYPES & SANITIZATION (SSOT 4.1).
    """
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

        bets = get_df_safe("bets", ['key','user','match_id','pick','stake','odds','result','gw','placed_at'])
        odds = get_df_safe("odds", ['match_id','home_win','draw','away_win'])
        results = get_df_safe("result", ['match_id','gw','home','away','utc_kickoff','status','home_score','away_score'])
        bm_log = get_df_safe("bm_log", ['gw','bookmaker'])
        users = get_df_safe("users", ['username','password','role','team'])
        config = get_df_safe("config", ['key','value'])
        
        # --- 1. Robust Type Enforcement (match_id) ---
        # Convert to string -> remove '.0' -> convert to int. This handles floats, ints, and strings.
        for df in [bets, results, odds]:
            if not df.empty and 'match_id' in df.columns:
                df.dropna(subset=['match_id'], inplace=True)
                df['match_id'] = df['match_id'].astype(str).str.replace(r'\.0$', '', regex=True).astype(int)

        # --- 2. String Sanitization (SSOT 4.1) ---
        # Remove whitespace and force uppercase to ensure matching
        if not bets.empty:
            bets['pick'] = bets['pick'].astype(str).str.strip().str.upper()
            bets['gw'] = bets['gw'].astype(str).str.strip().str.upper()
        
        if not results.empty:
            results['status'] = results['status'].astype(str).str.strip().str.upper()
            results['gw'] = results['gw'].astype(str).str.strip().str.upper()
            
        return bets, odds, results, bm_log, users, config
    except Exception as e:
        st.error(f"System Error: {e}")
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
# 2. Business Logic (Dynamic Settlement)
# ==============================================================================

def to_jst(iso_str):
    if not iso_str: return None
    try:
        dt = pd.to_datetime(iso_str)
        if dt.tz is None: dt = dt.tz_localize('UTC')
        return dt.tz_convert(JST)
    except: return None

def get_recent_form_html(team_name, results_df, current_kickoff_jst):
    """Generate Form Guide HTML (Old -> New)"""
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
    
    if past.empty: return '<span style="opacity:0.2">-</span>'

    past = past.iloc[::-1] # Reverse

    html_parts = ['<div class="form-container"><span class="form-arrow">OLD</span>']
    for _, g in past.iterrows():
        is_home = (g['home'] == team_name)
        ha_label = "H" if is_home else "A"
        h = int(g['home_score']) if pd.notna(g['home_score']) else 0
        a = int(g['away_score']) if pd.notna(g['away_score']) else 0
        
        icon = '<span style="color:#f87171">●</span>' 
        if h == a: icon = '<span style="color:#9ca3af">●</span>'
        elif (is_home and h > a) or (not is_home and a > h): icon = '<span style="color:#4ade80">●</span>'
        
        html_parts.append(f'<div class="form-item"><span class="form-ha">{ha_label}</span><span class="form-mark">{icon}</span></div>')
    
    html_parts.append('<span class="form-arrow">NEW</span></div>')
    return "".join(html_parts)

def determine_bet_outcome(bet_row, match_row):
    """
    Core Logic: Determine WIN/LOSE based on DB result OR Dynamic Match Status.
    Returns: 'WIN', 'LOSE', 'OPEN'
    """
    # 1. Trust DB Result if present
    db_res = str(bet_row.get('result', '')).strip().upper()
    if db_res in ['WIN', 'LOSE']:
        return db_res
    
    # 2. Dynamic Check: If match is FINISHED, calculate result
    status = str(match_row.get('status', 'SCHEDULED')).strip().upper()
    if status == 'FINISHED':
        h_s = int(match_row['home_score']) if pd.notna(match_row['home_score']) else 0
        a_s = int(match_row['away_score']) if pd.notna(match_row['away_score']) else 0
        
        outcome = "DRAW"
        if h_s > a_s: outcome = "HOME"
        elif a_s > h_s: outcome = "AWAY"
        
        # Safe Pick Comparison
        user_pick = str(bet_row['pick']).strip().upper()
        return 'WIN' if user_pick == outcome else 'LOSE'
        
    return 'OPEN'

def calculate_stats(bets_df, results_df, bm_log_df, users_df):
    """
    Calculate Total Stats with Dynamic Settlement.
    """
    if users_df.empty: return {}, {}
    stats = {u: {'balance': 0, 'wins': 0, 'total': 0, 'potential': 0} for u in users_df['username'].unique()}
    
    bm_map = {}
    if not bm_log_df.empty:
        for _, r in bm_log_df.iterrows():
            nums = "".join([c for c in str(r['gw']) if c.isdigit()])
            if nums: bm_map[f"GW{nums}"] = r['bookmaker']

    if bets_df.empty: return stats, bm_map

    # Merge bets with results for dynamic checking
    merged = pd.merge(bets_df, results_df[['match_id', 'status', 'home_score', 'away_score']], on='match_id', how='left')

    for _, b in merged.iterrows():
        user = b['user']
        if user not in stats: continue
        
        outcome = determine_bet_outcome(b, b) 
        stake = float(b['stake']) if b['stake'] else 0
        odds = float(b['odds']) if b['odds'] else 1.0
        
        nums = "".join([c for c in str(b['gw']) if c.isdigit()])
        gw_key = f"GW{nums}"
        bm = bm_map.get(gw_key)
        
        if outcome in ['WIN', 'LOSE']:
            stats[user]['total'] += 1
            pnl = (stake * odds) - stake if outcome == 'WIN' else -stake
            stats[user]['balance'] += int(pnl)
            
            if outcome == 'WIN': stats[user]['wins'] += 1
            if bm and bm in stats and bm != user: stats[bm]['balance'] -= int(pnl)
        else:
            stats[user]['potential'] += int((stake * odds) - stake)

    return stats, bm_map

def calculate_profitable_clubs(bets_df, results_df):
    """Top 3 Profitable Clubs (Dynamic)"""
    if bets_df.empty or results_df.empty: return {}
    
    merged = pd.merge(bets_df, results_df, on='match_id', how='inner')
    user_club_pnl = {} 
    
    for _, row in merged.iterrows():
        outcome = determine_bet_outcome(row, row)
        if outcome == 'WIN':
            user = row['user']
            pick = row['pick']
            team = row['home'] if pick == 'HOME' else (row['away'] if pick == 'AWAY' else None)
            
            if team:
                if user not in user_club_pnl: user_club_pnl[user] = {}
                profit = (float(row['stake']) * float(row['odds'])) - float(row['stake'])
                user_club_pnl[user][team] = user_club_pnl[user].get(team, 0) + int(profit)
            
    final_ranking = {}
    for u, clubs in user_club_pnl.items():
        sorted_clubs = sorted(clubs.items(), key=lambda x: x[1], reverse=True)[:3]
        final_ranking[u] = sorted_clubs
    return final_ranking

def calculate_live_leaderboard_data(bets_df, results_df, bm_map, users_df, target_gw):
    """
    Live P&L Logic: Total (Lifetime+Diff) vs Diff (GW specific)
    """
    base_stats, _ = calculate_stats(bets_df, results_df, pd.DataFrame(list(bm_map.items()), columns=['gw','bookmaker']), users_df)
    
    gw_total_pnl = {u: 0 for u in users_df['username'].unique()} 
    dream_profit = {u: 0 for u in users_df['username'].unique()}
    inplay_sim_only = {u: 0 for u in users_df['username'].unique()}

    gw_bets = bets_df[bets_df['gw'] == target_gw].copy() if not bets_df.empty else pd.DataFrame()
    
    if not gw_bets.empty:
        gw_bets = pd.merge(gw_bets, results_df[['match_id', 'status', 'home_score', 'away_score']], on='match_id', how='left')
        current_bm = bm_map.get(target_gw)

        for _, b in gw_bets.iterrows():
            user = b['user']
            if user not in base_stats: continue
            
            outcome = determine_bet_outcome(b, b)
            stake = float(b['stake'])
            odds = float(b['odds'])
            pot_win = (stake * odds) - stake
            
            dream_profit[user] += int(pot_win)
            
            pnl = 0
            is_inplay = False
            
            if outcome == 'WIN':
                pnl = pot_win
            elif outcome == 'LOSE':
                pnl = -stake
            else:
                status = b.get('status', 'SCHEDULED')
                if status not in ['SCHEDULED', 'TIMED', 'POSTPONED', 'FINISHED']:
                    h_sc = int(b['home_score']) if pd.notna(b['home_score']) else 0
                    a_sc = int(b['away_score']) if pd.notna(b['away_score']) else 0
                    curr_outcome = "DRAW"
                    if h_sc > a_sc: curr_outcome = "HOME"
                    elif a_sc > h_sc: curr_outcome = "AWAY"
                    
                    if b['pick'] == curr_outcome: pnl = pot_win
                    else: pnl = -stake
                    is_inplay = True
            
            gw_total_pnl[user] += int(pnl)
            if current_bm and current_bm in gw_total_pnl and current_bm != user:
                gw_total_pnl[current_bm] -= int(pnl)
            
            if is_inplay:
                inplay_sim_only[user] += int(pnl)
                if current_bm and current_bm in inplay_sim_only and current_bm != user:
                    inplay_sim_only[current_bm] -= int(pnl)

    live_data = []
    for u, s in base_stats.items():
        total_val = s['balance'] + inplay_sim_only.get(u, 0)
        diff_val = gw_total_pnl.get(u, 0)
        
        live_data.append({
            'User': u,
            'Total': total_val,
            'Diff': diff_val,
            'Dream': dream_profit.get(u, 0)
        })
        
    return pd.DataFrame(live_data).sort_values('Total', ascending=False)

def get_strict_target_gw(results_df):
    """Strict Future Mode"""
    if results_df.empty: return "GW1"
    now_jst = datetime.datetime.now(JST)
    if 'dt_jst' not in results_df.columns: results_df['dt_jst'] = results_df['utc_kickoff'].apply(to_jst)
    season_start = pd.Timestamp("2025-07-01", tz=JST)
    current_season = results_df[results_df['dt_jst'] >= season_start]
    if current_season.empty: return "GW1"
    future = current_season[current_season['dt_jst'] > (now_jst - timedelta(hours=4))].sort_values('dt_jst')
    if not future.empty: return future.iloc[0]['gw']
    past = current_season.sort_values('dt_jst', ascending=False)
    if not past.empty: return past.iloc[0]['gw']
    return "GW1"

def check_and_assign_bm(target_gw, bm_log_df, users_df):
    """Fairness Algorithm"""
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
            upserts.append({
                "match_id": m['id'], "gw": f"GW{m['matchday']}",
                "home": m['homeTeam']['name'], "away": m['awayTeam']['name'],
                "utc_kickoff": m['utcDate'], "status": m['status'],
                "home_score": m['score']['fullTime']['home'], "away_score": m['score']['fullTime']['away'],
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
    
    # --- 1. SYNC-FIRST ARCHITECTURE (SSOT 4.1) ---
    res_conf = supabase.table("config").select("*").execute()
    config = pd.DataFrame(res_conf.data) if res_conf.data else pd.DataFrame(columns=['key','value'])
    token = get_api_token(config)

    # Always sync on start
    if 'v48_synced' not in st.session_state:
        with st.spinner("Syncing..."): sync_api(token)
        st.session_state['v48_synced'] = True

    # --- 2. FETCH LATEST DATA (With Sanitization) ---
    bets, odds, results, bm_log, users, config = fetch_all_data()
    if users.empty: st.warning("User data missing."); st.stop()

    # Login Logic
    if 'user' not in st.session_state or not st.session_state['user']:
        st.markdown("<h2 style='text-align:center; opacity:0.8; letter-spacing:2px'>LOGIN</h2>", unsafe_allow_html=True)
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

    # 3. Setup Context
    target_gw = get_strict_target_gw(results)
    check_and_assign_bm(target_gw, bm_log, users)
    
    bm_log_refresh = supabase.table("bm_log").select("*").execute()
    bm_log = pd.DataFrame(bm_log_refresh.data) if bm_log_refresh.data else bm_log

    # 4. Global Stats Calculation (Dynamic)
    stats, bm_map = calculate_stats(bets, results, bm_log, users)
    
    nums = "".join([c for c in target_gw if c.isdigit()])
    current_bm = bm_map.get(f"GW{nums}", "Undecided")
    is_bm = (me == current_bm)
    lock_mins = get_config_value(config, "lock_minutes_before_earliest", 60)
    gw_locked = False
    
    budget_limit = get_config_value(config, "max_total_stake_per_gw", 20000)
    current_spend = 0
    if not bets.empty:
        my_gw_bets = bets[(bets['user'] == me) & (bets['gw'] == target_gw)]
        current_spend = int(my_gw_bets['stake'].sum()) if not my_gw_bets.empty else 0
    
    # Sidebar
    st.sidebar.markdown(f"## {me}")
    st.sidebar.caption(f"{st.session_state.get('team')}")
    my_stat = stats.get(me, {'balance':0})
    bal = my_stat['balance']
    col = "#4ade80" if bal >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:1.8rem; font-weight:800; color:{col}; font-family:monospace'>¥{bal:,}</div>", unsafe_allow_html=True)
    if st.sidebar.button("Logout"): st.session_state['user'] = None; st.rerun()

    t1, t2, t3, t4, t5 = st.tabs(["MATCHES", "LIVE", "HISTORY", "DASHBOARD", "ADMIN"])

    # --- TAB 1: MATCHES ---
    with t1:
        c_h1, c_h2 = st.columns([3, 1])
        c_h1.markdown(f"### {target_gw}")
        if is_bm: c_h2.markdown(f"<span class='bm-badge'>YOU ARE BM</span>", unsafe_allow_html=True)
        else: c_h2.markdown(f"<span class='bm-badge'>BM: {current_bm}</span>", unsafe_allow_html=True)
        
        b_col = "#4ade80" if current_spend <= budget_limit else "#f87171"
        st.markdown(f"""<div class="budget-header">USED: <span style="color:{b_col}">¥{current_spend:,}</span> / LIMIT: ¥{budget_limit:,}</div>""", unsafe_allow_html=True)

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
                        st.info(f"🔒 LOCKED (Starts: {first_ko.strftime('%H:%M')})")

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
                    
                    h_s = int(m['home_score']) if pd.notna(m['home_score']) else 0
                    a_s = int(m['away_score']) if pd.notna(m['away_score']) else 0
                    score_disp = f"{h_s}-{a_s}" if m['status'] != 'SCHEDULED' else "vs"

                    card_html = f"""<div class="app-card-top"><div class="card-header"><span>⏱ {dt_str}</span><span>{m['status']}</span></div><div class="matchup-flex"><div class="team-col"><span class="team-name">{m['home']}</span>{form_h}</div><div class="score-col"><span class="score-box">{score_disp}</span></div><div class="team-col"><span class="team-name">{m['away']}</span>{form_a}</div></div><div class="info-row"><div class="odds-label">HOME <span class="odds-value">{oh if oh else '-'}</span></div><div class="odds-label">DRAW <span class="odds-value">{od if od else '-'}</span></div><div class="odds-label">AWAY <span class="odds-value">{oa if oa else '-'}</span></div></div>"""
                    
                    if not match_bets.empty:
                        badges = ""
                        for _, b in match_bets.iterrows():
                            me_cls = "me" if b['user'] == me else ""
                            pick_txt = b['pick'][:4]
                            pnl_span = ""
                            outcome = determine_bet_outcome(b, m)
                            if outcome == 'WIN':
                                b_win = (float(b['stake']) * float(b['odds'])) - float(b['stake'])
                                pnl_span = f"<span class='bb-res-win'>+¥{int(b_win):,}</span>"
                            elif outcome == 'LOSE':
                                b_pnl = -float(b['stake'])
                                pnl_span = f"<span class='bb-res-lose'>-¥{int(abs(b_pnl)):,}</span>"
                            badges += f"""<div class="bet-badge {me_cls}"><span>{b['user']}:</span><span class="bb-pick">{pick_txt}</span> (¥{int(b['stake']):,}){pnl_span}</div>"""
                        card_html += f"""<div class="social-bets-container">{badges}</div>"""
                    card_html += "</div>"
                    st.markdown(card_html, unsafe_allow_html=True)

                    is_open = m['status'] not in ['IN_PLAY', 'FINISHED', 'PAUSED'] and oh > 0 and not gw_locked
                    if not is_open:
                        msg = "CLOSED"
                        if oh == 0: msg = "WAITING ODDS"
                        elif gw_locked: msg = "LOCKED"
                        st.markdown(f"<div class='status-msg'>{msg}</div><div style='margin-bottom:16px'></div>", unsafe_allow_html=True)
                    elif is_bm: st.markdown("<div style='margin-bottom:16px'></div>", unsafe_allow_html=True)
                    else:
                        with st.form(key=f"bf_{mid}"):
                            c_p, c_s, c_b = st.columns([3, 2, 2])
                            cur_p = my_bet.iloc[0]['pick'] if not my_bet.empty else "HOME"
                            cur_s = int(my_bet.iloc[0]['stake']) if not my_bet.empty else 1000
                            pick = c_p.selectbox("Pick", ["HOME", "DRAW", "AWAY"], index=["HOME", "DRAW", "AWAY"].index(cur_p), label_visibility="collapsed")
                            stake = c_s.number_input("Stake", 100, 20000, cur_s, 100, label_visibility="collapsed")
                            
                            new_total = current_spend - (int(my_bet.iloc[0]['stake']) if not my_bet.empty else 0) + stake
                            over_budget = new_total > budget_limit
                            
                            if c_b.form_submit_button("BET", use_container_width=True):
                                if over_budget: st.error(f"Over Budget! Limit: ¥{budget_limit:,}")
                                else:
                                    to = oh if pick=="HOME" else (od if pick=="DRAW" else oa)
                                    pl = {"key": f"{m['gw']}:{me}:{mid}", "gw": m['gw'], "user": me, "match_id": mid, "match": f"{m['home']} vs {m['away']}", "pick": pick, "stake": stake, "odds": to, "placed_at": datetime.datetime.now(JST).isoformat(), "status": "OPEN", "result": ""}
                                    supabase.table("bets").upsert(pl).execute()
                                    st.toast("Saved!", icon="✅"); time.sleep(1); st.rerun()
            else: st.info(f"No matches for {target_gw}")
        else: st.info("Loading...")

    # --- TAB 2: LIVE ---
    with t2:
        st.markdown(f"### ⚡ LIVE: {target_gw}")
        if st.button("🔄 REFRESH", use_container_width=True): sync_api(token); st.rerun()
        
        live_df = calculate_live_leaderboard_data(bets, results, bm_map, users, target_gw)
        
        st.markdown("#### LEADERBOARD")
        if not live_df.empty:
            rank = 1
            for _, r in live_df.iterrows():
                diff = r['Diff']
                diff_str = f"+¥{diff:,}" if diff > 0 else (f"¥{diff:,}" if diff < 0 else "-")
                col = "#4ade80" if diff > 0 else ("#f87171" if diff < 0 else "#666")
                dream_val = r['Dream']
                st.markdown(f"""<div style="display:flex; flex-direction:column; padding:12px; background:rgba(255,255,255,0.03); margin-bottom:8px; border-radius:6px;"><div style="display:flex; justify-content:space-between; align-items:center;"><div style="font-weight:bold; font-size:1.1rem; color:#fbbf24; width:30px">#{rank}</div><div style="flex:1; font-weight:bold;">{r['User']}</div><div style="text-align:right;"><div style="font-weight:bold; font-family:monospace">¥{int(r['Total']):,}</div><div style="font-size:0.8rem; color:{col}; font-family:monospace">({diff_str})</div></div></div><div style="text-align:right; font-size:0.7rem; opacity:0.6; margin-top:4px;">THEORETICAL GW PROFIT: <span style="color:#a5b4fc">¥{int(dream_val):,}</span></div></div>""", unsafe_allow_html=True)
                rank += 1
        
        st.markdown("#### SCOREBOARD")
        if not results.empty:
            lm = results[results['gw'] == target_gw].copy()
            lm['dt_jst'] = lm['utc_kickoff'].apply(to_jst)
            lm = lm.sort_values('dt_jst')
            for _, m in lm.iterrows():
                sts_disp = m['status']
                if m['status'] in ['IN_PLAY', 'PAUSED']: sts_disp = f"<span class='live-dot'>●</span> {m['status']}"
                mb = bets[bets['match_id'] == m['match_id']] if not bets.empty else pd.DataFrame()
                stake_str = ""
                if not mb.empty:
                    parts = []
                    for _, b in mb.iterrows(): parts.append(f"{b['user']}:{b['pick'][0]}")
                    stake_str = " ".join(parts)
                st.markdown(f"""<div style="padding:15px; background:rgba(255,255,255,0.02); margin-bottom:10px; border-radius:8px; border:1px solid rgba(255,255,255,0.05)"><div style="display:flex; justify-content:space-between; align-items:center;"><div style="flex:1; text-align:right; font-size:0.9rem; opacity:0.8">{m['home']}</div><div style="padding:0 15px; font-weight:800; font-family:monospace; font-size:1.4rem">{int(m['home_score']) if pd.notna(m['home_score']) else 0}-{int(m['away_score']) if pd.notna(m['away_score']) else 0}</div><div style="flex:1; font-size:0.9rem; opacity:0.8">{m['away']}</div></div><div style="display:flex; justify-content:space-between; margin-top:8px; font-size:0.75rem; opacity:0.6; text-transform:uppercase"><span>{sts_disp}</span><span>{stake_str}</span></div></div>""", unsafe_allow_html=True)

    # --- TAB 3: HISTORY ---
    with t3:
        if not bets.empty:
            c1, c2 = st.columns(2)
            sel_u = c1.selectbox("User", ["All"] + list(users['username'].unique()))
            sel_g = c2.selectbox("GW", ["All"] + sorted(list(bets['gw'].unique()), key=lambda x: int("".join([c for c in str(x) if c.isdigit()] or 0)), reverse=True))
            hist = bets.copy()
            if sel_u != "All": hist = hist[hist['user'] == sel_u]
            if sel_g != "All": hist = hist[hist['gw'] == sel_g]
            
            # Join for names and dynamic settlement
            hist = pd.merge(hist, results[['match_id', 'home', 'away', 'status', 'home_score', 'away_score']], on='match_id', how='left')
            hist['dt_jst'] = hist['placed_at'].apply(to_jst)
            hist = hist.sort_values('dt_jst', ascending=False)
            
            for _, b in hist.iterrows():
                outcome = determine_bet_outcome(b, b)
                cls = "h-win" if outcome == 'WIN' else ("h-lose" if outcome == 'LOSE' else "")
                pnl = "PENDING"
                col = "#aaa"
                if outcome == 'WIN':
                    val = (b['stake']*b['odds'])-b['stake']
                    pnl = f"+¥{int(val):,}"
                    col = "#4ade80"
                elif outcome == 'LOSE':
                    pnl = f"-¥{int(b['stake']):,}"
                    col = "#f87171"
                
                match_name = f"{b['home']} vs {b['away']}" if pd.notna(b['home']) else b.get('match', 'Unknown')
                st.markdown(f"""<div class="hist-card {cls}"><div style="display:flex; justify-content:space-between; font-size:0.75rem; opacity:0.6; margin-bottom:4px; text-transform:uppercase; font-family:'Courier New', monospace"><span>{b['user']} | {b['gw']}</span><span style="color:{col}; font-weight:bold;">{pnl}</span></div><div style="font-weight:bold; font-size:0.95rem; margin-bottom:4px">{match_name}</div><div style="font-size:0.8rem; opacity:0.8"><span style="color:#a5b4fc; font-weight:bold">{b['pick']}</span> <span style="opacity:0.6">(@{b['odds']})</span><span style="margin-left:8px; font-family:monospace">¥{int(b['stake']):,}</span></div></div>""", unsafe_allow_html=True)
        else: st.info("No history.")

    # --- TAB 4: DASHBOARD ---
    with t4:
        st.markdown("### 🏆 DASHBOARD")
        my_s = stats.get(me, {'balance':0, 'wins':0, 'total':0})
        win_rate = (my_s['wins']/my_s['total']*100) if my_s['total'] else 0
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>WIN RATE</div><div class='kpi-val'>{win_rate:.1f}%</div></div>", unsafe_allow_html=True)
        with c2: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>PROFIT</div><div class='kpi-val'>¥{my_s['balance']:,}</div></div>", unsafe_allow_html=True)
        with c3: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>GW</div><div class='kpi-val'>{target_gw}</div></div>", unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown("#### 💰 PROFITABLE CLUBS")
        prof_data = calculate_profitable_clubs(bets, results)
        if prof_data:
            c_cols = st.columns(len(prof_data))
            for i, (u, clubs) in enumerate(prof_data.items()):
                with c_cols[i]:
                    st.markdown(f"**{u}**")
                    if clubs:
                        for j, (team, amt) in enumerate(clubs): st.markdown(f"<div class='rank-list-item'><span class='rank-pos'>{j+1}.</span> <span style='flex:1'>{team}</span> <span class='prof-amt'>+¥{amt:,}</span></div>", unsafe_allow_html=True)
                    else: st.caption("No wins yet.")
        else: st.info("No data.")

        st.markdown("---")
        st.markdown("#### ⚖️ BM STATS")
        if not bm_log.empty:
            bm_counts = bm_log['bookmaker'].value_counts().reset_index()
            bm_counts.columns = ['User', 'Count']
            for _, r in bm_counts.iterrows(): st.markdown(f"<div class='rank-list-item'><span style='flex:1'>{r['User']}</span> <span style='font-weight:bold'>{r['Count']} times</span></div>", unsafe_allow_html=True)

    # --- TAB 5: ADMIN ---
    with t5:
        if role == 'admin':
            st.markdown("#### SYSTEM HEALTH")
            b_count = len(bets)
            r_count = len(results)
            # Debug Stats
            merged_debug = pd.merge(bets, results, on='match_id', how='inner')
            m_count = len(merged_debug)
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Bets", b_count)
            c2.metric("Merged Bets", m_count)
            c3.metric("Pending (Merged)", len(merged_debug[merged_debug['status'] != 'FINISHED']))
            
            if m_count < b_count:
                st.error(f"CRITICAL: {b_count - m_count} bets failed to merge with results! Check Match IDs.")
                
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
            with st.expander("👑 BM Manual Override"):
                 with st.form("bm_manual"):
                    t_gw = st.selectbox("GW", sorted(results['gw'].unique()) if not results.empty else ["GW1"])
                    t_u = st.selectbox("User", users['username'].tolist())
                    if st.form_submit_button("Assign"):
                        supabase.table("bm_log").upsert({"gw": t_gw, "bookmaker": t_u}).execute()
                        st.success("Assigned"); time.sleep(1); st.rerun()

if __name__ == "__main__":
    main()
