import streamlit as st
st.set_page_config(page_title="AI 穩贏自動化戰情牆", layout="wide")

import requests
import urllib3
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

# 關閉 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. 核心設定 (請更新您的 ngrok 網址)
# ==========================================
NGROK_BASE_URL = "https://您的ngrok網址.ngrok-free.app" 
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"

# ==========================================
# 2. 雲端直連證交所 & 櫃買中心 (偽裝流量 + 雙重抓取)
# ==========================================
@st.cache_data(ttl=86400, show_spinner="📡 正在突破防火牆，下載全台股最新清單...")
def fetch_all_stocks():
    stocks = {}
    # 🕵️‍♂️ 偽裝成正常的 Google Chrome 瀏覽器，繞過政府防火牆
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 抓取上市 (TWSE)
    try:
        twse_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        res_twse = requests.get(twse_url, headers=headers, verify=False, timeout=10)
        if res_twse.status_code == 200:
            for item in res_twse.json():
                if len(item["Code"]) == 4:
                    stocks[item["Code"]] = item["Name"]
    except Exception as e:
        print(f"上市清單抓取失敗: {e}")

    # 抓取上櫃 (TPEx) - 讓清單更完整
    try:
        tpex_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
        res_tpex = requests.get(tpex_url, headers=headers, verify=False, timeout=10)
        if res_tpex.status_code == 200:
            for item in res_tpex.json():
                if len(item.get("SecuritiesCompanyCode", "")) == 4:
                    stocks[item["SecuritiesCompanyCode"]] = item["CompanyName"]
    except Exception as e:
        print(f"上櫃清單抓取失敗: {e}")
        
    return stocks

# 載入動態字典
STOCKS_DICT = fetch_all_stocks()

# ==========================================
# 3. 雲端與本機通訊函式
# ==========================================
def subscribe_local_kline(stock_id):
    payload = {"secret": WEBHOOK_SECRET, "stock_id": stock_id}
    headers = {"ngrok-skip-browser-warning": "true", "Content-Type": "application/json"}
    try: requests.post(f"{NGROK_BASE_URL}/api/subscribe", json=payload, headers=headers, timeout=3)
    except: pass

def fetch_kline_from_local(stock_id):
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
# 4. UI 介面
# ==========================================
if 'watch_list' not in st.session_state:
    st.session_state['watch_list'] = ["1717"]

st.title("📈 AI 穩贏自動化戰情牆")

# 🚨 防禦機制：如果字典還是空的，提供強制清除快取的按鈕
if not STOCKS_DICT:
    st.error("⚠️ 偵測到股票字典為空！雲端主機目前被政府防火牆阻擋。")
    if st.button("🔄 強制清除快取並重試 (Clear Cache)", type="primary"):
        st.cache_data.clear()
        st.rerun()

st.markdown("### 🔍 新增監控標的 (全台股模糊搜尋)")
search_options = [f"{k} {v}" for k, v in STOCKS_DICT.items()]

col_search, col_btn, col_refresh = st.columns([5, 2, 2])
with col_search:
    selected_stock = st.selectbox(
        "搜尋", 
        ["請點擊此處並直接輸入代號或名稱 (例: 77)"] + search_options, 
        label_visibility="collapsed"
    )

with col_btn:
    if st.button("➕ 加入戰情牆", use_container_width=True):
        if selected_stock and not selected_stock.startswith("請點擊"):
            clean_id = selected_stock.split(' ')[0]
            if clean_id not in st.session_state['watch_list']:
                st.session_state['watch_list'].insert(0, clean_id)
                subscribe_local_kline(clean_id)
                st.rerun()

with col_refresh:
    if st.button("🔄 刷新全K線", use_container_width=True):
        st.rerun()

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
                st.plotly_chart(plot_capital_kline(k_data, stock_id), use_container_width=True)
                last_price = k_data[-1]['Close']
            else:
                st.warning("⏳ 正在等待您的地端 Windows 傳回群益 K 線資料...")
                last_price = 0.0

        with col_trade:
            st.markdown("#### ⚡ 穿透實體下單")
            with st.form(f"form_{stock_id}"):
                act = st.selectbox("買賣方向", ["buy", "sell"])
                price = st.number_input("委託價格", value=float(last_price), step=0.05)
                qty = st.number_input("委託張數", value=1, min_value=1)
                if st.form_submit_button("🚀 發射群益委託"):
                    send_order_to_local(act, stock_id, price, qty)
        st.markdown("---")
