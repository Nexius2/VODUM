"""Request-scoped reads for presentation settings; never cache authorization."""
from flask import g, has_request_context, request


def read_presentation_settings(db):
    # Mutating requests may render after saving settings: always read again.
    from core.i18n import GLOBAL_TEMPLATE_SETTINGS_COLUMNS
    cacheable = has_request_context() and request.method in ('GET', 'HEAD')
    cache = getattr(g, '_presentation_settings', None) if cacheable else None
    if cache is not None and cache[0] is db:
        return dict(cache[1])
    row = db.query_one(f'SELECT {GLOBAL_TEMPLATE_SETTINGS_COLUMNS} FROM settings WHERE id = 1')
    value = dict(row) if row else {}
    if cacheable:
        g._presentation_settings = (db, value)
    return dict(value)
