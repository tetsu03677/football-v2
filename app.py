import streamlit as st
import pandas as pd
import requests
import datetime
import pytz
from datetime import timedelta, timezone
from supabase import create_client

# ------------------------------------------------------------
# 1. 初期設定 & 旧アプリのデザイン(CSS)完全踏襲
# ------------------------------------------------------------
st.set_page_config(page_title="Premier Picks V2", layout="wide")
JST = timezone(timedelta(hours=9), 'JST')

# 旧アプリのCSSをそのまま適用
CSS = """
<style>
.block-container {padding-top:3.2rem; padding-bottom:3rem;}
.app-card{border:1px solid rgba(120,120,120,.25); border-radius:10px; padding:18px; background:rgba(255,255,255,.02); margin-bottom: 10px;}
.subtle{color:rgba(255,255,255,.6); font-size:.9rem}
.kpi-row{display:flex; gap:12px; flex-wrap:wrap; margin-bottom: 20px;}
.kpi{flex:1 1 140px; border:1px solid rgba(120,120,120,.25); border-radius:10px; padding:10px 14px; background: rgba(255,255,255,0.05);}
.kpi .h{font-size:.8rem; color:rgba(255,255,255,.7)}
.kpi .v{font-size:1.4rem; font-weight:700}
.team-stat-card {
    background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.02) 100%);
    border-radius: 8px; padding: 10px; margin-bottom: 5px; border-left: 4px solid #4CAF50;
}
.potential-box {
    background-color: #dcfce7; color: #166534; padding: 12px; 
    border-radius: 8px; font-weight: bold; text-align: center; margin-top: 20px;
    border: 1px solid #86efac;
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ------------------------------------------------------------
# 2. データベース & 設定接続
# ------------------------------------------------------------
@st.cache_resource
def init_db():
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except:
        return None

supabase = init_db()

def get_app_config():
    """DBから設定読み込み"""
    try:
        rows = supabase.table("app_config").select("*").execute().data
        return {r['key']: r['value'] for r in rows}
    except:
        return {}

CONFIG = get_app_config()
API_TOKEN = CONFIG.get("FOOTBALL_DATA_API_TOKEN") or st.secrets.get("api_token")
SEASON_STR = CONFIG.get("API_FOOTBALL_SEASON", "2024-2025")

# ------------------------------------------------------------
# 3. ユーティリティ関数 (旧 util.py / ui_parts.py 相当)
# ------------------------------------------------------------
def fmt_yen(n):
    return f"¥{int(n):,}"

def to_jst(iso_str):
    if not iso_str: return "-"
    try:
        dt = pd.to_datetime(iso_str).tz_convert('Asia/Tokyo')
        return dt.strftime('%m/%d %H:%M')
    except:
        return str(iso_str)

def outcome_jp(o):
    return {"HOME":"ホーム勝","DRAW":"引分","AWAY":"アウェイ勝"}.get(o, "-")

def kpi_card(label, value, sub=None):
    st.markdown(f"""
    <div class="kpi">
        <div class="h">{label}</div>
        <div class="v">{value}</div>
        {f'<div class="h" style="font-size:0.8rem; opacity:0.7">{sub}</div>' if sub else ''}
    </div>
    """, unsafe_allow_html=True)

# ------------------------------------------------------------
# 4. データ取得 & ロジック
# ------------------------------------------------------------
def sync_data():
    """APIからデータ取得＆保存（旧 football_api.py のロジックを継承）"""
    if not API_TOKEN:
        return False, "APIトークン未設定"
    
    headers = {'X-Auth-Token': API_TOKEN}
    # 前後2週間の試合を取得
    d_now = datetime.datetime.now()
    d_from = (d_now - timedelta(days=14)).strftime('%Y-%m-%d')
    d_to = (d_now + timedelta(days=14)).strftime('%Y-%m-%d')
    url = f"https://api.football-data.org/v4/competitions/PL/matches?dateFrom={d_from}&dateTo={d_to}"
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200: return False, "APIエラー"
        matches = res.json().get('matches', [])
        
        upsert_list = []
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        for m in matches:
            mid = m['id']
            kickoff = m['utcDate']
            kickoff_dt = datetime.datetime.fromisoformat(kickoff.replace('Z', '+00:00'))
            
            # オッズ更新判定 (1時間前まで)
            hours_left = (kickoff_dt - now_utc).total_seconds() / 3600
            
            row = {
                "match_id": mid,
                "season": SEASON_STR,
                "gameweek": m['matchday'],
                "home_team": m['homeTeam']['name'],
                "away_team": m['awayTeam']['name'],
                "kickoff_time": kickoff,
                "status": m['status'],
                "home_score": m['score']['fullTime']['home'],
                "away_score": m['score']['fullTime']['away'],
                "last_updated": datetime.datetime.now().isoformat()
            }
            
            # オッズがあれば更新
            odds = m.get('odds', {})
            if odds.get('homeWin') and hours_left > 1.0:
                row["odds_home"] = odds.get('homeWin')
                row["odds_draw"] = odds.get('draw')
                row["odds_away"] = odds.get('awayWin')
            
            upsert_list.append(row)
            
        if upsert_list:
            supabase.table("matches").upsert(upsert_list).execute()
        return True, f"{len(upsert_list)}試合を更新"
    except Exception as e:
        return False, str(e)

def get_user_stats(user_id):
    """ユーザーの戦績、得意チーム、ポテンシャル利益を計算"""
    # 履歴取得
    bets = supabase.table("bets").select("*, matches(*)").eq("user_id", user_id).execute().data
    
    total_bets = 0
    wins = 0
    pnl = 0
    potential_profit = 0
    team_stats = {} # {TeamName: {bets: 0, wins: 0}}
    
    for b in bets:
        m = b['matches']
        if not m: continue
        
        stake = b['stake']
        odds = b['odds_at_bet'] or 1.0
        status = b['status']
        choice = b['choice']
        
        # 1. ポテンシャル利益 (PENDINGのみ)
        if status == "PENDING":
            potential_profit += (stake * odds) - stake
        
        # 2. 戦績集計 (決着済みのみ)
        elif status in ["WON", "LOST"]:
            total_bets += 1
            if status == "WON":
                wins += 1
                pnl += (stake * odds) - stake
            else:
                pnl -= stake
                
            # 3. 得意チーム分析 (HOME/AWAYベット時のみ、対象チームを特定)
            target_team = None
            if choice == "HOME": target_team = m['home_team']
            elif choice == "AWAY": target_team = m['away_team']
            
            if target_team:
                if target_team not in team_stats: team_stats[target_team] = {'cnt':0, 'win':0}
                team_stats[target_team]['cnt'] += 1
                if status == "WON":
                    team_stats[target_team]['win'] += 1

    # 得意チームのソート (勝率 > ベット数 でソート)
    sorted_teams = []
    for tm, s in team_stats.items():
        if s['cnt'] >= 2: # 最低2回以上ベットしているチームに限定
            rate = s['win'] / s['cnt']
            sorted_teams.append((tm, rate, s['cnt'], s['win']))
    
    # 勝率降順、回数降順
    sorted_teams.sort(key=lambda x: (x[1], x[2]), reverse=True)
    
    return {
        "total": total_bets,
        "wins": wins,
        "win_rate": (wins/total_bets*100) if total_bets else 0,
        "pnl": pnl,
        "potential": potential_profit,
        "best_teams": sorted_teams[:3] # Top 3
    }

# ------------------------------------------------------------
# 5. UI構築 (旧アプリ構成を再現)
# ------------------------------------------------------------
def login_ui():
    st.sidebar.markdown("## Login")
    users = supabase.table("users").select("username").execute().data
    if not users:
        st.error("User not found")
        return None
    
    u_list = [u['username'] for u in users]
    name = st.sidebar.selectbox("Username", u_list)
    pw = st.sidebar.text_input("Password", type="password")
    
    if st.sidebar.button("Login"):
        res = supabase.table("users").select("*").eq("username", name).single().execute()
        ud = res.data
        if ud and str(ud.get('password')) == str(pw):
            st.session_state['user'] = ud
            st.rerun()
        else:
            st.error("Invalid password")
    
    return st.session_state.get('user')

def main():
    if not supabase: st.stop()
    
    user = st.session_state.get('user')
    if not user:
        login_ui()
        st.stop()
        
    # --- ユーザー情報の最新化 ---
    user = supabase.table("users").select("*").eq("user_id", user['user_id']).single().execute().data
    st.session_state['user'] = user
    stats = get_user_stats(user['user_id'])

    # --- サイドバー (旧構成 + ポテンシャル利益) ---
    st.sidebar.markdown(f"### 👤 {user['username']}")
    st.sidebar.markdown(f"**Balance:** {fmt_yen(user['balance'])}")
    
    # ★新機能: ポテンシャル利益表示
    if stats['potential'] > 0:
        st.sidebar.markdown(f"""
        <div class="potential-box">
            <div style="font-size:0.8rem; opacity:0.8">🚀 Potential Profit</div>
            <div style="font-size:1.3rem">+{fmt_yen(stats['potential'])}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.sidebar.divider()
    if st.sidebar.button("データ更新"):
        with st.spinner("Updating..."):
            sync_data()
            st.rerun()
            
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None
        st.rerun()

    # --- メイン画面 (タブ構成の再現) ---
    # 旧: ["トップ", "試合とベット", "履歴", "リアルタイム", "ダッシュボード", "オッズ管理"]
    # 今回は主要機能を統合
    tabs = st.tabs(["トップ", "試合とベット", "履歴", "分析"])

    # 1. トップ (KPI表示)
    with tabs[0]:
        st.markdown("### Dashboard")
        
        # KPI Row
        st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
        col1, col2, col3, col4 = st.columns(4)
        with col1: kpi_card("所持金", fmt_yen(user['balance']))
        with col2: kpi_card("通算損益", fmt_yen(stats['pnl']), f"{stats['win_rate']:.1f}% Win")
        with col3: kpi_card("的中数", f"{stats['wins']} / {stats['total']}")
        with col4: kpi_card("推しチーム", user.get('favorite_team', '-'))
        st.markdown('</div>', unsafe_allow_html=True)
        
        # ★新機能: 得意チーム (きれいに表示)
        st.markdown("#### 🎯 Best Performing Teams")
        if stats['best_teams']:
            c1, c2, c3 = st.columns(3)
            for i, (team, rate, cnt, win) in enumerate(stats['best_teams']):
                with [c1, c2, c3][i]:
                    st.markdown(f"""
                    <div class="team-stat-card">
                        <div style="font-size:0.8rem; color:#aaa">No.{i+1}</div>
                        <div style="font-weight:bold; font-size:1.1rem; margin-bottom:5px">{team}</div>
                        <div style="display:flex; justify-content:space-between; align-items:end">
                            <span style="font-size:1.5rem; font-weight:bold; color:#4CAF50">{rate*100:.0f}%</span>
                            <span style="font-size:0.8rem; color:#ccc">{win}/{cnt} wins</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("データ不足のため分析できません")

    # 2. 試合とベット (旧 match-card デザイン再現)
    with tabs[1]:
        st.markdown("### Upcoming Matches")
        
        # 試合取得
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        matches = supabase.table("matches").select("*")\
            .gte("kickoff_time", now_iso)\
            .order("kickoff_time")\
            .limit(20).execute().data
            
        if not matches:
            st.info("No matches found.")
        
        for m in matches:
            # 日時整形
            t_str = to_jst(m['kickoff_time'])
            
            # オッズ表示 (無ければ - )
            oh = m.get('odds_home') or '-'
            od = m.get('odds_draw') or '-'
            oa = m.get('odds_away') or '-'
            
            # 旧アプリ風カードレイアウト
            with st.container():
                st.markdown(f"""
                <div class="app-card">
                    <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                        <span class="subtle">GW{m['gameweek']}</span>
                        <span class="subtle">{t_str}</span>
                    </div>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:15px">
                        <div style="text-align:center; width:35%">
                            <div style="font-weight:bold; font-size:1.1rem">{m['home_team']}</div>
                            <div style="color:#4CAF50; font-weight:bold">{oh}</div>
                        </div>
                        <div style="color:#666; font-size:0.9rem">vs</div>
                        <div style="text-align:center; width:35%">
                            <div style="font-weight:bold; font-size:1.1rem">{m['away_team']}</div>
                            <div style="color:#4CAF50; font-weight:bold">{oa}</div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
                
                # ベット機能
                with st.form(key=f"b_{m['match_id']}"):
                    c1, c2, c3 = st.columns([4, 3, 2])
                    with c1:
                        # ラジオボタンの選択肢作成
                        opts = [f"HOME ({oh})", f"DRAW ({od})", f"AWAY ({oa})"]
                        sel = st.radio("Pick", opts, label_visibility="collapsed", horizontal=True)
                    with c2:
                        amt = st.number_input("Stake", min_value=100, step=100, value=1000, label_visibility="collapsed")
                    with c3:
                        submit = st.form_submit_button("BET 🔥", use_container_width=True)
                    
                    if submit:
                        # 選択肢解析
                        target = "HOME" if "HOME" in sel else ("DRAW" if "DRAW" in sel else "AWAY")
                        val = oh if target=="HOME" else (od if target=="DRAW" else oa)
                        
                        try:
                            odds_val = float(val)
                            if user['balance'] < amt:
                                st.error("残高不足")
                            else:
                                # DB登録
                                supabase.table("bets").insert({
                                    "user_id": user['user_id'],
                                    "match_id": m['match_id'],
                                    "choice": target,
                                    "stake": amt,
                                    "odds_at_bet": odds_val,
                                    "status": "PENDING"
                                }).execute()
                                # 残高減算
                                supabase.table("users").update({"balance": user['balance'] - amt}).eq("user_id", user['user_id']).execute()
                                st.success("ベット完了！")
                                st.rerun()
                        except:
                            st.error("オッズ未定のためベット不可")
                            
                st.markdown("</div>", unsafe_allow_html=True)

    # 3. 履歴
    with tabs[2]:
        st.markdown("### Betting History")
        hist = supabase.table("bets").select("*, matches(home_team, away_team)")\
            .eq("user_id", user['user_id']).order("created_at", desc=True).limit(50).execute().data
            
        if hist:
            rows = []
            for h in hist:
                m = h['matches']
                res = h['status']
                color = "white"
                if res == "WON": color = "#4CAF50"
                elif res == "LOST": color = "#EF5350"
                
                payout = 0
                if res == "WON": payout = int(h['stake'] * h['odds_at_bet'])
                
                rows.append({
                    "Date": to_jst(h['created_at']),
                    "Match": f"{m['home_team']} vs {m['away_team']}",
                    "Pick": h['choice'],
                    "Odds": h['odds_at_bet'],
                    "Stake": h['stake'],
                    "Result": res,
                    "Return": payout
                })
            st.dataframe(pd.DataFrame(rows))
        else:
            st.info("No history yet.")

    # 4. 分析 (ランキング)
    with tabs[3]:
        st.markdown("### Leaderboard")
        ranks = supabase.table("users").select("username, balance, favorite_team").order("balance", desc=True).execute().data
        for i, r in enumerate(ranks):
            st.markdown(f"""
            <div class="app-card" style="display:flex; align-items:center; justify-content:space-between">
                <div style="display:flex; align-items:center; gap:10px">
                    <span style="font-size:1.2rem; font-weight:bold; color:#888">{i+1}.</span>
                    <span style="font-size:1.1rem">{r['username']}</span>
                    <span class="subtle" style="font-size:0.8rem">({r['favorite_team']})</span>
                </div>
                <div style="font-size:1.2rem; font-weight:bold; color:#4CAF50">{fmt_yen(r['balance'])}</div>
            </div>
            """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
