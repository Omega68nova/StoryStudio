from app.services.context import estimate_tokens, suggestion_prompt


def test_image_prompt_receives_scene_era_visual_context() -> None:
    messages = suggestion_prompt("Mara enters.", "Mara: silver hair; blue coat")
    assert "silver hair" in messages[1]["content"]


def test_token_estimate_is_conservative_for_short_text() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("12345") == 2
