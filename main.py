# =========================================================
# 🚀 LifePilot — AI Pilot Engine (Detection + Automation)
# =========================================================

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from automation.cancel_bot import start_cancellation_bot
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import sessionmaker, declarative_base
from pydantic import BaseModel
from collections import defaultdict
from datetime import datetime
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
    status = Column(String, default="active")

Base.metadata.create_all(bind=engine)

# =========================================================
# DATA MODELS
# =========================================================
class SMSInput(BaseModel):
    text: str

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
    merchant_data = defaultdict(lambda: {"amounts": [], "last_date": "", "currencies": []})
    
    # Calculate total invested amount by currency
    currency_totals = defaultdict(float)
    for row in rows:
        if row.status == "invested":
            currency_totals[row.currency] += row.amount
    
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
                "is_stale": is_stale
            })
    db.close()
    return {
        "subscriptions": result, 
        "total_savings": round(total_savings_sum, 2), 
        "total_invested": round(sum(currency_totals.values()), 2),
        "currency_totals": {
            "USD": round(currency_totals.get("$", 0), 2),
            "INR": round(currency_totals.get("Rs.", 0), 2),
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
    
    db = SessionLocal()
    
    # Update or create investment record
    existing = db.query(Transaction).filter(
        Transaction.merchant == data.merchant,
        Transaction.amount == data.monthly_cost,
        Transaction.status == "active"
    ).first()
    
    if existing:
        existing.status = "invested"
        db.commit()
        print(f"✅ Updated {data.merchant} status to 'invested'")
    else:
        # Create new investment record
        investment = Transaction(
            merchant=data.merchant,
            amount=data.monthly_cost,
            currency=data.currency,  # Use currency from request
            date=datetime.now().strftime("%Y-%m-%d"),
            status="invested"
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
            # Normalize currency symbols
            if currency == 'Rs' or currency == 'Rs.':
                currency = 'Rs.'
        elif amount_match:
            amount = float(amount_match.group(1))
            currency = "$"  # Default currency
        else:
            continue
            
        # 🚀 DATA CLEANUP: Extracts only the core name and capitalizes it (e.g., "NETFLIX" -> "Netflix")
        raw_merchant = merchant_match.group(1).strip() if merchant_match else "unknown"
        merchant = raw_merchant.split()[0].capitalize() 
        
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
    db.query(Transaction).delete()
    db.commit()
    db.close()
    return {"status": "Database cleared!"}