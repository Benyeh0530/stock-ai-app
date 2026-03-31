import streamlit as st
# 鐵則 1 & 2：保留功能，更名為 AI 穩贏自動化戰情牆
st.set_page_config(page_title="AI 穩贏自動化戰情牆", layout="wide")

import requests
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime

# ==========================================
# 1. 核心設定 (保留群益整合 Webhook)
# ==========================================
LOCAL_AGENT_WEBHOOK = "https://hitless-axel-misapply.ngrok-free.dev/tv_webhook" 
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"
TG_BOT_TOKEN = "您的_Telegram_Bot_Token"
TG_CHAT_ID = "您的_Chat_ID"

# 鐵則 3：模糊搜尋字典 (可持續擴充)
STOCKS_DICT = {
    "1717": "東聯", "2330": "台積電", "2317": "鴻海", "2454": "聯發科",
    "2603": "長榮", "3037": "欣興", "3017": "奇鋐", "2303": "聯電",
    "2609": "陽明", "2615": "萬海", "2881": "富邦金", "2882": "國泰金",
    "3231": "緯創", "2382": "廣達", "1513": "中興電", "1519": "華城",
    "6770": "力積電", "3008": "大立光", "0050": "元大台灣50", "0056": "元大高股息"
}

# ==========================================
# 2. 功能函式 (鐵則 5：群益整合)
# ==========================================
def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": message}
    try: requests.post(url, json=payload, timeout=3)
    except: pass

def send_order(action, ticker, price, qty):
    clean_ticker = str(ticker).split('.')[0]
    payload = {
        "secret": WEBHOOK_SECRET, "ticker": clean_ticker,
        "action": action, "price": price, "qty": qty
    }
    headers = {"ngrok-skip-browser-warning": "true", "Content-Type": "application/json"}
    try:
        response = requests.post(LOCAL_AGENT_WEBHOOK, json=payload, headers=headers, timeout=5)
        if response.status_code == 200:
            msg = f"✅ [群益 API 已下單] {action.upper()} {clean_ticker} | 價格: {price} | 張數: {qty}"
            st.success(msg)
            send_telegram_msg(msg)
        else: st.error(f"❌ 地端回應異常: {response.text}")
    except Exception as e: st.error(f"❌ 無法連線地端: {e}")

def plot_stock_with_volume(df, title):
    """繪製專業量價走勢圖 (鐵則 4)"""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    # 價格線
    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], name='成交價', line=dict(color='#1f77b4', width=2)), row=1, col=1)
    # 成交量
    colors = ['red' if close >= open_p else 'green' for close, open_p in zip(df['Close'], df['Open'])]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)
    fig.update_layout(height=400, margin=dict(l=0, r=0, t=30, b=0), showlegend=False, xaxis_rangeslider_visible=False)
    return fig

# ==========================================
# 3. UI 介面與狀態初始化
# ==========================================
if 'watch_list' not in st.session_state:
    st.session_state['watch_list'] = ["1717.TW"]

# --- 側邊欄控制 ---
st.sidebar.title("⚙️ 控制中樞")

# 鐵則 3：模糊搜尋與快速加入
st.sidebar.subheader("🔍 搜尋股票")
# 建立顯示用的選項清單
search_options = [f"{k} {v}" for k, v in STOCKS_DICT.items()]
search_input = st.sidebar.selectbox("代號或名稱搜尋", ["請選擇"] + search_options)

# 鐵則 3：支援手動輸入代號按 Enter 加入
manual_input = st.sidebar.text_input("或直接輸入代號 (Enter 加入)", key="manual_add")

def add_to_watchlist(raw_id):
    clean_id = raw_id.split(' ')[0].strip()
    if clean_id:
        # 簡單判斷上市/上櫃
        ticker = f"{clean_id}.TW"
        if ticker not in st.session_state['watch_list']:
            st.session_state['watch_list'].append(ticker)
            st.rerun()

if st.sidebar.button("➕ 加入監控") or (manual_input and manual_input != st.session_state.get('last_input')):
    target = manual_input if manual_input else search_input
    if target != "請選擇":
        add_to_watchlist(target)
        st.session_state['last_input'] = manual_input

if st.sidebar.button("🗑️ 清空所有監控"):
    st.session_state['watch_list'] = []
    st.rerun()

# --- 主畫面 ---
st.title("📈 AI 穩贏自動化戰情牆")

# 鐵則 1 & 4：大盤走勢量價圖
st.subheader("🌐 大盤即時量價走勢")
m_col1, m_col2 = st.columns(2)

with m_col1:
    idx_df = yf.download("^TWII", period="1d", interval="5m", progress=False)
    if not idx_df.empty:
        st.plotly_chart(plot_stock_with_volume(idx_df, "加權指數"), use_container_width=True)
        st.metric("上市加權", f"{idx_df['Close'].iloc[-1]:.2f}", f"{idx_df['Close'].iloc[-1]-idx_df['Open'].iloc[0]:+.2f}")

with m_col2:
    otc_df = yf.download("^TWOII", period="1d", interval="5m", progress=False)
    if not otc_df.empty:
        st.plotly_chart(plot_stock_with_volume(otc_df, "櫃買指數"), use_container_width=True)
        st.metric("上櫃櫃買", f"{otc_df['Close'].iloc[-1]:.2f}", f"{otc_df['Close'].iloc[-1]-otc_df['Open'].iloc[0]:+.2f}")

st.markdown("---")

# --- 監控清單 ---
for ticker in st.session_state['watch_list']:
    stock_id = ticker.split('.')[0]
    stock_name = STOCKS_DICT.get(stock_id, "未知標的")
    
    with st.container():
        # 標題列：包含名稱與刪除按鈕 (鐵則 4)
        head1, head2 = st.columns([5, 1])
        head1.subheader(f"📊 {stock_id} {stock_name}")
        if head2.button("🗑️ 移除監控", key=f"del_{ticker}"):
            st.session_state['watch_list'].remove(ticker)
            st.rerun()
            
        col_chart, col_trade = st.columns([2, 1])
        
        with col_chart:
            df = yf.download(ticker, period="1d", interval="1m", progress=False)
            if not df.empty:
                st.plotly_chart(plot_stock_with_volume(df, ticker), use_container_width=True)
                last_price = float(df['Close'].iloc[-1])
            else:
                st.warning("暫無日內數據")
                last_price = 0.0

        with col_trade:
            st.markdown("#### ⚡ 遠端群益下單")
            with st.form(f"form_{ticker}"):
                act = st.selectbox("買賣", ["buy", "sell"], key=f"act_{ticker}")
                price = st.number_input("價格", value=last_price, step=0.05, key=f"prc_{ticker}")
                qty = st.number_input("張數", value=1, min_value=1, key=f"qty_{ticker}")
                if st.form_submit_button("🚀 發射實體委託"):
                    send_order(act, stock_id, price, qty)
        st.markdown("---")
