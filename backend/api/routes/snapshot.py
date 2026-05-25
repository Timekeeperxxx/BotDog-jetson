"""手动拍照路由。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy import select

from ...alert_service import get_alert_service
from ...auto_track_service import _save_snapshot_to_disk
from ...config import settings
from ...database import get_db
from ...models import InspectionTask

router = APIRouter(prefix="/api/v1/snapshot", tags=["snapshot"])


async def _grab_one_frame() -> bytes:
    """从 RTSP 流抓取一帧原始 BGR24 数据。"""
    w = settings.AI_FRAME_WIDTH
    h = settings.AI_FRAME_HEIGHT
    frame_size = w * h * 3

    cmd = [
        "ffmpeg",
        "-rtsp_transport", "tcp",
        "-i", settings.AI_RTSP_URL,
        "-vframes", "1",
        "-vf", f"scale={w}:{h}",
        "-f", "image2pipe",
        "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24",
        "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        frame, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(status_code=504, detail="抓帧超时，请检查视频流是否正常")

    if len(frame) < frame_size:
        raise HTTPException(status_code=503, detail="视频流不可用，无法抓取画面")

    return frame[:frame_size]


@router.post("")
async def manual_snapshot(
    task_id: Optional[int] = None,
    db=Depends(get_db),
) -> dict:
    """
    手动抓拍当前画面。

    - task_id 可由前端传入（当前巡检任务 ID）；若未传则自动查询正在运行的任务。
    - 抓拍结果写入证据库并通过 WebSocket 广播告警。
    """
    # 若未提供 task_id，查询当前正在运行的任务
    if task_id is None:
        stmt = select(InspectionTask).where(InspectionTask.status == "running").limit(1)
        result = await db.execute(stmt)
        running_task = result.scalar_one_or_none()
        task_id = running_task.task_id if running_task else None

    snapshot_dir = Path(settings.SNAPSHOT_DIR)

    frame = await _grab_one_frame()

    image_path, image_url = await _save_snapshot_to_disk(
        frame=frame,
        snapshot_dir=snapshot_dir,
        frame_width=settings.AI_FRAME_WIDTH,
        frame_height=settings.AI_FRAME_HEIGHT,
    )

    alert_service = get_alert_service()
    if alert_service:
        evidence = await alert_service.handle_ai_event(
            event_type="MANUAL_SNAPSHOT",
            event_code="E_MANUAL_SNAPSHOT",
            severity="INFO",
            message="手动拍照",
            confidence=1.0,
            file_path=str(image_path),
            image_url=image_url,
            gps_lat=None,
            gps_lon=None,
            task_id=task_id,
            session=db,
        )
        return {"image_url": image_url}

    return {"image_url": image_url}
