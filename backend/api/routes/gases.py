"""Authenticated, read-only access to the board's gas monitoring service."""
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool

from ...auth.dependencies import require_viewer
from ...auth.schemas import AuthUserInternal
from ...gas_monitor import GasMonitorError, GasMonitorSnapshot, read_gas_monitor

router = APIRouter(prefix="/api/v1/gases", tags=["gases"])


@router.get("", response_model=GasMonitorSnapshot)
async def current_gas_alarms(
    response: Response,
    _: AuthUserInternal = Depends(require_viewer),
) -> GasMonitorSnapshot:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await run_in_threadpool(read_gas_monitor)
    except GasMonitorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
