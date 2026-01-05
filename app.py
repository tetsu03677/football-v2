# [2025-12-22] 1行目に配置先とファイル名を必ずコメントアウトで記載してください。
# app.py
import streamlit as st
import pandas as pd
import requests
import datetime
import time
import pytz
import random
import re
import json
from datetime import timedelta
from supabase import create_client

# ==============================================================================
# 0. System Configuration & CSS (V8.2 Base)
# ==============================================================================
st.set_page_config(page_title="Football App V8.3", layout="wide", page_icon="⚽")
JST = pytz.timezone('Asia/Tokyo')

st.markdown("""
<style>
    /* Layout & Base */
    .block-container { padding-top: 4.5rem; padding-bottom: 6rem; max-width: 100%; padding-left: 0.5rem; padding-right: 0.5rem; }
    
    /* Cards (V6/V7 Rich Style for Matches/Live) */
    .app-card-top { border: 1px solid rgba(255,255,255,0.1); border-bottom: none; border-radius: 12px 12px 0 0; padding: 20px 16px 10px 16px; background: rgba(255,255,255,0.03); margin-bottom: 0px; }
    [data-testid="stForm"] { border: 1px solid rgba(255,255,255,0.1); border-top: none; border-radius: 0 0 12px 12px; padding: 0 16px 20px 16px; background: rgba(255,255,255,0.015); margin-bottom: 24px; }
    
    .card-header { display: flex; justify-content: space-between; font-family: 'Courier New', monospace; font-size: 0.75rem; opacity: 0.7; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 8px; margin-bottom: 16px; letter-spacing: 1px; }
    .matchup-flex { display: flex; align-items: center; justify-content: space-between; text-align: center; gap: 8px; margin-bottom: 16px; }
    .team-col { flex: 1; width: 0; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; }
    .team-name { font-weight: 700; font-size: 1.0rem; line-height: 1.2; min-height: 2.4em; display:flex; align-items:center; justify-content:center; word-wrap: break-word; overflow-wrap: break-word; }
    .score-col { flex: 0 0 auto; }
    .score-box { font-family: 'Courier New', monospace; font-size: 1.6rem; font-weight: 800; padding: 4px 10px; background: rgba(255,255,255,0.05); border-radius: 6px; letter-spacing: 2px; }
    @media (max-width: 600px) { .team-name { font-size: 0.9rem; } .score-box { font-size: 1.4rem; padding: 2px 8px; } }
    
    .form-container { display: flex; align-items: center; justify-content: center; gap: 4px; margin-top: 8px; opacity: 0.8; }
    .form-arrow { font-size: 0.5rem; opacity: 0.5; text-transform: uppercase; margin: 0 2px; letter-spacing: 1px; }
    .form-item { display: flex; flex-direction: column; align-items: center; line-height: 1; margin: 0 1px;}
    .form-ha { font-size: 0.5rem; opacity: 0.5; font-weight: bold; margin-bottom: 2px; }
    .form-mark { font-size: 0.7rem; font-weight: bold; } 
    
    .info-row { display: flex; justify-content: space-around; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px; font-size: 0.9rem; margin-bottom: 12px; }
    .odds-label { font-size: 0.6rem; opacity: 0.5; text-transform: uppercase; letter-spacing: 1px; }
    .odds-value { font-weight: bold; color: #4ade80; font-family: 'Courier New', monospace; font-size: 1.0rem; }
    .social-bets-container { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.05); }
    
    /* Badges (Rich V7.2 Style) */
    .bet-badge { display: inline-flex; align-items: center; gap: 6px; background: rgba(255,255,255,0.05); padding: 4px 8px; border-radius: 4px; font-size: 0.7rem; border: 1px solid rgba(255,255,255,0.05); color: #ccc; }
    .bet-badge.me { border: 1px solid rgba(59, 130, 246, 0.4); background: rgba(59, 130, 246, 0.1); color: #fff; }
    .bet-badge.ai { border: 1px solid rgba(139, 92, 246, 0.4); background: rgba(139, 92, 246, 0.15); color: #e9d5ff; }
    
    .bb-pick { font-weight: bold; color: #a5b4fc; text-transform: uppercase; }
    .bb-res-win { color: #4ade80; font-weight: bold; font-family: monospace; }
    .bb-res-lose { color: #f87171; font-weight: bold; font-family: monospace; }
    .bb-res-pot { color: #fbbf24; font-weight: bold; font-family: monospace; opacity: 0.8; }
    .bb-void { color: #aaa; text-decoration: line-through; }
    
    /* Dashboard & Admin & History (Restored V5.9.3 Styles) */
    .kpi-box { text-align: center; padding: 15px; background: rgba(255,255,255,0.02); border-radius: 8px; margin-bottom: 8px;}
    .kpi-label { font-size: 0.65rem; opacity: 0.5; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 4px;}
    .kpi-val { font-size: 2rem; font-weight: 800; font-family: 'Courier New', monospace; line-height: 1; }
    .rank-list-item { display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-family: 'Courier New', monospace; font-size: 0.9rem; }
    .rank-pos { color: #fbbf24; font-weight: bold; margin-right: 12px; }
    .prof-amt { color: #4ade80; font-weight: bold; }
    .status-msg { text-align: center; opacity: 0.5; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; margin-top: 12px; }
    .bm-badge { background: #fbbf24; color: #000; padding: 2px 8px; border-radius: 4px; font-weight: 800; font-size: 0.65rem; text-transform: uppercase; letter-spacing: 1px; }
    .live-dot { color: #f87171; animation: pulse 1.5s infinite; font-weight: bold; margin-right:4px; font-size: 1.2rem; line-height: 0; vertical-align: middle;}
    .hist-card { background: rgba(255,255,255,0.03); border-radius: 6px; padding: 12px; margin-bottom: 8px; border-left: 3px solid #444; }
    .h-win { border-left-color: #4ade80; }
    .h-lose { border-left-color: #f87171; }
    .h-void { border-left-color: #aaa; }
    .summary-box { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 20px; text-align: center; margin-bottom: 20px; }
    .summary-title { font-size: 0.8rem; opacity: 0.7; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 8px; }
    .summary-val { font-size: 2.2rem; font-weight: 800; font-family: 'Courier New', monospace; }
    .budget-header { font-family: 'Courier New', monospace; text-align: center; margin-bottom: 20px; padding: 10px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; font-size: 0.9rem; }
    .summary-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 24px; width: 100%; }
    .summary-row { display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 12px 20px; }
    .s-user { font-weight: bold; opacity: 0.9; }
    .s-amt { font-family: 'Courier New', monospace; font-weight: 800; font-size: 1.1rem; }
    
    /* CHIP STYLES */
    .chip-tag { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; font-weight: bold; margin-left: 4px; }
    .chip-boost { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); }
    .chip-limit { background: rgba(234, 179, 8, 0.2); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.4); }
    .chip-shield { background: rgba(168, 162, 158, 0.2); color: #d6d3d1; border: 1px solid rgba(168, 162, 158, 0.4); }
    
    /* Shield Console Style */
    .shield-row { display: flex; justify-content: space-between; align-items: center; padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .shield-stat { font-family: monospace; font-weight: bold; }
    .shield-locked { color: #f87171; font-size: 0.8rem; font-weight: bold; display: flex; align-items: center; gap: 4px; }
    .shield-ready { color: #4ade80; font-size: 0.8rem; font-weight: bold; display: flex; align-items: center; gap: 4px; }

    @keyframes pulse { 0% { opacity: 0.4; } 50% { opacity: 1; } 100% { opacity: 0.4; } }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
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

        # Updated bets for chip_used, user_chips table
        bets = get_df_safe("bets", ['key','user','match_id','pick','stake','odds','result','payout','net','gw','placed_at','chip_used'])
        odds = get_df_safe("odds", ['match_id','home_win','draw','away_win'])
        # Updated result for bm_shield
        results = get_df_safe("result", ['match_id','gw','home','away','utc_kickoff','status','home_score','away_score','bm_shield'])
        bm_log = get_df_safe("bm_log", ['gw','bookmaker'])
        users = get_df_safe("users", ['username','password','role','team'])
        config = get_df_safe("config", ['key','value'])
        user_chips = get_df_safe("user_chips", ['user_name','chip_type','amount'])
        
        for df in [bets, results, odds]:
            if not df.empty and 'match_id' in df.columns:
                df['match_id'] = pd.to_numeric(df['match_id'], errors='coerce').fillna(0).astype(int).astype(str)
                df = df[df['match_id'] != '0']

        if not bets.empty:
            bets['pick'] = bets['pick'].astype(str).str.strip().str.upper()
            bets['gw'] = bets['gw'].astype(str).str.strip().str.upper()
            bets['result'] = bets['result'].astype(str).str.strip().str.upper().replace({'NONE': '', 'NAN': ''})
            bets['net'] = pd.to_numeric(bets['net'], errors='coerce').fillna(0)
            bets['chip_used'] = bets['chip_used'].fillna("")
        
        if not results.empty:
            results['status'] = results['status'].astype(str).str.strip().str.upper()
            results['gw'] = results['gw'].astype(str).str.strip().str.upper()
            results['bm_shield'] = results['bm_shield'].fillna(False)
            
        return bets, odds, results, bm_log, users, config, user_chips
    except Exception as e:
        st.error(f"System Error: {e}")
        return [pd.DataFrame()]*7

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
        except: 
            if isinstance(default, int): return default
            return row.iloc[0]['value']
    return default

def to_jst(iso_str):
    if not iso_str: return None
    try:
        dt = pd.to_datetime(iso_str)
        if dt.tz is None: dt = dt.tz_localize('UTC')
        return dt.tz_convert(JST)
    except: return None

def get_recent_form_html(team_name, results_df, current_kickoff_jst, target_season):
    if results_df.empty: return "-"
    if 'dt_jst' not in results_df.columns:
        results_df['dt_jst'] = results_df['utc_kickoff'].apply(to_jst)
    season_start = pd.Timestamp(f"{target_season}-07-01", tz=JST) 
    past = results_df[
        (results_df['dt_jst'] >= season_start) &
        (results_df['status'] == 'FINISHED') & 
        (results_df['dt_jst'] < current_kickoff_jst) &
        ((results_df['home'] == team_name) | (results_df['away'] == team_name))
    ].sort_values('dt_jst', ascending=False).head(5)
    if past.empty: return '<span style="opacity:0.2">-</span>'
    past = past.iloc[::-1]
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

def extract_gw_num(gw_str):
    try:
        return int(re.sub(r'\D', '', str(gw_str)))
    except: return 0

# --- MATCH LOCK LOGIC ---
def is_match_locked(kickoff_iso, lock_minutes):
    if not kickoff_iso: return True
    try:
        ko_dt = pd.to_datetime(kickoff_iso)
        if ko_dt.tz is None: ko_dt = ko_dt.tz_localize('UTC')
        ko_dt = ko_dt.tz_convert(JST)
        lock_time = ko_dt - timedelta(minutes=lock_minutes)
        return datetime.datetime.now(JST) >= lock_time
    except: return True

def settle_bets_date_aware():
    try:
        b_res = supabase.table("bets").select("*").execute()
        r_res = supabase.table("result").select("*").execute()
        if not b_res.data or not r_res.data: return 0, "No data"
        df_b = pd.DataFrame(b_res.data)
        df_r = pd.DataFrame(r_res.data)
        df_b['match_id'] = pd.to_numeric(df_b['match_id'], errors='coerce').fillna(0).astype(int).astype(str)
        df_r['match_id'] = pd.to_numeric(df_r['match_id'], errors='coerce').fillna(0).astype(int).astype(str)
        df_r['dt_jst'] = df_r['utc_kickoff'].apply(to_jst)
        df_r['gw_num'] = df_r['gw'].apply(extract_gw_num)
        
        # Ensure new cols exist
        if 'bm_shield' not in df_r.columns: df_r['bm_shield'] = False
        if 'chip_used' not in df_b.columns: df_b['chip_used'] = ""
        
        now = datetime.datetime.now(JST)
        past_matches = df_r[df_r['dt_jst'] < now].sort_values('dt_jst', ascending=False)
        current_gw = 38 
        if not past_matches.empty: current_gw = past_matches.iloc[0]['gw_num']
        target_gws = range(current_gw - 10, current_gw + 2)
        df_r_scoped = df_r[df_r['gw_num'].isin(target_gws)].copy()
        df_r_scoped = df_r_scoped.rename(columns={'status': 'match_status'})
        merged = pd.merge(df_b, df_r_scoped[['match_id', 'match_status', 'home_score', 'away_score', 'gw_num', 'bm_shield']], on='match_id', how='inner')
        updates_count = 0
        for _, row in merged.iterrows():
            m_status = str(row.get('match_status', '')).strip().upper()
            if m_status == 'FINISHED':
                h_s = int(row['home_score'])
                a_s = int(row['away_score'])
                
                # --- CHIP LOGIC: BM SHIELD ---
                # If BM Shield is TRUE, result is VOID (Refund)
                is_void = bool(row.get('bm_shield', False))
                
                outcome = "DRAW"
                if h_s > a_s: outcome = "HOME"
                elif a_s > h_s: outcome = "AWAY"
                
                bet_pick = str(row['pick']).strip().upper()
                final_res = 'WIN' if bet_pick == outcome else 'LOSE'
                
                if is_void: final_res = 'VOID'
                
                stake = float(row['stake']) if row['stake'] else 0
                
                # --- CHIP LOGIC: ODDS BOOST ---
                # If Boost used, odds + 1.0
                base_odds = float(row['odds']) if row['odds'] else 1.0
                chip_used = str(row.get('chip_used', '')).strip()
                if chip_used == 'BOOST':
                    base_odds += 1.0
                
                if final_res == 'WIN':
                    payout = int(stake * base_odds)
                    net = int(payout - stake)
                elif final_res == 'VOID':
                    payout = int(stake)
                    net = 0
                else:
                    payout = 0
                    net = int(-stake)
                
                curr_res = str(row.get('result', '')).strip().upper()
                curr_net = float(row.get('net', 0)) if pd.notna(row.get('net')) else 0
                
                if curr_res != final_res or int(curr_net) != net:
                    supabase.table("bets").update({"result": final_res, "payout": payout, "net": net}).eq("key", row['key']).execute()
                    updates_count += 1
        return updates_count, f"GW {min(target_gws)} to {max(target_gws)}"
    except Exception as e:
        print(f"Settlement Error: {e}")
        return 0, str(e)

# --- AI CALCULATION ---
def calculate_ai_prediction(match_row, odds_df):
    mid = match_row['match_id']
    o_row = odds_df[odds_df['match_id'] == mid]
    if not o_row.empty:
        h = float(o_row.iloc[0]['home_win'])
        d = float(o_row.iloc[0]['draw'])
        a = float(o_row.iloc[0]['away_win'])
        if h > 0 and d > 0 and a > 0:
            ip_h = 1/h; ip_d = 1/d; ip_a = 1/a
            total_ip = ip_h + ip_d + ip_a
            p_h = (ip_h / total_ip) * 100
            p_a = (ip_a / total_ip) * 100
            p_d = (ip_d / total_ip) * 100
            if p_h > p_a and p_h > p_d: return "HOME", int(p_h)
            elif p_a > p_h and p_a > p_d: return "AWAY", int(p_a)
            else: return "DRAW", int(p_d)
    return None, 0

def calculate_stats_db_only(bets_df, results_df, bm_log_df, users_df):
    if users_df.empty: return {}, {}
    stats = {u: {'balance': 0, 'wins': 0, 'total': 0, 'potential': 0} for u in users_df['username'].unique()}
    bm_map = {}
    if not bm_log_df.empty:
        for _, r in bm_log_df.iterrows():
            nums = "".join([c for c in str(r['gw']) if c.isdigit()])
            if nums: bm_map[f"GW{nums}"] = r['bookmaker']
    if bets_df.empty: return stats, bm_map
    results_safe = results_df.rename(columns={'status': 'match_status'})
    merged = pd.merge(bets_df, results_safe[['match_id', 'match_status', 'home_score', 'away_score', 'bm_shield']], on='match_id', how='left')
    for _, b in merged.iterrows():
        user = b['user']
        if user not in stats: continue
        db_res = str(b.get('result', '')).strip().upper()
        # If VOID/Shielded, net is 0, ignored in PnL but refund happened
        db_net = float(b['net']) if pd.notna(b['net']) and str(b['net']).strip() != '' else 0
        stake = float(b['stake']) if b['stake'] else 0
        
        # Odds logic for potential
        raw_odds = float(b['odds']) if b['odds'] else 1.0
        if str(b.get('chip_used', '')) == 'BOOST': raw_odds += 1.0

        gw_key = f"GW{''.join([c for c in str(b['gw']) if c.isdigit()])}"
        bm = bm_map.get(gw_key)
        
        if db_res in ['WIN', 'LOSE', 'VOID']:
            stats[user]['total'] += 1
            stats[user]['balance'] += int(db_net)
            if db_res == 'WIN': stats[user]['wins'] += 1
            # BM Logic: If Shielded (VOID), BM takes no hit. If WIN/LOSE, standard logic
            if db_res != 'VOID' and bm and bm in stats and bm != user: 
                stats[bm]['balance'] -= int(db_net)
        else:
            stats[user]['potential'] += int((stake * raw_odds) - stake)
    return stats, bm_map

def calculate_profitable_clubs_fixed(bets_df, results_df):
    if bets_df.empty or results_df.empty: return {}
    results_safe = results_df.rename(columns={'status': 'match_status'})
    merged = pd.merge(bets_df, results_safe, on='match_id', how='inner')
    user_club_pnl = {}
    for _, row in merged.iterrows():
        if str(row.get('result', '')).strip().upper() == 'WIN':
            user = row['user']
            pick = row['pick']
            team = row['home'] if pick == 'HOME' else (row['away'] if pick == 'AWAY' else None)
            net = float(row['net']) if pd.notna(row['net']) else 0
            if team:
                if user not in user_club_pnl: user_club_pnl[user] = {}
                user_club_pnl[user][team] = user_club_pnl[user].get(team, 0) + int(net)
    final_ranking = {}
    for u, clubs in user_club_pnl.items():
        sorted_clubs = sorted(clubs.items(), key=lambda x: x[1], reverse=True)[:3]
        final_ranking[u] = sorted_clubs
    return final_ranking

def calculate_live_leaderboard_data(bets_df, results_df, bm_map, users_df, target_gw):
    base_stats, _ = calculate_stats_db_only(bets_df, results_df, pd.DataFrame(list(bm_map.items()), columns=['gw','bookmaker']), users_df)
    gw_total_pnl = {u: 0 for u in users_df['username'].unique()} 
    dream_profit = {u: 0 for u in users_df['username'].unique()}
    inplay_sim_only = {u: 0 for u in users_df['username'].unique()}
    gw_bets = bets_df[bets_df['gw'] == target_gw].copy() if not bets_df.empty else pd.DataFrame()
    if not gw_bets.empty:
        results_safe = results_df.rename(columns={'status': 'match_status'})
        gw_bets = pd.merge(gw_bets, results_safe[['match_id', 'match_status', 'home_score', 'away_score', 'bm_shield']], on='match_id', how='left')
        current_bm = bm_map.get(target_gw)
        for _, b in gw_bets.iterrows():
            user = b['user']
            if user not in base_stats: continue
            db_res = str(b.get('result', '')).strip().upper()
            db_net = float(b['net']) if pd.notna(b['net']) and str(b['net']).strip() != '' else 0
            stake = float(b['stake'])
            
            # Boost Check
            c_odds = float(b['odds'])
            if str(b.get('chip_used', '')) == 'BOOST': c_odds += 1.0

            pot_win = (stake * c_odds) - stake
            dream_profit[user] += int(pot_win)
            pnl = 0
            is_inplay = False
            
            # If shield is active, everything is 0
            is_shielded = bool(b.get('bm_shield', False))

            if db_res in ['WIN', 'LOSE', 'VOID']: pnl = db_net
            elif is_shielded: pnl = 0 # Future shield simulation if data lagged
            else:
                status = str(b.get('match_status', 'SCHEDULED')).strip().upper()
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
            # BM Logic: Shielded = No impact
            if not is_shielded and current_bm and current_bm in gw_total_pnl and current_bm != user:
                gw_total_pnl[current_bm] -= int(pnl)
            
            if is_inplay and not is_shielded:
                inplay_sim_only[user] += int(pnl)
                if current_bm and current_bm in inplay_sim_only and current_bm != user:
                    inplay_sim_only[current_bm] -= int(pnl)
    live_data = []
    for u, s in base_stats.items():
        total_val = s['balance'] + inplay_sim_only.get(u, 0)
        diff_val = gw_total_pnl.get(u, 0)
        live_data.append({'User': u, 'Total': total_val, 'Diff': diff_val, 'Dream': dream_profit.get(u, 0)})
    return pd.DataFrame(live_data).sort_values('Total', ascending=False)

def get_strict_target_gw(results_df, target_season):
    if results_df.empty: return "GW1"
    now_jst = datetime.datetime.now(JST)
    if 'dt_jst' not in results_df.columns: results_df['dt_jst'] = results_df['utc_kickoff'].apply(to_jst)
    season_start = pd.Timestamp(f"{target_season}-07-01", tz=JST)
    current_season = results_df[results_df['dt_jst'] >= season_start]
    if current_season.empty: return "GW1"
    future = current_season[current_season['dt_jst'] > (now_jst - timedelta(hours=3))].sort_values('dt_jst')
    if not future.empty: return future.iloc[0]['gw']
    past = current_season.sort_values('dt_jst', ascending=False)
    if not past.empty: return past.iloc[0]['gw']
    return "GW1"

def check_and_assign_bm(target_gw, bm_log_df, users_df):
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

# --- CLEAN SYNC LOGIC ---
def sync_api(api_token, season):
    if not api_token: return False
    url = f"https://api.football-data.org/v4/competitions/PL/matches?season={season}"
    headers = {'X-Auth-Token': api_token}
    try:
        r = requests.get(url, headers=headers)
        if r.status_code != 200: return False
        data = r.json().get('matches', [])
        upserts = []
        for m in data:
            upserts.append({
                "match_id": int(m['id']), 
                "gw": f"GW{m['matchday']}",
                "home": m['homeTeam']['name'], "away": m['awayTeam']['name'],
                "utc_kickoff": m['utcDate'], "status": m['status'],
                "home_score": m['score']['fullTime']['home'], "away_score": m['score']['fullTime']['away'],
                "updated_at": datetime.datetime.now().isoformat()
            })
        for i in range(0, len(upserts), 100):
            supabase.table("result").upsert(upserts[i:i+100]).execute()
        return True
    except: return False

def clean_old_data(season):
    """V8.2: Delete data older than target season start to fix pollution."""
    try:
        season_start = f"{season}-07-01T00:00:00Z"
        # Delete matches where utc_kickoff < season_start
        supabase.table("result").delete().lt("utc_kickoff", season_start).execute()
        return True
    except: return False

# ==============================================================================
# 3. Main Application
# ==============================================================================
def main():
    if not supabase: st.error("DB Error"); st.stop()
    
    res_conf = supabase.table("config").select("*").execute()
    config = pd.DataFrame(res_conf.data) if res_conf.data else pd.DataFrame(columns=['key','value'])
    token = get_api_token(config)
    
    target_season = get_config_value(config, "API_FOOTBALL_SEASON", 2024)

    if 'v83_api_synced' not in st.session_state:
        with st.spinner(f"Syncing Schedule ({target_season}) & Auto-Settling..."): 
            sync_api(token, target_season)
            settle_bets_date_aware()
            st.session_state['v83_api_synced'] = True
    
    bets, odds, results, bm_log, users, config, user_chips = fetch_all_data()
    if users.empty: st.warning("User data missing."); st.stop()

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
    
    target_gw = get_strict_target_gw(results, target_season)
    check_and_assign_bm(target_gw, bm_log, users)
    
    bm_log_refresh = supabase.table("bm_log").select("*").execute()
    bm_log = pd.DataFrame(bm_log_refresh.data) if bm_log_refresh.data else bm_log

    stats, bm_map = calculate_stats_db_only(bets, results, bm_log, users)
    
    nums = "".join([c for c in target_gw if c.isdigit()])
    current_bm = bm_map.get(f"GW{nums}", "Undecided")
    is_bm = (me == current_bm)
    lock_mins = get_config_value(config, "lock_minutes_before_earliest", 60)
    
    # --- BUDGET LOGIC (LIMIT BREAKER AWARE) ---
    base_budget = get_config_value(config, "max_total_stake_per_gw", 8000) # Default 8000
    
    # Check if I used LIMIT BREAKER in this GW already
    my_gw_bets = pd.DataFrame()
    if not bets.empty:
        my_gw_bets = bets[(bets['user'] == me) & (bets['gw'] == target_gw)]
    
    has_limit_breaker = False
    if not my_gw_bets.empty and 'chip_used' in my_gw_bets.columns:
        if 'LIMIT' in my_gw_bets['chip_used'].unique():
            has_limit_breaker = True
    
    # If LIMIT used in this GW, cap is 20,000. Else 8,000.
    budget_limit = 20000 if has_limit_breaker else base_budget
    current_spend = int(my_gw_bets['stake'].sum()) if not my_gw_bets.empty else 0
    
    # Sidebar
    st.sidebar.markdown(f"## {me}")
    st.sidebar.caption(f"{st.session_state.get('team')}")
    my_stat = stats.get(me, {'balance':0})
    bal = my_stat['balance']
    col = "#4ade80" if bal >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:1.8rem; font-weight:800; color:{col}; font-family:monospace'>¥{bal:,}</div>", unsafe_allow_html=True)
    
    # V8.5 Chip Display in Sidebar
    if not user_chips.empty:
        my_chips = user_chips[user_chips['user_name'] == me]
        chip_counts = {r['chip_type']: r['amount'] for _, r in my_chips.iterrows()}
        c_boost = chip_counts.get('BOOST', 0)
        c_limit = chip_counts.get('LIMIT', 0)
        c_shield = chip_counts.get('SHIELD', 0)
        st.sidebar.markdown(f"**Chips:** 🚀x{c_boost} 🔓x{c_limit} 🛡️x{c_shield}")

    if st.sidebar.button("Logout"): st.session_state['user'] = None; st.rerun()

    t1, t2, t3, t4, t5, t6 = st.tabs(["MATCHES", "LIVE", "HISTORY", "DASHBOARD", "ADMIN", "CHIPS"])

    # --- TAB 1: MATCHES (V8.5: + Chips) ---
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
                matches = matches[matches['dt_jst'] >= pd.Timestamp(f"{target_season}-07-01", tz=JST)].sort_values('dt_jst')
                
                for _, m in matches.iterrows():
                    mid = m['match_id']
                    dt_str = m['dt_jst'].strftime('%m/%d %H:%M')
                    
                    is_locked = is_match_locked(m['utc_kickoff'], lock_mins)
                    
                    o_row = odds[odds['match_id'] == mid]
                    oh = o_row.iloc[0]['home_win'] if not o_row.empty else 0
                    od = o_row.iloc[0]['draw'] if not o_row.empty else 0
                    oa = o_row.iloc[0]['away_win'] if not o_row.empty else 0
                    
                    form_h = get_recent_form_html(m['home'], results, m['dt_jst'], target_season)
                    form_a = get_recent_form_html(m['away'], results, m['dt_jst'], target_season)
                    
                    match_bets = bets[bets['match_id'] == mid] if not bets.empty else pd.DataFrame()
                    my_bet = match_bets[match_bets['user'] == me] if not match_bets.empty else pd.DataFrame()
                    
                    h_s = int(m['home_score']) if pd.notna(m['home_score']) else 0
                    a_s = int(m['away_score']) if pd.notna(m['away_score']) else 0
                    score_disp = f"{h_s}-{a_s}" if m['status'] != 'SCHEDULED' else "vs"

                    card_html = f"""<div class="app-card-top"><div class="card-header"><span>⏱ {dt_str}</span><span>{m['status']}</span></div><div class="matchup-flex"><div class="team-col"><span class="team-name">{m['home']}</span>{form_h}</div><div class="score-col"><span class="score-box">{score_disp}</span></div><div class="team-col"><span class="team-name">{m['away']}</span>{form_a}</div></div><div class="info-row"><div class="odds-label">HOME <span class="odds-value">{oh if oh else '-'}</span></div><div class="odds-label">DRAW <span class="odds-value">{od if od else '-'}</span></div><div class="odds-label">AWAY <span class="odds-value">{oa if oa else '-'}</span></div></div>"""
                    
                    badges = ""
                    ai_pick, ai_conf = calculate_ai_prediction(m, odds)
                    if ai_pick:
                        badges += f"""<div class="bet-badge ai"><span>🤖 AI:</span><span class="bb-pick">{ai_pick}</span> ({ai_conf}%)</div>"""
                    if not match_bets.empty:
                        for _, b in match_bets.iterrows():
                            me_cls = "me" if b['user'] == me else ""
                            pick_txt = b['pick'][:4]
                            
                            # Chip Badge
                            c_u = str(b.get('chip_used', '')).strip()
                            c_html = ""
                            if c_u == 'BOOST': c_html = "<span class='chip-tag chip-boost'>🚀BOOST</span>"
                            if c_u == 'LIMIT': c_html = "<span class='chip-tag chip-limit'>🔓LIMIT</span>"
                            
                            pnl_span = ""
                            db_res = str(b.get('result', '')).strip().upper()
                            db_net = float(b.get('net', 0)) if pd.notna(b.get('net')) else 0
                            
                            if db_res == 'WIN': pnl_span = f"<span class='bb-res-win'>+¥{int(db_net):,}</span>"
                            elif db_res == 'LOSE': pnl_span = f"<span class='bb-res-lose'>-¥{int(abs(db_net)):,}</span>"
                            elif db_res == 'VOID': pnl_span = f"<span class='bb-void'>VOID</span>"
                            
                            badges += f"""<div class="bet-badge {me_cls}"><span>{b['user']}:</span><span class="bb-pick">{pick_txt}</span> (¥{int(b['stake']):,}){c_html}{pnl_span}</div>"""
                    if badges: card_html += f"""<div class="social-bets-container">{badges}</div>"""
                    card_html += "</div>"
                    st.markdown(card_html, unsafe_allow_html=True)

                    is_finished = m['status'] in ['IN_PLAY', 'FINISHED', 'PAUSED']
                    
                    if is_finished or is_locked:
                        msg = "CLOSED"
                        if is_locked and not is_finished: msg = "🔒 LOCKED"
                        st.markdown(f"<div class='status-msg'>{msg}</div><div style='margin-bottom:16px'></div>", unsafe_allow_html=True)
                    elif is_bm: st.markdown("<div style='margin-bottom:16px'></div>", unsafe_allow_html=True)
                    elif oh == 0:
                        st.markdown(f"<div class='status-msg'>WAITING ODDS</div><div style='margin-bottom:16px'></div>", unsafe_allow_html=True)
                    else:
                        with st.form(key=f"bf_{mid}"):
                            c_p, c_s, c_b = st.columns([3, 2, 2])
                            cur_p = my_bet.iloc[0]['pick'] if not my_bet.empty else "HOME"
                            cur_s = int(my_bet.iloc[0]['stake']) if not my_bet.empty else 1000
                            pick = c_p.selectbox("Pick", ["HOME", "DRAW", "AWAY"], index=["HOME", "DRAW", "AWAY"].index(cur_p), label_visibility="collapsed")
                            stake = c_s.number_input("Stake", 100, 20000, cur_s, 100, label_visibility="collapsed")
                            
                            # --- V8.5 CHIP SELECTOR (Redesigned) ---
                            # Check inventory
                            my_chip_inv = user_chips[user_chips['user_name'] == me]
                            inv = {r['chip_type']: r['amount'] for _, r in my_chip_inv.iterrows()}
                            
                            # Build options (Japanese Simple)
                            chip_opts = ["利用しない (None)"]
                            if inv.get('BOOST', 0) > 0: chip_opts.append("🚀 ODDS BOOST (+1.0倍)")
                            if inv.get('LIMIT', 0) > 0: chip_opts.append("🔓 LIMIT BREAKER (上限解放)")
                            
                            sel_chip_str = st.radio("チップを使用しますか？", chip_opts, horizontal=True, key=f"chp_{mid}", label_visibility="collapsed")
                            
                            # Tech Spec Display
                            if "BOOST" in sel_chip_str:
                                st.caption("⚡ **効果:** オッズ+1.0倍 / **コスト:** 1枚")
                            elif "LIMIT" in sel_chip_str:
                                st.caption("⚡ **効果:** このGWの予算上限を20,000円にする / **コスト:** 1枚")

                            # Logic for budget check
                            temp_limit = budget_limit
                            if "LIMIT" in sel_chip_str: temp_limit = 20000
                            
                            new_total = current_spend - (int(my_bet.iloc[0]['stake']) if not my_bet.empty else 0) + stake
                            over_budget = new_total > temp_limit
                            
                            if c_b.form_submit_button("BET", use_container_width=True):
                                if over_budget: st.error(f"予算オーバーです！ 上限: ¥{temp_limit:,}")
                                else:
                                    to = oh if pick=="HOME" else (od if pick=="DRAW" else oa)
                                    
                                    # Extract Chip Code
                                    final_chip = None
                                    if "BOOST" in sel_chip_str: final_chip = "BOOST"
                                    if "LIMIT" in sel_chip_str: final_chip = "LIMIT"
                                    
                                    # Update Inventory if Chip Used (Decrease)
                                    if final_chip:
                                        curr_amt = inv.get(final_chip, 0)
                                        if curr_amt > 0:
                                            supabase.table("user_chips").update({"amount": curr_amt - 1}).match({"user_name": me, "chip_type": final_chip}).execute()
                                        else:
                                            st.error("チップが足りません！"); st.stop()
                                    
                                    pl = {
                                        "key": f"{m['gw']}:{me}:{mid}", "gw": m['gw'], "user": me, 
                                        "match_id": int(mid), "match": f"{m['home']} vs {m['away']}", 
                                        "pick": pick, "stake": stake, "odds": to, 
                                        "placed_at": datetime.datetime.now(JST).isoformat(), 
                                        "status": "OPEN", "result": "", "payout": 0, "net": 0,
                                        "chip_used": final_chip
                                    }
                                    supabase.table("bets").upsert(pl).execute()
                                    st.toast(f"Bet Placed @ {to} (Chip: {final_chip})", icon="✅"); time.sleep(1); st.rerun()
            else: st.info(f"No matches for {target_gw}")
        else: st.info("Loading...")

    # --- TAB 2: LIVE (V8.2: Rich Scoreboard) ---
    with t2:
        st.markdown(f"### ⚡ LIVE: {target_gw}")
        if st.button("🔄 REFRESH & SMART SETTLE", use_container_width=True): 
            sync_api(token, target_season)
            settle_bets_date_aware()
            st.rerun()
        
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
                
                # Check Shield
                is_shielded = bool(m.get('bm_shield', False))
                if is_shielded: sts_disp += " <span style='color:#aaa; font-weight:bold'>[🛡️VOIDED]</span>"

                mb = bets[bets['match_id'] == m['match_id']] if not bets.empty else pd.DataFrame()
                stake_str = ""
                
                if not mb.empty:
                    badges_html = []
                    for _, b in mb.iterrows():
                        u_name = b['user']
                        pick = b['pick']
                        stake = int(b['stake'])
                        pnl_display = ""
                        pnl_col = "#aaa"
                        db_res = str(b.get('result', '')).strip().upper()
                        db_net = float(b.get('net', 0)) if pd.notna(b.get('net')) else 0
                        
                        # Chip Icon
                        c_u = str(b.get('chip_used', '')).strip()
                        c_icon = ""
                        if c_u == 'BOOST': c_icon = "🚀"
                        if c_u == 'LIMIT': c_icon = "🔓"
                        
                        if db_res in ['WIN', 'LOSE']:
                            sign = "+" if db_net > 0 else ""
                            pnl_col = "#4ade80" if db_net > 0 else "#f87171"
                            pnl_display = f"→ <span style='color:{pnl_col}'>{sign}¥{int(db_net):,}</span>"
                        elif db_res == 'VOID':
                             pnl_display = f"→ <span style='color:#aaa'>REFUND</span>"
                        elif m['status'] in ['IN_PLAY', 'PAUSED'] and not is_shielded:
                            h_s = int(m['home_score']) if pd.notna(m['home_score']) else 0
                            a_s = int(m['away_score']) if pd.notna(m['away_score']) else 0
                            curr = "DRAW"
                            if h_s > a_s: curr = "HOME"
                            elif a_s > h_s: curr = "AWAY"
                            is_winning = (pick == curr)
                            
                            c_odds = float(b['odds'])
                            if c_u == 'BOOST': c_odds += 1.0
                            
                            pot_net = (stake * c_odds) - stake if is_winning else -stake
                            sign = "+" if pot_net > 0 else ""
                            pnl_col = "#4ade80" if pot_net > 0 else "#f87171"
                            pnl_display = f"→ <span style='color:{pnl_col}'>{sign}¥{int(pot_net):,}</span>"
                        else:
                            c_odds = float(b['odds'])
                            if c_u == 'BOOST': c_odds += 1.0
                            pot_win = (stake * c_odds) - stake
                            pnl_display = f"→ <span style='color:#666; font-size:0.7rem'>+¥{int(pot_win):,}?</span>"
                        badges_html.append(f"<div><span style='font-weight:bold'>{u_name}:</span> {pick} <span style='font-family:monospace; opacity:0.7'>(¥{stake:,}){c_icon}</span> {pnl_display}</div>")
                    stake_str = "<div style='display:flex; flex-direction:column; align-items:flex-end; font-size:0.75rem; gap:2px;'>" + "".join(badges_html) + "</div>"
                
                st.markdown(f"""<div style="padding:15px; background:rgba(255,255,255,0.02); margin-bottom:10px; border-radius:8px; border:1px solid rgba(255,255,255,0.05);"><div style="display:flex; justify-content:space-between; align-items:center;"><div style="flex:1; text-align:right; font-size:0.9rem; opacity:0.8">{m['home']}</div><div style="padding:0 15px; font-weight:800; font-family:monospace; font-size:1.4rem">{int(m['home_score']) if pd.notna(m['home_score']) else 0}-{int(m['away_score']) if pd.notna(m['away_score']) else 0}</div><div style="flex:1; font-size:0.9rem; opacity:0.8">{m['away']}</div></div><div style="display:flex; justify-content:space-between; margin-top:8px; font-size:0.75rem; opacity:0.6; text-transform:uppercase"><div style='display:flex; align-items:center'>{sts_disp}</div>{stake_str}</div></div>""", unsafe_allow_html=True)

    # --- TAB 3: HISTORY (V5.9.3 Restored) ---
    with t3:
        if not bets.empty:
            c1, c2 = st.columns(2)
            all_gws = sorted(list(bets['gw'].unique()), key=lambda x: int("".join([c for c in str(x) if c.isdigit()] or 0)), reverse=True)
            def_u_idx = 0 
            def_g_idx = 0 
            if target_gw in all_gws: def_g_idx = all_gws.index(target_gw)
            sel_u = c1.selectbox("User", ["All"] + list(users['username'].unique()), index=def_u_idx)
            if sel_u == "All": gw_opts = all_gws
            else:
                gw_opts = ["All"] + all_gws
                if target_gw in all_gws: def_g_idx = all_gws.index(target_gw) + 1
            if def_g_idx >= len(gw_opts): def_g_idx = 0
            sel_g = c2.selectbox("GW", gw_opts, index=def_g_idx)
            hist = bets.copy()
            if sel_u != "All": hist = hist[hist['user'] == sel_u]
            if sel_g != "All": hist = hist[hist['gw'] == sel_g]
            results_safe = results.rename(columns={'status': 'match_status'})
            hist = pd.merge(hist, results_safe[['match_id', 'home', 'away', 'match_status']], on='match_id', how='left')
            hist['dt_jst'] = hist['placed_at'].apply(to_jst)
            hist = hist.sort_values('dt_jst', ascending=False)
            if not hist.empty:
                total_net = hist['net'].sum()
                if sel_u != "All":
                    col_str = "#4ade80" if total_net >= 0 else "#f87171"
                    sign = "+" if total_net >= 0 else ""
                    st.markdown(f"""<div class="summary-box"><div class="summary-title">{sel_u} / {sel_g}</div><div class="summary-val" style="color:{col_str}">{sign}¥{int(total_net):,}</div></div>""", unsafe_allow_html=True)
                else:
                    user_sums = hist.groupby('user')['net'].sum().reset_index().sort_values('net', ascending=False)
                    html_list = ['<div class="summary-list">']
                    for _, r in user_sums.iterrows():
                        u_net = r['net']
                        u_col = "#4ade80" if u_net >= 0 else "#f87171"
                        u_sign = "+" if u_net >= 0 else ""
                        html_list.append(f"""<div class="summary-row"><div class="s-user">{r['user']}</div><div class="s-amt" style="color:{u_col}">{u_sign}¥{int(u_net):,}</div></div>""")
                    html_list.append('</div>')
                    st.markdown("".join(html_list), unsafe_allow_html=True)
            st.markdown("---") 
            for _, b in hist.iterrows():
                db_res = str(b.get('result', '')).strip().upper()
                if db_res not in ['WIN', 'LOSE', 'VOID']: db_res = 'PENDING'
                db_net = float(b.get('net', 0)) if pd.notna(b.get('net')) else 0
                
                cls = "h-win"
                col = "#4ade80"
                pnl = f"+¥{int(db_net):,}"
                
                if db_res == 'LOSE': 
                    cls = "h-lose"
                    col = "#f87171"
                    pnl = f"-¥{int(abs(db_net)):,}"
                elif db_res == 'VOID':
                    cls = "h-void"
                    col = "#aaa"
                    pnl = "REFUND"
                elif db_res == 'PENDING':
                    cls = ""
                    col = "#aaa"
                    pnl = "PENDING"
                
                # Chip Icon
                c_u = str(b.get('chip_used', '')).strip()
                c_icon = ""
                if c_u == 'BOOST': c_icon = "🚀"
                if c_u == 'LIMIT': c_icon = "🔓"

                match_name = f"{b['home']} vs {b['away']}" if pd.notna(b['home']) else b.get('match', 'Unknown')
                st.markdown(f"""<div class="hist-card {cls}"><div style="display:flex; justify-content:space-between; font-size:0.75rem; opacity:0.6; margin-bottom:4px; text-transform:uppercase; font-family:'Courier New', monospace"><span>{b['user']} | {b['gw']}</span><span style="color:{col}; font-weight:bold;">{pnl}</span></div><div style="font-weight:bold; font-size:0.95rem; margin-bottom:4px">{match_name}</div><div style="font-size:0.8rem; opacity:0.8"><span style="color:#a5b4fc; font-weight:bold">{b['pick']}</span> <span style="opacity:0.6">(@{b['odds']}){c_icon}</span><span style="margin-left:8px; font-family:monospace">¥{int(b['stake']):,}</span></div></div>""", unsafe_allow_html=True)
        else: st.info("No history.")

    # --- TAB 4: DASHBOARD (V5.9.3 Restored) ---
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
        prof_data = calculate_profitable_clubs_fixed(bets, results)
        if prof_data:
            c_cols = st.columns(len(prof_data))
            for i, (u, clubs) in enumerate(prof_data.items()):
                with c_cols[i]:
                    st.markdown(f"**{u}**")
                    if clubs:
                        for j, (team, amt) in enumerate(clubs): st.markdown(f"<div class='rank-list-item'><span class='rank-pos'>{j+1}.</span> <span style='flex:1'>{team}</span> <span class='prof-amt'>+¥{amt:,}</span></div>", unsafe_allow_html=True)
                    else: st.caption("No wins yet.")
        st.markdown("---")
        st.markdown("#### ⚖️ BM STATS")
        if not bm_log.empty:
            bm_counts = bm_log['bookmaker'].value_counts().reset_index()
            bm_counts.columns = ['User', 'Count']
            for _, r in bm_counts.iterrows(): st.markdown(f"<div class='rank-list-item'><span style='flex:1'>{r['User']}</span> <span style='font-weight:bold'>{r['Count']} times</span></div>", unsafe_allow_html=True)

    with t5:
        if role == 'admin':
            st.markdown("<div class='admin-section'><div class='admin-header'>⚙️ CONFIG MANAGER</div>", unsafe_allow_html=True)
            c_cfg1, c_cfg2 = st.columns([3, 1])
            curr_s = get_config_value(config, "API_FOOTBALL_SEASON", 2024)
            new_s = c_cfg1.number_input("API Season", 2023, 2030, int(curr_s))
            if c_cfg2.button("💾 SAVE CONFIG", use_container_width=True):
                supabase.table("config").upsert({"key": "API_FOOTBALL_SEASON", "value": str(new_s)}).execute()
                st.success("Saved!"); time.sleep(1); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("#### SYSTEM HEALTH")
            unsettled_q = 0
            if not bets.empty and not results.empty:
                results_safe = results.rename(columns={'status': 'match_status'})
                merged = pd.merge(bets, results_safe, on='match_id', how='inner')
                unsettled_q = len(merged[(pd.isna(merged['net']) | (merged['net'] == 0)) & (merged['match_status'] == 'FINISHED')])
            c1, c2 = st.columns(2)
            c1.metric("Total Bets", len(bets))
            c2.metric("Unsettled Finished", unsettled_q)
            if st.button("🚨 FORCE SCOPED SETTLE", type="secondary"):
                count, scope_desc = settle_bets_date_aware()
                st.success(f"Settled {count} bets ({scope_desc})! Reloading..."); time.sleep(1); st.rerun()
            
            if st.button(f"🔄 FORCE RESYNC (SEASON {target_season})", type="primary", use_container_width=True):
                with st.spinner("Cleaning old data & Resyncing..."):
                    clean_old_data(target_season)
                    sync_api(token, target_season)
                    st.success("Database Repaired & Synced!"); time.sleep(1); st.rerun()

            # --- V8.5 ADMIN CHIP INIT ---
            st.write("---")
            st.markdown("#### 💎 CHIP INITIALIZATION (Admin Only)")
            if st.button("INIT ALL USERS CHIPS (2 each)"):
                for usr in users['username'].unique():
                    supabase.table("user_chips").upsert({"user_name": usr, "chip_type": "BOOST", "amount": 2}).execute()
                    supabase.table("user_chips").upsert({"user_name": usr, "chip_type": "LIMIT", "amount": 2}).execute()
                    supabase.table("user_chips").upsert({"user_name": usr, "chip_type": "SHIELD", "amount": 2}).execute()
                st.success("Distributed 2 chips of each type to all users.")
            
            st.write("---")
            st.markdown("#### ODDS EDITOR (Manual)")
            with st.expander("📝 Update Odds", expanded=False):
                if not results.empty:
                    matches = results[results['gw'] == target_gw].copy()
                    if not matches.empty:
                        matches['dt_jst'] = matches['utc_kickoff'].apply(to_jst)
                        matches = matches[matches['dt_jst'] >= pd.Timestamp(f"{target_season}-07-01", tz=JST)].sort_values('dt_jst')
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
                            supabase.table("odds").upsert({"match_id": int(sel_m_id), "home_win": new_h, "draw": new_d, "away_win": new_a}).execute()
                            st.success("Updated"); time.sleep(1); st.rerun()
            
            # --- V8.4 NEW: RESULT OVERRIDE ---
            st.markdown("#### 👑 RESULT OVERRIDE (Emergency)")
            with st.expander("🚨 Manual Score/Status Fix", expanded=False):
                st.info("Use this ONLY when API data is stuck. It will overwrite the database and trigger settlement.")
                if not results.empty:
                    # 1. Select GW
                    all_gws = sorted(results['gw'].unique(), key=lambda x: int(re.sub(r'\D', '', str(x)) or 0))
                    # Default to last one
                    def_gw_idx = len(all_gws) - 1 if all_gws else 0
                    sel_gw_ovr = st.selectbox("Select GW", all_gws, index=def_gw_idx, key="ovr_gw_sel")
                    
                    # 2. Select Match
                    gw_matches = results[results['gw'] == sel_gw_ovr].copy()
                    match_map = {f"{r['home']} vs {r['away']}": r for _, r in gw_matches.iterrows()}
                    sel_match_name = st.selectbox("Select Match", list(match_map.keys()), key="ovr_match_sel")
                    
                    if sel_match_name:
                        target_m = match_map[sel_match_name]
                        curr_status = target_m['status']
                        curr_h = int(target_m['home_score']) if pd.notna(target_m['home_score']) else 0
                        curr_a = int(target_m['away_score']) if pd.notna(target_m['away_score']) else 0
                        
                        # --- V8.5 EXPLICIT DISPLAY ---
                        st.markdown(f"**Current DB State:** Status: `{curr_status}` | Score: `{curr_h} - {curr_a}`")
                        
                        c1, c2, c3 = st.columns(3)
                        # Status Selector
                        st_opts = ['FINISHED', 'IN_PLAY', 'SCHEDULED', 'POSTPONED']
                        st_idx = st_opts.index(curr_status) if curr_status in st_opts else 0
                        new_status = c1.selectbox("Status", st_opts, index=st_idx, key="ovr_status")
                        
                        # Score Selector (Dropdown 0-10)
                        score_opts = list(range(11))
                        h_idx = curr_h if curr_h <= 10 else 0
                        a_idx = curr_a if curr_a <= 10 else 0
                        new_h = c2.selectbox("Home Score", score_opts, index=h_idx, key="ovr_h")
                        new_a = c3.selectbox("Away Score", score_opts, index=a_idx, key="ovr_a")
                        
                        if st.button("FORCE UPDATE & SETTLE", type="primary", use_container_width=True):
                            # Update Result Table
                            supabase.table("result").update({
                                "status": new_status,
                                "home_score": new_h,
                                "away_score": new_a,
                                "updated_at": datetime.datetime.now().isoformat()
                            }).eq("match_id", target_m['match_id']).execute()
                            
                            # Trigger Settlement
                            count, msg = settle_bets_date_aware()
                            st.success(f"Updated Match & Settled {count} Bets! ({msg})")
                            time.sleep(1.5)
                            st.rerun()

            with st.expander("👑 BM Manual Override"):
                 with st.form("bm_manual"):
                    t_gw = st.selectbox("GW", sorted(results['gw'].unique()) if not results.empty else ["GW1"])
                    t_u = st.selectbox("User", users['username'].tolist())
                    if st.form_submit_button("Assign"):
                        supabase.table("bm_log").upsert({"gw": t_gw, "bookmaker": t_u}).execute()
                        st.success("Assigned"); time.sleep(1); st.rerun()

    # --- TAB 6: CHIPS (V8.5 REDESIGNED) ---
    with t6:
        st.markdown("### 💎 ARMORY (チップ管理)")
        
        # 1. Inventory (Professional UI)
        st.markdown("#### 🎒 所持チップ一覧")
        if not user_chips.empty:
            my_chips = user_chips[user_chips['user_name'] == me]
            if not my_chips.empty:
                cols = st.columns(3)
                inv_map = {r['chip_type']: r['amount'] for _, r in my_chips.iterrows()}
                
                with cols[0]:
                    st.metric("🚀 ODDS BOOST", f"x{inv_map.get('BOOST', 0)}")
                    st.caption("効果: オッズ+1.0倍")
                with cols[1]:
                    st.metric("🔓 LIMIT BREAKER", f"x{inv_map.get('LIMIT', 0)}")
                    st.caption("効果: 予算上限20,000円")
                with cols[2]:
                    st.metric("🛡️ BM SHIELD", f"x{inv_map.get('SHIELD', 0)}")
                    st.caption("効果: 試合無効化 (BM専用)")
            else:
                st.info("No chips found.")
        
        # 2. Public Intel (New Feature)
        st.divider()
        st.markdown("#### 🌍 参加者のチップ保有状況")
        if not user_chips.empty:
            # Pivot table to show Users x Chips
            pivot_chips = user_chips.pivot(index='user_name', columns='chip_type', values='amount').fillna(0).astype(int)
            # Ensure all columns exist
            for c in ['BOOST', 'LIMIT', 'SHIELD']:
                if c not in pivot_chips.columns: pivot_chips[c] = 0
            
            # Display as a clean table
            st.dataframe(
                pivot_chips[['BOOST', 'LIMIT', 'SHIELD']], 
                use_container_width=True, 
                column_config={
                    "BOOST": st.column_config.NumberColumn("🚀 Boost", format="x%d"),
                    "LIMIT": st.column_config.NumberColumn("🔓 Limit", format="x%d"),
                    "SHIELD": st.column_config.NumberColumn("🛡️ Shield", format="x%d"),
                }
            )

        st.divider()

        # 3. BM SHIELD CONSOLE (Limited to Latest GW)
        st.markdown("#### 🛡️ シールド発動コンソール (BM専用)")
        
        my_bm_gws = []
        if not bm_log.empty:
            my_bm_gws = bm_log[bm_log['bookmaker'] == me]['gw'].tolist()
        
        if my_bm_gws and not results.empty:
            # 1. First, find ALL potential matches
            candidates_all = results[
                (results['gw'].isin(my_bm_gws)) & 
                (results['status'] == 'FINISHED') & 
                ((results['bm_shield'] == False) | (pd.isna(results['bm_shield'])))
            ].copy()

            if not candidates_all.empty:
                # 2. Extract GW numbers and find the MAX (Latest)
                candidates_all['gw_num'] = candidates_all['gw'].apply(extract_gw_num)
                latest_gw_num = candidates_all['gw_num'].max()
                
                # 3. Filter to keep only matches from the Latest GW
                candidates = candidates_all[candidates_all['gw_num'] == latest_gw_num].copy()
                
                if not candidates.empty:
                    candidates['dt_jst'] = candidates['utc_kickoff'].apply(to_jst)
                    candidates = candidates.sort_values('dt_jst', ascending=False)
                    
                    st.caption(f"直近の担当GW (GW{latest_gw_num}) の対象試合を表示しています。")
                    
                    for _, m in candidates.iterrows():
                        mid = m['match_id']
                        m_name = f"{m['home']} vs {m['away']}"
                        
                        m_bets = bets[bets['match_id'] == mid]
                        chips_used_in_match = 0
                        if not m_bets.empty:
                             chips_used_in_match = m_bets[m_bets['chip_used'] != ""].shape[0]
                        
                        is_dirty = (chips_used_in_match > 0)
                        
                        with st.expander(f"{m['gw']}: {m_name} ({m['home_score']}-{m['away_score']})", expanded=True):
                            c1, c2, c3 = st.columns([2, 2, 1])
                            
                            with c1:
                                st.markdown(f"**試合結果:** {m['home_score']} - {m['away_score']}")
                                if is_dirty:
                                    st.markdown("<div class='shield-locked'>🔴 ロック中 (チップ使用あり)</div>", unsafe_allow_html=True)
                                else:
                                    st.markdown("<div class='shield-ready'>🟢 発動可能 (Ready)</div>", unsafe_allow_html=True)

                            with c2:
                                shield_count = 0
                                if not user_chips.empty:
                                    u_row = user_chips[(user_chips['user_name'] == me) & (user_chips['chip_type'] == 'SHIELD')]
                                    if not u_row.empty: shield_count = int(u_row.iloc[0]['amount'])
                                st.caption(f"シールド残数: {shield_count}")
                                
                            with c3:
                                if is_dirty:
                                    st.button("🔒", key=f"sh_lk_{mid}", disabled=True)
                                elif shield_count <= 0:
                                    st.button("🚫", key=f"sh_nc_{mid}", disabled=True)
                                else:
                                    if st.button("無効試合にする", key=f"sh_act_{mid}", type="primary", use_container_width=True):
                                        supabase.table("result").update({"bm_shield": True}).eq("match_id", mid).execute()
                                        supabase.table("user_chips").update({"amount": shield_count - 1}).match({"user_name": me, "chip_type": "SHIELD"}).execute()
                                        settle_bets_date_aware()
                                        st.success("シールド発動！試合を無効化しました。"); time.sleep(1.5); st.rerun()
                else:
                    st.info("直近のGWに対象試合はありません。")
            else:
                st.info("現在、シールド発動可能な試合はありません。")
        else:
             st.caption("BM担当履歴がありません。")

if __name__ == "__main__":
    main()
