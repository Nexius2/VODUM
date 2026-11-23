"""Local-only migration eligibility; no provider calls on navigation."""
from itertools import combinations

from db_manager import isolated_read_operation


@isolated_read_operation
def migration_topology(db):
    return [dict(row) for row in db.query("""
        SELECT s.id, LOWER(TRIM(s.type)) AS type, s.server_identifier,
          (SELECT TRIM(mu.external_user_id) FROM media_users mu
           WHERE mu.server_id=s.id AND LOWER(TRIM(mu.type))='plex'
             AND LOWER(TRIM(mu.role))='owner'
             AND TRIM(COALESCE(mu.external_user_id,''))<>''
           ORDER BY mu.id LIMIT 1) AS owner_id
        FROM servers s WHERE LOWER(TRIM(s.type)) IN ('plex','jellyfin')
    """)]


def compatible_topology_pair(source, destination):
    if source['id'] == destination['id']:
        return False
    if source['type'] == destination['type']:
        first = str(source.get('server_identifier') or '').strip()
        second = str(destination.get('server_identifier') or '').strip()
        if first and first == second:
            return False
    if source['type'] == destination['type'] == 'plex':
        return bool(source.get('owner_id') and destination.get('owner_id')
                    and source['owner_id'] != destination['owner_id'])
    return True


def has_migration_pair(servers):
    return any(compatible_topology_pair(first, second) for first, second in combinations(servers, 2))


def migrations_available(db):
    # Availability depends on configured identities, not transient outages.
    # Pair analysis still independently requires both servers to be online.
    return has_migration_pair(migration_topology(db))
