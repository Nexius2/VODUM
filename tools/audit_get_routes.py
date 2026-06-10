"""Report GET routes that may modify state.

This is a lightweight static audit. It intentionally favors false positives:
each reported route must be reviewed, then converted to POST or explicitly
documented as an allowed read-through proxy.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


ROUTE_DECORATORS = {"route", "get"}
SUSPICIOUS_CALLS = {
    "commit",
    "enable_and_run_task_by_name",
    "enqueue_server_discovery_sequence",
    "enqueue_task",
    "execute",
    "executemany",
    "force_task_run",
    "mkdir",
    "remove",
    "rename",
    "replace",
    "run_task_by_name",
    "save",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}

# GET routes that intentionally populate/read a cache while proxying media.
ALLOWED_GET_MUTATIONS = {
    ("app/routes/monitoring_api.py", "api_monitoring_poster"):
        "Authenticated artwork proxy with a local response cache.",
}


def _decorator_name(node: ast.expr) -> str | None:
    call = node if isinstance(node, ast.Call) else None
    target = call.func if call else node
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _route_methods(decorator: ast.expr) -> set[str] | None:
    name = _decorator_name(decorator)
    if name not in ROUTE_DECORATORS:
        return None
    if name == "get":
        return {"GET"}

    call = decorator if isinstance(decorator, ast.Call) else None
    if not call:
        return {"GET"}
    for keyword in call.keywords:
        if keyword.arg != "methods":
            continue
        if isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
            methods = {
                value.value.upper()
                for value in keyword.value.elts
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            }
            return methods
        return set()
    return {"GET"}


def _called_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def audit(routes_dir: Path, project_root: Path) -> tuple[list[dict], list[dict]]:
    findings = []
    allowed = []
    for path in sorted(routes_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(project_root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            methods = set()
            is_route = False
            for decorator in node.decorator_list:
                route_methods = _route_methods(decorator)
                if route_methods is not None:
                    is_route = True
                    methods.update(route_methods)
            if not is_route or "GET" not in methods:
                continue

            exception_reason = ALLOWED_GET_MUTATIONS.get((relative, node.name))
            if exception_reason:
                allowed.append(
                    {
                        "file": relative,
                        "line": node.lineno,
                        "function": node.name,
                        "calls": [],
                        "reason": exception_reason,
                    }
                )
                continue

            suspicious = sorted(_called_names(node) & SUSPICIOUS_CALLS)
            if not suspicious:
                continue
            item = {
                "file": relative,
                "line": node.lineno,
                "function": node.name,
                "calls": suspicious,
            }
            findings.append(item)
    return findings, allowed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit with status 1 when routes requiring review are found",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="print counts without individual route details",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    findings, allowed = audit(project_root / "app" / "routes", project_root)

    if not args.summary_only:
        for item in findings:
            calls = ", ".join(item["calls"])
            print(f"REVIEW {item['file']}:{item['line']} {item['function']} [{calls}]")
        for item in allowed:
            print(
                f"ALLOWED {item['file']}:{item['line']} {item['function']} "
                f"- {item['reason']}"
            )
    print(f"GET route audit: review={len(findings)}, allowed={len(allowed)}")
    return 1 if args.strict and findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
