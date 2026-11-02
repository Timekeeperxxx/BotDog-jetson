"""Map access snapshots and authorization using the robot's map position."""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any
from sqlalchemy import select
from .models import FaceIdentity, MapAccessZone
from .map_access_geometry import locate_robot_regions
from .logging_config import get_logger

access_logger = get_logger("人员区域权限")


POSE_SAMPLE_TOLERANCE_SECONDS = .35
MAX_FRAME_AGE_SECONDS = 1.
COORDINATE_METHOD = 'robot_position'


class MapAccessService:
    def __init__(self):
        self.lock = asyncio.Lock()
        self._initialized = False
        self._zones: tuple[dict,...] = ()
        self._identity_levels: dict[int,int | None] = {}
        self._identity_versions: dict[int,str] = {}
        self.revision = 0
        self.last_decisions: list[dict] = []
        self._last_frame_at: float | None = None

    async def ensure_initialized(self):
        if self._initialized: return
        async with self.lock:
            if not self._initialized:
                from .database import get_session_factory
                async with get_session_factory()() as db:
                    await self.reload(db)

    async def reload(self, db):
        zones = (await db.execute(select(MapAccessZone).order_by(MapAccessZone.id))).scalars().all()
        identities = (await db.execute(select(FaceIdentity).where(FaceIdentity.enabled == 1))).scalars().all()
        self._zones = tuple(self.zone_dict(z) for z in zones)
        self._identity_levels = {p.id:p.access_level for p in identities}
        self._identity_versions = {p.id:p.updated_at for p in identities}
        self.revision += 1
        self._initialized = True
        self.last_decisions = []
        access_logger.info("人员权限快照已同步：revision={} identity_levels={}", self.revision, self._identity_levels)

    @staticmethod
    def zone_dict(zone):
        return {key:getattr(zone,key) for key in ('id','scene_id','name','kind','vertices','plane','access_level','enabled','boundary_margin_m','updated_at')}

    def status(self):
        age = None if self._last_frame_at is None else max(0.,time.monotonic()-self._last_frame_at)
        decisions = self.last_decisions
        if age is not None and age > 2:
            decisions = [{**d,'status':'indeterminate','reason':'observations_stale'} for d in decisions]
        return {'calibration_required':False,'zone_count':len(self._zones),
                'enabled_zone_count':sum(bool(z['enabled']) for z in self._zones),
                'revision':self.revision,'last_decisions':decisions,'last_frame_age_seconds':age,
                'method':'robot_position_in_map_region','authorization_method':'hierarchical_access_level',
                'level_rule':'person_level <= region_level',
                'detail':'按机器人所在区域及人员权限级别判断，1级最高，无需相机标定'}

    def decide(self, person: Any, *, scene_id: str | None, robot_pose=None, error: str | None=None):
        zones = [z for z in self._zones if z['enabled'] and z['scene_id']==scene_id]
        if not zones: return None
        identity = getattr(person,'identity_id',None)
        recognized = getattr(person,'face_status',None)=='recognized' and identity in self._identity_levels
        level = self._identity_levels.get(identity) if recognized else None
        context = {'identity_access_level':level,'authorization_method':'hierarchical_access_level',
                   'scene_id':scene_id,'identity_id':identity if recognized else None,
                   'display_name':getattr(person,'display_name',None) if recognized else None,
                   'track_id':int(getattr(person,'track_id',-1)),
                   'face_status':getattr(person,'face_status',None),'revision':self.revision,
                   'coordinate_method':COORDINATE_METHOD, 'observed_at_monotonic':time.monotonic()}
        if error or robot_pose is None:
            return {**context,'status':'indeterminate','reason':error or 'robot_pose_unavailable','zones':[]}
        location = locate_robot_regions(robot_pose,zones)
        if location['status']=='indeterminate': return {**context,**location}
        if location['status']=='outside':
            return {**context,**location,'status':'allowed' if recognized else 'unidentified',
                    'reason':'outside_controlled_regions' if recognized else 'identity_unconfirmed'}
        if any(z.get('access_level') not in (1,2,3) for z in location['zones']):
            return {**context,**location,'status':'indeterminate','reason':'region_level_unset'}
        required = min(z['access_level'] for z in location['zones'])
        denied = [z for z in location['zones'] if not recognized or level not in (1,2,3) or level > z['access_level']]
        return {**context,**location,'status':'denied' if denied else 'allowed',
                'required_access_level':required,'denied_zone_ids':[z['id'] for z in denied],
                'reason':'identity_unconfirmed' if not recognized else 'person_level_unset' if level not in (1,2,3)
                         else 'insufficient_access_level' if denied else 'access_level_granted'}


    async def annotate(self, persons, *, frame_monotonic: float):
        self._last_frame_at = frame_monotonic
        if not self._initialized:
            for person in persons: person.map_access = None
            return
        from .services_nav_localization_scene import load_current_scene
        from .services_nav_state import get_nav_state, get_robot_pose_at
        try: scene = load_current_scene(strict=False).get('scene_id')
        except (OSError, ValueError): scene = None
        if scene is None and any(z['enabled'] for z in self._zones):
            self.last_decisions=[]
            for person in persons:
                person.map_access={'status':'indeterminate','reason':'map_scene_unavailable','zones':[],
                                   'coordinate_method':COORDINATE_METHOD}
                self.last_decisions.append(person.map_access)
            return
        relevant = any(z['enabled'] and z['scene_id']==scene for z in self._zones)
        if not relevant:
            for p in persons: p.map_access = None
            self.last_decisions = []
            return
        error = None
        pose = None
        if (get_nav_state().get('localization_status') or {}).get('status') != 'ok':
            error = 'localization_unavailable'
        elif not math.isfinite(frame_monotonic) or not -POSE_SAMPLE_TOLERANCE_SECONDS <= time.monotonic()-frame_monotonic <= MAX_FRAME_AGE_SECONDS:
            error = 'video_frame_stale'
        else:
            pose = get_robot_pose_at(frame_monotonic,POSE_SAMPLE_TOLERANCE_SECONDS)
            if pose is None: error = 'synchronized_robot_pose_unavailable'
        decisions=[]
        for person in persons:
            person.map_access=self.decide(person,scene_id=scene,robot_pose=pose,error=error)
            if person.map_access:
                person.map_access['frame_received_at_monotonic'] = frame_monotonic
                identity = person.map_access.get('identity_id')
                person.map_access['permission_version'] = f"person:{identity}:{self._identity_versions.get(identity,'')}:{person.map_access.get('identity_access_level')}|" + '|'.join(f"{z['id']}:{z.get('updated_at','')}:{z.get('access_level')}" for z in self._zones if z['id'] in person.map_access.get('denied_zone_ids',[]))
                decisions.append(person.map_access)
        self.last_decisions=decisions


_service = MapAccessService()


def get_map_access_service():
    return _service
