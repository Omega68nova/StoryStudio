
from pathlib import Path


def test_phase3_final_repository_boundaries() -> None:
    app = Path(__file__).resolve().parents[1] / "app"
    data = app / "data"

    required = {
        "authRepository.py",
        "environmentRepository.py",
        "jobRepository.py",
        "lifecycleRepository.py",
        "mediaRepository.py",
        "musicRepository.py",
        "planningRepository.py",
        "projectRepository.py",
        "reviewRepository.py",
        "soundRepository.py",
        "storyRepository.py",
        "workflowRepository.py",
        "worldRepository.py",
    }
    missing = sorted(name for name in required if not (data / name).is_file())
    assert not missing, f"Missing Phase 3 repositories: {missing}"


def test_managers_do_not_own_raw_sql() -> None:
    managers = Path(__file__).resolve().parents[1] / "app" / "managers"
    offenders = []
    for path in managers.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        upper = text.upper()
        if any(token in upper for token in (
            "SELECT ",
            "INSERT INTO ",
            "UPDATE ",
            "DELETE FROM ",
        )):
            offenders.append(path.name)
    assert not offenders, f"Managers still contain raw SQL: {offenders}"


def test_auth_and_lifecycle_services_use_repositories() -> None:
    app = Path(__file__).resolve().parents[1] / "app"
    auth = (app / "services" / "auth.py").read_text(encoding="utf-8")
    lifecycle = (app / "services" / "lifecycle.py").read_text(encoding="utf-8")
    assert "self.repo = self.data.auth" in auth
    assert "self.repo = self.data.lifecycle" in lifecycle
