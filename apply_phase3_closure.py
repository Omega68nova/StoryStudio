from __future__ import annotations

from pathlib import Path
import shutil
import sys

DATA_PROVIDER = Path("backend/app/data/dataProvider.py")
STORY_REPO = Path("backend/app/data/storyRepository.py")
STORY_MANAGER = Path("backend/app/managers/storyManager.py")
BOUNDARY_TEST = Path("backend/tests/test_phase3_final_boundaries.py")


def backup(path: Path) -> None:
    target = path.with_suffix(path.suffix + ".phase3-closure-backup")
    if not target.exists():
        shutil.copy2(path, target)


def patch_data_provider() -> None:
    text = DATA_PROVIDER.read_text(encoding="utf-8")
    original = text

    import_line = "from app.data.runtimeRepository import RuntimeRepository\n"
    if import_line not in text:
        marker = "from app.data.lifecycleRepository import LifecycleRepository\n"
        if marker not in text:
            marker = "from app.data.worldRepository import WorldRepository\n"
        if marker not in text:
            raise RuntimeError("Could not find DataProvider import marker")
        text = text.replace(marker, marker + import_line, 1)

    if "self.runtime = RuntimeRepository(db)" not in text:
        marker = "        self.lifecycle = LifecycleRepository(db)\n"
        if marker not in text:
            marker = "        self.world = WorldRepository(db)\n"
        if marker not in text:
            raise RuntimeError("Could not find DataProvider repository marker")
        text = text.replace(
            marker,
            marker + "        self.runtime = RuntimeRepository(db)\n",
            1,
        )

    if text != original:
        backup(DATA_PROVIDER)
        DATA_PROVIDER.write_text(text, encoding="utf-8")
        print(f"Updated {DATA_PROVIDER}")


def patch_story_repository() -> None:
    text = STORY_REPO.read_text(encoding="utf-8")
    original = text

    if "def branch_summary_for_path(" not in text:
        addition = '''
    def branch_summary_for_path(
        self,
        project_id: str,
        node_ids: set[str],
    ) -> dict[str, Any] | None:
        if not node_ids:
            return None
        rows = self.db.fetch_all(
            "SELECT * FROM branch_summaries "
            "WHERE project_id=? "
            "ORDER BY created_at DESC",
            (project_id,),
        )
        return next(
            (
                row
                for row in rows
                if row["through_node_id"] in node_ids
            ),
            None,
        )
'''
        marker = "\n    def inherited_view("
        if marker not in text:
            marker = "\n    def create_node("
        if marker not in text:
            raise RuntimeError(
                "Could not find StoryRepository insertion marker"
            )
        text = text.replace(marker, addition + marker, 1)

    if text != original:
        backup(STORY_REPO)
        STORY_REPO.write_text(text, encoding="utf-8")
        print(f"Updated {STORY_REPO}")


def patch_story_manager() -> None:
    text = STORY_MANAGER.read_text(encoding="utf-8")
    original = text

    if "from app.data.dataProvider import DataProvider\n" not in text:
        marker = (
            "from app.managers.contextBuilder import "
            "ContextBuilder, StoryContext\n"
        )
        if marker not in text:
            raise RuntimeError("Could not find StoryManager import marker")
        text = text.replace(
            marker,
            "from app.data.dataProvider import DataProvider\n" + marker,
            1,
        )

    old_ctor = '''    def __init__(
        self,
        db: Any,
        world: WorldEngine | None = None,
        environment: EnvironmentManager | None = None,
    ) -> None:
        self.db = db
        self.world = world or WorldEngine(db)
'''
    new_ctor = '''    def __init__(
        self,
        db: Any,
        world: WorldEngine | None = None,
        environment: EnvironmentManager | None = None,
        *,
        data_provider: DataProvider | None = None,
    ) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.world = world or WorldEngine(
            db,
            data_provider=self.data,
        )
'''
    if old_ctor in text:
        text = text.replace(old_ctor, new_ctor, 1)
    elif "self.data = data_provider or DataProvider(db)" not in text:
        raise RuntimeError("StoryManager constructor did not match expected source")

    old_path = '''        path = self.db.story_path(
            request.head_node_id
        )
'''
    new_path = '''        path = self.data.stories.path(
            request.head_node_id
        )
'''
    if old_path in text:
        text = text.replace(old_path, new_path, 1)

    start = text.find("    def _summary_for_path(\n")
    if start < 0:
        raise RuntimeError("Could not find StoryManager _summary_for_path")
    replacement = '''    def _summary_for_path(
        self,
        project_id: str,
        path: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        return self.data.stories.branch_summary_for_path(
            project_id,
            {node["id"] for node in path},
        )

    def _runtime_settings(
        self,
    ) -> dict[str, Any]:
        return self.data.runtime.settings()
'''
    text = text[:start] + replacement + "\n"

    if text != original:
        backup(STORY_MANAGER)
        STORY_MANAGER.write_text(text, encoding="utf-8")
        print(f"Updated {STORY_MANAGER}")


def patch_boundary_test() -> None:
    text = BOUNDARY_TEST.read_text(encoding="utf-8")
    original = text

    if "import ast\n" not in text:
        text = text.replace(
            "from pathlib import Path\n",
            "import ast\nfrom pathlib import Path\n",
            1,
        )

    start = text.find(
        "def test_managers_do_not_own_raw_sql() -> None:\n"
    )
    end = text.find(
        "\n\ndef test_auth_and_lifecycle_services_use_repositories",
        start,
    )
    if start < 0 or end < 0:
        raise RuntimeError("Could not locate manager boundary test")

    replacement = '''def test_managers_do_not_own_raw_sql() -> None:
    managers = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "managers"
    )
    offenders: list[str] = []

    for path in managers.glob("*.py"):
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in {
                "fetch_one",
                "fetch_all",
                "execute",
            }:
                continue

            owner = func.value
            is_db_call = (
                isinstance(owner, ast.Name)
                and owner.id == "db"
            ) or (
                isinstance(owner, ast.Attribute)
                and owner.attr == "db"
            )
            if is_db_call:
                offenders.append(
                    f"{path.name}:{getattr(node, 'lineno', '?')}"
                )

    assert not offenders, (
        "Managers still perform direct database persistence: "
        f"{offenders}"
    )
'''
    text = text[:start] + replacement + text[end:]

    if '"runtimeRepository.py",' not in text:
        marker = '        "reviewRepository.py",\n'
        if marker in text:
            text = text.replace(
                marker,
                marker + '        "runtimeRepository.py",\n',
                1,
            )

    if text != original:
        backup(BOUNDARY_TEST)
        BOUNDARY_TEST.write_text(text, encoding="utf-8")
        print(f"Updated {BOUNDARY_TEST}")


def main() -> int:
    required = [
        DATA_PROVIDER,
        STORY_REPO,
        STORY_MANAGER,
        BOUNDARY_TEST,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print(
            "Missing expected Phase 3 files:\n- "
            + "\n- ".join(missing),
            file=sys.stderr,
        )
        return 2

    patch_data_provider()
    patch_story_repository()
    patch_story_manager()
    patch_boundary_test()
    print("Phase 3 closure patch applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
