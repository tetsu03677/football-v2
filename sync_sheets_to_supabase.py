import streamlit as st
import gspread
import pandas as pd
from supabase import create_client

st.set_page_config(page_title="Shadow Sync Tool", layout="centered")
st.title("🔄 Shadow Sync (Sheets -> Supabase)")

# --- Init ---
try:
    su_url = st.secrets["supabase"]["url"]
    su_key = st.secrets["supabase"]["key"]
    supabase = create_client(su_url, su_key)
    
    gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
except Exception as e:
    st.error(f"Setup Error: {e}")
    st.stop()

def clean_data(records, pk_col):
    """データクリーニングと重複排除"""
    unique = {}
    for r in records:
        clean_r = {}
        for k, v in r.items():
            if v == "":
                clean_r[k] = None
            elif isinstance(v, str) and v.replace(',','').replace('.','').replace('-','').isdigit():
                if ',' in v:
                    try: clean_r[k] = float(v.replace(',',''))
                    except: clean_r[k] = v
                else:
                    clean_r[k] = v
            else:
                clean_r[k] = v
        
        # PKがあれば辞書で上書き（重複排除）
        pk_val = clean_r.get(pk_col)
        if pk_val: unique[pk_val] = clean_r
        
    return list(unique.values())

def sync_table(sheet_name, table_name, pk_col):
    st.write(f"Processing {sheet_name}...")
    try:
        ws = sh.worksheet(sheet_name)
        recs = ws.get_all_records()
        if not recs: return
        
        payload = clean_data(recs, pk_col)
        
        # Upsert
        chunk = 100
        for i in range(0, len(payload), chunk):
            supabase.table(table_name).upsert(payload[i:i+chunk]).execute()
            
        st.success(f"✅ {table_name}: {len(payload)} rows synced.")
    except Exception as e:
        st.error(f"Error {table_name}: {e}")

if st.button("🚀 Run Sync From Production Sheets", type="primary"):
    with st.spinner("Syncing..."):
        # UsersはConfigから
        try:
            import json
            ws_conf = sh.worksheet("config")
            conf = ws_conf.get_all_records()
            for row in conf:
                if row['key'] == 'users_json':
                    users = json.loads(row['value'])
                    for u in users:
                        supabase.table("users").upsert({
                            "username": u['username'], "password": u['password'],
                            "role": u['role'], "team": u['team'], "balance": 0
                        }, on_conflict="username").execute()
                    st.success("✅ Users synced.")
        except Exception as e: st.warning(f"User sync warning: {e}")

        # 各テーブル同期
        sync_table("config", "config", "key")
        sync_table("odds", "odds", "match_id")
        sync_table("bets", "bets", "key")
        sync_table("bm_log", "bm_log", "gw")
        sync_table("result", "result", "match_id")
        
        st.balloons()
