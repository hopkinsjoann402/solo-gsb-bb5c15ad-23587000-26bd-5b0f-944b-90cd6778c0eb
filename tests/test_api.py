"""API 端到端冒烟测试。

需要 fastapi + httpx (TestClient); 环境缺失时自动跳过。
运行: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name  # 必须在导入 app.db 之前设置

try:
    from fastapi.testclient import TestClient  # noqa: E402

    from app import db  # noqa: E402
    from app.main import app  # noqa: E402

    _DEPS = True
except ImportError:  # pragma: no cover
    _DEPS = False


@unittest.skipUnless(_DEPS, "fastapi/httpx 未安装, 跳过 API 冒烟测试")
class ApiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        db.init_db()
        cls.client = TestClient(app)

    def test_full_flow_and_forecast_correction(self):
        client = self.client

        # 健康检查
        self.assertEqual(200, client.get("/health").status_code)

        # 建港: 基准水深 10 米
        r = client.post(
            "/ports", json={"name": "冒烟港", "chart_datum_depth": 10.0}
        )
        self.assertEqual(201, r.status_code, r.text)
        port_id = r.json()["id"]

        # 录入预报: 0:00 潮高0 升到 4:00 潮高4, 6:00 恰好2, 8:00 回落0
        body = {
            "points": [
                {"time": "2026-09-24T00:00:00", "height": 0},
                {"time": "2026-09-24T04:00:00", "height": 4},
                {"time": "2026-09-24T06:00:00", "height": 2},
                {"time": "2026-09-24T08:00:00", "height": 0},
            ]
        }
        r = client.put(f"/ports/{port_id}/forecasts", json=body)
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(4, len(r.json()))

        # 查询: 吃水 11.5 + 富余 0.5, 通航 4 小时 -> 窗口 [02:00,06:00]
        r = client.post(
            f"/ports/{port_id}/navigation-windows",
            json={
                "draft": 11.5,
                "under_keel_clearance": 0.5,
                "navigation_duration_minutes": 240,
            },
        )
        self.assertEqual(200, r.status_code, r.text)
        data = r.json()
        self.assertEqual(1, data["count"])
        self.assertEqual(
            datetime.fromisoformat("2026-09-24T02:00:00+00:00"),
            datetime.fromisoformat(data["earliest_departure"]),
        )
        w = data["departure_windows"][0]
        self.assertEqual(
            datetime.fromisoformat("2026-09-24T06:00:00+00:00"),
            datetime.fromisoformat(w["depart_to"]),
        )

        # 预报更正: 高潮只有 3 米:
        #   上升段 0:00(0)->4:00(3), 2 米交点在 02:40
        #   6:00 恰好=2 达标, 之后 6:00->8:00 继续下降
        # 故达标窗口 [02:40, 06:00], 共 200 分钟; 通航 4 小时(240分)应被舍弃
        body["points"][1]["height"] = 3
        r = client.put(f"/ports/{port_id}/forecasts", json=body)
        self.assertEqual(200, r.status_code, r.text)
        r = client.post(
            f"/ports/{port_id}/navigation-windows",
            json={
                "draft": 11.5,
                "under_keel_clearance": 0.5,
                "navigation_duration_minutes": 240,
            },
        )
        data = r.json()
        self.assertEqual(0, data["count"])
        self.assertIsNone(data["earliest_departure"])

        # 缩短通航时长到 200 分钟: 窗口恰好够长, 保留
        r = client.post(
            f"/ports/{port_id}/navigation-windows",
            json={
                "draft": 11.5,
                "under_keel_clearance": 0.5,
                "navigation_duration_minutes": 200,
            },
        )
        data = r.json()
        self.assertEqual(1, data["count"])
        self.assertEqual(
            datetime.fromisoformat("2026-09-24T02:40:00+00:00"),
            datetime.fromisoformat(
                data["departure_windows"][0]["window_start"]
            ),
        )
        self.assertEqual(
            datetime.fromisoformat("2026-09-24T06:00:00+00:00"),
            datetime.fromisoformat(
                data["departure_windows"][0]["window_end"]
            ),
        )

    def test_404_and_validation(self):
        client = self.client
        self.assertEqual(404, client.get("/ports/999999").status_code)
        r = client.post("/ports", json={"name": "x", "chart_datum_depth": -1})
        self.assertEqual(422, r.status_code)


if __name__ == "__main__":
    unittest.main()
