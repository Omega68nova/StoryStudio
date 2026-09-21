from __future__ import annotations

import json

from app.data.worldRepository import WorldRepository


class FakeCursor:
    def __init__(self, rowcount: int = 1):
        self.rowcount = rowcount


class FakeConnection:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, parameters=()):
        self.db.executed.append((sql, tuple(parameters)))
        return FakeCursor()


class FakeConnectionContext:
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
        self.cache = None

    def connect(self):
        return FakeConnectionContext(FakeConnection(self))

    def execute(self, sql, parameters=()):
        self.executed.append((sql, tuple(parameters)))

    def fetch_one(self, sql, parameters=()):
        if "world_projection_cache" in sql:
            return (
                {"projection_json": json.dumps(self.cache)}
                if self.cache is not None
                else None
            )
        if "world_transactions WHERE id" in sql:
            return {
                "id": parameters[0],
                "project_id": "p1",
                "status": "committed",
            }
        if "story_nodes WHERE id" in sql:
            return {
                "id": parameters[0],
                "project_id": "p1",
                "role": "assistant",
            }
        return None

    def fetch_all(self, sql, parameters=()):
        if "FROM world_transactions" in sql:
            return [
                {
                    "id": "tx1",
                    "project_id": "p1",
                    "story_node_id": None,
                    "branch_sequence": 0,
                }
            ]
        if "FROM world_events" in sql:
            return [
                {
                    "id": "e1",
                    "transaction_id": "tx1",
                    "event_type": "time.advanced",
                    "ordinal": 0,
                    "payload_json": '{"minutes":5}',
                    "entity_id": None,
                }
            ]
        return []


def test_projection_cache_round_trip_shape() -> None:
    db = FakeDb()
    db.cache = {
        "project_id": "p1",
        "entities": {},
        "relations": {},
    }
    repo = WorldRepository(db)
    assert repo.cached_projection("p1:root") == db.cache

    repo.store_projection(
        cache_key="p1:root",
        project_id="p1",
        head_node_id=None,
        projection=db.cache,
    )
    assert any(
        "world_projection_cache" in sql
        for sql, _ in db.executed
    )


def test_world_history_reads_are_repository_owned() -> None:
    repo = WorldRepository(FakeDb())
    assert repo.committed_transactions("p1")[0]["id"] == "tx1"
    assert repo.transaction_events("tx1")[0]["event_type"] == "time.advanced"


def test_persist_commit_writes_world_bundle_and_invalidates_cache() -> None:
    db = FakeDb()
    repo = WorldRepository(db)

    node, transaction = repo.persist_commit(
        project_id="p1",
        story_node_id="n1",
        parent_node_id="parent",
        branch_sequence=2,
        elapsed_minutes=5,
        display_time=None,
        provenance="ai",
        summary="",
        transaction_id="tx-new",
        event_rows=[
            (
                "event-1",
                "entity-1",
                "entity.created",
                {
                    "entity": {
                        "id": "entity-1",
                        "kind": "character",
                        "name": "Test",
                        "aliases": [],
                        "tags": [],
                        "state": {},
                    }
                },
                0,
            )
        ],
        new_entities=[
            {
                "id": "entity-1",
                "kind": "character",
                "name": "Test",
                "aliases": [],
                "tags": [],
                "state": {},
            }
        ],
        affected_entities=[
            (
                {
                    "id": "entity-1",
                    "kind": "character",
                    "name": "Test",
                    "aliases": [],
                    "tags": [],
                    "state": {},
                },
                {
                    "compact_text": "Test",
                    "visual_description": "",
                    "image_tags": [],
                    "search_text": "Test",
                },
            )
        ],
        assistant={
            "id": "n1",
            "content": "Partial story.",
            "status": "complete",
            "pov_character_id": None,
            "narration_mode": "third_limited",
            "interventions": [],
            "appearances": [],
            "minigame_session_ids": [],
        },
    )

    statements = [sql for sql, _ in db.executed]
    assert any("INSERT INTO world_entities" in sql for sql in statements)
    assert any("INSERT INTO story_nodes" in sql for sql in statements)
    assert any("INSERT INTO world_transactions" in sql for sql in statements)
    assert any("INSERT INTO world_events" in sql for sql in statements)
    assert any("INSERT INTO lore_card_versions" in sql for sql in statements)
    assert any("DELETE FROM world_projection_cache" in sql for sql in statements)
    assert node["id"] == "n1"
    assert transaction["id"] == "tx-new"
