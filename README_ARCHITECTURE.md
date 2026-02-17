# LifePilot Backend - 2-Service Architecture

## 📁 File Structure

```
lifepilot-backend/
├── main.py                 # HTTP API Service (Clean)
├── worker.py               # Trading Worker Service
├── trading/
│   ├── __init__.py         # Module exports
│   └── engine.py          # All trading logic
├── automation/
│   └── cancel_bot.py       # Cancellation automation
├── database.py             # Database setup
├── models.py               # SQLAlchemy models
└── requirements.txt         # Dependencies
```

## 🚀 Service 1: FastAPI Web Service

**File:** `main.py`
- HTTP-only API service
- All routes preserved unchanged
- Database operations intact
- No trading logic
- No background scheduler

**Start Command:**
```bash
uvicorn main:app --host 0.0.0.0 --port 10000
```

## 🤖 Service 2: Trading Worker

**File:** `worker.py`
- Independent trading bot
- Hourly market scanning
- Weekly model retraining
- No HTTP routes
- Safe error handling

**Start Command:**
```bash
python worker.py
```

## 🧠 Trading Engine Module

**Files:** `trading/engine.py`, `trading/__init__.py`
- Clean separation of trading logic
- All ML models and algorithms
- State management
- Feature engineering

## ✅ Architecture Benefits

### **Independence**
- API service runs without trading bot
- Trading worker runs without API
- No blocking loops in web service
- Worker failures don't crash API

### **Scalability**
- Deploy multiple worker instances
- API service can scale horizontally
- Trading logic isolated and reusable

### **Maintainability**
- Clear separation of concerns
- Trading logic in dedicated module
- Easy to test individual components

### **Safety**
- Worker wrapped in try/catch
- API continues if worker fails
- No shared state conflicts

## 🔄 Data Flow

```
Frontend → FastAPI API → Database
Worker → Alpaca API → Trading
Worker → yfinance → Market Data
```

## 🚀 Render Deployment

### Web Service
- **Type:** Web Service
- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port 10000`
- **Port:** 10000

### Background Worker
- **Type:** Background Worker
- **Start Command:** `python worker.py`
- **No port needed**

## ✅ Validation Checklist

- [x] API routes unchanged
- [x] Database schema preserved
- [x] Trading logic moved to worker
- [x] No function renaming
- [x] No feature removal
- [x] Independent services
- [x] Safe error handling
- [x] Clean module structure

## 🎯 Result

**Production-ready 2-service architecture:**
- FastAPI serves HTTP requests
- Trading worker handles market operations
- Clean separation of concerns
- Zero logic changes
- Full error resilience
