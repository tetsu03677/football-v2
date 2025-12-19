import streamlit as st
import gspread
import pandas as pd
import json
from supabase import create_client

st.set_page_config(page_title="Config Migration", layout="wide")
st.title("⚙️ システム設定 & ユーザー権限 移行ツール")

# --- 接続確立 ---
try:
    if "supabase" in st.secrets:
        supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
        st.success("✅ Supabase 接続成功")
    else:
        st.error("Supabase secrets missing")
        st.stop()
        
    if "gcp_service_account" in st.secrets:
        gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
        st.success("✅ Google Sheets 接続成功")
    else:
        st.error("Google Sheets secrets missing")
        st.stop()
except Exception as e:
    st.error(f"接続エラー: {e}")
    st.stop()

# --- シート検索 ---
def find_config_sheet(sh):
    for ws in sh.worksheets():
        if "config" in ws.title.lower():
            return ws
    return None

# --- メイン処理 ---
if st.button("⚙️ Config & ユーザー完全移行を実行"):
    status = st.empty()
    
    # 1. Configシート読み込み
    ws_config = find_config_sheet(sh)
    if not ws_config:
        st.error("❌ 'config' シートが見つかりません")
        st.stop()
        
    config_data = ws_config.get_all_records()
    # config_data は [{'key': 'API_TOKEN', 'value': 'xxx'}, ...] の形式を想定
    
    # 2. app_config テーブルへ保存
    config_payload = []
    users_json_str = None
    
    for row in config_data:
        k = str(row.get('key', '')).strip()
        v = str(row.get('value', '')).strip()
        if not k: continue
        
        # users_json は後で個別に処理するため確保
        if k == 'users_json':
            users_json_str = v
        
        config_payload.append({"key": k, "value": v})
        
    if config_payload:
        try:
            supabase.table("app_config").upsert(config_payload).execute()
            st.success(f"✅ 設定値 {len(config_payload)} 件をデータベースに保存しました。")
        except Exception as e:
            st.error(f"Config保存エラー: {e}")
            
    # 3. ユーザー情報の詳細移行 (users_json の解析)
    if users_json_str:
        try:
            # JSONパース (CSV内のJSON文字列)
            users_list = json.loads(users_json_str)
            st.write("▼ 検出されたユーザー設定:", users_list)
            
            update_count = 0
            for u_conf in users_list:
                username = u_conf.get('username')
                password = u_conf.get('password')
                role = u_conf.get('role', 'user')
                team = u_conf.get('team', '')
                
                # Supabaseの既存ユーザーを更新 (usernameをキーに)
                # ※ユーザーが存在しない場合は作成(insert)
                supabase.table("users").upsert({
                    "username": username,
                    "password": password,     # 平文保存（元の仕様準拠）
                    "role": role,
                    "favorite_team": team,
                    # balanceは既存維持、新規ならデフォルトが入る
                }, on_conflict="username").execute()
                update_count += 1
                
            st.success(f"✅ ユーザー詳細情報（パスワード/権限）を {update_count} 名分更新しました。")
            
        except json.JSONDecodeError:
            st.error("❌ users_json のパースに失敗しました。書式を確認してください。")
        except Exception as e:
            st.error(f"ユーザー更新エラー: {e}")
    else:
        st.warning("⚠️ users_json が config シート内に見つかりませんでした。")

    st.info("移行完了後、本番アプリは `app_config` テーブルからAPIトークンや設定を読み込みます。")
