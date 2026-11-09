"""Opt-in, installation-level language observations, without visitor identifiers."""
import json
import re
import sqlite3
from pathlib import Path


def language_code(value):
    value = str(value or '').strip().lower().replace('_', '-')
    return value if re.fullmatch(r'[a-z]{2,3}(?:-[a-z]{4})?(?:-[a-z]{2}|-[0-9]{3})?', value) else 'unknown'


def configured_language(value):
    return language_code(value) if str(value or '').strip() else 'auto'


def observe(db, settings, displayed, request):
    if settings.get('enable_anonymous_telemetry') not in (1, True):
        return
    if request.headers.get('HX-Request') == 'true':
        return  # Full page renders already observe the same visitor preference.
    # The best preference, not the best supported match. Never store the header.
    preferred = next((code for code, quality in request.accept_languages if quality > 0), None)
    browser = language_code(preferred)
    scope = 'portal' if request.path == '/portal' or request.path.startswith('/portal/') else 'admin'
    from db_manager import DBManager
    if isinstance(db, DBManager):
        # Optional statistics must never wait for the application's writer lock
        # or another SQLite writer. Retry naturally on the next full page view.
        connection = sqlite3.connect(Path(db.db_path).absolute().as_uri() + '?mode=rw',
                                     uri=True, timeout=0)
        try:
            with connection:
                _store_observation(connection, scope, settings, browser, displayed)
        except sqlite3.OperationalError as exc:
            if 'locked' not in str(exc).lower() and 'busy' not in str(exc).lower():
                raise
        finally:
            connection.close()
    else:
        _store_observation(db, scope, settings, browser, displayed)


def _store_observation(db, scope, settings, browser, displayed):
    db.execute("""DELETE FROM telemetry_language_observations WHERE day < date('now','-30 days')""")
    db.execute("""INSERT OR IGNORE INTO telemetry_language_observations
        (day,scope,configured,browser,displayed)
        SELECT date('now'),?,?,?,? WHERE
        (SELECT COUNT(*) FROM telemetry_language_observations WHERE day=date('now')) < 32""",
        (scope, configured_language(settings.get('default_language')), browser, language_code(displayed)))


def observations(db):
    rows = db.query("""SELECT DISTINCT scope,configured,browser,displayed
        FROM telemetry_language_observations WHERE day >= date('now','-30 days')
        ORDER BY scope,configured,browser,displayed LIMIT 32""")
    return json.dumps([dict(row) for row in rows], separators=(',', ':'))
