"""Runtime data paths derived from the configured database location."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    database_path = Path(os.environ.get("DATABASE_PATH", "/appdata/database.db"))
    return database_path.expanduser().resolve().parent


def imports_dir() -> Path:
    override = (os.environ.get("VODUM_IMPORTS_DIR") or "").strip()
    return Path(override).expanduser().resolve() if override else data_dir() / "imports"


def update_status_path() -> Path:
    return data_dir() / "update_status.json"
