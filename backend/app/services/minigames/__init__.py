"""Stable public API for StoryStudio's bundled minigame framework."""

from app.services.minigames.service import (
    HEX_EDGES,
    MANIFESTS,
    MINIGAME_GROUPS,
    VIRTUAL_PLAYER_ID,
    MinigameService,
    hex_is_solved,
    replay_circled_teeth,
    score_timed_attack,
    simulate_bullethell,
)

__all__ = [
    "HEX_EDGES", "MANIFESTS", "MINIGAME_GROUPS", "VIRTUAL_PLAYER_ID",
    "MinigameService", "hex_is_solved", "replay_circled_teeth",
    "score_timed_attack", "simulate_bullethell",
]
