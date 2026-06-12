"""Provider-neutral disk cache for monitoring artwork."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path


ARTWORK_CACHE_DIR = Path(
    os.environ.get("VODUM_ARTWORK_CACHE_DIR", "/appdata/artwork_cache")
)
ARTWORK_CACHE_TTL_SECONDS = int(
    os.environ.get("VODUM_ARTWORK_CACHE_TTL_SECONDS", str(7 * 24 * 3600))
)


def detect_image_content_type(content: bytes) -> str | None:
    """Return a trusted image MIME type from the binary signature."""
    if not content:
        return None
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if len(content) >= 12 and content[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    return None


def _remove_cache_pair(img_path: Path, meta_path: Path) -> None:
    for path in (img_path, meta_path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def artwork_cache_key(*parts) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def artwork_cache_paths(cache_key: str) -> tuple[Path | None, Path | None]:
    safe_key = "".join(char for char in str(cache_key) if char.isalnum())
    if not safe_key:
        return None, None
    ARTWORK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return (
        ARTWORK_CACHE_DIR / f"{safe_key}.img",
        ARTWORK_CACHE_DIR / f"{safe_key}.json",
    )


def read_artwork_cache(cache_key: str, *, allow_stale: bool = False) -> dict | None:
    img_path, meta_path = artwork_cache_paths(cache_key)
    if not img_path or not meta_path or not img_path.exists() or not meta_path.exists():
        return None

    try:
        with img_path.open("rb") as handle:
            detected_content_type = detect_image_content_type(handle.read(32))
    except OSError:
        return None
    if not detected_content_type:
        _remove_cache_pair(img_path, meta_path)
        return None

    age = time.time() - img_path.stat().st_mtime
    is_stale = age > ARTWORK_CACHE_TTL_SECONDS
    if is_stale and not allow_stale:
        return None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}

    return {
        "path": img_path,
        "content_type": detected_content_type,
        "is_stale": is_stale,
        "max_age": 300 if is_stale else ARTWORK_CACHE_TTL_SECONDS,
    }


def is_artwork_cache_fresh(cache_key: str) -> bool:
    return read_artwork_cache(cache_key) is not None


def write_artwork_cache(cache_key: str, content: bytes, content_type: str) -> bool:
    detected_content_type = detect_image_content_type(content)
    if not detected_content_type:
        return False

    img_path, meta_path = artwork_cache_paths(cache_key)
    if not img_path or not meta_path:
        return False

    tmp_img_path = img_path.with_suffix(".img.tmp")
    tmp_meta_path = meta_path.with_suffix(".json.tmp")
    tmp_img_path.write_bytes(content)
    tmp_meta_path.write_text(
        json.dumps(
            {
                "content_type": detected_content_type,
                "saved_at": int(time.time()),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.replace(tmp_img_path, img_path)
    os.replace(tmp_meta_path, meta_path)
    return True
