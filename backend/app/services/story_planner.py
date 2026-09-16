from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Awaitable, Callable

from app.services.context import SYSTEM_PROMPT
from app.services.runtimes import LlamaClient
from app.services.world import READ_TOOLS, WorldEngine, WorldValidationError


ToolEvent = Callable[[dict[str, Any]], Awaitable[None]]


async def cancelable(awaitable: Awaitable[Any], cancel_event: asyncio.Event | None) -> Any:
    if cancel_event is None:
        return await awaitable
    task = asyncio.ensure_future(awaitable)
    cancelled = asyncio.create_task(cancel_event.wait())
    done, _ = await asyncio.wait({task, cancelled}, return_when=asyncio.FIRST_COMPLETED)
    if cancelled in done and cancel_event.is_set():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        raise asyncio.CancelledError
    cancelled.cancel()
    return await task


def normalize_native_tool_calls(tool_calls: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reads, writes = [], []
    for call in tool_calls:
        function = call.get("function") or {}
        name = str(function.get("name", ""))
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        normalized = {"tool": name, "arguments": arguments, "tool_call_id": call.get("id", "")}
        if name in READ_TOOLS:
            reads.append(normalized)
        elif name in {"createEntity", "updateEntity", "moveCharacter", "setRelationship", "revealKnowledge", "advanceTime", "updatePlotBeat", "adjustStat", "useAbility", "selectTheme", "setSceneEnvironment", "proposeWeather"}:
            writes.append(normalized)
    return reads, writes


def native_tools(allowed_names: set[str] | None = None) -> list[dict[str, Any]]:
    definitions: dict[str, str] = {
        "searchEntities": "Search visible entities by text and optional kinds.",
        "getEntity": "Read one visible entity by exact entity_id.",
        "getScene": "Read current time, POV, location, and present entities.",
        "getNearbyLocations": "List sibling locations, optionally in a cardinal direction.",
        "findRoute": "Find a traversable route between two location IDs.",
        "getKnownFacts": "Search facts visible to the current perspective.",
        "getActivePlotBeats": "Search active plot guidance visible to the narrator.",
        "getStats": "Read current stats for one character.",
        "getAbilities": "Read project ability definitions.",
        "searchLocations": "Search the complete ordinary location catalog in bounded pages.",
        "getLocationMap": "Read one compact hierarchical map layer.",
        "getSceneEnvironment": "Read the current compact scene environment.",
        "createEntity": "Stage creation of a canonical typed world entity.",
        "updateEntity": "Stage a merge patch to an existing entity.",
        "moveCharacter": "Stage movement to a location over a valid route.",
        "setRelationship": "Stage a relationship or route between two entities.",
        "revealKnowledge": "Stage revealing a fact to characters or factions.",
        "advanceTime": "Stage non-negative elapsed story time.",
        "updatePlotBeat": "Stage a plot beat status change.",
        "adjustStat": "Stage a bounded stat correction.",
        "useAbility": "Stage a known ability after validating costs and targets.",
        "selectTheme": "Choose one project-enabled music theme when AI music is enabled.",
        "setSceneEnvironment": "Set the focused player, short lowercase -ing action, and optionally valid next weather.",
        "proposeWeather": "Propose a reusable weather definition for administrator review.",
    }
    return [
        {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "additionalProperties": True}}}
        for name, description in definitions.items() if allowed_names is None or name in allowed_names
    ]


def parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorldValidationError(f"The storyteller returned invalid structured output: {exc}") from exc
    if not isinstance(parsed, dict):
        raise WorldValidationError("The storyteller's structured output was not an object")
    return parsed


def mutation_schema() -> dict[str, Any]:
    return {
        "tool": "one of createEntity, updateEntity, moveCharacter, setRelationship, revealKnowledge, advanceTime, updatePlotBeat, adjustStat, useAbility, selectTheme, setSceneEnvironment, proposeWeather",
        "arguments": {"tool_specific": "arguments"},
    }


class StoryPlanner:
    def __init__(self, world: WorldEngine) -> None:
        self.world = world

    async def plan(
        self,
        llama: LlamaClient,
        project_id: str,
        head_node_id: str | None,
        user_text: str,
        pov_character_id: str | None,
        narration_mode: str,
        context_tokens: int,
        tool_event: ToolEvent,
        feedback: str = "",
        semantic_ids: list[str] | None = None,
        cancel_event: asyncio.Event | None = None,
        max_rounds: int = 2,
        max_tokens: int = 320,
        time_budget_seconds: float | None = None,
    ) -> dict[str, Any]:
        package = self.world.context_package(
            project_id, head_node_id, user_text, pov_character_id, narration_mode,
            min(3000, max(800, context_tokens // 3)), semantic_ids,
        )
        compact_entities = [
            {"id": entity["id"], "kind": entity["kind"], "name": entity["name"],
             "card": entity["card"]["compact_text"], "reason": entity.get("reason")}
            for entity in package["entities"]
        ]
        rules = {
            "stats": self.world.db.fetch_all("SELECT stat_key, label, scope, default_value, minimum, maximum FROM stat_definitions WHERE project_id = ?", (project_id,)),
            "abilities": self.world.db.fetch_all("SELECT ability_key, name, description, target_type, costs_json, effects_json FROM ability_definitions WHERE project_id = ?", (project_id,)),
        }
        music = self.world.db.fetch_one("SELECT mode FROM project_music_settings WHERE project_id = ?", (project_id,)) or {"mode": "disabled"}
        music["themes"] = self.world.db.fetch_all("SELECT t.id, t.name, t.description FROM music_themes t JOIN project_music_themes p ON p.theme_id = t.id WHERE p.project_id = ?", (project_id,)) if music["mode"] == "ai_managed" else []
        allowed_tools = set(READ_TOOLS) | {"createEntity", "updateEntity", "moveCharacter", "setRelationship", "revealKnowledge", "advanceTime", "updatePlotBeat", "adjustStat", "useAbility", "selectTheme"}
        environment_settings = self.world.db.fetch_one("SELECT enabled,ai_create_locations,ai_propose_weather FROM project_environment_settings WHERE project_id=?", (project_id,)) or {"enabled": 0, "ai_create_locations": 0, "ai_propose_weather": 0}
        if environment_settings["enabled"]:
            allowed_tools.add("setSceneEnvironment")
        else:
            allowed_tools -= {"searchLocations", "getLocationMap", "getSceneEnvironment"}
        if environment_settings["enabled"] and environment_settings["ai_propose_weather"]:
            allowed_tools.add("proposeWeather")
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are the deterministic scene planner for a storytelling engine. Do not write prose. "
                    "Return JSON with scene_intent, queries, and mutations arrays. Queries use only the listed read tools; "
                    "mutations use only the listed write tools. Use exact UUIDs returned in context/tools. "
                    "Prefer no mutation over guessing. New entities use createEntity and may be canonical. "
                    "Never choose an irreversible action or core personality change for a player-controlled character."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "request": user_text,
                    "scene": {**package, "entities": compact_entities},
                    "game_rules": rules,
                    "music": music,
                    "environment_policy": {"enabled": bool(environment_settings["enabled"]), "may_create_locations": bool(environment_settings.get("ai_create_locations", 0)), "may_propose_weather": bool(environment_settings["ai_propose_weather"])},
                    "read_tools": sorted(READ_TOOLS & allowed_tools),
                    "write_shape": mutation_schema(),
                    "feedback": feedback,
                    "response_shape": {"scene_intent": "string", "queries": [{"tool": "searchEntities", "arguments": {}}],
                                       "mutations": [mutation_schema()]},
                }),
            },
        ]
        result: dict[str, Any] = {}
        native_mutations: list[dict[str, Any]] = []
        requests_made = 0
        native_available = hasattr(llama, "tool_step")
        deadline = time.monotonic() + time_budget_seconds if time_budget_seconds else None
        for round_number in range(max_rounds):
            if requests_made >= max_rounds:
                break
            native_message: dict[str, Any] | None = None
            native_failed = not native_available
            if native_available:
                try:
                    requests_made += 1
                    await tool_event({"phase": "model_request", "round": round_number + 1, "kind": "native"})
                    try:
                        request = llama.tool_step(messages, native_tools(allowed_tools), max_tokens=max_tokens)
                    except TypeError:
                        request = llama.tool_step(messages, native_tools(allowed_tools))
                    remaining = max(.01, deadline - time.monotonic()) if deadline else None
                    if remaining is not None:
                        async with asyncio.timeout(remaining):
                            native_message = await cancelable(request, cancel_event)
                    else:
                        native_message = await cancelable(request, cancel_event)
                except TimeoutError:
                    break
                except Exception:
                    native_failed = True
                    native_available = False
                    native_message = None
            if native_message and native_message.get("tool_calls"):
                queries, writes = normalize_native_tool_calls(native_message["tool_calls"])
                native_mutations.extend({"tool": item["tool"], "arguments": item["arguments"]} for item in writes)
                result = {"scene_intent": native_message.get("content") or user_text, "queries": queries,
                          "mutations": native_mutations}
            elif native_message and native_message.get("content", "").strip():
                # llama.cpp commonly returns schema JSON as ordinary content even
                # when native tools are enabled. It is already the planner result.
                result = parse_json_object(native_message["content"])
                queries = result.get("queries") or []
            elif native_failed and requests_made < max_rounds:
                # Compatibility fallback for servers that genuinely reject the
                # native tools request, not a second request after valid content.
                try:
                    request = llama.complete(messages, json_mode=True, max_tokens=max_tokens)
                except TypeError:
                    request = llama.complete(messages, json_mode=True)
                requests_made += 1
                await tool_event({"phase": "model_request", "round": round_number + 1, "kind": "json_fallback"})
                remaining = max(.01, deadline - time.monotonic()) if deadline else None
                try:
                    if remaining is not None:
                        async with asyncio.timeout(remaining):
                            raw = await cancelable(request, cancel_event)
                    else:
                        raw = await cancelable(request, cancel_event)
                except TimeoutError:
                    break
                result = parse_json_object(raw)
                queries = result.get("queries") or []
            else:
                result = {"scene_intent": user_text, "queries": [], "mutations": native_mutations}
                queries = []
            if not queries:
                break
            outputs = []
            for query in queries[:8]:
                tool = str(query.get("tool", ""))
                arguments = query.get("arguments") or {}
                try:
                    output = self.world.execute_read_tool(
                        project_id, head_node_id, pov_character_id, narration_mode, tool, arguments
                    )
                    outputs.append({"tool": tool, "arguments": arguments, "result": output})
                    await tool_event({"phase": "read", "round": round_number + 1, "tool": tool, "status": "ok"})
                except WorldValidationError as exc:
                    outputs.append({"tool": tool, "arguments": arguments, "error": str(exc)})
                    await tool_event({"phase": "read", "round": round_number + 1, "tool": tool, "status": "rejected"})
            messages.append({"role": "assistant", "content": json.dumps(result)})
            messages.append({
                "role": "user",
                "content": json.dumps({"tool_results": outputs, "instruction": "Now return the final plan, or another bounded query round."}),
            })
        result.setdefault("scene_intent", user_text)
        result.setdefault("mutations", native_mutations)
        if result.get("queries"):
            result["queries"] = []
        return result

    async def reconcile(
        self,
        llama: LlamaClient,
        prose: str,
        planned_mutations: list[dict[str, Any]],
        cancel_event: asyncio.Event | None = None,
    ) -> list[dict[str, Any]]:
        messages = [
            {
                "role": "system",
                "content": (
                    "Compare the prose with its planned state changes. Return JSON with a mutations array containing only "
                    "clear state changes expressed in the prose but absent from the plan. Do not infer hidden facts. "
                    "Use the supplied write-tool shape and exact IDs. Return an empty array when nothing is missing."
                ),
            },
            {"role": "user", "content": json.dumps({"prose": prose, "planned_mutations": planned_mutations,
                                                       "response_shape": {"mutations": [mutation_schema()]}})},
        ]
        try:
            return list(parse_json_object(await cancelable(llama.complete(messages, json_mode=True), cancel_event)).get("mutations") or [])
        except WorldValidationError:
            return []


def narrative_messages(
    context_package: dict[str, Any],
    path: list[dict[str, Any]],
    summary: dict[str, Any] | None,
    scene_intent: str,
    staged_mutations: list[dict[str, Any]],
    interventions: list[dict[str, Any]] | None = None,
    transient_instruction: str = "",
) -> list[dict[str, str]]:
    context = {
        "world_time": context_package["world_time"],
        "perspective": {"pov_character_id": context_package["pov_character_id"], "mode": context_package["narration_mode"]},
        "lore_cards": [entity["card"]["compact_text"] for entity in context_package["entities"]],
        "scene_intent": scene_intent,
        "approved_state_changes": staged_mutations,
        "npc_attempts_to_resolve": interventions or [],
    }
    if context_package.get("environment"):
        context["environment"] = context_package["environment"]
    system = SYSTEM_PROMPT + (
        "\nUse only the supplied canonical context. Approved state changes must occur naturally in this scene. "
        "Do not expose narrator-only information in limited POV. Return story prose plus only the hidden inline envelopes described below.\n\n# Scene context\n" + json.dumps(context)
    )
    if summary:
        system += "\n\n# Earlier branch summary\n" + summary["content"]
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    through = summary["through_node_id"] if summary else None
    skipping = bool(through)
    for node in path:
        if skipping:
            if node["id"] == through:
                skipping = False
            continue
        if node["status"] in {"complete", "awaiting_resolution"}:
            content = node["content"]
            if node["role"] == "user":
                action = node.get("action_kind") or "do"
                prefixes = {
                    "say": "The player says as their POV character:",
                    "do": "The player attempts this action:",
                    "guide": "Direction for the storyteller's next passage:",
                    "continue": "Continue the story naturally:",
                }
                content = f"{prefixes.get(action, 'Player input:')}\n{content}"
            messages.append({"role": node["role"], "content": content})
    if transient_instruction:
        messages.append({"role": "user", "content": transient_instruction})
    return messages
