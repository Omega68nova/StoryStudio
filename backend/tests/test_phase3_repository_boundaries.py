from __future__ import annotations

from pathlib import Path


def test_phase3_repository_files_exist() -> None:
    app = Path(__file__).resolve().parents[1] / "app"
    expected = {
        "projectRepository.py",
        "storyRepository.py",
        "jobRepository.py",
        "planningRepository.py",
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


def test_data_provider_exposes_world_and_planning() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "data"
        / "dataProvider.py"
    ).read_text(encoding="utf-8")
    assert "self.planning = PlanningRepository(db)" in source
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


def test_planning_service_uses_planning_repository_boundary() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "planning.py"
    ).read_text(encoding="utf-8")
    assert "self.repo = self.data.planning" in source
    assert "self.repo.create_session(" in source
    assert "self.repo.save_generated_draft(" in source
