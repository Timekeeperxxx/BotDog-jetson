from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from backend import workers_ai_processing
from backend.workers_ai_processing import AIWorkerProcessingMixin
from backend.alert_service import AlertService
from backend.evidence_labels import evidence_label

def worker():
    w=AIWorkerProcessingMixin();w._person_alert_boxes={};w._reset_misses=3
    w._record_recognized_person=AsyncMock(return_value=True)
    return w

def person(track=1,identity=9,status='recognized',box=(0,0,100,200)):
    return SimpleNamespace(label='person',track_id=track,identity_id=identity,face_status=status,bbox=box,display_name='测试人员',face_score=.8)

@pytest.mark.asyncio
async def test_one_snapshot_while_visible_and_face_fluctuates():
    w=worker();p=person()
    for i in range(1,10):await w._process_recognized_person_snapshots([p],b'frame',i)
    p.face_status='no_face';p.identity_id=None
    for i in range(10,20):await w._process_recognized_person_snapshots([p],b'frame',i)
    p.face_status='recognized';p.identity_id=9
    await w._process_recognized_person_snapshots([p],b'frame',20)
    assert w._record_recognized_person.await_count==1

@pytest.mark.asyncio
async def test_reentry_after_confirmed_absence_and_reused_id():
    w=worker();p=person();await w._process_recognized_person_snapshots([p],b'one',1)
    for i in [2,3]:await w._process_recognized_person_snapshots([],b'',i)
    await w._process_recognized_person_snapshots([p],b'short-gap',4)
    assert w._record_recognized_person.await_count==1
    for i in [5,6,7]:await w._process_recognized_person_snapshots([],b'',i)
    await w._process_recognized_person_snapshots([p],b'reentry',8)
    assert w._record_recognized_person.await_count==2

@pytest.mark.asyncio
async def test_track_number_changes_same_identity_without_duplicate():
    w=worker();await w._process_recognized_person_snapshots([person()],b'one',1)
    w._person_alert_boxes={1:(0,0,100,200)}
    await w._process_recognized_person_snapshots([person(7,None,'no_face')],b'no-face-new-id',2)
    await w._process_recognized_person_snapshots([person(7)],b'recognized-new-id',3)
    assert w._record_recognized_person.await_count==1

@pytest.mark.asyncio
async def test_two_identities_each_saved_once_and_identity_change():
    w=worker();a=person();b=person(2,10,box=(300,0,400,200))
    for i in [1,2,3]:await w._process_recognized_person_snapshots([a,b],b'frame',i)
    assert w._record_recognized_person.await_count==2
    a.identity_id=11;await w._process_recognized_person_snapshots([a,b],b'changed',4)
    assert w._record_recognized_person.await_count==3

@pytest.mark.asyncio
@pytest.mark.parametrize('status,identity',[('pending',9),('no_face',None),('unknown',None),('recognized',None),('unavailable',9)])
async def test_only_confirmed_library_identity_gets_capture(status,identity):
    w=worker();await w._process_recognized_person_snapshots([person(status=status,identity=identity)],b'frame',1)
    w._record_recognized_person.assert_not_awaited()

@pytest.mark.asyncio
async def test_capture_failure_retries_and_marks_only_success():
    w=worker();w._record_recognized_person.side_effect=[RuntimeError('write failed'),False,True,True]
    for i in [1,2,3,4]:await w._process_recognized_person_snapshots([person()],b'frame',i)
    assert w._record_recognized_person.await_count==3

@pytest.mark.asyncio
async def test_record_stores_info_identity_without_alarm(monkeypatch):
    service=AlertService();saved=[]
    async def store(e,session):saved.append(e);e.evidence_id=7
    service._store_evidence=store;service._broadcast_alert_payload=AsyncMock()
    e=await service.record_identity_snapshot(identity_id=9,display_name='测试人员',confidence=.8,file_path='/tmp/frame.jpg',image_url='/img/frame.jpg',gps_lat=None,gps_lon=None,task_id=None,session=object())
    assert e.evidence_id==7 and e.severity=='INFO' and e.event_code=='E_FACE_IDENTIFIED'
    assert '测试人员' in e.message and '9' in e.message
    assert evidence_label(e.event_code,e.event_type)=='已识别人员'
    service._broadcast_alert_payload.assert_not_awaited()

@pytest.mark.asyncio
async def test_worker_saves_actual_jpeg_with_face_score(tmp_path,monkeypatch):
    w=AIWorkerProcessingMixin();w._snapshot_dir=tmp_path;w._frame_width=2;w._frame_height=2;w._current_task_id=None;w._get_latest_gps=lambda:(None,None)
    class Session:
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
    w._session_factory=Session;records=[]
    async def record(**kw):records.append(kw);return SimpleNamespace(evidence_id=8)
    monkeypatch.setattr(workers_ai_processing,'get_alert_service',lambda:SimpleNamespace(record_identity_snapshot=record))
    assert await w._record_recognized_person(person(),bytes([20,40,60])*4)
    images=list(tmp_path.rglob('*.jpg'));assert len(images)==1 and images[0].read_bytes().startswith(b'\xff\xd8')
    assert records[0]['identity_id']==9 and records[0]['confidence']==.8

@pytest.mark.asyncio
async def test_continuous_identity_creates_one_database_record_and_one_jpeg(tmp_path,monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
    from sqlalchemy import select
    from backend.database import Base
    from backend.models import AnomalyEvidence
    engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
    w=AIWorkerProcessingMixin();w._person_alert_boxes={};w._reset_misses=3
    w._person_alert_last_seen={};w._person_pose_hits={};w._person_alert_frame=0
    w._snapshot_dir=tmp_path;w._frame_width=2;w._frame_height=2;w._current_task_id=None
    w._session_factory=async_sessionmaker(engine,expire_on_commit=False);w._get_latest_gps=lambda:(None,None)
    service=AlertService();service._broadcast_alert_payload=AsyncMock()
    monkeypatch.setattr(workers_ai_processing,'get_alert_service',lambda:service)
    for _ in range(8):await w._process_person_alerts([person()],bytes([20,40,60])*4)
    async with w._session_factory() as session:
        rows=(await session.execute(select(AnomalyEvidence))).scalars().all()
        assert len(rows)==1 and rows[0].event_code=='E_FACE_IDENTIFIED'
        assert rows[0].severity=='INFO' and '测试人员' in rows[0].message
        assert Path(rows[0].file_path).is_file()
    assert len(list(tmp_path.rglob('*.jpg')))==1
    service._broadcast_alert_payload.assert_not_awaited()
    await engine.dispose()

@pytest.mark.asyncio
async def test_task_context_reset_does_not_repeat_visible_identity():
    w=worker();w._person_alert_last_seen={};w._person_pose_hits={}
    w._weapon_first_seen={};w._weapon_hits={};w._weapon_last_bbox={}
    await w._process_recognized_person_snapshots([person()],b'one',1)
    w._reset_detection_state()
    await w._process_recognized_person_snapshots([person()],b'same-person-new-task',2)
    assert w._record_recognized_person.await_count==1
