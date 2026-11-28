from __future__ import annotations
from core.portal_provider_identity_state import row_media_identity_is_usable
from core.portal_account_state import ensure_provider_portal_account


class PlexPortalLinkAmbiguous(ValueError):
    def __init__(self, candidate_user_ids):
        self.candidate_user_ids = tuple(sorted({int(value) for value in candidate_user_ids}))
        super().__init__("portal_plex_link_ambiguous")


def resolve_plex_portal_account(db, provider_subject: str, *, provider_email="", confirmed_vodum_user_id=None) -> dict | None:
    subject = str(provider_subject or "").strip()
    if not subject:
        raise ValueError("portal_plex_identity_invalid")
    linked = db.query_one(
        "SELECT pai.portal_account_id,pa.vodum_user_id FROM portal_auth_identities pai "
        "JOIN portal_accounts pa ON pa.id=pai.portal_account_id "
        "WHERE pai.provider='plex' AND pai.provider_subject=? AND pai.is_active=1",
        (subject,),
    )
    if linked:
        return dict(linked)
    rows = db.query(
        "SELECT vodum_user_id,details_json FROM media_users WHERE type='plex' "
        "AND external_user_id=? AND vodum_user_id IS NOT NULL",
        (subject,),
    ) or []
    candidates = {int(row["vodum_user_id"]) for row in rows if row_media_identity_is_usable(row)}
    # Older Plex imports may not have persisted the numeric Plex id. The e-mail
    # returned by Plex is then a safe secondary match, but only among users who
    # actually have a usable Plex media account in VODUM.
    email = str(provider_email or "").strip().casefold()
    if not candidates and email:
        rows = db.query(
            "SELECT vodum_user_id,details_json FROM media_users WHERE type='plex' "
            "AND LOWER(TRIM(COALESCE(email,'')))=? AND vodum_user_id IS NOT NULL",
            (email,),
        ) or []
        candidates = {int(row["vodum_user_id"]) for row in rows if row_media_identity_is_usable(row)}
    if not candidates:
        return None
    if len(candidates) > 1 and confirmed_vodum_user_id is None:
        raise PlexPortalLinkAmbiguous(candidates)
    selected = int(confirmed_vodum_user_id) if confirmed_vodum_user_id is not None else next(iter(candidates))
    if selected not in candidates:
        raise ValueError("portal_plex_confirmation_invalid")
    account_id = ensure_provider_portal_account(db, selected)
    if account_id is None:
        return None
    db.execute(
        "INSERT INTO portal_auth_identities(portal_account_id,provider,provider_subject,is_active,verified_at) "
        "VALUES(?,'plex',?,1,CURRENT_TIMESTAMP)",
        (account_id, subject),
    )
    return {"portal_account_id": account_id, "vodum_user_id": selected}
