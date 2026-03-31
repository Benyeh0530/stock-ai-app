import streamlit as st
import pyotp
import requests
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime

# ==========================================
# 1. 資安設定與全域變數
# ==========================================
# 您的 Google 2FA 密鑰 (請在真實環境使用環境變數 st.secrets 儲存)
MOCK_2FA_SECRET = "JBSWY3DPEHPK3PXP" 

# Telegram 機器人設定
TG_BOT_TOKEN = "您的_Telegram_Bot_Token"
TG_CHAT_ID = "您的_Chat_ID"

# 您的 Windows 本機 Webhook 網址 (可透過 ngrok 產生)
LOCAL_AGENT_WEBHOOK = "https://您的ngrok網址/tv_webhook"
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"

# ==========================================
# 2. 核心功能函式
# ==========================================
def send_telegram_msg(message):
    """發送 Telegram 推播"""
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        st.error(f"Telegram 推播失敗: {e}")

def send_order_to_local_agent(action, ticker, price, qty):
    """將下單指令發送給 Windows 本機的群益 API"""
    payload = {
        "secret": WEBHOOK_SECRET,
        "ticker": str(ticker),
        "action": action,
        "price": price,
        "qty": qty
    }
    try:
        response = requests.post(LOCAL_AGENT_WEBHOOK, json=payload, timeout=5)
        if response.status_code == 200:
            msg = f"✅ [指令成功發送] {action.upper()} {ticker} | 價格: {price} | 數量: {qty}"
            st.success(msg)
            send_telegram_msg(msg)
        else:
            st.error("❌ 本機 Agent 拒絕連線，請確認 Windows 端的程式是否啟動。")
    except Exception as e:
        st.error(f"❌ 無法連線至本機 Agent (請確認 ngrok 網址正確): {e}")

# ==========================================
# 3. UI 介面與 2FA 驗證
# ==========================================
st.set_page_config(page_title="雲端自動交易戰情室", layout="wide")

# 初始化登入狀態
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

# --- 登入畫面 ---
if not st.session_state['authenticated']:
    st.title("🔒 系統安全驗證")
    st.write("請輸入 Google Authenticator 上的 6 位數一次性密碼。")
    
    totp = pyotp.TOTP(MOCK_2FA_SECRET)
    user_code = st.text_input("2FA 驗證碼", type="password", max_chars=6)
    
    if st.button("驗證登入"):
        if totp.verify(user_code):
            st.session_state['authenticated'] = True
            send_telegram_msg(f"🔐 系統登入通知：使用者已於 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 成功登入雲端戰情室。")
            st.rerun()
        else:
            st.error("❌ 驗證碼錯誤或已過期，請重試。")

# --- 戰情室主畫面 ---
else:
    st.title("📈 雲端自動交易戰情室 (1717 東聯)")
    st.sidebar.button("登出系統", on_click=lambda: st.session_state.update(authenticated=False))

    col1, col2 = st.columns([2, 1])

    # 左側：使用 yfinance 繪製即時 K 線 (解決 Linux 無法跑群益 API 的問題)
    with col1:
        st.subheader("即時市場動態 (來源: Yahoo Finance)")
        try:
            # yfinance 台灣股票代號需加上 .TW
            ticker = "1717.TW"
            data = yf.download(ticker, period="1mo", interval="1d", progress=False)
            
            if not data.empty:
                fig = go.Figure(data=[go.Candlestick(x=data.index,
                                open=data['Open'],
                                high=data['High'],
                                low=data['Low'],
                                close=data['Close'])])
                fig.update_layout(height=450, margin=dict(l=0, r=0, t=30, b=0))
                st.plotly_chart(fig, use_container_width=True)
                
                # 取得最新一筆報價
                last_price = data['Close'].iloc[-1]
                st.metric(label="最新收盤價", value=f"{last_price:.2f}")
            else:
                st.warning("暫時無法取得報價資料。")
        except Exception as e:
            st.error(f"圖表載入失敗: {e}")

    # 右側：遠端下單控制台
    with col2:
        st.subheader("⚡ 遠端指令中樞")
        st.write("此面板將透過 Webhook 將指令安全穿透至您的 Windows 實體機執行群益 API 下單。")
        
        with st.form("order_form"):
            order_ticker = st.text_input("股票代號", value="1717")
            order_action = st.selectbox("買賣方向", ["buy", "sell"])
            order_price = st.number_input("委託價格", value=35.5, step=0.1)
            order_qty = st.number_input("委託張數", value=1, min_value=1)
            
            submitted = st.form_submit_button("🚀 確認發射委託單")
            
            if submitted:
                send_order_to_local_agent(order_action, order_ticker, order_price, order_qty)
