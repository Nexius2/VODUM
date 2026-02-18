import time
import requests

DISCORD_API = "https://discord.com/api/v10"


class DiscordSendError(Exception):
    pass

def _as_dict(row_or_dict):
    if row_or_dict is None:
        return {}
    if isinstance(row_or_dict, dict):
        return row_or_dict
    try:
        return dict(row_or_dict)  # sqlite3.Row
    except Exception:
        return {}

# -------------------------------------------------------------------
# Bot selection / token resolution
# -------------------------------------------------------------------

def resolve_discord_bot(db, settings: dict) -> dict:
    """
    Returns a dict: {id, name, token, bot_username, bot_user_id, bot_type}.
    - If settings.discord_bot_id is set, pulls from discord_bots.
    - Else falls back to legacy settings.discord_bot_token.

    NOTE: db is expected to be a DBManager-like object with query_one().
    """
    s = _as_dict(settings)
    bot_id = s.get('discord_bot_id')
    try:
        bot_id = int(bot_id) if bot_id not in (None, '', 0, '0') else None
    except Exception:
        bot_id = None

    if bot_id and db is not None:
        try:
            row = db.query_one("SELECT * FROM discord_bots WHERE id = ?", (bot_id,))
            if row:
                b = dict(row)
                b['token'] = (b.get('token') or '').strip()
                return b
        except Exception:
            pass

    # Legacy fallback
    token = (s.get('discord_bot_token') or '').strip()
    return {
        'id': None,
        'name': 'Legacy token',
        'token': token,
        'bot_username': None,
        'bot_user_id': None,
        'bot_type': 'custom',
    }


def enrich_discord_settings(db, settings: dict) -> dict:
    """
    Mutates and returns settings with:
    - discord_bot_token_effective
    - discord_bot_username_effective
    - discord_bot_source ('bot_table'|'legacy')
    """
    s = _as_dict(settings)
    bot = resolve_discord_bot(db, s)
    s['discord_bot_token_effective'] = (bot.get('token') or '').strip()
    s['discord_bot_username_effective'] = bot.get('bot_username') or None
    s['discord_bot_source'] = 'bot_table' if bot.get('id') else 'legacy'
    return s



def is_discord_ready(settings: dict) -> bool:
    if not settings:
        return False
    try:
        enabled = int(settings.get("discord_enabled") or 0) == 1
    except Exception:
        enabled = False
    s = _as_dict(settings)
    token = (s.get('discord_bot_token_effective') or s.get('discord_bot_token') or '').strip()

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




def fetch_discord_bot_identity(bot_token: str, timeout: int = 10) -> tuple[bool, dict]:
    """
    Returns (ok, data).
    If ok=True, data includes: {id, username, global_name} when available.
    If ok=False, data includes: {error}.
    """
    bot_token = (bot_token or "").strip()
    if not bot_token:
        return False, {"error": "Missing bot token"}

    try:
        r = requests.get(
            f"{DISCORD_API}/users/@me",
            headers=_auth_headers(bot_token),
            timeout=timeout,
        )

        if r.status_code == 200:
            data = r.json() or {}
            return True, {
                "id": data.get("id"),
                "username": data.get("username"),
                "global_name": data.get("global_name"),
            }

        if r.status_code in (401, 403):
            return False, {"error": "Invalid bot token"}

        return False, {"error": f"Discord API error {r.status_code}: {r.text}"}

    except Exception as e:
        return False, {"error": f"Discord validation failed: {e}"}


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
