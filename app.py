import streamlit as st
import requests
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime

# ==========================================
# 1. 核心設定 (請確保網址正確且無特殊字元)
# ==========================================
# ⚠️ 注意：請檢查此網址，確保手打或純文字貼上，避免出現 xn-- 開頭的亂碼
LOCAL_AGENT_WEBHOOK = "https://stock-ai-app-ajmfbtg2rjyzaqkabfdmb7.streamlit.app/" 
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"

TG_BOT_TOKEN = "您的_Telegram_Bot_Token"
TG_CHAT_ID = "您的_Chat_ID"

# ==========================================
# 2. 常用台股清單 (用於模糊搜尋)
# ==========================================
# 您可以自由擴充此清單，格式為 "代號 名稱"
TAIWAN_STOCKS = [
    "1717 東聯", "2330 台積電", "2317 鴻海", "2454 聯發科", 
    "2603 長榮", "2881 富邦金", "2882 國泰金", "3008 大立光",
    "0050 元大台灣50", "0056 元大高股息", "3037 欣興", "3017 奇鋐"
]

# ==========================================
# 3. 功能函式
# ==========================================
def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload, timeout=5)
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
    try:
        # 這裡會送往您的 Windows 本機
        response = requests.post(LOCAL_AGENT_WEBHOOK, json=payload, timeout=5)
        if response.status_code == 200:
            msg = f"✅ [指令已送出] {action.upper()} {clean_ticker} | 價格: {price} | 數量: {qty}"
            st.success(msg)
            send_telegram_msg(msg)
        else:
            st.error(f"❌ 本機 Agent 回應異常 (Code: {response.status_code})")
    except Exception as e:
        st.error(f"❌ 無法連線至本機 Agent。請確認 ngrok 網址正確且 Windows 程式已啟動。\n錯誤訊息: {e}")

# ==========================================
# 4. UI 介面
# ==========================================
st.set_page_config(page_title="SOC 交易戰情室", layout="wide")

# 初始化監控清單
if 'watch_list' not in st.session_state:
    st.session_state['watch_list'] = ["1717 東聯"]

# --- 側邊欄：模糊搜尋與管理 ---
st.sidebar.title("⚙️ 戰情室控制台")

# 使用 selectbox 達成模糊搜尋效果
selected_stock = st.sidebar.selectbox("🔍 搜尋並新增股票", ["請輸入代號或名稱"] + TAIWAN_STOCKS)

if st.sidebar.button("➕ 加入監控"):
    if selected_stock != "請輸入代號或名稱" and selected_stock not in st.session_state['watch_list']:
        st.session_state['watch_list'].append(selected_stock)
        st.rerun()

if st.sidebar.button("🗑️ 清空清單"):
    st.session_state['watch_list'] = ["1717 東聯"]
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.info("💡 提示：網頁端數據由 Yahoo Finance 提供 (支援 Linux 雲端)，下單指令則穿透至本機群益 API 執行。")

# --- 主畫面 ---
st.title("📈 SOC 交易戰情室")

# 頂部大盤區
t1, t2 = st.columns(2)
with t1:
    # 畫大盤簡圖
    d_tw = yf.download("^TWII", period="1d", interval="5m", progress=False)
    if not d_tw.empty:
        curr = d_tw['Close'].iloc[-1].item()
        diff = curr - d_tw['Open'].iloc[0].item()
        st.metric("加權指數", f"{curr:.2f}", f"{diff:+.2f}")
with t2:
    d_otc = yf.download("^TWOII", period="1d", interval="5m", progress=False)
    if not d_otc.empty:
        curr = d_otc['Close'].iloc[-1].item()
        diff = curr - d_otc['Open'].iloc[0].item()
        st.metric("櫃買指數", f"{curr:.2f}", f"{diff:+.2f}")

st.markdown("---")

# 動態產生監控區
for stock_item in st.session_state['watch_list']:
    ticker_id = stock_item.split(' ')[0]
    # 判斷是否為上市或上櫃 (簡單邏輯：4碼且非特定代號通常加 .TW)
    yf_ticker = f"{ticker_id}.TW"
    
    with st.expander(f"📊 監控中：{stock_item}", expanded=True):
        col_chart, col_trade = st.columns([2, 1])
        
        with col_chart:
            # 取得即時與 K 線數據
            df = yf.download(yf_ticker, period="1mo", interval="1d", progress=False)
            if not df.empty:
                # K 線圖
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

        with col_trade:
            st.write(f"### ⚡ 遠端指令")
            with st.form(f"form_{ticker_id}"):
                act = st.selectbox("買賣", ["buy", "sell"])
                price = st.number_input("委託價", value=last_p, step=0.05)
                qty = st.number_input("張數", value=1, min_value=1)
                if st.form_submit_button("🚀 發送委託"):
                    send_order(act, ticker_id, price, qty)
