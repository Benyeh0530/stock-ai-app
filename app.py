import streamlit as st
# ⚠️ 致命關鍵：這行必須是全部程式碼的第一個 Streamlit 指令！
st.set_page_config(page_title="SOC 交易戰情室", layout="wide")

import requests
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime

# ==========================================
# 1. 核心設定 (請替換為您的 ngrok 網址)
# ==========================================
LOCAL_AGENT_WEBHOOK = "https://您的ngrok網址.ngrok-free.app/tv_webhook" 
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"

TG_BOT_TOKEN = "您的_Telegram_Bot_Token"
TG_CHAT_ID = "您的_Chat_ID"

TAIWAN_STOCKS = [
    "1717 東聯", "2330 台積電", "2317 鴻海", "2454 聯發科", 
    "2603 長榮", "2881 富邦金", "2882 國泰金", "3008 大立光",
    "0050 元大台灣50", "0056 元大高股息", "3037 欣興", "3017 奇鋐"
]

# ==========================================
# 2. 功能函式 (加入防呆與逾時保護)
# ==========================================
def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload, timeout=3) # 縮短 timeout 避免卡死
    except:
        pass

def send_order(action, ticker, price, qty):
    clean_ticker = str(ticker).split(' ')[0].replace(".TW", "").replace(".TWO", "")
    payload = {
        "secret": WEBHOOK_SECRET,
        "ticker": clean_ticker,
        "action": action,
        "price": price,
        "qty": qty
    }
    
    headers = {
        "ngrok-skip-browser-warning": "true",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(LOCAL_AGENT_WEBHOOK, json=payload, headers=headers, timeout=5)
        if response.status_code == 200:
            msg = f"✅ [指令已送出] {action.upper()} {clean_ticker} | 價格: {price} | 數量: {qty}"
            st.success(msg)
            send_telegram_msg(msg)
        else:
            st.error(f"❌ 本機 Agent 回應異常 (Code: {response.status_code})\n{response.text}")
    except Exception as e:
        st.error(f"❌ 無法連線至本機 Agent，請確認 ngrok 網址正確且程式執行中。\n{e}")

# ==========================================
# 3. UI 介面與狀態初始化
# ==========================================
if 'watch_list' not in st.session_state:
    st.session_state['watch_list'] = ["1717 東聯"]

# --- 側邊欄 ---
st.sidebar.title("⚙️ 戰情室控制台")
selected_stock = st.sidebar.selectbox("🔍 搜尋並新增股票", ["請選擇或輸入"] + TAIWAN_STOCKS)

if st.sidebar.button("➕ 加入監控"):
    if selected_stock != "請選擇或輸入" and selected_stock not in st.session_state['watch_list']:
        st.session_state['watch_list'].append(selected_stock)
        st.rerun()

if st.sidebar.button("🗑️ 清空清單"):
    st.session_state['watch_list'] = ["1717 東聯"]
    st.rerun()

# --- 主畫面 ---
st.title("📈 SOC 交易戰情室")

# 建立大盤區塊的佔位符 (防卡死設計)
st.subheader("🌐 即時走勢 (來源: Yahoo Finance)")
t1, t2 = st.columns(2)

with t1:
    try:
        d_tw = yf.download("^TWII", period="1d", interval="5m", progress=False)
        if not d_tw.empty:
            curr = d_tw['Close'].iloc[-1].item()
            diff = curr - d_tw['Open'].iloc[0].item()
            st.metric("加權指數 (上市)", f"{curr:.2f}", f"{diff:+.2f}")
    except:
        st.metric("加權指數 (上市)", "載入中或發生錯誤", "0.0")

with t2:
    try:
        d_otc = yf.download("^TWOII", period="1d", interval="5m", progress=False)
        if not d_otc.empty:
            curr = d_otc['Close'].iloc[-1].item()
            diff = curr - d_otc['Open'].iloc[0].item()
            st.metric("櫃買指數 (上櫃)", f"{curr:.2f}", f"{diff:+.2f}")
    except:
        st.metric("櫃買指數 (上櫃)", "載入中或發生錯誤", "0.0")

st.markdown("---")

# 動態產生監控區
for stock_item in st.session_state['watch_list']:
    ticker_id = stock_item.split(' ')[0]
    yf_ticker = f"{ticker_id}.TW"
    
    with st.expander(f"📊 監控中：{stock_item}", expanded=True):
        col_chart, col_trade = st.columns([2, 1])
        
        with col_chart:
            try:
                df = yf.download(yf_ticker, period="1mo", interval="1d", progress=False)
                if not df.empty:
                    fig = go.Figure(data=[go.Candlestick(
                        x=df.index, open=df['Open'].squeeze(), high=df['High'].squeeze(),
                        low=df['Low'].squeeze(), close=df['Close'].squeeze()
                    )])
                    fig.update_layout(height=350, margin=dict(l=0,r=0,t=0,b=0))
                    st.plotly_chart(fig, use_container_width=True)
                    last_p = float(df['Close'].iloc[-1].item())
                else:
                    st.warning(f"無法取得 {ticker_id} 的數據")
                    last_p = 0.0
            except Exception as e:
                st.error("圖表載入超時或失敗")
                last_p = 0.0

        with col_trade:
            st.write(f"### ⚡ 遠端指令")
            with st.form(f"form_{ticker_id}"):
                act = st.selectbox("買賣", ["buy", "sell"])
                price = st.number_input("委託價", value=float(last_p), step=0.05)
                qty = st.number_input("張數", value=1, min_value=1)
                if st.form_submit_button("🚀 發送委託"):
                    send_order(act, ticker_id, price, qty)
