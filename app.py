import streamlit as st
import pandas as pd
import gspread
import datetime
from supabase import create_client

# ==========================================
# 設定
# ==========================================
st.set_page_config(page_title="Data Migration Tool (Fix)", layout="wide")
st.title("📦 Google Sheets -> Supabase 完全移行ツール (Fix版)")

# 接続
try:
    su_url = st.secrets["supabase"]["url"]
    su_key = st.secrets["supabase"]["key"]
    supabase = create_client(su_url, su_key)
    
    gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
except Exception as e:
    st.error(f"接続設定エラー: {e}")
    st.stop()

# ==========================================
# ユーティリティ
# ==========================================
def clean_int(val):
    try:
        s = str(val).replace(',', '').strip()
        return int(float(s))
    except:
        return None

def clean_float(val):
    try:
        s = str(val).replace(',', '').strip()
        return float(s)
    except:
        return None

def clean_gw(val):
    s = str(val).upper()
    nums = "".join([c for c in s if c.isdigit()])
    return int(nums) if nums else None

# ==========================================
# メイン処理
# ==========================================
def run_migration():
    logs = []
    error_logs = []
    
    try:
        st.info("既存データをクリア中...")
        # 外部キー制約を考慮して順番に削除（または全削除）
        # ※エラーが出ても続行する
        try: supabase.table("bm_history").delete().neq("season", "dummy").execute()
        except: pass
        try: supabase.table("bets").delete().neq("choice", "dummy").execute()
        except: pass
        # matchesとusersは依存関係があるため残すが、upsertで上書きされる

        # ------------------------------------------------
        # 1. Users
        # ------------------------------------------------
        st.write("1️⃣ ユーザーデータの移行...")
        ws_bets = sh.worksheet("bets")
        bets_data = ws_bets.get_all_records()
        
        user_names = set()
        for r in bets_data:
            if r.get('user'): user_names.add(str(r.get('user')).strip())
            
        u_map = {} # username -> user_id
        
        for name in user_names:
            # 1. Upsert (select()をチェーンしない)
            supabase.table("users").upsert({
                "username": name,
                "password": "password", 
                "role": "user",
                "balance": 0
            }, on_conflict="username").execute()
            
            # 2. IDを取得するために再クエリ (これが一番確実)
            res = supabase.table("users").select("user_id").eq("username", name).single().execute()
            if res.data:
                u_map[name] = res.data['user_id']
        
        logs.append(f"✅ ユーザー登録完了: {len(u_map)}名")

        # ------------------------------------------------
        # 2. Matches
        # ------------------------------------------------
        st.write("2️⃣ 試合データの移行...")
        ws_odds = sh.worksheet("odds")
        odds_data = ws_odds.get_all_records()
        
        matches_payload = []
        seen_match_ids = set()
        
        for r in odds_data:
            mid = clean_int(r.get('match_id') or r.get('fd_match_id'))
            if not mid: continue
            if mid in seen_match_ids: continue
            seen_match_ids.add(mid)
            
            matches_payload.append({
                "match_id": mid,
                "season": "2024",
                "gameweek": clean_gw(r.get('gw')),
                "home_team": r.get('home\n') or r.get('home') or "Unknown",
                "away_team": r.get('away') or "Unknown",
                "odds_home": clean_float(r.get('home_win')),
                "odds_draw": clean_float(r.get('draw')),
                "odds_away": clean_float(r.get('away_win')),
                "odds_locked": True if str(r.get('locked')).upper() == 'YES' else False,
                # 日時は後でAPI補完。今はダミー
                "kickoff_time": datetime.datetime.now().isoformat() 
            })
            
        # 分割Insert
        for i in range(0, len(matches_payload), 100):
            try:
                # Upsertのみ実行
                supabase.table("matches").upsert(matches_payload[i:i+100]).execute()
            except Exception as e:
                error_logs.append(f"Matches Insert Error: {e}")
                
        logs.append(f"✅ 試合データ移行: {len(matches_payload)} 件")

        # ------------------------------------------------
        # 3. Bets
        # ------------------------------------------------
        st.write("3️⃣ ベット履歴の移行...")
        bets_payload = []
        
        for r in bets_data:
            uname = str(r.get('user')).strip()
            if uname not in u_map: continue
            
            mid = clean_int(r.get('match_id') or r.get('fd_match_id'))
            if not mid: continue
            
            # Match補完 (外部キーエラー回避)
            if mid not in seen_match_ids:
                try:
                    supabase.table("matches").upsert({
                        "match_id": mid,
                        "season": "2024",
                        "gameweek": 1,
                        "home_team": "Unknown Match",
                        "away_team": "Unknown Match"
                    }).execute()
                    seen_match_ids.add(mid)
                except: continue

            # ステータス正規化
            raw_res = str(r.get('result', '')).upper()
            status = 'PENDING'
            if 'WIN' in raw_res: status = 'WON'
            elif 'LOSE' in raw_res: status = 'LOST'
            
            bets_payload.append({
                "user_id": u_map[uname],
                "match_id": mid,
                "choice": r.get('pick'),
                "stake": clean_int(r.get('stake')),
                "odds_at_bet": clean_float(r.get('odds')),
                "status": status,
                "created_at": r.get('placed_at') or datetime.datetime.now().isoformat()
            })

        # 分割Insert
        for i in range(0, len(bets_payload), 100):
            try:
                supabase.table("bets").insert(bets_payload[i:i+100]).execute()
            except Exception as e:
                error_logs.append(f"Bets Insert Error (Chunk {i}): {e}")
                
        logs.append(f"✅ ベット履歴移行: 対象 {len(bets_payload)} 件")

        # ------------------------------------------------
        # 4. BM履歴
        # ------------------------------------------------
        st.write("4️⃣ BM履歴の移行...")
        ws_bm = sh.worksheet("bm_log")
        bm_data = ws_bm.get_all_records()
        bm_payload = []
        
        for r in bm_data:
            uname = str(r.get('bookmaker')).strip()
            if uname in u_map:
                bm_payload.append({
                    "season": "2024",
                    "gameweek": clean_gw(r.get('gw')),
                    "user_id": u_map[uname],
                    "created_at": r.get('decided_at')
                })
        
        if bm_payload:
            supabase.table("bm_history").insert(bm_payload).execute()
        
        logs.append(f"✅ BM履歴移行: {len(bm_payload)} 件")

        # 完了報告
        st.success("🎉 データコピー処理が完了しました")
        for l in logs: st.write(l)
        if error_logs:
            st.error("エラーログ:")
            for e in error_logs: st.write(e)
            
        # 件数確認
        st.divider()
        st.subheader("📊 移行結果")
        try:
            cnt_users = len(supabase.table("users").select("user_id").execute().data)
            cnt_matches = len(supabase.table("matches").select("match_id").execute().data)
            cnt_bets = len(supabase.table("bets").select("bet_id").execute().data)
            
            st.write(f"- ユーザー数: {cnt_users}")
            st.write(f"- 試合数: {cnt_matches}")
            st.write(f"- ベット数: {cnt_bets}")
        except:
            st.write("件数取得失敗（データは入っている可能性があります）")

    except Exception as e:
        st.error(f"致命的なエラー: {e}")

if st.button("🚀 データ移行を実行", type="primary"):
    run_migration()
