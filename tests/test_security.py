"""Guards against re-introducing hard-coded credentials."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [
    re.compile(r"""ALPACA_(KEY|SECRET)\s*=\s*["'][A-Za-z0-9]{16,}["']"""),
    re.compile(r"""FINNHUB_KEY\s*=\s*["'][a-z0-9]{20,}["']"""),
    re.compile(r"""\bPK[A-Z0-9]{18,}\b"""),  # Alpaca key-id shape
]


def test_no_hardcoded_credentials():
    offenders = []
    for path in ROOT.rglob("*.py"):
        if "tests" in path.parts or "venv" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        offenders += [f"{path.name}: {p.pattern}" for p in PATTERNS if p.search(text)]
    assert offenders == []


def test_engine_reads_credentials_from_env(monkeypatch):
    src = (ROOT / "trading" / "engine.py").read_text()
    assert 'os.environ.get("ALPACA_API_KEY"' in src
    assert 'os.environ.get("ALPACA_SECRET_KEY"' in src


def test_engine_disables_trading_without_credentials(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    import importlib

    import trading.engine as engine

    engine = importlib.reload(engine)
    assert engine.alpaca is None
    assert engine.main_cycle() is None  # returns early instead of crashing
