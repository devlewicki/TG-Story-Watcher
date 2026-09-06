import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

logger = logging.getLogger("storywatcher.db")

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

# Connection pool tuning: default pool_size=5 with max_overflow=10 may be
# insufficient when API requests + worker processes compete for connections.
is_postgres = settings.database_url.startswith("postgresql")
_pool_kwargs: dict = {
    "pool_pre_ping": True,
}
if is_postgres:
    _pool_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 1800,
    })
engine = create_engine(settings.database_url, connect_args=connect_args, **_pool_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def _run_migrations() -> None:
    """Apply lightweight schema migrations that ``create_all`` cannot handle
    (adding a column to an *existing* table).
    """
    with engine.begin() as conn:
        # Set a short lock timeout so we don't block startup if another
        # connection already holds a lock on the table.
        try:
            conn.execute(text("SET lock_timeout = '3s'"))
        except Exception:
            pass  # SQLite doesn't support this

        # --- is_premium on telegram_accounts ---
        try:
            conn.execute(text(
                "ALTER TABLE telegram_accounts ADD COLUMN IF NOT EXISTS "
                "is_premium BOOLEAN NOT NULL DEFAULT false"
            ))
            logger.info("Migration: ensured is_premium column on telegram_accounts")
        except Exception as e:
            logger.debug("Migration: is_premium skip — %s", e)

        # Reset lock_timeout
        try:
            conn.execute(text("RESET lock_timeout"))
        except Exception:
            pass


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
