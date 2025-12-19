import streamlit as st
import gspread
import pandas as pd
import json
import datetime
from supabase import create_client

st.set_page_config(page_title="Data Migration Tool", layout="wide")
st.title("📦 Google Sheets to Supabase 移行ツール")

# --- 接続設定 ---
def init_connections():
    try:
        # Supabase
        su_url = st.secrets["supabase"]["url"]
        su_key = st.secrets["supabase"]["key"]
        supabase = create_client(su_url, su_key)
        
        # Google Sheets
        gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
        
        return supabase, sh
    except Exception as e:
        st.error(f"接続エラー: {e}")
        return None, None

supabase, sh = init_connections()

# --- ユーティリティ ---
def safe_int(v):
    try: return int(float(str(v)))
    except: return None

def safe_float(v):
    try: return float(str(v))
    except: return None

# --- メイン移行処理 ---
if st.button("🚀 データ移行を開始する"):
    if not supabase or not sh:
        st.stop()
        
    status = st.empty()
    log_area = st.container()

    with log_area:
        # 1. Config & Users (configシート)
        status.info("1/5: 設定とユーザー情報を移行中...")
        ws_conf = sh.worksheet("config")
        conf_data = ws_conf.get_all_records()
        
        # Config移行
        conf_payload = []
        users_json = None
        for row in conf_data:
            k = str(row.get('key',''))
            v = str(row.get('value',''))
            if k == 'users_json':
                users_json = v
            if k:
                conf_payload.append({'key': k, 'value': v})
        
        if conf_payload:
            supabase.table("app_config").upsert(conf_payload).execute()
            st.write(f"✅ Config: {len(conf_payload)}件")

        # Users移行
        user_map = {} # username -> user_id (UUID) のマッピング用
        if users_json:
            try:
                users_list = json.loads(users_json)
                for u in users_list:
                    # insertしてuser_idを取得
                    res = supabase.table("users").upsert({
                        "username": u.get('username'),
                        "password": u.get('password'),
                        "role": u.get('role', 'user'),
                        "favorite_team": u.get('team'),
                        "balance": 0 # 初期値は0 (必要ならCSVから計算可能)
                    }, on_conflict="username").select().execute()
                    
                    if res.data:
                        user_map[u.get('username')] = res.data[0]['user_id']
                st.write(f"✅ Users: {len(user_map)}名を登録")
            except Exception as e:
                st.error(f"Users JSON parse error: {e}")

        # 2. Matches (oddsシート & resultシート)
        status.info("2/5: 試合データを結合・移行中...")
        try:
            ws_odds = sh.worksheet("odds")
            ws_res = sh.worksheet("result")
            odds_data = ws_odds.get_all_records()
            res_data = ws_res.get_all_records()
            
            matches_map = {} # match_id -> data

            # Oddsから基本情報
            for row in odds_data:
                mid = safe_int(row.get('match_id') or row.get('fd_match_id'))
                if not mid: continue
                
                # GWの数値化 (GW7 -> 7)
                gw_str = str(row.get('gw',''))
                gw_num = safe_int(''.join(filter(str.isdigit, gw_str)))

                matches_map[mid] = {
                    "match_id": mid,
                    "season": "2024", # 初期値
                    "gameweek": gw_num,
                    "home_team": row.get('home\n') or row.get('home'), # 表記揺れ対応
                    "away_team": row.get('away'),
                    "odds_home": safe_float(row.get('home_win')),
                    "odds_draw": safe_float(row.get('draw')),
                    "odds_away": safe_float(row.get('away_win')),
                    "odds_locked": True if str(row.get('locked')).upper() == 'YES' else False
                }

            # Resultからスコア情報などをマージ
            for row in res_data:
                mid = safe_int(row.get('match_id'))
                if mid and mid in matches_map:
                    matches_map[mid].update({
                        "status": row.get('status'),
                        "home_score": safe_int(row.get('home_score')),
                        "away_score": safe_int(row.get('away_score')),
                        "kickoff_time": row.get('utc_kickoff') # 日時
                    })

            # DBへ一括登録
            if matches_map:
                match_list = list(matches_map.values())
                # 100件ずつ分割insert
                for i in range(0, len(match_list), 100):
                    supabase.table("matches").upsert(match_list[i:i+100]).execute()
                st.write(f"✅ Matches: {len(match_list)}試合")
        except Exception as e:
            st.error(f"Matches error: {e}")

        # 3. Bets (betsシート)
        status.info("3/5: ベット履歴を移行中...")
        try:
            ws_bets = sh.worksheet("bets")
            bets_data = ws_bets.get_all_records()
            bets_payload = []
            
            for row in bets_data:
                uname = row.get('user')
                mid = safe_int(row.get('match_id'))
                
                # ユーザーIDと試合IDが存在する場合のみ移行
                if uname in user_map and mid in matches_map:
                    bets_payload.append({
                        "user_id": user_map[uname],
                        "match_id": mid,
                        "choice": row.get('pick'),
                        "stake": safe_int(row.get('stake')),
                        "odds_at_bet": safe_float(row.get('odds')),
                        "status": row.get('result') if row.get('result') in ['WON','LOST'] else 'PENDING',
                        "created_at": row.get('placed_at')
                    })
            
            if bets_payload:
                for i in range(0, len(bets_payload), 100):
                    supabase.table("bets").insert(bets_payload[i:i+100]).execute()
                st.write(f"✅ Bets: {len(bets_payload)}件")
        except Exception as e:
            st.warning(f"Bets sheet missing or error: {e}")

        # 4. BM History (bm_logシート)
        status.info("4/5: BM履歴を移行中...")
        try:
            ws_bm = sh.worksheet("bm_log") # シート名要確認
            bm_data = ws_bm.get_all_records()
            bm_payload = []
            
            for row in bm_data:
                uname = row.get('bookmaker')
                gw_str = str(row.get('gw',''))
                gw_num = safe_int(''.join(filter(str.isdigit, gw_str)))
                
                if uname in user_map:
                    bm_payload.append({
                        "user_id": user_map[uname],
                        "season": "2024",
                        "gameweek": gw_num,
                        "created_at": row.get('decided_at')
                    })
            
            if bm_payload:
                supabase.table("bm_history").insert(bm_payload).execute()
                st.write(f"✅ BM Logs: {len(bm_payload)}件")
        except:
            st.info("BM Log sheet not found, skipping.")

        status.success("🎉 全データの移行が完了しました！")
        st.balloons()
