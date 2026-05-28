"""
录像路由。

提供前置摄像头（cam1）的开始/停止录像接口。
录像通过后端 FFmpeg 从 RTSP 源（settings.AI_RTSP_URL）录制，保存为 MP4 文件。
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...config import settings
from ...database import get_session_factory
from ...models import Recording

router = APIRouter(prefix="/api/v1", tags=["recording"])

# ── 模块级单例：追踪当前录制状态 ────────────────────────────────────────────
_current_proc: asyncio.subprocess.Process | None = None
_current_recording_id: int | None = None
_current_file_path: str | None = None
_current_started_at: str | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ── 响应模型 ─────────────────────────────────────────────────────────────────

class RecordingStatusResponse(BaseModel):
    is_recording: bool
    recording_id: int | None = None
    started_at: str | None = None


class RecordingStartResponse(BaseModel):
    recording_id: int
    started_at: str


class RecordingStopResponse(BaseModel):
    recording_id: int
    ended_at: str
    duration_seconds: float
    file_size_bytes: int
    video_url: str


class RecordingItem(BaseModel):
    recording_id: int
    camera_name: str
    video_url: str
    file_size_bytes: int | None
    duration_seconds: float | None
    task_id: int | None
    started_at: str
    ended_at: str | None


class RecordingListResponse(BaseModel):
    items: list[RecordingItem]


# ── 接口 ─────────────────────────────────────────────────────────────────────

@router.get("/recording/status", response_model=RecordingStatusResponse)
async def get_recording_status() -> RecordingStatusResponse:
    global _current_proc, _current_recording_id, _current_started_at

    if _current_proc is not None and _current_proc.returncode is None:
        return RecordingStatusResponse(
            is_recording=True,
            recording_id=_current_recording_id,
            started_at=_current_started_at,
        )
    return RecordingStatusResponse(is_recording=False)


@router.post("/recording/start", response_model=RecordingStartResponse)
async def start_recording() -> RecordingStartResponse:
    global _current_proc, _current_recording_id, _current_file_path, _current_started_at

    # 若进程存在且仍在运行，返回 409
    if _current_proc is not None and _current_proc.returncode is None:
        raise HTTPException(status_code=409, detail="已在录制中")

    recording_dir = Path(settings.RECORDING_DIR)
    recording_dir.mkdir(parents=True, exist_ok=True)

    started_at = _utc_now_iso()
    filename = f"recording_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.mp4"
    file_path = str(recording_dir / filename)
    video_url = f"/api/v1/media/recordings/{filename}"

    # 写入 DB 记录（ended_at=NULL 表示录制中）
    async with get_session_factory()() as session:
        rec = Recording(
            camera_name="cam1",
            file_path=file_path,
            video_url=video_url,
            started_at=started_at,
        )
        session.add(rec)
        await session.commit()
        await session.refresh(rec)
        recording_id = rec.recording_id

    # 启动 FFmpeg（stream copy，零重编码）
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-fflags", "nobuffer",
        "-rtsp_transport", "tcp",
        "-i", settings.AI_RTSP_URL,
        "-c:v", "copy",
        "-an",
        file_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    _current_proc = proc
    _current_recording_id = recording_id
    _current_file_path = file_path
    _current_started_at = started_at

    return RecordingStartResponse(recording_id=recording_id, started_at=started_at)


@router.post("/recording/stop", response_model=RecordingStopResponse)
async def stop_recording() -> RecordingStopResponse:
    global _current_proc, _current_recording_id, _current_file_path, _current_started_at

    if _current_proc is None or _current_proc.returncode is not None:
        raise HTTPException(status_code=409, detail="当前未在录制")

    proc = _current_proc
    recording_id = _current_recording_id
    file_path = _current_file_path

    # 发送 SIGTERM 让 FFmpeg 正常写入 moov box 后退出
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()

    ended_at = _utc_now_iso()

    # 无损 remux：将 moov 移到文件开头（+faststart），确保浏览器可直接流式播放
    temp_path = file_path + ".tmp.mp4"
    try:
        remux = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", file_path,
            "-c", "copy",
            "-movflags", "+faststart",
            temp_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(remux.wait(), timeout=30.0)
        if remux.returncode == 0:
            os.replace(temp_path, file_path)
        else:
            try:
                os.remove(temp_path)
            except OSError:
                pass
    except Exception:
        pass

    # 计算文件大小
    file_size_bytes = 0
    try:
        file_size_bytes = os.path.getsize(file_path)
    except OSError:
        pass

    # 计算时长（基于时间戳字符串）
    duration_seconds = 0.0
    try:
        fmt = "%Y-%m-%dT%H:%M:%S.%f"
        started_dt = datetime.fromisoformat(_current_started_at.replace("Z", "+00:00"))
        ended_dt = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        duration_seconds = (ended_dt - started_dt).total_seconds()
    except Exception:
        pass

    # 更新 DB 记录
    async with get_session_factory()() as session:
        rec = await session.get(Recording, recording_id)
        if rec:
            rec.ended_at = ended_at
            rec.duration_seconds = round(duration_seconds, 2)
            rec.file_size_bytes = file_size_bytes
            await session.commit()
            video_url = rec.video_url
        else:
            video_url = f"/api/v1/static/recordings/{Path(file_path).name}"

    # 清空全局状态
    _current_proc = None
    _current_recording_id = None
    _current_file_path = None
    _current_started_at = None

    return RecordingStopResponse(
        recording_id=recording_id,
        ended_at=ended_at,
        duration_seconds=round(duration_seconds, 2),
        file_size_bytes=file_size_bytes,
        video_url=video_url,
    )


@router.get("/recordings", response_model=RecordingListResponse)
async def list_recordings() -> RecordingListResponse:
    from sqlalchemy import select, desc

    async with get_session_factory()() as session:
        result = await session.execute(
            select(Recording).order_by(desc(Recording.recording_id)).limit(100)
        )
        rows = result.scalars().all()

    return RecordingListResponse(
        items=[
            RecordingItem(
                recording_id=r.recording_id,
                camera_name=r.camera_name,
                video_url=r.video_url,
                file_size_bytes=r.file_size_bytes,
                duration_seconds=r.duration_seconds,
                task_id=r.task_id,
                started_at=r.started_at,
                ended_at=r.ended_at,
            )
            for r in rows
        ]
    )
