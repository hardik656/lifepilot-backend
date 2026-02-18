from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./lifepilot.db"

# Create engine with proper SQLite concurrency settings
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,  # Allow multi-thread access
        "timeout": 30                # Wait up to 30s if DB is locked
    }
)

# Enable WAL mode for better concurrent read/write handling
with engine.connect() as connection:
    connection.exec_driver_sql("PRAGMA journal_mode=WAL;")

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base model
Base = declarative_base()
