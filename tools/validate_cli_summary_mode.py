"""Validate the shared --summary-only CLI output contract."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.cli_output import add_summary_only_argument, emit_task_result  # noqa: E402


class Logger:
    def __init__(self):
        self.lines = []

    def info(self, message):
        self.lines.append(str(message))


def main() -> int:
    parser = argparse.ArgumentParser()
    add_summary_only_argument(parser)
    assert parser.parse_args([]).summary_only is False
    assert parser.parse_args(["--summary-only"]).summary_only is True

    logger = Logger()
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        payload = emit_task_result(
            logger,
            task_name="example",
            status="success",
            summary={"inserted": 3, "skipped": 1},
            summary_only=True,
            detail_lines=("detail one", "detail two"),
        )
    output = stdout.getvalue().strip().splitlines()
    assert len(output) == 1
    assert json.loads(output[0]) == payload
    assert logger.lines == [output[0]]
    assert "detail one" not in output[0]

    logger = Logger()
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        emit_task_result(
            logger,
            task_name="example",
            status="success",
            summary={"inserted": 3},
            summary_only=False,
            detail_lines=("detail one", "detail two"),
        )
    assert stdout.getvalue() == ""
    assert logger.lines == ["detail one", "detail two"]

    task_source = (ROOT / "app/tasks/import_tautulli.py").read_text(encoding="utf-8")
    assert "sys.path.insert(0, str(APP_DIR))" in task_source
    assert "add_summary_only_argument(parser)" in task_source
    assert "summary_only=bool(args.summary_only)" in task_source

    print("OK - shared summary-only CLI output is stable and Tautulli uses it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
