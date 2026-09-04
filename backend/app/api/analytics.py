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
def overview(db:Db,user_id:Annotated[int,Depends(current_user_id)],days:int=Query(30,ge=1,le=3650),period:str|None=Query(None),tz_offset:float=Query(0)):
 """Return overview stats for the selected period.

 period: 'today', '7d', '30d', '90d', 'all'
 - Stories count: by published_at within period
 - Views/Reactions/Forwards: delta from snapshots within period
 - Viewers: unique viewers with viewed_at within period
 - All time: cumulative values
 """
 from collections import defaultdict
 from zoneinfo import ZoneInfo

 user_tz = timezone(timedelta(hours=tz_offset))
 now_local = datetime.now(timezone.utc).astimezone(user_tz)
 today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

 # Determine period window
 if period == "today":
   period_start_local = today_start_local
   period_days = 1
 elif period == "7d":
   period_start_local = today_start_local - timedelta(days=6)
   period_days = 7
 elif period == "30d":
   period_start_local = today_start_local - timedelta(days=29)
   period_days = 30
 elif period == "90d":
   period_start_local = today_start_local - timedelta(days=89)
   period_days = 90
 else: # 'all' or None
   period_start_local = None
   period_days = days

 if period_start_local:
   period_start_utc = period_start_local.astimezone(timezone.utc)
 else:
   period_start_utc = datetime.now(timezone.utc) - timedelta(days=days)

 # Get all story IDs for this user
 story_ids = [
   s[0] for s in db.query(Story.id)
   .join(TelegramAccount)
   .filter(Story.source == "analytics", TelegramAccount.user_id == user_id)
   .all()
 ]

 # Stories count: by published_at within period
 if period_start_local and period not in (None, "all"):
   stories_count = (
     db.query(Story)
     .join(TelegramAccount)
     .filter(Story.source == "analytics", TelegramAccount.user_id == user_id)
     .filter(Story.published_at >= period_start_utc)
     .count()
   )
 else:
   stories_count = len(story_ids)

 # For Views/Reactions/Forwards
 total_views = 0
 total_reactions = 0
 total_forwards = 0

 if story_ids:
   is_all = period in (None, "all")

   if is_all:
     # All time: use latest snapshot per story (cumulative values)
     from sqlalchemy import func as sa_func
     latest_ids = (
       db.query(sa_func.max(StoryStatsSnapshot.id))
       .filter(StoryStatsSnapshot.story_id.in_(story_ids))
       .group_by(StoryStatsSnapshot.story_id)
       .all()
     )
     snap_ids = [row[0] for row in latest_ids if row[0]]
     if snap_ids:
       latest_snaps = db.query(StoryStatsSnapshot).filter(StoryStatsSnapshot.id.in_(snap_ids)).all()
       for snap in latest_snaps:
         total_views += snap.views_count or 0
         total_reactions += snap.reactions_count or 0
         total_forwards += snap.forwards_count or 0
   else:
     # Period mode: use SQL-level aggregation for performance
     from sqlalchemy import text
     story_id_list = ",".join(str(i) for i in story_ids)
     query = text(f"""
       WITH daily_last AS (
         SELECT DISTINCT ON (story_id, day)
           story_id, day, views_count, reactions_count, forwards_count
         FROM (
           SELECT
             story_id,
             DATE(collected_at AT TIME ZONE 'UTC' AT TIME ZONE :tz) AS day,
             views_count, reactions_count, forwards_count,
             ROW_NUMBER() OVER (
               PARTITION BY story_id, DATE(collected_at AT TIME ZONE 'UTC' AT TIME ZONE :tz)
               ORDER BY collected_at DESC
             ) AS rn
           FROM story_stats_snapshots
           WHERE story_id IN ({story_id_list})
           AND collected_at >= :start_utc - INTERVAL '1 day'
         ) sub WHERE rn = 1
       ),
       with_lag AS (
         SELECT
           story_id, day, views_count, reactions_count, forwards_count,
           LAG(views_count) OVER (PARTITION BY story_id ORDER BY day) AS prev_views,
           LAG(reactions_count) OVER (PARTITION BY story_id ORDER BY day) AS prev_reactions,
           LAG(forwards_count) OVER (PARTITION BY story_id ORDER BY day) AS prev_forwards
         FROM daily_last
       )
       SELECT
         SUM(GREATEST(0, views_count - COALESCE(prev_views, views_count)))::int AS v,
         SUM(GREATEST(0, reactions_count - COALESCE(prev_reactions, reactions_count)))::int AS r,
         SUM(GREATEST(0, forwards_count - COALESCE(prev_forwards, forwards_count)))::int AS f
       FROM with_lag
       WHERE day >= :start_date;
     """)
     row = db.execute(query, {
       "tz": f"+{int(tz_offset)}:00" if tz_offset >= 0 else f"{int(tz_offset)}:00",
       "start_utc": period_start_utc,
       "start_date": period_start_local.date(),
     }).fetchone()
     if row:
       total_views = row[0] or 0
       total_reactions = row[1] or 0
       total_forwards = row[2] or 0

   # Viewers: unique viewers with viewed_at within period
   if period_start_local and period not in (None, "all"):
     known_viewers = (
       db.query(StoryViewer)
       .join(Story)
       .join(TelegramAccount)
       .filter(
         Story.source == "analytics",
         TelegramAccount.user_id == user_id,
         StoryViewer.viewed_at >= period_start_utc,
       )
       .count()
     )
   else:
     known_viewers = sum(_summary(db, db.get(Story, sid))["known_viewers"] for sid in story_ids)
 else:
   known_viewers = 0

 # Top stories: sort by current views (always show all)
 a = [_summary(db, db.get(Story, sid)) for sid in story_ids]
 avg_er = ((total_reactions + total_forwards) / total_views * 100) if total_views > 0 else 0

 return {
   "stories": stories_count,
   "views": total_views,
   "known_viewers": known_viewers,
   "reactions": total_reactions,
   "forwards": total_forwards,
   "average_er": avg_er,
   "top_stories": sorted(a, key=lambda x: x["views"] or 0, reverse=True)[:10],
 }
@router.post("/sync")
async def sync(account_id:int,db:Db,user_id:Annotated[int,Depends(current_user_id)]):
 if not db.query(TelegramAccount).filter_by(id=account_id,user_id=user_id).first():raise HTTPException(404,"account not found")
 # Analytics sync is handled by the worker process which owns the Telegram
 # client.  Opening a second client from the backend process would conflict
 # on the shared SQLite session file ("database is locked").  The worker
 # runs analytics every 30s — this endpoint just confirms the account exists
 # and the worker will pick it up on the next cycle.
 return {"ok":True,"status":"queued","account_id":account_id}


@router.get("/daily")
def daily_analytics(db:Db,user_id:Annotated[int,Depends(current_user_id)],period:str=Query("7d"),tz_offset:float=Query(0)):
 """Return daily new views and reactions aggregated across all stories.

 Uses SQL-level aggregation for performance (no Python snapshot loading).
 period: 'today', '3d', '7d', 'month'
 tz_offset: hours offset from UTC for calendar day boundaries
 """
 from sqlalchemy import text

 # Determine time window in user's timezone
 user_tz = timezone(timedelta(hours=tz_offset))
 now_local = datetime.now(timezone.utc).astimezone(user_tz)
 today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

 if period == "today":
   start_local = today_start_local
 elif period == "3d":
   start_local = today_start_local - timedelta(days=2)
 elif period == "7d":
   start_local = today_start_local - timedelta(days=6)
 elif period == "month":
   start_local = today_start_local.replace(day=1)
 else:
   start_local = today_start_local - timedelta(days=6)

 start_utc = start_local.astimezone(timezone.utc)

 # Get all story IDs for this user's accounts
 story_ids = [
   s[0] for s in db.query(Story.id)
   .join(TelegramAccount)
   .filter(Story.source == "analytics", TelegramAccount.user_id == user_id)
   .all()
 ]
 if not story_ids:
   return {"period": period, "total_views": 0, "total_reactions": 0, "data": []}

 # SQL-level aggregation: get last snapshot per story per day, compute deltas
 # This avoids loading 100K+ snapshots into Python.
 story_id_list = ",".join(str(i) for i in story_ids)

 # Step 1: Get the last snapshot per story per calendar day (in user tz)
 # Step 2: Use LAG() to get previous day's values per story
 # Step 3: Sum deltas across all stories per day
 # Step 4: Handle negative deltas (floor to 0)
 query = text(f"""
   WITH daily_last AS (
     SELECT DISTINCT ON (story_id, day)
       story_id,
       day,
       views_count,
       reactions_count
     FROM (
       SELECT
         story_id,
         DATE(collected_at AT TIME ZONE 'UTC' AT TIME ZONE :tz) AS day,
         views_count,
         reactions_count,
         ROW_NUMBER() OVER (
           PARTITION BY story_id, DATE(collected_at AT TIME ZONE 'UTC' AT TIME ZONE :tz)
           ORDER BY collected_at DESC
         ) AS rn
       FROM story_stats_snapshots
       WHERE story_id IN ({story_id_list})
       AND collected_at >= :start_utc - INTERVAL '1 day'
     ) sub
     WHERE rn = 1
   ),
   with_lag AS (
     SELECT
       story_id,
       day,
       views_count,
       reactions_count,
       LAG(views_count) OVER (PARTITION BY story_id ORDER BY day) AS prev_views,
       LAG(reactions_count) OVER (PARTITION BY story_id ORDER BY day) AS prev_reactions
     FROM daily_last
   )
   SELECT
     day::text,
     SUM(GREATEST(0, views_count - COALESCE(prev_views, views_count)))::int AS delta_views,
     SUM(GREATEST(0, reactions_count - COALESCE(prev_reactions, reactions_count)))::int AS delta_reactions
   FROM with_lag
   WHERE day >= :start_date
   GROUP BY day
   ORDER BY day;
 """)

 rows = db.execute(query, {
   "tz": f"+{int(tz_offset)}:00" if tz_offset >= 0 else f"{int(tz_offset)}:00",
   "start_utc": start_utc,
   "start_date": start_local.date(),
 }).fetchall()

 # Build response with all calendar days in range
 data_map = {str(row[0]): (row[1], row[2]) for row in rows}
 result = []
 total_v = 0
 total_r = 0
 current = start_local.replace(hour=0, minute=0, second=0, microsecond=0)
 while current.date() <= now_local.date():
   day_key = current.strftime("%Y-%m-%d")
   v, r = data_map.get(day_key, (0, 0))
   total_v += v
   total_r += r
   result.append({"date": day_key, "views": v, "reactions": r})
   current += timedelta(days=1)

 return {"period": period, "total_views": total_v, "total_reactions": total_r, "data": result}
