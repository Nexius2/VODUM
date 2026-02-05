import time
import requests

DISCORD_API = "https://discord.com/api/v10"


class DiscordSendError(Exception):
    pass


def is_discord_ready(settings: dict) -> bool:
    if not settings:
        return False
    try:
        enabled = int(settings.get("discord_enabled") or 0) == 1
    except Exception:
        enabled = False
    token = (settings.get("discord_bot_token") or "").strip()
    return bool(enabled and token)


def _auth_headers(token: str) -> dict:
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }

def validate_discord_bot_token(bot_token: str, timeout: int = 10) -> tuple[bool, str]:
    """
    Returns (ok, detail). If ok=True, detail is bot username; else detail is error message.
    """
    bot_token = (bot_token or "").strip()
    if not bot_token:
        return False, "Missing bot token"

    try:
        r = requests.get(
            f"{DISCORD_API}/users/@me",
            headers=_auth_headers(bot_token),
            timeout=timeout,
        )

        if r.status_code == 200:
            data = r.json() or {}
            username = data.get("username") or "bot"
            return True, username

        # 401/403 are typical for invalid token / insufficient auth
        if r.status_code in (401, 403):
            return False, "Invalid bot token"

        return False, f"Discord API error {r.status_code}: {r.text}"

    except Exception as e:
        return False, f"Discord validation failed: {e}"


def _sleep_from_429(resp: requests.Response) -> None:
    try:
        data = resp.json()
        retry_after = float(data.get("retry_after", 1.0))
    except Exception:
        retry_after = 1.0
    time.sleep(max(0.2, retry_after))


def send_discord_dm(bot_token: str, recipient_user_id: str, content: str, max_retries: int = 4) -> None:
    bot_token = (bot_token or "").strip()
    recipient_user_id = (recipient_user_id or "").strip()

    if not bot_token:
        raise DiscordSendError("Missing Discord bot token")
    if not recipient_user_id:
        raise DiscordSendError("Missing recipient discord_user_id")
    if not content:
        return

    headers = _auth_headers(bot_token)

    # 1) Create/open DM channel
    r = requests.post(
        f"{DISCORD_API}/users/@me/channels",
        headers=headers,
        json={"recipient_id": recipient_user_id},
        timeout=30,
    )
    if r.status_code == 429:
        _sleep_from_429(r)
        r = requests.post(
            f"{DISCORD_API}/users/@me/channels",
            headers=headers,
            json={"recipient_id": recipient_user_id},
            timeout=30,
        )

    if r.status_code >= 300:
        raise DiscordSendError(f"DM channel create failed: {r.status_code} {r.text}")

    channel_id = (r.json() or {}).get("id")
    if not channel_id:
        raise DiscordSendError("No channel_id returned by Discord")

    # 2) Send message (rate-limit friendly)
    payload = {"content": content[:1900]}
    for _ in range(max_retries):
        s = requests.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if s.status_code == 429:
            _sleep_from_429(s)
            continue
        if s.status_code >= 300:
            raise DiscordSendError(f"Message send failed: {s.status_code} {s.text}")
        return

    raise DiscordSendError("Rate limit: max retries reached")
