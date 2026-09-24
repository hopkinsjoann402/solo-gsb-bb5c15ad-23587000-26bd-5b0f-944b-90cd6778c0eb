"""Pydantic 请求 / 响应模型。"""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .algorithm import TidePoint


class PortCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128, description="港口名称")
    chart_datum_depth: float = Field(
        gt=0, description="航道基准水深 (米, 相对潮高基准面)"
    )


class PortOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    chart_datum_depth: float
    created_at: datetime


class ForecastPointIn(BaseModel):
    time: datetime = Field(description="预报时刻 (无时区按 UTC 处理)")
    height: float = Field(description="潮高预报值 (米)")


class ForecastReplace(BaseModel):
    """整组替换某港口的潮高预报点 (更正预报即重新提交)。"""

    points: list[ForecastPointIn] = Field(min_length=2)

    @field_validator("points")
    @classmethod
    def _distinct_times(cls, v: list[ForecastPointIn]) -> list[ForecastPointIn]:
        times = [p.time for p in v]
        if len(set(times)) != len(times):
            raise ValueError("预报点时刻不能重复")
        return v


class ForecastPointOut(ForecastPointIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    port_id: int


class NavigationRequest(BaseModel):
    draft: float = Field(gt=0, description="船舶吃水 (米)")
    under_keel_clearance: float = Field(
        ge=0, description="安全富余水深 (米), 可为 0"
    )
    navigation_duration_minutes: float = Field(
        gt=0, description="一次通航所需时长 (分钟, 正数)"
    )


class DepartureWindowOut(BaseModel):
    window_start: datetime = Field(description="连续达标窗口开始 (UTC)")
    window_end: datetime = Field(description="连续达标窗口结束 (UTC)")
    depart_from: datetime = Field(description="可出发时段起点 (UTC)")
    depart_to: datetime = Field(description="可出发时段终点 (UTC)")
    window_duration_minutes: float = Field(description="达标窗口时长 (分钟)")


class NavigationResult(BaseModel):
    port_id: int
    port_name: str
    required_depth: float = Field(description="吃水 + 安全富余 (米)")
    navigation_duration_minutes: float
    coverage_start: datetime = Field(description="预报覆盖开始 (UTC)")
    coverage_end: datetime = Field(description="预报覆盖结束 (UTC)")
    departure_windows: list[DepartureWindowOut]
    earliest_departure: datetime | None = Field(
        default=None, description="最早可出发时刻 (UTC), 无窗口时为 null"
    )
    count: int


__all__ = [
    "TidePoint",
    "PortCreate",
    "PortOut",
    "ForecastPointIn",
    "ForecastReplace",
    "ForecastPointOut",
    "NavigationRequest",
    "DepartureWindowOut",
    "NavigationResult",
    "timedelta",
]
