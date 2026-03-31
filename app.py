import os
import time
import threading
import queue
import pythoncom
import comtypes.client
from flask import Flask, request, jsonify
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. 核心設定 (請填寫)
# ==========================================
ID = "您的身分證大寫"
PWD = "您的密碼"
WEBHOOK_SECRET = "MySOC_Secret_Key_2026"
TG_BOT_TOKEN = "您的_Telegram_Bot_Token"
TG_CHAT_ID = "您的_Chat_ID"

GLOBAL_KLINE_DATA = {}
api_ready = False
ts_account = ""
command_queue = queue.Queue()

# ==========================================
# 2. 警報與運算引擎 (AlertManager)
# ==========================================
def send_tg_alert(message):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": message}
    try: requests.post(url, json=payload, timeout=3)
    except: pass

class AlertManager:
    def __init__(self):
        self.settings = {}
        self.first_k = {}
        self.triggered_alerts = set() # 防止重複狂叫

    def update_settings(self, stock_id, config):
        self.settings[stock_id] = config
        print(f"⚙️ [{stock_id}] 監控設定已更新: {config}")

    def check_alerts(self, stock_id, current_price, date_str):
        if stock_id not in self.settings: return
        config = self.settings[stock_id]
        alerts = []
        
        # 建立一個唯一的觸發 ID，防止同一秒鐘一直發送
        def add_alert(msg_id, msg_text):
            trigger_key = f"{stock_id}_{msg_id}_{current_price}"
            if trigger_key not in self.triggered_alerts:
                alerts.append(msg_text)
                self.triggered_alerts.add(trigger_key)

        # 1. 自訂價格
        target_p = config.get('target_price', 0.0)
        if target_p > 0 and current_price >= target_p:
            add_alert("custom_p", f"🚩 [{stock_id}] 觸達自訂監控價: {current_price}")

        # (進階的 CDP 與 5K 均線需累積足夠的 K 線資料才能精確計算，此處先建立觸發框架)
        # 3. 第一根 K 棒高低
        if config.get('use_1k') and stock_id in self.first_k:
            fk = self.first_k[stock_id]
            if current_price >= fk['high']: add_alert("1k_high", f"🔥 [{stock_id}] 突破開盤第一根K高點 ({fk['high']})")
            if current_price <= fk['low']: add_alert("1k_low", f"❄️ [{stock_id}] 跌破開盤第一根K低點 ({fk['low']})")

        for msg in alerts:
            print(f"🔔 觸發警報: {msg}")
            send_tg_alert(msg)

alert_engine = AlertManager()

# ==========================================
# 3. Flask API 伺服器
# ==========================================
app = Flask(__name__)

@app.route('/api/kline/<stock_id>', methods=['GET'])
def get_kline(stock_id):
    return jsonify({"stock_id": stock_id, "data": GLOBAL_KLINE_DATA.get(stock_id, [])})

@app.route('/api/subscribe', methods=['POST'])
def subscribe_kline():
    data = request.json
    if data.get("secret") != WEBHOOK_SECRET: return jsonify({"error": "Unauthorized"}), 401
    stock_id = data.get("stock_id")
    if stock_id:
        if stock_id not in GLOBAL_KLINE_DATA: GLOBAL_KLINE_DATA[stock_id] = []
        command_queue.put({"type": "kline", "stock_id": stock_id})
        return jsonify({"status": "Subscribed"})
    return jsonify({"error": "Missing stock_id"}), 400

@app.route('/api/order', methods=['POST'])
def place_order():
    data = request.json
    if data.get("secret") != WEBHOOK_SECRET: return jsonify({"error": "Unauthorized"}), 401
    command_queue.put({"type": "order", "data": data})
    return jsonify({"status": "Order queued"})

@app.route('/api/alert_config', methods=['POST'])
def update_alert():
    data = request.json
    if data.get("secret") != WEBHOOK_SECRET: return jsonify({"error": "Unauthorized"}), 401
    alert_engine.update_settings(data['stock_id'], data['config'])
    return jsonify({"status": "Config updated"})

def run_flask():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    print("🌐 [API Server] 啟動於 Port 5000")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ==========================================
# 4. 群益 API 核心引擎
# ==========================================
def run_capital_engine():
    global api_ready, ts_account
    pythoncom.CoInitialize()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    comtypes.client.GetModule(os.path.join(script_dir, "SKCOM.dll"))
    import comtypes.gen.SKCOMLib as sk

    skC = comtypes.client.CreateObject(sk.SKCenterLib, interface=sk.ISKCenterLib)
    skO = comtypes.client.CreateObject(sk.SKOrderLib, interface=sk.ISKOrderLib)
    skQ = comtypes.client.CreateObject(sk.SKQuoteLib, interface=sk.ISKQuoteLib)

    class OrderEvent:
        def OnAccount(self, bstrLogInID, bstrAccountData):
            global ts_account
            values = bstrAccountData.split(',')
            if len(values) >= 4 and values[0].endswith("TS"):
                ts_account = values[1] + values[3]
                print(f"💳 台股帳號綁定: {ts_account}")
        def OnAsyncOrder(self, nThreadID, nCode, bstrMessage):
            print(f"📜 [委託回報] {bstrMessage}")

    class QuoteEvent:
        def OnConnection(self, nKind, nCode):
            global api_ready
            if nCode == 0: 
                api_ready = True
                print("✅ 報價伺服器連線成功！")
        
        def OnNotifyKLineData(self, bstrStockNo, bstrData):
            data_list = bstrData.split(',')
            if len(data_list) >= 6:
                date_str, open_p, high_p, low_p, close_p, vol = data_list[0], float(data_list[1]), float(data_list[2]), float(data_list[3]), float(data_list[4]), int(data_list[5])
                
                # 儲存第一根 K 棒
                if bstrStockNo not in alert_engine.first_k or len(GLOBAL_KLINE_DATA.get(bstrStockNo, [])) == 0:
                    alert_engine.first_k[bstrStockNo] = {'high': high_p, 'low': low_p}

                if bstrStockNo not in GLOBAL_KLINE_DATA: GLOBAL_KLINE_DATA[bstrStockNo] = []
                GLOBAL_KLINE_DATA[bstrStockNo].append({
                    "Date": date_str, "Open": open_p, "High": high_p, "Low": low_p, "Close": close_p, "Volume": vol
                })
                # 將最新價格送入監控引擎檢查
                alert_engine.check_alerts(bstrStockNo, close_p, date_str)

    OrderEventHandler = comtypes.client.GetEvents(skO, OrderEvent())
    QuoteEventHandler = comtypes.client.GetEvents(skQ, QuoteEvent())

    print("🚀 啟動群益登入程序...")
    skC.SKCenterLib_Login(ID, PWD)
    skO.SKOrderLib_Initialize()
    skO.GetUserAccount()
    skO.ReadCertByID(ID)
    skQ.SKQuoteLib_EnterMonitor()

    while True:
        pythoncom.PumpWaitingMessages()
        while not command_queue.empty():
            cmd = command_queue.get()
            if cmd["type"] == "kline" and api_ready:
                skQ.SKQuoteLib_RequestKLineAM(cmd["stock_id"], 0, 0, 0)
            elif cmd["type"] == "order" and ts_account:
                req = cmd["data"]
                print(f"⚡ [收到下單指令] {req['action']} {req['ticker']} | 價: {req['price']} | 量: {req['qty']}")
                pOrder = sk.STOCKORDER()
                pOrder.bstrFullAccount = ts_account
                pOrder.bstrStockNo = req["ticker"]
                pOrder.sPrime = 0; pOrder.sPeriod = 0; pOrder.sFlag = 0
                pOrder.sBuySell = 0 if req["action"] == 'buy' else 1
                pOrder.nTradeType = 0; pOrder.nSpecialTradeType = 2
                pOrder.bstrPrice = str(req["price"]); pOrder.nQty = int(req["qty"])
                # skO.SendStockOrder(ID, False, pOrder) # 實體驗證安全鎖
        time.sleep(0.05)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_capital_engine()
