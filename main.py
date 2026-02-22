# =========================================================
# 🚀 LifePilot — AI Pilot Engine (Detection + Automation)
# =========================================================
import sys
import os
import pandas as pd
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from automation.cancel_bot import start_cancellation_bot
from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Header
import time
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, text
from sqlalchemy.orm import sessionmaker, declarative_base
from pydantic import BaseModel
from collections import defaultdict
from datetime import datetime, timezone
import csv
import re

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN", ""),
    integrations=[FastApiIntegration()],
    traces_sample_rate=0.2,
    environment="beta"
)

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
from database import engine, SessionLocal, Base

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
    raw_sms = Column(String, default=None)
    recurrence_confidence = Column(Float, default=0.0)
    device_id = Column(String, default="legacy")

Base.metadata.create_all(bind=engine)

def ensure_columns():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN device_id VARCHAR DEFAULT 'legacy'"))
            conn.commit()
            print("✅ Added device_id column")
        except Exception:
            pass  # Column already exists — safe to ignore

ensure_columns()

from typing import Optional

def get_device_id(x_device_id: Optional[str] = None) -> str:
    if x_device_id and len(x_device_id) > 5:
        return x_device_id
    return "legacy"

# Simple in-memory rate limiter
_rate_limit_store = defaultdict(list)
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60

def check_rate_limit(client_ip: str):
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    _rate_limit_store[client_ip] = [
        t for t in _rate_limit_store[client_ip] if t > window_start
    ]
    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a moment before parsing more SMS."
        )
    _rate_limit_store[client_ip].append(now)

# =========================================================
# DATA MODELS
# =========================================================
class SMSInput(BaseModel):
    text: str
    device_id: Optional[str] = None

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
    merchant: str | None = None

class CancelRequest(BaseModel):
    merchant: str
    username: str = "user@example.com"
    password: str = "password123"

class InvestmentRequest(BaseModel):
    merchant: str
    monthly_cost: float
    currency: str = "$"
    device_id: Optional[str] = None

# =========================================================
# ROUTES: DETECTION
# =========================================================

def classify_recurrence(merchant: str, amount: float, raw_sms: str, db, device_id: str = "legacy") -> float:
    """
    3-layer recurrence classifier.
    Returns confidence score between 0.0 and 1.0.
    """
    confidence = 0.0

    # =========================================================
    # LAYER 3 — Text Signal Boost (check raw SMS first)
    # Boosts confidence if SMS contains recurring payment keywords
    # =========================================================
    RECURRING_KEYWORDS = [
        "subscription", "renewal", "auto-debit", "auto debit",
        "standing instruction", " si ", "recurring", "emi",
        "mandate", "autopay", "auto-pay", "monthly charge",
        "annual charge", "yearly charge", "membership"
    ]
    sms_lower = (raw_sms or "").lower()
    text_boost = 0.0
    for keyword in RECURRING_KEYWORDS:
        if keyword in sms_lower:
            text_boost = 0.2
            break

    # =========================================================
    # LAYER 1 + 2 — Pattern Analysis
    # Requires 2+ transactions for same merchant
    # =========================================================
    transactions = db.query(Transaction).filter(
        Transaction.merchant == merchant,
        Transaction.status == "active",
        Transaction.device_id == device_id
    ).order_by(Transaction.date).all()

    if len(transactions) < 2:
        # Single transaction — rely on text signal only
        confidence = text_boost
        return round(min(confidence, 1.0), 2)

    # Calculate intervals and amount variation
    dates = []
    amounts = []
    for t in transactions:
        try:
            dates.append(datetime.strptime(t.date, "%Y-%m-%d"))
            amounts.append(t.amount)
        except Exception:
            continue

    if len(dates) < 2:
        confidence = text_boost
        return round(min(confidence, 1.0), 2)

    intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
    avg_interval = sum(intervals) / len(intervals)
    avg_amount = sum(amounts) / len(amounts)
    amount_variation = max(abs(a - avg_amount) / avg_amount for a in amounts) if avg_amount > 0 else 1.0

    # LAYER 1 — Deterministic: monthly pattern, stable amount
    is_monthly = all(25 <= interval <= 35 for interval in intervals)
    is_stable_amount = amount_variation <= 0.20

    if is_monthly and is_stable_amount:
        confidence = 0.90 + text_boost
        return round(min(confidence, 1.0), 2)

    # LAYER 2 — Semi-recurring: inconsistent interval but similar amount
    is_semi_recurring = (
        15 <= avg_interval <= 45 and
        amount_variation <= 0.35 and
        len(transactions) >= 2
    )

    if is_semi_recurring:
        # Scale confidence based on how many occurrences
        occurrence_boost = min(len(transactions) * 0.05, 0.15)
        confidence = 0.60 + occurrence_boost + text_boost
        return round(min(confidence, 1.0), 2)

    # Below threshold — text signal only
    confidence = text_boost
    return round(min(confidence, 1.0), 2)

@app.get("/subscriptions")
def detect_subscriptions(x_device_id: Optional[str] = Header(None)):
    device_id = get_device_id(x_device_id)
    db = SessionLocal()
    rows = db.query(Transaction).filter(Transaction.device_id == device_id).all()
    merchant_invested = set()
    merchant_data = defaultdict(lambda: {"amounts": [], "last_date": "", "currencies": []})
    merchant_total_counts = defaultdict(int)
    
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
        # Track total historical transactions (active + cancelled)
        merchant_total_counts[r.merchant] += 1

        # Keep existing invested currency logic unchanged above this block

        if r.status == "active":
            merchant_data[r.merchant]["amounts"].append(r.amount)
            merchant_data[r.merchant]["currencies"].append(r.currency)

            if (
                not merchant_data[r.merchant]["last_date"]
                or r.date > merchant_data[r.merchant]["last_date"]
            ):
                merchant_data[r.merchant]["last_date"] = r.date
    
    # Build merchant transactions map — 1 query instead of N queries
    merchant_transactions_map = defaultdict(list)
    for r in rows:
        merchant_transactions_map[r.merchant].append(r)

    result = []
    total_savings_sum = 0
    today = datetime.now()
    
    for merchant, data in merchant_data.items():
        if len(data["amounts"]) >= 1:
            occurrences = len(data["amounts"])
            active_count = occurrences
            total_detected = merchant_total_counts[merchant]
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
            
            is_stale = days_diff > 45
            
            merchant_status = "active"
            
            merchant_transactions = merchant_transactions_map[merchant]

            statuses = {t.status for t in merchant_transactions}

            active_transactions = [t for t in merchant_transactions if t.status == "active"]

            if "charge_detected_after_cancel" in statuses:
                merchant_status = "charge_detected_after_cancel"
            elif "cancellation_requested" in statuses:
                merchant_status = "cancellation_requested"
            elif len(active_transactions) == 0 and "cancelled" in statuses:
                merchant_status = "cancelled"
            else:
                merchant_status = "active"
            
            duplicate_flag = active_count > 1
            
            # Get latest raw SMS for this merchant for text signal
            latest_raw_sms = next(
                (t.raw_sms for t in reversed(merchant_transactions) if t.raw_sms),
                ""
            )

            recurrence_score = classify_recurrence(
                merchant, monthly_cost, latest_raw_sms, db, device_id
            )

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
                "duplicate_count": total_detected,    # now reflects historical duplicates
                "active_count": active_count,         # NEW field (safe addition)
                "total_detected": total_detected,      # NEW field (safe addition)
                "recurrence_confidence": recurrence_score
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
def update_cancellation_status(merchant: str, data: CancellationUpdate, x_device_id: Optional[str] = Header(None)):
    device_id = get_device_id(x_device_id)
    db = SessionLocal()
    try:
        transactions = db.query(Transaction).filter(
            Transaction.merchant == merchant,
            Transaction.device_id == device_id
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
def handle_investment(data: InvestmentRequest, x_device_id: Optional[str] = Header(None)):
    """
    Records when user invests a subscription into Gold Vault.
    Updates subscription status to 'invested' and tracks total investments.
    """
    device_id = data.device_id or get_device_id(x_device_id)
    print(f"🏆 Investment: Received request to invest {data.merchant} for ${data.monthly_cost}")
    
    # Add Invalid Amount Guard
    if data.monthly_cost <= 0:
        return {"status": "error", "message": "Invalid investment amount"}
    
    db = SessionLocal()
    
    # Find all non-invested rows for this merchant
    non_invested_rows = db.query(Transaction).filter(
        Transaction.merchant == data.merchant,
        Transaction.is_invested == False,
        Transaction.status == "active",
        Transaction.device_id == device_id
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
        Transaction.merchant == data.merchant,
        Transaction.device_id == device_id
    ).first():
        # Create ONE new investment record
        print(f"➕ No existing rows found. Creating new investment record for {data.merchant}")
        investment = Transaction(
            merchant=data.merchant,
            amount=data.monthly_cost,
            currency=data.currency,
            date=datetime.now().strftime("%Y-%m-%d"),
            status="active",
            is_invested=True,
            device_id=device_id
        )
        db.add(investment)
        db.commit()
        print(f"✅ Created new investment record for {data.merchant}")
    
    # Verify final count
    invested_count = db.query(Transaction).filter(
        Transaction.merchant == data.merchant,
        Transaction.is_invested == True,
        Transaction.device_id == device_id
    ).count()
    print(f"📊 FINAL: {invested_count} invested rows for {data.merchant}")
    
    db.close()
    return {"status": "success", "message": f"Investment recorded for {data.merchant}"}

# =========================================================
# ROUTES: UTILS
# =========================================================

@app.post("/parse-sms")
def parse_sms(data: SMSInput, request: Request, x_device_id: Optional[str] = Header(None)):
    check_rate_limit(request.client.host)
    device_id = data.device_id or get_device_id(x_device_id)
    db = SessionLocal()
    lines = data.text.splitlines()
    parsed_transactions = []
    current_date = datetime.now().strftime("%Y-%m-%d")

    # Reject entire SMS if it looks like a one-time card spend
    full_text = data.text.lower()
    ONE_TIME_SIGNALS = [
        'avl limit',
        'available limit', 
        'not you? sms block',
        'avl bal',
    ]
    if any(signal in full_text for signal in ONE_TIME_SIGNALS):
        db.close()
        return {"parsed_transactions": []}

    # Load merchant DB once outside loop — performance critical
    import json
    try:
        with open("merchants.json", "r") as f:
            merchant_db = json.load(f)
    except Exception:
        merchant_db = {}

    for line in lines:
        if not line.strip():
            continue

        # 1️⃣ Currency + Amount Detection
        currency_match = re.search(r"(INR|Rs\.?|₹|\$|£)\s?(\d+(?:\.\d{1,2})?)", line)
        if not currency_match:
            continue

        currency = currency_match.group(1)
        amount = float(currency_match.group(2))

        # Normalize currency
        if currency in ["Rs", "Rs.", "₹", "INR"]:
            currency = "INR"
        elif currency == "$":
            currency = "USD"
        elif currency == "£":
            currency = "GBP"

        # 2️⃣ Smart Merchant Extraction
        merchant = None

        # PRIORITY 1: UPI VPA extraction — most reliable for Indian SMS
        # Matches: "to payzomato@hdfcbank" or "VPA payzomato@hdfcbank"
        vpa_match = re.search(r"(?:to|VPA)\s+([A-Za-z0-9]+)@[A-Za-z0-9]+", line, re.IGNORECASE)
        if vpa_match:
            vpa_handle = vpa_match.group(1).lower()

            # Known VPA prefix → clean merchant name mapping
            VPA_MAP = {
                "payzomato": "Zomato",
                "zomato": "Zomato",
                "netflix": "Netflix",
                "hotstar": "Hotstar",
                "spotify": "Spotify",
                "amazon": "Amazon",
                "primevideo": "Amazon",
                "applecom": "Apple",
                "apple": "Apple",
                "google": "Google",
                "youtube": "YouTube",
                "swiggy": "Swiggy",
                "ola": "Ola",
                "uber": "Uber",
                "gym": "Gym",
                "zerodha": "Zerodha",
                "groww": "Groww",
            }

            # Check known map first
            matched = False
            for key, name in VPA_MAP.items():
                if key in vpa_handle:
                    merchant = name
                    matched = True
                    break

            # If not in map, clean the VPA handle
            if not matched:
                # Strip common prefixes: pay, sub, bills, upi, auto
                cleaned = re.sub(r"^(pay|sub|bills?|upi|auto)", "", vpa_handle)
                # Strip trailing numbers
                cleaned = re.sub(r"\d+$", "", cleaned)
                if len(cleaned) >= 3:
                    merchant = cleaned.capitalize()

        # PRIORITY 2: Common preposition patterns
        if not merchant:
            patterns = [
                r"(?:at|to|for|on)\s+([A-Za-z][A-Za-z0-9&\s]{2,}?)(?:\s+via|\s+on|\s+ref|\.|\,|$)",
                r"from\s+([A-Za-z][A-Za-z0-9&\s]{2,}?)(?:\s+via|\s+on|\s+ref|\.|\,|$)",
            ]
            for pattern in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    merchant = match.group(1).strip()
                    break

        # PRIORITY 3: Skip personal transfers (names with numbers like pradeep4221)
        # If merchant looks like a personal UPI ID, discard it
        if merchant and re.search(r"\d{3,}", merchant):
            merchant = None

        # PRIORITY 4: Bank name fallback — skip, these are not merchants
        # Don't use Kotak/HDFC as merchant names

        # PRIORITY 5: Final fallback
        if not merchant:
            merchant = "Unknown"

        # Clean merchant name — remove noise words
        BANK_KEYWORDS = ['spent', 'debit', 'debited', 'payment', 'transaction',
                         'transfer', 'charged', 'purchase', 'paid', 'sent',
                         'alert', 'info', 'dear', 'your', 'acct', 'account',
                         'kotak', 'hdfc', 'icici', 'sbi', 'axis', 'bank',
                         'not', 'you', 'upi', 'ref', 'from', 'via']
        words = [w for w in merchant.split() if w.lower() not in BANK_KEYWORDS]
        merchant = words[0].capitalize() if words else "Unknown"

        # Normalize merchant against known merchant database
        try:
            # Normalize symbols before matching
            # Replace dots/dashes with spaces, strip non-alpha
            search = re.sub(r'[-.]', ' ', merchant)
            search = re.sub(r'[^a-zA-Z\s]', '', search).lower().strip()

            for key, data in merchant_db.items():
                aliases = data.get("aliases", [])
                matched = False
                for alias in aliases:
                    alias_clean = re.sub(r'[-.]', ' ', alias)
                    alias_clean = re.sub(r'[^a-zA-Z\s]', '', alias_clean).lower().strip()

                    # Exact match, search starts with alias, or alias is a whole word in search
                    if (search == alias_clean or
                        search.startswith(alias_clean) or
                        alias_clean in search.split()):
                        merchant = data["name"]
                        matched = True
                        break
                if matched:
                    break
        except Exception:
            pass  # Silent fallback — keep original merchant name

        # Add to parsed transactions array
        parsed_transactions.append({
            "merchant": merchant,
            "amount": amount,
            "currency": currency,
            "date": current_date,
            "raw_sms": line.strip()
        })

    # Insert all parsed transactions into database
    for transaction in parsed_transactions:
        # Calculate initial confidence on insert
        initial_confidence = classify_recurrence(
            transaction["merchant"],
            transaction["amount"],
            transaction.get("raw_sms", ""),
            db,
            device_id
        )
        t = Transaction(
            merchant=transaction["merchant"],
            amount=transaction["amount"],
            currency=transaction["currency"],
            date=transaction["date"],
            status="active",
            raw_sms=transaction.get("raw_sms"),
            recurrence_confidence=initial_confidence,
            device_id=device_id
        )
        db.add(t)

    db.commit()

    # Recalculate recurrence for all affected merchants after insert
    # This fixes confidence lag — new transaction now visible in DB
    unique_merchants = set(t["merchant"] for t in parsed_transactions)
    for merchant_name in unique_merchants:
        merchant_txns = db.query(Transaction).filter(
            Transaction.merchant == merchant_name,
            Transaction.device_id == device_id
        ).all()
        latest_sms = next(
            (t.raw_sms for t in reversed(merchant_txns) if t.raw_sms), ""
        )
        updated_score = classify_recurrence(merchant_name, 0, latest_sms, db, device_id)
        for t in merchant_txns:
            t.recurrence_confidence = updated_score

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
def delete_subscription(merchant: str, x_device_id: Optional[str] = Header(None)):
    """
    Delete a subscription by merchant name.
    Removes all transactions for the given merchant.
    """
    device_id = get_device_id(x_device_id)
    print(f"🗑️ Deleting subscription: {merchant}")
    db = SessionLocal()
    
    try:
        # Delete all transactions for this merchant
        deleted_count = db.query(Transaction).filter(
            Transaction.merchant == merchant,
            Transaction.device_id == device_id
        ).delete()
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
def reset_database(x_device_id: Optional[str] = Header(None)):
    """
    Clear all data from database.
    Called by frontend Reset button.
    """
    device_id = get_device_id(x_device_id)
    print(f"🔄 Resetting database for device {device_id}")
    db = SessionLocal()
    
    try:
        deleted_count = db.query(Transaction).filter(Transaction.device_id == device_id).delete()
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
def sync_cancel(data: CancellationUpdate, x_device_id: Optional[str] = Header(None)):
    """
    Sync cancellation status from frontend.
    Called when user confirms cancellation in Wealth Pilot.
    """
    device_id = get_device_id(x_device_id)
    print(f"🔄 Syncing cancellation status for {data.merchant}")
    db = SessionLocal()
    
    try:
        # Update all transactions for this merchant to cancelled
        updated_count = db.query(Transaction).filter(
            Transaction.merchant == data.merchant,
            Transaction.device_id == device_id
        ).update({
            "status": data.status,
            "cancellation_date": data.cancellation_date or datetime.now().strftime("%Y-%m-%d")
        })
        db.commit()
        print(f"✅ Updated {updated_count} transactions for {data.merchant} to cancelled")
        db.close()
        return {"status": "success", "merchant": data.merchant, "updated_count": updated_count}
    except Exception as e:
        db.rollback()
        db.close()
        print(f"❌ Error syncing cancellation: {e}")
        return {"status": "error", "message": f"Failed to sync cancellation for {data.merchant}"}

# In-memory market scan cache
_market_scan_cache = {
    "data": None,
    "timestamp": None
}
CACHE_TTL_SECONDS = 300  # 5 minutes

# =========================================================
# 📊 MARKET SCAN (INSIGHT ONLY - NO EXECUTION)
# =========================================================

@app.get("/market-scan")
def market_scan():
    global _market_scan_cache

    # Return cached result if fresh
    if (
        _market_scan_cache["data"] is not None and
        _market_scan_cache["timestamp"] is not None
    ):
        age = (datetime.now(timezone.utc) - _market_scan_cache["timestamp"]).total_seconds()
        if age < CACHE_TTL_SECONDS:
            cached = dict(_market_scan_cache["data"])
            cached["cached"] = True
            cached["cache_age_seconds"] = int(age)
            return cached

    import requests
    from collections import defaultdict

    FINNHUB_KEY = "d65ov1hr01qiish0i2rgd65ov1hr01qiish0i2s0"

    tickers = [
        "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA",
        "JPM", "GS", "LLY", "UNH", "TSM", "ASML", "NVO", "SHOP",
        "MELI", "INFY", "HDB", "BABA", "VALE"
    ]

    sector_map = {
        "NVDA": "TECH", "AAPL": "TECH", "MSFT": "TECH",
        "GOOGL": "TECH", "AMZN": "TECH", "META": "TECH",
        "TSLA": "AUTO", "JPM": "FIN", "GS": "FIN",
        "LLY": "HEALTH", "UNH": "HEALTH", "TSM": "TECH",
        "ASML": "TECH", "NVO": "HEALTH", "SHOP": "TECH",
        "MELI": "TECH", "INFY": "IND_TECH", "HDB": "FIN",
        "BABA": "CHN_TECH", "VALE": "MINING"
    }

    try:
        signals = {}
        sector_scores = defaultdict(list)
        regime = "Bullish"

        for symbol in tickers:
            try:
                url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
                res = requests.get(url, timeout=5)
                if res.status_code != 200:
                    continue
                data = res.json()

                current = data.get("c", 0)
                prev_close = data.get("pc", 0)

                if not current or not prev_close or prev_close == 0:
                    continue

                momentum = (current - prev_close) / prev_close
                signals[symbol] = float(momentum)

                sector = sector_map.get(symbol, "OTHER")
                sector_scores[sector].append(momentum)

            except Exception:
                continue

        if not signals:
            return {
                "status": "unavailable",
                "message": "Market data temporarily unavailable. Please try again later."
            }

        # Rank sectors
        sector_avg = {
            sec: sum(vals) / len(vals)
            for sec, vals in sector_scores.items()
            if len(vals) > 0
        }

        sorted_sectors = sorted(
            sector_avg.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )

        top_sector = sorted_sectors[0][0] if sorted_sectors else "NONE"

        # Determine regime from majority of signals
        bullish_count = sum(1 for v in signals.values() if v > 0)
        regime = "Bullish" if bullish_count > len(signals) / 2 else "Bearish"

        # Top opportunities
        top_symbols = sorted(
            signals.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )[:3]

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_regime": regime,
            "strongest_sector": top_sector,
            "sector_scores": sector_avg,
            "top_opportunities": [
                {"symbol": sym, "signal": round(sig, 5)}
                for sym, sig in top_symbols
            ],
            "cached": False,
            "cache_age_seconds": 0
        }

        _market_scan_cache["data"] = result
        _market_scan_cache["timestamp"] = datetime.now(timezone.utc)

        return result

    except Exception as e:
        return {
            "status": "unavailable",
            "message": "Market data temporarily unavailable. Please try again later.",
            "error": str(e)
        }

# =========================================================
# ROUTES: MERCHANTS DATABASE
# =========================================================

@app.get("/merchants")
def get_all_merchants():
    try:
        import json
        with open("merchants.json", "r") as f:
            data = json.load(f)
        return data
    except Exception as e:
        return {"error": str(e)}

@app.get("/merchants/{merchant_name}")
def get_merchant_info(merchant_name: str):
    try:
        import json
        with open("merchants.json", "r") as f:
            data = json.load(f)

        search = merchant_name.lower().strip()

        # Direct key match first
        if search in data:
            return data[search]

        # Alias match
        for key, merchant in data.items():
            aliases = merchant.get("aliases", [])
            if any(search in alias.lower() or alias.lower() in search for alias in aliases):
                return merchant

        return {"found": False}

    except Exception as e:
        return {"error": str(e)}

# =========================================================
# ROUTES: SUBSCRIPTION INSTANCES
# =========================================================

@app.get("/subscriptions/{merchant}/instances")
def get_subscription_instances(merchant: str, x_device_id: Optional[str] = Header(None)):
    device_id = get_device_id(x_device_id)
    db = SessionLocal()
    try:
        instances = db.query(Transaction).filter(
            Transaction.merchant == merchant,
            Transaction.status == "active",
            Transaction.device_id == device_id
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
    instance_check = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    merchant_name = instance_check.merchant if instance_check else 'NOT FOUND'
    print(f"===== CANCEL INSTANCE HIT for ID {transaction_id} - Merchant: {merchant_name} =====")
    try:
        instance = db.query(Transaction).filter(Transaction.id == transaction_id).first()
        
        if not instance:
            return {"error": "Transaction not found"}
        
        if instance.status != "cancelled":
            instance.status = "cancelled"
            instance.cancellation_date = datetime.now().strftime("%Y-%m-%d")
            db.commit()
            return {"success": True, "message": "Instance cancelled successfully"}
        else:
            return {"error": "Instance already cancelled"}
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()



