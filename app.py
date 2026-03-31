import streamlit as st
import pyotp
import requests
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime

# ==========================================
# 1. 資安設定與全域變數
# ==========================================
# 您的 Google 2FA 密鑰 (強烈建議未來移至 st.secrets)
MOCK_2FA_SECRET = "JBSWY3DPEHPK3PXP" 

# Telegram 機器人設定
TG_BOT_TOKEN = "您的_Telegram_Bot_Token"
TG_CHAT_ID = "您的_Chat_ID"

# 您的 Windows 本機 Webhook 網址
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
        st.sidebar.error(f"Telegram 推播失敗: {e}")

def send_order_to_local_agent(action, ticker, price, qty):
    """將下單指令發送給 Windows 本機的群益 API"""
    # 移除 .TW 以符合群益 API 格式 (例如 1717.TW -> 1717)
    clean_ticker = str(ticker).replace(".TW", "").replace(".TWO", "")
    
    payload = {
        "secret": WEBHOOK_SECRET,
        "ticker": clean_ticker,
        "action": action,
        "price": price,
        "qty": qty
    }
    try:
        response = requests.post(LOCAL_AGENT_WEBHOOK, json=payload, timeout=5)
        if response.status_code == 200:
            msg = f"✅ [指令成功發送] {action.upper()} {clean_ticker} | 價格: {price} | 數量: {qty}"
            st.success(msg)
            send_telegram_msg(msg)
        else:
            st.error("❌ 本機 Agent 拒絕連線，請確認 Windows 端的程式是否啟動。")
    except Exception as e:
        st.error(f"❌ 無法連線至本機 Agent (請確認 ngrok 網址正確): {e}")

def plot_mini_chart(ticker_symbol, title):
    """繪製大盤或個股的微型走勢圖"""
    try:
        data = yf.download(ticker_symbol, period="1d", interval="5m", progress=False)
        if not data.empty:
            # 計算漲跌幅
            open_price = data['Open'].iloc[0].item() if not data['Open'].empty else 0
            current_price = data['Close'].iloc[-1].item() if not data['Close'].empty else 0
            change = current_price - open_price
            pct_change = (change / open_price) * 100 if open_price != 0 else 0
            
            color = "red" if change >= 0 else "green" # 台股紅漲綠跌
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=data.index, y=data['Close'].squeeze(), mode='lines', line=dict(color=color, width=2)))
            fig.update_layout(
                title=f"{title} | {current_price:.2f} ({pct_change:+.2f}%)",
                height=200, margin=dict(l=10, r=10, t=40, b=10),
                xaxis=dict(visible=False), yaxis=dict(visible=False),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning(f"無 {title} 資料")
    except Exception as e:
        st.warning(f"載入 {title} 失敗")

# ==========================================
# 3. UI 介面與狀態初始化
# ==========================================
st.set_page_config(page_title="雲端自動交易戰情室", layout="wide")

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

# 初始化監控清單 (預設帶入您的標的)
if 'watch_list' not in st.session_state:
    st.session_state['watch_list'] = ["1717.TW"]

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
    # 側邊欄：新增監控股
    st.sidebar.title("⚙️ 戰情室設定")
    st.sidebar.button("登出系統", on_click=lambda: st.session_state.update(authenticated=False))
    st.sidebar.markdown("---")
    
    st.sidebar.subheader("➕ 新增監控股")
    new_stock = st.sidebar.text_input("輸入股票代號 (例: 2330.TW)")
    if st.sidebar.button("加入監控清單"):
        if new_stock and new_stock not in st.session_state['watch_list']:
            st.session_state['watch_list'].append(new_stock.upper())
            st.rerun()

    # 主畫面：頂部大盤走勢
    st.title("📈 雲端自動交易戰情室")
    
    st.subheader("🌐 上市/上櫃即時走勢")
    col_twse, col_otc = st.columns(2)
    with col_twse:
        plot_mini_chart("^TWII", "台灣加權指數 (上市)")
    with col_otc:
        # TWO.TW 或 ^TWOII 為櫃買指數，若 yfinance 抓不到可替換為 0050.TW 觀察大盤
        plot_mini_chart("TWO.TW", "櫃買指數 (上櫃)")

    st.markdown("---")
    
    # 主畫面：動態監控清單與下單區
    st.subheader("🎯 監控清單與遠端指令")
    
    # 動態產生每一檔股票的監控卡片
    for ticker in st.session_state['watch_list']:
        with st.container():
            col_chart, col_trade = st.columns([2, 1])
            
            with col_chart:
                # 繪製個股 K 線
                try:
                    data = yf.download(ticker, period="1mo", interval="1d", progress=False)
                    if not data.empty:
                        fig = go.Figure(data=[go.Candlestick(x=data.index,
                                        open=data['Open'].squeeze(),
                                        high=data['High'].squeeze(),
                                        low=data['Low'].squeeze(),
                                        close=data['Close'].squeeze())])
                        fig.update_layout(title=f"{ticker} 近一月 K 線", height=300, margin=dict(l=0, r=0, t=30, b=0))
                        st.plotly_chart(fig, use_container_width=True)
                        last_price = data['Close'].iloc[-1].item()
                    else:
                        st.warning(f"暫無 {ticker} 資料")
                        last_price = 0.0
                except Exception as e:
                    st.error(f"圖表載入失敗: {e}")
                    last_price = 0.0

            with col_trade:
                st.markdown(f"#### ⚡ 遠端下單 ({ticker.replace('.TW', '')})")
                st.write("指令將透過 Webhook 穿透至本機執行實體委託。")
                
                # 使用 form 包裝，避免點擊加減號時一直重新整理
                with st.form(f"form_{ticker}"):
                    order_action = st.selectbox("買賣方向", ["buy", "sell"], key=f"act_{ticker}")
                    order_price = st.number_input("委託價格", value=float(last_price), step=0.1, key=f"prc_{ticker}")
                    order_qty = st.number_input("委託張數", value=1, min_value=1, key=f"qty_{ticker}")
                    
                    submitted = st.form_submit_button("🚀 發射委託單")
                    
                    if submitted:
                        send_order_to_local_agent(order_action, ticker, order_price, order_qty)
                        
            st.markdown("---")
