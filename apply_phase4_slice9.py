from __future__ import annotations

from pathlib import Path
import ast
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "_payload"

PLANNING_V2 = Path("backend/app/services/planning_v2.py")
PLANNING = Path("backend/app/services/planning.py")
BRIDGE = Path("backend/app/services/planningGenerationBridge.py")
HANDLER = Path("backend/app/handlers/batchGenerationJobHandler.py")
DATABASE = Path("backend/app/database.py")


def load(name: str) -> str:
    return (PAYLOAD / name).read_text(encoding="utf-8")


def backup(path: Path) -> None:
    target = path.with_suffix(path.suffix + ".phase4-slice9-v3-backup")
    if not target.exists():
        shutil.copy2(path, target)


def write_checked(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    backup(path)
    path.write_text(text, encoding="utf-8")
    print(f"Updated {path}")


def function_span(text: str, name: str) -> tuple[int, int]:
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return offsets[node.lineno - 1], offsets[node.end_lineno]
    raise RuntimeError(f"Could not locate function {name}()")


def payload_functions() -> dict[str, str]:
    source = load("functions.pyfrag")
    module = ast.parse(source)
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    result: dict[str, str] = {}
    for node in module.body:
        if isinstance(node, ast.FunctionDef):
            result[node.name] = source[
                offsets[node.lineno - 1]:offsets[node.end_lineno]
            ].rstrip() + "\n"
    return result


def replace_if_present(text: str, old_name: str, new_name: str) -> str:
    old = load(old_name)
    if old not in text:
        return text
    return text.replace(old, load(new_name), 1)


def patch_planning_v2() -> None:
    text = PLANNING_V2.read_text(encoding="utf-8")
    original = text
    functions = payload_functions()

    if "def _provenance_owner_ids(" not in text:
        start, _ = function_span(text, "resolve_resource")
        helpers = (
            functions["_provenance_owner_ids"]
            + "\n"
            + functions["_resource_row"]
            + "\n"
        )
        text = text[:start] + helpers + text[start:]

    for name in (
        "resolve_resource",
        "record_resource",
        "apply_weather",
        "apply_rules",
        "apply_outfits",
        "apply_runtime",
        "prepare_image_plans",
    ):
        start, end = function_span(text, name)
        text = text[:start] + functions[name] + text[end:]

    if text != original:
        write_checked(PLANNING_V2, text)


def patch_planning() -> None:
    text = PLANNING.read_text(encoding="utf-8")
    original = text

    text = replace_if_present(text, "import_old.txt", "import_new.txt")

    if "generation_plan_id: str | None = None" not in text:
        pattern = re.compile(
            r"(def approve_stage\(.*?\*,\s*finalize: bool = True,\s*"
            r"next_draft: dict\[str, Any\] \| None = None,\s*"
            r"sync_legacy_state: bool = True)(\s*\) -> dict\[str, Any\]:)",
            re.S,
        )
        text, count = pattern.subn(
            r"\1,\n                      generation_plan_id: str | None = None\2",
            text,
            count=1,
        )
        if count != 1:
            raise RuntimeError(
                "Could not extend approve_stage() with generation_plan_id"
            )

    if "provenance_owner = generation_plan_id or session_id" not in text:
        marker = "        resolutions = resolutions or {}\n"
        if marker not in text:
            raise RuntimeError("approve_stage resolutions marker not found")
        text = text.replace(
            marker,
            marker + "        provenance_owner = generation_plan_id or session_id\n",
            1,
        )

    text = replace_if_present(
        text, "existing_keys_old.txt", "existing_keys_new.txt"
    )
    text = replace_if_present(text, "unlink_old.txt", "unlink_new.txt")
    text = replace_if_present(
        text, "entity_insert_old.txt", "entity_insert_new.txt"
    )
    text = replace_if_present(
        text, "relation_insert_old.txt", "relation_insert_new.txt"
    )

    text = text.replace(
        'resolve_resource(self.db, session_id, relation.get("key"), "relationship")',
        'resolve_resource(self.db, provenance_owner, relation.get("key"), "relationship")',
    )
    text = text.replace(
        'apply_weather(self.db, session["project_id"], session_id, stage_number, draft)',
        'apply_weather(self.db, session["project_id"], provenance_owner, stage_number, draft)',
    )
    text = text.replace(
        'apply_rules(self.db, session["project_id"], session_id, stage_number, draft)',
        'apply_rules(self.db, session["project_id"], provenance_owner, stage_number, draft)',
    )
    text = text.replace(
        'apply_outfits(self.db, session["project_id"], session_id, stage_number, draft)',
        'apply_outfits(self.db, session["project_id"], provenance_owner, stage_number, draft)',
    )
    text = text.replace(
        'apply_runtime(self.db, session["project_id"], session_id, draft)',
        'apply_runtime(self.db, session["project_id"], provenance_owner, draft)',
    )

    if "generation_plan_id: str | None = None" not in text[text.find("def prepare_image_stage"):]:
        text = text.replace(
            "def prepare_image_stage(self, session_id: str) -> dict[str, Any]:",
            "def prepare_image_stage("
            "self, session_id: str, *, "
            "generation_plan_id: str | None = None"
            ") -> dict[str, Any]:",
            1,
        )

    text = text.replace(
        'prepare_image_plans(self.db, session["project_id"], session_id, draft)',
        'prepare_image_plans('
        'self.db, session["project_id"], '
        'generation_plan_id or session_id, draft)',
    )

    if text != original:
        write_checked(PLANNING, text)


def patch_bridge() -> None:
    text = BRIDGE.read_text(encoding="utf-8")
    original = text

    if 'generation_plan_id=plan["id"]' not in text:
        old = load("bridge_commit_old.txt")
        if old not in text:
            raise RuntimeError(
                "Could not locate PlanningStageCommitter publication call"
            )
        text = text.replace(old, load("bridge_commit_new.txt"), 1)

    text = replace_if_present(
        text, "bridge_image_old.txt", "bridge_image_new.txt"
    )

    if text != original:
        write_checked(BRIDGE, text)


def patch_handler() -> None:
    text = HANDLER.read_text(encoding="utf-8")
    original = text
    text = replace_if_present(text, "handler_old.txt", "handler_new.txt")
    if text != original:
        write_checked(HANDLER, text)


def patch_database() -> None:
    text = DATABASE.read_text(encoding="utf-8")
    original = text
    text = replace_if_present(text, "database_old.txt", "database_new.txt")
    if text != original:
        write_checked(DATABASE, text)


def validate_boundary() -> None:
    planning_v2 = PLANNING_V2.read_text(encoding="utf-8")
    planning = PLANNING.read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")
    handler = HANDLER.read_text(encoding="utf-8")
    database = DATABASE.read_text(encoding="utf-8")

    required = [
        ("planning_v2 provenance helper", "def _provenance_owner_ids(", planning_v2),
        ("planning_v2 generation plan column", "generation_plan_id", planning_v2),
        ("PlanningService provenance owner", "provenance_owner = generation_plan_id or session_id", planning),
        ("committer plan ownership", 'generation_plan_id=plan["id"]', bridge),
        ("stage8 plan ownership", "generation_plan_id=plan_id", handler),
    ]
    missing = [label for label, needle, haystack in required if needle not in haystack]
    if "self._repair_planning_state(connection)" in database:
        missing.append("legacy restart recovery removal")
    if missing:
        raise RuntimeError(
            "Slice 9 boundary validation failed: " + ", ".join(missing)
        )


def main() -> int:
    required = [PLANNING_V2, PLANNING, BRIDGE, HANDLER, DATABASE]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print(
            "Run from the StoryStudio repository root after Phase 4 Slice 8. "
            "Missing: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 2

    patch_planning_v2()
    patch_planning()
    patch_bridge()
    patch_handler()
    patch_database()
    validate_boundary()

    print(
        "Phase 4 Slice 9 v3 applied. "
        "GenerationPlan now owns canonical planning provenance."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
