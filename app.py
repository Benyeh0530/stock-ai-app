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
    ai_model = genai.GenerativeModel('gemini-2.5-flash')

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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    }
    
    for suffix in [".TW", ".TWO"]:
        try:
            # 抓取 5 天的 1 分鐘資料，以防時區與開盤判定 Bug
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

            # 計算 15K 20MA (跨日濃縮計算)
            df_15m = df_1m_all['Close'].resample('15min').last().dropna()
            ma20_15k = df_15m.tail(20).mean() if len(df_15m) >= 20 else df_15m.mean()

            # 切割出當日資料供 VWAP 與即時 K 線使用
            last_day = df_1m_all.index[-1].date()
            df_1m_today = df_1m_all[df_1m_all.index.date == last_day]

            # 抓取日 K 資料供位階與波段判定使用
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
st.title("⚡ AI 智能監控戰情室")

# 初始化記憶體 (確保資料切換不消失)
if 'stocks' not in st.session_state: st.session_state.stocks = []
if 'logs' not in st.session_state: st.session_state.logs = []

all_stocks = get_full_stock_db()

# --- 側邊欄 ---
with st.sidebar:
    st.header("🤖 AI 獨家選股報告")
    if st.button("🚀 立即生成全盤選股報告", use_container_width=True, type="primary"):
        st.session_state.ai_report = "loading"
        st.rerun()
        
    st.divider()
    
    st.header("🎯 自訂監控選單")
    
    # --- 🚀 全新模糊搜尋下拉選單 ---
    stock_list = [f"{code} {name}" for code, name in all_stocks.items()]
    selected_stock = st.selectbox(
        "🔍 支援代碼或中文字搜尋", 
        options=["請點此搜尋..."] + stock_list,
        index=0
    )
    
    if st.button("➕ 加入即時監控"):
        if selected_stock and selected_stock != "請點此搜尋...":
            input_code = selected_stock.split(" ")[0]
            input_name = " ".join(selected_stock.split(" ")[1:])
            
            if input_code not in [s['code'] for s in st.session_state.stocks]:
                st.session_state.stocks.append({"code": input_code, "name": input_name})
                st.rerun()
    
    if st.button("🗑️ 清空監控與日誌"):
        st.session_state.stocks = []
        st.session_state.logs = [] 
        st.rerun()

# --- 報告載入區 ---
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

# --- 頂端控制區 ---
t_col1, t_col2 = st.columns([1, 1])
with t_col1:
    if st.button("🔄 手動刷新即時股價"):
        st.cache_data.clear()
        st.rerun()
with t_col2:
    tw_tz = pytz.timezone('Asia/Taipei')
    st.write(f"⏱️ 股價更新時間: {datetime.datetime.now(tw_tz).strftime('%H:%M:%S')}")

# --- 主戰情看板 ---
st.subheader("📺 即時戰情看板")
if not st.session_state.stocks:
    st.info("請於左側選單搜尋並加入您想監控的標的。")
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
            
            # --- 全日歷史爆量掃描 (5K / 15K) ---
            vol_5m = df_1m['Volume'].resample('5min').sum().dropna()
            vol_15m = df_1m['Volume'].resample('15min').sum().dropna()
            
            if len(vol_5m) > 0:
                avg_5m = vol_5m.mean()
                for ts, vol in vol_5m.items():
                    if vol > avg_5m * 2.5 and vol > 100:
                        time_str = ts.strftime("%H:%M")
                        msg = f"[{time_str}] ⚡ {name}({code}) | 5分K爆量: {int(vol)}張"
                        if msg not in [l['msg'] for l in st.session_state.logs]:
                            st.session_state.logs.append({"time": time_str, "msg": msg})

            if len(vol_15m) > 0:
                avg_15m = vol_15m.mean()
                for ts, vol in vol_15m.items():
                    if vol > avg_15m * 2.5 and vol > 200:
                        time_str = ts.strftime("%H:%M")
                        msg = f"[{time_str}] 🔥 {name}({code}) | 15分K爆量: {int(vol)}張"
                        if msg not in [l['msg'] for l in st.session_state.logs]:
                            st.session_state.logs.append({"time": time_str, "msg": msg})
            
            # 計算當日真實均價 (VWAP)
            vwap = ( (df_1m['High'] + df_1m['Low'] + df_1m['Close'])/3 * df_1m['Volume'] ).sum() / df_1m['Volume'].sum()
            
            # 顯示 UI 卡片
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

# --- 主力帶量日誌區 ---
st.divider()
st.subheader("🔔 帶量異常歷史紀錄 (5K / 15K)")
if st.session_state.logs:
    # 根據時間降冪排序，最新爆量在最上方
    sorted_logs = sorted(st.session_state.logs, key=lambda x: x['time'], reverse=True)
    log_text = "\n\n".join([l['msg'] for l in sorted_logs])
    st.text_area("今日爆量軌跡", value=log_text, height=200)
else:
    st.info("目前無異常爆量訊號。系統持續監控中...")
