"""Follow a Seerr request after submission: approval first, then availability.

Seerr keeps the request; VODUM only reads ``GET /api/v1/request/{id}`` for the
jobs a member can still see and stores the last state it learned.
"""
import time

from core import portal_media_requests as media_requests
from core.portal_media_requests import MediaRequestError, parallel_reads, _request_deadline
from core.portal_media_requests_seerr import FINAL_REQUEST_STATES, seerr_request_status
from logging_utils import get_logger

# One page load or poll waits at most this long for Seerr before showing the last known state.
REFRESH_BUDGET_SECONDS = 6
STATE_REMOVED = 'removed'


def _state_from_outcome(outcome):
    if isinstance(outcome, MediaRequestError):
        # A request deleted in Seerr has nothing left to follow.
        return STATE_REMOVED if getattr(outcome, 'http_status', None) == 404 else None
    return outcome


def refresh_seerr_states(db, jobs):
    """Update ``seerr_state`` in place and in the database for stale, unfinished Seerr requests."""
    due = [job for job in jobs
           if job.get('status') == 'done' and job.get('source') == 'seerr' and job.get('stale')
           and type(job.get('seerr_request_id')) is int and job.get('seerr_server_id') is not None
           and job.get('seerr_state') not in FINAL_REQUEST_STATES + (STATE_REMOVED,)]
    if not due:
        return
    server_ids = sorted({job['seerr_server_id'] for job in due})
    servers = {row['id']: dict(row) for row in db.query(
        "SELECT * FROM servers WHERE LOWER(type) = 'seerr' AND id IN (%s)" % ','.join('?' * len(server_ids)),
        server_ids)}
    due = [job for job in due if job['seerr_server_id'] in servers]
    token = _request_deadline.set(time.monotonic() + REFRESH_BUDGET_SECONDS)
    try:
        outcomes = parallel_reads([
            lambda job=job: seerr_request_status(media_requests.api, servers[job['seerr_server_id']], job['seerr_request_id'])
            for job in due])
    except Exception:
        get_logger('portal_media_request_tracking').exception('Seerr request state refresh failed')
        return
    finally:
        _request_deadline.reset(token)
    for job, outcome in zip(due, outcomes):
        state = _state_from_outcome(outcome)
        if state is not None:
            job['seerr_state'] = state
        # A failed read still counts as a check, so a slow Seerr is not asked again on the next poll.
        db.execute("""
            UPDATE portal_media_request_jobs SET seerr_state = COALESCE(?, seerr_state),
                seerr_checked_at = CURRENT_TIMESTAMP WHERE id = ?
        """, (state, job['id']))
