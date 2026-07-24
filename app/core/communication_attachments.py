from communications_engine import store_uploads


def store_communication_attachments(db, kind: str, owner_id: int, files) -> list[dict]:
    saved = store_uploads(kind, int(owner_id), files)
    if kind == "campaign":
        sql = "INSERT INTO comm_campaign_attachments(campaign_id, filename, mime_type, path) VALUES(?,?,?,?)"
    elif kind == "template":
        sql = "INSERT INTO comm_template_attachments(template_id, filename, mime_type, path) VALUES(?,?,?,?)"
    else:
        raise ValueError(f"Unsupported communication attachment kind: {kind}")
    for attachment in saved:
        db.execute(sql, (owner_id, attachment["filename"], attachment.get("mime_type"), attachment["path"]))
    return saved
