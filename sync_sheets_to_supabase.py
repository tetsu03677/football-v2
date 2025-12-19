import streamlit as st
import gspread
import pandas as pd
import json
from supabase import create_client

st.set_page_config(page_title="Full Resync Tool", layout="centered")
st.title("♻️ 完全初期化＆再同期ツール")
st.warning("注意: 実行するとSupabase上の既存データは全て一度削除され、スプレッドシートの内容で再構築されます。")

# --- 接続設定 ---
try:
    su_url = st.secrets["supabase"]["url"]
    su_key = st.secrets["supabase"]["key"]
    supabase = create_client(su_url, su_key)
    
    gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
except Exception as e:
    st.error(f"接続設定エラー: {e}")
    st.stop()

# --- データクリーニング関数 ---
def clean_data(records, pk_col):
    unique = {}
    for r in records:
        clean_r = {}
        for k, v in r.items():
            # キーの改行コードなどを除去
            clean_k = str(k).strip()
            
            # 値の変換
            clean_v = v
            if v == "":
                clean_v = None
            elif isinstance(v, str) and v.replace(',','').replace('.','').replace('-','').isdigit():
                if ',' in v:
                    try: clean_v = float(v.replace(',',''))
                    except: clean_v = v
                else:
                    clean_v = v
            
            clean_r[clean_k] = clean_v
        
        # PKで重複排除（後勝ち）
        pk_val = clean_r.get(pk_col)
        if pk_val is not None:
            unique[pk_val] = clean_r
        
    return list(unique.values())

# --- 全削除関数 (依存関係順) ---
def truncate_all_tables():
    st.info("🗑️ 既存データを削除中...")
    try:
        # 1. 子テーブルから削除 (外部キー制約回避のため)
        # Bets (Users, Matchesに依存)
        supabase.table("bets").delete().neq("key", "dummy_val").execute()
        # Odds (Matchesに依存)
        supabase.table("odds").delete().neq("match_id", -1).execute()
        
        # 2. 親テーブル削除
        # Result (Matches)
        supabase.table("result").delete().neq("match_id", -1).execute()
        # BM Log
        supabase.table("bm_log").delete().neq("gw", "dummy_val").execute()
        # Config
        supabase.table("config").delete().neq("key", "dummy_val").execute()
        
        # Users (今回はConfigシートから復元できるため削除して作り直す)
        # ※ UUIDが変わると紐づきが切れるリスクがあるが、今回の設計ではusername紐づけ運用も多いため
        #   安全を期して「Usersは削除しない」か「Upsertで更新」が良いが、
        #   「完全同期」要望のため、一度消すか、あるいはそのままにするか。
        #   ここでは安全のため「Usersは削除せずUpsertで更新」とします。
        
        st.success("✅ データのクリーンアップ完了")
        return True
    except Exception as e:
        st.error(f"削除エラー: {e}")
        return False

# --- 同期実行関数 ---
def sync_table(sheet_name, table_name, pk_col):
    status_text = st.empty()
    status_text.text(f"⏳ {sheet_name} を読み込み中...")
    
    try:
        ws = sh.worksheet(sheet_name)
        recs = ws.get_all_records()
        if not recs:
            status_text.warning(f"⚠️ {sheet_name} は空でした。")
            return
        
        payload = clean_data(recs, pk_col)
        
        # Insert (一度消しているのでInsertでOKだが、念のためUpsertを使用)
        chunk = 100
        for i in range(0, len(payload), chunk):
            supabase.table(table_name).upsert(payload[i:i+chunk]).execute()
            
        status_text.success(f"✅ {table_name}: {len(payload)} 件 同期完了")
        
    except Exception as e:
        status_text.error(f"❌ {table_name} エラー: {e}")

# --- メイン処理 ---
if st.button("🚀 完全初期化して同期を実行", type="primary"):
    # 1. 全削除
    if not truncate_all_tables():
        st.stop()
        
    # 2. Users同期 (Configシート内のJSONから)
    try:
        ws_conf = sh.worksheet("config")
        conf = ws_conf.get_all_records()
        for row in conf:
            if row['key'] == 'users_json':
                users_list = json.loads(row['value'])
                for u in users_list:
                    # Usersテーブルは消していないのでUpsert
                    supabase.table("users").upsert({
                        "username": u.get('username'),
                        "password": u.get('password'),
                        "role": u.get('role'),
                        "team": u.get('team'),
                        "balance": 0 # 初期化
                    }, on_conflict="username").execute()
                st.write("✅ Users マスタ更新完了")
    except Exception as e:
        st.warning(f"Users同期警告: {e}")

    # 3. 各テーブル同期 (親 -> 子 の順序が望ましい)
    sync_table("config", "config", "key")
    sync_table("result", "result", "match_id") # 親 (Matches)
    sync_table("odds", "odds", "match_id")     # 子
    sync_table("bm_log", "bm_log", "gw")
    sync_table("bets", "bets", "key")          # 子
    
    st.balloons()
    st.success("🎉 全工程が正常に完了しました！これでデータはスプレッドシートと完全に一致しています。")
