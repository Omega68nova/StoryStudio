from __future__ import annotations

import json
from typing import Any

from app.services.minigames import MinigameService
from app.services.npc import NpcDirector
from app.services.world import (
    NormalizedMutation,
    WorldEngine,
    WorldValidationError,
)


INLINE_TOOL_NAMES = [
    "createEntity",
    "updateEntity",
    "moveCharacter",
    "setRelationship",
    "revealKnowledge",
    "advanceTime",
    "updatePlotBeat",
    "adjustStat",
    "useAbility",
    "selectTheme",
    "npcIntervention",
    "suggestIllustration",
    "startMinigame",
    "setSceneEnvironment",
    "proposeWeather",
]


class StoryInlineActions:
    """Validates and stages hidden story-stream actions.

    This is extracted almost directly from the legacy scheduler so the story
    handler can focus on streaming/orchestration.
    """

    def __init__(
        self,
        db: Any,
        world: WorldEngine,
        npc_director: NpcDirector,
        minigames: MinigameService,
    ) -> None:
        self.db = db
        self.world = world
        self.npc_director = npc_director
        self.minigames = minigames

    def npc_packets(
        self,
        project_id: str,
        head_node_id: str | None,
        pov_character_id: str | None,
        turn_key: str,
    ) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
        candidates = self.npc_director.eligible(
            project_id,
            head_node_id,
            pov_character_id,
            turn_key,
        )
        facts_by_npc: dict[str, set[str]] = {}
        packets: list[dict[str, Any]] = []

        for npc in candidates:
            facts = self.world.search(
                project_id,
                "",
                head_node_id=head_node_id,
                pov_character_id=npc["id"],
                narration_mode="third_limited",
                kinds=["fact"],
                limit=30,
            )
            facts_by_npc[npc["id"]] = {
                fact["id"] for fact in facts
            }
            packets.append(
                {
                    "npc_id": npc["id"],
                    "name": npc["name"],
                    "personality": (
                        npc.get("state", {}).get(
                            "personality",
                            "",
                        )
                    ),
                    "appearance": (
                        npc.get("state", {}).get(
                            "appearance",
                            "",
                        )
                    ),
                    "known_fact_ids": sorted(
                        facts_by_npc[npc["id"]]
                    )[:12],
                }
            )

        return packets, facts_by_npc

    def accept(
        self,
        *,
        job: dict[str, Any],
        head_node_id: str | None,
        call: dict[str, Any],
        mutations: list[NormalizedMutation],
        major_mutations: list[NormalizedMutation],
        interventions: list[dict[str, Any]],
        npc_packets: list[dict[str, Any]],
        npc_facts: dict[str, set[str]],
        temporary_ids: dict[str, str],
        action: str,
    ) -> dict[str, Any] | None:
        name = call["name"]
        arguments = dict(call.get("arguments") or {})

        for key, value in list(arguments.items()):
            if (
                key.endswith("_id")
                and isinstance(value, str)
                and value in temporary_ids
            ):
                arguments[key] = temporary_ids[value]

        if "rnd(" in json.dumps(arguments).casefold():
            raise WorldValidationError(
                "Expressions are not allowed; provide literal values only"
            )

        if name == "startMinigame":
            existing = self.db.fetch_one(
                "SELECT id FROM minigame_sessions "
                "WHERE job_id=? AND status='awaiting_input'",
                (job["id"],),
            )
            if existing:
                raise WorldValidationError(
                    "Resolve the current minigame before starting another"
                )

            invocation = self.minigames.validate_invocation(
                job["project_id"],
                head_node_id,
                action,
                arguments,
                mutations,
            )
            return {
                "_checkpoint": True,
                "invocation": invocation,
            }

        if name == "suggestIllustration":
            prompt = str(
                arguments.get("prompt", "")
            ).strip()
            if not prompt:
                raise WorldValidationError(
                    "suggestIllustration requires a non-empty prompt"
                )
            return {
                "title": str(
                    arguments.get("title")
                    or "Illustration"
                )[:200],
                "prompt": prompt[:20_000],
                "negative_prompt": str(
                    arguments.get("negative_prompt") or ""
                )[:20_000],
            }

        if name == "npcIntervention":
            actor_id = str(
                arguments.get("npc_id")
                or arguments.get("actor_id")
                or ""
            )
            allowed = {
                packet["npc_id"]: packet
                for packet in npc_packets
            }
            cited = {
                str(value)
                for value in arguments.get(
                    "cited_fact_ids",
                    [],
                )
            }

            if actor_id not in allowed:
                raise WorldValidationError(
                    "npcIntervention actor is absent, "
                    "player-controlled, or not eligible this turn"
                )
            if not cited.issubset(
                npc_facts.get(actor_id, set())
            ):
                raise WorldValidationError(
                    "npcIntervention cites facts unavailable "
                    "to that NPC"
                )

            dialogue = str(
                arguments.get("dialogue") or ""
            ).strip()
            attempted = str(
                arguments.get("attempted_action") or ""
            ).strip()

            if not dialogue and not attempted:
                raise WorldValidationError(
                    "npcIntervention requires dialogue or an attempted action"
                )

            ability = (
                arguments.get("useAbility")
                or arguments.get("ability")
                or None
            )
            ability_key = None
            if (
                isinstance(ability, dict)
                and ability.get("ability_key")
            ):
                ability_args = {
                    "actor_id": actor_id,
                    **ability,
                }
                accepted = self.world.normalize_mutations(
                    job["project_id"],
                    head_node_id,
                    [
                        {
                            "tool": "useAbility",
                            "arguments": ability_args,
                        }
                    ],
                    provenance="npc",
                    staged=mutations,
                )
                mutations.extend(accepted)
                major_mutations.extend(
                    item
                    for item in accepted
                    if item.major
                )
                ability_key = str(
                    ability["ability_key"]
                )

            interventions.append(
                {
                    "npc_id": actor_id,
                    "npc_name": allowed[actor_id]["name"],
                    "dialogue": dialogue[:4000],
                    "attempted_action": attempted[:4000],
                    "cited_fact_ids": sorted(cited),
                    "ability_key": ability_key,
                }
            )
            return None

        if name not in INLINE_TOOL_NAMES:
            raise WorldValidationError(
                f"Unknown or read-only inline tool: {name}"
            )

        if name == "useAbility":
            actor_id = str(
                arguments.get("actor_id") or ""
            )
            actor = self.world.preview(
                job["project_id"],
                head_node_id,
                mutations,
            )["entities"].get(actor_id)

            requested = (
                job.get("payload", {}).get(
                    "requested_ability"
                )
                or {}
            )
            if (
                actor
                and actor.get("state", {}).get(
                    "player_controlled"
                )
                and (
                    requested.get("actor_id")
                    != actor_id
                    or requested.get("ability_key")
                    != arguments.get("ability_key")
                )
            ):
                raise WorldValidationError(
                    "A player-controlled character ability "
                    "requires an explicit player request"
                )

        accepted = self.world.normalize_mutations(
            job["project_id"],
            head_node_id,
            [
                {
                    "tool": name,
                    "arguments": arguments,
                }
            ],
            provenance="storyteller_inline",
            staged=mutations,
        )
        mutations.extend(accepted)
        major_mutations.extend(
            item
            for item in accepted
            if item.major
        )

        if (
            name == "createEntity"
            and arguments.get("key")
            and accepted
        ):
            temporary_ids[
                str(arguments["key"])
            ] = str(
                accepted[0].arguments["entity_id"]
            )

        return None

    @staticmethod
    def inline_error(
        call: dict[str, Any],
        exc: WorldValidationError,
    ) -> dict[str, Any]:
        return {
            "tool_name": call.get("name", ""),
            "error_code": "world_validation_failed",
            "explanation": str(exc),
            "offending_fields": sorted(
                (call.get("arguments") or {}).keys()
            ),
            "safe_correction_hints": [
                "Use exact known IDs and literal values, or omit the action."
            ],
        }

    @staticmethod
    def protocol_prompt(
        npc_packets: list[dict[str, Any]],
        eligible_games: list[dict[str, Any]] | None = None,
    ) -> str:
        compact_games: list[dict[str, Any]] = []

        for game in eligible_games or []:
            compact_games.append(
                {
                    key: value
                    for key, value in {
                        "game_key": game.get("game_key"),
                        "description": str(
                            game.get("description") or ""
                        )[:140],
                        "group": game.get("group"),
                        "recommended": bool(
                            game.get("recommended")
                        ),
                        "difficulty": game.get("difficulty"),
                        "participant_ids": [
                            item.get("id")
                            for item in list(
                                game.get("participants") or []
                            )[:3]
                        ],
                        "actor_ids": [
                            item.get("id")
                            for item in list(
                                game.get("actors") or []
                            )[:4]
                        ],
                        "timer_policy": game.get(
                            "timer_policy"
                        ),
                        "attempt_guidance": game.get(
                            "attempt_guidance"
                        ),
                        "parameter_guidance": game.get(
                            "parameter_guidance"
                        ),
                        "combat_guidance": game.get(
                            "combat_guidance"
                        ),
                    }.items()
                    if value not in (
                        None,
                        [],
                        {},
                        "",
                    )
                }
            )

        return (
            "\n\n# Hidden inline actions\n"
            "Stream the requested story immediately. When a canonical "
            "world change is explicit, insert a hidden literal JSON "
            'envelope: <ss-tool>{"name":"updateEntity",'
            '"arguments":{...}}</ss-tool>. Never show or explain these '
            "envelopes. Do not use expressions such as rnd(1,5). "
            "Allowed names: "
            + ", ".join(INLINE_TOOL_NAMES)
            + ". New entities may include a temporary key that later "
            "actions reference. NPC packets: "
            + json.dumps(npc_packets)
            + ". You may pause more than once in a turn at separate "
            "uncertain player-facing actions with startMinigame, but "
            "only one challenge may be unresolved at a time and only "
            "using this eligible catalog: "
            + json.dumps(
                compact_games,
                separators=(",", ":"),
            )
            + ". Copy IDs exactly from that catalog. actor_id is whoever "
            "performs the action; participant_id is the player-controlled "
            "character playing the challenge. Never invent IDs or outcomes. "
            "If the player explicitly requests a challenge represented by "
            "an eligible minigame, call startMinigame and do not narrate "
            "its outcome. Place startMinigame exactly where the outcome "
            "becomes uncertain and write no prose after it. Illustration "
            "prompts may reference known entities as {{Exact Name}}."
        )
