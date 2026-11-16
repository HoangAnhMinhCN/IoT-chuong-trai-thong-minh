
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

# Shared config with the broker and iot_core: deployment/.env (or IOT_ENV_FILE)
ENV_FILE = Path(os.environ.get(
    "IOT_ENV_FILE",
    Path(__file__).resolve().parents[2] / "deployment" / ".env",
))
load_dotenv(ENV_FILE)

DATABASE_URL = os.getenv("DATABASE_URL")

# Without DATABASE_URL the app still imports (tests, devs without MySQL):
# the gateway falls back to iot_core's SQLite stores, and MySQL-backed
# features fail when used instead of at import time.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
) if DATABASE_URL else None

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)



def test_db_connection():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            print("MySQL connected successfully!")
            return True

    except Exception as e:
        print(f"MySQL connection failed: {e}")
        return False