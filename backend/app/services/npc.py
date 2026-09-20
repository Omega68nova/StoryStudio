from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from app.services.story_planner import cancelable, parse_json_object
from app.services.world import NormalizedMutation, WorldEngine, WorldValidationError, make_lore_card


class NpcDirector:
    def __init__(self, world: WorldEngine) -> None:
        self.world = world

    def eligible(self, project_id: str, head_node_id: str, pov_character_id: str | None, turn_key: str) -> list[dict[str, Any]]:
        projection = self.world.projection(project_id, head_node_id)
        pov = projection["entities"].get(pov_character_id or "", {})
        location_id = pov.get("state", {}).get("current_location_id")
        thresholds = {"low": 25, "normal": 60, "high": 100}
        candidates = []
        for entity in projection["entities"].values():
            state = entity.get("state", {})
            if entity["kind"] != "character" or entity["id"] == pov_character_id or state.get("player_controlled"):
                continue
            if not state.get("autonomy_enabled", False) or state.get("alive", True) is False or state.get("conscious", True) is False:
                continue
            if location_id and state.get("current_location_id") != location_id:
                continue
            roll = int(hashlib.sha256(f"{turn_key}:{entity['id']}".encode()).hexdigest()[:8], 16) % 100
            if roll < thresholds.get(state.get("intervention_frequency", "normal"), 60):
                candidates.append(entity)
        return sorted(candidates, key=lambda item: item["name"].casefold())[:3]

    async def generate(self, llama: Any, project_id: str, head_node_id: str, pov_character_id: str | None, turn_key: str, scene_intent: str, cancel_event=None) -> tuple[list[dict[str, Any]], list[NormalizedMutation]]:
        projection = self.world.projection(project_id, head_node_id)
        candidates = self.eligible(project_id, head_node_id, pov_character_id, turn_key)
        if not candidates:
            return [], []
        packets = []
        visible_fact_ids: dict[str, set[str]] = {}
        for npc in candidates:
            facts = self.world.search(project_id, "", head_node_id=head_node_id, pov_character_id=npc["id"], narration_mode="third_limited", kinds=["fact"], limit=30)
            visible_fact_ids[npc["id"]] = {fact["id"] for fact in facts}
            private_knowledge = [str(item) for item in npc.get("state", {}).get("character_secrets", []) if str(item).strip()] if isinstance(npc.get("state", {}).get("character_secrets"), list) else []
            packets.append({"npc_id": npc["id"], "name": npc["name"], "sheet": make_lore_card(npc, projection)["compact_text"],
                            "private_knowledge": private_knowledge[:20],
                            "known_facts": [{"id": fact["id"], "summary": fact["card"]["compact_text"]} for fact in facts]})
        messages = [{"role": "system", "content": "Generate optional NPC reactions, not narration. Return JSON only. Each intervention must cite every canonical fact it relies on. private_knowledge belongs only to that NPC and may guide its behavior without being stated aloud. NPCs may only use abilities they know."},
                    {"role": "user", "content": json.dumps({"scene_intent": scene_intent, "npcs": packets, "shape": {"interventions": [{"npc_id": "uuid", "dialogue": "", "attempted_action": "", "cited_fact_ids": [], "ability": {"ability_key": "", "target_id": "uuid"}}]}})}]
        try:
            raw = parse_json_object(await cancelable(llama.complete(messages, json_mode=True), cancel_event)).get("interventions", [])
        except asyncio.CancelledError:
            raise
        except Exception:
            return [], []
        by_id = {npc["id"]: npc for npc in candidates}
        accepted, mutations = [], []
        for item in raw[:3]:
            npc_id = str(item.get("npc_id", "")); cited = set(item.get("cited_fact_ids") or [])
            if npc_id not in by_id or not cited.issubset(visible_fact_ids[npc_id]):
                continue
            action = str(item.get("attempted_action", "")).strip()
            dialogue = str(item.get("dialogue", "")).strip()
            if not action and not dialogue:
                continue
            ability = item.get("ability") or None
            if ability and ability.get("ability_key"):
                try:
                    mutations.extend(self.world.normalize_mutations(project_id, head_node_id, [{"tool": "useAbility", "arguments": {"actor_id": npc_id, **ability}}], provenance="npc"))
                except WorldValidationError:
                    ability = None
            accepted.append({"npc_id": npc_id, "npc_name": by_id[npc_id]["name"], "dialogue": dialogue[:4000],
                             "attempted_action": action[:4000], "cited_fact_ids": sorted(cited), "ability_key": ability.get("ability_key") if ability else None})
        return accepted, mutations
