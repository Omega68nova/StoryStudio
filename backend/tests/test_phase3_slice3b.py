from __future__ import annotations

import json

from app.data.planningRepository import PlanningRepository


class FakeCursor:
    def __init__(self, rowcount: int = 1):
        self.rowcount = rowcount


class FakeConnection:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, parameters=()):
        self.db.executed.append((sql, tuple(parameters)))
        return FakeCursor(1)


class FakeContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_):
        return False


class FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeDb:
    def __init__(self):
        self.executed = []
        self._lock = FakeLock()
        self.rows = {}

    def connect(self):
        return FakeContext(FakeConnection(self))

    def execute(self, sql, parameters=()):
        self.executed.append((sql, tuple(parameters)))

    def fetch_one(self, sql, parameters=()):
        if "active_job_id FROM planning_stages" in sql:
            return {"active_job_id": "job-1"}
        if "COUNT(*) n FROM planning_stage_revisions" in sql:
            return {"n": 3}
        if "FROM planning_image_plans WHERE id=" in sql:
            return {
                "id": "plan-1",
                "session_id": "session-1",
                "status": "ready",
                "prompt": "old",
            }
        return None

    def fetch_all(self, sql, parameters=()):
        if "planning_image_plans" in sql and "status='ready'" in sql:
            return [{"id": "plan-1"}, {"id": "plan-2"}]
        if "planning_image_plans" in sql:
            return [{"id": "plan-1"}, {"id": "plan-2"}]
        return []


def test_queue_stage_generation_is_atomic_control_write() -> None:
    db = FakeDb()
    repo = PlanningRepository(db)
    revision_id = repo.queue_stage_generation(
        stage_id="stage-1",
        job_id="job-1",
        prompt="Generate cast",
    )
    assert revision_id
    assert len(db.executed) == 2
    assert "planning_stage_revisions" in db.executed[0][0]
    assert "active_job_id" in db.executed[1][0]


def test_finish_generation_updates_stage_and_revision() -> None:
    db = FakeDb()
    repo = PlanningRepository(db)
    repo.finish_generation(
        session_id="session-1",
        stage_number=3,
        job_id="job-1",
        status="cancelled",
    )
    assert len(db.executed) == 2
    assert "planning_stages" in db.executed[0][0]
    assert "planning_stage_revisions" in db.executed[1][0]


def test_active_job_id() -> None:
    repo = PlanningRepository(FakeDb())
    assert repo.active_job_id("stage-1") == "job-1"


def test_image_plan_selection_helpers() -> None:
    repo = PlanningRepository(FakeDb())
    assert repo.image_plan_ids("session-1") == {"plan-1", "plan-2"}
    assert repo.ready_image_plan_ids("session-1") == ["plan-1", "plan-2"]


def test_clear_revisions_returns_removed_count() -> None:
    db = FakeDb()
    repo = PlanningRepository(db)
    assert repo.clear_revisions("session-1") == 3
    assert any("DELETE FROM planning_stage_revisions" in sql for sql, _ in db.executed)
