from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from backend import pose_lab


def jpeg(size=(640, 480), color=(255, 0, 0)):
    output = BytesIO()
    Image.new('RGB', size, color).save(output, format='JPEG')
    return output.getvalue()


def test_camera_protocol_and_frame_validation(monkeypatch):
    class Detector:
        def detect(self, frame):
            assert len(frame) == 640 * 480 * 3
            assert frame[2] > 240 and frame[0] < 10  # Red JPEG becomes BGR.
            return []

    monkeypatch.setattr(pose_lab, 'detector', Detector())
    with TestClient(pose_lab.app, base_url='http://localhost:8011') as client:
        assert '动作试验台' in client.get('/').text
        with client.websocket_connect('ws://localhost:8011/ws', headers={'origin': 'http://localhost:8011'}) as ws:
            assert ws.receive_json()['type'] == 'ready'
            ws.send_bytes(jpeg())
            result = ws.receive_json()
            assert result['poses'] == result['events'] == []
            assert result['inference_ms'] >= 0
            ws.send_bytes(jpeg((10, 10)))
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('ws://localhost:8011/ws', headers={'origin': 'http://other-site.example'}):
                pass
    with pytest.raises(ValueError):
        pose_lab.decode_frame(b'x' * 1_000_001)
