import streamlit as st
import gspread
from supabase import create_client
import pandas as pd

st.set_page_config(page_title="診断モード", layout="wide")
st.title("🔍 スプレッドシート診断ツール")

# --- 接続 ---
try:
    if "gcp_service_account" in st.secrets:
        creds = st.secrets["gcp_service_account"]
        gc = gspread.service_account_from_dict(creds)
        sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
        st.success(f"✅ スプレッドシート接続成功: {sh.title}")
    else:
        st.error("Google認証情報がありません")
        st.stop()
except Exception as e:
    st.error(f"接続エラー: {e}")
    st.stop()

# --- 診断実行 ---
st.subheader("1. シート一覧")
worksheet_list = sh.worksheets()
sheet_names = [ws.title for ws in worksheet_list]
st.write(sheet_names)

st.subheader("2. シートごとのデータ確認")

# シートを選択して中身をチラ見する
selected_sheet = st.selectbox("中身を確認したいシートを選んでください", sheet_names)

if st.button("このシートのデータを表示"):
    ws = sh.worksheet(selected_sheet)
    # 最初の5行だけ取得
    data = ws.get_all_records()[:5] 
    
    if data:
        st.write(f"データサンプル ({len(data)}件表示):")
        st.dataframe(data)
        
        # カラム名の確認
        st.write("カラム名一覧:", list(data[0].keys()))
        
        # もし 'user' っぽいカラムがあれば、ユニークなユーザー名を表示
        for col in data[0].keys():
            if "user" in col.lower() or "name" in col.lower():
                st.info(f"カラム '{col}' に含まれるユーザー名:")
                # 全データからユニーク値を取得
                all_data = ws.get_all_records()
                unique_users = set(row[col] for row in all_data)
                st.write(unique_users)
    else:
        st.warning("データが空、または読み込めませんでした")
