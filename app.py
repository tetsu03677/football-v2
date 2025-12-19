import streamlit as st
import pandas as pd
import requests
import datetime
import time
import pytz
from datetime import timedelta, timezone
from supabase import create_client

# ==============================================================================
# 0. システム設定 & CSS (UI/UX)
# ==============================================================================
st.set_page_config(page_title="Premier Picks V2 Pro", layout="wide", page_icon="⚽")
JST = timezone(timedelta(hours=9), 'JST')

# --- CSS Design System ---
st.markdown("""
<style>
/* 全体レイアウト */
.block-container {
    padding-top: 3.5rem;
    padding-bottom: 6rem;
    max-width: 1000px;
}
/* カードデザイン */
.app-card {
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 12px;
    padding: 16px;
    background: linear-gradient(145deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.01) 100%);
    margin-bottom: 12px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.2);
}
/* テキストスタイル */
.subtle { color: rgba(255,255,255,.5); font-size: 0.8rem; }
.bold-text { font-weight: 700; color: #f3f4f6; }
.match-time { font-family: monospace; font-size: 0.9rem; color: #a5b4fc; }

/* KPIパネル */
.kpi-container {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
    gap: 10px;
    margin-bottom: 20px;
}
.kpi-box {
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 10px;
    padding: 12px;
    background: rgba(0,0,0,0.2);
    text-align: center;
}
.kpi-label { font-size: 0.7rem; color: rgba(255,255,255,0.6); text-transform: uppercase; letter-spacing: 1px; }
.kpi-value { font-size: 1.4rem; font-weight: 800; margin-top: 4px; }

/* 新機能: ポテンシャル利益 */
.potential-box {
    margin-top: 15px;
    padding: 12px;
    border-radius: 8px;
    background: rgba(34, 197, 94, 0.15);
    border: 1px solid rgba(34, 197, 94, 0.4);
    color: #4ade80;
    text-align: center;
    font-weight: bold;
    animation: pulse 2s infinite;
}
@keyframes pulse {
    0% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.4); }
    70% { box-shadow: 0 0 0 10px rgba(74, 222, 128, 0); }
    100% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0); }
}

/* 他ユーザーのベット状況 */
.avatar-group { display: flex; gap: 4px; margin-top: 4px; justify-content: flex-end; }
.avatar-badge {
    display: inline-flex; align-items: center; justify-content: center;
    padding: 2px 8px; border-radius: 12px;
    font-size: 0.7rem; color: #fff;
    background: rgba(255,255,255,0.1);
    border: 1px solid rgba(255,255,255,0.1);
}

/* ライブ損益表示 */
.live-plus { color: #4ade80; text-shadow: 0 0 10px rgba(74, 222, 128, 0.3); }
.live-minus { color: #f87171; text-shadow: 0 0 10px rgba(248, 113, 113, 0.3); }
</style>
""", unsafe_allow_html=True)


# ==============================================================================
# 1. 堅牢なDB接続 (Retry Logic)
# ==============================================================================
@st.cache_resource(ttl=3600)
def get_supabase_client():
    """Supabaseクライアントを生成"""
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        client = create_client(url, key)
        # タイムアウト設定を試みる（ライブラリバージョン依存の回避）
        try:
            client.postgrest.timeout = 20
        except:
            pass
        return client
    except Exception as e:
        st.error(f"System Error (DB Init): {e}")
        return None

supabase = get_supabase_client()

def run_db_query(query_func, retries=3):
    """DB操作のリトライラッパー"""
    for i in range(retries):
        try:
            return query_func()
        except Exception as e:
            if i == retries - 1:
                return None
            time.sleep(1)
    return None

def get_config():
    """アプリ設定を取得"""
    def _q():
        return supabase.table("app_config").select("*").execute()
    
    res = run_db_query(_q)
    if res and res.data:
        return {r['key']: r['value'] for r in res.data}
    return {}

# ==============================================================================
# 2. ユーティリティ関数群 (Format & Calc)
# ==============================================================================
def fmt_yen(n):
    if n is None: return "¥0"
    try:
        return f"¥{int(n):,}"
    except:
        return str(n)

def to_jst_str(iso_str, fmt='%m/%d %H:%M'):
    if not iso_str: return "-"
    try:
        dt = pd.to_datetime(iso_str)
        if dt.tz is None:
            dt = dt.tz_localize('UTC')
        return dt.tz_convert(JST).strftime(fmt)
    except:
        return str(iso_str)

def parse_gw_number(val):
    """ 'GW7' -> 7, '10' -> 10 に変換する安全装置 """
    s = str(val).upper()
    # 数字だけ抽出
    nums = ''.join(filter(str.isdigit, s))
    if nums:
        return int(nums)
    return 1 # Fallback

# ==============================================================================
# 3. ビジネスロジック
# ==============================================================================

def sync_data_process(api_token, season_str="2024"):
    """データ同期: 試合更新, オッズロック, 自動精算"""
    if not api_token:
        return False, "API Token is missing."

    headers = {'X-Auth-Token': api_token}
    
    d_now = datetime.datetime.now()
    d_from = (d_now - timedelta(days=14)).strftime('%Y-%m-%d')
    d_to = (d_now + timedelta(days=21)).strftime('%Y-%m-%d')
    
    try:
        url = f"https://api.football-data.org/v4/competitions/PL/matches?dateFrom={d_from}&dateTo={d_to}"
        res = requests.get(url, headers=headers, timeout=15)
        
        if res.status_code != 200:
            return False, f"API Error: {res.status_code}"
            
        data = res.json()
        matches = data.get('matches', [])
        
        conf = get_config()
        lock_hours = float(conf.get('odds_lock_hours', 1.0))
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        upsert_list = []
        finished_ids = []
        
        for m in matches:
            kickoff = m['utcDate']
            k_dt = pd.to_datetime(kickoff)
            if k_dt.tz is None: k_dt = k_dt.tz_localize('UTC')
            
            hours_diff = (k_dt - now_utc).total_seconds() / 3600
            is_locked = (hours_diff <= lock_hours)
            
            row = {
                "match_id": m['id'],
                "season": season_str,
                "gameweek": m['matchday'],
                "home_team": m['homeTeam']['name'],
                "away_team": m['awayTeam']['name'],
                "kickoff_time": kickoff,
                "status": m['status'],
                "home_score": m['score']['fullTime']['home'],
                "away_score": m['score']['fullTime']['away'],
                "odds_locked": is_locked,
                "last_updated": datetime.datetime.now().isoformat()
            }
            
            api_odds = m.get('odds', {})
            if not is_locked and api_odds.get('homeWin'):
                row["odds_home"] = api_odds.get('homeWin')
                row["odds_draw"] = api_odds.get('draw')
                row["odds_away"] = api_odds.get('awayWin')
            
            upsert_list.append(row)
            
            if m['status'] == 'FINISHED':
                finished_ids.append(m['id'])
        
        if upsert_list:
            def _upsert():
                supabase.table("matches").upsert(upsert_list).execute()
            run_db_query(_upsert)

        settled_count = 0
        if finished_ids:
            def _get_pending():
                return supabase.table("bets").select("*").in_("match_id", finished_ids).eq("status", "PENDING").execute()
            
            pending_res = run_db_query(_get_pending)
            pending_bets = pending_res.data if pending_res else []
            
            def _get_matches():
                return supabase.table("matches").select("*").in_("match_id", finished_ids).execute()
            
            matches_res = run_db_query(_get_matches)
            matches_map = {m['match_id']: m for m in (matches_res.data if matches_res else [])}
            
            for b in pending_bets:
                m_info = matches_map.get(b['match_id'])
                if not m_info: continue
                
                hs = m_info['home_score']
                as_ = m_info['away_score']
                if hs is None or as_ is None: continue 
                
                actual_result = "DRAW"
                if hs > as_: actual_result = "HOME"
                elif as_ > hs: actual_result = "AWAY"
                
                new_status = "WON" if b['choice'] == actual_result else "LOST"
                
                profit_player = 0
                if new_status == "WON":
                    profit_player = int(b['stake'] * b['odds_at_bet']) - b['stake']
                else:
                    profit_player = -b['stake']
                
                # DB更新
                supabase.table("bets").update({"status": new_status}).eq("bet_id", b['bet_id']).execute()
                
                # P2P Settlement
                bm_query = supabase.table("bm_history").select("user_id").eq("gameweek", m_info['gameweek']).eq("season", season_str).execute()
                bm_id = bm_query.data[0]['user_id'] if bm_query.data else None
                
                supabase.rpc("increment_balance", {"p_user_id": b['user_id'], "p_amount": profit_player}).execute()
                
                if bm_id and bm_id != b['user_id']: 
                    supabase.rpc("increment_balance", {"p_user_id": bm_id, "p_amount": -profit_player}).execute()
                
                settled_count += 1

        return True, f"同期完了: {len(upsert_list)}試合更新, {settled_count}件精算"

    except Exception as e:
        return False, f"Sync Exception: {e}"

def get_detailed_user_stats(user_id):
    def _q():
        return supabase.table("bets").select("*, matches(*)").eq("user_id", user_id).execute()
    
    res = run_db_query(_q)
    if not res: return {
        "total_bets": 0, "wins": 0, "win_rate": 0.0,
        "potential_profit": 0, "live_profit": 0, "best_teams": []
    }
    
    bets = res.data
    stats = {
        "total_bets": 0, "wins": 0, "win_rate": 0.0,
        "potential_profit": 0, "live_profit": 0, "best_teams": []
    }
    team_map = {} 
    
    for b in bets:
        m = b['matches']
        if not m: continue
        
        status = b['status']
        stake = b['stake']
        odds = b['odds_at_bet'] or 1.0
        
        if status == 'PENDING':
            possible_win = (stake * odds) - stake
            stats['potential_profit'] += possible_win
            
            if m['status'] in ['IN_PLAY', 'PAUSED']:
                hs, as_ = m['home_score'], m['away_score']
                if hs is not None and as_ is not None:
                    curr_res = "DRAW"
                    if hs > as_: curr_res = "HOME"
                    elif as_ > hs: curr_res = "AWAY"
                    
                    if b['choice'] == curr_res:
                        stats['live_profit'] += possible_win
                    else:
                        stats['live_profit'] -= stake
                        
        elif status in ['WON', 'LOST']:
            stats['total_bets'] += 1
            if status == 'WON':
                stats['wins'] += 1
            
            chosen_team = None
            if b['choice'] == 'HOME': chosen_team = m['home_team']
            elif b['choice'] == 'AWAY': chosen_team = m['away_team']
            
            if chosen_team:
                if chosen_team not in team_map: team_map[chosen_team] = {'w':0, 't':0}
                team_map[chosen_team]['t'] += 1
                if status == 'WON': team_map[chosen_team]['w'] += 1
                
    if stats['total_bets'] > 0:
        stats['win_rate'] = (stats['wins'] / stats['total_bets']) * 100
        
    valid_teams = [
        (k, v['w']/v['t'], v['w'], v['t']) 
        for k, v in team_map.items() if v['t'] >= 2
    ]
    valid_teams.sort(key=lambda x: (x[1], x[3]), reverse=True)
    stats['best_teams'] = valid_teams[:5]
    
    return stats

# ==============================================================================
# 4. UI: コンポーネント
# ==============================================================================

def render_login_sidebar(users):
    st.sidebar.markdown("### 🔐 Login")
    username = st.sidebar.selectbox("Username", [u['username'] for u in users])
    password = st.sidebar.text_input("Password", type="password")
    
    if st.sidebar.button("Enter Stadium 🏟️", type="primary"):
        user = next((u for u in users if u['username'] == username), None)
        if user and str(user.get('password')) == str(password):
            st.session_state['user'] = user
            st.rerun()
        else:
            st.error("Authentication Failed")
    return None

def render_match_card(m, me, users, conf):
    mid = m['match_id']
    kickoff_fmt = to_jst_str(m['kickoff_time'])
    
    oh = m.get('odds_home') or '-'
    od = m.get('odds_draw') or '-'
    oa = m.get('odds_away') or '-'
    
    # 他人のベット (N+1回避のため親で取得すべきだが、ここは簡易実装)
    bets_res = run_db_query(lambda: supabase.table("bets").select("user_id, choice").eq("match_id", mid).execute())
    other_bets_html = ""
    my_bet_info = None
    
    if bets_res and bets_res.data:
        for b in bets_res.data:
            if b['user_id'] == me['user_id']:
                my_bet_info = b['choice']
            else:
                u_name = next((u['username'] for u in users if u['user_id'] == b['user_id']), "?")
                color = "#fbbf24" if b['choice']=='DRAW' else ("#ef4444" if b['choice']=='HOME' else "#3b82f6")
                initial = u_name[0]
                other_bets_html += f"""
                <span title="{u_name}: {b['choice']}" class="avatar-badge" style="background:{color}cc">
                    {initial}:{b['choice'][0]}
                </span>
                """

    with st.container():
        st.markdown(f"""
        <div class="app-card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <span class="match-time">⏱ {kickoff_fmt}</span>
                <div class="avatar-group">{other_bets_html}</div>
            </div>
            
            <div style="display:grid; grid-template-columns: 1fr 20px 1fr; align-items:center; gap:10px; margin-bottom:12px;">
                <div style="text-align:center;">
                    <div class="bold-text" style="font-size:1.1rem;">{m['home_team']}</div>
                    <div style="color:#4ade80; font-weight:bold; font-size:0.9rem;">{oh}</div>
                </div>
                <div style="text-align:center; color:#6b7280; font-size:0.8rem;">VS</div>
                <div style="text-align:center;">
                    <div class="bold-text" style="font-size:1.1rem;">{m['away_team']}</div>
                    <div style="color:#4ade80; font-weight:bold; font-size:0.9rem;">{oa}</div>
                </div>
            </div>
            
            {f'<div style="text-align:center; font-size:1.5rem; letter-spacing:4px; margin-bottom:10px; color:#fff;">{m["home_score"]} - {m["away_score"]}</div>' if m['status'] in ['IN_PLAY','FINISHED','PAUSED'] else ''}
            
            <div style="text-align:center;">
                <span style="background:#374151; color:#9ca3af; padding:2px 8px; border-radius:4px; font-size:0.7rem;">{m['status']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        if my_bet_info:
            st.info(f"✅ Pick: **{my_bet_info}**")
        else:
            if m['status'] not in ['FINISHED', 'IN_PLAY']:
                with st.form(key=f"form_{mid}"):
                    c1, c2, c3 = st.columns([3, 2, 2])
                    opts = [f"HOME ({oh})", f"DRAW ({od})", f"AWAY ({oa})"]
                    choice_label = c1.selectbox("予想", opts, label_visibility="collapsed")
                    stake = c2.number_input("¥", min_value=100, step=100, value=1000, label_visibility="collapsed")
                    submit = c3.form_submit_button("BET 🔥", use_container_width=True)
                    
                    if submit:
                        target = "HOME" if "HOME" in choice_label else ("DRAW" if "DRAW" in choice_label else "AWAY")
                        val = oh if target=="HOME" else (od if target=="DRAW" else oa)
                        
                        try:
                            odds_float = float(val)
                            supabase.table("bets").insert({
                                "user_id": me['user_id'],
                                "match_id": mid,
                                "choice": target,
                                "stake": stake,
                                "odds_at_bet": odds_float,
                                "status": "PENDING"
                            }).execute()
                            st.toast("Bet Successful!", icon="🎉")
                            time.sleep(1)
                            st.rerun()
                        except ValueError:
                            st.error("Odds not ready.")
            else:
                st.write("🔒 Closed")

# ==============================================================================
# 5. アプリケーション本体 (Main Loop)
# ==============================================================================

def main():
    if not supabase:
        st.error("Database connection failed. Please check your network or secrets.")
        st.stop()

    users_res = run_db_query(lambda: supabase.table("users").select("*").execute())
    users = users_res.data if users_res else []

    if 'user' not in st.session_state or st.session_state['user'] is None:
        render_login_sidebar(users)
        st.stop()

    curr_user = next((u for u in users if u['user_id'] == st.session_state['user']['user_id']), None)
    if not curr_user:
        st.session_state['user'] = None
        st.rerun()
        
    me = curr_user
    conf = get_config()
    my_stats = get_detailed_user_stats(me['user_id'])

    # --- Sidebar ---
    st.sidebar.markdown(f"## 👤 {me['username']}")
    st.sidebar.caption(f"Role: {me.get('role','user')} | Team: {me.get('favorite_team')}")
    st.sidebar.divider()
    
    bal = me['balance']
    color = "#4ade80" if bal >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:2rem; font-weight:800; color:{color};'>{fmt_yen(bal)}</div>", unsafe_allow_html=True)
    st.sidebar.caption("Current Balance")
    
    if my_stats['potential_profit'] > 0:
        st.sidebar.markdown(f"""
        <div class="potential-box">
            <div style="font-size:0.8rem; opacity:0.8; text-transform:uppercase;">Potential Win</div>
            <div style="font-size:1.5rem; line-height:1.2;">+{fmt_yen(my_stats['potential_profit'])}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.sidebar.divider()
    
    if st.sidebar.button("🔄 Update Data"):
        with st.spinner("Talking to Premier League..."):
            tk = conf.get("FOOTBALL_DATA_API_TOKEN") or st.secrets.get("api_token")
            ok, msg = sync_data_process(tk, conf.get("API_FOOTBALL_SEASON", "2024"))
            if ok:
                st.toast(msg, icon="✅")
                time.sleep(1)
                st.rerun()
            else:
                st.error(msg)
    
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None
        st.rerun()

    # --- Tabs ---
    tabs = st.tabs(["📊 Dashboard", "⚽ Matches", "📜 History", "🔴 Live", "🏆 Standings", "🛠 Admin"])

    with tabs[0]:
        st.markdown(f"#### 👋 Hi, {me['username']}")
        st.markdown('<div class="kpi-container">', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>Win Rate</div><div class='kpi-value'>{my_stats['win_rate']:.1f}%</div></div>", unsafe_allow_html=True)
        with c2: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>Wins</div><div class='kpi-value'>{my_stats['wins']} / {my_stats['total_bets']}</div></div>", unsafe_allow_html=True)
        with c3: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>Live Profit</div><div class='kpi-value' style='color:{'#4ade80' if my_stats['live_profit']>=0 else '#f87171'}'>{fmt_yen(my_stats['live_profit'])}</div></div>", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
        if my_stats['best_teams']:
            st.markdown("##### 🎯 Your Sniping Teams")
            for tm, rate, w, t in my_stats['best_teams']:
                st.markdown(f"""
                <div class="team-stat-row">
                    <div class="bold-text">{tm}</div>
                    <div style="text-align:right;">
                        <span style="color:#4ade80; font-weight:bold;">{rate*100:.0f}%</span>
                        <span class="subtle"> ({w}/{t} wins)</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

    with tabs[1]:
        # ★ ここで安全にパース
        curr_gw = parse_gw_number(conf.get("current_gw", "1"))
        
        st.markdown(f"#### Gameweek {curr_gw}")
        matches_res = run_db_query(lambda: supabase.table("matches").select("*").eq("gameweek", curr_gw).order("kickoff_time").execute())
        matches = matches_res.data if matches_res else []
        if not matches:
            st.warning("No matches scheduled for this Gameweek.")
        else:
            for m in matches:
                render_match_card(m, me, users, conf)

    with tabs[2]:
        st.markdown("#### Betting History")
        hist_res = run_db_query(lambda: supabase.table("bets").select("*, matches(home_team, away_team, kickoff_time)").eq("user_id", me['user_id']).order("created_at", desc=True).limit(50).execute())
        hist = hist_res.data if hist_res else []
        if hist:
            for h in hist:
                m = h['matches']
                res = h['status']
                pnl = 0
                bg_color = "rgba(255,255,255,0.05)"
                if res == "WON":
                    pnl = int(h['stake'] * h['odds_at_bet']) - h['stake']
                    bg_color = "rgba(74, 222, 128, 0.1)"
                elif res == "LOST":
                    pnl = -h['stake']
                    bg_color = "rgba(248, 113, 113, 0.1)"
                
                st.markdown(f"""
                <div style="background:{bg_color}; padding:10px; border-radius:8px; margin-bottom:8px; border:1px solid rgba(255,255,255,0.05); display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <div style="font-size:0.8rem; color:#9ca3af;">{to_jst_str(h['created_at'], '%m/%d')} | {m.get('home_team')} vs {m.get('away_team')}</div>
                        <div style="font-weight:bold;">PICK: {h['choice']} <span style="font-weight:normal; font-size:0.9em;">(@{h['odds_at_bet']})</span></div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:0.8rem;">{res}</div>
                        <div style="font-weight:bold; color:{'#4ade80' if pnl>=0 else '#f87171'}">{fmt_yen(pnl)}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No betting history found.")

    with tabs[3]:
        st.markdown("#### 🔴 Live Action")
        live_matches = [m for m in matches if m['status'] in ['IN_PLAY', 'PAUSED']] if 'matches' in locals() else []
        if not live_matches:
            st.info("No live matches right now.")
        else:
            for m in live_matches:
                st.markdown(f"**{m['home_team']} {m['home_score']} - {m['away_score']} {m['away_team']}**")
        
        if my_stats['live_profit'] != 0:
            cls = "live-plus" if my_stats['live_profit'] > 0 else "live-minus"
            st.markdown(f"""
            <div style="text-align:center; padding:20px; border:1px dashed rgba(255,255,255,0.2); border-radius:12px; margin-top:20px;">
                <div class="subtle">Projected Profit from Live Games</div>
                <div class="{cls}" style="font-size:3rem; font-weight:900;">{fmt_yen(my_stats['live_profit'])}</div>
            </div>
            """, unsafe_allow_html=True)

    with tabs[4]:
        st.markdown("#### 🏆 Leaderboard")
        ranked_users = sorted(users, key=lambda x: x['balance'], reverse=True)
        for idx, u in enumerate(ranked_users):
            is_me = (u['user_id'] == me['user_id'])
            bg = "rgba(255,255,255,0.1)" if is_me else "transparent"
            st.markdown(f"""
            <div style="background:{bg}; padding:12px; border-radius:8px; display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; border-bottom:1px solid rgba(255,255,255,0.05);">
                <div style="display:flex; align-items:center; gap:10px;">
                    <div style="font-size:1.5rem; font-weight:bold; color:#6b7280; width:30px;">{idx+1}</div>
                    <div>
                        <div style="font-weight:bold; font-size:1.1rem;">{u['username']}</div>
                        <div class="subtle">{u.get('favorite_team','-')}</div>
                    </div>
                </div>
                <div style="font-size:1.2rem; font-weight:bold; color:{'#4ade80' if u['balance']>=0 else '#f87171'}">
                    {fmt_yen(u['balance'])}
                </div>
            </div>
            """, unsafe_allow_html=True)

    with tabs[5]:
        if me['role'] == 'admin':
            st.markdown("#### 🛠 Admin Console")
            with st.expander("⚙️ System Config"):
                config_df = pd.DataFrame([{"key": k, "value": v} for k, v in conf.items()])
                edited_df = st.data_editor(config_df, num_rows="dynamic", key="conf_editor")
                if st.button("Save Config"):
                    new_conf = edited_df.to_dict(orient="records")
                    run_db_query(lambda: supabase.table("app_config").upsert(new_conf).execute())
                    st.success("Config Saved!")
                    time.sleep(1)
                    st.rerun()

            with st.expander("📝 Manual Odds Override"):
                mid_input = st.number_input("Match ID", value=0)
                c1, c2, c3 = st.columns(3)
                nh = c1.number_input("Home Odds", 0.0)
                nd = c2.number_input("Draw Odds", 0.0)
                na = c3.number_input("Away Odds", 0.0)
                if st.button("Update Odds"):
                    run_db_query(lambda: supabase.table("matches").update({
                        "odds_home": nh, "odds_draw": nd, "odds_away": na, "odds_locked": True
                    }).eq("match_id", mid_input).execute())
                    st.success("Odds Updated & Locked.")
        else:
            st.error("Admin Access Required.")

if __name__ == "__main__":
    main()
