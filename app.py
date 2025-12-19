import streamlit as st
import pandas as pd
import requests
import datetime
import time
import pytz
from datetime import timedelta
from supabase import create_client

# ==============================================================================
# 0. System Configuration & CSS (Mobile First)
# ==============================================================================
st.set_page_config(page_title="Football App V3.2", layout="wide", page_icon="⚽")
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

/* --- Form Guide (H/A + Icon) --- */
.form-box { display: flex; gap: 4px; justify-content: center; margin-top: 4px; }
.form-item { display: flex; flex-direction: column; align-items: center; line-height: 1; }
.form-ha { font-size: 0.55rem; color: #888; margin-bottom: 2px; font-weight: bold; }
.form-icon { font-size: 0.9rem; }
.f-win { color: #4ade80; } /* 🔵 fallback color */
.f-lose { color: #f87171; } /* ❌ fallback color */
.f-draw { color: #ddd; }   /* ▲ fallback color */

/* --- Social Bet Badges --- */
.social-bets-container { 
    display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; 
    padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.1); 
}
.bet-badge {
    display: inline-flex; align-items: center; gap: 6px;
    background: rgba(255,255,255,0.05); padding: 4px 10px; border-radius: 6px;
    font-size: 0.75rem; color: #ddd; border: 1px solid rgba(255,255,255,0.05);
}
.bet-badge.me {
    background: rgba(59, 130, 246, 0.15); border: 1px solid #3b82f6; color: #fff;
}
.bb-pick { font-weight: bold; color: #a5b4fc; }
.bb-stake { font-family: monospace; color: #aaa; }

/* --- History Cards --- */
.hist-card {
    background: rgba(255,255,255,0.03); border-radius: 8px; padding: 12px; margin-bottom: 8px;
    border-left: 4px solid #555;
}
.h-win { border-left-color: #4ade80; background: rgba(74, 222, 128, 0.05); }
.h-lose { border-left-color: #f87171; background: rgba(248, 113, 113, 0.05); }

/* --- Typography & Utils --- */
.match-time { font-family: monospace; color: #a5b4fc; font-size: 0.85rem; }
.team-name { font-weight: bold; font-size: 1.05rem; }
.vs { color: #888; font-size: 0.8rem; margin: 0 6px; }
.odds-val { color: #4ade80; font-weight: bold; font-size: 1.1rem; }
.bm-badge {
    background: #fbbf24; color: #000; padding: 3px 10px; border-radius: 99px;
    font-weight: bold; font-size: 0.75rem; display: inline-block;
}
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
                # Ensure columns
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
# 2. Business Logic (JST, Zero-Sum, Form)
# ==============================================================================

def to_jst(iso_str):
    if not iso_str: return None
    try:
        dt = pd.to_datetime(iso_str)
        if dt.tz is None: dt = dt.tz_localize('UTC')
        return dt.tz_convert(JST)
    except: return None

def get_recent_form_html(team_name, results_df, current_kickoff_jst):
    """Generate Form Guide HTML (H/A + Icon)"""
    if results_df.empty: return "-"
    
    if 'dt_jst' not in results_df.columns:
        results_df['dt_jst'] = results_df['utc_kickoff'].apply(to_jst)
    
    # 直近5試合 (終了済み)
    past = results_df[
        (results_df['status'] == 'FINISHED') & 
        (results_df['dt_jst'] < current_kickoff_jst) &
        ((results_df['home'] == team_name) | (results_df['away'] == team_name))
    ].sort_values('dt_jst', ascending=False).head(5)
    
    if past.empty: return "-"

    html = '<div class="form-box">'
    # Left=Newest
    for _, g in past.iterrows():
        is_home = (g['home'] == team_name)
        ha_label = "H" if is_home else "A"
        
        h = int(g['home_score']) if pd.notna(g['home_score']) else 0
        a = int(g['away_score']) if pd.notna(g['away_score']) else 0
        
        icon = ""
        if h == a:
            icon = '<span style="color:#222; text-shadow:0 0 1px #888">▲</span>'
        elif (is_home and h > a) or (not is_home and a > h):
            icon = '🔵'
        else:
            icon = '❌'
        
        html += f"""
        <div class="form-item">
            <span class="form-ha">{ha_label}</span>
            <span class="form-icon">{icon}</span>
        </div>
        """
    html += '</div>'
    return html

def calculate_stats(bets_df, bm_log_df, users_df):
    """Zero-Sum P&L"""
    if users_df.empty: return {}
    stats = {u: {'balance': 0, 'wins': 0, 'total': 0, 'potential': 0} for u in users_df['username'].unique()}
    
    bm_map = {}
    if not bm_log_df.empty:
        for _, r in bm_log_df.iterrows():
            nums = "".join([c for c in str(r['gw']) if c.isdigit()])
            if nums: bm_map[f"GW{nums}"] = r['bookmaker']

    if bets_df.empty: return stats

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

def get_strict_target_gw(results_df):
    """Strict Future Mode: Find ONE GW containing future matches"""
    if results_df.empty: return "GW1"
    
    now_jst = datetime.datetime.now(JST)
    if 'dt_jst' not in results_df.columns:
        results_df['dt_jst'] = results_df['utc_kickoff'].apply(to_jst)
    
    # 未来の試合 (now - 4h) を含む最も近いGWを探す
    future_matches = results_df[results_df['dt_jst'] > (now_jst - timedelta(hours=4))].sort_values('dt_jst')
    
    if not future_matches.empty:
        return future_matches.iloc[0]['gw']
    
    # 完全にシーズン終了等の場合は、DB内の最後の試合のGW
    past = results_df.sort_values('dt_jst', ascending=False)
    if not past.empty:
        return past.iloc[0]['gw']
        
    return "GW1"

def sync_api(api_token):
    """Force Season 2025 Sync"""
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
# 3. UI Components
# ==============================================================================

def render_match_card(m, odds_df, bets_df, me, is_bm, results_df):
    mid = m['match_id']
    dt_jst = to_jst(m['utc_kickoff'])
    dt_str = dt_jst.strftime('%m/%d %H:%M')
    
    # Odds
    o_row = odds_df[odds_df['match_id'] == mid]
    oh = o_row.iloc[0]['home_win'] if not o_row.empty else 0
    od = o_row.iloc[0]['draw'] if not o_row.empty else 0
    oa = o_row.iloc[0]['away_win'] if not o_row.empty else 0
    
    # Form HTML
    form_h = get_recent_form_html(m['home'], results_df, dt_jst)
    form_a = get_recent_form_html(m['away'], results_df, dt_jst)
    
    # Bets
    match_bets = bets_df[bets_df['match_id'] == mid] if not bets_df.empty else pd.DataFrame()
    my_bet = match_bets[match_bets['user'] == me] if not match_bets.empty else pd.DataFrame()
    has_bet = not my_bet.empty
    
    # --- Card Header ---
    st.markdown(f"""
    <div class="app-card">
        <div style="display:flex; justify-content:space-between; margin-bottom:8px; color:#aaa; font-size:0.8rem">
            <span class="match-time">⏱ {dt_str}</span>
            <span>{m['status']}</span>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 20px 1fr; align-items:center; text-align:center;">
            <div>
                <div class="team-name">{m['home']}</div>
                {form_h}
                <div class="odds-val" style="margin-top:6px">{oh if oh else '-'}</div>
            </div>
            <div class="vs">vs</div>
            <div>
                <div class="team-name">{m['away']}</div>
                {form_a}
                <div class="odds-val" style="margin-top:6px">{oa if oa else '-'}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    # --- Social Bets (Badge Style) ---
    if not match_bets.empty:
        st.markdown('<div class="social-bets-container">', unsafe_allow_html=True)
        for _, b in match_bets.iterrows():
            is_me = (b['user'] == me)
            me_cls = "me" if is_me else ""
            icon = "🟢" if is_me else "👤"
            st.markdown(f"""
            <div class="bet-badge {me_cls}">
                <span>{icon} {b['user']}</span>
                <span class="bb-pick">{b['pick']}</span>
                <span class="bb-stake">¥{int(b['stake']):,}</span>
            </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # --- Input / Status ---
    is_open = m['status'] not in ['IN_PLAY', 'FINISHED', 'PAUSED'] and oh > 0
    
    if not is_open:
        st.markdown(f"<div style='text-align:center; padding:10px; color:#aaa; font-size:0.8rem; margin-top:8px'>Betting Closed</div></div>", unsafe_allow_html=True)
    elif is_bm:
        st.markdown(f"<div style='text-align:center; margin-top:10px'><span class='bm-badge'>👑 You are BM</span></div></div>", unsafe_allow_html=True)
    else:
        st.markdown("</div>", unsafe_allow_html=True) # Close card
        
        # Form
        with st.form(key=f"bform_{mid}"):
            c1, c2, c3 = st.columns([3, 2, 2])
            
            cur_pick = my_bet.iloc[0]['pick'] if has_bet else "HOME"
            cur_stake = int(my_bet.iloc[0]['stake']) if has_bet else 1000
            
            opts = ["HOME", "DRAW", "AWAY"]
            try: p_idx = opts.index(cur_pick)
            except: p_idx = 0
            
            pick = c1.selectbox("Pick", opts, index=p_idx, label_visibility="collapsed")
            stake = c2.number_input("Stake", 100, 20000, cur_stake, 100, label_visibility="collapsed")
            btn_txt = "Update" if has_bet else "BET"
            
            if c3.form_submit_button(btn_txt, use_container_width=True):
                target_odds = oh if pick=="HOME" else (od if pick=="DRAW" else oa)
                key = f"{m['gw']}:{me}:{mid}"
                payload = {
                    "key": key, "gw": m['gw'], "user": me, "match_id": mid,
                    "match": f"{m['home']} vs {m['away']}",
                    "pick": pick, "stake": stake, "odds": target_odds,
                    "placed_at": datetime.datetime.now(JST).isoformat(),
                    "status": "OPEN", "result": ""
                }
                supabase.table("bets").upsert(payload).execute()
                st.toast(f"{btn_txt} Success!", icon="✅")
                time.sleep(1); st.rerun()

# ==============================================================================
# 4. Main
# ==============================================================================
def main():
    if not supabase: st.error("DB Error"); st.stop()
    
    bets, odds, results, bm_log, users, config = fetch_all_data()
    if users.empty or 'username' not in users.columns:
        st.warning("User data missing."); st.stop()

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
    if 'v32_synced' not in st.session_state:
        with st.spinner("🚀 Syncing Season 2025..."):
            sync_api(token)
        st.session_state['v32_synced'] = True
        st.rerun()

    # Logic
    target_gw = get_strict_target_gw(results) # Strict Future Mode
    stats, bm_map = calculate_stats(bets, bm_log, users)
    my_stat = stats.get(me, {'balance':0, 'wins':0, 'total':0, 'potential':0})
    
    # Current BM
    nums = "".join([c for c in target_gw if c.isdigit()])
    gw_key = f"GW{nums}"
    current_bm = bm_map.get(gw_key, "Undecided")
    is_bm = (me == current_bm)

    # Sidebar
    st.sidebar.markdown(f"## 👤 {me}")
    st.sidebar.caption(f"Team: {st.session_state.get('team')}")
    bal = my_stat['balance']
    col = "#4ade80" if bal >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:1.8rem; font-weight:800; color:{col}'>¥{bal:,}</div>", unsafe_allow_html=True)
    st.sidebar.caption("Total P&L")
    if my_stat['potential'] > 0:
        st.sidebar.markdown(f"<div style='margin-top:10px; padding:10px; border:1px solid #4ade80; border-radius:8px; color:#4ade80; text-align:center;'>PENDING: +¥{my_stat['potential']:,}</div>", unsafe_allow_html=True)
    st.sidebar.divider()
    if st.sidebar.button("Logout"): st.session_state['user'] = None; st.rerun()

    # Tabs
    t1, t2, t3, t4, t5 = st.tabs(["⚽ Matches", "📊 Dashboard", "📜 History", "🏆 Standings", "🛠 Admin"])

    # [TAB 1] Matches (Strict Future Mode)
    with t1:
        c1, c2 = st.columns([3, 1])
        c1.markdown(f"### Fixtures: {target_gw}")
        c2.markdown(f"<div class='bm-badge'>BM: {current_bm}</div>", unsafe_allow_html=True)
        
        # Matches Filter
        if not results.empty:
            matches = results[results['gw'] == target_gw].copy()
            if not matches.empty:
                matches['dt_jst'] = matches['utc_kickoff'].apply(to_jst)
                matches = matches.sort_values('dt_jst')
                
                for _, m in matches.iterrows():
                    render_match_card(m, odds, bets, me, is_bm, results)
            else:
                st.info(f"No matches data for {target_gw}.")
        else:
            st.info("No match data.")

    # [TAB 2] Dashboard
    with t2:
        st.markdown("#### Performance")
        win_rate = (my_stat['wins'] / my_stat['total'] * 100) if my_stat['total'] else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Win Rate", f"{win_rate:.1f}%")
        c2.metric("Wins", f"{my_stat['wins']} / {my_stat['total']}")
        c3.metric("Role", "Admin" if role=='admin' else "User")

    # [TAB 3] History (Card Style)
    with t3:
        st.markdown("#### Betting History")
        if not bets.empty:
            u_list = ["All"] + list(users['username'].unique())
            sel_u = st.selectbox("Filter User", u_list)
            
            hist = bets.copy()
            if sel_u != "All": hist = hist[hist['user'] == sel_u]
            hist['dt_jst'] = hist['placed_at'].apply(to_jst)
            hist = hist.sort_values('dt_jst', ascending=False)
            
            for _, b in hist.iterrows():
                res = b['result'] if b['result'] else "PENDING"
                cls = "h-win" if res == 'WIN' else ("h-lose" if res == 'LOSE' else "")
                pnl_str = "PENDING"
                if res == 'WIN':
                    p = (float(b['stake']) * float(b['odds'])) - float(b['stake'])
                    pnl_str = f"+¥{int(p):,}"
                elif res == 'LOSE':
                    pnl_str = f"-¥{int(b['stake']):,}"
                
                dt_s = b['dt_jst'].strftime('%m/%d %H:%M') if b['dt_jst'] else "-"
                
                st.markdown(f"""
                <div class="hist-card {cls}">
                    <div style="display:flex; justify-content:space-between; margin-bottom:4px; font-size:0.8rem; color:#aaa">
                        <span>{b['user']} | {dt_s}</span>
                        <span style="font-weight:bold; color:{'#ddd' if res=='PENDING' else '#fff'}">{pnl_str}</span>
                    </div>
                    <div style="font-weight:bold; font-size:1rem">{b['match']}</div>
                    <div style="margin-top:4px; font-size:0.9rem">
                        <span style="color:#a5b4fc">{b['pick']}</span> 
                        <span style="color:#aaa">(@{b['odds']})</span>
                        <span style="margin-left:8px; font-family:monospace">¥{int(b['stake']):,}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No history found.")

    # [TAB 4] Standings
    with t4:
        st.markdown("#### Leaderboard")
        ranking = []
        for u, s in stats.items():
            ranking.append({'User': u, 'Balance': s['balance'], 'Wins': s['wins']})
        st.dataframe(pd.DataFrame(ranking).sort_values('Balance', ascending=False), use_container_width=True, hide_index=True)

    # [TAB 5] Admin
    with t5:
        if role == 'admin':
            st.markdown("#### Admin")
            with st.expander("Assign BM"):
                with st.form("bm_form"):
                    # Extract all GWs
                    gws = sorted(results['gw'].unique(), key=lambda x: int("".join([c for c in str(x) if c.isdigit()] or 0))) if not results.empty else ["GW1"]
                    t_gw = st.selectbox("GW", gws)
                    t_u = st.selectbox("User", users['username'].tolist())
                    if st.form_submit_button("Assign"):
                        supabase.table("bm_log").upsert({"gw": t_gw, "bookmaker": t_u}).execute()
                        st.success("Assigned"); time.sleep(1); st.rerun()
            
            with st.expander("Reset Match Data"):
                if st.button("💥 Force Reset (2025)"):
                    supabase.table("result").delete().neq("match_id", -1).execute()
                    sync_api(token)
                    st.success("Reset Done"); time.sleep(1); st.rerun()

if __name__ == "__main__":
    main()
