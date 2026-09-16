from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.database import Database, new_id, utc_now
from app.services.auth import AuthService
from app.services.environment import EnvironmentService
from app.services.world import WorldEngine


def test_member_assignment_default_deny_and_shared_music(tmp_path: Path, monkeypatch) -> None:
    db = Database(tmp_path / "data")
    db.initialize()
    auth = AuthService(db)
    auth.create_user("Administrator", "temporary-admin-password", "admin")
    member = auth.create_user("Reader", "temporary-member-password", "member")
    assigned = db.create_project("Assigned")
    db.create_project("Hidden")
    db.execute(
        "INSERT INTO user_project_access(user_id,project_id,created_at) VALUES(?,?,?)",
        (member["id"], assigned["id"], utc_now()),
    )
    theme_id, track_id, now = new_id(), new_id(), utc_now()
    db.execute("INSERT INTO music_themes(id,name,description,playback_mode,created_at,updated_at) VALUES(?,?,'','repeat_one',?,?)", (theme_id, "Theme", now, now))
    db.execute("INSERT INTO music_tracks(id,theme_id,title,file_path,mime_type,sha256,position,created_at) VALUES(?,?,?,'music/test.mp3','audio/mpeg','test-hash',0,?)", (track_id, theme_id, "Track", now))
    db.execute("INSERT INTO project_music_settings(project_id,mode,volume) VALUES(?,'player_managed',.7)", (assigned["id"],))
    db.execute("INSERT INTO project_music_themes(project_id,theme_id) VALUES(?,?)", (assigned["id"], theme_id))

    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "auth", auth)
    client = TestClient(main.app)
    login = client.post("/api/auth/login", json={"username": "reader", "password": "temporary-member-password"})
    assert login.status_code == 200
    assert [item["id"] for item in client.get("/api/projects").json()] == [assigned["id"]]
    assert client.get("/api/settings").status_code == 403
    selected = client.put(
        f"/api/projects/{assigned['id']}/music/playback",
        json={"theme_id": theme_id, "track_id": track_id},
    )
    assert selected.status_code == 200
    assert selected.json()["current_track_id"] == track_id


def test_member_environment_reads_and_personal_ambient_only(tmp_path: Path, monkeypatch) -> None:
    db = Database(tmp_path / "data"); db.initialize(); auth = AuthService(db)
    auth.create_user("Administrator", "temporary-admin-password", "admin")
    member = auth.create_user("Reader", "temporary-member-password", "member")
    project = db.create_project("Assigned"); environment = EnvironmentService(db); environment.ensure_project(project["id"])
    db.execute("INSERT INTO user_project_access(user_id,project_id,created_at) VALUES(?,?,?)", (member["id"], project["id"], utc_now()))
    monkeypatch.setattr(main, "db", db); monkeypatch.setattr(main, "auth", auth); monkeypatch.setattr(main, "environment", environment)
    monkeypatch.setattr(main.scheduler, "world", WorldEngine(db))
    client = TestClient(main.app); assert client.post("/api/auth/login", json={"username": "reader", "password": "temporary-member-password"}).status_code == 200
    assert client.get(f"/api/projects/{project['id']}/environment/scene").status_code == 200
    assert client.get(f"/api/projects/{project['id']}/environment/map").status_code == 200
    saved = client.put("/api/preferences/ambient", json={"enabled": False, "master_volume": .35})
    assert saved.status_code == 200 and saved.json() == {"enabled": False, "master_volume": .35}
    assert client.get(f"/api/projects/{project['id']}/environment/settings").status_code == 403
