import streamlit as st
import gspread
import pandas as pd
import json
import datetime
from supabase import create_client

st.set_page_config(page_title="Data Migration Tool Fix", layout="wide")
st.title("📦 Google Sheets to Supabase 移行ツール (修正版)")

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

def clean_time(v):
    """空文字や無効な日付をNoneに変換"""
    if not v or str(v).strip() == "":
        return None
    return str(v)

def find_sheet(sh, name_candidates):
    """シート名をあいまい検索で見つける"""
    for ws in sh.worksheets():
        for candidate in name_candidates:
            if candidate.lower() in ws.title.lower():
                return ws
    return None

# --- メイン移行処理 ---
if st.button("🚀 データ移行を開始する (Fix)"):
    if not supabase or not sh:
        st.stop()
        
    status = st.empty()
    log_area = st.container()

    # マッピング用辞書
    user_map = {}     # username -> user_id
    matches_map = {}  # match_id -> data

    with log_area:
        # ---------------------------------------------------
        # 1. Config & Users
        # ---------------------------------------------------
        status.info("1/5: 設定とユーザー情報を移行中...")
        ws_conf = find_sheet(sh, ["config"])
        if ws_conf:
            conf_data = ws_conf.get_all_records()
            conf_payload = []
            users_json = None
            
            for row in conf_data:
                k = str(row.get('key',''))
                v = str(row.get('value',''))
                if k == 'users_json':
                    users_json = v
                if k:
                    conf_payload.append({'key': k, 'value': v})
            
            # Config upsert
            if conf_payload:
                try:
                    supabase.table("app_config").upsert(conf_payload).execute()
                    st.write(f"✅ Config: {len(conf_payload)}件")
                except Exception as e:
                    st.error(f"Config Error: {e}")

            # Users upsert
            if users_json:
                try:
                    users_list = json.loads(users_json)
                    for u in users_list:
                        # 1. Upsert実行 (エラー回避のため .select() は外す)
                        supabase.table("users").upsert({
                            "username": u.get('username'),
                            "password": u.get('password'),
                            "role": u.get('role', 'user'),
                            "favorite_team": u.get('team'),
                            "balance": 0 
                        }, on_conflict="username").execute()
                        
                        # 2. IDを取得するために再Select (これが確実)
                        res = supabase.table("users").select("user_id").eq("username", u.get('username')).single().execute()
                        if res.data:
                            user_map[u.get('username')] = res.data['user_id']
                            
                    st.write(f"✅ Users: {len(user_map)}名を登録")
                except Exception as e:
                    st.error(f"Users JSON Error: {e}")
        else:
            st.error("Config sheet not found")

        # ---------------------------------------------------
        # 2. Matches
        # ---------------------------------------------------
        status.info("2/5: 試合データを結合・移行中...")
        ws_odds = find_sheet(sh, ["odds"])
        ws_res = find_sheet(sh, ["result"])
        
        if ws_odds:
            try:
                odds_data = ws_odds.get_all_records()
                
                # Oddsからベース作成
                for row in odds_data:
                    mid = safe_int(row.get('match_id') or row.get('fd_match_id'))
                    if not mid: continue
                    
                    gw_str = str(row.get('gw',''))
                    gw_num = safe_int(''.join(filter(str.isdigit, gw_str)))

                    matches_map[mid] = {
                        "match_id": mid,
                        "season": "2024",
                        "gameweek": gw_num,
                        "home_team": row.get('home\n') or row.get('home') or "Unknown",
                        "away_team": row.get('away') or "Unknown",
                        "odds_home": safe_float(row.get('home_win')),
                        "odds_draw": safe_float(row.get('draw')),
                        "odds_away": safe_float(row.get('away_win')),
                        "odds_locked": True if str(row.get('locked')).upper() == 'YES' else False,
                        "last_updated": clean_time(row.get('updated_at'))
                    }
                
                # Resultから詳細マージ
                if ws_res:
                    res_data = ws_res.get_all_records()
                    for row in res_data:
                        mid = safe_int(row.get('match_id'))
                        if mid and mid in matches_map:
                            matches_map[mid].update({
                                "status": row.get('status'),
                                "home_score": safe_int(row.get('home_score')),
                                "away_score": safe_int(row.get('away_score')),
                                "kickoff_time": clean_time(row.get('utc_kickoff')) # ★Fix: 空文字対策
                            })
                
                # 送信
                if matches_map:
                    match_list = list(matches_map.values())
                    chunk_size = 100
                    for i in range(0, len(match_list), chunk_size):
                        supabase.table("matches").upsert(match_list[i:i+chunk_size]).execute()
                    st.write(f"✅ Matches: {len(match_list)}試合")
                    
            except Exception as e:
                st.error(f"Matches Error: {e}")
        else:
            st.warning("Odds/Matches sheet not found")

        # ---------------------------------------------------
        # 3. Bets
        # ---------------------------------------------------
        status.info("3/5: ベット履歴を移行中...")
        ws_bets = find_sheet(sh, ["bets"])
        if ws_bets:
            try:
                bets_data = ws_bets.get_all_records()
                bets_payload = []
                
                for row in bets_data:
                    uname = row.get('user')
                    mid = safe_int(row.get('match_id'))
                    
                    if uname in user_map and mid in matches_map:
                        bets_payload.append({
                            "user_id": user_map[uname],
                            "match_id": mid,
                            "choice": row.get('pick'),
                            "stake": safe_int(row.get('stake')),
                            "odds_at_bet": safe_float(row.get('odds')),
                            "status": row.get('result') if row.get('result') in ['WON','LOST'] else 'PENDING',
                            "created_at": clean_time(row.get('placed_at')) # ★Fix
                        })
                
                if bets_payload:
                    for i in range(0, len(bets_payload), 100):
                        supabase.table("bets").insert(bets_payload[i:i+100]).execute()
                    st.write(f"✅ Bets: {len(bets_payload)}件")
            except Exception as e:
                st.error(f"Bets Error: {e}")

        # ---------------------------------------------------
        # 4. BM History
        # ---------------------------------------------------
        status.info("4/5: BM履歴を移行中...")
        ws_bm = find_sheet(sh, ["bm_log"])
        if ws_bm:
            try:
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
                            "created_at": clean_time(row.get('decided_at')) # ★Fix
                        })
                
                if bm_payload:
                    supabase.table("bm_history").insert(bm_payload).execute()
                    st.write(f"✅ BM Logs: {len(bm_payload)}件")
            except Exception as e:
                st.error(f"BM Log Error: {e}")

        status.success("🎉 全データの移行が完了しました！")
        st.balloons()
