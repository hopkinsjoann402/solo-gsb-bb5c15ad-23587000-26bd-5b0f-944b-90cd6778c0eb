"""潮汐通航窗口核心算法。

规则:
- 相邻潮高预报点之间按线性插值求潮高。
- 只在预报覆盖时段 ``[第一个点, 最后一个点]`` 内计算。
- 实际水深 = 潮高 + 航道基准水深; 水深 >= 吃水 + 安全富余 即达标 (端点恰好达标纳入)。
- 跨相邻插值线段且彼此相接(含端点重合)的达标时段合并为连续窗口。
- 每个达标窗口的结束时刻减去所需通航时长, 得到该窗口的可出发时段;
  不足所需时长的窗口舍弃。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel


class TidePoint(BaseModel):
    """单个潮高预报点。"""

    time: datetime
    height: float  # 潮高 (米)


@dataclass(frozen=True)
class NavWindow:
    """一个连续通航窗口及其可出发时段。"""

    window_start: datetime
    window_end: datetime
    depart_from: datetime  # = window_end - navigation_duration

    @property
    def depart_to(self) -> datetime:
        """可出发时段的右端点, 即窗口结束时刻 (恰好出发也来得及)。"""
        return self.window_end


def _merge_intervals(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """把相接或重叠的闭区间合并 (end1 == start2 也算连续)。"""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda iv: iv[0])
    merged: list[tuple[datetime, datetime]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _eligible_intervals_for_segment(
    t0: datetime,
    h0: float,
    t1: datetime,
    h1: float,
    datum: float,
    required_depth: float,
) -> list[tuple[datetime, datetime]]:
    """求一条插值线段 [t0, t1] 内水深 >= required_depth 的闭子区间。

    端点恰好达标也纳入。平潮线段 (h0 == h1) 单独处理。
    """
    d0 = h0 + datum
    d1 = h1 + datum

    if h0 == h1:
        # 平潮: 整条线段水深一致
        if d0 >= required_depth:
            return [(t0, t1)]
        return []

    if d0 >= required_depth and d1 >= required_depth:
        return [(t0, t1)]

    if d0 < required_depth and d1 < required_depth:
        return []

    # 一端达标、一端不达标: 线性求解临界时刻 t*
    # depth(t*) = d0 + (d1 - d0) * f = required_depth
    f = (required_depth - d0) / (d1 - d0)
    # 浮点保护: 理论上 0 < f < 1
    if not (0.0 < f < 1.0):
        # 退化为端点判断, 避免产生零长度/方向异常区间
        out: list[tuple[datetime, datetime]] = []
        if d0 >= required_depth:
            out.append((t0, t0))
        if d1 >= required_depth:
            out.append((t1, t1))
        return out

    span = (t1 - t0).total_seconds()
    t_star = t0 + timedelta(seconds=span * f)

    if d0 >= required_depth:
        return [(t0, t_star)]
    return [(t_star, t1)]


def calculate_navigation_windows(
    points: list[TidePoint],
    chart_datum_depth: float,
    draft: float,
    under_keel_clearance: float,
    navigation_duration: timedelta,
) -> list[NavWindow]:
    """计算全部达标连续窗口及其可出发时段。

    参数
    ----
    points:
        潮高预报点 (时间, 潮高/米), 顺序无所谓, 内部按时间排序。
        预报点被更正后, 调用方传入最新数据即可, 本函数无任何缓存。
    chart_datum_depth:
        航道基准水深 (米, 相对于同一潮高基准面)。
    draft:
        船舶吃水 (米, 必须为正)。
    under_keel_clearance:
        安全富余水深 (米, 必须 >= 0)。
    navigation_duration:
        一次通航所需时长 (必须为正)。

    返回
    ----
    按窗口开始时刻升序排列的 :class:`NavWindow`; 不足所需时长的窗口已舍弃。
    """
    if draft <= 0:
        raise ValueError("draft 必须为正数")
    if under_keel_clearance < 0:
        raise ValueError("under_keel_clearance 不能为负数")
    if navigation_duration <= timedelta(0):
        raise ValueError("navigation_duration 必须为正数")
    if chart_datum_depth <= 0:
        raise ValueError("chart_datum_depth 必须为正数")

    ordered = sorted(points, key=lambda p: p.time)
    # 同时刻点只保留最后一条 (与入库更新语义一致)
    deduped: list[TidePoint] = []
    for p in ordered:
        if deduped and deduped[-1].time == p.time:
            deduped[-1] = p
        else:
            deduped.append(p)

    if len(deduped) < 2:
        raise ValueError("至少需要 2 个不同时刻的预报点才能插值计算")

    required_depth = draft + under_keel_clearance

    raw_intervals: list[tuple[datetime, datetime]] = []
    for i in range(len(deduped) - 1):
        a, b = deduped[i], deduped[i + 1]
        if a.time == b.time:
            continue
        raw_intervals.extend(
            _eligible_intervals_for_segment(
                a.time,
                a.height,
                b.time,
                b.height,
                chart_datum_depth,
                required_depth,
            )
        )

    windows: list[NavWindow] = []
    for win_start, win_end in _merge_intervals(raw_intervals):
        length = win_end - win_start
        if length < navigation_duration:
            # 不足所需通航时长, 舍弃
            continue
        depart_from = win_end - navigation_duration
        windows.append(
            NavWindow(
                window_start=win_start,
                window_end=win_end,
                depart_from=depart_from,
            )
        )

    windows.sort(key=lambda w: w.window_start)
    return windows
