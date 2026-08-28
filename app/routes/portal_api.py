from flask import g, jsonify

from core.auth_principal import permission_required, portal_login_required, portal_user_required
from core.portal_page_data import load_portal_media_access, load_portal_profile, load_portal_subscription
from core.portal_rate_limit import portal_request_allowed
from web.helpers import get_db
from web.security import get_client_ip


def register(app):
    @app.get("/api/portal/v1/me")
    @portal_login_required
    @permission_required("portal.api.read_own")
    @portal_user_required
    def portal_api_me():
        db = get_db()
        if not portal_request_allowed(db, "api_me", get_client_ip(), limit=120):
            response = jsonify({"error": "rate_limited"}); response.status_code = 429
            response.headers["Retry-After"] = "900"; return response
        user_id = int(g.auth_principal["vodum_user_id"])
        profile = load_portal_profile(db, user_id)
        if not profile:
            return jsonify({"error": "account_missing"}), 404
        subscription = load_portal_subscription(db, user_id) or {}
        media = load_portal_media_access(db, user_id)
        safe_profile = {key: profile.get(key) for key in ("username", "firstname", "lastname", "email", "second_email", "status", "created_at")}
        safe_subscription = {key: subscription.get(key) for key in ("subscription_name", "status", "expiration_date", "renewal_date", "is_lifetime", "limits", "renewal_url")}
        safe_media = [{"type": item["type"], "username": item["username"], "server_name": item["server_name"], "server_status": item["server_status"], "invitation_status": item["invitation_status"], "libraries": item["libraries"]} for item in media]
        response = jsonify({"api_version": "v1", "profile": safe_profile, "subscription": safe_subscription, "media_access": safe_media})
        response.headers["Cache-Control"] = "no-store"; return response
