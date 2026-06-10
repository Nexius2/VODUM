from __future__ import annotations

import unittest
from datetime import date

from app.core.dashboard_usage_risk import build_usage_risk_trend


class DashboardUsageRiskTrendTests(unittest.TestCase):
    def test_builds_daily_active_recommendation_counts(self):
        rows = [
            {
                "vodum_user_id": 1,
                "first_detected_at": "2026-06-01 10:00:00",
                "last_detected_at": "2026-06-03 10:00:00",
            },
            {
                "vodum_user_id": 2,
                "first_detected_at": "2026-06-02 10:00:00",
                "last_detected_at": "2026-06-04 10:00:00",
            },
        ]

        trend = build_usage_risk_trend(
            rows,
            current_count=1,
            days=5,
            today=date(2026, 6, 5),
        )

        self.assertEqual(trend["values"], [1, 2, 2, 1, 1])
        self.assertIn("C ", trend["line_path"])
        self.assertTrue(trend["area_path"].endswith("Z"))

    def test_last_point_matches_current_dashboard_value(self):
        trend = build_usage_risk_trend([], current_count=7)

        self.assertEqual(trend["values"][-1], 7)
        self.assertEqual(trend["max_value"], 7)


if __name__ == "__main__":
    unittest.main()
