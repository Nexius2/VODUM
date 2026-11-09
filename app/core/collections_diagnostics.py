"""Public collection diagnostics use provider identities and stable VODUM names."""

def normalize_collection_result(result, model):
    if model != 'franchises':
        return result

    def source_name(value):
        return 'franchise_universe' if isinstance(value,str) and value.endswith('_universe') else value

    def normalize(value):
        if isinstance(value,list):
            return [normalize(item) for item in value]
        if not isinstance(value,dict):
            return value
        output={}
        for key,item in value.items():
            if key=='source_kind':
                output[key]=source_name(item)
            elif key=='sources' and isinstance(item,list):
                output[key]=list(dict.fromkeys(source_name(source) for source in item))
            elif key in ('source_kinds','ranks_by_source') and isinstance(item,dict):
                output[key]={source_name(source):content for source,content in item.items()}
            else:
                output[key]=normalize(item)
        return output
    return normalize(result)


def collection_count_snapshots(db):
    """Read one measured sync per instance independently of the history page limit."""
    import json
    snapshots={row['instance_id']:json.loads(row['count_json'])
               for row in db.query('SELECT instance_id,count_json FROM collection_last_counts')}
    for row in db.query("""SELECT i.id AS instance_id,r.id,r.started_at,r.finished_at,r.state,
            json_extract(r.result_json,'$.present') AS present,
            json_extract(r.result_json,'$.missing') AS missing,
            json_extract(r.result_json,'$.arr_requests') AS arr_requests
        FROM collection_instances i JOIN collection_runs r ON r.id=(
            SELECT c.id FROM collection_runs c WHERE c.instance_id=i.id AND c.kind='sync'
              AND json_type(c.result_json,'$.present') IN ('integer','real')
              AND json_type(c.result_json,'$.missing') IN ('integer','real')
              AND (c.state IN ('success','warning') OR
                   json_extract(c.result_json,'$.stage') IN ('publish','complete') AND c.state='running'
                   OR c.state='error' AND json_extract(c.result_json,'$.stage')='publish')
            ORDER BY c.id DESC LIMIT 1)"""):
        snapshots[row['instance_id']]={key:row[key] for key in ('id','started_at','finished_at','state','present','missing','arr_requests')}
    return snapshots
