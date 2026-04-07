import streamlit as st
import yfinance as yf
import plotly.graph_objects as go

# ==========================================
# 0. 網頁基本設定 (寬屏模式)
# ==========================================
st.set_page_config(page_title="雲端戰情牆", layout="wide")

# ==========================================
# 1. ⬅️ 左邊菜單 (Sidebar) 與 模糊搜尋功能
# ==========================================
st.sidebar.markdown("## ⚙️ 戰情控制台")

# 建立股票清單，st.selectbox 天生內建「模糊搜尋」與「下拉自動完成」功能
# (這裡放入了您常看的標的，您可以隨時自由新增)
STOCK_LIST = [
    "1717 (長興)", "3017 (奇鋐)", "3037 (欣興)", "6770 (力積電)", 
    "0050 (元大台灣50)", "00891 (中信關鍵半導體)", "2330 (台積電)", 
    "VOO", "QQQ", "VT"
]

search_mode = st.sidebar.radio("搜尋模式", ["快速選單 (模糊搜尋)", "手動輸入代號"])

if search_mode == "快速選單 (模糊搜尋)":
    # 使用 selectbox 達成模糊搜尋效果
    selected_option = st.sidebar.selectbox("🔍 搜尋並選擇股票", STOCK_LIST, index=0)
    # 從選項中提取純代號 (例如 "1717 (長興)" -> "1717")
    stock_id = selected_option.split(" ")[0]
else:
    # 保留手動輸入彈性
    stock_id = st.sidebar.text_input("✍️ 手動輸入代號", value="1717")

st.sidebar.markdown("---")
st.sidebar.markdown("💡 *圖表資料來源: Yahoo Finance*")
st.sidebar.markdown("💡 *實體下單通道: 群益地端代理*")

# ==========================================
# 2. 主畫面：左右雙圖表配置
# ==========================================
st.markdown(f"### 📈 {stock_id} 即時戰情分析")
st.markdown("---")

if stock_id:
    # 建立左右兩個均分的區塊
    col1, col2 = st.columns(2)

    # ==========================================
    # 📈 左半邊：當日即時走勢圖 (1分K)
    # ==========================================
    with col1:
        st.markdown("##### ⚡ 當日即時走勢")
        try:
            # 判斷是否為美股 (純英文字母) 或台股 (數字)
            if stock_id.isalpha():
                ticker = yf.Ticker(stock_id)
                df_intraday = ticker.history(period="1d", interval="1m")
                df_daily = ticker.history(period="3mo", interval="1d")
            else:
                ticker = yf.Ticker(f"{stock_id}.TW")
                df_intraday = ticker.history(period="1d", interval="1m")
                df_daily = ticker.history(period="3mo", interval="1d")
                
                # 若上市沒資料，嘗試抓上櫃
                if df_intraday.empty or df_daily.empty:
                    ticker = yf.Ticker(f"{stock_id}.TWO")
                    df_intraday = ticker.history(period="1d", interval="1m")
                    df_daily = ticker.history(period="3mo", interval="1d")

            # 繪製左側走勢圖
            if not df_intraday.empty:
                fig_line = go.Figure()
                fig_line.add_trace(go.Scatter(
                    x=df_intraday.index, 
                    y=df_intraday['Close'], 
                    mode='lines', 
                    name='成交價',
                    line=dict(color='#1f77b4', width=2),
                    fill='tozeroy', # 增加底部陰影提升質感
                    fillcolor='rgba(31, 119, 180, 0.1)'
                ))
                fig_line.update_layout(
                    height=450, margin=dict(l=10, r=10, t=10, b=10),
                    xaxis_title="時間", yaxis_title="價格", template="plotly_white"
                )
                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.warning(
