"""Transactional, opt-in migration of reviewed franchise catalogues. No network."""
import hashlib
import json
from core.collection_lists import validate_catalog,_install_catalog,read_cursor
from core.collection_list_catalog_review import require_release_catalog
from core.collections_repository import stamp


def legacy_group_state(db,instance):
    with read_cursor(db) as cur:
        group=instance.get('group_id') or instance['id']
        if not cur.execute('SELECT 1 FROM collection_list_legacy_groups WHERE group_id=?',(group,)).fetchone():
            return {}
        return dict(cur.execute('SELECT list_id,legacy_key FROM collection_list_legacy_keys').fetchall())


def migrate_franchise_catalog(db,catalog):
    """Install and migrate atomically; repeat calls never recreate detached bindings."""
    require_release_catalog(catalog)
    validate_catalog(catalog)
    digest=hashlib.sha256(json.dumps(catalog,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    with db.transaction() as cur:
        instances=[dict(row) for row in cur.execute("SELECT * FROM collection_instances WHERE model='franchises'").fetchall()]
        for instance in instances:
            if instance['lease_id'] or instance['lease_until'] and instance['lease_until']>stamp() or instance['requested'] not in (None,'sync'):
                raise ValueError('collections.busy')
            for row in catalog['lists']:
                new=cur.execute('SELECT id FROM collection_objects WHERE instance_id=? AND person_key=?',(instance['id'],'list:movie:'+row['id'])).fetchone()
                if new:
                    # A separately published list cannot be silently adopted,
                    # even if no legacy object remains in this instance.
                    raise ValueError('collections.title_collision')
        changed=_install_catalog(cur,catalog,digest)
        for row in catalog['lists']:
            prior=cur.execute('SELECT legacy_key FROM collection_list_legacy_keys WHERE list_id=?',(row['id'],)).fetchone()
            if prior and prior[0]!=row['legacy_key']:
                raise ValueError('collections.invalid_configuration')
            cur.execute('INSERT OR IGNORE INTO collection_list_legacy_keys VALUES(?,?)',(row['id'],row['legacy_key']))
        groups={instance.get('group_id') or instance['id'] for instance in instances}
        migrated=[]
        for group in sorted(groups):
            inserted=cur.execute('INSERT OR IGNORE INTO collection_list_legacy_groups VALUES(?)',(group,)).rowcount
            if inserted:
                migrated.append(group)
                for row in catalog['lists']:
                    cur.execute('INSERT OR IGNORE INTO collection_list_bindings VALUES(?,?)',(row['id'],group))
            if inserted or changed:
                for instance in instances:
                    if (instance.get('group_id') or instance['id'])!=group:
                        continue
                    cur.execute('DELETE FROM collection_publication_batches WHERE instance_id=?',(instance['id'],))
                    cur.execute('DELETE FROM collection_publication_plans WHERE instance_id=?',(instance['id'],))
                    if instance['enabled'] and not instance['retired']:
                        cur.execute("UPDATE collection_instances SET requested=COALESCE(requested,'sync'),state='queued' WHERE id=?",(instance['id'],))
    return {'catalog_changed':changed,'migrated_groups':migrated}
