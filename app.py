@st.cache_data(ttl=86400, show_spinner=False)  # 🚀 修復 1：隱藏右上角的 Running 擾人提示
def get_correlated_stocks(code, name, is_us=False):
    if not API_KEY: return []
    market = "美股" if is_us else "台股"
    try:
        prompt = f"針對 {market} {name}({code})，找出 3 檔同產業高連動股票。第一檔須為絕對龍頭。請絕對只回傳代碼，不要任何中文或說明文字。"
        
        # 🚀 修復 2：加上 request_options={"timeout": 3.0} 強制 3 秒逾時，抓不到就果斷放棄，絕不卡死主畫面！
        res = ai_model.generate_content(
            prompt, 
            generation_config=genai.types.GenerationConfig(temperature=0.0),
            request_options={"timeout": 3.0}
        ).text
        
        if is_us: codes = re.findall(r'[A-Z]+', res.upper())
        else: codes = re.findall(r'\d{4,}', res)
        seen = set(); uniq = []
        for c in codes:
            if c not in seen and c != code:
                seen.add(c); uniq.append(c)
        return uniq[:3]
    except: 
        # 只要發生超時或錯誤，直接安靜地回傳空名單，保證系統流暢
        return []
