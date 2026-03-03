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
import copy
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
    if code and code not in [s['code'] for s in st.session_state.tw_stocks]:
        st.session_state.tw_stocks.append({"code": code, "name": name, "target_price": float(target_price), "condition": condition, "alert_triggered": False, "ai_advice": ""})
        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

def cb_add_us(code, name, target_price=0.0, condition=">="):
    if code and code not in [s['code'] for s in st.session_state.us_stocks]:
        st.session_state.us_stocks.append({"code": code, "name": name, "target_price": float(target_price), "condition": condition, "alert_triggered": False, "ai_advice": ""})
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

# 初始化
if 'initialized' not in st.session_state:
    data = load_watchlist()
    st.session_state.tw_stocks = data.get("tw", [])
    st.session_state.us_stocks = data.get("us", [])
    st.session_state.ai_report_dt = None
    st.session_state.ai_report_swing = None
    st.session_state.core_assets = [{"code": "0050", "is_us": False}, {"code": "009816", "is_us": False}, {"code": "QQQM", "is_us": True}]
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

# 🚀 移除快取，並加入 _t 破壞快取機制確保報價絕對即時更新
def get_realtime_tick(code, suffix):
    if suffix is None: return pd.DataFrame()
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        # 強制加入 timestamp 避免 Yahoo 伺服器回傳舊資料
        res_1m = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1m&range=1d&_t={int(time.time())}", headers=headers, timeout=3).json()
        idx_1m = pd.to_datetime(res_1m['chart']['result'][0]['timestamp'], unit='s', utc=True)
        q = res_1m['chart']['result'][0]['indicators']['quote'][0]
        return pd.DataFrame({'Open': q['open'], 'High': q['high'], 'Low': q['low'], 'Close': q['close'], 'Volume': q['volume']}, index=idx_1m).dropna()
    except: return pd.DataFrame()

# 🚀 移除快取確保連動股與最新價格即時跳動
def get_live_price(code, is_us=False):
    headers = {"User-Agent": "Mozilla/5.0"}
    suffixes = [""] if is_us else [".TW", ".TWO"]
    for suffix in suffixes:
        try:
            res = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range=5d&_t={int(time.time())}", headers=headers, timeout=2).json()
            closes = [c for c in res['chart']['result'][0]['indicators']['quote'][0]['close'] if c is not None]
            if len(closes) >= 2: return closes[-1], closes[-2]
        except: continue
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
        res = ai_model.generate_content(f"針對 {market} {name}({code})，找出 3 檔同產業高連動股票。第一檔須為絕對龍頭。回傳純代碼逗號分隔，不要多餘文字。", generation_config=genai.types.GenerationConfig(temperature=0.0)).text
        return [c.strip() for c in res.split(',') if c.strip() != ''][:3]
    except: return []

# --- 3. 介面渲染 ---
st.title("⚡ AI 跨海智能戰情室")
all_stocks = get_full_stock_db()
market_temp = get_market_temp()

# 頂部大盤溫度與更新時間
col_t1, col_t2, col_t3 = st.columns(3)
with col_t1:
    if '台股加權' in market_temp:
        st.metric("🇹🇼 台股大盤溫度", f"{market_temp['台股加權'][0]:.2f}", f"{market_temp['台股加權'][1]:.2f}%", delta_color="normal" if market_temp['台股加權'][1] > 0 else "inverse")
with col_t2:
    if '那斯達克' in market_temp:
        st.metric("🇺🇸 科技股溫度 (Nasdaq)", f"{market_temp['那斯達克'][0]:.2f}", f"{market_temp['那斯達克'][1]:.2f}%", delta_color="normal" if market_temp['那斯達克'][1] > 0 else "inverse")
with col_t3:
    if API_KEY: st.success(f"🟢 API 火力全開 | 最後更新: {datetime.datetime.now().strftime('%H:%M:%S')}")
    else: st.error("🔴 API 未設定")

st.divider()

# 側邊欄控制
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
        code = selected_tw.split(" ")[0]
        name = " ".join(selected_tw.split(" ")[1:])
        st.button(f"➕ 加入 {name} (台股)", on_click=cb_add_tw, args=(code, name))

    us_code = st.text_input("🇺🇸 輸入美股代碼 (如 NVDA)").strip().upper()
    if us_code:
        st.button(f"➕ 加入 {us_code} (美股)", on_click=cb_add_us, args=(us_code, us_code))
            
    st.divider()
    auto_refresh = st.checkbox("⚡ 開啟極速自動更新 (3秒)", value=False)
    st.button("🗑️ 徹底清空所有資料", on_click=cb_clear_all, type="secondary")

# 顯示分流報告 (即時校正股價)
for report in [st.session_state.ai_report_dt, st.session_state.ai_report_swing]:
    if report:
        with st.container(border=True):
            tabs = st.tabs(list(report.keys()))
            for i, (cat, stocks) in enumerate(report.items()):
                with tabs[i]:
                    for s in stocks:
                        c_p, _ = get_live_price(s['code'], "美股" in cat)
                        target = 0
                        cond = ">="
                        if c_p:
                            if "空" in cat:
                                target = round(c_p * 0.985, 2)
                                cond = "<="
                            elif "多" in cat:
                                target = round(c_p * 1.015, 2)
                            else:
                                target = round(c_p * 1.05, 2)
                        
                        with st.expander(f"🎯 {s['name']}({s['code']}) | 真實現價: {c_p or '--'} | 目標價: {target}"):
                            st.write(f"**策略理由**：{s.get('strategy', '')}")
                            btn_txt = f"➕ 帶入目標價 {target} 且監控 {'跌破' if cond=='<=' else '漲破'}"
                            if "美股" in cat:
                                st.button(btn_txt, key=f"btn_u_{s['code']}", on_click=cb_add_us, args=(s['code'], s['name'], target, cond))
                            else:
                                st.button(btn_txt, key=f"btn_t_{s['code']}", on_click=cb_add_tw, args=(s['code'], s['name'], target, cond))

# 監控分頁
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
        ai_advice = stock.get('ai_advice', '') # 🚀 讀取專屬 AI 建議
        
        df_daily, ma20_15k, suffix = get_historical_features(code, is_us=False)
        df_1m = get_realtime_tick(code, suffix)
        
        if not df_1m.empty and ma20_15k is not None and not df_daily.empty:
            curr_p = df_1m['Close'].iloc[-1]
            prev_p = df_daily['Close'].iloc[-2] if len(df_daily) > 1 else curr_p
            vwap = ( (df_1m['High'] + df_1m['Low'] + df_1m['Close'])/3 * df_1m['Volume'] ).sum() / (df_1m['Volume'].sum() + 0.001)
            
            # 🚀 5K / 15K 爆量動能偵測引擎 (確保隨時顯示運作狀態)
            vol_alert_msg = ""
            vol_info = ""
            if len(df_1m) >= 15:
                df_1m['Volume'] = df_1m['Volume'].fillna(0)
                avg_vol_1m = df_1m['Volume'].mean()
                if avg_vol_1m > 0:
                    vol_5m = df_1m['Volume'].tail(5).sum()
                    vol_15m = df_1m['Volume'].tail(15).sum()
                    ratio_5k = vol_5m / (avg_vol_1m * 5)
                    ratio_15k = vol_15m / (avg_vol_1m * 15)
                    
                    vol_info = f"量能比例: 5K({ratio_5k:.1f}x) | 15K({ratio_15k:.1f}x)"
                    if ratio_5k > 2.5: vol_alert_msg += "🔥 5K急行爆量！ "
                    if ratio_15k > 2.0: vol_alert_msg += "🔥 15K波段爆量！"
            
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
                if cond == ">=" and curr_p < t_price * 0.995: st.session_state.tw_stocks[idx]['alert_triggered'] = False
                if cond == "<=" and curr_p > t_price * 1.005: st.session_state.tw_stocks[idx]['alert_triggered'] = False

            with st.container(border=True):
                c_title, c_del = st.columns([5, 1])
                with c_title: st.markdown(f"#### {name}({code})")
                with c_del: st.button("❌ 移除", key=f"del_tw_{code}", on_click=cb_remove_tw, args=(idx,))

                if is_alert: st.error(f"🚨 **到價警示！** 現價 {curr_p} 已觸發 {cond} 目標 {t_price}")
                
                # 🚀 顯示爆量與常駐量能狀態
                if vol_alert_msg: st.warning(f"📊 **動能偵測**：{vol_alert_msg} ({vol_info})")
                elif vol_info: st.caption(f"📉 {vol_info}")

                # 🚀 顯示 AI 雙向算價結果
                if ai_advice: st.success(ai_advice)
                
                c_cond, c_inp, c_ai = st.columns([1.5, 2, 1])
                with c_cond:
                    new_cond = st.selectbox("方向", [">= 漲破", "<= 跌破"], index=0 if cond == ">=" else 1, key=f"cond_tw_{code}")
                    new_cond_val = ">=" if ">=" in new_cond else "<="
                    if new_cond_val != cond:
                        st.session_state.tw_stocks[idx]['condition'] = new_cond_val
                        st.session_state.tw_stocks[idx]['alert_triggered'] = False
                        st.rerun()
                with c_inp:
                    new_t_price = st.number_input(f"警示目標價", value=float(t_price), step=0.5, key=f"inp_{code}")
                    if new_t_price != t_price:
                        st.session_state.tw_stocks[idx]['target_price'] = new_t_price
                        st.session_state.tw_stocks[idx]['alert_triggered'] = False
                        st.rerun()
                with c_ai:
                    st.write("") 
                    # 🚀 AI 雙向算價按鈕：要求回傳進場與目標
                    if API_KEY and st.button("🤖 算價", key=f"ai_p_{code}"):
                        with st.spinner("..."):
                            try:
                                dir_str = '作多' if cond=='>=' else '作空'
                                prompt = f"針對台股 {name}({code}) 現價 {curr_p}，給出當沖{dir_str}建議。必須嚴格回傳JSON格式：{{\"entry\": 進場價數字, \"target\": 停利目標價數字}}"
                                res = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
                                match = re.search(r'\{.*\}', res, re.DOTALL)
                                if match:
                                    data = json.loads(match.group(0))
                                    st.session_state.tw_stocks[idx]['target_price'] = float(data['target'])
                                    st.session_state.tw_stocks[idx]['ai_advice'] = f"🤖 AI建議 -> 理想進場價: **{data['entry']}** | 停利目標: **{data['target']}**"
                                    st.session_state.tw_stocks[idx]['alert_triggered'] = False
                                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                                    st.rerun()
                            except: pass

                c1, c2, c3 = st.columns(3)
                c1.metric("現價", f"{curr_p:.2f}", f"{curr_p - prev_p:.2f}")
                c2.metric("當日VWAP", f"{vwap:.2f}")
                c3.metric("15K 20MA", f"{ma20_15k:.2f}")
                
                # 🚀 顯示連動股即時報價、漲跌與幅度
                corr_codes = get_correlated_stocks(code, name, is_us=False)
                if corr_codes:
                    corr_display = []
                    for i, c in enumerate(corr_codes):
                        c_name = all_stocks.get(c, c)
                        icon = "👑" if i == 0 else "🔗"
                        cp, pp = get_live_price(c, is_us=False)
                        if cp and pp and pp > 0:
                            diff = cp - pp
                            pct = (diff / pp) * 100
                            sign = "+" if diff > 0 else ""
                            corr_display.append(f"{icon} {c_name} {cp:.2f} ({sign}{diff:.2f}, {sign}{pct:.2f}%)")
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
        t_price = stock.get('target_price', 0.0)
        cond = stock.get('condition', '>=')
        ai_advice = stock.get('ai_advice', '')
        
        # 🚀 美股也破除快取，使用 get_live_price 抓現價
        curr_p, prev_p = get_live_price(code, is_us=True)
        df_daily, _, _ = get_historical_features(code, is_us=True)
        
        if curr_p and prev_p and not df_daily.empty:
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
                with c_del: st.button("❌ 移除", key=f"del_us_{code}", on_click=cb_remove_us, args=(idx,))

                if is_alert: st.error(f"🚨 **到價警示！** {code} 已觸發：現價 ${curr_p} {cond} 目標 ${t_price}")
                if ai_advice: st.success(ai_advice)
                
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
                                dir_str = '作多' if cond=='>=' else '作空'
                                prompt = f"針對美股 {code} 現價 {curr_p}，給出波段{dir_str}建議。必須嚴格回傳JSON格式：{{\"entry\": 進場價數字, \"target\": 停利目標價數字}}"
                                res = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
                                match = re.search(r'\{.*\}', res, re.DOTALL)
                                if match:
                                    data = json.loads(match.group(0))
                                    st.session_state.us_stocks[idx]['target_price'] = float(data['target'])
                                    st.session_state.us_stocks[idx]['ai_advice'] = f"🤖 AI建議 -> 理想進場價: **${data['entry']}** | 停利目標: **${data['target']}**"
                                    st.session_state.us_stocks[idx]['alert_triggered'] = False
                                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                                    st.rerun()
                            except: pass

                c1, c2, c3 = st.columns(3)
                c1.metric("收盤現價", f"${curr_p:.2f}", f"${curr_p - prev_p:.2f}")
                c2.metric("波段月線 (20MA)", f"${df_daily['Close'].tail(20).mean():.2f}")
                c3.metric("RSI", f"{df_daily['RSI'].iloc[-1]:.1f}", delta_color="off")
                
                # 🚀 美股連動股報價顯示
                corr_codes = get_correlated_stocks(code, code, is_us=True)
                if corr_codes:
                    corr_display = []
                    for i, c in enumerate(corr_codes):
                        icon = "👑" if i == 0 else "🔗"
                        cp, pp = get_live_price(c, is_us=True)
                        if cp and pp and pp > 0:
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
