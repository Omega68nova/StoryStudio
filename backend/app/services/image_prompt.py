from __future__ import annotations

import json
import re
from typing import Any

from app.database import Database
from app.services.world import WorldEngine


REFERENCE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


class ImagePromptReferenceError(ValueError):
    pass


def expand_image_prompt(
    db: Database, world: WorldEngine, project_id: str, head_node_id: str | None, prompt: str,
) -> tuple[str, list[dict[str, str]]]:
    """Resolve {{entity name/alias}} against the selected historical branch state."""
    requested = [match.group(1).strip() for match in REFERENCE.finditer(prompt)]
    if not requested:
        return prompt, []
    projection = world.projection(project_id, head_node_id)
    aliases: dict[str, list[dict[str, Any]]] = {}
    for entity in projection["entities"].values():
        for label in [entity["name"], *entity.get("aliases", [])]:
            aliases.setdefault(str(label).strip().casefold(), []).append(entity)

    resolved: dict[str, dict[str, Any]] = {}
    for label in requested:
        matches = aliases.get(label.casefold(), [])
        if not matches:
            raise ImagePromptReferenceError(
                f"Image prompt reference '{{{{{label}}}}}' was not found at this point in the story. "
                "Use an exact character name or alias from the current branch."
            )
        if len(matches) > 1:
            names = ", ".join(sorted(entity["name"] for entity in matches))
            raise ImagePromptReferenceError(f"Image prompt reference '{{{{{label}}}}}' is ambiguous: {names}")
        resolved[label.casefold()] = matches[0]

    descriptions: list[dict[str, str]] = []
    seen: set[str] = set()
    for label in requested:
        entity = resolved[label.casefold()]
        if entity["id"] in seen:
            continue
        seen.add(entity["id"])
        card = world.entity_card(project_id, entity["id"], head_node_id)["card"]
        description = str(card.get("visual_description") or card.get("compact_text") or entity["name"]).strip()
        state = entity.get("state", {})
        outfit_id = state.get("active_outfit_id")
        if outfit_id:
            outfit = db.fetch_one("SELECT name,description,equipment_json FROM entity_outfits WHERE id=? AND entity_id=?", (outfit_id, entity["id"]))
            if outfit:
                outfit_text = str(outfit.get("description") or "").strip()
                equipment = json.loads(outfit.get("equipment_json") or "[]")
                details = f"Current outfit: {outfit['name']}"
                if outfit_text:
                    details += f" — {outfit_text}"
                if equipment:
                    details += "; equipment: " + ", ".join(str(item) for item in equipment)
                description = f"{description}. {details}"
        descriptions.append({"entity_id": entity["id"], "name": entity["name"], "description": description})

    body = REFERENCE.sub(lambda match: resolved[match.group(1).strip().casefold()]["name"], prompt)
    prefix = "\n".join(f"{item['name']}: {item['description']}" for item in descriptions)
    return f"{prefix}\n\n{body}".strip(), descriptions
