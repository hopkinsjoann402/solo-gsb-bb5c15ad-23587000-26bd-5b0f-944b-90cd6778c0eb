"""港口潮汐通航窗口 API (FastAPI + SQLite)。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from . import db
from .algorithm import TidePoint, calculate_navigation_windows
from .schemas import (
    DepartureWindowOut,
    ForecastPointIn,
    ForecastPointOut,
    ForecastReplace,
    NavigationRequest,
    NavigationResult,
    PortCreate,
    PortOut,
)


def _to_utc(dt: datetime) -> datetime:
    """无时区时间按 UTC 处理; 带时区时间统一转 UTC。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 启动即完成数据库初始化 (建表幂等)
    db.init_db()
    yield


app = FastAPI(
    title="港口潮汐通航窗口 API",
    version="1.0.0",
    description=(
        "录入港口潮高预报点与航道基准水深, 基于线性插值计算船舶可出发时段。"
    ),
    lifespan=lifespan,
)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(db.sqlite3.IntegrityError)
def integrity_error_handler(_request, exc: db.sqlite3.IntegrityError):
    # 例如重名港口
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": f"数据冲突: {exc}"},
    )


def get_port_or_404(port_id: int):
    port = db.get_port(port_id)
    if port is None:
        raise HTTPException(status_code=404, detail=f"港口 {port_id} 不存在")
    return port


# ---------- ports ----------

@app.post("/ports", response_model=PortOut, status_code=201, tags=["ports"])
def create_port(payload: PortCreate):
    return db.create_port(payload.name, payload.chart_datum_depth)


@app.get("/ports", response_model=list[PortOut], tags=["ports"])
def list_ports():
    return db.list_ports()


@app.get("/ports/{port_id}", response_model=PortOut, tags=["ports"])
def get_port(port=Depends(get_port_or_404)):
    return port


@app.delete("/ports/{port_id}", status_code=204, tags=["ports"])
def delete_port(port=Depends(get_port_or_404)):
    db.delete_port(port["id"])


# ---------- forecasts ----------

@app.put(
    "/ports/{port_id}/forecasts",
    response_model=list[ForecastPointOut],
    status_code=200,
    tags=["forecasts"],
    summary="整组替换潮高预报点 (预报更正即重新 PUT)",
)
def replace_forecasts(
    payload: ForecastReplace, port=Depends(get_port_or_404)
):
    points = [
        (_to_utc(p.time), p.height) for p in payload.points
    ]
    db.replace_forecasts(port["id"], points)
    return db.list_forecasts(port["id"])


@app.get(
    "/ports/{port_id}/forecasts",
    response_model=list[ForecastPointOut],
    tags=["forecasts"],
)
def list_forecasts(port=Depends(get_port_or_404)):
    return db.list_forecasts(port["id"])


# ---------- navigation ----------

@app.post(
    "/ports/{port_id}/navigation-windows",
    response_model=NavigationResult,
    tags=["navigation"],
    summary="查询当前最新预报下的可出发时段",
)
def navigation_windows(
    payload: NavigationRequest, port=Depends(get_port_or_404)
) -> NavigationResult:
    rows = db.list_forecasts(port["id"])
    if len(rows) < 2:
        raise HTTPException(
            status_code=400,
            detail="该港口预报点不足 2 个, 无法进行线性插值计算, 请先 PUT 预报",
        )

    points = [
        TidePoint(time=_to_utc(datetime.fromisoformat(r["time"])),
                  height=r["height"])
        for r in rows
    ]
    duration = timedelta(minutes=payload.navigation_duration_minutes)

    try:
        windows = calculate_navigation_windows(
            points=points,
            chart_datum_depth=port["chart_datum_depth"],
            draft=payload.draft,
            under_keel_clearance=payload.under_keel_clearance,
            navigation_duration=duration,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    departure_windows = [
        DepartureWindowOut(
            window_start=w.window_start,
            window_end=w.window_end,
            depart_from=w.depart_from,
            depart_to=w.depart_to,
            window_duration_minutes=round(
                (w.window_end - w.window_start).total_seconds() / 60.0, 3
            ),
        )
        for w in windows
    ]
    earliest = departure_windows[0].depart_from if departure_windows else None

    return NavigationResult(
        port_id=port["id"],
        port_name=port["name"],
        required_depth=payload.draft + payload.under_keel_clearance,
        navigation_duration_minutes=payload.navigation_duration_minutes,
        coverage_start=points[0].time,
        coverage_end=points[-1].time,
        departure_windows=departure_windows,
        earliest_departure=earliest,
        count=len(departure_windows),
    )
