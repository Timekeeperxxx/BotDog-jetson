"""Run inside beijing-dev using beijing-env /opt/venv/bin/python."""
import os
from pathlib import Path
import subprocess
import urllib.request

root = Path('/workspace/project')
assert 'VERSION_ID="22.04"' in Path('/etc/os-release').read_text()
assert os.environ['LIVOX_LIDAR_IP'] == '192.168.123.188'
assert os.environ['LIVOX_HOST_IP'] == '192.168.123.11'
for repo in ('Navigation', 'BotDog-jetson'):
    branch = subprocess.check_output(['git', '-C', str(root / repo), 'branch', '--show-current'], text=True).strip()
    assert branch and branch not in ('main', 'master'), branch
hook = root / 'docker/hooks/pre-push'
for branch, expected in [('main', 1), ('master', 1), ('dev/check', 0)]:
    result = subprocess.run([str(hook)], input=f'refs/heads/dev a refs/heads/{branch} b\n', text=True, capture_output=True)
    assert result.returncode == expected, branch
for port, path in [(8002, '/'), (8092, '/api/status')]:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=10) as response:
        assert response.status == 200
packages = subprocess.check_output(['ros2', 'pkg', 'list'], text=True).splitlines()
assert {'nav_lio', 'nav_runtime', 'nav_bringup', 'livox_ros_driver2', 'scan_planner'} <= set(packages)
import sys
sys.path.insert(0, str(root / 'BotDog-jetson'))
from backend.config import settings
from backend.services_mapping import START_MAPPING_SCRIPT
from backend.services_rosbag_recording import RECORD_SCRIPT, ROSBAG_ROOT
assert START_MAPPING_SCRIPT.is_file()
assert RECORD_SCRIPT.is_file()
assert ROSBAG_ROOT == root / "Bags"
assert settings.CONTROL_ADAPTER_TYPE == 'simulation'
assert settings.Z2MINI_HOST == '192.168.123.100'
assert settings.AI_DEVICE == 'cpu'
import cv2
import numpy as np
from ultralytics import YOLO
png = subprocess.check_output(['ffmpeg', '-loglevel', 'error', '-rtsp_transport', 'tcp', '-i', 'rtsp://127.0.0.1:8556/cam', '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-threads', '1', '-'], timeout=25)
frame = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
assert frame is not None
for path in (settings.AI_MODEL_PATH, settings.POSE_MODEL_PATH):
    result = YOLO(path).predict(frame, device='cpu', imgsz=320, verbose=False)
    assert len(result) == 1
assert cv2.FaceDetectorYN.create(settings.FACE_DETECT_MODEL_PATH, '', (320, 320)) is not None
assert cv2.FaceRecognizerSF.create(settings.FACE_RECOGNITION_MODEL_PATH, '') is not None
print('PASS: Ubuntu, development branches, push guards, HTTP, ROS packages, real video, CPU helmet/pose inference and face models')
