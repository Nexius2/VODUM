"""Shared output contract for command-line task entry points."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping


def add_summary_only_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Emit one machine-readable JSON summary and suppress detailed CLI output.",
    )


def emit_task_result(
    logger,
    *,
    task_name: str,
    status: str,
    summary: Mapping[str, object],
    summary_only: bool,
    detail_lines: Iterable[str] = (),
) -> dict:
    """Emit either detailed log lines or one stable JSON summary."""
    payload = {
        "task": str(task_name),
        "status": str(status),
        "summary": dict(summary),
    }

    if summary_only:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        print(encoded)
        logger.info(encoded)
    else:
        for line in detail_lines:
            logger.info(str(line))

    return payload
