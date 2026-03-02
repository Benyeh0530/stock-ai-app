import streamlit as st
import pandas as pd
import google.generativeai as genai
import datetime
import requests
import urllib3
import pytz
import json
import re

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

            df_15m = df_1m_all['Close'].resample('15min').last().dropna()
            ma20_15k = df_15m.tail(20).mean() if len(df_15m) >= 20 else df_15m.mean()

            last_day = df_1m_all.index[-1].date()
            df_1m_today = df_1m_all[df_1m_all.index.date == last_day]

            url_1d = f"https://query2.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range=3mo"
            res_1d = requests.get(url_1d, headers=headers, timeout=5)
            data_1d = res_1d.json()
            
            df_daily = pd.DataFrame()
            if data_1d.get('chart', {}).get('result'):
                result_1d = data_1d['chart']['result'][0]
                if 'timestamp' in result_1d:
                    quote_1d = result_1d['indicators']['quote'][0]
                    df_daily = pd.DataFrame({
                        'Open': quote_1d['open'],
                        'High': quote_1d['high'],
                        'Low': quote_1d['low'],
                        'Close': quote_1d['close'],
                        'Volume': quote_1d['volume']
                    }).dropna()

            return df_1m_today, df_daily, ma20_15k

        except Exception as e:
            continue
    return None, None, None

def get_advanced_ai_report():
    if not API_KEY: return {"error": "⚠️ 請先設定 API Key"}
    tw_tz = pytz.timezone('Asia/Taipei')
    now = datetime.datetime.now(tw_tz)
    is_after_1230 = now.time() >= datetime.time(12, 30)
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # 🚀 提示詞終極進化：新增資金熱點產業分析
    prompt = f"""
    現在是台灣時間 {time_str}。你是頂尖台股操盤手。
    請給出你認為勝率最高的「絕對 TOP 5」精選名單。請嚴格依照以下 JSON 格式回傳，不可有其他多餘文字。
    
    【絕對限制條件】：
    1. 所有推薦股票目前股價必須在 150 元（含）以下！
    2. 每一個類別，必須精準提供剛好 5 檔股票！
    3. 必須在 "strategy" 欄位填寫簡短的判斷基準。特別是在「資金熱點TOP5」，請在 strategy 填寫「具體的熱門產業名稱 (如: 散熱模組、重電族群、CPO等)」。

    JSON 格式如下：
    {{
      "資金熱點TOP5": [ 5筆資料 ],
      "當沖作多": [ 5筆資料 ],
      "當沖作空": [ 5筆資料 ],
      "波段操作": [ 5筆資料 ],
      "隔日沖": [ 5筆資料 ]
    }}
    
    (物件格式：{{"code": "代碼", "name": "名稱", "price": "建議價位", "strategy": "判斷基準或所屬熱門產業", "reason": "詳細理由分析(若是資金熱點，請說明資金流入該產業的原因與個股優勢)"}})
    """
    if not is_after_1230:
        prompt += "\n注意：目前時間未達 12:30，請將「隔日沖」的值設為空陣列 []。"

    try:
        generation_config = genai.types.GenerationConfig(temperature=0.0)
        response = ai_model.generate_content(prompt, generation_config=generation_config).text
        match = re.search(r'\{.*\}', response, re.DOTALL)
        json_str = match.group(0) if match else response
        return json.loads(json_str)
    except Exception as e: 
        return {"error": f"AI 產出格式錯誤，請重新產生。錯誤碼: {e}"}

# --- 3. 網頁介面 ---
st.title("⚡ AI 智能監控戰情室")

if 'stocks' not in st.session_state: st.session_state.stocks = []
if 'logs' not in st.session_state: st.session_state.logs = []

all_stocks = get_full_stock_db()

with st.sidebar:
    st.header("🤖 AI 獨家選股報告")
    if st.button("🚀 立即生成全盤選股報告", use_container_width=True, type="primary"):
        st.session_state.ai_report = "loading"
        st.rerun()
        
    st.divider()
    
    st.header("🎯 自訂監控選單")
    stock_list = [f"{code} {name}" for code, name in all_stocks.items()]
    selected_stock = st.selectbox("🔍 支援代碼或中文字搜尋", options=["請點此搜尋..."] + stock_list, index=0)
    
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

if getattr(st.session_state, 'ai_report', None) == "loading":
    st.subheader("🤖 AI 正在深度運算 TOP 5 精選清單 (約需 10~20 秒)...")
    with st.spinner('掃描近期熱門產業與資金動向，篩選最優質個股...'):
        st.session_state.ai_report = get_advanced_ai_report()
    st.rerun()
elif getattr(st.session_state, 'ai_report', None):
    report_data = st.session_state.ai_report
    
    with st.container(border=True):
        st.subheader("🤖 AI 精選清單 (點擊看詳細分析)")
        if "error" in report_data:
            st.error(report_data["error"])
        else:
            tabs = st.tabs(list(report_data.keys()))
            for i, (category, stocks) in enumerate(report_data.items()):
                with tabs[i]:
                    if not stocks: 
                        st.info("時間未達或目前無符合條件的標的。")
                    else:
                        for stock in stocks:
                            display_title = f"🎯 {stock.get('name', '')}({stock.get('code', '')}) | 參考價：{stock.get('price', '--')} | {stock.get('strategy', '綜合評估')}"
                            
                            with st.expander(display_title):
                                st.write(f"**詳細分析**：\n{stock.get('reason', '無詳細說明')}")
                                if 'code' in stock and st.button(f"➕ 加入 {stock.get('name', '該檔')} 到下方看板", key=f"add_ai_{category}_{stock['code']}"):
                                    if stock['code'] not in [s['code'] for s in st.session_state.stocks]:
                                        st.session_state.stocks.append({"code": stock['code'], "name": stock.get('name', '')})
                                        st.rerun()
        st.divider()
        if st.button("✖️ 關閉報告"):
            st.session_state.ai_report = None
            st.rerun()

st.divider()

t_col1, t_col2 = st.columns([1, 1])
with t_col1:
    if st.button("🔄 手動刷新即時股價"):
        st.cache_data.clear()
        st.rerun()
with t_col2:
    tw_tz = pytz.timezone('Asia/Taipei')
    st.write(f"⏱️ 股價更新時間: {datetime.datetime.now(tw_tz).strftime('%H:%M:%S')}")

st.subheader("📺 即時戰情看板")
if not st.session_state.stocks:
    st.info("請於左側選單搜尋並加入您想監控的標的。")
else:
    for stock in st.session_state.stocks:
        code = stock['code']
        name = stock['name']
        
        df_1m, df_daily, ma20_15k = get_stock_data(code)
        
        if df_1m is not None and not df_1m.empty and ma20_15k is not None and not df_daily.empty:
            curr_p = df_1m['Close'].iloc[-1]
            prev_p = df_daily['Close'].iloc[-2] if len(df_daily) > 1 else curr_p
            high_p = df_1m['High'].max()
            low_p = df_1m['Low'].min()
            
            strategies = []
            if len(df_daily) >= 20:
                c_today = curr_p
                o_today = df_daily['Open'].iloc[-1]
                h_today = df_daily['High'].iloc[-1]
                l_today = df_daily['Low'].iloc[-1]
                v_today = df_daily['Volume'].iloc[-1]
                
                c_yest = df_daily['Close'].iloc[-2]
                o_yest = df_daily['Open'].iloc[-2]
                h_yest = df_daily['High'].iloc[-2]
                
                c_prev = df_daily['Close'].iloc[-3]
                o_prev = df_daily['Open'].iloc[-3]

                ma5 = df_daily['Close'].tail(5).mean()
                ma10 = df_daily['Close'].tail(10).mean()
                ma20 = df_daily['Close'].tail(20).mean()
                v_ma5 = df_daily['Volume'].tail(5).mean()

                if c_today > ma5 > ma10 > ma20: strategies.append("🌈 多頭排列")
                if v_today > v_ma5 * 2 and c_today > o_today: strategies.append("🔥 量價齊揚")
                if (c_today > o_today) and (c_yest > o_yest) and (c_prev > o_prev) and (c_today > c_yest > c_prev): strategies.append("📈 紅三兵")
                
                body = abs(c_today - o_today)
                lower_shadow = min(c_today, o_today) - l_today
                if lower_shadow > body * 2 and body > 0: strategies.append("🔨 探底神針")
                if o_today > h_yest: strategies.append("🚀 強勢跳空")

            vol_5m = df_1m['Volume'].resample('5min').sum().dropna()
            vol_15m = df_1m['Volume'].resample('15min').sum().dropna()
            
            if len(vol_5m) > 0:
                avg_5m = vol_5m.mean()
                for ts, vol in vol_5m.items():
                    if vol > avg_5m * 2.5 and vol > 100:
                        time_str = ts.strftime("%H:%M")
                        msg = f"[{time_str}] ⚡ {name}({code}) | 5分K爆量: {int(vol)}張"
                        if msg not in [l['msg'] for l in st.session_state.logs]: st.session_state.logs.append({"time": time_str, "msg": msg})

            if len(vol_15m) > 0:
                avg_15m = vol_15m.mean()
                for ts, vol in vol_15m.items():
                    if vol > avg_15m * 2.5 and vol > 200:
                        time_str = ts.strftime("%H:%M")
                        msg = f"[{time_str}] 🔥 {name}({code}) | 15分K爆量: {int(vol)}張"
                        if msg not in [l['msg'] for l in st.session_state.logs]: st.session_state.logs.append({"time": time_str, "msg": msg})
            
            vwap = ( (df_1m['High'] + df_1m['Low'] + df_1m['Close'])/3 * df_1m['Volume'] ).sum() / df_1m['Volume'].sum()
            
            with st.container(border=True):
                strat_tags = " | ".join(strategies) if strategies else "觀察中"
                st.markdown(f"#### {name}({code}) ✨ 觸發型態: **{strat_tags}**")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("現價", f"{curr_p:.2f}", f"{curr_p - prev_p:.2f}")
                c2.metric("當日均價線", f"{vwap:.2f}")
                c3.metric("15K 20MA", f"{ma20_15k:.2f}")
                
                with st.expander("🔍 深度策略分析", expanded=False):
                    d_col = "red" if curr_p > vwap else "green"
                    st.markdown(f"⚡ **當沖建議**: :{d_col}[{'多方強勢' if curr_p > vwap else '空方強勢'}] | 參考點位: {vwap:.2f}")
                    
                    ma5_daily = df_daily['Close'].tail(5).mean() if len(df_daily) >= 5 else curr_p
                    ma10_daily = df_daily['Close'].tail(10).mean() if len(df_daily) >= 10 else curr_p
                    st.markdown(f"🌊 **波段技術支撐**: 5日線 ({ma5_daily:.2f}) / 10日線 ({ma10_daily:.2f})")

                    pos = (curr_p - low_p) / (high_p - low_p + 0.001)
                    n_msg = "📈 尾盤鎖碼" if pos > 0.85 else "📉 尾盤殺低" if pos < 0.15 else "⏳ 區間震盪"
                    st.markdown(f"🌙 **隔日沖判定**: {n_msg} ({pos*100:.1f}%)")
                    
                    st.divider()
                    
                    if st.button(f"🤖 呼叫 AI 分析籌碼與波段進場價", key=f"ai_wave_{code}", use_container_width=True):
                        with st.spinner(f'正在為您深度分析 {name} 的籌碼動態與合理波段...'):
                            prompt = f"我是台股操盤手。請針對 {name}({code})，目前即時股價為 {curr_p:.2f}。請幫我分析近期『三大法人（外資/投信/自營商）可能的買賣超動態與籌碼集中度』，並綜合產業題材，給我一個『建議的波段進場價位區間』。字數請控制在100字以內，精準扼要。"
                            try:
                                analysis = ai_model.generate_content(prompt).text
                                st.success(analysis)
                            except Exception as e:
                                st.error("AI 伺服器稍微壅塞，請稍後再試。")
        else:
            st.warning(f"⚠️ {code} 數據獲取受限，請稍候刷新。")

st.divider()
st.subheader("🔔 帶量異常歷史紀錄 (5K / 15K)")
if st.session_state.logs:
    sorted_logs = sorted(st.session_state.logs, key=lambda x: x['time'], reverse=True)
    log_text = "\n\n".join([l['msg'] for l in sorted_logs])
    st.text_area("今日爆量軌跡", value=log_text, height=200)
else:
    st.info("目前無異常爆量訊號。系統持續監控中...")
