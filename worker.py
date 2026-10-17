# =========================================================
# 🤖 LifePilot Trading Worker
# =========================================================

import time
import warnings
import logging
import schedule

# Import trading engine (DO NOT MODIFY ENGINE LOGIC)
from trading.engine import (
    retrain_models,
    main_cycle
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
warnings.filterwarnings("ignore")

# =========================================================
# 🚀 WORKER MAIN LOOP
# =========================================================
if __name__ == "__main__":
    print("🤖 Starting Trading Worker...")

    try:
        # Initial training
        retrain_models()

        # Schedule hourly scans
        schedule.every().hour.do(main_cycle)

        # Schedule weekly retraining
        schedule.every().sunday.at("00:00").do(retrain_models)

        # Run first scan immediately
        main_cycle()

        # Infinite scheduler loop
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                print("🛑 Trading Worker stopped")
                break
            except Exception as e:
                print(f"❌ Scheduler error: {e}")
                time.sleep(10)

    except Exception as e:
        print(f"❌ Fatal worker error: {e}")
        time.sleep(30)
