"""Validate startup ordering and fatal/non-fatal failure behavior."""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))


class Logger:
    def info(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


logging_stub = types.ModuleType("logging_utils")
logging_stub.get_logger = lambda name: Logger()
sys.modules.setdefault("logging_utils", logging_stub)

from core.startup import StartupStep, run_startup_sequence  # noqa: E402


def main() -> int:
    calls = []

    def record(name):
        return lambda app: calls.append((name, app))

    app = object()
    run_startup_sequence(app, (
        StartupStep("first", record("first")),
        StartupStep("second", record("second")),
    ))
    assert calls == [("first", app), ("second", app)]

    calls.clear()

    def fail(current_app):
        calls.append(("failed", current_app))
        raise RuntimeError("expected")

    run_startup_sequence(app, (
        StartupStep("optional", fail, fatal=False),
        StartupStep("after_optional", record("after_optional")),
    ))
    assert calls == [("failed", app), ("after_optional", app)]

    try:
        run_startup_sequence(app, (StartupStep("fatal", fail),))
    except RuntimeError as exc:
        assert str(exc) == "expected"
    else:
        raise AssertionError("A fatal startup failure was swallowed")

    source = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
    markers = (
        'StartupStep("admin_recovery"',
        'StartupStep("maintenance_recovery"',
        'StartupStep("one_shot_repair"',
        'StartupStep("plex_websocket_engine"',
    )
    offsets = [source.index(marker) for marker in markers]
    assert offsets == sorted(offsets), "Application startup steps are out of order"
    assert 'StartupStep("plex_websocket_engine", _start_plex_websocket_engine, fatal=False)' in source

    print("OK - startup sequence ordering and failure policies validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
