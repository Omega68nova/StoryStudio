from __future__ import annotations

from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
TEST = Path("backend/tests/test_phase4_planning_bridge.py")


def load(name: str) -> str:
    return (HERE / "_payload" / name).read_text(encoding="utf-8")


def backup(path: Path) -> None:
    target = path.with_suffix(
        path.suffix + ".phase4-slice8-hotfix1-backup"
    )
    if not target.exists():
        shutil.copy2(path, target)


def main() -> int:
    if not TEST.is_file():
        print(
            "Run this script from the StoryStudio repository root.",
            file=sys.stderr,
        )
        return 2

    text = TEST.read_text(encoding="utf-8")
    old = load("old.txt")
    new = load("new.txt")

    if old not in text:
        print(
            "Expected old ownership assertion was not found. "
            "The test may already be updated.",
            file=sys.stderr,
        )
        return 3

    text = text.replace(old, new, 1)
    text = text.replace(
        "def test_phase4_commit_publishes_through_planning_service(",
        "def test_phase4_commit_publishes_without_syncing_legacy_lifecycle(",
        1,
    )

    compile(text, str(TEST), "exec")

    backup(TEST)
    TEST.write_text(text, encoding="utf-8")

    print(
        "Updated Phase 4 bridge test for GenerationPlan lifecycle ownership."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
