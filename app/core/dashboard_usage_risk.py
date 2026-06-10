from __future__ import annotations

from datetime import date, datetime, timedelta


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _smooth_svg_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    if len(points) == 1:
        x, y = points[0]
        return f"M {x:.1f} {y:.1f}"

    path = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    for index in range(len(points) - 1):
        p0 = points[max(0, index - 1)]
        p1 = points[index]
        p2 = points[index + 1]
        p3 = points[min(len(points) - 1, index + 2)]
        c1x = p1[0] + (p2[0] - p0[0]) / 6
        c1y = p1[1] + (p2[1] - p0[1]) / 6
        c2x = p2[0] - (p3[0] - p1[0]) / 6
        c2y = p2[1] - (p3[1] - p1[1]) / 6
        path.append(
            f"C {c1x:.1f} {c1y:.1f}, {c2x:.1f} {c2y:.1f}, {p2[0]:.1f} {p2[1]:.1f}"
        )
    return " ".join(path)


def build_usage_risk_trend(
    history_rows,
    current_count: int,
    *,
    days: int = 14,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    days = max(2, int(days))
    start_day = today - timedelta(days=days - 1)
    daily_users = [set() for _ in range(days)]

    for row in history_rows or []:
        item = dict(row)
        user_id = item.get("vodum_user_id")
        first_day = _as_date(item.get("first_detected_at"))
        last_day = _as_date(item.get("last_detected_at")) or first_day
        if user_id is None or first_day is None or last_day is None:
            continue

        first_index = max(0, (first_day - start_day).days)
        last_index = min(days - 1, (last_day - start_day).days)
        for index in range(first_index, last_index + 1):
            if 0 <= index < days:
                daily_users[index].add(int(user_id))

    values = [len(users) for users in daily_users]
    values[-1] = max(0, int(current_count or 0))

    width = 240.0
    height = 88.0
    top = 8.0
    bottom = 78.0
    max_value = max(max(values), 1)
    x_step = width / (days - 1)
    points = [
        (
            index * x_step,
            bottom - ((value / max_value) * (bottom - top)),
        )
        for index, value in enumerate(values)
    ]
    line_path = _smooth_svg_path(points)
    area_path = (
        f"{line_path} L {points[-1][0]:.1f} {bottom:.1f} "
        f"L {points[0][0]:.1f} {bottom:.1f} Z"
    )

    comparison_index = max(0, days - 8)
    previous_value = values[comparison_index]
    delta = values[-1] - previous_value

    return {
        "values": values,
        "line_path": line_path,
        "area_path": area_path,
        "max_value": max(values) if values else 0,
        "delta_7d": delta,
        "start_label": start_day.strftime("%d/%m"),
        "end_label": today.strftime("%d/%m"),
    }
