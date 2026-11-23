"""Administrator-selected request backend and bounded portal history size."""
DEFAULT_RECENT_LIMIT = 10
MAX_RECENT_LIMIT = 100


def request_options(db):
    row = db.query_one("SELECT portal_request_backend, portal_request_recent_limit FROM settings WHERE id=1")
    values = dict(row) if row else {}
    backend = values.get('portal_request_backend') or 'arr'
    # Unknown values disable routing rather than selecting a different provider.
    if backend not in ('arr', 'seerr'):
        backend = None
    try:
        limit = max(1, min(MAX_RECENT_LIMIT, int(values.get('portal_request_recent_limit', DEFAULT_RECENT_LIMIT))))
    except (TypeError, ValueError):
        limit = DEFAULT_RECENT_LIMIT
    return backend, limit
