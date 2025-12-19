import streamlit as st
import pandas as pd
import requests
import datetime
import json
from datetime import timedelta, timezone
from supabase import create_client

# ==============================================================================
# 0. 初期設定 & UI/CSS定義 (旧アプリ完全踏襲 + 美化)
# ==============================================================================
st.set_page_config(page_title="Premier Picks V2", layout="wide")
JST = timezone(timedelta(hours=9), 'JST')

# スマホ最適化 & 旧デザイン再現のためのCSS
st.markdown("""
<style>
/* 全体レイアウト調整 (スマホでヘッダーが被らないように) */
.block-container {padding-top:3.5rem; padding-bottom:5rem;}

/* --- 旧アプリのデザイン踏襲 --- */
.app-card {
    border: 1px solid rgba(120,120,120,.25);
    border-radius: 12px;
    padding: 16px;
    background: rgba(255,255,255,.03);
    margin-bottom: 12px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}
.subtle { color: rgba(255,255,255,.6); font-size: 0.85rem; }

/* KPIカード */
.kpi-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
.kpi {
    flex: 1 1 100px;
    border: 1px solid rgba(120,120,120,.25);
    border-radius: 10px;
    padding: 12px;
    background: rgba(255,255,255,0.02);
    text-align: center;
}
.kpi .h { font-size: 0.75rem; color: rgba(255,255,255,.7); margin-bottom: 4px; }
.kpi .v { font-size: 1.3rem; font-weight: 700; }

/* --- 新機能用スタイル --- */
/* ポテンシャル利益 (サイドバー用) */
.potential-box {
    margin-top: 10px; padding: 12px; border-radius: 8px;
    background: rgba(34, 197, 94, 0.1); border: 1px solid rgba(34, 197, 94, 0.3);
    color: #4ade80; text-align: center; font-weight: bold;
}

/* 他人のベット状況アイコン */
.bet-badge {
    display: inline-flex; align-items: center; 
    padding: 2px 8px; border-radius: 99px; 
    font-size: 0.75rem; margin-left: 5px; 
    background: rgba(255,255,255,0.1); color: #ddd; border: 1px solid rgba(255,255,255,0.1);
}

/* 得意チームリスト */
.team-stat-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.1);
}
.live-profit-plus { color: #4ade80; font-weight: bold; }
.live-profit-minus { color: #f87171; font-weight: bold; }

/* スマホ用ボタン調整 */
div[data-testid="stForm"] button {
    height: 3rem; font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. Supabase 接続 & データアクセス層
# ==============================================================================
@st.cache_resource
def get_db():
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except:
        return None

supabase = get_db()

# 設定読み込み (キャッシュしない、常に最新を)
def get_config():
    try:
        rows = supabase.table("app_config").select("*").execute().data
        return {r['key']: r['value'] for r in rows}
    except:
        return {}

# ユーティリティ
def fmt_yen(n): return f"¥{int(n):,}"
def to_jst(iso_str):
    if not iso_str: return "-"
    try:
        return pd.to_datetime(iso_str).tz_convert(JST).strftime('%m/%d %H:%M')
    except: return str(iso_str)

# ==============================================================================
# 2. ロジック (同期, 精算, BM, 分析)
# ==============================================================================

# A. API同期 & オッズ確定 & 自動精算
def sync_logic(api_token, season="2024"):
    if not api_token: return False, "API Token Missing"
    
    headers = {'X-Auth-Token': api_token}
    # 前後14日
    d_now = datetime.datetime.now()
    d_from = (d_now - timedelta(days=14)).strftime('%Y-%m-%d')
    d_to = (d_now + timedelta(days=14)).strftime('%Y-%m-%d')
    
    try:
        # 1. 試合更新
        url = f"https://api.football-data.org/v4/competitions/PL/matches?dateFrom={d_from}&dateTo={d_to}"
        res = requests.get(url, headers=headers)
        if res.status_code != 200: return False, "API Error"
        
        matches = res.json().get('matches', [])
        conf = get_config()
        lock_hours = float(conf.get('odds_lock_hours', 1.0))
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        upsert_list = []
        finished_matches = []

        for m in matches:
            kickoff = m['utcDate']
            k_dt = datetime.datetime.fromisoformat(kickoff.replace('Z', '+00:00'))
            hours_left = (k_dt - now_utc).total_seconds() / 3600
            
            # ロック判定
            is_locked = hours_left <= lock_hours
            
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
                finished_matches.append(row)

        if upsert_list:
            supabase.table("matches").upsert(upsert_list).execute()

        # 2. 精算処理 (P2P: Player vs BM)
        # そのGWのBMを特定する必要がある。今回は簡易的に bm_history から検索
        # 本来はGWごとにBMが異なるため、matchのgameweekを見てBMを引く
        
        settled_count = 0
        
        # 全てのPENDINGベットを取得 (FINISHEDの試合のみ)
        if finished_matches:
            target_ids = [m['match_id'] for m in finished_matches]
            # chunks
            pending_bets = []
            if target_ids:
                 pending_bets = supabase.table("bets").select("*").in_("match_id", target_ids).eq("status", "PENDING").execute().data
            
            for b in pending_bets:
                # 該当試合の結果を探す
                match_data = next((m for m in finished_matches if m['match_id'] == b['match_id']), None)
                if not match_data: continue
                
                # スコア判定
                hs, as_ = match_data['home_score'], match_data['away_score']
                if hs is None or as_ is None: continue
                
                result = "DRAW"
                if hs > as_: result = "HOME"
                elif as_ > hs: result = "AWAY"
                
                # 勝敗決定
                new_status = "WON" if b['choice'] == result else "LOST"
                
                # 損益計算
                pnl_player = 0
                if new_status == "WON":
                    pnl_player = int(b['stake'] * b['odds_at_bet']) - b['stake'] # 利益分
                else:
                    pnl_player = -b['stake'] # 損失
                
                # DB更新 (Status)
                supabase.table("bets").update({"status": new_status}).eq("bet_id", b['bet_id']).execute()
                
                # バランス移動 (Player)
                supabase.rpc("increment_balance", {"p_user_id": b['user_id'], "p_amount": pnl_player}).execute()
                
                # バランス移動 (BM)
                # BMを特定する: bm_history から match_data['gameweek'] のBMを探す
                bm_res = supabase.table("bm_history").select("user_id")\
                    .eq("gameweek", match_data['gameweek']).eq("season", season).execute().data
                
                if bm_res:
                    bm_id = bm_res[0]['user_id']
                    # プレイヤーの利益はBMの損失、プレイヤーの損失はBMの利益
                    # つまり pnl_player * -1
                    supabase.rpc("increment_balance", {"p_user_id": bm_id, "p_amount": -pnl_player}).execute()
                
                settled_count += 1
                
        return True, f"Updated {len(upsert_list)} matches, Settled {settled_count} bets."

    except Exception as e:
        return False, str(e)

# B. ユーザー統計 (Balance, Win Rate, Best Teams)
def get_user_stats(user_id):
    bets = supabase.table("bets").select("*, matches(*)").eq("user_id", user_id).execute().data
    
    total = 0
    wins = 0
    potential = 0
    team_stats = {} # {Team: {win:0, total:0}}
    
    # ライブ収支用
    live_pnl = 0
    
    for b in bets:
        m = b['matches']
        if not m: continue
        
        status = b['status']
        stake = b['stake']
        odds = b['odds_at_bet'] or 1.0
        
        # ポテンシャル (PENDINGのみ)
        if status == 'PENDING':
            profit = (stake * odds) - stake
            potential += profit
            
            # ライブ収支 (PENDINGだが試合が進行中/終了の場合)
            if m['status'] in ['IN_PLAY', 'FINISHED', 'PAUSED']:
                # 現在スコアで判定
                hs, as_ = m['home_score'], m['away_score']
                curr_res = "DRAW"
                if hs is not None and as_ is not None:
                    if hs > as_: curr_res = "HOME"
                    elif as_ > hs: curr_res = "AWAY"
                    
                    if b['choice'] == curr_res:
                        live_pnl += profit # 勝ち想定
                    else:
                        live_pnl -= stake # 負け想定

        # 確定済み
        elif status in ['WON', 'LOST']:
            total += 1
            if status == 'WON':
                wins += 1
            
            # チーム分析
            tgt = None
            if b['choice'] == "HOME": tgt = m['home_team']
            elif b['choice'] == "AWAY": tgt = m['away_team']
            
            if tgt:
                if tgt not in team_stats: team_stats[tgt] = {'w':0, 't':0}
                team_stats[tgt]['t'] += 1
                if status == 'WON': team_stats[tgt]['w'] += 1
                
    # Best Teams Sort
    best_teams = []
    for tm, val in team_stats.items():
        if val['t'] >= 2: # 最低2回
            rate = val['w'] / val['t']
            best_teams.append((tm, rate, val['w'], val['t']))
    best_teams.sort(key=lambda x: (x[1], x[3]), reverse=True)
    
    return {
        "total": total, "wins": wins, "potential": potential, 
        "live_pnl": live_pnl, "best_teams": best_teams[:3]
    }

# C. GWごとの収支 (アコーディオン用)
def get_gw_pnl_history():
    # 全ベット履歴から集計
    # 簡易化: betsテーブルを全件取得してPythonで集計
    all_bets = supabase.table("bets").select("*, matches(gameweek), users(username)").in_("status", ["WON","LOST"]).execute().data
    
    # {GW: {User: PnL}}
    res = {}
    for b in all_bets:
        gw = b['matches']['gameweek']
        u = b['users']['username']
        
        pnl = 0
        if b['status'] == 'WON':
            pnl = int(b['stake'] * b['odds_at_bet']) - b['stake']
        else:
            pnl = -b['stake']
            
        if gw not in res: res[gw] = {}
        if u not in res[gw]: res[gw][u] = 0
        res[gw][u] += pnl
        
    return res

# ==============================================================================
# 3. UI メイン
# ==============================================================================

def login_ui(users):
    st.sidebar.markdown("### 🔑 Login")
    name = st.sidebar.selectbox("Username", [u['username'] for u in users])
    pw = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        u = next((x for x in users if x['username'] == name), None)
        if u and str(u.get('password')) == str(pw):
            st.session_state['user'] = u
            st.rerun()
        else:
            st.error("Invalid password")
    return st.session_state.get('user')

def main():
    if not supabase: st.error("DB Connection Failed"); st.stop()
    
    conf = get_config()
    users = supabase.table("users").select("*").execute().data
    me = login_ui(users)
    if not me: st.stop()
    
    # DBから最新情報再取得
    me = next(u for u in users if u['username'] == me['username'])
    st.session_state['user'] = me
    
    # 統計データ
    stats = get_user_stats(me['user_id'])

    # --- サイドバー情報 ---
    st.sidebar.markdown(f"## 👤 {me['username']}")
    st.sidebar.caption(f"Fan of {me.get('favorite_team','-')}")
    
    # Balance
    bal_col = "#4ade80" if me['balance'] >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:1.8rem;font-weight:bold;color:{bal_col}'>{fmt_yen(me['balance'])}</div>", unsafe_allow_html=True)
    
    # ★ 新機能: ポテンシャル利益
    if stats['potential'] > 0:
        st.sidebar.markdown(f"""
        <div class="potential-box">
            <div>🚀 Potential Profit</div>
            <div style="font-size:1.4rem">+{fmt_yen(stats['potential'])}</div>
        </div>
        """, unsafe_allow_html=True)
        
    st.sidebar.divider()
    
    # 更新ボタン
    if st.sidebar.button("🔄 データ更新 & 精算"):
        with st.spinner("Syncing..."):
            tk = conf.get("FOOTBALL_DATA_API_TOKEN") or st.secrets.get("api_token")
            success, msg = sync_logic(tk, conf.get("API_FOOTBALL_SEASON","2024"))
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
                
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None
        st.rerun()

    # --- メインコンテンツ (完全踏襲タブ構成) ---
    tabs = st.tabs(["トップ", "試合とベット", "履歴", "リアルタイム", "ダッシュボード", "オッズ管理"])

    # [1] トップ (KPI & 分析)
    with tabs[0]:
        st.markdown(f"#### 👋 Hi, {me['username']}")
        
        # KPI Row
        st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
        win_rate = (stats['wins']/stats['total']*100) if stats['total'] else 0
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(f"<div class='kpi'><div class='h'>Win Rate</div><div class='v'>{win_rate:.0f}%</div></div>", unsafe_allow_html=True)
        with c2: st.markdown(f"<div class='kpi'><div class='h'>Wins</div><div class='v'>{stats['wins']}</div></div>", unsafe_allow_html=True)
        with c3: st.markdown(f"<div class='kpi'><div class='h'>Total Bets</div><div class='v'>{stats['total']}</div></div>", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
        # ★ 新機能: 得意チーム分析
        if stats['best_teams']:
            st.markdown("##### 🎯 Your Best Teams")
            with st.container():
                st.markdown('<div class="app-card">', unsafe_allow_html=True)
                for tm, rate, w, t in stats['best_teams']:
                    st.markdown(f"""
                    <div class="team-stat-row">
                        <div style="font-weight:bold">{tm}</div>
                        <div>
                            <span style="color:#4ade80; font-weight:bold">{rate*100:.0f}%</span>
                            <span class="subtle">({w}/{t})</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
        # ★ 新機能: 節ごとの収支 (アコーディオン)
        gw_pnl = get_gw_pnl_history()
        with st.expander("📊 GWごとの収支明細を見る"):
            for gw in sorted(gw_pnl.keys()): # GW番号でソート推奨
                st.markdown(f"**GW{gw}**")
                cols = st.columns(len(users))
                for i, u in enumerate(users):
                    p = gw_pnl[gw].get(u['username'], 0)
                    col_str = "#4ade80" if p >= 0 else "#f87171"
                    cols[i].markdown(f"{u['username']}: <span style='color:{col_str}'>{fmt_yen(p)}</span>", unsafe_allow_html=True)
                st.divider()

    # [2] 試合とベット (メイン)
    with tabs[1]:
        # GW選択 (現在はConfigのcurrent_gw)
        curr_gw = int(conf.get("current_gw", 1))
        st.markdown(f"### GW{curr_gw} Matches")
        
        matches = supabase.table("matches").select("*").eq("gameweek", curr_gw).order("kickoff_time").execute().data
        
        # 他人のベット情報を取得
        all_bets = supabase.table("bets").select("match_id, user_id, choice").in_("match_id", [m['match_id'] for m in matches]).execute().data
        
        if not matches:
            st.info("No matches found.")
        
        for m in matches:
            # 他人のベット表示
            others_html = ""
            for b in all_bets:
                if b['match_id'] == m['match_id'] and b['user_id'] != me['user_id']:
                    u_name = next((u['username'] for u in users if u['user_id'] == b['user_id']), "?")
                    others_html += f"<span class='bet-badge'>👤 {u_name}: {b['choice']}</span>"

            # カード表示
            oh = m.get('odds_home') or '-'
            od = m.get('odds_draw') or '-'
            oa = m.get('odds_away') or '-'
            
            st.markdown(f"""
            <div class="app-card">
                <div style="display:flex; justify-content:space-between; margin-bottom:8px">
                    <span class="subtle">{to_jst(m['kickoff_time'])}</span>
                    <div>{others_html}</div>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px">
                    <div style="text-align:center; flex:1">
                        <div style="font-weight:bold">{m['home_team']}</div>
                        <div style="color:#4ade80; font-weight:bold">{oh}</div>
                    </div>
                    <div class="subtle" style="padding:0 10px">vs</div>
                    <div style="text-align:center; flex:1">
                        <div style="font-weight:bold">{m['away_team']}</div>
                        <div style="color:#4ade80; font-weight:bold">{oa}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            # ベットフォーム
            with st.form(key=f"b_{m['match_id']}"):
                c1, c2 = st.columns([3, 1])
                opts = [f"HOME ({oh})", f"DRAW ({od})", f"AWAY ({oa})"]
                sel = c1.radio("Pick", opts, label_visibility="collapsed", horizontal=True)
                amt = c2.number_input("¥", min_value=100, step=100, value=1000, label_visibility="collapsed")
                
                if st.form_submit_button("BET 🔥", use_container_width=True):
                    # ロジック: バリデーション & 保存
                    target = "HOME" if "HOME" in sel else ("DRAW" if "DRAW" in sel else "AWAY")
                    odds_val = oh if target=="HOME" else (od if target=="DRAW" else oa)
                    
                    try:
                        odds_val = float(odds_val)
                        # キャップ確認 (GW合計)
                        # ここでは省略するが、本来は bets テーブルで sum(stake) where gw=curr_gw をチェック
                        supabase.table("bets").insert({
                            "user_id": me['user_id'], "match_id": m['match_id'],
                            "choice": target, "stake": amt, "odds_at_bet": odds_val, "status": "PENDING"
                        }).execute()
                        st.toast("Bet Placed!", icon="✅")
                        st.rerun()
                    except:
                        st.error("Odds unavailable or Error")
            st.markdown("</div>", unsafe_allow_html=True)

    # [3] 履歴
    with tabs[2]:
        st.markdown("### Betting History")
        hist = supabase.table("bets").select("*, matches(home_team, away_team)").eq("user_id", me['user_id']).order("created_at", desc=True).limit(50).execute().data
        
        if hist:
            rows = []
            for h in hist:
                m = h['matches']
                res = h['status']
                pnl = 0
                if res == "WON": pnl = int(h['stake'] * h['odds_at_bet']) - h['stake']
                elif res == "LOST": pnl = -h['stake']
                
                rows.append({
                    "Date": to_jst(h['created_at']),
                    "Match": f"{m.get('home_team')} vs {m.get('away_team')}",
                    "Pick": h['choice'],
                    "Stake": fmt_yen(h['stake']),
                    "Result": res,
                    "P&L": fmt_yen(pnl)
                })
            st.dataframe(pd.DataFrame(rows))
        else:
            st.info("No history.")

    # [4] リアルタイム収支 (新機能)
    with tabs[3]:
        st.markdown("### 🔴 Live Profit Monitor")
        st.info("進行中の試合結果に基づいた、あなたの暫定収支です。")
        
        lp = stats['live_pnl']
        cls = "live-profit-plus" if lp >= 0 else "live-profit-minus"
        sign = "+" if lp >= 0 else ""
        
        st.markdown(f"""
        <div class="app-card" style="text-align:center">
            <div class="subtle">Estimated Profit (Live)</div>
            <div class="{cls}" style="font-size:2.5rem">{sign}{fmt_yen(lp)}</div>
        </div>
        """, unsafe_allow_html=True)
        
        # 内訳表示 (PENDINGかつ進行中の試合)
        # ※ 詳細実装は API の status='IN_PLAY' に依存

    # [5] ダッシュボード (Leaderboard)
    with tabs[4]:
        st.markdown("### Leaderboard")
        sorted_users = sorted(users, key=lambda x: x['balance'], reverse=True)
        for i, u in enumerate(sorted_users):
            st.markdown(f"""
            <div class="app-card" style="display:flex; justify-content:space-between; align-items:center">
                <div>
                    <span style="font-weight:bold; color:#888; margin-right:8px">{i+1}.</span>
                    <span style="font-weight:bold; font-size:1.1rem">{u['username']}</span>
                    <span class="subtle">({u.get('favorite_team')})</span>
                </div>
                <div style="font-weight:bold; font-size:1.2rem; color:{'#4ade80' if u['balance']>=0 else '#f87171'}">
                    {fmt_yen(u['balance'])}
                </div>
            </div>
            """, unsafe_allow_html=True)

    # [6] オッズ管理
    with tabs[5]:
        if me['role'] == 'admin':
            st.markdown("### Config Management")
            st.json(conf)
            st.warning("設定変更は Supabase の app_config テーブルを直接編集してください。")
        else:
            st.error("Access Denied.")

if __name__ == "__main__":
    main()
