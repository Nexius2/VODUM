VALID_DELIVERY_CHANNELS = ("inherit", "email", "discord", "all")


def normalize_delivery_channels(value) -> str:
    normalized = str(value or "inherit").strip().lower()
    return normalized if normalized in VALID_DELIVERY_CHANNELS else "inherit"


def explicit_delivery_channels(value) -> list[str] | None:
    normalized = normalize_delivery_channels(value)
    if normalized == "inherit":
        return None
    if normalized == "all":
        return ["email", "discord"]
    return [normalized]
