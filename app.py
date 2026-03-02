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
import numpy as np

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

@st.cache_data(ttl=60)
def get_market_temp():
    headers = {"User-Agent": "Mozilla/5.0"}
    indices = {'^TWII': '台股加權', '^IXIC': '那斯達克'}
    results = {}
    for code, name in indices.items():
        try:
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{code}?interval=1d&range=2d"
            res = requests.get(url, headers=headers, timeout=3).json()
            quotes = res['chart']['result'][0]['indicators']['quote'][0]['close']
            closes = [c for c in quotes if c is not None]
            if len(closes) >= 2:
                curr, prev = closes[-1], closes[-2]
                pct = ((curr - prev) / prev) * 100
                results[name] = (curr, pct)
        except: pass
    return results

@st.cache_data(ttl=900)
def get_historical_features(code, is_us=False):
    headers = {"User-Agent": "Mozilla/5.0"}
    suffixes = [""] if is_us else [".TW", ".TWO"]
    for suffix in suffixes:
        try:
            url_1d = f"https://query2.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range=1y"
            res_1d = requests.get(url_1d, headers=headers, timeout=5).json()
            if not res_1d.get('chart', {}).get('result'): continue 
            
            res_1d_data = res_1d['chart']['result'][0]
            idx_1d = pd.to_datetime(res_1d_data['timestamp'], unit='s', utc=True)
            quote_1d = res_1d_data['indicators']['quote'][0]
            df_daily = pd.DataFrame({
                'Open': quote_1d['open'], 'High': quote_1d['high'],
                'Low': quote_1d['low'], 'Close': quote_1d['close'], 'Volume': quote_1d['volume']
            }, index=idx_1d).dropna()
            
            delta = df_daily['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df_daily['RSI'] = 100 - (100 / (1 + rs))

            ma20_15k = None
            if not is_us:
                url_15m = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=15m&range=5d"
                res_15m = requests.get(url_15m, headers=headers, timeout=5).json()
                res_15m_data = res_15m['chart']['result'][0]
                idx_15m = pd.to_datetime(res_15m_data['timestamp'], unit='s', utc=True)
                df_15m = pd.DataFrame({'Close': res_15m_data['indicators']['quote'][0]['close']}, index=idx_15m).dropna()
                ma20_15k = df_15m['Close'].tail(20).mean() if len(df_15m) >= 20 else df_15m['Close'].mean()

            return df_daily, ma20_15k, suffix
        except:
            continue
    return pd.DataFrame(), None, ""

def get_realtime_tick(code, suffix):
    if suffix is None: return pd.DataFrame()
    headers = {"User-Agent": "Mozilla/5.0"}
    url_1m = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1m&range=1d"
    try:
        res_1m = requests.get(url_1m, headers=headers, timeout=3).json()
        res_1m_data = res_1m['chart']['result'][0]
        idx_1m = pd.to_datetime(res_1m_data['timestamp'], unit='s', utc=True)
        quote_1m = res_1m_data['indicators']['quote'][0]
        return pd.DataFrame({
            'Open': quote_1m['open'], 'High': quote_1m['high'],
            'Low': quote_1m['low'], 'Close': quote_1m['close'], 'Volume': quote_1m['volume']
        }, index=idx_1m).dropna()
    except: return pd.DataFrame()

@st.cache_data(ttl=5)
def get_quick_quote(code, is_us=False):
    stock_db = get_full_stock_db()
    name = code if is_us else stock_db.get(code, code)
    headers = {"User-Agent": "Mozilla/5.0"}
    suffixes = [""] if is_us else [".TW", ".TWO"]
    for suffix in suffixes:
        try:
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range=5d"
            res = requests.get(url, headers=headers, timeout=2).json()
            if not res.get('chart', {}).get('result'): continue
            quotes = res['chart']['result'][0]['indicators']['quote'][0]['close']
            closes = [c for c in quotes if c is not None]
            if len(closes) < 2: continue
            return closes[-1], closes[-2], name
        except: continue
    return None, None, name

def get_advanced_ai_report():
    if not API_KEY: return {"error": "⚠️ 請先設定 API Key"}
    tw_tz = pytz.timezone('Asia/Taipei')
    now = datetime.datetime.now(tw_tz)
    is_after_1230 = now.time() >= datetime.time(12, 30)
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # 🚀 升級提示詞：鎖定美股短波段分析，著重催化劑與技術突破
    prompt = f"""
    現在是台灣時間 {time_str}。你是頂尖跨國操盤手。
    請嚴格依照以下 JSON 格式回傳一份實戰選股報告。
    
    【絕對限制】：
    1. 台股推薦價格必須在 150 元以下。美股則無價格限制。
    2. 每一個類別，精準提供 5 檔股票。各分類間名單絕對互斥不重複。
    3. 必須在 strategy 填寫判斷基準。
       - 台股當沖：必須找近期高震幅(>5%)的熱門活躍股。
       - 美股短波分析：請著重於「近期具有催化劑(財報/消息)」或「技術面即將突破/創高」的強勢股。

    JSON 格式如下：
    {{
      "美股短波分析": [ 5筆資料 (純美股代碼如 NVDA, TSLA) ],
      "資金熱點TOP5": [ 5筆台股資料 ],
      "台股當沖作多": [ 5筆台股資料 ],
      "台股當沖作空": [ 5筆台股資料 ]
    }}
    (物件格式：{{"code": "代碼", "name": "名稱", "price": "建議價位", "strategy": "判斷基準", "reason": "理由"}})
    """
    try:
        response = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
        match = re.search(r'\{.*\}', response, re.DOTALL)
        return json.loads(match.group(0) if match else response)
    except Exception as e: return {"error": f"AI 產出錯誤: {e}"}

@st.cache_data(ttl=86400)
def get_correlated_stocks(code, name, is_us=False):
    if not API_KEY: return []
    market = "美股" if is_us else "台股"
    prompt = f"針對 {market} {name}({code})，找出 3 檔同產業高連動股票。第一檔須為絕對龍頭。只回傳純代碼，用逗號分隔。"
    try:
        res = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
        return [c.strip() for c in res.split(',') if c.strip() != ''][:3]
    except: return []

# --- 3. 網頁介面 ---
st.title("⚡ AI 跨海智能戰情室")

if 'tw_stocks' not in st.session_state: st.session_state.tw_stocks = []
if 'us_stocks' not in st.session_state: st.session_state.us_stocks = []
if 'logs' not in st.session_state: st.session_state.logs = []
if 'core_assets' not in st.session_state: 
    st.session_state.core_assets = [
        {"code": "0050", "is_us": False}, 
        {"code": "009816", "is_us": False},
        {"code": "QQQM", "is_us": True}
    ]

all_stocks = get_full_stock_db()
market_temp = get_market_temp()

col_t1, col_t2, col_t3 = st.columns(3)
with col_t1:
    if '台股加權' in market_temp:
        val, pct = market_temp['台股加權']
        st.metric("🇹🇼 台股大盤溫度", f"{val:.2f}", f"{pct:.2f}%", delta_color="normal" if pct > 0 else "inverse")
with col_t2:
    if '那斯達克' in market_temp:
        val, pct = market_temp['那斯達克']
        st.metric("🇺🇸 科技股溫度 (Nasdaq)", f"{val:.2f}", f"{pct:.2f}%", delta_color="normal" if pct > 0 else "inverse")
with col_t3:
    tw_pct = market_temp.get('台股加權', (0,0))[1]
    if tw_pct < -1.5:
        st.error("🚨 警告：今日大盤重挫逆風，當沖請縮小部位，嚴控風險！")
    elif tw_pct > 1.0:
        st.success("🔥 大盤順風：多方動能強勁，可積極尋找突破口。")
    else:
        st.info("⚖️ 大盤震盪：請密切關注族群輪動與個股籌碼。")

st.divider()

with st.sidebar:
    st.header("⚙️ 實戰監控設定")
    auto_refresh = st.checkbox("⚡ 開啟台股極速自動更新 (3秒)", value=False)
    
    st.divider()
    st.header("🤖 AI 獨家選股報告")
    if st.button("🚀 立即生成全盤選股報告", use_container_width=True, type="primary"):
        st.session_state.ai_report = "loading"
        st.rerun()
        
    st.divider()
    st.header("🎯 台股當沖監控加入")
    stock_list = [f"{code} {name}" for code, name in all_stocks.items()]
    selected_tw = st.selectbox("🔍 搜尋台股代碼", options=["請點此搜尋..."] + stock_list, index=0)
    if st.button("➕ 加入台股"):
        if selected_tw and selected_tw != "請點此搜尋...":
            code = selected_tw.split(" ")[0]
            name = " ".join(selected_tw.split(" ")[1:])
            if code not in [s['code'] for s in st.session_state.tw_stocks]:
                st.session_state.tw_stocks.append({"code": code, "name": name})
                st.rerun()

    st.header("🦅 美股波段監控加入")
    us_code = st.text_input("🇺🇸 輸入美股代碼 (如 NVDA, TSLA)").strip().upper()
    if st.button("➕ 加入美股"):
        if us_code and us_code not in [s['code'] for s in st.session_state.us_stocks]:
            st.session_state.us_stocks.append({"code": us_code, "name": us_code})
            st.rerun()
            
    if st.button("🗑️ 清空所有自選與日誌"):
        st.session_state.tw_stocks = []
        st.session_state.us_stocks = []
        st.session_state.logs = [] 
        st.session_state.pop('core_assets', None)
        st.rerun()

if getattr(st.session_state, 'ai_report', None) == "loading":
    st.subheader("🤖 AI 正在深度運算跨國 TOP 5 精選清單...")
    with st.spinner('建立多空互斥防線，掃描全球資金動向...'):
        st.session_state.ai_report = get_advanced_ai_report()
    st.rerun()
elif getattr(st.session_state, 'ai_report', None):
    report_data = st.session_state.ai_report
    with st.container(border=True):
        st.subheader("🤖 AI 跨海精選清單 (點擊看詳細分析)")
        if "error" in report_data: st.error(report_data["error"])
        else:
            tabs = st.tabs(list(report_data.keys()))
            for i, (category, stocks) in enumerate(report_data.items()):
                with tabs[i]:
                    if not stocks: st.info("無符合條件標的。")
                    else:
                        for stock in stocks:
                            display_title = f"🎯 {stock.get('name', '')}({stock.get('code', '')}) | 參考價：{stock.get('price', '--')} | {stock.get('strategy', '')}"
                            with st.expander(display_title):
                                st.write(f"**詳細分析**：\n{stock.get('reason', '')}")
                                # 自動判定是否為美股清單，讓加入按鈕送到正確的頁籤
                                is_us_cat = "美股" in category
                                if 'code' in stock and st.button(f"➕ 加入看板", key=f"add_{category}_{stock['code']}"):
                                    target_list = st.session_state.us_stocks if is_us_cat else st.session_state.tw_stocks
                                    if stock['code'] not in [s['code'] for s in target_list]:
                                        target_list.append({"code": stock['code'], "name": stock.get('name', stock['code'])})
                                        st.rerun()
        if st.button("✖️ 關閉報告"):
            st.session_state.ai_report = None
            st.rerun()

tab_tw, tab_us, tab_core = st.tabs(["🇹🇼 台股極速當沖", "🇺🇸 美股波段戰情", "🐢 10年期核心長線 (20萬本金計畫)"])

# ====================
# 戰區 1：台股極速當沖
# ====================
with tab_tw:
    if not st.session_state.tw_stocks: st.info("請於左側加入台股。")
    for stock in st.session_state.tw_stocks:
        code, name = stock['code'], stock['name']
        df_daily, ma20_15k, suffix = get_historical_features(code, is_us=False)
        df_1m = get_realtime_tick(code, suffix)
        
        if not df_1m.empty and ma20_15k is not None and not df_daily.empty:
            curr_p = df_1m['Close'].iloc[-1]
            prev_p = df_daily['Close'].iloc[-2] if len(df_daily) > 1 else curr_p
            high_p, low_p = df_1m['High'].max(), df_1m['Low'].min()
            
            strategies = []
            if len(df_daily) >= 20:
                c_today, o_today, h_today = curr_p, df_daily['Open'].iloc[-1], df_daily['High'].iloc[-1]
                c_yest, h_yest = df_daily['Close'].iloc[-2], df_daily['High'].iloc[-2]
                ma5, ma20 = df_daily['Close'].tail(5).mean(), df_daily['Close'].tail(20).mean()
                if c_today > ma5 > ma20: strategies.append("🌈 多頭排列")
                if o_today > h_yest: strategies.append("🚀 強勢跳空")

            vol_15m = df_1m['Volume'].resample('15min').sum().dropna()
            if len(vol_15m) > 0:
                for ts, vol in vol_15m.items():
                    if vol > vol_15m.mean() * 2.5 and vol > 200:
                        msg = f"[{ts.strftime('%H:%M')}] 🔥 {name}({code}) | 15K爆量: {int(vol)}張"
                        if msg not in [l['msg'] for l in st.session_state.logs]: st.session_state.logs.append({"time": ts.strftime('%H:%M'), "msg": msg})
            
            vwap = ( (df_1m['High'] + df_1m['Low'] + df_1m['Close'])/3 * df_1m['Volume'] ).sum() / (df_1m['Volume'].sum() + 0.001)
            
            corr_codes = get_correlated_stocks(code, name, is_us=False)
            corr_displays = []
            for idx, c_code in enumerate(corr_codes):
                c_curr, c_prev, c_name = get_quick_quote(c_code, is_us=False)
                if c_curr is not None and c_prev is not None and c_prev > 0:
                    pct = ((c_curr - c_prev) / c_prev) * 100
                    color = "red" if pct > 0 else "green" if pct < 0 else "gray"
                    sign = "+" if pct > 0 else ""
                    prefix = "👑 " if idx == 0 else "🔗 "
                    corr_displays.append(f"{prefix}{c_name}: :{color}[**{c_curr:.2f} ({sign}{pct:.2f}%)**]")
                else:
                    corr_displays.append(f"🔗 {c_code}: 載入中")
            corr_str = " ｜ ".join(corr_displays) if corr_displays else ""

            with st.container(border=True):
                st.markdown(f"#### {name}({code}) ✨ 型態: **{','.join(strategies) if strategies else '觀察中'}**")
                
                if corr_str: st.markdown(f"**族群跟漲指標**：{corr_str}")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("現價", f"{curr_p:.2f}", f"{curr_p - prev_p:.2f}")
                c2.metric("當日VWAP", f"{vwap:.2f}")
                c3.metric("15K 20MA", f"{ma20_15k:.2f}")

    if st.session_state.logs:
        st.subheader("🔔 台股帶量異常歷史紀錄")
        st.text_area("今日爆量軌跡", value="\n\n".join([l['msg'] for l in sorted(st.session_state.logs, key=lambda x: x['time'], reverse=True)]), height=150)

# ====================
# 戰區 2：美股波段戰情
# ====================
with tab_us:
    if not st.session_state.us_stocks: st.info("請於左側加入美股 (波段監控看重日K與均線，無須秒級跳動)。")
    for stock in st.session_state.us_stocks:
        code = stock['code']
        df_daily, _, _ = get_historical_features(code, is_us=True)
        
        if not df_daily.empty:
            curr_p = df_daily['Close'].iloc[-1]
            prev_p = df_daily['Close'].iloc[-2] if len(df_daily) > 1 else curr_p
            ma10, ma20 = df_daily['Close'].tail(10).mean(), df_daily['Close'].tail(20).mean()
            rsi = df_daily['RSI'].iloc[-1]
            
            corr_codes = get_correlated_stocks(code, code, is_us=True)
            corr_displays = []
            for idx, c_code in enumerate(corr_codes):
                c_curr, c_prev, c_name = get_quick_quote(c_code, is_us=True)
                if c_curr is not None and c_prev is not None and c_prev > 0:
                    pct = ((c_curr - c_prev) / c_prev) * 100
                    color = "red" if pct > 0 else "green" if pct < 0 else "gray"
                    sign = "+" if pct > 0 else ""
                    prefix = "👑 " if idx == 0 else "🔗 "
                    corr_displays.append(f"{prefix}{c_name}: :{color}[**${c_curr:.2f} ({sign}{pct:.2f}%)**]")
                else:
                    corr_displays.append(f"🔗 {c_code}: 載入中")
            corr_str = " ｜ ".join(corr_displays) if corr_displays else ""

            with st.container(border=True):
                st.markdown(f"#### 🦅 {code} (美股)")
                
                if corr_str: st.markdown(f"**美股連動指標**：{corr_str}")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("收盤現價", f"${curr_p:.2f}", f"${curr_p - prev_p:.2f}")
                c2.metric("波段月線 (20MA)", f"${ma20:.2f}")
                
                rsi_col = "red" if rsi > 70 else "green" if rsi < 30 else "normal"
                c3.metric("RSI (超買/超賣)", f"{rsi:.1f}", delta_color="off")
                
                if st.button(f"🤖 呼叫 AI 分析 {code} 華爾街動向", key=f"us_ai_{code}"):
                    with st.spinner("調閱華爾街法人報告..."):
                        res = ai_model.generate_content(f"請分析美股 {code} 近期產業動態、華爾街機構看法，並給出波段進場建議，100字內。").text
                        st.success(res)

# ====================
# 戰區 3：10年核心資產
# ====================
with tab_core:
    st.markdown("### 🐢 穩健增長：20萬 TWD 核心配置計畫 (10年以上視野)")
    st.info("💡 長線投資心法：不看 1 分 K，不理會短線震盪。只要價格低於 60MA (季線) 或 RSI 進入超賣區 (<40)，就是啟動 20 萬本金分批佈局的甜甜價。")
    
    for asset in st.session_state.core_assets:
        code, is_us = asset['code'], asset['is_us']
        df_daily, _, _ = get_historical_features(code, is_us=is_us)
        
        if not df_daily.empty:
            curr_p = df_daily['Close'].iloc[-1]
            ma60 = df_daily['Close'].tail(60).mean() if len(df_daily)>=60 else curr_p
            ma200 = df_daily['Close'].tail(200).mean() if len(df_daily)>=200 else curr_p
            rsi = df_daily['RSI'].iloc[-1]
            
            signal = "⏳ 定期定額持倉"
            s_color = "gray"
            if curr_p < ma60 and rsi < 40:
                signal = "🎯 罕見超跌！啟動 20 萬資金加碼"
                s_color = "red"
            elif curr_p > ma60 * 1.2:
                signal = "🔥 乖離過大，暫停單筆買進"
                s_color = "orange"

            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([1.5, 1, 1, 1.5])
                icon = "🇺🇸" if is_us else "🇹🇼"
                c1.markdown(f"**{icon} {code}**\n\n現價: {curr_p:.2f}")
                c2.metric("季線 (60MA)", f"{ma60:.2f}")
                c3.metric("年線 (200MA)", f"{ma200:.2f}")
                c4.markdown(f"**佈局燈號**\n\n:{s_color}[{signal}] (RSI: {rsi:.1f})")

# 引擎循環控制
if auto_refresh:
    time.sleep(3) 
    st.rerun()
