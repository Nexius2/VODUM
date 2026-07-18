"""Pure validation rules for scheduler task return values."""

from __future__ import annotations


def validate_task_result(task_name: str, result, duration_seconds: float, max_duration: int):
    """Raise the scheduler-level error represented by a task result."""
    duration_seconds = max(0.0, float(duration_seconds or 0.0))
    max_duration = max(0, int(max_duration or 0))

    if duration_seconds > max_duration:
        raise TimeoutError(
            f"Task {task_name} exceeded maximum duration "
            f"({int(duration_seconds)}s > {max_duration}s)"
        )

    if isinstance(result, dict):
        returned_status = str(result.get("status") or "").strip().lower()
        if returned_status == "error":
            returned_error = (
                result.get("message")
                or result.get("error")
                or f"Task {task_name} returned status=error"
            )
            raise RuntimeError(str(returned_error))

    return result
