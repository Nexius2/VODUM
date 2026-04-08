# Auto-split from app.py (keep URLs/endpoints intact)
import math
import re
from datetime import datetime

from flask import Response, render_template, request

from logging_utils import read_all_logs
from web.helpers import get_db

def register(app):
    @app.route("/logs")
    def logs_page():
        # Filtres
        level = request.args.get("level")
        if not level:
            # Pas de filtre demandé => on choisit le défaut selon debug_mode
            db = get_db()
            row = db.query_one("SELECT debug_mode FROM settings WHERE id = 1")
            debug_mode = int(row["debug_mode"]) if row and row["debug_mode"] is not None else 0
            level = "ALL" if debug_mode == 1 else "INFO"

        level = level.upper()

        search = request.args.get("q", "").strip()

        # Pagination
        page = int(request.args.get("page", 1))
        per_page = 200  # Nombre de lignes de log à afficher par page

        
        lines = []

        # ----------------------------
        # Lecture fichier de log
        # ----------------------------
        raw_lines = read_all_logs()
        # ----------------------------
        # Filtrage + parsing minimal
        # ----------------------------
        for line in raw_lines:
            line = line.strip()

            # Filtre niveau
            if level != "ALL" and f"| {level} |" not in line:
                continue

            # Filtre recherche
            if search and search.lower() not in line.lower():
                continue

            lines.append(line)

        total_logs = len(lines)
        lines.reverse()  # ✅ plus récents d'abord


        # Pagination
        total_pages = max(1, math.ceil(total_logs / per_page))
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        end = start + per_page
        paginated = lines[start:end]

        # ----------------------------
        # Parser chaque ligne
        # Format réel :
        # 2025-01-01 12:00:00 | INFO | module | Message...
        # ----------------------------
        parsed_logs = []

        for l in paginated:
            try:
                parts = l.split("|", 3)
                created_at = parts[0].strip()
                level_part = parts[1].strip()
                source_part = parts[2].strip()
                message_part = parts[3].strip()

                parsed_logs.append({
                    "created_at": created_at,
                    "level": level_part,
                    "source": source_part,
                    "message": message_part,
                })
            except Exception:
                parsed_logs.append({
                    "created_at": "",
                    "level": "INFO",
                    "source": "system",
                    "message": l,
                })

        # ----------------------------
        # Fenêtre de pagination
        # ----------------------------
        window_size = 10
        page_window_start = max(1, page - 4)
        page_window_end = min(total_pages, page_window_start + window_size - 1)

        if (page_window_end - page_window_start) < (window_size - 1):
            page_window_start = max(1, page_window_end - window_size + 1)

        # ----------------------------
        # Rendu HTML
        # ----------------------------
        return render_template(
            "logs/logs.html",
            logs=parsed_logs,
            page=page,
            total_pages=total_pages,
            page_window_start=page_window_start,
            page_window_end=page_window_end,
            level=level,
            search=search,
            active_page="logs",
        )







    @app.route("/logs/download")
    def download_logs():
        log_path = "/logs/app.log"

        # Même règles d’anonymisation que logging_utils
        EMAIL_REGEX = re.compile(
            r'([a-zA-Z0-9._%+-])([a-zA-Z0-9._%+-]*)(@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
        )
        TOKEN_REGEX = re.compile(
            r'(?i)\b(x-plex-token|token|authorization|bearer)\b\s*[:=]\s*[a-z0-9\-._]+'
        )

        def anonymize(line: str) -> str:
            line = EMAIL_REGEX.sub(
                lambda m: f"{m.group(1)}{'*' * len(m.group(2))}{m.group(3)}",
                line
            )
            line = TOKEN_REGEX.sub(
                lambda m: f"{m.group(1)}=***REDACTED***",
                line
            )
            return line

        output = []

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    output.append(anonymize(line))
        except FileNotFoundError:
            output.append("No logs available.\n")

        # 🆕 Nom de fichier avec date en préfixe
        today = datetime.now().strftime("%Y-%m-%d")
        filename = f"{today}_vodum-logs-anonymized.log"

        return Response(
            "".join(output),
            mimetype="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )







    # -----------------------------
    # ABOUT
    # -----------------------------




