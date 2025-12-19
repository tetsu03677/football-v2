import streamlit as st
import pandas as pd
import requests
import datetime
import random
import pytz
from datetime import timedelta, timezone
from supabase import create_client

# ==============================================================================
# 0. 初期設定 & CSS (旧UI完全踏襲 + スマホ最適化)
# ==============================================================================
st.set_page_config(page_title="Premier Picks V2", layout="wide")
JST = timezone(timedelta(hours=9), 'JST')

# スマホで見やすいようにパディング調整＆旧CSSクラスの復元
st.markdown("""
<style>
.block-container {padding-top:2rem; padding-bottom:4rem;}

/* 旧アプリのデザイン定義 */
.app-card {
    border: 1px solid rgba(120,120,120,.25);
    border-radius: 12px;
    padding: 16px;
    background: rgba(255,255,255,.03);
    margin-bottom: 12px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}
.subtle { color: rgba(255,255,255,.6); font-size: 0.85rem; }
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

/* 新機能: ポテンシャル利益 (緑色のアクセント) */
.potential-box {
    margin-top: 10px; padding: 10px; border-radius: 8px;
    background: rgba(34, 197, 94, 0.1); border: 1px solid rgba(34, 197, 94, 0.3);
    color: #4ade80; text-align: center; font-size: 0.9rem;
}

/* 他人のベット状況アイコン */
.bet-icon {
    display: inline-block; padding: 2px 6px; border-radius: 4px; 
    font-size: 0.7rem; margin-right: 4px; background: rgba(255,255,255,0.1); color: #ccc;
}
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. データベース & 設定読み込み
# ==============================================================================
@st.cache_resource
def get_db():
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except:
        return None

supabase = get_db()

def get_config():
    try:
        data = supabase.table("app_config").select("*").execute().data
        return {item['key']: item['value'] for item in data}
    except:
        return {}

# ユーティリティ
def fmt_yen(n): return f"¥{int(n):,}"
def to_jst(iso_str):
    if not iso_str: return "-"
    try:
        return pd.to_datetime(iso_str).tz_convert(JST).strftime('%m/%d %H:%M')
    except: return iso_str

# ==============================================================================
# 2. ビジネスロジック (API連携・BM選定・自動ベット)
# ==============================================================================

# A. API連携とオッズ確定
def sync_data(api_token, season="2024"):
    if not api_token: return
    headers = {'X-Auth-Token': api_token}
    
    # 前後14日間の試合を取得（キャッシュ効率化）
    d_now = datetime.datetime.now()
    d_from = (d_now - timedelta(days=14)).strftime('%Y-%m-%d')
    d_to = (d_now + timedelta(days=14)).strftime('%Y-%m-%d')
    
    try:
        url = f"https://api.football-data.org/v4/competitions/PL/matches?dateFrom={d_from}&dateTo={d_to}"
        res = requests.get(url, headers=headers)
        if res.status_code != 200: return

        matches = res.json().get('matches', [])
        upsert_list = []
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        # 設定読み込み
        conf = get_config()
        lock_hours = float(conf.get('odds_lock_hours', 1.0))

        for m in matches:
            kickoff = m['utcDate']
            k_dt = datetime.datetime.fromisoformat(kickoff.replace('Z', '+00:00'))
            hours_left = (k_dt - now_utc).total_seconds() / 3600
            
            # オッズロック判定
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
            
            # オッズ更新 (ロックされていない場合のみAPI値を採用)
            # ※DBに既存のオッズがあるか確認するのが理想だが、ここでは「ロック前なら常に上書き」とする
            api_odds = m.get('odds', {})
            if not is_locked and api_odds.get('homeWin'):
                row["odds_home"] = api_odds.get('homeWin')
                row["odds_draw"] = api_odds.get('draw')
                row["odds_away"] = api_odds.get('awayWin')
                
            upsert_list.append(row)
            
        if upsert_list:
            supabase.table("matches").upsert(upsert_list).execute()
            
    except Exception as e:
        print(f"Sync Error: {e}")

# B. ベット精算とBMの損益反映 (P2P Settlement)
def settle_bets(bm_user_id):
    # 終了した試合で、かつPENDINGのベットを探す
    finished_matches = supabase.table("matches").select("match_id, home_score, away_score").eq("status", "FINISHED").execute().data
    if not finished_matches: return
    
    for m in finished_matches:
        mid = m['match_id']
        hs = m['home_score']
        as_ = m['away_score']
        
        # 結果判定
        result = "DRAW"
        if hs is not None and as_ is not None:
            if hs > as_: result = "HOME"
            elif as_ > hs: result = "AWAY"
        else:
            continue # スコア未定

        # PENDINGベットを取得
        pending = supabase.table("bets").select("*").eq("match_id", mid).eq("status", "PENDING").execute().data
        
        for b in pending:
            # 判定
            status = "LOST"
            payout = 0
            profit = -b['stake'] # プレイヤーの損益
            
            if b['choice'] == result:
                status = "WON"
                payout = int(b['stake'] * b['odds_at_bet'])
                profit = payout - b['stake']
            
            # 1. ベット状態更新
            supabase.table("bets").update({"status": status}).eq("bet_id", b['bet_id']).execute()
            
            # 2. お金の移動 (ゼロサム)
            # Player: profit分増える (負ければマイナス)
            rpc_params_player = {"p_user_id": b['user_id'], "p_amount": profit}
            supabase.rpc("increment_balance", rpc_params_player).execute()
            
            # BM: Playerの逆 (Playerが勝てばマイナス、負ければプラス)
            if bm_user_id:
                rpc_params_bm = {"p_user_id": bm_user_id, "p_amount": -profit}
                supabase.rpc("increment_balance", rpc_params_bm).execute()

# C. BM自動選定 (次節の準備)
def assign_next_bm(current_gw):
    # ロジック: まだこのGWのBMが決まっていない場合のみ実行
    # ここでは簡易的に「現在のGW」に対応するBMがいるかチェック
    # (本格実装には bm_history テーブルを参照)
    pass # 詳細は要件定義に基づき、シーズン進行に合わせて実装

# ==============================================================================
# 3. UI コンポーネント
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
    if not supabase: st.error("DB Error"); st.stop()
    
    # データ同期 (ログイン前でもバックグラウンドで行うとベターだが、今回はログイン後トリガー)
    conf = get_config()
    
    # ユーザー全取得
    users = supabase.table("users").select("*").execute().data
    me = login_ui(users)
    if not me: st.stop()
    
    # 最新ステータス取得
    me = next(u for u in users if u['username'] == me['username'])
    st.session_state['user'] = me
    
    # --- データ更新アクション ---
    if st.sidebar.button("🔄 データ更新 & 精算"):
        with st.spinner("Processing..."):
            token = conf.get("FOOTBALL_DATA_API_TOKEN") or st.secrets.get("api_token")
            sync_data(token, conf.get("API_FOOTBALL_SEASON", "2024"))
            # BMの特定 (仮: 今はTetsuがBMと仮定するか、Configから読む)
            # 本来は bm_history から「今週のBM」を取得する
            current_bm_id = None # 実装時にはここを特定する
            settle_bets(current_bm_id)
            st.success("Updated!")
            st.rerun()

    # --- サイドバー情報 ---
    st.sidebar.markdown(f"## 👤 {me['username']}")
    st.sidebar.markdown(f"**{me.get('favorite_team','-')}**")
    
    # バランス表示
    bal_color = "#4ade80" if me['balance'] >= 0 else "#f87171"
    st.sidebar.markdown(f"<div style='font-size:1.5rem;font-weight:bold;color:{bal_color}'>{fmt_yen(me['balance'])}</div>", unsafe_allow_html=True)
    
    # ポテンシャル利益計算
    my_pending = supabase.table("bets").select("*").eq("user_id", me['user_id']).eq("status", "PENDING").execute().data
    pot_profit = sum([(b['stake'] * b['odds_at_bet']) - b['stake'] for b in my_pending])
    
    if pot_profit > 0:
        st.sidebar.markdown(f"""
        <div class="potential-box">
            🚀 Potential: +{fmt_yen(pot_profit)}
        </div>
        """, unsafe_allow_html=True)
        
    st.sidebar.divider()
    if st.sidebar.button("Logout"):
        st.session_state['user'] = None
        st.rerun()

    # --- タブ構成 (旧アプリ踏襲) ---
    tabs = st.tabs(["トップ", "試合とベット", "履歴", "リアルタイム", "ダッシュボード", "オッズ管理"])

    # [1] トップ (KPI)
    with tabs[0]:
        st.markdown(f"#### Dashboard")
        
        # 集計
        my_bets = supabase.table("bets").select("*").eq("user_id", me['user_id']).execute().data
        finished = [b for b in my_bets if b['status'] in ['WON','LOST']]
        wins = len([b for b in finished if b['status']=='WON'])
        total = len(finished)
        win_rate = (wins/total*100) if total else 0.0
        
        st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"<div class='kpi'><div class='h'>Current Balance</div><div class='v' style='color:{bal_color}'>{fmt_yen(me['balance'])}</div></div>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"<div class='kpi'><div class='h'>Win Rate</div><div class='v'>{win_rate:.1f}%</div></div>", unsafe_allow_html=True)
        with col3:
            st.markdown(f"<div class='kpi'><div class='h'>Total Bets</div><div class='v'>{len(my_bets)}</div></div>", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
        # 得意チーム分析
        # (簡易ロジック: 勝ち数が多いチームを表示)
        # TODO: 本格実装は pandas で集計

    # [2] 試合とベット
    with tabs[1]:
        # GW選択 (現在はConfigのcurrent_gwをデフォルトに)
        curr_gw = int(conf.get("current_gw", 1))
        matches = supabase.table("matches").select("*").eq("gameweek", curr_gw).order("kickoff_time").execute().data
        
        st.markdown(f"### GW{curr_gw} Matches")
        
        if not matches:
            st.info("No matches found for this Gameweek.")
        
        # 他人のベット状況を取得
        all_bets_gw = supabase.table("bets").select("match_id, choice, user_id").in_("match_id", [m['match_id'] for m in matches]).execute().data
        
        for m in matches:
            # 他人のベット表示用
            others_html = ""
            for b in all_bets_gw:
                if b['match_id'] == m['match_id'] and b['user_id'] != me['user_id']:
                    # ユーザー名特定
                    u_name = next((u['username'] for u in users if u['user_id'] == b['user_id']), "Unknown")
                    others_html += f"<span class='bet-icon'>👤{u_name}:{b['choice']}</span>"

            # オッズ
            oh = m.get('odds_home') or '-'
            od = m.get('odds_draw') or '-'
            oa = m.get('odds_away') or '-'
            
            # カードUI
            st.markdown(f"""
            <div class="app-card">
                <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                    <span class="subtle">{to_jst(m['kickoff_time'])}</span>
                    <span class="subtle">{others_html}</span>
                </div>
                <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px">
                    <div style="text-align:center; flex:1">
                        <div style="font-weight:bold">{m['home_team']}</div>
                        <div style="color:#4ade80; font-weight:bold">{oh}</div>
                    </div>
                    <div class="subtle">vs</div>
                    <div style="text-align:center; flex:1">
                        <div style="font-weight:bold">{m['away_team']}</div>
                        <div style="color:#4ade80; font-weight:bold">{oa}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            # ベット入力フォーム (スマホ最適化)
            with st.form(key=f"bet_{m['match_id']}"):
                c1, c2 = st.columns([3, 1])
                # ラジオボタン
                opts = [f"HOME ({oh})", f"DRAW ({od})", f"AWAY ({oa})"]
                choice = c1.radio("Pick", opts, label_visibility="collapsed", horizontal=True)
                # 金額 (100円単位)
                stake = c2.number_input("Stake", min_value=100, step=100, value=1000, label_visibility="collapsed")
                
                if st.form_submit_button("BET 🔥", use_container_width=True):
                    # ロジック: オッズ確定
                    target = "HOME" if "HOME" in choice else ("DRAW" if "DRAW" in choice else "AWAY")
                    odds_val = oh if target=="HOME" else (od if target=="DRAW" else oa)
                    
                    if not odds_val or odds_val == '-':
                        st.error("オッズ未定")
                    elif m.get('odds_locked'): 
                         # ロックされていてもベット自体は締め切り時間までOKなら通す
                         # ここでは簡易的にAPIオッズがあればOKとする
                         pass

                    # DB登録
                    try:
                        supabase.table("bets").insert({
                            "user_id": me['user_id'],
                            "match_id": m['match_id'],
                            "choice": target,
                            "stake": stake,
                            "odds_at_bet": float(odds_val),
                            "status": "PENDING"
                        }).execute()
                        st.success("Bet Placed!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
            
            st.markdown("</div>", unsafe_allow_html=True)

    # [3] 履歴
    with tabs[2]:
        st.markdown("### History")
        # 自分の履歴
        my_hist = supabase.table("bets").select("*, matches(home_team, away_team)").eq("user_id", me['user_id']).order("created_at", desc=True).limit(30).execute().data
        
        if my_hist:
            data = []
            for h in my_hist:
                m = h['matches']
                res = h['status']
                profit = 0
                if res == "WON": profit = int(h['stake']*h['odds_at_bet']) - h['stake']
                elif res == "LOST": profit = -h['stake']
                
                data.append({
                    "Date": to_jst(h['created_at']),
                    "Match": f"{m.get('home_team')} vs {m.get('away_team')}",
                    "Pick": h['choice'],
                    "Stake": fmt_yen(h['stake']),
                    "Result": res,
                    "P&L": fmt_yen(profit)
                })
            st.dataframe(pd.DataFrame(data))
        else:
            st.info("No history.")

    # [4] リアルタイム (Coming Soon)
    with tabs[3]:
        st.info("Live Scores & Realtime P&L (API Integration Ready)")

    # [5] ダッシュボード
    with tabs[4]:
        st.markdown("### Leaderboard")
        sorted_users = sorted(users, key=lambda x: x['balance'], reverse=True)
        for i, u in enumerate(sorted_users):
            st.markdown(f"""
            <div class="app-card" style="display:flex; justify-content:space-between; align-items:center">
                <div>
                    <span style="font-weight:bold; font-size:1.1rem; color:#888; margin-right:8px">{i+1}.</span>
                    <span style="font-weight:bold">{u['username']}</span>
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
            st.write("Admin Config:")
            st.json(conf)
            st.write("※設定変更はDBの app_config テーブルを直接編集してください")
        else:
            st.warning("Admin only.")

if __name__ == "__main__":
    main()
