import streamlit as st
import pandas as pd
import requests
import datetime
import time
from datetime import timedelta, timezone
from supabase import create_client

# ==============================================================================
# 0. 初期設定
# ==============================================================================
st.set_page_config(page_title="Premier Picks V2.1", layout="wide", page_icon="⚽")
JST = timezone(timedelta(hours=9), 'JST')

# デザイン定義
st.markdown("""
<style>
.block-container { padding-top: 3.5rem; padding-bottom: 5rem; max-width: 1000px; }
.app-card {
    border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 16px;
    background: linear-gradient(145deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%);
    margin-bottom: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.2);
}
.kpi-box {
    border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; padding: 12px;
    background: rgba(0,0,0,0.2); text-align: center;
}
.kpi-label { font-size: 0.75rem; color: #aaa; }
.kpi-val { font-size: 1.4rem; font-weight: bold; }
.potential-box {
    margin-top: 15px; padding: 10px; border-radius: 8px;
    background: rgba(34, 197, 94, 0.15); border: 1px solid rgba(34, 197, 94, 0.4);
    color: #4ade80; text-align: center; font-weight: bold;
}
.match-time { font-family: monospace; color: #a5b4fc; font-size: 0.9rem; }
.status-badge {
    background: #374151; color: #d1d5db; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem;
}
.avatar {
    display: inline-flex; align-items: center; justify-content: center;
    width: 24px; height: 24px; border-radius: 50%; font-size: 0.7rem; font-weight: bold; color: white; margin-right: 5px;
}
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. データアクセス層
# ==============================================================================
@st.cache_resource
def get_supabase():
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except: return None

supabase = get_supabase()

def fetch_all_data():
    """全データを一括取得"""
    try:
        bets = pd.DataFrame(supabase.table("bets").select("*").execute().data)
        odds = pd.DataFrame(supabase.table("odds").select("*").execute().data)
        results = pd.DataFrame(supabase.table("result").select("*").execute().data)
        bm_log = pd.DataFrame(supabase.table("bm_log").select("*").execute().data)
        users = pd.DataFrame(supabase.table("users").select("*").execute().data)
        config = pd.DataFrame(supabase.table("config").select("*").execute().data)
        return bets, odds, results, bm_log, users, config
    except:
        # エラー時は空DFを返す
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_api_token(config_df):
    token = st.secrets.get("api_token")
    if token: return token
    if not config_df.empty:
        row = config_df[config_df['key'] == 'FOOTBALL_DATA_API_TOKEN']
        if not row.empty: return row.iloc[0]['value']
    return ""

# ==============================================================================
# 2. ロジックコア
# ==============================================================================

def calculate_stats(bets_df, bm_log_df, users_df):
    """ゼロサム収支計算"""
    if users_df.empty: return {}
    user_stats = {u: {'balance': 0, 'wins': 0, 'total': 0, 'potential': 0} for u in users_df['username'].unique()}
    
    bm_map = {} 
    if not bm_log_df.empty:
        for _, row in bm_log_df.iterrows():
            bm_map[str(row['gw'])] = row['bookmaker']

    if bets_df.empty: return user_stats

    for _, b in bets_df.iterrows():
        p_user = b['user']
        if p_user not in user_stats: continue
        
        status = str(b.get('result', '')).upper()
        # status列もチェック (SETTLED対応)
        is_settled = (status in ['WIN', 'LOSE'])
        
        stake = float(b['stake']) if b['stake'] else 0
        odds = float(b['odds']) if b['odds'] else 1.0
        gw = str(b['gw'])
        bm_user = bm_map.get(gw)

        if is_settled:
            user_stats[p_user]['total'] += 1
            pnl = 0
            if status == 'WIN':
                user_stats[p_user]['wins'] += 1
                pnl = (stake * odds) - stake
            else:
                pnl = -stake
            
            user_stats[p_user]['balance'] += int(pnl)
            
            # BM反映
            if bm_user and bm_user in user_stats and bm_user != p_user:
                user_stats[bm_user]['balance'] -= int(pnl)
        else:
            # 未確定
            pot_win = (stake * odds) - stake
            user_stats[p_user]['potential'] += int(pot_win)

    return user_stats

def determine_current_gw(results_df):
    """
    【修正版】現在時刻以降で、まだ終わっていない最初の試合のGWを採用
    """
    if results_df.empty: return "GW1"
    
    # 日付変換
    results_df['dt'] = pd.to_datetime(results_df['utc_kickoff'], errors='coerce', utc=True)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    
    # まだ終わっていない試合 (FINISHED以外) を日付順にソート
    # ※ステータスが SCHEDULED, TIMED, IN_PLAY, PAUSED のもの
    active_matches = results_df[
        (results_df['status'] != 'FINISHED') & 
        (results_df['dt'] > (now_utc - timedelta(hours=4))) # 念のため4時間前以降
    ].sort_values('dt')
    
    if not active_matches.empty:
        return active_matches.iloc[0]['gw']
    
    # 全部終わってるなら最新のGW
    return results_df.sort_values('dt', ascending=False).iloc[0]['gw']

def sync_with_api(api_token):
    """API同期: Resultテーブルを更新"""
    if not api_token: return False, "Token missing"
    headers = {'X-Auth-Token': api_token}
    url = "https://api.football-data.org/v4/competitions/PL/matches?season=2024"
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200: return False, f"API Error {res.status_code}"
        
        matches = res.json().get('matches', [])
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
            
        # 100件ずつ
        for i in range(0, len(upserts), 100):
            supabase.table("result").upsert(upserts[i:i+100]).execute()
        return True, f"Synced {len(upserts)} matches"
    except Exception as e:
        return False, str(e)

# ==============================================================================
# 3. メインアプリ
# ==============================================================================
def main():
    if not supabase: st.error("DB Connection Error"); st.stop()
    
    # データ取得
    bets, odds, results, bm_log, users, config = fetch_all_data()
    
    # ログイン
    if 'user' not in st.session_state: st.session_state['user'] = None
    if not st.session_state['user']:
        st.sidebar.title("🔐 Login")
        u_list = users['username'].tolist() if not users.empty else []
        name = st.sidebar.selectbox("User", u_list)
        pw = st.sidebar.text_input("Pass", type="password")
        if st.sidebar.button("Login"):
            user_row = users[users['username'] == name]
            if not user_row.empty and str(user_row.iloc[0]['password']) == pw:
                st.session_state['user'] = user_row.iloc[0].to_dict()
                st.rerun()
            else:
                st.error("Invalid Login")
        st.stop()
        
    me = st.session_state['user']
    api_token = get_api_token(config)
    
    # 自動判定
    current_gw = determine_current_gw(results)
    stats = calculate_stats(bets, bm_log, users)
    my_stats = stats.get(me['username'], {'balance':0, 'wins':0, 'total':0, 'potential':0})

    # --- Sidebar ---
    st.sidebar.markdown(f"## 👤 {me['username']}")
    st.sidebar.caption(f"Team: {me.get('team','-')}")
    st.sidebar.divider()
    
    bal = my_stats['balance']
    col = "#4ade80" if bal >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:2rem;font-weight:800;color:{col}'>{fmt_yen(bal)}</div>", unsafe_allow_html=True)
    st.sidebar.caption("Total P&L")
    
    if my_stats['potential'] > 0:
        st.sidebar.markdown(f"""
        <div class="potential-box">
            <div style="font-size:0.8rem;opacity:0.8">PENDING POTENTIAL</div>
            <div style="font-size:1.4rem">+{fmt_yen(my_stats['potential'])}</div>
        </div>
        """, unsafe_allow_html=True)

    st.sidebar.divider()
    if st.sidebar.button("🔄 Sync API"):
        with st.spinner("Talking to PL..."):
            ok, msg = sync_with_api(api_token)
            if ok: st.success(msg); time.sleep(1); st.rerun()
            else: st.error(msg)
    
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None; st.rerun()

    # --- Tabs ---
    tabs = st.tabs(["📊 Dashboard", "⚽ Matches", "📜 History", "🏆 Standings"])
    
    # [1] Dashboard
    with tabs[0]:
        st.markdown(f"#### 👋 Hi, {me['username']}")
        win_rate = (my_stats['wins'] / my_stats['total'] * 100) if my_stats['total'] else 0
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>Win Rate</div><div class='kpi-val'>{win_rate:.1f}%</div></div>", unsafe_allow_html=True)
        with c2: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>Wins</div><div class='kpi-val'>{my_stats['wins']}/{my_stats['total']}</div></div>", unsafe_allow_html=True)
        with c3: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>Current GW</div><div class='kpi-val'>{current_gw}</div></div>", unsafe_allow_html=True)

    # [2] Matches
    with tabs[1]:
        # GWリスト作成（数値順ソート）
        gw_list = []
        if not results.empty:
            gw_unique = results['gw'].unique()
            gw_list = sorted(gw_unique, key=lambda x: int(x.replace('GW','')) if 'GW' in str(x) else 0)
        
        idx = gw_list.index(current_gw) if current_gw in gw_list else 0
        sel_gw = st.selectbox("Gameweek", gw_list, index=idx)
        
        st.markdown(f"#### {sel_gw} Fixtures")
        
        # 【修正】Result(日程)を正としてループし、Oddsを紐づける
        target_matches = results[results['gw'] == sel_gw].sort_values('utc_kickoff')
        
        if target_matches.empty:
            st.info("No matches found.")
        else:
            for _, m in target_matches.iterrows():
                mid = m['match_id']
                kickoff = to_jst_str(m['utc_kickoff'])
                score = f"{int(m['home_score'])} - {int(m['away_score'])}" if pd.notna(m['home_score']) else ""
                
                # オッズ取得
                o_row = odds[odds['match_id'] == mid]
                oh = o_row.iloc[0]['home_win'] if not o_row.empty else 0
                od = o_row.iloc[0]['draw'] if not o_row.empty else 0
                oa = o_row.iloc[0]['away_win'] if not o_row.empty else 0
                
                # カード表示
                with st.container():
                    st.markdown(f"""
                    <div class="app-card">
                        <div style="display:flex; justify-content:space-between; margin-bottom:10px">
                            <span class="match-time">⏱ {kickoff}</span>
                            <span class="status-badge">{m['status']}</span>
                        </div>
                        <div style="display:grid; grid-template-columns: 1fr 20px 1fr; align-items:center; gap:10px; text-align:center; margin-bottom:15px">
                            <div>
                                <div style="font-weight:bold">{m['home']}</div>
                                <div style="color:#4ade80; font-weight:bold">{oh if oh else '-'}</div>
                            </div>
                            <div style="color:#888">vs</div>
                            <div>
                                <div style="font-weight:bold">{m['away']}</div>
                                <div style="color:#4ade80; font-weight:bold">{oa if oa else '-'}</div>
                            </div>
                        </div>
                        <div style="text-align:center; font-size:1.2rem; font-weight:bold; letter-spacing:2px">
                            {score}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # ベット機能
                    if m['status'] not in ['IN_PLAY', 'FINISHED', 'PAUSED']:
                        if not bets.empty:
                            my_bet = bets[(bets['match_id'] == mid) & (bets['user'] == me['username'])]
                        else:
                            my_bet = pd.DataFrame()
                        
                        if not my_bet.empty:
                            st.info(f"✅ Pick: **{my_bet.iloc[0]['pick']}**")
                        elif oh > 0: # オッズがある場合のみ
                            with st.form(key=f"b_{mid}"):
                                c1, c2, c3 = st.columns([3, 2, 2])
                                opts = [f"HOME ({oh})", f"DRAW ({od})", f"AWAY ({oa})"]
                                ch = c1.selectbox("Pick", opts, label_visibility="collapsed")
                                stk = c2.number_input("¥", 100, 10000, 1000, 100, label_visibility="collapsed")
                                if c3.form_submit_button("BET", use_container_width=True):
                                    tgt = "HOME" if "HOME" in ch else ("DRAW" if "DRAW" in ch else "AWAY")
                                    oval = float(oh if tgt=="HOME" else (od if tgt=="DRAW" else oa))
                                    
                                    key = f"{sel_gw}:{me['username']}:{mid}"
                                    supabase.table("bets").upsert({
                                        "key": key, "gw": sel_gw, "user": me['username'],
                                        "match_id": mid, "match": f"{m['home']} vs {m['away']}",
                                        "pick": tgt, "stake": stk, "odds": oval,
                                        "placed_at": datetime.datetime.now().isoformat(),
                                        "status": "OPEN", "result": ""
                                    }).execute()
                                    st.success("Bet Placed!")
                                    st.rerun()
                        else:
                            st.caption("Odds not available yet.")

    # [3] History (Global)
    with tabs[2]:
        st.markdown("#### Betting History (All Users)")
        if not bets.empty:
            # 時系列ソート
            hist = bets.sort_values('placed_at', ascending=False)
            
            for _, b in hist.iterrows():
                is_me = (b['user'] == me['username'])
                # デザイン分岐
                bg = "rgba(255,255,255,0.08)" if is_me else "rgba(255,255,255,0.02)"
                
                res = b['result'] if b['result'] else "PENDING"
                col = "#4ade80" if res == 'WIN' else ("#f87171" if res == 'LOSE' else "#aaa")
                
                # アバター色
                av_col = "#3b82f6"
                if b['user'] == 'Toshiya': av_col = "#ef4444"
                elif b['user'] == 'Koki': av_col = "#fbbf24"
                
                pnl_str = ""
                if res == 'WIN':
                    p = (float(b['stake']) * float(b['odds'])) - float(b['stake'])
                    pnl_str = f"+{fmt_yen(p)}"
                elif res == 'LOSE':
                    pnl_str = f"-{fmt_yen(b['stake'])}"
                
                st.markdown(f"""
                <div style="background:{bg}; padding:10px; margin-bottom:8px; border-radius:6px; border-left:3px solid {col}">
                    <div style="display:flex; justify-content:space-between; align-items:center">
                        <div style="display:flex; align-items:center">
                            <div class="avatar" style="background:{av_col}">{b['user'][0]}</div>
                            <span style="font-weight:{'bold' if is_me else 'normal'}">{b['user']}</span>
                        </div>
                        <span style="font-size:0.8rem; color:#888">{to_jst_str(b['placed_at'])}</span>
                    </div>
                    <div style="margin-top:6px; display:flex; justify-content:space-between">
                        <span>
                            <span style="color:#aaa; font-size:0.8rem">{b['gw']}</span>
                            {b['match']} <span style="font-weight:bold">[{b['pick']}]</span>
                        </span>
                        <span style="font-weight:bold; color:{col}">{pnl_str}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No history yet.")

    # [4] Standings
    with tabs[3]:
        st.markdown("#### 🏆 Leaderboard")
        rank = []
        for u, s in stats.items():
            rank.append({"user": u, "balance": s['balance']})
        rank.sort(key=lambda x: x['balance'], reverse=True)
        
        for i, r in enumerate(rank):
            is_me = (r['user'] == me['username'])
            bg = "rgba(255,255,255,0.1)" if is_me else "transparent"
            st.markdown(f"""
            <div style="background:{bg}; padding:10px; border-radius:8px; display:flex; justify-content:space-between; margin-bottom:5px; border-bottom:1px solid rgba(255,255,255,0.05)">
                <div><span style="color:#888; font-weight:bold; width:20px; display:inline-block">{i+1}.</span> {r['user']}</div>
                <div style="font-weight:bold; color:{'#4ade80' if r['balance']>=0 else '#f87171'}">{fmt_yen(r['balance'])}</div>
            </div>
            """, unsafe_allow_html=True)

# Utils
def to_jst_str(iso_str):
    if not iso_str: return "-"
    try:
        dt = pd.to_datetime(iso_str)
        if dt.tz is None: dt = dt.tz_localize('UTC')
        return dt.tz_convert(JST).strftime('%m/%d %H:%M')
    except: return str(iso_str)

def fmt_yen(n):
    return f"¥{int(n):,}"

if __name__ == "__main__":
    main()
