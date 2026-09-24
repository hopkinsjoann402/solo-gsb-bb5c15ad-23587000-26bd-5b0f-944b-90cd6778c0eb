"""核心算法单元测试 (仅依赖标准库 + pydantic)。"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from app.algorithm import TidePoint, calculate_navigation_windows

# 航道基准水深 10 米, 要求潮高 >= 2 米 (吃水 11.5 + 富余 0.5)
DATUM = 10.0
DRAFT = 11.5
UKC = 0.5  # under keel clearance


def pt(hour: float, height: float) -> TidePoint:
    t = datetime(2026, 9, 24, 0, 0) + timedelta(hours=hour)
    return TidePoint(time=t, height=height)


class NavigationWindowTests(unittest.TestCase):
    def test_single_window_linear_interpolation_and_endpoint_inclusive(self):
        # 0:00 潮高0 -> 4:00 潮高4 (2 点在 2:00); 6:00 恰好=2 (达标端点);
        # 之后降回 0。达标窗口应为 [2:00, 6:00], 恰好 4 小时。
        points = [pt(0, 0), pt(4, 4), pt(6, 2), pt(8, 0), pt(12, 0)]
        windows = calculate_navigation_windows(
            points, DATUM, DRAFT, UKC, timedelta(hours=4)
        )
        self.assertEqual(1, len(windows))
        w = windows[0]
        self.assertEqual(pt(2, 0).time, w.window_start)
        self.assertEqual(pt(6, 0).time, w.window_end)  # 恰好达标端点纳入
        self.assertEqual(pt(2, 0).time, w.depart_from)  # 6:00 - 4h
        self.assertEqual(w.window_end, w.depart_to)

    def test_window_exactly_equal_duration_is_kept(self):
        points = [pt(0, 0), pt(4, 4), pt(6, 2), pt(8, 0)]
        windows = calculate_navigation_windows(
            points, DATUM, DRAFT, UKC, timedelta(hours=4)
        )
        self.assertEqual(1, len(windows))

    def test_window_shorter_than_duration_discarded(self):
        points = [pt(0, 0), pt(4, 4), pt(6, 2), pt(8, 0)]
        windows = calculate_navigation_windows(
            points, DATUM, DRAFT, UKC, timedelta(hours=4, minutes=1)
        )
        self.assertEqual(0, len(windows))

    def test_departure_period_is_end_minus_duration(self):
        points = [pt(0, 0), pt(4, 4), pt(6, 2), pt(8, 0)]
        windows = calculate_navigation_windows(
            points, DATUM, DRAFT, UKC, timedelta(hours=3)
        )
        self.assertEqual(1, len(windows))
        self.assertEqual(pt(3, 0).time, windows[0].depart_from)
        self.assertEqual(pt(6, 0).time, windows[0].depart_to)

    def test_flat_segment_at_threshold_included(self):
        # 0:00-4:00 平潮恰好 2 米: 整条线段达标 (含两端);
        # 4:00 后下降, 4:00 仍是达标端点。
        points = [pt(0, 2), pt(4, 2), pt(8, 0)]
        windows = calculate_navigation_windows(
            points, DATUM, DRAFT, UKC, timedelta(hours=4)
        )
        self.assertEqual(1, len(windows))
        self.assertEqual(pt(0, 0).time, windows[0].window_start)
        self.assertEqual(pt(4, 0).time, windows[0].window_end)

    def test_two_separate_windows_and_earliest_departure(self):
        # 高潮在两端, 中间低潮: 两个各 2 小时的窗口
        points = [pt(0, 4), pt(4, 0), pt(8, 4)]
        windows = calculate_navigation_windows(
            points, DATUM, DRAFT, UKC, timedelta(hours=2)
        )
        self.assertEqual(2, len(windows))
        self.assertEqual(pt(0, 0).time, windows[0].window_start)
        self.assertEqual(pt(2, 0).time, windows[0].window_end)
        self.assertEqual(pt(6, 0).time, windows[1].window_start)
        self.assertEqual(pt(8, 0).time, windows[1].window_end)
        # 最早出发时刻 = 第一个窗口的 depart_from
        self.assertEqual(pt(0, 0).time, windows[0].depart_from)

    def test_all_windows_too_short_returns_empty(self):
        points = [pt(0, 4), pt(4, 0), pt(8, 4)]
        windows = calculate_navigation_windows(
            points, DATUM, DRAFT, UKC, timedelta(minutes=130)
        )
        self.assertEqual([], windows)

    def test_no_window_below_threshold(self):
        points = [pt(0, 0), pt(4, 1.9), pt(8, 0)]
        windows = calculate_navigation_windows(
            points, DATUM, DRAFT, UKC, timedelta(minutes=10)
        )
        self.assertEqual([], windows)

    def test_unsorted_and_duplicate_times_handled(self):
        points = [pt(8, 0), pt(0, 0), pt(6, 2), pt(4, 4), pt(4, 5)]
        # 同时刻两条, 后者(5)生效: 0->4 线段端点为5, 2 米交点在 1.6h
        windows = calculate_navigation_windows(
            points, DATUM, DRAFT, UKC, timedelta(hours=4)
        )
        self.assertEqual(1, len(windows))
        self.assertAlmostEqual(
            pt(1.6, 0).time, windows[0].window_start, delta=timedelta(seconds=1)
        )

    def test_validation_errors(self):
        good = [pt(0, 0), pt(4, 4)]
        with self.assertRaises(ValueError):
            calculate_navigation_windows(
                good, DATUM, 0, UKC, timedelta(hours=1)
            )  # 吃水非正
        with self.assertRaises(ValueError):
            calculate_navigation_windows(
                good, DATUM, DRAFT, -0.1, timedelta(hours=1)
            )  # 富余为负
        with self.assertRaises(ValueError):
            calculate_navigation_windows(
                good, DATUM, DRAFT, UKC, timedelta(0)
            )  # 时长非正
        with self.assertRaises(ValueError):
            calculate_navigation_windows(
                [pt(0, 1)], DATUM, DRAFT, UKC, timedelta(hours=1)
            )  # 不足两个点


if __name__ == "__main__":
    unittest.main()
