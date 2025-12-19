import streamlit as st
import pandas as pd
import requests
import datetime
import gspread
from datetime import timedelta, timezone
from supabase import create_client

# ==========================================
# 設定
# ==========================================
st.set_page_config(page_title="Master Repair Tool", layout="wide")
st.title("🚑 完全修復 & API同期ツール")

# 接続
try:
    # Supabase
    su_url = st.secrets["supabase"]["url"]
    su_key = st.secrets["supabase"]["key"]
    supabase = create_client(su_url, su_key)
    
    # Google Sheets
    gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
    
    # API Token
    # Configシートから取るか、Secretsから取る
    token = st.secrets.get("api_token")
    if not token:
        # Configシートから探す
        ws_conf = sh.worksheet("config")
        records = ws_conf.get_all_records()
        for r in records:
            if r.get('key') == 'FOOTBALL_DATA_API_TOKEN':
                token = r.get('value')
                break
except Exception as e:
    st.error(f"接続設定エラー: {e}")
    st.stop()

# ==========================================
# 処理ロジック
# ==========================================

def run_full_repair():
    logs = []
    
    # ----------------------------------------------------
    # 1. APIから全試合日程を取得 (Matchesの完全化)
    # ----------------------------------------------------
    st.subheader("1. 試合データのAPI同期")
    headers = {'X-Auth-Token': token}
    # 今シーズン全日程取得
    url = "https://api.football-data.org/v4/competitions/PL/matches?season=2024" # 2025年なら2024シーズン扱いの場合が多い
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            matches_data = res.json().get('matches', [])
            upsert_list = []
            for m in matches_data:
                upsert_list.append({
                    "match_id": m['id'],
                    "season": "2024", # 固定
                    "gameweek": m['matchday'],
                    "home_team": m['homeTeam']['name'],
                    "away_team": m['awayTeam']['name'],
                    "kickoff_time": m['utcDate'],
                    "status": m['status'],
                    "home_score": m['score']['fullTime']['home'],
                    "away_score": m['score']['fullTime']['away'],
                    # APIのオッズがあれば入れるが、ロックは解除しない方が安全かも
                    # ここではマスタデータ構築を優先
                })
            
            # 分割Upsert
            chunk_size = 100
            for i in range(0, len(upsert_list), chunk_size):
                supabase.table("matches").upsert(upsert_list[i:i+chunk_size]).execute()
                
            logs.append(f"✅ APIから {len(upsert_list)} 試合のデータを取得・保存しました。")
        else:
            st.error(f"API Error: {res.status_code}")
            return
    except Exception as e:
        st.error(f"API接続エラー: {e}")
        return

    # ----------------------------------------------------
    # 2. ベット履歴の再取込 (Status修正)
    # ----------------------------------------------------
    st.subheader("2. ベット履歴の再取込 (WIN/LOSE修正)")
    
    # 既存ベット全削除 (重複防ぐため洗い替え)
    supabase.table("bets").delete().neq("choice", "dummy").execute() # 全件
    
    # User ID マップ
    users = supabase.table("users").select("user_id, username").execute().data
    u_map = {u['username']: u['user_id'] for u in users}
    
    ws_bets = sh.worksheet("bets")
    sheet_bets = ws_bets.get_all_records()
    
    bets_payload = []
    skipped = 0
    
    for row in sheet_bets:
        uname = row.get('user')
        mid = row.get('match_id') or row.get('fd_match_id')
        
        # 数値変換など
        try: mid = int(float(str(mid)))
        except: mid = None
        
        if uname in u_map and mid:
            # ★ ここが重要: WIN/LOSE を WON/LOST に変換
            raw_res = str(row.get('result', '')).upper()
            status = 'PENDING'
            if 'WIN' in raw_res: status = 'WON'
            elif 'LOSE' in raw_res: status = 'LOST'
            elif 'SETTLED' in str(row.get('status','')).upper(): 
                # resultが空でもstatusがSETTLEDなら負けの可能性あるが、result優先
                pass
                
            bets_payload.append({
                "user_id": u_map[uname],
                "match_id": mid,
                "choice": row.get('pick'),
                "stake": int(float(str(row.get('stake', 0)).replace(',',''))),
                "odds_at_bet": float(row.get('odds', 1.0)),
                "status": status,
                "created_at": row.get('placed_at') or datetime.datetime.now().isoformat()
            })
        else:
            skipped += 1

    if bets_payload:
        # 分割Insert
        for i in range(0, len(bets_payload), 100):
            supabase.table("bets").insert(bets_payload[i:i+100]).execute()
        logs.append(f"✅ ベット履歴 {len(bets_payload)} 件を取り込みました (スキップ: {skipped}件)。")
    
    # ----------------------------------------------------
    # 3. BM履歴の取込
    # ----------------------------------------------------
    # BM履歴も洗い替え
    supabase.table("bm_history").delete().neq("season", "dummy").execute()
    
    ws_bm = sh.worksheet("bm_log")
    bm_data = ws_bm.get_all_records()
    bm_payload = []
    for row in bm_data:
        uname = row.get('bookmaker')
        gw_str = str(row.get('gw',''))
        # GW番号抽出
        gw_num = "".join([c for c in gw_str if c.isdigit()])
        
        if uname in u_map and gw_num:
            bm_payload.append({
                "season": "2024",
                "gameweek": int(gw_num),
                "user_id": u_map[uname],
                "created_at": row.get('decided_at')
            })
    
    if bm_payload:
        supabase.table("bm_history").insert(bm_payload).execute()
        logs.append(f"✅ BM履歴 {len(bm_payload)} 件を取り込みました。")

    # ----------------------------------------------------
    # 4. 収支再計算
    # ----------------------------------------------------
    st.subheader("3. 収支再計算")
    
    # リセット
    balances = {uid: 0 for uid in u_map.values()}
    
    # BMマップ
    bm_map = {} # (gw) -> uid
    for b in bm_payload:
        bm_map[b['gameweek']] = b['user_id']
        
    # ベット履歴から計算
    # DBに入れたばかりのデータを信頼して使う
    # しかしAPIからGWを取得したmatchesと紐づける必要がある
    
    # 結合が面倒なので、Python上でMatchのGWを参照
    matches_gw_map = {}
    all_matches = supabase.table("matches").select("match_id, gameweek").execute().data
    for m in all_matches:
        matches_gw_map[m['match_id']] = m['gameweek']
        
    for b in bets_payload:
        if b['status'] not in ['WON', 'LOST']: continue
        
        uid = b['user_id']
        profit = 0
        if b['status'] == 'WON':
            profit = int(b['stake'] * b['odds_at_bet']) - b['stake']
        else:
            profit = -b['stake']
            
        # Player反映
        balances[uid] += profit
        
        # BM反映
        mid = b['match_id']
        gw = matches_gw_map.get(mid)
        if gw:
            bm_id = bm_map.get(gw)
            if bm_id and bm_id != uid:
                balances[bm_id] -= profit

    # DB更新
    for uid, bal in balances.items():
        supabase.table("users").update({"balance": bal}).eq("user_id", uid).execute()
        
    logs.append("✅ 全員の収支を再計算し、DBを更新しました。")

    # ----------------------------------------------------
    # 5. GW自動判定
    # ----------------------------------------------------
    st.subheader("4. GW自動判定")
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # DBにはAPIから入れた正確なkickoff_timeがあるはず
    res = supabase.table("matches").select("gameweek, kickoff_time")\
        .gt("kickoff_time", now_iso)\
        .order("kickoff_time")\
        .limit(1)\
        .execute()
        
    target_gw = 1
    if res.data:
        target_gw = res.data[0]['gameweek']
        logs.append(f"✅ 未来の試合 ({res.data[0]['kickoff_time']}) を検知。次は GW{target_gw} です。")
    else:
        # シーズン終了等の場合
        last = supabase.table("matches").select("gameweek").order("kickoff_time", desc=True).limit(1).execute()
        if last.data:
            target_gw = last.data[0]['gameweek']
            logs.append(f"✅ 未来の試合なし。最新の GW{target_gw} を設定します。")
            
    supabase.table("app_config").upsert({"key": "current_gw", "value": str(target_gw)}).execute()

    # 完了
    st.success("🎉 すべての修復が完了しました！")
    for l in logs:
        st.write(l)
        
    # 結果表示
    st.write("### 📊 現在のステータス")
    final_users = supabase.table("users").select("username, balance").execute().data
    st.table(final_users)

if st.button("🚀 実行する", type="primary"):
    run_full_repair()
