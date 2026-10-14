import asyncio
import json
from types import SimpleNamespace
import pytest
from backend import mapping_save_progress as progress
from backend.schemas import MappingControlResponse
from backend.services_pcd_maps import PcdMapError, find_scene_pcd_files


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(progress.time, 'time', lambda: 1000.0)
    return SimpleNamespace(map_dir=tmp_path, stop_requested_at=900.0,
                           started_at=100.0, is_running=lambda: True)


def write_progress(session, **extra):
    data = dict(stage='loop_map', label='重建回环地图', detail='按最终轨迹重建',
                updated_at=995.0, stage_started_at=970.0, completed=3, total=12,
                unit='关键帧', baseline_saved=True, saved=True)
    data.update(extra)
    (session.map_dir/progress.PROGRESS_FILE).write_text(json.dumps(data))


def test_real_save_elapsed_stage_age_counts_and_heartbeat(session):
    write_progress(session)
    fields = progress.save_fields(session)
    assert fields['save_elapsed_seconds'] == 100
    assert fields['save_worker_alive'] is True
    assert fields['save_progress']['stage_elapsed_seconds'] == 30
    assert fields['save_progress']['update_age_seconds'] == 5
    assert fields['save_progress']['completed'] == 3
    assert 'saved' not in fields  # Neither a progress file nor a baseline claims success.


@pytest.mark.parametrize('extra', [dict(updated_at=800), dict(updated_at=float('nan')),
                                  dict(updated_at=10**400), dict(stage=['invalid']),
                                  dict(stage_started_at=float('inf'))])
def test_invalid_or_stale_progress_falls_back_without_failing_save(session, extra):
    write_progress(session, **extra)
    assert progress.save_fields(session)['save_progress']['stage'] == 'stopping'


def test_unknown_or_invalid_total_never_becomes_percentage(session):
    for completed, total in [(True, 12), (13, 12), (3, None), (-1, 12)]:
        write_progress(session, completed=completed, total=total)
        assert progress.save_fields(session)['save_progress']['total'] is None


def test_refinement_result_is_ignored_when_standard_save_failed(session):
    result = session.map_dir/'.height_refinement'
    result.mkdir()
    (result/'result.json').write_text(json.dumps({'state':'height_refined','reason':'验收通过'}))
    assert progress.refinement_fields(session.map_dir, False)['height_refinement_state'] == 'failed'
    assert progress.refinement_fields(session.map_dir, True)['height_refinement_state'] == 'height_refined'
    (result/'result.json').write_text(json.dumps({'state':'baseline_saved','reason':'证据不足'}))
    assert progress.refinement_fields(session.map_dir, True)['height_refinement_state'] == 'baseline_saved'


def test_saving_marker_blocks_navigation_even_when_files_exist(session):
    (session.map_dir/'.mapping_saving').write_text('saving')
    (session.map_dir/'map.pcd').write_text('baseline')
    (session.map_dir/'ground.pcd').write_text('baseline')
    with pytest.raises(PcdMapError, match='正在保存'):
        find_scene_pcd_files(session.map_dir)


def test_route_and_response_model_preserve_save_fields(session, monkeypatch):
    from backend.api.routes import nav
    from backend import services_mapping
    write_progress(session)
    status = dict(running=False, saving=True, saved=False, **progress.save_fields(session))
    monkeypatch.setattr(services_mapping, 'get_mapping_service',
                        lambda: SimpleNamespace(get_status=lambda: status))
    response = asyncio.run(nav.nav_get_mapping_status(user=object()))
    encoded = MappingControlResponse.model_validate(response).model_dump()
    assert encoded['save_progress']['completed'] == 3
    assert encoded['save_elapsed_seconds'] == 100
    assert encoded['saved'] is False
