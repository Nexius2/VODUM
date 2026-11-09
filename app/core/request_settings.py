"""Request-scoped reads for presentation settings; never cache authorization."""
from flask import g, has_request_context, request
from db_manager import isolated_read_operation


@isolated_read_operation
def _load_presentation_settings(db):
    from core.i18n import GLOBAL_TEMPLATE_SETTINGS_COLUMNS
    return db.query_one(f'SELECT {GLOBAL_TEMPLATE_SETTINGS_COLUMNS} FROM settings WHERE id = 1')


def read_presentation_settings(db):
    # Mutating requests may render after saving settings: always read again.
    cacheable = has_request_context() and request.method in ('GET', 'HEAD')
    cache = getattr(g, '_presentation_settings', None) if cacheable else None
    if cache is not None and cache[0] is db:
        return dict(cache[1])
    row = _load_presentation_settings(db)
    value = dict(row) if row else {}
    if cacheable:
        g._presentation_settings = (db, value)
    return dict(value)
