"""隔离的摄像头姿态试验台：不导入控制或告警服务，不保存图像。

在仓库根目录运行 .venv/bin/python -m backend.pose_lab。
通过 SSH 将 127.0.0.1:8011 转发至测试电脑的 localhost:8011。
"""
import asyncio
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from .config import settings
from .pose_detection import PoseEventEngine, UltralyticsPoseDetector

app = FastAPI(docs_url=None, redoc_url=None)
busy = asyncio.Lock()
detector = None
WIDTH, HEIGHT = 640, 480


def new_engine():
    return PoseEventEngine(
        keypoint_confidence=settings.POSE_KEYPOINT_CONFIDENCE,
        min_visible_keypoints=settings.POSE_MIN_VISIBLE_KEYPOINTS,
        stable_hits=settings.POSE_STABLE_HITS,
        chest_motion_seconds=settings.POSE_CHEST_MOTION_SECONDS,
        chest_motion_span=settings.POSE_CHEST_MOTION_SPAN,
        crouch_seconds=settings.POSE_CROUCH_SECONDS,
        loiter_seconds=settings.POSE_LOITER_SECONDS,
        event_cooldown_seconds=settings.POSE_EVENT_COOLDOWN_SECONDS,
        track_ttl_seconds=settings.POSE_TRACK_TTL_SECONDS,
    )


def decode_frame(data):
    if not data or len(data) > 1_000_000:
        raise ValueError('图像大小超出限制')
    with Image.open(BytesIO(data)) as image:
        if image.format != 'JPEG' or image.size != (WIDTH, HEIGHT):
            raise ValueError('需要 640×480 JPEG 图像')
        # 正式视频链路同样使用 BGR。
        return image.convert('RGB').tobytes('raw', 'BGR')


def infer(frame, engine, observed):
    global detector
    if detector is None:
        detector = UltralyticsPoseDetector(
            model_path=settings.POSE_MODEL_PATH, device=settings.POSE_DEVICE,
            confidence=settings.POSE_CONFIDENCE_THRESHOLD,
            inference_imgsz=settings.POSE_INFERENCE_IMGSZ,
            frame_width=WIDTH, frame_height=HEIGHT,
        )
    started = time.monotonic()
    poses = detector.detect(frame)
    observations, events = engine.update(poses, now=observed)
    return {'type': 'result', 'poses': [pose.as_overlay() for pose in observations],
            'events': [asdict(event) for event in events],
            'active_actions': sorted(engine.active_actions),
            'inference_ms': round((time.monotonic() - started) * 1000, 1)}


@app.get('/')
async def page():
    return FileResponse(Path(__file__).with_name('pose_lab.html'))


@app.websocket('/ws')
async def frames(ws: WebSocket):
    # 仅供本机/SSH 转发使用，阻止其他网站借浏览器访问本地推理服务。
    origin = urlsplit(ws.headers.get('origin', ''))
    if (origin.scheme not in ('http', 'https')
            or origin.hostname not in ('localhost', '127.0.0.1', '::1')
            or origin.netloc != ws.headers.get('host')):
        await ws.close(code=1008)
        return
    await ws.accept()
    if busy.locked():
        await ws.send_json({'type': 'error', 'message': '已有测试页面运行，请先停止另一页面。'})
        await ws.close()
        return
    # ponytail: 单测试会话，避免模型并发与动作历史串线；多人测试时再做资源调度。
    async with busy:
        engine = new_engine()
        await ws.send_json({'type': 'ready', 'crouch_seconds': settings.POSE_CROUCH_SECONDS,
                            'loiter_seconds': settings.POSE_LOITER_SECONDS,
                            'cooldown_seconds': settings.POSE_EVENT_COOLDOWN_SECONDS})
        try:
            while True:
                data = await asyncio.wait_for(ws.receive_bytes(), timeout=90)
                observed = time.monotonic()
                frame = decode_frame(data)
                result = await asyncio.to_thread(infer, frame, engine, observed)
                await ws.send_json(result)
        except WebSocketDisconnect:
            pass
        except (ValueError, UnidentifiedImageError, asyncio.TimeoutError):
            await ws.close(code=1008, reason='图像无效或测试超时，请重新开始')
        except Exception:
            import logging
            logging.exception('姿态测试失败')
            await ws.close(code=1011, reason='推理失败，请检查测试服务日志')


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8011, ws_max_size=1_000_000, ws_max_queue=1)
