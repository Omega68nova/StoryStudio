from __future__ import annotations

from pathlib import Path
import shutil
import sys


WORLD = Path("backend/app/services/world.py")
DATA_PROVIDER = Path("backend/app/data/dataProvider.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly one match, found {count}. "
            "No changes were written."
        )
    return text.replace(old, new, 1)


def replace_between(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
    label: str,
) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(
            f"{label}: start marker not found. No changes were written."
        )
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(
            f"{label}: end marker not found. No changes were written."
        )
    return text[:start] + replacement + text[end:]


def patch_data_provider() -> None:
    original = DATA_PROVIDER.read_text(encoding="utf-8")
    updated = original

    if "from app.data.worldRepository import WorldRepository\n" not in updated:
        # Add beside WorkflowRepository if possible.
        marker = "from app.data.workflowRepository import WorkflowRepository\n"
        if marker not in updated:
            raise RuntimeError(
                "DataProvider import marker not found. No changes were written."
            )
        updated = updated.replace(
            marker,
            marker + "from app.data.worldRepository import WorldRepository\n",
            1,
        )

    if "self.world = WorldRepository(db)" not in updated:
        marker = "        self.workflows = WorkflowRepository(db)\n"
        if marker not in updated:
            raise RuntimeError(
                "DataProvider repository marker not found. "
                "No changes were written."
            )
        updated = updated.replace(
            marker,
            marker + "        self.world = WorldRepository(db)\n",
            1,
        )

    if updated != original:
        backup = DATA_PROVIDER.with_suffix(
            DATA_PROVIDER.suffix + ".phase4-backup"
        )
        if not backup.exists():
            shutil.copy2(DATA_PROVIDER, backup)
        DATA_PROVIDER.write_text(updated, encoding="utf-8")
        print(f"Updated {DATA_PROVIDER}")


def patch_world() -> None:
    original = WORLD.read_text(encoding="utf-8")
    updated = original

    if "from app.data.dataProvider import DataProvider\n" not in updated:
        updated = replace_once(
            updated,
            "from app.database import Database, new_id, utc_now\n",
            "from app.database import Database, new_id, utc_now\n"
            "from app.data.dataProvider import DataProvider\n",
            "WorldEngine DataProvider import",
        )

    updated = replace_once(
        updated,
        """class WorldEngine:
    def __init__(self, db: Database) -> None:
        self.db = db
""",
        """class WorldEngine:
    def __init__(
        self,
        db: Database,
        *,
        data_provider: DataProvider | None = None,
    ) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.repo = self.data.world
""",
        "WorldEngine constructor",
    )

    # Projection cache read.
    updated = replace_once(
        updated,
        """        if use_cache:
            cached = self.db.fetch_one("SELECT projection_json FROM world_projection_cache WHERE cache_key = ?", (cache_key,))
            if cached:
                return json.loads(cached["projection_json"])
""",
        """        if use_cache:
            cached = self.repo.cached_projection(cache_key)
            if cached:
                return cached
""",
        "projection cache read",
    )

    # Transaction/event reconstruction.
    updated = replace_once(
        updated,
        """        transactions = self.db.fetch_all(
            "SELECT * FROM world_transactions WHERE project_id = ? AND status = 'committed' "
            "AND id NOT IN (SELECT transaction_id FROM inactive_world_transactions) ORDER BY branch_sequence, created_at",
            (project_id,),
        )
""",
        """        transactions = self.repo.committed_transactions(project_id)
""",
        "world transaction read",
    )

    updated = replace_once(
        updated,
        """            events = self.db.fetch_all(
                "SELECT * FROM world_events WHERE transaction_id = ? ORDER BY ordinal", (transaction["id"],)
            )
""",
        """            events = self.repo.transaction_events(transaction["id"])
""",
        "world event read",
    )

    updated = replace_once(
        updated,
        """        self.db.execute(
            "INSERT OR REPLACE INTO world_projection_cache(cache_key, project_id, head_node_id, projection_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (cache_key, project_id, head_node_id, json.dumps(projection), utc_now()),
        )
""",
        """        self.repo.store_projection(
            cache_key=cache_key,
            project_id=project_id,
            head_node_id=head_node_id,
            projection=projection,
        )
""",
        "projection cache write",
    )

    # Resolved minigame event dependency.
    updated = replace_once(
        updated,
        """            minigame = self.db.fetch_one(
                "SELECT game_key,game_version,invocation_json,result_json FROM minigame_sessions WHERE id=?",
                (minigame_session_id,),
            )
            if not minigame or not minigame.get("result_json"):
                raise WorldValidationError("Resolved minigame result is missing")
            event_rows.append((new_id(), None, "minigame.completed", {
                "session_id": minigame_session_id, "game_key": minigame["game_key"],
                "game_version": minigame["game_version"], "invocation": json.loads(minigame["invocation_json"]),
                "result": json.loads(minigame["result_json"]),
            }, ordinal))
""",
        """            minigame = self.repo.resolved_minigame(minigame_session_id)
            if not minigame or minigame.get("result") is None:
                raise WorldValidationError("Resolved minigame result is missing")
            event_rows.append((new_id(), None, "minigame.completed", {
                "session_id": minigame_session_id,
                "game_key": minigame["game_key"],
                "game_version": minigame["game_version"],
                "invocation": minigame["invocation"],
                "result": minigame["result"],
            }, ordinal))
""",
        "resolved minigame lookup",
    )

    commit_replacement = """        transaction_id = new_id()
        branch_sequence = len(self.db.story_path(parent_node_id)) + (
            1 if story_node_id else 0
        )
        elapsed = final["elapsed_minutes"] - base["elapsed_minutes"]

        affected_entities: list[
            tuple[dict[str, Any], dict[str, Any]]
        ] = []
        for entity_id in affected:
            entity = final["entities"].get(entity_id)
            if entity:
                affected_entities.append(
                    (entity, make_lore_card(entity, final))
                )

        return self.repo.persist_commit(
            project_id=project_id,
            story_node_id=story_node_id,
            parent_node_id=parent_node_id,
            branch_sequence=branch_sequence,
            elapsed_minutes=elapsed,
            display_time=final.get("display_time"),
            provenance=provenance,
            summary=summary,
            transaction_id=transaction_id,
            event_rows=event_rows,
            new_entities=list(new_entities.values()),
            affected_entities=affected_entities,
            assistant=assistant,
        )
"""

    updated = replace_between(
        updated,
        "        transaction_id, now = new_id(), utc_now()\n",
        "\n    def effective_stats(",
        commit_replacement,
        "atomic world commit storage",
    )

    if updated != original:
        backup = WORLD.with_suffix(WORLD.suffix + ".phase4-backup")
        if not backup.exists():
            shutil.copy2(WORLD, backup)
        WORLD.write_text(updated, encoding="utf-8")
        print(f"Updated {WORLD}")


def main() -> int:
    if not WORLD.is_file() or not DATA_PROVIDER.is_file():
        print(
            "Run this script from the StoryStudio repository root and make "
            "sure Slice 3 is already installed.",
            file=sys.stderr,
        )
        return 2

    patch_data_provider()
    patch_world()
    print("Phase 4 WorldRepository integration applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
