"""Admin configuration based exclusively on synchronized VODUM libraries."""
SCHEMA = 'CREATE TABLE IF NOT EXISTS library_request_settings (\n library_id INTEGER PRIMARY KEY REFERENCES libraries(id) ON DELETE CASCADE,\n requests_enabled INTEGER NOT NULL DEFAULT 1 CHECK(requests_enabled IN (0,1)),\n request_priority INTEGER NOT NULL DEFAULT 100,\n default_for_requests INTEGER NOT NULL DEFAULT 0 CHECK(default_for_requests IN (0,1)),\n created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n);\nCREATE TABLE IF NOT EXISTS library_arr_routes (\n id INTEGER PRIMARY KEY AUTOINCREMENT,\n library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,\n arr_server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,\n priority INTEGER NOT NULL CHECK(priority>0),\n enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),\n created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n UNIQUE(library_id,arr_server_id), UNIQUE(library_id,priority)\n);\nCREATE INDEX IF NOT EXISTS idx_library_arr_routes_server ON library_arr_routes(arr_server_id);\n'


class RoutingConfigurationError(ValueError):
    pass


def compatible_arr_type(library_type):
    kind=str(library_type or "").strip().lower()
    if kind in ("movie","movies","film","films"):
        return "radarr"
    if kind in ("show","shows","tvshow","tvshows","series","serie","tv"):
        return "sonarr"
    return None


def load_request_routing(db, server_id):
    libraries=[dict(r) for r in (db.query("""SELECT l.id,l.name,l.type,s.name AS media_server_name,
        COALESCE(rs.requests_enabled,1) AS requests_enabled,
        COALESCE(rs.request_priority,100) AS request_priority,
        COALESCE(rs.default_for_requests,0) AS default_for_requests
        FROM libraries l LEFT JOIN library_request_settings rs ON rs.library_id=l.id
        JOIN servers s ON s.id=l.server_id
        WHERE (? IS NULL OR l.server_id=?) AND LOWER(TRIM(s.type)) IN ('plex','jellyfin')
        ORDER BY s.name,l.name,l.id""",(server_id,server_id)) or [])]
    instances=[dict(r) for r in (db.query("""SELECT id,name,LOWER(TRIM(type)) AS type,status
        FROM servers WHERE LOWER(TRIM(type)) IN ('sonarr','radarr') ORDER BY id""") or [])]
    routes=[dict(r) for r in (db.query("""SELECT r.library_id,r.arr_server_id,r.priority,r.enabled
        FROM library_arr_routes r JOIN libraries l ON l.id=r.library_id
        WHERE (? IS NULL OR l.server_id=?) ORDER BY r.priority,r.arr_server_id""",(server_id,server_id)) or [])]
    result=[]
    for library in libraries:
        provider=compatible_arr_type(library["type"])
        if not provider:
            continue
        associated={r["arr_server_id"]:r for r in routes if r["library_id"]==library["id"]}
        candidates=[]
        for instance in instances:
            if instance["type"]!=provider:
                continue
            row=dict(instance); row.update(associated.get(row["id"],{}))
            row["associated"]=row["id"] in associated
            candidates.append(row)
        candidates.sort(key=lambda r:(not r["associated"],r.get("priority",r["id"])))
        library.update(arr_type=provider,candidates=candidates,
                       fallback=next((i for i in instances if i["type"]==provider),None))
        result.append(library)
    return result


def save_request_routing(db,server_id,library_id,form):
    # Revalidate all IDs and compatibility inside the write transaction.
    try:
        selected=[int(v) for v in form.getlist("arr_server_id")]
        if len(selected)!=len(set(selected)):
            raise ValueError()
        library_priority=int(form.get("request_priority","100"))
        if not 1<=library_priority<=100000:
            raise ValueError()
        ranks=[int(form.get(f"priority_{i}","")) for i in selected]
        if any(not 1<=r<=100000 for r in ranks) or len(ranks)!=len(set(ranks)):
            raise ValueError()
    except (TypeError,ValueError):
        raise RoutingConfigurationError("request_routing_invalid") from None
    with db.transaction() as cur:
        library=cur.execute("""SELECT l.type FROM libraries l JOIN servers s ON s.id=l.server_id
            WHERE l.id=? AND l.server_id=? AND LOWER(TRIM(s.type)) IN ('plex','jellyfin')""",
            (library_id,server_id)).fetchone()
        provider=compatible_arr_type(library["type"]) if library else None
        if not provider:
            raise RoutingConfigurationError("request_routing_invalid")
        for target in selected:
            row=cur.execute("SELECT type FROM servers WHERE id=?",(target,)).fetchone()
            if not row or str(row["type"]).strip().lower()!=provider:
                raise RoutingConfigurationError("request_routing_invalid")
        cur.execute("""INSERT INTO library_request_settings
            (library_id,requests_enabled,request_priority,default_for_requests)
            VALUES(?,?,?,?) ON CONFLICT(library_id) DO UPDATE SET
            requests_enabled=excluded.requests_enabled,request_priority=excluded.request_priority,
            default_for_requests=excluded.default_for_requests,updated_at=CURRENT_TIMESTAMP""",
            (library_id,int(form.get("requests_enabled")=="1"),library_priority,
             int(form.get("default_for_requests")=="1")))
        cur.execute("DELETE FROM library_arr_routes WHERE library_id=?",(library_id,))
        for target,rank in zip(selected,ranks):
            cur.execute("""INSERT INTO library_arr_routes(library_id,arr_server_id,priority,enabled)
                VALUES(?,?,?,?)""",(library_id,target,rank,int(form.get(f"enabled_{target}")=="1")))


CONDITIONS_SCHEMA = """CREATE TABLE IF NOT EXISTS library_arr_conditions (
 library_id INTEGER NOT NULL,
 arr_server_id INTEGER NOT NULL,
 conditions_json TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(library_id,arr_server_id),
 FOREIGN KEY(library_id,arr_server_id) REFERENCES library_arr_routes(library_id,arr_server_id) ON DELETE CASCADE
);"""
SCHEMA += CONDITIONS_SCHEMA


def load_arr_request_routing(db,arr_id):
    import json
    result=[]
    conditions={r["library_id"]:r["conditions_json"] for r in db.query(
        "SELECT library_id,conditions_json FROM library_arr_conditions WHERE arr_server_id=?",(arr_id,))}
    for library in load_request_routing(db,None):
        current=next((r for r in library["candidates"] if r["id"]==arr_id),None)
        if current is None:
            continue
        library["current_arr"]=current
        library["conditions"]=json.loads(conditions.get(library["id"],"{}"))
        result.append(library)
    return result


def parse_conditions(form):
    def values(key):
        text=str(form.get(key) or "").strip()
        if len(text)>2000:
            raise RoutingConfigurationError("request_routing_invalid")
        return list(dict.fromkeys(v.strip() for v in text.split(',') if v.strip()))
    genres,collections,resolutions=values('genres'),values('collections'),form.getlist('resolutions')
    if any(v not in ('720p','1080p','2160p') for v in resolutions):
        raise RoutingConfigurationError("request_routing_invalid")
    return {"genres":genres,"collections":collections,"resolutions":list(dict.fromkeys(resolutions))}


def save_arr_request_routing(db,arr_id,library_id,form):
    import json
    criteria=parse_conditions(form)
    try:
        priority=int(form.get('arr_priority','1'))
        library_priority=int(form.get('request_priority','100'))
        if not 1<=priority<=100000 or not 1<=library_priority<=100000:
            raise ValueError()
    except (ValueError,TypeError):
        raise RoutingConfigurationError("request_routing_invalid") from None
    with db.transaction() as cur:
        arr=cur.execute("SELECT type FROM servers WHERE id=?",(arr_id,)).fetchone()
        lib=cur.execute("""SELECT l.type FROM libraries l JOIN servers s ON s.id=l.server_id
            WHERE l.id=? AND LOWER(TRIM(s.type)) IN ('plex','jellyfin')""",(library_id,)).fetchone()
        if not arr or not lib or compatible_arr_type(lib['type'])!=str(arr['type']).lower():
            raise RoutingConfigurationError("request_routing_invalid")
        if form.get('arr_order_present') == '1':
            existing = cur.execute('SELECT arr_server_id,priority FROM library_arr_routes WHERE library_id=? ORDER BY priority', (library_id,)).fetchall()
            try: order = [int(value) for value in form.getlist('arr_order')]
            except (TypeError,ValueError): raise RoutingConfigurationError('request_routing_invalid') from None
            expected = {r['arr_server_id'] for r in existing if r['arr_server_id'] != arr_id}
            if form.get('associated') == '1': expected.add(arr_id)
            if len(order) != len(set(order)) or set(order) != expected:
                # Reject stale or forged lists rather than dropping another association.
                raise RoutingConfigurationError('request_routing_invalid')
            temporary = max((r['priority'] for r in existing), default=0) + len(existing) + 1
            for offset,row in enumerate(existing):
                cur.execute('UPDATE library_arr_routes SET priority=? WHERE library_id=? AND arr_server_id=?', (temporary+offset,library_id,row['arr_server_id']))
            for rank,server_id in enumerate(order,1):
                if server_id != arr_id:
                    cur.execute('UPDATE library_arr_routes SET priority=?,updated_at=CURRENT_TIMESTAMP WHERE library_id=? AND arr_server_id=?',(rank,library_id,server_id))
            priority = order.index(arr_id)+1 if arr_id in order else 1
        if form.get('associated')=='1':
            conflict=cur.execute("SELECT arr_server_id FROM library_arr_routes WHERE library_id=? AND priority=? AND arr_server_id<>?",
                (library_id,priority,arr_id)).fetchone()
            if conflict:
                raise RoutingConfigurationError("request_routing_invalid")
            cur.execute("""INSERT INTO library_arr_routes(library_id,arr_server_id,priority,enabled)
                VALUES(?,?,?,?) ON CONFLICT(library_id,arr_server_id) DO UPDATE SET
                priority=excluded.priority,enabled=excluded.enabled,updated_at=CURRENT_TIMESTAMP""",
                (library_id,arr_id,priority,int(form.get('single_activation')=='1' or form.get('arr_enabled')=='1')))
            cur.execute("""INSERT INTO library_arr_conditions(library_id,arr_server_id,conditions_json)
                VALUES(?,?,?) ON CONFLICT(library_id,arr_server_id) DO UPDATE SET conditions_json=excluded.conditions_json""",
                (library_id,arr_id,json.dumps(criteria)))
        else:
            cur.execute("DELETE FROM library_arr_routes WHERE library_id=? AND arr_server_id=?",(library_id,arr_id))
        requests_enabled = int(form.get('requests_enabled') == '1')
        if form.get('single_activation') == '1':
            # Unlinking this ARR must not switch off requests routed to another instance.
            existing = cur.execute("SELECT requests_enabled FROM library_request_settings WHERE library_id=?", (library_id,)).fetchone()
            requests_enabled = 1 if form.get('associated') == '1' else (existing['requests_enabled'] if existing else 1)
        cur.execute("""INSERT INTO library_request_settings(library_id,requests_enabled,request_priority,default_for_requests)
            VALUES(?,?,?,?) ON CONFLICT(library_id) DO UPDATE SET requests_enabled=excluded.requests_enabled,
            request_priority=excluded.request_priority,default_for_requests=excluded.default_for_requests,updated_at=CURRENT_TIMESTAMP""",
            (library_id,requests_enabled,library_priority,int(form.get('default_for_requests')=='1')))


def route_matches_media(conditions,metadata):
    # Empty criteria match all media; populated dimensions combine with AND,
    # while values inside one dimension combine with OR. Missing metadata fails closed.
    def normalized(value):
        if isinstance(value,str): value=[value]
        return {str(v).strip().casefold() for v in (value or [])}
    for key in ('genres','collections','resolutions'):
        expected=normalized(conditions.get(key))
        actual=normalized(metadata.get('resolution') if key=='resolutions' else metadata.get(key))
        if expected and not expected.intersection(actual):return False
    return True



def save_arr_page(db,arr_id,form,server_values):
    from contextlib import contextmanager
    from werkzeug.datastructures import MultiDict
    from core.server_admin import update_server
    try:
        ids=[int(v) for v in form.getlist('routing_library_id')]
        if len(ids)!=len(set(ids)):
            raise ValueError()
    except (ValueError,TypeError):
        raise RoutingConfigurationError('request_routing_invalid') from None
    with db.transaction() as cur:
        class TransactionDb:
            @contextmanager
            def transaction(self):
                yield cur
            def execute(self,sql,params=()):
                return cur.execute(sql,params)
        proxy=TransactionDb()
        for library_id in ids:
            prefix=f'routing_{library_id}_'
            fields=MultiDict((key[len(prefix):],value) for key,value in form.items(multi=True) if key.startswith(prefix))
            save_arr_request_routing(proxy,arr_id,library_id,fields)
        update_server(proxy,arr_id,**server_values)
