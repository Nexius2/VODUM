"""Shared pagination contracts for route modules."""

from __future__ import annotations


PAGE_SIZES = (20, 50, 100)


def normalize_page(value, default: int = 1) -> int:
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return max(int(default), 1)


def normalize_page_size(value, default: int = 20, allowed=PAGE_SIZES) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return parsed if parsed in tuple(allowed) else int(default)


def page_bounds(page, per_page, total_rows) -> dict:
    per_page = max(int(per_page), 1)
    total_rows = max(int(total_rows or 0), 0)
    total_pages = max(1, (total_rows + per_page - 1) // per_page)
    page = min(normalize_page(page), total_pages)
    return {
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total_rows": total_rows,
        "offset": (page - 1) * per_page,
    }


def pagination_links(page, per_page, total_rows, url_builder, *, unit_label=None) -> dict:
    result = page_bounds(page, per_page, total_rows)
    current = result["page"]
    last = result["total_pages"]
    result.update({
        "first_url": url_builder(1),
        "prev_url": url_builder(max(1, current - 1)),
        "next_url": url_builder(min(last, current + 1)),
        "last_url": url_builder(last),
        "unit_label": unit_label,
    })
    return result
