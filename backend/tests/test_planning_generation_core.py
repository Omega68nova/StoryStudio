from __future__ import annotations

import json

from app.services.planningGenerationCore import (
    _looks_like_token_truncation,
    _planning_json_error,
)


def test_complete_json_is_valid() -> None:
    assert _planning_json_error('{"ok": true}') is None


def test_fenced_json_is_valid() -> None:
    assert _planning_json_error(
        '```json\n{"ok": true}\n```'
    ) is None


def test_incomplete_json_is_detected() -> None:
    error = _planning_json_error(
        '{"items": [{"name": "unfinished'
    )
    assert error is not None
    assert _looks_like_token_truncation(
        '{"items": [{"name": "unfinished',
        error,
    )
