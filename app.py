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
# 1. 核心設定
# ==========================================
# ⚠️ 明天測試時，請務必更新為您最新產生的 ngrok 網址 (不要加尾巴的 /tv_webhook)
NGROK_BASE_URL = "https://您的ngrok網址.ngrok-free.app" 
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"

# ==========================================
# 2. 雲端直連證交所 (100% 動態，絕不寫死！)
# ==========================================
@st.cache_data(ttl=86400) # 每天自動去政府資料庫更新一次
def fetch_twse_all_stocks():
    """直接從台灣證券交易所 OpenAPI 取得全台股最新清單"""
    stocks = {}
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        # 直接由雲端發起請求，略過憑證驗證確保暢通
        res = requests.get(url, verify=False, timeout=10)
        data = res.json()
        for item in data:
            if len(item["Code"]) == 4: # 確保是標準 4 碼股票
                stocks[item["Code"]] = item["Name"]
    except Exception as e:
        st.error("⚠️ 無法連線至證交所 API，請重新整理網頁。")
    return stocks

# 全動態的股票字典，這理面包含了 1700+ 檔最新的台股
STOCKS_DICT = fetch_twse_all_stocks()

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
# 4. UI 介面 (主畫面優化)
# ==========================================
if 'watch_list' not in st.session_state:
    st.session_state['watch_list'] = ["1717"]

st.title("📈 AI 穩贏自動化戰情牆")
st.info("💡 架構狀態：股票清單由 TWSE 即時供應 | K 線與下單指令透過 ngrok 穿透至您的 Windows 本機群益 API。")

# --- 搜尋區塊移至主畫面 ---
st.markdown("### 🔍 新增監控標的 (全台股模糊搜尋)")
search_options = [f"{k} {v}" for k, v in STOCKS_DICT.items()]

col_search, col_btn, col_refresh = st.columns([5, 2, 2])
with col_search:
    # 這裡就是模糊搜尋的核心，點擊後直接打字就能過濾
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
                st.session_state['watch_list'].insert(0, clean_id) # 加到清單最上面
                subscribe_local_kline(clean_id) # 通知地端去抓這檔的群益K線
                st.rerun()

with col_refresh:
    if st.button("🔄 刷新全K線", use_container_width=True):
        st.rerun()

st.markdown("---")

# --- 監控清單與 K 線圖 ---
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
            # 雲端向本機拉取群益 K 線資料
            k_data = fetch_kline_from_local(stock_id)
            if k_data:
                st.plotly_chart(plot_capital_kline(k_data, stock_id), use_container_width=True)
                last_price = k_data[-1]['Close']
            else:
                st.warning("⏳ 正在等待您的地端 Windows 傳回群益 K 線資料... (請確認地端程式與 ngrok 已啟動)")
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
