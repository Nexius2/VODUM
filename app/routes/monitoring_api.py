# Auto-split from app.py (keep URLs/endpoints intact)
import json
import ipaddress

import requests
from flask import request, Response, current_app, jsonify, abort, send_file

from core.monitoring.artwork_cache import (
    ARTWORK_CACHE_TTL_SECONDS,
)
from core.monitoring.artwork_proxy import ArtworkProxyError, fetch_monitoring_artwork
from web.helpers import get_db
from logging_utils import get_logger


logger = get_logger("monitoring_api")

def json_rows(rows):
    return current_app.response_class(
        json.dumps([dict(r) for r in rows], ensure_ascii=False),
        mimetype='application/json',
    )


def _is_safe_relative_media_path(path: str) -> bool:
    if not path:
        return False

    path = str(path).strip()

    if not path.startswith("/"):
        return False

    # on refuse toute URL absolue / schéma externe
    if "://" in path or path.startswith("//"):
        return False

    # on refuse les chemins douteux
    if ".." in path or "\\" in path:
        return False

    return True


def register(app):
    # -----------------------------------------------------------------
    # Route explicitement autorisée à proxyfier un média distant
    # pour le monitoring (poster / art uniquement).
    # Toute autre route monitoring doit lire la DB uniquement.
    # -----------------------------------------------------------------
    @app.route("/api/monitoring/poster/<int:server_id>")
    def api_monitoring_poster(server_id: int):
        db = get_db()
        srv = db.query_one(
            """
            SELECT id, LOWER(TRIM(type)) AS type, url, local_url, public_url, token, settings_json
            FROM servers
            WHERE id = ?
              AND LOWER(TRIM(type)) IN ('plex','jellyfin')
            LIMIT 1
            """,
            (server_id,),
        )
        if not srv:
            abort(404)

        try:
            result = fetch_monitoring_artwork(dict(srv), request.args)
        except ArtworkProxyError as exc:
            abort(exc.status_code)

        if result["kind"] == "content":
            return Response(
                result["content"],
                mimetype=result["content_type"],
                headers={
                    "Cache-Control": f"public, max-age={ARTWORK_CACHE_TTL_SECONDS}",
                    "X-VODUM-Artwork-Cache": "MISS",
                },
            )

        response = send_file(
            result["path"],
            mimetype=result["content_type"],
            conditional=True,
            max_age=result["max_age"],
        )
        response.headers["Cache-Control"] = f"public, max-age={result['max_age']}"
        response.headers["X-VODUM-Artwork-Cache"] = "STALE" if result["is_stale"] else "HIT"
        return response

    # =====================================================================
    # ⚠️ END MONITORING ROUTES
    # =====================================================================


    @app.route("/api/monitoring/activity")
    def api_monitoring_activity():
        db = get_db()
        rng = request.args.get("range", "7d")

        if rng == "all":
            where = "1=1"
            params = ()
        else:
            delta = {"7d": "-7 days", "1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(rng, "-7 days")
            where = "stopped_at >= datetime('now', ?)"
            params = (delta,)

        rows = db.query(
            f"""
            WITH base AS (
              SELECT
                stopped_at,
                (CAST(server_id AS TEXT) || '|' ||
                 CAST(media_user_id AS TEXT) || '|' ||
                 COALESCE(NULLIF(TRIM(media_key), ''), 'no_media') || '|' ||
                 strftime('%Y-%m-%d %H:%M', started_at)
                ) AS play_key
              FROM media_session_history
              WHERE {where}
            ),
            plays AS (
              SELECT
                play_key,
                MAX(stopped_at) AS stopped_at
              FROM base
              GROUP BY play_key
            )
            SELECT
              strftime('%Y-%m-%d', stopped_at) AS day,
              COUNT(*) AS sessions
            FROM plays
            GROUP BY strftime('%Y-%m-%d', stopped_at)
            ORDER BY day ASC
            """,
            params,
        )
        return json_rows(rows)





    @app.route("/api/monitoring/media_types")
    def api_monitoring_media_types():
        db = get_db()
        rng = request.args.get("range", "7d")

        if rng == "all":
            where = "1=1"
            params = ()
        else:
            delta = {"7d": "-7 days", "1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(rng, "-7 days")
            where = "stopped_at >= datetime('now', ?)"
            params = (delta,)

        rows = db.query(
            f"""
            WITH base AS (
              SELECT
                (CAST(server_id AS TEXT) || '|' ||
                 CAST(media_user_id AS TEXT) || '|' ||
                 COALESCE(NULLIF(TRIM(media_key), ''), 'no_media') || '|' ||
                 strftime('%Y-%m-%d %H:%M', started_at)
                ) AS play_key,

                CASE
                  -- Règle prioritaire : si grandparent_title existe, c'est une série/épisode
                  WHEN TRIM(COALESCE(grandparent_title, '')) <> '' THEN 'series'

                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('serie', 'series', 'episode', 'show', 'season') THEN 'series'
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('movie', 'film', 'video') THEN 'movie'
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('music', 'audio', 'song', 'track', 'tracks') THEN 'music'
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('photo', 'photos', 'image', 'picture', 'pictures') THEN 'photo'
                  ELSE 'other'
                END AS media_type,

                CASE
                  -- On évite MAX(text) alphabétique ; on choisit un rang métier
                  WHEN TRIM(COALESCE(grandparent_title, '')) <> '' THEN 400
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('serie', 'series', 'episode', 'show', 'season') THEN 400
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('movie', 'film', 'video') THEN 300
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('music', 'audio', 'song', 'track', 'tracks') THEN 200
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('photo', 'photos', 'image', 'picture', 'pictures') THEN 100
                  ELSE 0
                END AS media_rank
              FROM media_session_history
              WHERE {where}
            ),
            plays AS (
              SELECT
                play_key,
                CASE MAX(media_rank)
                  WHEN 400 THEN 'series'
                  WHEN 300 THEN 'movie'
                  WHEN 200 THEN 'music'
                  WHEN 100 THEN 'photo'
                  ELSE 'other'
                END AS media_type
              FROM base
              GROUP BY play_key
            )
            SELECT media_type, COUNT(*) AS sessions
            FROM plays
            GROUP BY media_type
            ORDER BY sessions DESC
            """,
            params,
        )

        return json_rows(rows)


    @app.route("/api/monitoring/per_server")
    def api_monitoring_per_server():
        db = get_db()
        rng = request.args.get("range", "7d")

        if rng == "all":
            where = "1=1"
            params = ()
        else:
            delta = {"7d": "-7 days", "1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(rng, "-7 days")
            where = "h.stopped_at >= datetime('now', ?)"
            params = (delta,)

        rows = db.query(
            f"""
            WITH base AS (
              SELECT
                h.server_id,
                (CAST(h.server_id AS TEXT) || '|' ||
                 CAST(h.media_user_id AS TEXT) || '|' ||
                 COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                 strftime('%Y-%m-%d %H:%M', h.started_at)
                ) AS play_key
              FROM media_session_history h
              WHERE {where}
            ),
            plays AS (
              SELECT
                MAX(server_id) AS server_id,
                play_key
              FROM base
              GROUP BY play_key
            )
            SELECT
              COALESCE(NULLIF(s.name, ''), 'Server ' || p.server_id) AS server_name,
              COUNT(*) AS sessions
            FROM plays p
            LEFT JOIN servers s ON s.id = p.server_id
            GROUP BY p.server_id
            ORDER BY sessions DESC
            """,
            params,
        )
        return json_rows(rows)




    @app.route("/api/monitoring/weekday")
    def api_monitoring_weekday():
        db = get_db()
        rng = request.args.get("range", "1m")

        if rng == "all":
            where = "1=1"
            params = ()
        else:
            delta = {"1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(rng, "-1 month")
            where = "stopped_at >= datetime('now', ?)"
            params = (delta,)

        rows = db.query(
            f"""
            WITH base AS (
              SELECT
                stopped_at,
                (CAST(server_id AS TEXT) || '|' ||
                 CAST(media_user_id AS TEXT) || '|' ||
                 COALESCE(NULLIF(TRIM(media_key), ''), 'no_media') || '|' ||
                 strftime('%Y-%m-%d %H:%M', started_at)
                ) AS play_key
              FROM media_session_history
              WHERE {where}
            ),
            plays AS (
              SELECT
                play_key,
                MAX(stopped_at) AS stopped_at
              FROM base
              GROUP BY play_key
            )
            SELECT
              CAST(strftime('%w', stopped_at) AS INTEGER) AS weekday,
              COUNT(*) AS sessions
            FROM plays
            GROUP BY CAST(strftime('%w', stopped_at) AS INTEGER)
            ORDER BY weekday
            """,
            params,
        )
        return json_rows(rows)

    @app.route("/api/monitoring/ip_lookup")
    def api_monitoring_ip_lookup():
        raw_ip = (request.args.get("ip") or "").strip()
        if not raw_ip:
            return jsonify({"ok": False, "error": "missing_ip"}), 400

        try:
            ip_obj = ipaddress.ip_address(raw_ip)
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_ip"}), 400

        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            return jsonify({
                "ok": True,
                "ip": raw_ip,
                "is_private": True,
                "display_name": "Private / local IP",
                "country": None,
                "region": None,
                "city": None,
                "zip": None,
                "lat": None,
                "lon": None,
                "timezone": None,
                "isp": None,
                "org": None,
                "asn": None,
                "asname": None,
                "mobile": False,
                "proxy": False,
                "hosting": False,
                "map_url": None,
            })

        fields = ",".join([
            "status",
            "message",
            "country",
            "regionName",
            "city",
            "zip",
            "lat",
            "lon",
            "timezone",
            "isp",
            "org",
            "as",
            "asname",
            "mobile",
            "proxy",
            "hosting",
            "query",
        ])

        lookup_url = f"http://ip-api.com/json/{raw_ip}"
        try:
            resp = requests.get(
                lookup_url,
                params={"fields": fields},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json() or {}
        except Exception:
            logger.exception("IP geolocation lookup failed")
            return jsonify({"ok": False, "error": "lookup_failed"}), 502

        if data.get("status") != "success":
            logger.warning(
                "IP geolocation provider rejected lookup | reason=%s",
                data.get("message") or "lookup_failed",
            )
            return jsonify({
                "ok": False,
                "error": data.get("message") or "lookup_failed",
            }), 502

        lat = data.get("lat")
        lon = data.get("lon")
        map_url = None
        if lat is not None and lon is not None:
            map_url = (
                "https://www.openstreetmap.org/export/embed.html"
                f"?bbox={float(lon)-0.08}%2C{float(lat)-0.04}%2C{float(lon)+0.08}%2C{float(lat)+0.04}"
                f"&layer=mapnik&marker={float(lat)}%2C{float(lon)}"
            )

        return jsonify({
            "ok": True,
            "ip": data.get("query") or raw_ip,
            "is_private": False,
            "display_name": ", ".join(
                [x for x in [data.get("city"), data.get("regionName"), data.get("country")] if x]
            ) or raw_ip,
            "country": data.get("country"),
            "region": data.get("regionName"),
            "city": data.get("city"),
            "zip": data.get("zip"),
            "lat": lat,
            "lon": lon,
            "timezone": data.get("timezone"),
            "isp": data.get("isp"),
            "org": data.get("org"),
            "asn": data.get("as"),
            "asname": data.get("asname"),
            "mobile": bool(data.get("mobile")),
            "proxy": bool(data.get("proxy")),
            "hosting": bool(data.get("hosting")),
            "map_url": map_url,
        })

    @app.route("/api/monitoring/user/<int:user_id>/daily")
    def api_monitoring_user_daily(user_id: int):
        db = get_db()
        rng = request.args.get("range", "30d")

        if rng == "all":
            where = "1=1"
            params = (user_id,)
        else:
            delta = {
                "7d": "-7 days",
                "30d": "-30 days",
                "90d": "-90 days",
                "12m": "-12 months",
            }.get(rng, "-30 days")
            where = "h.stopped_at >= datetime('now', ?)"
            params = (user_id, delta)

        rows = db.query(
            f"""
            WITH base AS (
              SELECT
                h.started_at,
                h.stopped_at,
                MIN(
                  COALESCE(h.watch_ms, 0),
                  CASE
                    WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                    ELSE COALESCE(h.watch_ms, 0)
                  END
                ) AS watch_ms_capped,
                (CAST(h.server_id AS TEXT) || '|' ||
                 CAST(h.media_user_id AS TEXT) || '|' ||
                 COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                 strftime('%Y-%m-%d %H:%M', h.started_at)
                ) AS play_key
              FROM media_session_history h
              WHERE h.media_user_id = ?
                AND {where}
            ),
            plays AS (
              SELECT
                play_key,
                MAX(stopped_at) AS stopped_at,
                MAX(watch_ms_capped) AS watch_ms
              FROM base
              GROUP BY play_key
            )
            SELECT
              strftime('%Y-%m-%d', stopped_at) AS day,
              COUNT(*) AS plays,
              COALESCE(SUM(watch_ms), 0) AS watch_ms
            FROM plays
            GROUP BY strftime('%Y-%m-%d', stopped_at)
            ORDER BY day ASC
            """,
            params,
        )
        return json_rows(rows)
