"""Keep welcome credentials encrypted until the email is rendered."""
import html

from secret_store import encrypt_secret, decrypt_secret


def encrypted_credential(server, username, password):
    return {"server_id": int(server["id"]), "server_name": server.get("name") or "Jellyfin",
            "server_url": server.get("public_url") or server.get("url") or server.get("local_url") or "",
            "username": username, "encrypted_password": encrypt_secret(password)}


def credential_context(payload, *, provider=None):
    credentials = payload.get("jellyfin_credentials") or []
    decoded = [(item, decrypt_secret(item["encrypted_password"])) for item in credentials]
    if not decoded:
        # Compatibility with migration welcome emails using the older variable.
        password = payload.get("temporary_password") if provider == "jellyfin" else ""
        return {"jellyfin_password": password or "", "jellyfin_username": (payload.get("login_username") or "") if password else ""}
    def combined(get_value):
        values = [get_value(item, password) for item, password in decoded]
        if len(set(values)) == 1:
            return values[0]
        return "\n".join(f"{item['server_name']}: {value}" for (item, _), value in zip(decoded, values))
    context = {"jellyfin_password": combined(lambda item, password: password),
               "jellyfin_username": combined(lambda item, password: item["username"])}
    if provider == "jellyfin":
        context["login_username"] = context["jellyfin_username"]
        context["server_url"] = combined(lambda item, password: item.get("server_url") or "")
    return context


def redact_credential_context(context):
    return {key: value for key, value in context.items()
            if key not in {"jellyfin_credentials", "jellyfin_password", "temporary_password"}}


def redact_credential_body(body, context):
    secrets = [context.get("jellyfin_password"), context.get("temporary_password")]
    secrets.extend(decrypt_secret(item["encrypted_password"]) for item in context.get("jellyfin_credentials") or [])
    for password in sorted({str(value) for value in secrets if value}, key=len, reverse=True):
        body = body.replace(password, "[Jellyfin password]")
        body = body.replace(html.escape(password), "[Jellyfin password]")
    return body
