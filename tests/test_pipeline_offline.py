"""Execute the actual shell watchdog bodies with fake probes, sleep and recovery."""
import os
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def shell_environment(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "rtsp-healthcheck.py").write_text('''import os,sys,pathlib
root=pathlib.Path(os.environ['TEST_ROOT'])
mode=os.environ['TEST_MODE']
kind='network' if '--network-only' in sys.argv else ('maintenance' if '--recovery-port' in sys.argv else 'video')
with (root/'probes').open('a') as f: f.write(kind+'\\n')
if kind=='network':
 print('no carrier' if mode=='offline' else 'link up');sys.exit(2 if mode=='offline' else 0)
if kind=='maintenance': sys.exit(2 if mode=='unreachable' else 0)
sys.exit(0 if (root/'restored').exists() else 1)
''')
    (scripts / "z2mini-recover.py").write_text('''import os,sys,pathlib
root=pathlib.Path(os.environ['TEST_ROOT']);kind=sys.argv[sys.argv.index('--mode')+1]
with (root/'recoveries').open('a') as f:f.write(kind+'\\n')
mode=os.environ['TEST_MODE']
ok=(mode=='service_ready' and kind=='service') or (mode=='reboot_ready' and kind=='reboot')
if ok:(root/'restored').write_text('ready')
sys.exit(0 if ok else 1)
''')
    env = {**os.environ, "TEST_ROOT": str(tmp_path), "ROOT_DIR": str(tmp_path), "CAMERA_RTSP_URL": "rtsp://fake-camera/",
           "CAM_REMOTE_SOURCE": "rtsp://fake-relay/", "CAM1_PROBE_TIMEOUT": "1", "CAM1_RETRY_INITIAL_DELAY": "5",
           "CAM1_RETRY_MAX_DELAY": "30", "CAM1_RECOVERY_ENABLED": "1", "CAM1_RECOVERY_FAILURES": "3",
           "CAM1_RECOVERY_COOLDOWN": "300", "CAM1_RECOVERY_TELNET_PORT": "23", "CAM1_RECOVERY_TIMEOUT": "1",
           "CAM1_RECOVERY_SETTLE_DELAY": "0", "CAM1_RECOVERY_REBOOT_ENABLED": "1", "CAM1_RECOVERY_REBOOT_SETTLE_DELAY": "0",
           "CAM1_HOST": "fake-camera", "CAMERA_RETRY_DELAY": "2", "CAM_REMOTE_ENCODER": "ffmpeg",
           "CAM_REMOTE_WIDTH": "640", "CAM_REMOTE_HEIGHT": "360", "CAM_REMOTE_FPS": "10", "CAM_REMOTE_BITRATE": "1000k"}
    (tmp_path / "logs").mkdir()
    return tmp_path, env


def run_body(root, env, body, *, mode, sleeps):
    harness = '''set -eu
sleep_count=0
cam1_recovery_last_uptime=0
log_cam1() { printf '%s\\n' "$*" >> "$TEST_ROOT/messages"; }
sleep() {
  printf '%s\\n' "$1" >> "$TEST_ROOT/delays"
  sleep_count=$((sleep_count+1))
  if [ "$sleep_count" -ge "$TEST_SLEEP_LIMIT" ]; then exit 0; fi
}
run_cam_remote_ffmpeg() { printf 'TRANSCODE\\n' >> "$TEST_ROOT/actions"; }
run_cam_remote_gst_nvenc() { printf 'TRANSCODE\\n' >> "$TEST_ROOT/actions"; }
'''
    result = subprocess.run(["bash", "-c", harness + body], env={**env, "TEST_MODE": mode, "TEST_SLEEP_LIMIT": str(sleeps)},
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    return {name: (root / name).read_text().splitlines() if (root / name).exists() else []
            for name in ["probes", "recoveries", "messages", "actions", "delays"]}


def main_body():
    script = (Path(__file__).resolve().parents[1] / "scripts/run-pipeline.sh").read_text()
    start = script.index("  wait_for_cam1_video() {")
    end = script.index("  configure_cam1_osd()", start)
    return script[start:end] + "\nwait_for_cam1_video\n"


def test_no_carrier_enters_standby_without_video_probe_or_camera_reboot(shell_environment):
    root, env = shell_environment
    result = run_body(root, env, main_body(), mode="offline", sleeps=1)
    assert result["probes"] == ["network"]
    assert result["recoveries"] == []
    assert result["delays"] == ["30"]
    assert "standby" in result["messages"][0]


def test_unreachable_camera_maintenance_disables_service_and_reboot_recovery(shell_environment):
    root, env = shell_environment
    result = run_body(root, env, main_body(), mode="unreachable", sleeps=5)
    assert "maintenance" in result["probes"]
    assert result["recoveries"] == []
    assert any("skipping service recovery and reboot" in message for message in result["messages"])


@pytest.mark.parametrize("mode,expected", [("service_ready", ["service"]), ("reboot_ready", ["service", "reboot"])])
def test_reachable_camera_retains_verified_two_stage_recovery(shell_environment, mode, expected):
    root, env = shell_environment
    result = run_body(root, env, main_body(), mode=mode, sleeps=10)
    assert result["recoveries"] == expected
    assert result["probes"][-1] == "video"
    assert (root / "restored").exists()


def test_remote_stream_waits_for_source_and_uses_bounded_backoff(shell_environment):
    root, env = shell_environment
    script = (Path(__file__).resolve().parents[1] / "scripts/run-pipeline.sh").read_text()
    start = script.index('    retry_delay="$CAMERA_RETRY_DELAY"', script.index('# ── cam_remote'))
    end = script.index("  ' &", start)
    result = run_body(root, env, script[start:end], mode="unreachable", sleeps=6)
    assert result["actions"] == []
    assert result["delays"] == ["2", "4", "8", "16", "30", "30"]
    assert len(result["probes"]) == 6
