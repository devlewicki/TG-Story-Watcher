import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

logger = logging.getLogger("storywatcher.db")

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def _run_migrations() -> None:
    """Apply lightweight schema migrations that ``create_all`` cannot handle
    (adding a column to an *existing* table).
    """
    with engine.begin() as conn:
        # --- is_premium on telegram_accounts ---
        try:
            conn.execute(text(
                "ALTER TABLE telegram_accounts ADD COLUMN IF NOT EXISTS "
                "is_premium BOOLEAN NOT NULL DEFAULT false"
            ))
            logger.info("Migration: ensured is_premium column on telegram_accounts")
        except Exception:
            logger.debug("Migration: is_premium column already present or table missing")


def init_db() -> None:
    from . import models  # noqa: F401  ensure models are imported

    Base.metadata.create_all(bind=engine)
    _run_migrations()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()