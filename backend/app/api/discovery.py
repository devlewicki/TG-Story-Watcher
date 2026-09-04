from __future__ import annotations
import json, logging, math, os, urllib.parse, urllib.request
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel as _BM
from sqlalchemy import or_
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import GeoPlace
from ..services.settings_service import SettingsService
from .deps import require_api_token, current_user_id
logger = logging.getLogger("storywatcher.api.discovery")
router = APIRouter(prefix="/discovery", tags=["discovery"], dependencies=[Depends(require_api_token)])
Db = Annotated[Session, Depends(get_db)]


class DiscoveryConfig(_BM):
    """Unified discovery config with all search modes."""
    enabled: bool = False
    # Hashtag search
    hashtags: list[str] = []
    hashtags_enabled: bool = True
    # Place / city search
    locations: list[str] = []
    auto_add_places: bool = True
    # Geo-radius search
    geo_search_enabled: bool = False
    geo_search_lat: float | None = None
    geo_search_lng: float | None = None
    geo_search_radius_km: float = 10.0
    # Scheduling
    search_interval: int = 300
    search_results_max: int = 50


def _defaults(cfg: dict | None) -> dict:
    out = {
        "enabled": False,
        "hashtags": [],
        "hashtags_enabled": True,
        "locations": [],
        "auto_add_places": True,
        "geo_search_enabled": False,
        "geo_search_lat": None,
        "geo_search_lng": None,
        "geo_search_radius_km": 10,
        "search_interval": 300,
        "search_results_max": 50,
    }
    if cfg:
        # Handle legacy nested geo_search object → flatten into top-level keys
        if "geo_search" in cfg and isinstance(cfg["geo_search"], dict):
            gs = cfg["geo_search"]
            # Only migrate from legacy dict if flat keys are genuinely missing
            # (not present or empty string / None).  This prevents a stale
            # empty legacy dict from clobbering valid flat keys.
            if not cfg.get("geo_search_enabled") and gs.get("enabled"):
                cfg["geo_search_enabled"] = True
            if not cfg.get("geo_search_lat") and gs.get("lat") is not None:
                cfg["geo_search_lat"] = gs["lat"]
            if not cfg.get("geo_search_lng") and gs.get("lng") is not None:
                cfg["geo_search_lng"] = gs["lng"]
            if not cfg.get("geo_search_radius_km") and gs.get("radius_km") is not None:
                cfg["geo_search_radius_km"] = gs["radius_km"]
        out.update(cfg)
    # Treat empty-string values as missing (DB stores JSON null as "")
    for k in ("hashtags_enabled", "geo_search_enabled", "geo_search_lat",
              "geo_search_lng", "geo_search_radius_km"):
        if out.get(k) in ("", None) and k in out:
            # Keep None for lat/lng (they can legitimately be None)
            if k not in ("geo_search_lat", "geo_search_lng"):
                out[k] = {"hashtags_enabled": True, "geo_search_enabled": False,
                           "geo_search_radius_km": 10}.get(k, out[k])
    return out


@router.get("/config")
def get_discovery_config(db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    return _defaults(SettingsService(db, user_id).get("discovery"))


@router.post("/config")
def set_discovery_config(
    payload: DiscoveryConfig,
    db: Db,
    user_id: Annotated[int, Depends(current_user_id)],
):
    data = payload.model_dump()
    # Merge with existing config to preserve fields the frontend may not
    # have sent (e.g. hashtags array when only geo fields changed).
    existing = SettingsService(db, user_id).get("discovery") or {}
    merged = {**existing, **data}
    # Also write legacy nested geo_search for scheduler backward-compat
    merged["geo_search"] = {
        "enabled": merged.get("geo_search_enabled", False),
        "lat": merged.get("geo_search_lat"),
        "lng": merged.get("geo_search_lng"),
        "radius_km": merged.get("geo_search_radius_km", 10),
    }
    return {"ok": True, "config": SettingsService(db, user_id).set("discovery", merged)}


# ---------- Places ----------

@router.get("/places/count")
def count_places(db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    return {"count": db.query(GeoPlace).count()}


@router.get("/places")
def list_places(
    db: Db,
    q: str | None = None,
    user_id: Annotated[int, Depends(current_user_id)] = None,
):
    query = db.query(GeoPlace)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(GeoPlace.title.ilike(like), GeoPlace.address.ilike(like), GeoPlace.venue_id.ilike(like))
        )
    return [
        {
            "id": p.id, "venue_id": p.venue_id, "title": p.title,
            "address": p.address, "provider": p.provider,
            "lat": p.lat, "long": p.long,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        for p in query.order_by(GeoPlace.updated_at.desc()).all()
    ]


# ---------- Geocode ----------

@router.get("/geocode")
def geocode(
    db: Db,
    q: str = "",
    user_id: Annotated[int, Depends(current_user_id)] = None,
):
    if len((q or "").strip()) < 2:
        return []
    url = (
        os.environ.get("STORYWATCHER_GEOCODER_URL", "https://nominatim.openstreetmap.org").rstrip("/")
        + "/search?"
        + urllib.parse.urlencode({"q": q.strip(), "format": "jsonv2", "limit": 5})
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "StoryWatcher/1.0"})
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode())
    except Exception:
        return []
    return [
        {
            "name": x.get("name", ""),
            "display_name": x.get("display_name", ""),
            "lat": float(x.get("lat", 0) or 0),
            "lon": float(x.get("lon", 0) or 0),
            "type": x.get("type", ""),
            "category": x.get("category", ""),
        }
        for x in data
    ]


# ---------- Manual search trigger ----------

@router.post("/search")
def run_discovery_search(db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    svc = SettingsService(db, user_id)
    cfg = svc.get("discovery")
    if not cfg.get("enabled"):
        raise HTTPException(400, "discovery is disabled")
    has_hashtags = cfg.get("hashtags") and cfg.get("hashtags_enabled", True)
    has_locations = bool(cfg.get("locations")) or cfg.get("auto_add_places", True)
    has_geo = cfg.get("geo_search_enabled", False) and cfg.get("geo_search_lat") is not None
    if not has_hashtags and not has_locations and not has_geo:
        raise HTTPException(400, "no search modes enabled")
    cfg["force_next"] = True
    svc.set("discovery", cfg)
    return {"ok": True, "status": "queued"}


# ---------- Geo-radius (preview / one-time) ----------

class GeoRadiusRequest(_BM):
    lat: float
    lng: float
    radius_km: float = 10.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@router.post("/geo-radius")
def geo_radius(payload: GeoRadiusRequest, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    lat_margin = payload.radius_km / 111.0 + 0.5
    lng_margin = payload.radius_km / (111.0 * math.cos(math.radians(payload.lat))) + 0.5
    candidates = (
        db.query(GeoPlace)
        .filter(
            GeoPlace.lat.isnot(None), GeoPlace.long.isnot(None),
            GeoPlace.lat >= payload.lat - lat_margin, GeoPlace.lat <= payload.lat + lat_margin,
            GeoPlace.long >= payload.lng - lng_margin, GeoPlace.long <= payload.lng + lng_margin,
        )
        .all()
    )
    results = []
    for p in candidates:
        dist = _haversine_km(payload.lat, payload.lng, p.lat, p.long)
        if dist <= payload.radius_km:
            results.append({
                "id": p.id, "venue_id": p.venue_id, "title": p.title,
                "address": p.address, "lat": p.lat, "long": p.long,
                "distance_km": round(dist, 2),
            })
    results.sort(key=lambda x: x["distance_km"])
    return {"places": results, "count": len(results)}


# ---------- One-time geo-search (adds venues to config + triggers) ----------

@router.post("/geo-search")
def run_geo_search(payload: GeoRadiusRequest, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    radius_result = geo_radius(payload, db, user_id)
    venues = radius_result["places"]
    if not venues:
        raise HTTPException(400, "no collected venues found in this radius")
    svc = SettingsService(db, user_id)
    cfg = svc.get("discovery")
    venue_lines = [f"venue:{v['venue_id']}" for v in venues]
    existing = set(cfg.get("locations", []))
    added = [line for line in venue_lines if line not in existing]
    cfg["locations"] = list(existing | set(venue_lines))
    cfg["force_next"] = True
    cfg["enabled"] = True
    svc.set("discovery", cfg)
    return {
        "ok": True, "status": "queued",
        "venues_found": len(venues), "venues_added": len(added),
        "total_locations": len(cfg["locations"]),
    }
