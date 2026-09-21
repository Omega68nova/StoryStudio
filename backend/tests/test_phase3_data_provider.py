from pathlib import Path

from app.data.dataProvider import DataProvider
from app.managers.musicManager import MusicManager
from app.managers.soundManager import SoundManager


class FakeDb:
    def fetch_one(self, sql: str, parameters=()):
        if "project_music_settings" in sql:
            return {
                "project_id": "p1",
                "mode": "disabled",
                "volume": 0.7,
                "manual_theme_id": None,
            }
        return None

    def fetch_all(self, sql: str, parameters=()):
        return []

    def execute(self, sql: str, parameters=()):
        return None


class FakeWorld:
    def projection(self, project_id: str, head_node_id=None):
        return {"current_theme_id": None}


def test_data_provider_exposes_typed_repositories() -> None:
    data = DataProvider(FakeDb())
    assert data.music.db is data.db
    assert data.sound.db is data.db
    assert data.environment.db is data.db


def test_music_manager_uses_repository_facade() -> None:
    manager = MusicManager(FakeDb(), FakeWorld())
    state = manager.project_state("p1")
    assert state["mode"] == "disabled"
    assert state["enabled_theme_ids"] == []
    assert state["playback_revision"] == 0


def test_sound_manager_works_with_repository_facade(tmp_path: Path) -> None:
    manager = SoundManager(FakeDb(), sound_root=tmp_path)
    assert manager.list_variants("p1") == []
