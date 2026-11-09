"""Keep one completed result and the latest publication per remote object."""
import json


def _published_objects(cursor, instance_id):
    return dict(cursor.execute("""SELECT person_key,id FROM collection_objects
        WHERE instance_id=? AND remote_id IS NOT NULL AND state!='deleted'""",
        (instance_id,)).fetchall())


def _save_publications(cursor, objects, run_id, people):
    for person in people:
        key = person.get('person_key')
        if key not in objects or person.get('published') is not True:
            continue
        cursor.execute("""INSERT INTO collection_publication_snapshots VALUES(?,?,?)
            ON CONFLICT(object_id) DO UPDATE SET run_id=excluded.run_id,
                publication_json=excluded.publication_json
            WHERE excluded.run_id > collection_publication_snapshots.run_id""",
            (objects.pop(key), run_id, json.dumps(person, ensure_ascii=False)))


def _save_last_counts(cursor, instance_id):
    row = cursor.execute("""SELECT id,started_at,finished_at,state,
            json_extract(result_json,'$.present') AS present,
            json_extract(result_json,'$.missing') AS missing,
            json_extract(result_json,'$.arr_requests') AS arr_requests
        FROM collection_runs WHERE instance_id=? AND kind='sync'
          AND json_type(result_json,'$.present') IN ('integer','real')
          AND json_type(result_json,'$.missing') IN ('integer','real')
          AND (state IN ('success','warning')
               OR (state='error' AND json_extract(result_json,'$.stage')='publish'))
        ORDER BY id DESC LIMIT 1""", (instance_id,)).fetchone()
    if row:
        cursor.execute("""INSERT INTO collection_last_counts VALUES(?,?)
            ON CONFLICT(instance_id) DO UPDATE SET count_json=excluded.count_json""",
            (instance_id, json.dumps(dict(row))))


def prune_finished_runs(cursor, instance_id):
    """Keep counters before pruning and roll up the telemetry for removed runs."""
    _save_last_counts(cursor, instance_id)
    latest = cursor.execute("""SELECT MAX(id) FROM collection_runs
        WHERE instance_id=? AND state!='running'""", (instance_id,)).fetchone()[0]
    if latest is None:
        return
    cursor.execute("""INSERT INTO collection_run_daily_totals(day,runs,failures,warnings)
        SELECT substr(started_at,1,10),COUNT(*),SUM(state='error'),SUM(state='warning')
        FROM collection_runs
        WHERE instance_id=? AND id!=? AND state IN ('success','warning','error')
          AND kind='sync' AND started_at>=date('now','-30 days')
        GROUP BY substr(started_at,1,10)
        ON CONFLICT(day) DO UPDATE SET runs=runs+excluded.runs,
            failures=failures+excluded.failures,warnings=warnings+excluded.warnings""",
        (instance_id, latest))
    cursor.execute("""DELETE FROM collection_runs
        WHERE instance_id=? AND id!=? AND state!='running'""", (instance_id, latest))


def store_finished_run(cursor, instance_id, run_id, kind, state, result, error_type, finished_at):
    if kind != 'preview':
        _save_publications(cursor, _published_objects(cursor, instance_id), run_id, result.get('people', []))
    summary = {key:value for key,value in result.items() if key != 'people'}
    cursor.execute("""UPDATE collection_runs SET state=?,result_json=?,error_type=?,finished_at=?
        WHERE id=?""", (state, json.dumps(summary), error_type, finished_at, run_id))
    prune_finished_runs(cursor, instance_id)
    cursor.execute("UPDATE collection_instances SET history_compacted=1 WHERE id=?", (instance_id,))


def compact_legacy_collection_history(db):
    """Migrate one instance per transaction, outside database bootstrap."""
    for instance in db.query("""SELECT id FROM collection_instances WHERE history_compacted=0
        AND EXISTS (SELECT 1 FROM collection_runs WHERE instance_id=collection_instances.id)"""):
        instance_id = instance['id']
        with db.transaction() as cursor:
            current = cursor.execute("""SELECT history_compacted,lease_id FROM collection_instances
                WHERE id=?""", (instance_id,)).fetchone()
            if not current or current[0] or current[1]:
                continue
            objects = _published_objects(cursor, instance_id)
            # Read one large result at a time, starting with the newest.
            if objects:
                runs = cursor.connection.execute("""SELECT id,result_json FROM collection_runs
                    WHERE instance_id=? AND kind!='preview' AND state!='running'
                    ORDER BY id DESC""", (instance_id,))
                try:
                    for run_id, payload in runs:
                        _save_publications(cursor, objects, run_id, json.loads(payload).get('people', []))
                        if not objects:
                            break
                finally:
                    runs.close()
            prune_finished_runs(cursor, instance_id)
            cursor.execute("""UPDATE collection_runs SET result_json=json_remove(result_json,'$.people')
                WHERE instance_id=? AND state!='running'""", (instance_id,))
            cursor.execute("UPDATE collection_instances SET history_compacted=1 WHERE id=?", (instance_id,))
    db.execute("DELETE FROM collection_run_daily_totals WHERE day<date('now','-30 days')")
