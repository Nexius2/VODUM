from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app
from markupsafe import Markup, escape

from web.helpers import get_db
from core.i18n import get_translator


def inject_brand_name():
    try:
        db = get_db()
        row = db.query_one("SELECT brand_name FROM settings WHERE id = 1")
        brand_name = None
        if row:
            brand_name = row["brand_name"]
        brand_name = (brand_name or "").strip()
    except Exception:
        brand_name = ""

    return {"app_brand_name": brand_name if brand_name else "VODUM"}

def utc_iso(value):
    if value is None:
        return ""

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return ""

        if s.isdigit():
            ts = int(s)
            if ts > 1_000_000_000_000:
                ts = ts / 1000
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except Exception:
                try:
                    dt = datetime.fromisoformat(s.replace(" ", "T"))
                except Exception:
                    return s
    else:
        return str(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def browser_datetime(value, mode="datetime", fallback="-"):
    iso = utc_iso(value)
    if not iso:
        return fallback

    return Markup(
        f'<span data-vodum-datetime="{escape(iso)}" '
        f'data-vodum-datetime-mode="{escape(mode)}">{escape(str(value))}</span>'
    )

def safe_datetime(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value




def _format_minute_list(minutes: list[int]) -> str:
    formatted = [f":{minute:02d}" for minute in minutes]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} and {formatted[1]}"
    return f"{', '.join(formatted[:-1])} and {formatted[-1]}"


def _parse_minute_list(value: str) -> list[int] | None:
    try:
        minutes = [int(part) for part in value.split(",") if part.strip() != ""]
    except ValueError:
        return None

    if not minutes or any(minute < 0 or minute > 59 for minute in minutes):
        return None

    if sorted(minutes) != minutes or len(set(minutes)) != len(minutes):
        return None

    return minutes


def _regular_minute_step(minutes: list[int]) -> int | None:
    if len(minutes) < 2:
        return None

    gaps = [b - a for a, b in zip(minutes, minutes[1:])]
    gaps.append((minutes[0] + 60) - minutes[-1])
    if len(set(gaps)) != 1:
        return None
    return gaps[0]

def cron_human(expr, t=None):
    """
    Convertit une expression CRON en phrase lisible, multilingue via t().
    """
    if t is None:
        t = get_translator()
    if not expr:
        return ""

    parts = expr.split()
    if len(parts) != 5:
        return expr

    minute, hour, dom, month, dow = parts

    minute_list = _parse_minute_list(minute) if "," in minute else None
    if hour == "*" and dom == "*" and month == "*" and dow == "*" and minute_list:
        step = _regular_minute_step(minute_list)
        if step:
            return t("cron_every_x_minutes_at_minutes").format(
                x=step,
                minutes=_format_minute_list(minute_list),
            )
        return t("cron_every_hour_at_minutes").format(minutes=_format_minute_list(minute_list))

    if hour == "*" and dom == "*" and month == "*" and dow == "*" and minute.isdigit():
        return t("cron_every_hour_at_minute").format(m=f":{int(minute):02d}")

    if hour == "*" and dom == "*" and month == "*" and dow == "*" and minute.startswith("*/"):
        return t("cron_every_x_minutes").format(x=minute[2:])

    if minute == "0" and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return t("cron_every_hour_at").format(m="00")

    if dom == "*" and month == "*" and dow == "*" and hour.startswith("*/"):
        try:
            minute_value = int(minute)
        except Exception:
            minute_value = None
        if minute_value is not None and minute_value != 0:
            return t("cron_every_x_hours_at_minute").format(
                x=hour[2:],
                m=f":{minute_value:02d}",
            )
        if minute_value == 0:
            return t("cron_every_x_hours").format(x=hour[2:])


    if dom == "*" and month == "*" and dow == "*":
        try:
            return t("cron_every_day_at").format(
                h=f"{int(hour):02d}",
                m=f"{int(minute):02d}",
            )
        except Exception:
            return expr

    if dom.startswith("*/") and month == "*" and dow == "*":
        try:
            return t("cron_every_x_days_at").format(
                x=dom[2:],
                h=f"{int(hour):02d}",
                m=f"{int(minute):02d}",
            )
        except Exception:
            return expr

    if dow != "*" and dom == "*" and month == "*":
        weekdays = {
            "1": t("monday"),
            "2": t("tuesday"),
            "3": t("wednesday"),
            "4": t("thursday"),
            "5": t("friday"),
            "6": t("saturday"),
            "0": t("sunday"),
        }

        dayname = weekdays.get(dow, dow)

        try:
            return t("cron_every_weekday_at").format(
                day=dayname,
                h=f"{int(hour):02d}",
                m=f"{int(minute):02d}",
            )
        except Exception:
            return t("cron_every_weekday").format(day=dayname)

    return expr


def tz_filter(dt):
    """
    Convertit une date UTC vers le fuseau horaire configuré dans settings.
    Accepte :
    - datetime
    - string ISO "YYYY-MM-DD HH:MM:SS"
    - epoch seconds (int/float) ou string digits ("1772193763")
    - epoch milliseconds (13 digits)
    """
    if dt is None:
        return "-"

    # epoch int/float
    if isinstance(dt, (int, float)):
        try:
            ts = float(dt)
            if ts > 1e12:  # ms
                ts = ts / 1000.0
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return dt

    # string: iso or digits
    if isinstance(dt, str):
        s = dt.strip()
        if s.isdigit():
            try:
                ts = int(s)
                if ts > 1_000_000_000_000:  # ms
                    ts = ts // 1000
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                return dt
        else:
            try:
                dt = datetime.fromisoformat(s)
            except Exception:
                return dt

    if not isinstance(dt, datetime):
        return dt

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    db = get_db()
    row = db.query_one("SELECT timezone FROM settings WHERE id = 1")

    tzname = "UTC"
    if row:
        try:
            tzname = row["timezone"] or "UTC"
        except (KeyError, IndexError):
            tzname = "UTC"

    try:
        local_tz = ZoneInfo(tzname)
        return dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
