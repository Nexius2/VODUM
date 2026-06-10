from __future__ import annotations

import unittest

from app.core.dashboard_servers import DASHBOARD_SERVER_LIMIT, dashboard_server_preview


class DashboardServerPreviewTests(unittest.TestCase):
    def test_online_servers_are_first_then_sorted_by_peak(self):
        servers = [
            {"name": "Offline high", "status": "down", "peak_streams_7d": 99},
            {"name": "Online low", "status": "up", "peak_streams_7d": 2},
            {"name": "Online high", "status": "up", "peak_streams_7d": 8},
            {"name": "Offline low", "status": "down", "peak_streams_7d": 1},
        ]

        preview = dashboard_server_preview(servers)

        self.assertEqual(
            [server["name"] for server in preview],
            ["Online high", "Online low", "Offline high", "Offline low"],
        )

    def test_preview_is_limited_to_six_servers(self):
        servers = [
            {"name": f"Server {index}", "status": "up", "peak_streams_7d": index}
            for index in range(10)
        ]

        preview = dashboard_server_preview(servers)

        self.assertEqual(len(preview), DASHBOARD_SERVER_LIMIT)
        self.assertEqual(preview[0]["name"], "Server 9")


if __name__ == "__main__":
    unittest.main()
