from datetime import datetime
from collections import Counter

from flask import Response, render_template, request

from logging_utils import AnonymizeFilter, read_all_logs, read_log_page


ALLOWED_LOG_LEVELS = {"ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def normalize_log_level(value) -> str:
    level = str(value or "ALL").strip().upper()
    return level if level in ALLOWED_LOG_LEVELS else "ALL"


def summarize_log_levels(records=(), *, level_counts=None) -> dict[str, int]:
    if level_counts is None:
        level_counts = Counter(str(record.get("level") or "").upper() for record in records)
    counts = {level: level_counts.get(level, 0) for level in ALLOWED_LOG_LEVELS if level != "ALL"}
    counts["ALL"] = sum(counts.values())
    return counts


def register(app):
    @app.route("/logs")
    def logs_page():
        # Default to the complete stream. The previous INFO default was an
        # exact filter and therefore hid WARNING/ERROR/CRITICAL incidents.
        level = normalize_log_level(request.args.get("level"))
        search = request.args.get("q", "").strip()
        try:
            page = int(request.args.get("page", 1))
        except (TypeError, ValueError):
            page = 1
        per_page = 200

        snapshot = read_log_page(level, search, page, per_page)
        level_counts = summarize_log_levels(level_counts=snapshot["counts"])
        page = snapshot["page"]
        total_pages = snapshot["total_pages"]
        paginated = snapshot["records"]

        window_size = 10
        page_window_start = max(1, page - 4)
        page_window_end = min(total_pages, page_window_start + window_size - 1)
        if (page_window_end - page_window_start) < (window_size - 1):
            page_window_start = max(1, page_window_end - window_size + 1)

        return render_template(
            "logs/logs.html",
            logs=paginated,
            page=page,
            total_pages=total_pages,
            page_window_start=page_window_start,
            page_window_end=page_window_end,
            level=level,
            search=search,
            level_counts=level_counts,
            log_read_errors=snapshot["errors"],
            active_page="logs",
        )

    @app.route("/logs/download")
    def download_logs():
        output = []
        anonymizer = AnonymizeFilter(force=True)
        for line in read_all_logs():
            output.append(anonymizer.anonymize(line))

        if not output:
            output.append("No logs available.\n")

        filename = f"{datetime.now().strftime('%Y-%m-%d')}_vodum-logs-anonymized.log"
        return Response(
            "".join(output),
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
