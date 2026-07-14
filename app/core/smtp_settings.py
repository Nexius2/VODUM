def has_configured_secret(value) -> bool:
    return bool(str(value or "").strip())


def normalize_smtp_auth_method(requested: str, settings: dict, smtp_pass, smtp_oauth_access_token) -> str:
    method = (requested or "password").strip().lower()
    if method not in ("password", "oauth2"):
        method = "password"

    has_password = has_configured_secret(smtp_pass)
    has_oauth_token = has_configured_secret(smtp_oauth_access_token)

    # Avoid silently breaking an existing password setup if OAuth2 is selected
    # without providing or already having an OAuth token.
    if method == "oauth2" and not has_oauth_token and (
        has_password or has_configured_secret(settings.get("smtp_pass"))
    ):
        return "password"

    return method