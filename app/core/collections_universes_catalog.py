"""Stable franchise keys and titles, backed by the bundled local lists."""
from core.collections_franchise_lists import CATALOG
UNIVERSES={row['id']:{'title':row['name'],'provider':'vodum','media_types':['movie','tv']} for row in CATALOG['lists']}
