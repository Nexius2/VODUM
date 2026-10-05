import time

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for

from core import user_activation as service
from core.plex_auth_client import PlexAuthClient, PlexAuthError
from core.plex_auth_flow import begin_plex_flow, consume_plex_flow, PlexFlowRejected
from core.portal_rate_limit import portal_request_allowed
from core.portal_sessions import create_portal_session
from core.auth_principal import open_portal_session, portal_principal
from core.portal_audit import record_portal_event
from web.helpers import get_db
from web.security import get_client_ip


CONTEXT = 'user_activation'


def register(app):
    def load():
        db = get_db()
        settings = service.activation_settings(db)
        if not int(settings.get('portal_enabled') or 0):
            raise ValueError('portal_unavailable')
        activation = service.load_activation(db, context=session.get(CONTEXT))
        if not int(settings.get(f"portal_{activation['mode']}_auth_enabled") or 0):
            raise ValueError('activation_mode_disabled')
        return db, activation, settings

    def client(db):
        row = db.query_one('SELECT plex_client_identifier FROM admin_accounts WHERE id=1')
        return PlexAuthClient(str(row['plex_client_identifier'] or '') if row else '')

    def failure(key, code=400):
        return render_template('portal/access_invalid.html', message_key=key), code

    @app.after_request
    def activation_response_security(response):
        if request.path.startswith('/portal/access'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/portal/access')
    def portal_access():
        db = get_db()
        try:
            if request.args.get('token'):
                if not portal_request_allowed(db, 'activation_link', get_client_ip(), limit=30):
                    return failure('portal_login_locked', 429)
                activation = service.load_activation(db, token=request.args['token'])
                session[CONTEXT] = {'id': activation['id'], 'generation': activation['generation']}
                session['activation_auto'] = bool(activation['plex_token']) or activation['mode'] == 'jellyfin'
                session['activation_auto_login'] = activation['mode'] == 'plex' and not activation['plex_token'] and not activation['completed_at']
                # Strip personal token before rendering links or loading external resources.
                return redirect(url_for('portal_access'))
            db, activation, settings = load()
            targets = service.activation_targets(db, activation['id'])
            jellyfin_accounts = [dict(r) for r in db.query("SELECT server_id,username FROM media_users WHERE vodum_user_id=? AND type='jellyfin'", (activation['vodum_user_id'],))]
            return render_template('portal/access.html', activation=activation, targets=targets,
                                   jellyfin_accounts=jellyfin_accounts,
                                   has_token=bool(activation['plex_token']),
                                   ready=bool(activation['completed_at']),
                                   auto_login=bool(session.pop('activation_auto_login', False)),
                                   auto=bool(session.pop('activation_auto', False)))
        except ValueError as exc:
            return failure(str(exc))

    @app.post('/portal/access/plex')
    def portal_access_plex():
        session.pop('activation_auto_login', None)
        try:
            db, activation, settings = load()
            if activation['mode'] != 'plex':
                raise ValueError('activation_invalid')
            if not portal_request_allowed(db, 'activation_plex', get_client_ip(), limit=20):
                return failure('portal_login_locked', 429)
            plex = client(db)
            pin = plex.create_pin()
            flow = begin_plex_flow(session, pin_id=pin.id, purpose='activation')
            session['activation_plex_context'] = dict(session[CONTEXT])
            from mailing_utils import build_portal_login_url
            callback = build_portal_login_url(settings['portal_public_url']).removesuffix('/login') + '/access/plex/callback?state=' + flow.state
            return redirect(plex.build_authorization_url(pin, callback, signup=not bool(activation['plex_subject'])))
        except (ValueError, PlexAuthError):
            flash('activation_reauthenticate', 'error')
            return redirect(url_for('portal_access'))

    @app.get('/portal/access/plex/callback')
    def portal_access_plex_callback():
        try:
            flow = consume_plex_flow(session, returned_state=request.args.get('state') or '', expected_purpose='activation')
            bound_context = session.pop('activation_plex_context', None)
            if not bound_context or bound_context != session.get(CONTEXT):
                raise ValueError('activation_invalid')
            db, activation, settings = load()
            plex = client(db)
            token = plex.wait_for_token(flow.pin_id)
            if not token:
                raise ValueError('activation_reauthenticate')
            identity = plex.fetch_identity(token)
            linked = service.bind_plex_identity(db, activation, identity, token)
            created = create_portal_session(db, linked['portal_account_id'], ttl=current_app.permanent_session_lifetime)
            context = dict(session[CONTEXT])
            open_portal_session(session, portal_principal(portal_account_id=linked['portal_account_id'],
                vodum_user_id=linked['vodum_user_id'], session_id=created['session_id'], session_token=created['token']))
            session[CONTEXT] = context
            record_portal_event(db, 'activation_plex_verified', 'success', portal_account_id=linked['portal_account_id'])
            # Access changes run via CSRF-protected POST, independently for each server.
            session['activation_auto'] = True
            return redirect(url_for('portal_access'))
        except (PlexFlowRejected, PlexAuthError):
            flash('activation_reauthenticate', 'error')
        except ValueError as exc:
            flash(str(exc), 'error')
        return redirect(url_for('portal_access'))

    @app.post('/portal/access/server/<int:server_id>')
    def portal_access_server(server_id):
        try:
            db, activation, settings = load()
            if not portal_request_allowed(db, 'activation_server', get_client_ip(), limit=60):
                return failure('portal_login_locked', 429)
            if activation['mode'] == 'plex' and not activation['plex_subject']:
                raise ValueError('activation_reauthenticate')
            identifier = client(db).client_identifier if activation['mode'] == 'plex' else ''
            service.process_server(db, activation, server_id, identifier)
            if request.headers.get('Accept') == 'application/json':
                return jsonify(ok=True)
            return redirect(url_for('portal_access'))
        except ValueError as exc:
            return failure(str(exc))

    @app.post('/portal/access/local')
    def portal_access_local():
        try:
            db, activation, settings = load()
            if activation['mode'] != 'local':
                raise ValueError('activation_invalid')
            account = db.query_one('SELECT status FROM portal_accounts WHERE vodum_user_id=?', (activation['vodum_user_id'],))
            if account and account['status'] == 'active':
                return redirect(url_for('portal_login'))
            token = service.local_activation_token(db, activation)
            return redirect(url_for('portal_activate', token=token))
        except ValueError as exc:
            return failure(str(exc))

    @app.post('/portal/access/jellyfin')
    def portal_access_jellyfin():
        from core.portal_jellyfin_auth import authenticate_jellyfin_user, resolve_jellyfin_portal_account, JellyfinPortalAuthError
        try:
            db, activation, settings = load()
            if not portal_request_allowed(db, 'activation_jellyfin', get_client_ip(), limit=10):
                return failure('portal_login_locked', 429)
            sid = int(request.form.get('server_id') or 0)
            account = db.query_one("SELECT username,external_user_id FROM media_users WHERE vodum_user_id=? AND server_id=? AND type='jellyfin'", (activation['vodum_user_id'], sid))
            if not account:
                raise ValueError('activation_invalid')
            if activation['mode'] != 'jellyfin':
                raise ValueError('activation_invalid')
            identity = authenticate_jellyfin_user(db, sid, account['username'], request.form.get('password') or '')
            if str(identity.subject) != str(account['external_user_id']):
                raise ValueError('activation_wrong_account')
            linked = resolve_jellyfin_portal_account(db, identity)
            if not linked or linked['vodum_user_id'] != activation['vodum_user_id']:
                raise ValueError('activation_wrong_account')
            created = create_portal_session(db, linked['portal_account_id'], ttl=current_app.permanent_session_lifetime)
            context = dict(session[CONTEXT])
            open_portal_session(session, portal_principal(portal_account_id=linked['portal_account_id'], vodum_user_id=linked['vodum_user_id'], session_id=created['session_id'], session_token=created['token']))
            session[CONTEXT] = context
            db.execute('UPDATE user_activations SET token_hash=NULL,email_token=NULL,completed_at=? WHERE id=?', (int(time.time()), activation['id']))
            return redirect(url_for('portal_home'))
        except (ValueError, JellyfinPortalAuthError):
            flash('portal_invalid_credentials', 'error')
            return redirect(url_for('portal_access'))
