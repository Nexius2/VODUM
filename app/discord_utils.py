import time
import requests
from secret_store import decrypt_secret

DISCORD_API = "https://discord.com/api/v10"
DISCORD_SAFE_MESSAGE_LENGTH = 1900


class DiscordSendError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code

    def diagnostic(self) -> str:
        retry_kind = "temporary" if self.retryable else "permanent"
        status = f", HTTP {self.status_code}" if self.status_code else ""
        return f"Discord [{self.code}, {retry_kind}{status}]: {self}"

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
            row = db.query_one("SELECT id, name, token, bot_user_id, bot_username, bot_type, created_at, updated_at FROM discord_bots WHERE id = ?", (bot_id,))
            if row:
                b = dict(row)
                b['token'] = (decrypt_secret(b.get('token')) or '').strip()
                return b
        except Exception:
            pass

    # Legacy fallback
    token = (decrypt_secret(s.get('discord_bot_token')) or '').strip()
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
    token = (
        decrypt_secret(
            s.get('discord_bot_token_effective') or s.get('discord_bot_token')
        )
        or ''
    ).strip()

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


def _discord_response_error(stage: str, response: requests.Response) -> DiscordSendError:
    status = int(response.status_code or 0)
    if status == 401:
        return DiscordSendError("invalid_token", "The Discord bot token is invalid", retryable=False, status_code=status)
    if status == 403:
        return DiscordSendError("dm_forbidden", "Discord refused the direct message", retryable=False, status_code=status)
    if status == 404:
        return DiscordSendError("recipient_not_found", "The Discord recipient or channel was not found", retryable=False, status_code=status)
    if status == 429:
        return DiscordSendError("rate_limited", "Discord rate limit retries were exhausted", retryable=True, status_code=status)
    if status >= 500:
        return DiscordSendError("service_unavailable", "Discord is temporarily unavailable", retryable=True, status_code=status)
    return DiscordSendError(
        "api_error",
        f"Discord rejected the {stage} request",
        retryable=False,
        status_code=status or None,
    )


def _discord_post(url: str, *, headers: dict, payload: dict) -> requests.Response:
    try:
        return requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        raise DiscordSendError(
            "network_error",
            "Unable to reach Discord",
            retryable=True,
        ) from exc


def split_discord_content(content: str, limit: int = DISCORD_SAFE_MESSAGE_LENGTH) -> list[str]:
    """Split content without data loss, preferring paragraph or line boundaries."""
    remaining = str(content or "")
    if not remaining:
        return []

    limit = max(1, int(limit or DISCORD_SAFE_MESSAGE_LENGTH))
    parts = []
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit + 1)
        if split_at < max(1, limit // 2):
            split_at = limit
        else:
            split_at += 1
        parts.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        parts.append(remaining)
    return parts


def send_discord_dm(bot_token: str, recipient_user_id: str, content: str, max_retries: int = 4) -> None:
    bot_token = (bot_token or "").strip()
    recipient_user_id = (recipient_user_id or "").strip()

    if not bot_token:
        raise DiscordSendError("missing_token", "Missing Discord bot token", retryable=False)
    if not recipient_user_id:
        raise DiscordSendError("missing_recipient", "Missing recipient Discord user ID", retryable=False)
    if not content:
        return

    headers = _auth_headers(bot_token)

    # 1) Create/open DM channel
    r = None
    for _ in range(max(1, max_retries)):
        r = _discord_post(
            f"{DISCORD_API}/users/@me/channels",
            headers=headers,
            payload={"recipient_id": recipient_user_id},
        )
        if r.status_code != 429:
            break
        _sleep_from_429(r)

    if r.status_code >= 300:
        raise _discord_response_error("DM channel creation", r)

    channel_id = (r.json() or {}).get("id")
    if not channel_id:
        raise DiscordSendError("invalid_response", "Discord returned no DM channel ID", retryable=True)

    # 2) Send every part without silently truncating long template output.
    parts = split_discord_content(content)
    for part_index, part in enumerate(parts, start=1):
        payload = {"content": part}
        for _ in range(max(1, max_retries)):
            s = _discord_post(
                f"{DISCORD_API}/channels/{channel_id}/messages",
                headers=headers,
                payload=payload,
            )
            if s.status_code == 429:
                _sleep_from_429(s)
                continue
            if s.status_code >= 300:
                raise _discord_response_error(f"message delivery (part {part_index}/{len(parts)})", s)
            break
        else:
            raise DiscordSendError(
                "rate_limited",
                f"Discord rate limit retries were exhausted on message part {part_index}/{len(parts)}",
                retryable=True,
                status_code=429,
            )
