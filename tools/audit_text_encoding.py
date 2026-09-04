"""Reject high-confidence UTF-8 mojibake in user-visible project text."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOTS = ("app", "templates", "static", "translations", "vodum-docs")
TEXT_SUFFIXES = {".html", ".js", ".json", ".md", ".py"}
MOJIBAKE_MARKERS = (
    "Ã",
    "Â",
    "â€",
    "â‚",
    "â˜",
    "â",
    "â",
    "ðŸ",
    "�",
)


def main() -> int:
    failures: list[str] = []
    for root_name in SEARCH_ROOTS:
        root = ROOT / root_name
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if any(marker in line for marker in MOJIBAKE_MARKERS):
                    failures.append(
                        f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}"
                    )
    if failures:
        print("Potential UTF-8 mojibake detected:")
        print("\n".join(failures))
        return 1
    print("OK - no high-confidence UTF-8 mojibake found in project text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
