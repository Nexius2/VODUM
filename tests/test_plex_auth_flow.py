import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.plex_auth_flow import (
    PLEX_FLOW_SESSION_KEY,
    PlexFlowRejected,
    begin_plex_flow,
    consume_plex_flow,
)


class PlexAuthFlowTests(unittest.TestCase):
    def test_flow_is_bound_to_session_state_and_consumed_once(self):
        session = {}
        flow = begin_plex_flow(session, pin_id=42, purpose="link", now=100)
        self.assertGreaterEqual(len(flow.state), 32)

        consumed = consume_plex_flow(
            session, returned_state=flow.state, expected_purpose="link", now=101
        )
        self.assertEqual(42, consumed.pin_id)
        self.assertNotIn(PLEX_FLOW_SESSION_KEY, session)
        with self.assertRaises(PlexFlowRejected):
            consume_plex_flow(session, returned_state=flow.state, now=102)

    def test_wrong_state_is_rejected_and_invalidates_flow(self):
        session = {}
        begin_plex_flow(session, pin_id=42, purpose="login", now=100)
        with self.assertRaises(PlexFlowRejected):
            consume_plex_flow(session, returned_state="attacker", now=101)
        self.assertNotIn(PLEX_FLOW_SESSION_KEY, session)

    def test_expired_future_and_wrong_purpose_are_rejected(self):
        cases = (
            ({"now": 701}, {}),
            ({"now": 99}, {}),
            ({"now": 101}, {"expected_purpose": "replace"}),
        )
        for consume_args, extra in cases:
            with self.subTest(consume_args=consume_args, extra=extra):
                session = {}
                flow = begin_plex_flow(session, pin_id=1, purpose="link", now=100)
                with self.assertRaises(PlexFlowRejected):
                    consume_plex_flow(
                        session,
                        returned_state=flow.state,
                        **consume_args,
                        **extra,
                    )


if __name__ == "__main__":
    unittest.main()
