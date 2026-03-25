from __future__ import annotations

import importlib
import sys


ALIASES = {
    # modules de base d'abord
    "config": "app.config",
    "db_manager": "app.db_manager",
    "db_utils": "app.db_utils",
    "logging_utils": "app.logging_utils",
    "email_layout_utils": "app.email_layout_utils",
    "email_sender": "app.email_sender",
    "discord_utils": "app.discord_utils",
    "mailing_utils": "app.mailing_utils",
    "notifications_utils": "app.notifications_utils",
    "tasks_engine": "app.tasks_engine",

    # modules dépendants ensuite
    "communications_engine": "app.communications_engine",

    # packages à la fin
    "api": "app.api",
    "blueprints": "app.blueprints",
    "core": "app.core",
    "external": "app.external",
    "routes": "app.routes",
    "tasks": "app.tasks",
    "web": "app.web",
}


def install_module_aliases() -> None:
    for alias, target in ALIASES.items():
        if alias in sys.modules:
            continue

        module = importlib.import_module(target)
        sys.modules.setdefault(alias, module)