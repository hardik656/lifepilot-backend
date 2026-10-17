import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # merchants.json is read relative to CWD
_tmp = tempfile.mkdtemp(prefix="lp-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ.pop("FINNHUB_API_KEY", None)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    import main

    main.rate_limit_store.clear() if hasattr(main, "rate_limit_store") else None
    c = TestClient(main.app)
    c.post("/reset", headers={"x-device-id": "test-device"})
    return c
