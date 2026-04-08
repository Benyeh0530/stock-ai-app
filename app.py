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
    df_chart = df_chart[df_chart.index.date == df_chart.index[-1].date()].resample('1min').ffill()
    
    start_time = pd.Timestamp(datetime.datetime.combine(df_chart.index[-1].date(), datetime.time(9, 0 if market_type == "TW" else 30))).tz_localize(tz_str)
    end_time = pd.Timestamp(datetime.datetime.combine(df_chart.index[-1].date(), datetime.time(13 if market_type == "TW" else 16, 30 if market_type == "TW" else 0))).tz_localize(tz_str)
    
    df_chart = df_chart.reindex(pd.date_range(start=start_time, end=end_time, freq='1min'))
    now_time = pd.Timestamp.now(tz=tz_str).floor('min')
    if now_time > end_time: now_time = end_time
    
    past_mask = df_chart.index <= now_time
    df_chart.loc[past_mask, 'Close'] = df_chart.loc[past_mask, 'Close'].ffill()
    
    if curr_p is not None and (last_valid_idx := df_chart.loc[past_mask, 'Close'].last_valid_index()) is not None:
        df_chart.loc[last_valid_idx:now_time if now_time >= last_valid_idx else last_valid_idx, 'Close'] = df_chart.loc[last_valid_idx, 'Close'] if now_time >= last_valid_idx else curr_p
        if now_time >= last_valid_idx: df_chart.loc[now_time, 'Close'] = curr_p
                
    df_chart = df_chart.dropna(subset=['Close'])
    if df_chart.empty: return
        
    df_chart = df_chart.reset_index().rename(columns={'index': 'Time'})
    df_chart['x_idx'] = np.arange(len(df_chart))
    
    color = ("#ef4444" if market_type == "TW" else "#10b981") if curr_p >= prev_close else ("#10b981" if market_type == "TW" else "#ef4444")
    y_min, y_max = min(df_chart['Close'].min(), prev_close), max(df_chart['Close'].max(), prev_close)
    buffer = (y_max - y_min) * 0.05 if y_max != y_min else curr_p * 0.001
    
    base = alt.Chart(df_chart).encode(x=alt.X('x_idx:Q', scale=alt.Scale(domain=[0, len(df_chart)-1]), axis=alt.Axis(labels=False, ticks=False, grid=False, title='')))
    line = base.mark_line(color=color, strokeWidth=2).encode(y=alt.Y('Close:Q', scale=alt.Scale(domain=[y_min-buffer, y_max+buffer], zero=False), axis=alt.Axis(labels=False, ticks=False, grid=False, title='')))
    rule = alt.Chart(pd.DataFrame({'p': [prev_close]})).mark_rule(color='#94a3b8', strokeDash=[3,3], strokeWidth=1.5).encode(y='p:Q')
    area = base.mark_area(color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color=color, offset=0), alt.GradientStop(color='rgba(0,0,0,0)', offset=1)], x1=1, x2=1, y1=0, y2=1), opacity=0.3).encode(y=alt.Y('Close:Q', scale=alt.Scale(domain=[y_min-buffer, y_max+buffer], zero=False)), y2=alt.datum(y_min-buffer))
    st.altair_chart(alt.layer(rule, area, line).properties(height=80), use_container_width=True)

def render_mini_chart(df_1m, cdp_nh, cdp_nl, curr_p, alerts=[], is_us=False):
    if df_1m.empty: return
    tz_str = 'America/New_York' if is_us else 'Asia/Taipei'
    chart_df = df_1m[['Open', 'Close', 'Volume']].copy()
    chart_df.index = chart_df.index.tz_convert(tz_str)
    chart_df = chart_df[chart_df.index.date == chart_df.index[-1].date()].resample('1min').asfreq()
    
    start_time = pd.Timestamp(datetime.datetime.combine(chart_df.index[-1].date(), datetime.time(9, 30 if is_us else 0))).tz_localize(tz_str)
    end_time = pd.Timestamp(datetime.datetime.combine(chart_df.index[-1].date(), datetime.time(16 if is_us else 13, 0 if is_us else 30))).tz_localize(tz_str)
    chart_df = chart_df.reindex(pd.date_range(start=start_time, end=end_time, freq='1min'))

    now_time = pd.Timestamp.now(tz=tz_str).floor('min')
    if now_time > end_time: now_time = end_time
    
    past_mask = chart_df.index <= now_time
    chart_df.loc[past_mask, 'Close'] = chart_df.loc[past_mask, 'Close'].ffill()
    chart_df.loc[past_mask, 'Open'] = chart_df.loc[past_mask, 'Open'].fillna(chart_df.loc[past_mask, 'Close'])
    chart_df.loc[past_mask, 'Volume'] = chart_df.loc[past_mask, 'Volume'].fillna(0)
    
    if curr_p is not None and (last_valid_idx := chart_df['Close'].last_valid_index()) is not None:
        if now_time >= last_valid_idx:
            chart_df.loc[last_valid_idx:now_time, 'Close'] = chart_df.loc[last_valid_idx, 'Close']
            chart_df.loc[last_valid_idx:now_time, 'Open'] = chart_df.loc[last_valid_idx, 'Close']
            chart_df.loc[now_time, 'Close'] = curr_p
        else: chart_df.loc[last_valid_idx, 'Close'] = curr_p
        
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
        df_chart = df_chart.resample('1min').ffill()
        start_time = pd.Timestamp(datetime.datetime.combine(df_chart.index[-1].date(), datetime.time(9, 30 if is_us else 0))).tz_localize(tz_str)
        end_time = pd.Timestamp(datetime.datetime.combine(df_chart.index[-1].date(), datetime.time(16 if is_us else 13, 0 if is_us else 30))).tz_localize(tz_str)
        df_chart = df_chart.reindex(pd.date_range(start=start_time, end=end_time, freq='1min'))
        
        now_time = pd.Timestamp.now(tz=tz_str).floor('min')
        if now_time > end_time: now_time = end_time
        
        past_mask = df_chart.index <= now_time
        df_chart.loc[past_mask, 'Close'] = df_chart.loc[past_mask, 'Close'].ffill()
        df_chart.loc[past_mask, 'Open'] = df_chart.loc[past_mask, 'Open'].fillna(df_chart.loc[past_mask, 'Close'])
        df_chart.loc[past_mask, 'High'] = df_chart.loc[past_mask, 'High'].fillna(df_chart.loc[past_mask, 'Close'])
        df_chart.loc[past_mask, 'Low'] = df_chart.loc[past_mask, 'Low'].fillna(df_chart.loc[past_mask, 'Close'])
        
        if curr_p is not None and len(df_chart[past_mask]) > 0:
            df_chart.loc[now_time, 'Close'] = curr_p
            if df_chart.loc[now_time, 'High'] < curr_p: df_chart.loc[now_time, 'High'] = curr_p
            if df_chart.loc[now_time, 'Low'] > curr_p: df_chart.loc[now_time, 'Low'] = curr_p
            
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

    v_rule_vol = base.mark_rule(color='#94a3b8', strokeDash=[3, 3]).encode(opacity=alt.condition(hover, alt.value(1), alt.value(0))).transform_filter(hover)
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
            if st.button(f"➕ 加入 {name} (台股)", key=f"add_tw_sel_{code}"):
                cb_add_tw(code, name); st.rerun()
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
            if st.button(f"➕ 強制加入 {tw_name} (台股)", key=f"add_tw_man_{tw_code}"):
                cb_add_tw(tw_code, tw_name); st.rerun()

    st.markdown("---")
    us_code = st.text_input("🇺🇸 輸入美股代碼 (如 NVDA)").strip().upper()
    if us_code: 
        if st.button(f"➕ 加入 {us_code} (美股)", key=f"add_us_man_{us_code}"):
            cb_add_us(us_code, us_code); st.rerun()

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

all_tw_to_fetch = list(set([s['code'] for s in st.session_state.tw_stocks]))
us_set = set([s['code'] for s in st.session_state.us_stocks])
all_us_to_fetch = list(us_set)

for s in st.session_state.tw_stocks:
    c_codes = get_correlated_stocks(s['code'], s['name'], API_KEY, is_us=False)
    if c_codes: all_tw_to_fetch.extend(c_codes)
for s in st.session_state.us_stocks:
    c_codes = get_correlated_stocks(s['code'], s['name'], API_KEY, is_us=True)
    if c_codes: all_us_to_fetch.extend(c_codes)

for report in [st.session_state.ai_report_daytrade, st.session_state.ai_report_overnight, st.session_state.ai_report_swing]:
    if report:
        for cat, stocks in report.items():
            for s in stocks: all_tw_to_fetch.append(s['code'])
if st.session_state.ai_report_us:
    for cat, stocks in st.session_state.ai_report_us.items():
        for s in stocks: all_us_to_fetch.append(s['code'])

all_tw_to_fetch = tuple(set(all_tw_to_fetch))
all_us_to_fetch = tuple(set(all_us_to_fetch))
live_price_dict = get_bulk_live_prices(all_tw_to_fetch, all_us_to_fetch, fast_cache_key)

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
            
        # 🔥 新增 5K 首 K 高低點抓取
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
        
        # 🔥 雲端智慧停損邏輯
        sl_p = float(stock.get('stop_loss', 0.0))
        if sl_p > 0 and not stock.get('sl_triggered', False) and st.session_state.authenticated and int(stock.get('my_lots', 0)) > 0:
            if stock.get('my_dir') == '作多' and curr_p <= sl_p:
                res = fire_order_to_agent(code, curr_p, "Sell", int(stock.get('my_lots', 1)))
                if res.get('status') == 'success':
                    send_telegram_alert(f"💥 【雲端停損觸發】\n{name}({code}) 跌破停損價 {sl_p}\n已自動送出市價平倉 (SELL) 委託！")
                    st.session_state.tw_stocks[idx]['sl_triggered'] = True
            elif stock.get('my_dir') == '作空' and curr_p >= sl_p:
                res = fire_order_to_agent(code, curr_p, "Buy", int(stock.get('my_lots', 1)))
                if res.get('status') == 'success':
                    send_telegram_alert(f"💥 【雲端停損觸發】\n{name}({code}) 漲破停損價 {sl_p}\n已自動送出市價平倉 (BUY) 委託！")
                    st.session_state.tw_stocks[idx]['sl_triggered'] = True

        if triggered_msgs and is_tw_market_open: save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

        with st.container(border=True):
            my_p, my_l, my_dir, my_tt = float(stock.get('my_price', 0.0)), int(stock.get('my_lots', 1)), stock.get('my_dir', '作多'), stock.get('my_trade_type', '當沖')
            c_title, c_p, c_pnl, c_r1, c_s1, c_del = st.columns([2.5, 1.5, 1.5, 1, 1, 0.5])
            with c_title: st.markdown(f"#### {name}({code})")
            
            diff = curr_p - prev_p; pct = (diff / prev_p) * 100 if prev_p > 0 else 0
            is_limit_up = pct >= 9.85; is_limit_down = pct <= -9.85
            with c_p:
                if is_limit_up: st.markdown(f"<div style='background-color:#ef4444 !important; border-radius:8px !important; padding:8px 0px !important; text-align:center; box-shadow: 0 0 8px rgba(239,68,68,0.6) !important;'><div style='font-size:0.75rem; color:#fee2e2; margin-bottom:0px;'>實時現價 🚀 漲停</div><div style='font-size:1.4rem; font-weight:700; color:white; line-height:1.2;'>{curr_p:.2f}</div><div style='font-size:0.8rem; color:#fecaca;'>+{diff:.2f} (+{pct:.2f}%)</div></div>", unsafe_allow_html=True)
                elif is_limit_down: st.markdown(f"<div style='background-color:#10b981 !important; border-radius:8px !important; padding:8px 0px !important; text-align:center; box-shadow: 0 0 8px rgba(16,185,129,0.6) !important;'><div style='font-size:0.75rem; color:#d1fae5; margin-bottom:0px;'>實時現價 💥 跌停</div><div style='font-size:1.4rem; font-weight:700; color:white; line-height:1.2;'>{curr_p:.2f}</div><div style='font-size:0.8rem; color:#a7f3d0;'>{diff:.2f} ({pct:.2f}%)</div></div>", unsafe_allow_html=True)
                else: st.metric("實時現價", f"{curr_p:.2f}", f"{diff:+.2f} ({pct:+.2f}%)", delta_color="normal" if diff >= 0 else "inverse")
            
            with c_pnl:
                if my_p > 0:
                    if st.session_state.authenticated:
                        pnl = calc_tw_pnl(my_p, curr_p, my_l, my_dir, my_tt)
                        st.metric("未實現淨利", f"{pnl:,.0f} 元", f"{(pnl / (my_p * my_l * 1000)) * 100 if my_p > 0 else 0:+.2f}%", delta_color="normal" if pnl > 0 else "inverse")
                    else: st.metric("未實現淨利", "*** (鎖定)", "登入後查看", delta_color="off")
                else: st.metric("未實現淨利", "--", delta_color="off")
            with c_r1: st.metric("壓力(R1)", f"{r1:.2f}", delta_color="off")
            with c_s1: st.metric("支撐(S1)", f"{s1:.2f}", delta_color="off")
            with c_del: 
                if st.button("❌", key=f"del_tw_{code}"): cb_remove_tw(idx); st.rerun()
            
            if is_alert: st.error(f"🚨 **到價警示！** 現價 {curr_p} 已觸發設定目標")
            
            corr_codes = get_correlated_stocks(code, name, API_KEY, is_us=False)
            if not corr_codes:
                if API_KEY:
                    col_m, col_b = st.columns([5, 1])
                    col_m.markdown("<div style='font-size:0.9rem; color:#94a3b8; margin-top:5px; margin-bottom:10px;'>🔗 <b>族群聯動：</b> AI 正在重新鎖定中，請重試。</div>", unsafe_allow_html=True)
                    if col_b.button("🔄 重試", key=f"retry_corr_tw_{code}"): get_correlated_stocks.clear(code, name, API_KEY, is_us=False); st.rerun()
            else:
                corr_display = []
                for i, c in enumerate(corr_codes):
                    c_name = all_stocks.get(c, c); icon = "👑" if i == 0 else "🔗"
                    _, cp, pp = get_realtime_tick_and_price(c, ".TW", fast_cache_key) 
                    if cp is None: _, cp, pp = get_realtime_tick_and_price(c, ".TWO", fast_cache_key)
                    if cp is not None and pp is not None and pp > 0:
                        diff_c = cp - pp; pct_c = (diff_c / pp) * 100; sign_c = "+" if diff_c > 0 else ""
                        color_c = '#ef4444' if diff_c > 0 else '#10b981' if diff_c < 0 else '#94a3b8'
                        corr_display.append(f"<b>{icon} {c_name}({c})</b> {cp:.2f} (<span style='color:{color_c}'>{sign_c}{diff_c:.2f}, {sign_c}{pct_c:.2f}%</span>)")
                    else: corr_display.append(f"<b>{icon} {c_name}({c})</b> 讀取中...")
                st.markdown(f"<div style='font-size:0.95rem; margin-top:5px; margin-bottom:10px; padding:8px; background-color:rgba(30,41,59,0.5); border-radius:8px;'>🔗 <b>高度聯動：</b> {' ｜ '.join(corr_display)}</div>", unsafe_allow_html=True)
            
            st.divider()
            c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([1.5, 1, 1])
            with c_ctrl1: st.markdown("##### 📉 雙視角走勢與無縫 K 線圖")
            with c_ctrl2: tf_sel = st.selectbox("切換時區", ["1K", "5K", "15K", "日K"], index=3, key=f"tf_tw_{code}", label_visibility="collapsed")
            with c_ctrl3: layers_sel = st.multiselect("圖層開關", ["K棒", "MA3", "MA5", "MA10", "MA23"], default=["K棒", "MA3", "MA5", "MA10", "MA23"], key=f"layers_tw_{code}", label_visibility="collapsed")

            c_chart1, c_chart2 = st.columns(2)
            with c_chart1: render_mini_chart(df_1m, cdp_nh, cdp_nl, curr_p, alerts, is_us=False)
            with c_chart2: render_kline_chart(tf_sel, df_1m, df_5k, df_15k, df_daily, curr_p, alerts, is_us=False, visible_layers=layers_sel)

            # 🔥 統一且華麗的「智能監控與自動化交易面板」
            with st.expander("⚙️ 智能監控與自動化交易面板", expanded=False):
                if st.session_state.authenticated:
                    st.markdown("##### 🛡️ 持倉設定與雲端停損防線")
                    c_pos1, c_pos2, c_pos3, c_pos4, c_pos5 = st.columns([1, 1, 1, 1, 1])
                    with c_pos1: new_trade_type = st.selectbox("交易類型", ["當沖", "留倉"], index=0 if my_tt == "當沖" else 1, key=f"tt_tw_{code}")
                    with c_pos2: new_dir = st.selectbox("方向", ["作多", "作空"], index=0 if my_dir == "作多" else 1, key=f"dir_tw_{code}")
                    with c_pos3: new_price = st.number_input("基準均價", value=my_p, step=0.5, key=f"my_p_tw_{code}")
                    with c_pos4: new_lots = st.number_input("口/張數", value=my_l, min_value=1, step=1, key=f"my_l_tw_{code}")
                    with c_pos5: new_sl = st.number_input("雲端停損價", value=sl_p, step=0.5, key=f"sl_tw_{code}")
                    
                    if new_trade_type != my_tt or new_dir != my_dir or new_price != my_p or new_lots != my_l or new_sl != sl_p:
                        st.session_state.tw_stocks[idx]['my_trade_type'] = new_trade_type; st.session_state.tw_stocks[idx]['my_dir'] = new_dir; st.session_state.tw_stocks[idx]['my_price'] = new_price; st.session_state.tw_stocks[idx]['my_lots'] = new_lots; st.session_state.tw_stocks[idx]['stop_loss'] = new_sl; st.session_state.tw_stocks[idx]['sl_triggered'] = False
                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks); st.rerun()

                    st.markdown("##### 🎯 攻擊發起線 (監控觸發)")
                    for a_idx, al in enumerate(alerts):
                        c_type, c_cond, c_inp, c_auto, c_ret, c_del_al = st.columns([2, 1.5, 2, 2.5, 2, 0.5])
                        opts = ["固定價格", "當日VWAP", "5分K_10MA", "15分K_10MA", "CDP_NH(壓力)", "CDP_NL(支撐)", "5K首K高", "5K首K低"]
                        current_type = al.get('type', "固定價格") if al.get('type', "固定價格") in opts else "固定價格"
                        
                        with c_type:
                            new_type = st.selectbox("監控目標", opts, index=opts.index(current_type), key=f"type_tw_{code}_{a_idx}", label_visibility="collapsed")
                        with c_cond:
                            new_cond = st.selectbox("方向", [">= 漲破", "<= 跌破"], index=0 if al['cond'] == ">=" else 1, key=f"cond_tw_{code}_{a_idx}", label_visibility="collapsed")
                        with c_inp:
                            if current_type == "固定價格":
                                new_t_price = st.number_input("警示價", value=float(al['price']), step=0.5, key=f"inp_{code}_{a_idx}", label_visibility="collapsed")
                            else: st.markdown(f"<div style='padding-top:5px; color:#cbd5e1;'>現值: **{mas.get(current_type, 0.0):.2f}**</div>", unsafe_allow_html=True)
                        with c_auto:
                            new_auto = st.checkbox("✅ 觸發即下單", value=al.get('auto_trade', False), key=f"auto_{code}_{a_idx}")
                        with c_ret:
                            new_ret = st.checkbox("🛡️ 回測兩次才下單", value=al.get('require_retest', False), key=f"ret_{code}_{a_idx}", disabled=not al.get('auto_trade', False))
                        with c_del_al:
                            if st.button("🗑️", key=f"del_al_{code}_{a_idx}"): st.session_state.tw_stocks[idx]['alerts'].pop(a_idx); save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks); st.rerun()

                        if new_type != current_type or ("固定價格" in current_type and new_t_price != al['price']) or (">=" in new_cond and al['cond'] != ">=") or ("<=" in new_cond and al['cond'] != "<=") or new_auto != al.get('auto_trade') or new_ret != al.get('require_retest'):
                            st.session_state.tw_stocks[idx]['alerts'][a_idx].update({'type': new_type, 'cond': ">=" if ">=" in new_cond else "<=", 'price': new_t_price if current_type == "固定價格" else al['price'], 'auto_trade': new_auto, 'require_retest': new_ret, 'triggered': False, 'touch_2_triggered': False, 'trade_fired': False})
                            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks); st.rerun()

                    c_btn1, c_btn2, _ = st.columns([2, 2, 3])
                    with c_btn1:
                        if st.button("➕ 新增防線", key=f"add_al_tw_{code}"): st.session_state.tw_stocks[idx]['alerts'].append({"type": "固定價格", "price": 0.0, "cond": ">=", "triggered": False, "touch_2_triggered": False, "auto_trade": False, "require_retest": False, "trade_fired": False}); st.rerun()
                    with c_btn2:
                        if st.button("🤖 AI 算價", key=f"ai_p_{code}"):
                            with st.spinner("AI 運算中..."): cb_ai_calc_price_tw(idx, code, curr_p); st.rerun()

                    st.markdown("---")
                    c_order1, c_order2, c_order3 = st.columns([2, 1, 1])
                    with c_order1: st.markdown(f"⚡ **強制手動介入區**")
                    with c_order2:
                        if st.button(f"🔴 市價買進", key=f"fire_b_tw_{code}", use_container_width=True, type="primary"):
                            res = fire_order_to_agent(code, curr_p, "Buy", my_l)
                            if res.get('status') == 'success': st.toast(f"✅ 已手動送出買進指令", icon='🔥')
                            else: st.error(f"❌ {res.get('msg')}")
                    with c_order3:
                        if st.button(f"🟢 市價賣出", key=f"fire_s_tw_{code}", use_container_width=True):
                            res = fire_order_to_agent(code, curr_p, "Sell", my_l)
                            if res.get('status') == 'success': st.toast(f"✅ 已手動送出賣出指令", icon='❄️')
                            else: st.error(f"❌ {res.get('msg')}")
                else: st.warning("🔒 請先通過左側 2FA 雙因子認證，解鎖自動化下單權限。")

# ====================
# 戰區 2：美股波段戰情
# ====================
with tab_us:
    if not st.session_state.us_stocks: st.info("請至側邊欄加入美股標的。")
    for idx, stock in enumerate(st.session_state.us_stocks):
        code, name = stock['code'], stock['name']; alerts = stock.get('alerts', [])
        df_daily, suffix = get_historical_features(code, is_us=True)
        df_1m_us, curr_p, prev_p = get_realtime_tick_and_price(code, suffix, fast_cache_key)
        df_5k = get_kline_data(code, suffix, '5m', t5_key)
        df_15k = get_kline_data(code, suffix, '15m', t15_key)
        
        mas = {}; cdp_nh = cdp_nl = 0.0
        if not df_1m_us.empty:
            df_1m_us['Cum_Vol'] = df_1m_us['Volume'].cumsum()
            df_1m_us['Cum_PV'] = (((df_1m_us['High'] + df_1m_us['Low'] + df_1m_us['Close']) / 3) * df_1m_us['Volume']).cumsum()
            df_1m_us['VWAP'] = (df_1m_us['Cum_PV'] / df_1m_us['Cum_Vol'].replace(0, np.nan)).bfill().fillna(df_1m_us['Close'])
            mas['當日VWAP'] = df_1m_us['VWAP'].iloc[-1]

        if curr_p is None: curr_p = df_1m_us['Close'].iloc[-1] if not df_1m_us.empty else 0.0
        if prev_p is None: prev_p = curr_p
        
        if not df_5k.empty:
            mas['5分K_10MA'] = df_5k['Close'].tail(10).mean()
            df_5k_tz = df_5k.copy()
            df_5k_tz.index = df_5k_tz.index.tz_convert('America/New_York')
            df_5k_today = df_5k_tz[df_5k_tz.index.date == pd.Timestamp.now(tz='America/New_York').date()]
            if not df_5k_today.empty:
                mas['5K首K高'] = df_5k_today.iloc[0]['High']; mas['5K首K低'] = df_5k_today.iloc[0]['Low']
                
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
                t_p_label = f"${t_p}" if al_type == '固定價格' else f"{al_type} (${t_p:.2f})"
                if (cond == ">=" and curr_p >= t_p) or (cond == "<=" and curr_p <= t_p):
                    is_alert = True
                    if not al.get('triggered', False): 
                        triggered_msgs.append(f"{'漲破' if cond=='>=' else '跌破'} {t_p_label}")
                        st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = True
                        if al.get('auto_trade', False) and not al.get('require_retest', False) and not al.get('trade_fired', False) and st.session_state.authenticated:
                            act = "buy" if stock.get('my_dir', '作多') == "作多" else "sell"
                            res = fire_order_to_agent(code, float(stock.get('my_price', curr_p)), act, int(stock.get('my_shares', 1)))
                            if res.get('status') == 'success': 
                                send_telegram_alert(f"🚀 【自動下單成功】\n{code} 首度觸發設定價\n已自動送出 {act.upper()} 委託！")
                                st.session_state.us_stocks[idx]['alerts'][a_idx]['trade_fired'] = True

                touches = 0
                if not df_1m_us.empty and len(df_1m_us) >= 15:
                    if cond == ">=": touches = max((df_1m_us['High'].tail(15) >= t_p).sum(), 1 if curr_p >= t_p else 0)
                    else: touches = max((df_1m_us['Low'].tail(15) <= t_p).sum(), 1 if curr_p <= t_p else 0)

                if touches >= 2 and not al.get('touch_2_triggered', False):
                    send_telegram_alert(f"⚠️ 🦅【美股叩關確認】\n{code} 近 15 分鐘測試 {t_p_label} 達 {touches} 次！")
                    st.session_state.us_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = True
                    if al.get('auto_trade', False) and al.get('require_retest', False) and not al.get('trade_fired', False) and st.session_state.authenticated:
                        act = "buy" if stock.get('my_dir', '作多') == "作多" else "sell"
                        res = fire_order_to_agent(code, float(stock.get('my_price', curr_p)), act, int(stock.get('my_shares', 1)))
                        if res.get('status') == 'success': 
                            send_telegram_alert(f"🚀 【自動下單成功】\n{code} 多次回測確認完畢\n已自動送出 {act.upper()} 委託！")
                            st.session_state.us_stocks[idx]['alerts'][a_idx]['trade_fired'] = True

                if cond == ">=" and curr_p < t_p * 0.995: st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = False; st.session_state.us_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False
                if cond == "<=" and curr_p > t_p * 1.005: st.session_state.us_stocks[idx]['alerts'][a_idx]['triggered'] = False; st.session_state.us_stocks[idx]['alerts'][a_idx]['touch_2_triggered'] = False

        sl_p = float(stock.get('stop_loss', 0.0))
        if sl_p > 0 and not stock.get('sl_triggered', False) and st.session_state.authenticated and int(stock.get('my_shares', 0)) > 0:
            if stock.get('my_dir') == '作多' and curr_p <= sl_p:
                res = fire_order_to_agent(code, curr_p, "Sell", int(stock.get('my_shares', 1)))
                if res.get('status') == 'success':
                    send_telegram_alert(f"💥 【雲端停損觸發】\n{code} 跌破停損價 {sl_p}\n已自動送出市價平倉 (SELL) 委託！")
                    st.session_state.us_stocks[idx]['sl_triggered'] = True
            elif stock.get('my_dir') == '作空' and curr_p >= sl_p:
                res = fire_order_to_agent(code, curr_p, "Buy", int(stock.get('my_shares', 1)))
                if res.get('status') == 'success':
                    send_telegram_alert(f"💥 【雲端停損觸發】\n{code} 漲破停損價 {sl_p}\n已自動送出市價平倉 (BUY) 委託！")
                    st.session_state.us_stocks[idx]['sl_triggered'] = True

        if triggered_msgs: save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

        with st.container(border=True):
            my_p_us, my_l_us, my_dir_us = float(stock.get('my_price', 0.0)), int(stock.get('my_shares', 10)), stock.get('my_dir', '作多')
            c_title, c_p, c_pnl, c_r1, c_s1, c_del = st.columns([2.5, 1.5, 1.5, 1, 1, 0.5])
            with c_title: st.markdown(f"#### 🦅 {code}")
            
            diff = curr_p - prev_p; pct = (diff / prev_p) * 100 if prev_p > 0 else 0
            with c_p: st.metric("實時現價", f"${curr_p:.2f}", f"{diff:+.2f} ({pct:+.2f}%)", delta_color="normal" if diff >= 0 else "inverse")
            
            with c_pnl:
                if my_p_us > 0:
                    if st.session_state.authenticated:
                        pnl_us = (curr_p - my_p_us) * my_l_us if my_dir_us == "作多" else (my_p_us - curr_p) * my_l_us
                        st.metric("未實現損益", f"${pnl_us:,.2f}", f"{(pnl_us / (my_p_us * my_l_us)) * 100 if my_p_us > 0 else 0:+.2f}%", delta_color="normal" if pnl_us > 0 else "inverse")
                    else: st.metric("未實現損益", "*** (鎖定)", "登入後查看", delta_color="off")
                else: st.metric("未實現損益", "--", delta_color="off")
            with c_r1: st.metric("壓力(R1)", f"${r1:.2f}", delta_color="off")
            with c_s1: st.metric("支撐(S1)", f"${s1:.2f}", delta_color="off")
            with c_del: 
                if st.button("❌", key=f"del_us_{code}"): cb_remove_us(idx); st.rerun()
            
            if is_alert: st.error(f"🚨 **到價警示！** 現價 ${curr_p} 已觸發設定目標")
            
            corr_codes = get_correlated_stocks(code, code, API_KEY, is_us=True)
            if not corr_codes:
                if API_KEY:
                    col_m, col_b = st.columns([5, 1])
                    col_m.markdown("<div style='font-size:0.9rem; color:#94a3b8; margin-top:5px; margin-bottom:10px;'>🔗 <b>族群聯動雷達：</b> 網路擁塞，暫無資料。</div>", unsafe_allow_html=True)
                    if col_b.button("🔄 重試", key=f"retry_corr_us_{code}"): get_correlated_stocks.clear(code, code, API_KEY, is_us=True); st.rerun()
            else:
                corr_display = []
                for i, c in enumerate(corr_codes):
                    icon = "👑" if i == 0 else "🔗"
                    _, cp, pp = get_realtime_tick_and_price(c, "", fast_cache_key) 
                    if cp is not None and pp is not None and pp > 0:
                        diff_c = cp - pp; pct_c = (diff_c / pp) * 100; sign_c = "+" if diff_c > 0 else ""
                        color_c = '#10b981' if diff_c > 0 else '#ef4444' if diff_c < 0 else '#94a3b8'
                        corr_display.append(f"<b>{icon} {c}</b> {cp:.2f} (<span style='color:{color_c};'>{sign_c}{diff_c:.2f}, {sign_c}{pct_c:.2f}%</span>)")
                    else: corr_display.append(f"<b>{icon} {c}</b> 讀取中...")
                st.markdown(f"<div style='font-size:0.95rem; margin-top:5px; margin-bottom:10px; padding:8px; background-color:rgba(30,41,59,0.5); border-radius:8px;'>🔗 <b>高度聯動：</b> {' ｜ '.join(corr_display)}</div>", unsafe_allow_html=True)
            
            st.divider()
            
            c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([1.5, 1, 1])
            with c_ctrl1: st.markdown("##### 📉 雙視角走勢與無縫 K 線圖")
            with c_ctrl2: tf_sel = st.selectbox("切換時區", ["1K", "5K", "15K", "日K"], index=3, key=f"tf_us_{code}", label_visibility="collapsed")
            with c_ctrl3: layers_sel = st.multiselect("圖層開關", ["K棒", "MA3", "MA5", "MA10", "MA23"], default=["K棒", "MA3", "MA5", "MA10", "MA23"], key=f"layers_us_{code}", label_visibility="collapsed")

            c_chart1, c_chart2 = st.columns(2)
            with c_chart1: render_mini_chart(df_1m_us, cdp_nh, cdp_nl, curr_p, alerts, is_us=True)
            with c_chart2: render_kline_chart(tf_sel, df_1m_us, df_5k, df_15k, df_daily, curr_p, alerts, is_us=True, visible_layers=layers_sel)

            with st.expander("⚙️ 智能監控與自動化交易面板", expanded=False):
                if st.session_state.authenticated:
                    st.markdown("##### 🛡️ 持倉設定與雲端停損防線")
                    c_pos1, c_pos2, c_pos3, c_pos4, c_pos5 = st.columns([1, 1, 1, 1, 1])
                    with c_pos1: new_dir = st.selectbox("方向", ["作多", "作空"], index=0 if my_dir_us == "作多" else 1, key=f"dir_us_{code}")
                    with c_pos2: new_price = st.number_input("基準均價", value=my_p_us, step=1.0, key=f"my_p_us_{code}")
                    with c_pos3: new_shares = st.number_input("股數", value=my_l_us, min_value=1, step=1, key=f"my_l_us_{code}")
                    with c_pos4: new_sl = st.number_input("雲端停損價", value=sl_p, step=1.0, key=f"sl_us_{code}")
                    
                    if new_dir != my_dir_us or new_price != my_p_us or new_shares != my_l_us or new_sl != sl_p:
                        st.session_state.us_stocks[idx]['my_dir'] = new_dir; st.session_state.us_stocks[idx]['my_price'] = new_price; st.session_state.us_stocks[idx]['my_shares'] = new_shares; st.session_state.us_stocks[idx]['stop_loss'] = new_sl; st.session_state.us_stocks[idx]['sl_triggered'] = False
                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks); st.rerun()

                    st.markdown("##### 🎯 攻擊發起線 (監控觸發)")
                    for a_idx, al in enumerate(alerts):
                        c_type, c_cond, c_inp, c_auto, c_ret, c_del_al = st.columns([2, 1.5, 2, 2.5, 2, 0.5])
                        opts = ["固定價格", "當日VWAP", "5分K_10MA", "15分K_10MA", "CDP_NH(壓力)", "CDP_NL(支撐)", "5K首K高", "5K首K低"]
                        current_type = al.get('type', "固定價格") if al.get('type', "固定價格") in opts else "固定價格"
                        
                        with c_type:
                            new_type = st.selectbox("監控目標", opts, index=opts.index(current_type), key=f"type_us_{code}_{a_idx}", label_visibility="collapsed")
                        with c_cond:
                            new_cond = st.selectbox("方向", [">= 漲破", "<= 跌破"], index=0 if al['cond'] == ">=" else 1, key=f"cond_us_{code}_{a_idx}", label_visibility="collapsed")
                        with c_inp:
                            if current_type == "固定價格":
                                new_t_price = st.number_input("警示價", value=float(al['price']), step=1.0, key=f"inp_us_{code}_{a_idx}", label_visibility="collapsed")
                            else: st.markdown(f"<div style='padding-top:5px; color:#cbd5e1;'>現值: **${mas.get(current_type, 0.0):.2f}**</div>", unsafe_allow_html=True)
                        with c_auto:
                            new_auto = st.checkbox("✅ 觸發即下單", value=al.get('auto_trade', False), key=f"auto_us_{code}_{a_idx}")
                        with c_ret:
                            new_ret = st.checkbox("🛡️ 回測兩次才下單", value=al.get('require_retest', False), key=f"ret_us_{code}_{a_idx}", disabled=not al.get('auto_trade', False))
                        with c_del_al:
                            if st.button("🗑️", key=f"del_al_us_{code}_{a_idx}"): st.session_state.us_stocks[idx]['alerts'].pop(a_idx); save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks); st.rerun()

                        if new_type != current_type or ("固定價格" in current_type and new_t_price != al['price']) or (">=" in new_cond and al['cond'] != ">=") or ("<=" in new_cond and al['cond'] != "<=") or new_auto != al.get('auto_trade') or new_ret != al.get('require_retest'):
                            st.session_state.us_stocks[idx]['alerts'][a_idx].update({'type': new_type, 'cond': ">=" if ">=" in new_cond else "<=", 'price': new_t_price if current_type == "固定價格" else al['price'], 'auto_trade': new_auto, 'require_retest': new_ret, 'triggered': False, 'touch_2_triggered': False, 'trade_fired': False})
                            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks); st.rerun()

                    c_btn1, c_btn2, _ = st.columns([2, 2, 3])
                    with c_btn1:
                        if st.button("➕ 新增防線", key=f"add_al_us_{code}"): st.session_state.us_stocks[idx]['alerts'].append({"type": "固定價格", "price": 0.0, "cond": ">=", "triggered": False, "touch_2_triggered": False, "auto_trade": False, "require_retest": False, "trade_fired": False}); st.rerun()
                    with c_btn2:
                        if st.button("🤖 AI 算價", key=f"ai_p_us_{code}"):
                            with st.spinner("AI 運算中..."): cb_ai_calc_price_tw(idx, code, curr_p); st.rerun()

                    st.markdown("---")
                    c_order1, c_order2, c_order3 = st.columns([2, 1, 1])
                    with c_order1: st.markdown(f"⚡ **強制手動介入區**")
                    with c_order2:
                        if st.button(f"🔴 市價買進", key=f"fire_b_us_{code}", use_container_width=True, type="primary"):
                            res = fire_order_to_agent(code, curr_p, "Buy", my_l_us)
                            if res.get('status') == 'success': st.toast(f"✅ 已手動送出買進指令", icon='🔥')
                            else: st.error(f"❌ {res.get('msg')}")
                    with c_order3:
                        if st.button(f"🟢 市價賣出", key=f"fire_s_us_{code}", use_container_width=True):
                            res = fire_order_to_agent(code, curr_p, "Sell", my_l_us)
                            if res.get('status') == 'success': st.toast(f"✅ 已手動送出賣出指令", icon='❄️')
                            else: st.error(f"❌ {res.get('msg')}")
                else: st.warning("🔒 請先通過左側 2FA 雙因子認證，解鎖自動化下單權限。")

# ====================
# 戰區 3：🤖 AI 選股報告中心
# ====================
with tab_ai:
    st.markdown("### 🤖 跨海智能 AI 選股報告中心")
    st.caption("💡 點擊下方對應的頁籤切換不同策略報告。若無資料，請至左側邊欄點擊對應的「生成」按鈕。")
    
    ai_tabs = st.tabs(["🚀 台股當沖", "🌙 台股隔日沖", "🦅 台股波段", "🇺🇸 美股專區"])
    reports_mapping = [(ai_tabs[0], st.session_state.ai_report_daytrade, "台股"), (ai_tabs[1], st.session_state.ai_report_overnight, "台股"), (ai_tabs[2], st.session_state.ai_report_swing, "台股"), (ai_tabs[3], st.session_state.ai_report_us, "美股")]
    
    for tab, report, market_type in reports_mapping:
        with tab:
            if not report: st.info("尚無報告，請至側邊欄點選生成對應的策略報告。")
            else:
                sub_tabs = st.tabs(list(report.keys()))
                for i, (cat, stocks) in enumerate(report.items()):
                    with sub_tabs[i]:
                        for s in stocks:
                            _, c_p, _ = get_realtime_tick_and_price(s['code'], "" if market_type=="美股" else ".TW", fast_cache_key)
                            if c_p is None and market_type=="台股": _, c_p, _ = get_realtime_tick_and_price(s['code'], ".TWO", fast_cache_key)
                            
                            target = 0; cond = ">="
                            if c_p:
                                if "空" in cat: target = round(c_p * 0.985, 2); cond = "<="
                                elif "多" in cat: target = round(c_p * 1.015, 2)
                                else: target = round(c_p * 1.05, 2)
                            
                            with st.expander(f"🎯 {s['name']}({s['code']}) | 真實現價: {c_p or '--'} | 建議目標價: {target}"):
                                st.write(f"**策略理由**：{s.get('strategy', '')}")
                                btn_txt = f"➕ 帶入目標價 {target} 且監控 {'跌破' if cond=='<=' else '漲破'}"
                                if market_type == "美股": 
                                    if st.button(btn_txt, key=f"btn_u_{s['code']}_{target}_{cat}"): cb_add_us(s['code'], s['name'], target, cond); st.rerun()
                                else: 
                                    if st.button(btn_txt, key=f"btn_t_{s['code']}_{target}_{cat}"): cb_add_tw(s['code'], s['name'], target, cond); st.rerun()

# ====================
# 戰區 4：10年核心資產
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

# ====================
# 戰區 5：📡 爆量雷達快篩
# ====================
with tab_radar:
    st.markdown("### 📡 盤中動態爆量雷達")
    st.caption("💡 請在此貼上您想掃描的自選股清單（最多建議 50 檔），系統會自動比對當前是否有異常大單爆量。")
    default_pool = "2330, 2317, 2454, 3231, 2382, 3443, 2368, 2303, 3034, 2603"
    scan_pool_input = st.text_area("🎯 掃描目標代碼 (用逗號隔開)", value=default_pool)
    
    if st.button("🚀 啟動全域爆量掃描", type="primary"):
        pool_codes = [c.strip() for c in scan_pool_input.split(",") if c.strip()]
        if not pool_codes: st.warning("請先輸入要掃描的股票代碼。")
        else:
            with st.spinner(f"正在掃描 {len(pool_codes)} 檔股票的即時量能，請稍候..."):
                found_targets = []
                progress_bar = st.progress(0)
                
                for i, code in enumerate(pool_codes):
                    time.sleep(0.1); progress_bar.progress((i + 1) / len(pool_codes))
                    df_1m, curr_p, _ = get_realtime_tick_and_price(code, ".TW", fast_cache_key)
                    if df_1m.empty: df_1m, curr_p, _ = get_realtime_tick_and_price(code, ".TWO", fast_cache_key)
                    
                    if not df_1m.empty:
                        df_m = df_1m.copy()
                        df_m['Time'] = df_m.index.tz_convert('Asia/Taipei')
                        latest_time = df_m['Time'].iloc[-1]
                        today_start = latest_time.replace(hour=0, minute=0, second=0, microsecond=0)
                        df_today = df_m[df_m['Time'] >= today_start].copy()
                        
                        if len(df_today) > 5:
                            df_today['Vol_MA10'] = df_today['Volume'].rolling(10, min_periods=1).mean()
                            avg_vol_day = df_today['Volume'].mean()
                            spike_cond = (df_today['Volume'] > df_today['Vol_MA10'] * 2.0) & (df_today['Volume'] > avg_vol_day * 1.5) & (df_today['Volume'] >= 50000)
                            spikes = df_today[spike_cond].copy()
                            
                            if not spikes.empty:
                                if curr_p is None: curr_p = df_today['Close'].iloc[-1]
                                max_spike = spikes.loc[spikes['Volume'].idxmax()]
                                t_str = max_spike['Time'].strftime("%H:%M"); is_buy = max_spike['Close'] >= max_spike['Open']
                                action = "大單敲進" if is_buy else "大單倒貨"; v_disp = max_spike['Volume'] / 1000
                                found_targets.append({"code": code, "price": curr_p, "time": t_str, "vol": v_disp, "action": action, "is_buy": is_buy})
                
                progress_bar.empty()
                if found_targets:
                    st.success(f"🎯 掃描完畢！共發現 **{len(found_targets)}** 檔股票出現異常爆量：")
                    for t in found_targets:
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([2, 3, 1])
                            c1.markdown(f"#### **{t['code']}**"); icon = "🔴" if t['is_buy'] else "🟢"; color = "#ef4444" if t['is_buy'] else "#10b981"
                            c2.markdown(f"現價: **{t['price']}** <br> <span style='color:{color}'>{icon} {t['time']} | 爆出 {t['vol']:,.0f} 張 ({t['action']})</span>", unsafe_allow_html=True)
                            if c3.button("➕ 加入監控", key=f"radar_add_{t['code']}"): cb_add_tw(t['code'], t['code']); st.rerun()
                else: st.info("掃描完畢。目前的目標池中尚未發現明顯的 5K/15K 爆量跡象。")

if auto_refresh:
    time.sleep(3)
    try: st.rerun()
    except AttributeError: st.experimental_rerun()
