import streamlit as st
import pandas as pd
import requests
import datetime
import pytz
import uuid
from datetime import timedelta, timezone
from supabase import create_client

# ==============================================================================
# 0. 初期設定
# ==============================================================================
st.set_page_config(page_title="Premier Picks V2", layout="wide", page_icon="⚽")
JST = timezone(timedelta(hours=9), 'JST')

# スタイル定義 (旧アプリ踏襲 + 美化)
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
    """全テーブルのデータを取得してDataFrame化"""
    # 数百件程度なら全件取得でOK
    bets = pd.DataFrame(supabase.table("bets").select("*").execute().data)
    odds = pd.DataFrame(supabase.table("odds").select("*").execute().data)
    results = pd.DataFrame(supabase.table("result").select("*").execute().data)
    bm_log = pd.DataFrame(supabase.table("bm_log").select("*").execute().data)
    users = pd.DataFrame(supabase.table("users").select("*").execute().data)
    config = pd.DataFrame(supabase.table("config").select("*").execute().data)
    
    return bets, odds, results, bm_log, users, config

def get_api_token(config_df):
    """ConfigテーブルまたはSecretsからトークン取得"""
    # Secrets優先
    token = st.secrets.get("api_token")
    if token: return token
    # Configテーブル
    if not config_df.empty:
        row = config_df[config_df['key'] == 'FOOTBALL_DATA_API_TOKEN']
        if not row.empty: return row.iloc[0]['value']
    return ""

# ==============================================================================
# 2. ロジックコア (計算・判定)
# ==============================================================================

def calculate_stats(bets_df, bm_log_df, users_df):
    """
    ベット履歴とBM履歴から、全ユーザーの現在の収支を再計算する
    """
    # ユーザー初期化
    user_stats = {u: {'balance': 0, 'wins': 0, 'total': 0, 'potential': 0} for u in users_df['username'].unique()}
    
    # BMマップ作成: GW -> Bookmaker Name
    # gwカラムは "GW7" などの文字列
    bm_map = {} 
    if not bm_log_df.empty:
        for _, row in bm_log_df.iterrows():
            bm_map[str(row['gw'])] = row['bookmaker']

    if bets_df.empty:
        return user_stats

    for _, b in bets_df.iterrows():
        p_user = b['user']
        if p_user not in user_stats: continue
        
        status = str(b.get('result', '')).upper() # WIN / LOSE / (empty)
        # スプレッドシートのstatusカラムも考慮 (SETTLED)
        is_settled = (str(b.get('status','')).upper() == 'SETTLED') or (status in ['WIN', 'LOSE'])
        
        stake = float(b['stake']) if b['stake'] else 0
        odds = float(b['odds']) if b['odds'] else 1.0
        
        gw = str(b['gw'])
        bm_user = bm_map.get(gw)

        if is_settled:
            user_stats[p_user]['total'] += 1
            pnl = 0
            
            if status == 'WIN':
                user_stats[p_user]['wins'] += 1
                pnl = (stake * odds) - stake # 利益
            else:
                pnl = -stake # 損失
            
            # Player反映
            user_stats[p_user]['balance'] += int(pnl)
            
            # BM反映 (Playerと逆)
            if bm_user and bm_user in user_stats and bm_user != p_user:
                user_stats[bm_user]['balance'] -= int(pnl)
        
        else:
            # 未確定 (Pending) -> ポテンシャル計算
            # "利益" のみ加算
            pot_win = (stake * odds) - stake
            user_stats[p_user]['potential'] += int(pot_win)

    return user_stats

def determine_current_gw(results_df, api_token):
    """
    現在時刻と試合日程からGWを判定
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    
    # 1. DBのResultテーブルから未来の試合を探す
    if not results_df.empty and 'utc_kickoff' in results_df.columns:
        # 文字列を日付に変換
        results_df['dt'] = pd.to_datetime(results_df['utc_kickoff'], errors='coerce', utc=True)
        # 4時間前より未来の試合
        future = results_df[results_df['dt'] > (now_utc - timedelta(hours=4))].sort_values('dt')
        
        if not future.empty:
            gw_str = future.iloc[0]['gw'] # "GW17"
            return gw_str
    
    # 2. なければAPIで確認 (シーズン終了等の可能性もあるが、最新を取得)
    # ここでは簡易的に「DBにある最大のGW」を返す (API頻度節約)
    # 必要ならここでAPIコールを入れる
    if not results_df.empty:
        # GW番号を抽出してソート
        def extract_gw(s):
            num = "".join([c for c in str(s) if c.isdigit()])
            return int(num) if num else 0
            
        results_df['gw_num'] = results_df['gw'].apply(extract_gw)
        max_gw = results_df.sort_values('gw_num', ascending=False).iloc[0]['gw']
        return max_gw
        
    return "GW1"

# ==============================================================================
# 3. データ更新処理
# ==============================================================================
def sync_with_api(api_token):
    """APIから最新データを取得し、odds/resultテーブルを更新"""
    if not api_token: return False, "Token not found"
    
    headers = {'X-Auth-Token': api_token}
    url = "https://api.football-data.org/v4/competitions/PL/matches?season=2024" # 2024-2025
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200: return False, f"API Error: {res.status_code}"
        
        matches = res.json().get('matches', [])
        
        # Resultテーブル用データ & Oddsテーブル用データ
        result_upserts = []
        odds_upserts = []
        
        for m in matches:
            gw_str = f"GW{m['matchday']}"
            mid = m['id']
            
            # Result
            res_row = {
                "match_id": mid,
                "gw": gw_str,
                "home": m['homeTeam']['name'],
                "away": m['awayTeam']['name'],
                "utc_kickoff": m['utcDate'],
                "status": m['status'],
                "home_score": m['score']['fullTime']['home'],
                "away_score": m['score']['fullTime']['away'],
                "updated_at": datetime.datetime.now().isoformat()
            }
            result_upserts.append(res_row)
            
            # Odds (APIにオッズがあれば更新、なければ既存維持したいがUpsertは上書き)
            # ここではAPIにオッズがないため、Oddsテーブルは「マスタ」として扱う
            # ただし、試合IDとチーム名は同期しておく
            odds_row = {
                "match_id": mid,
                "gw": gw_str,
                "home": m['homeTeam']['name'],
                "away": m['awayTeam']['name'],
                # "updated_at": datetime.datetime.now().isoformat() # オッズは手動管理かもしれないので更新しない
            }
            # odds_upserts.append(odds_row) # OddsはAPIから消えたりするので慎重に
            
        # DB更新
        chunk = 100
        for i in range(0, len(result_upserts), chunk):
            supabase.table("result").upsert(result_upserts[i:i+chunk]).execute()
            
        return True, f"Synced {len(result_upserts)} matches."
        
    except Exception as e:
        return False, str(e)

# ==============================================================================
# 4. メインアプリ (UI)
# ==============================================================================
def main():
    if not supabase: st.error("DB Error"); st.stop()
    
    # ------------------
    # データロード
    # ------------------
    bets, odds, results, bm_log, users, config = fetch_all_data()
    
    # ログイン
    if 'user' not in st.session_state:
        st.session_state['user'] = None

    if not st.session_state['user']:
        st.sidebar.title("🔐 Login")
        u_list = users['username'].tolist() if not users.empty else []
        name = st.sidebar.selectbox("User", u_list)
        pw = st.sidebar.text_input("Pass", type="password")
        if st.sidebar.button("Login"):
            # 簡易認証
            user_row = users[users['username'] == name]
            if not user_row.empty and str(user_row.iloc[0]['password']) == pw:
                st.session_state['user'] = user_row.iloc[0].to_dict()
                st.rerun()
            else:
                st.error("NG")
        st.stop()
        
    me = st.session_state['user']
    api_token = get_api_token(config)
    
    # ------------------
    # 自動判定 & 計算
    # ------------------
    # GW判定
    current_gw = determine_current_gw(results, api_token)
    
    # 収支計算
    stats = calculate_stats(bets, bm_log, users)
    my_stats = stats.get(me['username'], {'balance':0, 'wins':0, 'total':0, 'potential':0})

    # ------------------
    # サイドバー
    # ------------------
    st.sidebar.markdown(f"## 👤 {me['username']}")
    st.sidebar.caption(f"Team: {me.get('team', '-')}")
    st.sidebar.divider()
    
    # Balance
    bal = my_stats['balance']
    col = "#4ade80" if bal >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:2rem;font-weight:800;color:{col}'>{fmt_yen(bal)}</div>", unsafe_allow_html=True)
    st.sidebar.caption("Total P&L (All Time)")
    
    # Potential
    if my_stats['potential'] > 0:
        st.sidebar.markdown(f"""
        <div class="potential-box">
            <div style="font-size:0.8rem;opacity:0.8">PENDING POTENTIAL</div>
            <div style="font-size:1.4rem">+{fmt_yen(my_stats['potential'])}</div>
        </div>
        """, unsafe_allow_html=True)
        
    st.sidebar.divider()
    if st.sidebar.button("🔄 Sync & Refresh"):
        with st.spinner("Syncing..."):
            ok, msg = sync_with_api(api_token)
            if ok: st.success(msg)
            else: st.error(msg)
            st.cache_resource.clear()
            time.sleep(1)
            st.rerun()
            
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None
        st.rerun()

    # ------------------
    # タブ構成
    # ------------------
    tabs = st.tabs(["📊 Dashboard", "⚽ Matches", "📜 History", "🏆 Standings", "🛠 Admin"])
    
    # [1] Dashboard
    with tabs[0]:
        st.markdown(f"#### 👋 Hi, {me['username']}")
        
        # KPI
        win_rate = (my_stats['wins'] / my_stats['total'] * 100) if my_stats['total'] else 0
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>Win Rate</div><div class='kpi-val'>{win_rate:.1f}%</div></div>", unsafe_allow_html=True)
        with c2: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>Wins</div><div class='kpi-val'>{my_stats['wins']}/{my_stats['total']}</div></div>", unsafe_allow_html=True)
        with c3: st.markdown(f"<div class='kpi-box'><div class='kpi-label'>Current GW</div><div class='kpi-val'>{current_gw}</div></div>", unsafe_allow_html=True)
        
    # [2] Matches (Betting)
    with tabs[1]:
        # GW選択
        gw_list = sorted(list(set(results['gw'].dropna())), key=lambda x: int(x.replace('GW','')) if 'GW' in str(x) else 0)
        default_idx = gw_list.index(current_gw) if current_gw in gw_list else 0
        selected_gw = st.selectbox("Gameweek", gw_list, index=default_idx)
        
        st.markdown(f"#### {selected_gw} Fixtures")
        
        # 結合: Odds + Result (match_id)
        # Oddsテーブルにオッズがあり、Resultテーブルに日程がある
        target_odds = odds[odds['gw'] == selected_gw]
        if target_odds.empty:
            st.info("No odds data for this GW.")
        else:
            for _, row in target_odds.iterrows():
                mid = row['match_id']
                # Resultから詳細取得
                res_row = results[results['match_id'] == mid]
                kickoff = ""
                status = "SCHEDULED"
                score = ""
                
                if not res_row.empty:
                    k_str = res_row.iloc[0]['utc_kickoff']
                    kickoff = to_jst_str(k_str)
                    status = res_row.iloc[0]['status']
                    h_sc = res_row.iloc[0]['home_score']
                    a_sc = res_row.iloc[0]['away_score']
                    if pd.notna(h_sc): score = f"{int(h_sc)} - {int(a_sc)}"
                
                # カード表示
                with st.container():
                    st.markdown(f"""
                    <div class="app-card">
                        <div style="display:flex; justify-content:space-between; margin-bottom:10px">
                            <span class="match-time">⏱ {kickoff}</span>
                            <span class="status-badge">{status}</span>
                        </div>
                        <div style="display:grid; grid-template-columns: 1fr 20px 1fr; align-items:center; gap:10px; text-align:center; margin-bottom:15px">
                            <div>
                                <div style="font-weight:bold">{row['home']}</div>
                                <div style="color:#4ade80; font-weight:bold">{row['home_win']}</div>
                            </div>
                            <div style="color:#888">vs</div>
                            <div>
                                <div style="font-weight:bold">{row['away']}</div>
                                <div style="color:#4ade80; font-weight:bold">{row['away_win']}</div>
                            </div>
                        </div>
                        <div style="text-align:center; font-size:1.2rem; font-weight:bold; letter-spacing:2px">
                            {score}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # ベット機能 (進行中・終了後はロック)
                    if status not in ['IN_PLAY', 'FINISHED', 'PAUSED']:
                        # 自分のベット済みチェック
                        my_bet = bets[(bets['match_id'] == mid) & (bets['user'] == me['username'])]
                        
                        if not my_bet.empty:
                            pick = my_bet.iloc[0]['pick']
                            st.info(f"✅ You picked: **{pick}**")
                        else:
                            with st.form(key=f"bet_{mid}"):
                                c1, c2, c3 = st.columns([3, 2, 2])
                                # 選択肢
                                oh, od, oa = row['home_win'], row['draw'], row['away_win']
                                opts = [f"HOME ({oh})", f"DRAW ({od})", f"AWAY ({oa})"]
                                choice = c1.selectbox("Pick", opts, label_visibility="collapsed")
                                stake = c2.number_input("¥", 100, 10000, 1000, 100, label_visibility="collapsed")
                                
                                if c3.form_submit_button("BET", use_container_width=True):
                                    tgt = "HOME" if "HOME" in choice else ("DRAW" if "DRAW" in choice else "AWAY")
                                    odds_val = float(oh if tgt=="HOME" else (od if tgt=="DRAW" else oa))
                                    
                                    # キー生成 (GWxx:User:MatchID)
                                    new_key = f"{selected_gw}:{me['username']}:{mid}"
                                    
                                    # DB登録
                                    payload = {
                                        "key": new_key,
                                        "gw": selected_gw,
                                        "user": me['username'],
                                        "match_id": mid,
                                        "match": f"{row['home']} vs {row['away']}",
                                        "pick": tgt,
                                        "stake": stake,
                                        "odds": odds_val,
                                        "placed_at": datetime.datetime.now().isoformat(),
                                        "status": "OPEN", # DBのカラム名に合わせる
                                        "result": "",     # まだ結果なし
                                    }
                                    supabase.table("bets").upsert(payload).execute()
                                    st.success("Bet Placed!")
                                    time.sleep(1)
                                    st.cache_resource.clear()
                                    st.rerun()

    # [3] History
    with tabs[2]:
        st.markdown("#### Your Betting History")
        my_hist = bets[bets['user'] == me['username']].sort_values('placed_at', ascending=False)
        
        if not my_hist.empty:
            for _, b in my_hist.iterrows():
                res = b['result'] if b['result'] else "PENDING"
                col = "gray"
                pnl_disp = "-"
                
                if res == 'WIN':
                    col = "#4ade80" # Green
                    prof = (float(b['stake']) * float(b['odds'])) - float(b['stake'])
                    pnl_disp = f"+{fmt_yen(prof)}"
                elif res == 'LOSE':
                    col = "#f87171" # Red
                    pnl_disp = f"-{fmt_yen(b['stake'])}"
                
                st.markdown(f"""
                <div style="border-left: 4px solid {col}; background: rgba(255,255,255,0.05); padding: 10px; margin-bottom: 8px; border-radius: 4px;">
                    <div style="display:flex; justify-content:space-between;">
                        <span style="font-weight:bold">{b['match']}</span>
                        <span style="font-size:0.8rem; color:#aaa">{b['gw']}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-top:4px;">
                        <span>{b['pick']} <span class="subtle">(@{b['odds']})</span></span>
                        <span style="font-weight:bold; color:{col}">{pnl_disp}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

    # [4] Standings
    with tabs[3]:
        st.markdown("#### 🏆 Leaderboard")
        # 統計データからランキング作成
        ranking = []
        for u, s in stats.items():
            ranking.append({"user": u, "balance": s['balance']})
        
        ranking.sort(key=lambda x: x['balance'], reverse=True)
        
        for i, r in enumerate(ranking):
            is_me = (r['user'] == me['username'])
            bg = "rgba(255,255,255,0.1)" if is_me else "transparent"
            st.markdown(f"""
            <div style="background:{bg}; padding:10px; border-radius:8px; display:flex; justify-content:space-between; margin-bottom:5px; border-bottom:1px solid rgba(255,255,255,0.05)">
                <div><span style="color:#888; font-weight:bold; width:20px; display:inline-block">{i+1}.</span> {r['user']}</div>
                <div style="font-weight:bold; color:{'#4ade80' if r['balance']>=0 else '#f87171'}">{fmt_yen(r['balance'])}</div>
            </div>
            """, unsafe_allow_html=True)

# ユーティリティ: 時刻変換
def to_jst_str(iso_str):
    if not iso_str: return "-"
    try:
        dt = pd.to_datetime(iso_str)
        if dt.tz is None: dt = dt.tz_localize('UTC')
        return dt.tz_convert(JST).strftime('%m/%d %H:%M')
    except: return str(iso_str)

def fmt_yen(n):
    return f"¥{int(n):,}"

import time

if __name__ == "__main__":
    main()
