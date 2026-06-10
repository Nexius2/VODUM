import json

from flask import url_for

ARTWORK_CACHE_RESOLVER = "canonical_v13"




def _safe_int(v):
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _load_json(raw):
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_ref_json(raw):
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _dump_ref_json(ref):
    if not isinstance(ref, dict) or not ref:
        return None
    return json.dumps(ref, ensure_ascii=False)


def _is_series_media_type(media_type: str) -> bool:
    mt = (media_type or "").strip().lower()
    return mt in ("serie", "series", "show", "episode", "season", "tv", "tv_episode")


def _artwork_scope(row) -> str:
    return "series" if _is_series_media_type((row or {}).get("media_type")) else "movie"

def _normalize_media_id(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _get_plex_target_media_id(row):
    row = dict(row or {})
    raw = _load_json(row.get("raw_json"))
    attrs = raw.get("VideoOrTrack") or {}
    scope = _artwork_scope(row)

    if scope == "series":
        return _normalize_media_id(
            attrs.get("grandparentRatingKey")
            or row.get("grandparent_rating_key")
            or row.get("media_key")
        )


    row_media_key = _normalize_media_id(row.get("media_key"))
    raw_rating_key = _normalize_media_id(attrs.get("ratingKey"))

    if row_media_key:
        return row_media_key

    return raw_rating_key

def _plex_raw_matches_row_target(row) -> bool:
    row = dict(row or {})
    raw = _load_json(row.get("raw_json"))
    attrs = raw.get("VideoOrTrack") or {}
    scope = _artwork_scope(row)

    if scope == "series":
        # Pour les séries, media_key peut être l'épisode alors que le poster cible
        # est la série. On accepte donc le raw_json.
        return True

    row_media_key = _normalize_media_id(row.get("media_key"))
    raw_rating_key = _normalize_media_id(attrs.get("ratingKey"))

    if row_media_key and raw_rating_key and row_media_key != raw_rating_key:
        return False

    return True

def _build_plex_image_url(server_id: int, path: str):
    if not server_id or not path:
        return None
    return url_for(
        "api_monitoring_poster",
        server_id=int(server_id),
        path=str(path),
    )


def _build_jellyfin_image_url(server_id: int, item_id: str, image_type: str = "Primary"):
    if not server_id or not item_id:
        return None
    return url_for(
        "api_monitoring_poster",
        server_id=int(server_id),
        item_id=str(item_id),
        image_type=str(image_type),
    )


def _build_url_from_ref(server_id: int, ref: dict):
    if not server_id or not isinstance(ref, dict):
        return None

    provider = (ref.get("provider") or "").strip().lower()

    if provider == "plex":
        path = (ref.get("path") or "").strip()
        return _build_plex_image_url(server_id, path) if path else None

    if provider == "jellyfin":
        item_id = ref.get("item_id")
        image_type = ref.get("image_type") or "Primary"
        return _build_jellyfin_image_url(server_id, str(item_id), str(image_type)) if item_id else None

    return None


def _make_ref(provider: str, scope: str, **kwargs):
    ref = {
        "provider": provider,
        "scope": scope,
        "resolver": ARTWORK_CACHE_RESOLVER,
    }
    ref.update(kwargs)
    return ref


def _is_valid_ref(ref: dict) -> bool:
    if not isinstance(ref, dict):
        return False

    provider = (ref.get("provider") or "").strip().lower()
    if provider == "plex":
        return bool((ref.get("path") or "").strip())
    if provider == "jellyfin":
        return bool(ref.get("item_id"))
    return False


def _is_fresh_cached_ref(ref: dict, row, image_kind: str) -> bool:
    if not _is_valid_ref(ref):
        return False

    row = dict(row or {})
    provider = (row.get("provider") or "").strip().lower()
    scope = _artwork_scope(row)
    image_kind = (image_kind or "").strip().lower()

    if image_kind not in ("poster", "backdrop"):
        return False

    ref_resolver = (ref.get("resolver") or "")
    ref_provider = (ref.get("provider") or "").strip().lower()
    ref_scope = (ref.get("scope") or "")
    ref_image_kind = (ref.get("image_kind") or "").strip().lower()

    if not (
        ref_resolver == ARTWORK_CACHE_RESOLVER
        and ref_provider == provider
        and ref_scope == scope
        and ref_image_kind == image_kind
    ):
        return False

    if provider == "plex":
        raw = _load_json(row.get("raw_json"))
        attrs = raw.get("VideoOrTrack") or {}

        target_id = _get_plex_target_media_id(row)
        ref_target_id = _normalize_media_id(ref.get("target_id"))
        ref_path = (ref.get("path") or "").strip()

        if not target_id or not ref_target_id or not ref_path:
            return False

        if ref_target_id != target_id:
            return False

        raw_matches = _plex_raw_matches_row_target(row)

        if scope == "series":
            expected_path = (
                attrs.get("grandparentArt")
                if image_kind == "backdrop"
                else attrs.get("grandparentThumb")
            )
            if not expected_path:
                expected_path = attrs.get("art") if image_kind == "backdrop" else attrs.get("thumb")
        else:
            expected_path = None
            if raw_matches:
                expected_path = attrs.get("art") if image_kind == "backdrop" else attrs.get("thumb")

        if not expected_path:
            expected_path = (
                f"/library/metadata/{target_id}/art"
                if image_kind == "backdrop"
                else f"/library/metadata/{target_id}/thumb"
            )

        return ref_path == str(expected_path).strip()

    if provider == "jellyfin":
        return True

    return False


def _extract_plex_canonical_refs_from_raw(row):
    row = dict(row or {})
    raw = _load_json(row.get("raw_json"))
    attrs = raw.get("VideoOrTrack") or {}
    scope = _artwork_scope(row)
    target_id = _get_plex_target_media_id(row)

    if not target_id:
        return (None, None)

    poster_path = None
    backdrop_path = None
    raw_matches = _plex_raw_matches_row_target(row)

    if scope == "series":
        poster_path = attrs.get("grandparentThumb") or attrs.get("thumb")
        backdrop_path = attrs.get("grandparentArt") or attrs.get("art")
    else:
        if raw_matches:
            poster_path = attrs.get("thumb")
            backdrop_path = attrs.get("art")

    if not poster_path:
        poster_path = f"/library/metadata/{target_id}/thumb"

    if not backdrop_path:
        backdrop_path = f"/library/metadata/{target_id}/art"

    poster_ref = _make_ref(
        "plex",
        scope,
        path=str(poster_path),
        target_id=str(target_id),
        image_kind="poster",
    )

    backdrop_ref = _make_ref(
        "plex",
        scope,
        path=str(backdrop_path),
        target_id=str(target_id),
        image_kind="backdrop",
    )

    return poster_ref, backdrop_ref


def _extract_jellyfin_canonical_refs(row):
    raw = _load_json((row or {}).get("raw_json"))
    now = raw.get("NowPlayingItem") or {}
    scope = _artwork_scope(row)

    if scope == "series":
        item_id = (
            now.get("SeriesId")
            or raw.get("SeriesId")
            or (row or {}).get("series_id")
        )
    else:
        item_id = (
            now.get("Id")
            or raw.get("Id")
            or (row or {}).get("media_key")
        )

    poster_ref = None
    backdrop_ref = None

    if item_id:
        poster_ref = _make_ref(
            "jellyfin",
            scope,
            item_id=str(item_id),
            image_type="Primary",
            image_kind="poster",
        )
        backdrop_ref = _make_ref(
            "jellyfin",
            scope,
            item_id=str(item_id),
            image_type="Backdrop",
            image_kind="backdrop",
        )

    return poster_ref, backdrop_ref


def extract_artwork_refs(row):
    row = dict(row or {})
    provider = (row.get("provider") or "").strip().lower()

    poster_ref = None
    backdrop_ref = None

    if provider == "plex":
        poster_ref, backdrop_ref = _extract_plex_canonical_refs_from_raw(row)
    elif provider == "jellyfin":
        poster_ref, backdrop_ref = _extract_jellyfin_canonical_refs(row)

    return {
        "poster_ref": poster_ref,
        "backdrop_ref": backdrop_ref,
        "poster_ref_json": _dump_ref_json(poster_ref),
        "backdrop_ref_json": _dump_ref_json(backdrop_ref),
    }


def _persist_artwork_cache(
    db,
    table_name: str,
    row_id,
    poster_ref_json,
    backdrop_ref_json,
    current_poster_json,
    current_backdrop_json,
):
    if not db or not row_id:
        return

    if (
        poster_ref_json == current_poster_json
        and backdrop_ref_json == current_backdrop_json
    ):
        return

    db.execute(
        f"""
        UPDATE {table_name}
        SET poster_ref_json = ?,
            backdrop_ref_json = ?
        WHERE id = ?
        """,
        (poster_ref_json, backdrop_ref_json, row_id),
    )











def _make_plex_ref_from_rating_key(scope, rating_key, image_kind, attrs=None):
    target_id = _normalize_media_id(rating_key)
    if not target_id:
        return None

    image_kind = (image_kind or "poster").strip().lower()
    attrs = attrs or {}

    path = None

    if scope == "series":
        if image_kind == "backdrop":
            path = attrs.get("grandparentArt") or attrs.get("art")
        else:
            path = attrs.get("grandparentThumb") or attrs.get("thumb")
    else:
        if image_kind == "backdrop":
            path = attrs.get("art")
        else:
            path = attrs.get("thumb")

    if not path:
        if image_kind == "backdrop":
            path = f"/library/metadata/{target_id}/art"
        else:
            path = f"/library/metadata/{target_id}/thumb"

    return _make_ref(
        "plex",
        scope,
        path=str(path),
        target_id=str(target_id),
        image_kind=image_kind,
    )


def _resolve_plex_refs_via_metadata(db, row):
    row = dict(row or {})
    raw = _load_json(row.get("raw_json"))
    attrs = raw.get("VideoOrTrack") or {}
    scope = _artwork_scope(row)
    target_id = _get_plex_target_media_id(row)

    if not target_id:
        return (None, None)

    safe_attrs = attrs

    if scope != "series" and not _plex_raw_matches_row_target(row):
        # Film uniquement:
        # si raw_json.ratingKey ne correspond pas à row.media_key,
        # on ne doit surtout pas réutiliser attrs.thumb / attrs.art.
        #
        # Sinon on crée un objet incohérent:
        # - target_id du bon film
        # - path du mauvais film
        safe_attrs = {}

    return (
        _make_plex_ref_from_rating_key(scope, target_id, "poster", safe_attrs),
        _make_plex_ref_from_rating_key(scope, target_id, "backdrop", safe_attrs),
    )


def _resolve_row_artwork(row, db=None, table_name=None):
    if row is None:
        return None, None

    if row.get("_resolved_poster_ref") is not None or row.get("_resolved_backdrop_ref") is not None:
        return row.get("_resolved_poster_ref"), row.get("_resolved_backdrop_ref")

    row = dict(row)
    server_id = _safe_int(row.get("server_id"))
    scope = _artwork_scope(row)
    provider = (row.get("provider") or "").strip().lower()

    current_poster_json = row.get("poster_ref_json")
    current_backdrop_json = row.get("backdrop_ref_json")

    cached_poster_ref = _load_ref_json(current_poster_json)
    cached_backdrop_ref = _load_ref_json(current_backdrop_json)

    if (
        _is_fresh_cached_ref(cached_poster_ref, row, "poster")
        and _is_fresh_cached_ref(cached_backdrop_ref, row, "backdrop")
    ):
        row["_resolved_poster_ref"] = cached_poster_ref
        row["_resolved_backdrop_ref"] = cached_backdrop_ref
        return cached_poster_ref, cached_backdrop_ref

    poster_ref = None
    backdrop_ref = None

    if provider == "plex" and db and server_id:
        poster_ref, backdrop_ref = _resolve_plex_refs_via_metadata(db, row)

    elif provider == "jellyfin":
        poster_ref, backdrop_ref = _extract_jellyfin_canonical_refs(row)

    # fallback ultime si Plex metadata indisponible
    if not poster_ref and not backdrop_ref:
        fallback = extract_artwork_refs(row)
        poster_ref = fallback.get("poster_ref")
        backdrop_ref = fallback.get("backdrop_ref")

    row["_resolved_poster_ref"] = poster_ref
    row["_resolved_backdrop_ref"] = backdrop_ref

    if db and table_name:
        row_id = _safe_int(row.get("hist_id") or row.get("id"))
        _persist_artwork_cache(
            db,
            table_name,
            row_id,
            _dump_ref_json(poster_ref),
            _dump_ref_json(backdrop_ref),
            current_poster_json,
            current_backdrop_json,
        )

    return poster_ref, backdrop_ref


def build_history_poster_url(row, db=None):
    row = dict(row or {})

    server_id = _safe_int(row.get("server_id"))
    if not server_id:
        return None

    poster_ref, backdrop_ref = _resolve_row_artwork(
        row,
        db=db,
        table_name="media_session_history",
    )

    return _build_url_from_ref(server_id, poster_ref)


def build_history_backdrop_url(row, db=None):
    row = dict(row or {})

    server_id = _safe_int(row.get("server_id"))
    if not server_id:
        return None

    poster_ref, backdrop_ref = _resolve_row_artwork(
        row,
        db=db,
        table_name="media_session_history",
    )

    return _build_url_from_ref(server_id, backdrop_ref)


def enrich_live_session_artwork(session_row, db=None):
    s = dict(session_row or {})

    s["season_number"] = None
    s["episode_number"] = None
    s["episode_code"] = None
    s["poster_url"] = None
    s["backdrop_url"] = None

    server_id = _safe_int(s.get("server_id"))
    if not server_id:
        return s

    provider = (s.get("provider") or "").strip().lower()
    raw = _load_json(s.get("raw_json"))

    if provider == "plex":
        attrs = raw.get("VideoOrTrack") or {}

        season = _safe_int(attrs.get("parentIndex"))
        episode = _safe_int(attrs.get("index"))

        s["season_number"] = season
        s["episode_number"] = episode

        if season is not None and episode is not None:
            s["episode_code"] = f"S{season:02d}E{episode:02d}"
        elif season is not None:
            s["episode_code"] = f"S{season}"

    elif provider == "jellyfin":
        now = raw.get("NowPlayingItem") or {}

        season = _safe_int(now.get("ParentIndexNumber"))
        episode = _safe_int(now.get("IndexNumber"))

        s["season_number"] = season
        s["episode_number"] = episode

        if season is not None and episode is not None:
            s["episode_code"] = f"S{season:02d}E{episode:02d}"
        elif season is not None:
            s["episode_code"] = f"S{season}"

    poster_ref, backdrop_ref = _resolve_row_artwork(
        s,
        db=db,
        table_name="media_sessions",
    )

    s["poster_url"] = _build_url_from_ref(server_id, poster_ref)
    s["backdrop_url"] = _build_url_from_ref(server_id, backdrop_ref)

    return s
