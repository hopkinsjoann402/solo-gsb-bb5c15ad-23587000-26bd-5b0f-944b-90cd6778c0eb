"""SQLite 访问层。

使用标准库 ``sqlite3``; 服务以单进程 uvicorn 启动, 用一把进程内 RLock
串行化写事务并配合 ``WAL``, 足以支撑本 API 的并发只读查询。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "/data/tides.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL UNIQUE,
    chart_datum_depth REAL NOT NULL CHECK (chart_datum_depth > 0),
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tide_forecasts (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    port_id INTEGER NOT NULL REFERENCES ports(id) ON DELETE CASCADE,
    time    TEXT NOT NULL,
    height  REAL NOT NULL,
    UNIQUE (port_id, time)
);

CREATE INDEX IF NOT EXISTS idx_forecasts_port_time
    ON tide_forecasts (port_id, time);
"""

_lock = threading.RLock()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_path() -> str:
    return DB_PATH


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db() -> None:
    """建表 (幂等)。数据库文件所在目录不存在时自动创建。"""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _lock, connect() as conn:
        conn.executescript(_SCHEMA)


# ---------- ports ----------

def create_port(name: str, chart_datum_depth: float) -> dict:
    with _lock, connect() as conn:
        cur = conn.execute(
            "INSERT INTO ports (name, chart_datum_depth, created_at) "
            "VALUES (?, ?, ?)",
            (name, chart_datum_depth, utc_now_iso()),
        )
        port_id = cur.lastrowid
    row = get_port(port_id)
    assert row is not None
    return row


def list_ports() -> list[dict]:
    with connect() as conn:
        return [
            dict(r)
            for r in conn.execute("SELECT * FROM ports ORDER BY id")
        ]


def get_port(port_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM ports WHERE id = ?", (port_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def delete_port(port_id: int) -> bool:
    with _lock, connect() as conn:
        cur = conn.execute("DELETE FROM ports WHERE id = ?", (port_id,))
        return cur.rowcount > 0


# ---------- tide forecasts ----------

def replace_forecasts(
    port_id: int, points: list[tuple[datetime, float]]
) -> None:
    """整组替换某港口的预报点。

    在一个事务内 ``DELETE + INSERT``: 查询要么看到旧数据、要么看到新数据,
    因此"预报点更正后按最新数据重算"天然成立。
    """
    payload = [
        (_normalize_utc(t).isoformat(), float(h)) for t, h in points
    ]
    with _lock, connect() as conn:
        conn.execute("DELETE FROM tide_forecasts WHERE port_id = ?", (port_id,))
        conn.executemany(
            "INSERT INTO tide_forecasts (port_id, time, height) "
            "VALUES (?, ?, ?)",
            [(port_id, t, h) for t, h in payload],
        )


def list_forecasts(port_id: int) -> list[dict]:
    """按时间升序返回某港口全部最新预报点。"""
    with connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM tide_forecasts WHERE port_id = ? ORDER BY time",
                (port_id,),
            )
        ]


def _normalize_utc(dt: datetime) -> datetime:
    """无时区时间按 UTC 处理; 带时区时间统一转 UTC。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
