from __future__ import annotations

from typing import Any

try:
    from shapely.geometry import LineString, Point, shape
except ImportError:  # pragma: no cover
    LineString = Point = shape = None  # type: ignore[assignment]

from app.data.spatialV3Repository import SpatialV3Repository
from app.domain.spatial_v3 import NavigationSpace
from app.services.spatial_v3 import SpatialV3Error, SpatialV3Service
from app.services.spatial_v3_context import (
    SpatialV3ContextError,
    child_to_parent_point,
    inherited_parent_context,
    parent_to_child_point,
)
from app.services.spatial_v3_pathfinding import SpatialV3Pathfinder


class SpatialV3NestingService:
    """Resolve seamless movement across open parent/child Navigation Spaces.

    Connector-only bindings remain explicit transitions. Open bindings behave
    like continuous nested maps whose coordinates are related through the
    inherited parent footprint transform.
    """

    def __init__(self, repository: SpatialV3Repository) -> None:
        self.repository = repository
        self.resolver = SpatialV3Service(repository)
        self.pathfinder = SpatialV3Pathfinder(repository)

    def _space(self, project_id: str, space_id: str) -> NavigationSpace:
        space = self.repository.space(space_id)
        if not space or space.project_id != project_id:
            raise SpatialV3Error(f"Navigation space not found: {space_id}")
        return space

    def _context(self, project_id: str, space: NavigationSpace) -> dict[str, Any] | None:
        try:
            return inherited_parent_context(
                self.repository,
                project_id=project_id,
                space=space,
            )
        except SpatialV3ContextError as exc:
            raise SpatialV3Error(str(exc)) from exc

    def _segment_allowed(
        self,
        project_id: str,
        space_id: str,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> bool:
        # Reuse the pathfinder's canonical barrier, movement-policy and bounds
        # checks for a direct movement segment.
        return self.pathfinder._segment_cost(
            project_id=project_id,
            space_id=space_id,
            start=start,
            end=end,
        ) is not None

    def _open_children(
        self,
        project_id: str,
        parent_space_id: str,
    ) -> list[tuple[NavigationSpace, dict[str, Any]]]:
        result: list[tuple[NavigationSpace, dict[str, Any]]] = []
        for child in self.repository.spaces(project_id):
            if child.id == parent_space_id or not child.owner_location_id:
                continue
            binding = self.repository.location_space(project_id, child.owner_location_id)
            if not binding or str(binding.get("entrance_policy") or "") != "open":
                continue
            context = self._context(project_id, child)
            if context and context["source_space_id"] == parent_space_id:
                result.append((child, context))
        return result

    def resolve_step(
        self,
        *,
        project_id: str,
        space_id: str,
        current: tuple[float, float],
        candidate: tuple[float, float],
    ) -> dict[str, Any]:
        """Resolve one movement step, including implicit open-space transitions."""
        if Point is None or shape is None:
            raise SpatialV3Error("Spatial V3 nesting requires Shapely")

        space = self._space(project_id, space_id)
        current_point = Point(*current)
        candidate_point = Point(*candidate)

        # First handle walking out of an inherited child map. The attempted
        # candidate may be beyond local bounds; map it back to the parent and
        # validate the corresponding parent movement segment.
        binding = (
            self.repository.location_space(project_id, space.owner_location_id)
            if space.owner_location_id
            else None
        )
        context = self._context(project_id, space)
        if (
            binding
            and str(binding.get("entrance_policy") or "") == "open"
            and context is not None
        ):
            child_boundary = shape(context["boundary"])
            if child_boundary.covers(current_point) and not child_boundary.covers(candidate_point):
                parent_space_id = str(context["source_space_id"])
                parent_current = child_to_parent_point(context, current)
                parent_candidate = child_to_parent_point(context, candidate)
                if not self._segment_allowed(
                    project_id,
                    parent_space_id,
                    parent_current,
                    parent_candidate,
                ):
                    return {
                        "allowed": False,
                        "transition": None,
                        "reason": "parent_blocked",
                    }
                parent_context = self.resolver.movement_context(
                    project_id=project_id,
                    navigation_space_id=parent_space_id,
                    x=parent_candidate[0],
                    y=parent_candidate[1],
                )
                if not parent_context["movement"]["default_allowed"]:
                    return {
                        "allowed": False,
                        "transition": None,
                        "reason": "parent_not_walkable",
                    }
                return {
                    "allowed": True,
                    "transition": {
                        "kind": "ascend",
                        "from_space_id": space_id,
                        "to_space_id": parent_space_id,
                    },
                    "space_id": parent_space_id,
                    "point": list(parent_candidate),
                }

        # Ordinary movement inside the current space still needs to be valid
        # before a child-space descent can happen.
        if not self._segment_allowed(project_id, space_id, current, candidate):
            return {
                "allowed": False,
                "transition": None,
                "reason": "blocked",
            }

        # Enter the most specific open child whose parent footprint was crossed.
        matches: list[tuple[NavigationSpace, dict[str, Any], float]] = []
        for child, child_context in self._open_children(project_id, space_id):
            footprint = shape(
                # The parent's original footprint is equivalent to mapping the
                # normalized child boundary back through source/target bounds.
                inherited_parent_context(
                    self.repository,
                    project_id=project_id,
                    space=child,
                )["boundary"]
            )
            # The above boundary lives in child coordinates. Use the owner's
            # parent-space Surface(s) for the actual crossing test.
            source_ids = set(child_context["source_feature_ids"])
            source_shapes = [
                shape(feature.geometry.model_dump(mode="json"))
                for feature in self.repository.features(project_id, space_id)
                if feature.id in source_ids
            ]
            if not source_shapes:
                continue
            parent_footprint = source_shapes[0]
            for extra in source_shapes[1:]:
                parent_footprint = parent_footprint.union(extra)
            if parent_footprint.covers(candidate_point) and not parent_footprint.covers(current_point):
                matches.append((child, child_context, float(parent_footprint.area)))

        if matches:
            # Smaller containing footprint is the more specific nested area.
            child, child_context, _area = min(matches, key=lambda item: item[2])
            child_point = parent_to_child_point(child_context, candidate)
            child_movement = self.resolver.movement_context(
                project_id=project_id,
                navigation_space_id=child.id,
                x=child_point[0],
                y=child_point[1],
            )
            if child_movement["movement"]["default_allowed"]:
                return {
                    "allowed": True,
                    "transition": {
                        "kind": "descend",
                        "from_space_id": space_id,
                        "to_space_id": child.id,
                    },
                    "space_id": child.id,
                    "point": list(child_point),
                }

        return {
            "allowed": True,
            "transition": None,
            "space_id": space_id,
            "point": [float(candidate[0]), float(candidate[1])],
        }
