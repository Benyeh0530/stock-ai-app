import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd

# 假設您從輸入框或按鈕獲取了股票代號
# stock_id = "1717" 

st.markdown(f"### 📈 {stock_id} 即時戰情分析")

# 建立左右兩個區塊
col1, col2 = st.columns(2)

# ==========================================
# ⬅️ 左半邊：當日即時走勢圖 (1分K)
# ==========================================
with col1:
    st.markdown("##### ⚡ 當日即時走勢")
    
    # 透過 Streamlit 雲端直接向 Yahoo 請求今日 1 分鐘級別資料
    ticker_tw = yf.Ticker(f"{stock_id}.TW")
    df_intraday = ticker_tw.history(period="1d", interval="1m")
    
    # 若上市沒資料，嘗試抓上櫃
    if df_intraday.empty:
        ticker_two = yf.Ticker(f"{stock_id}.TWO")
        df_intraday = ticker_two.history(period="1d", interval="1m")

    if not df_intraday.empty:
        # 繪製走勢線圖 (Line Chart)
        fig_line = go.Figure()
        fig_line.add_trace(go.Scatter(
            x=df_intraday.index, 
            y=df_intraday['Close'], 
            mode='lines', 
            name='成交價',
            line=dict(color='#1f77b4', width=2)
        ))
        
        # 美化版面
        fig_line.update_layout(
            height=350,
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis_title="時間",
            yaxis_title="價格",
            template="plotly_white"
        )
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.warning("⚠️ 尚無今日即時走勢資料 (可能尚未開盤或代號錯誤)")

# ==========================================
# ➡️ 右半邊：歷史 K 線圖 (日K)
# ==========================================
with col2:
    st.markdown("##### 📊 歷史 K 線圖 (近三個月)")
    
    # 透過 Streamlit 雲端直接向 Yahoo 請求近 3 個月日線資料
    df_daily = ticker_tw.history(period="3mo", interval="1d")
    if df_daily.empty:
        df_daily = ticker_two.history(period="3mo", interval="1d")

    if not df_daily.empty:
        # 繪製蠟燭圖 (Candlestick Chart)
        fig_candle = go.Figure(data=[go.Candlestick(
            x=df_daily.index,
            open=df_daily['Open'],
            high=df_daily['High'],
            low=df_daily['Low'],
            close=df_daily['Close'],
            increasing_line_color='red',    # 台股紅漲
            decreasing_line_color='green'   # 台股綠跌
        )])
        
        # 美化版面並隱藏底部的範圍選擇器 (節省空間)
        fig_candle.update_layout(
            height=350,
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis_rangeslider_visible=False,
            template="plotly_white"
        )
        st.plotly_chart(fig_candle, use_container_width=True)
    else:
        st.warning("⚠️ 尚無歷史 K 線資料")
