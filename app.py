import streamlit as st
st.set_page_config(page_title="AI 穩贏自動化戰情牆", layout="wide")

import requests
import urllib3
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. 核心設定
# ==========================================
NGROK_BASE_URL = "https://hitless-axel-misapply.ngrok-free.dev" 
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"
KVDB_BUCKET_ID = "PmpHQWa5QcddYqHfvc8Tp8"  

# ==========================================
# 2. 雲端全市場動態掃描 (FinMind API)
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
# 3. 🛡️ 雙軌通訊引擎與警報
# ==========================================
def subscribe_local_kline(stock_id):
    try: requests.post(f"{NGROK_BASE_URL}/api/subscribe", json={"secret": WEBHOOK_SECRET, "stock_id": stock_id}, headers={"ngrok-skip-browser-warning": "true"}, timeout=2)
    except: pass

def send_alert_config(stock_id, config):
    """將監控設定送到地端，並同步備份到雲端"""
    try:
        requests.post(f"https://kvdb.io/{KVDB_BUCKET_ID}/alert_{stock_id}", json=config, timeout=3)
        st.success("☁️ 監控設定已儲存至雲端資料庫！隔日開機將自動生效。")
    except:
        st.error("❌ 雲端儲存失敗。")

    try:
        requests.post(f"{NGROK_BASE_URL}/api/alert_config", json={"secret": WEBHOOK_SECRET, "stock_id": stock_id, "config": config}, headers={"ngrok-skip-browser-warning": "true"}, timeout=2)
    except: pass

# ==========================================
# 4. UI 介面與主邏輯
# ==========================================
if 'watch_list' not in st.session_state: st.session_state['watch_list'] = ["1717"]

# --- 左側邊欄：模糊搜尋 ---
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

# --- 主畫面 ---
st.title("📈 AI 穩贏自動化戰情牆")
st.info("☁️ 報價引擎：Yahoo Finance 雲端直連 (全時段即時顯示) | ⚡ 下單引擎：本機群益 NGROK 通道")
st.markdown("---")

for stock_id in st.session_state['watch_list']:
    stock_name = STOCKS_DICT.get(stock_id, "未知標的")
    
    with st.container():
        head1, head2 = st.columns([8, 1])
        head1.subheader(f"📊 {stock_id} {stock_name}")
        if head2.button("🗑️ 移除", key=f"del_{stock_id}"):
            st.session_state['watch_list'].remove(stock_id)
            st.rerun()
            
        # 畫面切分：左側占 2/3 (放兩張圖表)，右側占 1/3 (放下單)
        col_charts, col_trade = st.columns([2, 1])
        
        last_price = 0.0 # 預設價格
        
        with col_charts:
            # 將圖表區塊再次對分：左走勢、右 K 線
            chart_left, chart_right = st.columns(2)
            
            # --- 抓取 Yahoo 資料 ---
            ticker_tw = yf.Ticker(f"{stock_id}.TW")
            df_intraday = ticker_tw.history(period="1d", interval="1m")
            df_daily = ticker_tw.history(period="3mo", interval="1d")
            
            if df_intraday.empty or df_daily.empty:
                ticker_two = yf.Ticker(f"{stock_id}.TWO")
                df_intraday = ticker_two.history(period="1d", interval="1m")
                df_daily = ticker_two.history(period="3mo", interval="1d")
            
            if not df_intraday.empty:
                last_price = round(float(df_intraday['Close'].iloc[-1]), 2)
            
            # --- 繪製左側走勢圖 ---
            with chart_left:
                st.markdown("##### ⚡ 當日即時走勢")
                if not df_intraday.empty:
                    fig_line = go.Figure()
                    fig_line.add_trace(go.Scatter(
                        x=df_intraday.index, y=df_intraday['Close'], 
                        mode='lines', name='成交價',
                        line=dict(color='#1f77b4', width=2),
                        fill='tozeroy', fillcolor='rgba(31, 119, 180, 0.1)'
                    ))
                    fig_line.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="", yaxis_title="價格", template="plotly_white")
                    st.plotly_chart(fig_line, use_container_width=True)
                else:
                    st.warning("尚無今日即時走勢資料")

            # --- 繪製右側 K 線圖 ---
            with chart_right:
                st.markdown("##### 📊 歷史 K 線圖 (近三月)")
                if not df_daily.empty:
                    fig_candle = go.Figure(data=[go.Candlestick(
                        x=df_daily.index,
                        open=df_daily['Open'], high=df_daily['High'],
                        low=df_daily['Low'], close=df_daily['Close'],
                        increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
                    )])
                    fig_candle.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10), xaxis_rangeslider_visible=False, template="plotly_white")
                    st.plotly_chart(fig_candle, use_container_width=True)
                else:
                    st.warning("尚無歷史 K 線資料")

        # --- 實體下單區塊 (保留原本配置) ---
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
                    
        # --- 深度監控設定 (保留原本配置) ---
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
