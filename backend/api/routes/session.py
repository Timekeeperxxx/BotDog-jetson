"""巡检任务会话路由。"""

from fastapi import APIRouter, Depends, HTTPException

from ...database import get_db
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


@router.post("/start", response_model=SessionStartResponse)
async def session_start(
    body: SessionStartRequest,
    db=Depends(get_db),
) -> SessionStartResponse:
    """
    启动新巡检任务（Session）。

    当前阶段：
    - 不做用户鉴权与并发 Session 限制；
    - 每次调用都会新建一条任务记录。
    """

    task = await create_task(db, task_name=body.task_name)
    await write_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"Session started: {task.task_name} (id={task.task_id})",
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
        message=f"Session stopped: {task.task_name} (id={task.task_id})",
        task_id=task.task_id,
    )

    state_machine = get_state_machine()
    if state_machine is not None:
        state_machine.update_mission_status(False)
    else:
        logger.warning("Session stop succeeded but StateMachine is not initialized")

    return SessionStopResponse(
        task_id=task.task_id,
        task_name=task.task_name,
        status=task.status,
        started_at=task.started_at,
        ended_at=task.ended_at,
    )
