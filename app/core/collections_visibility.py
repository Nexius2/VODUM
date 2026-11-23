"""Publication destinations are independent of collection scheduling/enabled."""
import json

DESTINATIONS=('home','shared','recommended')


def collection_visibility(config):
    default=config.get('mode','published')=='published'
    values=config.get('visibility',{})
    if not isinstance(values,dict) or any(key not in DESTINATIONS or type(value) is not bool for key,value in values.items()):
        raise ValueError('collections.invalid_configuration')
    return {key:values.get(key,default) if default else False for key in DESTINATIONS}


def collection_sort_title(record, config, title):
    """Priority orders configurations; the stable instance key groups children."""
    priority = min(999,max(1,int(config.get('priority',10))))
    group = str(config.get('_priority_group_key') or record.get('instance_id') or '')
    return f'_{priority:03d}_{group}_{title}'


def priority_config(db,record,config):
    """Equal priorities follow creation order, keeping one configuration together."""
    if db is None or not record.get('instance_id'):return config
    row=db.query_one('''SELECT COALESCE(root.created_at,i.created_at) AS created_at,
        COALESCE(i.group_id,i.id) AS group_id,i.config_json FROM collection_instances i
        LEFT JOIN collection_instances root ON root.id=COALESCE(i.group_id,i.id)
        WHERE i.id=?''',(record['instance_id'],))
    if row is None:return config
    current=json.loads(row['config_json'])
    presentation={key:current[key] for key in ('visibility','priority','mode') if key in current}
    return {**config,**presentation,'_priority_group_key':str(row['created_at'])+'_'+str(row['group_id'])}


def run_visibility(db, instance, *, heartbeat=lambda:None, adapter_factory=None, reorder=True):
    from core.collections_media import media_adapter,PlexCollections
    config={**json.loads(instance['config_json']),'_collection_model':instance['model']}
    config['_visibility_only']=not reorder
    library=dict(db.query_one('SELECT * FROM libraries WHERE id=?',(instance['library_id'],)))
    server=dict(db.query_one('SELECT * FROM servers WHERE id=?',(library['server_id'],)))
    adapter=(adapter_factory or media_adapter)(server,library)
    adapter.heartbeat=heartbeat
    adapter.collection_db=db
    adapter.collection_library_id=library['id']
    if isinstance(adapter,PlexCollections):
        adapter.defer_library_reorder=True
        adapter._verified_presentations={}
    result={'warnings':[],'errors':[],'outcome':'visibility','stage':'publish','diagnostics':{'visibility_failures':[]}}
    try:
        for row in db.query("SELECT * FROM collection_objects WHERE instance_id=? AND remote_id IS NOT NULL AND state!='deleted'",(instance['id'],)):
            heartbeat()
            try:
                result['warnings'].extend(adapter.apply_visibility(dict(row),config) or [])
            except Exception as exc:
                from core.collections_repository import CollectionRunCancelled
                if isinstance(exc,CollectionRunCancelled):raise
                from core.error_reporting import log_handled_failure
                log_handled_failure('collections.visibility.object',level='error',
                    context={'collection_name':instance['name'],'instance_id':instance['id'],'library_name':library['name'],
                        'server_name':server['name'],'object_title':row['title']},library_id=library['id'],server_id=server['id'])
                result['warnings'].append('collections.priority_not_applied')
                result['diagnostics']['visibility_failures'].append({'object_id':row['id'],
                    'title':row['title'],'error_type':type(exc).__name__})
        if reorder and isinstance(adapter,PlexCollections):
            try:result['warnings'].extend(adapter.reorder_owned_collections(db) or [])
            except Exception as exc:
                from core.collections_repository import CollectionRunCancelled
                if isinstance(exc,CollectionRunCancelled):raise
                from core.error_reporting import log_handled_failure
                log_handled_failure('collections.visibility.library',level='error')
                result['warnings'].append('collections.priority_not_applied')
        result['warnings']=list(dict.fromkeys(result['warnings']))
        return result
    finally:
        adapter.close()
