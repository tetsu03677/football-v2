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
st.set_page_config(page_title="Premier Picks V2.2", layout="wide", page_icon="⚽")
JST = timezone(timedelta(hours=9), 'JST')

st.markdown("""
<style>
/* 全体レイアウト */
.block-container { padding-top: 3.5rem; padding-bottom: 5rem; max-width: 1000px; }

/* カードデザイン */
.app-card {
    border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 16px;
    background: linear-gradient(145deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%);
    margin-bottom: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.2);
}

/* BMパネル (ダッシュボード用) */
.bm-panel {
    border: 1px solid rgba(251, 191, 36, 0.4); border-radius: 12px; padding: 20px;
    background: rgba(251, 191, 36, 0.1); text-align: center; margin-bottom: 20px;
}
.bm-label { font-size: 0.9rem; color: #fbbf24; letter-spacing: 2px; text-transform: uppercase; }
.bm-name { font-size: 2rem; font-weight: 800; color: #fff; margin-top: 5px; }
.gw-tag { background: #fbbf24; color: #000; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; vertical-align: middle; margin-right: 10px; }

/* KPIボックス */
.kpi-box {
    border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; padding: 12px;
    background: rgba(0,0,0,0.2); text-align: center;
}
.kpi-label { font-size: 0.75rem; color: #aaa; }
.kpi-val { font-size: 1.4rem; font-weight: bold; }

/* 履歴カード (シンプル版) */
.hist-card {
    border-left: 4px solid #555; background: rgba(255,255,255,0.03); 
    padding: 12px; margin-bottom: 8px; border-radius: 4px;
}
.hist-win { border-left-color: #4ade80; background: rgba(74, 222, 128, 0.05); }
.hist-lose { border-left-color: #f87171; background: rgba(248, 113, 113, 0.05); }

/* その他 */
.match-time { font-family: monospace; color: #a5b4fc; font-size: 0.9rem; }
.status-badge { background: #374151; color: #d1d5db; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; }
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
    """全データを一括取得 (キャッシュせず常に最新を推奨)"""
    try:
        bets = pd.DataFrame(supabase.table("bets").select("*").execute().data)
        odds = pd.DataFrame(supabase.table("odds").select("*").execute().data)
        results = pd.DataFrame(supabase.table("result").select("*").execute().data)
        bm_log = pd.DataFrame(supabase.table("bm_log").select("*").execute().data)
        users = pd.DataFrame(supabase.table("users").select("*").execute().data)
        config = pd.DataFrame(supabase.table("config").select("*").execute().data)
        return bets, odds, results, bm_log, users, config
    except:
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
    """収支計算"""
    if users_df.empty: return {}
    user_stats = {u: {'balance': 0, 'wins': 0, 'total': 0, 'potential': 0} for u in users_df['username'].unique()}
    
    # BMマップ (GW -> User)
    bm_map = {} 
    if not bm_log_df.empty:
        for _, row in bm_log_df.iterrows():
            # gwカラムが "GW7" でも "7" でも対応
            gw_str = str(row['gw'])
            gw_num = "".join([c for c in gw_str if c.isdigit()])
            if gw_num: bm_map[f"GW{gw_num}"] = row['bookmaker']

    if bets_df.empty: return user_stats

    for _, b in bets_df.iterrows():
        p_user = b['user']
        if p_user not in user_stats: continue
        
        status = str(b.get('result', '')).upper()
        is_settled = (status in ['WIN', 'LOSE'])
        
        stake = float(b['stake']) if b['stake'] else 0
        odds = float(b['odds']) if b['odds'] else 1.0
        
        # GW正規化
        gw_raw = str(b['gw'])
        gw_num = "".join([c for c in gw_raw if c.isdigit()])
        gw_key = f"GW{gw_num}"
        
        bm_user = bm_map.get(gw_key)

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
            pot_win = (stake * odds) - stake
            user_stats[p_user]['potential'] += int(pot_win)

    return user_stats, bm_map

def determine_current_gw(results_df):
    """
    現在時刻を基準にGWを判定。
    GW38問題を防ぐため、未来の試合があるGWを優先する。
    """
    if results_df.empty: return "GW1"
    
    # 日付変換
    results_df['dt'] = pd.to_datetime(results_df['utc_kickoff'], errors='coerce', utc=True)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    
    # 1. これから行われる、または現在進行中の試合を探す
    # (Kickoffが現在 - 4時間 より未来)
    active = results_df[results_df['dt'] > (now_utc - timedelta(hours=4))].sort_values('dt')
    
    if not active.empty:
        return active.iloc[0]['gw']
    
    # 2. 未来の試合が全くない場合（シーズン終了など） -> データの最後を採用
    # ただし、GW38に飛ばないよう、今日の日付に最も近い過去の試合を見る
    past = results_df[results_df['dt'] <= now_utc].sort_values('dt', ascending=False)
    if not past.empty:
        return past.iloc[0]['gw']
        
    return "GW1"

def sync_with_api(api_token):
    """API同期"""
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
            
        chunk = 100
        for i in range(0, len(upserts), chunk):
            supabase.table("result").upsert(upserts[i:i+chunk]).execute()
        return True, f"Synced {len(upserts)} matches"
    except Exception as e:
        return False, str(e)

# ==============================================================================
# 3. メインアプリ
# ==============================================================================
def main():
    if not supabase: st.error("DB Connection Error"); st.stop()
    
    # -----------------------------------
    # 1. ログイン & 初期データロード
    # -----------------------------------
    bets, odds, results, bm_log, users, config = fetch_all_data()
    
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

    # -----------------------------------
    # 2. 自動Sync (セッション開始時のみ)
    # -----------------------------------
    if 'auto_synced' not in st.session_state:
        with st.spinner("🚀 Initializing & Syncing Data..."):
            sync_with_api(api_token)
        st.session_state['auto_synced'] = True
        # データ再取得
        bets, odds, results, bm_log, users, config = fetch_all_data()
        st.rerun() # リフレッシュして最新データを表示

    # -----------------------------------
    # 3. 計算処理
    # -----------------------------------
    current_gw = determine_current_gw(results)
    stats, bm_map = calculate_stats(bets, bm_log, users)
    my_stats = stats.get(me['username'], {'balance':0, 'wins':0, 'total':0, 'potential':0})
    
    # 現在のBM特定
    current_bm = bm_map.get(current_gw, "未定")

    # -----------------------------------
    # 4. サイドバー
    # -----------------------------------
    st.sidebar.markdown(f"## 👤 {me['username']}")
    st.sidebar.caption(f"Team: {me.get('team','-')}")
    st.sidebar.divider()
    
    bal = my_stats['balance']
    col = "#4ade80" if bal >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:2rem;font-weight:800;color:{col}'>{fmt_yen(bal)}</div>", unsafe_allow_html=True)
    st.sidebar.caption("Total P&L")
    
    if my_stats['potential'] > 0:
        st.sidebar.markdown(f"""
        <div style="margin-top:15px;padding:10px;border-radius:8px;background:rgba(34,197,94,0.15);border:1px solid #4ade80;color:#4ade80;text-align:center;font-weight:bold">
            <div style="font-size:0.8rem;opacity:0.8">PENDING POTENTIAL</div>
            <div style="font-size:1.4rem">+{fmt_yen(my_stats['potential'])}</div>
        </div>
        """, unsafe_allow_html=True)

    st.sidebar.divider()
    if st.sidebar.button("🔄 Manual Sync"):
        with st.spinner("Syncing..."):
            sync_with_api(api_token)
        st.rerun()
        
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None; st.rerun()

    # -----------------------------------
    # 5. メイン画面 (Tabs)
    # -----------------------------------
    tabs = st.tabs(["📊 Dashboard", "⚽ Matches", "📜 History", "🏆 Standings"])
    
    # [1] Dashboard
    with tabs[0]:
        # BMパネル (ご要望の視覚的明示)
        st.markdown(f"""
        <div class="bm-panel">
            <div class="bm-label"><span class="gw-tag">{current_gw}</span>BOOKMAKER</div>
            <div class="bm-name">{current_bm}</div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown(f"#### 👋 Hi, {me['username']}")
        win_rate = (my_stats['wins'] / my_stats['total'] * 100) if my_stats['total'] else 0
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>Win Rate</div><div class='kpi-val'>{win_rate:.1f}%</div></div>", unsafe_allow_html=True)
        with c2: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>Wins</div><div class='kpi-val'>{my_stats['wins']}/{my_stats['total']}</div></div>", unsafe_allow_html=True)
        with c3: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>Role</div><div class='kpi-val'>{me['role']}</div></div>", unsafe_allow_html=True)

    # [2] Matches
    with tabs[1]:
        # GW選択 (数値順)
        gw_list = []
        if not results.empty:
            gw_unique = results['gw'].unique()
            gw_list = sorted(gw_unique, key=lambda x: int(x.replace('GW','')) if 'GW' in str(x) else 0)
        
        idx = gw_list.index(current_gw) if current_gw in gw_list else 0
        sel_gw = st.selectbox("Gameweek", gw_list, index=idx)
        
        st.markdown(f"#### {sel_gw} Fixtures")
        
        target_matches = results[results['gw'] == sel_gw].sort_values('utc_kickoff')
        
        if target_matches.empty:
            st.info("No matches.")
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
                    
                    # ベットフォーム
                    if m['status'] not in ['IN_PLAY', 'FINISHED', 'PAUSED']:
                        if not bets.empty:
                            my_bet = bets[(bets['match_id'] == mid) & (bets['user'] == me['username'])]
                        else: my_bet = pd.DataFrame()
                        
                        if not my_bet.empty:
                            st.info(f"✅ Pick: **{my_bet.iloc[0]['pick']}**")
                        elif oh > 0:
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
                                    st.success("Bet Placed!"); time.sleep(1); st.rerun()

    # [3] History (Simple Cards)
    with tabs[2]:
        st.markdown("#### Betting History (My Bets)")
        if not bets.empty:
            # 自分のベットのみに絞る（シンプル化）
            my_hist = bets[bets['user'] == me['username']].sort_values('placed_at', ascending=False)
            
            for _, b in my_hist.iterrows():
                res = b['result'] if b['result'] else "PENDING"
                cls = "hist-card"
                pnl_str = "PENDING"
                
                if res == 'WIN':
                    cls += " hist-win"
                    p = (float(b['stake']) * float(b['odds'])) - float(b['stake'])
                    pnl_str = f"+{fmt_yen(p)}"
                elif res == 'LOSE':
                    cls += " hist-lose"
                    pnl_str = f"-{fmt_yen(b['stake'])}"
                
                st.markdown(f"""
                <div class="{cls}">
                    <div style="display:flex; justify-content:space-between; margin-bottom:4px">
                        <span style="font-size:0.8rem; color:#aaa">{to_jst_str(b['placed_at'])} | {b['gw']}</span>
                        <span style="font-weight:bold">{pnl_str}</span>
                    </div>
                    <div style="font-weight:bold; font-size:1rem">{b['match']}</div>
                    <div style="margin-top:4px">
                        Picked: <span style="font-weight:bold">{b['pick']}</span> <span style="font-size:0.9rem">(@{b['odds']})</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No history yet.")

    # [4] Standings
    with tabs[3]:
        st.markdown("#### 🏆 Leaderboard")
        rank = sorted([{"user": u, "balance": s['balance']} for u, s in stats.items()], key=lambda x: x['balance'], reverse=True)
        for i, r in enumerate(rank):
            bg = "rgba(255,255,255,0.1)" if r['user'] == me['username'] else "transparent"
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
