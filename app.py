import streamlit as st
import pandas as pd
import google.generativeai as genai
import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
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

# ==========================================
# 🚀 效能優化：全域連線池
# ==========================================
http_session = requests.Session()
retries = Retry(total=2, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
http_session.mount('https://', HTTPAdapter(max_retries=retries, pool_connections=100, pool_maxsize=100))
http_session.mount('http://', HTTPAdapter(max_retries=retries, pool_connections=100, pool_maxsize=100))

# --- 🔐 雙因子認證 (2FA) 金鑰設定 ---
TWO_FA_SECRET = "JBSWY3DPEHPK3PXP" 

if 'authenticated' not in st.session_state: st.session_state.authenticated = False

# --- 🎨 首席設計師的 CSS 視覺美化 ---
st.markdown("""
<style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    h1 { background: -webkit-linear-gradient(45deg, #00f2fe, #4facfe); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 900; letter-spacing: 1px; text-shadow: 0px 2px 4px rgba(0,0,0,0.1); }
    section[data-testid="stSidebar"] { background-color: #0f172a !important; border-right: 1px solid #1e293b; }
    section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] span, section[data-testid="stSidebar"] div.stMarkdown { color: #ffffff !important; font-weight: 600 !important; text-shadow: 0px 1px 2px rgba(0,0,0,0.8); }
    section[data-testid="stSidebar"] div[data-baseweb="select"] span, section[data-testid="stSidebar"] div[data-baseweb="select"] li { color: #0f172a !important; text-shadow: none !important; }
    section[data-testid="stSidebar"] input { color: #0f172a !important; background-color: #ffffff !important; text-shadow: none !important; }
    div[data-testid="stMetricValue"] { font-size: 1.5rem; font-weight: 700; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
    label[data-testid="stMetricLabel"] p { font-weight: 600; color: #8b9bb4 !important; font-size: 0.85rem; }
    div[data-testid="stVerticalBlock"] div[style*="border"] { border-radius: 12px !important; border: 1px solid #2d3748 !important; background-color: rgba(17, 24, 39, 0.4) !important; transition: transform 0.2s ease-in-out; }
    div[data-testid="stVerticalBlock"] div[style*="border"]:hover { transform: translateY(-2px); }
    button[kind="primary"] { background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); color: white !important; font-weight: 600; border: none; border-radius: 8px; }
    button[kind="primary"]:hover { background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); }
</style>
""", unsafe_allow_html=True)

# --- 1. 引擎與雲地通訊設定 ---
API_KEY = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
if API_KEY: genai.configure(api_key=API_KEY); ai_model = genai.GenerativeModel('gemini-2.5-flash')
TG_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
TG_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID", ""))

NGROK_BASE_URL = "https://hitless-axel-misapply.ngrok-free.dev" 
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"
if 'agent_url' not in st.session_state: st.session_state.agent_url = NGROK_BASE_URL

def send_telegram_alert(msg):
    st.toast(f"🔔 內部觸發警報: {msg[:25]}...", icon="🚨")
    if not TG_BOT_TOKEN or not TG_CHAT_ID: return
    try: http_session.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", json={"chat_id": TG_CHAT_ID, "text": msg}, timeout=5)
    except Exception: pass

def fire_order_to_agent(code, price, action, qty=1):
    payload = {"secret": WEBHOOK_SECRET, "ticker": code, "action": action.lower(), "price": price, "qty": qty}
    try:
        response = http_session.post(f"{st.session_state.agent_url.rstrip('/')}/api/order", json=payload, headers={"ngrok-skip-browser-warning": "true"}, timeout=3)
        return {"status": "success"} if response.status_code == 200 else {"status": "error", "msg": f"地端回應錯誤碼: {response.status_code}"}
    except Exception: return {"status": "error", "msg": "無法連線至地端 Agent"}

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
        if s['code'] == code: exists = True; break
    if not exists:
        st.session_state.tw_stocks.append({"code": code, "name": name, "alerts": [{"type": "固定價格", "price": float(target_price), "cond": condition, "triggered": False, "touch_2_triggered": False, "auto_trade": False, "require_retest": False, "trade_fired": False}], "ai_advice": "", "vol_alert_triggered": False, "my_trade_type": "當沖", "my_price": 0.0, "my_lots": 1, "my_dir": "作多", "stop_loss": 0.0, "sl_triggered": False})
    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

def cb_add_us(code, name, target_price=0.0, condition=">="):
    exists = False
    for s in st.session_state.us_stocks:
        if s['code'] == code: exists = True; break
    if not exists:
        st.session_state.us_stocks.append({"code": code, "name": name, "alerts": [{"type": "固定價格", "price": float(target_price), "cond": condition, "triggered": False, "touch_2_triggered": False, "auto_trade": False, "require_retest": False, "trade_fired": False}], "ai_advice": "", "my_price": 0.0, "my_shares": 10, "my_dir": "作多", "stop_loss": 0.0, "sl_triggered": False})
    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

def cb_remove_tw(idx): st.session_state.tw_stocks.pop(idx); save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
def cb_remove_us(idx): st.session_state.us_stocks.pop(idx); save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
def cb_clear_all(): st.session_state.tw_stocks = []; st.session_state.us_stocks = []; st.session_state.ai_report_daytrade = None; st.session_state.ai_report_overnight = None; st.session_state.ai_report_swing = None; st.session_state.ai_report_us = None; save_watchlist([], [])

def cb_ai_calc_price_tw(idx, code, curr_p):
    if not API_KEY: return
    try:
        res = ai_model.generate_content(f"【系統 API 測試模式】針對台股代碼 {code} (現價 {curr_p}) 進行數學運算。嚴格回傳JSON格式：{{\"entry\": 數字, \"target\": 數字}}", generation_config=genai.types.GenerationConfig(temperature=0.0)).text
        match = re.search(r'\{.*\}', res, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            if st.session_state.tw_stocks[idx].get('alerts'): 
                st.session_state.tw_stocks[idx]['alerts'][0].update({'type': "固定價格", 'price': float(data['target']), 'triggered': False, 'touch_2_triggered': False, 'trade_fired': False})
            st.session_state.tw_stocks[idx]['ai_advice'] = f"🤖 理想進場價: **{data['entry']}** | 停利目標: **{data['target']}**"
            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
    except: pass

if 'initialized' not in st.session_state:
    data = load_watchlist()
    st.session_state.tw_stocks = data.get("tw", [])
    st.session_state.us_stocks = data.get("us", [])
    for lst in [st.session_state.tw_stocks, st.session_state.us_stocks]:
        for s in lst:
            if 'stop_loss' not in s: s['stop_loss'] = 0.0
            if 'sl_triggered' not in s: s['sl_triggered'] = False
            if 'alerts' not in s: s['alerts'] = [{"type": "固定價格", "price": s.get('target_price', 0.0), "cond": s.get('condition', '>='), "triggered": s.get('alert_triggered', False), "touch_2_triggered": False, "auto_trade": False, "require_retest": False, "trade_fired": False}]
            for al in s['alerts']:
                for key, default in [('touch_2_triggered', False), ('type', "固定價格"), ('auto_trade', False), ('require_retest', False), ('trade_fired', False)]:
                    if key not in al: al[key] = default
    st.session_state.ai_report_daytrade = None; st.session_state.ai_report_overnight = None; st.session_state.ai_report_swing = None; st.session_state.ai_report_us = None
    st.session_state.core_assets = [{"code": "0050", "is_us": False}, {"code": "009816", "is_us": False}, {"code": "QQQM", "is_us": True}]
    if 'market_alert_flags' not in st.session_state: st.session_state.market_alert_flags = {}
    st.session_state.initialized = True

# --- 2. 數據引擎 ---
@st.cache_data(ttl=86400, show_spinner=False)
def get_full_stock_db():
    db = {}
    try:
        res = http_session.get("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo", timeout=10, headers={"User-Agent": "Mozilla/5.0"}).json()
        if res.get('msg') == 'success':
            for item in res['data']: db[str(item['stock_id'])] = str(item['stock_name'])
    except: pass
    if len(db) < 100: get_full_stock_db.clear()
    return db

@st.cache_data(ttl=1, max_entries=10, show_spinner=False)
def get_index_data_engine(symbol, cache_buster):
    df_spark = pd.DataFrame(); q_curr = q_prev = None
    for interval, rng in [('1m', '1d'), ('5m', '5d')]:
        try:
            res = http_session.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={rng}&_t={int(time.time())}", headers={"User-Agent": "Mozilla/5.0"}, timeout=2).json()
            if result := res.get('chart', {}).get('result', []):
                if timestamp := result[0].get('timestamp'):
                    df_all = pd.DataFrame({'Close': result[0]['indicators']['quote'][0]['close']}, index=pd.to_datetime(timestamp, unit='s', utc=True)).dropna()
                    if not df_all.empty:
                        df_all['Date'] = df_all.index.tz_convert('Asia/Taipei').date
                        df_spark = df_all[df_all['Date'] == df_all['Date'].iloc[-1]].copy()
                        df_spark.drop(columns=['Date'], inplace=True)
                        q_curr = df_spark['Close'].iloc[-1]; q_prev = result[0].get('meta', {}).get('chartPreviousClose', result[0].get('meta', {}).get('previousClose'))
                        break 
        except: continue
    if symbol == '^TWOII' and df_spark.empty:
        try:
            res = http_session.get(f"https://query1.finance.yahoo.com/v8/finance/chart/006201.TWO?interval=1m&range=1d&_t={int(time.time())}", headers={"User-Agent": "Mozilla/5.0"}, timeout=2).json()
            if result := res.get('chart', {}).get('result', []):
                if result[0].get('timestamp'):
                    df_all = pd.DataFrame({'Close': result[0]['indicators']['quote'][0]['close']}, index=pd.to_datetime(result[0]['timestamp'], unit='s', utc=True)).dropna()
                    if not df_all.empty:
                        df_all['Date'] = df_all.index.tz_convert('Asia/Taipei').date
                        df_spark = df_all[df_all['Date'] == df_all['Date'].iloc[-1]].copy()
                        df_spark.drop(columns=['Date'], inplace=True)
        except: pass
    if q_curr is None or q_prev is None:
        try:
            res_list = http_session.get(f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}&_t={int(time.time())}", headers={"User-Agent": "Mozilla/5.0"}, timeout=2).json().get('quoteResponse', {}).get('result', [])
            if res_list:
                if q_curr is None: q_curr = res_list[0].get('regularMarketPrice')
                if q_prev is None: q_prev = res_list[0].get('regularMarketPreviousClose')
        except: pass
        if q_curr is None:
            try:
                closes = http_session.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d", headers={"User-Agent": "Mozilla/5.0"}, timeout=2).json()['chart']['result'][0]['indicators']['quote'][0]['close']
                valid_closes = [c for c in closes if c is not None]
                if valid_closes:
                    q_curr = valid_closes[-1]
                    if len(valid_closes) > 1 and q_prev is None: q_prev = valid_closes[-2]
            except: pass
    if symbol == '^TWOII' and not df_spark.empty and q_prev: df_spark['Close'] = df_spark['Close'] * (q_prev / df_spark['Close'].iloc[0])
    return df_spark, q_curr, q_prev if q_prev is not None else q_curr

@st.cache_data(ttl=300)
def get_index_mas(code='^TWII'):
    try:
        closes = http_session.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{code}?interval=1d&range=6mo", headers={"User-Agent": "Mozilla/5.0"}, timeout=5).json()['chart']['result'][0]['indicators']['quote'][0]['close']
        df = pd.DataFrame({'Close': closes}).dropna()
        if len(df) >= 60: return {'3日線': df['Close'].tail(3).mean(), '5日線': df['Close'].tail(5).mean(), '月線(20MA)': df['Close'].tail(20).mean(), '季線(60MA)': df['Close'].tail(60).mean()}
    except: pass
    return None

@st.cache_data(show_spinner=False)
def get_kline_data(code, suffix, interval, time_key):
    try:
        res = http_session.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval={interval}&range={'60d' if interval in ['5m', '15m'] else '5d'}", headers={"User-Agent": "Mozilla/5.0"}, timeout=3).json()
        idx = pd.to_datetime(res['chart']['result'][0]['timestamp'], unit='s', utc=True)
        return pd.DataFrame({'Open': res['chart']['result'][0]['indicators']['quote'][0]['open'], 'High': res['chart']['result'][0]['indicators']['quote'][0]['high'], 'Low': res['chart']['result'][0]['indicators']['quote'][0]['low'], 'Close': res['chart']['result'][0]['indicators']['quote'][0]['close'], 'Volume': res['chart']['result'][0]['indicators']['quote'][0]['volume']}, index=idx).dropna()
    except: return pd.DataFrame()

@st.cache_data(ttl=900)
def get_historical_features(code, is_us=False):
    for suffix in [""] if is_us else [".TW", ".TWO"]:
        try:
            res_1d_data = http_session.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range=2y", headers={"User-Agent": "Mozilla/5.0"}, timeout=5).json().get('chart', {}).get('result', [])[0]
            df_daily = pd.DataFrame({'Open': res_1d_data['indicators']['quote'][0]['open'], 'High': res_1d_data['indicators']['quote'][0]['high'], 'Low': res_1d_data['indicators']['quote'][0]['low'], 'Close': res_1d_data['indicators']['quote'][0]['close'], 'Volume': res_1d_data['indicators']['quote'][0]['volume']}, index=pd.to_datetime(res_1d_data['timestamp'], unit='s', utc=True)).dropna()
            delta = df_daily['Close'].diff()
            df_daily['RSI'] = 100 - (100 / (1 + (delta.where(delta > 0, 0)).rolling(window=14).mean() / ((-delta.where(delta < 0, 0)).rolling(window=14).mean() + 1e-9)))
            return df_daily, suffix
        except: continue
    return pd.DataFrame(), ""

@st.cache_data(ttl=1, max_entries=100, show_spinner=False)
def get_realtime_tick_and_price(code, suffix, cache_buster):
    if suffix is None: return pd.DataFrame(), None, None
    for rng in ['1d', '5d']:
        try:
            result = http_session.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1m&range={rng}&_t={int(time.time())}", headers={"User-Agent": "Mozilla/5.0"}, timeout=3).json().get('chart', {}).get('result', [])
            if result:
                meta = result[0].get('meta', {})
                curr_p, prev_p = meta.get('regularMarketPrice'), meta.get('chartPreviousClose', meta.get('previousClose'))
                if result[0].get('timestamp'):
                    q = result[0]['indicators']['quote'][0]
                    return pd.DataFrame({'Open': q['open'], 'High': q['high'], 'Low': q['low'], 'Close': q['close'], 'Volume': q.get('volume', [0]*len(q['close']))}, index=pd.to_datetime(result[0]['timestamp'], unit='s', utc=True)).dropna(), curr_p, prev_p
                return pd.DataFrame(), curr_p, prev_p
        except: pass
    return pd.DataFrame(), None, None

@st.cache_data(ttl=1, max_entries=10, show_spinner=False)
def get_bulk_live_prices(tw_codes, us_codes, cache_buster):
    symbols = [f"{c}.TW" for c in tw_codes] + [f"{c}.TWO" for c in tw_codes] + list(us_codes)
    if not symbols: return {}
    prices = {}
    for i in range(0, len(symbols), 15):
        try:
            for r in http_session.get(f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={','.join(symbols[i:i + 15])}&_t={int(time.time())}", headers={"User-Agent": "Mozilla/5.0"}, timeout=3).json().get('quoteResponse', {}).get('result', []):
                if (curr_p := r.get('regularMarketPrice')) is not None: prices[r.get('symbol', '').replace('.TW', '').replace('.TWO', '')] = (curr_p, r.get('regularMarketPreviousClose', curr_p))
        except: pass
    return prices

@st.cache_data(ttl=1, max_entries=100, show_spinner=False)
def get_single_live_price(code, is_us, cache_buster):
    for suf in [""] if is_us else [".TW", ".TWO"]:
        try:
            res_list = http_session.get(f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={code}{suf}&_t={int(time.time())}", headers={"User-Agent": "Mozilla/5.0"}, timeout=2).json().get('quoteResponse', {}).get('result', [])
            if res_list and (cp := res_list[0].get('regularMarketPrice')) is not None: return cp, res_list[0].get('regularMarketPreviousClose', cp)
        except: pass
    return None, None

@st.cache_data(ttl=86400, show_spinner=False)
def get_correlated_stocks(code, name, key_hash, is_us=False):
    if not key_hash: return []
    try: genai.configure(api_key=key_hash)
    except: pass
    for attempt in range(2):
        try:
            codes = re.findall(r'[A-Z]+' if is_us else r'\d{4,}', genai.GenerativeModel('gemini-2.5-flash').generate_content(f"針對 {'美股' if is_us else '台股'} {name}({code})，找出 3 檔同產業高連動的股票。嚴格規定：只能輸出代碼。請絕對只回傳股票代碼，用逗號隔開。", generation_config=genai.types.GenerationConfig(temperature=0.1), request_options={"timeout": 8.0}).text.upper() if is_us else genai.GenerativeModel('gemini-2.5-flash').generate_content(f"針對 {'美股' if is_us else '台股'} {name}({code})，找出 3 檔同產業高連動的股票。嚴格規定：只能輸出代碼。請絕對只回傳股票代碼，用逗號隔開。", generation_config=genai.types.GenerationConfig(temperature=0.1), request_options={"timeout": 8.0}).text)
            seen = set(); uniq = [c for c in codes if not (c in seen or seen.add(c) or c == code)]
            if uniq: return uniq[:3]
        except: time.sleep(1)
    return []

# --- 📊 視覺圖表引擎 ---
def render_index_sparkline(df, prev_close, curr_p, market_type="TW"):
    if df.empty or prev_close is None: return
    tz_str = 'Asia/Taipei' if market_type == "TW" else 'America/New_York'
    df_chart = df.copy()
    df_chart.index = df_chart.index.tz_convert(tz_str)
    
    now_time = pd.Timestamp.now(tz=tz_str).floor('min')
    today_date = now_time.date()
    
    start_time = pd.Timestamp(datetime.datetime.combine(today_date, datetime.time(9, 0 if market_type == "TW" else 30))).tz_localize(tz_str)
    end_time = pd.Timestamp(datetime.datetime.combine(today_date, datetime.time(13 if market_type == "TW" else 16, 30 if market_type == "TW" else 0))).tz_localize(tz_str)
    
    df_chart = df_chart[df_chart.index >= start_time]
    if not df_chart.empty: df_chart = df_chart.resample('1min').ffill()
    df_chart = df_chart.reindex(pd.date_range(start=start_time, end=end_time, freq='1min'))
    
    plot_now = now_time if now_time <= end_time else end_time
    plot_now = plot_now if plot_now >= start_time else start_time
    past_mask = df_chart.index <= plot_now
    df_chart.loc[past_mask, 'Close'] = df_chart.loc[past_mask, 'Close'].ffill()
    
    if curr_p is not None:
        last_valid_idx = df_chart.loc[past_mask, 'Close'].last_valid_index()
        if last_valid_idx is not None:
            df_chart.loc[last_valid_idx:plot_now, 'Close'] = df_chart.loc[last_valid_idx, 'Close']
            df_chart.loc[plot_now, 'Close'] = curr_p
        else:
            df_chart.loc[plot_now, 'Close'] = curr_p
                
    df_chart = df_chart.dropna(subset=['Close'])
    if df_chart.empty: return
        
    df_chart = df_chart.reset_index().rename(columns={'index': 'Time'})
    df_chart['x_idx'] = np.arange(len(df_chart))
    
    color = ("#ef4444" if market_type == "TW" else "#10b981") if curr_p >= prev_close else ("#10b981" if market_type == "TW" else "#ef4444")
    y_min, y_max = min(df_chart['Close'].min(), prev_close), max(df_chart['Close'].max(), prev_close)
    buffer = (y_max - y_min) * 0.05 if y_max != y_min else curr_p * 0.001
    
    base = alt.Chart(df_chart).encode(x=alt.X('x_idx:Q', scale=alt.Scale(domain=[0, len(pd.date_range(start=start_time, end=end_time, freq='1min'))-1]), axis=alt.Axis(labels=False, ticks=False, grid=False, title='')))
    line = base.mark_line(color=color, strokeWidth=2).encode(y=alt.Y('Close:Q', scale=alt.Scale(domain=[y_min-buffer, y_max+buffer], zero=False), axis=alt.Axis(labels=False, ticks=False, grid=False, title='')))
    rule = alt.Chart(pd.DataFrame({'p': [prev_close]})).mark_rule(color='#94a3b8', strokeDash=[3,3], strokeWidth=1.5).encode(y='p:Q')
    area = base.mark_area(color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color=color, offset=0), alt.GradientStop(color='rgba(0,0,0,0)', offset=1)], x1=1, x2=1, y1=0, y2=1), opacity=0.3).encode(y=alt.Y('Close:Q', scale=alt.Scale(domain=[y_min-buffer, y_max+buffer], zero=False)), y2=alt.datum(y_min-buffer))
    st.altair_chart(alt.layer(rule, area, line).properties(height=80), use_container_width=True)

def render_mini_chart(df_1m, cdp_nh, cdp_nl, curr_p, alerts=[], is_us=False):
    if df_1m.empty: return
    tz_str = 'America/New_York' if is_us else 'Asia/Taipei'
    chart_df = df_1m[['Open', 'Close', 'Volume']].copy()
    chart_df.index = chart_df.index.tz_convert(tz_str)
    
    now_time = pd.Timestamp.now(tz=tz_str).floor('min')
    today_date = now_time.date()
    
    start_time = pd.Timestamp(datetime.datetime.combine(today_date, datetime.time(9, 30 if is_us else 0))).tz_localize(tz_str)
    end_time = pd.Timestamp(datetime.datetime.combine(today_date, datetime.time(16 if is_us else 13, 0 if is_us else 30))).tz_localize(tz_str)
    
    chart_df = chart_df[chart_df.index >= start_time]
    if not chart_df.empty: chart_df = chart_df.resample('1min').asfreq()
    chart_df = chart_df.reindex(pd.date_range(start=start_time, end=end_time, freq='1min'))

    plot_now = now_time if now_time <= end_time else end_time
    plot_now = plot_now if plot_now >= start_time else start_time
    
    past_mask = chart_df.index <= plot_now
    chart_df.loc[past_mask, 'Close'] = chart_df.loc[past_mask, 'Close'].ffill()
    chart_df.loc[past_mask, 'Open'] = chart_df.loc[past_mask, 'Open'].fillna(chart_df.loc[past_mask, 'Close'])
    chart_df.loc[past_mask, 'Volume'] = chart_df.loc[past_mask, 'Volume'].fillna(0)
    
    if curr_p is not None:
        last_valid_idx = chart_df.loc[past_mask, 'Close'].last_valid_index()
        if last_valid_idx is not None:
            chart_df.loc[last_valid_idx:plot_now, 'Close'] = chart_df.loc[last_valid_idx, 'Close']
            chart_df.loc[last_valid_idx:plot_now, 'Open'] = chart_df.loc[last_valid_idx, 'Close']
            chart_df.loc[plot_now, 'Close'] = curr_p
        else:
            chart_df.loc[plot_now, 'Close'] = curr_p
            chart_df.loc[plot_now, 'Open'] = curr_p
        
    chart_df = chart_df.reset_index().rename(columns={'index': 'Time'})
    chart_df['現價'] = chart_df['Close']
    chart_df['x_idx'] = np.arange(len(chart_df))

    color_domain = ['現價']; color_range = ['#3b82f6']
    if 'VWAP' in df_1m.columns:
        chart_df['當日VWAP(均線)'] = df_1m['VWAP'].replace(0, np.nan).bfill().fillna(df_1m['Close']).tz_convert(tz_str).resample('1min').ffill().reindex(pd.date_range(start=start_time, end=end_time, freq='1min')).values
        color_domain.append('當日VWAP(均線)'); color_range.append('#f59e0b')

    df_melted = chart_df.dropna(subset=['價格']).melt(id_vars=['Time', 'x_idx', 'Open', 'Close', 'Volume'], var_name='線型', value_name='價格') if '價格' in chart_df.columns else chart_df.melt(id_vars=['Time', 'x_idx', 'Open', 'Close', 'Volume'], var_name='線型', value_name='價格')
    valid_prices = df_melted.dropna(subset=['價格'])['價格']
    
    if cdp_nh > 0 and cdp_nl > 0:
        valid_prices = pd.concat([valid_prices, pd.Series([cdp_nh, cdp_nl])])
        color_domain.extend(['CDP_NH(壓力)', 'CDP_NL(支撐)']); color_range.extend(['#ef4444', '#10b981'])

    y_min, y_max = (valid_prices.min() * 0.995, valid_prices.max() * 1.005) if not valid_prices.empty else (0, 100)

    base = alt.Chart(df_melted.dropna(subset=['價格'])).encode(x=alt.X('x_idx:Q', title='', scale=alt.Scale(domain=[0, len(chart_df)-1]), axis=alt.Axis(labels=False, ticks=False, grid=False)))
    line = base.mark_line(strokeWidth=2.5).encode(y=alt.Y('價格:Q', scale=alt.Scale(domain=[y_min, y_max]), title='', axis=alt.Axis(gridColor='#334155')), color=alt.Color('線型:N', scale=alt.Scale(domain=color_domain, range=color_range), legend=alt.Legend(title="", orient="top", padding=0)))
    hover = alt.selection_point(fields=['x_idx'], nearest=True, on='mouseover', empty=False)
    points = line.mark_circle(size=80).encode(opacity=alt.condition(hover, alt.value(1), alt.value(0)), tooltip=[alt.Tooltip('Time:T', format='%H:%M', title='時間'), '線型', alt.Tooltip('價格:Q', format='.2f')]).add_params(hover)
    v_rules = base.mark_rule(color='#94a3b8', strokeDash=[3, 3]).encode(opacity=alt.condition(hover, alt.value(1), alt.value(0))).transform_filter(hover)
    h_rules = base.mark_rule(color='#94a3b8', strokeDash=[3, 3]).encode(y='價格:Q', opacity=alt.condition(hover, alt.value(1), alt.value(0))).transform_filter(hover).transform_filter(alt.datum.線型 == '現價')

    alert_layers = []
    if cdp_nh > 0 and cdp_nl > 0: alert_layers.append(alt.Chart(pd.DataFrame({'價格': [cdp_nh, cdp_nl], '線型': ['CDP_NH(壓力)', 'CDP_NL(支撐)']})).mark_rule(strokeWidth=2).encode(y='價格:Q', color=alt.Color('線型:N', scale=alt.Scale(domain=color_domain, range=color_range))))
    for al in alerts:
        if al.get('type') == '固定價格' and al.get('price', 0) > 0: alert_layers.append(alt.Chart(pd.DataFrame({'價格': [al['price']]})).mark_rule(color='#eab308', strokeWidth=2, strokeDash=[4, 4]).encode(y='價格:Q'))

    main_chart = alt.layer(line, v_rules, h_rules, points, *alert_layers).properties(height=200)

    up_color = "#ef4444" if not is_us else "#10b981"
    down_color = "#10b981" if not is_us else "#ef4444"
    base_vol = alt.Chart(chart_df.dropna(subset=['Volume'])).encode(x=alt.X('x_idx:Q', title='', scale=alt.Scale(domain=[0, len(chart_df)-1]), axis=alt.Axis(labels=False, ticks=False)))
    v_rules_vol = base_vol.mark_rule(color='#94a3b8', strokeDash=[3, 3]).encode(opacity=alt.condition(hover, alt.value(1), alt.value(0))).transform_filter(hover)
    vol_chart = alt.layer(base_vol.mark_bar(opacity=0.6).encode(y=alt.Y('Volume:Q', title='量', axis=alt.Axis(labels=False, grid=False)), color=alt.condition("datum.Close >= datum.Open", alt.value(up_color), alt.value(down_color)), tooltip=[alt.Tooltip('Time:T', format='%H:%M', title='時間'), alt.Tooltip('Volume:Q', title='成交量')]), v_rules_vol).properties(height=60)
    st.altair_chart(alt.vconcat(main_chart, vol_chart).resolve_scale(x='shared').configure_concat(spacing=0), use_container_width=True)

def render_kline_chart(tf, df_1m, df_5k, df_15k, df_daily, curr_p, alerts=[], is_us=False, visible_layers=["K棒", "MA3", "MA5", "MA10", "MA23"]):
    df = df_1m if tf == "1K" else (df_5k if tf == "5K" else (df_15k if tf == "15K" else df_daily))
    if df.empty: return
    tz_str = 'America/New_York' if is_us else 'Asia/Taipei'
    df_chart = df.copy()
    df_chart.index = df_chart.index.tz_convert(tz_str)

    if tf == "1K":
        now_time = pd.Timestamp.now(tz=tz_str).floor('min')
        today_date = now_time.date()
        start_time = pd.Timestamp(datetime.datetime.combine(today_date, datetime.time(9, 30 if is_us else 0))).tz_localize(tz_str)
        end_time = pd.Timestamp(datetime.datetime.combine(today_date, datetime.time(16 if is_us else 13, 0 if is_us else 30))).tz_localize(tz_str)
        
        df_chart = df_chart[df_chart.index >= start_time]
        if not df_chart.empty: df_chart = df_chart.resample('1min').ffill()
        df_chart = df_chart.reindex(pd.date_range(start=start_time, end=end_time, freq='1min'))
        
        plot_now = now_time if now_time <= end_time else end_time
        plot_now = plot_now if plot_now >= start_time else start_time
        
        past_mask = df_chart.index <= plot_now
        df_chart.loc[past_mask, 'Close'] = df_chart.loc[past_mask, 'Close'].ffill()
        df_chart.loc[past_mask, 'Open'] = df_chart.loc[past_mask, 'Open'].fillna(df_chart.loc[past_mask, 'Close'])
        df_chart.loc[past_mask, 'High'] = df_chart.loc[past_mask, 'High'].fillna(df_chart.loc[past_mask, 'Close'])
        df_chart.loc[past_mask, 'Low'] = df_chart.loc[past_mask, 'Low'].fillna(df_chart.loc[past_mask, 'Close'])
        
        if curr_p is not None:
            last_valid_idx = df_chart.loc[past_mask, 'Close'].last_valid_index()
            if last_valid_idx is not None:
                df_chart.loc[last_valid_idx:plot_now, 'Close'] = df_chart.loc[last_valid_idx, 'Close']
                df_chart.loc[last_valid_idx:plot_now, 'Open'] = df_chart.loc[last_valid_idx, 'Close']
                df_chart.loc[last_valid_idx:plot_now, 'High'] = df_chart.loc[last_valid_idx, 'Close']
                df_chart.loc[last_valid_idx:plot_now, 'Low'] = df_chart.loc[last_valid_idx, 'Close']
                df_chart.loc[plot_now, 'Close'] = curr_p
                if curr_p > df_chart.loc[plot_now, 'High']: df_chart.loc[plot_now, 'High'] = curr_p
                if curr_p < df_chart.loc[plot_now, 'Low']: df_chart.loc[plot_now, 'Low'] = curr_p
            else:
                df_chart.loc[plot_now, 'Close'] = curr_p
                df_chart.loc[plot_now, 'Open'] = curr_p
                df_chart.loc[plot_now, 'High'] = curr_p
                df_chart.loc[plot_now, 'Low'] = curr_p
                
        df_chart = df_chart.dropna(subset=['Close'])
        start_idx, end_idx = 0, len(pd.date_range(start=start_time, end=end_time, freq='1min')) - 1
    else:
        if curr_p is not None and not df_chart.empty:
            last_idx = df_chart.index[-1]
            df_chart.at[last_idx, 'Close'] = curr_p
            if curr_p > df_chart.at[last_idx, 'High']: df_chart.at[last_idx, 'High'] = curr_p
            if curr_p < df_chart.at[last_idx, 'Low']: df_chart.at[last_idx, 'Low'] = curr_p
        start_idx, end_idx = max(0, len(df_chart) - 80), len(df_chart) - 1

    if df_chart.empty: return
    
    for ma in [3, 5, 10, 23]: df_chart[f'MA{ma}'] = df_chart['Close'].rolling(ma).mean()
    df_chart = df_chart.reset_index().rename(columns={'index': 'Time'})
    df_chart['x_idx'] = np.arange(len(df_chart))
    df_chart['TimeStr'] = df_chart['Time'].dt.strftime('%y/%m/%d' if tf == "日K" else '%m/%d %H:%M')
    df_chart['Draw_Close'] = np.where(df_chart['Close'] == df_chart['Open'], df_chart['Close'] + (df_chart['Close'] * 0.0005), df_chart['Close'])
    
    y_min, y_max = df_chart['Low'].min() * 0.995, df_chart['High'].max() * 1.005
    up_color = "#ef4444" if not is_us else "#10b981"
    down_color = "#10b981" if not is_us else "#ef4444"
    pan_zoom = alt.selection_interval(bind='scales', encodings=['x'])
    base = alt.Chart(df_chart).encode(x=alt.X('x_idx:Q', title='', scale=alt.Scale(domain=[start_idx, end_idx]), axis=alt.Axis(labels=False, ticks=False, grid=False)))
    
    layers = []
    if "K棒" in visible_layers:
        layers.extend([
            base.mark_rule(size=1.5).encode(y=alt.Y('Low:Q', scale=alt.Scale(domain=[y_min, y_max]), title='', axis=alt.Axis(gridColor='#334155')), y2='High:Q', color=alt.condition("datum.Close >= datum.Open", alt.value(up_color), alt.value(down_color))),
            base.mark_bar(size=5).encode(y='Open:Q', y2='Draw_Close:Q', color=alt.condition("datum.Close >= datum.Open", alt.value(up_color), alt.value(down_color)))
        ])
    
    ma_colors = {'MA3': '#f59e0b', 'MA5': '#3b82f6', 'MA10': '#a855f7', 'MA23': '#ec4899'}
    for ma in ['MA3', 'MA5', 'MA10', 'MA23']:
        if ma in visible_layers and ma in df_chart.columns: layers.append(base.mark_line(size=1.5, opacity=0.8).encode(y=alt.Y(f'{ma}:Q'), color=alt.value(ma_colors[ma])))
            
    for al in alerts:
        if al.get('type') == '固定價格' and al.get('price', 0) > 0: layers.append(alt.Chart(pd.DataFrame({'價格': [al['price']]})).mark_rule(color='#eab308', strokeWidth=2, strokeDash=[4, 4]).encode(y='價格:Q'))
            
    if not layers: return st.altair_chart(alt.Chart(pd.DataFrame({'x': [0], 'y': [0], 't': ['👀 已隱藏所有圖層']})).mark_text(size=18, color='#94a3b8').encode(text='t:N').properties(height=260), use_container_width=True)

    hover = alt.selection_point(fields=['x_idx'], nearest=True, on='mouseover', empty=False)
    tooltip_data = [alt.Tooltip('TimeStr:N', title='時間'), alt.Tooltip('Open:Q', format='.2f', title='開盤'), alt.Tooltip('High:Q', format='.2f', title='最高'), alt.Tooltip('Low:Q', format='.2f', title='最低'), alt.Tooltip('Close:Q', format='.2f', title='收盤')]
    for ma in ['MA3', 'MA5', 'MA10', 'MA23']:
        if ma in visible_layers and ma in df_chart.columns: tooltip_data.append(alt.Tooltip(f'{ma}:Q', format='.2f', title=ma))

    hover_points = base.mark_circle(size=80, opacity=0).encode(y='Close:Q', tooltip=tooltip_data).add_params(hover)
    v_rule = base.mark_rule(color='#94a3b8', strokeDash=[3, 3]).encode(opacity=alt.condition(hover, alt.value(1), alt.value(0))).transform_filter(hover)
    h_rule = base.mark_rule(color='#94a3b8', strokeDash=[3, 3]).encode(y='Close:Q', opacity=alt.condition(hover, alt.value(1), alt.value(0))).transform_filter(hover)

    main_kline = alt.layer(*layers, hover_points, v_rule, h_rule).properties(height=200).add_params(pan_zoom)

    # 🔥 修正 base_vol 未定義的問題
    base_vol = alt.Chart(df_chart.dropna(subset=['Volume'])).encode(x=alt.X('x_idx:Q', title='', scale=alt.Scale(domain=[start_idx, end_idx]), axis=alt.Axis(labels=False, ticks=False)))
    v_rule_vol = base_vol.mark_rule(color='#94a3b8', strokeDash=[3, 3]).encode(opacity=alt.condition(hover, alt.value(1), alt.value(0))).transform_filter(hover)
    vol_chart = alt.layer(base_vol.mark_bar(opacity=0.6).encode(y=alt.Y('Volume:Q', title='量', axis=alt.Axis(labels=False, grid=False)), color=alt.condition("datum.Close >= datum.Open", alt.value(up_color), alt.value(down_color)), tooltip=[alt.Tooltip('TimeStr:N', title='時間'), alt.Tooltip('Volume:Q', title='成交量')]), v_rule_vol).properties(height=60)

    ma_info = f"<div style='font-size:0.85rem; color:#cbd5e1; margin-top:-5px; margin-bottom:8px; text-align:right;'>📊 "
    last_idx = df_chart.dropna(subset=['Close']).index[-1] if not df_chart.dropna(subset=['Close']).empty else -1
    if "MA3" in visible_layers and last_idx >= 0: ma_info += f"<span style='color:#f59e0b; font-weight:bold;'>MA3: {df_chart['MA3'].iloc[last_idx]:.2f}</span> &nbsp; "
    if "MA5" in visible_layers and last_idx >= 0: ma_info += f"<span style='color:#3b82f6; font-weight:bold;'>MA5: {df_chart['MA5'].iloc[last_idx]:.2f}</span> &nbsp; "
    if "MA10" in visible_layers and last_idx >= 0: ma_info += f"<span style='color:#a855f7; font-weight:bold;'>MA10: {df_chart['MA10'].iloc[last_idx]:.2f}</span> &nbsp; "
    if "MA23" in visible_layers and last_idx >= 0: ma_info += f"<span style='color:#ec4899; font-weight:bold;'>MA23: {df_chart['MA23'].iloc[last_idx]:.2f}</span>"
    st.markdown(ma_info + "</div>", unsafe_allow_html=True)
    st.altair_chart(alt.vconcat(main_kline, vol_chart).resolve_scale(x='shared').configure_concat(spacing=0), use_container_width=True)

# --- 側邊欄 ---
with st.sidebar:
    st.title("🛡️ 終極安控中心")
    st.header("🎯 1. 自訂監控加入")
    all_stocks = get_full_stock_db()
    
    if all_stocks:
        stock_list = [f"{code} {name}" for code, name in all_stocks.items()]
        selected_tw = st.selectbox("🔍 搜尋台股代碼 (下拉或輸入)", options=["請點此搜尋..."] + stock_list, index=0)
        if selected_tw != "請點此搜尋...":
            parts = selected_tw.split(" "); code = parts[0]; name = " ".join(parts[1:])
            # 👇 修正：改用 on_click 與 args 綁定事件，不用再寫 if 與 st.rerun()
            st.button(f"➕ 加入 {name} (台股)", key=f"add_tw_sel_{code}", on_click=cb_add_tw, args=(code, name))
    else:
        st.error("⚠️ 證交所 API 暫時阻擋雲端主機，下拉選單無法載入。請直接使用下方【手動加入】。")
        if st.button("🔄 重新嘗試連線", use_container_width=True):
            get_full_stock_db.clear(); st.rerun()

    with st.expander("🛠️ 找不到？手動強制加入"):
        if st.button("🔄 重新載入股票清單 (解決連線異常)", use_container_width=True):
            get_full_stock_db.clear(); st.rerun()
        tw_code = st.text_input("🇹🇼 輸入台股代碼 (如 2330, 9933)").strip()
        if tw_code:
            tw_name = all_stocks.get(tw_code, tw_code)
            # 👇 修正：同步改用 on_click 強化穩定性
            st.button(f"➕ 強制加入 {tw_name} (台股)", key=f"add_tw_man_{tw_code}", on_click=cb_add_tw, args=(tw_code, tw_name))

    st.markdown("---")
    us_code = st.text_input("🇺🇸 輸入美股代碼 (如 NVDA)").strip().upper()
    if us_code: 
        # 👇 修正：美股也同步改用 on_click
        st.button(f"➕ 加入 {us_code} (美股)", key=f"add_us_man_{us_code}", on_click=cb_add_us, args=(us_code, us_code))

    if st.button("🗑️ 徹底清空所有資料", type="secondary"):
        cb_clear_all(); st.rerun()

    st.divider()
    st.header("⚡ 2. 系統更新頻率")
    auto_refresh = st.checkbox("開啟極速自動更新 (3秒)", value=False)

    st.divider()
    st.header("🤖 3. AI 選股報告")
    st.caption("💡 藍色按鈕及 ✅ 代表已產出報告並留存紀錄，點擊可再次刷新。")
    
    dt_type = "primary" if st.session_state.ai_report_daytrade else "secondary"
    if st.button("✅ [今日已生成] 台股當沖報告" if st.session_state.ai_report_daytrade else "🚀 生成【台股當沖】報告", use_container_width=True, type=dt_type):
        st.session_state.ai_report_daytrade = fetch_ai_list("daytrade", API_KEY); st.rerun()
        
    on_type = "primary" if st.session_state.ai_report_overnight else "secondary"
    if st.button("✅ [今日已生成] 台股隔日沖報告" if st.session_state.ai_report_overnight else "🌙 生成【台股隔日沖】報告", use_container_width=True, type=on_type):
        st.session_state.ai_report_overnight = fetch_ai_list("overnight", API_KEY); st.rerun()
        
    sw_type = "primary" if st.session_state.ai_report_swing else "secondary"
    if st.button("✅ [今日已生成] 台股波段報告" if st.session_state.ai_report_swing else "🦅 生成【台股波段】報告", use_container_width=True, type=sw_type):
        st.session_state.ai_report_swing = fetch_ai_list("swing", API_KEY); st.rerun()
        
    us_type = "primary" if st.session_state.ai_report_us else "secondary"
    if st.button("✅ [今日已生成] 美股專區報告" if st.session_state.ai_report_us else "🇺🇸 生成【美股專區】報告", use_container_width=True, type=us_type):
        st.session_state.ai_report_us = fetch_ai_list("us_stocks", API_KEY); st.rerun()
    
    st.divider()
    st.header("🛡️ 4. 終極安控中心")
    if not st.session_state.authenticated:
        st.warning("🔒 損益與下單功能已鎖定")
        auth_code = st.text_input("輸入 Google Authenticator 6碼驗證碼", type="password")
        if st.button("解鎖戰情室", use_container_width=True, type="primary"):
            if pyotp.TOTP(TWO_FA_SECRET).verify(auth_code):
                st.session_state.authenticated = True; st.success("✅ 身分驗證成功，武器系統已解鎖！"); st.rerun()
            else: st.error("❌ 驗證碼錯誤")
    else:
        st.success("🔓 指揮官已登入，火力全開")
        if st.button("登出並鎖定", use_container_width=True): st.session_state.authenticated = False; st.rerun()

    st.markdown("##### 🌐 雲地通訊設定")
    new_agent_url = st.text_input("地端 Agent 網址 (Ngrok/IP)", value=st.session_state.agent_url)
    if new_agent_url != st.session_state.agent_url: st.session_state.agent_url = new_agent_url; st.toast("✅ Agent 連線網址已更新")
        
    st.markdown("##### 🔔 Telegram 推播測試")
    if st.button("發送測試警報", use_container_width=True): send_telegram_alert("✅ 這是一條測試訊息，您的 Telegram 推播功能設定完全正確！")

    st.divider()
    st.header("🤖 5. API 引擎狀態")
    if not API_KEY: st.error("🔴 API 未設定 (AI 相關功能已停擺)\n\n請至 Streamlit Cloud 後台 Secrets 頁面設定 `GEMINI_API_KEY`")
    else: st.success("🟢 API 已連線，AI 引擎運轉中 (金鑰已隱藏)")

# --- 主畫面渲染 ---
st.title("⚡ AI 雲地混合智能戰情室")
now_tpe = datetime.datetime.now(pytz.timezone('Asia/Taipei'))
fast_cache_key = int(time.time()) // 3 
t5_key = f"{now_tpe.year}{now_tpe.month}{now_tpe.day}{now_tpe.hour}_{now_tpe.minute // 5}"
t15_key = f"{now_tpe.year}{now_tpe.month}{now_tpe.day}{now_tpe.hour}_{now_tpe.minute // 15}"
is_tw_market_open = datetime.time(9, 0) <= now_tpe.time() <= datetime.time(13, 30)

col_t1, col_t2, col_t3, col_t4 = st.columns([1.5, 1.5, 1, 1])
df_twii, curr_twii, prev_twii = get_index_data_engine('^TWII', fast_cache_key)
df_twoii, curr_twoii, prev_twoii = get_index_data_engine('^TWOII', fast_cache_key)
_, curr_ixic, prev_ixic = get_index_data_engine('^IXIC', fast_cache_key)

with col_t1:
    if curr_twii and prev_twii:
        diff = curr_twii - prev_twii; pct = diff / prev_twii * 100
        st.metric("🇹🇼 加權指數 (上市)", f"{curr_twii:,.2f}", f"{diff:+.2f} ({pct:+.2f}%)", delta_color="inverse" if diff < 0 else "normal")
        if not df_twii.empty: render_index_sparkline(df_twii, prev_twii, curr_twii, "TW")
        else: st.caption("走勢圖暫無資料")
    else: st.metric("🇹🇼 加權指數 (上市)", "讀取中...", "--")

with col_t2:
    if curr_twoii and prev_twoii:
        diff = curr_twoii - prev_twoii; pct = diff / prev_twoii * 100
        st.metric("🇹🇼 櫃買指數 (上櫃)", f"{curr_twoii:,.2f}", f"{diff:+.2f} ({pct:+.2f}%)", delta_color="inverse" if diff < 0 else "normal")
        if not df_twoii.empty: render_index_sparkline(df_twoii, prev_twoii, curr_twoii, "TW")
        else: st.caption("⚠️ Yahoo 暫無上櫃分K")
    else: st.metric("🇹🇼 櫃買指數 (上櫃)", "讀取中...", "--")

with col_t3:
    if curr_ixic and prev_ixic:
        diff = curr_ixic - prev_ixic; pct = diff / prev_ixic * 100
        st.metric("🇺🇸 納斯達克 (Nasdaq)", f"{curr_ixic:,.2f}", f"{diff:+.2f} ({pct:+.2f}%)", delta_color="inverse" if diff < 0 else "normal")
    else: st.metric("🇺🇸 納斯達克 (Nasdaq)", "讀取中...", "--")

with col_t4:
    if API_KEY: st.success(f"⚡ 實時跳動中\n\n更新: {now_tpe.strftime('%H:%M:%S')}")
    else: st.error("🔴 API 未設定")

st.divider()
twii_mas = get_index_mas('^TWII')
if curr_twii and twii_mas:
    st.markdown(f"##### 📊 台股大盤關鍵均線雷達 (現價: **{curr_twii:.0f}**)")
    ma_cols = st.columns(4)
    for idx, (ma_name, ma_val) in enumerate(twii_mas.items()):
        dist_pts = curr_twii - ma_val; dist_pct = dist_pts / ma_val
        if abs(dist_pct) <= 0.003:
            if dist_pts > 0: ma_cols[idx].warning(f"**{ma_name}** `{ma_val:.0f}`\n\n⚠️ **回測警戒**：僅剩 **{dist_pts:.0f}** 點")
            else: ma_cols[idx].warning(f"**{ma_name}** `{ma_val:.0f}`\n\n🔥 **突破叩關**：僅差 **{abs(dist_pts):.0f}** 點")
        else:
            if dist_pts > 0: ma_cols[idx].success(f"**{ma_name}** `{ma_val:.0f}`\n\n🛡️ **支撐防護**：還剩 **{dist_pts:.0f}** 點")
            else: ma_cols[idx].error(f"**{ma_name}** `{ma_val:.0f}`\n\n⚔️ **上檔壓力**：還差 **{abs(dist_pts):.0f}** 點")
    st.divider()

tab_tw, tab_us, tab_ai, tab_core, tab_radar = st.tabs(["🇹🇼 台股極速當沖", "🇺🇸 美股波段戰情", "🤖 AI 選股報告", "🐢 10年期核心長線", "📡 爆量雷達快篩"])

# ====================
# 戰區 1：台股極速當沖
# ====================
with tab_tw:
    if not st.session_state.tw_stocks: st.info("請至側邊欄加入台股標的。")
    for idx, stock in enumerate(st.session_state.tw_stocks):
        code, name = stock['code'], stock['name']; alerts = stock.get('alerts', [])
        df_daily, suffix = get_historical_features(code, is_us=False)
        df_1m, curr_p, prev_p = get_realtime_tick_and_price(code, suffix, fast_cache_key)
        df_5k = get_kline_data(code, suffix, '5m', t5_key)
        df_15k = get_kline_data(code, suffix, '15m', t15_key)
        
        mas = {}; cdp_nh = cdp_nl = 0.0
        if not df_1m.empty:
            df_1m['Cum_Vol'] = df_1m['Volume'].cumsum()
            df_1m['Cum_PV'] = (((df_1m['High'] + df_1m['Low'] + df_1m['Close']) / 3) * df_1m['Volume']).cumsum()
            df_1m['VWAP'] = (df_1m['Cum_PV'] / df_1m['Cum_Vol'].replace(0, np.nan)).bfill().fillna(df_1m['Close'])
            mas['當日VWAP'] = df_1m['VWAP'].iloc[-1]
            
        if curr_p is None: curr_p = df_1m['Close'].iloc[-1] if not df_1m.empty else 0.0
        if prev_p is None: prev_p = curr_p
            
        if not df_5k.empty:
            mas['5分K_10MA'] = df_5k['Close'].tail(10).mean()
            df_5k_tz = df_5k.copy()
            df_5k_tz.index = df_5k_tz.index.tz_convert('Asia/Taipei')
            df_5k_today = df_5k_tz[df_5k_tz.index.date == now_tpe.date()]
            if not df_5k_today.empty:
                mas['5K首K高'] = df_5k_today.iloc[0]['High']
                mas['5K首K低'] = df_5k_today.iloc[0]['Low']
                
        if not df_15k.empty and len(df_15k) >= 10: mas['15分K_10MA'] = df_15k['Close'].tail(10).mean()
        if not df_daily.empty:
            mas['日線3MA'] = df_daily['Close'].tail(3).mean(); mas['日線5MA'] = df_daily['Close'].tail(5).mean()
            mas['日線10MA'] = df_daily['Close'].tail(10).mean(); mas['日線23MA'] = df_daily['Close'].tail(23).mean()
        
        r1 = s1 = 0.0
        if len(df_daily) >= 2:
            y_high, y_low, y_close = df_daily['High'].iloc[-2], df_daily['Low'].iloc[-2], df_daily['Close'].iloc[-2]
            pivot = (y_high + y_low + y_close) / 3
            r1 = (2 * pivot) - y_low; s1 = (2 * pivot) - y_high
            cdp = (y_high + y_low + 2 * y_close) / 4
            cdp_nh = (2 * cdp) - y_low; cdp_nl = (2 * cdp) - y_high
            mas['CDP_NH(壓力)'] = cdp_nh; mas['CDP_NL(支撐)'] = cdp_nl

        is_alert = False; triggered_msgs = []
        for a_idx, al in enumerate(alerts):
            al_type = al.get('type', '固定價格'); t_p = al['price'] if al_type == '固定價格' else mas.get(al_type, 0.0); cond = al['cond']
            if t_p > 0:
                t_p_label = f"{t_p}" if al_type == '固定價格' else f"{al_type} ({t_p:.2f})"
                if (cond == ">=" and curr_p >= t_p) or (cond == "<=" and curr_p <= t_p):
                    is_alert = True
                    if not al.get('triggered', False):
                        triggered_msgs.append(f"{'漲破' if cond=='>=' else '跌破'} {t_p_label}")
                        st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = True
                        if al.get('auto_trade', False) and not al.get('require_retest', False) and not al.get('trade_fired', False) and st.session_state.authenticated:
                            act = "buy" if stock.get('my_dir', '作多') == "作多" else "sell"
                            res = fire_order_to_agent(code, float(stock.get('my_price', curr_p)), act, int(stock.get('my_lots', 1)))
                            if res.get('status') == 'success': 
                                send_telegram_alert(f"🚀 【自動下單成功】\n{name}({code}) 首度觸發設定價\n已自動送出 {act.upper()} 委託！")
                                st.session_state.tw_stocks[idx]['alerts'][a_idx]['trade_fired'] = True

                touches = 0
                if not df_1m.empty and len(df_1m) >= 15:
                    if cond == ">=": touches = max((df_1m['High'].tail(15) >= t_p).sum(), 1 if curr_p >= t_p else 0)
                    else: touches = max((df_1m['Low'].tail(15) <= t_p).sum(), 1 if curr_p <= t_p else 0)

                if touches >= 2 and not al.get('touch_2_triggered', False):
                    send_telegram_alert(f"⚠️ 🚨【多次叩關確認】\n{name}({code}) 近 15 分鐘測試 {t_p_label} 達 {touches} 次！")
                    st.session_state.tw_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = True
                    if al.get('auto_trade', False) and al.get('require_retest', False) and not al.get('trade_fired', False) and st.session_state.authenticated:
                        act = "buy" if stock.get('my_dir', '作多') == "作多" else "sell"
                        res = fire_order_to_agent(code, float(stock.get('my_price', curr_p)), act, int(stock.get('my_lots', 1)))
                        if res.get('status') == 'success': 
                            send_telegram_alert(f"🚀 【自動下單成功】\n{name}({code}) 多次回測確認完畢\n已自動送出 {act.upper()} 委託！")
                            st.session_state.tw_stocks[idx]['alerts'][a_idx]['trade_fired'] = True

                if cond == ">=" and curr_p < t_p * 0.995: st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = False; st.session_state.tw_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
                if cond == "<=" and curr_p > t_p * 1.005: st.session_state.tw_stocks[idx]['alerts'][a_idx]['triggered'] = False; st.session_state.tw_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
        
        sl_p = float(stock.get('stop_loss', 0.0))
        if sl_p > 0 and not stock.get('sl_triggered', False) and st.session_state.authenticated and int(stock.get('my_lots', 0)) > 0:
            pass
