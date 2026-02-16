# =========================================================
# 🚀 LifePilot — AI Pilot Engine (Detection + Automation)
# =========================================================

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from automation.cancel_bot import start_cancellation_bot
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, text
from sqlalchemy.orm import sessionmaker, declarative_base
from pydantic import BaseModel
from collections import defaultdict
from datetime import datetime, timedelta
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
            currency_totals[row.currency] += row.amount
            merchant_invested.add(row.merchant)
    
    for r in rows:
        merchant_data[r.merchant]["amounts"].append(r.amount)
        merchant_data[r.merchant]["currencies"].append(r.currency)
        if not merchant_data[r.merchant]["last_date"] or r.date > merchant_data[r.merchant]["last_date"]:
            merchant_data[r.merchant]["last_date"] = r.date
    
    result = []
    total_savings_sum = 0
    today = datetime.now()
    
    for merchant, data in merchant_data.items():
        if len(data["amounts"]) >= 1:
            avg_cost = sum(data["amounts"]) / len(data["amounts"])
            total_savings_sum += avg_cost
            last_dt = datetime.strptime(data["last_date"], "%Y-%m-%d")
            days_diff = (today - last_dt).days
            
            # Get most common currency for this merchant
            most_common_currency = max(set(data["currencies"]), key=data["currencies"].count)
            
            # STALE LOGIC
            is_stale = True
            
            result.append({
                "merchant": merchant,
                "monthly_cost": round(avg_cost, 2),
                "currency": most_common_currency,
                "occurrences": len(data["amounts"]),
                "last_seen_days": days_diff,
                "is_stale": is_stale,
                "invested": merchant in merchant_invested
            })
    db.close()
    return {
        "subscriptions": result, 
        "total_savings": round(total_savings_sum, 2), 
        "total_invested": round(sum(currency_totals.values()), 2),
        "currency_totals": {
            "USD": round(currency_totals.get("$", 0), 2),
            "INR": round(currency_totals.get("Rs.", 0) + currency_totals.get("₹", 0), 2),
            "GBP": round(currency_totals.get("£", 0), 2)
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
    
    # Prevent Duplicate Investments
    already_invested = db.query(Transaction).filter(
        Transaction.merchant == data.merchant,
        Transaction.amount == data.monthly_cost,
        Transaction.is_invested == True
    ).first()
    
    if already_invested:
        return {"status": "already_invested", "message": "Subscription already invested"}
    
    # Update or create investment record
    existing = db.query(Transaction).filter(
        Transaction.merchant == data.merchant,
        Transaction.amount == data.monthly_cost,
        Transaction.is_invested == False
    ).first()
    
    if existing:
        existing.is_invested = True
        db.commit()
        print(f"✅ Updated {data.merchant} is_invested to True")
    else:
        # Create new investment record
        investment = Transaction(
            merchant=data.merchant,
            amount=data.monthly_cost,
            currency=data.currency,  # Use currency from request
            date=datetime.now().strftime("%Y-%m-%d"),
            status="active",
            is_invested=True
        )
        db.add(investment)
        db.commit()
        print(f"✅ Created investment record for {data.merchant}")
    
    db.close()
    return {"status": "success", "message": f"Investment recorded for {data.merchant}"}

# =========================================================
# ROUTES: UTILS
# =========================================================

@app.post("/parse-sms")
def parse_sms(data: SMSInput):
    db = SessionLocal()
    lines = data.text.splitlines()
    count = 0
    current_date = datetime.now().strftime("%Y-%m-%d")

    for line in lines:
        if not line.strip(): continue
        # Dynamic currency detection: Capture currency prefix and amount
        currency_match = re.search(r"(Rs\.?|\$|£|€)\s?(\d+(?:\.\d{1,2})?)", line)
        amount_match = re.search(r"\$?\s?(\d+(?:\.\d{1,2})?)", line)  # Fallback
        # 🧹 IMPROVED REGEX: Captures only the first word after the trigger for cleaner UI
        merchant_match = re.search(r"(?:for|at|to|[:]|spent)\s+([A-Za-z]+)", line, re.IGNORECASE)

        if currency_match:
            amount = float(currency_match.group(2))
            currency = currency_match.group(1)
            # Normalize Currency Before Saving
            if currency == 'Rs' or currency == 'Rs.':
                currency = 'Rs.'
            elif currency == '₹':
                currency = '₹'
            elif currency == '$' or currency == 'USD':
                currency = '$'
        elif amount_match:
            amount = float(amount_match.group(1))
            currency = "$"  # Default currency
        else:
            continue
            
        # 🚀 DATA CLEANUP: Extracts only the core name and capitalizes it (e.g., "NETFLIX" -> "Netflix")
        raw_merchant = merchant_match.group(1).strip() if merchant_match else "unknown"
        merchant = raw_merchant.split()[0].capitalize() 
        
        # Harden SMS Duplicate Detection (24h Protection)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        recent_duplicate = db.query(Transaction).filter(
            Transaction.merchant == merchant, 
            Transaction.amount == amount,
            Transaction.date >= yesterday
        ).first()

        if recent_duplicate:
            continue  # Skip insertion for recent duplicates
        
        existing = db.query(Transaction).filter(
            Transaction.merchant == merchant, 
            Transaction.amount == amount,
            Transaction.date == current_date
        ).first()

        if not existing:
            t = Transaction(merchant=merchant, amount=amount, currency=currency, date=current_date, status="active")
            db.add(t)
            count += 1
    db.commit()
    db.close()
    return {"parsed_transactions": count}

@app.get("/brokerages")
def get_brokerages():
    """Get list of active brokerages for investment redirection"""
    try:
        # Mock data - in production, this would come from database
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
        
        # Filter only active brokerages
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