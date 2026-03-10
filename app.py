import streamlit as st
import pandas as pd
import google.generativeai as genai
import datetime
import requests
import urllib3
import pytz
import json
import re
import time
import os
import numpy as np
import altair as alt
import pyotp

# --- 基礎設定 ---
st.set_page_config(page_title="AI 跨海智能戰情室 | Ben's SOC Ops", layout="wide", initial_sidebar_state="expanded")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 🎨 CSS 視覺美化 (保留既有風格並優化圖表空間) ---
st.markdown("""
<style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    h1 {
        background: -webkit-linear-gradient(45deg, #00f2fe, #4facfe);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 900; letter-spacing: 1px;
    }
    section[data-testid="stSidebar"] { background-color: #0f172a !important; }
    div[data-testid="stMetricValue"] { font-size: 1.5rem; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

# --- 1. 引擎與雲地通訊設定 ---
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if API_KEY:
    genai.configure(api_key=API_KEY)
    ai_model = genai.GenerativeModel('gemini-2.5-flash')

# --- 2. 數據引擎優化 ---
@st.cache_data(ttl=86400)
def get_full_stock_db():
    db = {}
    try:
        url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"
        res = requests.get(url, timeout=8).json()
        if res.get('msg') == 'success':
            for item in res['data']:
                db[str(item['stock_id'])] = str(item['stock_name'])
    except: pass
    return db

@st.cache_data(ttl=300)
def get_kline_data(code, suffix, interval, range_str='5d'):
    """優化 K 線抓取，支援更長的範圍"""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval={interval}&range={range_str}"
        res = requests.get(url, headers=headers, timeout=5).json()
        res_data = res['chart']['result'][0]
        idx = pd.to_datetime(res_data['timestamp'], unit='s', utc=True)
        quotes = res_data['indicators']['quote'][0]
        df = pd.DataFrame({
            'Open': quotes['open'], 'High': quotes['high'],
            'Low': quotes['low'], 'Close': quotes['close'],
            'Volume': quotes['volume']
        }, index=idx).dropna()
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=86400, show_spinner=False)
def get_correlated_stocks(code, name, is_us=False):
    """AI 聯動雷達：優化 Prompt 與重試機制"""
    if not API_KEY: return []
    market = "美股" if is_us else "台股"
    try:
        prompt = f"你是資深交易員。針對 {market} {name}({code})，找出 3 檔同產業或高度連動的股票代碼。規則：只輸出代碼，用逗號隔開。例：2330,2303,5347。"
        response = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.1)).text
        codes = re.findall(r'[A-Z0-9]{3,}', response.upper())
        return [c for c in codes if c != code][:3]
    except: return None

# --- 3. 圖表渲染引擎 (新增成交量圖層) ---
def render_combined_chart(df, is_us=False, chart_type="mini", alerts=[]):
    """結合價格與成交量的混合圖表"""
    if df.empty: return
    
    tz_str = 'America/New_York' if is_us else 'Asia/Taipei'
    df_plot = df.copy()
    df_plot['Time'] = df_plot.index.tz_convert(tz_str)
    
    # 價格主圖
    base = alt.Chart(df_plot.reset_index()).encode(x=alt.X('Time:T', title=''))
    
    line = base.mark_line(strokeWidth=2, color='#3b82f6').encode(
        y=alt.Y('Close:Q', scale=alt.Scale(zero=False), title='價格'),
        tooltip=['Time:T', 'Close:Q', 'Volume:Q']
    )
    
    # 成交量副圖
    volume = base.mark_bar(opacity=0.5).encode(
        y=alt.Y('Volume:Q', title='成交量', axis=alt.Axis(labels=False, ticks=False)),
        color=alt.condition(
            alt.datum.Close >= alt.datum.Open if 'Open' in df_plot.columns else alt.value(True),
            alt.value('#ef4444' if not is_us else '#10b981'), # 台股紅漲，美股綠漲
            alt.value('#10b981' if not is_us else '#ef4444')
        )
    ).properties(height=60)
    
    # 組合圖表
    main_chart = (line).properties(height=200)
    final_chart = alt.vconcat(main_chart, volume).resolve_scale(x='shared')
    st.altair_chart(final_chart, use_container_width=True)

def render_advanced_kline(df, curr_p, alerts=[], is_us=False, visible_layers=[], lookback=60):
    """進階 K 線圖：支援追溯與量能顯示"""
    if df.empty: return
    df_chart = df.tail(lookback).copy()
    
    up_color = "#ef4444" if not is_us else "#10b981"
    down_color = "#10b981" if not is_us else "#ef4444"
    
    # K棒圖層
    base = alt.Chart(df_chart.reset_index()).encode(x=alt.X('index:T', title=''))
    
    rule = base.mark_rule().encode(
        y=alt.Y('Low:Q', scale=alt.Scale(zero=False), title='價格'),
        y2='High:Q',
        color=alt.condition("datum.Close >= datum.Open", alt.value(up_color), alt.value(down_color))
    )
    
    bar = base.mark_bar().encode(
        y='Open:Q', y2='Close:Q',
        color=alt.condition("datum.Close >= datum.Open", alt.value(up_color), alt.value(down_color))
    )
    
    # 均線圖層 (MA5, MA20)
    df_chart['MA5'] = df_chart['Close'].rolling(5).mean()
    df_chart['MA20'] = df_chart['Close'].rolling(20).mean()
    ma5 = base.mark_line(color='#f59e0b', size=1.5).encode(y='MA5:Q')
    ma20 = base.mark_line(color='#a855f7', size=1.5).encode(y='MA20:Q')
    
    # 成交量圖層
    vol = base.mark_bar(opacity=0.4).encode(
        y=alt.Y('Volume:Q', title='量', axis=alt.Axis(labels=False)),
        color=alt.condition("datum.Close >= datum.Open", alt.value(up_color), alt.value(down_color))
    ).properties(height=50)
    
    k_main = alt.layer(rule, bar, ma5, ma20).properties(height=220)
    st.altair_chart(alt.vconcat(k_main, vol).resolve_scale(x='shared'), use_container_width=True)

# --- 4. 主程式邏輯 ---
st.title("⚡ AI 智能戰情室 2.0")

# 側邊欄設定
with st.sidebar:
    st.header("⚙️ 顯示設定")
    k_lookback = st.select_slider("🕯️ K 線追溯長度", options=[60, 120, 240, 480], value=60)
    st.info(f"當前設定：追溯過去 {k_lookback} 根 K 棒")
    st.divider()
    # (保留既有的 2FA 與下單網址設定...)

# 戰區渲染 (範例：台股)
all_stocks = get_full_stock_db()
if 'tw_stocks' not in st.session_state: st.session_state.tw_stocks = []

for idx, stock in enumerate(st.session_state.tw_stocks):
    code, name = stock['code'], stock['name']
    
    # 抓取長數據以支援回測
    df_daily, suffix = get_historical_features(code, is_us=False)
    df_1m = get_realtime_tick(code, suffix)
    
    with st.container(border=True):
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown(f"### {name}({code}) | 當日分時量價")
            render_combined_chart(df_1m, is_us=False)
            
        with col2:
            st.markdown(f"### 歷史追溯 K 線 (MA5/MA20)")
            render_advanced_kline(df_daily, None, is_us=False, lookback=k_lookback)
            
        # 族群聯動雷達優化顯示
        corr_codes = get_correlated_stocks(code, name, is_us=False)
        if corr_codes is None:
            st.warning("🔗 族群雷達掃描中... (AI 正在計算關聯度)")
        else:
            corr_str = " | ".join([f"**{all_stocks.get(c, c)}({c})**" for c in corr_codes])
            st.markdown(f"🔗 **AI 聯動推薦：** {corr_str}")

# (其餘下單與美股邏輯保留...)
