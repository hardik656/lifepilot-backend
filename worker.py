# =========================================================
# 🤖 LifePilot Trading Worker
# =========================================================

import os, time, warnings, json, joblib, csv, logging
from datetime import datetime
import schedule

# Import trading engine
from trading.engine import (
    retrain_models, main_cycle, print_heatmap,
    TICKERS, SECTOR_MAP, state
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
warnings.filterwarnings("ignore")

# =========================================================
# 🚀 WORKER MAIN LOOP
# =========================================================
if __name__ == "__main__":
    print("🤖 Starting Trading Worker...")
    
    try:
        # Initial training
        retrain_models()
        
        # Schedule hourly scans and weekly retraining
        schedule.every().hour.do(main_cycle)
        schedule.every().sunday.at("00:00").do(retrain_models)
        
        # Run first scan immediately
        main_cycle()
        
        # Main scheduler loop
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                print("\n🛑 Trading Worker stopped by user")
                break
            except Exception as e:
                print(f"❌ Scheduler error: {e}")
                time.sleep(10)  # Wait before retry
                
    except Exception as e:
        print(f"❌ Fatal error in Trading Worker: {e}")
        time.sleep(30)  # Wait before possible restart
