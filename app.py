import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import datetime
import requests
import re
import urllib3

# 基礎設定
st.set_page_config(page_title="AI 智能量價戰情室", layout="wide")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. AI 引擎設定 (從 Secrets 讀取) ---
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. 資料獲取引擎 (OpenAPI + Yahoo) ---
@st.cache_data(ttl=3600)
def get_stock_db():
    """抓取全台股清單"""
    db = {}
    try:
        res_tw = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=10, verify=False)
        for item in res_tw.json():
            db[item['Code']] = item['Name']
        res_otc = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=10, verify=False)
        for item in res_otc.json():
            db[item['SecuritiesCompanyCode']] = item['CompanyName']
    except: pass
    return db

def get_ai_recommendation():
    """AI 自動分析建議"""
    if not API_KEY: return "請先設定 API Key"
    prompt = "你是台股專家，請分析今日市場並推薦2檔適合當沖/波段的個股代碼與理由。請用繁體中文。"
    try:
        return model.generate_content(prompt).text
    except: return "AI 分析暫時無法連線..."

# --- 3. 介面與監控邏輯 ---
st.title("⚡ AI 智能監控戰情室 (iPhone版)")

# 初始化自選股 (利用 Session State 記憶)
if 'stocks' not in st.session_state:
    st.session_state.stocks = []

# 側邊欄
with st.sidebar:
    st.header("🎯 監控選單")
    all_db = get_stock_db()
    
    # 模糊搜尋輸入
    input_val = st.text_input("輸入代碼 (如: 8183)").strip()
    if input_val and input_val in all_db:
        st.write(f"已選中: {all_db[input_val]}")
    
    if st.button("➕ 加入監控"):
        if input_val and input_val not in st.session_state.stocks:
            st.session_state.stocks.append(input_val)
            st.rerun()

    if st.button("🗑️ 全部清空"):
        st.session_state.stocks = []
        st.rerun()

# 主畫面佈局
col_main, col_ai = st.columns([2, 1])

with col_ai:
    st.subheader("🤖 AI 今日戰情")
    if st.button("🚀 獲取 AI 深度分析"):
        with st.spinner('AI 分析中...'):
            st.markdown(get_ai_recommendation())
    
    st.subheader("🔔 主力訊號日誌")
    # 網頁版日誌暫存 (簡化版)
    st.info("系統已連線，1K 動能監控中...")

with col_main:
    st.subheader("📺 即時戰情看板")
    if not st.session_state.stocks:
        st.info("請在左側輸入代碼加入監控。")
    else:
        for code in st.session_state.stocks:
            name = all_db.get(code, "股票")
            ticker = yf.Ticker(f"{code}.TW" if len(code)==4 else f"{code}.TWO")
            
            # 獲取 1K 與 日K 數據
            df_1m = ticker.history(period="1d", interval="1m")
            df_daily = ticker.history(period="1mo", interval="1d")
            
            if not df_1m.empty:
                curr_p = df_1m['Close'].iloc[-1]
                ref_p = df_daily['Close'].iloc[-2] if len(df_daily) > 1 else curr_p
                high_p = df_1m['High'].max()
                low_p = df_1m['Low'].min()
                
                # 計算真實 VWAP (均價) 與 1K MA5
                vwap = ( (df_1m['High'] + df_1m['Low'] + df_1m['Close'])/3 * df_1m['Volume'] ).sum() / df_1m['Volume'].sum()
                ma5_1k = df_1m['Close'].tail(5).mean()
                
                # 介面顯示
                with st.container(border=True):
                    c1, c2, c3 = st.columns([1, 1, 1])
                    c1.metric(f"{name} ({code})", f"{curr_p:.2f}", f"{curr_p - ref_p:.2f}")
                    c2.metric("真實均價", f"{vwap:.2f}")
                    c3.metric("1K MA5", f"{ma5_1k:.2f}")
                    
                    # 三維策略判定邏輯
                    st.write("**--- 智能策略分析 ---**")
                    
                    # 1. 當沖
                    day_msg = "⚡ 當沖: "
                    if curr_p > vwap and curr_p > ma5_1k: day_msg += "✅ 強勢多方 | 建議回測均價守穩進場"
                    elif curr_p < vwap and curr_p < ma5_1k: day_msg += "📉 弱勢空方 | 建議反彈均價不過佈空"
                    else: day_msg += "⏳ 盤整回檔 | 建議觀望"
                    st.write(day_msg)
                    
                    # 2. 隔日沖
                    night_msg = "🌙 隔日沖: "
                    pos = (curr_p - low_p) / (high_p - low_p + 0.001)
                    if pos > 0.85: night_msg += "📈 尾盤鎖碼強勢 | 具備隔日沖優勢"
                    elif pos < 0.15: night_msg += "📉 尾盤殺低弱勢 | 慎防隔日續跌"
                    else: night_msg += "⏳ 位階中性 | 無明顯優勢"
                    st.write(night_msg)

            else:
                st.error(f"無法獲取 {code} 資料")
