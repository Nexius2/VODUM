"""Report likely user-visible template text that bypasses the translator."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
PATTERN = re.compile(r">([^<>{}\n]*[A-Za-z][^<>{}\n]*)<")
TECHNICAL = {
    "VODUM", "Plex", "Jellyfin", "CPU", "RAM", "IP", "IPs", "ASN",
    "Lax", "Strict", "None", "UP", "DOWN", "UNKNOWN", "OK",
    "allowSync", "allowCameraUpload", "allowChannels", "filterMovies",
    "filterTelevision", "filterMusic", "local_ip=yes", "stream_enforcer",
    "plex", "jellyfin", "master", "target", "computed", "rows",
    "GitHub", "tautulli.db", "smtp.gmail.com", "smtp.office365.com",
    "smtp.mail.yahoo.com",
}
ICON_NAMES = {
    "dashboard", "tv", "group", "dns", "redeem", "forum", "move_up",
    "save", "settings", "list", "schedule", "help_outline", "info", "logout",
}


def candidates() -> list[tuple[str, int, str]]:
    found = []
    for path in sorted((ROOT / "templates").rglob("*.html")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in PATTERN.finditer(line):
                value = match.group(1).strip()
                if not value or value in TECHNICAL or value in ICON_NAMES:
                    continue
                if "&&" in value or "${" in value or value in {"ies", "-&gt;"}:
                    continue
                found.append((str(path.relative_to(ROOT)), line_number, value))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when candidates remain")
    parser.add_argument("--details", action="store_true", help="Print every candidate with its line number")
    parser.add_argument("--path", help="Only report candidates whose relative path contains this value")
    args = parser.parse_args()
    found = candidates()
    if args.path:
        found = [item for item in found if args.path.lower() in item[0].lower()]
    counts = Counter(path for path, _, _ in found)
    print(f"hardcoded_i18n_candidates={len(found)} files={len(counts)}")
    for path, count in counts.most_common():
        print(f"{count:4d}  {path}")
    if args.details:
        for path, line, value in found:
            print(f"{path}:{line}: {value}")
    if args.strict and found:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
