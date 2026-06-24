"""Validate that GitHub installation guidance matches the repository."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
readme = (ROOT / "README.md").read_text(encoding="utf-8")
compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

for obsolete in ("/app/data", ":/logs", ":/backups", "UID=", "GID="):
    assert obsolete not in readme, f"Obsolete README guidance remains: {obsolete}"

for required in (
    "nexius2/vodum:latest",
    "./appdata",
    "/appdata/logs",
    "/appdata/backups",
    "tools/smoke_application_runtime.py",
    "--summary-only",
):
    assert required in readme, f"README is missing current guidance: {required}"

for line in env_example.splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key = line.split("=", 1)[0]
    assert key in readme, f"README does not mention .env.example variable: {key}"

for host_path, container_path in re.findall(r"-\s+([^:\s]+):([^\s]+)", compose):
    if host_path.startswith("./"):
        assert host_path in readme
        assert container_path in readme

for relative in re.findall(r'(?:src|href)="([^"#:?]+)"', readme):
    assert (ROOT / relative).exists(), f"Broken local README asset: {relative}"

for command_path in (
    "requirements.txt",
    "tools/smoke_routes.py",
    "tools/smoke_application_runtime.py",
    "app/tasks/import_tautulli.py",
    "LICENSE",
):
    assert (ROOT / command_path).exists(), f"README references missing file: {command_path}"

print("OK - README paths, variables, assets and installation guidance validated.")
