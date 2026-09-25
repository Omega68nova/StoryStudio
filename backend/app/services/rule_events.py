from __future__ import annotations

import copy
from typing import Any


Event = tuple[str, str | None, dict[str, Any]]


class RuleEventProjector:
    """Projection and mutation-event contract for canonical rules.

    WorldEngine owns branch replay and transaction ordering. Rule-specific
    event shapes live here so the coordinator does not also own active-effect,
    inventory-cost, and ability-expansion behavior.
    """

    @staticmethod
    def apply(
        projection: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
        entity_id: str | None,
    ) -> bool:
        entities = projection.setdefault("entities", {})
        relations = projection.setdefault("relations", {})
        if event_type == "stat.changed":
            container = entities.get(payload.get("entity_id") or entity_id) or relations.get(
                payload.get("relation_id")
            )
            if container is not None:
                container.setdefault("stats", {})[payload["stat_key"]] = payload["value"]
            return True
        if event_type == "effect.instance_applied":
            active = projection.setdefault("active_effects", {})
            for replaced in payload.get("replace_instance_ids", []):
                active.pop(replaced, None)
            active[payload["id"]] = copy.deepcopy(payload)
            return True
        if event_type == "effect.instance_updated":
            instance = projection.setdefault("active_effects", {}).get(payload["id"])
            if instance:
                instance.update(copy.deepcopy(payload))
            return True
        if event_type == "effect.instance_removed":
            projection.setdefault("active_effects", {}).pop(payload["id"], None)
            return True
        if event_type == "story.action_committed":
            projection["world_action_count"] = int(projection.get("world_action_count", 0)) + 1
            actor_id = payload.get("actor_id") or entity_id
            if actor_id:
                counts = projection.setdefault("target_action_counts", {})
                counts[str(actor_id)] = int(counts.get(str(actor_id), 0)) + 1
            return True
        if event_type == "inventory.adjusted":
            owner_id = str(payload.get("character_id") or payload.get("entity_id") or entity_id or "")
            if owner_id not in entities:
                return True
            state = entities[owner_id].setdefault("state", {})
            inventory = copy.deepcopy(state.get("inventory", []))
            item_id = str(payload["item_id"])
            entry = next((item for item in inventory if str(item.get("item_id")) == item_id), None)
            if entry:
                entry["quantity"] = payload["quantity"]
            elif payload["quantity"] > 0:
                inventory.append({"item_id": item_id, "quantity": payload["quantity"]})
            state["inventory"] = [item for item in inventory if int(item.get("quantity", 0)) > 0]
            if int(payload["quantity"]) <= 0:
                state["equipment"] = [
                    equipped for equipped in state.get("equipment", []) if str(equipped) != item_id
                ]
            return True
        return False

    @staticmethod
    def mutation_events(tool: str, arguments: dict[str, Any]) -> list[Event] | None:
        if tool == "adjustStat":
            return [("stat.changed", arguments.get("entity_id"), arguments)]
        if tool == "useAbility":
            rows: list[Event] = [("ability.used", arguments["actor_id"], arguments)]
            rows.extend(("stat.changed", cost.get("entity_id"), cost) for cost in arguments.get("costs", []))
            rows.extend(
                ("inventory.adjusted", change.get("entity_id"), change)
                for change in arguments.get("inventory_changes", [])
            )
            for effect in arguments.get("effects", []):
                payload = {**effect, "ability_key": arguments["ability_key"]}
                event_type = str(payload.pop("event_type", "stat.changed"))
                if event_type == "entity.created":
                    entity = {
                        key: payload[key]
                        for key in ("entity_id", "kind", "name", "aliases", "tags", "state")
                        if key in payload
                    }
                    entity["id"] = entity.pop("entity_id")
                    payload = {"entity": entity, "ability_key": arguments["ability_key"]}
                rows.append((event_type, effect.get("entity_id"), payload))
            rows.extend(RuleEventProjector._scheduled(arguments))
            rows.append(("story.action_committed", arguments["actor_id"], {"actor_id": arguments["actor_id"]}))
            return rows
        if tool == "applyEffect":
            event_type = str(arguments.get("event_type", "stat.changed"))
            return [(event_type, arguments.get("entity_id"), {key: value for key, value in arguments.items() if key != "event_type"})]
        if tool == "removeEffect":
            return [("effect.instance_removed", None, arguments)]
        if tool == "cloneEffectInstance":
            return [("effect.instance_applied", None, arguments)]
        if tool == "storyAction":
            return [
                ("story.action_committed", arguments.get("actor_id"), {"actor_id": arguments.get("actor_id")}),
                *RuleEventProjector._scheduled(arguments),
            ]
        return None

    @staticmethod
    def _scheduled(arguments: dict[str, Any]) -> list[Event]:
        return [
            (
                str(item["event_type"]),
                item.get("entity_id"),
                {key: value for key, value in item.items() if key != "event_type"},
            )
            for item in arguments.get("scheduled_effects", [])
        ]
