"""Small local list editor. Origin flags are enforced on the server."""
import json
import re
import uuid
from core.collections_portraits import portrait_path
from core.collections_franchise_lists import (ORDER_MODES, apply_order, catalog_title, default_list_ids,
                                              has_bundled_chronology, order_source)
from core.collections_repository import stamp
from core.collections_list_metadata import bundled_title, imdb_metadata



def require_list(db, key):
    row = db.query_one('SELECT * FROM franchise_lists WHERE id=?', (key,))
    if row is None:
        raise ValueError('collections.lists_not_found')
    return dict(row)


def usages(db, key):
    result = []
    defaults=default_list_ids(db)
    for row in db.query("""SELECT i.id,COALESCE(i.group_id,i.id) AS group_id,i.name,i.enabled,i.model,i.config_json,l.name AS library_name,
            s.name AS server_name FROM collection_instances i JOIN libraries l ON l.id=i.library_id
            JOIN servers s ON s.id=l.server_id WHERE i.model IN ('franchises','media_list') AND i.retired=0
            ORDER BY i.name,l.name"""):
        config = json.loads(row['config_json'])
        if (row['model']=='media_list' and config.get('media_list')==key) or (row['model']=='franchises' and key in config.get('franchise_lists',defaults)):
            result.append({k:row[k] for k in ('id','group_id','name','enabled','library_name','server_name')})
    grouped = {}
    for item in result:
        group = grouped.setdefault(item['group_id'], {**item, 'id':item['group_id'], 'libraries':[]})
        group['libraries'].append({k:item[k] for k in ('server_name','library_name','enabled')})
        group['enabled'] = bool(group['enabled'] or item['enabled'])
    return list(grouped.values())


def link_targets(db, key):
    require_list(db,key)
    groups={}
    defaults=default_list_ids(db)
    for row in db.query("""SELECT i.*,l.name AS library_name,s.name AS server_name FROM collection_instances i
            JOIN libraries l ON l.id=i.library_id JOIN servers s ON s.id=l.server_id
            WHERE i.model='franchises' AND i.retired=0 ORDER BY i.name,l.name"""):
        group_id=row['group_id'] or row['id']
        target=groups.setdefault(group_id,{'id':group_id,'name':row['name'],'libraries':[],
            'linked':True,'busy':False})
        target['libraries'].append({'server_name':row['server_name'],'library_name':row['library_name']})
        target['linked']=target['linked'] and key in json.loads(row['config_json']).get('franchise_lists',defaults)
        target['busy']=target['busy'] or bool(row['lease_until'] and row['lease_until']>stamp()) or row['requested'] in ('delete','cancel','cleanup')
    return list(groups.values())


def set_link(db, key, payload):
    group=payload.get('collection_id');linked=payload.get('linked')
    if not isinstance(group,str) or type(linked) is not bool:
        raise ValueError('collections.invalid_configuration')
    now=stamp()
    with db.transaction() as cursor:
        if cursor.execute('SELECT id FROM franchise_lists WHERE id=?',(key,)).fetchone() is None:
            raise ValueError('collections.lists_not_found')
        rows=cursor.execute("SELECT * FROM collection_instances WHERE (group_id=? OR id=?) AND retired=0",(group,group)).fetchall()
        if not rows or any(row['model']!='franchises' for row in rows):
            raise ValueError('collections.invalid_configuration')
        if any((row['lease_until'] and row['lease_until']>now) or row['requested'] in ('delete','cancel','cleanup') for row in rows):
            raise ValueError('collections.busy')
        defaults=[row['id'] for row in cursor.execute('SELECT id FROM franchise_lists WHERE is_vodum=1')]
        for row in rows:
            config=json.loads(row['config_json'])
            selected=config.get('franchise_lists',defaults)
            selected=list(dict.fromkeys([*selected,key])) if linked else [value for value in selected if value!=key]
            config['franchise_lists']=selected
            from core.collections_franchise_lists import SELECTION_VERSION
            config['franchise_selection_version']=SELECTION_VERSION
            cursor.execute('UPDATE collection_instances SET config_json=?,updated_at=? WHERE id=?',
                           (json.dumps(config),now,row['id']))


def catalog(db):
    rows = []
    for row in db.query("""SELECT l.*,COUNT(i.external_id) AS total,
            COALESCE(SUM(i.enabled),0) AS active FROM franchise_lists l
            LEFT JOIN franchise_list_items i ON i.list_id=l.id GROUP BY l.id ORDER BY l.rowid"""):
        rows.append({**dict(row), 'usages':usages(db,row['id'])})
    return rows


def contents(db, key):
    row = require_list(db,key)
    row['items'] = [dict(item) for item in db.query(
        'SELECT * FROM franchise_list_items WHERE list_id=? ORDER BY media_type,COALESCE(title,external_id),external_id', (key,))]
    for item in row['items']:
        if not item.get('title'):
            item['title'] = (bundled_title(item['provider'],item['external_id'],item['media_type'])
                             or catalog_title(key,item['provider'],item['media_type'],item['external_id']))
    row['order_source'] = order_source(db, key)
    row['has_bundled_order'] = has_bundled_chronology(key)
    for item in row['items']:
        item['chronology_saved'] = item.get('chronology') is not None
    apply_order(row['order_source'], key, row['items'])
    row['chronological'] = any(item.get('chronology') is not None for item in row['items'])
    if row['chronological']:
        # Unplaced entries (added after the order was saved) follow by release year.
        row['items'].sort(key=lambda item:(item.get('chronology') is None,item.get('chronology') or 0,
                                           str(item.get('year') or '9999'),str(item.get('title') or '')))
    row['usages'] = usages(db,key)
    return row


def name_value(payload):
    name = payload.get('name')
    if not isinstance(name,str) or not 1 <= len(name.strip()) <= 120:
        raise ValueError('collections.lists_name_required')
    return name.strip()


def identity(payload):
    provider,kind,identifier = (payload.get(k) for k in ('provider','media_type','external_id'))
    if provider not in ('imdb','tmdb','tvdb') or kind not in ('movie','tv'):
        raise ValueError('collections.invalid_configuration')
    if not isinstance(identifier,str) or not re.fullmatch(r'tt[0-9]+' if provider=='imdb' else r'[1-9][0-9]*',identifier):
        raise ValueError('collections.invalid_configuration')
    if provider=='tvdb' and kind!='tv':
        raise ValueError('collections.invalid_configuration')
    return provider,kind,identifier


def create_list(db, payload):
    name = name_value(payload)
    key = 'custom_'+uuid.uuid4().hex
    db.execute('INSERT INTO franchise_lists(id,name,is_vodum) VALUES(?,?,0)',(key,name))
    return key


def update_list(db, key, payload):
    action = payload.get('action')
    with db.transaction() as cur:
        row = cur.execute('SELECT * FROM franchise_lists WHERE id=?',(key,)).fetchone()
        if row is None:raise ValueError('collections.lists_not_found')
        if action=='delete':
            if row['is_vodum']:raise ValueError('collections.lists_protected')
            # Keep references explicit; unlink a custom list in the configuration first.
            if usages(db,key):raise ValueError('collections.lists_in_use')
            cur.execute('DELETE FROM franchise_list_items WHERE list_id=?',(key,))
            cur.execute('DELETE FROM franchise_lists WHERE id=?',(key,))
        elif action=='save':
            if type(payload.get('enabled')) is not bool:raise ValueError('collections.invalid_configuration')
            cur.execute('UPDATE franchise_lists SET name=?,enabled=? WHERE id=?',
                        (name_value(payload),int(payload['enabled']),key))
        else:raise ValueError('collections.invalid_configuration')


def update_item(db, key, payload, metadata=None):
    provider,kind,identifier = identity(payload)
    action = payload.get('action')
    with db.transaction() as cur:
        if not cur.execute('SELECT id FROM franchise_lists WHERE id=?',(key,)).fetchone():
            raise ValueError('collections.lists_not_found')
        params = (key,provider,kind,identifier)
        row = cur.execute('SELECT * FROM franchise_list_items WHERE list_id=? AND provider=? AND media_type=? AND external_id=?',params).fetchone()
        if action=='add':
            if row:raise ValueError('collections.lists_duplicate')
            if not metadata or not metadata.get('title'):raise ValueError('collections.lists_identity_failed')
            cur.execute("""INSERT INTO franchise_list_items(list_id,provider,media_type,external_id,title,year,poster_path,metadata_state,is_vodum)
                VALUES(?,?,?,?,?,?,?,?,0)""",(*params,metadata['title'],metadata.get('year'),metadata.get('poster_path'),metadata.get('metadata_state','resolved' if metadata.get('poster_path') else 'partial')))
        elif action in ('delete','toggle'):
            if row is None:raise ValueError('collections.lists_not_found')
            if action=='delete':
                if row['is_vodum']:raise ValueError('collections.lists_protected')
                cur.execute('DELETE FROM franchise_list_items WHERE list_id=? AND provider=? AND media_type=? AND external_id=?',params)
            else:
                if type(payload.get('enabled')) is not bool:raise ValueError('collections.invalid_configuration')
                cur.execute('UPDATE franchise_list_items SET enabled=? WHERE list_id=? AND provider=? AND media_type=? AND external_id=?',
                            (int(payload['enabled']),*params))
        else:raise ValueError('collections.invalid_configuration')


def set_order(db, key, payload):
    """Save the in-universe order of a list, or clear it with an empty list.

    The order must name every entry exactly once: a stale page must not save a
    partial order over entries added or removed in the meantime.
    """
    mode = payload.get('mode')
    if mode is not None:
        # Switch between the automatic order (saved > bundled > release) and release order.
        if mode not in ORDER_MODES or 'items' in payload:
            raise ValueError('collections.invalid_configuration')
        if db.execute('UPDATE franchise_lists SET order_mode=? WHERE id=?', (mode, key)).rowcount == 0:
            raise ValueError('collections.lists_not_found')
        return
    entries = payload.get('items')
    if not isinstance(entries, list) or len(entries) > 5000:
        raise ValueError('collections.invalid_configuration')
    order = [identity(entry if isinstance(entry, dict) else {}) for entry in entries]
    if len(set(order)) != len(order):
        raise ValueError('collections.invalid_configuration')
    with db.transaction() as cur:
        if cur.execute('SELECT id FROM franchise_lists WHERE id=?', (key,)).fetchone() is None:
            raise ValueError('collections.lists_not_found')
        known = {(row['provider'], row['media_type'], row['external_id']) for row in cur.execute(
            'SELECT provider,media_type,external_id FROM franchise_list_items WHERE list_id=?', (key,))}
        if order and set(order) != known:
            raise ValueError('collections.lists_order_stale')
        cur.execute('UPDATE franchise_list_items SET chronology=NULL WHERE list_id=?', (key,))
        # Saving an order, or clearing it to return to the default, re-enables the automatic order.
        cur.execute("UPDATE franchise_lists SET order_mode='auto' WHERE id=?", (key,))
        for position, (provider, kind, identifier) in enumerate(order, 1):
            cur.execute('UPDATE franchise_list_items SET chronology=? WHERE list_id=? AND provider=? AND media_type=? AND external_id=?',
                        (position, key, provider, kind, identifier))


def resolve_media(source, provider, kind, identifier):
    if provider=='tmdb':
        media = source.tmdb('/'+kind+'/'+identifier)
        if media.get('id')!=int(identifier):raise ValueError('collections.lists_identity_failed')
    else:
        matches = source.tmdb('/find/'+identifier,external_source=provider+'_id').get('movie_results' if kind=='movie' else 'tv_results')
        if not isinstance(matches,list) or not matches:
            if provider=='imdb':return imdb_metadata(source,identifier,kind)
            raise ValueError('collections.lists_identity_failed')
        if len(matches)!=1:raise ValueError('collections.lists_identity_failed')
        media = matches[0]
    if type(media.get('id')) is not int or media['id']<=0 or not (media.get('title') or media.get('name')):
        raise ValueError('collections.lists_identity_failed')
    poster=portrait_path(media.get('poster_path'))
    if not poster and provider=='imdb':
        try:poster=imdb_metadata(source,identifier,kind).get('poster_path')
        except ValueError:pass
    return {'provider':provider,'media_type':kind,'external_id':identifier,
            'title':media.get('title') or media.get('name'),
            'year':str(media.get('release_date') or media.get('first_air_date') or '')[:4],
            'poster_path':poster}
