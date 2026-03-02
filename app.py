import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import datetime
import requests
import urllib3
import time

# --- 基礎設定 ---
st.set_page_config(page_title="AI 智能監控戰情室", layout="wide", initial_sidebar_state="collapsed")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. AI 引擎設定 ---
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if API_KEY:
    genai.configure(api_key=API_KEY)
    ai_model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. 核心數據引擎 (方案 A: 10秒極速快取) ---

@st.cache_data(ttl=3600) # 股票名稱清單一小時更新一次
def get_full_stock_db():
    db = {}
    try:
        res_tw = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=10, verify=False)
        for item in res_tw.json(): db[item['Code']] = item['Name']
        res_otc = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=10, verify=False)
        for item in res_otc.json(): db[item['SecuritiesCompanyCode']] = item['CompanyName']
    except: pass
    return db

@st.cache_data(ttl=10) # 🎯 方案 A：10 秒極速快取，兼顧即時與穩定
def get_stock_data(code):
    try:
        suffix = ".TW" if len(code) == 4 else ".TWO"
        ticker = yf.Ticker(f"{code}{suffix}")
        df_1m = ticker.history(period="1d", interval="1m")
        df_daily = ticker.history(period="1mo", interval="1d")
        return df_1m, df_daily
    except:
        return None, None

def get_ai_recommendation():
    if not API_KEY: return "⚠️ 請先設定 API Key"
    prompt = "你是專業台股分析師，請分析今日市場大盤並推薦2檔適合當沖/波段的個股代碼、進場位階與理由。請用繁體中文。"
    try:
        return ai_model.generate_content(prompt).text
    except: return "AI 分析連線超時..."

# --- 3. 網頁介面 ---
st.title("⚡ AI 智能監控 (iPhone 極速版)")

# 初始化 Session State
if 'stocks' not in st.session_state: st.session_state.stocks = []
if 'logs' not in st.session_state: st.session_state.logs = []

all_stocks = get_full_stock_db()

# --- 頂部功能區 ---
t_col1, t_col2 = st.columns([1, 1])
with t_col1:
    if st.button("🔄 立即手動刷新 (跳過快取)"):
        st.cache_data.clear() # 清除所有 10 秒快取，強迫抓最新
        st.rerun()
with t_col2:
    # 顯示最後更新時間，讓您知道數據新不新鮮
    st.write(f"⏱️ 數據時間: {datetime.datetime.now().strftime('%H:%M:%S')}")

# --- 側邊欄 ---
with st.sidebar:
    st.header("🎯 監控選單")
    input_code = st.text_input("輸入代碼 (如: 8183)").strip()
    if input_code and input_code in all_stocks:
        st.write(f"✅ 已選取: {all_stocks[input_code]}")
        
    if st.button("➕ 加入清單"):
        if input_code and input_code not in [s['code'] for s in st.session_state.stocks]:
            st.session_state.stocks.append({"code": input_code, "name": all_stocks.get(input_code, "股票")})
            st.rerun()
    
    if st.button("🗑️ 全部清空"):
        st.session_state.stocks = []
        st.session_state.logs = []
        st.rerun()

# --- 主畫面佈局 ---
col_main, col_side = st.columns([1.8, 1.2])

with col_main:
    st.subheader("📺 即時戰情看板")
    if not st.session_state.stocks:
        st.info("請於側邊欄輸入代碼加入監控")
    else:
        for stock in st.session_state.stocks:
            code = stock['code']
            name = stock['name']
            
            df_1m, df_daily = get_stock_data(code)
            
            if df_1m is not None and not df_1m.empty:
                curr_p = df_1m['Close'].iloc[-1]
                prev_p = df_daily['Close'].iloc[-2] if len(df_daily) > 1 else curr_p
                high_p = df_1m['High'].max()
                low_p = df_1m['Low'].min()
                
                # VWAP 與 MA 計算
                vwap = ( (df_1m['High'] + df_1m['Low'] + df_1m['Close'])/3 * df_1m['Volume'] ).sum() / df_1m['Volume'].sum()
                ma5_1k = df_1m['Close'].tail(5).mean()
                avg_vol = df_1m['Volume'].mean()
                
                # 爆量偵測
                last_vol = df_1m['Volume'].iloc[-1]
                if last_vol > avg_vol * 3:
                    time_str = df_1m.index[-1].strftime("%H:%M:%S")
                    direction = "帶量上攻" if curr_p > vwap else "帶量下殺"
                    log_msg = f"[{time_str}] {name}({code}) ➔ {direction} | 價: {curr_p:.2f} | 量: {int(last_vol)}"
                    if log_msg not in [l['msg'] for l in st.session_state.logs]:
                        st.session_state.logs.append({"time": time_str, "msg": log_msg})

                with st.container(border=True):
                    c1, c2, c3 = st.columns(3)
                    c1.metric(f"{name}({code})", f"{curr_p:.2f}", f"{curr_p - prev_p:.2f}")
                    c2.metric("真實均價", f"{vwap:.2f}")
                    c3.metric("1K MA5", f"{ma5_1k:.2f}")
                    
                    with st.expander("🔍 深度策略報告", expanded=True):
                        d_col = "red" if curr_p > vwap else "green"
                        st.markdown(f"⚡ **當沖建議**: :{d_col}[{'多方強勢' if curr_p > vwap else '空方強勢'}] | 參考點位: {vwap:.2f}")
                        pos = (curr_p - low_p) / (high_p - low_p + 0.001)
                        n_msg = "📈 尾盤鎖碼" if pos > 0.85 else "📉 尾盤殺低" if pos < 0.15 else "⏳ 區間震盪"
                        st.markdown(f"🌙 **隔日沖判定**: {n_msg} ({pos*100:.1f}%)")
                        ma20 = df_daily['Close'].tail(20).mean()
                        st.markdown(f"🌊 **波段趨勢**: {'偏多' if curr_p > ma20 else '偏空'}")
            else:
                st.warning(f"⚠️ {code} 數據獲取中或受限，請點擊上方刷新按鈕。")

with col_side:
    st.subheader("🤖 AI 今日戰情")
    if st.button("🚀 啟動 AI 深度分析"):
        with st.spinner('Gemini 分析中...'):
            st.markdown(get_ai_recommendation())
            
    st.subheader("🔔 主力訊號日誌")
    if st.session_state.logs:
        sorted_logs = sorted(st.session_state.logs, key=lambda x: x['time'], reverse=True)
        log_text = "\n\n".join([l['msg'] for l in sorted_logs])
        st.text_area("即時動態", value=log_text, height=450)
    else:
        st.info("等待異常訊號...")
