USER_MERGE_COLUMNS = """
    id,
    username,
    firstname,
    lastname,
    email,
    second_email,
    expiration_date,
    renewal_method,
    renewal_date,
    status,
    created_at,
    notes
"""


def _max_date(a, b):
    if not a:
        return b
    if not b:
        return a
    return max(str(a), str(b))  # OK si ISO

def merge_vodum_users(db, master_id: int, other_id: int) -> None:
    if master_id == other_id:
        return

    master = db.query_one(f"SELECT {USER_MERGE_COLUMNS} FROM vodum_users WHERE id=?", (master_id,))
    other = db.query_one(f"SELECT {USER_MERGE_COLUMNS} FROM vodum_users WHERE id=?", (other_id,))
    if not master or not other:
        raise ValueError("user not found")

    master = dict(master)
    other = dict(other)

    # ⚠️ IMPORTANT :
    # DBManager.execute() commit déjà (autocommit). Donc PAS de BEGIN/COMMIT/ROLLBACK ici.
    # Sinon tu as exactement "cannot commit/rollback - no transaction is active".

    # Ancien index trop strict :
    # il empêchait un même utilisateur VODUM d'avoir plusieurs comptes
    # Plex/Jellyfin sur le même serveur après un merge manuel.
    db.execute("DROP INDEX IF EXISTS uq_media_users_vodum_server")
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_media_users_vodum_server
        ON media_users(vodum_user_id, server_id)
        WHERE vodum_user_id IS NOT NULL
        """
    )

    # 1) Déplacer media_users
    db.execute(
        "UPDATE media_users SET vodum_user_id=? WHERE vodum_user_id=?",
        (master_id, other_id),
    )

    # 2) user_identities (éviter collisions UNIQUE)
    db.execute(
        """
        DELETE FROM user_identities
        WHERE vodum_user_id = ?
          AND EXISTS (
            SELECT 1
            FROM user_identities ui2
            WHERE ui2.vodum_user_id = ?
              AND ui2.type = user_identities.type
              AND COALESCE(ui2.server_id, -1) = COALESCE(user_identities.server_id, -1)
              AND ui2.external_user_id = user_identities.external_user_id
          )
        """,
        (other_id, master_id),
    )
    db.execute(
        "UPDATE user_identities SET vodum_user_id=? WHERE vodum_user_id=?",
        (master_id, other_id),
    )

    # 3) sent_emails (éviter collisions UNIQUE)
    db.execute(
        """
        DELETE FROM sent_emails
        WHERE user_id = ?
          AND EXISTS (
            SELECT 1
            FROM sent_emails se2
            WHERE se2.user_id = ?
              AND se2.template_type = sent_emails.template_type
              AND se2.expiration_date = sent_emails.expiration_date
          )
        """,
        (other_id, master_id),
    )
    db.execute(
        "UPDATE sent_emails SET user_id=? WHERE user_id=?",
        (master_id, other_id),
    )

    # 3bis) media_jobs (sinon supprimés par ON DELETE CASCADE)
    db.execute(
        "UPDATE media_jobs SET vodum_user_id=? WHERE vodum_user_id=?",
        (master_id, other_id),
    )

    # 3ter) Dédupliquer les media_users après merge
    # Cas typique :
    # - le master et le other avaient déjà chacun une ligne media_users
    #   pour le même serveur / même compte Plex-Jellyfin
    # - après UPDATE vodum_user_id, on se retrouve avec 2 lignes identiques
    duplicate_groups = db.query(
        """
        SELECT
            server_id,
            type,
            COALESCE(NULLIF(TRIM(external_user_id), ''), '__NO_EXTERNAL__') AS ext_key,
            LOWER(TRIM(COALESCE(username, ''))) AS user_key,
            COUNT(*) AS cnt
        FROM media_users
        WHERE vodum_user_id = ?
        GROUP BY
            server_id,
            type,
            COALESCE(NULLIF(TRIM(external_user_id), ''), '__NO_EXTERNAL__'),
            LOWER(TRIM(COALESCE(username, '')))
        HAVING COUNT(*) > 1
        """,
        (master_id,),
    )

    for grp in duplicate_groups:
        dup_rows = db.query(
            """
            SELECT id, details_json, raw_json
            FROM media_users
            WHERE vodum_user_id = ?
              AND server_id = ?
              AND type = ?
              AND COALESCE(NULLIF(TRIM(external_user_id), ''), '__NO_EXTERNAL__') = ?
              AND LOWER(TRIM(COALESCE(username, ''))) = ?
            ORDER BY
                CASE
                    WHEN COALESCE(NULLIF(TRIM(details_json), ''), '') <> '' THEN 0
                    ELSE 1
                END,
                CASE
                    WHEN COALESCE(NULLIF(TRIM(raw_json), ''), '') <> '' THEN 0
                    ELSE 1
                END,
                id ASC
            """,
            (
                master_id,
                grp["server_id"],
                grp["type"],
                grp["ext_key"],
                grp["user_key"],
            ),
        )

        if len(dup_rows) <= 1:
            continue

        keep_id = int(dup_rows[0]["id"])
        duplicate_ids = [int(r["id"]) for r in dup_rows[1:]]

        if not duplicate_ids:
            continue

        placeholders = ",".join("?" * len(duplicate_ids))

        # Rebrancher toutes les bibliothèques sur la ligne conservée
        db.execute(
            f"""
            INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
            SELECT ?, library_id
            FROM media_user_libraries
            WHERE media_user_id IN ({placeholders})
            """,
            (keep_id, *duplicate_ids),
        )

        # Supprimer les doublons media_users
        # media_user_libraries sera nettoyé par ON DELETE CASCADE
        db.execute(
            f"DELETE FROM media_users WHERE id IN ({placeholders})",
            tuple(duplicate_ids),
        )

    # 4) Merge champs (master prioritaire, other complète)
    merged = {}

    # expiration: garder la plus tardive
    merged["expiration_date"] = _max_date(
        master.get("expiration_date"), other.get("expiration_date")
    )

    # compléter identité
    for f in ("firstname", "lastname", "renewal_method", "renewal_date"):
        if not (master.get(f) or "").strip() and (other.get(f) or "").strip():
            merged[f] = other.get(f)

    # --- notes + emails (inchangé chez toi) ---
    base_notes = (master.get("notes") or "").strip()
    other_notes = (other.get("notes") or "").strip()

    m_email = (master.get("email") or "").strip()
    m_second = (master.get("second_email") or "").strip()

    o_email = (other.get("email") or "").strip()
    o_second = (other.get("second_email") or "").strip()

    def _same(a: str, b: str) -> bool:
        return (a or "").strip().lower() == (b or "").strip().lower()

    def add_note_line(line: str):
        nonlocal base_notes
        line = (line or "").strip()
        if not line:
            return
        if line in base_notes:
            return
        base_notes = (base_notes + "\n" + line).strip() if base_notes else line

    def push_second(val: str):
        nonlocal m_second
        val = (val or "").strip()
        if not val:
            return
        if _same(val, m_email) or _same(val, m_second):
            return
        if not m_second:
            m_second = val
            return
        add_note_line(f"[merge] email additionnel non stocké (second_email déjà pris): {val}")

    if not m_email and o_email:
        m_email = o_email
    elif m_email and o_email and not _same(m_email, o_email):
        push_second(o_email)

    if o_second and not _same(o_second, m_email):
        push_second(o_second)

    if m_email:
        merged["email"] = m_email
    merged["second_email"] = m_second or None

    if other_notes and other_notes not in base_notes:
        add_note_line("--- merged ---")
        add_note_line(other_notes)

    if base_notes != (master.get("notes") or "").strip():
        merged["notes"] = base_notes

    if merged:
        sets = ", ".join([f"{k}=?" for k in merged.keys()])
        db.execute(
            f"UPDATE vodum_users SET {sets} WHERE id=?",
            [*merged.values(), master_id],
        )

    # 5) Supprimer other
    db.execute("DELETE FROM vodum_users WHERE id=?", (other_id,))

def build_merge_preview(master: dict, other: dict) -> dict:
    """
    Reproduit les règles de merge_vodum_users, mais sans écrire en DB.
    Retourne:
      - result: dict des champs vodum_users après fusion
      - sources: dict champ -> 'master'|'target'|'computed'
      - notes_preview: notes finales
    """
    def _same(a: str, b: str) -> bool:
        return (a or "").strip().lower() == (b or "").strip().lower()

    def _max_date(a, b):
        if not a:
            return b
        if not b:
            return a
        return max(str(a), str(b))  # OK si ISO

    sources = {}
    result = dict(master)  # base = master

    # expiration_date = max(master, other) => computed
    exp = _max_date(master.get("expiration_date"), other.get("expiration_date"))
    result["expiration_date"] = exp
    sources["expiration_date"] = "computed"

    # Compléter certains champs si master vide
    for f in ("firstname", "lastname", "renewal_method", "renewal_date"):
        m = (master.get(f) or "").strip()
        o = (other.get(f) or "").strip()
        if not m and o:
            result[f] = other.get(f)
            sources[f] = "target"
        else:
            sources[f] = "master"

    # Emails + notes : mêmes règles que merge_vodum_users
    m_email = (master.get("email") or "").strip()
    m_second = (master.get("second_email") or "").strip()
    o_email = (other.get("email") or "").strip()
    o_second = (other.get("second_email") or "").strip()

    base_notes = (master.get("notes") or "").strip()
    other_notes = (other.get("notes") or "").strip()

    def add_note_line(line: str):
        nonlocal base_notes
        line = (line or "").strip()
        if not line:
            return
        if line in base_notes:
            return
        base_notes = (base_notes + "\n" + line).strip() if base_notes else line

    def push_second(val: str):
        nonlocal m_second
        val = (val or "").strip()
        if not val:
            return
        if _same(val, m_email) or _same(val, m_second):
            return
        if not m_second:
            m_second = val
            return
        add_note_line(f"[merge] email additionnel non stocké (second_email déjà pris): {val}")

    # email principal
    if not m_email and o_email:
        m_email = o_email
        sources["email"] = "target"
    else:
        sources["email"] = "master"

    if m_email and o_email and not _same(m_email, o_email):
        push_second(o_email)

    # second email other
    if o_second and not _same(o_second, m_email):
        push_second(o_second)

    # appliquer email/second_email
    result["email"] = m_email or None
    result["second_email"] = m_second or None

    # source second_email
    if (master.get("second_email") or "").strip():
        sources["second_email"] = "master"
    elif (result["second_email"] or "").strip():
        sources["second_email"] = "target"  # rempli via other
    else:
        sources["second_email"] = "master"

    # notes finales
    if other_notes and other_notes not in base_notes:
        add_note_line("--- merged ---")
        add_note_line(other_notes)

    result["notes"] = base_notes
    # notes = computed si ça a changé
    sources["notes"] = "computed" if (base_notes != (master.get("notes") or "").strip()) else "master"

    # Champs non modifiés dans merge_vodum_users : restent master
    # (username, status, etc.)
    for k in result.keys():
        sources.setdefault(k, "master")

    return {"result": result, "sources": sources}
