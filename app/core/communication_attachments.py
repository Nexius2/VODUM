from communications_engine import store_uploads


def remove_template_attachments(db, template_id: int, attachment_ids):
    """Detach selected files from this template only, when its form is saved."""
    for value in set(attachment_ids):
        if str(value).isdigit():
            db.execute('DELETE FROM comm_template_attachments WHERE template_id=? AND id=?',
                       (int(template_id), int(value)))


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
