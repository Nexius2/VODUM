from core.providers.registry import get_provider


def kill_session(server_row: dict, session_key: str, reason: str) -> bool:
    return get_provider(server_row).terminate_session(session_key, reason=reason)


def warn_session(server_row: dict, session_key: str, title: str, text: str, timeout_ms: int = 8000):
    provider = get_provider(server_row)
    try:
        return provider.send_session_message(session_key, title, text, timeout_ms=timeout_ms)
    except TypeError:
        return provider.send_session_message(session_key, title, text)
