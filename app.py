import streamlit as st
import gspread
import json
from supabase import create_client

st.set_page_config(page_title="Direct Clone Tool (Fixed)", layout="wide")
st.title("📦 Google Sheets → Supabase 直コピー (Fix版)")

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
def copy_sheet_to_table(sheet_name, table_name, pk_col):
    try:
        st.write(f"🔄 `{sheet_name}` シートを `{table_name}` テーブルへコピー中...")
        ws = sh.worksheet(sheet_name)
        records = ws.get_all_records()
        
        if not records:
            st.warning(f"  - `{sheet_name}` は空でした。")
            return

        # 1. 既存データ削除 (型に合わせてダミー値を変える)
        try:
            if pk_col == "match_id":
                # 数値型PKの場合
                supabase.table(table_name).delete().neq(pk_col, -1).execute()
            else:
                # 文字列型PKの場合
                supabase.table(table_name).delete().neq(pk_col, "dummy_delete_val").execute()
        except Exception as e:
            st.warning(f"  - テーブルクリア時に警告 (初回なら無視可): {e}")

        # 2. データ整形と重複排除
        # リスト内でPKが重複しているとSQLエラーになるため、Python側でユニークにする
        unique_records = {}
        for r in records:
            # データのクリーニング
            clean_r = {}
            for k, v in r.items():
                clean_k = k.strip()
                if v == "":
                    clean_r[clean_k] = None
                else:
                    # カンマ入り数値のケア ("1,000" -> 1000)
                    if isinstance(v, str) and v.replace(',','').replace('.','').replace('-','').isdigit():
                        if ',' in v:
                            try:
                                clean_r[clean_k] = float(v.replace(',',''))
                            except:
                                clean_r[clean_k] = v
                        else:
                            clean_r[clean_k] = v
                    else:
                        clean_r[clean_k] = v
            
            # PKをキーにして辞書に保存（後勝ちで上書き＝重複排除）
            pk_val = clean_r.get(pk_col)
            if pk_val is not None:
                unique_records[pk_val] = clean_r

        # 辞書からリストに戻す
        final_list = list(unique_records.values())

        # 3. 分割インサート
        chunk_size = 100
        for i in range(0, len(final_list), chunk_size):
            chunk = final_list[i:i+chunk_size]
            supabase.table(table_name).upsert(chunk).execute()
            
        st.success(f"✅ `{table_name}`: {len(final_list)} 件 コピー完了 (元データ: {len(records)}件)")
        
    except Exception as e:
        st.error(f"❌ `{table_name}` のコピー失敗: {e}")

# --- ユーザーマスタ作成 ---
def setup_users():
    st.write("🔄 ユーザー情報の抽出 (Config -> Users)...")
    try:
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
                    "balance": 0 
                }, on_conflict="username").execute()
            st.success(f"✅ ユーザーマスタ作成完了: {len(users_list)}名")
        else:
            st.warning("Configに users_json が見つかりません。")
    except Exception as e:
        st.error(f"ユーザー作成エラー: {e}")

# --- メイン処理 ---
if st.button("🚀 完全コピーを実行 (重複排除・Fix版)", type="primary"):
    # 1. 各シートを対応するテーブルへコピー
    copy_sheet_to_table("config", "config", "key")
    copy_sheet_to_table("odds", "odds", "match_id")
    copy_sheet_to_table("bets", "bets", "key")
    copy_sheet_to_table("bm_log", "bm_log", "gw")
    copy_sheet_to_table("result", "result", "match_id")
    
    # 2. Usersテーブルの構築
    setup_users()
    
    st.balloons()
    st.success("🎉 スプレッドシートの内容をSupabaseに複製しました。")
    
    # 件数確認
    st.write("---")
    st.subheader("📊 データ件数確認")
    tables = ["bets", "odds", "result", "bm_log", "users"]
    for t in tables:
        try:
            res = supabase.table(t).select("*", count="exact").head(True).execute() # countのみ取得
            st.write(f"- **{t}**: {res.count} レコード")
        except:
            st.write(f"- {t}: 取得不可 (データが入っていない可能性があります)")
