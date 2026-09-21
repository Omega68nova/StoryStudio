from __future__ import annotations

import asyncio
import json
from typing import Any

from app.database import new_id, utc_now
from app.managers.environmentManager import EnvironmentManager
from app.managers.musicManager import MusicManager
from app.services.memory import provider_for
from app.services.world import NormalizedMutation, WorldEngine


class StoryFinalizer:
    """Persists story results and triggers story-owned side effects."""

    def __init__(
        self,
        db: Any,
        events: Any,
        world: WorldEngine,
        enqueue: Any,
        environment: EnvironmentManager | None = None,
        music: MusicManager | None = None,
    ) -> None:
        self.db = db
        self.events = events
        self.world = world
        self.enqueue = enqueue
        self.environment = (
            environment
            or EnvironmentManager(
                db,
                world,
                events=events,
            )
        )
        self.music = (
            music
            or self.environment.music
        )

    @staticmethod
    def serialize_mutations(
        mutations: list[NormalizedMutation],
    ) -> list[dict[str, Any]]:
        return [
            {
                "tool": mutation.tool,
                "arguments": mutation.arguments,
                "major": mutation.major,
                "reason": mutation.reason,
            }
            for mutation in mutations
        ]

    @staticmethod
    def split_review_mutations(
        mutations: list[NormalizedMutation],
    ) -> tuple[
        list[NormalizedMutation],
        list[NormalizedMutation],
    ]:
        reviewed = [
            mutation
            for mutation in mutations
            if mutation.major
        ]
        blocked_ids = {
            str(
                mutation.arguments.get(
                    "entity_id"
                )
            )
            for mutation in reviewed
            if (
                mutation.tool == "createEntity"
                and mutation.arguments.get(
                    "entity_id"
                )
            )
        }

        changed = True
        while changed:
            changed = False
            for mutation in mutations:
                if mutation in reviewed:
                    continue
                encoded = json.dumps(
                    mutation.arguments
                )
                if any(
                    entity_id in encoded
                    for entity_id in blocked_ids
                ):
                    reviewed.append(mutation)
                    if (
                        mutation.tool == "createEntity"
                        and mutation.arguments.get(
                            "entity_id"
                        )
                    ):
                        blocked_ids.add(
                            str(
                                mutation.arguments[
                                    "entity_id"
                                ]
                            )
                        )
                    changed = True

        return (
            [
                mutation
                for mutation in mutations
                if mutation not in reviewed
            ],
            reviewed,
        )

    def encounter_appearances(
        self,
        project_id: str,
        head_node_id: str,
        prose: str,
        mutations: list[NormalizedMutation],
    ) -> list[dict[str, Any]]:
        projection = self.world.preview(
            project_id,
            head_node_id,
            mutations,
        )
        ancestry = {
            node["id"]
            for node in self.db.story_path(
                head_node_id
            )
        }
        prior = {
            row["entity_id"]
            for row in self.db.fetch_all(
                "SELECT a.entity_id,a.story_node_id "
                "FROM scene_appearances a "
                "JOIN story_nodes n "
                "ON n.id=a.story_node_id "
                "WHERE n.project_id=?",
                (project_id,),
            )
            if row["story_node_id"] in ancestry
        }

        result: list[dict[str, Any]] = []
        folded = prose.casefold()

        for entity in projection["entities"].values():
            if (
                entity["id"] in prior
                or entity["kind"]
                not in {
                    "character",
                    "location",
                }
                or entity["name"].casefold()
                not in folded
            ):
                continue

            outfit_id = (
                entity.get("state", {}).get(
                    "active_outfit_id"
                )
                if entity["kind"] == "character"
                else None
            )
            result.append(
                {
                    "entity_id": entity["id"],
                    "entity_name": entity["name"],
                    "outfit_id": outfit_id,
                    "encounter_kind": (
                        "character"
                        if entity["kind"]
                        == "character"
                        else "location"
                    ),
                }
            )

        return result

    def ensure_encounter_assets(
        self,
        project_id: str,
        story_node_id: str,
        appearances: list[dict[str, Any]],
    ) -> None:
        now = utc_now()

        for appearance in appearances:
            kinds = (
                ["portrait", "full_body"]
                if appearance[
                    "encounter_kind"
                ]
                == "character"
                else ["location"]
            )

            for kind in kinds:
                existing = self.db.fetch_one(
                    "SELECT id FROM entity_media_assets "
                    "WHERE entity_id=? AND kind=? "
                    "AND COALESCE(outfit_id,'')="
                    "COALESCE(?, '') AND featured=1",
                    (
                        appearance["entity_id"],
                        kind,
                        appearance.get("outfit_id"),
                    ),
                )
                if existing:
                    continue

                entity = self.world.entity_card(
                    project_id,
                    appearance["entity_id"],
                    story_node_id,
                )
                prompt = (
                    entity["card"].get(
                        "visual_description"
                    )
                    or entity["card"].get(
                        "compact_text",
                        "",
                    )
                )
                self.db.execute(
                    "INSERT INTO entity_media_assets"
                    "(id,project_id,entity_id,outfit_id,kind,"
                    "source,status,prompt,source_story_node_id,"
                    "created_at,updated_at) "
                    "VALUES(?,?,?,?,?,'suggested','suggested',?,?,?,?)",
                    (
                        new_id(),
                        project_id,
                        appearance["entity_id"],
                        appearance.get("outfit_id"),
                        kind,
                        prompt,
                        story_node_id,
                        now,
                        now,
                    ),
                )

    def create_review(
        self,
        job: dict[str, Any],
        phase: str,
        mutations: list[NormalizedMutation],
        story_node_id: str | None,
    ) -> dict[str, Any]:
        review_id = new_id()
        now = utc_now()
        serialized = self.serialize_mutations(
            mutations
        )
        reasons = "; ".join(
            mutation.reason
            or mutation.tool
            for mutation in mutations
            if mutation.major
        )

        self.db.execute(
            "INSERT INTO pending_reviews"
            "(id,job_id,story_node_id,phase,status,"
            "mutations_json,reason,created_at,updated_at) "
            "VALUES(?,?,?,?, 'pending',?,?,?,?)",
            (
                review_id,
                job["id"],
                story_node_id,
                phase,
                json.dumps(serialized),
                reasons,
                now,
                now,
            ),
        )
        return {
            "id": review_id,
            "job_id": job["id"],
            "story_node_id": story_node_id,
            "phase": phase,
            "status": "pending",
            "mutations": serialized,
            "reason": reasons,
        }

    def create_suggestion(
        self,
        assistant: dict[str, Any],
        supplied: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if supplied:
            title = supplied["title"]
            prompt = supplied["prompt"]
            negative = supplied.get(
                "negative_prompt",
                "",
            )
        else:
            projection = self.world.projection(
                assistant["project_id"],
                assistant["id"],
            )
            references: list[str] = []
            prose = assistant["content"].casefold()

            for entity in projection["entities"].values():
                if (
                    entity["name"].casefold()
                    not in prose
                ):
                    continue
                card = self.world.entity_card(
                    assistant["project_id"],
                    entity["id"],
                    assistant["id"],
                )["card"]
                visual = card.get(
                    "visual_description",
                    "",
                )
                if visual:
                    references.append(visual)

            title = "Illustration idea"
            prompt = ". ".join(
                [
                    *references[:6],
                    assistant["content"][-1600:],
                ]
            ).strip()
            negative = ""

        suggestion_id = new_id()
        now = utc_now()

        self.db.execute(
            "INSERT INTO image_suggestions"
            "(id,story_node_id,title,prompt,"
            "negative_prompt,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,'suggested',?,?)",
            (
                suggestion_id,
                assistant["id"],
                title,
                prompt,
                negative,
                now,
                now,
            ),
        )

        return (
            self.db.fetch_one(
                "SELECT * FROM image_suggestions "
                "WHERE id=?",
                (suggestion_id,),
            )
            or {}
        )

    async def queue_environment_backgrounds(
        self,
        project_id: str,
        story_node_id: str,
        mutations: list[NormalizedMutation],
    ) -> None:
        settings = self.db.fetch_one(
            "SELECT enabled,auto_generate_backgrounds,"
            "background_workflow_id "
            "FROM project_environment_settings "
            "WHERE project_id=?",
            (project_id,),
        )
        if (
            not settings
            or not settings["enabled"]
            or not settings[
                "auto_generate_backgrounds"
            ]
            or not settings[
                "background_workflow_id"
            ]
        ):
            return

        projection = self.world.projection(
            project_id
        )
        scene = environment.scene(
            project_id,
            projection,
        )

        targets: list[
            tuple[
                str,
                str | None,
                str | None,
            ]
        ] = []

        for mutation in mutations:
            if (
                mutation.tool == "createEntity"
                and mutation.arguments.get(
                    "kind"
                )
                == "location"
            ):
                targets.append(
                    (
                        mutation.arguments[
                            "entity_id"
                        ],
                        None,
                        None,
                    )
                )

        if scene.get("location"):
            targets.append(
                (
                    scene["location"]["id"],
                    (
                        scene.get("weather")
                        or {}
                    ).get("id"),
                    (
                        scene.get("time_phase")
                        or {}
                    ).get("id"),
                )
            )

        for (
            location_id,
            weather_id,
            phase_id,
        ) in dict.fromkeys(targets):
            existing = self.db.fetch_one(
                "SELECT b.id FROM location_backgrounds b "
                "WHERE b.project_id=? AND b.location_id=? "
                "AND b.weather_id IS ? "
                "AND b.time_phase_id IS ?",
                (
                    project_id,
                    location_id,
                    weather_id,
                    phase_id,
                ),
            )
            if existing:
                continue

            location = projection[
                "entities"
            ].get(location_id)
            if not location:
                continue

            prompt = (
                self.environment.composed_background_prompt(
                    project_id,
                    location,
                    weather_id,
                    phase_id,
                )
            )
            asset_id = new_id()
            background_id = new_id()
            now = utc_now()

            self.db.execute(
                "INSERT INTO entity_media_assets"
                "(id,project_id,entity_id,kind,source,status,"
                "prompt,featured,source_story_node_id,"
                "created_at,updated_at) "
                "VALUES(?,?,?,'location','suggested','queued',"
                "?,0,?,?,?)",
                (
                    asset_id,
                    project_id,
                    location_id,
                    prompt,
                    story_node_id,
                    now,
                    now,
                ),
            )
            self.db.execute(
                "INSERT INTO location_backgrounds"
                "(id,project_id,location_id,media_asset_id,"
                "weather_id,time_phase_id,position,created_at) "
                "VALUES(?,?,?,?,?,?,0,?)",
                (
                    background_id,
                    project_id,
                    location_id,
                    asset_id,
                    weather_id,
                    phase_id,
                    now,
                ),
            )

            image_job = self.db.create_job(
                project_id,
                "image",
                {
                    "media_asset_id": asset_id,
                    "preset_id": settings[
                        "background_workflow_id"
                    ],
                    "values": {
                        "prompt": prompt,
                    },
                    "environment_background_id": (
                        background_id
                    ),
                },
            )
            await self.enqueue(
                image_job["id"]
            )

    async def sync_theme_cue(
        self,
        project_id: str,
        mutations: list[NormalizedMutation],
    ) -> None:
        """Compatibility shim; MusicManager owns theme/playback synchronization."""
        await self.music.apply_story_mutations(
            project_id,
            mutations,
        )

    async def commit_stopped_story(
        self,
        *,
        context: Any,
        head_node_id: str | None,
        content: str,
        pov_character_id: str | None,
        narration_mode: str,
        minigame_session_ids: list[str],
        mutations: list[NormalizedMutation],
    ) -> None:
        await context.state(
            "finalizing_story"
        )
        context.db.update_job_progress(
            context.job_id,
            "finalizing_story",
            "Saving completed sentences",
        )

        assistant, transaction = (
            self.world.commit_story_turn(
                context.project_id,
                head_node_id,
                content,
                mutations,
                pov_character_id=(
                    pov_character_id
                ),
                narration_mode=narration_mode,
                interventions=[],
                appearances=[],
                minigame_session_ids=(
                    minigame_session_ids
                ),
            )
        )

        result = {
            "story_node_id": assistant["id"],
            "suggestion_id": None,
            "minigame_session_id": (
                minigame_session_ids[-1]
                if minigame_session_ids
                else None
            ),
            "minigame_session_ids": (
                minigame_session_ids
            ),
            "stopped": True,
        }
        self.db.update_job(
            context.job_id,
            "completed",
            result=result,
        )
        await self.events.publish(
            "story",
            {
                "job_id": context.job_id,
                "node": assistant,
                "stopped": True,
            },
        )
        await self.events.publish(
            "world_head",
            {
                "project_id": context.project_id,
                "node_id": assistant["id"],
            },
        )
        await self.events.publish(
            "memory_changed",
            {
                "job_id": context.job_id,
                "transaction_id": transaction[
                    "id"
                ],
                "changes": [],
            },
        )
        await self.events.publish(
            "job",
            {
                "job_id": context.job_id,
                "status": "completed",
                "result": result,
            },
        )

    async def sync_memory(
        self,
        project_id: str,
    ) -> None:
        provider = provider_for(
            "cognee",
            self.db,
            self.world,
        )
        result = await provider.index_project(
            project_id
        )
        if result.get("status") == "failed":
            await self.events.publish(
                "tool",
                {
                    "phase": "memory",
                    "status": "fallback",
                    **result,
                },
            )
