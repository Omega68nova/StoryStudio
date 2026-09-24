from __future__ import annotations

import hashlib
import json
from typing import Any

from app.database import Database, new_id, utc_now
from app.domain.world import ActionEffect, RequirementExpression
from app.services.world import WorldValidationError


PLANNING_STAGES = (
    (1, "foundation", "Core Bible, theme, style, world overview, cast direction, and narration defaults"),
    (2, "macro_world", "Scale-appropriate major geography, routes, factions, weather, and transitions"),
    (3, "detailed_locations", "Important minor locations and only the rooms likely to be revisited"),
    (4, "systems", "Lore rules, stats, abilities, sickness, skills, and system-linked items"),
    (5, "cast", "Playable characters, active NPCs, supporting cast, factions, knowledge, and starting locations"),
    (6, "character_details", "Character details, outfits, relationships, routines, arcs, secrets, and plot hooks"),
    (7, "runtime_presentation", "Minigames, ambient assignments, bullet-hell options, and Music themes"),
    (8, "images", "Deterministic portrait and location-background prompt preparation"),
)

SCALE_PRESETS: dict[str, dict[str, int]] = {
    "intimate": {"major_locations": 3, "minor_locations": 8, "rooms": 8, "characters": 6},
    "local": {"major_locations": 6, "minor_locations": 20, "rooms": 16, "characters": 10},
    "regional": {"major_locations": 12, "minor_locations": 40, "rooms": 24, "characters": 18},
    "global": {"major_locations": 24, "minor_locations": 80, "rooms": 40, "characters": 30},
}

STAGE_PUBLISHES = {
    1: {"foundation"}, 2: {"macro_locations", "weather"}, 3: {"detailed_locations"},
    4: {"rules", "stats_abilities"}, 5: {"cast"}, 6: {"character_details"},
    7: {"runtime_configuration"}, 8: {"visual_assets"},
}
STAGE_CONSUMES = {
    1: set(), 2: {"foundation"}, 3: {"foundation", "macro_locations"},
    4: {"foundation"}, 5: {"foundation", "macro_locations", "detailed_locations", "rules", "stats_abilities"},
    6: {"cast", "macro_locations", "detailed_locations", "rules", "stats_abilities"},
    7: {"weather", "macro_locations", "detailed_locations", "stats_abilities", "cast", "character_details"},
    8: {"foundation", "macro_locations", "weather", "detailed_locations", "cast", "character_details"},
}

STAGE_GENERATION_FOCI: dict[int, tuple[str, ...]] = {
    2: ("locations", "weather", "factions", "anchors", "connections"),
    3: ("locations", "anchors", "connections"),
    4: ("lore_systems", "stats", "abilities", "items"),
    5: ("characters", "factions", "facts"),
    6: ("character_updates", "outfits", "relationships", "routines", "facts", "plot_beats"),
    7: ("minigames", "bullethell", "ambient", "music"),
}


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def normalized_settings(settings: dict[str, Any]) -> dict[str, Any]:
    scale = str(settings.get("scale_preset") or "local")
    if scale not in SCALE_PRESETS:
        raise WorldValidationError("Unknown planning scale preset")
    defaults = SCALE_PRESETS[scale]
    limits = {"major_locations": (1, 30), "minor_locations": (0, 200), "rooms": (0, 200), "characters": (1, 100)}
    result: dict[str, Any] = {"scale_preset": scale, "direction": str(settings.get("direction") or "")[:10_000]}
    for key, (minimum, maximum) in limits.items():
        fallback = settings.get("secondary_locations", defaults[key]) if key == "minor_locations" else defaults[key]
        value = int(settings.get(key, fallback))
        result[key] = max(minimum, min(maximum, value))
    return result


def empty_draft(stage_number: int) -> dict[str, Any]:
    base: dict[str, Any] = {"summary": "", "notes": []}
    payloads: dict[int, dict[str, Any]] = {
        1: {"foundation": {"premise": "", "genres": [], "themes": [], "tone": "", "style": "", "world_description": "", "character_description": "", "narration_mode": "third_limited", "pov_strategy": "first_player"}},
        2: {"root_location_key": "", "locations": [], "anchors": [], "connections": [], "factions": [], "weather": [], "weather_transitions": [], "initial_weather_key": ""},
        3: {"locations": [], "anchors": [], "connections": []},
        4: {"lore_systems": [], "stats": [], "abilities": [], "items": []},
        5: {"characters": [], "factions": [], "facts": [], "default_pov_character_key": ""},
        6: {"character_updates": [], "outfits": [], "relationships": [], "routines": [], "facts": [], "plot_beats": []},
        7: {"minigames": [], "bullethell": {"mode_ids": [], "skill_ids": [], "attack_ids": []}, "ambient": [], "music": {"mode": "disabled", "enabled_theme_ids": [], "manual_theme_id": None}, "recommendations": []},
        8: {"assets": []},
    }
    return {**base, **payloads[stage_number]}


def compact_schema(stage_number: int, focus: str | None = None) -> dict[str, Any]:
    examples = {
        1: {"foundation": {"premise": "", "genres": [], "themes": [], "tone": "", "style": "", "world_description": "", "character_description": "", "narration_mode": "third_limited", "pov_strategy": "first_player"}},
        2: {"root_location_key": "world", "locations": [{"key": "world", "preset": "routed_map", "name": "", "tags": [], "state": {"description": "", "imagegen_description": "", "parent_location_key": None, "exposure": "outdoor", "topology": "closed", "occupancy": "child_required", "boundary_access": "free", "spatial_kind": "area", "planning_tier": "major", "important": True}}], "anchors": [{"key": "", "location_key": "", "name": "", "kind": "waypoint", "x": None, "y": None}], "connections": [{"key": "", "kind": "route", "source_anchor_key": "", "target_anchor_key": "", "travel_minutes": 0, "modes": ["walk"], "bidirectional": True}], "factions": [], "weather": [{"key": "", "name": "", "description": "", "imagegen_description": "", "tags": [], "image_tags": [], "enabled": True}], "weather_transitions": [{"source_key": "", "target_key": ""}], "initial_weather_key": ""},
        3: {"locations": [{"key": "", "preset": "house", "name": "", "tags": [], "state": {"description": "", "imagegen_description": "", "parent_location_key": "", "exposure": "indoor", "topology": "closed", "occupancy": "child_required", "boundary_access": "connection_required", "spatial_kind": "area", "planning_tier": "minor", "important": False}}], "anchors": [], "connections": []},
        4: {
            "lore_systems": [{
                "key": "magic_system", "name": "Magic System", "aliases": [], "tags": ["magic"],
                "state": {
                    "description": "A concise explanation of what the system is and how it affects the world.",
                    "rules": [], "limits": [], "costs": [], "secrets": [],
                },
            }],
            "stats": [
                {"key": "hp", "stat_key": "hp", "label": "Health", "description": "Current physical health.", "scope": "character", "default_value": 100, "minimum": 0, "maximum": 100, "minimum_stat_key": None, "maximum_stat_key": None, "color": "#5a9b63", "minimum_color": "#b94a48", "maximum_color": None, "display_style": "bar", "integer_only": True, "visibility": "public"},
                {"key": "stamina", "stat_key": "stamina", "label": "Stamina", "description": "Current exertion reserve.", "scope": "character", "default_value": 100, "minimum": 0, "maximum": 100, "minimum_stat_key": None, "maximum_stat_key": None, "color": "#5a9b63", "minimum_color": "#b94a48", "maximum_color": None, "display_style": "bar", "integer_only": True, "visibility": "public"},
            ],
            "abilities": [{
                "key": "basic_attack", "ability_key": "basic_attack", "name": "Basic Attack",
                "description": "Deals a fixed amount of physical damage to one character.",
                "target_type": "character", "requirements": {}, "costs": {"stamina": 10},
                "effects": [{"target": "target", "stat_key": "hp", "operation": "subtract", "amount": 10}],
                "minigame_profile": {},
            }],
            "items": [],
        },
        5: {
            "characters": [{
                "key": "character_key", "name": "Character name", "aliases": [], "tags": [],
                "state": {
                    "description": "A concise overview including identity, background, role, and other generally useful facts.",
                    "imagegen_description": "Visual-only details useful to an image model.",
                    "pronouns": "they/them",
                    "appearance": "Persistent physical features, build, hair, eyes, and distinguishing traits.",
                    "personality": "Temperament, values, habits, strengths, and flaws.",
                    "goals": [],
                    "character_secrets": [],
                    "secrets_to_character": [],
                    "cast_role": "active_npc",
                    "player_controlled": False,
                    "autonomy_enabled": True,
                    "intervention_frequency": "normal",
                    "current_location_key": None,
                },
            }],
            "factions": [], "facts": [], "default_pov_character_key": "",
        },
        6: {
            "character_updates": [{
                "key": "existing_character_key", "name": "Character name",
                "state": {
                    "description": "Updated identity, background, role, and general character overview.",
                    "imagegen_description": "Detailed visual-only guidance for character image generation.",
                    "pronouns": "they/them",
                    "appearance": "Detailed persistent appearance.",
                    "personality": "Detailed personality, values, habits, strengths, and flaws.",
                    "goals": [], "character_secrets": [], "secrets_to_character": [],
                    "wardrobe_notes": "Usual clothing and style notes.",
                    "equipment": [], "inventory": [], "abilities": [], "relationships": "",
                },
            }],
            "outfits": [{"key": "outfit_key", "character_key": "existing_character_key", "name": "Outfit name", "description": "General outfit purpose and semantic description.", "imagegen_description": "Visual-only clothing, materials, colors, and accessories.", "equipment": []}], "relationships": [], "routines": [], "facts": [], "plot_beats": [],
        },
        7: {"minigames": [], "bullethell": {"mode_ids": [], "skill_ids": [], "attack_ids": []}, "ambient": [], "music": {"mode": "disabled", "enabled_theme_ids": [], "manual_theme_id": None}, "recommendations": []},
    }
    example = examples.get(stage_number, {})
    if focus:
        if focus not in STAGE_GENERATION_FOCI.get(stage_number, ()):
            raise WorldValidationError("Unsupported generation section for this planning stage")
        selected_fields = {focus}
        if stage_number == 2 and focus == "weather":
            selected_fields.update({"weather_transitions", "initial_weather_key"})
        if stage_number == 5 and focus == "characters":
            selected_fields.add("default_pov_character_key")
        example = {field: example.get(field, [] if field not in {"music", "bullethell"} else {}) for field in selected_fields}
    return {"summary": "short batch overview", "notes": ["editable note"], **example}


def _record_identity(item: Any) -> str:
    if not isinstance(item, dict):
        return stable_hash(item)
    for key in ("key", "id", "stat_key", "ability_key", "game_key"):
        if item.get(key):
            return f"{key}:{str(item[key]).casefold()}"
    if item.get("source_key") and item.get("target_key"):
        return ":".join(str(item.get(key, "")).casefold() for key in ("source_key", "target_key", "relation"))
    return stable_hash(item)


def _merge_missing(base: Any, addition: Any) -> Any:
    if isinstance(base, dict) and isinstance(addition, dict):
        result = json.loads(json.dumps(base))
        for key, value in addition.items():
            result[key] = _merge_missing(result[key], value) if key in result else value
        return result
    if isinstance(base, list) and isinstance(addition, list):
        result = list(base)
        seen = {stable_hash(item) for item in result}
        for item in addition:
            fingerprint = stable_hash(item)
            if fingerprint not in seen:
                result.append(item)
                seen.add(fingerprint)
        return result
    return base if base not in (None, "", [], {}) else addition


def merge_generated_batch(stage_number: int, base: dict[str, Any], addition: dict[str, Any], focus: str) -> dict[str, Any]:
    """Append a focused AI batch without replacing accepted draft resources."""
    if focus not in STAGE_GENERATION_FOCI.get(stage_number, ()):
        raise WorldValidationError("Unsupported generation section for this planning stage")
    merged = json.loads(json.dumps(base or empty_draft(stage_number)))
    incoming = addition.get(focus)
    if isinstance(incoming, list):
        current = list(merged.get(focus) or [])
        known = {_record_identity(item) for item in current}
        for item in incoming:
            identity = _record_identity(item)
            if identity not in known:
                current.append(item)
                known.add(identity)
            elif stage_number == 6 and focus == "character_updates":
                index = next(index for index, existing_item in enumerate(current) if _record_identity(existing_item) == identity)
                current[index] = _merge_missing(current[index], item)
        merged[focus] = current
    elif isinstance(incoming, dict):
        current = dict(merged.get(focus) or {})
        for key, value in incoming.items():
            if isinstance(value, list):
                current_values = list(current.get(key) or [])
                seen = {_record_identity(item) for item in current_values}
                for item in value:
                    identity = _record_identity(item)
                    if identity not in seen:
                        current_values.append(item)
                        seen.add(identity)
                current[key] = current_values
            elif value not in (None, "", [], {}):
                current[key] = value
        merged[focus] = current
    else:
        raise WorldValidationError(f"Generated batch did not contain the requested {focus} section")
    if stage_number == 2 and focus == "weather":
        transitions = list(merged.get("weather_transitions") or [])
        seen = {_record_identity(item) for item in transitions}
        for item in addition.get("weather_transitions", []):
            if _record_identity(item) not in seen:
                transitions.append(item)
                seen.add(_record_identity(item))
        merged["weather_transitions"] = transitions
        if not merged.get("initial_weather_key") and addition.get("initial_weather_key"):
            merged["initial_weather_key"] = addition["initial_weather_key"]
    if stage_number == 5 and focus == "characters" and not merged.get("default_pov_character_key"):
        merged["default_pov_character_key"] = addition.get("default_pov_character_key", "")
    notes = list(merged.get("notes") or [])
    notes.extend(note for note in addition.get("notes", []) if note not in notes)
    merged["notes"] = notes
    if not str(merged.get("summary") or "").strip():
        merged["summary"] = str(addition.get("summary") or "")
    return merged


def _records(draft: dict[str, Any], field: str, kind: str) -> list[dict[str, Any]]:
    result = []
    for item in draft.get(field, []):
        if isinstance(item, dict):
            result.append({**item, "kind": kind, "aliases": list(item.get("aliases") or []), "tags": list(item.get("tags") or []), "state": dict(item.get("state") or {})})
    return result


def world_payload(stage_number: int, draft: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # Generic payloads remain accepted as an Advanced JSON compatibility path.
    if "entities" in draft:
        return list(draft.get("entities") or []), list(draft.get("relations") or [])
    entities: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    if stage_number == 2:
        entities += _records(draft, "locations", "location") + _records(draft, "factions", "faction")
        relations += list(draft.get("routes") or [])
    elif stage_number == 3:
        entities += _records(draft, "locations", "location"); relations += list(draft.get("routes") or [])
    elif stage_number == 4:
        entities += _records(draft, "lore_systems", "lore_system") + _records(draft, "items", "item")
    elif stage_number == 5:
        entities += _records(draft, "characters", "character") + _records(draft, "factions", "faction") + _records(draft, "facts", "fact")
    elif stage_number == 6:
        entities += _records(draft, "character_updates", "character") + _records(draft, "facts", "fact") + _records(draft, "plot_beats", "plot_beat")
        relations += list(draft.get("relationships") or [])
    return entities, relations


def validate_stage(stage_number: int, draft: dict[str, Any], settings: dict[str, Any] | None = None) -> None:
    if not isinstance(draft, dict) or not isinstance(draft.get("summary", ""), str) or not isinstance(draft.get("notes", []), list):
        raise WorldValidationError("Planning output requires a summary and notes array")
    entities, relations = world_payload(stage_number, draft)
    keys: set[str] = set()
    for item in entities:
        key, name = str(item.get("key") or "").strip(), str(item.get("name") or "").strip()
        if not key or not name or key in keys:
            raise WorldValidationError("Planning resource keys and names must be non-empty and unique within the stage")
        keys.add(key)
        if item["kind"] == "character":
            character_state = item.get("state", {})
            role = str(character_state.get("cast_role") or "supporting")
            if role not in {"player", "active_npc", "supporting", "background"}:
                raise WorldValidationError("Unsupported cast role")
            if role == "player":
                character_state["player_controlled"], character_state["autonomy_enabled"] = True, False
            if stage_number == 5:
                if not str(character_state.get("description") or "").strip():
                    raise WorldValidationError(f"Character '{name}' requires a description")
                if not str(character_state.get("appearance") or "").strip():
                    raise WorldValidationError(f"Character '{name}' requires an appearance")
    for relation in relations:
        if not relation.get("source_key") or not relation.get("target_key") or not str(relation.get("relation") or "").strip():
            raise WorldValidationError("Every planning relationship requires source, target, and relation")
    location_keys = {str(item.get("key")) for item in draft.get("locations", []) if isinstance(item, dict)}
    anchor_keys: set[str] = set()
    for location in draft.get("locations", []):
        if not isinstance(location, dict):
            continue
        state = location.get("state") or {}
        if state.get("topology", "closed") not in {"open", "closed"} or state.get("occupancy", "direct_allowed") not in {"direct_allowed", "child_required"}:
            raise WorldValidationError("Planning locations require valid topology and occupancy")
    for anchor in draft.get("anchors", []):
        key, location_key = str(anchor.get("key") or ""), str(anchor.get("location_key") or "")
        if not key or key in anchor_keys or not location_key:
            raise WorldValidationError("Planning anchors require unique keys and a location_key")
        anchor_keys.add(key)
    for connection in draft.get("connections", []):
        if connection.get("kind", "route") not in {"route", "door", "portal"} or connection.get("source_anchor_key") not in anchor_keys or connection.get("target_anchor_key") not in anchor_keys:
            raise WorldValidationError("Planning connections require a valid kind and two generated anchor keys")
    if draft.get("root_location_key") and str(draft["root_location_key"]) not in location_keys:
        raise WorldValidationError("Planning root_location_key must reference a generated location")
    #if settings:
        #caps = {2: ("locations", "major_locations"), 3: ("locations", "minor_locations"), 5: ("characters", "characters")}
        #if stage_number in caps:
        #    field, setting = caps[stage_number]
        #    if len(draft.get(field, [])) > int(settings[setting]):
        #        raise WorldValidationError(f"Stage exceeds the configured {setting.replace('_', ' ')} cap")
        #if stage_number == 3:
        #    rooms = sum(1 for item in draft.get("locations", []) if item.get("state", {}).get("planning_tier") == "room")
        #    if rooms > int(settings["rooms"]):
        #        raise WorldValidationError("Stage exceeds the configured room cap")
    if stage_number == 1 and "entities" not in draft:
        foundation = draft.get("foundation")
        if not isinstance(foundation, dict) or foundation.get("narration_mode", "third_limited") not in {"first_person", "third_limited", "third_omniscient"} or foundation.get("pov_strategy", "first_player") not in {"first_player", "selected_character", "none"}:
            raise WorldValidationError("Foundation requires valid narration and POV settings")
    if stage_number == 4:
        for lore_system in draft.get("lore_systems", []):
            lore_name = str(lore_system.get("name") or lore_system.get("key") or "Unnamed lore system")
            description = str((lore_system.get("state") or {}).get("description") or "").strip()
            if not description:
                raise WorldValidationError(f"Lore system '{lore_name}' requires a description")
        for ability in draft.get("abilities", []):
            ability_name = str(ability.get("name") or ability.get("ability_key") or ability.get("key") or "Unnamed ability")
            aliases = {"target": "target_type", "cost": "costs", "effect": "effects"}
            invalid_aliases = [f"'{wrong}' (use '{right}')" for wrong, right in aliases.items() if wrong in ability]
            if invalid_aliases:
                raise WorldValidationError(f"Ability '{ability_name}' uses unsupported field(s): {', '.join(invalid_aliases)}")
            if ability.get("target_type", "self") not in {"self", "character", "choice", "relationship", "location", "all", "party", "allies", "enemies", "nearby_enemies", "faction_members", "random"}:
                raise WorldValidationError(f"Ability '{ability_name}' has invalid target_type")
            if not isinstance(ability.get("costs", {}), dict) or not isinstance(ability.get("effects", []), list):
                raise WorldValidationError(f"Ability '{ability_name}' requires a costs object and an effects array")
            try:
                RequirementExpression.model_validate(ability.get("requirements", {}))
            except ValueError as exc:
                raise WorldValidationError(f"Ability '{ability_name}' has invalid requirements: {exc}") from exc
            for index, effect in enumerate(ability.get("effects", []), start=1):
                if not isinstance(effect, dict):
                    raise WorldValidationError(f"Ability '{ability_name}' effect {index} must be an object")
                if effect.get("target", "target") not in {"actor", "target", "party", "location", "nearby_enemies", "faction_members", "relationship_target", "allies", "enemies", "all", "random"}:
                    raise WorldValidationError(f"Ability '{ability_name}' effect {index} has invalid target")
                operation = effect.get("operation", "add")
                if operation not in {"add", "subtract", "set", "multiply", "move", "create", "remove", "apply_status", "reveal_knowledge", "change_relationship", "advance_time", "play_noise"}:
                    raise WorldValidationError(f"Ability '{ability_name}' effect {index} has invalid operation")
                if operation in {"add", "subtract", "set", "multiply"} and not str(effect.get("stat_key") or "").strip():
                    raise WorldValidationError(f"Ability '{ability_name}' effect {index} requires stat_key")
                try:
                    ActionEffect.model_validate(effect)
                except (TypeError, ValueError) as exc:
                    raise WorldValidationError(
                        f"Ability '{ability_name}' effect {index} is invalid: {exc}"
                    ) from exc
    if stage_number == 7:
        mode = (draft.get("music") or {}).get("mode", "disabled")
        if mode not in {"disabled", "player_managed", "ai_managed"}:
            raise WorldValidationError("Unsupported Music mode")


def normalize_generated_defaults(stage_number: int, draft: dict[str, Any]) -> dict[str, Any]:
    """AI-created resources start usable; admins may disable them after review."""
    if stage_number == 2:
        for weather in draft.get("weather", []):
            if isinstance(weather, dict):
                weather["enabled"] = True
    if stage_number in {2, 3}:
        for location in draft.get("locations", []):
            if isinstance(location, dict):
                location.setdefault("state", {})["enabled"] = True
    return draft


def generated_stage_has_content(stage_number: int, draft: dict[str, Any], focus: str | None = None) -> bool:
    if focus:
        value = draft.get(focus)
        return bool(value) if isinstance(value, (list, dict)) else False
    required_fields = {
        2: ("locations",),
        3: ("locations",),
        4: ("lore_systems", "stats", "abilities", "items"),
        5: ("characters",),
        6: ("character_updates", "outfits", "relationships", "routines", "facts", "plot_beats"),
    }
    if stage_number == 1:
        foundation = draft.get("foundation")
        return isinstance(foundation, dict) and any(str(foundation.get(key) or "").strip() for key in ("premise", "world_description", "style"))
    if stage_number == 7:
        return any(key in draft for key in ("minigames", "bullethell", "ambient", "music"))
    fields = required_fields.get(stage_number, ())
    return not fields or any(isinstance(draft.get(field), list) and bool(draft[field]) for field in fields)


def validate_catalog_references(db: Database, project_id: str, stage_number: int, draft: dict[str, Any]) -> None:
    """Reject externally managed identifiers before canonical writes begin."""
    if stage_number == 4:
        defined = {str(item.get("stat_key") or "") for item in draft.get("stats", [])}
        defined.update(row["stat_key"] for row in db.fetch_all("SELECT stat_key FROM stat_definitions WHERE project_id=?", (project_id,)))
        for ability in draft.get("abilities", []):
            referenced = {*dict(ability.get("costs") or {}), *[str(item.get("stat_key")) for item in ability.get("effects", []) if item.get("stat_key")]}
            missing = sorted(referenced - defined)
            if missing:
                ability_name = str(ability.get("name") or ability.get("ability_key") or ability.get("key") or "Unnamed ability")
                available = ", ".join(sorted(defined)) or "none"
                raise WorldValidationError(
                    f"Ability '{ability_name}' references unavailable stat(s): {', '.join(missing)}. "
                    f"Available stat keys: {available}"
                )
    if stage_number != 7:
        return
    games = {row["game_key"] for row in db.fetch_all("SELECT game_key FROM project_minigame_configs WHERE project_id=?", (project_id,))}
    if any(str(item.get("game_key") or "") not in games for item in draft.get("minigames", [])):
        raise WorldValidationError("Runtime presentation references an unknown minigame")
    bullet = draft.get("bullethell") or {}
    for kind, table in (("mode", "bullethell_modes"), ("skill", "bullethell_skills"), ("attack", "bullethell_attacks")):
        known = {row["id"] for row in db.fetch_all(f"SELECT id FROM {table}")}
        if not set(bullet.get(f"{kind}_ids", [])) <= known:
            raise WorldValidationError(f"Unknown bullet-hell {kind}")
    variants = {row["id"] for row in db.fetch_all("SELECT id FROM ambient_variants WHERE project_id=?", (project_id,))}
    for rule in draft.get("ambient", []):
        selected = list(rule.get("variant_ids") or [])
        for sound_set in rule.get("sets", []):
            selected.extend(sound_set.get("variant_ids") or [])
        if not set(selected) <= variants:
            raise WorldValidationError("Ambient assignment references an unavailable variant")
    themes = {row["id"] for row in db.fetch_all("SELECT id FROM music_themes")}
    music = draft.get("music") or {}; enabled = set(music.get("enabled_theme_ids") or [])
    if not enabled <= themes or (music.get("manual_theme_id") and music["manual_theme_id"] not in enabled):
        raise WorldValidationError("Music settings reference unavailable themes")


def dependency_snapshot(stages: list[dict[str, Any]], stage_number: int) -> dict[str, str]:
    wanted = STAGE_CONSUMES[stage_number]
    result: dict[str, str] = {}
    for stage in stages:
        domains = json.loads(stage.get("published_domains_json") or "{}")
        for domain, digest in domains.items():
            if domain in wanted:
                result[domain] = digest
    return result


def published_domains(stage_number: int, draft: dict[str, Any]) -> dict[str, str]:
    return {domain: stable_hash({"stage": stage_number, "domain": domain, "draft": draft}) for domain in STAGE_PUBLISHES[stage_number]}


def _resource_row(
    db: Database,
    owner_id: str,
    key: str,
    expected_type: str | None = None,
) -> dict[str, Any] | None:
    if expected_type:
        return db.fetch_one(
            "SELECT resource_id,resource_type,rowid "
            "FROM generation_resource_keys "
            "WHERE generation_plan_id=? AND resource_key=? AND resource_type=?",
            (owner_id, key, expected_type),
        )
    return db.fetch_one(
        "SELECT resource_id,resource_type,rowid "
        "FROM generation_resource_keys "
        "WHERE generation_plan_id=? AND resource_key=?",
        (owner_id, key),
    )


def resolve_resource(
    db: Database,
    owner_id: str,
    key_or_id: str | None,
    expected_type: str | None = None,
) -> str | None:
    if not key_or_id:
        return None
    row = _resource_row(db, owner_id, str(key_or_id), expected_type)
    return str(row["resource_id"]) if row else str(key_or_id)


def record_resource(
    db: Database,
    owner_id: str,
    stage_number: int,
    key: str,
    resource_type: str,
    resource_id: str,
    value: Any,
) -> None:
    legacy = db.fetch_one(
        "SELECT json_extract(settings_json,'$.legacy_session_id') legacy "
        "FROM generation_plans WHERE id=?",
        (owner_id,),
    )
    db.execute(
        "INSERT INTO generation_resource_keys("
        "generation_plan_id,resource_key,resource_type,resource_id,"
        "stage_number,fingerprint,legacy_session_id,updated_at"
        ") VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(generation_plan_id,resource_key) DO UPDATE SET "
        "resource_type=excluded.resource_type,"
        "resource_id=excluded.resource_id,"
        "stage_number=excluded.stage_number,"
        "fingerprint=excluded.fingerprint,"
        "updated_at=excluded.updated_at",
        (
            owner_id,
            key,
            resource_type,
            resource_id,
            stage_number,
            stable_hash(value),
            legacy.get("legacy") if legacy else None,
            utc_now(),
        ),
    )


def apply_foundation(db: Database, project_id: str, draft: dict[str, Any]) -> None:
    foundation = draft.get("foundation") or {}
    values = {
        "premise": "\n\n".join(filter(None, [str(foundation.get("premise") or "").strip(), "Themes: " + ", ".join(foundation.get("themes") or []) if foundation.get("themes") else ""])),
        "style": "\n\n".join(filter(None, [str(foundation.get("style") or "").strip(), f"Tone: {foundation.get('tone')}" if foundation.get("tone") else "", "Genres: " + ", ".join(foundation.get("genres") or []) if foundation.get("genres") else ""])),
        "world": str(foundation.get("world_description") or ""),
        "characters": str(foundation.get("character_description") or ""),
    }
    now = utc_now()
    for kind, content in values.items():
        db.execute("UPDATE bible_documents SET content=?,updated_at=? WHERE project_id=? AND kind=?", (content, now, project_id, kind))
    db.execute(
        "INSERT INTO project_story_defaults(project_id,narration_mode,pov_strategy,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(project_id) DO UPDATE SET narration_mode=excluded.narration_mode,pov_strategy=excluded.pov_strategy,updated_at=excluded.updated_at",
        (project_id, foundation.get("narration_mode", "third_limited"), foundation.get("pov_strategy", "first_player"), now),
    )


def apply_weather(db: Database, project_id: str, owner_id: str, stage_number: int, draft: dict[str, Any]) -> None:
    now, ids = utc_now(), {}
    for weather in draft.get("weather", []):
        key = str(weather["key"]); existing = _resource_row(db, owner_id, key, "weather")
        weather_id = str(existing["resource_id"]) if existing else new_id()
        if existing:
            db.execute("UPDATE weather_definitions SET name=?,description=?,imagegen_description=?,tags_json=?,image_tags_json=?,enabled=?,updated_at=? WHERE id=? AND project_id=?", (weather["name"], weather.get("description", ""), weather.get("imagegen_description", ""), json.dumps(weather.get("tags", [])), json.dumps(weather.get("image_tags", [])), int(weather.get("enabled", True)), now, weather_id, project_id))
        else:
            db.execute("INSERT INTO weather_definitions(id,project_id,name,description,imagegen_description,tags_json,image_tags_json,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (weather_id, project_id, weather["name"], weather.get("description", ""), weather.get("imagegen_description", ""), json.dumps(weather.get("tags", [])), json.dumps(weather.get("image_tags", [])), int(weather.get("enabled", True)), now, now))
        ids[key] = weather_id; record_resource(db, owner_id, stage_number, key, "weather", weather_id, weather)
    managed = set(ids.values())
    if managed:
        placeholders = ",".join("?" for _ in managed)
        db.execute(f"DELETE FROM weather_transitions WHERE project_id=? AND source_weather_id IN ({placeholders})", (project_id, *managed))
    for edge in draft.get("weather_transitions", []):
        source = ids.get(str(edge.get("source_key"))) or resolve_resource(db, owner_id, edge.get("source_key"), "weather")
        target = ids.get(str(edge.get("target_key"))) or resolve_resource(db, owner_id, edge.get("target_key"), "weather")
        count = db.fetch_one("SELECT COUNT(DISTINCT id) count FROM weather_definitions WHERE id IN (?,?) AND project_id=?", (source, target, project_id))
        #if not source or not target or not count or int(count["count"]) != len({source, target}):
        #    raise WorldValidationError("Weather transition references an unavailable weather")
        db.execute("INSERT OR IGNORE INTO weather_transitions(project_id,source_weather_id,target_weather_id) VALUES(?,?,?)", (project_id, source, target))
    initial = ids.get(str(draft.get("initial_weather_key"))) or resolve_resource(db, owner_id, draft.get("initial_weather_key"), "weather")
    if initial:
        if not db.fetch_one("SELECT id FROM weather_definitions WHERE id=? AND project_id=? AND enabled=1", (initial, project_id)):
            raise WorldValidationError("Initial weather must be enabled")
        db.execute("UPDATE project_environment_settings SET initial_weather_id=?,revision=revision+1,updated_at=? WHERE project_id=?", (initial, now, project_id))


def apply_rules(db: Database, project_id: str, owner_id: str, stage_number: int, draft: dict[str, Any]) -> None:
    now = utc_now()
    for stat in draft.get("stats", []):
        key = str(stat.get("key") or stat.get("stat_key") or "").strip()
        if not key or stat.get("scope", "character") not in {"character", "relationship"}:
            raise WorldValidationError("Invalid stat definition")
        existing = _resource_row(db, owner_id, key, "stat")
        stat_id = str(existing["resource_id"]) if existing else new_id()
        values = (
            stat["stat_key"],
            stat.get("label") or stat["stat_key"],
            stat.get("description", ""),
            stat.get("scope", "character"),
            float(stat.get("default_value", 0)),
            float(stat.get("minimum", 0)),
            float(stat.get("maximum", 100)),
            stat.get("minimum_stat_key"),
            stat.get("maximum_stat_key"),
            stat.get("color"),
            stat.get("minimum_color"),
            stat.get("maximum_color"),
            stat.get("display_style", "compact"),
            int(stat.get("integer_only", True)),
            stat.get("visibility", "public"),
        )
        if values[5] > values[6]:
            raise WorldValidationError("Stat minimum cannot exceed maximum")
        if values[7] == values[0] or values[8] == values[0]:
            raise WorldValidationError("A stat cannot use itself as a bound")
        if existing:
            db.execute(
                "UPDATE stat_definitions SET stat_key=?,label=?,description=?,"
                "scope=?,default_value=?,minimum=?,maximum=?,minimum_stat_key=?,"
                "maximum_stat_key=?,color=?,minimum_color=?,maximum_color=?,"
                "display_style=?,integer_only=?,visibility=?,updated_at=? "
                "WHERE id=? AND project_id=?",
                (*values, now, stat_id, project_id),
            )
        else:
            db.execute(
                "INSERT INTO stat_definitions("
                "id,project_id,stat_key,label,description,scope,default_value,"
                "minimum,maximum,minimum_stat_key,maximum_stat_key,color,"
                "minimum_color,maximum_color,display_style,integer_only,"
                "visibility,created_at,updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (stat_id, project_id, *values, now, now),
            )
        record_resource(db, owner_id, stage_number, key, "stat", stat_id, stat)
    known_stat_rows = db.fetch_all(
        "SELECT stat_key,scope FROM stat_definitions WHERE project_id=?",
        (project_id,),
    )
    known_stats = {row["stat_key"] for row in known_stat_rows}
    stat_scopes = {row["stat_key"]: row["scope"] for row in known_stat_rows}
    for stat in draft.get("stats", []):
        key = str(stat.get("stat_key") or stat.get("key") or "")
        scope = str(stat.get("scope") or "character")
        for field in ("minimum_stat_key", "maximum_stat_key"):
            reference = stat.get(field)
            if not reference:
                continue
            if reference not in known_stats:
                raise WorldValidationError(
                    f"Stat '{key}' {field} references unknown stat '{reference}'"
                )
            if stat_scopes.get(reference) != scope:
                raise WorldValidationError(
                    f"Stat '{key}' {field} must reference a {scope} stat"
                )
    for ability in draft.get("abilities", []):
        key = str(ability.get("key") or ability.get("ability_key") or "").strip()
        referenced = {*dict(ability.get("costs") or {}), *[str(item.get("stat_key")) for item in ability.get("effects", []) if item.get("stat_key")]}
        if not key:
            raise WorldValidationError(f"Ability '{ability.get('name') or 'Unnamed ability'}' requires a stable key")
        missing = sorted(referenced - known_stats)
        if missing:
            ability_name = str(ability.get("name") or ability.get("ability_key") or key)
            available = ", ".join(sorted(known_stats)) or "none"
            raise WorldValidationError(
                f"Ability '{ability_name}' references unavailable stat(s): {', '.join(missing)}. "
                f"Available stat keys: {available}"
            )
        existing = _resource_row(db, owner_id, key, "ability"); ability_id = str(existing["resource_id"]) if existing else new_id()
        values = (ability.get("ability_key") or key, ability.get("name") or key, ability.get("description", ""), ability.get("target_type", "self"), json.dumps(ability.get("requirements", {})), json.dumps(ability.get("costs", {})), json.dumps(ability.get("effects", [])), json.dumps(ability.get("minigame_profile", {})))
        if existing: db.execute("UPDATE ability_definitions SET ability_key=?,name=?,description=?,target_type=?,requirements_json=?,costs_json=?,effects_json=?,minigame_profile_json=?,updated_at=? WHERE id=? AND project_id=?", (*values, now, ability_id, project_id))
        else: db.execute("INSERT INTO ability_definitions(id,project_id,ability_key,name,description,target_type,requirements_json,costs_json,effects_json,minigame_profile_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (ability_id, project_id, *values, now, now))
        record_resource(db, owner_id, stage_number, key, "ability", ability_id, ability)


def apply_outfits(db: Database, project_id: str, owner_id: str, stage_number: int, draft: dict[str, Any]) -> None:
    now = utc_now()
    for outfit in draft.get("outfits", []):
        key = str(outfit.get("key") or "").strip(); entity_id = resolve_resource(db, owner_id, outfit.get("character_key"), "entity")
        if not key or not entity_id or not db.fetch_one("SELECT id FROM world_entities WHERE id=? AND project_id=? AND kind='character'", (entity_id, project_id)): raise WorldValidationError("Outfit references an unavailable character")
        existing = _resource_row(db, owner_id, key, "outfit"); outfit_id = str(existing["resource_id"]) if existing else new_id()
        if existing:
            db.execute(
                "UPDATE entity_outfits SET name=?,description=?,"
                "imagegen_description=?,equipment_json=?,updated_at=? "
                "WHERE id=? AND entity_id=?",
                (
                    outfit.get("name", "Outfit"),
                    outfit.get("description", ""),
                    outfit.get("imagegen_description", ""),
                    json.dumps(outfit.get("equipment", [])),
                    now,
                    outfit_id,
                    entity_id,
                ),
            )
        else:
            db.execute(
                "INSERT INTO entity_outfits("
                "id,entity_id,name,description,imagegen_description,"
                "equipment_json,created_at,updated_at"
                ") VALUES(?,?,?,?,?,?,?,?)",
                (
                    outfit_id,
                    entity_id,
                    outfit.get("name", "Outfit"),
                    outfit.get("description", ""),
                    outfit.get("imagegen_description", ""),
                    json.dumps(outfit.get("equipment", [])),
                    now,
                    now,
                ),
            )
        record_resource(db, owner_id, stage_number, key, "outfit", outfit_id, outfit)
    for routine in draft.get("routines", []):
        key = str(routine.get("key") or "").strip(); character_id = resolve_resource(db, owner_id, routine.get("character_key"), "entity"); location_id = resolve_resource(db, owner_id, routine.get("location_key"), "entity")
        if not key or not character_id or not db.fetch_one("SELECT id FROM world_entities WHERE id=? AND project_id=? AND kind='character'", (character_id, project_id)): raise WorldValidationError("Routine references an unavailable character")
        if location_id and not db.fetch_one("SELECT id FROM world_entities WHERE id=? AND project_id=? AND kind='location'", (location_id, project_id)): raise WorldValidationError("Routine references an unavailable location")
        phase_id = routine.get("time_phase_id")
        if phase_id and not db.fetch_one("SELECT id FROM time_phases WHERE id=? AND project_id=?", (phase_id, project_id)): raise WorldValidationError("Routine references an unavailable time phase")
        existing = _resource_row(db, owner_id, key, "routine"); routine_id = str(existing["resource_id"]) if existing else new_id()
        if existing: db.execute("UPDATE character_routines SET character_id=?,location_id=?,time_phase_id=?,notes=?,updated_at=? WHERE id=? AND project_id=?", (character_id, location_id, phase_id, routine.get("notes", ""), now, routine_id, project_id))
        else: db.execute("INSERT INTO character_routines(id,project_id,character_id,location_id,time_phase_id,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (routine_id, project_id, character_id, location_id, phase_id, routine.get("notes", ""), now, now))
        record_resource(db, owner_id, stage_number, key, "routine", routine_id, routine)


def apply_runtime(db: Database, project_id: str, owner_id: str, draft: dict[str, Any]) -> None:
    for item in draft.get("minigames", []):
        game_key = str(item.get("game_key") or "")
        if not db.fetch_one("SELECT game_key FROM project_minigame_configs WHERE project_id=? AND game_key=?", (project_id, game_key)): raise WorldValidationError(f"Unknown minigame: {game_key}")
        db.execute("UPDATE project_minigame_configs SET enabled=?,ai_description=?,allowed_actions_json=?,required_actor_tags_json=?,required_location_tags_json=?,min_difficulty=?,max_difficulty=?,updated_at=? WHERE project_id=? AND game_key=?", (int(item.get("enabled", False)), item.get("ai_description", ""), json.dumps(item.get("allowed_actions", ["do"])), json.dumps(item.get("required_actor_tags", [])), json.dumps(item.get("required_location_tags", [])), int(item.get("min_difficulty", 1)), int(item.get("max_difficulty", 10)), utc_now(), project_id, game_key))
    if "bullethell" in draft:
        bullet = draft.get("bullethell") or {}
        catalogs = {"mode": "bullethell_modes", "skill": "bullethell_skills", "attack": "bullethell_attacks"}
        joins = {"mode": "project_bullethell_modes", "skill": "project_bullethell_skills", "attack": "project_bullethell_attacks"}
        for kind, catalog in catalogs.items():
            ids = list(dict.fromkeys(bullet.get(f"{kind}_ids", []))); known = {row["id"] for row in db.fetch_all(f"SELECT id FROM {catalog}")}
            if not set(ids) <= known: raise WorldValidationError(f"Unknown bullet-hell {kind}")
            join, column = joins[kind], f"{kind}_id"; db.execute(f"DELETE FROM {join} WHERE project_id=?", (project_id,))
            for definition_id in ids: db.execute(f"INSERT INTO {join}(project_id,{column}) VALUES(?,?)", (project_id, definition_id))
    variants = {row["id"] for row in db.fetch_all("SELECT id FROM ambient_variants WHERE project_id=?", (project_id,))}
    for rule in draft.get("ambient", []):
        owner_type = str(rule.get("owner_type") or ""); ambient_owner_id = resolve_resource(db, owner_id, rule.get("owner_key"))
        if owner_type not in {"weather", "time", "location", "action"} or not ambient_owner_id: raise WorldValidationError("Invalid ambient owner")
        selected = set(rule.get("variant_ids") or [])
        if not selected <= variants: raise WorldValidationError("Ambient assignment references an unavailable variant")
        db.execute("DELETE FROM ambient_assignments WHERE project_id=? AND owner_type=? AND owner_id=?", (project_id, owner_type, ambient_owner_id))
        for sound_set in rule.get("sets", [{"selector_type": "default", "variant_ids": list(selected)}]):
            for variant_id in dict.fromkeys(sound_set.get("variant_ids") or []):
                if variant_id not in variants: raise WorldValidationError("Ambient assignment references an unavailable variant")
                db.execute("INSERT INTO ambient_assignments(id,project_id,owner_type,owner_id,selector_type,selector_value,weather_id,time_phase_id,variant_id) VALUES(?,?,?,?,?,?,?,?,?)", (new_id(), project_id, owner_type, ambient_owner_id, sound_set.get("selector_type", "default"), sound_set.get("selector_value"), resolve_resource(db, owner_id, sound_set.get("weather_key"), "weather"), sound_set.get("time_phase_id"), variant_id))
    if "music" in draft:
        music = draft.get("music") or {}; theme_ids = list(dict.fromkeys(music.get("enabled_theme_ids") or [])); known_themes = {row["id"] for row in db.fetch_all("SELECT id FROM music_themes")}
        if not set(theme_ids) <= known_themes or (music.get("manual_theme_id") and music["manual_theme_id"] not in theme_ids): raise WorldValidationError("Music settings reference unavailable themes")
        db.execute("UPDATE project_music_settings SET mode=?,manual_theme_id=? WHERE project_id=?", (music.get("mode", "disabled"), music.get("manual_theme_id"), project_id)); db.execute("DELETE FROM project_music_themes WHERE project_id=?", (project_id,))
        for theme_id in theme_ids: db.execute("INSERT INTO project_music_themes(project_id,theme_id) VALUES(?,?)", (project_id, theme_id))


def prepare_image_plans(db: Database, project_id: str, owner_id: str, draft: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    bible = {row["kind"]: row["content"] for row in db.fetch_all("SELECT kind,content FROM bible_documents WHERE project_id=?", (project_id,))}
    owner_plan = db.fetch_one(
        "SELECT id,json_extract(settings_json,'$.legacy_session_id') legacy_session_id "
        "FROM generation_plans WHERE id=?",
        (owner_id,),
    )
    if not owner_plan:
        raise WorldValidationError("Planning workspace not found")
    generation_plan_id = str(owner_plan["id"])
    legacy_session_id = owner_plan.get("legacy_session_id")
    rows = db.fetch_all("SELECT id,kind,canonical_name,tags_json FROM world_entities WHERE project_id=? AND kind IN ('character','location')", (project_id,))
    projection_rows = {}
    # Latest lore version carries the branch-aware state without duplicating the world replay here.
    for row in rows:
        version = db.fetch_one("SELECT state_json FROM lore_card_versions WHERE entity_id=? ORDER BY created_at DESC LIMIT 1", (row["id"],)); projection_rows[row["id"]] = json.loads(version["state_json"]) if version else {}
    requested = {str(item.get("resource_key")): item for item in (draft or {}).get("assets", [])}
    now = utc_now(); result = []
    for row in rows:
        state = projection_rows[row["id"]]
        eligible = (row["kind"] == "character" and state.get("cast_role") in {"player", "active_npc"}) or (row["kind"] == "location" and (state.get("planning_tier") == "major" or state.get("important")))
        if not eligible: continue
        kind = "portrait" if row["kind"] == "character" else "location"; resource_key = f"{kind}:{row['id']}"; override = requested.get(resource_key, {})
        details = [bible.get("style", ""), row["canonical_name"], str(state.get("appearance") or state.get("imagegen_description") or state.get("description") or ""), ", ".join(json.loads(row["tags_json"]) + list(state.get("image_tags") or []))]
        prompt = str(override.get("prompt") or ". ".join(part.strip() for part in details if part and part.strip()))[:20_000]
        workflow_id = override.get("workflow_preset_id"); workflow = db.fetch_one("SELECT id,validation_status FROM workflow_presets WHERE id=?", (workflow_id,)) if workflow_id else None
        status = "ready" if workflow and workflow["validation_status"] == "valid" and prompt else "draft"; revision = stable_hash({"prompt": prompt, "negative": override.get("negative_prompt", ""), "workflow": workflow_id, "width": override.get("width"), "height": override.get("height")})
        existing = db.fetch_one("SELECT id,status,prompt_revision,media_asset_id,generation_job_id FROM generation_image_plans WHERE generation_plan_id=? AND resource_key=? LIMIT 1", (generation_plan_id, resource_key)); plan_id = existing["id"] if existing else new_id()
        keep_status = existing and existing["prompt_revision"] == revision and existing["status"] in {"queued", "generated"}
        next_status = existing["status"] if keep_status else status
        if existing: db.execute("UPDATE generation_image_plans SET generation_plan_id=COALESCE(generation_plan_id,?),prompt=?,negative_prompt=?,workflow_preset_id=?,width=?,height=?,prompt_revision=?,status=?,error=NULL,updated_at=? WHERE id=?", (generation_plan_id, prompt, override.get("negative_prompt", ""), workflow_id, override.get("width"), override.get("height"), revision, next_status, now, plan_id))
        else: db.execute("INSERT INTO generation_image_plans(id,generation_plan_id,project_id,resource_key,entity_id,kind,prompt,negative_prompt,workflow_preset_id,width,height,prompt_revision,status,legacy_session_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (plan_id, generation_plan_id, project_id, resource_key, row["id"], kind, prompt, override.get("negative_prompt", ""), workflow_id, override.get("width"), override.get("height"), revision, next_status, legacy_session_id, now, now))
        result.append(db.fetch_one("SELECT * FROM generation_image_plans WHERE id=?", (plan_id,)) or {})
    return result
