"""Follow a Seerr request after submission: approval first, then availability.

Seerr keeps the request; VODUM only reads ``GET /api/v1/request/{id}`` for the
jobs a member can still see and stores the last state it learned.
"""
import time

from core import portal_media_requests as media_requests
from core.portal_media_requests import MediaRequestError, parallel_reads, _request_deadline
from core.portal_media_requests_seerr import (FINAL_REQUEST_STATES, seerr_find_user, seerr_request_result,
                                              seerr_request_state, seerr_request_status, seerr_user_lookup_keys)
from core.portal_media_requests_tvdb import find_existing_request
from logging_utils import get_logger

# One page load or poll waits at most this long for Seerr before showing the last known state.
REFRESH_BUDGET_SECONDS = 3
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


def reconcile_uncertain_seerr_jobs(db, account_id, jobs):
    """Attach the Seerr request id to jobs whose POST answer was lost.

    Looks for a request of the same Seerr user, TMDB id and 4K flag; once found,
    the job gets its id, state and a proper result, so the portal can follow it.
    Each job is tried at most once per minute (``seerr_checked_at``).
    """
    due = [job for job in jobs
           if job.get('status') == 'done' and job.get('source') == 'seerr' and job.get('stale')
           and job.get('result') == 'portal_requests_add_uncertain'
           and job.get('seerr_request_id') is None and job.get('seerr_server_id') is not None]
    if not due:
        return
    try:
        identity = db.query("SELECT type, external_user_id FROM media_users WHERE vodum_user_id = "
                            "(SELECT vodum_user_id FROM portal_accounts WHERE id = ?) "
                            "AND LOWER(type) IN ('plex','jellyfin')", (account_id,)) or []
        keys = seerr_user_lookup_keys([dict(row) for row in identity])
        token = _request_deadline.set(time.monotonic() + REFRESH_BUDGET_SECONDS)
        try:
            for job in due:
                server = db.query_one("SELECT * FROM servers WHERE LOWER(type) = 'seerr' AND id = ?",
                                      (job['seerr_server_id'],))
                found = None
                if server is not None:
                    server = dict(server)
                    try:
                        user = seerr_find_user(media_requests.api, server, keys)
                        if user is not None:
                            found = find_existing_request(media_requests.api, server, user['id'], job['kind'],
                                                          job['external_id'], bool(job.get('is_4k')))
                    except MediaRequestError:
                        found = None
                if found is None:
                    db.execute("UPDATE portal_media_request_jobs SET seerr_checked_at = CURRENT_TIMESTAMP WHERE id = ?",
                               (job['id'],))
                    continue
                state = seerr_request_state(found)
                result = seerr_request_result(found) or 'portal_requests_added'
                db.execute("""
                    UPDATE portal_media_request_jobs SET seerr_request_id = ?, seerr_state = ?, result = ?,
                        seerr_checked_at = CURRENT_TIMESTAMP WHERE id = ? AND seerr_request_id IS NULL
                """, (found['id'], state, result, job['id']))
                job.update({'seerr_request_id': found['id'], 'seerr_state': state, 'result': result})
        finally:
            _request_deadline.reset(token)
    except Exception:
        get_logger('portal_media_request_tracking').exception('Seerr request reconciliation failed')
