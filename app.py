# [地端 local_agent.py 關鍵片段 - 監控引擎]
class AlertManager:
    def __init__(self):
        self.settings = {} # 存放雲端傳來的監控閾值
        self.first_k = {}  # 存放每日第一根 K 棒數據
        self.ma_data = {}  # 存放 5K 均線計算用的歷史價格

    def update_settings(self, stock_id, config):
        self.settings[stock_id] = config

    def check_alerts(self, stock_id, current_price, current_volume):
        config = self.settings.get(stock_id, {})
        alerts = []
        
        # 1. 自訂價格監控
        if config.get('target_price') and current_price >= config['target_price']:
            alerts.append(f"🚩 自訂價格觸達: {current_price}")

        # 2. 5K 20MA 監控 (需結合地端快取的 MA 數值)
        ma_20 = config.get('ma20_val')
        if ma_20 and current_price >= ma_20:
            alerts.append(f"📈 觸發 5K 20MA 支撐/壓力: {current_price}")

        # 3. 每日第一根 K 棒監控
        first_k = self.first_k.get(stock_id)
        if first_k:
            if current_price >= first_k['high']: alerts.append("🔥 突破第一根K高點")
            if current_price <= first_k['low']: alerts.append("❄️ 跌破第一根K低點")

        # 4. CDP 點位監控 (NH, NL 等)
        cdp = config.get('cdp_data')
        if cdp:
            if current_price >= cdp['AH']: alerts.append("⚡ 挑戰 CDP 追買價(AH)")
            if current_price <= cdp['AL']: alerts.append("📉 觸及 CDP 追賣價(AL)")

        return alerts

# ⚠️ 注意：這份邏輯會嵌入在您的 SKQuoteLib 事件中，當價格跳動時自動觸發 Telegram 告警
