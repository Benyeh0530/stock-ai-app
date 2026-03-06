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

# --- 基礎設定 ---
st.set_page_config(page_title="AI 跨海智能戰情室", layout="wide", initial_sidebar_state="expanded")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 🎨 首席設計師的 CSS 視覺美化 ---
st.markdown("""
<style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    
    h1 {
        background: -webkit-linear-gradient(45deg, #00f2fe, #4facfe);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 900; letter-spacing: 1px;
        text-shadow: 0px 2px 4px rgba(0,0,0,0.1);
    }

    section[data-testid="stSidebar"] {
        background-color: #0f172a !important; 
        border-right: 1px solid #1e293b;
    }
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] div.stMarkdown {
        color: #ffffff !important; 
        font-weight: 600 !important;
        text-shadow: 0px 1px 2px rgba(0,0,0,0.8);
    }

    section[data-testid="stSidebar"] div[data-baseweb="select"] span,
    section[data-testid="stSidebar"] div[data-baseweb="select"] li {
        color: #0f172a !important; 
        text-shadow: none !important;
    }
    section[data-testid="stSidebar"] input {
        color: #0f172a !important;
        background-color: #ffffff !important;
        text-shadow: none !important;
    }
    section[data-testid="stSidebar"] input::placeholder {
        color: #64748b !important;
    }
    
    div[data-testid="stMetricValue"] {
        font-size: 1.9rem; font-weight: 700;
        font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }
    label[data-testid="stMetricLabel"] p {
        font-weight: 600; color: #8b9bb4 !important; font-size: 0.95rem;
    }

    div[data-testid="stVerticalBlock"] div[style*="border"] {
        border-radius: 12px !important; border: 1px solid #2d3748 !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06) !important;
        background-color: rgba(17, 24, 39, 0.4) !important;
        transition: transform 0.2s ease-in-out;
    }
    div[data-testid="stVerticalBlock"] div[style*="border"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.2), 0 4px 6px -2px rgba(0, 0, 0, 0.05) !important;
    }

    button[kind="primary"] {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
        color: white !important; font-weight: 600; border: none; border-radius: 8px;
        box-shadow: 0 4px 6px rgba(37, 99, 235, 0.2);
    }
    button[kind="primary"] * {
        color: white !important; text-shadow: none !important;
    }
    button[kind="primary"]:hover {
        background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
        box-shadow: 0 6px 8px rgba(37, 99, 235, 0.3);
    }

    div[data-testid="stExpander"] {
        border-radius: 8px !important; border: 1px solid #334155 !important;
        background-color: rgba(30, 41, 59, 0.5) !important;
    }
    div[data-testid="stExpander"] p { font-weight: 600; font-size: 1.05rem; }
    div[data-testid="stTabs"] button { font-size: 1.1rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

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

# --- 🚀 券商級精準當沖/留倉損益計算引擎 ---
def calc_tw_pnl(entry_price, current_price, lots, direction="作多", trade_type="當沖"):
    shares = lots * 1000
    discount = 0.18
    tax_rate = 0.0015 if trade_type == "當沖" else 0.003
    
    if direction == "作多":
        buy_val = entry_price * shares
        buy_fee_orig = int(buy_val * 0.001425 + 0.5)
        buy_fee = max(1, int(buy_fee_orig * discount + 0.5))
        buy_cost = buy_val + buy_fee
        
        sell_val = current_price * shares
        sell_fee_orig = int(sell_val * 0.001425 + 0.5)
        sell_fee = max(1, int(sell_fee_orig * discount + 0.5))
        sell_tax = int(sell_val * tax_rate)
        sell_net = sell_val - sell_fee - sell_tax
        
        return sell_net - buy_cost
    else: 
        sell_val = entry_price * shares
        sell_fee_orig = int(sell_val * 0.001425 + 0.5)
        sell_fee = max(1, int(sell_fee_orig * discount + 0.5))
        sell_tax = int(sell_val * tax_rate)
        sell_net = sell_val - sell_fee - sell_tax
        
        buy_val = current_price * shares
        buy_fee_orig = int(buy_val * 0.001425 + 0.5)
        buy_fee = max(1, int(buy_fee_orig * discount + 0.5))
        buy_cost = buy_val + buy_fee
        
        return sell_net - buy_cost

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
            "ai_advice": "", "vol_alert_triggered": False,
            "my_trade_type": "當沖", "my_price": 0.0, "my_lots": 1, "my_dir": "作多" 
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
            "ai_advice": "",
            "my_price": 0.0, "my_shares": 10, "my_dir": "作多" 
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

# 初始化與舊資料向下相容
if 'initialized' not in st.session_state:
    data = load_watchlist()
    tw_data = data.get("tw", [])
    us_data = data.get("us", [])
    
    for s in tw_data:
        if 'my_trade_type' not in s: s['my_trade_type'] = "當沖"
        if 'my_price' not in s: s['my_price'] = 0.0
        if 'my_lots' not in s: s['my_lots'] = 1
        if 'my_dir' not in s: s['my_dir'] = "作多"
        if 'alerts' not in s:
            s['alerts'] = [{"type": "固定價格", "price": s.get('target_price', 0.0), "cond": s.get('condition', '>='), "triggered": s.get('alert_triggered', False), "touch_2_triggered": False}]
        else:
            for al in s['alerts']:
                if 'touch_2_triggered' not in al: al['touch_2_triggered'] = False
                if 'type' not in al: al['type'] = "固定價格"
    for s in us_data:
        if 'my_price' not in s: s['my_price'] = 0.0
        if 'my_shares' not in s: s['my_shares'] = 10
        if 'my_dir' not in s: s['my_dir'] = "作多"
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
    if 'market_alert_flags' not in st.session_state: st.session_state.market_alert_flags = {}
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
                '3日線': df['Close'].tail(3).mean(), '5日線': df['Close'].tail(5).mean(),
                '月線(20MA)': df['Close'].tail(20).mean(), '季線(60MA)': df['Close'].tail(60).mean()
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
        prompt = f"時間 {now}。你是台股當沖高手。提供5檔作多、5檔作空標的。限150元以下。找尋高波動活躍股。嚴格限制只輸出JSON，絕不可包含任何Markdown標記(如```json)或程式碼。JSON: {{ '台股當沖作多': [], '台股當沖作空': [] }} (格式：{{'code': '代碼', 'name': '名稱', 'strategy': '純白話文理由'}})"
    else:
        prompt = f"時間 {now}。你是跨國波段操盤手。提供5檔美股短波、5檔台股資金熱點。台股限150元以下。嚴格限制只輸出JSON，絕不可包含任何Markdown標記(如```json)或程式碼。JSON: {{ '美股短波分析': [], '資金熱點TOP5': [] }} (格式：{{'code': '代碼', 'name': '名稱', 'strategy': '純白話文理由'}})"
    try:
        response = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
        # 🚀 修復 Bug 1：強制脫水，去除 AI 的 Markdown 標記
        cleaned_response = response.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\{.*\}', cleaned_response, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return None
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

# 🚀 專業級 Altair 磁吸走勢圖
def render_mini_chart(df_1m, cdp_nh, cdp_nl, is_us=False):
    if df_1m.empty: return
    
    chart_df = df_1m[['Close']].copy()
    tz_str = 'America/New_York' if is_us else 'Asia/Taipei'
    chart_df['Time'] = chart_df.index.tz_convert(tz_str)
    chart_df.rename(columns={'Close': '現價'}, inplace=True)
    
    color_domain = ['現價']
    color_range = ['#3b82f6']

    if 'VWAP' in df_1m.columns:
        vwap_clean = df_1m['VWAP'].replace(0, np.nan).bfill().fillna(df_1m['Close'])
        chart_df['當日VWAP(均線)'] = vwap_clean
        color_domain.append('當日VWAP(均線)')
        color_range.append('#f59e0b')

    if cdp_nh > 0 and cdp_nl > 0:
        chart_df['CDP_NH(壓力)'] = cdp_nh
        chart_df['CDP_NL(支撐)'] = cdp_nl
        color_domain.extend(['CDP_NH(壓力)', 'CDP_NL(支撐)'])
        color_range.extend(['#ef4444', '#10b981'])
    
    df_melted = chart_df.melt('Time', var_name='線型', value_name='價格')
    
    valid_prices = df_melted[df_melted['價格'] > 0]['價格']
    if not valid_prices.empty:
        y_min = valid_prices.min() * 0.995
        y_max = valid_prices.max() * 1.005
    else:
        y_min, y_max = 0, 100

    base = alt.Chart(df_melted).encode(x=alt.X('Time:T', title='', axis=alt.Axis(format='%H:%M', grid=False, tickCount=10)))
    
    line = base.mark_line(strokeWidth=2.5).encode(
        y=alt.Y('價格:Q', scale=alt.Scale(domain=[y_min, y_max]), title='', axis=alt.Axis(gridColor='#334155')),
        color=alt.Color('線型:N', scale=alt.Scale(domain=color_domain, range=color_range), legend=alt.Legend(title="", orient="top", padding=0))
    )

    hover = alt.selection_point(fields=['Time'], nearest=True, on='mouseover', empty=False)

    points = line.mark_circle(size=80).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip('Time:T', format='%H:%M', title='時間'), '線型', alt.Tooltip('價格:Q', format='.2f')]
    ).add_params(hover)

    rules = base.mark_rule(color='#94a3b8', strokeDash=[3, 3]).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0))
    ).transform_filter(hover)

    chart = alt.layer(line, rules, points).properties(height=220).interactive(bind_y=False)
    st.altair_chart(chart, use_container_width=True)

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

# 🚀 營業時間鎖
is_tw_market_open = datetime.time(9, 0) <= now_tpe.time() <= datetime.time(13, 30)

col_t1, col_t2, col_t3 = st.columns(3)
with col_t1:
    if '台股加權' in market_temp: st.metric("🇹🇼 台股大盤溫度", f"{market_temp['台股加權'][0]:.2f}", f"{market_temp['台股加權'][1]:.2f}%", delta_color="normal" if market_temp['台股加權'][1] > 0 else "inverse")
with col_t2:
    if '那斯達克' in market_temp: st.metric("🇺🇸 科技股溫度 (Nasdaq
