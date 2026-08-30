from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel as _BM
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import GeoPlace
from ..services.settings_service import SettingsService
from .deps import require_api_token

logger = logging.getLogger("storywatcher.api.discovery")

router = APIRouter(prefix="/discovery", tags=["discovery"], dependencies=[Depends(require_api_token)])

Db = Annotated[Session, Depends(get_db)]


class DiscoveryConfig(_BM):
    enabled: bool = False
    hashtags: list[str] = []
    locations: list[str] = []
    auto_add_places: bool = True
    search_interval: int = 300
    search_results_max: int = 50


def _config_defaults(cfg: dict) -> dict:
    """Fill a stored discovery config with current defaults.

    Keeps forward compatibility: fields added after the config was first saved
    are returned with their defaults instead of being absent.
    """
    merged = dict(
        {
            "enabled": False,
            "hashtags": [],
            "locations": [],
            "auto_add_places": True,
            "search_interval": 300,
            "search_results_max": 50,
        }
    )
    merged.update({k: v for k, v in (cfg or {}).items() if v is not None})
    return merged


@router.get("/config")
def get_discovery_config(db: Db):
    svc = SettingsService(db)
    return _config_defaults(svc.get("discovery"))


@router.post("/config")
def set_discovery_config(payload: DiscoveryConfig, db: Db):
    svc = SettingsService(db)
    merged = svc.set(
        "discovery",
        {
            "enabled": payload.enabled,
            "hashtags": [h.lstrip("#") for h in payload.hashtags],
            "locations": payload.locations,
            "auto_add_places": payload.auto_add_places,
            "search_interval": payload.search_interval,
            "search_results_max": payload.search_results_max,
        },
    )
    return {"ok": True, "config": merged}


@router.get("/places/count")
def count_places(db: Db):
    return {"count": db.query(GeoPlace).count()}


@router.get("/places")
def list_places(db: Db, q: str | None = None):
    """List collected geo places (venues harvested from stories)."""
    query = db.query(GeoPlace)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                GeoPlace.title.ilike(like),
                GeoPlace.address.ilike(like),
                GeoPlace.venue_id.ilike(like),
            )
        )
    # No cap: the counter and the panel show the full collected list, so a
    # hard limit here would silently hide newer places (same bug as /stories).
    places = query.order_by(GeoPlace.updated_at.desc()).all()
    return [
        {
            "id": p.id,
            "venue_id": p.venue_id,
            "title": p.title,
            "address": p.address,
            "provider": p.provider,
            "lat": p.lat,
            "long": p.long,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        for p in places
    ]


class PlaceIn(_BM):
    venue_id: str
    title: str | None = None
    address: str | None = None
    lat: float | None = None
    long: float | None = None
    provider: str | None = None


@router.post("/places")
def add_place(payload: PlaceIn, db: Db):
    """Add a geo place manually (upsert by venue id)."""
    vid = (payload.venue_id or "").strip()
    if not vid:
        raise HTTPException(status_code=400, detail="venue_id обязателен")
    place = db.query(GeoPlace).filter_by(venue_id=vid).first()
    if place is None:
        place = GeoPlace(venue_id=vid)
        db.add(place)
    place.title = (payload.title or "Место").strip()[:255]
    place.address = payload.address or None
    place.lat = payload.lat
    place.long = payload.long
    if payload.provider:
        place.provider = payload.provider
    db.commit()
    return {"ok": True, "id": place.id}


@router.delete("/places/{place_id}")
def delete_place(place_id: int, db: Db):
    place = db.get(GeoPlace, place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="место не найдено")
    db.delete(place)
    db.commit()
    return {"ok": True}


@router.get("/geocode")
def geocode(db: Db, q: str = ""):
    """Autocomplete for city/place names via a Nominatim (OpenStreetMap) server.

    Used by the panel's autocomplete so city names appear while typing. The
    selected city is stored as a ``city:<name>`` location; at search time it is
    resolved to a collected venue when possible, otherwise searched by hashtag.
    The geocoder URL can be overridden via ``STORYWATCHER_GEOCODER_URL``.
    """
    q = (q or "").strip()
    if len(q) < 2:
        return []
    base = os.environ.get(
        "STORYWATCHER_GEOCODER_URL", "https://nominatim.openstreetmap.org"
    ).rstrip("/")
    url = base + "/search?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "limit": 5, "addressdetails": 0}
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": "StoryWatcher/1.0 (self-hosted story monitor)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("geocode '%s' failed: %s", q, exc)
        return []
    out = []
    for it in data:
        name = it.get("name") or ""
        out.append(
            {
                "name": name,
                "display_name": it.get("display_name", ""),
                "lat": float(it.get("lat", 0) or 0),
                "lon": float(it.get("lon", 0) or 0),
                "type": it.get("type", ""),
                "category": it.get("category", ""),
            }
        )
    return out


@router.post("/search")
def run_discovery_search(db: Db):
    """Trigger an immediate discovery run.

    The actual MTProto search runs in the worker process (the sole owner of the
    Telegram session), so this endpoint sets a ``force_next`` flag that the
    worker picks up on its next cycle.
    """
    svc = SettingsService(db)
    cfg = svc.get("discovery")
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="поиск историй выключен")
    hashtags = cfg.get("hashtags") or []
    locations = cfg.get("locations") or []
    if not hashtags and not locations:
        raise HTTPException(status_code=400, detail="не заданы хештеги или геолокации")
    cfg["force_next"] = True
    svc.set("discovery", cfg)
    return {
        "ok": True,
        "status": "queued",
        "note": "поиск будет выполнен worker'ом в ближайшем цикле",
        "hashtags": hashtags,
        "locations": locations,
    }