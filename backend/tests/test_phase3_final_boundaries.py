
import ast
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
        "projectRepository.py",
        "reviewRepository.py",
        "runtimeRepository.py",
        "soundRepository.py",
        "storyRepository.py",
        "workflowRepository.py",
        "worldRepository.py",
    }
    missing = sorted(name for name in required if not (data / name).is_file())
    assert not missing, f"Missing Phase 3 repositories: {missing}"


def test_managers_do_not_own_raw_sql() -> None:
    managers = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "managers"
    )
    offenders: list[str] = []

    for path in managers.glob("*.py"):
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in {
                "fetch_one",
                "fetch_all",
                "execute",
            }:
                continue

            owner = func.value
            is_db_call = (
                isinstance(owner, ast.Name)
                and owner.id == "db"
            ) or (
                isinstance(owner, ast.Attribute)
                and owner.attr == "db"
            )
            if is_db_call:
                offenders.append(
                    f"{path.name}:{getattr(node, 'lineno', '?')}"
                )

    assert not offenders, (
        "Managers still perform direct database persistence: "
        f"{offenders}"
    )


def test_auth_and_lifecycle_services_use_repositories() -> None:
    app = Path(__file__).resolve().parents[1] / "app"
    auth = (app / "services" / "auth.py").read_text(encoding="utf-8")
    lifecycle = (app / "services" / "lifecycle.py").read_text(encoding="utf-8")
    assert "self.repo = self.data.auth" in auth
    assert "self.repo = self.data.lifecycle" in lifecycle
