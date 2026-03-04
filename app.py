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
st.set_page_config(page_title="AI 跨海智能戰情室", layout="wide", initial_sidebar_state="expanded")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. 引擎設定 ---
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

# --- 💾 永久記憶資料庫 ---
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

# --- 🚀 防彈按鈕 Callbacks ---
def cb_add_tw(code, name, target_price=0.0, condition=">="):
    exists = False
    for s in st.session_state.tw_stocks:
        if s['code'] == code:
            exists = True
            s['alerts'].append({"type": "固定價格", "price": float(target_price), "cond": condition, "triggered": False, "touch_2_triggered": False})
            break
    if not exists:
        st.session_state.tw_stocks.append({
            "code": code, "name": name, 
            "alerts": [{"type": "固定價格", "price": float(target_price), "cond": condition, "triggered": False, "touch_2_triggered": False}], 
            "ai_advice": "", "vol_alert_triggered": False
        })
    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

def cb_add_us(code, name, target_price=0.0, condition=">="):
    exists = False
    for s in st.session_state.us_stocks:
        if s['code'] == code:
            exists = True
            s['alerts'].append({"type": "固定價格", "price": float(target_price), "cond": condition, "triggered": False, "touch_2_triggered": False})
            break
    if not exists:
        st.session_state.us_stocks.append({
            "code": code, "name": name, 
            "alerts": [{"type": "固定價格", "price": float(target_price), "cond": condition, "triggered": False, "touch_2_triggered": False}], 
            "ai_advice": ""
        })
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
    st.session_state.ai_report_dt = None
    st.session_state.ai_report_swing = None
    save_watchlist([], [])

# 初始化與舊資料向下相容升級
if 'initialized' not in st.session_state:
    data = load_watchlist()
    tw_data = data.get("tw", [])
    us_data = data.get("us", [])
    
    for s in tw_data:
        if 'alerts' not in s:
            s['alerts'] = [{"type": "固定價格", "price": s.get('target_price', 0.0), "cond": s.get('condition', '>='), "triggered": s.get('alert_triggered', False), "touch_2_triggered": False}]
        else:
            for al in s['alerts']:
                if 'touch_2_triggered' not in al: al['touch_2_triggered'] = False
                if 'type' not in al: al['type'] = "固定價格"
    for s in us_data:
        if 'alerts' not in s:
            s['alerts'] = [{"type": "固定價格", "price": s.get('target_price', 0.0), "cond": s.get('condition', '>='), "triggered": s.get('alert_triggered', False), "touch_2_triggered": False}]
        else:
            for al in s['alerts']:
                if 'touch_2_triggered' not in al: al['touch_2_triggered'] = False
                if 'type' not in al: al['type'] = "固定價格"

    st.session_state.tw_stocks = tw_data
    st.session_state.us_stocks = us_data
    st.session_state.ai_report_dt = None
    st.session_state.ai_report_swing = None
    st.session_state.core_assets = [{"code": "0050", "is_us": False}, {"code": "009816", "is_us": False}, {"code": "QQQM", "is_us": True}]
    
    if 'market_alert_flags' not in st.session_state:
        st.session_state.market_alert_flags = {}
        
    st.session_state.initialized = True

# --- 2. 數據引擎 ---
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
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{code}?interval=1d&range=2d&_t={int(time.time())}"
            res = requests.get(url, headers=headers, timeout=3).json()
            quotes = res['chart']['result'][0]['indicators']['quote'][0]['close']
            closes = [c for c in quotes if c is not None]
            if len(closes) >= 2: results[name] = (closes[-1], ((closes[-1] - closes[-2]) / closes[-2]) * 100)
        except: pass
    return results

@st.cache_data(ttl=300)
def get_index_mas(code='^TWII'):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{code}?interval=1d&range=6mo"
        res = requests.get(url, headers=headers, timeout=5).json()
        closes = res['chart']['result'][0]['indicators']['quote'][0]['close']
        df = pd.DataFrame({'Close': closes}).dropna()
        if len(df) >= 60:
            return {
                '3日線': df['Close'].tail(3).mean(),
                '5日線': df['Close'].tail(5).mean(),
                '月線(20MA)': df['Close'].tail(20).mean(),
                '季線(60MA)': df['Close'].tail(60).mean()
            }
    except: pass
    return None

@st.cache_data(show_spinner=False)
def get_kline_data(code, suffix, interval, time_key):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval={interval}&range=5d"
        res = requests.get(url, headers=headers, timeout=3).json()
        idx = pd.to_datetime(res['chart']['result'][0]['timestamp'], unit='s', utc=True)
        df = pd.DataFrame({'Close': res['chart']['result'][0]['indicators']['quote'][0]['close']}, index=idx).dropna()
        return df
    except: return pd.DataFrame()

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

            return df_daily, suffix
        except: continue
    return pd.DataFrame(), ""

def get_realtime_tick(code, suffix):
    if suffix is None: return pd.DataFrame()
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1m&range=1d&_t={int(time.time())}"
        res_1m = requests.get(url, headers=headers, timeout=3).json()
        idx_1m = pd.to_datetime(res_1m['chart']['result'][0]['timestamp'], unit='s', utc=True)
        q = res_1m['chart']['result'][0]['indicators']['quote'][0]
        return pd.DataFrame({'Open': q['open'], 'High': q['high'], 'Low': q['low'], 'Close': q['close'], 'Volume': q['volume']}, index=idx_1m).dropna()
    except: return pd.DataFrame()

def get_bulk_spark_prices(tw_codes, us_codes):
    symbols = []
    for c in tw_codes: symbols.extend([f"{c}.TW", f"{c}.TWO"])
    for c in us_codes: symbols.append(c)
    if not symbols: return {}
    
    prices = {}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    chunk_size = 15
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        sym_str = ",".join(chunk)
        try:
            url = f"https://query2.finance.yahoo.com/v8/finance/spark?symbols={sym_str}&range=1d&_t={int(time.time())}"
            res = requests.get(url, headers=headers, timeout=5).json()
            results = res.get('spark', {}).get('result', [])
            for r in results:
                sym = r.get('symbol', '')
                base_sym = sym.replace('.TW', '').replace('.TWO', '')
                resp_list = r.get('response', [])
                if resp_list:
                    meta = resp_list[0].get('meta', {})
                    curr_p = meta.get('regularMarketPrice')
                    prev_p = meta.get('chartPreviousClose', meta.get('previousClose', curr_p))
                    if curr_p is not None: prices[base_sym] = (curr_p, prev_p)
        except: pass
    return prices

@st.cache_data(ttl=3, show_spinner=False)
def get_single_live_price(code, is_us=False):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    suffixes = [""] if is_us else [".TW", ".TWO"]
    for suffix in suffixes:
        try:
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1m&range=2d&_t={int(time.time())//3}"
            res = requests.get(url, headers=headers, timeout=2).json()
            meta = res['chart']['result'][0]['meta']
            cp = meta.get('regularMarketPrice')
            pp = meta.get('chartPreviousClose', cp)
            if cp is not None: return cp, pp
        except: pass
    return None, None

@st.cache_data(ttl=43200)
def fetch_ai_list(report_type):
    if not API_KEY: return None
    now = datetime.datetime.now(pytz.timezone('Asia/Taipei')).strftime("%Y-%m-%d %H:%M")
    if report_type == "daytrade":
        prompt = f"時間 {now}。你是台股當沖高手。提供5檔作多、5檔作空標的。限150元以下。找尋高波動活躍股。JSON: {{ '台股當沖作多': [], '台股當沖作空': [] }} (格式：{{'code': '代碼', 'name': '名稱', 'strategy': '理由'}})"
    else:
        prompt = f"時間 {now}。你是跨國波段操盤手。提供5檔美股短波、5檔台股資金熱點。台股限150元以下。JSON: {{ '美股短波分析': [], '資金熱點TOP5': [] }} (格式：{{'code': '代碼', 'name': '名稱', 'strategy': '理由'}})"
    try:
        response = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
        match = re.search(r'\{.*\}', response, re.DOTALL)
        return json.loads(match.group(0))
    except: return None

@st.cache_data(ttl=86400)
def get_correlated_stocks(code, name, is_us=False):
    if not API_KEY: return []
    market = "美股" if is_us else "台股"
    try:
        prompt = f"針對 {market} {name}({code})，找出 3 檔同產業高連動股票。第一檔須為絕對龍頭。請絕對只回傳代碼，不要任何中文或說明文字。"
        res = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
        if is_us: codes = re.findall(r'[A-Z]+', res.upper())
        else: codes = re.findall(r'\d{4,}', res)
        seen = set(); uniq = []
        for c in codes:
            if c not in seen and c != code:
                seen.add(c); uniq.append(c)
        return uniq[:3]
    except: return []

# --- 3. 介面渲染 ---
st.title("⚡ AI 跨海智能戰情室")
all_stocks = get_full_stock_db()
market_temp = get_market_temp()

all_tw_to_fetch = set()
all_us_to_fetch = set()
for s in st.session_state.tw_stocks:
    all_tw_to_fetch.add(s['code'])
    all_tw_to_fetch.update(get_correlated_stocks(s['code'], s['name'], False))
for s in st.session_state.us_stocks:
    all_us_to_fetch.add(s['code'])
    all_us_to_fetch.update(get_correlated_stocks(s['code'], s['code'], True))

all_us_to_fetch.add('^TWII')
live_price_dict = get_bulk_spark_prices(list(all_tw_to_fetch), list(all_us_to_fetch))

now_tpe = datetime.datetime.now(pytz.timezone('Asia/Taipei'))
t5_key = f"{now_tpe.year}{now_tpe.month}{now_tpe.day}{now_tpe.hour}_{now_tpe.minute // 5}"
t15_key = f"{now_tpe.year}{now_tpe.month}{now_tpe.day}{now_tpe.hour}_{now_tpe.minute // 15}"

col_t1, col_t2, col_t3 = st.columns(3)
with col_t1:
    if '台股加權' in market_temp: st.metric("🇹🇼 台股大盤溫度", f"{market_temp['台股加權'][0]:.2f}", f"{market_temp['台股加權'][1]:.2f}%", delta_color="normal" if market_temp['台股加權'][1] > 0 else "inverse")
with col_t2:
    if '那斯達克' in market_temp: st.metric("🇺🇸 科技股溫度 (Nasdaq)", f"{market_temp['那斯達克'][0]:.2f}", f"{market_temp['那斯達克'][1]:.2f}%", delta_color="normal" if market_temp['那斯達克'][1] > 0 else "inverse")
with col_t3:
    if API_KEY: st.success(f"🟢 API 火力全開 | 最後跳動: {now_tpe.strftime('%H:%M:%S')}")
    else: st.error("🔴 API 未設定")

st.divider()

twii_mas = get_index_mas('^TWII')
twii_cp = live_price_dict.get('^TWII', (None, None))[0]
if twii_cp is None and '台股加權' in market_temp:
    twii_cp = market_temp['台股加權'][0]

if twii_cp and twii_mas:
    st.markdown(f"##### 📊 台股大盤關鍵均線雷達 (現價: **{twii_cp:.0f}**)")
    ma_cols = st.columns(4)
    threshold = 0.003
    alert_msgs = []
    
    for idx, (ma_name, ma_val) in enumerate(twii_mas.items()):
        dist_pts = twii_cp - ma_val
        dist_pct = dist_pts / ma_val
        
        if abs(dist_pct) <= threshold:
            if dist_pts > 0:
                ma_cols[idx].warning(f"**{ma_name}** `{ma_val:.0f}`\n\n⚠️ **回測警戒**：即將跌破，僅剩 **{dist_pts:.0f}** 點 ({dist_pct*100:+.2f}%)")
            else:
                ma_cols[idx].warning(f"**{ma_name}** `{ma_val:.0f}`\n\n🔥 **突破叩關**：即將突破，僅差 **{abs(dist_pts):.0f}** 點 ({dist_pct*100:+.2f}%)")
        else:
            if dist_pts > 0:
                ma_cols[idx].success(f"**{ma_name}** `{ma_val:.0f}`\n\n🛡️ **支撐防護**：距跌破還剩 **{dist_pts:.0f}** 點 ({dist_pct*100:+.2f}%)")
            else:
                ma_cols[idx].error(f"**{ma_name}** `{ma_val:.0f}`\n\n⚔️ **上檔壓力**：距突破還差 **{abs(dist_pts):.0f}** 點 ({dist_pct*100:+.2f}%)")
        
        state_key = f"twii_{ma_name}"
        if abs(dist_pct) <= threshold:
            if not st.session_state.market_alert_flags.get(state_key, False):
                if dist_pts > 0: msg = f"📉 大盤現價 {twii_cp:.0f}，即將向下回測 {ma_name} ({ma_val:.0f})！距離僅 {dist_pts:.0f} 點"
                else: msg = f"📈 大盤現價 {twii_cp:.0f}，即將向上挑戰 {ma_name} ({ma_val:.0f})！距離僅 {abs(dist_pts):.0f} 點"
                alert_msgs.append(msg)
                st.session_state.market_alert_flags[state_key] = True
        else:
            st.session_state.market_alert_flags[state_key] = False
            
    if alert_msgs:
        full_msg = "⚠️ 🚨【大盤關鍵均線警報】\n" + "\n".join(alert_msgs)
        send_telegram_alert(full_msg)
    
    st.divider()

with st.sidebar:
    st.header("🤖 選股報告分流")
    if st.button("🚀 生成【當沖短線】報告", use_container_width=True, type="primary"):
        st.session_state.ai_report_dt = fetch_ai_list("daytrade")
    if st.button("🦅 生成【波段熱點】報告", use_container_width=True):
        st.session_state.ai_report_swing = fetch_ai_list("swing")
    
    st.divider()
    st.header("🎯 自訂監控加入")
    stock_list = [f"{code} {name}" for code, name in all_stocks.items()]
    selected_tw = st.selectbox("🔍 搜尋台股代碼", options=["請點此搜尋..."] + stock_list, index=0)
    if selected_tw != "請點此搜尋...":
        code = selected_tw.split(" ")[0]; name = " ".join(selected_tw.split(" ")[1:])
        st.button(f"➕ 加入 {name} (台股)", on_click=cb_add_tw, args=(code, name))

    us_code = st.text_input("🇺🇸 輸入美股代碼 (如 NVDA)").strip().upper()
    if us_code: st.button(f"➕ 加入 {us_code} (美股)", on_click=cb_add_us, args=(us_code, us_code))
            
    st.divider()
    auto_refresh = st.checkbox("⚡ 開啟極速自動更新 (3秒)", value=False)
    st.button("🗑️ 徹底清空所有資料", on_click=cb_clear_all, type="secondary")

for report in [st.session_state.ai_report_dt, st.session_state.ai_report_swing]:
    if report:
        with st.container(border=True):
            tabs = st.tabs(list(report.keys()))
            for i, (cat, stocks) in enumerate(report.items()):
                with tabs[i]:
                    for s in stocks:
                        c_p_t = get_bulk_spark_prices([s['code']] if "台股" in cat or "資金" in cat else [], [s['code']] if "美股" in cat else [])
                        c_p = c_p_t.get(s['code'], (None, None))[0]
                        if c_p is None: c_p, _ = get_single_live_price(s['code'], "美股" in cat)
                        
                        target = 0; cond = ">="
                        if c_p:
                            if "空" in cat: target = round(c_p * 0.985, 2); cond = "<="
                            elif "多" in cat: target = round(c_p * 1.015, 2)
                            else: target = round(c_p * 1.05, 2)
                        
                        with st.expander(f"🎯 {s['name']}({s['code']}) | 真實現價: {c_p or '--'} | 目標價: {target}"):
                            st.write(f"**策略理由**：{s.get('strategy', '')}")
                            btn_txt = f"➕ 帶入目標價 {target} 且監控 {'跌破' if cond=='<=' else '漲破'}"
                            if "美股" in cat: st.button(btn_txt, key=f"btn_u_{s['code']}", on_click=cb_add_us, args=(s['code'], s['name'], target, cond))
                            else: st.button(btn_txt, key=f"btn_t_{s['code']}", on_click=cb_add_tw, args=(s['code'], s['name'], target, cond))

tab_tw, tab_us, tab_core = st.tabs(["🇹🇼 台股極速當沖", "🇺🇸 美股波段戰情", "🐢 10年期核心長線"])

# ====================
# 戰區 1：台股極速當沖
# ====================
with tab_tw:
    if not st.session_state.tw_stocks: st.info("請加入台股。")
    for idx, stock in enumerate(st.session_state.tw_stocks):
        code, name = stock['code'], stock['name']
        alerts = stock.get('alerts', [])
        ai_advice = stock.get('ai_advice', '') 
        
        df_daily, suffix = get_historical_features(code, is_us=False)
        df_1m = get_realtime_tick(code, suffix)
        
        df_5k = get_kline_data(code, suffix, '5m', t5_key)
        df_15k = get_kline_data(code, suffix, '15m', t15_key)
        
        mas = {}
        if not df_5k.empty:
            mas['5K3MA'] = df_5k['Close'].tail(3).mean()
            mas['5K5MA'] = df_5k['Close'].tail(5).mean()
            mas['5K20MA'] = df_5k['Close'].tail(20).mean()
        if not df_15k.empty:
            mas['15K3MA'] = df_15k['Close'].tail(3).mean()
            mas['15K5MA'] = df_15k['Close'].tail(5).mean()
            mas['15K20MA'] = df_15k['Close'].tail(20).mean()
        
        if not df_1m.empty and not df_daily.empty:
            live_cp, live_pp = live_price_dict.get(code, (None, None))
            if live_cp is None: live_cp, live_pp = get_single_live_price(code, is_us=False)
            
            curr_p = live_cp if live_cp is not None else df_1m['Close'].iloc[-1]
            prev_p = live_pp if live_pp is not None else df_daily['Close'].iloc[-2]
            vwap = ( (df_1m['High'] + df_1m['Low'] + df_1m['Close'])/3 * df_1m['Volume'] ).sum() / (df_1m['Volume'].sum() + 0.001)
            
            r1, s1 = 0.0, 0.0
            if len(df_daily) >= 2:
                y_high = df_daily['High'].iloc[-2]
                y_low = df_daily['Low'].iloc[-2]
                y_close = df_daily['Close'].iloc[-2]
                pivot = (y_high + y_low + y_close) / 3
                r1 = (2 * pivot) - y_low
                s1 = (2 * pivot) - y_high
            
            vol_alert_msg = ""; vol_info = ""
            is_vol_surge = False 
            if len(df_1m) >= 15:
                df_1m['Volume'] = df_1m['Volume'].fillna(0)
                avg_vol_1m = df_1m['Volume'].mean()
                if avg_vol_1m > 0:
                    vol_5m = df_1m['Volume'].tail(5).sum()
                    vol_15m = df_1m['Volume'].tail(15).sum()
                    ratio_5k = vol_5m / (avg_vol_1m * 5)
                    ratio_15k = vol_15m / (avg_vol_1m * 15)
                    vol_info = f"量能比例: 5K({ratio_5k:.1f}x) | 15K({ratio_15k:.1f}x)"
                    if ratio_5k > 2.5: 
                        vol_alert_msg += "🔥 5K急行爆量！ "
                        is_vol_surge = True
                    if ratio_15k > 2.0: 
                        vol_alert_msg += "🔥 15K波段爆量！"
                        is_vol_surge = True

            if is_vol_surge:
                if not stock.get('vol_alert_triggered', False):
                    send_telegram_alert(f"📊 🚨【台股動能異常】\n{name}({code}) 觸發主力爆量！\n現價：{curr_p}\n狀態：{vol_alert_msg.strip()}\n詳細：{vol_info}")
                    st.session_state.tw_stocks[idx]['vol_alert_triggered'] = True
                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
            else:
                if stock.get('vol_alert_triggered', False):
                    st.session_state.tw_stocks[idx]['vol_alert_triggered'] = False
                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
            
            tg_vol_str = f"\n📊 動能: {vol_alert_msg.strip()} {vol_info}".strip() if vol_info else ""

            is_alert = False
            triggered_msgs = []
            
            for a_idx, al in enumerate(alerts):
                al_type = al.get('type', '固定價格')
                if al_type == '固定價格': t_p = al['price']
                else: t_p = mas.get(al_type, 0.0)
                
                cond = al['cond']
                if t_p > 0:
                    t_p_label = f"{t_p}" if al_type == '固定價格' else f"{al_type} ({t_p:.2f})"
                    
                    if cond == ">=" and curr_p >= t_p:
                        is_alert = True
                        if not al['triggered']:
                            triggered_msgs.append(f"漲破 {t_p_label}")
                            st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = True
                            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                    elif cond == "<=" and curr_p <= t_p:
                        is_alert = True
                        if not al['triggered']:
                            triggered_msgs.append(f"跌破 {t_p_label}")
                            st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = True
                            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                    
                    if len(df_1m) >= 15:
                        touches = 0
                        if cond == ">=":
                            touches = (df_1m['High'].tail(15) >= t_p).sum()
                            if curr_p >= t_p: touches = max(touches, 1)
                        else:
                            touches = (df_1m['Low'].tail(15) <= t_p).sum()
                            if curr_p <= t_p: touches = max(touches, 1)

                        if touches >= 2 and not al.get('touch_2_triggered', False):
                            send_telegram_alert(f"⚠️ 🚨【多次叩關確認】\n{name}({code}) 近 15 分鐘內已測試目標 {t_p_label} 達 {touches} 次！\n方向：{'漲破' if cond=='>=' else '跌破'}\n現價：{curr_p}\n突破機率大增，請密切留意！{tg_vol_str}")
                            st.session_state.tw_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = True
                            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                    
                    if cond == ">=" and curr_p < t_p * 0.995: 
                        st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = False
                        st.session_state.tw_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
                    if cond == "<=" and curr_p > t_p * 1.005: 
                        st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = False
                        st.session_state.tw_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
            
            if triggered_msgs:
                msg_joined = "、".join(triggered_msgs)
                send_telegram_alert(f"🚨【台股多重到價】\n{name}({code}) 已觸發：{msg_joined}！\n現價：{curr_p}\n{tg_vol_str}")

            with st.container(border=True):
                c_title, c_del = st.columns([5, 1])
                with c_title: st.markdown(f"#### {name}({code})")
                with c_del: st.button("❌ 移除", key=f"del_tw_{code}", on_click=cb_remove_tw, args=(idx,))

                if is_alert: st.error(f"🚨 **到價警示！** 現價 {curr_p} 已觸發設定目標")
                if vol_alert_msg: st.warning(f"📊 **動能偵測**：{vol_alert_msg} ({vol_info})")
                elif vol_info: st.caption(f"📉 {vol_info}")
                if ai_advice: st.success(ai_advice)
                
                if mas:
                    st.caption(f"📈 **動態短均線** | 5K: 3MA(`{mas.get('5K3MA',0):.2f}`) 5MA(`{mas.get('5K5MA',0):.2f}`) 20MA(`{mas.get('5K20MA',0):.2f}`) ｜ 15K: 3MA(`{mas.get('15K3MA',0):.2f}`) 5MA(`{mas.get('15K5MA',0):.2f}`) 20MA(`{mas.get('15K20MA',0):.2f}`)")

                for a_idx, al in enumerate(alerts):
                    c_type, c_cond, c_inp, c_del_al = st.columns([2, 2, 3, 1])
                    opts = ["固定價格", "5K3MA", "5K5MA", "5K20MA", "15K3MA", "15K5MA", "15K20MA"]
                    current_type = al.get('type', "固定價格")
                    
                    with c_type:
                        new_type = st.selectbox("監控目標", opts, index=opts.index(current_type), key=f"type_tw_{code}_{a_idx}", label_visibility="collapsed")
                        if new_type != current_type:
                            st.session_state.tw_stocks[idx]['alerts'][a_idx]['type'] = new_type
                            st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = False
                            st.session_state.tw_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
                            st.rerun()
                    with c_cond:
                        new_cond = st.selectbox("方向", [">= 漲破", "<= 跌破"], index=0 if al['cond'] == ">=" else 1, key=f"cond_tw_{code}_{a_idx}", label_visibility="collapsed")
                        new_cond_val = ">=" if ">=" in new_cond else "<="
                        if new_cond_val != al['cond']:
                            st.session_state.tw_stocks[idx]['alerts'][a_idx]['cond'] = new_cond_val
                            st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = False
                            st.session_state.tw_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
                            st.rerun()
                    with c_inp:
                        if current_type == "固定價格":
                            new_t_price = st.number_input("警示價", value=float(al['price']), step=0.5, key=f"inp_{code}_{a_idx}", label_visibility="collapsed")
                            if new_t_price != al['price']:
                                st.session_state.tw_stocks[idx]['alerts'][a_idx]['price'] = new_t_price
                                st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = False
                                st.session_state.tw_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
                                st.rerun()
                        else:
                            ma_val = mas.get(current_type, 0.0)
                            st.markdown(f"<div style='padding-top:5px; color:#aaa;'>自動追蹤現值: **{ma_val:.2f}**</div>", unsafe_allow_html=True)
                    with c_del_al:
                        if st.button("🗑️", key=f"del_al_{code}_{a_idx}"):
                            st.session_state.tw_stocks[idx]['alerts'].pop(a_idx)
                            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                            st.rerun()
                
                c_btn1, c_btn2, _ = st.columns([1, 1, 2])
                with c_btn1:
                    if st.button("➕ 新增警示", key=f"add_al_tw_{code}"):
                        st.session_state.tw_stocks[idx]['alerts'].append({"type": "固定價格", "price": 0.0, "cond": ">=", "triggered": False, "touch_2_triggered": False})
                        st.rerun()
                with c_btn2:
                    if API_KEY and st.button("🤖 AI 算價", key=f"ai_p_{code}"):
                        with st.spinner("..."):
                            try:
                                base_cond = alerts[0]['cond'] if alerts else ">="
                                dir_str = '作多' if base_cond=='>=' else '作空'
                                math_rule = "停利目標價必須大於進場價" if base_cond=='>=' else "停利目標價必須小於進場價"
                                prompt = f"針對台股 {name}({code}) 現價 {curr_p}，給出當沖{dir_str}建議。嚴格限制：{math_rule}。必須嚴格回傳JSON格式：{{\"entry\": 進場價數字, \"target\": 停利目標價數字}}"
                                res = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
                                match = re.search(r'\{.*\}', res, re.DOTALL)
                                if match:
                                    data = json.loads(match.group(0))
                                    if alerts:
                                        st.session_state.tw_stocks[idx]['alerts'][0]['type'] = "固定價格"
                                        st.session_state.tw_stocks[idx]['alerts'][0]['price'] = float(data['target'])
                                        st.session_state.tw_stocks[idx]['alerts'][0]['triggered'] = False
                                        st.session_state.tw_stocks[idx]['alerts'][0]['touch_2_triggered'] = False
                                    st.session_state.tw_stocks[idx]['ai_advice'] = f"🤖 AI建議 -> 理想進場價: **{data['entry']}** | 停利目標: **{data['target']}**"
                                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                                    st.rerun()
                            except: pass

                st.divider()
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("現價", f"{curr_p:.2f}", f"{curr_p - prev_p:.2f}")
                c2.metric("當日VWAP", f"{vwap:.2f}")
                c3.metric("壓力(R1)", f"{r1:.2f}", help="當沖壓力算法：2*Pivot - 昨日最低價")
                c4.metric("支撐(S1)", f"{s1:.2f}", help="當沖支撐算法：2*Pivot - 昨日最高價")
                
                corr_codes = get_correlated_stocks(code, name, is_us=False)
                if corr_codes:
                    corr_display = []
                    for i, c in enumerate(corr_codes):
                        c_name = all_stocks.get(c, c)
                        icon = "👑" if i == 0 else "🔗"
                        cp, pp = live_price_dict.get(c, (None, None))
                        if cp is None: cp, pp = get_single_live_price(c, is_us=False)
                        
                        if cp is not None and pp is not None and pp > 0:
                            diff = cp - pp
                            pct = (diff / pp) * 100
                            sign = "+" if diff > 0 else ""
                            corr_display.append(f"{icon} {c_name}({c}) {cp:.2f} ({sign}{diff:.2f}, {sign}{pct:.2f}%)")
                        else:
                            corr_display.append(f"{icon} {c_name}({c})")
                    st.caption(" | ".join(corr_display))

# ====================
# 戰區 2：美股波段戰情
# ====================
with tab_us:
    if not st.session_state.us_stocks: st.info("請加入美股。")
    for idx, stock in enumerate(st.session_state.us_stocks):
        code = stock['code']
        alerts = stock.get('alerts', [])
        ai_advice = stock.get('ai_advice', '')
        
        df_daily, suffix = get_historical_features(code, is_us=True)
        df_1m_us = get_realtime_tick(code, suffix)
        
        df_5k = get_kline_data(code, suffix, '5m', t5_key)
        df_15k = get_kline_data(code, suffix, '15m', t15_key)
        
        mas = {}
        if not df_5k.empty:
            mas['5K3MA'] = df_5k['Close'].tail(3).mean()
            mas['5K5MA'] = df_5k['Close'].tail(5).mean()
            mas['5K20MA'] = df_5k['Close'].tail(20).mean()
        if not df_15k.empty:
            mas['15K3MA'] = df_15k['Close'].tail(3).mean()
            mas['15K5MA'] = df_15k['Close'].tail(5).mean()
            mas['15K20MA'] = df_15k['Close'].tail(20).mean()

        live_cp, live_pp = live_price_dict.get(code, (None, None))
        if live_cp is None: live_cp, live_pp = get_single_live_price(code, is_us=True)
        
        if live_cp is not None and not df_daily.empty:
            curr_p = live_cp
            
            r1, s1 = 0.0, 0.0
            if len(df_daily) >= 2:
                y_high = df_daily['High'].iloc[-2]
                y_low = df_daily['Low'].iloc[-2]
                y_close = df_daily['Close'].iloc[-2]
                pivot = (y_high + y_low + y_close) / 3
                r1 = (2 * pivot) - y_low
                s1 = (2 * pivot) - y_high
            
            is_alert = False
            triggered_msgs = []
            
            for a_idx, al in enumerate(alerts):
                al_type = al.get('type', '固定價格')
                if al_type == '固定價格': t_p = al['price']
                else: t_p = mas.get(al_type, 0.0)

                cond = al['cond']
                if t_p > 0:
                    t_p_label = f"${t_p}" if al_type == '固定價格' else f"{al_type} (${t_p:.2f})"

                    if cond == ">=" and curr_p >= t_p:
                        is_alert = True
                        if not al['triggered']:
                            triggered_msgs.append(f"漲破 {t_p_label}")
                            st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = True
                            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                    elif cond == "<=" and curr_p <= t_p:
                        is_alert = True
                        if not al['triggered']:
                            triggered_msgs.append(f"跌破 {t_p_label}")
                            st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = True
                            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                    
                    if not df_1m_us.empty and len(df_1m_us) >= 15:
                        touches = 0
                        if cond == ">=":
                            touches = (df_1m_us['High'].tail(15) >= t_p).sum()
                            if curr_p >= t_p: touches = max(touches, 1)
                        else:
                            touches = (df_1m_us['Low'].tail(15) <= t_p).sum()
                            if curr_p <= t_p: touches = max(touches, 1)

                        if touches >= 2 and not al.get('touch_2_triggered', False):
                            send_telegram_alert(f"⚠️ 🦅【美股叩關確認】\n{code} 近 15 分鐘內已測試目標 {t_p_label} 達 {touches} 次！\n方向：{'漲破' if cond=='>=' else '跌破'}\n現價：${curr_p}")
                            st.session_state.us_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = True
                            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

                    if cond == ">=" and curr_p < t_p * 0.995: 
                        st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = False
                        st.session_state.us_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
                    if cond == "<=" and curr_p > t_p * 1.005: 
                        st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = False
                        st.session_state.us_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False

            if triggered_msgs:
                msg_joined = "、".join(triggered_msgs)
                send_telegram_alert(f"🦅 🚨【美股多重到價】\n{code} 已觸發：{msg_joined}！\n現價：${curr_p}")

            with st.container(border=True):
                c_title, c_del = st.columns([5, 1])
                with c_title: st.markdown(f"#### 🦅 {code} (美股)")
                with c_del: st.button("❌ 移除", key=f"del_us_{code}", on_click=cb_remove_us, args=(idx,))

                if is_alert: st.error(f"🚨 **到價警示！** 現價 ${curr_p} 已觸發設定目標")
                if ai_advice: st.success(ai_advice)
                
                if mas:
                    st.caption(f"📈 **動態短均線** | 5K: 3MA(`{mas.get('5K3MA',0):.2f}`) 5MA(`{mas.get('5K5MA',0):.2f}`) 20MA(`{mas.get('5K20MA',0):.2f}`) ｜ 15K: 3MA(`{mas.get('15K3MA',0):.2f}`) 5MA(`{mas.get('15K5MA',0):.2f}`) 20MA(`{mas.get('15K20MA',0):.2f}`)")

                for a_idx, al in enumerate(alerts):
                    c_type, c_cond, c_inp, c_del_al = st.columns([2, 2, 3, 1])
                    opts = ["固定價格", "5K3MA", "5K5MA", "5K20MA", "15K3MA", "15K5MA", "15K20MA"]
                    current_type = al.get('type', "固定價格")
                    
                    with c_type:
                        new_type = st.selectbox("監控目標", opts, index=opts.index(current_type), key=f"type_us_{code}_{a_idx}", label_visibility="collapsed")
                        if new_type != current_type:
                            st.session_state.us_stocks[idx]['alerts'][a_idx]['type'] = new_type
                            st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = False
                            st.session_state.us_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
                            st.rerun()
                    with c_cond:
                        new_cond = st.selectbox("方向", [">= 漲破", "<= 跌破"], index=0 if al['cond'] == ">=" else 1, key=f"cond_us_{code}_{a_idx}", label_visibility="collapsed")
                        new_cond_val = ">=" if ">=" in new_cond else "<="
                        if new_cond_val != al['cond']:
                            st.session_state.us_stocks[idx]['alerts'][a_idx]['cond'] = new_cond_val
                            st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = False
                            st.session_state.us_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
                            st.rerun()
                    with c_inp:
                        if current_type == "固定價格":
                            new_t_price = st.number_input("警示價", value=float(al['price']), step=1.0, key=f"inp_us_{code}_{a_idx}", label_visibility="collapsed")
                            if new_t_price != al['price']:
                                st.session_state.us_stocks[idx]['alerts'][a_idx]['price'] = new_t_price
                                st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = False
                                st.session_state.us_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
                                st.rerun()
                        else:
                            ma_val = mas.get(current_type, 0.0)
                            st.markdown(f"<div style='padding-top:5px; color:#aaa;'>自動追蹤現值: **${ma_val:.2f}**</div>", unsafe_allow_html=True)
                    with c_del_al:
                        if st.button("🗑️", key=f"del_al_us_{code}_{a_idx}"):
                            st.session_state.us_stocks[idx]['alerts'].pop(a_idx)
                            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                            st.rerun()

                c_btn1, c_btn2, _ = st.columns([1, 1, 2])
                with c_btn1:
                    if st.button("➕ 新增警示", key=f"add_al_us_{code}"):
                        st.session_state.us_stocks[idx]['alerts'].append({"type": "固定價格", "price": 0.0, "cond": ">=", "triggered": False, "touch_2_triggered": False})
                        st.rerun()
                with c_btn2:
                    if API_KEY and st.button("🤖 AI 算價", key=f"ai_p_us_{code}"):
                        with st.spinner("..."):
                            try:
                                base_cond = alerts[0]['cond'] if alerts else ">="
                                dir_str = '作多' if base_cond=='>=' else '作空'
                                math_rule = "停利目標價必須大於進場價" if base_cond=='>=' else "停利目標價必須小於進場價"
                                prompt = f"針對美股 {code} 現價 {curr_p}，給出波段{dir_str}建議。嚴格限制：{math_rule}。必須嚴格回傳JSON格式：{{\"entry\": 進場價數字, \"target\": 停利目標價數字}}"
                                res = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
                                match = re.search(r'\{.*\}', res, re.DOTALL)
                                if match:
                                    data = json.loads(match.group(0))
                                    if alerts:
                                        st.session_state.us_stocks[idx]['alerts'][0]['type'] = "固定價格"
                                        st.session_state.us_stocks[idx]['alerts'][0]['price'] = float(data['target'])
                                        st.session_state.us_stocks[idx]['alerts'][0]['triggered'] = False
                                        st.session_state.us_stocks[idx]['alerts'][0]['touch_2_triggered'] = False
                                    st.session_state.us_stocks[idx]['ai_advice'] = f"🤖 AI建議 -> 理想進場價: **${data['entry']}** | 停利目標: **${data['target']}**"
                                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                                    st.rerun()
                            except: pass

                st.divider()
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("收盤現價", f"${curr_p:.2f}", f"${curr_p - live_pp:.2f}" if live_pp else "--")
                c2.metric("波段月線", f"${df_daily['Close'].tail(20).mean():.2f}")
                c3.metric("壓力(R1)", f"${r1:.2f}", delta_color="off")
                c4.metric("支撐(S1)", f"${s1:.2f}", delta_color="off")
                
                corr_codes = get_correlated_stocks(code, code, is_us=True)
                if corr_codes:
                    corr_display = []
                    for i, c in enumerate(corr_codes):
                        icon = "👑" if i == 0 else "🔗"
                        cp, pp = live_price_dict.get(c, (None, None))
                        if cp is None: cp, pp = get_single_live_price(c, is_us=True)
                        
                        if cp is not None and pp is not None and pp > 0:
                            diff = cp - pp
                            pct = (diff / pp) * 100
                            sign = "+" if diff > 0 else ""
                            corr_display.append(f"{icon} {c} {cp:.2f} ({sign}{diff:.2f}, {sign}{pct:.2f}%)")
                        else:
                            corr_display.append(f"{icon} {c}")
                    st.caption(" | ".join(corr_display))

# ====================
# 戰區 3：10年核心資產
# ====================
with tab_core:
    st.markdown("### 🐢 穩健增長：20萬 TWD 核心配置計畫")
    for asset in st.session_state.core_assets:
        code, is_us = asset['code'], asset['is_us']
        # 🚀 Bug 已修復，精準接收 2 個回傳值
        df_daily, _ = get_historical_features(code, is_us=is_us)
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
