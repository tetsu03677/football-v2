import streamlit as st
import pandas as pd
import requests
import datetime
from datetime import timedelta, timezone
from supabase import create_client

# ==============================================================================
# 1. CSS & UI 定義 (旧 app.py / ui_parts.py から完全移植)
# ==============================================================================
st.set_page_config(page_title="Premier Picks V2", layout="wide")

# 旧アプリのCSS定義をそのまま使用
CSS = """
<style>
.block-container {padding-top:3.2rem; padding-bottom:3rem;}
.app-card{border:1px solid rgba(120,120,120,.25); border-radius:10px; padding:18px; background:rgba(255,255,255,.02); margin-bottom:12px;}
.subtle{color:rgba(255,255,255,.6); font-size:.9rem}
.kpi-row{display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px;}
.kpi{flex:1 1 140px; border:1px solid rgba(120,120,120,.25); border-radius:10px; padding:10px 14px; background:rgba(255,255,255,0.02);}
.kpi .h{font-size:.8rem; color:rgba(255,255,255,.7)}
.kpi .v{font-size:1.4rem; font-weight:700}
/* 新機能用: ポテンシャル利益 (旧デザインに馴染む緑) */
.potential-box {
    margin-top: 10px; padding: 10px; border-radius: 8px;
    background: rgba(34, 197, 94, 0.1); border: 1px solid rgba(34, 197, 94, 0.3);
    color: #4ade80; text-align: center;
}
/* 新機能用: チーム分析カード */
.team-stat-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.1); }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ui_parts.py の関数群を再現
def section_header(title: str):
    st.markdown(f"## {title}")

def muted(text: str):
    st.markdown(f"<span style='color:#6b7280'>{text}</span>", unsafe_allow_html=True)

def tag(text: str, kind: str = "info"):
    # ダークモード対応の色調整
    color = {"info":"#374151","success":"#064e3b","danger":"#7f1d1d"}.get(kind,"#374151")
    text_col = {"info":"#d1d5db","success":"#34d399","danger":"#fca5a5"}.get(kind,"#d1d5db")
    return f"<span style='background:{color};color:{text_col};padding:2px 8px;border-radius:999px;font-size:0.8em'>{text}</span>"

def pill(text: str, kind: str = "info"):
    st.markdown(tag(text, kind), unsafe_allow_html=True)

def kpi(container, label, value, sub=None):
    with container:
        sub_html = f"<div style='font-size:0.8rem;opacity:0.6'>{sub}</div>" if sub else ""
        st.markdown(f"""
        <div class='kpi'>
          <div class='h'>{label}</div>
          <div class='v'>{value}</div>
          {sub_html}
        </div>
        """, unsafe_allow_html=True)

# ユーティリティ
def fmt_yen(n): return f"¥{int(n):,}"

# ==============================================================================
# 2. データベース接続 (Supabase)
# ==============================================================================
@st.cache_resource
def init_db():
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except:
        return None

supabase = init_db()

# 設定読み込み
def get_conf():
    try:
        rows = supabase.table("app_config").select("*").execute().data
        return {r['key']: r['value'] for r in rows}
    except:
        return {}

CONFIG = get_conf()
API_TOKEN = CONFIG.get("FOOTBALL_DATA_API_TOKEN") or st.secrets.get("api_token")

# ==============================================================================
# 3. ロジック (API連携・オッズ確定・分析)
# ==============================================================================
def sync_data_logic():
    """APIから試合情報を取得しDB更新 + オッズ確定ロジック"""
    if not API_TOKEN: return

    headers = {'X-Auth-Token': API_TOKEN}
    # 前後2週間
    d_now = datetime.datetime.now()
    d_from = (d_now - timedelta(days=14)).strftime('%Y-%m-%d')
    d_to = (d_now + timedelta(days=14)).strftime('%Y-%m-%d')
    url = f"https://api.football-data.org/v4/competitions/PL/matches?dateFrom={d_from}&dateTo={d_to}"
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            matches = res.json().get('matches', [])
            upsert_list = []
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            
            for m in matches:
                # オッズ確定判定 (1時間前)
                kickoff = m['utcDate']
                kickoff_dt = datetime.datetime.fromisoformat(kickoff.replace('Z', '+00:00'))
                hours_left = (kickoff_dt - now_utc).total_seconds() / 3600
                
                row = {
                    "match_id": m['id'],
                    "season": "2024-2025",
                    "gameweek": m['matchday'],
                    "home_team": m['homeTeam']['name'],
                    "away_team": m['awayTeam']['name'],
                    "kickoff_time": kickoff,
                    "status": m['status'],
                    "home_score": m['score']['fullTime']['home'],
                    "away_score": m['score']['fullTime']['away'],
                    "last_updated": datetime.datetime.now().isoformat()
                }
                # 時間に余裕がある場合のみオッズ更新
                odds = m.get('odds', {})
                if odds.get('homeWin') and hours_left > 1.0:
                    row["odds_home"] = odds.get('homeWin')
                    row["odds_draw"] = odds.get('draw')
                    row["odds_away"] = odds.get('awayWin')
                
                upsert_list.append(row)
            
            if upsert_list:
                supabase.table("matches").upsert(upsert_list).execute()
    except:
        pass

def get_stats(user_id):
    """KPI、ポテンシャル利益、得意チーム分析"""
    # 履歴全件
    bets = supabase.table("bets").select("*, matches(*)").eq("user_id", user_id).execute().data
    
    total = 0
    wins = 0
    pnl = 0
    potential = 0
    team_stats = {} # {TeamName: {bets:0, wins:0}}

    for b in bets:
        m = b['matches']
        if not m: continue
        
        status = b['status']
        stake = b['stake']
        odds = b['odds_at_bet'] or 1.0
        
        if status == "PENDING":
            potential += (stake * odds) - stake
        elif status in ["WON", "LOST"]:
            total += 1
            if status == "WON":
                wins += 1
                pnl += (stake * odds) - stake
            else:
                pnl -= stake
                
            # 得意チーム集計
            tgt = None
            if b['choice'] == "HOME": tgt = m['home_team']
            elif b['choice'] == "AWAY": tgt = m['away_team']
            
            if tgt:
                if tgt not in team_stats: team_stats[tgt] = {'cnt':0, 'win':0}
                team_stats[tgt]['cnt'] += 1
                if status == "WON": team_stats[tgt]['win'] += 1
                
    # 得意チームソート (勝率 > 回数)
    best_teams = []
    for tm, d in team_stats.items():
        if d['cnt'] >= 2: # 最低2回以上
            rate = d['win']/d['cnt']
            best_teams.append((tm, rate, d['cnt']))
    best_teams.sort(key=lambda x: (x[1], x[2]), reverse=True)
    
    return {
        "total": total, "wins": wins, "pnl": pnl, "potential": potential,
        "best_teams": best_teams[:3]
    }

# ==============================================================================
# 4. メイン UI
# ==============================================================================
def login_ui():
    st.sidebar.markdown("## Login")
    users = supabase.table("users").select("username").execute().data
    if not users:
        st.error("No users found in DB")
        return None
    name = st.sidebar.selectbox("Username", [u['username'] for u in users])
    pw = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        u = supabase.table("users").select("*").eq("username", name).single().execute().data
        if u and str(u.get('password')) == str(pw):
            st.session_state['user'] = u
            st.rerun()
        else:
            st.error("Invalid Password")
    return st.session_state.get('user')

def main():
    if not supabase: 
        st.error("DB Connection Failed"); st.stop()

    user = st.session_state.get('user')
    if not user:
        login_ui()
        st.stop()
        
    # 最新情報取得
    user = supabase.table("users").select("*").eq("user_id", user['user_id']).single().execute().data
    st.session_state['user'] = user
    stats = get_stats(user['user_id'])
    
    # --- サイドバー (旧アプリ構成維持 + 新機能) ---
    st.sidebar.markdown(f"### 👤 {user['username']}")
    st.sidebar.markdown(f"**{user.get('favorite_team','')}**")
    st.sidebar.divider()
    
    # Balance表示
    st.sidebar.metric("Balance", fmt_yen(user['balance']))
    
    # ★新機能: ポテンシャル利益 (デザインを崩さず挿入)
    if stats['potential'] > 0:
        st.sidebar.markdown(f"""
        <div class="potential-box">
            <div style="font-size:0.8rem; opacity:0.8">🚀 Potential Profit</div>
            <div style="font-size:1.2rem; font-weight:bold">+{fmt_yen(stats['potential'])}</div>
        </div>
        """, unsafe_allow_html=True)

    st.sidebar.divider()
    if st.sidebar.button("🔄 データ更新"):
        with st.spinner("Updating..."):
            sync_data_logic()
            st.rerun()
            
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None
        st.rerun()

    # --- メイン画面 (6タブ構成を完全再現) ---
    tabs = st.tabs(["トップ", "試合とベット", "履歴", "リアルタイム", "ダッシュボード", "オッズ管理"])

    # 1. トップ
    with tabs[0]:
        st.markdown(f"### 👋 Welcome back, {user['username']}")
        
        # KPI Row
        st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        win_rate = (stats['wins']/stats['total']*100) if stats['total'] else 0
        kpi(c1, "通算損益", fmt_yen(stats['pnl']), f"Win Rate: {win_rate:.1f}%")
        kpi(c2, "総ベット数", f"{stats['total']} <span style='font-size:0.8rem'>bets</span>")
        kpi(c3, "的中数", f"{stats['wins']} <span style='font-size:0.8rem'>wins</span>")
        st.markdown('</div>', unsafe_allow_html=True)
        
        # ★新機能: 得意チーム分析 (旧デザインに合わせたカード表示)
        st.markdown("#### 🎯 Best Teams")
        if stats['best_teams']:
            with st.container():
                st.markdown('<div class="app-card">', unsafe_allow_html=True)
                for tm, rate, cnt in stats['best_teams']:
                    st.markdown(f"""
                    <div class="team-stat-row">
                        <div style="font-weight:bold">{tm}</div>
                        <div style="text-align:right">
                            <span style="color:#4ade80; font-weight:bold">{rate*100:.0f}%</span>
                            <span class="subtle" style="font-size:0.8rem"> ({cnt} bets)</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("データ不足のため分析できません")

    # 2. 試合とベット
    with tabs[1]:
        st.markdown("### Upcoming Matches")
        
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        matches = supabase.table("matches").select("*").gte("kickoff_time", now_iso).order("kickoff_time").limit(30).execute().data
        
        if not matches: st.info("No matches.")
        
        for m in matches:
            # 日時変換
            try:
                dt = pd.to_datetime(m['kickoff_time']).tz_convert('Asia/Tokyo')
                d_str = dt.strftime('%m/%d %H:%M')
            except: d_str = "-"
            
            oh = m.get('odds_home') or '-'
            od = m.get('odds_draw') or '-'
            oa = m.get('odds_away') or '-'

            # 旧アプリの .app-card 構成を再現
            st.markdown(f"""
            <div class="app-card">
                <div style="display:flex; justify-content:space-between; margin-bottom:10px">
                    <span class="subtle">GW{m['gameweek']}</span>
                    <span class="subtle">{d_str}</span>
                </div>
                <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:15px">
                    <div style="text-align:center; flex:1">
                        <div style="font-weight:bold">{m['home_team']}</div>
                        <div style="color:#4ade80">{oh}</div>
                    </div>
                    <div class="subtle">vs</div>
                    <div style="text-align:center; flex:1">
                        <div style="font-weight:bold">{m['away_team']}</div>
                        <div style="color:#4ade80">{oa}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            with st.form(key=f"b_{m['match_id']}"):
                c1, c2, c3 = st.columns([4, 3, 2])
                with c1:
                    opts = [f"HOME ({oh})", f"DRAW ({od})", f"AWAY ({oa})"]
                    sel = st.radio("Pick", opts, label_visibility="collapsed", horizontal=True)
                with c2:
                    stk = st.number_input("Stake", min_value=100, step=100, value=1000, label_visibility="collapsed")
                with c3:
                    submit = st.form_submit_button("BET")
                
                if submit:
                    raw = "HOME" if "HOME" in sel else ("DRAW" if "DRAW" in sel else "AWAY")
                    try:
                        odds_val = float(oh if raw=="HOME" else (od if raw=="DRAW" else oa))
                        if user['balance'] < stk:
                            st.error("残高不足")
                        else:
                            supabase.table("bets").insert({
                                "user_id": user['user_id'], "match_id": m['match_id'],
                                "choice": raw, "stake": stk, "odds_at_bet": odds_val, "status": "PENDING"
                            }).execute()
                            supabase.table("users").update({"balance": user['balance'] - stk}).eq("user_id", user['user_id']).execute()
                            st.success("Success!")
                            st.rerun()
                    except:
                        st.error("オッズ未定")
            st.markdown("</div>", unsafe_allow_html=True)

    # 3. 履歴
    with tabs[2]:
        st.markdown("### Betting History")
        my_bets = supabase.table("bets").select("*, matches(*)").eq("user_id", user['user_id']).order("created_at", desc=True).limit(50).execute().data
        
        if my_bets:
            rows = []
            for b in my_bets:
                m = b['matches'] or {}
                res = b['status']
                # PnL計算
                profit = 0
                if res == "WON": profit = (b['stake'] * b['odds_at_bet']) - b['stake']
                elif res == "LOST": profit = -b['stake']
                
                rows.append({
                    "Date": pd.to_datetime(b['created_at']).tz_convert('Asia/Tokyo').strftime('%m/%d %H:%M'),
                    "Match": f"{m.get('home_team')} vs {m.get('away_team')}",
                    "Pick": b['choice'],
                    "Odds": b['odds_at_bet'],
                    "Result": res,
                    "P&L": fmt_yen(profit)
                })
            st.dataframe(pd.DataFrame(rows))
        else:
            st.info("履歴なし")

    # 4. リアルタイム (旧アプリのプレースホルダー)
    with tabs[3]:
        st.info("Realtime Score Feature (Coming Soon with API integration)")

    # 5. ダッシュボード (ランキング等)
    with tabs[4]:
        st.markdown("### Leaderboard")
        users_list = supabase.table("users").select("username, balance, favorite_team").order("balance", desc=True).execute().data
        for i, u in enumerate(users_list):
            st.markdown(f"""
            <div class="app-card" style="display:flex; justify-content:space-between; align-items:center">
                <div>
                    <span style="font-weight:bold; font-size:1.2rem; color:#666; margin-right:10px">{i+1}.</span>
                    <span style="font-weight:bold">{u['username']}</span>
                    <span class="subtle" style="font-left:10px">({u.get('favorite_team','-')})</span>
                </div>
                <div style="font-weight:bold; font-size:1.2rem; color:#4ade80">{fmt_yen(u['balance'])}</div>
            </div>
            """, unsafe_allow_html=True)

    # 6. オッズ管理 (管理者用)
    with tabs[5]:
        st.markdown("### Odds Management")
        if user.get('role') == 'admin':
            st.info("管理者機能: オッズの手動上書きなどが可能です (実装準備中)")
        else:
            st.error("管理者権限が必要です")

if __name__ == "__main__":
    main()
