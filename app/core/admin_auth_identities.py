from __future__ import annotations

from secret_store import decrypt_secret, encrypt_secret


class AdminIdentityConflict(ValueError):
    pass


def get_admin_auth_identity(db, provider: str) -> dict | None:
    row = db.query_one(
        """
        SELECT id, provider, provider_subject, display_name, display_email,
               is_active, linked_at, last_login_at
        FROM admin_auth_identities
        WHERE admin_account_id = 1 AND provider = ?
        """,
        (provider,),
    )
    return dict(row) if row else None


def link_admin_auth_identity(
    db,
    *,
    provider: str,
    subject: str,
    display_name: str = "",
    display_email: str = "",
    allow_replace: bool = False,
) -> dict:
    normalized_provider = str(provider or "").strip().lower()
    normalized_subject = str(subject or "").strip()
    if not normalized_provider or not normalized_subject:
        raise ValueError("provider and subject are required")

    existing = get_admin_auth_identity(db, normalized_provider)
    replacing = existing and existing["provider_subject"] != normalized_subject
    if replacing and not allow_replace:
        raise AdminIdentityConflict(
            "A different identity is already linked for this provider"
        )

    if existing:
        db.execute(
            """
            UPDATE admin_auth_identities
            SET provider_subject = ?, display_name = ?, display_email = ?,
                is_active = 1, linked_at = CASE WHEN provider_subject != ?
                    THEN CURRENT_TIMESTAMP ELSE linked_at END,
                discovery_token_enc = CASE WHEN provider_subject != ?
                    THEN NULL ELSE discovery_token_enc END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                normalized_subject,
                display_name or None,
                display_email or None,
                normalized_subject,
                normalized_subject,
                existing["id"],
            ),
        )
    else:
        db.execute(
            """
            INSERT INTO admin_auth_identities(
                admin_account_id, provider, provider_subject,
                display_name, display_email, is_active
            ) VALUES (1, ?, ?, ?, ?, 1)
            """,
            (
                normalized_provider,
                normalized_subject,
                display_name or None,
                display_email or None,
            ),
        )
    return get_admin_auth_identity(db, normalized_provider)


def unlink_admin_auth_identity(db, *, provider: str) -> bool:
    normalized_provider = str(provider or "").strip().lower()
    if not normalized_provider or normalized_provider == "local":
        raise ValueError("Only a non-local authentication identity may be unlinked")
    existing = get_admin_auth_identity(db, normalized_provider)
    if not existing:
        return False
    db.execute(
        "DELETE FROM admin_auth_identities WHERE id = ?",
        (existing["id"],),
    )
    return True


def set_admin_auth_discovery_token(db, identity_id: int, token: str) -> None:
    secret = str(token or "").strip()
    if not secret:
        return
    db.execute(
        "UPDATE admin_auth_identities SET discovery_token_enc=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (encrypt_secret(secret), int(identity_id)),
    )


def get_admin_auth_discovery_token(db, provider: str) -> str:
    row = db.query_one(
        "SELECT discovery_token_enc FROM admin_auth_identities WHERE admin_account_id=1 AND provider=? AND is_active=1",
        (str(provider or "").strip().lower(),),
    )
    return decrypt_secret(row["discovery_token_enc"]) if row and row["discovery_token_enc"] else ""


def sync_local_admin_identity(db, admin_email: str) -> dict | None:
    """Keep local identity metadata aligned with the credential in settings."""
    email = str(admin_email or "").strip()
    if not email:
        return None
    return link_admin_auth_identity(
        db,
        provider="local",
        subject=email.casefold(),
        display_email=email,
        allow_replace=True,
    )
