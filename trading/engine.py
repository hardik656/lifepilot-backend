# =========================================================
# 🧠 Trading Engine Module
# =========================================================

import os, time, warnings, json, joblib, csv, logging
from datetime import datetime
from collections import Counter
import numpy as np
import pandas as pd
import yfinance as yf
import lightgbm as lgb
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, TakeProfitRequest, StopLossRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
warnings.filterwarnings("ignore")
np.random.seed(42)

# =========================================================
# 🛡️ CONFIGURATION
# =========================================================
ALPACA_KEY = "PKXV7Q55RDCNWF3KMBFSSQKL4M"
ALPACA_SECRET = "GeVWw8J96PZ1M5Q4WksHy2fFQW8KrNCacHCoCurUm7Dy"

TICKERS = [
    "TSM", "SONY", "HMC", "TM", "BABA", "JD", "BIDU", "PDD", "INFY", "WIT", "HDB", "IBN",
    "ASML", "SAP", "NVO", "SNY", "AZN", "RHHBY", "HSBC", "SHEL", "BP", "MBGYY", 
    "RY", "TD", "SHOP", "MELI", "PBR", "VALE",
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "JPM", "GS", "LLY", "UNH",
    "SPY", "QQQ", "EEM", "VGK", "EWJ", "INDA", "GLD", "SLV", "USO",
    "BTC-USD", "ETH-USD", "SOL-USD"
]

SECTOR_MAP = {
    "TSM":"TECH", "SONY":"TECH", "HMC":"AUTO", "TM":"AUTO", 
    "BABA":"CHN_TECH", "JD":"CHN_TECH", "BIDU":"CHN_TECH", "PDD":"CHN_TECH",
    "INFY":"IND_TECH", "WIT":"IND_TECH", "HDB":"FIN", "IBN":"FIN",
    "ASML":"TECH", "SAP":"TECH", "NVO":"HEALTH", "SNY":"HEALTH", "AZN":"HEALTH", "RHHBY":"HEALTH",
    "HSBC":"FIN", "SHEL":"ENERGY", "BP":"ENERGY", "MBGYY":"AUTO",
    "RY":"FIN", "TD":"FIN", "SHOP":"TECH", "MELI":"TECH", "PBR":"ENERGY", "VALE":"MINING",
    "NVDA":"TECH", "AAPL":"TECH", "MSFT":"TECH", "GOOGL":"TECH", "AMZN":"TECH", "TSLA":"AUTO",
    "JPM":"FIN", "GS":"FIN", "LLY":"HEALTH", "UNH":"HEALTH",
    "SPY":"INDEX", "QQQ":"INDEX", "EEM":"GLOBAL_EM", "VGK":"EURO_INDEX", "EWJ":"JAPAN_INDEX", 
    "INDA":"INDIA_INDEX", "GLD":"COMMODITY", "SLV":"COMMODITY", "USO":"COMMODITY",
    "BTC-USD":"CRYPTO", "ETH-USD":"CRYPTO", "SOL-USD":"CRYPTO"
}

LONG_ENTRY_TH = 0.06 
RISK_PER_TRADE = 0.01
MAX_PER_SECTOR = 2 
MAX_SECTOR_EXPOSURE = 0.25 # 📊 Portfolio Limit: 25% per sector

alpaca = TradingClient(ALPACA_KEY.strip(), ALPACA_SECRET.strip(), paper=True)

# =========================================================
# 📉 NEW: 10-LINE REGIME FILTER
# =========================================================
def get_market_regime(df):
    """Returns True if Market is Bullish (Price > 200 SMA)"""
    if len(df) < 200: return True
    sma_200 = df['Close'].rolling(window=200).mean().iloc[-1]
    current_price = df['Close'].iloc[-1]
    return current_price > sma_200

# =========================================================
# 📊 FEATURE ENGINEERING & UTILS
# =========================================================
def translate_symbol(s): return s.replace("-USD", "/USD") if "-USD" in s else s

def generate_features(df):
    if len(df) < 200: return np.zeros((1, 14))
    c, v, h, l = df['Close'], df['Volume'], df['High'], df['Low']
    ret = c.pct_change()
    mom_3h = (c.iloc[-1] / (c.iloc[-4] + 1e-6)) - 1
    delta = c.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    current_rsi = (100 - (100 / (1 + rs))).iloc[-1] / 100.0
    tp = (h + l + c) / 3
    vwap = (tp * v).rolling(window=24).sum() / (v.rolling(window=24).sum() + 1e-9)
    vwap_dist = (c.iloc[-1] / vwap.iloc[-1]) - 1
    tr = np.maximum(h-l, np.maximum(np.abs(h-c.shift()), np.abs(l-c.shift())))
    atr = tr.rolling(14).mean().iloc[-1]
    vol_spike = v.iloc[-1] / (v.rolling(50).mean().iloc[-1] + 1e-9)
    f = [
        mom_3h, current_rsi, vwap_dist, ret.tail(20).mean(),
        ret.tail(20).std(), c.iloc[-1]/c.rolling(50).mean().iloc[-1]-1,
        (c.iloc[-1]-c.rolling(20).max().iloc[-1])/(c.iloc[-1]+1e-9), vol_spike,
        float(atr)/(c.iloc[-1]+1e-9), 1 if (ret.tail(20).std()) < 0.035 else -3,
        ret.tail(30).skew(), (c.iloc[-1]-c.rolling(50).min().iloc[-1])/(c.rolling(50).max().iloc[-1]-c.rolling(50).min().iloc[-1]+1e-9),
        ret.tail(10).mean(), ret.tail(5).std()
    ]
    return np.array([np.nan_to_num(x) for x in f]).reshape(1, -1)

# =========================================================
# 🧠 STATE MANAGEMENT
# =========================================================
class State:
    def __init__(self):
        self.models, self.scalers, self.last_retrain = {}, {}, 0
        os.makedirs("vault", exist_ok=True)
        self.load_vault()
    def save_vault(self):
        joblib.dump(self.models, "vault/models.pkl")
        joblib.dump(self.scalers, "vault/scalers.pkl")
        json.dump({"last": self.last_retrain}, open("vault/meta.json","w"))
    def load_vault(self):
        if os.path.exists("vault/models.pkl"): 
            self.models = joblib.load("vault/models.pkl")
            self.scalers = joblib.load("vault/scalers.pkl")
            self.last_retrain = json.load(open("vault/meta.json")).get("last", 0)

state = State()

# =========================================================
# 🧠 VALIDATED RETRAINING
# =========================================================
def retrain_models():
    print(f"🧠 [{datetime.now().strftime('%Y-%m-%d')}] Starting Shadow-Validation Test...")
    data_vault = {}
    sector_performance = {}
    
    try:
        raw_batch = yf.download(TICKERS, period="250d", interval="1h", group_by="ticker", progress=False, timeout=60)
        for s in TICKERS:
            if s in raw_batch and not raw_batch[s].empty:
                df = raw_batch[s].dropna()
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                if len(df) > 200: data_vault[s] = df
    except Exception as e:
        logging.error(f"Batch fail: {e}")

    for s, df in data_vault.items():
        try:
            c = df['Close']
            X, y = [], []
            for i in range(200, len(df)-24, 24):
                feat = generate_features(df.iloc[:i])[0]
                future_ret = (c.iloc[i+24] / c.iloc[i]) - 1 
                X.append(feat); y.append(future_ret)
            
            if len(X) > 60:
                split = int(len(X) * 0.85)
                X_train, X_test = np.array(X)[:split], np.array(X)[split:]
                y_train, y_test = np.array(y)[:split], np.array(y)[split:]
                sc = StandardScaler()
                X_train_s = sc.fit_transform(X_train)
                X_test_s = sc.transform(X_test)
                model = lgb.LGBMRegressor(n_estimators=150, max_depth=5, learning_rate=0.03, num_leaves=31, verbosity=-1)
                model.fit(X_train_s, y_train)
                preds = model.predict(X_test_s)
                mse = mean_squared_error(y_test, preds)
                sec = SECTOR_MAP.get(s, "OTHER")
                if sec not in sector_performance: sector_performance[sec] = []
                sector_performance[sec].append(mse)
                state.models[s], state.scalers[s] = model, sc
        except: continue
            
    print("\n✅ TEST COMPLETE - Confidence Score (Lower is Better):")
    for sec, scores in sector_performance.items():
        avg_mse = sum(scores) / len(scores)
        star_rating = "⭐" * max(1, min(5, int(5 - (avg_mse * 1000))))
        print(f"{sec:<12} | Score: {avg_mse:.6f} | Reliability: {star_rating}")

    state.last_retrain = time.time(); state.save_vault()
    print(f"\n🚀 System Armed with {len(state.models)} Tested Models.")

# =========================================================
# 🔄 LIVE CYCLE
# =========================================================
def main_cycle():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Global Scanning...")
    current_signals = {}
    try:
        acc = alpaca.get_account(); equity = float(acc.equity)
        positions = alpaca.get_all_positions()
        current_pos = {p.symbol for p in positions}
        
        # ⚡ LIGHTWEIGHT PORTFOLIO ALLOCATOR
        sector_values = Counter()
        for p in positions:
            sec = SECTOR_MAP.get(p.symbol.replace("/USD","-USD"), "OTHER")
            sector_values[sec] += float(p.market_value)
            
    except Exception as e: print(f"❌ Account Sync: {e}"); return

    batch_df = yf.download(TICKERS, period="5d", interval="1h", group_by='ticker', progress=False, timeout=60)

    for s in TICKERS:
        try:
            if s in batch_df and not batch_df[s].empty:
                df = batch_df[s].dropna()
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            else: continue
            
            # --- 🛡️ REGIME FILTER & VOLATILITY GUARD ---
            if not get_market_regime(df): continue # Skip if in Bear Regime
            
            h, l, c = df['High'], df['Low'], df['Close']
            tr = np.maximum(h-l, np.maximum(np.abs(h-c.shift()), np.abs(l-c.shift())))
            if tr.iloc[-1] > tr.rolling(20).mean().iloc[-1] * 2.2: continue 

            # --- 📊 ALLOCATOR CHECK ---
            current_sector = SECTOR_MAP.get(s, "OTHER")
            if (sector_values[current_sector] / equity) >= MAX_SECTOR_EXPOSURE: continue

            feat = generate_features(df)
            if s not in state.models: continue
            pred = state.models[s].predict(state.scalers[s].transform(feat))[0]
            current_signals[s] = pred
            
            if abs(pred) >= LONG_ENTRY_TH:
                alp_sym = translate_symbol(s); side = OrderSide.BUY if pred >= 0 else OrderSide.SELL
                if alp_sym in current_pos: continue
                price, atr = float(c.iloc[-1]), float(tr.rolling(14).mean().iloc[-1])
                qty = max(1, int((equity * RISK_PER_TRADE) / (atr * 2.5 + 1e-6)))
                
                sl, tp = round(price - atr*2.5 if side==OrderSide.BUY else price + atr*2.5, 2), round(price + atr*4.5 if side==OrderSide.BUY else price - atr*4.5, 2)
                order = LimitOrderRequest(symbol=alp_sym, qty=qty, side=side, time_in_force=TimeInForce.GTC, order_class=OrderClass.BRACKET, limit_price=round(price,2), take_profit=TakeProfitRequest(limit_price=tp), stop_loss=StopLossRequest(stop_price=sl))
                alpaca.submit_order(order)
                print(f"🚀 EXECUTED {side} {alp_sym} | Sector: {current_sector}")
        except: continue
    print_heatmap(current_signals)

def print_heatmap(signals):
    if not signals: return
    print("\n" + "="*45 + "\n🌡️  GLOBAL MARKET HEATMAP (v7.7.6)\n" + "="*45)
    sector_data = {}
    for sym, sig in signals.items():
        sec = SECTOR_MAP.get(sym, "OTHER")
        if sec not in sector_data: sector_data[sec] = []
        sector_data[sec].append(sig)
    for sec, sigs in sorted(sector_data.items()):
        avg_sig = sum(sigs) / len(sigs)
        bar = ("🟩" if avg_sig > 0 else "🟥") * int(abs(avg_sig) * 200)
        print(f"{sec:<12} | {avg_sig:>8.5f} | {bar if bar else '⬜'}")
    print("="*45 + "\n")
