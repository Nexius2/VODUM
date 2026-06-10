from __future__ import annotations

import os
import re
from pathlib import Path


VERSION_PATTERN = re.compile(r"^v?\d+\.\d+\.\d+(?:[\s._-]+(?:b|build)\d+)?$", re.IGNORECASE)
INVALID_VERSIONS = {"", "unknown", "dev", "none", "null", "n/a"}


def is_valid_app_version(value: object) -> bool:
    version = str(value or "").strip()
    return version.lower() not in INVALID_VERSIONS and bool(VERSION_PATTERN.fullmatch(version))


def _candidate_info_paths() -> list[Path]:
    module_path = Path(__file__).resolve()
    return [
        Path("/app/INFO"),
        module_path.parents[1] / "INFO",
        module_path.parents[2] / "INFO",
        Path.cwd() / "INFO",
    ]


def load_app_version(fallback: str | None = None) -> str | None:
    environment_version = (os.getenv("VODUM_VERSION") or "").strip()
    if is_valid_app_version(environment_version):
        return environment_version

    seen: set[Path] = set()
    for info_path in _candidate_info_paths():
        try:
            resolved = info_path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            for line in resolved.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("VERSION="):
                    version = line.split("=", 1)[1].strip()
                    if is_valid_app_version(version):
                        return version
                    break
        except (OSError, RuntimeError):
            continue

    return fallback
