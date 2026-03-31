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
# 2. 雲端雙軌資料庫 (鐵壁備援 + 動態抓取)
# ==========================================
# 核心名單：保證就算政府 API 封鎖雲端 IP，這些重要標的也絕對找得到！
BASE_STOCKS = {
    "1717": "東聯", "2330": "台積電", "2317": "鴻海", "2454": "聯發科",
    "2603": "長榮", "3037": "欣興", "3017": "奇鋐", "2303": "聯電",
    "2609": "陽明", "2615": "萬海", "2881": "富邦金", "2882": "國泰金",
    "3231": "緯創", "2382": "廣達", "1513": "中興電", "1519": "華城",
    "6770": "力積電", "3008": "大立光", "0050": "元大台灣50", "0056": "元大高股息"
}

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_all_stocks():
    stocks = BASE_STOCKS.copy() # 先載入鐵壁名單
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"
    }
    
    # 嘗試抓取上市 (TWSE)
    try:
        res_twse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", headers=headers, verify=False, timeout=5)
        if res_twse.status_code == 200:
            for item in res_twse.json():
                if len(item["Code"]) == 4: stocks[item["Code"]] = item["Name"]
    except: pass

    # 嘗試抓取上櫃 (TPEx)
    try:
        res_tpex = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", headers=headers, verify=False, timeout=5)
        if res_tpex.status_code == 200:
            for item in res_tpex.json():
                if len(item.get("SecuritiesCompanyCode", "")) == 4: 
                    stocks[item["SecuritiesCompanyCode"]] = item["CompanyName"]
    except: pass
        
    return stocks

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

# --- 側邊欄：搜尋控制中樞 (回歸左側) ---
st.sidebar.title("⚙️ 戰情控制台")
st.sidebar.markdown("### 🔍 新增監控標的")

search_options = [f"{k} {v}" for k, v in STOCKS_DICT.items()]
selected_stock = st.sidebar.selectbox(
    "全台股模糊搜尋", 
    ["請點擊並輸入代號/名稱 (例: 鴻海)"] + search_options
)

if st.sidebar.button("➕ 加入戰情牆", use_container_width=True):
    if selected_stock and not selected_stock.startswith("請點擊"):
        clean_id = selected_stock.split(' ')[0]
        if clean_id not in st.session_state['watch_list']:
            st.session_state['watch_list'].insert(0, clean_id)
            subscribe_local_kline(clean_id)
            st.rerun()

st.sidebar.markdown("---")
if st.sidebar.button("🔄 刷新全畫面 K 線", use_container_width=True):
    st.rerun()

# --- 主畫面：乾淨的看盤與下單區 ---
st.title("📈 AI 穩贏自動化戰情牆")
st.info("💡 提示：請在左側選單搜尋並新增股票。K 線與下單指令將即時穿透至您的 Windows 本機。")
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
