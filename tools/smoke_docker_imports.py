#!/usr/bin/env python3
"""Verify imports using the same flat Python layout as the Docker image."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
sys.path.insert(0, str(APP_DIR))

# Import the production application module first: Waitress resolves ``run:app``
# from the same flat /app directory used here. The explicit route imports guard
# compatibility contracts that can otherwise be missed by isolated unit tests.
for module_name in (
    "routes.users_list",
    "routes.users_actions",
    "routes.users_detail",
    "app",
):
    importlib.import_module(module_name)

print("DOCKER IMPORT SMOKE OK")
