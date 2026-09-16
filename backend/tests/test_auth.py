from __future__ import annotations

from pathlib import Path

import pytest

from app.database import Database
from app.services.auth import AuthError, AuthService


def setup_auth(tmp_path: Path) -> tuple[Database, AuthService]:
    db = Database(tmp_path / "data")
    db.initialize()
    return db, AuthService(db)


def test_argon2_login_is_case_insensitive_and_sessions_are_revoked(tmp_path: Path) -> None:
    db, auth = setup_auth(tmp_path)
    created = auth.create_user("Omega", "correct-horse-battery", "admin")
    stored = db.fetch_one("SELECT * FROM users WHERE id=?", (created["id"],))
    assert stored and stored["password_hash"].startswith("$argon2id$")
    assert "correct-horse-battery" not in stored["password_hash"]

    logged_in, token = auth.authenticate("oMeGa", "correct-horse-battery", "local")
    assert logged_in["id"] == created["id"]
    session_user = auth.user_for_token(token)
    assert session_user and session_user.id == created["id"]

    auth.set_password(created["id"], "a-different-password")
    assert auth.user_for_token(token) is None
    with pytest.raises(AuthError):
        auth.authenticate("Omega", "correct-horse-battery", "another-client")


def test_project_assignments_are_explicit(tmp_path: Path) -> None:
    db, auth = setup_auth(tmp_path)
    member = auth.create_user("Reader", "reader-password", "member")
    project = db.create_project("Shared story")
    assert not auth.assigned(member["id"], project["id"])
    db.execute(
        "INSERT INTO user_project_access(user_id,project_id,created_at) VALUES(?,?,datetime('now'))",
        (member["id"], project["id"]),
    )
    assert auth.assigned(member["id"], project["id"])
