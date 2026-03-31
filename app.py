import streamlit as st
# ⚠️ 鐵則 2：更名為 AI 穩贏自動化戰情牆
st.set_page_config(page_title="AI 穩贏自動化戰情牆", layout="wide")

import requests
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

# ==========================================
# 1. 核心設定 (保留既有 Webhook 與 TG 功能)
# ==========================================
LOCAL_AGENT_WEBHOOK = "https://hitless-axel-misapply.ngrok-free.dev/tv_webhook" 
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"

TG_BOT_TOKEN = "您的_Telegram_Bot_Token"
TG_CHAT_ID = "您的_Chat_ID"

# ==========================================
# 2. 功能函式 (保留既有警示與下單穿透機制)
# ==========================================
def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload, timeout=3)
    except:
        pass

def send_order(action, ticker, price, qty):
    # 確保傳給群益的代號是乾淨的純數字 (鐵則 5：群益下單整合)
    clean_ticker = str(ticker).replace(".TW", "").replace(".TWO", "")
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
            msg = f"✅ [群益 API 指令已送出] {action.upper()} {clean_ticker} | 價格: {price} | 數量: {qty}"
            st.success(msg)
            send_telegram_msg(msg)
        else:
            st.error(f"❌ 本機 Agent 回應異常 (Code: {response.status_code})\n{response.text}")
    except Exception as e:
        st.error(f"❌ 無法連線至本機 Agent，請確認 ngrok 網址正確且程式執行中。\n{e}")

def get_valid_ticker(stock_id):
    """驗證並轉換股票代號 (支援上市 .TW 與上櫃 .TWO)"""
    stock_id = str(stock_id).strip()
    if not stock_id: return None
    
    # 簡單驗證邏輯：先試上市，不行再試上櫃
    test_tw = f"{stock_id}.TW"
    try:
        info = yf.Ticker(test_tw).fast_info
        if 'lastPrice' in info: return test_tw
    except:
        pass
        
    test_two = f"{stock_id}.TWO"
    try:
        info = yf.Ticker(test_two).fast_info
        if 'lastPrice' in info: return test_two
    except:
        return None
    return None

# ==========================================
# 3. UI 介面與狀態初始化
# ==========================================
if 'watch_list' not in st.session_state:
    st.session_state['watch_list'] = ["1717.TW"] # 預設保留東聯

# --- 側邊欄：鐵則 3 (全股票模糊搜尋機制) ---
st.sidebar.title("⚙️ 戰情室控制台")
st.sidebar.write("🔍 **全台股搜尋與新增**")
new_stock_input = st.sidebar.text_input("請輸入股票代號 (如: 2330, 3017)", placeholder="輸入代號後按 Enter")

if st.sidebar.button("➕ 加入監控"):
    if new_stock_input:
        with st.spinner("驗證代號中..."):
            valid_ticker = get_valid_ticker(new_stock_input)
            if valid_ticker:
                if valid_ticker not in st.session_state['watch_list']:
                    st.session_state['watch_list'].append(valid_ticker)
                    st.rerun()
                else:
                    st.sidebar.warning("此股票已在監控清單中！")
            else:
                st.sidebar.error("找不到此股票代號，請確認是否輸入正確。")

if st.sidebar.button("🗑️ 清空清單"):
    st.session_state['watch_list'] = []
    st.rerun()

# --- 主畫面 ---
st.title("📈 AI 穩贏自動化戰情牆")

# 保留既有的大盤監控
st.subheader("🌐 大盤即時走勢")
t1, t2 = st.columns(2)
with t1:
    try:
        d_tw = yf.download("^TWII", period="1d", interval="5m", progress=False)
        if not d_tw.empty:
            curr = d_tw['Close'].iloc[-1].item()
            diff = curr - d_tw['Open'].iloc[0].item()
            st.metric("加權指數 (上市)", f"{curr:.2f}", f"{diff:+.2f}")
    except:
        st.metric("加權指數 (上市)", "載入中...", "0.0")

with t2:
    try:
        d_otc = yf.download("^TWOII", period="1d", interval="5m", progress=False)
        if not d_otc.empty:
            curr = d_otc['Close'].iloc[-1].item()
            diff = curr - d_otc['Open'].iloc[0].item()
            st.metric("櫃買指數 (上櫃)", f"{curr:.2f}", f"{diff:+.2f}")
    except:
        st.metric("櫃買指數 (上櫃)", "載入中...", "0.0")

st.markdown("---")

# 動態產生監控區
for yf_ticker in st.session_state['watch_list']:
    display_name = yf_ticker.replace(".TW", "").replace(".TWO", "")
    
    with st.container():
        st.markdown(f"### 🎯 標的：{display_name}")
        col_chart, col_trade = st.columns([2, 1])
        
        with col_chart:
            try:
                # 鐵則 4：抓取單日 1 分鐘級別的即時走勢與成交量
                df = yf.download(yf_ticker, period="1d", interval="1m", progress=False)
                if not df.empty:
                    # 建立上下雙層圖表 (走勢圖 + 成交量)
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                        vertical_spacing=0.05, row_heights=[0.7, 0.3])
                    
                    # 上層：即時價格走勢線
                    fig.add_trace(go.Scatter(x=df.index, y=df['Close'].squeeze(), 
                                             mode='lines', name='成交價', 
                                             line=dict(color='#1f77b4', width=2)), row=1, col=1)
                    
                    # 下層：成交量柱狀圖 (台股慣例：收盤>=開盤為紅，反之為綠)
                    colors = ['red' if close >= open else 'green' 
                              for close, open in zip(df['Close'].squeeze(), df['Open'].squeeze())]
                    fig.add_trace(go.Bar(x=df.index, y=df['Volume'].squeeze(), 
                                         name='成交量', marker_color=colors), row=2, col=1)
                    
                    fig.update_layout(height=400, margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
                    fig.update_xaxes(rangeslider_visible=False)
                    
                    st.plotly_chart(fig, use_container_width=True)
                    last_p = float(df['Close'].iloc[-1].item())
                else:
                    st.warning(f"目前非交易時間或無法取得 {display_name} 的日內走勢數據")
                    last_p = 0.0
            except Exception as e:
                st.error("圖表載入失敗")
                last_p = 0.0

        # 保留既有的遠端下單區塊
        with col_trade:
            st.markdown(f"#### ⚡ 群益遠端指令中樞")
            with st.form(f"form_{display_name}"):
                act = st.selectbox("買賣方向", ["buy", "sell"])
                price = st.number_input("委託價", value=float(last_p), step=0.5)
                qty = st.number_input("委託張數", value=1, min_value=1)
                if st.form_submit_button("🚀 發送實體委託"):
                    send_order(act, display_name, price, qty)
        st.markdown("---")
