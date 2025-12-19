import streamlit as st
import pandas as pd
import gspread
from supabase import create_client

st.set_page_config(page_title="Data Audit", layout="wide")
st.title("🕵️ データ移行検証（監査）ツール")

# --- 接続設定 ---
def init_connections():
    try:
        # Supabase接続
        su_url = st.secrets["supabase"]["url"]
        su_key = st.secrets["supabase"]["key"]
        supabase = create_client(su_url, su_key)
        
        # Google Sheets接続
        creds = st.secrets["gcp_service_account"]
        gc = gspread.service_account_from_dict(creds)
        ssid = st.secrets["sheets"]["sheet_id"]
        sh = gc.open_by_key(ssid)
        
        return supabase, sh
    except Exception as e:
        st.error(f"接続エラー: {e}")
        return None, None

supabase, sh = init_connections()

if st.button("🔍 データの整合性をチェックする"):
    if not supabase or not sh: st.stop()
    
    with st.spinner("スプレッドシートとSupabaseを比較中..."):
        # -----------------------------------------------
        # 1. ユーザーマスタの照合
        # -----------------------------------------------
        st.subheader("1. ユーザーマスタ (Users)")
        
        # Sheet (config -> json) はパースが面倒なので、betsシートのユニークユーザー数と比較
        ws_bets = sh.worksheet("bets")
        sheet_bets = ws_bets.get_all_records()
        sheet_users = set([r['user'] for r in sheet_bets if r['user']])
        
        # DB
        db_users = supabase.table("users").select("username, balance").execute().data
        db_user_names = set([u['username'] for u in db_users])
        
        c1, c2 = st.columns(2)
        c1.write(f"Google Sheets (Bets登場): {len(sheet_users)} 名 {list(sheet_users)}")
        c2.write(f"Supabase DB: {len(db_user_names)} 名 {list(db_user_names)}")
        
        if sheet_users == db_user_names:
            st.success("✅ ユーザー名は一致しています")
        else:
            st.error(f"⚠️ ユーザー不一致: {sheet_users ^ db_user_names}")

        # -----------------------------------------------
        # 2. ベットデータの照合 (Bets)
        # -----------------------------------------------
        st.subheader("2. ベットデータ (Bets)")
        
        # Sheet集計
        sheet_total_stake = 0
        sheet_count = 0
        sheet_won_count = 0
        
        for r in sheet_bets:
            try:
                s = int(str(r['stake']).replace(',', ''))
                sheet_total_stake += s
                sheet_count += 1
                if str(r['result']).upper() == 'WON':
                    sheet_won_count += 1
            except: pass
            
        # DB集計
        db_bets = supabase.table("bets").select("*").execute().data
        db_total_stake = sum([b['stake'] for b in db_bets])
        db_count = len(db_bets)
        db_won_count = len([b for b in db_bets if b['status'] == 'WON'])
        
        # 比較表
        audit_df = pd.DataFrame({
            "項目": ["総ベット件数", "勝利数(WON)", "総ベット金額(Stake合計)"],
            "Google Sheets (正)": [sheet_count, sheet_won_count, f"¥{sheet_total_stake:,}"],
            "Supabase DB (現状)": [db_count, db_won_count, f"¥{db_total_stake:,}"],
            "差分": [sheet_count - db_count, sheet_won_count - db_won_count, sheet_total_stake - db_total_stake]
        })
        st.table(audit_df)
        
        if sheet_count != db_count:
            st.error(f"❌ ベット件数が {sheet_count - db_count} 件 足りていません！コピー失敗しています。")
        else:
            st.success("✅ ベット件数は一致しています。")

        # -----------------------------------------------
        # 3. 試合データの照合 (Matches)
        # -----------------------------------------------
        st.subheader("3. 試合データ (Matches)")
        ws_odds = sh.worksheet("odds")
        sheet_odds = ws_odds.get_all_records()
        sheet_match_ids = set([str(r['match_id'] or r['fd_match_id']) for r in sheet_odds if r.get('match_id') or r.get('fd_match_id')])
        
        db_matches = supabase.table("matches").select("match_id, gameweek").execute().data
        db_match_ids = set([str(m['match_id']) for m in db_matches])
        
        st.write(f"Sheets試合数: {len(sheet_match_ids)} vs DB試合数: {len(db_match_ids)}")
        
        missing_in_db = sheet_match_ids - db_match_ids
        if missing_in_db:
            st.error(f"⚠️ DBに未登録の試合ID (SheetsにあるのにDBにない): {list(missing_in_db)[:10]} ...")
        else:
            st.success("✅ 試合データIDは全て移行されています。")

        # -----------------------------------------------
        # 4. GW判定のテスト
        # -----------------------------------------------
        st.subheader("4. 現在のGW判定ロジック テスト")
        import datetime
        from datetime import timezone, timedelta
        
        now_utc = datetime.datetime.now(timezone.utc)
        st.write(f"現在時刻 (UTC): {now_utc}")
        
        # ロジック検証
        future_matches = [m for m in db_matches if m.get('kickoff_time') and pd.to_datetime(m['kickoff_time']) > (now_utc - timedelta(hours=4))]
        # DBからkickoff_timeをとるために再クエリが必要ですが、ここでは簡易チェック
        res = supabase.table("matches").select("gameweek, kickoff_time").gt("kickoff_time", (now_utc - timedelta(hours=4)).isoformat()).order("kickoff_time").limit(1).execute()
        
        detected = "不明"
        if res.data:
            detected = res.data[0]['gameweek']
            kickoff = res.data[0]['kickoff_time']
            st.info(f"💡 判定ロジック: 直近の試合は {kickoff} (GW{detected}) です。よって現在は GW{detected} です。")
        else:
            st.warning("未来の試合が見つかりません。")
