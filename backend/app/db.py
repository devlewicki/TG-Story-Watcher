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
        "pool_timeout": 10,
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

        # --- backup_operations.stage: widen varchar(128) -> TEXT ---
        # Validation/restore results are stored as JSON here and exceed 128 chars.
        try:
            conn.execute(text("ALTER TABLE backup_operations ALTER COLUMN stage TYPE TEXT"))
            logger.info("Migration: backup_operations.stage -> TEXT")
        except Exception as e:
            logger.debug("Migration: stage skip — %s", e)

        # --- Performance indexes for stories browsing/searching/marking ---
        _perf_indexes = [
            # stories: sort by discovered_at (main listing ORDER BY)
            "CREATE INDEX IF NOT EXISTS ix_stories_discovered_at ON stories(discovered_at DESC)",
            # stories: WHERE filters on peer_id and source
            "CREATE INDEX IF NOT EXISTS ix_stories_peer_id ON stories(peer_id)",
            "CREATE INDEX IF NOT EXISTS ix_stories_source ON stories(source)",
            # stories: compound index for account+discovered (listing per user)
            "CREATE INDEX IF NOT EXISTS ix_stories_account_discovered ON stories(account_id, discovered_at DESC)",
            # stories: author search (ILIKE on username/name)
            "CREATE INDEX IF NOT EXISTS ix_stories_author_username ON stories(author_username)",
            "CREATE INDEX IF NOT EXISTS ix_stories_author_name ON stories(author_name)",
            # story_views: WHERE peer_id, GROUP BY telegram_story_id, ORDER BY viewed_at
            "CREATE INDEX IF NOT EXISTS ix_story_views_peer_id ON story_views(peer_id)",
            "CREATE INDEX IF NOT EXISTS ix_story_views_story_id_status ON story_views(story_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_story_views_viewed_at ON story_views(viewed_at)",
            "CREATE INDEX IF NOT EXISTS ix_story_views_account_viewed ON story_views(account_id, viewed_at)",
            # story_queue: FK story_id (no auto FK index), compound status+created
            "CREATE INDEX IF NOT EXISTS ix_story_queue_story_id ON story_queue(story_id)",
            "CREATE INDEX IF NOT EXISTS ix_story_queue_account_status ON story_queue(account_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_story_queue_status_created ON story_queue(status, created_at DESC)",
            # activity_logs: compound for likes lookup (event_type + account_id)
            "CREATE INDEX IF NOT EXISTS ix_activity_event_account ON activity_logs(event_type, account_id)",
            # activity_logs: story_skipped dedup scan
            "CREATE INDEX IF NOT EXISTS ix_activity_skip_dedup ON activity_logs(event_type, account_id, created_at DESC)",
        ]
        for stmt in _perf_indexes:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                logger.debug("Migration: index skip (%s): %s", stmt.split("ON ")[1] if "ON " in stmt else stmt, e)
        else:
            logger.info("Migration: applied %d performance indexes", len(_perf_indexes))

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
