"""Personal activation with immutable identity binding and resumable server intent."""
import hashlib
import json
import secrets
import time
from urllib.parse import urlsplit

from core.portal_local_auth import create_local_invitation
from core.plex_activation import activate_plex_server
from core.providers.plex_invitation_state import plex_invite_state_payload
from secret_store import encrypt_secret, decrypt_secret


TTL = 7 * 86400
TOKEN_TTL = 15 * 60


def digest(token):
    return hashlib.sha256(str(token or '').encode()).hexdigest()


def activation_settings(db):
    return dict(db.query_one('SELECT portal_enabled,portal_public_url,portal_local_auth_enabled,'
                            'portal_plex_auth_enabled,portal_jellyfin_auth_enabled '
                            'FROM settings WHERE id=1') or {})


def activation_mode(settings, providers):
    if not int(settings.get('portal_enabled') or 0):
        return None
    mode = 'plex' if 'plex' in providers else ('jellyfin' if 'jellyfin' in providers and int(settings.get('portal_jellyfin_auth_enabled') or 0) else 'local')
    if not int(settings.get(f'portal_{mode}_auth_enabled') or 0):
        raise ValueError('activation_mode_disabled')
    url = urlsplit(str(settings.get('portal_public_url') or ''))
    if url.scheme not in {'https', 'http'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('portal_public_url_required')
    return mode


def prepare_activation(db, user_id, mode, blocks, servers):
    """Persist selected libraries per actual server, including linked Plex servers."""
    targets = {}
    for block in blocks:
        sid = int(block['server_id'])
        ids = sorted({int(i) for i in block.get('library_ids') or []})
        if servers[sid]['type'].lower() == 'plex' and not ids:
            raise ValueError('activation_libraries_required')
        rows = db.query('SELECT id,server_id FROM libraries WHERE id IN (' +
                        ','.join('?' for _ in ids) + ')', ids) if ids else []
        for row in rows:
            target = targets.setdefault(int(row['server_id']), {'ids': set(), 'options': block.get('plex_share') or {}})
            target['ids'].add(int(row['id']))
        if servers[sid]['type'].lower() != 'plex':
            targets.setdefault(sid, {'ids': set(ids), 'options': {}})
    user = db.query_one('SELECT email FROM vodum_users WHERE id=?', (user_id,))
    with db.transaction() as cur:
        cur.execute('INSERT INTO user_activations(vodum_user_id,expires_at,mode,expected_email) VALUES(?,?,?,?)',
                    (user_id, int(time.time()) + TTL, mode, str(user['email']).strip().casefold()))
        aid = cur.lastrowid
        cur.execute("INSERT INTO portal_accounts(vodum_user_id,status) VALUES(?,'invited') ON CONFLICT(vodum_user_id) DO NOTHING", (user_id,))
        for sid, target in targets.items():
            cur.execute('INSERT INTO user_activation_servers(activation_id,server_id,library_ids,options_json) VALUES(?,?,?,?)',
                        (aid, sid, json.dumps(sorted(target['ids'])), json.dumps(target['options'])))
    return aid


def send_activation(db, user_id, *, jellyfin_credentials=None):
    """Queue the configured user_creation templates, one per existing delay slot."""
    from communications_engine import select_comm_templates_for_user, schedule_template_notification, enqueue_named_task
    row = db.query_one('SELECT id,mode FROM user_activations WHERE vodum_user_id=?', (user_id,))
    if not row:
        raise ValueError('activation_invalid')
    settings = activation_settings(db)
    if not activation_mode(settings, {row['mode']} if row['mode'] != 'local' else set()):
        raise ValueError('portal_unavailable')
    targets = activation_targets(db, row['id'])
    provider = 'plex' if any(t['type'].lower() == 'plex' for t in targets) else ('jellyfin' if targets else 'local')
    templates = select_comm_templates_for_user(db=db, trigger_event='user_creation', provider=provider, user_id=user_id)
    if not templates:
        raise ValueError('activation_no_template')
    user = db.query_one('SELECT email FROM vodum_users WHERE id=?', (user_id,))
    db.execute('UPDATE user_activations SET token_hash=NULL,email_token=NULL,expires_at=?,generation=generation+1,plex_token=NULL,'
               'plex_token_expires=NULL,expected_email=? WHERE id=?',
               (int(time.time()) + TTL, str(user['email'] or '').strip().casefold(), row['id']))
    generation = db.query_one('SELECT generation FROM user_activations WHERE id=?', (row['id'],))['generation']
    db.execute("UPDATE portal_account_tokens SET revoked_at=CURRENT_TIMESTAMP WHERE purpose='invitation' AND used_at IS NULL AND revoked_at IS NULL "
               "AND portal_account_id IN (SELECT id FROM portal_accounts WHERE vodum_user_id=?)", (user_id,))
    for template in templates:
        days = max(0, int(template.get('days_after') or 0))
        schedule_template_notification(db=db, template_id=int(template['id']), user_id=user_id,
            provider=provider, server_id=None, send_at_modifier=f'+{days} days' if days else None,
            payload={'activation_id': row['id'], 'activation_generation': generation,
                     'trigger_event': 'user_creation', 'provider_name': provider.capitalize(),
                     'server_name': ', '.join(t['name'] for t in targets),
                     'jellyfin_credentials': jellyfin_credentials or []},
            dedupe_key=f"activation:{row['id']}:{generation}:template:{template['id']}")
    if any(int(template.get('days_after') or 0) <= 0 for template in templates):
        enqueue_named_task(db, 'send_expiration_emails')


def activation_delivery_url(db, user_id, payload):
    """Mint at delivery, never store a bearer link in the scheduling queue."""
    from mailing_utils import build_portal_login_url
    settings = activation_settings(db)
    if not int(settings.get('portal_enabled') or 0):
        raise ValueError('portal_unavailable')
    row = db.query_one('SELECT * FROM user_activations WHERE id=? AND vodum_user_id=? AND generation=?',
                       (payload['activation_id'], user_id, payload['activation_generation']))
    if not row:
        raise ValueError('activation_invalid')
    login = build_portal_login_url(settings.get('portal_public_url'))
    if row['completed_at']:
        return login
    account = db.query_one('SELECT status FROM portal_accounts WHERE vodum_user_id=?', (user_id,))
    if account and account['status'] in {'suspended', 'deleted'}:
        raise ValueError('activation_invalid')
    # Validate account state without requiring an undelivered invitation to be unexpired.
    user = db.query_one('SELECT email,status FROM vodum_users WHERE id=?', (user_id,))
    if not user or user['status'] in {'expired','suspended','disabled','deleted'} or str(user['email'] or '').strip().casefold() != row['expected_email']:
        raise ValueError('activation_invalid')
    if row['email_token'] and row['expires_at'] > int(time.time()):
        token = decrypt_secret(row['email_token'])
    else:
        token = secrets.token_urlsafe(32)
        db.execute('UPDATE user_activations SET token_hash=?,email_token=?,expires_at=? WHERE id=? AND generation=?',
                   (digest(token), encrypt_secret(token), int(time.time()) + TTL, row['id'], row['generation']))
    return login.removesuffix('/login') + '/access?token=' + token


def load_activation(db, *, token=None, context=None):
    now = int(time.time())
    # No expired Plex bearer remains usable, including after interrupted flows.
    db.execute('UPDATE user_activations SET plex_token=NULL WHERE plex_token_expires<=? AND plex_token IS NOT NULL', (now,))
    db.execute('UPDATE user_activations SET email_token=NULL WHERE expires_at<=? AND email_token IS NOT NULL', (now,))
    if token:
        row = db.query_one('SELECT * FROM user_activations WHERE token_hash=? AND expires_at>?', (digest(token), now))
    elif context:
        row = db.query_one('SELECT * FROM user_activations WHERE id=? AND generation=? AND expires_at>?',
                           (context.get('id'), context.get('generation'), now))
    else:
        row = None
    if not row:
        raise ValueError('activation_invalid')
    row = dict(row)
    user = db.query_one('SELECT status,email,expiration_date FROM vodum_users WHERE id=?', (row['vodum_user_id'],))
    account = db.query_one('SELECT status FROM portal_accounts WHERE vodum_user_id=?', (row['vodum_user_id'],))
    if (not user or user['status'] in {'expired', 'suspended', 'disabled', 'deleted'} or
            (user['expiration_date'] and str(user['expiration_date'])[:10] < time.strftime('%Y-%m-%d', time.gmtime())) or
            (account and account['status'] in {'suspended', 'deleted'})):
        raise ValueError('activation_invalid')
    if str(user['email'] or '').strip().casefold() != row['expected_email']:
        raise ValueError('activation_email_changed')
    return row


def bind_plex_identity(db, activation, identity, token):
    """Email must match the invitation, or the already pinned stable Plex ID."""
    uid = int(activation['vodum_user_id'])
    subject = str(identity.subject or '').strip()
    if not subject.isdigit():
        raise ValueError('activation_wrong_account')
    if activation['plex_subject']:
        if activation['plex_subject'] != subject:
            raise ValueError('activation_wrong_account')
    elif str(identity.email or '').strip().casefold() != activation['expected_email']:
        raise ValueError('activation_wrong_account')
    encrypted = encrypt_secret(token)
    with db.transaction() as cur:
        # Recheck generation and pinned identity inside the write transaction.
        cur.execute('SELECT plex_subject FROM user_activations WHERE id=? AND generation=? AND expires_at>?',
                    (activation['id'], activation['generation'], int(time.time())))
        live = cur.fetchone()
        if not live or (live[0] and live[0] != subject):
            raise ValueError('activation_invalid')
        cur.execute("SELECT vodum_user_id,external_user_id FROM user_identities WHERE type='plex' AND (external_user_id=? OR vodum_user_id=?) "
                    "UNION SELECT vodum_user_id,external_user_id FROM media_users WHERE type='plex' AND (external_user_id=? OR vodum_user_id=?)",
                    (subject, uid, subject, uid))
        for owner, native in cur.fetchall():
            if (str(native or '') == subject and owner is not None and int(owner) != uid) or (owner == uid and native and str(native) != subject):
                raise ValueError('activation_identity_conflict')
        cur.execute("SELECT pa.vodum_user_id,pai.provider_subject,pai.is_active FROM portal_auth_identities pai JOIN portal_accounts pa ON pa.id=pai.portal_account_id "
                    "WHERE pai.provider='plex' AND (pai.provider_subject=? OR pa.vodum_user_id=?)", (subject, uid))
        for owner, native, active in cur.fetchall():
            if owner != uid or native != subject or not active:
                raise ValueError('activation_identity_conflict')
        cur.execute("INSERT INTO portal_accounts(vodum_user_id,status) VALUES(?,'active') ON CONFLICT(vodum_user_id) DO UPDATE SET status='active' WHERE status='invited'", (uid,))
        cur.execute('SELECT id,status FROM portal_accounts WHERE vodum_user_id=?', (uid,))
        account_id, status = cur.fetchone()
        if status != 'active':
            raise ValueError('activation_invalid')
        cur.execute("INSERT OR IGNORE INTO portal_auth_identities(portal_account_id,provider,provider_subject,is_active,verified_at) VALUES(?,'plex',?,1,CURRENT_TIMESTAMP)", (account_id, subject))
        cur.execute("INSERT OR IGNORE INTO portal_account_roles(portal_account_id,role_id) SELECT ?,id FROM portal_roles WHERE name='user'", (account_id,))
        cur.execute("INSERT INTO user_identities(vodum_user_id,type,external_user_id) SELECT ?,'plex',? WHERE NOT EXISTS(SELECT 1 FROM user_identities WHERE vodum_user_id=? AND type='plex' AND external_user_id=?)", (uid, subject, uid, subject))
        cur.execute('UPDATE user_activations SET plex_subject=?,plex_token=?,plex_token_expires=? WHERE id=?',
                    (subject, encrypted, int(time.time()) + TOKEN_TTL, activation['id']))
    return {'portal_account_id': account_id, 'vodum_user_id': uid}


def activation_targets(db, aid):
    return [dict(r) for r in db.query('SELECT a.server_id,a.state,a.error_key,s.name,s.type,s.public_url '
                                    'FROM user_activation_servers a JOIN servers s ON s.id=a.server_id WHERE a.activation_id=? ORDER BY s.id', (aid,))]


def process_server(db, activation, sid, identifier):
    now = int(time.time())
    lease = secrets.token_urlsafe(16)
    with db.transaction() as cur:
        cur.execute('UPDATE user_activation_servers SET lease_until=?,lease_id=?,state=\'working\' '
                    'WHERE activation_id=? AND server_id=? AND lease_until<=? AND state<>\'ready\'',
                    (now + 300, lease, activation['id'], sid, now))
        if cur.rowcount != 1:
            return
    state, error = 'error', 'activation_server_error'
    try:
        target = dict(db.query_one('SELECT * FROM user_activation_servers WHERE activation_id=? AND server_id=?', (activation['id'], sid)))
        server = dict(db.query_one('SELECT id,name,type,server_identifier,token FROM servers WHERE id=?', (sid,)))
        ids = json.loads(target['library_ids'])
        libraries = [dict(r) for r in db.query('SELECT id,name FROM libraries WHERE server_id=? AND id IN (' + ','.join('?' for _ in ids) + ')', [sid] + ids)] if ids else []
        if server['type'].lower() == 'plex':
            if not activation['plex_subject'] or not activation['plex_token'] or (activation['plex_token_expires'] or 0) <= now:
                raise ValueError('activation_reauthenticate')
            if len(libraries) != len(ids) or not ids:
                raise ValueError('activation_configuration_error')
            state = activate_plex_server(server, libraries, json.loads(target['options_json']), activation['plex_subject'],
                                         decrypt_secret(activation['plex_token']), identifier)
            persist_plex_access(db, activation, sid, ids, state)
        else:
            found = db.query_one("SELECT id FROM media_users WHERE vodum_user_id=? AND server_id=? AND type='jellyfin'", (activation['vodum_user_id'], sid))
            state = 'ready' if found else 'error'
        error = None if state != 'error' else error
    except ValueError as exc:
        if str(exc) in {'activation_reauthenticate', 'activation_configuration_error', 'activation_identity_conflict'}:
            error = str(exc)
    except Exception:
        # Provider exceptions can contain credentials/URLs; never put them in the UI or logs.
        error = 'activation_server_error'
    finally:
        db.execute('UPDATE user_activation_servers SET state=?,error_key=?,lease_until=0,lease_id=NULL WHERE activation_id=? AND server_id=? AND lease_id=?',
                   (state, error, activation['id'], sid, lease))
    targets = activation_targets(db, activation['id'])
    if activation['mode'] == 'plex' and targets and all(t['state'] == 'ready' for t in targets):
        db.execute('UPDATE user_activations SET completed_at=?,token_hash=NULL,email_token=NULL,plex_token=NULL WHERE id=?', (now, activation['id']))


def persist_plex_access(db, activation, sid, ids, state):
    uid, subject = activation['vodum_user_id'], activation['plex_subject']
    with db.transaction() as cur:
        cur.execute("SELECT id,vodum_user_id,details_json FROM media_users WHERE server_id=? AND type='plex' AND (external_user_id=? OR vodum_user_id=?)", (sid, subject, uid))
        rows = cur.fetchall()
        if len(rows) > 1 or (rows and rows[0][1] not in (None, uid)):
            raise ValueError('activation_identity_conflict')
        if rows:
            mid = rows[0][0]
            try:
                details = json.loads(rows[0][2] or '{}')
            except (ValueError, TypeError):
                details = {}
            details['plex_invite_state'] = plex_invite_state_payload('friend' if state == 'ready' else 'pending', primary_server_id=sid)
            cur.execute('UPDATE media_users SET vodum_user_id=?,external_user_id=?,details_json=? WHERE id=?', (uid, subject, json.dumps(details), mid))
        else:
            details = json.dumps({'plex_invite_state': plex_invite_state_payload('friend' if state == 'ready' else 'pending', primary_server_id=sid)})
            cur.execute("INSERT INTO media_users(vodum_user_id,server_id,type,external_user_id,username,email,details_json) VALUES(?,?,'plex',?,?,?,?)", (uid, sid, subject, subject, activation['expected_email'], details))
            mid = cur.lastrowid
        cur.executemany('INSERT OR IGNORE INTO media_user_libraries(media_user_id,library_id) VALUES(?,?)', [(mid, i) for i in ids])
        if state == 'ready':
            cur.execute('UPDATE media_users SET accepted_at=COALESCE(accepted_at,CURRENT_TIMESTAMP) WHERE id=?', (mid,))
            cur.execute("UPDATE vodum_users SET status='active' WHERE id=? AND status='invited'", (uid,))


def local_activation_token(db, activation):
    return create_local_invitation(db, activation['vodum_user_id'], activation['expected_email'])['token']
