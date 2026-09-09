from secret_store import decrypt_secret


def jellyfin_headers(token=None):
    """Modern Jellyfin authorization (also supported by older servers)."""
    authorization = 'MediaBrowser Client="VODUM", Device="Server", DeviceId="vodum", Version="1"'
    secret = (decrypt_secret(token) or "").strip()
    if secret:
        if any(ord(char) < 32 or char in '\\"' for char in secret):
            raise ValueError("Invalid Jellyfin API key format")
        authorization += f', Token="{secret}"'
    return {"Authorization": authorization, "Accept": "application/json"}
