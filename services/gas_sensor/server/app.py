"""Serve the GT-01 reader and its gas-only dashboard."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .gas_sensor import GasSensorError, GasSensorReader

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.reader = GasSensorReader()
    app.state.reader.start()
    try:
        yield
    finally:
        await run_in_threadpool(app.state.reader.stop)


app = FastAPI(title="GT-01 Gas Monitor", lifespan=lifespan)


@app.get("/api/gases")
async def gas_readings() -> dict:
    try:
        return await run_in_threadpool(app.state.reader.snapshot)
    except GasSensorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/")
@app.get("/gases")
@app.get("/ph3")
async def gases() -> FileResponse:
    return FileResponse(STATIC_DIR / "h2s.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
