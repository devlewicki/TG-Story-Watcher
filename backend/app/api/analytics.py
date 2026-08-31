from __future__ import annotations
from datetime import datetime,timedelta,timezone
from typing import Annotated
from fastapi import APIRouter,Depends,HTTPException,Query
from sqlalchemy.orm import Session
from ..db import SessionLocal,get_db
from ..models import Story,StoryReactionStat,StoryStatsSnapshot,StoryViewer,TelegramAccount
from .deps import require_api_token,current_user_id
router=APIRouter(prefix="/analytics",tags=["analytics"],dependencies=[Depends(require_api_token)])
Db=Annotated[Session,Depends(get_db)]
def _story(db,story_id,user_id):
 s=db.query(Story).join(TelegramAccount).filter(Story.id==story_id,Story.source=="analytics",TelegramAccount.user_id==user_id).first()
 if not s:raise HTTPException(404,"analytics story not found")
 return s
def _summary(db,s):
 snap=db.query(StoryStatsSnapshot).filter_by(story_id=s.id).order_by(StoryStatsSnapshot.collected_at.desc()).first(); rs=db.query(StoryReactionStat).filter_by(story_id=s.id).all(); v=snap.views_count if snap else None; r=snap.reactions_count if snap else None; f=snap.forwards_count if snap else None
 return {"story_id":s.id,"telegram_story_id":s.telegram_story_id,"views":v,"reactions":r,"forwards":f,"known_viewers":db.query(StoryViewer).filter_by(story_id=s.id).count(),"er":((r or 0)+(f or 0))/v*100 if v else None,"reaction_breakdown":{x.reaction:x.count for x in rs},"published_at":s.published_at}
@router.get("/stories")
def stories(db:Db,user_id:Annotated[int,Depends(current_user_id)],account_id:int|None=None,limit:int=Query(100,le=500),offset:int=0):
 q=db.query(Story).join(TelegramAccount).filter(Story.source=="analytics",TelegramAccount.user_id==user_id)
 if account_id:q=q.filter(Story.account_id==account_id)
 return [_summary(db,s) for s in q.order_by(Story.published_at.desc().nullslast(),Story.id.desc()).offset(offset).limit(limit)]
@router.get("/stories/{story_id}")
def one(story_id:int,db:Db,user_id:Annotated[int,Depends(current_user_id)]):return _summary(db,_story(db,story_id,user_id))
@router.get("/stories/{story_id}/views")
def views(story_id:int,db:Db,user_id:Annotated[int,Depends(current_user_id)],since_hours:int=Query(168,ge=1,le=8760)):
 s=_story(db,story_id,user_id); rows=db.query(StoryStatsSnapshot).filter(StoryStatsSnapshot.story_id==s.id,StoryStatsSnapshot.collected_at>=datetime.now(timezone.utc)-timedelta(hours=since_hours)).order_by(StoryStatsSnapshot.collected_at).all(); return [{"collected_at":x.collected_at,"views":x.views_count,"reactions":x.reactions_count,"forwards":x.forwards_count} for x in rows]
@router.get("/stories/{story_id}/viewers")
def viewers(story_id:int,db:Db,user_id:Annotated[int,Depends(current_user_id)],search:str|None=None,reactions_only:bool=False,limit:int=Query(100,le=500),offset:int=0):
 s=_story(db,story_id,user_id); q=db.query(StoryViewer).filter_by(story_id=s.id)
 if reactions_only:q=q.filter(StoryViewer.reaction.isnot(None))
 if search:
  x=f"%{search}%"; q=q.filter((StoryViewer.username.ilike(x))|(StoryViewer.first_name.ilike(x))|(StoryViewer.last_name.ilike(x)))
 return [{"telegram_user_id":x.telegram_user_id,"username":x.username,"first_name":x.first_name,"last_name":x.last_name,"viewed_at":x.viewed_at,"reaction":x.reaction} for x in q.order_by(StoryViewer.viewed_at.desc().nullslast()).offset(offset).limit(limit)]
@router.get("/stories/{story_id}/reactions")
def reactions(story_id:int,db:Db,user_id:Annotated[int,Depends(current_user_id)]):
 s=_story(db,story_id,user_id); return [{"reaction":x.reaction,"count":x.count} for x in db.query(StoryReactionStat).filter_by(story_id=s.id).order_by(StoryReactionStat.count.desc())]
@router.get("/recent-events")
def events(db:Db,user_id:Annotated[int,Depends(current_user_id)],limit:int=Query(30,le=100)):
 q=db.query(StoryViewer,Story).join(Story,Story.id==StoryViewer.story_id).join(TelegramAccount,Story.account_id==TelegramAccount.id).filter(Story.source=="analytics",TelegramAccount.user_id==user_id,StoryViewer.viewed_at.isnot(None)).order_by(StoryViewer.viewed_at.desc()).limit(limit)
 return [{"type":"reaction" if v.reaction else "view","story_id":s.id,"telegram_story_id":s.telegram_story_id,"user_id":v.telegram_user_id,"username":v.username,"first_name":v.first_name,"last_name":v.last_name,"reaction":v.reaction,"occurred_at":v.viewed_at} for v,s in q.all()]
@router.get("/overview")
def overview(db:Db,user_id:Annotated[int,Depends(current_user_id)],days:int=Query(30,ge=1,le=3650)):
 since=datetime.now(timezone.utc)-timedelta(days=days); q=db.query(Story).join(TelegramAccount).filter(Story.source=="analytics",TelegramAccount.user_id==user_id).filter((Story.published_at>=since)|(Story.published_at.is_(None))); a=[_summary(db,s) for s in q.all()]; return {"stories":len(a),"views":sum(x["views"] or 0 for x in a),"known_viewers":sum(x["known_viewers"] for x in a),"reactions":sum(x["reactions"] or 0 for x in a),"forwards":sum(x["forwards"] or 0 for x in a),"average_views":sum(x["views"] or 0 for x in a)/len(a) if a else 0,"average_er":sum(x["er"] or 0 for x in a)/len(a) if a else 0,"top_stories":sorted(a,key=lambda x:x["views"] or 0,reverse=True)[:10]}
@router.post("/sync")
async def sync(account_id:int,db:Db,user_id:Annotated[int,Depends(current_user_id)]):
 if not db.query(TelegramAccount).filter_by(id=account_id,user_id=user_id).first():raise HTTPException(404,"account not found")
 # Analytics sync is handled by the worker process which owns the Telegram
 # client.  Opening a second client from the backend process would conflict
 # on the shared SQLite session file ("database is locked").  The worker
 # runs analytics every 30s — this endpoint just confirms the account exists
 # and the worker will pick it up on the next cycle.
 return {"ok":True,"status":"queued","account_id":account_id}
