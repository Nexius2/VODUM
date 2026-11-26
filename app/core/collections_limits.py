"""Hard membership limits apply to local media IDs, including partial refreshes."""


def removable_member_ids(current, desired, config):
    stale=set(map(str,current))-set(map(str,desired))
    if not config.get('preserve_existing') or config.get('limit'):
        return stale
    if 'preserve_existing_ids' in config:
        return stale-set(map(str,config['preserve_existing_ids']))
    return set()


def bounded_members(matches, existing, config):
    limit=int(config.get('limit') or 0)
    result=[]
    seen=set()
    rows=list(matches)
    if limit and config.get('preserve_existing'):
        rows+=list(existing)
    for row in rows:
        key=str(row['id'])
        if key in seen:continue
        seen.add(key)
        result.append(row)
        if limit and len(result)>=limit:break
    return result
