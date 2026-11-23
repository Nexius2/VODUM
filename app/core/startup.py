"""Centralized, observable application startup sequencing."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Callable, Iterable

from logging_utils import get_logger


@dataclass(frozen=True)
class StartupStep:
    name: str
    action: Callable[[object], object]
    fatal: bool = True


def run_startup_sequence(app, steps: Iterable[StartupStep]) -> None:
    """Run startup steps in order, with one explicit failure policy."""
    boot_logger = get_logger("boot")
    steps = tuple(steps)
    boot_logger.info("[BOOT] application startup begin | steps=%s", len(steps))

    for position, step in enumerate(steps, start=1):
        started_at = monotonic()
        boot_logger.info(
            "[BOOT] step begin | position=%s/%s | name=%s | fatal=%s",
            position, len(steps), step.name, step.fatal,
        )
        try:
            step.action(app)
        except Exception:
            boot_logger.exception(
                "[BOOT] step failed | position=%s/%s | name=%s | fatal=%s",
                position, len(steps), step.name, step.fatal,
            )
            if step.fatal:
                raise
        else:
            boot_logger.info(
                "[BOOT] step done | position=%s/%s | name=%s | duration_ms=%s",
                position, len(steps), step.name,
                round((monotonic() - started_at) * 1000),
            )

    boot_logger.info("[BOOT] application startup end")
