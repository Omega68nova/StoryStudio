from __future__ import annotations

import math
from typing import Any

from app.data.spatialV3Repository import SpatialV3Repository
from app.domain.spatial_v3 import (
    BarrierProperties,
    ConnectorEndpoint,
    ConnectorProperties,
    CorridorProperties,
    EncounterCandidate,
    EncounterPolicy,
    MapFeature,
    NavigationLayer,
    NavigationSpace,
    PointGeometry,
    SpotProperties,
    SurfaceProperties,
    TraversalOption,
    TraversalPolicy,
)


class SpatialV3Migration:
    """Legacy spatial -> V3 adapter used only during the parallel trial.

    It deliberately prefers deterministic IDs and explicit warnings over
    silently guessing semantics that did not exist in the old model.
    """

    def __init__(self, repository: SpatialV3Repository) -> None:
        self.repository = repository

    @staticmethod
    def space_id(location_id: str) -> str:
        return f"v3-space:{location_id}"

    @staticmethod
    def location_feature_id(location_id: str) -> str:
        return f"v3-location:{location_id}"

    @staticmethod
    def barrier_feature_id(barrier_id: str) -> str:
        return f"v3-barrier:{barrier_id}"

    @staticmethod
    def connection_feature_id(connection_id: str) -> str:
        return f"v3-connection:{connection_id}"

    @staticmethod
    def encounter_policy_id(rule_id: str) -> str:
        return f"v3-encounter:{rule_id}"

    @staticmethod
    def _location_rows(projection: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(key): value
            for key, value in projection.get("entities", {}).items()
            if value.get("kind") == "location"
            and not value.get("state", {}).get("archived")
        }

    @staticmethod
    def _point_from_location(location: dict[str, Any]) -> tuple[float, float] | None:
        state = location.get("state", {})
        footprint = state.get("footprint")
        if isinstance(footprint, dict):
            points = footprint.get("points") or []
            if points and all(isinstance(points[0].get(key), (int, float)) for key in ("x", "y")):
                return float(points[0]["x"]), float(points[0]["y"])
        if isinstance(state.get("x"), (int, float)) and isinstance(state.get("y"), (int, float)):
            return float(state["x"]), float(state["y"])
        return None

    @staticmethod
    def _polygon_from_legacy(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict) or raw.get("kind") != "polygon":
            return None
        points = raw.get("points") or []
        if len(points) < 3:
            return None
        ring = [
            (float(item["x"]), float(item["y"]))
            for item in points
            if isinstance(item, dict)
            and isinstance(item.get("x"), (int, float))
            and isinstance(item.get("y"), (int, float))
        ]
        if len(ring) < 3:
            return None
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return {"type": "Polygon", "coordinates": [ring]}

    @staticmethod
    def _line_from_legacy(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        points = raw.get("points") or []
        coords = [
            (float(item["x"]), float(item["y"]))
            for item in points
            if isinstance(item, dict)
            and isinstance(item.get("x"), (int, float))
            and isinstance(item.get("y"), (int, float))
        ]
        if len(coords) < 2:
            return None
        if raw.get("kind") == "polygon" and coords[0] != coords[-1]:
            coords.append(coords[0])
        return {"type": "LineString", "coordinates": coords}

    @staticmethod
    def _surface_traversal(state: dict[str, Any]) -> TraversalPolicy:
        if state.get("boundary_access") == "connection_required":
            return TraversalPolicy(default_allowed=False)
        return TraversalPolicy(default_allowed=True)

    @staticmethod
    def _legacy_requirement_option(raw: Any, label: str = "Legacy requirement") -> list[TraversalOption]:
        if not isinstance(raw, dict):
            return []
        return [
            TraversalOption(
                key="legacy-requirement",
                label=label,
                requirements={"schema_version": 1, **raw},
            )
        ]

    def preview(
        self,
        project_id: str,
        projection: dict[str, Any],
    ) -> dict[str, Any]:
        locations = self._location_rows(projection)
        root_id = str(projection.get("root_location_id") or "")
        children: dict[str, list[str]] = {}
        for location_id, location in locations.items():
            parent = str(location.get("state", {}).get("parent_location_id") or "")
            if parent:
                children.setdefault(parent, []).append(location_id)

        warnings: list[dict[str, str]] = []
        spaces: list[NavigationSpace] = []
        bindings: list[dict[str, Any]] = []
        space_owners: set[str] = set()

        for location_id, location in locations.items():
            state = location.get("state", {})
            owns_space = (
                location_id == root_id
                or bool(children.get(location_id))
                or state.get("occupancy") == "child_required"
                or bool(state.get("local_bounds"))
            )
            if not owns_space:
                continue
            bounds = self._polygon_from_legacy(state.get("local_bounds"))
            if state.get("local_bounds") and bounds is None:
                warnings.append({
                    "kind": "bounds",
                    "id": location_id,
                    "message": "Legacy local bounds could not be losslessly converted to Polygon/MultiPolygon.",
                })
            mode = "free" if state.get("topology") == "open" else "routed"
            space = NavigationSpace(
                id=self.space_id(location_id),
                project_id=project_id,
                owner_location_id=location_id,
                navigation_mode=mode,
                base_travel_multiplier=max(0.0001, float(state.get("minutes_per_unit") or 1)),
                bounds=bounds,
            )
            spaces.append(space)
            space_owners.add(location_id)
            bindings.append({
                "project_id": project_id,
                "location_id": location_id,
                "navigation_space_id": space.id,
                "entrance_policy": "connectors" if state.get("boundary_access") == "connection_required" else "open",
                "bounds_mode": "independent" if bounds else "inherit_parent",
            })

        features: list[MapFeature] = []
        location_feature_by_id: dict[str, str] = {}

        for location_id, location in locations.items():
            state = location.get("state", {})
            parent_id = str(state.get("parent_location_id") or "")
            if not parent_id:
                continue
            if parent_id not in space_owners:
                warnings.append({
                    "kind": "placement",
                    "id": location_id,
                    "message": f"Parent {parent_id} has no inferred V3 navigation space; placement was skipped.",
                })
                continue

            feature_id = self.location_feature_id(location_id)
            if state.get("spatial_kind") == "area":
                geometry = self._polygon_from_legacy(state.get("footprint"))
                if geometry is None:
                    warnings.append({
                        "kind": "geometry",
                        "id": location_id,
                        "message": "Legacy area is degenerate or missing geometry and needs V3 review.",
                    })
                    continue
                priority = -float(state.get("priority_layer") or 0)
                feature = MapFeature(
                    id=feature_id,
                    project_id=project_id,
                    navigation_space_id=self.space_id(parent_id),
                    semantic_location_id=location_id,
                    feature_kind="surface",
                    name=str(location.get("name") or ""),
                    geometry=geometry,
                    render_layer="regions",
                    render_order=priority,
                    movement_priority=priority,
                    hidden=bool(state.get("hidden", False)),
                    discovered=bool(state.get("discovered", True)),
                    enabled=bool(state.get("enabled", True)),
                    metadata={
                        "legacy_spatial_kind": "area",
                        "legacy_exposure": state.get("exposure", "outdoor"),
                        "requires_v3_review": bool(state.get("requires_map_review", False)),
                    },
                    properties=SurfaceProperties(
                        traversal=self._surface_traversal(state),
                        ambience_tags=[str(state.get("exposure") or "outdoor")],
                        environment_tags=[str(state.get("exposure") or "outdoor")],
                    ),
                )
            else:
                point = self._point_from_location(location)
                if point is None:
                    warnings.append({
                        "kind": "geometry",
                        "id": location_id,
                        "message": "Legacy spot has no coordinate and needs V3 placement.",
                    })
                    continue
                feature = MapFeature(
                    id=feature_id,
                    project_id=project_id,
                    navigation_space_id=self.space_id(parent_id),
                    semantic_location_id=location_id,
                    feature_kind="spot",
                    name=str(location.get("name") or ""),
                    geometry=PointGeometry(coordinates=point),
                    render_layer="places",
                    hidden=bool(state.get("hidden", False)),
                    discovered=bool(state.get("discovered", True)),
                    enabled=bool(state.get("enabled", True)),
                    metadata={
                        "legacy_spatial_kind": "spot",
                        "legacy_exposure": state.get("exposure", "outdoor"),
                    },
                    properties=SpotProperties(),
                )
            features.append(feature)
            location_feature_by_id[location_id] = feature_id

        # Old barriers already map cleanly to the V3 crossing primitive.
        for barrier_id, raw in projection.get("map_barriers", {}).items():
            owner_id = str(raw.get("location_id") or "")
            if owner_id not in space_owners:
                warnings.append({
                    "kind": "barrier",
                    "id": str(barrier_id),
                    "message": "Barrier owner has no V3 navigation space.",
                })
                continue
            geometry = self._line_from_legacy(raw.get("geometry"))
            if geometry is None:
                warnings.append({
                    "kind": "barrier",
                    "id": str(barrier_id),
                    "message": "Barrier geometry could not be converted.",
                })
                continue
            requirements = raw.get("requirements")
            traversal = TraversalPolicy(
                default_allowed=False,
                options=self._legacy_requirement_option(requirements, "Cross barrier"),
            )
            features.append(MapFeature(
                id=self.barrier_feature_id(str(barrier_id)),
                project_id=project_id,
                navigation_space_id=self.space_id(owner_id),
                feature_kind="barrier",
                name=str(raw.get("name") or "Barrier"),
                geometry=geometry,
                render_layer="barriers",
                hidden=bool(raw.get("hidden", False)),
                discovered=bool(raw.get("discovered", True)),
                enabled=bool(raw.get("enabled", True)),
                metadata={
                    "legacy_barrier_id": str(barrier_id),
                    "legacy_blocked_modes": list(raw.get("blocked_modes") or ["walk"]),
                },
                properties=BarrierProperties(traversal=traversal),
            ))

        anchors = projection.get("map_anchors", {})

        def endpoint(anchor_id: str) -> tuple[str, tuple[float, float]] | None:
            raw = anchors.get(anchor_id)
            if not raw:
                return None
            owner_id = str(raw.get("coordinate_space_id") or raw.get("location_id") or "")
            if owner_id not in space_owners:
                return None
            x, y = raw.get("x"), raw.get("y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                location = locations.get(str(raw.get("binding_target_id") or raw.get("location_id") or ""))
                point = self._point_from_location(location or {})
                if point is None:
                    return None
                x, y = point
            return self.space_id(owner_id), (float(x), float(y))

        for connection_id, raw in projection.get("travel_connections", {}).items():
            source = endpoint(str(raw.get("source_anchor_id") or ""))
            target = endpoint(str(raw.get("target_anchor_id") or ""))
            if source is None or target is None:
                warnings.append({
                    "kind": "connection",
                    "id": str(connection_id),
                    "message": "Connection endpoints need V3 placement review.",
                })
                continue
            kind = str(raw.get("kind") or "route")
            connector_kind = {
                "door": "door",
                "portal": "portal",
                "route": "generic",
            }.get(kind, "generic")
            traversal = TraversalPolicy(
                default_allowed=not bool((raw.get("lock") or {}).get("locked")),
                options=self._legacy_requirement_option(raw.get("requirements"), "Use connection"),
            )
            feature_id = self.connection_feature_id(str(connection_id))
            features.append(MapFeature(
                id=feature_id,
                project_id=project_id,
                navigation_space_id=source[0],
                feature_kind="connector",
                name=str(raw.get("name") or kind.title()),
                geometry=PointGeometry(coordinates=source[1]),
                render_layer="connections",
                hidden=bool(raw.get("hidden", False)),
                discovered=bool(raw.get("discovered", True)),
                enabled=bool(raw.get("enabled", True)),
                metadata={
                    "legacy_connection_id": str(connection_id),
                    "legacy_kind": kind,
                    "legacy_modes": list(raw.get("modes") or ["walk"]),
                    "legacy_lock": raw.get("lock"),
                    "requires_v3_review": kind == "route",
                },
                properties=ConnectorProperties(
                    connector_kind=connector_kind,
                    source=ConnectorEndpoint(
                        navigation_space_id=source[0],
                        point=source[1],
                    ),
                    target=ConnectorEndpoint(
                        navigation_space_id=target[0],
                        point=target[1],
                    ),
                    traversal=traversal,
                    travel_minutes=float(raw.get("travel_minutes") or 0),
                    bidirectional=bool(raw.get("bidirectional", True)),
                ),
            ))
            if kind == "route":
                warnings.append({
                    "kind": "route",
                    "id": str(connection_id),
                    "message": "Legacy zero-width route migrated as a connector; convert to a width-bearing corridor if it represents a physical road/path.",
                })

        encounter_policies: list[EncounterPolicy] = []
        connection_feature_ids = {
            str(key): self.connection_feature_id(str(key))
            for key in projection.get("travel_connections", {})
        }
        for rule_id, raw in projection.get("encounter_rules", {}).items():
            candidates = [
                EncounterCandidate(
                    location_id=str(item["location_id"]),
                    weight=float(item.get("weight") or 1),
                )
                for item in raw.get("candidates") or []
                if item.get("location_id")
            ]
            location_id = str(raw.get("location_id") or "")
            connection_id = str(raw.get("connection_id") or "")
            target_feature = (
                location_feature_by_id.get(location_id)
                if location_id and location_id not in space_owners
                else connection_feature_ids.get(connection_id)
            )
            target_space = (
                self.space_id(location_id)
                if location_id in space_owners
                else None
            )
            if not target_feature and not target_space:
                warnings.append({
                    "kind": "encounter",
                    "id": str(rule_id),
                    "message": "Encounter rule has no V3 feature/space target and needs review.",
                })
                continue
            probability = max(0.0, min(1.0, float(raw.get("probability") or 0)))
            encounter_policies.append(EncounterPolicy(
                id=self.encounter_policy_id(str(rule_id)),
                project_id=project_id,
                navigation_space_id=target_space,
                feature_id=target_feature,
                mode="augment",
                trigger_kind="transition",
                probability_per_transition=probability,
                candidates=candidates,
                enabled=bool(raw.get("enabled", True)),
            ))

        # Preserve the legacy open-map fallback: encounter_rate on a map owner
        # plus random_encounter children meant one roll per geometric segment.
        # V3 keeps that behavior as an explicit transition policy so migration
        # is lossless; authors can later convert it to a distance policy.
        for owner_id in sorted(space_owners):
            owner = locations.get(owner_id, {})
            owner_state = owner.get("state", {})
            probability = max(0.0, min(1.0, float(owner_state.get("encounter_rate") or 0)))
            if probability <= 0:
                continue
            candidates = [
                EncounterCandidate(
                    location_id=child_id,
                    weight=float(
                        locations[child_id].get("state", {}).get("encounter_weight") or 1
                    ),
                )
                for child_id in children.get(owner_id, [])
                if locations[child_id].get("state", {}).get("random_encounter")
            ]
            if not candidates:
                continue
            policy_id = f"v3-legacy-open:{owner_id}"
            if any(item.id == policy_id for item in encounter_policies):
                continue
            encounter_policies.append(EncounterPolicy(
                id=policy_id,
                project_id=project_id,
                navigation_space_id=self.space_id(owner_id),
                mode="augment",
                trigger_kind="transition",
                probability_per_transition=probability,
                candidates=candidates,
            ))
            warnings.append({
                "kind": "encounter",
                "id": owner_id,
                "message": "Legacy encounter_rate preserved as one transition roll; review and convert to distance-based V3 encounters if desired.",
            })

        layers = [
            NavigationLayer(
                navigation_space_id=space.id,
                layer_key=layer_key,
                label=label,
                position=position,
                visible=True,
                labels_mode="important",
            )
            for space in spaces
            for position, (layer_key, label) in enumerate([
                ("topology", "Base / topology"),
                ("regions", "Regions"),
                ("roads", "Roads & corridors"),
                ("places", "Buildings & spots"),
                ("barriers", "Barriers"),
                ("connections", "Connections"),
            ])
        ]

        return {
            "project_id": project_id,
            "spaces": [item.model_dump(mode="json") for item in spaces],
            "location_space_bindings": bindings,
            "features": [item.model_dump(mode="json") for item in features],
            "encounter_policies": [
                item.model_dump(mode="json") for item in encounter_policies
            ],
            "layers": [item.model_dump(mode="json") for item in layers],
            "warnings": warnings,
            "counts": {
                "spaces": len(spaces),
                "features": len(features),
                "encounter_policies": len(encounter_policies),
                "warnings": len(warnings),
            },
        }

    def branch_replacement_mutations(
        self,
        project_id: str,
        projection: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Return a lossless replacement transaction for branch-owned V3 state.

        Existing spaces are removed first. Space removal cascades through the
        V3 event projection, so stale features, layers, bindings and encounters
        cannot survive a re-migration.
        """
        preview = self.preview(project_id, projection)
        current = projection.get("spatial_v3") or {}
        raw: list[dict[str, Any]] = [
            {"tool": "removeSpatialV3Space", "arguments": {"id": space_id}}
            for space_id in sorted(current.get("spaces", {}))
        ]
        raw.extend(
            {"tool": "upsertSpatialV3Space", "arguments": item}
            for item in preview["spaces"]
        )
        raw.extend(
            {"tool": "bindSpatialV3LocationSpace", "arguments": item}
            for item in preview["location_space_bindings"]
        )
        raw.extend(
            {"tool": "upsertSpatialV3Feature", "arguments": item}
            for item in preview["features"]
        )
        raw.extend(
            {"tool": "upsertSpatialV3Encounter", "arguments": item}
            for item in preview["encounter_policies"]
        )
        raw.extend(
            {"tool": "updateSpatialV3Layer", "arguments": item}
            for item in preview["layers"]
        )
        return preview, raw

    def materialize(
        self,
        project_id: str,
        projection: dict[str, Any],
    ) -> dict[str, Any]:
        preview = self.preview(project_id, projection)
        self.repository.clear_project(project_id)
        for raw in preview["spaces"]:
            self.repository.save_space(NavigationSpace.model_validate(raw))
        for raw in preview["location_space_bindings"]:
            self.repository.bind_location_space(**raw)
        for raw in preview["features"]:
            self.repository.save_feature(MapFeature.model_validate(raw))
        for raw in preview["encounter_policies"]:
            self.repository.save_encounter_policy(EncounterPolicy.model_validate(raw))
        for raw in preview["layers"]:
            self.repository.save_layer(NavigationLayer.model_validate(raw))
        return preview
