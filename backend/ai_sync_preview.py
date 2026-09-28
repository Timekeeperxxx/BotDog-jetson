"""Pull-only preview: one latest frame, one encoder, no inference or frame queue."""
import asyncio
import base64
import io
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse, JSONResponse
from .auth.dependencies import get_current_user

router = APIRouter(prefix='/api/v1/ai-preview', tags=['ai-preview'])
_latest = None
_encoding = None
_cached = None
_sequence = 0


def publish(frame, width, height, received, detections, poses, pose_due, weapon_due):
    global _latest, _sequence
    _sequence += 1
    _latest = (_sequence, frame, width, height, received, time.monotonic(), {
        'detections': [{'bbox': list(d.bbox), 'label': d.label, 'confidence': d.confidence}
                       for d in detections if d.bbox is not None],
        'poses': [p.as_overlay() for p in poses],
        'pose_due': bool(pose_due), 'weapon_due': bool(weapon_due),
    })


def _encode(sample):
    from PIL import Image
    seq, frame, width, height, received, done, payload = sample
    image = Image.frombytes('RGB', (width, height), frame, 'raw', 'BGR')
    buf = io.BytesIO()
    image.save(buf, format='JPEG', quality=75)
    return {**payload, 'seq': seq, 'width': width, 'height': height,
            'processing_ms': round((done - received) * 1000, 1),
            'image': base64.b64encode(buf.getvalue()).decode('ascii')}


async def _encode_latest(sample):
    global _cached
    data = await asyncio.to_thread(_encode, sample)
    _cached = (sample[0], sample[4], data)
    return _cached


@router.get('', include_in_schema=False)
async def page():
    return FileResponse(Path(__file__).with_name('ai_sync_preview.html'), headers={'Cache-Control': 'no-store'})


@router.get('/frame', dependencies=[Depends(get_current_user)])
async def latest_frame(after: int = 0):
    global _encoding
    sample = _latest
    if sample is None or time.monotonic() - sample[4] > 2:
        return JSONResponse({'detail': '等待新检测帧，旧画面已停止显示'}, status_code=503)
    if sample[0] <= after:
        return Response(status_code=204, headers={'Cache-Control': 'no-store'})
    if _encoding is not None and not _encoding.done():
        return Response(status_code=429, headers={'Cache-Control': 'no-store'})
    if _cached is None or _cached[0] != sample[0]:
        # Cancellation cannot enqueue another encoder while the thread still runs.
        _encoding = asyncio.create_task(_encode_latest(sample))
        _encoding.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        result = await asyncio.shield(_encoding)
    else:
        result = _cached
    age = (time.monotonic() - result[1]) * 1000
    if age > 2000:
        return Response(status_code=503)
    return JSONResponse({**result[2], 'age_ms': round(age, 1)}, headers={'Cache-Control': 'no-store'})
