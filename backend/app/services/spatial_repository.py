from __future__ import annotations

import json
from typing import Any

from app.database import Database, utc_now


class SpatialRepository:
    """Normalized, rebuildable persistence for the active spatial projection.

    WorldEngine events remain the branch/revision history. This repository stores
    the active branch in relational tables so map editing/runtime reads do not
    depend on repeatedly unpacking JSON event payloads.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _json(value: Any) -> str | None:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False) if value is not None else None

    @staticmethod
    def _geometry(value: Any) -> tuple[str | None, list[dict[str, float]]]:
        if not isinstance(value, dict):
            return None, []
        kind = value.get("kind")
        points = value.get("points")
        if kind not in {"point", "polyline", "polygon"} or not isinstance(points, list):
            return None, []
        clean: list[dict[str, float]] = []
        for point in points:
            if not isinstance(point, dict) or not isinstance(point.get("x"), (int, float)) or not isinstance(point.get("y"), (int, float)):
                continue
            clean.append({"x": float(point["x"]), "y": float(point["y"])})
        return str(kind), clean

    @staticmethod
    def _source_transaction_id(projection: dict[str, Any]) -> str | None:
        transactions = projection.get("transactions") or []
        return str(transactions[-1]["id"]) if transactions and transactions[-1].get("id") else None

    def state(self, project_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one("SELECT * FROM spatial_project_state WHERE project_id=?", (project_id,))

    def synchronize(self, project_id: str, projection: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        head_node_id = projection.get("head_node_id")
        source_transaction_id = self._source_transaction_id(projection)
        existing = self.state(project_id)
        if (
            not force
            and existing
            and existing.get("source_head_node_id") == head_node_id
            and existing.get("source_transaction_id") == source_transaction_id
        ):
            return existing

        now = utc_now()
        locations = {
            str(key): value for key, value in (projection.get("entities") or {}).items()
            if value.get("kind") == "location" and not value.get("state", {}).get("archived")
        }
        anchors = {str(key): value for key, value in (projection.get("map_anchors") or {}).items()}
        barriers = {str(key): value for key, value in (projection.get("map_barriers") or {}).items()}
        connections = {str(key): value for key, value in (projection.get("travel_connections") or {}).items()}
        encounters = {str(key): value for key, value in (projection.get("encounter_rules") or {}).items()}
        itineraries = {str(key): value for key, value in (projection.get("travel_itineraries") or {}).items()}

        self.db.begin_transaction()
        try:
            # Replace the materialized branch atomically. The event log is still the
            # immutable source used to rebuild this state after branch changes.
            self.db.execute("DELETE FROM spatial_itineraries_current WHERE project_id=?", (project_id,))
            self.db.execute("DELETE FROM spatial_encounter_rules_current WHERE project_id=?", (project_id,))
            self.db.execute("DELETE FROM spatial_connections_current WHERE project_id=?", (project_id,))
            self.db.execute("DELETE FROM spatial_barriers_current WHERE project_id=?", (project_id,))
            self.db.execute("DELETE FROM spatial_anchors_current WHERE project_id=?", (project_id,))
            self.db.execute("DELETE FROM spatial_locations WHERE project_id=?", (project_id,))

            for location_id, entity in locations.items():
                state = entity.get("state", {})
                footprint_kind, footprint = self._geometry(state.get("footprint"))
                bounds_kind, bounds = self._geometry(state.get("local_bounds"))
                self.db.execute(
                    "INSERT INTO spatial_locations("
                    "location_id,project_id,parent_location_id,topology,occupancy,boundary_access,spatial_kind,exposure,"
                    "x,y,hidden,discovered,enabled,random_encounter,minutes_per_unit,base_visibility_units,encounter_rate,"
                    "footprint_kind,local_bounds_kind,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        location_id, project_id, state.get("parent_location_id"),
                        state.get("topology", "closed"), state.get("occupancy", "direct_allowed"),
                        state.get("boundary_access", "free"), state.get("spatial_kind", "spot"),
                        state.get("exposure", "outdoor"), state.get("x"), state.get("y"),
                        int(bool(state.get("hidden", False))), int(bool(state.get("discovered", True))),
                        int(state.get("enabled", True) is not False), int(bool(state.get("random_encounter", False))),
                        float(state.get("minutes_per_unit", 1) or 0),
                        state.get("base_visibility_units"), float(state.get("encounter_rate", 0) or 0),
                        footprint_kind, bounds_kind, now,
                    ),
                )
                for role, points in (("footprint", footprint), ("local_bounds", bounds)):
                    for position, point in enumerate(points):
                        self.db.execute(
                            "INSERT INTO spatial_location_vertices(location_id,geometry_role,position,x,y) VALUES(?,?,?,?,?)",
                            (location_id, role, position, point["x"], point["y"]),
                        )

            for anchor_id, item in anchors.items():
                if str(item.get("location_id")) not in locations:
                    continue
                self.db.execute(
                    "INSERT INTO spatial_anchors_current("
                    "id,project_id,location_id,name,kind,x,y,hidden,discovered,enabled,requires_map_review,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        anchor_id, project_id, str(item["location_id"]), str(item.get("name") or "Anchor"),
                        str(item.get("kind") or "waypoint"), item.get("x"), item.get("y"),
                        int(bool(item.get("hidden", False))), int(bool(item.get("discovered", True))),
                        int(item.get("enabled", True) is not False), int(bool(item.get("requires_map_review", False))), now,
                    ),
                )

            for barrier_id, item in barriers.items():
                location_id = str(item.get("location_id") or "")
                if location_id not in locations:
                    continue
                geometry_kind, points = self._geometry(item.get("geometry"))
                self.db.execute(
                    "INSERT INTO spatial_barriers_current("
                    "id,project_id,location_id,name,geometry_kind,blocked_modes_json,requirements_json,hidden,discovered,"
                    "enabled,requires_map_review,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        barrier_id, project_id, location_id, str(item.get("name") or "Barrier"), geometry_kind,
                        self._json(item.get("blocked_modes") or ["walk"]) or "[]", self._json(item.get("requirements")),
                        int(bool(item.get("hidden", False))), int(bool(item.get("discovered", True))),
                        int(item.get("enabled", True) is not False), int(bool(item.get("requires_map_review", False))), now,
                    ),
                )
                for position, point in enumerate(points):
                    self.db.execute(
                        "INSERT INTO spatial_barrier_vertices(barrier_id,position,x,y) VALUES(?,?,?,?)",
                        (barrier_id, position, point["x"], point["y"]),
                    )

            valid_anchor_ids = set(anchors).intersection(
                row["id"] for row in self.db.fetch_all("SELECT id FROM spatial_anchors_current WHERE project_id=?", (project_id,))
            )
            for connection_id, item in connections.items():
                source_id, target_id = str(item.get("source_anchor_id") or ""), str(item.get("target_anchor_id") or "")
                if source_id not in valid_anchor_ids or target_id not in valid_anchor_ids:
                    continue
                self.db.execute(
                    "INSERT INTO spatial_connections_current("
                    "id,project_id,kind,source_anchor_id,target_anchor_id,travel_minutes,modes_json,bidirectional,"
                    "requirements_json,lock_json,hidden,discovered,enabled,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        connection_id, project_id, str(item.get("kind") or "route"), source_id, target_id,
                        max(0, int(item.get("travel_minutes", 0) or 0)),
                        self._json(item.get("modes") or ["walk"]) or "[]", int(bool(item.get("bidirectional", True))),
                        self._json(item.get("requirements")), self._json(item.get("lock")),
                        int(bool(item.get("hidden", False))), int(bool(item.get("discovered", True))),
                        int(item.get("enabled", True) is not False), now,
                    ),
                )

            valid_connection_ids = {
                row["id"] for row in self.db.fetch_all("SELECT id FROM spatial_connections_current WHERE project_id=?", (project_id,))
            }
            for rule_id, item in encounters.items():
                location_id = str(item.get("location_id") or "") or None
                connection_id = str(item.get("connection_id") or "") or None
                if location_id and location_id not in locations:
                    continue
                if connection_id and connection_id not in valid_connection_ids:
                    continue
                if bool(location_id) == bool(connection_id):
                    continue
                self.db.execute(
                    "INSERT INTO spatial_encounter_rules_current("
                    "id,project_id,location_id,connection_id,probability,hidden,discovered,enabled,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        rule_id, project_id, location_id, connection_id,
                        max(0.0, min(1.0, float(item.get("probability", 0) or 0))),
                        int(bool(item.get("hidden", False))), int(bool(item.get("discovered", True))),
                        int(item.get("enabled", True) is not False), now,
                    ),
                )
                for position, candidate in enumerate(item.get("candidates") or []):
                    candidate_id = str(candidate.get("location_id") or "")
                    if candidate_id not in locations:
                        continue
                    self.db.execute(
                        "INSERT INTO spatial_encounter_candidates(rule_id,position,location_id,weight) VALUES(?,?,?,?)",
                        (rule_id, position, candidate_id, max(0.000001, float(candidate.get("weight", 1) or 1))),
                    )

            for itinerary_id, item in itineraries.items():
                character_id = str(item.get("character_id") or "")
                if not character_id:
                    continue
                destination_location_id = str(item.get("destination_location_id") or "") or None
                destination_anchor_id = str(item.get("destination_anchor_id") or "") or None
                if destination_location_id and destination_location_id not in locations:
                    destination_location_id = None
                if destination_anchor_id and destination_anchor_id not in valid_anchor_ids:
                    destination_anchor_id = None
                self.db.execute(
                    "INSERT INTO spatial_itineraries_current("
                    "id,project_id,character_id,destination_location_id,destination_anchor_id,destination_x,destination_y,"
                    "mode,current_segment,remaining_minutes,status,interruption_json,traversal_seed,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        itinerary_id, project_id, character_id, destination_location_id, destination_anchor_id,
                        item.get("destination_x"), item.get("destination_y"), str(item.get("mode") or "walk"),
                        max(0, int(item.get("current_segment", 0) or 0)),
                        max(0.0, float(item.get("remaining_minutes", 0) or 0)),
                        str(item.get("status") or "active"), self._json(item.get("interruption")),
                        str(item.get("traversal_seed") or ""), now,
                    ),
                )
                for position, segment in enumerate(item.get("segments") or []):
                    source_id = str(segment.get("source_location_id") or "")
                    target_id = str(segment.get("target_location_id") or "")
                    if source_id not in locations or target_id not in locations:
                        continue
                    connection_id = str(segment.get("connection_id") or "") or None
                    if connection_id and connection_id not in valid_connection_ids:
                        connection_id = None
                    self.db.execute(
                        "INSERT INTO spatial_itinerary_segments("
                        "itinerary_id,position,kind,source_location_id,target_location_id,minutes,connection_id"
                        ") VALUES(?,?,?,?,?,?,?)",
                        (
                            itinerary_id, position, str(segment.get("kind") or "geometric"),
                            source_id, target_id, max(0.0, float(segment.get("minutes", 0) or 0)), connection_id,
                        ),
                    )
                    for point_position, point in enumerate(segment.get("points") or []):
                        if not isinstance(point, dict) or not isinstance(point.get("x"), (int, float)) or not isinstance(point.get("y"), (int, float)):
                            continue
                        self.db.execute(
                            "INSERT INTO spatial_itinerary_segment_points("
                            "itinerary_id,segment_position,point_position,x,y"
                            ") VALUES(?,?,?,?,?)",
                            (itinerary_id, position, point_position, float(point["x"]), float(point["y"])),
                        )

            root_location_id = projection.get("root_location_id")
            if root_location_id not in locations:
                roots = [
                    location_id for location_id, entity in locations.items()
                    if not entity.get("state", {}).get("parent_location_id")
                ]
                root_location_id = roots[0] if len(roots) == 1 else None
            revision = int(existing.get("revision", 0) if existing else 0) + 1
            self.db.execute(
                "INSERT INTO spatial_project_state(project_id,root_location_id,source_head_node_id,source_transaction_id,revision,updated_at) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET root_location_id=excluded.root_location_id,"
                "source_head_node_id=excluded.source_head_node_id,source_transaction_id=excluded.source_transaction_id,"
                "revision=excluded.revision,updated_at=excluded.updated_at",
                (project_id, root_location_id, head_node_id, source_transaction_id, revision, now),
            )
            self.db.finish_transaction(commit=True)
        except Exception:
            self.db.finish_transaction(commit=False)
            raise
        return self.state(project_id) or {}

    def _location_geometry(self, location_id: str, role: str) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT footprint_kind,local_bounds_kind FROM spatial_locations WHERE location_id=?",
            (location_id,),
        )
        if not row:
            return None
        kind = row["footprint_kind" if role == "footprint" else "local_bounds_kind"]
        if not kind:
            return None
        points = self.db.fetch_all(
            "SELECT x,y FROM spatial_location_vertices WHERE location_id=? AND geometry_role=? ORDER BY position",
            (location_id, role),
        )
        return {"location_id": location_id, "kind": kind, "points": [{"x": item["x"], "y": item["y"]} for item in points]}

    def local_map(self, project_id: str, location_id: str | None, *, administrative: bool = False, include_geometry: bool = False) -> dict[str, Any]:
        state = self.state(project_id)
        if not state or not state.get("root_location_id"):
            return {
                "enabled": False,
                "root_location_id": None,
                "blocked_reason": "missing_root",
                "locations": [],
                "anchors": [],
                "connections": [],
                "barriers": [],
                "revision": int((state or {}).get("revision", 0)),
            }
        focus_id = location_id or str(state["root_location_id"])
        focus = self.db.fetch_one(
            "SELECT * FROM spatial_locations WHERE project_id=? AND location_id=?",
            (project_id, focus_id),
        )
        if not focus:
            focus_id = str(state["root_location_id"])
            focus = self.db.fetch_one(
                "SELECT * FROM spatial_locations WHERE project_id=? AND location_id=?",
                (project_id, focus_id),
            )
        if not focus:
            return {
                "enabled": False,
                "root_location_id": state.get("root_location_id"),
                "blocked_reason": "root_not_materialized",
                "locations": [],
                "anchors": [],
                "connections": [],
                "barriers": [],
                "revision": int(state.get("revision", 0)),
            }

        visibility = "" if administrative else " AND l.discovered=1 AND l.hidden=0"
        rows = self.db.fetch_all(
            "SELECT l.*,e.canonical_name AS name FROM spatial_locations l "
            "JOIN world_entities e ON e.id=l.location_id "
            "WHERE l.project_id=? AND l.parent_location_id=?" + visibility + " ORDER BY e.canonical_name COLLATE NOCASE",
            (project_id, focus_id),
        )
        locations: list[dict[str, Any]] = []
        for item in rows:
            mapped = {
                "id": item["location_id"],
                "name": item["name"],
                "parent_location_id": item["parent_location_id"],
                "topology": item["topology"],
                "occupancy": item["occupancy"],
                "boundary_access": item["boundary_access"],
                "spatial_kind": item["spatial_kind"],
                "exposure": item["exposure"],
                "hidden": bool(item["hidden"]),
                "discovered": bool(item["discovered"]),
                "enabled": bool(item["enabled"]),
                "random_encounter": bool(item["random_encounter"]),
                "minutes_per_unit": item["minutes_per_unit"],
                "base_visibility_units": item["base_visibility_units"],
                "encounter_rate": item["encounter_rate"],
            }
            if administrative and include_geometry:
                mapped["x"], mapped["y"] = item["x"], item["y"]
                mapped["footprint"] = self._location_geometry(item["location_id"], "footprint")
                mapped["local_bounds"] = self._location_geometry(item["location_id"], "local_bounds")
            locations.append(mapped)

        child_ids = {focus_id, *(str(item["id"]) for item in locations)}
        placeholders = ",".join("?" for _ in child_ids)
        anchor_rows = self.db.fetch_all(
            f"SELECT * FROM spatial_anchors_current WHERE project_id=? AND location_id IN ({placeholders})"
            + ("" if administrative else " AND discovered=1 AND hidden=0"),
            (project_id, *child_ids),
        )
        anchors = [
            {
                "id": item["id"], "location_id": item["location_id"], "name": item["name"], "kind": item["kind"],
                **({"x": item["x"], "y": item["y"]} if administrative and include_geometry else {}),
                "hidden": bool(item["hidden"]), "discovered": bool(item["discovered"]),
                "enabled": bool(item["enabled"]), "requires_map_review": bool(item["requires_map_review"]),
            }
            for item in anchor_rows
        ]
        anchor_ids = {item["id"] for item in anchors}
        connections: list[dict[str, Any]] = []
        if anchor_ids:
            ph = ",".join("?" for _ in anchor_ids)
            connection_rows = self.db.fetch_all(
                f"SELECT * FROM spatial_connections_current WHERE project_id=? "
                f"AND source_anchor_id IN ({ph}) AND target_anchor_id IN ({ph})"
                + ("" if administrative else " AND discovered=1 AND hidden=0"),
                (project_id, *anchor_ids, *anchor_ids),
            )
            for item in connection_rows:
                connections.append({
                    "id": item["id"], "kind": item["kind"], "source_anchor_id": item["source_anchor_id"],
                    "target_anchor_id": item["target_anchor_id"], "travel_minutes": item["travel_minutes"],
                    "modes": json.loads(item["modes_json"] or "[]"), "bidirectional": bool(item["bidirectional"]),
                    "requirements": json.loads(item["requirements_json"]) if item["requirements_json"] else None,
                    "lock": json.loads(item["lock_json"]) if item["lock_json"] else None,
                    "hidden": bool(item["hidden"]), "discovered": bool(item["discovered"]), "enabled": bool(item["enabled"]),
                })

        barrier_rows = self.db.fetch_all(
            "SELECT * FROM spatial_barriers_current WHERE project_id=? AND location_id=?"
            + ("" if administrative else " AND discovered=1 AND hidden=0"),
            (project_id, focus_id),
        )
        barriers: list[dict[str, Any]] = []
        for item in barrier_rows:
            barrier = {
                "id": item["id"], "name": item["name"], "location_id": item["location_id"],
                "blocked_modes": json.loads(item["blocked_modes_json"] or "[]"),
                "requirements": json.loads(item["requirements_json"]) if item["requirements_json"] else None,
                "hidden": bool(item["hidden"]), "discovered": bool(item["discovered"]),
                "enabled": bool(item["enabled"]), "requires_map_review": bool(item["requires_map_review"]),
            }
            if administrative and include_geometry and item["geometry_kind"]:
                points = self.db.fetch_all(
                    "SELECT x,y FROM spatial_barrier_vertices WHERE barrier_id=? ORDER BY position",
                    (item["id"],),
                )
                barrier["geometry"] = {
                    "location_id": item["location_id"],
                    "kind": item["geometry_kind"],
                    "points": [{"x": point["x"], "y": point["y"]} for point in points],
                }
            barriers.append(barrier)

        return {
            "enabled": True,
            "root_location_id": state["root_location_id"],
            "location_id": focus_id,
            "topology": focus["topology"],
            "revision": int(state["revision"]),
            "source_head_node_id": state.get("source_head_node_id"),
            "locations": locations,
            "anchors": anchors,
            "connections": connections,
            "barriers": barriers,
        }

    def counts(self, project_id: str) -> dict[str, int]:
        tables = {
            "locations": "spatial_locations",
            "anchors": "spatial_anchors_current",
            "barriers": "spatial_barriers_current",
            "connections": "spatial_connections_current",
            "encounters": "spatial_encounter_rules_current",
            "itineraries": "spatial_itineraries_current",
        }
        result: dict[str, int] = {}
        for key, table in tables.items():
            row = self.db.fetch_one(f"SELECT COUNT(*) AS count FROM {table} WHERE project_id=?", (project_id,))
            result[key] = int((row or {}).get("count", 0))
        return result
