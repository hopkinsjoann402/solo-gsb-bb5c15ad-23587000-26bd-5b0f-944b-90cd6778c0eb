"""可选: 写入一个演示港口及 25 小时的整点潮高预报点。

幂等: 同名演示港口已存在时直接跳过。
关闭方式: 环境变量 ``SEED_DEMO=0``。

演示潮高 (米, 周期 12 小时):
    height(t) = 2.5 + 2.0 * sin(2π * t / 12)
基准水深 10.0 米; 吃水 11.5 米 + 富余 0.5 米时需要潮高 >= 2.0 米,
每天形成两个高潮窗口, 便于直接验证通航计算。
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone

from . import db

DEMO_PORT_NAME = "示例港"
DEMO_DATUM_DEPTH = 10.0


def _demo_points() -> list[tuple[datetime, float]]:
    start = datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)
    points: list[tuple[datetime, float]] = []
    for hour in range(25):  # 0..24 共 25 个整点, 覆盖 24 小时
        t = start + timedelta(hours=hour)
        height = 2.5 + 2.0 * math.sin(2.0 * math.pi * hour / 12.0)
        points.append((t, round(height, 4)))
    return points


def seed() -> None:
    db.init_db()
    existing = next(
        (p for p in db.list_ports() if p["name"] == DEMO_PORT_NAME), None
    )
    if existing is not None:
        print(f"[seed] 演示港口 '{DEMO_PORT_NAME}' 已存在 (id={existing['id']}), 跳过")
        return

    port = db.create_port(DEMO_PORT_NAME, DEMO_DATUM_DEPTH)
    db.replace_forecasts(port["id"], _demo_points())
    print(
        f"[seed] 已创建演示港口 '{DEMO_PORT_NAME}' (id={port['id']}, "
        f"基准水深 {DEMO_DATUM_DEPTH} 米), 写入 25 个整点潮高预报点"
    )


if __name__ == "__main__":
    if os.environ.get("SEED_DEMO", "1") not in ("0", "false", "False", ""):
        seed()
    else:
        print("[seed] SEED_DEMO=0, 跳过演示数据")
