"""User-scoped saved health; never probes services or exposes connection data."""
from db_manager import isolated_read_operation
from core.library_request_routing import compatible_arr_type


def health_state(value):
    value=str(value or '').strip().lower()
    return 'up' if value in {'up','online'} else 'down' if value in {'down','offline'} else 'unknown'


@isolated_read_operation
def load_portal_system_status(db, user_id):
    direct={}
    for row in db.query("""SELECT DISTINCT s.id,s.name,s.type,s.status,s.last_checked,s.unavailable_since,
            l.id AS library_id,l.name AS library_name
        FROM media_users mu JOIN servers s ON s.id=mu.server_id
        LEFT JOIN media_user_libraries mul ON mul.media_user_id=mu.id
        LEFT JOIN libraries l ON l.id=mul.library_id AND l.server_id=s.id
        WHERE mu.vodum_user_id=? AND LOWER(TRIM(s.type)) IN ('plex','jellyfin')
        ORDER BY s.name,s.id,l.name""",(int(user_id),)):
        row=dict(row)
        system=direct.setdefault(row['id'],{'id':row['id'],'name':row['name'],'type':row['type'],
            'status':health_state(row['status']),'last_checked':row['last_checked'],'offline_since':row.get('unavailable_since') if health_state(row['status'])=='down' else None,'libraries':[]})
        if row['library_id'] is not None and row['library_name'] not in system['libraries']:
            system['libraries'].append(row['library_name'])
    indirect={}
    for row in db.query("""SELECT DISTINCT s.id,s.name,s.type,s.status,s.last_checked,s.unavailable_since,
            l.id AS library_id,l.name AS library_name,l.type AS library_type,ms.name AS media_server_name
        FROM media_users mu JOIN media_user_libraries mul ON mul.media_user_id=mu.id
        JOIN libraries l ON l.id=mul.library_id AND l.server_id=mu.server_id
        JOIN servers ms ON ms.id=l.server_id
        JOIN library_arr_routes r ON r.library_id=l.id AND r.enabled=1
        JOIN servers s ON s.id=r.arr_server_id
        WHERE mu.vodum_user_id=? AND LOWER(TRIM(ms.type)) IN ('plex','jellyfin')
            AND LOWER(TRIM(s.type)) IN ('sonarr','radarr')
        ORDER BY s.name,s.id,l.name""",(int(user_id),)):
        row=dict(row)
        if compatible_arr_type(row['library_type'])!=str(row['type']).strip().lower():continue
        system=indirect.setdefault(row['id'],{'id':row['id'],'name':row['name'],'type':row['type'],
            'status':health_state(row['status']),'last_checked':row['last_checked'],'offline_since':row.get('unavailable_since') if health_state(row['status'])=='down' else None,'libraries':[]})
        label=row['media_server_name']+' / '+row['library_name']
        if label not in system['libraries']:system['libraries'].append(label)
    systems=[*direct.values(),*indirect.values()]
    systems.sort(key=lambda row:({'down':0,'unknown':1,'up':2}[row['status']],str(row['name'] or '').casefold(),row['id']))
    return {'direct':direct,'services':list(indirect.values()),'systems':systems,
        'counts':{state:sum(row['status']==state for row in systems) for state in ('up','down','unknown')}}
