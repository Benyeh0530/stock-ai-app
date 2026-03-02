import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import datetime
import requests
import urllib3
import pytz

# --- 基礎設定 ---
st.set_page_config(page_title="AI 智能監控戰情室", layout="wide", initial_sidebar_state="expanded")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. AI 引擎設定 ---
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if API_KEY:
    genai.configure(api_key=API_KEY)
    # 使用 gemini-1.5-pro 可以獲得更深度的產業與法人分析，若跑太慢可改回 flash
    ai_model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. 核心數據引擎 ---
@st.cache_data(ttl=3600)
def get_full_stock_db():
    db = {}
    try:
        res_tw = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=10, verify=False)
        for item in res_tw.json(): db[item['Code']] = item['Name']
        res_otc = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=10, verify=False)
        for item in res_otc.json(): db[item['SecuritiesCompanyCode']] = item['CompanyName']
    except: pass
    return db

@st.cache_data(ttl=10)
def get_stock_data(code):
    try:
        suffix = ".TW" if len(code) == 4 else ".TWO"
        ticker = yf.Ticker(f"{code}{suffix}")
        df_1m = ticker.history(period="1d", interval="1m")
        df_daily = ticker.history(period="1mo", interval="1d")
        return df_1m, df_daily
    except:
        return None, None

# 🚀 全新強大的 AI 投顧選股引擎
def get_advanced_ai_report():
    if not API_KEY: return "⚠️ 請先設定 API Key"
    
    # 取得台灣時間
    tw_tz = pytz.timezone('Asia/Taipei')
    now = datetime.datetime.now(tw_tz)
    is_after_1230 = now.time() >= datetime.time(12, 30)
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    prompt = f"""
    現在是台灣時間 {time_str}。你現在是一位頂尖的台股操盤手與分析師。
    請根據今日台股最新的市場真實狀況（包含熱門產業、資金流向、三大法人動態），提供一份精準的實戰選股報告。
    
    【嚴格限制條件 - 違反將導致嚴重虧損】：
    1. 價格限制：以下所有推薦的股票，目前股價「絕對必須在 150 元（含）以下」！超過 150 元的標的請勿列入。
    2. 明確實戰：請一定要給出明確的「建議進場價位」或「進場區間」。
    3. 排版格式：請用繁體中文，使用清晰的條列式或 Markdown 格式方便手機閱讀。

    請依序提供以下四大單元：

    ### 📈 1. 當沖作多推薦 (5檔)
    - 挑選今日強勢、量價配合的標的。
    - 格式：代碼、名稱、建議進場價位、看多理由。

    ### 📉 2. 當沖作空推薦 (5檔)
    - 挑選今日弱勢、跌破均線或支撐的標的。
    - 格式：代碼、名稱、建議空單進場價、看空理由。

    ### 🌊 3. 波段操作推薦 (5檔)
    - 嚴格挑選條件：近期熱門產業、具備實質題材、有大量資金湧入、且「三大法人（外資/投信）剛開始買超佈局」。
    - 格式：代碼、名稱、建議進場區間、詳細看多理由（請務必點出所屬產業、題材與法人動態）。
    """

    if is_after_1230:
        prompt += """
    ### 🌙 4. 隔日沖推薦 (5檔)
    - 現在時間已過 12:30，請挑選今日尾盤有機會鎖碼、均價線之上、適合隔日沖的標的。
    - 格式：代碼、名稱、建議進場價位、隔日沖勝率分析理由。
    """
    else:
        prompt += """
    ### 🌙 4. 隔日沖推薦 (⚠️ 目前時間未達 12:30，暫不提供尾盤標的)
    """

    try:
        return ai_model.generate_content(prompt).text
    except Exception as e: 
        return f"AI 分析連線失敗，請稍後再試。錯誤: {e}"

# --- 3. 網頁介面 ---
st.title("⚡ AI 智能監控 (含投顧選股報告)")

if 'stocks' not in st.session_state: st.session_state.stocks = []
if 'logs' not in st.session_state: st.session_state.logs = []

all_stocks = get_full_stock_db()

# --- 側邊欄：AI 選股報告專區 ---
with st.sidebar:
    st.header("🤖 AI 獨家選股報告")
    st.info("包含當沖多空、波段(法人題材)、隔日沖(12:30後解鎖)，皆限150元內。")
    if st.button("🚀 立即生成全盤選股報告", use_container_width=True, type="primary"):
        st.session_state.ai_report = "loading"
        st.rerun()
        
    st.divider()
    
    st.header("🎯 自訂監控選單")
    input_code = st.text_input("輸入代碼 (如: 8183)").strip()
    if input_code and input_code in all_stocks:
        st.write(f"✅ 已選取: {all_stocks[input_code]}")
        
    if st.button("➕ 加入即時監控"):
        if input_code and input_code not in [s['code'] for s in st.session_state.stocks]:
            st.session_state.stocks.append({"code": input_code, "name": all_stocks.get(input_code, "股票")})
            st.rerun()
    
    if st.button("🗑️ 清空監控清單"):
        st.session_state.stocks = []
        st.rerun()

# --- 主畫面佈局 ---
# 如果點擊了生成報告，優先顯示報告
if getattr(st.session_state, 'ai_report', None) == "loading":
    st.subheader("🤖 AI 正在深度運算全台股數據 (約需 10~20 秒)...")
    with st.spinner('分析熱門產業、比對三大法人籌碼、過濾 150 元以下標的...'):
        report = get_advanced_ai_report()
        st.session_state.ai_report = report
    st.rerun()
elif getattr(st.session_state, 'ai_report', None):
    with st.expander("🌟 點我收起 / 展開【AI 深度選股報告】", expanded=True):
        st.markdown(st.session_state.ai_report)
        if st.button("關閉報告"):
            st.session_state.ai_report = None
            st.rerun()

st.divider()

# --- 頂部功能區 (即時監控) ---
t_col1, t_col2 = st.columns([1, 1])
with t_col1:
    if st.button("🔄 手動刷新即時股價"):
        st.cache_data.clear()
        st.rerun()
with t_col2:
    tw_tz = pytz.timezone('Asia/Taipei')
    st.write(f"⏱️ 股價更新時間: {datetime.datetime.now(tw_tz).strftime('%H:%M:%S')}")

# 即時監控看板邏輯 (與之前相同)
st.subheader("📺 即時戰情看板")
if not st.session_state.stocks:
    st.info("請於側邊欄輸入代碼加入監控，或產出 AI 報告後將心儀標的加入。")
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
            
            vwap = ( (df_1m['High'] + df_1m['Low'] + df_1m['Close'])/3 * df_1m['Volume'] ).sum() / df_1m['Volume'].sum()
            ma5_1k = df_1m['Close'].tail(5).mean()
            
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                c1.metric(f"{name}({code})", f"{curr_p:.2f}", f"{curr_p - prev_p:.2f}")
                c2.metric("真實均價", f"{vwap:.2f}")
                c3.metric("1K MA5", f"{ma5_1k:.2f}")
                
                with st.expander("🔍 深度策略分析", expanded=False):
                    d_col = "red" if curr_p > vwap else "green"
                    st.markdown(f"⚡ **當沖建議**: :{d_col}[{'多方強勢' if curr_p > vwap else '空方強勢'}] | 參考點位: {vwap:.2f}")
                    pos = (curr_p - low_p) / (high_p - low_p + 0.001)
                    n_msg = "📈 尾盤鎖碼" if pos > 0.85 else "📉 尾盤殺低" if pos < 0.15 else "⏳ 區間震盪"
                    st.markdown(f"🌙 **隔日沖判定**: {n_msg} ({pos*100:.1f}%)")
        else:
            st.warning(f"⚠️ {code} 數據獲取受限，請稍候刷新。")
