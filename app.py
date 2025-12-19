import streamlit as st
import pandas as pd
import requests
import datetime
import time
import pytz
from datetime import timedelta
from supabase import create_client

# ==============================================================================
# 0. System Configuration & CSS (Mobile First & Wide)
# ==============================================================================
st.set_page_config(page_title="Football App V3.5", layout="wide", page_icon="⚽")
JST = pytz.timezone('Asia/Tokyo')

st.markdown("""
<style>
/* --- Layout: Full Width for Mobile --- */
.block-container {
    padding-top: 3.5rem;
    padding-bottom: 5rem;
    max-width: 100%;
    padding-left: 0.5rem;
    padding-right: 0.5rem;
}

/* --- Card Visual Integration Strategy --- */
/* Top part (HTML) */
.app-card-top {
    border: 1px solid rgba(255,255,255,0.1);
    border-bottom: none; /* Connect to bottom */
    border-radius: 12px 12px 0 0;
    padding: 16px 16px 8px 16px;
    background: linear-gradient(145deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%);
    margin-bottom: 0px; /* Attach to form */
}

/* Bottom part (Form) - Targeting Streamlit Form container */
[data-testid="stForm"] {
    border: 1px solid rgba(255,255,255,0.1);
    border-top: none; /* Connect to top */
    border-radius: 0 0 12px 12px;
    padding: 10px 16px 16px 16px;
    background: linear-gradient(145deg, rgba(255,255,255,0.02) 0%, rgba(255,255,255,0.01) 100%);
    margin-top: 0px;
    margin-bottom: 16px; /* Space between cards */
}

/* --- Header Section (Time | Status) --- */
.card-header {
    display: flex;
    justify-content: space-between;
    font-family: monospace;
    font-size: 0.85rem;
    color: #a5b4fc;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    padding-bottom: 8px;
    margin-bottom: 12px;
}

/* --- Matchup Section --- */
.matchup-grid {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    text-align: center;
    gap: 8px;
    margin-bottom: 12px;
}
.team-col {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
}
.team-name {
    font-weight: bold;
    font-size: 1.0rem;
    line-height: 1.2;
    min-height: 2.4em;
    display: flex;
    align-items: center;
    justify-content: center;
}
.score-box {
    font-size: 1.4rem;
    font-weight: 800;
    color: #fff;
    background: rgba(0,0,0,0.3);
    padding: 4px 10px;
    border-radius: 8px;
}

/* --- Form Guide (H/A + Icon) --- */
.form-box { display: flex; gap: 4px; justify-content: center; margin-top: 6px; }
.form-item { display: flex; flex-direction: column; align-items: center; line-height: 1; }
.form-ha { font-size: 0.6rem; color: #888; font-weight: bold; margin-bottom: 2px; }
.form-icon { font-size: 0.9rem; }

/* --- Info Row (Odds) --- */
.info-row {
    display: flex;
    justify-content: space-around;
    background: rgba(255,255,255,0.03);
    padding: 8px;
    border-radius: 8px;
    font-size: 0.9rem;
    margin-bottom: 8px;
}
.odds-item { text-align: center; }
.odds-label { font-size: 0.65rem; color: #888; }
.odds-value { font-weight: bold; color: #4ade80; }

/* --- Social Bets --- */
.social-bets-container { 
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: center;
    padding-top: 8px;
    border-top: 1px solid rgba(255,255,255,0.05);
}
.bet-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(255,255,255,0.05);
    padding: 4px 8px;
    border-radius: 6px;
    font-size: 0.75rem;
    color: #ddd;
    border: 1px solid rgba(255,255,255,0.1);
}
.bet-badge.me {
    background: rgba(59, 130, 246, 0.15);
    border: 1px solid #3b82f6;
    color: #fff;
}
.bb-pick { font-weight: bold; color: #a5b4fc; }

/* --- Live Leaderboard --- */
.rank-row {
    display: flex; justify-content: space-between; padding: 12px;
    background: rgba(255,255,255,0.03); border-radius: 8px; margin-bottom: 8px;
    align-items: center;
}
.rank-pos { font-size: 1.2rem; font-weight: bold; color: #fbbf24; width: 30px; }
.rank-bal { font-weight: bold; font-size: 1.1rem; }
.rank-diff { font-size: 0.85rem; margin-left: 8px; }
.diff-plus { color: #4ade80; }
.diff-minus { color: #f87171; }

/* --- History Cards --- */
.hist-card {
    background: rgba(255,255,255,0.03); border-radius: 8px; padding: 12px; margin-bottom: 8px;
    border-left: 4px solid #555;
}
.h-win { border-left-color: #4ade80; background: rgba(74, 222, 128, 0.05); }
.h-lose { border-left-color: #f87171; background: rgba(248, 113, 113, 0.05); }

/* --- Utils --- */
.bm-badge {
    background: #fbbf24; color: #000; padding: 3px 10px; border-radius: 99px;
    font-weight: bold; font-size: 0.75rem; display: inline-block;
}
.status-msg { text-align: center; color: #666; font-size: 0.8rem; margin-top: 8px; }
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
    """Fetch all tables safely with schema validation"""
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
    token = st.secrets.get("api_token")
    if token: return token
    if not config_df.empty:
        row = config_df[config_df['key'] == 'FOOTBALL_DATA_API_TOKEN']
        if not row.empty: return row.iloc[0]['value']
    return ""

# ==============================================================================
# 2. Business Logic
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
    Generate HTML (H/A + Icon) as a SINGLE line string to prevent Streamlit rendering bug.
    NO INDENTATION ALLOWED IN HTML STRING.
    """
    if results_df.empty: return "-"
    
    if 'dt_jst' not in results_df.columns:
        results_df['dt_jst'] = results_df['utc_kickoff'].apply(to_jst)
    
    # Filter: 2025 Season + Finished + Past
    season_start = pd.Timestamp("2025-07-01", tz=JST)
    past = results_df[
        (results_df['dt_jst'] >= season_start) &
        (results_df['status'] == 'FINISHED') & 
        (results_df['dt_jst'] < current_kickoff_jst) &
        ((results_df['home'] == team_name) | (results_df['away'] == team_name))
    ].sort_values('dt_jst', ascending=False).head(5)
    
    if past.empty: return '<span style="color:#666">-</span>'

    # Build HTML as a single concatenated string
    html_parts = ['<div class="form-box">']
    for _, g in past.iterrows():
        is_home = (g['home'] == team_name)
        ha_label = "H" if is_home else "A"
        h = int(g['home_score']) if pd.notna(g['home_score']) else 0
        a = int(g['away_score']) if pd.notna(g['away_score']) else 0
        
        icon = '❌'
        if h == a:
            icon = '<span style="color:#ccc; text-shadow:0 0 1px #000">▲</span>'
        elif (is_home and h > a) or (not is_home and a > h):
            icon = '🔵'
        
        # Single line append
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
            pnl = 0
            if res == 'WIN':
                stats[user]['wins'] += 1
                pnl = (stake * odds) - stake
            else:
                pnl = -stake
            
            stats[user]['balance'] += int(pnl)
            if bm and bm in stats and bm != user:
                stats[bm]['balance'] -= int(pnl)
        else:
            pot = (stake * odds) - stake
            stats[user]['potential'] += int(pot)

    return stats, bm_map

def calculate_live_pnl(bets_df, results_df, bm_map, users_df, target_gw):
    """Real-time P&L including provisional results of active matches"""
    base_stats, _ = calculate_stats(bets_df, pd.DataFrame(list(bm_map.items()), columns=['gw','bookmaker']), users_df)
    live_data = []

    if bets_df.empty or results_df.empty:
        for u, s in base_stats.items():
            live_data.append({'User': u, 'Total': s['balance'], 'LiveDiff': 0})
        return pd.DataFrame(live_data).sort_values('Total', ascending=False)

    target_bets = bets_df[
        (bets_df['gw'] == target_gw) & 
        (bets_df['status'] == 'OPEN')
    ].copy()
    
    sim_pnl = {u: 0 for u in users_df['username'].unique()}
    current_bm = bm_map.get(target_gw)
    
    for _, b in target_bets.iterrows():
        mid = b['match_id']
        m_row = results_df[results_df['match_id'] == mid]
        if m_row.empty: continue
        
        m = m_row.iloc[0]
        # Simulate only if match has started (IN_PLAY, PAUSED, FINISHED but not in DB)
        if m['status'] not in ['SCHEDULED', 'TIMED', 'POSTPONED']:
            h_sc = int(m['home_score']) if pd.notna(m['home_score']) else 0
            a_sc = int(m['away_score']) if pd.notna(m['away_score']) else 0
            
            outcome = "DRAW"
            if h_sc > a_sc: outcome = "HOME"
            elif a_sc > h_sc: outcome = "AWAY"
            
            pnl = 0
            if b['pick'] == outcome:
                pnl = (float(b['stake']) * float(b['odds'])) - float(b['stake'])
            else:
                pnl = -float(b['stake'])
            
            sim_pnl[b['user']] += int(pnl)
            if current_bm and current_bm in sim_pnl and current_bm != b['user']:
                sim_pnl[current_bm] -= int(pnl)

    for u, s in base_stats.items():
        live_data.append({
            'User': u,
            'Total': s['balance'] + sim_pnl.get(u, 0),
            'LiveDiff': sim_pnl.get(u, 0)
        })
        
    return pd.DataFrame(live_data).sort_values('Total', ascending=False)

def get_strict_target_gw(results_df):
    """
    Strict Future Mode with Season Filter (>= 2025-07-01).
    """
    if results_df.empty: return "GW1"
    
    now_jst = datetime.datetime.now(JST)
    if 'dt_jst' not in results_df.columns:
        results_df['dt_jst'] = results_df['utc_kickoff'].apply(to_jst)
    
    # Season Filter (2025 Only)
    season_start = pd.Timestamp("2025-07-01", tz=JST)
    current_season_matches = results_df[results_df['dt_jst'] >= season_start]
    
    if current_season_matches.empty: return "GW1"

    # Future Logic
    future_matches = current_season_matches[
        current_season_matches['dt_jst'] > (now_jst - timedelta(hours=4))
    ].sort_values('dt_jst')
    
    if not future_matches.empty:
        return future_matches.iloc[0]['gw']
    
    past = current_season_matches.sort_values('dt_jst', ascending=False)
    if not past.empty:
        return past.iloc[0]['gw']
        
    return "GW1"

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
        st.markdown("## 🔐 Login")
        u = st.selectbox("User", users['username'].tolist())
        p = st.text_input("Pass", type="password")
        if st.button("Enter"):
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
    if 'v35_synced' not in st.session_state:
        with st.spinner("🚀 Syncing Season 2025..."):
            sync_api(token)
        st.session_state['v35_synced'] = True
        st.rerun()

    # Logic
    target_gw = get_strict_target_gw(results)
    stats, bm_map = calculate_stats(bets, bm_log, users)
    
    nums = "".join([c for c in target_gw if c.isdigit()])
    current_bm = bm_map.get(f"GW{nums}", "Undecided")
    is_bm = (me == current_bm)

    # Sidebar
    st.sidebar.markdown(f"## 👤 {me}")
    my_stat = stats.get(me, {'balance':0})
    bal = my_stat['balance']
    col = "#4ade80" if bal >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:1.8rem; font-weight:800; color:{col}'>¥{bal:,}</div>", unsafe_allow_html=True)
    if st.sidebar.button("Logout"): st.session_state['user'] = None; st.rerun()

    # Tabs
    t1, t2, t3, t4, t5 = st.tabs(["⚽ Matches", "⚡ Live", "📜 History", "🏆 Standings", "🛠 Admin"])

    # --- TAB 1: Matches (Vertical Tile & Visual Integration) ---
    with t1:
        st.markdown(f"### {target_gw} Fixtures")
        if is_bm: st.markdown(f"<span class='bm-badge'>👑 You are BM</span>", unsafe_allow_html=True)
        else: st.markdown(f"<span class='bm-badge'>BM: {current_bm}</span>", unsafe_allow_html=True)

        if not results.empty:
            matches = results[results['gw'] == target_gw].copy()
            if not matches.empty:
                matches['dt_jst'] = matches['utc_kickoff'].apply(to_jst)
                # Filter 2025 Season again
                season_start = pd.Timestamp("2025-07-01", tz=JST)
                matches = matches[matches['dt_jst'] >= season_start].sort_values('dt_jst')
                
                for _, m in matches.iterrows():
                    mid = m['match_id']
                    dt_str = m['dt_jst'].strftime('%m/%d %H:%M')
                    
                    # Data
                    o_row = odds[odds['match_id'] == mid]
                    oh = o_row.iloc[0]['home_win'] if not o_row.empty else 0
                    od = o_row.iloc[0]['draw'] if not o_row.empty else 0
                    oa = o_row.iloc[0]['away_win'] if not o_row.empty else 0
                    
                    form_h = get_recent_form_html(m['home'], results, m['dt_jst'])
                    form_a = get_recent_form_html(m['away'], results, m['dt_jst'])
                    
                    match_bets = bets[bets['match_id'] == mid] if not bets.empty else pd.DataFrame()
                    my_bet = match_bets[match_bets['user'] == me] if not match_bets.empty else pd.DataFrame()
                    
                    h_score = int(m['home_score']) if pd.notna(m['home_score']) else 0
                    a_score = int(m['away_score']) if pd.notna(m['away_score']) else 0
                    score_disp = f"{h_score} - {a_score}" if m['status'] != 'SCHEDULED' else "vs"

                    # --- Render Top Part (HTML) ---
                    # IMPORTANT: NO indentation inside the HTML string to avoid Streamlit parsing it as code blocks.
                    card_html = f"""<div class="app-card-top"><div class="card-header"><span>⏱ {dt_str}</span><span>{m['status']}</span></div><div class="matchup-grid"><div class="team-col"><span class="team-name">{m['home']}</span>{form_h}</div><div class="team-col"><span class="score-box">{score_disp}</span></div><div class="team-col"><span class="team-name">{m['away']}</span>{form_a}</div></div><div class="info-row"><div class="odds-item"><div class="odds-label">HOME</div><div class="odds-value">{oh if oh else '-'}</div></div><div class="odds-item"><div class="odds-label">DRAW</div><div class="odds-value">{od if od else '-'}</div></div><div class="odds-item"><div class="odds-label">AWAY</div><div class="odds-value">{oa if oa else '-'}</div></div></div>"""
                    
                    # Add Social Bets
                    if not match_bets.empty:
                        badges = ""
                        for _, b in match_bets.iterrows():
                            me_cls = "me" if b['user'] == me else ""
                            badges += f"""<div class="bet-badge {me_cls}"><span>{b['user']}</span><span class="bb-pick">{b['pick']}</span><span>¥{int(b['stake']):,}</span></div>"""
                        card_html += f"""<div class="social-bets-container">{badges}</div>"""
                    
                    # Close HTML card div
                    card_html += "</div>"
                    st.markdown(card_html, unsafe_allow_html=True)

                    # --- Render Bottom Part (Form) ---
                    is_open = m['status'] not in ['IN_PLAY', 'FINISHED', 'PAUSED'] and oh > 0
                    
                    if not is_open:
                        # Just a visual closure if closed
                        st.markdown(f"<div class='status-msg'>Betting Closed</div>", unsafe_allow_html=True)
                        st.markdown("<div style='margin-bottom:16px'></div>", unsafe_allow_html=True) # Spacer
                    elif is_bm:
                        # Just a visual closure if BM
                         st.markdown("<div style='margin-bottom:16px'></div>", unsafe_allow_html=True)
                    else:
                        # The Form (CSS will style it to look attached to top)
                        with st.form(key=f"bf_{mid}"):
                            c_p, c_s, c_b = st.columns([3, 2, 2])
                            cur_p = my_bet.iloc[0]['pick'] if not my_bet.empty else "HOME"
                            cur_s = int(my_bet.iloc[0]['stake']) if not my_bet.empty else 1000
                            
                            opts = ["HOME", "DRAW", "AWAY"]
                            pick = c_p.selectbox("Pick", opts, index=opts.index(cur_p), label_visibility="collapsed")
                            stake = c_s.number_input("Stake", 100, 20000, cur_s, 100, label_visibility="collapsed")
                            
                            if c_b.form_submit_button("Update" if not my_bet.empty else "BET", use_container_width=True):
                                to = oh if pick=="HOME" else (od if pick=="DRAW" else oa)
                                pl = {
                                    "key": f"{m['gw']}:{me}:{mid}", "gw": m['gw'], "user": me, "match_id": mid,
                                    "match": f"{m['home']} vs {m['away']}", "pick": pick, "stake": stake, "odds": to,
                                    "placed_at": datetime.datetime.now(JST).isoformat(), "status": "OPEN", "result": ""
                                }
                                supabase.table("bets").upsert(pl).execute()
                                st.toast("Saved!", icon="✅"); time.sleep(1); st.rerun()

            else: st.info(f"No matches found for {target_gw}.")
        else: st.info("Loading...")

    # --- TAB 2: Live ---
    with t2:
        st.markdown(f"### ⚡ Live: {target_gw}")
        if st.button("🔄 Refresh"):
            sync_api(token); st.rerun()
            
        live_df = calculate_live_pnl(bets, results, bm_map, users, target_gw)
        
        st.markdown("#### Live Leaderboard")
        if not live_df.empty:
            for i, r in live_df.iterrows():
                diff = r['LiveDiff']
                diff_str = f"+¥{diff:,}" if diff > 0 else (f"¥{diff:,}" if diff < 0 else "-")
                d_cls = "diff-plus" if diff > 0 else ("diff-minus" if diff < 0 else "")
                
                st.markdown(f"""
                <div class="rank-row">
                    <div class="rank-pos">{i+1}</div>
                    <div style="flex:1; margin-left:12px; font-weight:bold;">{r['User']}</div>
                    <div style="text-align:right;">
                        <div class="rank-bal">¥{int(r['Total']):,}</div>
                        <div class="rank-diff {d_cls}">({diff_str})</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

    # --- TAB 3: History ---
    with t3:
        if not bets.empty:
            c1, c2 = st.columns(2)
            u_list = ["All"] + list(users['username'].unique())
            sel_u = c1.selectbox("User", u_list)
            
            gw_list = ["All"] + sorted(list(bets['gw'].unique()), key=lambda x: int("".join([c for c in str(x) if c.isdigit()] or 0)), reverse=True)
            sel_g = c2.selectbox("GW", gw_list)
            
            hist = bets.copy()
            if sel_u != "All": hist = hist[hist['user'] == sel_u]
            if sel_g != "All": hist = hist[hist['gw'] == sel_g]
            
            hist['dt_jst'] = hist['placed_at'].apply(to_jst)
            hist = hist.sort_values('dt_jst', ascending=False)
            
            for _, b in hist.iterrows():
                res = b['result'] if b['result'] else "PENDING"
                cls = "h-win" if res == 'WIN' else ("h-lose" if res == 'LOSE' else "")
                pnl = f"+¥{int((b['stake']*b['odds'])-b['stake']):,}" if res == 'WIN' else (f"-¥{int(b['stake']):,}" if res=='LOSE' else "PENDING")
                col = "#fff" if res=='WIN' else ("#f87171" if res=='LOSE' else "#aaa")
                
                st.markdown(f"""
                <div class="hist-card {cls}">
                    <div style="display:flex; justify-content:space-between; font-size:0.8rem; color:#aaa; margin-bottom:4px">
                        <span>{b['user']} | {b['gw']}</span>
                        <span style="color:{col}; font-weight:bold">{pnl}</span>
                    </div>
                    <div style="font-weight:bold; font-size:1rem">{b['match']}</div>
                    <div style="margin-top:4px; font-size:0.85rem">
                        <span style="color:#a5b4fc">{b['pick']}</span> 
                        <span style="color:#888">(@{b['odds']})</span>
                        <span style="margin-left:8px; font-family:monospace">¥{int(b['stake']):,}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else: st.info("No history.")

    # --- TAB 4: Standings ---
    with t4:
        ranking = []
        for u, s in stats.items():
            ranking.append({'User': u, 'Balance': s['balance'], 'Wins': s['wins']})
        st.dataframe(pd.DataFrame(ranking).sort_values('Balance', ascending=False), use_container_width=True, hide_index=True)

    # --- TAB 5: Admin ---
    with t5:
        if role == 'admin':
            if st.button("Force Reset"):
                supabase.table("result").delete().neq("match_id", -1).execute()
                sync_api(token)
                st.success("Done"); time.sleep(1); st.rerun()

if __name__ == "__main__":
    main()
