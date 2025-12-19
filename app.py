import streamlit as st
import gspread
import pandas as pd

st.set_page_config(page_title="Column Inspector")
st.title("🔍 列名チェック")

# --- 接続 ---
try:
    if "gcp_service_account" in st.secrets:
        creds = st.secrets["gcp_service_account"]
        gc = gspread.service_account_from_dict(creds)
        sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
        st.success("✅ スプレッドシート接続OK")
    else:
        st.error("認証情報がありません")
        st.stop()
except Exception as e:
    st.error(f"接続エラー: {e}")
    st.stop()

# --- シート選択 ---
sheet_names = [ws.title for ws in sh.worksheets()]
target_sheet = st.selectbox("「試合日程」が入っているシートを選んでください", sheet_names)

if st.button("列名を表示"):
    ws = sh.worksheet(target_sheet)
    # 最初の1行目（ヘッダー）だけ取得
    headers = ws.row_values(1)
    st.write("▼ このシートの列名リスト（コピーして教えてください）")
    st.code(headers)
    
    # データのサンプルも少し表示
    st.write("▼ データの中身（最初の3行）")
    st.dataframe(ws.get_all_records()[:3])
