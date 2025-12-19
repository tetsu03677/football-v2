import streamlit as st
import pandas as pd
import datetime
from datetime import timezone, timedelta
from supabase import create_client

# ==========================================
# 設定 & 接続
# ==========================================
st.set_page_config(page_title="Data Repair Tool", layout="centered")

@st.cache_resource
def get_db():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except:
        return None

supabase = get_db()

# ==========================================
# ロジック: P2P収支の完全再計算
# ==========================================
def recalculate_balances():
    logs = []
    try:
        # 1. データ全取得
        users = supabase.table("users").select("user_id, username").execute().data
        bets = supabase.table("bets").select("*, matches(gameweek)").execute().data
        bm_history = supabase.table("bm_history").select("*").execute().data
        
        if not users or not bets:
            return False, ["データが見つかりません。移行が正しく行われているか確認してください。"]

        # 2. 初期化 (全員0円スタート)
        # user_id -> balance
        balances = {u['user_id']: 0 for u in users}
        logs.append("・全員の収支を 0 にリセットしました。")

        # 3. BM特定用マップ作成: key=(season, gw) -> value=user_id
        # ※seasonが空の場合は'2024'など仮定
        bm_map = {}
        for h in bm_history:
            s = str(h.get('season') or '2024')
            g = int(h.get('gameweek') or 0)
            bm_map[(s, g)] = h['user_id']

        # 4. 履歴リプレイ (過去のベットをすべて再演)
        count = 0
        for b in bets:
            # 確定済みのみ対象
            if b['status'] not in ['WON', 'LOST']:
                continue
                
            player_id = b['user_id']
            match_data = b.get('matches')
            if not match_data: continue
            
            gw = match_data['gameweek']
            season = str(b.get('season') or '2024') # betsにseasonがない場合はmatchesからとるべきだが簡易化
            
            # --- プレイヤーの損益計算 ---
            stake = int(b['stake'])
            odds = float(b['odds_at_bet'] or 1.0)
            
            player_pnl = 0
            if b['status'] == 'WON':
                # 勝ち: (賭け金 * オッズ) - 賭け金 = 純利益
                player_pnl = int(stake * odds) - stake
            else:
                # 負け: 賭け金没収 = 損失
                player_pnl = -stake
            
            # プレイヤーの残高反映
            if player_id in balances:
                balances[player_id] += player_pnl
            
            # --- BMの損益計算 (ゼロサム) ---
            # そのGWのBMを探す
            bm_id = bm_map.get((season, gw))
            
            # もしBM履歴がない場合、スプレッドシートの bm_log が正しく移行されていない可能性あり
            # その場合は救済措置として、「自分以外の人」に割り振るなどのロジックがいるが、
            # ここでは「BMが見つかった場合のみ」計算する（見つからないと収支が合わない原因になる）
            if bm_id:
                # プレイヤー自身がBMであるケース(通常ありえない)を除外
                if bm_id != player_id and bm_id in balances:
                    # プレイヤーの利益 ＝ BMの損失
                    # プレイヤーの損失 ＝ BMの利益
                    # よって -1 を掛ける
                    balances[bm_id] -= player_pnl
            
            count += 1

        logs.append(f"・過去 {count} 件のベット履歴を処理しました。")

        # 5. DB保存
        for uid, val in balances.items():
            supabase.table("users").update({"balance": val}).eq("user_id", uid).execute()
            
        logs.append("・データベースの数値を更新しました。")
        return True, logs, balances

    except Exception as e:
        return False, [f"エラー発生: {str(e)}"], {}

# ==============================================================================
# ロジック: GW自動判定
# ==============================================================================
def detect_and_fix_gw():
    try:
        now_utc = datetime.datetime.now(timezone.utc)
        now_iso = now_utc.isoformat()
        
        # 未来の試合がある中で、最も日時が近い試合を探す
        res = supabase.table("matches").select("gameweek, kickoff_time")\
            .gt("kickoff_time", now_iso)\
            .order("kickoff_time")\
            .limit(1)\
            .execute()
            
        target_gw = 17 # デフォルト
        
        if res.data:
            # 未来の試合がある -> その試合のGWが現在
            target_gw = res.data[0]['gameweek']
            msg = f"未来の試合を検知: 次は GW{target_gw} です。"
        else:
            # 未来の試合がない -> 最後の試合のGW
            last = supabase.table("matches").select("gameweek").order("kickoff_time", desc=True).limit(1).execute()
            if last.data:
                target_gw = last.data[0]['gameweek']
                msg = f"全日程終了: 最新は GW{target_gw} です。"
            else:
                msg = "試合データがありません。GW17とします。"

        # Config更新 (文字列 "GW17" ではなく 数値 "17" で保存推奨だが、旧仕様に合わせるなら "GW17")
        # ここでは数値と文字列両方に対応できるよう、シンプルに数値文字列 "17" を保存します
        supabase.table("app_config").upsert({"key": "current_gw", "value": str(target_gw)}).execute()
        
        return True, msg, target_gw
    except Exception as e:
        return False, str(e), 0

# ==============================================================================
# UI
# ==============================================================================
st.title("🛠 データ整合性 修復ツール")
st.markdown("""
このツールは以下の処理を行い、アプリの状態を正常化します：
1. **収支の完全リプレイ**: 過去の全ベット履歴から、ゼロサムルールに基づいて3人の収支を再計算します。
2. **GW自動補正**: 日付情報に基づき、正しい Gameweek を設定します。
""")

if st.button("🚀 収支リプレイ計算 & GW修正を実行", type="primary"):
    if not supabase:
        st.error("DB接続エラー")
        st.stop()
        
    with st.status("修復処理を実行中...", expanded=True) as status:
        # 1. 収支計算
        st.write("🔄 ベット履歴を集計中...")
        ok_bal, logs_bal, final_balances = recalculate_balances()
        if ok_bal:
            for l in logs_bal: st.write(l)
        else:
            st.error(logs_bal[0])
            
        # 2. GW修正
        st.write("🔄 試合日程を確認中...")
        ok_gw, msg_gw, new_gw = detect_and_fix_gw()
        if ok_gw:
            st.write(f"・{msg_gw}")
        else:
            st.error(f"GW判定エラー: {msg_gw}")
            
        status.update(label="完了しました！", state="complete", expanded=True)

    # 結果確認テーブル
    st.divider()
    st.subheader("📊 修復後のステータス")
    
    # ユーザー名マッピングして表示
    if ok_bal:
        users = supabase.table("users").select("user_id, username").execute().data
        display_data = []
        total_checksum = 0
        
        for u in users:
            bal = final_balances.get(u['user_id'], 0)
            total_checksum += bal
            display_data.append({
                "User": u['username'],
                "Total P&L (収支)": f"¥{bal:,}"
            })
            
        df = pd.DataFrame(display_data)
        st.table(df)
        
        if total_checksum == 0:
            st.success(f"✅ ゼロサムチェック OK (合計: ¥{total_checksum})")
        else:
            st.warning(f"⚠️ ゼロサムチェック 警告 (合計: ¥{total_checksum}) - BM履歴の不足などが考えられます")

    st.success(f"現在の設定: **GW{new_gw}**")
    st.info("確認できたら、このコードを本来のアプリコード(app.py)に戻してください。")
