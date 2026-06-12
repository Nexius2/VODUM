"""Ensure every translation catalog has exactly the English reference keys."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LANG_DIR = ROOT / "lang"


def _keys(path: Path) -> set[str]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise AssertionError(f"{path.name} must contain a JSON object")
    return set(data)


def main() -> int:
    reference = _keys(LANG_DIR / "en.json")
    errors = []
    for path in sorted(LANG_DIR.glob("*.json")):
        keys = _keys(path)
        missing = sorted(reference - keys)
        extra = sorted(keys - reference)
        if missing or extra:
            errors.append(
                f"{path.name}: missing={missing or 'none'}, extra={extra or 'none'}"
            )
    if errors:
        raise AssertionError("\n".join(errors))
    print(f"OK - all translation catalogs match the {len(reference)} English keys.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
