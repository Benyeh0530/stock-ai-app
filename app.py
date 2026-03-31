def send_order(action, ticker, price, qty):
    clean_ticker = str(ticker).split(' ')[0].replace(".TW", "").replace(".TWO", "")
    payload = {
        "secret": WEBHOOK_SECRET,
        "ticker": clean_ticker,
        "action": action,
        "price": price,
        "qty": qty
    }
    
    # 🔥 破解 ngrok 攔截的關鍵：加入專屬 Header
    headers = {
        "ngrok-skip-browser-warning": "true",
        "Content-Type": "application/json"
    }
    
    try:
        # 將 headers 參數加入 requests.post 中
        response = requests.post(LOCAL_AGENT_WEBHOOK, json=payload, headers=headers, timeout=5)
        
        if response.status_code == 200:
            msg = f"✅ [指令已送出] {action.upper()} {clean_ticker} | 價格: {price} | 數量: {qty}"
            st.success(msg)
            send_telegram_msg(msg)
        else:
            # 如果失敗，印出 ngrok 或 Flask 回傳的真實錯誤內容
            st.error(f"❌ 本機 Agent 回應異常 (Code: {response.status_code})\n詳細內容: {response.text}")
            
    except Exception as e:
        st.error(f"❌ 無法連線至本機 Agent。請確認 ngrok 網址正確且 Windows 程式已啟動。\n錯誤訊息: {e}")
