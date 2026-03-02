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
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg}, timeout=2)
    except: pass

# --- 💾 永久記憶資料庫系統 ---
DATA_FILE = "watchlist_data.json"

def load_watchlist():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"tw": [], "us": []}

def save_watchlist(tw, us):
    try:
        with open(DATA_FILE, "w", encoding='utf-8') as f:
            json.dump({"tw": tw, "us": us}, f, ensure_ascii=False)
    except: pass

# 狀態初始化 (讀取永久記憶)
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
            if len(closes) >= 2:
                results[name] = (closes[-1], ((closes[-1] - closes[-2]) / closes[-2]) * 100)
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
            rs = gain / (loss + 1e-9)
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
        except: continue
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

def get_advanced_ai_report():
    if not API_KEY: return {"error": "⚠️ 請先設定 API Key"}
    tw_tz = pytz.timezone('Asia/Taipei')
    now = datetime.datetime.now(tw_tz)
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    prompt = f"""
    現在是台灣時間 {time_str}。你是頂尖跨國操盤手。
    請嚴格依照 JSON 格式回傳實戰選股報告。
    【要求】：1. 台股150元以下。2. 各類別精準5檔且不重複。3. 價格請務必給出具體數字(例如 142.5)。
    JSON:
    {{
      "美股短波分析": [ 5筆資料 ],
      "資金熱點TOP5": [ 5筆台股資料 ],
      "台股當沖作多": [ 5筆台股資料 (高震幅) ],
      "台股當沖作空": [ 5筆台股資料 (高震幅) ]
    }}
    (格式：{{"code": "代碼", "name": "名稱", "price": "數字建議價位", "strategy": "判斷基準", "reason": "理由"}})
    """
    try:
        response = ai_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0)).text
        match = re.search(r'\{.*\}', response, re.DOTALL)
        return json.loads(match.group(0) if match else response)
    except Exception as e:
        if "429" in str(e): return {"error": "🚨 Google API 額度已滿，暫時切換純監控模式。"}
        return {"error": f"AI 產出錯誤: {e}"}

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
        val, pct = market_temp['台股加權']
        st.metric("🇹🇼 台股大盤溫度", f"{val:.2f}", f"{pct:.2f}%", delta_color="normal" if pct > 0 else "inverse")
with col_t2:
    if '那斯達克' in market_temp:
        val, pct = market_temp['那斯達克']
        st.metric("🇺🇸 科技股溫度 (Nasdaq)", f"{val:.2f}", f"{pct:.2f}%", delta_color="normal" if pct > 0 else "inverse")
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
    
    if TG_BOT_TOKEN and TG_CHAT_ID:
        st.success("📱 Telegram 推播已啟用")
    else:
        st.warning("📱 尚未設定 Telegram (設定 st.secrets 即可啟用)")

    st.divider()
    st.header("🤖 AI 獨家選股報告")
    if st.button("🚀 立即生成全盤選股報告", use_container_width=True, type="primary"):
        st.session_state.ai_report = "loading"
        st.rerun()
        
    st.divider()
    st.header("🎯 自訂監控加入")
    stock_list = [f"{code} {name}" for code, name in all_stocks.items()]
    selected_tw = st.selectbox("🔍 搜尋台股代碼", options=["請點此搜尋..."] + stock_list, index=0)
    if st.button("➕ 加入台股"):
        if selected_tw != "請點此搜尋...":
            code = selected_tw.split(" ")[0]
            name = " ".join(selected_tw.split(" ")[1:])
            if code not in [s['code'] for s in st.session_state.tw_stocks]:
                st.session_state.tw_stocks.append({"code": code, "name": name, "target_price": 0.0, "alert_triggered": False})
                save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                st.rerun()

    us_code = st.text_input("🇺🇸 輸入美股代碼 (如 NVDA)").strip().upper()
    if st.button("➕ 加入美股"):
        if us_code and us_code not in [s['code'] for s in st.session_state.us_stocks]:
            st.session_state.us_stocks.append({"code": us_code, "name": us_code, "target_price": 0.0, "alert_triggered": False})
            save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
            st.rerun()
            
    if st.button("🗑️ 徹底清空所有資料"):
        st.session_state.tw_stocks = []; st.session_state.us_stocks = []; st.session_state.logs = []
        save_watchlist([], [])
        st.rerun()

if getattr(st.session_state, 'ai_report', None) == "loading":
    st.subheader("🤖 AI 正在深度運算跨國 TOP 5 精選清單...")
    with st.spinner('掃描全球資金動向...'):
        st.session_state.ai_report = get_advanced_ai_report()
    st.rerun()
elif getattr(st.session_state, 'ai_report', None):
    report_data = st.session_state.ai_report
    with st.container(border=True):
        st.subheader("🤖 AI 跨海精選清單")
        if "error" in report_data: st.error(report_data["error"])
        else:
            tabs = st.tabs(list(report_data.keys()))
            for i, (category, stocks) in enumerate(report_data.items()):
                with tabs[i]:
                    for stock in stocks:
                        display_title = f"🎯 {stock.get('name', '')}({stock.get('code', '')}) | 參考價：{stock.get('price', '--')} | {stock.get('strategy', '')}"
                        with st.expander(display_title):
                            st.write(f"**詳細分析**：\n{stock.get('reason', '')}")
                            if 'code' in stock and st.button(f"➕ 帶入價格並監控", key=f"add_{category}_{stock['code']}"):
                                target_list = st.session_state.us_stocks if "美股" in category else st.session_state.tw_stocks
                                if stock['code'] not in [s['code'] for s in target_list]:
                                    t_price = extract_price(stock.get('price', '0'))
                                    target_list.append({"code": stock['code'], "name": stock.get('name', stock['code']), "target_price": t_price, "alert_triggered": False})
                                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                                    st.rerun()

tab_tw, tab_us, tab_core = st.tabs(["🇹🇼 台股極速當沖", "🇺🇸 美股波段戰情", "🐢 10年期核心長線"])

# ====================
# 戰區 1：台股極速當沖
# ====================
with tab_tw:
    if not st.session_state.tw_stocks: st.info("請加入台股。")
    for idx, stock in enumerate(st.session_state.tw_stocks):
        code, name = stock['code'], stock['name']
        t_price = stock.get('target_price', 0.0)
        
        df_daily, ma20_15k, suffix = get_historical_features(code, is_us=False)
        df_1m = get_realtime_tick(code, suffix)
        
        if not df_1m.empty and ma20_15k is not None and not df_daily.empty:
            curr_p = df_1m['Close'].iloc[-1]
            prev_p = df_daily['Close'].iloc[-2] if len(df_daily) > 1 else curr_p
            vwap = ( (df_1m['High'] + df_1m['Low'] + df_1m['Close'])/3 * df_1m['Volume'] ).sum() / (df_1m['Volume'].sum() + 0.001)
            
            is_alert = False
            if t_price > 0:
                if curr_p >= t_price:
                    is_alert = True
                    if not stock.get('alert_triggered', False):
                        msg = f"🚨 【台股到價通知】\n{name}({code}) 已達目標價！\n現價：{curr_p}\n警示價：{t_price}"
                        send_telegram_alert(msg)
                        st.session_state.tw_stocks[idx]['alert_triggered'] = True
                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                elif curr_p < t_price * 0.99: 
                    st.session_state.tw_stocks[idx]['alert_triggered'] = False
                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

            with st.container(border=True):
                # 📌 標題區與「單獨移除按鈕」
                c_title, c_del = st.columns([5, 1])
                with c_title: st.markdown(f"#### {name}({code})")
                with c_del:
                    if st.button("❌ 移除", key=f"del_tw_{code}"):
                        st.session_state.tw_stocks.pop(idx)
                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                        st.rerun()

                if is_alert:
                    st.error(f"🚨 **到價警示！** {name} 已碰觸或越過目標價 {t_price}")
                
                # 📌 設定價格區與「手動一鍵算價」
                c_inp, c_ai = st.columns([2, 1])
                with c_inp:
                    new_t_price = st.number_input(f"目標警示價", value=float(t_price), step=0.5, key=f"inp_{code}")
                    if new_t_price != t_price:
                        st.session_state.tw_stocks[idx]['target_price'] = new_t_price
                        st.session_state.tw_stocks[idx]['alert_triggered'] = False
                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                        st.rerun()
                with c_ai:
                    if API_KEY and st.button("🤖 AI 算價", key=f"ai_p_{code}"):
                        with st.spinner("算價中..."):
                            try:
                                res = ai_model.generate_content(f"台股 {name} 現價 {curr_p}，請給一個當沖停利目標價，只回傳數字。").text
                                p_match = extract_price(res)
                                if p_match > 0:
                                    st.session_state.tw_stocks[idx]['target_price'] = p_match
                                    st.session_state.tw_stocks[idx]['alert_triggered'] = False
                                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                                    st.rerun()
                            except: st.error("API繁忙")

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
        df_daily, _, _ = get_historical_features(code, is_us=True)
        
        if not df_daily.empty:
            curr_p = df_daily['Close'].iloc[-1]
            prev_p = df_daily['Close'].iloc[-2] if len(df_daily) > 1 else curr_p
            
            is_alert = False
            if t_price > 0:
                if curr_p >= t_price:
                    is_alert = True
                    if not stock.get('alert_triggered', False):
                        msg = f"🦅 【美股到價通知】\n{code} 已達目標價！\n現價：${curr_p}\n警示價：${t_price}"
                        send_telegram_alert(msg)
                        st.session_state.us_stocks[idx]['alert_triggered'] = True
                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                elif curr_p < t_price * 0.99:
                    st.session_state.us_stocks[idx]['alert_triggered'] = False
                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)

            with st.container(border=True):
                # 📌 標題與刪除按鈕
                c_title, c_del = st.columns([5, 1])
                with c_title: st.markdown(f"#### 🦅 {code} (美股)")
                with c_del:
                    if st.button("❌ 移除", key=f"del_us_{code}"):
                        st.session_state.us_stocks.pop(idx)
                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                        st.rerun()

                if is_alert:
                    st.error(f"🚨 **到價警示！** {code} 已碰觸或越過目標價 ${t_price}")
                
                # 📌 設定價格區與「手動一鍵算價」
                c_inp, c_ai = st.columns([2, 1])
                with c_inp:
                    new_t_price = st.number_input(f"目標警示價", value=float(t_price), step=1.0, key=f"inp_us_{code}")
                    if new_t_price != t_price:
                        st.session_state.us_stocks[idx]['target_price'] = new_t_price
                        st.session_state.us_stocks[idx]['alert_triggered'] = False
                        save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                        st.rerun()
                with c_ai:
                    if API_KEY and st.button("🤖 AI 算價", key=f"ai_p_us_{code}"):
                        with st.spinner("算價中..."):
                            try:
                                res = ai_model.generate_content(f"美股 {code} 現價 {curr_p}，請給一個波段停利目標價，只回傳數字。").text
                                p_match = extract_price(res)
                                if p_match > 0:
                                    st.session_state.us_stocks[idx]['target_price'] = p_match
                                    st.session_state.us_stocks[idx]['alert_triggered'] = False
                                    save_watchlist(st.session_state.tw_stocks, st.session_state.us_stocks)
                                    st.rerun()
                            except: st.error("API繁忙")

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

# 引擎循環控制 (只有網頁開著的時候才會執行倒數與重整)
if auto_refresh:
    time.sleep(3) 
    st.rerun()
