import json

from app.services.planning import stage_prompt


def test_planning_prompt_compacts_large_prior_stages_and_inventory() -> None:
    session = {
        "settings_json": json.dumps(
            {
                "major_locations": 4,
                "secondary_locations": 12,
                "characters": 8,
                "direction": "direction " * 3000,
            }
        )
    }
    stage = {
        "stage_number": 2,
        "kind": "systems",
        "description": "Lore and magic systems",
        "human_prompt": "notes " * 3000,
    }
    approved = [
        {
            "stage_number": 1,
            "kind": "foundation",
            "approved_json": json.dumps(
                {
                    "summary": "foundation " * 3000,
                    "entities": [
                        {
                            "key": f"place_{index}",
                            "kind": "location",
                            "name": f"Place {index}",
                            "state": {"large": "x" * 1000},
                        }
                        for index in range(200)
                    ],
                    "relations": [
                        {
                            "source_key": f"place_{index}",
                            "target_key": f"place_{index + 1}",
                            "relation": "route",
                            "large": "x" * 1000,
                        }
                        for index in range(199)
                    ],
                }
            ),
        }
    ]
    inventory = [
        {
            "id": str(index),
            "kind": "location",
            "name": f"Existing {index}",
            "aliases": ["alias"] * 20,
            "tags": ["tag"] * 20,
        }
        for index in range(500)
    ]

    messages = stage_prompt(
        stage,
        session,
        approved,
        inventory,
        character_budget=13_000,
    )
    content = "\n".join(message["content"] for message in messages)

    assert len(content) <= 13_000
    assert "large" not in content
    assert "... [trimmed]" in content
    assert "Existing 499" not in content
