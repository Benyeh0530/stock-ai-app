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
st.set_page_config(page_title="AI 跨海智能戰情室", layout="wide", initial_sidebar_state="expanded")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 🔐 雙因子認證 (2FA) 金鑰設定 ---
TWO_FA_SECRET = "JBSWY3DPEHPK3PXP" 

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

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
        color: #ffffff !important; font-weight: 600 !important;
        text-shadow: 0px 1px 2px rgba(0,0,0,0.8);
    }
    section[data-testid="stSidebar"] div[data-baseweb="select"] span,
    section[data-testid="stSidebar"] div[data-baseweb="select"] li {
        color: #0f172a !important; text-shadow: none !important;
    }
    section[data-testid="stSidebar"] input {
        color: #0f172a !important; background-color: #ffffff !important; text-shadow: none !important;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.5rem; font-weight: 700; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }
    label[data-testid="stMetricLabel"] p {
        font-weight: 600; color: #8b9bb4 !important; font-size: 0.85rem;
    }
    div[data-testid="stVerticalBlock"] div[style*="border"] {
        border-radius: 12px !important; border: 1px solid #2d3748 !important;
        background-color: rgba(17, 24, 39, 0.4) !important;
        transition: transform 0.2s ease-in-out;
    }
    div[data-testid="stVerticalBlock"] div[style*="border"]:hover {
        transform: translateY(-2px);
    }
    button[kind="primary"] {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
        color: white !important; font-weight: 600; border: none; border-radius: 8px;
    }
    button[kind="primary"]:hover {
        background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
    }
</style>
""", unsafe_allow_html=True)

# --- 1. 引擎與雲地通訊設定 ---
if 'api_key' not in st.session_state:
    st.session_state.api_key = st.secrets.get("GEMINI_API_KEY", "")

API_KEY = st.session_state.api_key
if API_KEY:
    genai.configure(api_key=API_KEY)
    ai_model = genai.GenerativeModel('gemini-2.5-flash')

TG_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

if 'agent_url' not in st.session_state:
    st.session_state.agent_url = "http://127.0.0.1:5000"

def send_telegram_alert(msg):
    if not TG_BOT_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg}, timeout=2)
    except: pass

def fire_order_to_agent(code, price, action, qty=1):
    url = f"{st.session_state.agent_url.rstrip('/')}/api/fire"
    payload = {"code": code, "price": price, "action": action, "qty": qty}
    try:
        response = requests.post(url, json=payload, timeout=3)
        return response.json()
    except Exception as e:
        return {"status": "error", "msg": "無法連線至地端 Agent，請檢查網址或大腦是否啟動"}

def calc_tw_pnl(entry_price, current_price, lots, direction="作多", trade_type="當沖"):
    shares = lots * 1000; discount = 0.18; tax_rate = 0.0015 if trade_type == "當沖" else 0.003
    if direction == "作多":
        buy_val = entry_price * shares; buy_fee = max(1, int(int(buy_val * 0.001425 + 0.5) * discount + 0.5)); buy_cost = buy_val + buy_fee
        sell_val = current_price * shares; sell_fee = max(1, int(int(sell_val * 0.001425 + 0.5) * discount + 0.5)); sell_tax = int(sell_val * tax_rate)
        return (sell_val - sell_fee - sell_tax) - buy_cost
    else: 
        sell_val = entry_price * shares; sell_fee = max(1, int(int(sell_val * 0.001425 + 0.5) * discount + 0.5)); sell_tax = int(sell_val * tax_rate)
        buy_val = current_price * shares; buy_fee = max(1, int(int(buy_val * 0.001425 + 0.5) * discount + 0.5)); buy_cost = buy_val + buy_fee
        return (sell_val - sell_fee - sell_tax) - buy_cost

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

def cb_add_tw(code, name, target_price=0.0, condition=">="):
    exists = False
    for s in st.session_state.tw_stocks:
        if s['code'] == code:
            exists = True
            s['alerts'].append({"type": "固定價格", "price": float(target_price), "cond": condition, "triggered": False, "touch_2_triggered": False})
            break
    if not exists:
        st.session_state.tw_stocks.append({
            "code": code, "name": name, "alerts": [{"type": "固定價格", "price": float(target_price), "cond": condition, "triggered": False, "touch_2_triggered": False}], 
            "ai_advice": "", "vol_alert_triggered": False, "my_trade_type": "當沖", "my_price": 0.0, "my_lots": 1, "my_dir": "作多" 
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
            "code": code, "name": name, "alerts": [{"type": "固定價格", "price": float(target_price), "cond": condition, "triggered": False, "touch_2_triggered": False}], 
            "ai_advice": "", "my_price": 0.0, "my_shares": 10, "my_dir": "作多" 
        })
    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

def cb_remove_tw(idx): st.session_state.tw_stocks.pop(idx); save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
def cb_remove_us(idx): st.session_state.us_stocks.pop(idx); save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
def cb_clear_all():
    st.session_state.tw_stocks = []; st.session_state.us_stocks = []; st.session_state.ai_report_dt = None; st.session_state.ai_report_swing = None; save_watchlist([], [])

if 'initialized' not in st.session_state:
    data = load_watchlist()
    st.session_state.tw_stocks = data.get("tw", [])
    st.session_state.us_stocks = data.get("us", [])
    for lst in [st.session_state.tw_stocks, st.session_state.us_stocks]:
        for s in lst:
            if 'alerts' not in s: s['alerts'] = [{"type": "固定價格", "price": s.get('target_price', 0.0), "cond": s.get('condition', '>='), "triggered": s.get('alert_triggered', False), "touch_2_triggered": False}]
            for al in s['alerts']:
                if 'touch_2_triggered' not in al: al['touch_2_triggered'] = False
                if 'type' not in al: al['type'] = "固定價格"
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
        url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"
        res = requests.get(url, timeout=8).json()
        if res.get('msg') == 'success':
            for item in res['data']: db[str(item['stock_id'])] = str(item['stock_name'])
            if db: return db
    except: pass
    try:
        res_tw = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=5, verify=False)
        if res_tw.status_code == 200:
            for item in res_tw.json(): db[item['Code']] = item['Name']
        res_otc = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=5, verify=False)
        if res_otc.status_code == 200:
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
            return {'3日線': df['Close'].tail(3).mean(), '5日線': df['Close'].tail(5).mean(), '月線(20MA)': df['Close'].tail(20).mean(), '季線(60MA)': df['Close'].tail(60).mean()}
    except: pass
    return None

@st.cache_data(show_spinner=False)
def get_kline_data(code, suffix, interval, time_key):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        range_str = "60d" if interval in ["5m", "15m"] else "5d"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval={interval}&range={range_str}"
        res = requests.get(url, headers=headers, timeout=3).json()
        idx = pd.to_datetime(res['chart']['result'][0]['timestamp'], unit='s', utc=True)
        df = pd.DataFrame({
            'Open': res['chart']['result'][0]['indicators']['quote'][0]['open'], 'High': res['chart']['result'][0]['indicators']['quote'][0]['high'],
            'Low': res['chart']['result'][0]['indicators']['quote'][0]['low'], 'Close': res['chart']['result'][0]['indicators']['quote'][0]['close'],
            'Volume': res['chart']['result'][0]['indicators']['quote'][0]['volume']
        }, index=idx).dropna()
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=900)
def get_historical_features(code, is_us=False):
    headers = {"User-Agent": "Mozilla/5.0"}
    suffixes = [""] if is_us else [".TW", ".TWO"]
    for suffix in suffixes:
        try:
            url_1d = f"https://query2.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range=2y"
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
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1m&range=5d&_t={int(time.time())}"
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

@st.cache_data(ttl=43200, show_spinner=False)
def fetch_ai_list(report_type, api_key_hash):
    if not API_KEY: return None
    now = datetime.datetime.now(pytz.timezone('Asia/Taipei')).strftime("%Y-%m-%d %H:%M")
    if report_type == "daytrade": prompt = f"時間 {now}。你是台股當沖高手。提供5檔作多、5檔作空標的。找尋高波動活躍股。嚴格限制只輸出JSON。JSON: {{ '台股當沖作多': [], '台股當沖作空': [] }} (格式：{{'code': '代碼', 'name': '名稱', 'strategy': '純白話文理由'}})"
    else: prompt = f"時間 {now}。你是跨國波段操盤手。提供5檔美股短波、5檔台股資金熱點。嚴格限制只輸出JSON。JSON: {{ '美股短波分析': [], '資金熱點TOP5': [] }} (格式：{{'code': '代碼', 'name': '名稱', 'strategy': '純白話文理由'}})"
    try:
        response = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
        cleaned_response = response.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\{.*\}', cleaned_response, re.DOTALL)
        if match: return json.loads(match.group(0))
        return None
    except: return None

# 🚀 修復 AI 雷達卡死：綁定 API_KEY 作為參數，確保 Key 變更時刷新快取
@st.cache_data(ttl=86400, show_spinner=False)
def get_correlated_stocks(code, name, key_hash, is_us=False):
    if not key_hash: return []
    try: genai.configure(api_key=key_hash)
    except: pass
    market = "美股" if is_us else "台股"
    rule_str = "請絕對只回傳股票代碼，用逗號隔開(如:2330,2303,5347)" if not is_us else "請絕對只回傳股票代碼，用逗號隔開(如:NVDA,AMD,TSM)"
    
    for attempt in range(2):
        try:
            local_model = genai.GenerativeModel('gemini-2.5-flash')
            prompt = f"針對 {market} {name}({code})，找出 3 檔同產業高連動的股票。嚴格規定：只能輸出代碼，不要任何中文。{rule_str}。"
            res = local_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.1), request_options={"timeout": 8.0}).text
            if is_us: codes = re.findall(r'[A-Z]+', res.upper())
            else: codes = re.findall(r'\d{4,}', res)
            
            seen = set(); uniq = []
            for c in codes:
                if c not in seen and c != code:
                    seen.add(c); uniq.append(c)
            if uniq: return uniq[:3]
        except: 
            time.sleep(1)
            continue
    return None

# --- 📊 視覺圖表引擎 ---
def render_mini_chart(df_1m, cdp_nh, cdp_nl, alerts=[], is_us=False):
    if df_1m.empty: return
    
    chart_df = df_1m[['Open', 'Close', 'Volume']].copy()
    tz_str = 'America/New_York' if is_us else 'Asia/Taipei'
    chart_df['Time'] = chart_df.index.tz_convert(tz_str)
    chart_df['現價'] = chart_df['Close']
    
    latest_time = chart_df['Time'].iloc[-1]
    if is_us:
        start_time = latest_time.replace(hour=9, minute=30, second=0, microsecond=0)
        end_time = latest_time.replace(hour=16, minute=0, second=0, microsecond=0)
    else:
        start_time = latest_time.replace(hour=9, minute=0, second=0, microsecond=0)
        end_time = latest_time.replace(hour=13, minute=30, second=0, microsecond=0)
    
    chart_df = chart_df[(chart_df['Time'] >= start_time) & (chart_df['Time'] <= end_time)]
    if chart_df.empty: return

    color_domain = ['現價']; color_range = ['#3b82f6']

    if 'VWAP' in df_1m.columns:
        vwap_clean = df_1m['VWAP'].replace(0, np.nan).bfill().fillna(df_1m['Close'])
        chart_df['當日VWAP(均線)'] = vwap_clean.loc[chart_df.index]
        color_domain.append('當日VWAP(均線)'); color_range.append('#f59e0b')

    if cdp_nh > 0 and cdp_nl > 0:
        chart_df['CDP_NH(壓力)'] = cdp_nh; chart_df['CDP_NL(支撐)'] = cdp_nl
        color_domain.extend(['CDP_NH(壓力)', 'CDP_NL(支撐)']); color_range.extend(['#ef4444', '#10b981'])
    
    df_melted = chart_df.melt(id_vars=['Time', 'Open', 'Close', 'Volume'], var_name='線型', value_name='價格')
    valid_prices = df_melted[df_melted['價格'] > 0]['價格']
    y_min, y_max = (valid_prices.min() * 0.995, valid_prices.max() * 1.005) if not valid_prices.empty else (0, 100)

    # 主圖
    base = alt.Chart(df_melted).encode(x=alt.X('Time:T', title='', scale=alt.Scale(domain=[start_time.isoformat(), end_time.isoformat()]), axis=alt.Axis(format='%H:%M', grid=False, tickCount=8)))
    line = base.mark_line(strokeWidth=2.5).encode(
        y=alt.Y('價格:Q', scale=alt.Scale(domain=[y_min, y_max]), title='', axis=alt.Axis(gridColor='#334155')),
        color=alt.Color('線型:N', scale=alt.Scale(domain=color_domain, range=color_range), legend=alt.Legend(title="", orient="top", padding=0))
    )

    hover = alt.selection_point(fields=['Time'], nearest=True, on='mouseover', empty=False)
    points = line.mark_circle(size=80).encode(opacity=alt.condition(hover, alt.value(1), alt.value(0)), tooltip=[alt.Tooltip('Time:T', format='%H:%M', title='時間'), '線型', alt.Tooltip('價格:Q', format='.2f')]).add_params(hover)
    v_rules = base.mark_rule(color='#94a3b8', strokeDash=[3, 3]).encode(opacity=alt.condition(hover, alt.value(1), alt.value(0))).transform_filter(hover)
    h_rules = base.mark_rule(color='#94a3b8', strokeDash=[3, 3]).encode(y='價格:Q', opacity=alt.condition(hover, alt.value(1), alt.value(0))).transform_filter(hover).transform_filter(alt.datum.線型 == '現價')

    alert_layers = []
    for al in alerts:
        if al.get('type') == '固定價格' and al.get('price', 0) > 0:
            alert_layers.append(alt.Chart(pd.DataFrame({'價格': [al['price']]})).mark_rule(color='#eab308', strokeWidth=2, strokeDash=[4, 4]).encode(y='價格:Q'))

    main_chart = alt.layer(line, v_rules, h_rules, points, *alert_layers).properties(height=200)

    # 副圖
    up_color = "#ef4444" if not is_us else "#10b981"
    down_color = "#10b981" if not is_us else "#ef4444"
    vol_chart = alt.Chart(chart_df).mark_bar(opacity=0.6).encode(
        x=alt.X('Time:T', title='', scale=alt.Scale(domain=[start_time.isoformat(), end_time.isoformat()]), axis=alt.Axis(labels=False, ticks=False)),
        y=alt.Y('Volume:Q', title='量', axis=alt.Axis(labels=False, grid=False)),
        color=alt.condition("datum.Close >= datum.Open", alt.value(up_color), alt.value(down_color)),
        tooltip=[alt.Tooltip('Time:T', format='%H:%M', title='時間'), alt.Tooltip('Volume:Q', title='成交量')]
    ).properties(height=60)

    st.altair_chart(alt.vconcat(main_chart, vol_chart).resolve_scale(x='shared').configure_concat(spacing=0), use_container_width=True)

# 🚀 終極修復：無縫平移 K 線與消除非交易時間斷層
def render_kline_chart(tf, df_1m, df_5k, df_15k, df_daily, curr_p, alerts=[], is_us=False, visible_layers=["K棒", "MA3", "MA5", "MA10", "MA23"], lookback=60):
    if tf == "1K": df = df_1m
    elif tf == "5K": df = df_5k
    elif tf == "15K": df = df_15k
    else: df = df_daily
    
    if df.empty: return
    df_chart = df.copy()
    
    if curr_p is not None and not df_chart.empty:
        last_idx = df_chart.index[-1]
        df_chart.at[last_idx, 'Close'] = curr_p
        if curr_p > df_chart.at[last_idx, 'High']: df_chart.at[last_idx, 'High'] = curr_p
        if curr_p < df_chart.at[last_idx, 'Low']: df_chart.at[last_idx, 'Low'] = curr_p
        
    df_chart['MA3'] = df_chart['Close'].rolling(3).mean()
    df_chart['MA5'] = df_chart['Close'].rolling(5).mean()
    df_chart['MA10'] = df_chart['Close'].rolling(10).mean()
    df_chart['MA23'] = df_chart['Close'].rolling(23).mean()
    
    tz_str = 'America/New_York' if is_us else 'Asia/Taipei'
    df_chart['Time'] = df_chart.index.tz_convert(tz_str)
    
    # 🔓 關鍵修復 1：過濾非交易時段，根除圖表空白斷層
    if tf != "日K":
        df_chart = df_chart.set_index('Time')
        if is_us: df_chart = df_chart.between_time('09:30', '16:00')
        else: df_chart = df_chart.between_time('09:00', '13:30')
        df_chart = df_chart.reset_index()
    else:
        df_chart = df_chart.reset_index(drop=True)
        
    if df_chart.empty: return

    # 🔓 關鍵修復 2：映射至連續索引，支援完美平移拖曳
    df_chart['x_idx'] = np.arange(len(df_chart))
    axis_format = '%y/%m/%d' if tf == "日K" else '%m/%d %H:%M'
    df_chart['TimeStr'] = df_chart['Time'].dt.strftime(axis_format)
    
    start_idx = max(0, len(df_chart) - lookback)
    end_idx = len(df_chart) - 1
    
    y_min = df_chart['Low'].min() * 0.995; y_max = df_chart['High'].max() * 1.005
    up_color = "#ef4444" if not is_us else "#10b981"
    down_color = "#10b981" if not is_us else "#ef4444"
    
    pan_zoom = alt.selection_interval(bind='scales', encodings=['x'])
    
    # 強制關閉 X 軸文字標籤，完美消滅重疊亂碼
    base = alt.Chart(df_chart).encode(
        x=alt.X('x_idx:Q', title='', scale=alt.Scale(domain=[start_idx, end_idx]), axis=alt.Axis(labels=False, ticks=False, grid=False))
    )
    
    layers = []
    if "K棒" in visible_layers:
        rule = base.mark_rule().encode(
            y=alt.Y('Low:Q', scale=alt.Scale(domain=[y_min, y_max]), title='', axis=alt.Axis(gridColor='#334155')), y2='High:Q',
            color=alt.condition("datum.Close >= datum.Open", alt.value(up_color), alt.value(down_color))
        )
        bar = base.mark_bar().encode(
            y='Open:Q', y2='Close:Q', color=alt.condition("datum.Close >= datum.Open", alt.value(up_color), alt.value(down_color)),
            tooltip=[alt.Tooltip('TimeStr:N', title='時間'), 'Open', 'High', 'Low', 'Close', 'Volume']
        )
        layers.extend([rule, bar])
    
    ma_colors = {'MA3': '#f59e0b', 'MA5': '#3b82f6', 'MA10': '#a855f7', 'MA23': '#ec4899'}
    for ma in ['MA3', 'MA5', 'MA10', 'MA23']:
        if ma in visible_layers and ma in df_chart.columns:
            layers.append(base.mark_line(size=1.5, opacity=0.8).encode(y=alt.Y(f'{ma}:Q'), color=alt.value(ma_colors[ma]), tooltip=[alt.Tooltip('TimeStr:N', title='時間'), alt.Tooltip(f'{ma}:Q', format='.2f', title=ma)]))
            
    for al in alerts:
        if al.get('type') == '固定價格' and al.get('price', 0) > 0:
            layers.append(alt.Chart(pd.DataFrame({'價格': [al['price']]})).mark_rule(color='#eab308', strokeWidth=2, strokeDash=[4, 4]).encode(y='價格:Q'))
            
    if not layers:
        st.altair_chart(alt.Chart(pd.DataFrame({'x': [0], 'y': [0], 't': ['👀 已隱藏所有圖層']})).mark_text(size=18, color='#94a3b8').encode(text='t:N').properties(height=260), use_container_width=True)
        return
        
    main_kline = alt.layer(*layers).properties(height=200).add_params(pan_zoom)

    vol_chart = base.mark_bar(opacity=0.6).encode(
        y=alt.Y('Volume:Q', title='量', axis=alt.Axis(labels=False, grid=False)),
        color=alt.condition("datum.Close >= datum.Open", alt.value(up_color), alt.value(down_color)),
        tooltip=[alt.Tooltip('TimeStr:N', title='時間'), alt.Tooltip('Volume:Q', title='成交量')]
    ).properties(height=60)

    st.altair_chart(alt.vconcat(main_kline, vol_chart).resolve_scale(x='shared').configure_concat(spacing=0), use_container_width=True)

# --- 側邊欄：安全驗證與雲地中控設定 ---
with st.sidebar:
    st.title("🛡️ 終極安控中心")
    
    if not st.session_state.authenticated:
        st.warning("🔒 損益與下單功能已鎖定")
        auth_code = st.text_input("輸入 Google Authenticator 6碼驗證碼", type="password")
        if st.button("解鎖戰情室", use_container_width=True, type="primary"):
            totp = pyotp.TOTP(TWO_FA_SECRET)
            if totp.verify(auth_code):
                st.session_state.authenticated = True
                st.success("✅ 身分驗證成功，武器系統已解鎖！")
                st.rerun()
            else:
                st.error("❌ 驗證碼錯誤")
    else:
        st.success("🔓 指揮官已登入，火力全開")
        if st.button("登出並鎖定", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()

    st.divider()
    st.header("🤖 AI 引擎與 API 設定")
    if not st.session_state.api_key:
        st.error("🔴 API 未設定 (AI 雷達與算價已停擺)")
        user_key = st.text_input("🔑 輸入 Gemini API Key 啟動 AI", type="password")
        if st.button("💾 儲存 API Key 並啟動", use_container_width=True, type="primary"):
            st.session_state.api_key = user_key
            get_correlated_stocks.clear() # 🚀 強制清洗舊快取
            st.rerun()
    else:
        st.success("🟢 API 已連線，AI 引擎運轉中")
        if st.button("🗑️ 清除 API Key", use_container_width=True):
            st.session_state.api_key = ""
            st.rerun()

    st.divider()
    st.header("⚙️ 圖表視角設定")
    ui_lookback = st.select_slider("🕯️ 初始渲染 K 棒數量", options=[30, 60, 90, 120, 240], value=60)
    st.caption("設定後，圖表上仍可透過滑鼠拖曳或滾輪自由往前追溯歷史數據。")
            
    st.divider()
    st.header("🌐 雲地通訊設定")
    new_agent_url = st.text_input("地端 Agent 網址 (Ngrok/IP)", value=st.session_state.agent_url)
    if new_agent_url != st.session_state.agent_url:
        st.session_state.agent_url = new_agent_url
        st.toast("✅ Agent 連線網址已更新")

    st.divider()
    st.header("🤖 選股報告分流")
    if st.button("🚀 生成【當沖短線】報告", use_container_width=True, type="primary"):
        st.session_state.ai_report_dt = fetch_ai_list("daytrade", API_KEY)
    if st.button("🦅 生成【波段熱點】報告", use_container_width=True):
        st.session_state.ai_report_swing = fetch_ai_list("swing", API_KEY)
    
    st.divider()
    st.header("🎯 自訂監控加入")
    all_stocks = get_full_stock_db()
    if all_stocks: stock_list = [f"{code} {name}" for code, name in all_stocks.items()]
    else: stock_list = ["伺服器連線異常，請使用下方強制加入"]

    selected_tw = st.selectbox("🔍 搜尋台股代碼", options=["請點此搜尋..."] + stock_list, index=0)
    if selected_tw != "請點此搜尋..." and "伺服器連線異常" not in selected_tw:
        parts = selected_tw.split(" "); code = parts[0]; name = " ".join(parts[1:])
        st.button(f"➕ 加入 {name} (台股)", on_click=cb_add_tw, args=(code, name))

    with st.expander("🛠️ 找不到？手動強制加入"):
        tw_code = st.text_input("🇹🇼 手動輸入台股代碼 (如 2330)").strip()
        if tw_code:
            tw_name = all_stocks.get(tw_code, tw_code)
            st.button(f"➕ 強制加入 {tw_name} (台股)", on_click=cb_add_tw, args=(tw_code, tw_name))

    us_code = st.text_input("🇺🇸 輸入美股代碼 (如 NVDA)").strip().upper()
    if us_code: st.button(f"➕ 加入 {us_code} (美股)", on_click=cb_add_us, args=(us_code, us_code))
            
    st.divider()
    auto_refresh = st.checkbox("⚡ 開啟極速自動更新 (3秒)", value=False)
    st.button("🗑️ 徹底清空所有資料", on_click=cb_clear_all, type="secondary")

# --- AI 報告渲染 ---
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

# --- 主畫面渲染 ---
st.title("⚡ AI 雲地混合智能戰情室")

now_tpe = datetime.datetime.now(pytz.timezone('Asia/Taipei'))
t5_key = f"{now_tpe.year}{now_tpe.month}{now_tpe.day}{now_tpe.hour}_{now_tpe.minute // 5}"
t15_key = f"{now_tpe.year}{now_tpe.month}{now_tpe.day}{now_tpe.hour}_{now_tpe.minute // 15}"
is_tw_market_open = datetime.time(9, 0) <= now_tpe.time() <= datetime.time(13, 30)

all_tw_to_fetch = set([s['code'] for s in st.session_state.tw_stocks])
all_us_to_fetch = set([s['code'] for s in st.session_state.us_stocks])
all_us_to_fetch.add('^TWII')
live_price_dict = get_bulk_spark_prices(list(all_tw_to_fetch), list(all_us_to_fetch))
market_temp = get_market_temp()

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
    threshold = 0.003; reset_threshold = 0.005; alert_msgs = []
    
    for idx, (ma_name, ma_val) in enumerate(twii_mas.items()):
        dist_pts = twii_cp - ma_val
        dist_pct = dist_pts / ma_val
        if abs(dist_pct) <= threshold:
            if dist_pts > 0: ma_cols[idx].warning(f"**{ma_name}** `{ma_val:.0f}`\n\n⚠️ **回測警戒**：即將跌破，僅剩 **{dist_pts:.0f}** 點 ({dist_pct*100:+.2f}%)")
            else: ma_cols[idx].warning(f"**{ma_name}** `{ma_val:.0f}`\n\n🔥 **突破叩關**：即將突破，僅差 **{abs(dist_pts):.0f}** 點 ({dist_pct*100:+.2f}%)")
        else:
            if dist_pts > 0: ma_cols[idx].success(f"**{ma_name}** `{ma_val:.0f}`\n\n🛡️ **支撐防護**：距跌破還剩 **{dist_pts:.0f}** 點 ({dist_pct*100:+.2f}%)")
            else: ma_cols[idx].error(f"**{ma_name}** `{ma_val:.0f}`\n\n⚔️ **上檔壓力**：距突破還差 **{abs(dist_pts):.0f}** 點 ({dist_pct*100:+.2f}%)")
        
        state_key = f"twii_{ma_name}"
        if abs(dist_pct) <= threshold:
            if not st.session_state.market_alert_flags.get(state_key, False):
                if dist_pts > 0: msg = f"📉 大盤現價 {twii_cp:.0f}，即將向下回測 {ma_name} ({ma_val:.0f})！距離僅 {dist_pts:.0f} 點"
                else: msg = f"📈 大盤現價 {twii_cp:.0f}，即將向上挑戰 {ma_name} ({ma_val:.0f})！距離僅 {abs(dist_pts):.0f} 點"
                alert_msgs.append(msg)
                st.session_state.market_alert_flags[state_key] = True
        elif abs(dist_pct) > reset_threshold:
            st.session_state.market_alert_flags[state_key] = False
            
    if alert_msgs and is_tw_market_open:
        send_telegram_alert("⚠️ 🚨【大盤關鍵均線警報】\n" + "\n".join(alert_msgs))
    
    st.divider()

tab_tw, tab_us, tab_core = st.tabs(["🇹🇼 台股極速當沖", "🇺🇸 美股波段戰情", "🐢 10年期核心長線"])

# ====================
# 戰區 1：台股極速當沖
# ====================
with tab_tw:
    if not st.session_state.tw_stocks: st.info("請加入台股。")
    for idx, stock in enumerate(st.session_state.tw_stocks):
        code, name = stock['code'], stock['name']
        alerts = stock.get('alerts', []); ai_advice = stock.get('ai_advice', '') 
        
        df_daily, suffix = get_historical_features(code, is_us=False)
        df_1m = get_realtime_tick(code, suffix)
        df_5k = get_kline_data(code, suffix, '5m', t5_key)
        df_15k = get_kline_data(code, suffix, '15m', t15_key)
        
        mas = {}; cdp_nh = cdp_nl = 0.0
        if not df_1m.empty and not df_daily.empty:
            df_1m['Typical_Price'] = (df_1m['High'] + df_1m['Low'] + df_1m['Close']) / 3
            df_1m['Cum_Vol'] = df_1m['Volume'].cumsum().replace(0, np.nan)
            df_1m['Cum_PV'] = (df_1m['Typical_Price'] * df_1m['Volume']).cumsum()
            df_1m['VWAP'] = (df_1m['Cum_PV'] / df_1m['Cum_Vol']).bfill().fillna(df_1m['Close'])
            mas['當日VWAP'] = df_1m['VWAP'].iloc[-1]

            live_cp, live_pp = live_price_dict.get(code, (None, None))
            if live_cp is None: live_cp, live_pp = get_single_live_price(code, is_us=False)
            curr_p = live_cp if live_cp is not None else df_1m['Close'].iloc[-1]
            prev_p = live_pp if live_pp is not None else df_daily['Close'].iloc[-2]
            
            df_daily_rt = df_daily.copy()
            if not df_daily_rt.empty:
                df_daily_rt.iloc[-1, df_daily_rt.columns.get_loc('Close')] = curr_p
                mas['日線3MA'] = df_daily_rt['Close'].tail(3).mean(); mas['日線5MA'] = df_daily_rt['Close'].tail(5).mean()
                mas['日線10MA'] = df_daily_rt['Close'].tail(10).mean(); mas['日線23MA'] = df_daily_rt['Close'].tail(23).mean()
            
            r1, s1 = 0.0, 0.0
            if len(df_daily) >= 2:
                y_high, y_low, y_close = df_daily['High'].iloc[-2], df_daily['Low'].iloc[-2], df_daily['Close'].iloc[-2]
                pivot = (y_high + y_low + y_close) / 3
                r1 = (2 * pivot) - y_low; s1 = (2 * pivot) - y_high
                cdp = (y_high + y_low + 2 * y_close) / 4
                cdp_nh = (2 * cdp) - y_low; cdp_nl = (2 * cdp) - y_high
                mas['CDP(中價)'] = cdp; mas['CDP_NH(壓力)'] = cdp_nh; mas['CDP_NL(支撐)'] = cdp_nl
            
            vol_alert_msg = ""; vol_info = ""; is_vol_surge = False 
            if len(df_1m) >= 15:
                df_1m['Volume'] = df_1m['Volume'].fillna(0)
                avg_vol_1m = df_1m['Volume'].mean()
                if avg_vol_1m > 0:
                    vol_5m = df_1m['Volume'].tail(5).sum(); vol_15m = df_1m['Volume'].tail(15).sum()
                    ratio_5k = vol_5m / (avg_vol_1m * 5); ratio_15k = vol_15m / (avg_vol_1m * 15)
                    vol_info = f"量能比例: 5K({ratio_5k:.1f}x) | 15K({ratio_15k:.1f}x)"
                    if ratio_5k > 2.5: vol_alert_msg += "🔥 5K急行爆量！ "; is_vol_surge = True
                    if ratio_15k > 2.0: vol_alert_msg += "🔥 15K波段爆量！"; is_vol_surge = True

            if is_vol_surge:
                if not stock.get('vol_alert_triggered', False):
                    if is_tw_market_open: send_telegram_alert(f"📊 🚨【台股動能異常】\n{name}({code}) 觸發主力爆量！\n現價：{curr_p}\n狀態：{vol_alert_msg.strip()}\n詳細：{vol_info}")
                    st.session_state.tw_stocks[idx]['vol_alert_triggered'] = True
                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
            else:
                if stock.get('vol_alert_triggered', False):
                    st.session_state.tw_stocks[idx]['vol_alert_triggered'] = False
                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
            
            tg_vol_str = f"\n📊 動能: {vol_alert_msg.strip()} {vol_info}".strip() if vol_info else ""
            is_alert = False; triggered_msgs = []
            
            for a_idx, al in enumerate(alerts):
                al_type = al.get('type', '固定價格')
                t_p = al['price'] if al_type == '固定價格' else mas.get(al_type, 0.0)
                cond = al['cond']
                
                if t_p > 0:
                    t_p_label = f"{t_p}" if al_type == '固定價格' else f"{al_type} ({t_p:.2f})"
                    if cond == ">=" and curr_p >= t_p:
                        is_alert = True
                        if not al['triggered']:
                            triggered_msgs.append(f"漲破 {t_p_label}"); st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = True
                    elif cond == "<=" and curr_p <= t_p:
                        is_alert = True
                        if not al['triggered']:
                            triggered_msgs.append(f"跌破 {t_p_label}"); st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = True
                    
                    touches = 0
                    if len(df_1m) >= 15:
                        if cond == ">=":
                            touches = (df_1m['High'].tail(15) >= t_p).sum()
                            if curr_p >= t_p: touches = max(touches, 1)
                        else:
                            touches = (df_1m['Low'].tail(15) <= t_p).sum()
                            if curr_p <= t_p: touches = max(touches, 1)

                        if touches >= 2 and not al.get('touch_2_triggered', False):
                            if is_tw_market_open: send_telegram_alert(f"⚠️ 🚨【多次叩關確認】\n{name}({code}) 近 15 分鐘測試 {t_p_label} 達 {touches} 次！\n現價：{curr_p}{tg_vol_str}")
                            st.session_state.tw_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = True
                    
                    if cond == ">=" and curr_p < t_p * 0.995: st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = False
                    if cond == "<=" and curr_p > t_p * 1.005: st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = False
                    if touches < 2: st.session_state.tw_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
            
            if triggered_msgs and is_tw_market_open:
                save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                send_telegram_alert(f"🚨【台股多重到價】\n{name}({code}) 已觸發：{'、'.join(triggered_msgs)}！\n現價：{curr_p}\n{tg_vol_str}")

            with st.container(border=True):
                my_p, my_l, my_dir, my_tt = float(stock.get('my_price', 0.0)), int(stock.get('my_lots', 1)), stock.get('my_dir', '作多'), stock.get('my_trade_type', '當沖')
                c_title, c_p, c_pnl, c_r1, c_s1, c_del = st.columns([2.5, 1.2, 1.5, 1.2, 1.2, 0.5])
                with c_title: st.markdown(f"#### {name}({code})")
                with c_p: st.metric("現價", f"{curr_p:.2f}", f"{curr_p - prev_p:.2f}")
                with c_pnl:
                    if my_p > 0:
                        if st.session_state.authenticated:
                            pnl = calc_tw_pnl(my_p, curr_p, my_l, my_dir, my_tt)
                            st.metric("未實現淨利", f"{pnl:,.0f} 元", f"{(pnl / (my_p * my_l * 1000)) * 100 if my_p > 0 else 0:+.2f}%", delta_color="normal" if pnl > 0 else "inverse")
                        else: st.metric("未實現淨利", "*** (鎖定)", "登入後查看", delta_color="off")
                    else: st.metric("未實現淨利", "--", delta_color="off")
                with c_r1: st.metric("壓力(R1)", f"{r1:.2f}", delta_color="off")
                with c_s1: st.metric("支撐(S1)", f"{s1:.2f}", delta_color="off")
                with c_del: st.button("❌", key=f"del_tw_{code}", on_click=cb_remove_tw, args=(idx,))
                
                if is_alert: st.error(f"🚨 **到價警示！** 現價 {curr_p} 已觸發設定目標")
                if vol_alert_msg: st.warning(f"📊 **動能偵測**：{vol_alert_msg} ({vol_info})")

                if ai_advice: st.markdown(f"<div style='color:#10b981;font-size:0.85rem;margin-top:-15px;margin-bottom:10px;'>{ai_advice}</div>", unsafe_allow_html=True)
                
                # 🚀 修復雷達卡死：帶入 API_KEY 作為參數
                corr_codes = get_correlated_stocks(code, name, API_KEY, is_us=False)
                if not corr_codes:
                    if API_KEY:
                        get_correlated_stocks.clear(code, name, API_KEY, is_us=False)
                        st.markdown("<div style='font-size:0.9rem; color:#94a3b8; margin-top:-10px; margin-bottom:10px;'>🔗 <b>族群聯動雷達：</b> 網路擁塞，AI 重新鎖定中... (稍後自動重試)</div>", unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='font-size:0.9rem; color:#ef4444; margin-top:-10px; margin-bottom:10px;'>🔗 <b>族群聯動雷達：</b> 需在左側輸入 API Key 以解鎖此功能。</div>", unsafe_allow_html=True)
                else:
                    corr_display = []
                    for i, c in enumerate(corr_codes):
                        c_name = all_stocks.get(c, c); icon = "👑" if i == 0 else "🔗"
                        cp, pp = live_price_dict.get(c, (None, None))
                        if cp is None: cp, pp = get_single_live_price(c, is_us=False)
                        if cp is not None and pp is not None and pp > 0:
                            diff = cp - pp; pct = (diff / pp) * 100; sign = "+" if diff > 0 else ""
                            color = '#ef4444' if diff > 0 else '#10b981' if diff < 0 else '#94a3b8'
                            corr_display.append(f"<b>{icon} {c_name}({c})</b> {cp:.2f} (<span style='color:{color}'>{sign}{diff:.2f}, {sign}{pct:.2f}%</span>)")
                        else: corr_display.append(f"<b>{icon} {c_name}({c})</b> 讀取中...")
                    st.markdown(f"<div style='font-size:0.95rem; margin-top:-10px; margin-bottom:10px; padding:8px; background-color:rgba(30,41,59,0.5); border-radius:8px;'>🔗 <b>高度聯動：</b> {' ｜ '.join(corr_display)}</div>", unsafe_allow_html=True)
                
                st.divider()

                # 🚀 修復排版對齊：統一將控制項拉出
                c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([1.5, 1, 1])
                with c_ctrl1: st.markdown("##### 📉 雙視角走勢與無縫 K 線圖")
                with c_ctrl2: tf_sel = st.selectbox("切換時區", ["1K", "5K", "15K", "日K"], index=3, key=f"tf_tw_{code}", label_visibility="collapsed")
                with c_ctrl3: layers_sel = st.multiselect("圖層開關", ["K棒", "MA3", "MA5", "MA10", "MA23"], default=["K棒", "MA3", "MA5", "MA10", "MA23"], key=f"layers_tw_{code}", label_visibility="collapsed")

                c_chart1, c_chart2 = st.columns(2)
                with c_chart1:
                    render_mini_chart(df_1m, cdp_nh, cdp_nl, alerts, is_us=False)
                with c_chart2:
                    render_kline_chart(tf_sel, df_1m, df_5k, df_15k, df_daily, curr_p, alerts, is_us=False, visible_layers=layers_sel, lookback=ui_lookback)

                st.markdown("---")
                if st.session_state.authenticated:
                    c_order1, c_order2, c_order3 = st.columns([2, 1, 1])
                    with c_order1: st.markdown(f"⚡ **雲端中控：火力打擊區** (張數設定: {my_l})")
                    with c_order2:
                        if st.button(f"🔴 閃電買進", key=f"fire_b_tw_{code}", use_container_width=True, type="primary"):
                            res = fire_order_to_agent(code, curr_p, "Buy", my_l)
                            if res.get('status') == 'success': st.toast(f"✅ 地端 Agent 收到買進指令: {code}", icon='🔥')
                            else: st.error(f"❌ {res.get('msg')}")
                    with c_order3:
                        if st.button(f"🟢 閃電賣出", key=f"fire_s_tw_{code}", use_container_width=True):
                            res = fire_order_to_agent(code, curr_p, "Sell", my_l)
                            if res.get('status') == 'success': st.toast(f"✅ 地端 Agent 收到賣出指令: {code}", icon='❄️')
                            else: st.error(f"❌ {res.get('msg')}")
                else:
                    st.info("🔒 閃電交易按鈕已隱藏。請在左側面板輸入 Google Authenticator 密碼以解鎖火力控制權限。")

                with st.expander("⚙️ 展開設定：持倉參數 & 專屬監控防線", expanded=False):
                    if st.session_state.authenticated:
                        st.markdown("##### 💰 持倉參數設定")
                        c_pos1, c_pos2, c_pos3, c_pos4 = st.columns(4)
                        with c_pos1: new_trade_type = st.selectbox("交易類型", ["當沖", "留倉"], index=0 if my_tt == "當沖" else 1, key=f"tt_tw_{code}")
                        with c_pos2: new_dir = st.selectbox("方向", ["作多", "作空"], index=0 if my_dir == "作多" else 1, key=f"dir_tw_{code}")
                        with c_pos3: new_price = st.number_input("成交均價", value=my_p, step=0.5, key=f"my_p_tw_{code}")
                        with c_pos4: new_lots = st.number_input("張數", value=my_l, min_value=1, step=1, key=f"my_l_tw_{code}")
                        
                        if new_trade_type != my_tt or new_dir != my_dir or new_price != my_p or new_lots != my_l:
                            st.session_state.tw_stocks[idx]['my_trade_type'] = new_trade_type
                            st.session_state.tw_stocks[idx]['my_dir'] = new_dir
                            st.session_state.tw_stocks[idx]['my_price'] = new_price
                            st.session_state.tw_stocks[idx]['my_lots'] = new_lots
                            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks); st.rerun()
                    else: st.warning("🔒 請先通過 2FA 雙因子認證才能修改機密部位參數。")

                    st.divider()
                    st.markdown("##### 🎯 專屬監控防線")
                    for a_idx, al in enumerate(alerts):
                        c_type, c_cond, c_inp, c_del_al = st.columns([3, 2, 3, 1])
                        opts = ["固定價格", "當日VWAP", "CDP(中價)", "CDP_NH(壓力)", "CDP_NL(支撐)"]
                        current_type = al.get('type', "固定價格") if al.get('type', "固定價格") in opts else "固定價格"
                        
                        with c_type:
                            new_type = st.selectbox("監控目標", opts, index=opts.index(current_type), key=f"type_tw_{code}_{a_idx}", label_visibility="collapsed")
                            if new_type != current_type: st.session_state.tw_stocks[idx]['alerts'][a_idx]['type'] = new_type; st.rerun()
                        with c_cond:
                            new_cond = st.selectbox("方向", [">= 漲破", "<= 跌破"], index=0 if al['cond'] == ">=" else 1, key=f"cond_tw_{code}_{a_idx}", label_visibility="collapsed")
                            new_cond_val = ">=" if ">=" in new_cond else "<="
                            if new_cond_val != al['cond']: st.session_state.tw_stocks[idx]['alerts'][a_idx]['cond'] = new_cond_val; st.rerun()
                        with c_inp:
                            if current_type == "固定價格":
                                new_t_price = st.number_input("警示價", value=float(al['price']), step=0.5, key=f"inp_{code}_{a_idx}", label_visibility="collapsed")
                                if new_t_price != al['price']: st.session_state.tw_stocks[idx]['alerts'][a_idx]['price'] = new_t_price; st.rerun()
                            else: st.markdown(f"<div style='padding-top:5px; color:#cbd5e1;'>追蹤現值: **{mas.get(current_type, 0.0):.2f}**</div>", unsafe_allow_html=True)
                        with c_del_al:
                            if st.button("🗑️", key=f"del_al_{code}_{a_idx}"): st.session_state.tw_stocks[idx]['alerts'].pop(a_idx); save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks); st.rerun()
                    
                    c_btn1, c_btn2, _ = st.columns([2, 2, 3])
                    with c_btn1:
                        if st.button("➕ 新增警示", key=f"add_al_tw_{code}"): st.session_state.tw_stocks[idx]['alerts'].append({"type": "固定價格", "price": 0.0, "cond": ">=", "triggered": False, "touch_2_triggered": False}); st.rerun()
                    with c_btn2:
                        if API_KEY and st.button("🤖 AI 算價", key=f"ai_p_{code}"):
                            with st.spinner("..."):
                                try:
                                    dir_str = '作多' if (alerts[0]['cond'] if alerts else ">=")=='>=' else '作空'
                                    res = ai_model.generate_content(f"針對台股 {code} 現價 {curr_p} 給當沖{dir_str}建議。嚴格回傳JSON格式：{{\"entry\": 進場價數字, \"target\": 停利目標價數字}}", generation_config=genai.types.GenerationConfig(temperature=0.0)).text
                                    match = re.search(r'\{.*\}', res, re.DOTALL)
                                    if match:
                                        data = json.loads(match.group(0))
                                        if alerts: st.session_state.tw_stocks[idx]['alerts'][0]['type'] = "固定價格"; st.session_state.tw_stocks[idx]['alerts'][0]['price'] = float(data['target'])
                                        st.session_state.tw_stocks[idx]['ai_advice'] = f"🤖 理想進場價: **{data['entry']}** | 停利目標: **{data['target']}**"
                                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks); st.rerun()
                                except: pass

# ====================
# 戰區 2：美股波段戰情
# ====================
with tab_us:
    if not st.session_state.us_stocks: st.info("請加入美股。")
    for idx, stock in enumerate(st.session_state.us_stocks):
        code = stock['code']; alerts = stock.get('alerts', []); ai_advice = stock.get('ai_advice', '')
        
        df_daily, suffix = get_historical_features(code, is_us=True)
        df_1m_us = get_realtime_tick(code, suffix)
        df_5k = get_kline_data(code, suffix, '5m', t5_key)
        df_15k = get_kline_data(code, suffix, '15m', t15_key)
        
        mas = {}; cdp_nh = cdp_nl = 0.0
        if not df_1m_us.empty and not df_daily.empty:
            df_1m_us['Typical_Price'] = (df_1m_us['High'] + df_1m_us['Low'] + df_1m_us['Close']) / 3
            df_1m_us['Cum_Vol'] = df_1m_us['Volume'].cumsum().replace(0, np.nan)
            df_1m_us['Cum_PV'] = (df_1m_us['Typical_Price'] * df_1m_us['Volume']).cumsum()
            df_1m_us['VWAP'] = (df_1m_us['Cum_PV'] / df_1m_us['Cum_Vol']).bfill().fillna(df_1m_us['Close'])
            mas['當日VWAP'] = df_1m_us['VWAP'].iloc[-1]

        live_cp, live_pp = live_price_dict.get(code, (None, None))
        if live_cp is None: live_cp, live_pp = get_single_live_price(code, is_us=True)
        
        if live_cp is not None and not df_daily.empty:
            curr_p = live_cp; df_daily_rt = df_daily.copy()
            if not df_daily_rt.empty:
                df_daily_rt.iloc[-1, df_daily_rt.columns.get_loc('Close')] = curr_p
                mas['日線3MA'] = df_daily_rt['Close'].tail(3).mean(); mas['日線5MA'] = df_daily_rt['Close'].tail(5).mean()
                mas['日線10MA'] = df_daily_rt['Close'].tail(10).mean(); mas['日線23MA'] = df_daily_rt['Close'].tail(23).mean()
            
            r1, s1 = 0.0, 0.0
            if len(df_daily) >= 2:
                y_high, y_low, y_close = df_daily['High'].iloc[-2], df_daily['Low'].iloc[-2], df_daily['Close'].iloc[-2]
                pivot = (y_high + y_low + y_close) / 3
                r1 = (2 * pivot) - y_low; s1 = (2 * pivot) - y_high
                cdp = (y_high + y_low + 2 * y_close) / 4
                cdp_nh = (2 * cdp) - y_low; cdp_nl = (2 * cdp) - y_high
                mas['CDP(中價)'] = cdp; mas['CDP_NH(压力)'] = cdp_nh; mas['CDP_NL(支撑)'] = cdp_nl
            
            is_alert = False; triggered_msgs = []
            for a_idx, al in enumerate(alerts):
                al_type = al.get('type', '固定價格')
                t_p = al['price'] if al_type == '固定價格' else mas.get(al_type, 0.0)
                cond = al['cond']
                
                if t_p > 0:
                    t_p_label = f"${t_p}" if al_type == '固定價格' else f"{al_type} (${t_p:.2f})"
                    if cond == ">=" and curr_p >= t_p:
                        is_alert = True
                        if not al['triggered']: triggered_msgs.append(f"漲破 {t_p_label}"); st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = True
                    elif cond == "<=" and curr_p <= t_p:
                        is_alert = True
                        if not al['triggered']: triggered_msgs.append(f"跌破 {t_p_label}"); st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = True
                    
                    touches = 0
                    if not df_1m_us.empty and len(df_1m_us) >= 15:
                        if cond == ">=": touches = max((df_1m_us['High'].tail(15) >= t_p).sum(), 1 if curr_p >= t_p else 0)
                        else: touches = max((df_1m_us['Low'].tail(15) <= t_p).sum(), 1 if curr_p <= t_p else 0)

                        if touches >= 2 and not al.get('touch_2_triggered', False):
                            send_telegram_alert(f"⚠️ 🦅【美股叩關確認】\n{code} 近 15 分鐘測試 {t_p_label} 達 {touches} 次！\n方向：{'漲破' if cond=='>=' else '跌破'}\n現價：${curr_p}")
                            st.session_state.us_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = True

                    if cond == ">=" and curr_p < t_p * 0.995: st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = False
                    if cond == "<=" and curr_p > t_p * 1.005: st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = False
                    if touches < 2: st.session_state.us_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False

            if triggered_msgs:
                save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                send_telegram_alert(f"🦅 🚨【美股多重到價】\n{code} 已觸發：{'、'.join(triggered_msgs)}！\n現價：${curr_p}")

            with st.container(border=True):
                my_p_us, my_l_us, my_dir_us = float(stock.get('my_price', 0.0)), int(stock.get('my_shares', 10)), stock.get('my_dir', '作多')
                c_title, c_p, c_pnl, c_r1, c_s1, c_del = st.columns([2.5, 1.2, 1.5, 1.2, 1.2, 0.5])
                with c_title: st.markdown(f"#### 🦅 {code}")
                with c_p: st.metric("收盤現價", f"${curr_p:.2f}", f"${curr_p - live_pp:.2f}" if live_pp else "--")
                with c_pnl:
                    if my_p_us > 0:
                        if st.session_state.authenticated:
                            pnl_us = (curr_p - my_p_us) * my_l_us if my_dir_us == "作多" else (my_p_us - curr_p) * my_l_us
                            st.metric("未實現損益", f"${pnl_us:,.2f}", f"{(pnl_us / (my_p_us * my_l_us)) * 100 if my_p_us > 0 else 0:+.2f}%", delta_color="normal" if pnl_us > 0 else "inverse")
                        else: st.metric("未實現損益", "*** (鎖定)", "登入後查看", delta_color="off")
                    else: st.metric("未實現損益", "--", delta_color="off")
                with c_r1: st.metric("壓力(R1)", f"${r1:.2f}", delta_color="off")
                with c_s1: st.metric("支撐(S1)", f"${s1:.2f}", delta_color="off")
                with c_del: st.button("❌", key=f"del_us_{code}", on_click=cb_remove_us, args=(idx,))
                
                if is_alert: st.error(f"🚨 **到價警示！** 現價 ${curr_p} 已觸發設定目標")
                if ai_advice: st.markdown(f"<div style='color:#10b981;font-size:0.85rem;margin-top:-15px;margin-bottom:10px;'>{ai_advice}</div>", unsafe_allow_html=True)
                
                # 🚀 修復雷達卡死：帶入 API_KEY 作為參數
                corr_codes = get_correlated_stocks(code, code, API_KEY, is_us=True)
                if not corr_codes:
                    if API_KEY:
                        get_correlated_stocks.clear(code, code, API_KEY, is_us=True)
                        st.markdown("<div style='font-size:0.9rem; color:#94a3b8; margin-top:-10px; margin-bottom:10px;'>🔗 <b>族群聯動雷達：</b> 網路擁塞，AI 重新鎖定中... (稍後自動重試)</div>", unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='font-size:0.9rem; color:#ef4444; margin-top:-10px; margin-bottom:10px;'>🔗 <b>族群聯動雷達：</b> 需在左側輸入 API Key 以解鎖此功能。</div>", unsafe_allow_html=True)
                else:
                    corr_display = []
                    for i, c in enumerate(corr_codes):
                        icon = "👑" if i == 0 else "🔗"
                        cp, pp = live_price_dict.get(c, (None, None))
                        if cp is None: cp, pp = get_single_live_price(c, is_us=True)
                        if cp is not None and pp is not None and pp > 0:
                            diff = cp - pp; pct = (diff / pp) * 100; sign = "+" if diff > 0 else ""
                            color = '#10b981' if diff > 0 else '#ef4444' if diff < 0 else '#94a3b8'
                            corr_display.append(f"<b>{icon} {c}</b> {cp:.2f} (<span style='color:{color};'>{sign}{diff:.2f}, {sign}{pct:.2f}%</span>)")
                        else: corr_display.append(f"<b>{icon} {c}</b> 讀取中...")
                    st.markdown(f"<div style='font-size:0.95rem; margin-top:-10px; margin-bottom:10px; padding:8px; background-color:rgba(30,41,59,0.5); border-radius:8px;'>🔗 <b>高度聯動：</b> {' ｜ '.join(corr_display)}</div>", unsafe_allow_html=True)

                st.divider()
                
                # 🚀 修復排版對齊：統一將控制項拉出
                c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([1.5, 1, 1])
                with c_ctrl1: st.markdown("##### 📉 雙視角走勢與無縫 K 線圖")
                with c_ctrl2: tf_sel = st.selectbox("切換時區", ["1K", "5K", "15K", "日K"], index=3, key=f"tf_us_{code}", label_visibility="collapsed")
                with c_ctrl3: layers_sel = st.multiselect("圖層開關", ["K棒", "MA3", "MA5", "MA10", "MA23"], default=["K棒", "MA3", "MA5", "MA10", "MA23"], key=f"layers_us_{code}", label_visibility="collapsed")

                c_chart1, c_chart2 = st.columns(2)
                with c_chart1:
                    render_mini_chart(df_1m_us, cdp_nh, cdp_nl, alerts, is_us=True)
                with c_chart2:
                    render_kline_chart(tf_sel, df_1m_us, df_5k, df_15k, df_daily, curr_p, alerts, is_us=True, visible_layers=layers_sel, lookback=ui_lookback)

                st.markdown("---")
                if st.session_state.authenticated:
                    c_order1, c_order2, c_order3 = st.columns([2, 1, 1])
                    with c_order1: st.markdown(f"⚡ **雲端中控：火力打擊區** (股數設定: {my_l_us})")
                    with c_order2:
                        if st.button(f"🔴 閃電買進", key=f"fire_b_us_{code}", use_container_width=True, type="primary"):
                            res = fire_order_to_agent(code, curr_p, "Buy", my_l_us)
                            if res.get('status') == 'success': st.toast(f"✅ 地端 Agent 收到買進指令: {code}", icon='🔥')
                            else: st.error(f"❌ {res.get('msg')}")
                    with c_order3:
                        if st.button(f"🟢 閃電賣出", key=f"fire_s_us_{code}", use_container_width=True):
                            res = fire_order_to_agent(code, curr_p, "Sell", my_l_us)
                            if res.get('status') == 'success': st.toast(f"✅ 地端 Agent 收到賣出指令: {code}", icon='❄️')
                            else: st.error(f"❌ {res.get('msg')}")
                else:
                    st.info("🔒 閃電交易按鈕已隱藏。請在左側面板輸入 Google Authenticator 密碼以解鎖火力控制權限。")

                with st.expander("⚙️ 展開設定：持倉參數 & 專屬監控防線", expanded=False):
                    if st.session_state.authenticated:
                        st.markdown("##### 💰 美股持倉參數")
                        c_pos1, c_pos2, c_pos3 = st.columns(3)
                        with c_pos1: new_dir = st.selectbox("方向", ["作多", "作空"], index=0 if my_dir_us == "作多" else 1, key=f"dir_us_{code}")
                        with c_pos2: new_price = st.number_input("成交均價", value=my_p_us, step=1.0, key=f"my_p_us_{code}")
                        with c_pos3: new_shares = st.number_input("股數", value=my_l_us, min_value=1, step=1, key=f"my_l_us_{code}")
                        
                        if new_dir != my_dir_us or new_price != my_p_us or new_shares != my_l_us:
                            st.session_state.us_stocks[idx]['my_dir'] = new_dir; st.session_state.us_stocks[idx]['my_price'] = new_price; st.session_state.us_stocks[idx]['my_shares'] = new_shares
                            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks); st.rerun()
                    else: st.warning("🔒 請先通過 2FA 雙因子認證才能修改機密部位參數。")

                    st.divider()
                    st.markdown("##### 🎯 專屬監控防線")
                    for a_idx, al in enumerate(alerts):
                        c_type, c_cond, c_inp, c_del_al = st.columns([3, 2, 3, 1])
                        opts = ["固定價格", "當日VWAP", "CDP(中價)", "CDP_NH(壓力)", "CDP_NL(支撐)"]
                        current_type = al.get('type', "固定價格") if al.get('type', "固定價格") in opts else "固定價格"
                        
                        with c_type:
                            new_type = st.selectbox("監控目標", opts, index=opts.index(current_type), key=f"type_us_{code}_{a_idx}", label_visibility="collapsed")
                            if new_type != current_type: st.session_state.us_stocks[idx]['alerts'][a_idx]['type'] = new_type; st.rerun()
                        with c_cond:
                            new_cond = st.selectbox("方向", [">= 漲破", "<= 跌破"], index=0 if al['cond'] == ">=" else 1, key=f"cond_us_{code}_{a_idx}", label_visibility="collapsed")
                            new_cond_val = ">=" if ">=" in new_cond else "<="
                            if new_cond_val != al['cond']: st.session_state.us_stocks[idx]['alerts'][a_idx]['cond'] = new_cond_val; st.rerun()
                        with c_inp:
                            if current_type == "固定價格":
                                new_t_price = st.number_input("警示價", value=float(al['price']), step=1.0, key=f"inp_us_{code}_{a_idx}", label_visibility="collapsed")
                                if new_t_price != al['price']: st.session_state.us_stocks[idx]['alerts'][a_idx]['price'] = new_t_price; st.rerun()
                            else: st.markdown(f"<div style='padding-top:5px; color:#cbd5e1;'>自動追蹤現值: **${mas.get(current_type, 0.0):.2f}**</div>", unsafe_allow_html=True)
                        with c_del_al:
                            if st.button("🗑️", key=f"del_al_us_{code}_{a_idx}"): st.session_state.us_stocks[idx]['alerts'].pop(a_idx); save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks); st.rerun()

                    c_btn1, c_btn2, _ = st.columns([2, 2, 3])
                    with c_btn1:
                        if st.button("➕ 新增警示", key=f"add_al_us_{code}"): st.session_state.us_stocks[idx]['alerts'].append({"type": "固定價格", "price": 0.0, "cond": ">=", "triggered": False, "touch_2_triggered": False}); st.rerun()
                    with c_btn2:
                        if API_KEY and st.button("🤖 AI 算價", key=f"ai_p_us_{code}"):
                            with st.spinner("..."):
                                try:
                                    dir_str = '作多' if (alerts[0]['cond'] if alerts else ">=")=='>=' else '作空'
                                    res = ai_model.generate_content(f"針對美股 {code} 現價 {curr_p} 給波段{dir_str}建議。嚴格回傳JSON格式：{{\"entry\": 進場價數字, \"target\": 停利目標價數字}}", generation_config=genai.types.GenerationConfig(temperature=0.0)).text
                                    match = re.search(r'\{.*\}', res, re.DOTALL)
                                    if match:
                                        data = json.loads(match.group(0))
                                        if alerts: st.session_state.us_stocks[idx]['alerts'][0]['type'] = "固定價格"; st.session_state.us_stocks[idx]['alerts'][0]['price'] = float(data['target'])
                                        st.session_state.us_stocks[idx]['ai_advice'] = f"🤖 理想進場價: **${data['entry']}** | 停利目標: **${data['target']}**"
                                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks); st.rerun()
                                except: pass

# ====================
# 戰區 3：10年核心資產
# ====================
with tab_core:
    st.markdown("### 🐢 穩健增長：20萬 TWD 核心配置計畫")
    for asset in st.session_state.core_assets:
        code, is_us = asset['code'], asset['is_us']
        df_daily, _ = get_historical_features(code, is_us=is_us)
        if not df_daily.empty:
            curr_p = df_daily['Close'].iloc[-1]
            with st.container(border=True):
                c1, c2, c3 = st.columns([1.5, 1.5, 1])
                c1.markdown(f"**{'🇺🇸' if is_us else '🇹🇼'} {code}** | 現價: {curr_p:.2f}")
                c2.metric("季線 (60MA)", f"{df_daily['Close'].tail(60).mean():.2f}")
                c3.metric("RSI", f"{df_daily['RSI'].iloc[-1]:.1f}")

if auto_refresh: time.sleep(3); st.rerun()
