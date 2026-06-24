"""Ensure every translation catalog has exactly the English reference keys."""

from __future__ import annotations

import json
import re
import string
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LANG_DIR = ROOT / "lang"


def _catalog(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise AssertionError(f"{path.name} must contain a JSON object")
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise AssertionError(f"{path.name}: {key!r} must map to a string")
        if not key.strip() or not value.strip():
            raise AssertionError(f"{path.name}: empty key/value for {key!r}")
    return data


def _placeholders(value: str) -> set[str]:
    names = set()
    try:
        for _, field_name, _, _ in string.Formatter().parse(value):
            if field_name:
                names.add(field_name.split(".", 1)[0].split("[", 1)[0])
    except ValueError as exc:
        raise AssertionError(f"Invalid format string {value!r}: {exc}") from exc
    names.update(re.findall(r"%\(([^)]+)\)[#0 +\-]?[0-9.]*[a-zA-Z]", value))
    return names


def main() -> int:
    reference_catalog = _catalog(LANG_DIR / "en.json")
    reference = set(reference_catalog)
    errors = []
    for path in sorted(LANG_DIR.glob("*.json")):
        catalog = _catalog(path)
        keys = set(catalog)
        missing = sorted(reference - keys)
        extra = sorted(keys - reference)
        if missing or extra:
            errors.append(
                f"{path.name}: missing={missing or 'none'}, extra={extra or 'none'}"
            )
        for key in sorted(reference & keys):
            expected = _placeholders(reference_catalog[key])
            actual = _placeholders(catalog[key])
            if actual != expected:
                errors.append(
                    f"{path.name}: placeholder mismatch for {key}: "
                    f"expected={sorted(expected)}, actual={sorted(actual)}"
                )

    used_keys = set()
    call_pattern = re.compile(r"\bt\(\s*['\"]([^'\"]+)['\"]\s*\)")
    for base, suffixes in ((ROOT / "templates", {".html"}), (ROOT / "app", {".py"})):
        for source in base.rglob("*"):
            if source.suffix in suffixes:
                used_keys.update(call_pattern.findall(source.read_text(encoding="utf-8")))
    unknown = sorted(used_keys - reference)
    if unknown:
        errors.append(f"translation calls reference unknown keys: {unknown}")
    if errors:
        raise AssertionError("\n".join(errors))
    print(
        f"OK - {len(list(LANG_DIR.glob('*.json')))} catalogs match "
        f"{len(reference)} keys, placeholders and {len(used_keys)} static calls."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
