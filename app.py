import streamlit as st
st.set_page_config(page_title="AI 穩贏自動化戰情牆", layout="wide")

import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

# ==========================================
# 1. 核心設定 (請填入您最新的 ngrok 網址)
# ==========================================
# ⚠️ 務必更新為您剛剛執行的 ngrok 網址 (不要加尾巴的 /tv_webhook)
NGROK_BASE_URL = "https://hitless-axel-misapply.ngrok-free.dev" 
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"

# ==========================================
# 2. 雲端與本機通訊函式
# ==========================================
@st.cache_data(ttl=3600)
def fetch_stocks_from_local():
    """從您的本機伺服器取得全台股清單"""
    try:
        res = requests.get(f"{NGROK_BASE_URL}/api/stocks", headers={"ngrok-skip-browser-warning": "true"}, timeout=5)
        return res.json()
    except:
        return {"1717": "東聯", "2330": "台積電"} # 斷線時的備用

STOCKS_DICT = fetch_stocks_from_local()

def subscribe_local_kline(stock_id):
    """通知本機去向群益要 K 線資料"""
    payload = {"secret": WEBHOOK_SECRET, "stock_id": stock_id}
    headers = {"ngrok-skip-browser-warning": "true", "Content-Type": "application/json"}
    try:
        requests.post(f"{NGROK_BASE_URL}/api/subscribe", json=payload, headers=headers, timeout=3)
    except: pass

def fetch_kline_from_local(stock_id):
    """從本機伺服器拉取最新的 K 線資料"""
    try:
        res = requests.get(f"{NGROK_BASE_URL}/api/kline/{stock_id}", headers={"ngrok-skip-browser-warning": "true"}, timeout=3)
        return res.json().get("data", [])
    except: return []

def send_order_to_local(action, ticker, price, qty):
    payload = {"secret": WEBHOOK_SECRET, "ticker": ticker, "action": action, "price": price, "qty": qty}
    headers = {"ngrok-skip-browser-warning": "true", "Content-Type": "application/json"}
    try:
        res = requests.post(f"{NGROK_BASE_URL}/api/order", json=payload, headers=headers, timeout=5)
        if res.status_code == 200: st.success(f"✅ 委託已送達本機: {action.upper()} {ticker}")
        else: st.error("❌ 本機拒絕請求。")
    except: st.error("❌ 無法連線至本機伺服器。")

def plot_capital_kline(data_list, title):
    if not data_list: return None
    df = pd.DataFrame(data_list)
    df['Date'] = pd.to_datetime(df['Date'], format='%Y%m%d', errors='coerce')
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=df['Date'], open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
    colors = ['red' if c >= o else 'green' for c, o in zip(df['Close'], df['Open'])]
    fig.add_trace(go.Bar(x=df['Date'], y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)
    
    fig.update_layout(height=450, margin=dict(l=0, r=0, t=30, b=0), showlegend=False, xaxis_rangeslider_visible=False)
    return fig

# ==========================================
# 3. UI 介面
# ==========================================
if 'watch_list' not in st.session_state:
    st.session_state['watch_list'] = ["1717"]

st.sidebar.title("⚙️ 雲端戰情控制台")
search_options = [f"{k} {v}" for k, v in STOCKS_DICT.items()]
search_input = st.sidebar.selectbox("🔍 模糊搜尋台股", ["請選擇"] + search_options)
manual_input = st.sidebar.text_input("✍️ 輸入代號 (按 Enter 加入)", key="manual_add")

def add_stock(raw_id):
    clean_id = raw_id.split(' ')[0].strip()
    if clean_id and clean_id not in st.session_state['watch_list']:
        st.session_state['watch_list'].append(clean_id)
        subscribe_local_kline(clean_id) # 通知本機去抓資料
        st.rerun()

if st.sidebar.button("➕ 加入監控") or (manual_input and manual_input != st.session_state.get('last_input')):
    target = manual_input if manual_input else search_input
    if target != "請選擇":
        add_stock(target)
        st.session_state['last_input'] = manual_input

if st.sidebar.button("🔄 刷新全畫面 (拉取最新 K 線)"):
    st.rerun()

st.title("📈 AI 穩贏雲端戰情牆 (群益私有雲架構)")
st.info("架構說明：此網頁的 K 線與下單，皆透過 ngrok 隧道即時與您的 Windows 本機連線。")

for stock_id in st.session_state['watch_list']:
    stock_name = STOCKS_DICT.get(stock_id, "未知標的")
    
    with st.container():
        head1, head2 = st.columns([5, 1])
        head1.subheader(f"📊 {stock_id} {stock_name}")
        if head2.button("🗑️ 移除", key=f"del_{stock_id}"):
            st.session_state['watch_list'].remove(stock_id)
            st.rerun()
            
        col_chart, col_trade = st.columns([2, 1])
        
        with col_chart:
            # 雲端向本機拉取 K 線資料
            k_data = fetch_kline_from_local(stock_id)
            if k_data:
                st.plotly_chart(plot_capital_kline(k_data, stock_id), use_container_width=True)
                last_price = k_data[-1]['Close']
            else:
                st.warning("本機尚未回傳資料。請點擊上方 [刷新全畫面] 或稍後再試。")
                last_price = 0.0

        with col_trade:
            st.markdown("#### ⚡ 穿透實體下單")
            with st.form(f"form_{stock_id}"):
                act = st.selectbox("買賣", ["buy", "sell"])
                price = st.number_input("價格", value=float(last_price), step=0.05)
                qty = st.number_input("張數", value=1, min_value=1)
                if st.form_submit_button("🚀 發射群益委託"):
                    send_order_to_local(act, stock_id, price, qty)
        st.markdown("---")
