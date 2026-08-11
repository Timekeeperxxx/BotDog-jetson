"""Admin-only endpoints for testing local vision models with uploaded media."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...auth.dependencies import require_admin
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...database import get_db
from ...logging_config import get_logger
from ... import model_test_service


router = APIRouter(prefix="/api/v1/model-tester", tags=["model-tester"])
model_test_logger = get_logger("模型测试")


class ModelOptionResponse(BaseModel):
    key: str
    name: str
    description: str
    available: bool
    runtime: str


class ModelOptionsResponse(BaseModel):
    items: list[ModelOptionResponse]
    max_upload_bytes: int
    result_ttl_seconds: int


class ModelTestRunResponse(BaseModel):
    result_id: str
    filename: str
    result_url: str
    model_key: str
    model_name: str
    runtime: str
    is_video: bool
    media_type: str
    frames: int
    source_frames: int
    source_fps: float | None
    processing_fps: float | None
    detections: int
    label_counts: dict[str, int]
    elapsed_seconds: float


@router.get("/models", response_model=ModelOptionsResponse)
async def list_test_models(
    _: AuthUserInternal = Depends(require_admin),
) -> ModelOptionsResponse:
    model_test_service.cleanup_stale_outputs()
    return ModelOptionsResponse(
        items=[ModelOptionResponse(**item) for item in model_test_service.public_model_definitions()],
        max_upload_bytes=model_test_service.MODEL_TEST_MAX_UPLOAD_BYTES,
        result_ttl_seconds=model_test_service.MODEL_TEST_RESULT_TTL_SECONDS,
    )


async def _save_upload(upload: UploadFile, destination: Path) -> int:
    total_bytes = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > model_test_service.MODEL_TEST_MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="上传文件不能超过 512 MB",
                    )
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return total_bytes


@router.post("/runs", response_model=ModelTestRunResponse)
async def create_model_test_run(
    model: str = Form(...),
    confidence: float = Form(...),
    video_fps: float = Form(5.0),
    media: UploadFile = File(...),
    user: AuthUserInternal = Depends(require_admin),
    db=Depends(get_db),
) -> ModelTestRunResponse:
    original_filename = media.filename or ""
    extension = Path(original_filename).suffix.lower()
    if extension not in model_test_service.ALLOWED_EXTENSIONS:
        await media.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"不支持的文件格式：{extension or '未知'}",
        )
    if model not in model_test_service.get_model_definitions():
        await media.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="请选择有效的模型",
        )
    if not 0.05 <= confidence <= 0.95:
        await media.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="置信度必须在 0.05 到 0.95 之间",
        )
    if not 1.0 <= video_fps <= 30.0:
        await media.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="视频检测帧率必须在 1 到 30 FPS 之间",
        )

    output_dir = model_test_service.MODEL_TEST_OUTPUT_DIR
    source_path = output_dir / f".upload-{uuid.uuid4().hex}{extension}"
    upload_bytes = await _save_upload(media, source_path)
    if upload_bytes == 0:
        source_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="上传文件为空",
        )

    try:
        result = await asyncio.to_thread(
            model_test_service.run_model_test,
            source=source_path,
            original_filename=original_filename,
            model_key=model,
            confidence=confidence,
            video_fps=video_fps,
            output_dir=output_dir,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if isinstance(exc, FileNotFoundError)
                else status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=str(exc),
        ) from exc
    except Exception as exc:
        model_test_logger.exception(
            "模型测试失败：user={} model={} file={} reason={}",
            user.username,
            model,
            original_filename,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"模型推理失败：{exc}",
        ) from exc
    finally:
        source_path.unlink(missing_ok=True)

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=model_test.run "
            f"模型={result.model_key} 文件={original_filename} 大小={upload_bytes} "
            f"运行时={result.runtime} 检测画面={result.frames}/{result.source_frames} "
            f"检测帧率={result.processing_fps} 识别累计={result.detections} 结果=success"
        ),
    )
    return ModelTestRunResponse(
        result_id=result.result_id,
        filename=result.filename,
        result_url=f"/api/v1/model-tester/results/{result.filename}",
        model_key=result.model_key,
        model_name=result.model_name,
        runtime=result.runtime,
        is_video=result.is_video,
        media_type=result.media_type,
        frames=result.frames,
        source_frames=result.source_frames,
        source_fps=result.source_fps,
        processing_fps=result.processing_fps,
        detections=result.detections,
        label_counts=result.label_counts,
        elapsed_seconds=result.elapsed_seconds,
    )


@router.get("/results/{filename}")
async def get_model_test_result(
    filename: str,
    download: bool = Query(default=False),
    _: AuthUserInternal = Depends(require_admin),
) -> FileResponse:
    model_test_service.cleanup_stale_outputs()
    path = model_test_service.resolve_result_file(filename)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试结果不存在或已过期")
    media_type = "video/mp4" if path.suffix.lower() == ".mp4" else "image/jpeg"
    response = FileResponse(
        path,
        media_type=media_type,
        filename=filename if download else None,
    )
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response
