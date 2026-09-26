from __future__ import annotations

import base64
import hashlib
import json
import math
from typing import Any

from app.data.spatialV3Repository import SpatialV3Repository
from app.services.spatial_v3 import SpatialV3Error, SpatialV3Service
from app.services.spatial_v3_pathfinding import SpatialV3Pathfinder


class SpatialV3TravelPreview:
    """Deterministic encounter traversal over a Spatial V3 route.

    This is intentionally side-effect free. It returns either a completed
    preview or the first encounter interruption plus an opaque resume cursor.
    Production story travel can adopt the same contract after V3 is proven.
    """

    def __init__(self, repository: SpatialV3Repository) -> None:
        self.repository = repository
        self.resolver = SpatialV3Service(repository)
        self.pathfinder = SpatialV3Pathfinder(repository)

    @staticmethod
    def _stable_uniform(*parts: Any) -> float:
        raw = "|".join(str(part) for part in parts).encode("utf-8")
        integer = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
        # Strictly inside (0, 1) so log/threshold operations stay well-defined.
        return (integer + 0.5) / (2**64)

    @staticmethod
    def _route_signature(route: dict[str, Any]) -> str:
        payload = {
            "start": route["start"],
            "target": route["target"],
            "steps": route["steps"],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _encode_cursor(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(token: str) -> dict[str, Any]:
        try:
            padded = token + "=" * (-len(token) % 4)
            value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        except Exception as exc:
            raise SpatialV3Error("Invalid Spatial V3 resume cursor") from exc
        if not isinstance(value, dict):
            raise SpatialV3Error("Invalid Spatial V3 resume cursor")
        return value

    def _distance_policy_signature(
        self,
        project_id: str,
        step: dict[str, Any],
    ) -> tuple[Any, ...]:
        space_id = str(step["navigation_space_id"])
        active_feature_ids = {
            *[str(item) for item in step.get("surface_ids", [])],
            *[str(item) for item in step.get("corridor_ids", [])],
        }
        policies = [
            policy
            for policy in self.repository.encounter_policies(project_id, space_id)
            if policy.enabled
            and str(policy.trigger_kind) == "distance"
            and (
                policy.navigation_space_id == space_id
                or policy.feature_id in active_feature_ids
            )
        ]
        return tuple(
            (
                policy.id,
                str(policy.mode),
                float(policy.priority),
                float(policy.minimum_distance),
                bool(policy.conditions),
                tuple(
                    (candidate.location_id, float(candidate.weight), bool(candidate.requirements))
                    for candidate in policy.candidates
                ),
            )
            for policy in policies
        )

    def _units(
        self,
        project_id: str,
        route: dict[str, Any],
    ) -> list[dict[str, Any]]:
        units: list[dict[str, Any]] = []
        for route_step_index, step in enumerate(route["steps"]):
            if step["kind"] == "connector":
                units.append({
                    "kind": "connector",
                    "route_step_indices": [route_step_index],
                    "step": step,
                    "distance": 0.0,
                })
                continue

            signature = self._distance_policy_signature(project_id, step)
            space_id = str(step["navigation_space_id"])
            can_merge = (
                units
                and units[-1]["kind"] == "movement"
                and units[-1]["navigation_space_id"] == space_id
                and units[-1]["policy_signature"] == signature
            )
            if not can_merge:
                units.append({
                    "kind": "movement",
                    "navigation_space_id": space_id,
                    "policy_signature": signature,
                    "route_step_indices": [],
                    "parts": [],
                    "distance": 0.0,
                })
            unit = units[-1]
            unit["route_step_indices"].append(route_step_index)
            unit["parts"].append(step)
            unit["distance"] += float(step.get("distance") or 0)
        return units

    @staticmethod
    def _point_along(unit: dict[str, Any], distance: float) -> dict[str, Any]:
        remaining = max(0.0, float(distance))
        cumulative = 0.0
        for part in unit["parts"]:
            part_distance = float(part.get("distance") or 0)
            if remaining <= part_distance + 1e-9:
                ratio = 0.0 if part_distance <= 1e-12 else max(0.0, min(1.0, remaining / part_distance))
                start = part["start"]
                end = part["end"]
                point = [
                    float(start[0]) + (float(end[0]) - float(start[0])) * ratio,
                    float(start[1]) + (float(end[1]) - float(start[1])) * ratio,
                ]
                return {
                    "navigation_space_id": part["navigation_space_id"],
                    "point": point,
                    "route_step_index": unit["route_step_indices"][unit["parts"].index(part)],
                    "distance_into_step": min(remaining, part_distance),
                    "distance_into_span": cumulative + min(remaining, part_distance),
                }
            remaining -= part_distance
            cumulative += part_distance
        last = unit["parts"][-1]
        return {
            "navigation_space_id": last["navigation_space_id"],
            "point": [float(last["end"][0]), float(last["end"][1])],
            "route_step_index": unit["route_step_indices"][-1],
            "distance_into_step": float(last.get("distance") or 0),
            "distance_into_span": float(unit["distance"]),
        }

    @staticmethod
    def _weighted_candidate(
        candidates: list[dict[str, Any]],
        uniform: float,
    ) -> dict[str, Any] | None:
        total = sum(float(item.get("weight") or 0) for item in candidates)
        if total <= 0:
            return None
        cursor = uniform * total
        cumulative = 0.0
        for item in candidates:
            cumulative += float(item.get("weight") or 0)
            if cursor < cumulative:
                return item
        return candidates[-1] if candidates else None

    def _movement_context(self, project_id: str, unit: dict[str, Any]) -> dict[str, Any]:
        first = unit["parts"][0]
        start = first["start"]
        end = first["end"]
        x = (float(start[0]) + float(end[0])) / 2
        y = (float(start[1]) + float(end[1])) / 2
        return self.resolver.encounter_context(
            project_id=project_id,
            navigation_space_id=unit["navigation_space_id"],
            x=x,
            y=y,
            distance=float(unit["distance"]),
        )

    def preview(
        self,
        *,
        project_id: str,
        start_space_id: str,
        start: tuple[float, float],
        target_space_id: str,
        target: tuple[float, float],
        seed: str,
        resume_cursor: str | None = None,
    ) -> dict[str, Any]:
        route = self.pathfinder.plan(
            project_id=project_id,
            start_space_id=start_space_id,
            start=start,
            target_space_id=target_space_id,
            target=target,
        )
        route_signature = self._route_signature(route)
        units = self._units(project_id, route)

        unit_index = 0
        distance_offset = 0.0
        encounter_ordinal = 0
        if resume_cursor:
            cursor = self._decode_cursor(resume_cursor)
            if cursor.get("route_signature") != route_signature:
                raise SpatialV3Error("Resume cursor does not match the current route")
            if cursor.get("seed_hash") != hashlib.sha256(seed.encode("utf-8")).hexdigest():
                raise SpatialV3Error("Resume cursor was created with a different seed")
            unit_index = int(cursor.get("unit_index", 0))
            distance_offset = float(cursor.get("distance_offset", 0))
            encounter_ordinal = int(cursor.get("encounter_ordinal", 0))
            if unit_index < 0 or unit_index > len(units) or distance_offset < 0 or encounter_ordinal < 0:
                raise SpatialV3Error("Invalid Spatial V3 resume cursor state")

        unresolved: list[dict[str, Any]] = []
        traversed_distance = sum(float(unit.get("distance") or 0) for unit in units[:unit_index])
        traversed_cost = 0.0
        for prior in units[:unit_index]:
            if prior["kind"] == "connector":
                traversed_cost += float(prior["step"].get("travel_cost") or 0)
            else:
                traversed_cost += sum(float(part.get("travel_cost") or 0) for part in prior["parts"])

        for index in range(unit_index, len(units)):
            unit = units[index]
            current_offset = distance_offset if index == unit_index else 0.0
            current_ordinal = encounter_ordinal if index == unit_index else 0

            if unit["kind"] == "connector":
                step = unit["step"]
                context = self.resolver.transition_encounter_context(
                    project_id=project_id,
                    navigation_space_id=str(step["source_space_id"]),
                    feature_id=str(step["feature_id"]),
                )
                unresolved.extend(context.get("unresolved_conditions", []))
                unresolved.extend(context.get("unresolved_candidates", []))
                candidates = context.get("candidates", [])
                probability = float(context.get("probability") or 0)
                roll = self._stable_uniform(seed, route_signature, index, "transition")
                if candidates and probability > 0 and roll < probability:
                    selected = self._weighted_candidate(
                        candidates,
                        self._stable_uniform(seed, route_signature, index, "candidate"),
                    )
                    next_cursor = self._encode_cursor({
                        "route_signature": route_signature,
                        "seed_hash": hashlib.sha256(seed.encode("utf-8")).hexdigest(),
                        "unit_index": index + 1,
                        "distance_offset": 0,
                        "encounter_ordinal": 0,
                    })
                    return {
                        "status": "interrupted",
                        "route": route,
                        "route_signature": route_signature,
                        "encounter": {
                            "trigger_kind": "transition",
                            "candidate": selected,
                            "probability": probability,
                            "roll": roll,
                            "policy_ids": context.get("policy_ids", []),
                            "feature_id": step["feature_id"],
                            "navigation_space_id": step["source_space_id"],
                            "point": step["source"],
                            "route_step_index": unit["route_step_indices"][0],
                        },
                        "resume_cursor": next_cursor,
                        "progress": {
                            "traversed_distance": traversed_distance,
                            "traversed_travel_cost": traversed_cost,
                        },
                        "unresolved_requirements": unresolved,
                    }
                traversed_cost += float(step.get("travel_cost") or 0)
                distance_offset = 0.0
                encounter_ordinal = 0
                continue

            context = self._movement_context(project_id, unit)
            unresolved.extend(context.get("unresolved_conditions", []))
            unresolved.extend(context.get("unresolved_candidates", []))
            rate = float(context.get("rate_per_100_units") or 0)
            candidates = context.get("candidates", [])
            span_distance = float(unit["distance"])
            if current_offset > span_distance + 1e-9:
                raise SpatialV3Error("Resume cursor distance is outside its encounter span")

            if rate > 0 and candidates:
                rate_per_unit = rate / 100.0
                u = self._stable_uniform(
                    seed,
                    route_signature,
                    index,
                    current_ordinal,
                    "distance",
                )
                interval = -math.log(1.0 - u) / rate_per_unit
                event_distance = current_offset + interval
                if event_distance <= span_distance + 1e-9:
                    position = self._point_along(unit, event_distance)
                    selected = self._weighted_candidate(
                        candidates,
                        self._stable_uniform(
                            seed,
                            route_signature,
                            index,
                            current_ordinal,
                            "candidate",
                        ),
                    )
                    # Cost progress is accumulated exactly to the encounter point.
                    partial_cost = 0.0
                    remaining = event_distance
                    for part in unit["parts"]:
                        part_distance = float(part.get("distance") or 0)
                        consumed = min(remaining, part_distance)
                        if consumed > 0 and part_distance > 0:
                            partial_cost += float(part.get("travel_cost") or 0) * (consumed / part_distance)
                        remaining -= consumed
                        if remaining <= 1e-9:
                            break
                    next_cursor = self._encode_cursor({
                        "route_signature": route_signature,
                        "seed_hash": hashlib.sha256(seed.encode("utf-8")).hexdigest(),
                        "unit_index": index,
                        "distance_offset": event_distance,
                        "encounter_ordinal": current_ordinal + 1,
                    })
                    return {
                        "status": "interrupted",
                        "route": route,
                        "route_signature": route_signature,
                        "encounter": {
                            "trigger_kind": "distance",
                            "candidate": selected,
                            "rate_per_100_units": rate,
                            "policy_ids": context.get("policy_ids", []),
                            **position,
                        },
                        "resume_cursor": next_cursor,
                        "progress": {
                            "traversed_distance": traversed_distance + event_distance,
                            "traversed_travel_cost": traversed_cost + partial_cost,
                        },
                        "unresolved_requirements": unresolved,
                    }

            # Progress is always reported from the start of the route.
            # The accumulator excludes the current unit, so after a resumed
            # span completes we add the whole span rather than only the
            # unconsumed suffix.
            traversed_distance += span_distance
            traversed_cost += sum(
                float(part.get("travel_cost") or 0)
                for part in unit["parts"]
            )
            distance_offset = 0.0
            encounter_ordinal = 0

        return {
            "status": "complete",
            "route": route,
            "route_signature": route_signature,
            "encounter": None,
            "resume_cursor": None,
            "progress": {
                "traversed_distance": route["total_distance"],
                "traversed_travel_cost": route["total_travel_cost"],
            },
            "unresolved_requirements": unresolved,
        }
