from __future__ import annotations
import json
from sqlalchemy.orm import Session
from ..models import SettingsStore
class SettingsService:
    DEFAULTS={"general":{"language":"en","timezone":"UTC","theme":"dark","autostart":True},"telegram":{"api_id":None,"api_hash":None,"reconnect":True},"monitoring":{"check_interval":30,"realtime":True,"resync":True},"queue":{"max_tasks":500,"parallel":1,"backoff_factor":2.0,"processing_timeout":300,"max_auto_retries":3},"limits":{"views_per_minute":5,"views_per_hour":100,"views_per_day":800,"searches_per_hour":5,"search_results_max":50,"search_delay":300},"view":{"min_delay":20,"max_delay":120,"auto_like":False,"like_emoji":"👍"},"discovery":{"hashtags":[],"locations":[],"enabled":False,"hashtags_enabled":True},"filters":{"include_contacts":False,"include_unknown":True,"include_mutual_contacts":False,"include_non_mutual":True,"include_channels":True,"include_groups":True,"include_bots":True,"include_deleted":False,"include_blocked":False}}
    def __init__(self,db:Session,user_id:int|None=None): self.db,self.user_id=db,user_id
    def _key(self,s): return f"user:{self.user_id}:{s}" if self.user_id is not None else s
    def _merge(self,s,v):
        out=dict(self.DEFAULTS.get(s,{})); out.update(v or {}); return out
    def get(self,s):
        row=self.db.get(SettingsStore,self._key(s))
        # User-scoped settings never fall back to the legacy global value.
        # Legacy settings are intentionally isolated from new users.
        if not row:return dict(self.DEFAULTS.get(s,{}))
        try:return self._merge(s,json.loads(row.value or "{}"))
        except json.JSONDecodeError:return dict(self.DEFAULTS.get(s,{}))
    def get_all(self):return {s:self.get(s) for s in self.DEFAULTS}
    def set(self,s,v):
        key=self._key(s); merged=self._merge(s,v); row=self.db.get(SettingsStore,key)
        if row is None:self.db.add(SettingsStore(key=key,value=json.dumps(merged)))
        else:row.value=json.dumps(merged)
        self.db.commit();return merged
    def set_all(self,values):
        for s,v in values.items():
            if s in self.DEFAULTS:self.set(s,v)
        return self.get_all()
