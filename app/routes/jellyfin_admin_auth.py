import hashlib
import secrets
import time

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for

from core.admin_auth_identities import get_admin_auth_identity, link_admin_auth_identity
from core.admin_jellyfin_auth import (
    JellyfinAdminAuthError, JellyfinApprovalPending, JellyfinQuickConnectClient, decode_binding,
)
from core.auth_principal import open_admin_session
from core.setup_wizard_servers import create_setup_media_server, record_setup_media_servers
from core.setup_wizard_state import (
    decode_setup_wizard_state, load_setup_wizard_settings, save_setup_wizard_progress,
    should_resume_setup_wizard,
)
from logging_utils import get_logger
from secret_store import decrypt_secret, encrypt_secret
from web.helpers import get_db
from web.security import get_client_ip

FLOW_KEY = 'vodum_jellyfin_admin_flow'
FLOW_TTL = 5 * 60
logger = get_logger('auth')


def _nonce_hash(flow):
    return hashlib.sha256(str((flow or {}).get('nonce') or '').encode()).hexdigest()


def _consume(db, flow, *, require_valid=False):
    if not isinstance(flow, dict) or not flow.get('nonce'):
        return False
    result = db.execute("DELETE FROM admin_auth_flows WHERE nonce_hash=? AND provider='jellyfin' AND expires_at>=?",
                        (_nonce_hash(flow), int(time.time()) if require_valid else 0))
    return result.rowcount == 1


def _rate_allowed(db, *, charge=True):
    from datetime import datetime, timezone
    from routes.auth import _is_login_locked, _register_failed_login
    now = datetime.now(timezone.utc)
    address = get_client_ip()
    if _is_login_locked(db, 'ip', address, now)[0]:
        return False
    if charge:
        _register_failed_login(db, 'ip', address, now)
    return True


def _wizard_available(db):
    settings = load_setup_wizard_settings(db)
    return (int(settings.get('wizard_active') or 0) == 1
            and int(settings.get('wizard_completed') or 0) != 1
            and int(settings.get('wizard_step') or 1) == 2)


def _start(db, url, purpose, identity=None):
    _consume(db, session.pop(FLOW_KEY, None))
    if not _rate_allowed(db):
        raise JellyfinAdminAuthError('plex_auth_rate_limited')
    client = JellyfinQuickConnectClient(url)
    try:
        pin = client.start()
        if identity and pin['server_id'] != decode_binding(identity['provider_subject'])[1]:
            raise JellyfinAdminAuthError('jellyfin_admin_failed')
        flow = {
            'purpose': purpose, 'url': client.url, 'server_id': pin['server_id'],
            'code': pin['code'], 'secret_enc': encrypt_secret(pin['secret']),
            'device_id': pin['device_id'], 'started_at': time.time(),
            'identity_id': identity['id'] if identity else None,
            'subject': identity['provider_subject'] if identity else None,
            'nonce': secrets.token_urlsafe(32),
        }
        db.execute('DELETE FROM admin_auth_flows WHERE expires_at < ?', (int(time.time()),))
        db.execute("INSERT INTO admin_auth_flows(nonce_hash,provider,expires_at) VALUES(?,'jellyfin',?)",
                   (_nonce_hash(flow), int(flow['started_at'] + FLOW_TTL)))
        session[FLOW_KEY] = flow
    finally:
        client.close()


def start_wizard_jellyfin_link(db, url):
    if not _wizard_available(db):
        abort(403)
    try:
        _start(db, url, 'wizard')
    except JellyfinAdminAuthError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('setup_wizard', resume='wizard'))
    return redirect(url_for('jellyfin_admin_wizard'))


def _flow(db, purpose):
    flow = session.get(FLOW_KEY)
    if not isinstance(flow, dict) or flow.get('purpose') != purpose:
        raise JellyfinAdminAuthError('jellyfin_admin_expired')
    try:
        valid = 0 <= time.time() - float(flow.get('started_at') or 0) <= FLOW_TTL
    except (TypeError, ValueError):
        valid = False
    if not valid or not all(flow.get(key) for key in ('url', 'server_id', 'code', 'secret_enc', 'device_id', 'nonce')):
        raise JellyfinAdminAuthError('jellyfin_admin_expired')
    if not db.query_one("SELECT 1 FROM admin_auth_flows WHERE nonce_hash=? AND provider='jellyfin' AND expires_at>=?",
                        (_nonce_hash(flow), int(time.time()))):
        raise JellyfinAdminAuthError('jellyfin_admin_expired')
    return flow


def _confirm(purpose):
    db = get_db()
    wizard = purpose == 'wizard'
    back = url_for('setup_wizard', resume='wizard') if wizard else url_for('login')
    if wizard and not _wizard_available(db):
        abort(403)
    try:
        flow = _flow(db, purpose)
        if request.method == 'GET':
            return render_template('auth/jellyfin_quick_connect.html', code=flow['code'],
                                   server_url=flow['url'], back_url=back)
        if request.form.get('action') == 'cancel':
            _consume(db, session.pop(FLOW_KEY, None))
            return redirect(back)
        if not _rate_allowed(db, charge=False):
            raise JellyfinAdminAuthError('plex_auth_rate_limited')
        client = JellyfinQuickConnectClient(flow['url'], flow['device_id'])
        try:
            verified = client.finish(decrypt_secret(flow['secret_enc']), flow['server_id'])
        finally:
            client.close()
        # A successful exchange is single-use, including a mismatching account.
        if not _consume(db, flow, require_valid=True):
            raise JellyfinAdminAuthError('jellyfin_admin_expired')
        session.pop(FLOW_KEY, None)
        if wizard:
            existing = get_admin_auth_identity(db, 'jellyfin')
            if existing and existing['provider_subject'] != verified['subject']:
                raise JellyfinAdminAuthError('jellyfin_admin_failed')
            server = db.query_one("SELECT id FROM servers WHERE type='jellyfin' AND server_identifier=?",
                                  (flow['server_id'],))
            if server:
                server_id = server['id']
            else:
                result = create_setup_media_server(db, server_type='jellyfin', url=flow['url'],
                                                  token=verified['token'], expected_identifier=flow['server_id'])
                if not result.get('ok'):
                    raise JellyfinAdminAuthError('jellyfin_admin_failed')
                server_id = result['server_id']
            linked = link_admin_auth_identity(db, provider='jellyfin', subject=verified['subject'],
                                              display_name=verified['name'])
            db.execute('UPDATE settings SET auth_enabled=1 WHERE id=1')
            record_setup_media_servers(db, [server_id])
            state = decode_setup_wizard_state(load_setup_wizard_settings(db))
            state['administrator'] = 'jellyfin'
            save_setup_wizard_progress(db, step=3, state=state, active=1)
        else:
            linked = get_admin_auth_identity(db, 'jellyfin')
            if (not linked or not linked['is_active'] or linked['id'] != flow['identity_id']
                    or linked['provider_subject'] != flow['subject']
                    or linked['provider_subject'] != verified['subject']):
                raise JellyfinAdminAuthError('jellyfin_admin_failed')
        db.execute('UPDATE admin_auth_identities SET last_login_at=CURRENT_TIMESTAMP WHERE id=?', (linked['id'],))
        from routes.auth import _reset_failed_login
        _reset_failed_login(db, 'ip', get_client_ip())
        settings = load_setup_wizard_settings(db)
        open_admin_session(session, settings.get('admin_email') or '', auth_level='jellyfin',
                           db=db, session_ttl=current_app.permanent_session_lifetime)
        logger.info('AUTH Jellyfin admin login ok identity_id=%s', linked['id'])
        if wizard or should_resume_setup_wizard(db, settings):
            return redirect(url_for('setup_wizard', resume='wizard'))
        return redirect(url_for('dashboard'))
    except JellyfinApprovalPending:
        flash('jellyfin_admin_pending', 'error')
        return redirect(request.path)
    except JellyfinAdminAuthError as exc:
        _consume(db, session.pop(FLOW_KEY, None))
        flash(str(exc), 'error')
        logger.warning('AUTH Jellyfin admin connection rejected')
        return redirect(back)


def register(app):
    @app.after_request
    def jellyfin_admin_no_store(response):
        if request.path.startswith('/auth/jellyfin/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/auth/jellyfin/wizard', methods=['GET', 'POST'])
    def jellyfin_admin_wizard():
        return _confirm('wizard')

    @app.post('/auth/jellyfin/login')
    def jellyfin_admin_login_start():
        db = get_db()
        linked = get_admin_auth_identity(db, 'jellyfin')
        try:
            if not linked or not linked['is_active']:
                raise JellyfinAdminAuthError('jellyfin_admin_failed')
            _start(db, decode_binding(linked['provider_subject'])[0], 'login', linked)
            return redirect(url_for('jellyfin_admin_login_confirm'))
        except JellyfinAdminAuthError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('login'))

    @app.route('/auth/jellyfin/login/confirm', methods=['GET', 'POST'])
    def jellyfin_admin_login_confirm():
        return _confirm('login')
