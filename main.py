# =========================================================
# 🚀 LifePilot — AI Pilot Engine (Detection + Automation)
# =========================================================
import sys
import os
import pandas as pd
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from automation.cancel_bot import start_cancellation_bot
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, text
from sqlalchemy.orm import sessionmaker, declarative_base
from pydantic import BaseModel
from collections import defaultdict
from datetime import datetime, timezone
import csv
import re

# 🚀 CONSOLIDATE APP DEFINITION
app = FastAPI(title="LifePilot AI 🚀")

# 🚀 ADD THIS TO CONNECT YOUR PHONE
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows your phone to connect from anywhere
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# DATABASE SETUP
# =========================================================
DATABASE_URL = "sqlite:///./lifepilot.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    merchant = Column(String)
    amount = Column(Float)
    currency = Column(String, default="$")
    date = Column(String, default=datetime.now().strftime("%Y-%m-%d"))
    status = Column(String, default="active")  # lifecycle only
    is_invested = Column(Boolean, default=False)
    cancellation_date = Column(String, default=None)

Base.metadata.create_all(bind=engine)

def ensure_is_invested_column():
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(transactions);"))
        columns = [row[1] for row in result]

        if "is_invested" not in columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN is_invested BOOLEAN DEFAULT 0;"))
            print("✅ Added missing is_invested column")

ensure_is_invested_column()

# =========================================================
# DATA MODELS
# =========================================================
class SMSInput(BaseModel):
    text: str

class Brokerage(BaseModel):
    id: str
    name: str
    deep_link: str
    web_url: str
    region: str
    is_active: bool

class CancellationUpdate(BaseModel):
    status: str
    cancellation_date: str | None = None

class CancelRequest(BaseModel):
    merchant: str
    username: str = "user@example.com"
    password: str = "password123"

class InvestmentRequest(BaseModel):
    merchant: str
    monthly_cost: float
    currency: str = "$"

# =========================================================
# ROUTES: DETECTION
# =========================================================

@app.get("/subscriptions")
def detect_subscriptions():
    db = SessionLocal()
    rows = db.query(Transaction).all()
    merchant_invested = set()
    merchant_data = defaultdict(lambda: {"amounts": [], "last_date": "", "currencies": []})
    
    # Calculate total invested amount by currency
    currency_totals = defaultdict(float)

    for row in rows:
        if getattr(row, "is_invested", False):
            currency_key = row.currency

            # Normalize currency to unified buckets
            if currency_key in ["$", "USD"]:
                currency_key = "USD"
            elif currency_key in ["₹", "Rs.", "INR"]:
                currency_key = "INR"
            elif currency_key in ["£", "GBP"]:
                currency_key = "GBP"

            currency_totals[currency_key] += row.amount
            merchant_invested.add(row.merchant)
    
    # ✅ ONLY INCLUDE ACTIVE TRANSACTIONS IN AGGREGATION
    for r in rows:
        if r.status == "active":
            merchant_data[r.merchant]["amounts"].append(r.amount)
            merchant_data[r.merchant]["currencies"].append(r.currency)

            if (
                not merchant_data[r.merchant]["last_date"]
                or r.date > merchant_data[r.merchant]["last_date"]
            ):
                merchant_data[r.merchant]["last_date"] = r.date
    
    result = []
    total_savings_sum = 0
    today = datetime.now()
    
    for merchant, data in merchant_data.items():
        if len(data["amounts"]) >= 1:
            occurrences = len(data["amounts"])
            monthly_cost = data["amounts"][-1]  # Latest transaction amount, not sum

            total_savings_sum += monthly_cost
            last_dt = datetime.strptime(data["last_date"], "%Y-%m-%d")
            days_diff = (today - last_dt).days
            
            most_common_currency = max(
                set(data["currencies"]),
                key=data["currencies"].count
            )
            
            # Normalize currency symbols
            normalized_currency = most_common_currency
            if most_common_currency in ["₹", "Rs."]:
                normalized_currency = "INR"
            elif most_common_currency == "$":
                normalized_currency = "USD"
            
            is_stale = True
            
            merchant_status = "active"
            
            merchant_transactions = db.query(Transaction).filter(
                Transaction.merchant == merchant
            ).all()
            
            statuses = {t.status for t in merchant_transactions}

            if "charge_detected_after_cancel" in statuses:
                merchant_status = "charge_detected_after_cancel"
            elif "cancellation_requested" in statuses:
                merchant_status = "cancellation_requested"
            elif "cancelled" in statuses:
                merchant_status = "cancelled"
            else:
                merchant_status = "active"
            
            duplicate_flag = occurrences > 1
            
            result.append({
                "merchant": merchant,
                "monthly_cost": round(monthly_cost, 2),
                "currency": normalized_currency,
                "occurrences": occurrences,
                "last_seen_days": days_diff,
                "is_stale": is_stale,
                "invested": bool(merchant in merchant_invested),
                "cancellation_status": merchant_status or "active",
                "cancellation_date": next(
                    (t.cancellation_date for t in merchant_transactions if t.cancellation_date),
                    None
                ),
                "duplicate_flag": duplicate_flag,
                "duplicate_count": occurrences
            })

    db.close()
    return {
        "subscriptions": result, 
        "total_savings": round(total_savings_sum, 2), 
        "total_invested": round(sum(currency_totals.values()), 2),
        "currency_totals": {
            "USD": round(currency_totals.get("USD", 0), 2),
            "INR": round(currency_totals.get("INR", 0), 2),
            "GBP": round(currency_totals.get("GBP", 0), 2)
        }
    }

# =========================================================
# ROUTES: AUTOMATION
# =========================================================

@app.post("/cancel-subscription")
def handle_cancel(data: CancelRequest):
    """
    Triggers the Playwright bot to handle 'One-tap cancellation'.
    """
    print(f"🚀 AI Pilot: Received request to cancel {data.merchant}")
    success = start_cancellation_bot(data.merchant, data.username, data.password)
    
    if success:
        return {"status": "success", "message": f"Automation started for {data.merchant}"}
    return {"status": "error", "message": "Bot failed to execute"}

@app.put("/subscriptions/{merchant}/cancellation-status")
def update_cancellation_status(merchant: str, data: CancellationUpdate):
    db = SessionLocal()
    try:
        transactions = db.query(Transaction).filter(
            Transaction.merchant == merchant
        ).all()

        if not transactions:
            return {"status": "error", "message": "Merchant not found"}

        for t in transactions:
            t.status = data.status
            if data.cancellation_date:
                t.cancellation_date = data.cancellation_date

        db.commit()
        return {"status": "success", "merchant": merchant}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        db.close()

# =========================================================
# ROUTES: INVESTMENT TRACKING
# =========================================================

@app.post("/invest/{merchant}")
def handle_investment(data: InvestmentRequest):
    """
    Records when user invests a subscription into Gold Vault.
    Updates subscription status to 'invested' and tracks total investments.
    """
    print(f"🏆 Investment: Received request to invest {data.merchant} for ${data.monthly_cost}")
    
    # Add Invalid Amount Guard
    if data.monthly_cost <= 0:
        return {"status": "error", "message": "Invalid investment amount"}
    
    db = SessionLocal()
    
    # Find all non-invested rows for this merchant
    non_invested_rows = db.query(Transaction).filter(
        Transaction.merchant == data.merchant,
        Transaction.is_invested == False,
        Transaction.status == "active"
    ).all()
    
    print(f"📊 Found {len(non_invested_rows)} non-invested rows for {data.merchant}")
    
    if non_invested_rows:
        # Update ALL non-invested rows to is_invested=True
        for row in non_invested_rows:
            row.is_invested = True
            print(f"📝 Setting is_invested=True on row ID {row.id} (amount: {row.amount})")
        
        db.commit()
        print(f"✅ Updated {len(non_invested_rows)} rows to invested for {data.merchant}")
    elif not db.query(Transaction).filter(
        Transaction.merchant == data.merchant
    ).first():
        # Create ONE new investment record
        print(f"➕ No existing rows found. Creating new investment record for {data.merchant}")
        investment = Transaction(
            merchant=data.merchant,
            amount=data.monthly_cost,
            currency=data.currency,
            date=datetime.now().strftime("%Y-%m-%d"),
            status="active",
            is_invested=True
        )
        db.add(investment)
        db.commit()
        print(f"✅ Created new investment record for {data.merchant}")
    
    # Verify final count
    invested_count = db.query(Transaction).filter(
        Transaction.merchant == data.merchant,
        Transaction.is_invested == True
    ).count()
    print(f"📊 FINAL: {invested_count} invested rows for {data.merchant}")
    
    db.close()
    return {"status": "success", "message": f"Investment recorded for {data.merchant}"}

# =========================================================
# ROUTES: UTILS
# =========================================================

@app.post("/parse-sms")
def parse_sms(data: SMSInput):
    db = SessionLocal()
    lines = data.text.splitlines()
    parsed_transactions = []
    current_date = datetime.now().strftime("%Y-%m-%d")

    for line in lines:
        if not line.strip():
            continue

        # 1️⃣ Currency + Amount Detection
        currency_match = re.search(r"(Rs\.?|₹|\$|£)\s?(\d+(?:\.\d{1,2})?)", line)
        if not currency_match:
            continue

        currency = currency_match.group(1)
        amount = float(currency_match.group(2))

        # Normalize currency
        if currency in ["Rs", "Rs.", "₹"]:
            currency = "INR"
        elif currency == "$":
            currency = "USD"
        elif currency == "£":
            currency = "GBP"

        # 2️⃣ Smart Merchant Extraction
        merchant = None

        # Try common merchant patterns
        patterns = [
            r"(?:at|to|for)\s+([A-Za-z0-9&\s]+)",
            r"VPA\s+([A-Za-z0-9@\.]+)",
            r"from\s+([A-Za-z0-9&\s]+)"
        ]

        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                merchant = match.group(1).strip()
                break

        # Fallback: detect common Indian banks
        if not merchant:
            bank_match = re.search(r"(Kotak|HDFC|ICICI|SBI|Axis)", line, re.IGNORECASE)
            if bank_match:
                merchant = bank_match.group(1)

        # Final fallback
        if not merchant:
            merchant = "Transaction"

        # Clean merchant name
        merchant = merchant.split()[0].capitalize()

        # Add to parsed transactions array
        parsed_transactions.append({
            "merchant": merchant,
            "amount": amount,
            "currency": currency,
            "date": current_date
        })

    # Insert all parsed transactions into database
    for transaction in parsed_transactions:
        t = Transaction(
            merchant=transaction["merchant"],
            amount=transaction["amount"],
            currency=transaction["currency"],
            date=transaction["date"],
            status="active"
        )
        db.add(t)

    db.commit()
    db.close()
    return {"parsed_transactions": parsed_transactions}

@app.get("/brokerages")
def get_brokerages():
    try:
        brokerages = [
            {
                "id": "zerodha",
                "name": "Zerodha",
                "type": "Discount Broker",
                "deep_link": "kite://",
                "web_url": "https://kite.zerodha.com/",
                "region": "IN",
                "is_active": True
            },
            {
                "id": "groww",
                "name": "Groww",
                "type": "Investment Platform",
                "deep_link": "groww://",
                "web_url": "https://groww.in/",
                "region": "IN",
                "is_active": True
            }
        ]

        active_brokerages = [b for b in brokerages if b["is_active"]]
        return {"brokerages": active_brokerages}

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.delete("/subscriptions/{merchant}")
def delete_subscription(merchant: str):
    """
    Delete a subscription by merchant name.
    Removes all transactions for the given merchant.
    """
    print(f"🗑️ Deleting subscription: {merchant}")
    db = SessionLocal()
    
    try:
        # Delete all transactions for this merchant
        deleted_count = db.query(Transaction).filter(Transaction.merchant == merchant).delete()
        db.commit()
        print(f"✅ Deleted {deleted_count} transactions for {merchant}")
        db.close()
        return {"status": "success", "message": f"Deleted {merchant} subscription", "deleted_count": deleted_count}
    except Exception as e:
        db.rollback()
        db.close()
        print(f"❌ Error deleting subscription: {e}")
        return {"status": "error", "message": f"Failed to delete {merchant} subscription"}

@app.post("/reset")
def reset_database():
    """
    Clear all data from database.
    Called by frontend Reset button.
    """
    print("🔄 Resetting entire database")
    db = SessionLocal()
    
    try:
        deleted_count = db.query(Transaction).delete()
        db.commit()
        print(f"✅ Reset complete: deleted {deleted_count} transactions")
        db.close()
        return {"status": "success", "message": "Database reset complete", "deleted_count": deleted_count}
    except Exception as e:
        db.rollback()
        db.close()
        print(f"❌ Error resetting database: {e}")
        return {"status": "error", "message": "Failed to reset database"}

@app.delete("/clear")
def clear_data():
    db = SessionLocal()
    try:
        deleted_count = db.query(Transaction).delete()
        db.commit()
        print(f"✅ Clear complete: deleted {deleted_count} transactions")
        db.close()
        return {"status": "success", "message": "Database cleared!", "deleted_count": deleted_count}
    except Exception as e:
        db.rollback()
        db.close()
        print(f"❌ Error clearing database: {e}")
        return {"status": "error", "message": f"Failed to clear database: {e}"}

@app.post("/cancel")
def sync_cancel(merchant: str):
    """
    Sync cancellation status from frontend.
    Called when user confirms cancellation in Wealth Pilot.
    """
    print(f"🔄 Syncing cancellation status for {merchant}")
    db = SessionLocal()
    
    try:
        # Update all transactions for this merchant to cancelled
        updated_count = db.query(Transaction).filter(Transaction.merchant == merchant).update({
            "status": "cancelled",
            "cancellation_date": datetime.now().strftime("%Y-%m-%d")
        })
        db.commit()
        print(f"✅ Updated {updated_count} transactions for {merchant} to cancelled")
        db.close()
        return {"status": "success", "merchant": merchant, "updated_count": updated_count}
    except Exception as e:
        db.rollback()
        db.close()
        print(f"❌ Error syncing cancellation: {e}")
        return {"status": "error", "message": f"Failed to sync cancellation for {merchant}"}

# =========================================================
# 📊 MARKET SCAN (INSIGHT ONLY - NO EXECUTION)
# =========================================================

@app.get("/market-scan")
def market_scan():
    """
    Lightweight market intelligence endpoint.
    DOES NOT execute trades.
    Returns strongest sectors and top opportunities.
    """

    import yfinance as yf
    from collections import defaultdict
    from datetime import datetime

    try:
        tickers = [
            "TSM", "SONY", "HMC", "TM", "BABA", "JD", "BIDU", "PDD", "INFY", "WIT", "HDB", "IBN",
            "ASML", "SAP", "NVO", "SNY", "AZN", "RHHBY", "HSBC", "SHEL", "BP", "MBGYY", 
            "RY", "TD", "SHOP", "MELI", "PBR", "VALE",
            "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "JPM", "GS", "LLY", "UNH",
            "SPY", "QQQ", "EEM", "VGK", "EWJ", "INDA", "GLD", "SLV", "USO",
            "BTC-USD", "ETH-USD", "SOL-USD"
        ]
        
        sector_map = {
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

        raw = yf.download(tickers, period="5d", interval="1h", group_by="ticker", progress=False)

        signals = {}
        sector_scores = defaultdict(list)

        for s in tickers:
            if s not in raw or raw[s].empty:
                continue

            df = raw[s].dropna()
            if len(df) < 20:
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # Regime filter
            if len(df) >= 200:
                sma_200 = df['Close'].rolling(window=200).mean().iloc[-1]
                current_price = df['Close'].iloc[-1]
                regime = "Bullish" if current_price > sma_200 else "Bearish"
            else:
                regime = "Bullish"

            # Simple momentum signal (simplified version)
            if len(df) >= 20:
                momentum = (df['Close'].iloc[-1] / df['Close'].iloc[-20]) - 1
                signals[s] = float(momentum)

                sector = sector_map.get(s, "OTHER")
                sector_scores[sector].append(momentum)

        if not signals:
            return {"status": "no_data"}

        # Rank sectors
        sector_avg = {
            sec: sum(vals)/len(vals)
            for sec, vals in sector_scores.items()
            if len(vals) > 0
        }

        sorted_sectors = sorted(
            sector_avg.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )

        top_sector = sorted_sectors[0][0] if sorted_sectors else "NONE"

        # Rank symbols
        top_symbols = sorted(
            signals.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )[:3]

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_regime": regime,
            "strongest_sector": top_sector,
            "sector_scores": sector_avg,
            "top_opportunities": [
                {"symbol": sym, "signal": round(sig, 5)}
                for sym, sig in top_symbols
            ]
        }

    except Exception as e:
        return {"error": str(e)}

# =========================================================
# ROUTES: SUBSCRIPTION INSTANCES
# =========================================================

@app.get("/subscriptions/{merchant}/instances")
def get_subscription_instances(merchant: str):
    db = SessionLocal()
    try:
        instances = db.query(Transaction).filter(
            Transaction.merchant == merchant,
            Transaction.status == "active"
        ).all()
        
        return [
            {
                "id": instance.id,
                "amount": instance.amount,
                "currency": instance.currency,
                "date": instance.date
            }
            for instance in instances
        ]
    finally:
        db.close()

@app.post("/cancel-instance/{transaction_id}")
def cancel_subscription_instance(transaction_id: int):
    db = SessionLocal()
    print(f"===== CANCEL INSTANCE HIT for ID {transaction_id} - Merchant: {db.query(Transaction).filter(Transaction.id == transaction_id).first().merchant if db.query(Transaction).filter(Transaction.id == transaction_id).first() else 'NOT FOUND'} =====")
    try:
        instance = db.query(Transaction).filter(Transaction.id == transaction_id).first()
        
        if not instance:
            return {"error": "Transaction not found"}
        
        if instance.status == "active":
            instance.status = "cancelled"
            instance.cancellation_date = datetime.now().strftime("%Y-%m-%d")
            db.commit()
            return {"success": True, "message": "Instance cancelled successfully"}
        else:
            return {"error": "Instance is not active"}
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()



