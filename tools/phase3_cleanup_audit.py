from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SQL_RE = re.compile(
    r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|WITH\s+RECURSIVE|PRAGMA)\b",
    re.IGNORECASE,
)
DB_CALLS = {
    "fetch_one",
    "fetch_all",
    "execute",
    "create_job",
    "get_job",
    "update_job",
    "update_job_payload",
    "update_job_progress",
    "update_job_partial_output",
    "update_job_metrics",
    "create_story_node",
    "story_path",
    "get_project",
    "begin_transaction",
    "finish_transaction",
    "connect",
}

# Files where persistence primitives are intentionally allowed.
ALLOWED_PERSISTENCE = {
    "app/database.py",
}
ALLOWED_PREFIXES = (
    "app/data/",
    "app/migrations/",
)

# These are transitional calls that may legitimately remain for now because
# they are non-SQL compatibility facades or transaction primitives.
TRANSITIONAL_ALLOWED_CALLS = {
    "connect",
    "begin_transaction",
    "finish_transaction",
}


def rel(path: Path, backend: Path) -> str:
    return path.relative_to(backend).as_posix()


def is_allowed_persistence(path_name: str) -> bool:
    return (
        path_name in ALLOWED_PERSISTENCE
        or any(path_name.startswith(prefix) for prefix in ALLOWED_PREFIXES)
    )


def string_literals(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if SQL_RE.search(node.value):
                found.append((getattr(node, "lineno", 0), node.value))
    return found


def db_calls(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in DB_CALLS:
            continue
        owner = func.value
        owner_name = None
        if isinstance(owner, ast.Name):
            owner_name = owner.id
        elif isinstance(owner, ast.Attribute):
            owner_name = owner.attr
        if owner_name in {"db", "database"} or (
            isinstance(owner, ast.Attribute)
            and owner.attr == "db"
        ):
            found.append((getattr(node, "lineno", 0), func.attr))
    return found


def scan_backend(backend: Path) -> dict[str, Any]:
    raw_sql: list[dict[str, Any]] = []
    transitional: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []

    app = backend / "app"
    for path in sorted(app.rglob("*.py")):
        path_name = rel(path, backend)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except Exception as exc:
            parse_errors.append({
                "file": path_name,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        if not is_allowed_persistence(path_name):
            for line, literal in string_literals(tree):
                raw_sql.append({
                    "file": path_name,
                    "line": line,
                    "preview": " ".join(literal.split())[:180],
                })

        for line, method in db_calls(tree):
            if is_allowed_persistence(path_name):
                continue
            transitional.append({
                "file": path_name,
                "line": line,
                "method": method,
                "severity": (
                    "low"
                    if method in TRANSITIONAL_ALLOWED_CALLS
                    else "review"
                ),
            })

    return {
        "raw_sql": raw_sql,
        "transitional_db_calls": transitional,
        "parse_errors": parse_errors,
    }


def test_inventory(backend: Path) -> dict[str, Any]:
    tests_dir = backend / "tests"
    files = sorted(tests_dir.glob("test_*.py")) if tests_dir.exists() else []
    phase3 = [p for p in files if "phase3" in p.name.lower()]
    legacy = [p for p in files if p not in phase3]
    return {
        "total": len(files),
        "phase3": [p.name for p in phase3],
        "legacy": [p.name for p in legacy],
    }


def run_pytest(backend: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q"]
    proc = subprocess.run(
        command,
        cwd=backend,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        errors="replace",
    )
    output = proc.stdout
    failure_headers = re.findall(
        r"^_{2,}\s+(.+?)\s+_{2,}$",
        output,
        flags=re.MULTILINE,
    )
    failed_nodes = re.findall(
        r"^FAILED\s+([^\s]+)",
        output,
        flags=re.MULTILINE,
    )
    return {
        "command": " ".join(command),
        "returncode": proc.returncode,
        "failed_nodes": failed_nodes,
        "failure_headers": failure_headers,
        "output": output,
    }


def render_report(data: dict[str, Any]) -> str:
    scan = data["scan"]
    tests = data["tests"]
    pytest = data.get("pytest")

    by_file_sql = Counter(item["file"] for item in scan["raw_sql"])
    by_file_calls = Counter(
        item["file"] for item in scan["transitional_db_calls"]
    )
    by_method = Counter(
        item["method"] for item in scan["transitional_db_calls"]
    )

    lines = [
        "# StoryStudio Phase 3 Cleanup Audit",
        "",
        "This report is generated from the current local checkout, not from the GitHub baseline.",
        "",
        "## Test inventory",
        "",
        f"- Total test files: {tests['total']}",
        f"- Phase 3 test files: {len(tests['phase3'])}",
        f"- Legacy test files: {len(tests['legacy'])}",
        "",
    ]

    if pytest is not None:
        lines += [
            "## Pytest result",
            "",
            f"- Return code: {pytest['returncode']}",
            f"- Failed nodes: {len(pytest['failed_nodes'])}",
            "",
        ]
        if pytest["failed_nodes"]:
            lines += ["### Failed tests", ""]
            lines += [f"- `{node}`" for node in pytest["failed_nodes"]]
            lines.append("")

    lines += [
        "## Raw SQL outside repositories/database",
        "",
        f"Found {len(scan['raw_sql'])} SQL literals requiring review.",
        "",
    ]
    if by_file_sql:
        lines += ["| File | SQL literals |", "|---|---:|"]
        lines += [
            f"| `{file}` | {count} |"
            for file, count in by_file_sql.most_common()
        ]
        lines.append("")

    lines += [
        "## Transitional Database facade calls",
        "",
        f"Found {len(scan['transitional_db_calls'])} calls outside repositories/database.",
        "",
    ]
    if by_method:
        lines += ["| Method | Count |", "|---|---:|"]
        lines += [
            f"| `{method}` | {count} |"
            for method, count in by_method.most_common()
        ]
        lines.append("")

    if by_file_calls:
        lines += ["### Files with the most facade calls", ""]
        lines += [
            f"- `{file}` — {count}"
            for file, count in by_file_calls.most_common(25)
        ]
        lines.append("")

    if scan["parse_errors"]:
        lines += ["## Parse errors", ""]
        lines += [
            f"- `{item['file']}` — {item['error']}"
            for item in scan["parse_errors"]
        ]
        lines.append("")

    lines += [
        "## Recommended interpretation",
        "",
        "- A legacy test is safe to update/remove only when its failure is caused by an intentionally removed persistence boundary or constructor assumption.",
        "- Behavioral assertions should be preserved and redirected through repositories/services rather than deleted.",
        "- SQL still present in managers/handlers/services should normally move to an existing typed repository or a new narrow domain repository.",
        "- `connect`, `begin_transaction`, and `finish_transaction` calls are lower priority when they guard a domain-level atomic operation, but should still be reviewed.",
        "- Do not move unrelated domain SQL into `WorldRepository` or `PlanningRepository` merely to make this report smaller.",
        "",
    ]

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        default="backend",
        help="Path to the backend directory (default: backend)",
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run the full pytest suite and include failures in the report",
    )
    parser.add_argument(
        "--output",
        default="phase3_cleanup_report",
        help="Output path without extension",
    )
    args = parser.parse_args()

    backend = Path(args.backend).resolve()
    if not (backend / "app").is_dir():
        print(
            f"{backend} does not look like StoryStudio/backend",
            file=sys.stderr,
        )
        return 2

    data: dict[str, Any] = {
        "backend": str(backend),
        "scan": scan_backend(backend),
        "tests": test_inventory(backend),
    }
    if args.run_tests:
        data["pytest"] = run_pytest(backend)

    output = Path(args.output)
    if not output.is_absolute():
        output = Path.cwd() / output

    json_path = output.with_suffix(".json")
    md_path = output.with_suffix(".md")

    json_path.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(
        render_report(data),
        encoding="utf-8",
    )

    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    print(
        f"Raw SQL findings: {len(data['scan']['raw_sql'])}; "
        f"DB facade calls: {len(data['scan']['transitional_db_calls'])}"
    )
    if "pytest" in data:
        print(
            f"Pytest return code: {data['pytest']['returncode']}; "
            f"failed nodes: {len(data['pytest']['failed_nodes'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
