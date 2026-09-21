from __future__ import annotations

from app.handlers.storyJobHandler import StoryJobHandler
from app.managers.storyManager import StoryManager


class FakeDB:
    def fetch_one(self, *args, **kwargs):
        return None

    def fetch_all(self, *args, **kwargs):
        return []

    def story_path(self, *args, **kwargs):
        return []


def test_scene_intent_override_is_preserved() -> None:
    manager = StoryManager.__new__(StoryManager)
    manager.db = FakeDB()

    request = StoryManager.build_request(
        manager,
        project_id="p",
        payload={
            "action": "continue",
            "scene_intent": "Keep the scene quiet",
        },
        user_node={},
        head_node_id="h",
        context_limit=8192,
    )

    assert request.scene_intent_override == "Keep the scene quiet"


def test_story_handler_keeps_complete_sentence_stop() -> None:
    assert (
        StoryJobHandler._complete_sentences(
            "First sentence. Second sentence. unfinished"
        )
        == "First sentence. Second sentence."
    )
