from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import auth, user_auth, settings, dashboard, discovery, accounts, rules, whitelist, blacklist
from .api import stories, queue, history, analytics
from .api.admin import router as admin_router
from .config import get_settings
from .db import init_db
from .telegram import client_manager as cm


logger = logging.getLogger("storywatcher")

settings_cfg = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (simple bootstrap; migrations can be added later).
    init_db()
    # Create the initial SUPER_ADMIN if no admin exists yet.
    try:
        from .admin_auth import ensure_bootstrap_admin
        from .db import SessionLocal

        _db = SessionLocal()
        try:
            ensure_bootstrap_admin(_db)
        finally:
            _db.close()
    except Exception:
        logger.exception("bootstrap admin creation failed")
    logger.info("%s starting (db=%s)", settings_cfg.app_name, settings_cfg.database_url)
    yield
    logger.info("%s shutting down, disconnecting Telegram clients", settings_cfg.app_name)
    try:
        await cm.shutdown_all()
    except Exception:
        logger.exception("error disconnecting Telegram clients during shutdown")


app = FastAPI(
    title=settings_cfg.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "app": settings_cfg.app_name}


# Routers grouped by domain. Auth-protected routers add the token dependency
# in the dependency_overrides-friendly way via the router's dependencies list.
app.include_router(auth.router, prefix="/api")
app.include_router(user_auth.router, prefix="/api")
app.include_router(accounts.router, prefix="/api")
app.include_router(stories.router, prefix="/api")
app.include_router(queue.router, prefix="/api")
app.include_router(rules.router, prefix="/api")
app.include_router(whitelist.router, prefix="/api")
app.include_router(blacklist.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(discovery.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")

# Admin panel API — separate auth (admin_sessions), mounted under /api/admin.
app.include_router(admin_router, prefix="/api")