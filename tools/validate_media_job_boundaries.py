"""Ensure web routes queue media jobs through the central service."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_DIRS = (ROOT / "app" / "routes", ROOT / "app" / "blueprints", ROOT / "app" / "api")
DIRECT_INSERT = re.compile(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+media_jobs", re.IGNORECASE)


def main() -> int:
    violations = []
    for directory in WEB_DIRS:
        for path in directory.rglob("*.py"):
            if DIRECT_INSERT.search(path.read_text(encoding="utf-8")):
                violations.append(path.relative_to(ROOT).as_posix())
    if violations:
        raise AssertionError(f"Web modules insert media_jobs directly: {', '.join(violations)}")
    print("OK - web routes queue media jobs only through the central service.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
