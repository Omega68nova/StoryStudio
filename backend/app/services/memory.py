from __future__ import annotations

import importlib
import json
from typing import Any, Protocol

from app.database import Database, utc_now
from app.services.world import WorldEngine


class MemoryProvider(Protocol):
    async def index_project(self, project_id: str) -> dict[str, Any]: ...
    async def candidates(self, project_id: str, query: str, limit: int = 12) -> list[str]: ...


class BuiltinMemoryProvider:
    def __init__(self, world: WorldEngine) -> None:
        self.world = world

    async def index_project(self, project_id: str) -> dict[str, Any]:
        return {"provider": "builtin", "status": "ready"}

    async def candidates(self, project_id: str, query: str, limit: int = 12) -> list[str]:
        return [item["id"] for item in self.world.search(project_id, query, narration_mode="third_omniscient", limit=limit)]


class CogneeMemoryProvider:
    """Optional candidate generator. Returned IDs are always revalidated by WorldEngine."""

    def __init__(self, db: Database, world: WorldEngine) -> None:
        self.db, self.world = db, world

    def _module(self):
        try:
            cognee = importlib.import_module("cognee")
        except ImportError as exc:
            raise RuntimeError("Cognee is not installed; install backend/requirements-memory.txt or use built-in memory") from exc
        root = self.db.data_dir / "cognee"
        # Keep the optional index local and CPU-only. Cognee is retrieval assistance, not StoryStudio's LLM.
        cognee.config.set("embedding_provider", "fastembed")
        cognee.config.set("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
        cognee.config.set("embedding_dimensions", 384)
        cognee.config.set("db_provider", "sqlite")
        cognee.config.set("vector_db_provider", "lancedb")
        cognee.config.set("graph_database_provider", "kuzu")
        cognee.config.set("data_root_directory", str(root / "data"))
        cognee.config.set("system_root_directory", str(root / "system"))
        return cognee

    async def index_project(self, project_id: str) -> dict[str, Any]:
        cognee = self._module()
        projection = self.world.projection(project_id)
        dataset = f"storystudio_{project_id.replace('-', '_')}"
        payloads = []
        for entity in projection["entities"].values():
            card = self.world.entity_card(project_id, entity["id"])["card"]
            payloads.append(json.dumps({"storystudio_entity_id": entity["id"], "text": card["compact_text"]}))
        event_rows = self.db.fetch_all(
            "SELECT e.entity_id, e.event_type, e.payload_json FROM world_events e "
            "JOIN world_transactions t ON t.id = e.transaction_id "
            "WHERE t.project_id = ? AND t.status = 'committed' AND e.entity_id IS NOT NULL ORDER BY t.created_at, e.ordinal",
            (project_id,),
        )
        for event in event_rows:
            if event["entity_id"] in projection["entities"]:
                payloads.append(json.dumps({"storystudio_entity_id": event["entity_id"], "event": event["event_type"], "payload": json.loads(event["payload_json"])}))
        try:
            if payloads:
                await cognee.remember(payloads, dataset_name=dataset)
            for entity in projection["entities"].values():
                version = self.db.fetch_one(
                    "SELECT id FROM lore_card_versions WHERE entity_id = ? ORDER BY created_at DESC LIMIT 1", (entity["id"],)
                )
                if version:
                    self.db.execute(
                        "INSERT OR REPLACE INTO memory_sync_state(provider, project_id, entity_id, version_id, status, error, updated_at) "
                        "VALUES ('cognee', ?, ?, ?, 'ready', NULL, ?)",
                        (project_id, entity["id"], version["id"], utc_now()),
                    )
            return {"provider": "cognee", "status": "ready", "indexed": len(payloads)}
        except Exception as exc:
            return {"provider": "cognee", "status": "failed", "error": str(exc), "indexed": 0}

    async def candidates(self, project_id: str, query: str, limit: int = 12) -> list[str]:
        cognee = self._module()
        dataset = f"storystudio_{project_id.replace('-', '_')}"
        try:
            search_type = getattr(cognee.SearchType, "CHUNKS", None)
            results = await cognee.search(query_text=query, query_type=search_type, datasets=[dataset], top_k=limit)
        except Exception:
            return []
        valid_ids = set(self.world.projection(project_id)["entities"])
        found: list[str] = []
        for result in results or []:
            text = json.dumps(result, default=str)
            for entity_id in valid_ids:
                if entity_id in text and entity_id not in found:
                    found.append(entity_id)
        return found[:limit]


def provider_for(name: str, db: Database, world: WorldEngine) -> MemoryProvider:
    return CogneeMemoryProvider(db, world) if name == "cognee" else BuiltinMemoryProvider(world)
