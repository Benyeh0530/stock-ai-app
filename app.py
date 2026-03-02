import streamlit as st
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
    # 使用最新穩定的 2.5 版本模型
    ai_model = genai.GenerativeModel('gemini-2.5-flash')

# --- 2. 核心數據引擎 ---
@st.cache_data(ttl=3600)
def get_full_stock_db():
    """從政府 OpenAPI 抓取全台股清單，用來對照股票名稱"""
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
    """🚀 終極核彈版：直連 Yahoo 底層 JSON，完全防封鎖，並自動運算 15K MA"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    }
    
    # 自動雙面嘗試上市與上櫃
    for suffix in [".TW", ".TWO"]:
        try:
            # 1. 抓取 5 天的 1 分鐘資料
            url_1m = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1m&range=5d"
            res_1m = requests.get(url_1m, headers=headers, timeout=5)
            data_1m = res_1m.json()
            
            if not data_1m.get('chart', {}).get('result'): continue 
            
            result_1m = data_1m['chart']['result'][0]
            if 'timestamp' not in result_1m: continue
                
            idx = pd.to_datetime(result_1m['timestamp'], unit='s', utc=True).tz_convert('Asia/Taipei')
            quote_1m = result_1m['indicators']['quote'][0]
            df_1m_all = pd.DataFrame({
                'High': quote_1m['high'], 
                'Low': quote_1m['low'], 
                'Close': quote_1m['close'], 
                'Volume': quote_1m['volume']
            }, index=idx).dropna()
            
            if df_1m_all.empty: continue

            # --- 計算 15K 20MA (包含昨日籌碼) ---
            df_15m = df_1m_all['Close'].resample('15min').last().dropna()
            ma20_15k = df_15m.tail(20).mean() if len(df_15m) >= 20 else df_15m.mean()

            # --- 切割出「今日」的 1 分鐘資料供即時當日均線使用 ---
            last_day = df_1m_all.index[-1].date()
            df_1m_today = df_1m_all[df_1m_all.index.date == last_day]

            # 2. 抓取日 K 資料
            url_1d = f"https://query2.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range=1mo"
            res_1d = requests.get(url_1d, headers=headers, timeout=5)
            data_1d = res_1d.json()
            
            df_daily = pd.DataFrame()
            if data_1d.get('chart', {}).get('result'):
                result_1d = data_1d['chart']['result'][0]
                if 'timestamp' in result_1d:
                    quote_1d = result_1d['indicators']['quote'][0]
                    df_daily = pd.DataFrame({'Close': quote_1d['close']}).dropna()

            return df_1m_today, df_daily, ma20_15k

        except Exception as e:
            continue
            
    return None, None, None

# 🚀 AI 投顧選股報告
def get_advanced_ai_report():
    if not API_KEY: return "⚠️ 請先設定 API Key"
    tw_tz = pytz.timezone('Asia/Taipei')
    now = datetime.datetime.now(tw_tz)
    is_after_1230 = now.time() >= datetime.time(12, 30)
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    prompt = f"""
    現在是台灣時間 {time_str}。你是頂尖台股操盤手。
    請給出一份實戰選股報告。
    【限制條件】：所有推薦股票必須在 150 元以下！請給出明確進場價位。繁體中文條列式。
    
    ### 📈 1. 當沖作多推薦 (5檔)
    ### 📉 2. 當沖作空推薦 (5檔)
    ### 🌊 3. 波段操作推薦 (5檔) (須包含法人動態與熱門產業分析)
    """
    if is_after_1230:
        prompt += "\n### 🌙 4. 隔日沖推薦 (5檔) (尾盤鎖碼標的)"
    else:
        prompt += "\n### 🌙 4. 隔日沖推薦 (⚠️ 目前時間未達 12:30，暫不提供)"

    try:
        return ai_model.generate_content(prompt).text
    except Exception as e: 
        return f"AI 分析連線失敗: {e}"

# --- 3. 網頁介面 ---
st.title("⚡ AI 智能監控 (終極完整版)")

if 'stocks' not in st.session_state: st.session_state.stocks = []

all_stocks = get_full_stock_db()

with st.sidebar:
    st.header("🤖 AI 獨家選股報告")
    if st.button("🚀 立即生成全盤選股報告", use_container_width=True, type="primary"):
        st.session_state.ai_report = "loading"
        st.rerun()
        
    st.divider()
    
    st.header("🎯 自訂監控選單")
    # 💡 終極防呆機制：自動清除多餘的英文與小數點，只保留數字
    raw_input = st.text_input("輸入代碼 (如: 8183)").strip()
    input_code = raw_input.upper().replace(".TW", "").replace(".TWO", "")
    
    if input_code and input_code in all_stocks:
        st.write(f"✅ 已選取: {all_stocks[input_code]}")
        
    if st.button("➕ 加入即時監控"):
        if input_code and input_code not in [s['code'] for s in st.session_state.stocks]:
            st.session_state.stocks.append({"code": input_code, "name": all_stocks.get(input_code, "股票")})
            st.rerun()
    
    if st.button("🗑️ 清空監控清單"):
        st.session_state.stocks = []
        st.rerun()

# 主畫面佈局
if getattr(st.session_state, 'ai_report', None) == "loading":
    st.subheader("🤖 AI 正在深度運算全台股數據 (約需 10~20 秒)...")
    with st.spinner('過濾 150 元以下標的...'):
        st.session_state.ai_report = get_advanced_ai_report()
    st.rerun()
elif getattr(st.session_state, 'ai_report', None):
    with st.expander("🌟 點我收起 / 展開【AI 深度選股報告】", expanded=True):
        st.markdown(st.session_state.ai_report)
        if st.button("關閉報告"):
            st.session_state.ai_report = None
            st.rerun()

st.divider()

t_col1, t_col2 = st.columns([1, 1])
with t_col1:
    if st.button("🔄 手動刷新即時股價"):
        st.cache_data.clear()
        st.rerun()
with t_col2:
    tw_tz = pytz.timezone('Asia/Taipei')
    st.write(f"⏱️ 股價更新時間: {datetime.datetime.now(tw_tz).strftime('%H:%M:%S')}")

st.subheader("📺 即時戰情看板")
if not st.session_state.stocks:
    st.info("請於側邊欄輸入純數字代碼 (如 8183) 加入監控。")
else:
    for stock in st.session_state.stocks:
        code = stock['code']
        name = stock['name']
        
        df_1m, df_daily, ma20_15k = get_stock_data(code)
        
        if df_1m is not None and not df_1m.empty and ma20_15k is not None:
            curr_p = df_1m['Close'].iloc[-1]
            prev_p = df_daily['Close'].iloc[-2] if len(df_daily) > 1 else curr_p
            high_p = df_1m['High'].max()
            low_p = df_1m['Low'].min()
            
            # 真實當日均價 (VWAP)
            vwap = ( (df_1m['High'] + df_1m['Low'] + df_1m['Close'])/3 * df_1m['Volume'] ).sum() / df_1m['Volume'].sum()
            
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                c1.metric(f"{name}({code})", f"{curr_p:.2f}", f"{curr_p - prev_p:.2f}")
                c2.metric("當日均價線", f"{vwap:.2f}")
                c3.metric("15K 20MA", f"{ma20_15k:.2f}")
                
                with st.expander("🔍 深度策略分析", expanded=False):
                    d_col = "red" if curr_p > vwap else "green"
                    st.markdown(f"⚡ **當沖建議**: :{d_col}[{'多方強勢' if curr_p > vwap else '空方強勢'}] | 參考點位: {vwap:.2f}")
                    
                    trend_col = "red" if curr_p > ma20_15k else "green"
                    st.markdown(f"🌊 **短波段趨勢 (15K)**: :{trend_col}[{'站上 20MA 偏多' if curr_p > ma20_15k else '跌破 20MA 偏空'}]")

                    pos = (curr_p - low_p) / (high_p - low_p + 0.001)
                    n_msg = "📈 尾盤鎖碼" if pos > 0.85 else "📉 尾盤殺低" if pos < 0.15 else "⏳ 區間震盪"
                    st.markdown(f"🌙 **隔日沖判定**: {n_msg} ({pos*100:.1f}%)")
        else:
            st.warning(f"⚠️ {code} 數據獲取受限，請稍候刷新。")
