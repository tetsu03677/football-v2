import streamlit as st
import pandas as pd
import requests
import datetime
import time
import pytz
from datetime import timedelta, timezone
from supabase import create_client

# ==============================================================================
# 0. システム設定 & CSS
# ==============================================================================
st.set_page_config(page_title="Premier Picks V2 Ultimate", layout="wide", page_icon="⚽")
JST = timezone(timedelta(hours=9), 'JST')

st.markdown("""
<style>
/* --- 全体レイアウト --- */
.block-container { padding-top: 3.5rem; padding-bottom: 6rem; max-width: 1000px; }

/* --- 旧アプリのデザイン踏襲 --- */
.app-card {
    border: 1px solid rgba(120,120,120,.25); border-radius: 12px; padding: 16px;
    background: rgba(255,255,255,.03); margin-bottom: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}
.subtle { color: rgba(255,255,255,.6); font-size: 0.85rem; }
.bold-text { font-weight: 700; color: #f3f4f6; }
.match-time { font-family: monospace; font-size: 0.9rem; color: #a5b4fc; }

/* --- KPIパネル --- */
.kpi-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
.kpi {
    flex: 1 1 100px; border: 1px solid rgba(120,120,120,.25); border-radius: 10px; padding: 12px;
    background: rgba(255,255,255,0.02); text-align: center;
}
.kpi .h { font-size: 0.75rem; color: rgba(255,255,255,.7); margin-bottom: 4px; }
.kpi .v { font-size: 1.3rem; font-weight: 700; }

/* --- 新機能: ポテンシャル利益 (GW特化) --- */
.potential-box {
    margin-top: 15px; padding: 12px; border-radius: 8px;
    background: rgba(34, 197, 94, 0.15); border: 1px solid rgba(34, 197, 94, 0.4);
    color: #4ade80; text-align: center; font-weight: bold;
    animation: pulse 2s infinite;
}
@keyframes pulse {
    0% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.4); }
    70% { box-shadow: 0 0 0 10px rgba(74, 222, 128, 0); }
    100% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0); }
}

/* --- バッジ類 --- */
.avatar-badge {
    display: inline-flex; align-items: center; justify-content: center;
    padding: 2px 8px; border-radius: 12px; font-size: 0.7rem; color: #fff;
    background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.1); margin-left: 4px;
}
.live-plus { color: #4ade80; text-shadow: 0 0 10px rgba(74, 222, 128, 0.3); }
.live-minus { color: #f87171; text-shadow: 0 0 10px rgba(248, 113, 113, 0.3); }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. データベース接続 & ユーティリティ
# ==============================================================================
@st.cache_resource(ttl=3600)
def get_supabase_client():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        client = create_client(url, key)
        try: client.postgrest.timeout = 20
        except: pass
        return client
    except Exception as e:
        st.error(f"System Error: {e}")
        return None

supabase = get_supabase_client()

def run_db_query(query_func, retries=3):
    for i in range(retries):
        try: return query_func()
        except Exception:
            if i == retries - 1: return None
            time.sleep(1)
    return None

def fmt_yen(n):
    if n is None: return "¥0"
    try: return f"¥{int(n):,}"
    except: return str(n)

def to_jst_str(iso_str, fmt='%m/%d %H:%M'):
    if not iso_str: return "-"
    try:
        dt = pd.to_datetime(iso_str)
        if dt.tz is None: dt = dt.tz_localize('UTC')
        return dt.tz_convert(JST).strftime(fmt)
    except: return str(iso_str)

def parse_gw(val):
    """'GW7' -> 7"""
    s = str(val).upper()
    nums = ''.join(filter(str.isdigit, s))
    return int(nums) if nums else 1

# ==============================================================================
# 2. スマート・ロジック (自動判定・同期・計算)
# ==============================================================================

def get_smart_current_gw():
    """
    【重要】現在時刻から最適なGWを自動判定する。
    1. DB内の全試合を日時順に取得
    2. 現在時刻より未来の試合を含む最初のGWを特定
    3. もし全試合終了していれば最終GW+1
    4. 特定したGWをConfigに保存して返す
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    
    # 全試合のスケジュール取得（軽量化のためカラム絞る）
    res = run_db_query(lambda: supabase.table("matches").select("gameweek, kickoff_time, status").order("kickoff_time").execute())
    matches = res.data if res else []
    
    detected_gw = 1
    if matches:
        # 未来の試合を探す
        future_matches = [m for m in matches if m['kickoff_time'] and pd.to_datetime(m['kickoff_time']) > (now_utc - timedelta(hours=2))]
        
        if future_matches:
            # 直近の未来の試合があるGW
            detected_gw = future_matches[0]['gameweek']
        else:
            # 全て終わっているなら最終GW
            detected_gw = matches[-1]['gameweek']

    # Configを更新（次回以降のために）
    run_db_query(lambda: supabase.table("app_config").upsert({"key": "current_gw", "value": str(detected_gw)}).execute())
    
    return detected_gw

def sync_data_logic(api_token, season="2024"):
    """
    データ同期処理。
    - APIから広範囲(前後21日)を取得
    - オッズロック時刻判定
    - 自動精算 (Settlement)
    """
    if not api_token: return False, "No Token"
    
    headers = {'X-Auth-Token': api_token}
    d_now = datetime.datetime.now()
    d_from = (d_now - timedelta(days=21)).strftime('%Y-%m-%d')
    d_to = (d_now + timedelta(days=21)).strftime('%Y-%m-%d')
    
    try:
        url = f"https://api.football-data.org/v4/competitions/PL/matches?dateFrom={d_from}&dateTo={d_to}"
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200: return False, f"API {res.status_code}"
        
        matches_data = res.json().get('matches', [])
        conf = get_config_map()
        lock_hours = float(conf.get('odds_lock_hours', 1.0))
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        upsert_list = []
        finished_ids = []
        
        for m in matches_data:
            kickoff = m['utcDate']
            k_dt = pd.to_datetime(kickoff)
            if k_dt.tz is None: k_dt = k_dt.tz_localize('UTC')
            
            # ロック判定
            hours_diff = (k_dt - now_utc).total_seconds() / 3600
            is_locked = (hours_diff <= lock_hours)
            
            row = {
                "match_id": m['id'],
                "season": season,
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
            
            # オッズ更新 (ロック前ならAPI採用)
            api_odds = m.get('odds', {})
            if not is_locked and api_odds.get('homeWin'):
                row["odds_home"] = api_odds.get('homeWin')
                row["odds_draw"] = api_odds.get('draw')
                row["odds_away"] = api_odds.get('awayWin')
                
            upsert_list.append(row)
            if m['status'] == 'FINISHED':
                finished_ids.append(m['id'])
                
        # 保存
        if upsert_list:
            run_db_query(lambda: supabase.table("matches").upsert(upsert_list).execute())
            
        # 精算 (FinishedかつPendingのもの)
        settled = 0
        if finished_ids:
            pending = run_db_query(lambda: supabase.table("bets").select("*").in_("match_id", finished_ids).eq("status", "PENDING").execute())
            if pending and pending.data:
                # 最新のマッチ情報を取得
                m_rows = run_db_query(lambda: supabase.table("matches").select("*").in_("match_id", finished_ids).execute()).data
                m_map = {x['match_id']: x for x in m_rows}
                
                for b in pending.data:
                    m = m_map.get(b['match_id'])
                    if not m or m['home_score'] is None: continue
                    
                    # 結果判定
                    actual = "DRAW"
                    if m['home_score'] > m['away_score']: actual = "HOME"
                    elif m['away_score'] > m['home_score']: actual = "AWAY"
                    
                    res_status = "WON" if b['choice'] == actual else "LOST"
                    
                    # 金額計算
                    profit = 0
                    if res_status == "WON":
                        profit = int(b['stake'] * b['odds_at_bet']) - b['stake']
                    else:
                        profit = -b['stake']
                        
                    # DB更新 (Status)
                    supabase.table("bets").update({"status": res_status}).eq("bet_id", b['bet_id']).execute()
                    
                    # ユーザー残高更新 (RPC)
                    supabase.rpc("increment_balance", {"p_user_id": b['user_id'], "p_amount": profit}).execute()
                    
                    # BMの残高更新 (Playerの逆)
                    # ※BM特定ロジックは簡略化のためGW固定とするが、本来はbm_historyを参照
                    bm_res = supabase.table("bm_history").select("user_id").eq("gameweek", m['gameweek']).eq("season", season).execute()
                    if bm_res and bm_res.data:
                        bm_id = bm_res.data[0]['user_id']
                        if bm_id != b['user_id']:
                            supabase.rpc("increment_balance", {"p_user_id": bm_id, "p_amount": -profit}).execute()
                            
                    settled += 1
                    
        return True, f"Synced: {len(upsert_list)} matches, Settled: {settled} bets"
        
    except Exception as e:
        return False, str(e)

def get_config_map():
    res = run_db_query(lambda: supabase.table("app_config").select("*").execute())
    if res and res.data:
        return {r['key']: r['value'] for r in res.data}
    return {}

def calculate_gw_potential(user_id, target_gw):
    """
    【重要】指定されたGWにおける「ポテンシャル利益」のみを計算する。
    条件: user_id一致, status=PENDING, match.gameweek=target_gw
    """
    # 結合クエリがSupabase pyで面倒なため、2段階で取得
    # 1. 対象GWのMatch IDを取得
    matches = run_db_query(lambda: supabase.table("matches").select("match_id").eq("gameweek", target_gw).execute())
    if not matches or not matches.data: return 0
    
    m_ids = [m['match_id'] for m in matches.data]
    
    # 2. その試合への自分のPENDINGベットを取得
    bets = run_db_query(lambda: supabase.table("bets").select("*").in_("match_id", m_ids).eq("user_id", user_id).eq("status", "PENDING").execute())
    
    potential = 0
    if bets and bets.data:
        for b in bets.data:
            odds = b['odds_at_bet'] or 1.0
            stake = b['stake']
            # 純粋な利益分
            potential += (stake * odds) - stake
            
    return int(potential)

def get_user_kpi(user_id):
    """ユーザーの通算成績"""
    bets = run_db_query(lambda: supabase.table("bets").select("*").eq("user_id", user_id).execute())
    if not bets or not bets.data: return {"win_rate":0, "total":0, "wins":0}
    
    finished = [b for b in bets.data if b['status'] in ['WON', 'LOST']]
    total = len(finished)
    wins = len([b for b in finished if b['status'] == 'WON'])
    
    return {
        "total": total,
        "wins": wins,
        "win_rate": (wins/total*100) if total else 0
    }

# ==============================================================================
# 3. UIコンポーネント
# ==============================================================================

def render_login(users):
    st.sidebar.markdown("### 🔐 Login")
    name = st.sidebar.selectbox("Username", [u['username'] for u in users])
    pw = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Enter Stadium 🏟️", type="primary"):
        u = next((x for x in users if x['username'] == name), None)
        if u and str(u.get('password')) == str(pw):
            st.session_state['user'] = u
            st.rerun()
        else:
            st.error("Auth Failed")

def render_match_card(m, me, users):
    mid = m['match_id']
    kickoff = to_jst_str(m['kickoff_time'])
    
    oh = m.get('odds_home') or '-'
    od = m.get('odds_draw') or '-'
    oa = m.get('odds_away') or '-'
    
    # 他人のベット情報取得
    bets_res = run_db_query(lambda: supabase.table("bets").select("*").eq("match_id", mid).execute())
    other_html = ""
    my_choice = None
    
    if bets_res and bets_res.data:
        for b in bets_res.data:
            if b['user_id'] == me['user_id']:
                my_choice = b['choice']
            else:
                uname = next((u['username'] for u in users if u['user_id'] == b['user_id']), "?")
                col = "#fbbf24" if b['choice']=='DRAW' else ("#ef4444" if b['choice']=='HOME' else "#3b82f6")
                other_html += f"<span class='avatar-badge' style='background:{col}cc' title='{uname}'>{uname[0]}:{b['choice'][0]}</span>"

    # カード描画
    st.markdown(f"""
    <div class="app-card">
        <div style="display:flex; justify-content:space-between; margin-bottom:8px">
            <span class="match-time">⏱ {kickoff}</span>
            <div>{other_html}</div>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 20px 1fr; align-items:center; gap:10px; margin-bottom:12px">
            <div style="text-align:center">
                <div class="bold-text">{m['home_team']}</div>
                <div style="color:#4ade80; font-weight:bold">{oh}</div>
            </div>
            <div style="text-align:center; color:#888; font-size:0.8rem">VS</div>
            <div style="text-align:center">
                <div class="bold-text">{m['away_team']}</div>
                <div style="color:#4ade80; font-weight:bold">{oa}</div>
            </div>
        </div>
        <div style="text-align:center">
            <span style="background:#374151; color:#9ca3af; padding:2px 8px; border-radius:4px; font-size:0.7rem">{m['status']}</span>
            {f"<span style='margin-left:10px; font-weight:bold'>{m['home_score']} - {m['away_score']}</span>" if m['status'] in ['IN_PLAY','FINISHED'] else ""}
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # ベット入力 (未確定かつロック前なら)
    if my_choice:
        st.info(f"✅ Pick: **{my_choice}**")
    elif m['status'] not in ['FINISHED', 'IN_PLAY']:
        with st.form(key=f"f_{mid}"):
            c1, c2, c3 = st.columns([3, 2, 2])
            opts = [f"HOME ({oh})", f"DRAW ({od})", f"AWAY ({oa})"]
            pick_lbl = c1.selectbox("Pick", opts, label_visibility="collapsed")
            stake = c2.number_input("¥", 100, 10000, 1000, 100, label_visibility="collapsed")
            if c3.form_submit_button("BET", use_container_width=True):
                tgt = "HOME" if "HOME" in pick_lbl else ("DRAW" if "DRAW" in pick_lbl else "AWAY")
                odds_val = float(oh if tgt=="HOME" else (od if tgt=="DRAW" else oa))
                
                supabase.table("bets").insert({
                    "user_id": me['user_id'], "match_id": mid, "choice": tgt,
                    "stake": stake, "odds_at_bet": odds_val, "status": "PENDING"
                }).execute()
                st.toast("Bet Placed!")
                time.sleep(0.5)
                st.rerun()
    else:
        st.write("🔒 Closed")

# ==============================================================================
# 4. メインアプリ
# ==============================================================================

def main():
    if not supabase: st.stop()
    
    # ユーザー取得
    users_res = run_db_query(lambda: supabase.table("users").select("*").execute())
    users = users_res.data if users_res else []
    
    # ログイン画面
    if 'user' not in st.session_state or not st.session_state['user']:
        render_login(users)
        st.stop()
        
    # ユーザー情報リフレッシュ
    me = next((u for u in users if u['user_id'] == st.session_state['user']['user_id']), None)
    if not me: st.session_state['user'] = None; st.rerun()
    
    # --- 自動同期 & GW判定 (初回のみ or 時間経過で) ---
    conf = get_config_map()
    
    # スマートGW判定 (DB内の最新状態から判定)
    smart_gw = get_smart_current_gw()
    
    # 現在のGWのポテンシャル計算
    pot_profit = calculate_gw_potential(me['user_id'], smart_gw)
    
    # KPI計算
    kpi = get_user_kpi(me['user_id'])

    # --- サイドバー ---
    st.sidebar.markdown(f"## 👤 {me['username']}")
    st.sidebar.caption(f"{me.get('favorite_team','-')}")
    st.sidebar.divider()
    
    # Balance
    bal = me['balance']
    col = "#4ade80" if bal >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:2rem; font-weight:800; color:{col}'>{fmt_yen(bal)}</div>", unsafe_allow_html=True)
    st.sidebar.caption("Total Balance")
    
    # Potential Profit (現在のGW限定)
    if pot_profit > 0:
        st.sidebar.markdown(f"""
        <div class="potential-box">
            <div style="font-size:0.8rem; text-transform:uppercase; opacity:0.8">GW{smart_gw} Potential</div>
            <div style="font-size:1.5rem; line-height:1.2">+{fmt_yen(pot_profit)}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.sidebar.divider()
    
    if st.sidebar.button("🔄 Sync Data"):
        tk = conf.get("FOOTBALL_DATA_API_TOKEN") or st.secrets.get("api_token")
        with st.spinner("Updating..."):
            ok, msg = sync_data_logic(tk, conf.get("API_FOOTBALL_SEASON","2024"))
            if ok: st.toast(msg); time.sleep(1); st.rerun()
            else: st.error(msg)
            
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None; st.rerun()

    # --- メインコンテンツ ---
    tabs = st.tabs(["📊 Dashboard", "⚽ Matches", "📜 History", "🔴 Live", "🏆 Standings", "🛠 Admin"])

    # Tab 1: Dashboard
    with tabs[0]:
        st.markdown(f"#### 👋 Hi, {me['username']}")
        st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(f"<div class='kpi'><div class='h'>Win Rate</div><div class='v'>{kpi['win_rate']:.1f}%</div></div>", unsafe_allow_html=True)
        with c2: st.markdown(f"<div class='kpi'><div class='h'>Wins</div><div class='v'>{kpi['wins']} / {kpi['total']}</div></div>", unsafe_allow_html=True)
        # GW収支 (簡易計算: PENDING除く)
        st.markdown('</div>', unsafe_allow_html=True)
        
        # 移行データ確認用: 最新の完了試合
        st.markdown("##### 🏁 Recent Results")
        recent = run_db_query(lambda: supabase.table("matches").select("*").eq("status", "FINISHED").order("kickoff_time", desc=True).limit(3).execute())
        if recent and recent.data:
            for m in recent.data:
                st.markdown(f"**GW{m['gameweek']}**: {m['home_team']} {m['home_score']}-{m['away_score']} {m['away_team']}")

    # Tab 2: Matches (Auto-Selected GW)
    with tabs[1]:
        # セレクトボックスでGW変更可能にするが、デフォルトはSmart GW
        all_gws = run_db_query(lambda: supabase.table("matches").select("gameweek").execute())
        gw_list = sorted(list(set([x['gameweek'] for x in (all_gws.data or [])]))) if all_gws else [1]
        
        # デフォルトインデックス設定
        try: def_idx = gw_list.index(smart_gw)
        except: def_idx = 0
        
        selected_gw = st.selectbox("Select Gameweek", gw_list, index=def_idx)
        st.markdown(f"#### Gameweek {selected_gw}")
        
        matches = run_db_query(lambda: supabase.table("matches").select("*").eq("gameweek", selected_gw).order("kickoff_time").execute())
        if matches and matches.data:
            for m in matches.data:
                render_match_card(m, me, users)
        else:
            st.info("No matches found.")

    # Tab 3: History
    with tabs[2]:
        st.markdown("#### Your Bets")
        # 履歴取得 (新しい順)
        hist = run_db_query(lambda: supabase.table("bets").select("*, matches(home_team, away_team, gameweek)").eq("user_id", me['user_id']).order("created_at", desc=True).limit(50).execute())
        if hist and hist.data:
            for b in hist.data:
                m = b['matches']
                res = b['status']
                pnl = 0
                bg = "rgba(255,255,255,0.05)"
                if res == "WON":
                    pnl = int(b['stake'] * b['odds_at_bet']) - b['stake']
                    bg = "rgba(74, 222, 128, 0.1)"
                elif res == "LOST":
                    pnl = -b['stake']
                    bg = "rgba(248, 113, 113, 0.1)"
                
                st.markdown(f"""
                <div style="background:{bg}; padding:8px; border-radius:8px; margin-bottom:8px; border:1px solid rgba(255,255,255,0.05); display:flex; justify-content:space-between; align-items:center">
                    <div>
                        <div style="font-size:0.75rem; color:#aaa">GW{m.get('gameweek')} | {m.get('home_team')} vs {m.get('away_team')}</div>
                        <div style="font-weight:bold">PICK: {b['choice']} <span class="subtle">(@{b['odds_at_bet']})</span></div>
                    </div>
                    <div style="text-align:right">
                        <div style="font-size:0.8rem">{res}</div>
                        <div style="font-weight:bold; color:{'#4ade80' if pnl>=0 else '#f87171'}">{fmt_yen(pnl)}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

    # Tab 4: Live
    with tabs[3]:
        st.markdown("#### 🔴 Live")
        # 進行中の試合
        live = run_db_query(lambda: supabase.table("matches").select("*").in_("status", ["IN_PLAY","PAUSED"]).execute())
        if live and live.data:
            for m in live.data:
                st.markdown(f"**{m['home_team']} {m['home_score']}-{m['away_score']} {m['away_team']}**")
        else:
            st.info("No live matches.")

    # Tab 5: Standings
    with tabs[4]:
        st.markdown("#### 🏆 Leaderboard")
        rank = sorted(users, key=lambda x: x['balance'], reverse=True)
        for i, u in enumerate(rank):
            bg = "rgba(255,255,255,0.1)" if u['user_id']==me['user_id'] else "transparent"
            st.markdown(f"""
            <div style="background:{bg}; padding:10px; border-radius:8px; display:flex; justify-content:space-between; margin-bottom:5px; border-bottom:1px solid rgba(255,255,255,0.05)">
                <div><span style="color:#888; font-weight:bold; width:20px; display:inline-block">{i+1}.</span> {u['username']}</div>
                <div style="font-weight:bold; color:{'#4ade80' if u['balance']>=0 else '#f87171'}">{fmt_yen(u['balance'])}</div>
            </div>
            """, unsafe_allow_html=True)

    # Tab 6: Admin
    with tabs[5]:
        if me['role']=='admin':
            st.markdown("#### Admin")
            if st.button("Force Settlement"):
                # 未実装だが枠だけ用意
                st.warning("Needs implementation")
        else:
            st.error("No Access")

if __name__ == "__main__":
    main()
