"""
录像路由。

提供前置摄像头（cam1）的开始/停止录像接口。
录像通过后端 FFmpeg 从 RTSP 源（settings.AI_RTSP_URL）录制，保存为 MP4 文件。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from ...auth.dependencies import require_viewer, require_operator
from pydantic import BaseModel

from ...config import settings
from ...database import get_session_factory
from ...logging_config import get_logger
from ...models import Recording

router = APIRouter(prefix="/api/v1", tags=["recording"], dependencies=[Depends(require_viewer)])


@dataclass
class _ActiveRecording:
    proc: asyncio.subprocess.Process
    recording_id: int
    file_path: Path
    started_at: str
    ended_at: str | None = None

    def mark_ended(self) -> str:
        # Preserve the process end time across remux and failed DB finalization.
        if self.ended_at is None:
            self.ended_at = _utc_now_iso()
        return self.ended_at


# The backend runs one worker. Hold this lock through start/stop and DB finalization.
_recording_lock = asyncio.Lock()
_current_recording: _ActiveRecording | None = None
_monitor_tasks: set[asyncio.Task] = set()
_STARTUP_PROBE_SECONDS = 0.2
_logger = get_logger("录像")


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


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        try:
            proc.terminate()
        except ProcessLookupError:
            # The OS process can exit before asyncio updates returncode.
            _logger.debug("录像进程在发送 SIGTERM 前已退出")
        try:
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            _logger.warning("录像进程未在 10 秒内退出，发送 SIGKILL")
            try:
                proc.kill()
            except ProcessLookupError:
                _logger.debug("录像进程在发送 SIGKILL 前已退出")
            await proc.wait()
    else:
        await proc.wait()


async def _finish_recording(active: _ActiveRecording) -> RecordingStopResponse:
    """Called under the lock; retain ownership until the DB update succeeds."""
    global _current_recording
    ended_at = active.mark_ended()
    try:
        file_size_bytes = active.file_path.stat().st_size
    except FileNotFoundError:
        file_size_bytes = 0
    duration_seconds = round((
        datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        - datetime.fromisoformat(active.started_at.replace("Z", "+00:00"))
    ).total_seconds(), 2)

    async with get_session_factory()() as session:
        rec = await session.get(Recording, active.recording_id)
        if rec is None:
            raise RuntimeError(f"录像记录不存在：{active.recording_id}")
        rec.ended_at = ended_at
        rec.duration_seconds = duration_seconds
        rec.file_size_bytes = file_size_bytes
        await session.commit()
        video_url = rec.video_url

    _current_recording = None
    return RecordingStopResponse(
        recording_id=active.recording_id, ended_at=ended_at,
        duration_seconds=duration_seconds, file_size_bytes=file_size_bytes, video_url=video_url,
    )


async def _monitor_recording(active: _ActiveRecording) -> None:
    await active.proc.wait()
    active.mark_ended()
    async with _recording_lock:
        # A completed stop or a later start owns a different session.
        if _current_recording is not active:
            return
        _logger.error("录像进程自行退出：recording_id={}，returncode={}", active.recording_id, active.proc.returncode)
        try:
            await _finish_recording(active)
        except Exception:
            # No request is waiting here. Log the failure and keep ownership so a
            # subsequent start/stop can retry finalization rather than orphan the row.
            _logger.exception("录像进程退出后更新数据库失败：recording_id={}", active.recording_id)


async def _remux_recording(file_path: Path) -> None:
    """Optional faststart optimization; retain the original if remux fails."""
    temp_path = Path(str(file_path) + ".tmp.mp4")
    remux = None
    try:
        remux = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(file_path), "-c", "copy",
            "-movflags", "+faststart", str(temp_path),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(remux.wait(), timeout=30.0)
        if remux.returncode == 0:
            os.replace(temp_path, file_path)
        else:
            _logger.warning("录像 faststart 失败，保留原文件：returncode={}", remux.returncode)
    except (OSError, asyncio.TimeoutError) as exc:
        _logger.warning("录像 faststart 失败，保留原文件：{}", exc)
    finally:
        if remux is not None:
            await _terminate_process(remux)
        temp_path.unlink(missing_ok=True)


# ── 接口 ─────────────────────────────────────────────────────────────────────

@router.get("/recording/status", response_model=RecordingStatusResponse)
async def get_recording_status() -> RecordingStatusResponse:
    active = _current_recording
    if active is not None and active.proc.returncode is None:
        return RecordingStatusResponse(
            is_recording=True, recording_id=active.recording_id, started_at=active.started_at,
        )
    return RecordingStatusResponse(is_recording=False)


@router.post("/recording/start", response_model=RecordingStartResponse, dependencies=[Depends(require_operator)])
async def start_recording() -> RecordingStartResponse:
    global _current_recording
    async with _recording_lock:
        if _current_recording is not None:
            if _current_recording.proc.returncode is None:
                raise HTTPException(status_code=409, detail="已在录制中")
            await _finish_recording(_current_recording)

        recording_dir = Path(settings.RECORDING_DIR)
        recording_dir.mkdir(parents=True, exist_ok=True)
        started_at = _utc_now_iso()
        filename = f"recording_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex}.mp4"
        file_path = recording_dir / filename
        proc = None
        try:
            # Flush for the ID, but commit only after the process starts. Failure
            # rolls back the row; a failed DB commit must also stop the process.
            async with get_session_factory()() as session:
                rec = Recording(
                    camera_name="cam1", file_path=str(file_path),
                    video_url=f"/api/v1/media/recordings/{filename}", started_at=started_at,
                )
                session.add(rec)
                await session.flush()
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-fflags", "nobuffer", "-rtsp_transport", "tcp",
                        "-i", settings.AI_RTSP_URL, "-c:v", "copy", "-an", str(file_path),
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    )
                except OSError as exc:
                    raise HTTPException(status_code=502, detail="无法启动录像进程") from exc
                try:
                    await asyncio.wait_for(proc.wait(), timeout=_STARTUP_PROBE_SECONDS)
                except asyncio.TimeoutError:
                    # Still running after the startup probe; this is not a claim
                    # that RTSP frames have arrived or that the video is playable.
                    pass
                else:
                    raise HTTPException(status_code=502, detail=f"录像进程启动后立即退出：{proc.returncode}")
                await session.commit()
                active = _ActiveRecording(proc, rec.recording_id, file_path, started_at)
        except BaseException:
            # Also applies to a cancelled request: never leave an untracked process.
            if proc is not None:
                await _terminate_process(proc)
            file_path.unlink(missing_ok=True)
            raise

        _current_recording = active
        # A DB commit also yields: do not acknowledge a process already known to
        # have exited during that await. The committed row still needs an end time.
        if active.proc.returncode is not None:
            await _finish_recording(active)
            raise HTTPException(status_code=502, detail=f"录像进程在初始化期间退出：{active.proc.returncode}")
        monitor = asyncio.create_task(_monitor_recording(active))
        _monitor_tasks.add(monitor)
        monitor.add_done_callback(_monitor_tasks.discard)
        return RecordingStartResponse(recording_id=active.recording_id, started_at=started_at)


@router.post("/recording/stop", response_model=RecordingStopResponse, dependencies=[Depends(require_operator)])
async def stop_recording() -> RecordingStopResponse:
    async with _recording_lock:
        active = _current_recording
        if active is None:
            raise HTTPException(status_code=409, detail="当前未在录制")
        if active.proc.returncode is not None:
            await _finish_recording(active)
            raise HTTPException(status_code=409, detail="录像进程已退出")
        await _terminate_process(active.proc)
        active.mark_ended()
        await _remux_recording(active.file_path)
        result = await _finish_recording(active)
        if result.file_size_bytes == 0:
            raise HTTPException(status_code=502, detail="录像已停止，但没有生成视频文件")
        return result


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
