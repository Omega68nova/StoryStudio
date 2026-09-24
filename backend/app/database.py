from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import re
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
            # The unfinished canonical-rules branch originally used migration 041.
            # In the merged history, spatial storage owns 041 and canonical rules
            # move to 042. Databases that already ran the unfinished branch must
            # not execute the canonical schema rewrite a second time.
            if "041_canonical_rules" in applied and "042_canonical_rules" not in applied:
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    ("042_canonical_rules", utc_now()),
                )
                applied.add("042_canonical_rules")
            for path in sorted(migration_dir.glob("*.sql")):
                if path.stem in applied:
                    continue
                connection.executescript(path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (path.stem, utc_now()),
                )
            self._migrate_canonical_rules(connection)
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
            # GenerationPlan owns generation/review recovery.

    def _migrate_canonical_rules(self, connection: sqlite3.Connection) -> None:
        """Complete the canonical-rules data conversion once, atomically."""
        legacy_stats = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stat_definitions_legacy_v2'"
        ).fetchone()
        legacy_abilities = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ability_definitions_legacy_v2'"
        ).fetchone()
        if not legacy_stats and not legacy_abilities:
            return

        now = utc_now()
        if legacy_stats:
            rows = connection.execute("SELECT * FROM stat_definitions_legacy_v2").fetchall()
            for row in rows:
                record = dict(row)
                connection.execute(
                    "INSERT OR IGNORE INTO stat_definitions("
                    "project_id,stat_key,label,description,default_value,minimum,maximum,"
                    "minimum_stat_key,maximum_stat_key,color,minimum_color,maximum_color,"
                    "display_style,integer_only,visibility,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        record["project_id"], record["stat_key"], record["label"],
                        record.get("description") or "", record["default_value"],
                        record["minimum"], record["maximum"], record.get("minimum_stat_key"),
                        record.get("maximum_stat_key"), record.get("color"),
                        record.get("minimum_color"), record.get("maximum_color"),
                        record.get("display_style") or "compact", record["integer_only"],
                        record.get("visibility") or "public", record["created_at"], record["updated_at"],
                    ),
                )
                owner_kind = "relationship" if record.get("scope") == "relationship" else "character"
                connection.execute(
                    "INSERT OR IGNORE INTO stat_definition_owner_kinds(project_id,stat_key,owner_kind) VALUES(?,?,?)",
                    (record["project_id"], record["stat_key"], owner_kind),
                )
            for project in connection.execute("SELECT DISTINCT project_id FROM stat_definitions").fetchall():
                graph = {row["stat_key"]: [key for key in (row["minimum_stat_key"], row["maximum_stat_key"]) if key] for row in connection.execute("SELECT stat_key,minimum_stat_key,maximum_stat_key FROM stat_definitions WHERE project_id=?", (project["project_id"],)).fetchall()}
                visiting: set[str] = set(); visited: set[str] = set()
                def visit(key: str) -> None:
                    if key in visiting: raise ValueError(f"Stat bound dependency cycle in project {project['project_id']}")
                    if key in visited: return
                    visiting.add(key)
                    for child in graph.get(key, []): visit(child)
                    visiting.remove(key); visited.add(key)
                for key in graph: visit(key)

        if legacy_abilities:
            rows = connection.execute("SELECT * FROM ability_definitions_legacy_v2").fetchall()
            for row in rows:
                self._migrate_legacy_ability(connection, dict(row), now)

        discarded = connection.execute(
            "SELECT t.project_id,COUNT(*) count "
            "FROM world_events e JOIN world_transactions t ON t.id=e.transaction_id "
            "WHERE e.event_type='effect.applied' GROUP BY t.project_id"
        ).fetchall()
        for row in discarded:
            connection.execute(
                "INSERT INTO rule_migration_warnings(id,project_id,warning_kind,message,details_json,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (new_id(), row["project_id"], "discarded_active_effects",
                 f"Discarded {row['count']} legacy active effect event(s).",
                 json.dumps({"instance_count": row["count"]}), now),
            )
        connection.execute("DELETE FROM world_events WHERE event_type='effect.applied'")
        embedded = connection.execute(
            "SELECT t.project_id,"
            "COALESCE(SUM("
            "COALESCE(json_array_length(json_extract(e.payload_json,'$.entity.active_effects')),0)+"
            "COALESCE(json_array_length(json_extract(e.payload_json,'$.patch.active_effects')),0)"
            "),0) count "
            "FROM world_events e JOIN world_transactions t ON t.id=e.transaction_id "
            "GROUP BY t.project_id"
        ).fetchall()
        connection.execute("DROP TRIGGER IF EXISTS world_events_no_update")
        connection.execute(
            "UPDATE world_events SET payload_json=json_remove(payload_json,'$.entity.active_effects','$.patch.active_effects') WHERE json_type(payload_json,'$.entity.active_effects') IS NOT NULL OR json_type(payload_json,'$.patch.active_effects') IS NOT NULL"
        )
        connection.execute("CREATE TRIGGER world_events_no_update BEFORE UPDATE ON world_events BEGIN SELECT RAISE(ABORT, 'world events are immutable'); END")
        for row in embedded:
            if int(row["count"] or 0) <= 0: continue
            connection.execute(
                "INSERT INTO rule_migration_warnings(id,project_id,warning_kind,message,details_json,created_at) VALUES(?,?,?,?,?,?)",
                (new_id(), row["project_id"], "discarded_embedded_effects", f"Discarded {row['count']} embedded legacy active effect instance(s).", json.dumps({"instance_count": row["count"]}), now),
            )
        connection.execute("DELETE FROM world_projection_cache")
        if legacy_abilities:
            connection.execute("DROP TABLE ability_definitions_legacy_v2")
        if legacy_stats:
            connection.execute("DROP TABLE stat_definitions_legacy_v2")

    def _migrate_legacy_ability(
        self, connection: sqlite3.Connection, record: dict[str, Any], now: str
    ) -> None:
        project_id, ability_key = record["project_id"], record["ability_key"]
        profile = _safe_json(record.get("minigame_profile_json"), {})
        timed = profile.get("timed_attack") if isinstance(profile, dict) else None
        connection.execute(
            "INSERT OR IGNORE INTO ability_definitions("
            "project_id,ability_key,name,description,ability_kind,target_type,enabled,"
            "timed_attack_line_count,timed_attack_damage_per_line,created_at,updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, ability_key, record["name"], record.get("description") or "", "active",
             record.get("target_type") or "self", 1,
             timed.get("line_count") if isinstance(timed, dict) else None,
             timed.get("damage_per_line") if isinstance(timed, dict) else None,
             record["created_at"], record["updated_at"]),
        )
        connection.execute(
            "INSERT OR IGNORE INTO ability_owner_kinds(project_id,ability_key,owner_kind) VALUES(?,?, 'character')",
            (project_id, ability_key),
        )
        requirements = _safe_json(record.get("requirements_json"), {})
        if requirements:
            self._insert_legacy_requirement(connection, project_id, ability_key, requirements)
        costs = _safe_json(record.get("costs_json"), {})
        for position, (stat_key, amount) in enumerate(costs.items() if isinstance(costs, dict) else []):
            connection.execute(
                "INSERT INTO ability_costs(id,project_id,ability_key,position,cost_kind,stat_key,amount) VALUES(?,?,?,?, 'stat',?,?)",
                (new_id(), project_id, ability_key, position, stat_key, amount),
            )
        effects = _safe_json(record.get("effects_json"), [])
        for position, effect in enumerate(effects if isinstance(effects, list) else []):
            if not isinstance(effect, dict):
                continue
            operation = effect.get("operation", "add")
            if operation == "apply_status":
                connection.execute(
                    "INSERT INTO rule_migration_warnings(id,project_id,warning_kind,message,details_json,created_at) VALUES(?,?,?,?,?,?)",
                    (new_id(), project_id, "discarded_marker_status",
                     f"Discarded marker-only status from ability {ability_key}.",
                     json.dumps({"ability_key": ability_key, "position": position, "status": effect.get("status") or effect.get("name")}), now),
                )
                continue
            if operation in {"add", "subtract", "set", "multiply"}:
                base = re.sub(r"[^a-z0-9_]", "_", f"{ability_key}_effect_{position + 1}".lower())[:64]
                effect_key, suffix = base, 2
                while connection.execute(
                    "SELECT 1 FROM effect_definitions WHERE project_id=? AND effect_key=?", (project_id, effect_key)
                ).fetchone():
                    tail = f"_{suffix}"
                    effect_key, suffix = base[:64-len(tail)] + tail, suffix + 1
                duration = max(0, int(effect.get("duration_value") or 0))
                duration_type = effect.get("duration_type")
                clock = "story_minutes" if duration_type == "minutes" else "world_actions"
                connection.execute(
                    "INSERT INTO effect_definitions(project_id,effect_key,name,description,target_stat_key,operation,clock,duration,tick_interval,evaluation_mode,stacking_policy,max_stacks,visibility,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,0,'snapshot','replace',1,'public',1,?,?)",
                    (project_id, effect_key, effect.get("name") or effect_key.replace("_", " ").title(),
                     "Migrated from an inline ability effect.", effect.get("stat_key"), operation,
                     clock, duration, now, now),
                )
                connection.execute(
                    "INSERT INTO effect_formula_nodes(id,project_id,effect_key,parent_id,position,node_kind,constant_value) VALUES(?,?,?,?,0,'constant',?)",
                    (new_id(), project_id, effect_key, None, float(effect.get("amount") or 0)),
                )
                connection.execute(
                    "INSERT INTO ability_actions(id,project_id,ability_key,position,action_kind,target,effect_key) VALUES(?,?,?,?, 'apply_effect',?,?)",
                    (new_id(), project_id, ability_key, position, effect.get("target") or "target", effect_key),
                )
                continue
            action_kind = {
                "move": "move", "create": "create", "remove": "remove",
                "reveal_knowledge": "reveal_knowledge", "change_relationship": "change_relationship",
                "advance_time": "advance_time", "play_noise": "play_noise",
            }.get(operation)
            if action_kind:
                connection.execute(
                    "INSERT INTO ability_actions(id,project_id,ability_key,position,action_kind,target,destination_id,entity_kind,entity_name,state_json,fact_id,relation,minutes,noise_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), project_id, ability_key, position, action_kind, effect.get("target") or "target",
                     effect.get("destination_id"), effect.get("entity_kind"), effect.get("name"),
                     json.dumps(effect.get("state") or {}), effect.get("fact_id"), effect.get("relation"),
                     int(effect.get("minutes") or effect.get("amount") or 0), effect.get("noise_id")),
                )
        for position, skill_id in enumerate(profile.get("bullethell_skill_ids", []) if isinstance(profile, dict) else []):
            connection.execute(
                "INSERT OR IGNORE INTO ability_bullethell_skills(project_id,ability_key,skill_id,position) VALUES(?,?,?,?)",
                (project_id, ability_key, skill_id, position),
            )

    def _insert_legacy_requirement(
        self, connection: sqlite3.Connection, project_id: str, ability_key: str, value: dict[str, Any]
    ) -> None:
        leaves: list[dict[str, Any]] = []
        leaves.extend({"kind": "has_tag", "target": "actor", "tag": tag} for tag in value.get("tags", []) if isinstance(tag, str))
        leaves.extend({"kind": "compare", "target": "actor", "stat_key": key, "comparison": "gte", "value": amount} for key, amount in (value.get("min_stats") or {}).items())
        if value.get("kind"): leaves.append({key: item for key, item in value.items() if key not in {"tags", "min_stats"}})
        if not leaves: return
        root_value = leaves[0] if len(leaves) == 1 else {"kind": "and", "children": leaves}

        def write(node: dict[str, Any], parent_id: str | None, position: int, edge_kind: str = "child") -> None:
            node_id = new_id()
            connection.execute(
                "INSERT INTO ability_requirement_nodes(id,project_id,ability_key,parent_id,position,edge_kind,node_kind,target,stat_key,comparison,value_json,item_id,tag,relation,location_id,time_phase_id,weather_id,required_ability_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (node_id, project_id, ability_key, parent_id, position, edge_kind, node.get("kind"), node.get("target", "actor"), node.get("stat_key"), node.get("comparison", "gte"), json.dumps(node.get("value")) if node.get("value") is not None else None, node.get("item_id"), node.get("tag"), node.get("relation"), node.get("location_id"), node.get("time_phase_id"), node.get("weather_id"), node.get("ability_key")),
            )
            for index, child in enumerate(node.get("children") or []):
                if isinstance(child, dict):
                    write(child, node_id, index, "child")
            child = node.get("child")
            if isinstance(child, dict):
                write(child, node_id, 0, "not_child")
        write(root_value, None, 0)


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


def _safe_json(raw: Any, fallback: Any) -> Any:
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw if raw is not None else fallback)
    except (TypeError, json.JSONDecodeError):
        return fallback


def decode_json_fields(row: dict[str, Any] | None, *fields: str) -> dict[str, Any] | None:
    if row is None:
        return None
    decoded = dict(row)
    for field in fields:
        raw = decoded.pop(field, None)
        decoded[field.removesuffix("_json")] = json.loads(raw) if raw else None
    return decoded
