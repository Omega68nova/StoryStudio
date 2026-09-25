from __future__ import annotations

import json
from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import new_id, utc_now


class WorldRepository(BaseRepository):
    """Storage-only boundary for WorldEngine.

    WorldEngine remains responsible for normalization, previews, branch
    visibility, validation, event semantics, and transaction composition.
    """

    # ------------------------------------------------------------------
    # Typed rule/tool read models
    # ------------------------------------------------------------------

    def stat_summaries(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetch_all(
            "SELECT stat_key,label,default_value,minimum,maximum FROM stat_definitions WHERE project_id=?", (project_id,)
        )
        for row in rows:
            row["compatible_owner_kinds"] = [item["owner_kind"] for item in self.db.fetch_all(
                "SELECT owner_kind FROM stat_definition_owner_kinds WHERE project_id=? AND stat_key=? ORDER BY owner_kind", (project_id, row["stat_key"])
            )]
        return rows

    def ability_summaries(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT ability_key,name,description,ability_kind,target_type FROM ability_definitions WHERE project_id=?",
            (project_id,),
        )

    # ------------------------------------------------------------------
    # Projection reconstruction/cache
    # ------------------------------------------------------------------

    def cached_projection(self, cache_key: str) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT projection_json FROM world_projection_cache "
            "WHERE cache_key=?",
            (cache_key,),
        )
        if not row:
            return None
        return json.loads(row["projection_json"])

    def store_projection(
        self,
        *,
        cache_key: str,
        project_id: str,
        head_node_id: str | None,
        projection: dict[str, Any],
    ) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO world_projection_cache"
            "(cache_key,project_id,head_node_id,projection_json,created_at) "
            "VALUES(?,?,?,?,?)",
            (
                cache_key,
                project_id,
                head_node_id,
                json.dumps(projection),
                utc_now(),
            ),
        )

    def invalidate_projection_cache(self, project_id: str) -> None:
        self.db.execute(
            "DELETE FROM world_projection_cache WHERE project_id=?",
            (project_id,),
        )

    def committed_transactions(
        self,
        project_id: str,
    ) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM world_transactions "
            "WHERE project_id=? AND status='committed' "
            "AND id NOT IN "
            "(SELECT transaction_id FROM inactive_world_transactions) "
            "ORDER BY branch_sequence,created_at",
            (project_id,),
        )

    def transaction_events(
        self,
        transaction_id: str,
    ) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM world_events "
            "WHERE transaction_id=? ORDER BY ordinal",
            (transaction_id,),
        )

    def transaction(
        self,
        transaction_id: str | None,
    ) -> dict[str, Any] | None:
        if not transaction_id:
            return None
        return self.db.fetch_one(
            "SELECT * FROM world_transactions WHERE id=?",
            (transaction_id,),
        )

    # ------------------------------------------------------------------
    # World commit dependencies
    # ------------------------------------------------------------------

    def resolved_minigame(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT game_key,game_version,invocation_json,result_json "
            "FROM minigame_sessions WHERE id=?",
            (session_id,),
        )
        if not row:
            return None
        result = dict(row)
        result["invocation"] = json.loads(result.pop("invocation_json") or "{}")
        result["result"] = (
            json.loads(result.pop("result_json"))
            if result.get("result_json")
            else None
        )
        return result

    # ------------------------------------------------------------------
    # Atomic commit persistence
    # ------------------------------------------------------------------

    def persist_commit(
        self,
        *,
        project_id: str,
        story_node_id: str | None,
        parent_node_id: str | None,
        branch_sequence: int,
        elapsed_minutes: int,
        display_time: str | None,
        provenance: str,
        summary: str,
        transaction_id: str,
        event_rows: list[
            tuple[str, str | None, str, dict[str, Any], int]
        ],
        new_entities: list[dict[str, Any]],
        affected_entities: list[
            tuple[dict[str, Any], dict[str, Any]]
        ],
        assistant: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Persist a fully composed WorldEngine commit atomically.

        `affected_entities` contains `(entity, lore_card)` tuples. This method
        does not derive cards or event semantics.
        """
        now = utc_now()

        with self.db._lock, self.db.connect() as connection:
            # Inline-created entities must exist before assistant encounter/NPC
            # records can reference them.
            for entity in new_entities:
                connection.execute(
                    "INSERT INTO world_entities"
                    "(id,project_id,kind,canonical_name,aliases_json,tags_json,"
                    "created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        entity["id"],
                        project_id,
                        entity["kind"],
                        entity["name"],
                        json.dumps(entity.get("aliases", [])),
                        json.dumps(entity.get("tags", [])),
                        now,
                    ),
                )

            if assistant:
                connection.execute(
                    "INSERT INTO story_nodes"
                    "(id,project_id,parent_id,role,content,status,created_at,"
                    "pov_character_id,narration_mode) "
                    "VALUES(?,?,?,'assistant',?,?,?,?,?)",
                    (
                        assistant["id"],
                        project_id,
                        parent_node_id,
                        assistant["content"],
                        assistant["status"],
                        now,
                        assistant["pov_character_id"],
                        assistant["narration_mode"],
                    ),
                )

                for intervention in assistant.get("interventions", []):
                    connection.execute(
                        "INSERT INTO npc_interventions"
                        "(id,story_node_id,npc_id,dialogue,attempted_action,"
                        "cited_fact_ids_json,ability_key,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (
                            new_id(),
                            assistant["id"],
                            intervention["npc_id"],
                            intervention.get("dialogue", ""),
                            intervention.get("attempted_action", ""),
                            json.dumps(
                                intervention.get("cited_fact_ids", [])
                            ),
                            intervention.get("ability_key"),
                            now,
                        ),
                    )

                for appearance in assistant.get("appearances", []):
                    connection.execute(
                        "INSERT INTO scene_appearances"
                        "(id,story_node_id,entity_id,outfit_id,encounter_kind,"
                        "created_at) VALUES(?,?,?,?,?,?)",
                        (
                            new_id(),
                            assistant["id"],
                            appearance["entity_id"],
                            appearance.get("outfit_id"),
                            appearance["encounter_kind"],
                            now,
                        ),
                    )

            connection.execute(
                "INSERT INTO world_transactions"
                "(id,project_id,story_node_id,parent_node_id,branch_sequence,"
                "elapsed_minutes,display_time,provenance,status,summary,"
                "created_at) "
                "VALUES(?,?,?,?,?,?,?,?, 'committed',?,?)",
                (
                    transaction_id,
                    project_id,
                    story_node_id,
                    parent_node_id,
                    branch_sequence,
                    elapsed_minutes,
                    display_time,
                    provenance,
                    summary,
                    now,
                ),
            )

            for (
                event_id,
                entity_id,
                event_type,
                payload,
                ordinal,
            ) in event_rows:
                connection.execute(
                    "INSERT INTO world_events"
                    "(id,transaction_id,entity_id,event_type,ordinal,"
                    "payload_json,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        event_id,
                        transaction_id,
                        entity_id,
                        event_type,
                        ordinal,
                        json.dumps(payload),
                        now,
                    ),
                )

                spatial_kind = {
                    "world.root_set": "root",
                    "map.anchor_upserted": "anchor",
                    "map.barrier_upserted": "barrier",
                    "map.connection_upserted": "connection",
                    "map.encounter_upserted": "encounter",
                    "travel.itinerary_set": "itinerary",
                }.get(event_type)
                spatial_id = payload.get("id")
                if event_type == "world.root_set":
                    spatial_id = project_id
                elif event_type == "map.discovery_set":
                    spatial_kind = {
                        "map_anchors": "anchor",
                        "map_barriers": "barrier",
                        "travel_connections": "connection",
                        "encounter_rules": "encounter",
                    }.get(payload.get("collection"))
                    spatial_id = payload.get("id")
                elif event_type == "map.object_removed":
                    spatial_kind = {"map_anchors": "anchor", "map_barriers": "barrier", "travel_connections": "connection", "encounter_rules": "encounter"}.get(payload.get("collection"))
                    spatial_id = payload.get("id")
                if spatial_kind and spatial_id:
                    connection.execute(
                        "INSERT OR IGNORE INTO spatial_objects"
                        "(id,project_id,object_kind,created_at) VALUES(?,?,?,?)",
                        (spatial_id, project_id, spatial_kind, now),
                    )
                    revision_id = new_id()
                    connection.execute(
                        "INSERT INTO spatial_object_revisions"
                        "(id,project_id,object_kind,object_id,transaction_id,event_ordinal,payload_json,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (revision_id, project_id, spatial_kind, spatial_id, transaction_id, ordinal, json.dumps(payload), now),
                    )
                    geometry = payload.get("geometry") or {}
                    for position, point in enumerate(geometry.get("points") or []):
                        connection.execute(
                            "INSERT INTO map_geometry_vertices"
                            "(revision_id,geometry_role,position,x,y) VALUES(?,?,?,?,?)",
                            (revision_id, "primary", position, point["x"], point["y"]),
                        )

                if event_type == "weather.proposed":
                    connection.execute(
                        "INSERT OR IGNORE INTO weather_proposals"
                        "(id,project_id,name,description,tags_json,"
                        "image_tags_json,transitions_json,source_story_node_id,"
                        "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            payload["proposal_id"],
                            project_id,
                            payload["name"],
                            payload.get("description", ""),
                            json.dumps(payload.get("tags", [])),
                            json.dumps(payload.get("image_tags", [])),
                            json.dumps(payload.get("transition_ids", [])),
                            story_node_id,
                            now,
                            now,
                        ),
                    )

            for entity, card in affected_entities:
                connection.execute(
                    "UPDATE world_entities "
                    "SET canonical_name=?,aliases_json=?,tags_json=? "
                    "WHERE id=?",
                    (
                        entity["name"],
                        json.dumps(entity.get("aliases", [])),
                        json.dumps(entity.get("tags", [])),
                        entity["id"],
                    ),
                )

                version_id = new_id()
                connection.execute(
                    "INSERT INTO lore_card_versions"
                    "(id,entity_id,transaction_id,state_json,compact_text,"
                    "visual_description,image_tags_json,search_text,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        version_id,
                        entity["id"],
                        transaction_id,
                        json.dumps(entity["state"]),
                        card["compact_text"],
                        card["visual_description"],
                        json.dumps(card["image_tags"]),
                        card["search_text"],
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO lore_card_search"
                    "(entity_id,project_id,version_id,search_text) "
                    "VALUES(?,?,?,?)",
                    (
                        entity["id"],
                        project_id,
                        version_id,
                        card["search_text"],
                    ),
                )

            if story_node_id:
                connection.execute(
                    "UPDATE projects "
                    "SET active_node_id=?,updated_at=? WHERE id=?",
                    (story_node_id, now, project_id),
                )
                for session_id in (
                    assistant or {}
                ).get("minigame_session_ids", []):
                    connection.execute(
                        "UPDATE minigame_sessions "
                        "SET status='committed',story_node_id=?,"
                        "committed_at=?,updated_at=? "
                        "WHERE id=? AND status IN ('resolved','committed')",
                        (
                            story_node_id,
                            now,
                            now,
                            session_id,
                        ),
                    )
            else:
                connection.execute(
                    "UPDATE projects SET updated_at=? WHERE id=?",
                    (now, project_id),
                )

            connection.execute(
                "DELETE FROM world_projection_cache WHERE project_id=?",
                (project_id,),
            )

        node = (
            self.db.fetch_one(
                "SELECT * FROM story_nodes WHERE id=?",
                (story_node_id,),
            )
            if story_node_id
            else {}
        )
        transaction = self.transaction(transaction_id) or {}
        return node or {}, transaction
