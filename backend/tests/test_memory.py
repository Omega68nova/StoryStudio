from pathlib import Path
from types import SimpleNamespace

import pytest

from app.database import Database
from app.services.memory import BuiltinMemoryProvider, CogneeMemoryProvider, provider_for
from app.services.world import WorldEngine


def world_with_entity(path: Path):
    db = Database(path); db.initialize(); project = db.create_project("Memory"); world = WorldEngine(db)
    mutation = world.normalize_mutations(project["id"], None, [{"tool": "createEntity", "arguments": {"kind": "character", "name": "Mara", "state": {"appearance": "silver hair"}}}], provenance="author")
    world.commit_root(project["id"], mutation, provenance="author", summary="Mara")
    return db, project, world, mutation[0].arguments["entity_id"]


@pytest.mark.asyncio
async def test_cognee_is_local_cpu_and_filters_stale_ids(tmp_path: Path, monkeypatch) -> None:
    db, project, world, entity_id = world_with_entity(tmp_path)
    configured, remembered = {}, []

    class Config:
        @staticmethod
        def set(key, value): configured[key] = value

    async def remember(payloads, **kwargs): remembered.extend(payloads)
    async def search(**kwargs): return [{"text": f"candidate {entity_id} and stale-id"}]
    fake = SimpleNamespace(config=Config(), remember=remember, search=search, SearchType=SimpleNamespace(CHUNKS="chunks"))
    monkeypatch.setattr("app.services.memory.importlib.import_module", lambda _: fake)
    provider = CogneeMemoryProvider(db, world)
    result = await provider.index_project(project["id"])
    assert result["status"] == "ready" and remembered
    assert configured["embedding_provider"] == "fastembed"
    assert configured["graph_database_provider"] == "kuzu"
    assert configured["db_provider"] == "sqlite"
    assert await provider.candidates(project["id"], "silver") == [entity_id]


@pytest.mark.asyncio
async def test_missing_cognee_is_actionable_and_builtin_remains_available(tmp_path: Path, monkeypatch) -> None:
    db, project, world, entity_id = world_with_entity(tmp_path)
    def missing(_): raise ImportError("missing")
    monkeypatch.setattr("app.services.memory.importlib.import_module", missing)
    with pytest.raises(RuntimeError, match="requirements-memory"):
        await CogneeMemoryProvider(db, world).candidates(project["id"], "Mara")
    builtin = provider_for("builtin", db, world)
    assert isinstance(builtin, BuiltinMemoryProvider)
    assert await builtin.candidates(project["id"], "Mara") == [entity_id]
