from types import SimpleNamespace
import json
import pytest
from backend import services_nav_localization_process as process
from backend.services_ros_nav import RosNavBridge

@pytest.mark.parametrize('reason,cleared', [('nav_e_stop', True), ('control_e_stop', False), ('nav_localization_stop', False)])
def test_only_navigation_soft_stop_can_resume(monkeypatch, tmp_path, reason, cleared):
    monkeypatch.setattr(process.settings, 'NAV_RUNTIME_DIR', str(tmp_path))
    process.set_cmd_vel_estop(True, reason)
    assert process.resume_navigation_soft_stop() is cleared
    assert process.get_cmd_vel_estop_status()['active'] is not cleared


def test_soft_stop_does_not_overwrite_system_stop(monkeypatch, tmp_path):
    monkeypatch.setattr(process.settings, 'NAV_RUNTIME_DIR', str(tmp_path))
    process.set_cmd_vel_estop(True, 'control_e_stop')
    process.set_cmd_vel_estop(True, 'nav_e_stop')
    assert process.get_cmd_vel_estop_status()['reason'] == 'control_e_stop'


def test_resume_waits_for_current_planning_generation(monkeypatch):
    bridge = RosNavBridge.__new__(RosNavBridge)
    calls = []
    bridge._latest_planning_generation = 4
    bridge._latest_planning_status = 'path_ready'
    bridge._planning_status_awaiting_new_generation = True
    bridge._planning_generation_floor = 4
    bridge._resume_after_soft_stop = True
    bridge._navigation_control_expected = True
    bridge._update_live_navigation_status = lambda payload: None
    bridge.publish_navigation_start = lambda enabled: calls.append(enabled)
    bridge._planning_status_publisher_epoch = lambda info: (True, False)
    def status(value, generation):
        bridge._handle_planning_status_message(SimpleNamespace(data=json.dumps(dict(status=value, generation=generation, message=value, elapsed_seconds=0))))
    status('path_ready', 4)
    assert calls == []
    status('queued', 5)
    assert calls == []
    status('path_ready', 5)
    assert calls == [True]


def test_system_state_blocks_legacy_soft_stop_release(monkeypatch, tmp_path):
    monkeypatch.setattr(process.settings, 'NAV_RUNTIME_DIR', str(tmp_path))
    monkeypatch.setattr('backend.control_service.get_control_service', lambda: SimpleNamespace(is_e_stop_active=lambda: True))
    process.set_cmd_vel_estop(True, 'nav_e_stop')
    with pytest.raises(RuntimeError, match='系统急停'):
        process.resume_navigation_soft_stop()
    assert process.get_cmd_vel_estop_status()['active']


@pytest.mark.asyncio
@pytest.mark.parametrize("publish_fails", [False, True])
async def test_explicit_go_to_resumes_soft_stop_before_starting_bridge(monkeypatch, tmp_path, publish_fails):
    from test_nav_go_to import _install_concurrent_go_to_dependencies, _operator, _goal_publish_result
    from backend.api.routes import nav
    calls = []
    waypoint = dict(id='wp', x=1.0, y=2.0, z=0.0, yaw=0.0, frame_id='map')
    class Bridge:
        def publish_navigation_task_start(self, enabled):
            return dict(success=True, topic='/nav_task_start')
        def arm_soft_stop_resume(self):
            calls.append('arm')
        def publish_goal_xyz_yaw(self, goal):
            calls.append('goal')
            if publish_fails:
                raise RuntimeError('goal failed')
            return _goal_publish_result(goal)
        def publish_navigation_stop(self):
            raise RuntimeError('stop publisher unavailable')
    class Service:
        def is_e_stop_active(self):
            return False
        async def prepare_navigation_motion(self):
            return dict(success=True)
    _install_concurrent_go_to_dependencies(monkeypatch, bridge=Bridge(), control_service=Service(), waypoints={('scene', 'wp'): waypoint})
    monkeypatch.setattr(process.settings, 'NAV_RUNTIME_DIR', str(tmp_path))
    def start_bridge():
        assert not process.get_cmd_vel_estop_status()['active']
        calls.append('start')
        return dict(success=True, pid=1234)
    monkeypatch.setattr('backend.services_nav_localization.start_cmd_vel_script', start_bridge)
    process.set_cmd_vel_estop(True, 'nav_e_stop')
    monkeypatch.setattr('backend.services_nav_localization.stop_cmd_vel_script', lambda: calls.append('stop'))
    if publish_fails:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await nav.nav_go_to_waypoint('scene', 'wp', user=_operator(), db=None)
        assert exc.value.detail == 'goal failed'
        assert process.get_cmd_vel_estop_status()['active']
        assert calls == ['arm', 'start', 'goal', 'stop']
    else:
        result = await nav.nav_go_to_waypoint('scene', 'wp', user=_operator(), db=None)
        assert result['success']
        assert calls == ['arm', 'start', 'goal']
