import streamlit as st
st.set_page_config(page_title="AI 穩贏自動化戰情牆", layout="wide")

import requests
import urllib3
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. 核心設定
# ==========================================
# ⚠️ 請更新為您的 ngrok 網址
NGROK_BASE_URL = "https://您的ngrok網址.ngrok-free.app" 
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"

# ==========================================
# 2. 雲端全市場動態掃描
# ==========================================
@st.cache_data(ttl=86400, show_spinner="📡 正在載入全市場清單...")
def fetch_all_stocks():
    stocks = {"1717": "東聯", "2330": "台積電", "2317": "鴻海"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
    try:
        url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"
        res = requests.get(url, verify=False, timeout=5)
        if res.status_code == 200:
            for item in res.json().get("data", []):
                code = str(item.get("stock_id", ""))
                if len(code) == 4 and code.isdigit():
                    stocks[code] = item.get("stock_name", "")
    except: pass
    return stocks

STOCKS_DICT = fetch_all_stocks()

# ==========================================
# 3. 雲端與本機通訊函式
# ==========================================
def send_request(endpoint, payload=None):
    headers = {"ngrok-skip-browser-warning": "true", "Content-Type": "application/json"}
    url = f"{NGROK_BASE_URL}{endpoint}"
    if payload:
        payload["secret"] = WEBHOOK_SECRET
        return requests.post(url, json=payload, headers=headers, timeout=5)
    else:
        return requests.get(url, headers=headers, timeout=5)

def subscribe_local_kline(stock_id):
    try: send_request("/api/subscribe", {"stock_id": stock_id})
    except: pass

def fetch_kline_from_local(stock_id):
    try:
        res = send_request(f"/api/kline/{stock_id}")
        return res.json().get("data", []) if res.status_code == 200 else []
    except: return []

def send_alert_config(stock_id, config):
    try:
        res = send_request("/api/alert_config", {"stock_id": stock_id, "config": config})
        if res.status_code == 200: st.success("✅ 監控設定已同步至地端引擎！")
        else: st.error("❌ 同步失敗。")
    except: st.error("❌ 無法連線至地端。")

def plot_capital_kline(data_list):
    if not data_list: return go.Figure()
    df = pd.DataFrame(data_list)
    df['Date'] = pd.to_datetime(df['Date'], format='%Y%m%d', errors='coerce')
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=df['Date'], open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
    colors = ['red' if c >= o else 'green' for c, o in zip(df['Close'], df['Open'])]
    fig.add_trace(go.Bar(x=df['Date'], y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)
    fig.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0), showlegend=False, xaxis_rangeslider_visible=False)
    return fig

# ==========================================
# 4. UI 介面
# ==========================================
if 'watch_list' not in st.session_state: st.session_state['watch_list'] = ["1717"]

st.sidebar.title("⚙️ 戰情控制台")
search_options = [f"{k} {v}" for k, v in STOCKS_DICT.items()]
selected_stock = st.sidebar.selectbox("全台股模糊搜尋 (含興櫃)", ["請點擊並輸入 (例: 776)"] + search_options)

if st.sidebar.button("➕ 加入戰情牆", use_container_width=True):
    if selected_stock and not selected_stock.startswith("請點擊"):
        clean_id = selected_stock.split(' ')[0]
        if clean_id not in st.session_state['watch_list']:
            st.session_state['watch_list'].insert(0, clean_id)
            subscribe_local_kline(clean_id)
            st.rerun()

st.title("📈 AI 穩贏自動化戰情牆")
st.markdown("---")

for stock_id in st.session_state['watch_list']:
    stock_name = STOCKS_DICT.get(stock_id, "未知標的")
    
    with st.container():
        head1, head2 = st.columns([8, 1])
        head1.subheader(f"📊 {stock_id} {stock_name}")
        if head2.button("🗑️ 移除", key=f"del_{stock_id}"):
            st.session_state['watch_list'].remove(stock_id)
            st.rerun()
            
        col_chart, col_trade = st.columns([2, 1])
        with col_chart:
            k_data = fetch_kline_from_local(stock_id)
            if k_data:
                st.plotly_chart(plot_capital_kline(k_data), use_container_width=True)
                last_price = k_data[-1]['Close']
            else:
                st.warning("⏳ 等待地端 Windows 傳回資料...")
                last_price = 0.0

        with col_trade:
            st.markdown("#### ⚡ 實體下單")
            with st.form(f"form_{stock_id}"):
                act = st.selectbox("方向", ["buy", "sell"])
                price = st.number_input("價格", value=float(last_price), step=0.05)
                qty = st.number_input("張數", value=1, min_value=1)
                if st.form_submit_button("🚀 發射委託"):
                    send_request("/api/order", {"ticker": stock_id, "action": act, "price": price, "qty": qty})
                    st.success("指令已送出")
                    
        # 🎯 深度監控設定面板
        with st.expander(f"🔔 {stock_id} 深度監控設定 (到價 TG 警報)"):
            c1, c2, c3 = st.columns(3)
            with c1:
                target_p = st.number_input("自訂到價監控", value=float(last_price), step=0.05, key=f"p_{stock_id}")
                use_cdp = st.checkbox("監控 CDP 關鍵位", key=f"cdp_{stock_id}")
            with c2:
                use_ma = st.checkbox("監控 5K 20MA", key=f"ma_{stock_id}")
                use_1k = st.checkbox("第一根K棒高低監控", key=f"1k_{stock_id}")
            with c3:
                k_times = st.multiselect("多分K監控", ["3M", "5M", "10M", "23M"], key=f"k_{stock_id}")
            
            if st.button("💾 套用監控設定", key=f"save_{stock_id}"):
                config = {"target_price": target_p, "use_cdp": use_cdp, "use_ma20": use_ma, "use_1k": use_1k, "k_times": k_times}
                send_alert_config(stock_id, config)
                
        st.markdown("---")
