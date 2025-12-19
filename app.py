import streamlit as st
import pandas as pd
import requests
import datetime
import pytz
import json
import re
from datetime import timedelta, timezone
from supabase import create_client

# ==============================================================================
# 0. 初期設定 & 定数
# ==============================================================================
st.set_page_config(page_title="Premier Picks", layout="wide")
JST = timezone(timedelta(hours=9), 'JST')

# Supabase接続
@st.cache_resource
def get_supabase():
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except:
        return None

supabase = get_supabase()

# ==============================================================================
# 1. Util & UI Parts (いただいたファイルをそのまま移植)
# ==============================================================================
# --- from util.py ---
def safe_int(v, default=0):
    try: return int(float(v))
    except: return default

def fmt_yen(n):
    try: return f"{int(n):,}"
    except: return str(n)

def to_local(dt, tz):
    if dt is None: return None
    if isinstance(dt, str):
        try: dt = datetime.datetime.fromisoformat(dt)
        except: return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(tz)

def gw_label(gw):
    if gw is None: return "GW"
    s = str(gw)
    return s if s.startswith("GW") else f"GW{safe_int(s,0)}"

def outcome_text_jp(o):
    return {"HOME":"ホーム勝ち","DRAW":"引き分け","AWAY":"アウェイ勝ち"}.get(o or "", "-")

# --- from ui_parts.py ---
def section_header(title: str):
    st.markdown(f"## {title}")

def muted(text: str):
    st.markdown(f"<span style='color:#6b7280'>{text}</span>", unsafe_allow_html=True)

def kpi(container, label, value):
    with container:
        st.markdown(f"""
        <div style='padding:12px 14px;border:1px solid #eee;border-radius:8px;background:rgba(255,255,255,0.02);'>
          <div style='color:#bbb;font-size:12px'>{label}</div>
          <div style='font-size:22px;font-weight:700;color:white'>{value}</div>
        </div>
        """, unsafe_allow_html=True)

# --- CSS (from app.py) ---
CSS = """
<style>
/* ← タブ上部が切れないように上マージンを増量 */
.block-container {padding-top:3.2rem; padding-bottom:3rem;}

.app-card{border:1px solid rgba(120,120,120,.25); border-radius:10px; padding:18px; background:rgba(255,255,255,.02);}
.subtle{color:rgba(255,255,255,.6); font-size:.9rem}
.kpi-row{display:flex; gap:12px; flex-wrap:wrap}
.kpi{flex:1 1 140px; border:1px solid rgba(120,120,120,.25); border-radius:10px; padding:10px 14px}
.kpi .h{font-size:.8rem; color:rgba(255,255,255,.7)}
.kpi .v{font-size:1.4rem; font-weight:700}

/* 追加機能用: 旧デザインに馴染むスタイル */
.potential-profit {
    color: #4ade80; font-size: 0.9rem; margin-top: 4px;
}
.team-stat-row {
    display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 0.9rem;
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ==============================================================================
# 2. Data Access Layer (Google Sheets Clientの代わり)
# ==============================================================================
def read_config_map():
    """app_configテーブルから設定を取得"""
    try:
        data = supabase.table("app_config").select("*").execute().data
        return {item['key']: item['value'] for item in data}
    except:
        return {}

def fetch_user(username):
    """ユーザー情報を取得"""
    try:
        # パスワードは平文保存されている前提(旧仕様踏襲)
        res = supabase.table("users").select("*").eq("username", username).single().execute()
        return res.data
    except:
        return None

def fetch_matches_for_gw(gw_label):
    """指定GWの試合を取得"""
    try:
        # DB上の gameweek は integer 想定 (GW7 -> 7)
        gw_num = safe_int(str(gw_label).replace("GW",""))
        res = supabase.table("matches").select("*").eq("gameweek", gw_num).order("kickoff_time").execute()
        return res.data
    except:
        return []

def fetch_my_bets(user_id):
    """自分のベット履歴を取得"""
    try:
        res = supabase.table("bets").select("*, matches(*)").eq("user_id", user_id).execute()
        return res.data
    except:
        return []

def fetch_all_users():
    """ランキング用全ユーザー"""
    try:
        return supabase.table("users").select("*").execute().data
    except:
        return []

def upsert_bet(user_id, match_id, pick, stake, odds):
    """ベット保存"""
    # 既存チェック (match_id + user_id)
    # Supabaseの unique constraints に任せるか、ここでチェック
    # ここでは旧アプリの挙動(上書き)に合わせる
    row = {
        "user_id": user_id,
        "match_id": match_id,
        "choice": pick,
        "stake": stake,
        "odds_at_bet": odds,
        "status": "PENDING"
    }
    # 既存があるか確認して update or insert (upsert)
    # betsテーブルには user_id, match_id の複合ユニーク制約があると望ましい
    # なければ delete insert
    existing = supabase.table("bets").select("bet_id").eq("user_id", user_id).eq("match_id", match_id).execute().data
    if existing:
        supabase.table("bets").update(row).eq("bet_id", existing[0]['bet_id']).execute()
    else:
        supabase.table("bets").insert(row).execute()

def update_balance(user_id, amount):
    supabase.table("users").update({"balance": amount}).eq("user_id", user_id).execute()

# API連携 (Football-Data.org)
def sync_latest_matches(api_token, season="2024-2025"):
    if not api_token: return
    headers = {'X-Auth-Token': api_token}
    # 前後2週間を取得
    d_now = datetime.datetime.now()
    d_from = (d_now - timedelta(days=14)).strftime('%Y-%m-%d')
    d_to = (d_now + timedelta(days=14)).strftime('%Y-%m-%d')
    url = f"https://api.football-data.org/v4/competitions/PL/matches?dateFrom={d_from}&dateTo={d_to}"
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            matches = res.json().get('matches', [])
            upsert_data = []
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            
            for m in matches:
                # オッズ更新判定 (1時間前まで)
                kickoff = m['utcDate']
                k_dt = datetime.datetime.fromisoformat(kickoff.replace('Z', '+00:00'))
                hours = (k_dt - now_utc).total_seconds() / 3600
                
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
                    "last_updated": datetime.datetime.now().isoformat()
                }
                
                # オッズ更新 (1時間以上前ならAPI値を採用)
                api_odds = m.get('odds', {})
                if api_odds.get('homeWin') and hours > 1.0:
                    row["odds_home"] = api_odds.get('homeWin')
                    row["odds_draw"] = api_odds.get('draw')
                    row["odds_away"] = api_odds.get('awayWin')
                
                upsert_data.append(row)
            
            if upsert_data:
                supabase.table("matches").upsert(upsert_data).execute()
    except:
        pass

# ==============================================================================
# 3. アプリケーションロジック (旧 app.py 踏襲)
# ==============================================================================

def login_ui(conf):
    st.sidebar.markdown("## Login")
    # ユーザーリスト取得
    users_data = fetch_all_users()
    if not users_data:
        st.error("DBにユーザーがいません")
        return None
    
    unames = [u['username'] for u in users_data]
    name = st.sidebar.selectbox("ユーザー名", unames)
    pw = st.sidebar.text_input("パスワード", type="password")
    
    if st.sidebar.button("ログイン"):
        # 認証
        target = next((u for u in users_data if u['username'] == name), None)
        if target and str(target.get('password')) == str(pw):
            st.session_state['user'] = target
            st.rerun()
        else:
            st.error("パスワードが違います")
    
    return st.session_state.get('user')

def calculate_stats(user_id):
    """新機能のための統計計算"""
    bets = fetch_my_bets(user_id)
    
    potential = 0
    team_stats = {} # {Team: {win:0, total:0}}
    
    for b in bets:
        # Potential Profit
        if b['status'] == 'PENDING':
            stake = b['stake']
            odds = b['odds_at_bet'] or 1.0
            potential += (stake * odds) - stake
        
        # Best Teams
        if b['status'] in ['WON', 'LOST']:
            m = b['matches']
            if not m: continue
            
            choice = b['choice'] # HOME, AWAY
            team_name = None
            if choice == 'HOME': team_name = m['home_team']
            elif choice == 'AWAY': team_name = m['away_team']
            
            if team_name:
                if team_name not in team_stats: team_stats[team_name] = {'win':0, 'total':0}
                team_stats[team_name]['total'] += 1
                if b['status'] == 'WON':
                    team_stats[team_name]['win'] += 1
                    
    # 得意チームソート
    best_teams = []
    for tm, val in team_stats.items():
        if val['total'] >= 2: # 2回以上ベット
            rate = val['win'] / val['total']
            best_teams.append((tm, rate, val['win'], val['total']))
    
    best_teams.sort(key=lambda x: (x[1], x[3]), reverse=True) # 勝率優先
    
    return potential, best_teams[:3]

def main():
    conf = read_config_map()
    if not conf:
        st.warning("Config not found in DB.") # 初回だけ出るかも
    
    me = login_ui(conf)
    if not me:
        st.stop()

    # DBから最新のUser情報を再取得
    me = fetch_user(me['username'])
    st.session_state['user'] = me
    
    # 統計計算 (新機能)
    potential_profit, best_teams = calculate_stats(me['user_id'])

    # --- サイドバー情報 (旧デザイン維持 + 新機能) ---
    st.sidebar.markdown(f"### 👤 {me['username']}")
    st.sidebar.markdown(f"**Team:** {me.get('favorite_team', '-')}")
    
    balance_disp = fmt_yen(me['balance'])
    st.sidebar.metric("Balance", balance_disp)
    
    # ★新機能1: ポテンシャル利益
    if potential_profit > 0:
        st.sidebar.markdown(f"""
        <div class='potential-profit'>
          🚀 Potential: +{fmt_yen(potential_profit)}
        </div>
        """, unsafe_allow_html=True)
    
    st.sidebar.divider()
    
    if st.sidebar.button("データ更新"):
        with st.spinner("更新中..."):
            token = conf.get("FOOTBALL_DATA_API_TOKEN") or st.secrets.get("api_token")
            sync_latest_matches(token)
            st.success("完了")
            st.rerun()

    if st.sidebar.button("ログアウト"):
        st.session_state['user'] = None
        st.rerun()

    # --- メインコンテンツ (旧タブ構成を完全維持) ---
    tabs = st.tabs(["トップ", "試合とベット", "履歴", "リアルタイム", "ダッシュボード", "オッズ管理"])

    # 1. トップ
    with tabs[0]:
        st.markdown(f"#### Welcome, {me['username']}")
        
        # KPIエリア (旧ロジックで計算)
        my_bets = fetch_my_bets(me['user_id'])
        finished = [b for b in my_bets if b['status'] in ['WON', 'LOST']]
        wins = len([b for b in finished if b['status'] == 'WON'])
        total_fin = len(finished)
        
        pnl = 0
        for b in finished:
            if b['status'] == 'WON':
                pnl += (b['stake'] * b['odds_at_bet']) - b['stake']
            else:
                pnl -= b['stake']
                
        st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        kpi(col1, "通算損益", fmt_yen(pnl))
        kpi(col2, "的中数", f"{wins}/{total_fin}")
        win_rate = (wins/total_fin*100) if total_fin else 0
        kpi(col3, "勝率", f"{win_rate:.1f}%")
        st.markdown('</div>', unsafe_allow_html=True)
        
        # ★新機能2: 得意チーム分析
        if best_teams:
            st.markdown("<br><h5>🎯 得意なチーム (High Accuracy)</h5>", unsafe_allow_html=True)
            with st.container():
                st.markdown('<div class="app-card">', unsafe_allow_html=True)
                for tm, rate, w, t in best_teams:
                    st.markdown(f"""
                    <div class="team-stat-row">
                        <span><b>{tm}</b></span>
                        <span><b style="color:#4ade80">{rate*100:.0f}%</b> <span class="subtle">({w}/{t})</span></span>
                    </div>
                    """, unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

    # 2. 試合とベット
    with tabs[1]:
        # GW計算 (簡易的に直近の未消化試合があるGWを自動選択させたいが、ここは旧仕様の指定があればそれに従う)
        # 今回はDBから未来の試合があるGWをリストアップ
        matches = supabase.table("matches").select("gameweek").gte("kickoff_time", datetime.datetime.now().isoformat()).execute().data
        gws = sorted(list(set([m['gameweek'] for m in matches]))) if matches else [1]
        
        target_gw = st.selectbox("GW選択", [f"GW{g}" for g in gws])
        
        st.markdown(f"### {target_gw} の試合")
        matches_data = fetch_matches_for_gw(target_gw)
        
        if not matches_data:
            st.info("試合がありません")
        
        for m in matches_data:
            # 日時
            dt_local = to_local(m['kickoff_time'], JST)
            d_str = dt_local.strftime('%m/%d %H:%M') if dt_local else "-"
            
            oh = m.get('odds_home')
            od = m.get('odds_draw')
            oa = m.get('odds_away')
            
            # 旧アプリの .app-card デザイン
            with st.container():
                st.markdown(f"""
                <div class="app-card">
                    <div style="display:flex; justify-content:space-between; margin-bottom:10px">
                        <span class="subtle">GW{m['gameweek']}</span>
                        <span class="subtle">{d_str}</span>
                    </div>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:15px">
                        <div style="text-align:center; width:30%">
                            <div style="font-weight:bold">{m['home_team']}</div>
                            <div style="color:#4ade80;font-weight:bold">{oh or '-'}</div>
                        </div>
                        <div class="subtle">vs</div>
                        <div style="text-align:center; width:30%">
                            <div style="font-weight:bold">{m['away_team']}</div>
                            <div style="color:#4ade80;font-weight:bold">{oa or '-'}</div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
                
                # 投票フォーム
                with st.form(key=f"bet_{m['match_id']}"):
                    c1, c2, c3 = st.columns([3, 2, 2])
                    
                    label_h = f"HOME ({oh})" if oh else "HOME"
                    label_d = f"DRAW ({od})" if od else "DRAW"
                    label_a = f"AWAY ({oa})" if oa else "AWAY"
                    
                    sel = c1.radio("予想", [label_h, label_d, label_a], label_visibility="collapsed", horizontal=True)
                    stake = c2.number_input("金額", min_value=100, step=100, value=1000, label_visibility="collapsed")
                    submit = c3.form_submit_button("BET 🔥", use_container_width=True)
                    
                    if submit:
                        # オッズ特定
                        chosen = "HOME"
                        chosen_odds = 1.0
                        if "HOME" in sel: chosen, chosen_odds = "HOME", oh
                        elif "DRAW" in sel: chosen, chosen_odds = "DRAW", od
                        elif "AWAY" in sel: chosen, chosen_odds = "AWAY", oa
                        
                        try:
                            chosen_odds = float(chosen_odds)
                            if me['balance'] < stake:
                                st.error("残高不足です")
                            else:
                                upsert_bet(me['user_id'], m['match_id'], chosen, stake, chosen_odds)
                                # 残高減算
                                update_balance(me['user_id'], me['balance'] - stake)
                                st.success("ベット完了")
                                st.rerun()
                        except:
                            st.error("オッズが出ていません")
                            
                st.markdown("</div>", unsafe_allow_html=True)

    # 3. 履歴
    with tabs[2]:
        st.markdown("### Betting History")
        hist = fetch_my_bets(me['user_id'])
        # 新しい順
        hist.sort(key=lambda x: x['created_at'], reverse=True)
        
        if hist:
            data = []
            for h in hist:
                m = h['matches']
                res = h['status']
                
                # 損益
                pl = 0
                if res == 'WON':
                    pl = (h['stake'] * h['odds_at_bet']) - h['stake']
                elif res == 'LOST':
                    pl = -h['stake']
                
                dt_str = "-"
                if h['created_at']:
                    dt_str = to_local(h['created_at'], JST).strftime('%m/%d %H:%M')
                    
                data.append({
                    "Date": dt_str,
                    "Match": f"{m.get('home_team')} vs {m.get('away_team')}" if m else "-",
                    "Pick": h['choice'],
                    "Odds": h['odds_at_bet'],
                    "Stake": fmt_yen(h['stake']),
                    "Result": res,
                    "P&L": fmt_yen(pl)
                })
            st.dataframe(pd.DataFrame(data))
        else:
            st.info("履歴はありません")

    # 4. リアルタイム (Placeholder)
    with tabs[3]:
        st.info("リアルタイム速報 (Coming Soon via API)")

    # 5. ダッシュボード
    with tabs[4]:
        st.markdown("### Leaderboard")
        all_u = fetch_all_users()
        # バランス順
        all_u.sort(key=lambda x: x['balance'], reverse=True)
        
        for i, u in enumerate(all_u):
            st.markdown(f"""
            <div class="app-card" style="display:flex; justify-content:space-between; align-items:center">
                <div>
                    <span style="font-weight:bold; font-size:1.2rem; margin-right:10px; color:#888">{i+1}.</span>
                    <span style="font-weight:bold">{u['username']}</span>
                    <span class="subtle">({u.get('favorite_team','-')})</span>
                </div>
                <div style="font-weight:bold; font-size:1.2rem; color:#4ade80">
                    {fmt_yen(u['balance'])}
                </div>
            </div>
            """, unsafe_allow_html=True)

    # 6. オッズ管理
    with tabs[5]:
        st.markdown("### Odds Management")
        if me.get('role') == 'admin':
            st.info("管理者用機能（SQL直接操作またはAPI更新ボタンを利用）")
        else:
            st.warning("権限がありません")

if __name__ == "__main__":
    main()
