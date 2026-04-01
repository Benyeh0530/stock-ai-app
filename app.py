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
NGROK_BASE_URL = "https://hitless-axel-misapply.ngrok-free.dev" 
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"
# ⚠️ 請填入您剛剛在 kvdb.io 取得的 Bucket ID
KVDB_BUCKET_ID = "PmpHQWa5QcddYqHfvc8Tp8"  

# ==========================================
# 2. 雲端全市場動態掃描 (保留上一版設定)
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
                if len(code) == 4 and code.isdigit(): stocks[code] = item.get("stock_name", "")
    except: pass
    return stocks

STOCKS_DICT = fetch_all_stocks()

# ==========================================
# 3. 🛡️ 雙軌通訊引擎 (本機優先 -> 雲端備援)
# ==========================================
def subscribe_local_kline(stock_id):
    try: requests.post(f"{NGROK_BASE_URL}/api/subscribe", json={"secret": WEBHOOK_SECRET, "stock_id": stock_id}, headers={"ngrok-skip-browser-warning": "true"}, timeout=2)
    except: pass

def fetch_kline(stock_id):
    """先嘗試連線本機群益，失敗則自動讀取雲端影分身"""
    try:
        # 嘗試連線地端
        res = requests.get(f"{NGROK_BASE_URL}/api/kline/{stock_id}", headers={"ngrok-skip-browser-warning": "true"}, timeout=2)
        if res.status_code == 200 and res.json().get("data"):
            return res.json().get("data")
    except:
        pass
    
    # 地端斷線，從雲端拉取昨日群益留下來的資料
    try:
        res = requests.get(f"https://kvdb.io/{KVDB_BUCKET_ID}/kline_{stock_id}", timeout=3)
        if res.status_code == 200:
            st.toast(f"💻 本機離線，已載入 {stock_id} 雲端群益歷史快取", icon="☁️")
            return res.json()
    except: pass
    return []

def send_alert_config(stock_id, config):
    """將監控設定送到地端，並同步備份到雲端"""
    # 1. 永遠寫入雲端 (這樣就算本機關機，明天早上開機也能抓到)
    try:
        requests.post(f"https://kvdb.io/{KVDB_BUCKET_ID}/alert_{stock_id}", json=config, timeout=3)
        st.success("☁️ 監控設定已儲存至雲端資料庫！隔日開機將自動生效。")
    except:
        st.error("❌ 雲端儲存失敗。")

    # 2. 嘗試即時通知地端 (如果地端醒著的話)
    try:
        requests.post(f"{NGROK_BASE_URL}/api/alert_config", json={"secret": WEBHOOK_SECRET, "stock_id": stock_id, "config": config}, headers={"ngrok-skip-browser-warning": "true"}, timeout=2)
    except: pass

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
selected_stock = st.sidebar.selectbox("全台股模糊搜尋", ["請點擊並輸入"] + search_options)

if st.sidebar.button("➕ 加入戰情牆", use_container_width=True):
    if selected_stock and not selected_stock.startswith("請點擊"):
        clean_id = selected_stock.split(' ')[0]
        if clean_id not in st.session_state['watch_list']:
            st.session_state['watch_list'].insert(0, clean_id)
            subscribe_local_kline(clean_id)
            st.rerun()

st.title("📈 AI 穩贏自動化戰情牆")
st.info("🌙 夜間模式啟動：當地端關機時，圖表將自動讀取群益雲端快取。您仍可自由設定隔日警報！")
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
            k_data = fetch_kline(stock_id)
            if k_data:
                st.plotly_chart(plot_capital_kline(k_data), use_container_width=True)
                last_price = k_data[-1]['Close']
            else:
                st.warning("尚無歷史群益資料，請在地端開機時刷新一次以建立雲端快取。")
                last_price = 0.0

        with col_trade:
            st.markdown("#### ⚡ 實體下單")
            with st.form(f"form_{stock_id}"):
                act = st.selectbox("方向", ["buy", "sell"])
                price = st.number_input("價格", value=float(last_price), step=0.05)
                qty = st.number_input("張數", value=1, min_value=1)
                if st.form_submit_button("🚀 發射委託"):
                    try:
                        requests.post(f"{NGROK_BASE_URL}/api/order", json={"secret": WEBHOOK_SECRET, "ticker": stock_id, "action": act, "price": price, "qty": qty}, headers={"ngrok-skip-browser-warning": "true"}, timeout=3)
                        st.success("指令已送出")
                    except:
                        st.error("連線失敗，無法送單。")
                    
        with st.expander(f"🔔 {stock_id} 深度監控設定 (隔日生效)"):
            c1, c2, c3 = st.columns(3)
            with c1:
                target_p = st.number_input("自訂到價監控", value=float(last_price), step=0.05, key=f"p_{stock_id}")
                use_cdp = st.checkbox("監控 CDP 關鍵位", key=f"cdp_{stock_id}")
            with c2:
                use_ma = st.checkbox("監控 5K 20MA", key=f"ma_{stock_id}")
                use_1k = st.checkbox("第一根K棒高低監控", key=f"1k_{stock_id}")
            with c3:
                k_times = st.multiselect("多分K監控", ["3M", "5M", "10M", "23M"], key=f"k_{stock_id}")
            
            if st.button("💾 儲存並同步至明日排程", key=f"save_{stock_id}"):
                config = {"target_price": target_p, "use_cdp": use_cdp, "use_ma20": use_ma, "use_1k": use_1k, "k_times": k_times}
                send_alert_config(stock_id, config)
                
        st.markdown("---")
