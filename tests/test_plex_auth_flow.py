import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.plex_auth_flow import (
    PLEX_FLOW_SESSION_KEY,
    PlexFlowExpired,
    PlexFlowInvalid,
    PlexFlowMissing,
    begin_plex_flow,
    consume_plex_flow,
)


class PlexAuthFlowTests(unittest.TestCase):
    def test_valid_flow_is_single_use(self):
        store = {}
        flow = begin_plex_flow(store, pin_id=42, purpose="login", now=100)

        consumed = consume_plex_flow(
            store, returned_state=flow.state, expected_purpose="login", now=101
        )

        self.assertEqual(42, consumed.pin_id)
        self.assertNotIn(PLEX_FLOW_SESSION_KEY, store)
        with self.assertRaises(PlexFlowMissing):
            consume_plex_flow(
                store, returned_state=flow.state, expected_purpose="login", now=102
            )

    def test_invalid_state_is_consumed_before_rejection(self):
        store = {}
        flow = begin_plex_flow(store, pin_id=42, purpose="login", now=100)

        with self.assertRaises(PlexFlowInvalid):
            consume_plex_flow(
                store, returned_state="attacker-state",
                expected_purpose="login", now=101,
            )

        self.assertNotIn(PLEX_FLOW_SESSION_KEY, store)
        with self.assertRaises(PlexFlowMissing):
            consume_plex_flow(
                store, returned_state=flow.state, expected_purpose="login", now=102
            )

    def test_expired_and_wrong_purpose_flows_are_rejected(self):
        expired_store = {}
        expired = begin_plex_flow(
            expired_store, pin_id=42, purpose="login", now=100
        )
        with self.assertRaises(PlexFlowExpired):
            consume_plex_flow(
                expired_store, returned_state=expired.state,
                expected_purpose="login", now=701,
            )

        purpose_store = {}
        discovery = begin_plex_flow(
            purpose_store, pin_id=43, purpose="discover", now=100
        )
        with self.assertRaises(PlexFlowInvalid):
            consume_plex_flow(
                purpose_store, returned_state=discovery.state,
                expected_purpose="login", now=101,
            )


if __name__ == "__main__":
    unittest.main()
