"""Local list storage. No network calls or remote publication side effects."""
import hashlib
import json
import re
import uuid
from pathlib import Path
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_list_catalog (
 id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_lists (
 id TEXT PRIMARY KEY, origin TEXT NOT NULL CHECK(origin IN ('official','custom')),
 name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
 available INTEGER NOT NULL DEFAULT 1 CHECK(available IN (0,1)),
 revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS collection_list_official_members (
 list_id TEXT NOT NULL REFERENCES collection_lists(id) ON DELETE CASCADE,
 provider TEXT NOT NULL, media_type TEXT NOT NULL, external_id TEXT NOT NULL,
 data_json TEXT NOT NULL, position INTEGER NOT NULL,
 PRIMARY KEY(list_id,provider,media_type,external_id)
);
CREATE TABLE IF NOT EXISTS collection_list_overrides (
 list_id TEXT NOT NULL REFERENCES collection_lists(id) ON DELETE CASCADE,
 provider TEXT NOT NULL, media_type TEXT NOT NULL, external_id TEXT NOT NULL,
 added INTEGER NOT NULL DEFAULT 0, excluded INTEGER NOT NULL DEFAULT 0,
 data_json TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(list_id,provider,media_type,external_id)
);
CREATE TABLE IF NOT EXISTS collection_catalog_preparation (
 id INTEGER PRIMARY KEY CHECK(id=1), source_digest TEXT NOT NULL,
 catalog_json TEXT NOT NULL, report_json TEXT NOT NULL DEFAULT '{}',
 state TEXT NOT NULL DEFAULT 'draft', lease_id TEXT, lease_until TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS collection_list_legacy_keys (
 list_id TEXT PRIMARY KEY REFERENCES collection_lists(id) ON DELETE CASCADE,
 legacy_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS collection_list_legacy_groups (
 group_id TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS collection_list_cleanup (
 object_id TEXT PRIMARY KEY REFERENCES collection_objects(id) ON DELETE CASCADE,
 remote_id TEXT NOT NULL, scope TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 error TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS collection_list_deleted (
 list_id TEXT PRIMARY KEY, name TEXT NOT NULL, deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS collection_list_bindings (
 list_id TEXT NOT NULL REFERENCES collection_lists(id) ON DELETE CASCADE,
 group_id TEXT NOT NULL, PRIMARY KEY(list_id,group_id)
);
"""


@contextmanager
def read_cursor(db):
    if hasattr(db, 'readonly_snapshot'):
        with db.readonly_snapshot() as reader:
            cursor = reader.connection.cursor()
            try:
                yield cursor
            finally:
                cursor.close()
    else:
        with db.transaction() as cursor:
            yield cursor


def identity(member):
    provider = member.get('provider')
    kind = member.get('media_type')
    identifier = str(member.get('external_id', ''))
    pattern = r'tt[0-9]+' if provider == 'imdb' else r'[1-9][0-9]*'
    if (provider not in ('tmdb', 'tvdb', 'imdb') or kind not in ('movie', 'tv')
            or isinstance(member.get('external_id'), bool) or not re.fullmatch(pattern, identifier)):
        raise ValueError('Invalid media identity')
    return provider, kind, identifier


def validate_catalog(catalog):
    if (catalog.get('schema_version') != 1 or type(catalog.get('catalog_version')) is not int
            or catalog['catalog_version'] < 1 or catalog.get('status') != 'ready'
            or not isinstance(catalog.get('lists'), list) or not catalog['lists']):
        raise ValueError('Catalogue must be complete and reviewed before installation')
    legacy_ids={'vodum.franchise.'+key for key in json.loads((Path(__file__).resolve().parents[1]/'data'/'franchise_universes.json').read_text(encoding='utf-8'))['universes']}
    if any(isinstance(row,dict) and row.get('id') in legacy_ids for row in catalog['lists']):
        from core.collection_list_catalog_review import require_release_catalog
        require_release_catalog(catalog)
    seen = set()
    for row in catalog['lists']:
        key = row.get('id', '')
        if not isinstance(key, str) or not re.fullmatch(r'vodum[.][a-z0-9_.-]+', key) or key in seen:
            raise ValueError('Invalid or duplicate official list')
        seen.add(key)
        if not isinstance(row.get('name'), str) or not row['name'].strip():
            raise ValueError('Missing list name')
        if not isinstance(row.get('description', ''), str) or not isinstance(row.get('members'), list):
            raise ValueError('Invalid list definition')
        identities = [identity(member) for member in row['members']]
        if len(set(identities)) != len(identities):
            raise ValueError('Duplicate media identity')
    return catalog


def load_catalog(path=None):
    path = path or Path(__file__).resolve().parents[1] / 'data' / 'collection_lists.json'
    return validate_catalog(json.loads(Path(path).read_text(encoding='utf-8')))


def install_catalog(db, catalog):
    """Atomically replace official content, retaining local intentions and states."""
    validate_catalog(catalog)
    digest = hashlib.sha256(json.dumps(catalog, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with db.transaction() as cur:
        return _install_catalog(cur,catalog,digest)


def _install_catalog(cur,catalog,digest):
    previous = cur.execute('SELECT version,digest FROM collection_list_catalog WHERE id=1').fetchone()
    if previous:
        if catalog['catalog_version'] < previous[0]:
            raise ValueError('Catalogue downgrade refused')
        if catalog['catalog_version'] == previous[0]:
            if digest != previous[1]:
                raise ValueError('Catalogue version reused with different content')
            return False
    cur.execute("UPDATE collection_lists SET available=0,revision=revision+1 WHERE origin='official'")
    cur.execute('DELETE FROM collection_list_official_members')
    for row in catalog['lists']:
        existing = cur.execute('SELECT origin FROM collection_lists WHERE id=?', (row['id'],)).fetchone()
        if existing and existing[0] != 'official':
            raise ValueError('List identity collision')
        cur.execute("""INSERT INTO collection_lists(id,origin,name,description)
            VALUES(?,'official',?,?) ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,description=excluded.description,available=1""",
            (row['id'], row['name'].strip(), row.get('description', '')))
        for position, member in enumerate(row['members']):
            cur.execute('INSERT INTO collection_list_official_members VALUES(?,?,?,?,?,?)',
                (row['id'], *identity(member), json.dumps(member), position))
    cur.execute('INSERT OR REPLACE INTO collection_list_catalog VALUES(1,?,?)',
                (catalog['catalog_version'], digest))
    return True

def create_list(db, name, description=''):
    if not isinstance(name, str) or not name.strip() or not isinstance(description, str):
        raise ValueError('Invalid list name or description')
    key = 'custom.' + str(uuid.uuid4())
    with db.transaction() as cur:
        cur.execute("INSERT INTO collection_lists(id,origin,name,description) VALUES(?,'custom',?,?)",
                    (key, name.strip(), description))
    return key


def edit_list(db, key, *, name=None, description=None, enabled=None):
    if enabled is not None and type(enabled) is not bool:
        raise ValueError('Invalid activation state')
    with db.transaction() as cur:
        row = cur.execute('SELECT origin FROM collection_lists WHERE id=?', (key,)).fetchone()
        if row is None:
            raise ValueError('Unknown list')
        values = {}
        if name is not None or description is not None:
            if row[0] != 'custom':
                raise ValueError('Official definitions are read-only')
            if name is not None:
                if not isinstance(name, str) or not name.strip():
                    raise ValueError('Invalid name')
                values['name'] = name.strip()
            if description is not None:
                if not isinstance(description, str):
                    raise ValueError('Invalid description')
                values['description'] = description
        if enabled is not None:
            values['enabled'] = int(enabled)
        if values:
            cur.execute('UPDATE collection_lists SET ' + ','.join(field+'=?' for field in values)
                        + ',revision=revision+1 WHERE id=?', (*values.values(), key))


def change_member(db, key, member, action):
    """Addition/removal and exclusion/reintegration are independent intentions."""
    media = identity(member)
    if action not in ('add', 'remove', 'exclude', 'restore'):
        raise ValueError('Unknown member action')
    with db.transaction() as cur:
        row = cur.execute('SELECT origin FROM collection_lists WHERE id=?', (key,)).fetchone()
        if row is None:
            raise ValueError('Unknown list')
        if action == 'exclude':
            official = cur.execute('SELECT 1 FROM collection_list_official_members WHERE list_id=? AND provider=? AND media_type=? AND external_id=?', (key, *media)).fetchone()
            if not official:
                raise ValueError('Only official members can be excluded')
        cur.execute('INSERT OR IGNORE INTO collection_list_overrides(list_id,provider,media_type,external_id) VALUES(?,?,?,?)', (key, *media))
        field = 'added' if action in ('add', 'remove') else 'excluded'
        value = int(action in ('add', 'exclude'))
        cur.execute('UPDATE collection_list_overrides SET '+field+'=? WHERE list_id=? AND provider=? AND media_type=? AND external_id=?', (value, key, *media))
        if action == 'add':
            cur.execute('UPDATE collection_list_overrides SET data_json=? WHERE list_id=? AND provider=? AND media_type=? AND external_id=?', (json.dumps(member), key, *media))
        cur.execute('DELETE FROM collection_list_overrides WHERE list_id=? AND added=0 AND excluded=0', (key,))
        cur.execute('UPDATE collection_lists SET revision=revision+1 WHERE id=?', (key,))


def list_detail(db, key):
    with read_cursor(db) as cur:
        return _list_detail(cur, key)


def _list_detail(cur, key):
    row = cur.execute('SELECT * FROM collection_lists WHERE id=?', (key,)).fetchone()
    if row is None:
        raise ValueError('Unknown list')
    result = dict(row)
    members = {}
    for item in cur.execute('SELECT * FROM collection_list_official_members WHERE list_id=? ORDER BY position', (key,)).fetchall():
        media = (item['provider'], item['media_type'], item['external_id'])
        members[media] = {**json.loads(item['data_json']), 'official': True, 'added': False, 'excluded': False}
    for item in cur.execute('SELECT * FROM collection_list_overrides WHERE list_id=? ORDER BY provider,media_type,external_id', (key,)).fetchall():
        media = (item['provider'], item['media_type'], item['external_id'])
        if media not in members and not item['added']:
            continue
        value = members.setdefault(media, {**json.loads(item['data_json']), 'official': False})
        value.update(added=bool(item['added']), excluded=bool(item['excluded']))
    result['bindings'] = [item[0] for item in cur.execute('SELECT group_id FROM collection_list_bindings WHERE list_id=? ORDER BY group_id', (key,)).fetchall()]
    result['members'] = list(members.values())
    result['effective_members'] = [m for m in members.values() if not m['excluded']] if result['enabled'] and result['available'] else []
    return result

def bind_list(db, key, group_id, *, attached):
    """Persist associations for the next sync; do not schedule immediate remote work."""
    if type(attached) is not bool or not isinstance(group_id, str):
        raise ValueError('Invalid association')
    with db.transaction() as cur:
        if not cur.execute('SELECT 1 FROM collection_lists WHERE id=?', (key,)).fetchone():
            raise ValueError('Unknown list')
        if attached:
            rows = cur.execute("SELECT model,requested FROM collection_instances WHERE (group_id=? OR (group_id IS NULL AND id=?)) AND retired=0", (group_id, group_id)).fetchall()
            if not rows or any(row[0] != 'franchises' or row[1] == 'delete' for row in rows):
                raise ValueError('Only existing Franchises groups may be associated')
            changed = cur.execute('INSERT OR IGNORE INTO collection_list_bindings VALUES(?,?)', (key, group_id)).rowcount
        else:
            changed = cur.execute('DELETE FROM collection_list_bindings WHERE list_id=? AND group_id=?', (key, group_id)).rowcount
        if changed:
            cur.execute('UPDATE collection_lists SET revision=revision+1 WHERE id=?', (key,))


def browse_lists(db, query='', origin=''):
    if origin not in ('', 'official', 'custom'):
        raise ValueError('Invalid origin')
    with read_cursor(db) as cur:
        # Count the union once: official additions must not be counted twice.
        rows = cur.execute("""WITH media AS (
            SELECT m.list_id,m.provider,m.media_type,m.external_id,COALESCE(o.excluded,0) AS excluded
            FROM collection_list_official_members m LEFT JOIN collection_list_overrides o
            USING(list_id,provider,media_type,external_id)
            UNION ALL
            SELECT o.list_id,o.provider,o.media_type,o.external_id,o.excluded
            FROM collection_list_overrides o WHERE o.added=1 AND NOT EXISTS (
                SELECT 1 FROM collection_list_official_members m WHERE m.list_id=o.list_id
                AND m.provider=o.provider AND m.media_type=o.media_type AND m.external_id=o.external_id)
        ), counts AS (
            SELECT list_id,SUM(media_type='movie' AND excluded=0) AS movies,
            SUM(media_type='tv' AND excluded=0) AS shows FROM media GROUP BY list_id
        ) SELECT l.*,COALESCE(c.movies,0) AS movies,COALESCE(c.shows,0) AS shows,
            (SELECT COUNT(*) FROM collection_list_overrides o WHERE o.list_id=l.id AND added=1) AS additions,
            (SELECT COUNT(*) FROM collection_list_overrides o WHERE o.list_id=l.id AND excluded=1) AS exclusions
            FROM collection_lists l LEFT JOIN counts c ON c.list_id=l.id
            ORDER BY l.name COLLATE NOCASE,l.id""").fetchall()
        bindings = {}
        for row in cur.execute('SELECT list_id,group_id FROM collection_list_bindings ORDER BY group_id').fetchall():
            bindings.setdefault(row[0], []).append(row[1])
        needle = query.casefold().strip()
        return [{**dict(row), 'bindings': bindings.get(row['id'], [])} for row in rows
                if (not origin or row['origin'] == origin)
                and (not needle or needle in (row['name']+' '+row['description']).casefold())]


def bound_list_snapshot(db, instance):
    group_id = instance.get('group_id') or instance['id']
    with read_cursor(db) as cur:
        keys = [row[0] for row in cur.execute('SELECT list_id FROM collection_list_bindings WHERE group_id=? ORDER BY list_id', (group_id,)).fetchall()]
        lists = [_list_detail(cur, key) for key in keys]
    return lists, _list_revision(lists)


def _list_revision(rows):
    return hashlib.sha256(json.dumps([(row['id'], row['revision'], row['enabled'], row['available']) for row in rows]).encode()).hexdigest()


def bound_list_revision(db, instance):
    with read_cursor(db) as cur:
        rows = cur.execute("""SELECT l.id,l.revision,l.enabled,l.available FROM collection_lists l
            JOIN collection_list_bindings b ON b.list_id=l.id WHERE b.group_id=? ORDER BY l.id""",
            (instance.get('group_id') or instance['id'],)).fetchall()
        return _list_revision(rows)


def delete_custom_list(db, key, *, revision, confirmed=False):
    """Delete local intent only, keeping published objects and a cleanup trace."""
    if confirmed is not True or type(revision) is not int:
        raise ValueError('lists.delete_confirmation_required')
    from core.collections_repository import stamp
    with db.transaction() as cur:
        row = cur.execute('SELECT origin,name,revision FROM collection_lists WHERE id=?', (key,)).fetchone()
        if not row or row['origin'] != 'custom':
            raise ValueError('lists.delete_custom_only')
        if row['revision'] != revision:
            raise ValueError('lists.delete_changed')
        object_keys = ('list:movie:'+key, 'list:tv:'+key)
        running = cur.execute("""SELECT 1 FROM collection_instances i
            WHERE i.lease_id IS NOT NULL AND i.lease_until>? AND (
                EXISTS (SELECT 1 FROM collection_list_bindings b WHERE b.list_id=?
                    AND b.group_id=COALESCE(i.group_id,i.id))
                OR EXISTS (SELECT 1 FROM collection_objects o WHERE o.instance_id=i.id
                    AND o.person_key IN (?,?))) LIMIT 1""", (stamp(), key, *object_keys)).fetchone()
        if running:
            raise ValueError('collections.busy')
        cur.execute('INSERT INTO collection_list_deleted(list_id,name) VALUES(?,?)', (key, row['name']))
        # A detached list may still have a pending publication plan. Invalidate
        # that plan too; retaining the remote object does not mean republishing it.
        cur.execute("""DELETE FROM collection_publication_plans WHERE object_id IN (
            SELECT id FROM collection_objects WHERE person_key IN (?,?))""", object_keys)
        cur.execute('DELETE FROM collection_lists WHERE id=?', (key,))
