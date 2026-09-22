from __future__ import annotations

from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "_slice8_payload"

EXECUTOR = Path("backend/app/services/planningBatchTaskExecutor.py")
BRIDGE = Path("backend/app/services/planningGenerationBridge.py")
PLANNING = Path("backend/app/services/planning.py")
GEN_API = Path("backend/app/services/generationPlanApiService.py")
MAIN = Path("backend/app/main.py")
PLANNING_UI = Path("frontend/src/PlanningStudio.tsx")


def load(name: str) -> str:
    return (PAYLOAD / name).read_text(encoding="utf-8")


def backup(path: Path) -> None:
    target = path.with_suffix(path.suffix + ".phase4-slice8-backup")
    if path.exists() and not target.exists():
        shutil.copy2(path, target)


def replace_required(
    text: str,
    old_name: str,
    new_name: str,
    *,
    count: int = 1,
) -> str:
    old = load(old_name)
    new = load(new_name)
    if old not in text:
        raise RuntimeError(
            f"Expected Slice 7 source block not found: {old_name}"
        )
    return text.replace(old, new, count)


def patch_executor() -> None:
    text = EXECUTOR.read_text(encoding="utf-8")
    original = text

    import_line = load("executor_import.txt")
    if import_line not in text:
        marker = "from app.services.planning import PlanningService, stage_prompt\n"
        if marker not in text:
            raise RuntimeError(
                "planningBatchTaskExecutor import marker not found"
            )
        text = text.replace(marker, marker + import_line, 1)

    if load("executor_context_old.txt") in text:
        text = replace_required(
            text,
            "executor_context_old.txt",
            "executor_context_new.txt",
        )

    if text != original:
        backup(EXECUTOR)
        EXECUTOR.write_text(text, encoding="utf-8")
        print(f"Updated {EXECUTOR}")


def patch_bridge() -> None:
    text = BRIDGE.read_text(encoding="utf-8")
    original = text

    if load("bridge_existing_old.txt") in text:
        text = replace_required(
            text,
            "bridge_existing_old.txt",
            "bridge_existing_new.txt",
        )

    if load("bridge_new_plan_old.txt") in text:
        text = replace_required(
            text,
            "bridge_new_plan_old.txt",
            "bridge_new_plan_new.txt",
        )

    if load("committer_call_old.txt") in text:
        text = replace_required(
            text,
            "committer_call_old.txt",
            "committer_call_new.txt",
        )

    if text != original:
        backup(BRIDGE)
        BRIDGE.write_text(text, encoding="utf-8")
        print(f"Updated {BRIDGE}")


def patch_planning_service() -> None:
    text = PLANNING.read_text(encoding="utf-8")
    original = text

    if load("planning_signature_old.txt") in text:
        text = replace_required(
            text,
            "planning_signature_old.txt",
            "planning_signature_new.txt",
        )

    if load("planning_idempotency_old.txt") in text:
        text = replace_required(
            text,
            "planning_idempotency_old.txt",
            "planning_idempotency_new.txt",
        )

    if load("planning_tail_old.txt") in text:
        text = replace_required(
            text,
            "planning_tail_old.txt",
            "planning_tail_new.txt",
        )

    if text != original:
        backup(PLANNING)
        PLANNING.write_text(text, encoding="utf-8")
        print(f"Updated {PLANNING}")


def patch_generation_api() -> None:
    text = GEN_API.read_text(encoding="utf-8")
    if "    def save_planning_result(" in text:
        return

    marker = "    def replace_generated_result(\n"
    pos = text.find(marker)
    if pos < 0:
        raise RuntimeError(
            "GenerationPlanApiService.replace_generated_result() not found"
        )

    backup(GEN_API)
    GEN_API.write_text(
        text[:pos] + load("api_method.txt") + text[pos:],
        encoding="utf-8",
    )
    print(f"Updated {GEN_API}")


def remove_route(
    text: str,
    start_marker: str,
    end_marker: str,
) -> str:
    start = text.find(start_marker)
    if start < 0:
        return text
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(
            f"Could not find route end for {start_marker}"
        )
    return text[:start] + text[end:]


def patch_main() -> None:
    text = MAIN.read_text(encoding="utf-8")
    original = text

    route = load("main_route.txt")
    if route not in text:
        marker = (
            '@app.post(\n'
            '    "/api/generation-plans/planning/{session_id}/tasks/'
            '{stage_number}/preflight"\n'
            ')\n'
        )
        pos = text.find(marker)
        if pos < 0:
            raise RuntimeError(
                "GenerationPlan planning preflight route not found"
            )
        text = text[:pos] + route + text[pos:]

    # Legacy draft persistence no longer owns editable planning state.
    text = remove_route(
        text,
        '@app.put("/api/planning/{session_id}/stages/{stage_number}")',
        '\n\n@app.post("/api/planning/{session_id}/stages/{stage_number}/accept-batch")',
    )

    if text != original:
        backup(MAIN)
        MAIN.write_text(text, encoding="utf-8")
        print(f"Updated {MAIN}")


def patch_planning_ui() -> None:
    text = PLANNING_UI.read_text(encoding="utf-8")
    original = text

    old = load("ui_save_old.txt")
    if old in text:
        text = text.replace(
            old,
            load("ui_save_new.txt"),
            1,
        )

    old = load("ui_saveapprove_old.txt")
    if old in text:
        text = text.replace(
            old,
            load("ui_saveapprove_new.txt"),
            1,
        )

    legacy = '`/planning/${session!.id}/stages/${stage}`'
    if legacy in text:
        raise RuntimeError(
            "PlanningStudio still contains an unexpected legacy stage PUT call"
        )

    if text != original:
        backup(PLANNING_UI)
        PLANNING_UI.write_text(text, encoding="utf-8")
        print(f"Updated {PLANNING_UI}")


def main() -> int:
    required = [
        EXECUTOR,
        BRIDGE,
        PLANNING,
        GEN_API,
        MAIN,
        PLANNING_UI,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print(
            "Run from the StoryStudio repository root after Phase 4 Slice 7. "
            "Missing: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 2

    patch_executor()
    patch_bridge()
    patch_planning_service()
    patch_generation_api()
    patch_main()
    patch_planning_ui()

    print(
        "Phase 4 Slice 8 persistence consolidation applied. "
        "GenerationPlan now owns editable/review planning state."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
