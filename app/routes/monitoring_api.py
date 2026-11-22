# Auto-split from app.py (keep URLs/endpoints intact)
import json

import requests
from flask import request, Response, current_app, jsonify, abort, send_file

from core.monitoring.artwork_cache import (
    ARTWORK_CACHE_TTL_SECONDS,
)
from core.auth_principal import admin_required
from core.monitoring.artwork_proxy import ArtworkProxyError, fetch_monitoring_artwork, fetch_monitoring_avatar
from core.monitoring.ip_location import format_ip_location, is_public_ip, parse_stream_ip
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



def _prepared_chart_response(metric, user_id=None):
    from core.monitoring.precomputed_tabs import load_tab_snapshot
    kind = 'user_daily' if user_id is not None else 'activity'
    options = {'range': request.args.get('range', '30d' if user_id is not None else '7d')}
    if user_id is not None:
        options['user_id'] = user_id
    payload, status = load_tab_snapshot(get_db(), kind, options)
    response = jsonify((payload or {}).get(metric, []))
    response.status_code = 200 if status['ready'] else (429 if status['queue_full'] else 202)
    if not status['ready']:
        response.headers['Retry-After'] = '5'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-VODUM-Statistics-Stale'] = '1' if status['stale'] else '0'
    response.headers['X-VODUM-Statistics-Failed'] = '1' if status['failed'] else '0'
    response.headers['X-VODUM-Statistics-Ready'] = '1' if status['ready'] else '0'
    if status['computed_at']:
        response.headers['X-VODUM-Statistics-Computed-At'] = status['computed_at']
    return response


def register(app):
    @app.route("/api/monitoring/avatar/<int:account_id>")
    @admin_required
    def api_monitoring_avatar(account_id):
        row = get_db().query_one(
            """
            SELECT s.id, LOWER(TRIM(s.type)) AS type, s.url, s.local_url, s.public_url,
                   s.token, s.settings_json, mu.avatar, mu.external_user_id
            FROM media_users mu JOIN servers s ON s.id = mu.server_id
            WHERE mu.id = ?
            """,
            (account_id,),
        )
        if not row or not row["avatar"]:
            abort(404)
        result = fetch_monitoring_avatar(dict(row), row["avatar"], row["external_user_id"])
        if not result:
            abort(404)
        if result["kind"] == "file":
            response = send_file(result["path"], mimetype=result["content_type"], conditional=True)
        else:
            response = Response(result["content"], mimetype=result["content_type"])
        response.headers["Cache-Control"] = "private, no-store"
        return response

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
        return _prepared_chart_response("activity")





    @app.route("/api/monitoring/media_types")
    def api_monitoring_media_types():
        return _prepared_chart_response("media_types")


    @app.route("/api/monitoring/per_server")
    def api_monitoring_per_server():
        return _prepared_chart_response("per_server")




    @app.route("/api/monitoring/weekday")
    def api_monitoring_weekday():
        return _prepared_chart_response("weekday")

    @app.route("/api/monitoring/ip_lookup")
    def api_monitoring_ip_lookup():
        raw_ip = (request.args.get("ip") or "").strip()
        if not raw_ip:
            return jsonify({"ok": False, "error": "missing_ip"}), 400

        ip_obj = parse_stream_ip(raw_ip)
        if ip_obj is None:
            return jsonify({"ok": False, "error": "invalid_ip"}), 400

        if not is_public_ip(ip_obj):
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

        lookup_url = f"http://ip-api.com/json/{ip_obj}"
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
            "display_name": format_ip_location(data) or raw_ip,
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
        return _prepared_chart_response("user_daily", user_id=user_id)
