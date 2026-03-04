from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app

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


def safe_datetime(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def cron_human(expr):
    """
    Convertit une expression CRON en phrase lisible, multilingue via t().
    """
    t = get_translator()
    if not expr:
        return ""

    parts = expr.split()
    if len(parts) != 5:
        return expr

    minute, hour, dom, month, dow = parts

    if hour == "*" and dom == "*" and month == "*" and dow == "*" and minute.startswith("*/"):
        return t("cron_every_x_minutes").format(x=minute[2:])

    if minute == "0" and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return t("cron_every_hour_at").format(m="00")

    if minute == "0" and dom == "*" and month == "*" and dow == "*" and hour.startswith("*/"):
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
