from core.migrations.analysis import SUPPORTED_PROVIDERS, is_server_online


def online_migration_servers(db) -> list[dict]:
    return [
        dict(row)
        for row in db.query(
            """
            SELECT id, name, type, status, last_checked
            FROM servers
            ORDER BY lower(name), id
            """
        )
        if str(row["type"] or "").strip().lower() in SUPPORTED_PROVIDERS
        and is_server_online(row["status"])
    ]


def mapping_overrides_from_form(form, prefix: str = "library_mapping_") -> dict[int, list[int]]:
    overrides: dict[int, list[int]] = {}
    for key in form.keys():
        if not key.startswith(prefix):
            continue
        try:
            source_library_id = int(key[len(prefix):])
        except (TypeError, ValueError):
            continue
        destination_ids = []
        for value in form.getlist(key):
            try:
                if str(value).strip():
                    destination_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        overrides[source_library_id] = sorted(set(destination_ids))
    return overrides


def group_mapping_rows(rows: list[dict]) -> list[dict]:
    groups: dict[int, dict] = {}
    for row in rows:
        source_id = int(row["source_library_id"])
        group = groups.setdefault(source_id, {
            "source_library_id": source_id,
            "source_name": row.get("source_name"),
            "source_type": row.get("source_type"),
            "mapping_status": row.get("mapping_status"),
            "destination_library_ids": [],
            "destinations": [],
        })
        if row.get("destination_library_id"):
            destination_id = int(row["destination_library_id"])
            if destination_id not in group["destination_library_ids"]:
                group["destination_library_ids"].append(destination_id)
                group["destinations"].append({
                    "id": destination_id,
                    "name": row.get("destination_name"),
                    "type": row.get("destination_type"),
                })
                group["mapping_status"] = "mapped"
    return list(groups.values())
