"""Local franchise lists. Local membership and protected bundled defaults."""
import json
import re
from pathlib import Path

CATALOG=json.loads((Path(__file__).resolve().parents[1]/'data'/'franchise_lists.json').read_text(encoding='utf-8'))
SELECTION_VERSION = 2
LEGACY_DEFAULT_IDS = {'dcu', 'avp', 'fast', 'mcu', 'starwars', 'trek',
                      'stargate', 'wizarding_world', 'middle_earth'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS franchise_lists (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 is_vodum INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS franchise_list_items (
 list_id TEXT NOT NULL REFERENCES franchise_lists(id) ON DELETE CASCADE,
 provider TEXT NOT NULL CHECK(provider IN ('tmdb','imdb','tvdb')),
 media_type TEXT NOT NULL CHECK(media_type IN ('movie','tv')),
 external_id TEXT NOT NULL, title TEXT, year TEXT,
 poster_path TEXT, metadata_state TEXT NOT NULL DEFAULT 'pending',
 metadata_error TEXT, metadata_checked_at TEXT,
 enabled INTEGER NOT NULL DEFAULT 1, is_vodum INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(list_id,provider,media_type,external_id)
);
"""


def seed_lists(cursor):
    for row in CATALOG['lists']:
        if not re.fullmatch(r'[a-z0-9_]+',row['id']) or not row['name']:
            raise ValueError('Invalid local franchise list')
        cursor.execute('INSERT OR IGNORE INTO franchise_lists(id,name) VALUES(?,?)',(row['id'],row['name']))
        for item in row['items']:
            provider,kind,identifier=item['provider'],item['media_type'],str(item['external_id'])
            if provider not in ('tmdb','imdb','tvdb') or kind not in ('movie','tv') or not re.fullmatch(r'tt[0-9]+' if provider=='imdb' else r'[1-9][0-9]*',identifier):
                raise ValueError('Invalid local franchise identity')
            cursor.execute('INSERT OR IGNORE INTO franchise_list_items(list_id,provider,media_type,external_id,title,year) VALUES(?,?,?,?,?,?)',(row['id'],provider,kind,identifier,item.get('title'),item.get('year')))


def definitions(db=None):
    if db is None:
        return [{'id':row['id'],'name':row['name'],'enabled':1,'is_vodum':1} for row in CATALOG['lists']]
    return [dict(row) for row in db.query('SELECT id,name,enabled,is_vodum FROM franchise_lists ORDER BY rowid')]


def default_list_ids(db=None):
    return [row['id'] for row in definitions(db) if row.get('is_vodum')]


def upgrade_franchise_selections(cursor):
    """Expand the former complete default once; preserve deliberate subsets."""
    defaults = [row['id'] for row in CATALOG['lists']]
    rows = list(cursor.execute("SELECT id,config_json FROM collection_instances WHERE model='franchises'"))
    for identifier, raw in rows:
        config = json.loads(raw or '{}')
        if config.get('franchise_selection_version', 0) >= SELECTION_VERSION:
            continue
        selected = config.get('franchise_lists')
        if isinstance(selected, list) and set(selected) == LEGACY_DEFAULT_IDS:
            config['franchise_lists'] = defaults
        config['franchise_selection_version'] = SELECTION_VERSION
        cursor.execute('UPDATE collection_instances SET config_json=? WHERE id=?',
                       (json.dumps(config), identifier))


def list_items(db,key,kind):
    if db is None:
        row=next(row for row in CATALOG['lists'] if row['id']==key)
        return [dict(item) for item in row['items'] if item['media_type']==kind]
    return [dict(row) for row in db.query('SELECT * FROM franchise_list_items WHERE list_id=? AND media_type=? AND enabled=1 ORDER BY rowid',(key,kind))]
