"""巡检任务会话路由。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ...database import get_db
from ...models import InspectionTask
from ...logging_config import logger
from ...schemas import (
    SessionStartRequest,
    SessionStartResponse,
    SessionStopRequest,
    SessionStopResponse,
)
from ...services_logs import write_log
from ...services_tasks import create_task, stop_task
from ...state_machine_state import get_state_machine

router = APIRouter(prefix="/api/v1/session", tags=["session"])


@router.get("/current", response_model=SessionStartResponse | None)
async def session_current(db=Depends(get_db)):
    result = await db.execute(
        select(InspectionTask)
        .where(InspectionTask.status == "running")
        .order_by(InspectionTask.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.post("/start", response_model=SessionStartResponse)
async def session_start(
    body: SessionStartRequest,
    db=Depends(get_db),
) -> SessionStartResponse:
    """
    启动巡检；已有运行中的会话时返回该会话，避免重复启动。
    """

    task = await create_task(db, task_name=body.task_name)
    await write_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户=anonymous 角色=anonymous 操作=session.start "
            f"目标={task.task_id} 结果=success 任务名={task.task_name}"
        ),
        task_id=task.task_id,
    )

    state_machine = get_state_machine()
    if state_machine is not None:
        state_machine.update_mission_status(True)
    else:
        logger.warning("Session start succeeded but StateMachine is not initialized")

    return SessionStartResponse(
        task_id=task.task_id,
        task_name=task.task_name,
        status=task.status,
        started_at=task.started_at,
        ended_at=task.ended_at,
    )


@router.post("/stop", response_model=SessionStopResponse)
async def session_stop(
    body: SessionStopRequest,
    db=Depends(get_db),
) -> SessionStopResponse:
    """
    停止指定任务。
    """

    task = await stop_task(db, task_id=body.task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=f"task_id={body.task_id} not found",
        )

    await write_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户=anonymous 角色=anonymous 操作=session.stop "
            f"目标={task.task_id} 结果=success 任务名={task.task_name}"
        ),
        task_id=task.task_id,
    )

    state_machine = get_state_machine()
    if state_machine is not None:
        current = await session_current(db)
        state_machine.update_mission_status(current is not None)
    else:
        logger.warning("Session stop succeeded but StateMachine is not initialized")

    return SessionStopResponse(
        task_id=task.task_id,
        task_name=task.task_name,
        status=task.status,
        started_at=task.started_at,
        ended_at=task.ended_at,
    )
