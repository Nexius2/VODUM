"""Delete historical rows in independently committed, bounded batches."""
import re
import time


def delete_retained_rows(db, table, predicate, params, *, batch_size=500):
    if not re.fullmatch(r'[a-z_]+', table):
        raise ValueError('Invalid retention table')
    batch_size = max(1, min(int(batch_size), 500))
    horizon = db.query_one(f'SELECT MAX(rowid) AS last_id FROM {table}')
    if not horizon or horizon['last_id'] is None:
        return 0
    last_id, high_id, total = -9223372036854775808, horizon['last_id'], 0
    while True:
        rows = db.query(f'SELECT rowid AS retention_id FROM {table} '
                        f'WHERE rowid > ? AND rowid <= ? AND ({predicate}) '
                        'ORDER BY rowid LIMIT ?', (last_id, high_id, *params, batch_size))
        if not rows:
            return total
        ids = [row['retention_id'] for row in rows]
        # Recheck the predicate: another writer may have corrected a date.
        cursor = db.execute(f'DELETE FROM {table} WHERE rowid IN '
                            f'({",".join("?" for _ in ids)}) AND ({predicate})', (*ids, *params))
        total += max(int(cursor.rowcount or 0), 0)
        last_id = ids[-1]
        if len(ids) < batch_size:
            return total
        # The DB lock was released by execute(); give interactive writers a turn.
        time.sleep(0.005)
