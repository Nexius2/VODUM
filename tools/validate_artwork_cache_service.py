"""Validate the artwork disk-cache service and its route/task boundary."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.monitoring import artwork_cache  # noqa: E402


PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        artwork_cache.ARTWORK_CACHE_DIR = Path(tmp)
        artwork_cache.ARTWORK_CACHE_TTL_SECONDS = 60
        key = artwork_cache.artwork_cache_key("plex", 1, "/library/metadata/1/thumb")

        assert artwork_cache.write_artwork_cache(key, PNG, "text/html")
        cached = artwork_cache.read_artwork_cache(key)
        assert cached and cached["content_type"] == "image/png"
        assert cached["path"].read_bytes() == PNG
        assert cached["is_stale"] is False
        assert artwork_cache.is_artwork_cache_fresh(key)

        old = time.time() - 120
        os.utime(cached["path"], (old, old))
        assert artwork_cache.read_artwork_cache(key) is None
        stale = artwork_cache.read_artwork_cache(key, allow_stale=True)
        assert stale and stale["is_stale"] is True and stale["max_age"] == 300

        invalid_key = artwork_cache.artwork_cache_key("plex", 1, "/invalid")
        assert artwork_cache.write_artwork_cache(invalid_key, b"<html>Unauthorized</html>", "image/jpeg") is False

        invalid_img, invalid_meta = artwork_cache.artwork_cache_paths(invalid_key)
        invalid_img.write_bytes(b"<html>Cached error</html>")
        invalid_meta.write_text('{"content_type":"image/jpeg"}', encoding="utf-8")
        assert artwork_cache.read_artwork_cache(invalid_key, allow_stale=True) is None
        assert not invalid_img.exists() and not invalid_meta.exists()

    warmup = (ROOT / "app" / "tasks" / "warmup_artwork_cache.py").read_text(encoding="utf-8")
    assert "routes.monitoring_api" not in warmup
    assert "core.monitoring.artwork_cache" in warmup
    print("OK - artwork cache is provider-neutral and tasks no longer import its route.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
