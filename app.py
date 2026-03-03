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

# --- 基礎設定 ---
st.set_page_config(page_title="AI 智能監控戰情室", layout="wide", initial_sidebar_state="expanded")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. 引擎設定 (AI 與 Telegram) ---
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if API_KEY:
    genai.configure(api_key=API_KEY)
    ai_model = genai.GenerativeModel('gemini-2.5-flash')

TG_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

def send_telegram_alert(msg):
    if not TG_BOT_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg}, timeout=2)
    except: pass

# --- 💾 永久記憶資料庫系統 ---
DATA_FILE = "watchlist_data.json"

def load_watchlist():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding='utf-8') as f: return json.load(f)
        except: pass
    return {"tw": [], "us": []}

def save_watchlist(tw, us):
    try:
        with open(DATA_FILE, "w", encoding='utf-8') as f: json.dump({"tw": tw, "us": us}, f, ensure_ascii=False)
    except: pass

# --- 🚀 防彈按鈕 Callback 函數 ---
def cb_add_tw(code, name, target_price=0.0, condition=">="):
    if code and code not in [s['code'] for s in st.session_state.tw_stocks]:
        st.session_state.tw_stocks.append({"code": code, "name": name, "target_price": float(target_price), "condition": condition, "alert_triggered": False})
        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

def cb_add_us(code, name, target_price=0.0, condition=">="):
    if code and code not in [s['code'] for s in st.session_state.us_stocks]:
        st.session_state.us_stocks.append({"code": code, "name": name, "target_price": float(target_price), "condition": condition, "alert_triggered": False})
        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

def cb_remove_tw(idx):
    st.session_state.tw_stocks.pop(idx)
    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

def cb_remove_us(idx):
    st.session_state.us_stocks.pop(idx)
    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

def cb_clear_all():
    st.session_state.tw_stocks = []
    st.session_state.us_stocks = []
    st.session_state.logs = []
    save_watchlist([], [])

if 'initialized' not in st.session_state:
    data = load_watchlist()
    st.session_state.tw_stocks = data.get("tw", [])
    st.session_state.us_stocks = data.get("us", [])
    st.session_state.logs = []
    st.session_state.core_assets = [{"code": "0050", "is_us": False}, {"code": "009816", "is_us": False}, {"code": "QQQM", "is_us": True}]
    st.session_state.initialized = True

# --- 2. 核心數據引擎 ---
@st.cache_data(ttl=86400)
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
            if len(closes) >= 2: results[name] = (closes[-1], ((closes[-1] - closes[-2]) / closes[-2]) * 100)
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
            df_daily = pd.DataFrame({
                'Open': res_1d_data['indicators']['quote'][0]['open'], 'High': res_1d_data['indicators']['quote'][0]['high'],
                'Low': res_1d_data['indicators']['quote'][0]['low'], 'Close': res_1d_data['indicators']['quote'][0]['close'], 'Volume': res_1d_data['indicators']['quote'][0]['volume']
            }, index=idx_1d).dropna()
            
            delta = df_daily['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            df_daily['RSI'] = 100 - (100 / (1 + gain / (loss + 1e-9)))

            ma20_15k = None
            if not is_us:
                url_15m = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=15m&range=5d"
                res_15m = requests.get(url_15m, headers=headers, timeout=5).json()
                idx_15m = pd.to_datetime(res_15m['chart']['result'][0]['timestamp'], unit='s', utc=True)
                df_15m = pd.DataFrame({'Close': res_15m['chart']['result'][0]['indicators']['quote'][0]['close']}, index=idx_15m).dropna()
                ma20_15k = df_15m['Close'].tail(20).mean() if len(df_15m) >= 20 else df_15m['Close'].mean()

            return df_daily, ma20_15k, suffix
        except: continue
    return pd.DataFrame(), None, ""

def get_realtime_tick(code, suffix):
    if suffix is None: return pd.DataFrame()
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res_1m = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1m&range=1d", headers=headers, timeout=3).json()
        idx_1m = pd.to_datetime(res_1m['chart']['result'][0]['timestamp'], unit='s', utc=True)
        q = res_1m['chart']['result'][0]['indicators']['quote'][0]
        return pd.DataFrame({'Open': q['open'], 'High': q['high'], 'Low': q['low'], 'Close': q['close'], 'Volume': q['volume']}, index=idx_1m).dropna()
    except: return pd.DataFrame()

@st.cache_data(ttl=5)
def get_quick_quote(code, is_us=False):
    stock_db = get_full_stock_db()
    name = code if is_us else stock_db.get(code, code)
    headers = {"User-Agent": "Mozilla/5.0"}
    suffixes = [""] if is_us else [".TW", ".TWO"]
    for suffix in suffixes:
        try:
            res = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range=5d", headers=headers, timeout=2).json()
            closes = [c for c in res['chart']['result'][0]['indicators']['quote'][0]['close'] if c is not None]
            if len(closes) >= 2: return closes[-1], closes[-2], name
        except: continue
    return None, None, name

# --- 🚀 報告分流：當沖專屬報告 ---
def get_ai_daytrade_report():
    if not API_KEY: return {"error": "⚠️ 請設定 API Key"}
    now = datetime.datetime.now(pytz.timezone('Asia/Taipei')).strftime("%Y-%m-%d %H:%M:%S")
    prompt = f"""時間 {now}。你是台股當沖高手。請提供實戰名單。要求：1. 限150元以下。2. 各類別5檔不重複。3. 找近期高震幅活躍股。
    JSON: {{ "台股當沖作多": [], "台股當沖作空": [] }} 
    (格式：{{"code": "代碼", "name": "名稱", "strategy": "判斷基準(如爆量、均線)", "reason": "理由"}})"""
    try:
        response = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
        match = re.search(r'\{.*\}', response, re.DOTALL)
        data = json.loads(match.group(0) if match else response)
        
        # 🚀 Python 即時報價校正引擎 (消滅 AI 幻覺價格)
        for cat, stocks in data.items():
            for s in stocks:
                c_p, _, _ = get_quick_quote(s['code'], False)
                if c_p:
                    s['curr_p'] = c_p
                    # 當沖合規價格推算：作多抓現價 +1.5%，作空抓現價 -1.5%
                    s['price'] = round(c_p * 1.015, 2) if "多" in cat else round(c_p * 0.985, 2)
                else:
                    s['curr_p'] = "未知"
                    s['price'] = 0.0
        return data
    except Exception as e: return {"error": f"API 錯誤: {e}"}

# --- 🚀 報告分流：波段熱點專屬報告 ---
def get_ai_swing_report():
    if not API_KEY: return {"error": "⚠️ 請設定 API Key"}
    now = datetime.datetime.now(pytz.timezone('Asia/Taipei')).strftime("%Y-%m-%d %H:%M:%S")
    prompt = f"""時間 {now}。你是跨國波段操盤手。請提供實戰名單。要求：台股限150元以下。各類別5檔不重複。
    JSON: {{ "美股短波分析": [美股代碼], "資金熱點TOP5": [台股代碼] }} 
    (格式：{{"code": "代碼", "name": "名稱", "strategy": "判斷基準", "reason": "理由"}})"""
    try:
        response = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
        match = re.search(r'\{.*\}', response, re.DOTALL)
        data = json.loads(match.group(0) if match else response)
        
        # 🚀 Python 即時報價校正引擎
        for cat, stocks in data.items():
            is_us = "美股" in cat
            for s in stocks:
                c_p, _, _ = get_quick_quote(s['code'], is_us)
                if c_p:
                    s['curr_p'] = c_p
                    # 波段合規價格推算：抓現價 +5% 作為停利參考
                    s['price'] = round(c_p * 1.05, 2)
                else:
                    s['curr_p'] = "未知"
                    s['price'] = 0.0
        return data
    except Exception as e: return {"error": f"API 錯誤: {e}"}

@st.cache_data(ttl=86400)
def get_correlated_stocks(code, name, is_us=False):
    if not API_KEY: return []
    market = "美股" if is_us else "台股"
    try:
        res = ai_model.generate_content(f"針對 {market} {name}({code})，找出 3 檔同產業高連動股票。第一檔須為絕對龍頭。回傳純代碼逗號分隔。", generation_config=genai.types.GenerationConfig(temperature=0.0)).text
        return [c.strip() for c in res.split(',') if c.strip() != ''][:3]
    except: return []

def extract_price(price_str):
    match = re.search(r'\d+(\.\d+)?', str(price_str))
    return float(match.group()) if match else 0.0

# --- 3. 網頁介面 ---
st.title("⚡ AI 跨海智能戰情室")

all_stocks = get_full_stock_db()
market_temp = get_market_temp()

col_t1, col_t2, col_t3 = st.columns(3)
with col_t1:
    if '台股加權' in market_temp:
        st.metric("🇹🇼 台股大盤溫度", f"{market_temp['台股加權'][0]:.2f}", f"{market_temp['台股加權'][1]:.2f}%", delta_color="normal" if market_temp['台股加權'][1] > 0 else "inverse")
with col_t2:
    if '那斯達克' in market_temp:
        st.metric("🇺🇸 科技股溫度 (Nasdaq)", f"{market_temp['那斯達克'][0]:.2f}", f"{market_temp['那斯達克'][1]:.2f}%", delta_color="normal" if market_temp['那斯達克'][1] > 0 else "inverse")
with col_t3:
    tw_pct = market_temp.get('台股加權', (0,0))[1]
    if tw_pct < -1.5: st.error("🚨 大盤重挫，當沖嚴控風險！")
    elif tw_pct > 1.0: st.success("🔥 大盤順風：多方動能強勁。")
    else: st.info("⚖️ 大盤震盪：關注族群輪動。")

st.divider()

with st.sidebar:
    st.header("⚙️ 實戰監控設定")
    auto_refresh = st.checkbox("⚡ 開啟極速自動更新 (3秒)", value=False)
    st.divider()
    
    if TG_BOT_TOKEN and TG_CHAT_ID: st.success("📱 Telegram 推播已啟用")
    else: st.warning("📱 尚未設定 Telegram (設定 st.secrets 即可啟用)")

    # 🚀 報告分流按鈕
    st.divider()
    st.header("🤖 AI 獨家選股報告")
    if st.button("🚀 生成【當沖短線】報告", use_container_width=True, type="primary"):
        st.session_state.ai_report_data = "loading_dt"
        st.rerun()
    if st.button("🦅 生成【波段熱點】報告", use_container_width=True):
        st.session_state.ai_report_data = "loading_swing"
        st.rerun()
        
    st.divider()
    st.header("🎯 自訂監控加入")
    stock_list = [f"{code} {name}" for code, name in all_stocks.items()]
    selected_tw = st.selectbox("🔍 搜尋台股代碼", options=["請點此搜尋..."] + stock_list, index=0)
    # 🚀 使用 Callback 防彈寫法
    if selected_tw != "請點此搜尋...":
        code = selected_tw.split(" ")[0]
        name = " ".join(selected_tw.split(" ")[1:])
        st.button(f"➕ 加入 {name} (台股)", on_click=cb_add_tw, args=(code, name))

    us_code = st.text_input("🇺🇸 輸入美股代碼 (如 NVDA)").strip().upper()
    if us_code:
        st.button(f"➕ 加入 {us_code} (美股)", on_click=cb_add_us, args=(us_code, us_code))
            
    st.divider()
    st.button("🗑️ 徹底清空所有資料", on_click=cb_clear_all, type="secondary")

# --- 顯示 AI 報告區域 ---
report_state = getattr(st.session_state, 'ai_report_data', None)
if report_state == "loading_dt":
    with st.spinner('掃描盤面高波動活躍股，計算合理當沖目標價...'):
        st.session_state.ai_report_data = get_ai_daytrade_report()
    st.rerun()
elif report_state == "loading_swing":
    with st.spinner('調閱跨國產業資金流向，計算波段滿足點...'):
        st.session_state.ai_report_data = get_ai_swing_report()
    st.rerun()
elif isinstance(report_state, dict):
    with st.container(border=True):
        st.subheader("🤖 AI 精選清單 (已校正即時股價)")
        if "error" in report_state: st.error(report_state["error"])
        else:
            tabs = st.tabs(list(report_state.keys()))
            for i, (category, stocks) in enumerate(report_state.items()):
                with tabs[i]:
                    for stock in stocks:
                        c_p = stock.get('curr_p', '--')
                        t_p = stock.get('price', 0.0)
                        display_title = f"🎯 {stock.get('name', '')}({stock.get('code', '')}) | 現價：{c_p} | 推算目標價：{t_p}"
                        with st.expander(display_title):
                            st.write(f"**策略理由**：{stock.get('strategy', '')}")
                            st.write(f"**詳細分析**：{stock.get('reason', '')}")
                            
                            # 🚀 使用 Callback 防彈帶入價格
                            cond = "<=" if "空" in category else ">="
                            is_us_cat = "美股" in category
                            btn_text = f"➕ 帶入目標價 {t_p} 且監控 {'跌破' if cond=='<=' else '漲破'}"
                            if is_us_cat:
                                st.button(btn_text, key=f"add_u_{stock['code']}", on_click=cb_add_us, args=(stock['code'], stock.get('name', stock['code']), t_p, cond))
                            else:
                                st.button(btn_text, key=f"add_t_{stock['code']}", on_click=cb_add_tw, args=(stock['code'], stock.get('name', stock['code']), t_p, cond))

tab_tw, tab_us, tab_core = st.tabs(["🇹🇼 台股極速當沖", "🇺🇸 美股波段戰情", "🐢 10年期核心長線"])

# ====================
# 戰區 1：台股極速當沖
# ====================
with tab_tw:
    if not st.session_state.tw_stocks: st.info("請加入台股。")
    for idx, stock in enumerate(st.session_state.tw_stocks):
        code, name = stock['code'], stock['name']
        t_price = stock.get('target_price', 0.0)
        cond = stock.get('condition', '>=') 
        
        df_daily, ma20_15k, suffix = get_historical_features(code, is_us=False)
        df_1m = get_realtime_tick(code, suffix)
        
        if not df_1m.empty and ma20_15k is not None and not df_daily.empty:
            curr_p = df_1m['Close'].iloc[-1]
            prev_p = df_daily['Close'].iloc[-2] if len(df_daily) > 1 else curr_p
            vwap = ( (df_1m['High'] + df_1m['Low'] + df_1m['Close'])/3 * df_1m['Volume'] ).sum() / (df_1m['Volume'].sum() + 0.001)
            
            is_alert = False
            if t_price > 0:
                if cond == ">=" and curr_p >= t_price:
                    is_alert = True
                    if not stock.get('alert_triggered', False):
                        send_telegram_alert(f"📈 🚨【台股作多/停損】\n{name}({code}) 已『漲破』目標價！\n現價：{curr_p}\n警示價：{t_price}")
                        st.session_state.tw_stocks[idx]['alert_triggered'] = True
                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                elif cond == "<=" and curr_p <= t_price:
                    is_alert = True
                    if not stock.get('alert_triggered', False):
                        send_telegram_alert(f"📉 🚨【台股作空/停損】\n{name}({code}) 已『跌穿』目標價！\n現價：{curr_p}\n警示價：{t_price}")
                        st.session_state.tw_stocks[idx]['alert_triggered'] = True
                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                # 脫離警戒區重置
                if cond == ">=" and curr_p < t_price * 0.995: st.session_state.tw_stocks[idx]['alert_triggered'] = False
                if cond == "<=" and curr_p > t_price * 1.005: st.session_state.tw_stocks[idx]['alert_triggered'] = False

            with st.container(border=True):
                c_title, c_del = st.columns([5, 1])
                with c_title: st.markdown(f"#### {name}({code})")
                with c_del:
                    # 🚀 Callback 單獨刪除
                    st.button("❌ 移除", key=f"del_tw_{code}", on_click=cb_remove_tw, args=(idx,))

                if is_alert:
                    st.error(f"🚨 **到價警示！** 現價 {curr_p} 已觸發 {cond} 目標 {t_price}")
                
                c_cond, c_inp, c_ai = st.columns([1.5, 2, 1])
                with c_cond:
                    new_cond = st.selectbox("方向", [">= 漲破", "<= 跌破"], index=0 if cond == ">=" else 1, key=f"cond_tw_{code}")
                    new_cond_val = ">=" if ">=" in new_cond else "<="
                    if new_cond_val != cond:
                        st.session_state.tw_stocks[idx]['condition'] = new_cond_val
                        st.session_state.tw_stocks[idx]['alert_triggered'] = False
                        st.rerun()
                with c_inp:
                    new_t_price = st.number_input(f"警示價", value=float(t_price), step=0.5, key=f"inp_{code}")
                    if new_t_price != t_price:
                        st.session_state.tw_stocks[idx]['target_price'] = new_t_price
                        st.session_state.tw_stocks[idx]['alert_triggered'] = False
                        st.rerun()
                with c_ai:
                    st.write("") 
                    if API_KEY and st.button("🤖 算價", key=f"ai_p_{code}"):
                        with st.spinner("..."):
                            try:
                                res = ai_model.generate_content(f"台股 {name} 現價 {curr_p}，請給當沖{'作多' if cond=='>=' else '作空'}停利目標價，只回傳數字。").text
                                p_match = extract_price(res)
                                if p_match > 0:
                                    st.session_state.tw_stocks[idx]['target_price'] = p_match
                                    st.session_state.tw_stocks[idx]['alert_triggered'] = False
                                    st.rerun()
                            except: pass

                c1, c2, c3 = st.columns(3)
                c1.metric("現價", f"{curr_p:.2f}", f"{curr_p - prev_p:.2f}")
                c2.metric("當日VWAP", f"{vwap:.2f}")
                c3.metric("15K 20MA", f"{ma20_15k:.2f}")

# ====================
# 戰區 2：美股波段戰情
# ====================
with tab_us:
    if not st.session_state.us_stocks: st.info("請加入美股。")
    for idx, stock in enumerate(st.session_state.us_stocks):
        code = stock['code']
        t_price = stock.get('target_price', 0.0)
        cond = stock.get('condition', '>=')
        df_daily, _, _ = get_historical_features(code, is_us=True)
        
        if not df_daily.empty:
            curr_p = df_daily['Close'].iloc[-1]
            prev_p = df_daily['Close'].iloc[-2] if len(df_daily) > 1 else curr_p
            
            is_alert = False
            if t_price > 0:
                if cond == ">=" and curr_p >= t_price:
                    is_alert = True
                    if not stock.get('alert_triggered', False):
                        send_telegram_alert(f"🦅 📈【美股作多】\n{code} 已漲破目標價！\n現價：${curr_p}\n警示價：${t_price}")
                        st.session_state.us_stocks[idx]['alert_triggered'] = True
                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                elif cond == "<=" and curr_p <= t_price:
                    is_alert = True
                    if not stock.get('alert_triggered', False):
                        send_telegram_alert(f"🦅 📉【美股作空/停損】\n{code} 已跌穿目標價！\n現價：${curr_p}\n警示價：${t_price}")
                        st.session_state.us_stocks[idx]['alert_triggered'] = True
                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                
                if cond == ">=" and curr_p < t_price * 0.995: st.session_state.us_stocks[idx]['alert_triggered'] = False
                if cond == "<=" and curr_p > t_price * 1.005: st.session_state.us_stocks[idx]['alert_triggered'] = False

            with st.container(border=True):
                c_title, c_del = st.columns([5, 1])
                with c_title: st.markdown(f"#### 🦅 {code} (美股)")
                with c_del:
                    st.button("❌ 移除", key=f"del_us_{code}", on_click=cb_remove_us, args=(idx,))

                if is_alert:
                    st.error(f"🚨 **到價警示！** {code} 已觸發：現價 ${curr_p} {cond} 目標 ${t_price}")
                
                c_cond, c_inp, c_ai = st.columns([1.5, 2, 1])
                with c_cond:
                    new_cond = st.selectbox("方向", [">= 漲破", "<= 跌破"], index=0 if cond == ">=" else 1, key=f"cond_us_{code}")
                    new_cond_val = ">=" if ">=" in new_cond else "<="
                    if new_cond_val != cond:
                        st.session_state.us_stocks[idx]['condition'] = new_cond_val
                        st.session_state.us_stocks[idx]['alert_triggered'] = False
                        st.rerun()
                with c_inp:
                    new_t_price = st.number_input(f"警示價", value=float(t_price), step=1.0, key=f"inp_us_{code}")
                    if new_t_price != t_price:
                        st.session_state.us_stocks[idx]['target_price'] = new_t_price
                        st.session_state.us_stocks[idx]['alert_triggered'] = False
                        st.rerun()
                with c_ai:
                    st.write("") 
                    if API_KEY and st.button("🤖 算價", key=f"ai_p_us_{code}"):
                        with st.spinner("..."):
                            try:
                                res = ai_model.generate_content(f"美股 {code} 現價 {curr_p}，請給波段{'作多' if cond=='>=' else '作空'}目標價，只回傳數字。").text
                                p_match = extract_price(res)
                                if p_match > 0:
                                    st.session_state.us_stocks[idx]['target_price'] = p_match
                                    st.session_state.us_stocks[idx]['alert_triggered'] = False
                                    st.rerun()
                            except: pass

                c1, c2, c3 = st.columns(3)
                c1.metric("收盤現價", f"${curr_p:.2f}", f"${curr_p - prev_p:.2f}")
                c2.metric("波段月線 (20MA)", f"${df_daily['Close'].tail(20).mean():.2f}")
                c3.metric("RSI", f"{df_daily['RSI'].iloc[-1]:.1f}", delta_color="off")

# ====================
# 戰區 3：10年核心資產
# ====================
with tab_core:
    st.markdown("### 🐢 穩健增長：20萬 TWD 核心配置計畫")
    for asset in st.session_state.core_assets:
        code, is_us = asset['code'], asset['is_us']
        df_daily, _, _ = get_historical_features(code, is_us=is_us)
        if not df_daily.empty:
            curr_p = df_daily['Close'].iloc[-1]
            with st.container(border=True):
                c1, c2, c3 = st.columns([1.5, 1.5, 1])
                c1.markdown(f"**{'🇺🇸' if is_us else '🇹🇼'} {code}** | 現價: {curr_p:.2f}")
                c2.metric("季線 (60MA)", f"{df_daily['Close'].tail(60).mean():.2f}")
                c3.metric("RSI", f"{df_daily['RSI'].iloc[-1]:.1f}")

if auto_refresh:
    time.sleep(3) 
    st.rerun()
