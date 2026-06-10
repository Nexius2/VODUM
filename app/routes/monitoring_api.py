# Auto-split from app.py (keep URLs/endpoints intact)
import json
import ipaddress
import os
import time
import hashlib

import requests
from core.http_security import server_http_session
from flask import request, Response, current_app, jsonify, abort, send_file

from logging_utils import get_logger
from core.plex_rate_limit import wait_for_plex_slot
from web.helpers import get_db

task_logger = get_logger("tasks_ui")

ARTWORK_DISK_CACHE_DIR = os.environ.get("VODUM_ARTWORK_CACHE_DIR", "/appdata/artwork_cache")
ARTWORK_DISK_CACHE_TTL_SECONDS = int(os.environ.get("VODUM_ARTWORK_CACHE_TTL_SECONDS", str(7 * 24 * 3600)))


def _artwork_cache_key(*parts) -> str:
    raw = "|".join(str(p or "") for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _artwork_cache_paths(cache_key: str):
    safe_key = "".join(c for c in str(cache_key) if c.isalnum())
    if not safe_key:
        return None, None

    os.makedirs(ARTWORK_DISK_CACHE_DIR, exist_ok=True)

    return (
        os.path.join(ARTWORK_DISK_CACHE_DIR, f"{safe_key}.img"),
        os.path.join(ARTWORK_DISK_CACHE_DIR, f"{safe_key}.json"),
    )


def _read_artwork_cache(cache_key: str, allow_stale: bool = False):
    img_path, meta_path = _artwork_cache_paths(cache_key)
    if not img_path or not meta_path:
        return None

    if not os.path.exists(img_path) or not os.path.exists(meta_path):
        return None

    age = time.time() - os.path.getmtime(img_path)
    is_stale = age > ARTWORK_DISK_CACHE_TTL_SECONDS

    if is_stale and not allow_stale:
        return None

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = {}

    mimetype = meta.get("content_type") or "image/jpeg"
    response_max_age = 300 if is_stale else ARTWORK_DISK_CACHE_TTL_SECONDS

    response = send_file(
        img_path,
        mimetype=mimetype,
        conditional=True,
        max_age=response_max_age,
    )

    response.headers["Cache-Control"] = f"public, max-age={response_max_age}"
    response.headers["X-VODUM-Artwork-Cache"] = "STALE" if is_stale else "HIT"

    return response


def _write_artwork_cache(cache_key: str, content: bytes, content_type: str):
    if not content:
        return

    img_path, meta_path = _artwork_cache_paths(cache_key)
    if not img_path or not meta_path:
        return

    tmp_img_path = img_path + ".tmp"
    tmp_meta_path = meta_path + ".tmp"

    with open(tmp_img_path, "wb") as f:
        f.write(content)

    with open(tmp_meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "content_type": content_type or "image/jpeg",
                "saved_at": int(time.time()),
            },
            f,
            ensure_ascii=False,
        )

    os.replace(tmp_img_path, img_path)
    os.replace(tmp_meta_path, meta_path)


def _cached_image_response(cache_key: str, content: bytes, content_type: str):
    try:
        _write_artwork_cache(cache_key, content, content_type)
    except Exception:
        task_logger.warning("Unable to write artwork disk cache", exc_info=True)

    return Response(
        content,
        mimetype=content_type or "image/jpeg",
        headers={
            "Cache-Control": f"public, max-age={ARTWORK_DISK_CACHE_TTL_SECONDS}",
            "X-VODUM-Artwork-Cache": "MISS",
        },
    )

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

        srv = dict(srv)
        stype = (srv.get("type") or "").lower()
        token = srv.get("token")
        if not token:
            abort(404)

        # url > local_url > public_url
        bases = []
        for u in (srv.get("url"), srv.get("local_url"), srv.get("public_url")):
            if u and str(u).strip():
                b = str(u).strip().rstrip("/")
                if b not in bases:
                    bases.append(b)

        if not bases:
            abort(502)

        http = server_http_session(srv)

        def _try_get(full_url, headers=None, params=None):
            r = http.get(full_url, headers=headers, params=params, timeout=10)
            r.raise_for_status()
            return r

        # ---------------- PLEX ----------------
        if stype == "plex":
            path = (request.args.get("path") or "").strip()
            if not _is_safe_relative_media_path(path):
                abort(400)

            cache_key = _artwork_cache_key("plex", server_id, path)
            cached = _read_artwork_cache(cache_key)
            if cached:
                return cached

            headers = {"X-Plex-Token": token}

            candidate_paths = []
            if path:
                candidate_paths.append(path)

            # Fallback utile :
            # si /art échoue, on tente le /thumb du même media
            if path.endswith("/art"):
                candidate_paths.append(path[:-4] + "/thumb")

            # on évite les doublons
            deduped_paths = []
            seen_paths = set()
            for p in candidate_paths:
                if p and p not in seen_paths:
                    deduped_paths.append(p)
                    seen_paths.add(p)

            last_err = None
            for candidate_path in deduped_paths:
                for base in bases:
                    try:
                        wait_for_plex_slot(base)
                        r = _try_get(base + candidate_path, headers=headers)
                        ct = r.headers.get("Content-Type") or "image/jpeg"
                        return _cached_image_response(cache_key, r.content, ct)
                    except Exception as e:
                        last_err = e
                        continue

            stale = _read_artwork_cache(cache_key, allow_stale=True)
            if stale:
                task_logger.warning(
                    f"Serving stale Plex artwork cache after provider failure: server_id={server_id} path={path}"
                )
                return stale

            abort(502)

        # --------------- JELLYFIN --------------
        if stype == "jellyfin":
            item_id = request.args.get("item_id")
            if not item_id:
                abort(400)

            image_type = (request.args.get("image_type") or "Primary").strip()
            image_index = request.args.get("image_index")

            w = request.args.get("w", "120")
            q = request.args.get("q", "90")

            cache_key = _artwork_cache_key("jellyfin", server_id, item_id, image_type, image_index, w, q)
            cached = _read_artwork_cache(cache_key)
            if cached:
                return cached

            path = f"/Items/{item_id}/Images/{image_type}"
            if image_index not in (None, ""):
                path += f"/{image_index}"

            params = {"maxWidth": w, "quality": q}
            headers = {"X-Emby-Token": token}

            last_err = None
            for base in bases:
                try:
                    r = _try_get(base + path, headers=headers, params=params)
                    ct = r.headers.get("Content-Type") or "image/jpeg"
                    return _cached_image_response(cache_key, r.content, ct)
                except Exception as e:
                    last_err = e
                    continue

            if image_type.lower() != "primary":
                path = f"/Items/{item_id}/Images/Primary"
                for base in bases:
                    try:
                        r = _try_get(base + path, headers=headers, params=params)
                        ct = r.headers.get("Content-Type") or "image/jpeg"
                        return _cached_image_response(cache_key, r.content, ct)
                    except Exception:
                        continue
            stale = _read_artwork_cache(cache_key, allow_stale=True)
            if stale:
                task_logger.warning(
                    f"Serving stale Jellyfin artwork cache after provider failure: server_id={server_id} item_id={item_id}"
                )
                return stale

            abort(502)
        abort(404)


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
            return jsonify({"ok": False, "error": "lookup_failed"}), 502

        if data.get("status") != "success":
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




