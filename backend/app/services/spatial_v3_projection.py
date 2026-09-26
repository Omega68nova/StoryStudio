from __future__ import annotations

from typing import Any

from app.data.spatialV3Repository import SpatialV3Repository
from app.domain.spatial_v3 import (
    EncounterPolicy,
    MapFeature,
    NavigationLayer,
    NavigationSpace,
)


class SpatialV3ProjectionMaterializer:
    """Rebuild the Spatial V3 query tables from a WorldEngine branch projection."""

    def __init__(self, repository: SpatialV3Repository) -> None:
        self.repository = repository

    def synchronize(
        self,
        project_id: str,
        projection: dict[str, Any],
    ) -> dict[str, int]:
        if projection.get("project_id") not in (None, project_id):
            raise ValueError("Spatial V3 projection belongs to another project")

        state = projection.get("spatial_v3") or {}
        spaces = [
            NavigationSpace.model_validate(item)
            for item in state.get("spaces", {}).values()
        ]
        features = [
            MapFeature.model_validate(item)
            for item in state.get("features", {}).values()
        ]
        encounters = [
            EncounterPolicy.model_validate(item)
            for item in state.get("encounter_policies", {}).values()
        ]
        layers = [
            NavigationLayer.model_validate(item)
            for item in state.get("layers", {}).values()
        ]
        bindings = list(state.get("location_space_bindings", {}).values())

        self.repository.clear_project(project_id)
        for space in spaces:
            if space.project_id != project_id:
                raise ValueError(f"Navigation space {space.id} belongs to another project")
            self.repository.save_space(space)
        for binding in bindings:
            if binding.get("project_id") != project_id:
                raise ValueError("Location/navigation-space binding belongs to another project")
            self.repository.bind_location_space(**binding)
        for feature in features:
            if feature.project_id != project_id:
                raise ValueError(f"Map feature {feature.id} belongs to another project")
            self.repository.save_feature(feature)
        for encounter in encounters:
            if encounter.project_id != project_id:
                raise ValueError(f"Encounter policy {encounter.id} belongs to another project")
            self.repository.save_encounter_policy(encounter)
        for layer in layers:
            self.repository.save_layer(layer)

        return {
            "spaces": len(spaces),
            "features": len(features),
            "encounter_policies": len(encounters),
            "layers": len(layers),
            "location_space_bindings": len(bindings),
        }
