
from __future__ import annotations

from pathlib import Path
import shutil
import sys

DATA_PROVIDER = Path("backend/app/data/dataProvider.py")
TEST_CONSISTENCY = Path("backend/tests/test_consistency.py")
TEST_MULTIPLAYER = Path("backend/tests/test_multiplayer_api.py")
TEST_SCHEDULER = Path("backend/tests/test_scheduler.py")


def backup(path: Path) -> None:
    target = path.with_suffix(path.suffix + ".phase3-final-backup")
    if not target.exists():
        shutil.copy2(path, target)


def patch_data_provider() -> None:
    text = DATA_PROVIDER.read_text(encoding="utf-8")
    original = text

    additions = [
        ("AuthRepository", "authRepository"),
        ("LifecycleRepository", "lifecycleRepository"),
    ]
    for class_name, module_name in additions:
        line = f"from app.data.{module_name} import {class_name}\n"
        if line not in text:
            marker = "from app.data.worldRepository import WorldRepository\n"
            if marker not in text:
                marker = "from app.data.workflowRepository import WorkflowRepository\n"
            if marker not in text:
                raise RuntimeError("Could not find DataProvider import marker")
            text = text.replace(marker, marker + line, 1)

    if "self.auth = AuthRepository(db)" not in text:
        marker = "        self.world = WorldRepository(db)\n"
        if marker not in text:
            marker = "        self.workflows = WorkflowRepository(db)\n"
        if marker not in text:
            raise RuntimeError("Could not find DataProvider repository marker")
        text = text.replace(
            marker,
            marker
            + "        self.auth = AuthRepository(db)\n"
            + "        self.lifecycle = LifecycleRepository(db)\n",
            1,
        )

    if text != original:
        backup(DATA_PROVIDER)
        DATA_PROVIDER.write_text(text, encoding="utf-8")
        print(f"Updated {DATA_PROVIDER}")


def patch_consistency() -> None:
    text = TEST_CONSISTENCY.read_text(encoding="utf-8")
    original = text

    import_line = "from app.data.dataProvider import DataProvider\n"
    if import_line not in text:
        marker = "from app.database import Database, new_id, utc_now\n"
        if marker in text:
            text = text.replace(marker, marker + import_line, 1)

    old = (
        '    db, project, _, _ = setup(tmp_path); now = utc_now(); '
        'monkeypatch.setattr(app_main, "db", db)\n'
    )
    new = (
        '    db, project, _, _ = setup(tmp_path); now = utc_now(); '
        'monkeypatch.setattr(app_main, "db", db)\n'
        '    monkeypatch.setattr(app_main, "data", DataProvider(db))\n'
    )
    if old in text:
        text = text.replace(old, new, 1)

    if text != original:
        backup(TEST_CONSISTENCY)
        TEST_CONSISTENCY.write_text(text, encoding="utf-8")
        print(f"Updated {TEST_CONSISTENCY}")


def patch_multiplayer() -> None:
    text = TEST_MULTIPLAYER.read_text(encoding="utf-8")
    original = text

    if "from app.data.dataProvider import DataProvider\n" not in text:
        marker = "from app.database import Database, new_id, utc_now\n"
        text = text.replace(
            marker,
            marker
            + "from app.data.dataProvider import DataProvider\n"
            + "from app.services.routeDataService import RouteDataService\n",
            1,
        )

    old = '''    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "auth", auth)
'''
    new = '''    monkeypatch.setattr(main, "db", db)
    data = DataProvider(db)
    monkeypatch.setattr(main, "data", data)
    monkeypatch.setattr(main, "route_data", RouteDataService(data))
    monkeypatch.setattr(main, "auth", auth)
'''
    if old in text:
        text = text.replace(old, new, 1)

    if text != original:
        backup(TEST_MULTIPLAYER)
        TEST_MULTIPLAYER.write_text(text, encoding="utf-8")
        print(f"Updated {TEST_MULTIPLAYER}")


def patch_scheduler_tests() -> None:
    text = TEST_SCHEDULER.read_text(encoding="utf-8")
    original = text

    old_import = (
        "from app.services.scheduler import GenerationScheduler, "
        "_looks_like_token_truncation, _planning_json_error\n"
    )
    new_import = (
        "from app.services.scheduler import GenerationScheduler\n"
        "from app.handlers.planningJobHandler import "
        "PlanningJobHandler, _looks_like_token_truncation, "
        "_planning_json_error\n"
        "from app.services.job_handlers import JobExecutionContext\n"
    )
    if old_import in text:
        text = text.replace(old_import, new_import, 1)
    elif "from app.handlers.planningJobHandler import PlanningJobHandler" not in text:
        marker = "from app.services.scheduler import GenerationScheduler\n"
        if marker in text:
            text = text.replace(marker, marker + new_import.split(marker)[-1], 1)

    old_empty = '''    job = db.create_job(project["id"], "planning", {"action": "test"})
    with pytest.raises(Exception, match="cache-free retry"):
        await scheduler._generate_planning_json_raw(
            job, llama, [{"role": "user", "content": "Return JSON"}], 8192,
            asyncio.Event(), "Test stage", None,
        )
    assert llama.cache_flags == [True, False]
'''
    new_empty = '''    job = db.create_job(project["id"], "planning", {"action": "test"})
    handler = scheduler.handlers["planning"]
    assert isinstance(handler, PlanningJobHandler)

    async def set_state(*_args):
        return None

    async def enqueue(_job_id):
        return None

    context = JobExecutionContext(
        db=db,
        events=scheduler.events,
        ai=scheduler.ai,
        job=job,
        cancel_event=asyncio.Event(),
        set_runtime_state=set_state,
        enqueue=enqueue,
    )
    handler._start_metrics(context)
    with pytest.raises(Exception, match="cache-free retry"):
        await handler._generate_planning_json_raw(
            context,
            llama,
            [{"role": "user", "content": "Return JSON"}],
            8192,
            "Test stage",
            None,
        )
    assert llama.cache_flags == [True, False]
'''
    if old_empty in text:
        text = text.replace(old_empty, new_empty, 1)

    text = text.replace(
        "async def test_stopping_stream_keeps_only_complete_sentences(",
        "async def test_stopping_stream_preserves_all_streamed_prose(",
        1,
    )
    text = text.replace(
        '    assert assistant and assistant["content"] == '
        '"The first sentence is complete."\n',
        '''    assert assistant and assistant["content"] == (
        "The first sentence is complete. The unfinished sentence"
    )
''',
        1,
    )

    old_cutoff = '''def test_sentence_cutoff_discards_incomplete_tail() -> None:
    assert GenerationScheduler._complete_sentences("One. Two unfinished") == "One."
    assert GenerationScheduler._complete_sentences("No completed sentence") == ""


'''
    if old_cutoff in text:
        text = text.replace(old_cutoff, "", 1)

    if text != original:
        backup(TEST_SCHEDULER)
        TEST_SCHEDULER.write_text(text, encoding="utf-8")
        print(f"Updated {TEST_SCHEDULER}")


def main() -> int:
    required = [
        DATA_PROVIDER,
        TEST_CONSISTENCY,
        TEST_MULTIPLAYER,
        TEST_SCHEDULER,
    ]
    if not all(path.is_file() for path in required):
        print(
            "Run this script from the StoryStudio repo root after applying "
            "the earlier Phase 3 slices.",
            file=sys.stderr,
        )
        return 2

    patch_data_provider()
    patch_consistency()
    patch_multiplayer()
    patch_scheduler_tests()
    print("Phase 3 final cleanup patch applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
