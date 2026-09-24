from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any, Callable

from app.database import new_id
from app.domain.adapters import entity_from_projection
from app.domain.operations import (
    DomainOperationError,
    EffectExecutor,
    FormulaEvaluator,
    RequirementEvaluator,
    StatAdjustmentExecutor,
    TargetResolver,
)
from app.domain.world import Character, resolve_stat_bounds


class RulesRuntimeError(ValueError):
    pass


Event = tuple[str, str | None, dict[str, Any]]


class RulesRuntime:
    """Stat, global-effect, and ability execution over a branch projection.

    This service resolves canonical rule definitions into deterministic world
    events. It does not persist transactions or reconstruct branches.
    """

    def __init__(self, data: Any, apply_event: Callable[[dict[str, Any], str, dict[str, Any], str | None], None]) -> None:
        self.data = data
        self.apply_event = apply_event

    @staticmethod
    def entity(projection: dict[str, Any], entity_id: Any, kind: str | None = None) -> dict[str, Any]:
        entity = projection.get("entities", {}).get(str(entity_id))
        if not entity: raise RulesRuntimeError(f"Unknown entity: {entity_id}")
        if kind and entity.get("kind") != kind: raise RulesRuntimeError(f"Entity '{entity.get('name')}' is not a {kind}")
        return entity

    def stat(self, project_id: str, key: str, owner_kind: str):
        definition = self.data.rules.stat(project_id, key)
        if not definition or owner_kind not in map(str, definition.compatible_owner_kinds):
            raise DomainOperationError(f"Unknown or incompatible {owner_kind} stat: {key}")
        return definition

    def effective_stats(self, project_id: str, container: dict[str, Any], owner_kind: str) -> dict[str, float]:
        definitions = {item.stat_key: item for item in self.data.rules.stats(project_id) if owner_kind in map(str, item.compatible_owner_kinds)}
        raw = {key: float(container.get("stats", {}).get(key, definition.default_value)) for key, definition in definitions.items()}
        values: dict[str, float] = {}
        for key, definition in definitions.items():
            try: bounds = resolve_stat_bounds(definition, raw, lambda candidate: definitions[candidate])
            except (KeyError, ValueError) as exc: raise RulesRuntimeError(str(exc)) from exc
            value = max(float(bounds.minimum), min(float(bounds.maximum), raw[key]))
            values[key] = int(round(value)) if definition.integer_only else value
        return values

    def adjust_stat(self, project_id: str, projection: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return StatAdjustmentExecutor().normalize(
                projection=projection, entity_id=arguments.get("entity_id"), relation_id=arguments.get("relation_id"),
                stat_key=str(arguments.get("stat_key", "")), operation=str(arguments.get("operation", "add")), amount=arguments.get("amount", 0),
                stat_lookup=lambda key, owner="character": self.stat(project_id, key, owner),
            )
        except DomainOperationError as exc: raise RulesRuntimeError(str(exc)) from exc

    def participant(self, project_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        owner_kind = "relationship" if "source_id" in raw else str(raw.get("kind") or "character")
        return {**raw, "stats": self.effective_stats(project_id, raw, owner_kind)}

    def normalize_effect(self, project_id: str, projection: dict[str, Any], definition: Any, target: Any, participants: dict[str, Any], duration_override: int | None = None, tick_override: int | None = None) -> dict[str, Any]:
        target_raw = projection["relations"].get(target.id) if target.scope == "relationship" else projection["entities"].get(target.id)
        if not target_raw: raise DomainOperationError("Effect target is unavailable")
        target_kind = "relationship" if target.scope == "relationship" else str(target_raw.get("kind"))
        stat = self.stat(project_id, definition.target_stat_key, target_kind)
        participant_values = {**participants, "target": self.participant(project_id, target_raw)}
        magnitude, inputs = FormulaEvaluator().evaluate(definition.formula, participant_values)
        duration = definition.duration if duration_override is None else duration_override
        tick = definition.tick_interval if tick_override is None else tick_override
        if not ((duration == 0 and tick == 0) or (duration > 0 and tick <= duration) or (duration == -1 and tick > 0)):
            raise DomainOperationError("Ability action has an invalid effect timing override")
        common = {"effect_key": definition.effect_key, "target_id": target.id, "target_kind": target_kind, "stat_key": definition.target_stat_key, "operation": str(definition.operation), "resolved_inputs": inputs, "resolved_magnitude": magnitude}
        if duration == 0:
            current = float(participant_values["target"]["stats"][definition.target_stat_key])
            value = EffectExecutor._bounded_value(stat, current, str(definition.operation), magnitude, values=participant_values["target"]["stats"], stat_lookup=lambda key: self.data.rules.stat(project_id, key))
            return {**common, "event_type": "stat.changed", "relation_id" if target.scope == "relationship" else "entity_id": target.id, "previous_value": current, "value": value}
        progress = int(projection.get("elapsed_minutes", 0)) if str(definition.clock) == "story_minutes" else int(projection.get("world_action_count", 0)) if str(definition.clock) == "world_actions" else int(projection.get("target_action_counts", {}).get(target.id, 0))
        matches = [item for item in projection.get("active_effects", {}).values() if item.get("effect_key") == definition.effect_key and item.get("target_id") == target.id]
        policy = str(definition.stacking_policy)
        base = {**common, "actor_id": participants["actor"].get("id"), "source_id": participants["source"].get("id"), "clock": str(definition.clock), "duration": duration, "tick_interval": tick, "evaluation_mode": str(definition.evaluation_mode), "stacking_policy": policy, "max_stacks": definition.max_stacks, "started_at": progress, "next_tick": progress + (tick or duration), "expires_at": None if duration == -1 else progress + duration}
        if matches and policy in {"refresh", "stack"}:
            previous = matches[0]
            if policy == "refresh": return {**previous, "event_type": "effect.instance_updated", "started_at": progress, "next_tick": progress + (tick or duration), "expires_at": None if duration == -1 else progress + duration}
            return {**previous, **base, "event_type": "effect.instance_updated", "stacks": min(definition.max_stacks, int(previous.get("stacks", 1)) + 1), "snapshot_inputs": inputs if str(definition.evaluation_mode) == "snapshot" else None, "snapshot_magnitude": magnitude if str(definition.evaluation_mode) == "snapshot" else None}
        return {**base, "event_type": "effect.instance_applied", "id": new_id(), "stacks": 1, "replace_instance_ids": [item["id"] for item in matches] if policy == "replace" else [], "snapshot_inputs": inputs if str(definition.evaluation_mode) == "snapshot" else None, "snapshot_magnitude": magnitude if str(definition.evaluation_mode) == "snapshot" else None}

    @staticmethod
    def normalize_action(action: Any, target: Any, actor: Character) -> dict[str, Any]:
        kind = str(action.kind); common = {"operation": kind}
        if kind == "move": return {**common, "event_type": "character.moved", "entity_id": target.id, "character_id": target.id, "destination_id": str(action.destination_id)}
        if kind == "remove": return {**common, "event_type": "relationship.removed", "relationship_id": target.id} if target.scope == "relationship" else {**common, "event_type": "entity.updated", "entity_id": target.id, "patch": {"archived": True}}
        if kind == "reveal_knowledge": return {**common, "event_type": "knowledge.revealed", "entity_id": str(action.fact_id), "fact_id": str(action.fact_id), "character_ids": [target.id], "faction_ids": []}
        if kind == "change_relationship": return {**common, "event_type": "relationship.set", "source_id": str(actor.id), "target_id": target.id, "relation": action.relation}
        if kind == "advance_time": return {**common, "event_type": "time.advanced", "minutes": int(action.minutes or 0)}
        if kind == "play_noise": return {**common, "event_type": "noise.played", "noise_id": str(action.noise_id)}
        if kind == "create": return {**common, "event_type": "entity.created", "entity_id": new_id(), "kind": action.entity_kind, "name": action.entity_name, "state": action.state, "aliases": [], "tags": []}
        raise DomainOperationError(f"Unsupported ability action: {kind}")

    def normalize_ability(self, project_id: str, projection: dict[str, Any], arguments: dict[str, Any], provenance: str) -> dict[str, Any]:
        actor_raw = self.entity(projection, arguments.get("actor_id"), "character")
        actor = entity_from_projection(actor_raw)
        if not isinstance(actor, Character): raise RulesRuntimeError("Ability actor is not a character")
        if actor.state.player_controlled and provenance not in {"player", "author"}: raise RulesRuntimeError("Player-character abilities require an explicit player request")
        ability = self.data.rules.ability(project_id, str(arguments.get("ability_key") or ""))
        if not ability or not ability.enabled: raise RulesRuntimeError("Unknown ability")
        if str(ability.ability_kind) != "active": raise RulesRuntimeError("Passive abilities cannot be used directly")
        source_raw, source_item_id = actor_raw, arguments.get("source_item_id")
        if source_item_id:
            if "item" not in map(str, ability.compatible_owner_kinds): raise RulesRuntimeError("This ability cannot be supplied by an item")
            source_raw = self.entity(projection, source_item_id, "item")
            inventory = {str(entry.get("item_id")): int(entry.get("quantity", 0)) for entry in actor_raw.get("state", {}).get("inventory", [])}
            if inventory.get(str(source_item_id), 0) <= 0 and str(source_item_id) not in set(map(str, actor_raw.get("state", {}).get("equipment", []))): raise RulesRuntimeError("The source item must be held or equipped")
        elif "character" not in map(str, ability.compatible_owner_kinds): raise RulesRuntimeError("This ability requires a source item")
        elif ability.ability_key not in actor.state.abilities and ability.name not in actor.state.abilities: raise RulesRuntimeError(f"{actor.name} does not know {ability.name}")
        lookup = lambda key, owner="character": self.stat(project_id, key, owner)
        effective = lambda character: self.effective_stats(project_id, projection["entities"].get(str(character.id), actor_raw), "character")
        targets = TargetResolver()
        try:
            phases = self.data.environment.phases(project_id, enabled_only=True); total = sum(int(item["duration_minutes"]) for item in phases)
            if total:
                offset = int(projection.get("elapsed_minutes", 0)) % total
                for phase in phases:
                    if offset < int(phase["duration_minutes"]): projection["current_time_phase_id"] = phase["id"]; break
                    offset -= int(phase["duration_minutes"])
            primary = targets.resolve_ability_target(projection, actor, ability, arguments.get("target_id"))
            RequirementEvaluator().ensure_satisfied(actor, ability, projection=projection, primary_target=primary, stat_lookup=lookup, effective_stats=effective)
            execution = EffectExecutor(targets).normalize(projection=projection, actor=actor, primary_target=primary, ability=ability, next_sequence=int(projection.get("_next_sequence", 0)), elapsed_minutes=int(projection.get("elapsed_minutes", 0)), stat_lookup=lookup, effective_stats=effective, id_factory=new_id)
            inventory_changes: list[dict[str, Any]] = []
            available_inventory = {
                str(entry.get("item_id")): int(entry.get("quantity", 0))
                for entry in actor_raw.get("state", {}).get("inventory", [])
            }
            equipped_ids = set(map(str, actor_raw.get("state", {}).get("equipment", [])))
            for cost in ability.costs:
                kind = str(cost.kind)
                if kind == "stat":
                    continue
                item_id = str(source_item_id) if kind == "consume_source" else str(cost.item_id)
                current = available_inventory.get(item_id, 0)
                if kind == "consume_source" and item_id in equipped_ids:
                    current = max(current, 1)
                quantity = int(cost.amount)
                if current < quantity:
                    raise DomainOperationError("Ability item cost is unavailable")
                remaining = current - quantity
                available_inventory[item_id] = remaining
                inventory_changes.append({
                    "character_id": str(actor.id),
                    "entity_id": str(actor.id),
                    "item_id": item_id,
                    "previous_quantity": current,
                    "quantity": remaining,
                    "delta": -quantity,
                })
            effects: list[dict[str, Any]] = []
            participants = {"actor": self.participant(project_id, actor_raw), "source": self.participant(project_id, source_raw)}
            # Active effects created by this ability begin after the action that
            # applied them has committed. Otherwise an effect with a one-action
            # delay would already be overdue immediately after creation.
            timing_projection = copy.deepcopy(projection)
            timing_projection["world_action_count"] = int(projection.get("world_action_count", 0)) + 1
            target_counts = dict(projection.get("target_action_counts", {}))
            target_counts[str(actor.id)] = int(target_counts.get(str(actor.id), 0)) + 1
            timing_projection["target_action_counts"] = target_counts
            proposed_names = {str(entity.get("name", "")).casefold() for entity in projection["entities"].values() if not entity.get("state", {}).get("archived")}
            for action in ability.actions:
                if action.destination_id: self.entity(projection, action.destination_id, "location")
                if action.fact_id: self.entity(projection, action.fact_id, "fact")
                if str(action.kind) == "play_noise" and not self.data.sound.noise_variant(project_id, str(action.noise_id), playable_only=True): raise DomainOperationError("Ability noise is not enabled or available")
                if str(action.kind) == "create":
                    proposed = str(action.entity_name or "").casefold()
                    if proposed in proposed_names: raise DomainOperationError(f"An entity named '{action.entity_name}' already exists on this branch")
                    proposed_names.add(proposed)
                resolved = targets.resolve_effect_targets(projection, actor, primary, ability, action)
                if str(action.kind) == "apply_effect":
                    definition = self.data.rules.effect(project_id, str(action.effect_key))
                    if not definition or not definition.enabled: raise DomainOperationError(f"Unknown effect: {action.effect_key}")
                    effects.extend(self.normalize_effect(project_id, timing_projection, definition, target, participants, action.duration_override, action.tick_override) for target in resolved)
                else: effects.extend(self.normalize_action(action, target, actor) for target in (resolved[:1] if str(action.kind) in {"advance_time", "play_noise", "create"} else resolved))
        except DomainOperationError as exc: raise RulesRuntimeError(str(exc)) from exc
        return {"actor_id": actor.id, "target_id": primary.id, "ability_key": ability.ability_key, "ability_name": ability.name, "source_item_id": source_item_id, "costs": execution.costs, "inventory_changes": inventory_changes, "effects": effects}

    def direct_effect(self, project_id: str, projection: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
        definition = self.data.rules.effect(project_id, str(arguments.get("effect_key") or ""))
        if not definition or not definition.enabled: raise RulesRuntimeError("Unknown effect")
        target_id = str(arguments.get("target_id") or ""); target_raw = projection["entities"].get(target_id) or projection["relations"].get(target_id)
        if not target_raw: raise RulesRuntimeError("Effect target is unavailable")
        target = SimpleNamespace(id=target_id, scope="relationship" if target_id in projection["relations"] else str(target_raw.get("kind")))
        actor_raw = projection["entities"].get(str(arguments.get("actor_id"))) if arguments.get("actor_id") else target_raw
        source_raw = projection["entities"].get(str(arguments.get("source_id"))) if arguments.get("source_id") else actor_raw
        if not actor_raw or not source_raw: raise RulesRuntimeError("Effect actor or source is unavailable")
        try: return self.normalize_effect(project_id, projection, definition, target, {"actor": self.participant(project_id, actor_raw), "source": self.participant(project_id, source_raw)})
        except DomainOperationError as exc: raise RulesRuntimeError(str(exc)) from exc

    def due_effects(self, project_id: str, projection: dict[str, Any], clock: str, new_progress: int, *, target_id: str | None = None) -> list[dict[str, Any]]:
        working, emitted, firings = copy.deepcopy(projection), [], 0
        for instance in list(working.get("active_effects", {}).values()):
            if instance.get("clock") != clock or (target_id and instance.get("target_id") != target_id): continue
            next_tick, expires = int(instance["next_tick"]), instance.get("expires_at")
            while next_tick <= new_progress and (expires is None or next_tick <= int(expires)):
                firings += 1
                if firings > 1000: raise RulesRuntimeError("Effect advancement exceeds 1,000 firings")
                definition = self.data.rules.effect(project_id, instance["effect_key"])
                actor_raw = working["entities"].get(instance.get("actor_id")) or working["relations"].get(instance.get("actor_id")); source_raw = working["entities"].get(instance.get("source_id")) or working["relations"].get(instance.get("source_id")); target_raw = working["entities"].get(instance["target_id"]) or working["relations"].get(instance["target_id"])
                if not definition or not actor_raw or not source_raw or not target_raw: raise RulesRuntimeError("Active effect definition or participant is unavailable")
                magnitude, inputs = (float(instance["snapshot_magnitude"]), dict(instance.get("snapshot_inputs") or {})) if instance.get("evaluation_mode") == "snapshot" else FormulaEvaluator().evaluate(definition.formula, {"actor": self.participant(project_id, actor_raw), "source": self.participant(project_id, source_raw), "target": self.participant(project_id, target_raw)})
                magnitude *= int(instance.get("stacks", 1)); target_kind = "relationship" if instance["target_id"] in working["relations"] else str(target_raw.get("kind")); stat = self.stat(project_id, definition.target_stat_key, target_kind); values = self.effective_stats(project_id, target_raw, target_kind); current = float(values[definition.target_stat_key]); value = EffectExecutor._bounded_value(stat, current, str(definition.operation), magnitude, values=values, stat_lookup=lambda key: self.data.rules.stat(project_id, key))
                row = {"event_type": "stat.changed", "relation_id" if target_kind == "relationship" else "entity_id": instance["target_id"], "stat_key": definition.target_stat_key, "previous_value": current, "value": value, "effect_key": definition.effect_key, "active_instance_id": instance["id"], "resolved_inputs": inputs, "resolved_magnitude": magnitude, "fired_at": next_tick, "operation": str(definition.operation)}
                emitted.append(row); self.apply_event(working, "stat.changed", row, row.get("entity_id")); next_tick += int(instance.get("tick_interval") or instance.get("duration"))
            if expires is not None and new_progress >= int(expires): emitted.append({"event_type": "effect.instance_removed", "id": instance["id"], "reason": "expired"})
            elif next_tick != int(instance["next_tick"]): emitted.append({"event_type": "effect.instance_updated", "id": instance["id"], "next_tick": next_tick})
        return emitted

    def dependent_clamps(self, project_id: str, projection: dict[str, Any], events: list[Event]) -> list[dict[str, Any]]:
        """Persist transitive clamping caused by dynamic stat bounds.

        A bound stat can itself be another stat's bound, so one mutation may
        require a chain of deterministic derived stat.changed events. The
        definition graph is validated as acyclic at write/migration time; the
        event cap is a second line of defence against malformed persisted data.
        """
        working, derived = copy.deepcopy(projection), []
        queue: list[Event] = list(events)
        definitions = list(self.data.rules.stats(project_id))
        while queue:
            event_type, entity_id, payload = queue.pop(0)
            self.apply_event(working, event_type, payload, entity_id)
            if event_type != "stat.changed":
                continue
            container = working["relations"].get(payload.get("relation_id")) or working["entities"].get(payload.get("entity_id"))
            if not container:
                continue
            kind = "relationship" if payload.get("relation_id") else str(container.get("kind"))
            changed_key = payload.get("stat_key")
            for definition in definitions:
                if kind not in map(str, definition.compatible_owner_kinds):
                    continue
                if changed_key not in {definition.minimum_stat_key, definition.maximum_stat_key}:
                    continue
                raw = float(container.get("stats", {}).get(definition.stat_key, definition.default_value))
                effective = self.effective_stats(project_id, container, kind).get(definition.stat_key, raw)
                if float(effective) == raw:
                    continue
                row = {
                    "event_type": "stat.changed",
                    ("relation_id" if kind == "relationship" else "entity_id"): container["id"],
                    "stat_key": definition.stat_key,
                    "previous_value": raw,
                    "value": effective,
                    "derived": True,
                    "reason": f"clamped after {changed_key} changed",
                }
                derived.append(row)
                if len(derived) > 256:
                    raise RulesRuntimeError("Dependent stat clamping exceeded 256 derived events")
                queue.append(("stat.changed", row.get("entity_id"), row))
        return derived

    def passive_cascade(self, project_id: str, projection: dict[str, Any], events: list[Event]) -> list[dict[str, Any]]:
        hooks = {"ability.used": "ability_used", "stat.changed": "stat_changed", "character.moved": "movement", "time.advanced": "time_advanced", "story.action_committed": "owner_action"}
        working, emitted, queue = copy.deepcopy(projection), [], []
        for event_type, entity_id, payload in events:
            self.apply_event(working, event_type, payload, entity_id)
            hook = "damage" if event_type == "stat.changed" and payload.get("operation") == "subtract" else hooks.get(event_type)
            if hook: queue.append((hook, entity_id or payload.get("entity_id"), payload, 1, ()))
        definitions = self.data.rules.abilities(project_id); by_key = {item.ability_key: item for item in definitions}; by_name = {item.name: item for item in definitions}
        while queue:
            hook, owner_id, payload, depth, ancestry = queue.pop(0)
            if depth > 8: raise RulesRuntimeError("Passive ability cascade exceeds depth 8")
            owners = [working["entities"].get(owner_id)] if owner_id else [item for item in working["entities"].values() if item.get("kind") == "character"]
            for owner_raw in [item for item in owners if item and item.get("kind") == "character"]:
                sources: list[tuple[Any, dict[str, Any]]] = []
                for key in owner_raw.get("state", {}).get("abilities", []):
                    ability = by_key.get(str(key)) or by_name.get(str(key))
                    if ability and str(ability.ability_kind) == "passive" and "character" in map(str, ability.compatible_owner_kinds): sources.append((ability, owner_raw))
                for item_id in owner_raw.get("state", {}).get("equipment", []):
                    item_raw = working["entities"].get(str(item_id))
                    for key in (item_raw or {}).get("state", {}).get("abilities", []):
                        ability = by_key.get(str(key)) or by_name.get(str(key))
                        if ability and str(ability.ability_kind) == "passive" and "item" in map(str, ability.compatible_owner_kinds): sources.append((ability, item_raw))
                actor = entity_from_projection(owner_raw)
                if not isinstance(actor, Character): continue
                for ability, source_raw in sources:
                    if not any(str(trigger.kind) == hook and (not trigger.stat_key or trigger.stat_key == payload.get("stat_key")) for trigger in ability.passive_triggers): continue
                    marker = (str(owner_raw["id"]), ability.ability_key, hook)
                    if marker in ancestry: raise RulesRuntimeError(f"Recursive passive loop detected at {ability.ability_key}")
                    primary_id = str(payload.get("target_id") or payload.get("entity_id") or owner_raw["id"])
                    resolver = TargetResolver()
                    try: primary = resolver.resolve_ability_target(working, actor, ability, primary_id if str(ability.target_type) != "self" else None)
                    except DomainOperationError: primary = resolver.resolve_ability_target(working, actor, ability, None)
                    lookup = lambda key, owner="character": self.stat(project_id, key, owner)
                    effective = lambda character: self.effective_stats(project_id, working["entities"][str(character.id)], "character")
                    RequirementEvaluator().ensure_satisfied(actor, ability, projection=working, primary_target=primary, stat_lookup=lookup, effective_stats=effective)
                    cost_result = EffectExecutor().normalize(projection=working, actor=actor, primary_target=primary, ability=ability, next_sequence=int(working.get("branch_sequence", 0)) + 1, elapsed_minutes=int(working.get("elapsed_minutes", 0)), stat_lookup=lookup, effective_stats=effective)
                    for cost in cost_result.costs:
                        row = {"event_type": "stat.changed", **cost, "passive_ability_key": ability.ability_key}; emitted.append(row); self.apply_event(working, "stat.changed", row, row.get("entity_id")); queue.append(("stat_changed", row.get("entity_id"), row, depth + 1, (*ancestry, marker)))
                    passive_inventory = {
                        str(entry.get("item_id")): int(entry.get("quantity", 0))
                        for entry in owner_raw.get("state", {}).get("inventory", [])
                    }
                    passive_equipment = set(map(str, owner_raw.get("state", {}).get("equipment", [])))
                    for cost in ability.costs:
                        if str(cost.kind) == "stat":
                            continue
                        item_id = str(source_raw["id"]) if str(cost.kind) == "consume_source" else str(cost.item_id)
                        current = passive_inventory.get(item_id, 0)
                        if str(cost.kind) == "consume_source" and item_id in passive_equipment:
                            current = max(current, 1)
                        amount = int(cost.amount)
                        if current < amount:
                            raise RulesRuntimeError(f"Passive ability {ability.name} lacks its item cost")
                        remaining = current - amount
                        passive_inventory[item_id] = remaining
                        row = {
                            "event_type": "inventory.adjusted",
                            "entity_id": owner_raw["id"],
                            "character_id": owner_raw["id"],
                            "item_id": item_id,
                            "previous_quantity": current,
                            "quantity": remaining,
                            "delta": -amount,
                            "passive_ability_key": ability.ability_key,
                        }
                        emitted.append(row)
                        self.apply_event(working, "inventory.adjusted", row, owner_raw["id"])
                    participants = {"actor": self.participant(project_id, owner_raw), "source": self.participant(project_id, source_raw)}
                    for action in ability.actions:
                        targets = resolver.resolve_effect_targets(working, actor, primary, ability, action)
                        for target in (targets[:1] if str(action.kind) in {"advance_time", "play_noise", "create"} else targets):
                            if str(action.kind) == "apply_effect":
                                effect = self.data.rules.effect(project_id, str(action.effect_key))
                                if not effect: raise RulesRuntimeError(f"Passive ability references missing effect {action.effect_key}")
                                row = self.normalize_effect(project_id, working, effect, target, participants, action.duration_override, action.tick_override)
                            else: row = self.normalize_action(action, target, actor)
                            emitted.append(row); event_type = str(row["event_type"]); event_payload = {key: value for key, value in row.items() if key != "event_type"}; self.apply_event(working, event_type, event_payload, row.get("entity_id")); next_hook = "damage" if event_type == "stat.changed" and row.get("operation") == "subtract" else hooks.get(event_type)
                            if next_hook: queue.append((next_hook, row.get("entity_id"), row, depth + 1, (*ancestry, marker)))
                            if len(emitted) > 64: raise RulesRuntimeError("Passive ability cascade exceeds 64 derived events")
        return emitted
