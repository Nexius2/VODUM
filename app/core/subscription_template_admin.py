SUBSCRIPTION_TEMPLATE_DUPLICATE_COLUMNS = """
    id,
    name,
    notes,
    duration_days,
    subscription_value,
    is_enabled,
    is_lifetime,
    policies_json
"""


def duplicate_subscription_template(db, template_id: int) -> dict:
    row = db.query_one(
        f"SELECT {SUBSCRIPTION_TEMPLATE_DUPLICATE_COLUMNS} "
        "FROM subscription_templates WHERE id = ?",
        (template_id,),
    )
    if not row:
        return {"ok": False, "reason": "subscription_template_not_found"}

    template = dict(row)
    base_name = (template.get("name") or "Template").strip()
    new_name = f"{base_name} - Copy"
    suffix = 2
    while db.query_one(
        "SELECT id FROM subscription_templates WHERE name = ?",
        (new_name,),
    ):
        new_name = f"{base_name} - Copy {suffix}"
        suffix += 1

    db.execute(
        """
        INSERT INTO subscription_templates(
          name,
          notes,
          duration_days,
          subscription_value,
          is_default,
          is_enabled,
          is_lifetime,
          policies_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_name,
            template.get("notes") or "",
            template.get("duration_days") or 30,
            template.get("subscription_value") or 0,
            0,
            int(template.get("is_enabled") or 0),
            int(template.get("is_lifetime") or 0),
            template.get("policies_json") or "[]",
        ),
    )
    return {"ok": True, "base_name": base_name, "new_name": new_name}


def toggle_subscription_template(db, template_id: int) -> dict:
    row = db.query_one(
        "SELECT id, name, is_enabled, is_default "
        "FROM subscription_templates WHERE id = ?",
        (template_id,),
    )
    if not row:
        return {"ok": False, "reason": "subscription_template_not_found"}

    template = dict(row)
    enabled = 0 if int(template.get("is_enabled") or 0) == 1 else 1
    db.execute(
        """
        UPDATE subscription_templates
        SET is_enabled = ?,
            is_default = CASE WHEN ? = 0 THEN 0 ELSE is_default END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (enabled, enabled, template_id),
    )
    return {
        "ok": True,
        "name": template.get("name"),
        "enabled": bool(enabled),
    }


def delete_subscription_template(db, template_id: int) -> dict:
    row = db.query_one(
        "SELECT id, name FROM subscription_templates WHERE id = ?",
        (template_id,),
    )
    if not row:
        return {"ok": False, "reason": "subscription_template_not_found"}

    template = dict(row)
    name = template.get("name") or f"#{template_id}"
    db.execute(
        "UPDATE vodum_users SET subscription_template_id = NULL "
        "WHERE subscription_template_id = ?",
        (template_id,),
    )
    db.execute("DELETE FROM subscription_templates WHERE id = ?", (template_id,))
    return {"ok": True, "name": name}
