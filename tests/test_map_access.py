"""Software-only map authorization tests; synthetic coordinates, no camera or robot."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, func, text, inspect
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend import database, alert_service, services_map_access
from backend.api.routes import map_access as routes, face_identities as face_routes
from backend.services_face_identities import FaceIdentityService
from backend.auth.dependencies import require_admin, require_viewer, get_current_user
from backend.auth.schemas import AuthUserInternal
from backend.database import Base
from backend.map_access_geometry import validate_polygon
from backend.models import FaceIdentity, MapAccessZone, MapAccessGrant, AnomalyEvidence
from backend.services_map_access import MapAccessService
from backend.stranger_policy import is_authorized_person
from backend.person_alert_confirmation import PersonAlertConfirmation
from backend.workers_ai_processing import AIWorkerProcessingMixin


def polygon(x=0):
    return [{'x':x,'y':0,'z':0},{'x':x+4,'y':0,'z':0},{'x':x+4,'y':4,'z':0},{'x':x,'y':4,'z':0}]


def robot_pose(x=2,y=2,z=0):
    return {'x':x,'y':y,'z':z,'frame_id':'map','source_frame':'base_footprint',
            'timestamp':123.,'source':'test-map-localization'}


def person(identity=1,track=7):
    return SimpleNamespace(label='person',track_id=track,identity_id=identity,face_status='recognized' if identity else 'unknown',display_name='测试身份',confidence=.9,bbox=(100,50,200,300),map_access=None)


def make_service():
    s=MapAccessService();s._identity_levels={1:1,2:2,3:3,4:None};s._initialized=True;s.revision=1
    s._zones=tuple({'id':i,'name':f'区域{i}','scene_id':'Scene01_Test','enabled':1,'vertices':validate_polygon(polygon(x))[0],'plane':[0,0,0],'access_level':i,'boundary_margin_m':.1} for i,x in [(1,0),(2,5),(3,10)])
    s._identity_versions={i:"software-test" for i in s._identity_levels}
    return s


def decision(s,p,x=2,scene='Scene01_Test'):
    return s.decide(p,scene_id=scene,robot_pose=robot_pose(x))


@pytest.mark.parametrize('identity,region_level',[(i,z) for i in (1,2,3) for z in (1,2,3)])
def test_complete_person_level_and_region_level_matrix(identity,region_level):
    s=make_service();p=person(identity);p.map_access=decision(s,p,x=2+5*(region_level-1))
    expected='allowed' if identity<=region_level else 'denied'
    assert p.map_access['status']==expected
    assert is_authorized_person(p)==(expected=='allowed')
    assert p.map_access['identity_access_level']==identity
    assert p.map_access['required_access_level']==region_level


@pytest.mark.parametrize('identity,reason',[(4,'person_level_unset'),(None,'identity_unconfirmed')])
def test_unassigned_or_unknown_person_is_not_granted_access(identity,reason):
    d=decision(make_service(),person(identity),x=12)
    assert d['status']=='denied' and d['reason']==reason


def test_scene_isolation_disabled_identity_and_strictest_overlap_without_camera_calibration():
    s=make_service();p=person(2)
    assert not hasattr(s,'_calibration')
    assert s.status()['calibration_required'] is False
    assert decision(s,p,scene='Scene02_Other') is None
    s._identity_levels={};assert decision(s,p)['status']=='denied'
    s._identity_levels={2:2}
    s._zones=(*s._zones,{**s._zones[1],'id':4,'access_level':1,'name':'严格重叠区'})
    d=decision(s,p,7);assert d['status']=='denied' and d['denied_zone_ids']==[4] and d['required_access_level']==1
    s._identity_levels={2:1}
    assert decision(s,p,7)['status']=='allowed'
    s._zones=({**s._zones[0],'access_level':None},)
    assert decision(s,p)['reason']=='region_level_unset'


@pytest.mark.parametrize('pose,reason',[
    (robot_pose(.05),'region_boundary'),
    (None,'robot_pose_unavailable'),
    ({**robot_pose(),'frame_id':'odom'},'robot_pose_frame_mismatch'),
    ({**robot_pose(),'x':float('nan')},'invalid_robot_pose'),
    ({**robot_pose(),'z':None},'invalid_robot_pose'),
])
def test_uncertain_robot_positions_never_allow(pose,reason):
    s=make_service();d=s.decide(person(),scene_id='Scene01_Test',robot_pose=pose)
    assert d['status']=='indeterminate' and d['reason']==reason


@pytest.mark.parametrize('identity,expected',[(1,'allowed'),(None,'unidentified')])
def test_robot_outside_controlled_regions(identity,expected):
    d=decision(make_service(),person(identity),x=20)
    assert d['status']==expected and d['zones']==[]
    assert d['robot_map_position']==[20.,2.,0.]


@pytest.mark.parametrize('vertices',[
    [{'x':0,'y':0,'z':0},{'x':1,'y':1,'z':0},{'x':2,'y':2,'z':0}],
    [{'x':0,'y':0,'z':0},{'x':3,'y':3,'z':0},{'x':0,'y':3,'z':0},{'x':3,'y':0,'z':0}],
    [{'x':0,'y':0,'z':0},{'x':4,'y':0,'z':0},{'x':4,'y':4,'z':0},{'x':0,'y':0,'z':0}],
])
def test_invalid_region_geometry_rejected(vertices):
    with pytest.raises(ValueError):validate_polygon(vertices)


def test_horizontal_region_membership_does_not_require_flat_ground():
    vertices=polygon();vertices[2]['z']=2
    points,plane=validate_polygon(vertices)
    s=make_service();s._zones=({**s._zones[0],'vertices':points,'plane':plane},)
    d=s.decide(person(),scene_id='Scene01_Test',robot_pose=robot_pose(z=.8))
    assert d['status']=='allowed'
    assert d['robot_map_position']==[2.,2.,.8]


def test_allowed_to_denied_and_cross_region_restart_confirmation():
    s=make_service();p=person(3);engine=PersonAlertConfirmation()
    def update(frame,x):
        p.map_access=decision(s,p,x)
        return engine.update([p],frame=frame,required_hits=2,pose_batch=0,fresh_pose_ids=set())
    assert update(1,12)==set()
    assert update(2,2)==set()
    assert update(3,2)=={7}
    p.map_access={'status':'indeterminate','reason':'stale'}
    assert engine.update([p],frame=4,required_hits=2,pose_batch=0,fresh_pose_ids=set())==set()


@pytest.mark.asyncio
async def test_annotation_uses_robot_region_for_each_person_without_feet_or_gimbal(monkeypatch):
    s=make_service()
    p=person(2);p.bbox=(300,100,340,360)
    q=person(3,track=8);q.bbox=None
    clock=[100.]
    monkeypatch.setattr(services_map_access.time,'monotonic',lambda:clock[0])
    scene={'scene_id':'Scene01_Test'}
    monkeypatch.setattr('backend.services_nav_localization_scene.load_current_scene',lambda **_:scene)
    monkeypatch.setattr('backend.services_nav_state.get_nav_state',lambda:{'localization_status':{'status':'ok'}})
    pose=robot_pose(7)
    monkeypatch.setattr('backend.services_nav_state.get_robot_pose_at',lambda *_:pose)
    def no_gimbal():raise AssertionError('Robot-region access must not depend on the gimbal')
    monkeypatch.setattr('backend.z2mini_gimbal.get_z2mini_gimbal',no_gimbal)
    await s.annotate([p,q],frame_monotonic=100.)
    assert p.map_access['status']=='allowed' and q.map_access['status']=='denied'
    assert p.map_access['robot_map_position']==q.map_access['robot_map_position']==[7.,2.,0.]
    assert p.map_access['coordinate_method']=='robot_position'
    pose['x']=2
    await s.annotate([p,q],frame_monotonic=100.)
    assert p.map_access['status']=='denied' and q.map_access['status']=='denied'
    assert p.map_access['denied_zone_ids']==[1]
    scene['scene_id']='Scene02_Other'
    await s.annotate([p,q],frame_monotonic=100.)
    assert p.map_access is None and q.map_access is None
    scene.clear()
    await s.annotate([p],frame_monotonic=100.)
    assert p.map_access['reason']=='map_scene_unavailable'
    clock[0]=104
    assert s.status()['last_decisions'][0]['reason']=='observations_stale'


@pytest.mark.asyncio
@pytest.mark.parametrize('localization,pose,frame,reason',[
    ('initializing',robot_pose(),100.,'localization_unavailable'),
    ('ok',None,100.,'synchronized_robot_pose_unavailable'),
    ('ok',robot_pose(),98.,'video_frame_stale'),
    ('ok',robot_pose(),102.,'video_frame_stale'),
    ('ok',{**robot_pose(),'frame_id':'odom'},100.,'robot_pose_frame_mismatch'),
])
async def test_annotation_rejects_unavailable_or_stale_robot_location(monkeypatch,localization,pose,frame,reason):
    s=make_service();p=person()
    monkeypatch.setattr(services_map_access.time,'monotonic',lambda:100.)
    monkeypatch.setattr('backend.services_nav_localization_scene.load_current_scene',lambda **_:{'scene_id':'Scene01_Test'})
    monkeypatch.setattr('backend.services_nav_state.get_nav_state',lambda:{'localization_status':{'status':localization}})
    monkeypatch.setattr('backend.services_nav_state.get_robot_pose_at',lambda *_:pose)
    await s.annotate([p],frame_monotonic=frame)
    assert p.map_access['status']=='indeterminate' and p.map_access['reason']==reason
    assert not is_authorized_person(p)


@pytest.fixture
async def harness(tmp_path,monkeypatch):
    engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "access.db"}')
    async with engine.begin() as connection:await connection.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    service=MapAccessService()
    monkeypatch.setattr(services_map_access,'_service',service)
    monkeypatch.setattr(database,'get_session_factory',lambda:factory)
    root=tmp_path/'maps';(root/'Scene01_Test').mkdir(parents=True);(root/'Scene01_Test'/'ground.pcd').write_text('test-fixture')
    monkeypatch.setattr('backend.services_pcd_maps.settings.SCENE_MAP_ROOT',str(root))
    async with factory() as db:
        db.add_all([FaceIdentity(id=1,display_name='甲',access_level=1),FaceIdentity(id=2,display_name='乙',access_level=3)]);await db.commit();await service.reload(db)
    async def db_override():
        async with factory() as db:yield db
    app=FastAPI();app.include_router(routes.router);app.include_router(face_routes.router);app.dependency_overrides[database.get_db]=db_override
    face_service=FaceIdentityService()
    monkeypatch.setattr(face_routes,'get_face_identity_service',lambda:face_service)
    admin=AuthUserInternal(id=1,username='test-admin',role='admin',token_version=0)
    app.dependency_overrides[require_admin]=lambda:admin;app.dependency_overrides[require_viewer]=lambda:admin
    yield app,factory,service,tmp_path
    await engine.dispose()


@pytest.mark.asyncio
async def test_region_and_face_level_changes_apply_immediately_and_survive_restart(harness):
    app,factory,service,_=harness
    payload=dict(scene_id='Scene01_Test',name='区域1',access_level=1,vertices=polygon())
    async with AsyncClient(app=app,base_url='http://test') as client:
        assert (await client.post('/api/v1/map-access/zones',json={**payload,'scene_id':'../escape'})).status_code==422
        for invalid in (0,4,True,'1'):
            assert (await client.post('/api/v1/map-access/zones',json={**payload,'access_level':invalid})).status_code==422
            assert (await client.patch('/api/v1/face-identities/1',json={'access_level':invalid})).status_code==422
        created=await client.post('/api/v1/map-access/zones',json=payload);assert created.status_code==201
        zone_id=created.json()['id']
        assert decision(service,person())['status']=='allowed'
        assert decision(service,person(2))['status']=='denied'
        assert (await client.put(f'/api/v1/map-access/zones/{zone_id}',json={**payload,'access_level':3})).status_code==200
        assert decision(service,person(2))['status']=='allowed'
        assert (await client.put(f'/api/v1/map-access/zones/{zone_id}',json=payload)).status_code==200
        assert (await client.patch('/api/v1/face-identities/1',json={'access_level':3})).status_code==200
        assert decision(service,person())['status']=='denied'
        assert (await client.patch('/api/v1/face-identities/1',json={'access_level':None})).status_code==200
        assert decision(service,person())['reason']=='person_level_unset'
        status=(await client.get('/api/v1/map-access/status')).json()
        assert status['calibration_required'] is False
        assert status['authorization_method']=='hierarchical_access_level'
        reloaded=MapAccessService()
        async with factory() as db:await reloaded.reload(db)
        assert decision(reloaded,person())['status']=='denied'
        assert (await client.delete(f'/api/v1/map-access/zones/{zone_id}')).status_code==200
        assert (await client.get('/api/v1/map-access/zones')).json()==[]


@pytest.mark.asyncio
async def test_management_requires_authentication(harness,monkeypatch):
    app,_,_,_=harness
    monkeypatch.setattr('backend.auth.dependencies.settings.AUTH_ENABLED',True)
    app.dependency_overrides.pop(require_admin)
    app.dependency_overrides.pop(require_viewer)
    async with AsyncClient(app=app,base_url='http://test') as client:
        assert (await client.get('/api/v1/map-access/zones')).status_code==401
        assert (await client.post('/api/v1/map-access/zones',json=dict(scene_id='Scene01_Test',name='区域',access_level=1,vertices=polygon()))).status_code==401


@pytest.mark.asyncio
async def test_existing_evidence_survives_idempotent_context_migration(monkeypatch):
    engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(text('ALTER TABLE anomaly_evidence DROP COLUMN access_context'))
        await connection.execute(text("INSERT INTO anomaly_evidence(event_type,severity,created_at) VALUES('HISTORICAL','WARNING','2026-10-20T00:00:00Z')"))
    monkeypatch.setattr(database,'get_engine',lambda:engine)
    await database.init_db();await database.init_db()
    async with engine.connect() as connection:
        columns=await connection.run_sync(lambda c:{v['name'] for v in inspect(c).get_columns('anomaly_evidence')})
        assert 'access_context' in columns
        assert (await connection.execute(text('SELECT event_type,access_context FROM anomaly_evidence'))).one()==('HISTORICAL',None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_worker_emits_no_alarm_for_allowed_and_records_identified_region_denial(harness,monkeypatch):
    _,factory,service,tmp_path=harness
    configured=make_service()
    service._zones=configured._zones;service._identity_levels=configured._identity_levels;service._identity_versions=configured._identity_versions
    broadcaster=AsyncMock();broadcaster.broadcast_alert.return_value=1
    alerts=alert_service.AlertService(broadcaster)
    monkeypatch.setattr('backend.workers_ai_processing.get_alert_service',lambda:alerts)
    worker=AIWorkerProcessingMixin();worker._session_factory=factory;worker._current_task_id=None
    worker._person_alert_last_seen={};worker._person_pose_hits={};worker._person_alert_frame=0;worker._reset_misses=20
    worker._record_recognized_person=AsyncMock(return_value=True)
    path=tmp_path/'snapshot.jpg';path.write_bytes(b'isolated-test-snapshot')
    worker._save_snapshot=AsyncMock(return_value=(path,'/test/snapshot.jpg'))
    p=person(3);p.map_access=decision(service,p,12)
    for _ in range(5):await worker._process_person_alerts([p],b'not-a-video')
    assert broadcaster.broadcast_alert.await_count==0
    p.map_access=decision(service,p,2)
    for _ in range(5):await worker._process_person_alerts([p],b'not-a-video')
    assert broadcaster.broadcast_alert.await_count==1
    async with factory() as db:
        row=(await db.execute(select(AnomalyEvidence))).scalar_one()
        assert row.event_code=='E_MAP_ACCESS_DENIED'
        assert row.access_context['identity_id']==3
        assert row.access_context['denied_zone_ids']==[1]
        assert row.access_context['robot_map_position']==[2.,2.,0.]
        assert row.access_context['identity_access_level']==3
        assert row.access_context['required_access_level']==1
        assert row.access_context['coordinate_method']=='robot_position'
        assert '机器人所在区域' in row.message


@pytest.mark.asyncio
async def test_scoped_repeat_does_not_suppress_other_region_and_survives_restart(harness,monkeypatch):
    _,factory,_,_=harness
    monkeypatch.setattr(alert_service.settings,'AI_COOLDOWN_SECONDS',30)
    service=alert_service.AlertService(AsyncMock())
    async def emit(scope,instance=service):
        async with factory() as db:
            return await instance.handle_ai_event(event_type='MAP_ACCESS_DENIED',event_code='E_MAP_ACCESS_DENIED',severity='CRITICAL',message='test',confidence=.9,file_path=None,image_url=None,gps_lat=None,gps_lon=None,task_id=None,session=db,access_context={'repeat_scope':scope},repeat_scope=scope)
    assert await emit('person1:zone1') is not None
    assert await emit('person1:zone1') is None
    assert await emit('person1:zone2') is not None
    assert await emit('person2:zone1') is not None
    assert await emit('person1:zone1',alert_service.AlertService(AsyncMock())) is None


@pytest.mark.asyncio
async def test_viewer_can_read_regions_but_cannot_change_levels(harness):
    app,_,_,_=harness
    app.dependency_overrides.pop(require_admin)
    app.dependency_overrides.pop(require_viewer)
    app.dependency_overrides[get_current_user]=lambda:AuthUserInternal(id=2,username='viewer',role='viewer',token_version=0)
    async with AsyncClient(app=app,base_url='http://test') as client:
        assert (await client.get('/api/v1/map-access/zones')).status_code==200
        assert (await client.post('/api/v1/map-access/zones',json=dict(scene_id='Scene01_Test',name='区域',access_level=1,vertices=polygon()))).status_code==403
        assert (await client.patch('/api/v1/face-identities/1',json={'access_level':1})).status_code==403


@pytest.mark.asyncio
async def test_additive_level_migration_preserves_existing_people_and_regions(tmp_path,monkeypatch):
    engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "legacy.db"}')
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE face_identities (id INTEGER PRIMARY KEY, display_name VARCHAR(100) NOT NULL, notes VARCHAR(500), enabled INTEGER NOT NULL, created_at VARCHAR NOT NULL, updated_at VARCHAR NOT NULL)"))
        await connection.execute(text("CREATE TABLE map_access_zones (id INTEGER PRIMARY KEY, scene_id VARCHAR NOT NULL, name VARCHAR NOT NULL, kind VARCHAR NOT NULL, vertices JSON NOT NULL, plane JSON NOT NULL, enabled INTEGER NOT NULL, boundary_margin_m FLOAT NOT NULL, updated_at VARCHAR NOT NULL)"))
        await connection.execute(text("INSERT INTO face_identities VALUES (1,'既有测试人员','保留记录',1,'software-test','software-test')"))
        await connection.execute(text("INSERT INTO map_access_zones VALUES (1,'Scene01_Test','既有区域','sensitive','[[0,0,0],[4,0,0],[4,4,0],[0,4,0]]','[0,0,0]',1,0.15,'software-test')"))
    monkeypatch.setattr(database,'get_engine',lambda:engine)
    await database.init_db();await database.init_db()
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async with factory() as session:
        identity=await session.get(FaceIdentity,1);zone=await session.get(MapAccessZone,1)
        assert identity.display_name=='既有测试人员' and identity.notes=='保留记录' and identity.access_level is None
        assert zone.name=='既有区域' and zone.access_level is None
        service=MapAccessService();await service.reload(session)
        assert decision(service,person())['reason']=='region_level_unset'
        identity.access_level=3;zone.access_level=1
        session.add(MapAccessGrant(identity_id=1,zone_id=1));await session.commit()
        await service.reload(session)
        assert decision(service,person())['reason']=='insufficient_access_level'
    await engine.dispose()
