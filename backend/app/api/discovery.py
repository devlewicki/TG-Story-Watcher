from __future__ import annotations
import json, logging, os, urllib.parse, urllib.request
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel as _BM
from sqlalchemy import or_
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import GeoPlace
from ..services.settings_service import SettingsService
from .deps import require_api_token, current_user_id
logger=logging.getLogger("storywatcher.api.discovery")
router=APIRouter(prefix="/discovery",tags=["discovery"],dependencies=[Depends(require_api_token)])
Db=Annotated[Session,Depends(get_db)]
class DiscoveryConfig(_BM):
 enabled:bool=False; hashtags:list[str]=[]; locations:list[str]=[]; auto_add_places:bool=True; search_interval:int=300; search_results_max:int=50
def _defaults(cfg):
 out={"enabled":False,"hashtags":[],"locations":[],"auto_add_places":True,"search_interval":300,"search_results_max":50}; out.update(cfg or {}); return out
@router.get("/config")
def get_discovery_config(db:Db,user_id:Annotated[int,Depends(current_user_id)]): return _defaults(SettingsService(db,user_id).get("discovery"))
@router.post("/config")
def set_discovery_config(payload:DiscoveryConfig,db:Db,user_id:Annotated[int,Depends(current_user_id)]):
 return {"ok":True,"config":SettingsService(db,user_id).set("discovery",payload.model_dump())}
@router.get("/places/count")
def count_places(db:Db,user_id:Annotated[int,Depends(current_user_id)]): return {"count":db.query(GeoPlace).count()}
@router.get("/places")
def list_places(db:Db,q:str|None=None,user_id:Annotated[int,Depends(current_user_id)]=None):
 query=db.query(GeoPlace)
 if q and q.strip():
  like=f"%{q.strip()}%"; query=query.filter(or_(GeoPlace.title.ilike(like),GeoPlace.address.ilike(like),GeoPlace.venue_id.ilike(like)))
 return [{"id":p.id,"venue_id":p.venue_id,"title":p.title,"address":p.address,"provider":p.provider,"lat":p.lat,"long":p.long,"created_at":p.created_at.isoformat() if p.created_at else None,"updated_at":p.updated_at.isoformat() if p.updated_at else None} for p in query.order_by(GeoPlace.updated_at.desc()).all()]
@router.get("/geocode")
def geocode(db:Db,q:str="",user_id:Annotated[int,Depends(current_user_id)]=None):
 if len((q or "").strip())<2:return []
 url=os.environ.get("STORYWATCHER_GEOCODER_URL","https://nominatim.openstreetmap.org").rstrip("/")+"/search?"+urllib.parse.urlencode({"q":q.strip(),"format":"jsonv2","limit":5})
 try:
  req=urllib.request.Request(url,headers={"User-Agent":"StoryWatcher/1.0"})
  with urllib.request.urlopen(req,timeout=8) as response:data=json.loads(response.read().decode())
 except Exception:return []
 return [{"name":x.get("name", ""),"display_name":x.get("display_name", ""),"lat":float(x.get("lat",0) or 0),"lon":float(x.get("lon",0) or 0),"type":x.get("type",""),"category":x.get("category","")} for x in data]
@router.post("/search")
def run_discovery_search(db:Db,user_id:Annotated[int,Depends(current_user_id)]):
 svc=SettingsService(db,user_id); cfg=svc.get("discovery")
 if not cfg.get("enabled"):raise HTTPException(400,"поиск историй выключен")
 if not cfg.get("hashtags") and not cfg.get("locations"):raise HTTPException(400,"не заданы хештеги или геолокации")
 cfg["force_next"]=True; svc.set("discovery",cfg); return {"ok":True,"status":"queued"}
