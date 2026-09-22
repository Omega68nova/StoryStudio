from __future__ import annotations

from pathlib import Path


def test_phase3_repository_files_exist() -> None:
    app = Path(__file__).resolve().parents[1] / "app"
    expected = {
        "projectRepository.py",
        "storyRepository.py",
        "jobRepository.py",
        "workflowRepository.py",
        "mediaRepository.py",
        "reviewRepository.py",
        "environmentRepository.py",
        "musicRepository.py",
        "soundRepository.py",
        "worldRepository.py",
    }
    data = app / "data"
    missing = sorted(name for name in expected if not (data / name).is_file())
    assert not missing, f"Missing Phase 3 repositories: {missing}"


def test_data_provider_exposes_world_repository() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "data"
        / "dataProvider.py"
    ).read_text(encoding="utf-8")
    assert "self.world = WorldRepository(db)" in source


def test_world_engine_uses_world_repository_boundary() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "world.py"
    ).read_text(encoding="utf-8")
    assert "self.repo = self.data.world" in source
    assert "self.repo.persist_commit(" in source
    assert "self.repo.committed_transactions(" in source
    assert "self.repo.transaction_events(" in source


