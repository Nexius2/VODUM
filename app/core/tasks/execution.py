import importlib
import time

from core.tasks.result_validation import validate_task_result


def load_task_callable(task_name: str):
    module_name = f"tasks.{task_name}"
    try:
        module = importlib.import_module(module_name)
        run_func = getattr(module, "run", None)
        if run_func is None:
            raise AttributeError(f"The module {module_name} does not expose run()")
        return run_func
    except Exception as exc:
        raise RuntimeError(f"Unable to load {module_name}: {exc}") from exc


class TaskExecutionRunner:
    """Coordinate one task execution while persistence stays injectable."""

    def __init__(
        self, db, load_context, mark_running, mark_success, mark_error,
        finalize, task_log, logger, debug_enabled, *, clock=time.time,
        callable_loader=load_task_callable,
    ):
        self.db = db
        self.load_context = load_context
        self.mark_running = mark_running
        self.mark_success = mark_success
        self.mark_error = mark_error
        self.finalize = finalize
        self.task_log = task_log
        self.logger = logger
        self.debug_enabled = debug_enabled
        self.clock = clock
        self.callable_loader = callable_loader

    def _process_result(self, task_id, task_name, result, started_at, max_duration):
        if result is not None:
            try:
                self.task_log(
                    task_id, "info", f"Task '{task_name}' returned",
                    details=result, debug_only=True,
                )
            except Exception:
                self.logger.warning(
                    "Unable to log task return payload | task=%s | id=%s",
                    task_name, task_id, exc_info=True,
                )
        return validate_task_result(
            task_name, result, self.clock() - started_at, max_duration
        )

    def run(self, task_id):
        context = self.load_context(task_id)
        if not context:
            return None

        task_name = context["name"]
        schedule = context["schedule"]
        max_duration = context["max_duration"]
        self.task_log(
            task_id, "start", f"Starting task '{task_name}'", debug_only=True
        )
        started_at = self.clock()

        try:
            self.mark_running(task_id)
        except Exception as exc:
            self.logger.error("Unable to mark task running | id=%s", task_id, exc_info=True)
            self.task_log(task_id, "error", f"Unable to mark task running: {exc}")
            return None

        try:
            run_func = self.callable_loader(task_name)
        except Exception as exc:
            self.logger.error(str(exc), exc_info=True)
            self.task_log(task_id, "error", str(exc))
            self.mark_error(task_id, task_name, str(exc))
            self._finalize(task_id)
            return None

        try:
            result = run_func(task_id, self.db)
            self._process_result(task_id, task_name, result, started_at, max_duration)
            self.mark_success(task_id, task_name, schedule)
            return result
        except Exception as exc:
            message = f"Error while running {task_name}: {exc}"
            self.logger.error(message, exc_info=True)
            self.task_log(task_id, "error", message)
            self.mark_error(task_id, task_name, str(exc))
            return None
        finally:
            self._finalize(task_id)

    def _finalize(self, task_id):
        try:
            self.finalize(task_id)
        except Exception as exc:
            self.logger.error("Failsafe unable to finalize task %s", task_id, exc_info=True)
            self.task_log(task_id, "warning", f"Failsafe final failed: {exc}")
