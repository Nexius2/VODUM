"""Common publication order, independent of discovery and acquisition ranking."""
import hashlib
from bisect import bisect_left
from datetime import datetime, timezone


def stationary_members(current, desired):
    """Keep the longest already ordered subsequence to minimize Plex moves."""
    positions={key:index for index,key in enumerate(desired)}
    sequence=[key for key in current if key in positions]
    tails=[]
    indices=[]
    previous=[-1]*len(sequence)
    for index,key in enumerate(sequence):
        position=positions[key]
        slot=bisect_left(tails,position)
        if slot:previous[index]=indices[slot-1]
        if slot==len(tails):
            tails.append(position);indices.append(index)
        else:
            tails[slot]=position;indices[slot]=index
    keep=set()
    index=indices[-1] if indices else -1
    while index>=0:
        keep.add(sequence[index]);index=previous[index]
    return keep


def added_timestamp(row):
    value=row.get('added_at')
    if value is None:
        item=row.get('item')
        fields=item if isinstance(item,dict) else vars(item) if hasattr(item,'__dict__') else {}
        value=fields.get('addedAt') or fields.get('DateCreated')
    if isinstance(value,(int,float)):return value
    try:
        if isinstance(value,str) and value.isdigit():return float(value)
        parsed=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
    except (ValueError,TypeError,OverflowError):return float('-inf')


def order_media(rows, config):
    rows=list(rows)
    sort=config.get('sort')
    if sort=='added':
        return sorted(rows,key=lambda row:(added_timestamp(row),str(row['id'])),reverse=True)
    if sort=='release' and not config.get('native_release_order'):
        def release_date(row):
            item=row.get('item')
            fields=item if isinstance(item,dict) else vars(item) if hasattr(item,'__dict__') else {}
            value=row.get('release_date') or fields.get('originallyAvailableAt') or fields.get('PremiereDate')
            if not value:
                year=row.get('year') or fields.get('year')
                if str(year or '').isdigit() and 1<=int(year)<=9999:
                    value=f'{int(year):04d}-01-01'
            try:
                return datetime.fromisoformat(str(value).replace('Z','+00:00')).date().toordinal()
            except (ValueError,TypeError,OverflowError):
                return 0
        return sorted(rows,key=release_date,reverse=True)
    if sort=='random':
        seed=str(config.get('_order_seed') or datetime.now(timezone.utc).date().isoformat())
        return sorted(rows,key=lambda row:hashlib.sha256((seed+':'+str(row['id'])).encode()).digest())
    return rows
