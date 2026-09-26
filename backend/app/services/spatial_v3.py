from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Callable

try:
    from shapely.geometry import Point, shape
    from shapely.geometry.base import BaseGeometry
except ImportError:  # pragma: no cover - exercised only without optional deps.
    Point = shape = None  # type: ignore[assignment]
    BaseGeometry = Any  # type: ignore[misc,assignment]

from app.domain.spatial_v3 import (
    CorridorProperties,
    EncounterPolicy,
    MapFeature,
    NavigationSpace,
    SurfaceProperties,
)
from app.data.spatialV3Repository import SpatialV3Repository


class SpatialV3Error(ValueError):
    pass


def _require_geometry() -> None:
    if Point is None or shape is None:
        raise SpatialV3Error(
            "Spatial V3 geometry requires Shapely; install backend requirements and restart StoryStudio"
        )


class SpatialV3Service:
    """Experimental resolver for the parallel Spatial V3 model.

    This service intentionally does not replace SpatialService yet. It exists so
    V3 geometry/traversal/encounter semantics can be exercised side-by-side
    before the legacy runtime is removed.
    """

    def __init__(
        self,
        repository: SpatialV3Repository,
        *,
        condition_evaluator: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self.repository = repository
        self.condition_evaluator = condition_evaluator

    def _condition_state(self, payload: dict[str, Any] | None) -> bool | None:
        if not payload:
            return True
        if self.condition_evaluator is None:
            return None
        try:
            return bool(self.condition_evaluator(dict(payload)))
        except (ValueError, TypeError):
            return None

    def _encounter_contributors(
        self,
        policies: list[EncounterPolicy],
    ) -> tuple[list[EncounterPolicy], list[dict[str, Any]], bool]:
        contributors: list[EncounterPolicy] = []
        unresolved: list[dict[str, Any]] = []
        disabled = False
        states: dict[str, bool | None] = {}
        for policy in policies:
            state = self._condition_state(policy.conditions)
            states[policy.id] = state
            if state is False:
                continue
            mode = str(policy.mode)
            if mode == "disabled":
                contributors = []
                disabled = True
                if state is None:
                    unresolved.append(policy.model_dump(mode="json"))
                continue
            if mode == "replace":
                contributors = []
                disabled = False
            if mode in {"replace", "augment"}:
                contributors.append(policy)
                if state is None:
                    unresolved.append(policy.model_dump(mode="json"))

        active = [
            policy
            for policy in contributors
            if states.get(policy.id) is True
        ]
        return active, unresolved, disabled and not contributors

    def _candidate_allowed(
        self,
        requirements: dict[str, Any] | None,
    ) -> bool | None:
        return self._condition_state(requirements)

    @staticmethod
    def _geometry(feature: MapFeature) -> BaseGeometry:
        _require_geometry()
        geometry = shape(feature.geometry.model_dump(mode="json"))
        if feature.feature_kind == "corridor":
            props = feature.properties
            if not isinstance(props, CorridorProperties):
                raise SpatialV3Error(f"Corridor properties missing for {feature.id}")
            geometry = geometry.buffer(float(props.width) / 2, cap_style=2, join_style=2)
        if geometry.is_empty or not geometry.is_valid:
            raise SpatialV3Error(f"Invalid geometry for feature {feature.id}")
        return geometry

    def point_membership(
        self,
        *,
        project_id: str,
        navigation_space_id: str,
        x: float,
        y: float,
    ) -> dict[str, Any]:
        """Return every feature containing/touching a point.

        Unlike Map V2 area resolution, this never picks one semantic winner.
        City + district + road may all be present at the same coordinate.
        """
        _require_geometry()
        point = Point(float(x), float(y))
        features = [
            item
            for item in self.repository.features(project_id, navigation_space_id)
            if item.enabled
        ]
        containing: list[MapFeature] = []
        touching_barriers: list[MapFeature] = []
        spots: list[MapFeature] = []
        connectors: list[MapFeature] = []
        for feature in features:
            geometry = self._geometry(feature)
            if feature.feature_kind in {"surface", "corridor"} and geometry.covers(point):
                containing.append(feature)
            elif feature.feature_kind == "barrier" and geometry.distance(point) <= 1e-7:
                touching_barriers.append(feature)
            elif feature.feature_kind == "spot" and geometry.distance(point) <= 1e-7:
                spots.append(feature)
            elif feature.feature_kind == "connector" and geometry.distance(point) <= 1e-7:
                connectors.append(feature)

        containing.sort(
            key=lambda item: (
                str(item.render_layer),
                float(item.render_order),
                str(item.id),
            )
        )
        return {
            "navigation_space_id": navigation_space_id,
            "surfaces": [
                item.model_dump(mode="json")
                for item in containing
                if item.feature_kind == "surface"
            ],
            "corridors": [
                item.model_dump(mode="json")
                for item in containing
                if item.feature_kind == "corridor"
            ],
            "barriers": [item.model_dump(mode="json") for item in touching_barriers],
            "spots": [item.model_dump(mode="json") for item in spots],
            "connectors": [item.model_dump(mode="json") for item in connectors],
            "semantic_location_ids": list(dict.fromkeys(
                item.semantic_location_id
                for item in containing
                if item.semantic_location_id
            )),
        }

    def movement_context(
        self,
        *,
        project_id: str,
        navigation_space_id: str,
        x: float,
        y: float,
    ) -> dict[str, Any]:
        """Resolve movement without discarding overlapping memberships.

        The highest movement_priority traversable feature supplies the local
        movement policy. This is deliberately separate from semantic/render
        ordering: a road can override river/forest movement while the actor
        remains inside every overlapping semantic region.
        """
        space = self.repository.space(navigation_space_id)
        if not space or space.project_id != project_id:
            raise SpatialV3Error("Navigation space not found")
        membership = self.point_membership(
            project_id=project_id,
            navigation_space_id=navigation_space_id,
            x=x,
            y=y,
        )
        traversable = [
            *membership["surfaces"],
            *membership["corridors"],
        ]
        features = [MapFeature.model_validate(item) for item in traversable]
        features.sort(
            key=lambda item: (
                float(item.movement_priority),
                float(item.render_order),
                str(item.id),
            ),
            reverse=True,
        )

        # Free maps permit unassigned base space. Routed maps are void unless a
        # surface/corridor explicitly supplies occupiable space.
        allowed = str(space.navigation_mode) == "free"
        multiplier = float(space.base_travel_multiplier)
        source_feature_id: str | None = None
        alternatives: list[dict[str, Any]] = []

        if features:
            winner = features[0]
            props = winner.properties
            if isinstance(props, (SurfaceProperties, CorridorProperties)):
                policy = props.traversal
                allowed = bool(policy.default_allowed)
                multiplier *= float(policy.travel_multiplier)
                alternatives = [
                    option.model_dump(mode="json") for option in policy.options
                ]
                source_feature_id = winner.id

        return {
            **membership,
            "navigation_mode": str(space.navigation_mode),
            "movement": {
                "default_allowed": allowed,
                "travel_multiplier": multiplier,
                "source_feature_id": source_feature_id,
                "conditional_options": alternatives,
            },
        }

    def encounter_context(
        self,
        *,
        project_id: str,
        navigation_space_id: str,
        x: float,
        y: float,
        distance: float,
    ) -> dict[str, Any]:
        """Resolve layered random-encounter contributors for travel distance.

        rate_per_100_units is treated as a Poisson expectation, so the chance
        of at least one encounter over distance d is:
            1 - exp(-(rate / 100) * d)

        Conditions/requirements are retained in the result for the later shared
        Requirements V2 evaluator; unconditional policies resolve immediately.
        """
        if distance < 0:
            raise SpatialV3Error("Encounter distance cannot be negative")
        membership = self.point_membership(
            project_id=project_id,
            navigation_space_id=navigation_space_id,
            x=x,
            y=y,
        )
        active_feature_ids = {
            item["id"]
            for item in [*membership["surfaces"], *membership["corridors"]]
        }
        policies = [
            policy
            for policy in self.repository.encounter_policies(
                project_id,
                navigation_space_id,
            )
            if policy.enabled
            and str(policy.trigger_kind) == "distance"
            and (
                policy.navigation_space_id == navigation_space_id
                or policy.feature_id in active_feature_ids
            )
            and distance >= policy.minimum_distance
        ]
        policies.sort(key=lambda item: (float(item.priority), str(item.id)))

        active, unresolved, disabled = self._encounter_contributors(policies)

        if disabled:
            return {
                "enabled": False,
                "rate_per_100_units": 0,
                "probability": 0,
                "candidates": [],
                "policy_ids": [policy.id for policy in policies],
                "unresolved_conditions": unresolved,
                "unresolved_candidates": [],
            }

        rate = sum(float(policy.rate_per_100_units) for policy in active)
        probability = 0.0 if rate <= 0 or distance <= 0 else (
            1 - math.exp(-(rate / 100.0) * float(distance))
        )

        candidate_weights: dict[str, float] = defaultdict(float)
        candidate_sources: dict[str, list[str]] = defaultdict(list)
        unresolved_candidates: list[dict[str, Any]] = []
        for policy in active:
            for candidate in policy.candidates:
                state = self._candidate_allowed(candidate.requirements)
                if state is None:
                    unresolved_candidates.append({
                        "policy_id": policy.id,
                        "candidate": candidate.model_dump(mode="json"),
                    })
                    continue
                if state is False:
                    continue
                candidate_weights[candidate.location_id] += float(candidate.weight)
                candidate_sources[candidate.location_id].append(policy.id)

        candidates = [
            {
                "location_id": location_id,
                "weight": weight,
                "policy_ids": candidate_sources[location_id],
            }
            for location_id, weight in candidate_weights.items()
        ]
        candidates.sort(key=lambda item: (-item["weight"], item["location_id"]))

        return {
            "enabled": bool(active),
            "rate_per_100_units": rate,
            "probability": probability,
            "candidates": candidates,
            "policy_ids": [policy.id for policy in active],
            "unresolved_conditions": unresolved,
            "unresolved_candidates": unresolved_candidates,
        }


    def transition_encounter_context(
        self,
        *,
        project_id: str,
        navigation_space_id: str,
        feature_id: str,
    ) -> dict[str, Any]:
        """Resolve a one-roll encounter for a connector/feature transition."""
        feature = self.repository.feature(feature_id)
        if not feature or feature.project_id != project_id:
            raise SpatialV3Error("Transition feature not found")
        if feature.feature_kind == "connector":
            props = feature.properties
            if not hasattr(props, "source") or navigation_space_id not in {
                props.source.navigation_space_id,
                props.target.navigation_space_id,
            }:
                raise SpatialV3Error("Transition feature is not reachable from this navigation space")
        elif feature.navigation_space_id != navigation_space_id:
            raise SpatialV3Error("Transition feature not found")

        policies = [
            policy
            for policy in self.repository.encounter_policies_for_transition(
                project_id,
                navigation_space_id,
                feature_id,
            )
            if policy.enabled
            and str(policy.trigger_kind) == "transition"
            and (
                policy.navigation_space_id == navigation_space_id
                or policy.feature_id == feature_id
            )
        ]
        policies.sort(key=lambda item: (float(item.priority), str(item.id)))

        active, unresolved, disabled = self._encounter_contributors(policies)

        if disabled:
            return {
                "enabled": False,
                "probability": 0,
                "candidates": [],
                "policy_ids": [policy.id for policy in policies],
                "unresolved_conditions": unresolved,
                "unresolved_candidates": [],
            }

        # Multiple augmenting transition probabilities are independent chances.
        no_encounter = 1.0
        candidate_weights: dict[str, float] = defaultdict(float)
        candidate_sources: dict[str, list[str]] = defaultdict(list)
        unresolved_candidates: list[dict[str, Any]] = []
        for policy in active:
            probability = float(policy.probability_per_transition or 0)
            no_encounter *= 1 - probability
            for candidate in policy.candidates:
                state = self._candidate_allowed(candidate.requirements)
                if state is None:
                    unresolved_candidates.append({
                        "policy_id": policy.id,
                        "candidate": candidate.model_dump(mode="json"),
                    })
                    continue
                if state is False:
                    continue
                candidate_weights[candidate.location_id] += float(candidate.weight)
                candidate_sources[candidate.location_id].append(policy.id)

        candidates = [
            {
                "location_id": location_id,
                "weight": weight,
                "policy_ids": candidate_sources[location_id],
            }
            for location_id, weight in candidate_weights.items()
        ]
        candidates.sort(key=lambda item: (-item["weight"], item["location_id"]))
        return {
            "enabled": bool(active),
            "probability": 1 - no_encounter,
            "candidates": candidates,
            "policy_ids": [policy.id for policy in active],
            "unresolved_conditions": unresolved,
            "unresolved_candidates": unresolved_candidates,
        }
