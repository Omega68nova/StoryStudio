from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Sequence
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid4())


class Database:
    def __init__(self, data_dir: Path | None = None) -> None:
        configured = os.environ.get("STORYSTUDIO_DATA_DIR")
        self._location_root = Path(os.environ.get("LOCALAPPDATA", Path.cwd())) / "StoryStudio"
        self._location_file = self._location_root / "location.json"
        self._environment_locked = configured is not None or data_dir is not None
        remembered: str | None = None
        if not self._environment_locked and self._location_file.is_file():
            try:
                remembered = json.loads(self._location_file.read_text(encoding="utf-8")).get("data_dir")
            except (OSError, json.JSONDecodeError, AttributeError):
                remembered = None
        default_root = self._location_root
        if configured:
            selected_dir = Path(configured)
        elif data_dir is not None:
            selected_dir = data_dir
        elif remembered:
            selected_dir = Path(remembered)
        else:
            selected_dir = default_root
        self.data_dir = selected_dir
        self.data_dir = self.data_dir.resolve()
        self.db_path = self.data_dir / "storystudio.db"
        self.images_dir = self.data_dir / "images"
        self.music_dir = self.data_dir / "music"
        self._lock = threading.RLock()
        self._transaction_state = threading.local()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        active = getattr(self._transaction_state, "connection", None)
        if active is not None:
            yield active
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.music_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def begin_transaction(self) -> None:
        if getattr(self._transaction_state, "connection", None) is not None:
            raise RuntimeError("A database transaction is already active on this thread")
        self._lock.acquire()
        connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("BEGIN IMMEDIATE")
        self._transaction_state.connection = connection

    def finish_transaction(self, *, commit: bool) -> None:
        connection = getattr(self._transaction_state, "connection", None)
        if connection is None:
            return
        try:
            connection.commit() if commit else connection.rollback()
        finally:
            self._transaction_state.connection = None
            connection.close()
            self._lock.release()

    def initialize(self) -> None:
        migration_dir = Path(__file__).resolve().parents[1] / "migrations"
        with self._lock, self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                row[0] for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for path in sorted(migration_dir.glob("*.sql")):
                if path.stem in applied:
                    continue
                connection.executescript(path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (path.stem, utc_now()),
                )
            connection.execute(
                "INSERT OR IGNORE INTO runtime_settings(id, updated_at) VALUES (1, ?)",
                (utc_now(),),
            )
            connection.execute(
                "UPDATE generation_jobs SET status = 'interrupted', "
                "error = 'StoryStudio restarted before this job completed', updated_at = ? "
            "WHERE status IN ('queued', 'running', 'switching')",
                (utc_now(),),
            )
            connection.execute(
                "UPDATE image_suggestions SET status='interrupted', updated_at=? WHERE status='queued' "
                "AND NOT EXISTS (SELECT 1 FROM generation_jobs j WHERE j.status IN ('queued','running','switching') "
                "AND json_extract(j.payload_json,'$.suggestion_id')=image_suggestions.id)",
                (utc_now(),),
            )
            connection.execute(
                "UPDATE entity_media_assets SET status='interrupted', updated_at=? WHERE status='queued' "
                "AND NOT EXISTS (SELECT 1 FROM generation_jobs j WHERE j.status IN ('queued','running','switching') "
                "AND json_extract(j.payload_json,'$.media_asset_id')=entity_media_assets.id)",
                (utc_now(),),
            )
            self._repair_planning_state(connection)

    def _repair_planning_state(self, connection: sqlite3.Connection) -> None:
        """Idempotently recover legacy/in-flight planning without discarding drafts."""
        now = utc_now()
        connection.execute(
            "UPDATE planning_stages SET status='approved', active_job_id=NULL, updated_at=? "
            "WHERE approved_json IS NOT NULL AND status NOT IN ('approved','stale','skipped')", (now,),
        )
        connection.execute("UPDATE planning_stages SET status='ready', updated_at=? WHERE status='draft'", (now,))
        connection.execute(
            "UPDATE planning_stages SET status='cancelled', active_job_id=NULL, updated_at=? "
            "WHERE status IN ('queued','generating') AND (active_job_id IS NULL OR active_job_id IN "
            "(SELECT id FROM generation_jobs WHERE status NOT IN ('queued','running','switching')))", (now,),
        )
        connection.execute("DELETE FROM planning_approval_claims WHERE stage_id IN (SELECT id FROM planning_stages WHERE status NOT IN ('approved','stale'))")
        sessions = connection.execute("SELECT id, project_id, created_at FROM planning_sessions").fetchall()
        for session in sessions:
            warnings: list[dict[str, str]] = []
            stages = connection.execute(
                "SELECT id, stage_number, transaction_id FROM planning_stages WHERE session_id=? AND status IN ('approved','stale') ORDER BY stage_number",
                (session["id"],),
            ).fetchall()
            missing = [stage for stage in stages if not stage["transaction_id"]]
            transactions = connection.execute(
                "SELECT id FROM world_transactions WHERE project_id=? AND provenance='planning' AND created_at>=? "
                "AND id NOT IN (SELECT transaction_id FROM planning_stages WHERE transaction_id IS NOT NULL) ORDER BY created_at",
                (session["project_id"], session["created_at"]),
            ).fetchall()
            if missing and len(missing) == len(transactions):
                for stage, transaction in zip(missing, transactions, strict=True):
                    connection.execute(
                        "UPDATE planning_stages SET transaction_id=?, legacy_link_state='linked' WHERE id=?",
                        (transaction["id"], stage["id"]),
                    )
            elif missing:
                warnings.append({"code": "ambiguous_legacy_transactions", "message": "Approved stages could not be linked safely to legacy world transactions."})
                for stage in missing:
                    connection.execute("UPDATE planning_stages SET legacy_link_state='ambiguous' WHERE id=?", (stage["id"],))
            linked_stages = connection.execute(
                "SELECT stage_number,transaction_id FROM planning_stages WHERE session_id=? AND transaction_id IS NOT NULL", (session["id"],)
            ).fetchall()
            for linked in linked_stages:
                connection.execute(
                    "UPDATE planning_entity_keys SET stage_number=? WHERE session_id=? AND stage_number=0 AND entity_id IN "
                    "(SELECT entity_id FROM world_events WHERE transaction_id=? AND event_type='entity.created')",
                    (linked["stage_number"], session["id"], linked["transaction_id"]),
                )
            unresolved = connection.execute(
                "SELECT MIN(stage_number) n FROM planning_stages WHERE session_id=? AND status NOT IN ('approved','skipped')", (session["id"],)
            ).fetchone()["n"]
            current = int(unresolved or 8)
            status = "completed" if unresolved is None else "active"
            connection.execute(
                "UPDATE planning_sessions SET current_stage=?, status=?, recovery_warnings_json=?, updated_at=? WHERE id=?",
                (current, status, json.dumps(warnings), now, session["id"]),
            )

    def relocate(self, destination: Path) -> None:
        if self._environment_locked:
            raise ValueError("The data directory is controlled by STORYSTUDIO_DATA_DIR and cannot be changed here")
        destination = destination.expanduser().resolve()
        if destination == self.data_dir:
            return
        if destination in self.data_dir.parents or self.data_dir in destination.parents:
            raise ValueError("The new data directory cannot contain, or be contained by, the current directory")
        if destination.exists() and any(destination.iterdir()):
            raise ValueError("The new data directory must be empty")
        with self._lock:
            with self.connect() as connection:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.db_path, destination / self.db_path.name)
            if self.images_dir.is_dir():
                shutil.copytree(self.images_dir, destination / "images", dirs_exist_ok=True)
            if self.music_dir.is_dir():
                shutil.copytree(self.music_dir, destination / "music", dirs_exist_ok=True)
            self._location_root.mkdir(parents=True, exist_ok=True)
            temporary = self._location_file.with_suffix(".tmp")
            temporary.write_text(json.dumps({"data_dir": str(destination)}), encoding="utf-8")
            temporary.replace(self._location_file)
            self.data_dir = destination
            self.db_path = destination / "storystudio.db"
            self.images_dir = destination / "images"
            self.music_dir = destination / "music"
            self.images_dir.mkdir(parents=True, exist_ok=True)
            self.music_dir.mkdir(parents=True, exist_ok=True)

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(sql, parameters)

    def fetch_one(self, sql: str, parameters: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self._lock, self.connect() as connection:
            row = connection.execute(sql, parameters).fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, parameters: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock, self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]

    def create_project(self, title: str) -> dict[str, Any]:
        project_id, now = new_id(), utc_now()
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO projects(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (project_id, title, now, now),
            )
            connection.execute(
                "INSERT INTO project_story_settings(project_id, default_generation_mode, response_max_tokens, updated_at) "
                "VALUES (?, 'low', 300, ?)", (project_id, now),
            )
            connection.execute(
                "INSERT INTO project_story_defaults(project_id,narration_mode,pov_strategy,updated_at) "
                "VALUES (?, 'third_limited', 'first_player', ?)", (project_id, now),
            )
            sunny_id = new_id()
            connection.execute(
                "INSERT INTO weather_definitions(id,project_id,name,description,created_at,updated_at) VALUES(?,?, 'Sunny','Clear, neutral weather with no environmental effects.',?,?)",
                (sunny_id, project_id, now, now),
            )
            connection.execute(
                "INSERT INTO project_environment_settings(project_id,enabled,initial_weather_id,updated_at) VALUES(?,1,?,?)",
                (project_id, sunny_id, now),
            )
            for position, (phase_name, duration) in enumerate((("Morning", 180), ("Day", 180), ("Noon", 120), ("Afternoon", 360), ("Night", 600))):
                connection.execute(
                    "INSERT INTO time_phases(id,project_id,name,duration_minutes,position) VALUES(?,?,?,?,?)",
                    (new_id(), project_id, phase_name, duration, position),
                )
            games = (
                ("roll_d20", "A dramatic twenty-sided die challenge.", 1, 19),
                ("roll_d6", "A quick six-sided die challenge.", 1, 5),
                ("flip_coin", "A binary chance challenge where the player calls heads or tails.", 1, 1),
                ("timing_hit", "Hit a moving marker inside a shrinking target.", 1, 10),
                ("key_mash", "Press rapidly for four seconds to overcome resistance.", 1, 10),
                ("red_light", "Hold during green and release during red without exceeding the mistake threshold.", 1, 10),
                ("lockpicking", "Position a pick and apply torque to open a lock.", 1, 10),
                ("hex_circuit", "Rotate seven hexagonal circuit tiles until every connection matches.", 1, 10),
                ("circled_teeth", "Time inputs against a rotating selector to push every occupied tooth inward.", 1, 10),
                ("timed_attack", "Strike overlapping attack cursors as close to the center as possible.", 1, 10),
                ("dodge_box", "Move inside a bounded arena for a five-second defensive challenge.", 1, 10),
            )
            for game_key, description, minimum, maximum in games:
                connection.execute(
                    "INSERT INTO project_minigame_configs(project_id,game_key,enabled,ai_description,min_difficulty,max_difficulty,updated_at) VALUES (?,?,0,?,?,?,?)",
                    (project_id, game_key, description, minimum, maximum, now),
                )
            defaults = (
                ("premise", "Premise"),
                ("style", "Style"),
                ("world", "World"),
                ("characters", "Characters"),
                ("continuity", "Continuity"),
            )
            for position, (kind, label) in enumerate(defaults):
                connection.execute(
                    "INSERT INTO bible_documents"
                    "(id, project_id, kind, title, content, position, updated_at) "
                    "VALUES (?, ?, ?, ?, '', ?, ?)",
                    (new_id(), project_id, kind, label, position, now),
                )
        return self.get_project(project_id) or {}

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))

    def create_story_node(
        self, project_id: str, parent_id: str | None, role: str, content: str, status: str = "complete",
        pov_character_id: str | None = None, narration_mode: str = "third_limited", action_kind: str = "story",
        author_user_id: str | None = None, author_name_snapshot: str | None = None,
    ) -> dict[str, Any]:
        node_id, now = new_id(), utc_now()
        self.execute(
            "INSERT INTO story_nodes(id, project_id, parent_id, role, content, status, created_at, pov_character_id, narration_mode, action_kind, author_user_id, author_name_snapshot) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (node_id, project_id, parent_id, role, content, status, now, pov_character_id, narration_mode, action_kind, author_user_id, author_name_snapshot),
        )
        return self.fetch_one("SELECT * FROM story_nodes WHERE id = ?", (node_id,)) or {}

    def story_path(self, leaf_id: str | None) -> list[dict[str, Any]]:
        if not leaf_id:
            return []
        rows = self.fetch_all(
            "WITH RECURSIVE path(id, project_id, parent_id, role, content, status, created_at, action_kind, depth) AS ("
            " SELECT id, project_id, parent_id, role, content, status, created_at, action_kind, 0 FROM story_nodes WHERE id = ?"
            " UNION ALL"
            " SELECT n.id, n.project_id, n.parent_id, n.role, n.content, n.status, n.created_at, n.action_kind, path.depth + 1"
            " FROM story_nodes n JOIN path ON path.parent_id = n.id"
            ") SELECT id, project_id, parent_id, role, content, status, created_at, action_kind "
            "FROM path ORDER BY depth DESC",
            (leaf_id,),
        )
        return rows

    def create_job(
        self, project_id: str, kind: str, payload: dict[str, Any],
        requested_by_user_id: str | None = None, requester_name_snapshot: str | None = None,
    ) -> dict[str, Any]:
        job_id, now = new_id(), utc_now()
        self.execute(
            "INSERT INTO generation_jobs"
            "(id, project_id, kind, status, payload_json, created_at, updated_at, requested_by_user_id, requester_name_snapshot) "
            "VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
            (job_id, project_id, kind, json.dumps(payload), now, now, requested_by_user_id, requester_name_snapshot),
        )
        return self.get_job(job_id) or {}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.fetch_one("SELECT * FROM generation_jobs WHERE id = ?", (job_id,))
        return decode_json_fields(row, "payload_json", "result_json", "metrics_json")

    def update_job_metrics(self, job_id: str, metrics: dict[str, Any]) -> None:
        self.execute(
            "UPDATE generation_jobs SET metrics_json=?, updated_at=? WHERE id=?",
            (json.dumps(metrics), utc_now(), job_id),
        )

    def update_job_partial_output(self, job_id: str, content: str) -> None:
        self.execute(
            "UPDATE generation_jobs SET partial_output=?, updated_at=? WHERE id=?",
            (content, utc_now(), job_id),
        )

    def update_job(
        self,
        job_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.execute(
            "UPDATE generation_jobs SET status = ?, result_json = COALESCE(?, result_json), "
            "error = ?, updated_at = ? WHERE id = ?",
            (status, json.dumps(result) if result is not None else None, error, utc_now(), job_id),
        )

    def update_job_progress(
        self, job_id: str, phase: str, message: str = "", current: float | None = None, total: float | None = None
    ) -> None:
        self.execute(
            "UPDATE generation_jobs SET phase = ?, progress_message = ?, progress_current = ?, progress_total = ?, updated_at = ? WHERE id = ?",
            (phase, message, current, total, utc_now(), job_id),
        )

    def update_job_payload(self, job_id: str, payload: dict[str, Any], status: str = "queued") -> None:
        self.execute(
            "UPDATE generation_jobs SET payload_json = ?, status = ?, error = NULL, updated_at = ? WHERE id = ?",
            (json.dumps(payload), status, utc_now(), job_id),
        )


def decode_json_fields(row: dict[str, Any] | None, *fields: str) -> dict[str, Any] | None:
    if row is None:
        return None
    decoded = dict(row)
    for field in fields:
        raw = decoded.pop(field, None)
        decoded[field.removesuffix("_json")] = json.loads(raw) if raw else None
    return decoded
