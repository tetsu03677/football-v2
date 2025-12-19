import streamlit as st
import gspread
import json
from supabase import create_client

st.set_page_config(page_title="Direct Clone Tool", layout="wide")
st.title("📦 Google Sheets → Supabase 直コピー (無加工)")

# --- 接続 ---
try:
    su_url = st.secrets["supabase"]["url"]
    su_key = st.secrets["supabase"]["key"]
    supabase = create_client(su_url, su_key)
    
    gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
except Exception as e:
    st.error(f"接続設定エラー: {e}")
    st.stop()

# --- コピー実行関数 ---
def copy_sheet_to_table(sheet_name, table_name, pk_col=None):
    try:
        st.write(f"🔄 `{sheet_name}` シートを `{table_name}` テーブルへコピー中...")
        ws = sh.worksheet(sheet_name)
        records = ws.get_all_records()
        
        if not records:
            st.warning(f"  - `{sheet_name}` は空でした。")
            return

        # 既存データ削除
        supabase.table(table_name).delete().neq(pk_col if pk_col else "gw", "dummy_val").execute()
        
        # 100件ずつインサート
        chunk_size = 100
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i+chunk_size]
            # 空文字を None に変換せず、そのまま文字列として入れるか、
            # 数値型カラムでエラーが出る場合は最低限のケアだけする
            cleaned_chunk = []
            for r in chunk:
                # キー名に改行コードなどが含まれる場合のケア (oddsシートの "home\n" など)
                clean_r = {}
                for k, v in r.items():
                    clean_k = k.strip()
                    # 数値フィールドの空文字ケア
                    if v == "":
                        clean_r[clean_k] = None 
                    else:
                        # "1,000" などのカンマ除去だけは必要（数値型に入らないため）
                        if isinstance(v, str) and v.replace(',','').replace('.','').isdigit():
                             # 数値っぽければカンマ取る
                             if ',' in v:
                                 try:
                                     clean_r[clean_k] = float(v.replace(',',''))
                                 except:
                                     clean_r[clean_k] = v
                             else:
                                 clean_r[clean_k] = v
                        else:
                            clean_r[clean_k] = v
                cleaned_chunk.append(clean_r)

            # Insert実行
            supabase.table(table_name).upsert(cleaned_chunk).execute()
            
        st.success(f"✅ `{table_name}`: {len(records)} 件 コピー完了")
        
    except Exception as e:
        st.error(f"❌ `{table_name}` のコピー失敗: {e}")

# --- ユーザーマスタ作成 (Configから) ---
def setup_users():
    st.write("🔄 ユーザー情報の抽出 (Config -> Users)...")
    try:
        # Configシートから users_json を探す
        res = supabase.table("config").select("value").eq("key", "users_json").execute()
        if res.data:
            json_str = res.data[0]['value']
            users_list = json.loads(json_str)
            
            for u in users_list:
                supabase.table("users").upsert({
                    "username": u.get("username"),
                    "password": u.get("password"),
                    "role": u.get("role"),
                    "team": u.get("team"),
                    "balance": 0 # 初期値
                }, on_conflict="username").execute()
            st.success(f"✅ ユーザーマスタ作成完了: {len(users_list)}名")
        else:
            st.warning("Configに users_json が見つかりません。")
    except Exception as e:
        st.error(f"ユーザー作成エラー: {e}")

# --- メイン処理 ---
if st.button("🚀 完全コピーを実行 (100% Mirror)", type="primary"):
    # 1. 各シートを対応するテーブルへコピー
    copy_sheet_to_table("config", "config", "key")
    copy_sheet_to_table("odds", "odds", "match_id")
    copy_sheet_to_table("bets", "bets", "key")
    copy_sheet_to_table("bm_log", "bm_log", "gw")
    copy_sheet_to_table("result", "result", "match_id")
    
    # 2. Usersテーブルの構築
    setup_users()
    
    st.balloons()
    st.success("🎉 スプレッドシートの内容をSupabaseに完全複製しました。")
    
    # 件数確認
    st.write("---")
    st.subheader("📊 データ件数確認")
    tables = ["bets", "odds", "result", "bm_log", "users"]
    for t in tables:
        try:
            cnt = len(supabase.table(t).select("*").execute().data)
            st.write(f"- **{t}**: {cnt} レコード")
        except:
            st.write(f"- {t}: 取得不可")
