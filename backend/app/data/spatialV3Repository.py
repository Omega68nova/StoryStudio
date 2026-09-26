from __future__ import annotations

import json
from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import utc_now
from app.domain.spatial_v3 import (
    BarrierProperties,
    ConnectorEndpoint,
    ConnectorProperties,
    CorridorProperties,
    EncounterPolicy,
    MapFeature,
    NavigationLayer,
    NavigationSpace,
    SpotProperties,
    SurfaceProperties,
    TraversalPolicy,
)


class SpatialV3Repository(BaseRepository):
    """Materialized read model for branch-authoritative Spatial V3 state.

    WorldEngine events/projections are canonical. These tables are rebuildable
    query/index state used by geometry resolution and the experimental editor.
    """

    def clear_project(self, project_id: str) -> None:
        # navigation_spaces_current owns all V3 feature/layer/binding rows by
        # cascade. Encounter policies directly owned by a space/feature cascade
        # with those rows as well.
        self.db.execute(
            "DELETE FROM navigation_spaces_current WHERE project_id=?",
            (project_id,),
        )

    def spaces(self, project_id: str) -> list[NavigationSpace]:
        return [
            self._space_from_row(row)
            for row in self.db.fetch_all(
                "SELECT * FROM navigation_spaces_current WHERE project_id=? ORDER BY id",
                (project_id,),
            )
        ]

    def space(self, space_id: str) -> NavigationSpace | None:
        row = self.db.fetch_one(
            "SELECT * FROM navigation_spaces_current WHERE id=?",
            (space_id,),
        )
        return self._space_from_row(row) if row else None

    @staticmethod
    def _space_from_row(row: dict[str, Any]) -> NavigationSpace:
        return NavigationSpace.model_validate({
            "id": row["id"],
            "project_id": row["project_id"],
            "owner_location_id": row.get("owner_location_id"),
            "navigation_mode": row["navigation_mode"],
            "base_travel_multiplier": row["base_travel_multiplier"],
            "bounds": json.loads(row["bounds_geojson"]) if row.get("bounds_geojson") else None,
            "revision": row["revision"],
        })

    def save_space(self, space: NavigationSpace) -> NavigationSpace:
        self.db.execute(
            """
            INSERT INTO navigation_spaces_current(
              id,project_id,owner_location_id,navigation_mode,
              base_travel_multiplier,bounds_geojson,revision,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              owner_location_id=excluded.owner_location_id,
              navigation_mode=excluded.navigation_mode,
              base_travel_multiplier=excluded.base_travel_multiplier,
              bounds_geojson=excluded.bounds_geojson,
              revision=navigation_spaces_current.revision + 1,
              updated_at=excluded.updated_at
            """,
            (
                space.id,
                space.project_id,
                space.owner_location_id,
                str(space.navigation_mode),
                float(space.base_travel_multiplier),
                json.dumps(space.bounds.model_dump(mode="json")) if space.bounds else None,
                int(space.revision),
                utc_now(),
            ),
        )
        return self.space(space.id)  # type: ignore[return-value]

    def bind_location_space(
        self,
        *,
        project_id: str,
        location_id: str,
        navigation_space_id: str,
        entrance_policy: str = "connectors",
        bounds_mode: str = "inherit_parent",
    ) -> None:
        self.db.execute(
            """
            INSERT INTO location_navigation_spaces_current(
              project_id,location_id,navigation_space_id,entrance_policy,bounds_mode
            ) VALUES(?,?,?,?,?)
            ON CONFLICT(project_id,location_id) DO UPDATE SET
              navigation_space_id=excluded.navigation_space_id,
              entrance_policy=excluded.entrance_policy,
              bounds_mode=excluded.bounds_mode
            """,
            (project_id, location_id, navigation_space_id, entrance_policy, bounds_mode),
        )

    def location_space(self, project_id: str, location_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM location_navigation_spaces_current WHERE project_id=? AND location_id=?",
            (project_id, location_id),
        )

    def features(
        self,
        project_id: str,
        navigation_space_id: str | None = None,
    ) -> list[MapFeature]:
        if navigation_space_id:
            rows = self.db.fetch_all(
                """
                SELECT * FROM map_features_current
                WHERE project_id=? AND navigation_space_id=?
                ORDER BY render_layer,render_order,id
                """,
                (project_id, navigation_space_id),
            )
        else:
            rows = self.db.fetch_all(
                """
                SELECT * FROM map_features_current
                WHERE project_id=?
                ORDER BY navigation_space_id,render_layer,render_order,id
                """,
                (project_id,),
            )
        return [self._feature_from_row(row) for row in rows]

    def feature(self, feature_id: str) -> MapFeature | None:
        row = self.db.fetch_one(
            "SELECT * FROM map_features_current WHERE id=?",
            (feature_id,),
        )
        return self._feature_from_row(row) if row else None

    def _feature_from_row(self, row: dict[str, Any]) -> MapFeature:
        feature_id = row["id"]
        kind = row["feature_kind"]
        if kind == "surface":
            props = self.db.fetch_one(
                "SELECT * FROM map_surface_properties WHERE feature_id=?",
                (feature_id,),
            ) or {}
            properties: Any = SurfaceProperties(
                traversal=TraversalPolicy.model_validate(
                    json.loads(props.get("traversal_json") or "{}")
                ),
                ambience_tags=json.loads(props.get("ambience_tags_json") or "[]"),
                environment_tags=json.loads(props.get("environment_tags_json") or "[]"),
            )
        elif kind == "corridor":
            props = self.db.fetch_one(
                "SELECT * FROM map_corridor_properties WHERE feature_id=?",
                (feature_id,),
            ) or {}
            properties = CorridorProperties(
                width=float(props.get("width") or 1),
                traversal=TraversalPolicy.model_validate(
                    json.loads(props.get("traversal_json") or "{}")
                ),
                ambience_tags=json.loads(props.get("ambience_tags_json") or "[]"),
            )
        elif kind == "barrier":
            props = self.db.fetch_one(
                "SELECT * FROM map_barrier_properties WHERE feature_id=?",
                (feature_id,),
            ) or {}
            properties = BarrierProperties(
                traversal=TraversalPolicy.model_validate(
                    json.loads(props.get("traversal_json") or '{"default_allowed":false}')
                ),
            )
        elif kind == "connector":
            props = self.db.fetch_one(
                "SELECT * FROM map_connector_properties WHERE feature_id=?",
                (feature_id,),
            )
            if not props:
                raise ValueError(f"Connector properties missing for {feature_id}")
            properties = ConnectorProperties(
                connector_kind=props["connector_kind"],
                source=ConnectorEndpoint(
                    navigation_space_id=props["source_space_id"],
                    point=tuple(json.loads(props["source_point_json"])),
                ),
                target=ConnectorEndpoint(
                    navigation_space_id=props["target_space_id"],
                    point=tuple(json.loads(props["target_point_json"])),
                ),
                traversal=TraversalPolicy.model_validate(
                    json.loads(props.get("traversal_json") or "{}")
                ),
                travel_minutes=props.get("travel_minutes"),
                bidirectional=bool(props.get("bidirectional", 1)),
            )
        elif kind == "spot":
            props = self.db.fetch_one(
                "SELECT * FROM map_spot_properties WHERE feature_id=?",
                (feature_id,),
            ) or {}
            properties = SpotProperties(
                interaction_kind=str(props.get("interaction_kind") or "generic"),
            )
        else:
            raise ValueError(f"Unknown Spatial V3 feature kind: {kind}")

        return MapFeature.model_validate({
            "id": feature_id,
            "project_id": row["project_id"],
            "navigation_space_id": row["navigation_space_id"],
            "semantic_location_id": row.get("semantic_location_id"),
            "feature_kind": kind,
            "name": row.get("name") or "",
            "geometry": json.loads(row["geometry_geojson"]),
            "render_layer": row["render_layer"],
            "render_order": row["render_order"],
            "movement_priority": row["movement_priority"],
            "hidden": bool(row["hidden"]),
            "discovered": bool(row["discovered"]),
            "enabled": bool(row["enabled"]),
            "metadata": json.loads(row.get("metadata_json") or "{}"),
            "properties": properties,
        })

    def save_feature(self, feature: MapFeature) -> MapFeature:
        self.db.execute(
            """
            INSERT INTO map_features_current(
              id,project_id,navigation_space_id,semantic_location_id,
              feature_kind,name,geometry_geojson,render_layer,render_order,
              movement_priority,hidden,discovered,enabled,metadata_json,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              navigation_space_id=excluded.navigation_space_id,
              semantic_location_id=excluded.semantic_location_id,
              feature_kind=excluded.feature_kind,
              name=excluded.name,
              geometry_geojson=excluded.geometry_geojson,
              render_layer=excluded.render_layer,
              render_order=excluded.render_order,
              movement_priority=excluded.movement_priority,
              hidden=excluded.hidden,
              discovered=excluded.discovered,
              enabled=excluded.enabled,
              metadata_json=excluded.metadata_json,
              updated_at=excluded.updated_at
            """,
            (
                feature.id,
                feature.project_id,
                feature.navigation_space_id,
                feature.semantic_location_id,
                str(feature.feature_kind),
                feature.name,
                json.dumps(feature.geometry.model_dump(mode="json")),
                str(feature.render_layer),
                float(feature.render_order),
                float(feature.movement_priority),
                int(feature.hidden),
                int(feature.discovered),
                int(feature.enabled),
                json.dumps(feature.metadata),
                utc_now(),
            ),
        )
        self._replace_feature_properties(feature)
        return self.feature(feature.id)  # type: ignore[return-value]

    def _replace_feature_properties(self, feature: MapFeature) -> None:
        feature_id = feature.id
        for table in (
            "map_surface_properties",
            "map_corridor_properties",
            "map_barrier_properties",
            "map_connector_properties",
            "map_spot_properties",
        ):
            self.db.execute(f"DELETE FROM {table} WHERE feature_id=?", (feature_id,))

        props = feature.properties
        if feature.feature_kind == "surface":
            assert isinstance(props, SurfaceProperties)
            self.db.execute(
                """
                INSERT INTO map_surface_properties(
                  feature_id,traversal_json,ambience_tags_json,environment_tags_json
                ) VALUES(?,?,?,?)
                """,
                (
                    feature_id,
                    json.dumps(props.traversal.model_dump(mode="json")),
                    json.dumps(props.ambience_tags),
                    json.dumps(props.environment_tags),
                ),
            )
        elif feature.feature_kind == "corridor":
            assert isinstance(props, CorridorProperties)
            self.db.execute(
                """
                INSERT INTO map_corridor_properties(
                  feature_id,width,traversal_json,ambience_tags_json
                ) VALUES(?,?,?,?)
                """,
                (
                    feature_id,
                    props.width,
                    json.dumps(props.traversal.model_dump(mode="json")),
                    json.dumps(props.ambience_tags),
                ),
            )
        elif feature.feature_kind == "barrier":
            assert isinstance(props, BarrierProperties)
            self.db.execute(
                "INSERT INTO map_barrier_properties(feature_id,traversal_json) VALUES(?,?)",
                (feature_id, json.dumps(props.traversal.model_dump(mode="json"))),
            )
        elif feature.feature_kind == "connector":
            assert isinstance(props, ConnectorProperties)
            self.db.execute(
                """
                INSERT INTO map_connector_properties(
                  feature_id,connector_kind,source_space_id,target_space_id,
                  source_point_json,target_point_json,traversal_json,
                  travel_minutes,bidirectional
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    feature_id,
                    str(props.connector_kind),
                    props.source.navigation_space_id,
                    props.target.navigation_space_id,
                    json.dumps(list(props.source.point)),
                    json.dumps(list(props.target.point)),
                    json.dumps(props.traversal.model_dump(mode="json")),
                    props.travel_minutes,
                    int(props.bidirectional),
                ),
            )
        elif feature.feature_kind == "spot":
            assert isinstance(props, SpotProperties)
            self.db.execute(
                "INSERT INTO map_spot_properties(feature_id,interaction_kind) VALUES(?,?)",
                (feature_id, props.interaction_kind),
            )

    def delete_feature(self, feature_id: str) -> None:
        self.db.execute("DELETE FROM map_features_current WHERE id=?", (feature_id,))

    def layers(self, navigation_space_id: str) -> list[NavigationLayer]:
        return [
            NavigationLayer.model_validate({
                "navigation_space_id": row["navigation_space_id"],
                "layer_key": row["layer_key"],
                "label": row["label"],
                "position": row["position"],
                "visible": bool(row["visible"]),
                "labels_mode": row["labels_mode"],
            })
            for row in self.db.fetch_all(
                """
                SELECT * FROM navigation_space_layers_current
                WHERE navigation_space_id=?
                ORDER BY position,layer_key
                """,
                (navigation_space_id,),
            )
        ]

    def save_layer(self, layer: NavigationLayer) -> NavigationLayer:
        self.db.execute(
            """
            INSERT INTO navigation_space_layers_current(
              navigation_space_id,layer_key,label,position,visible,labels_mode
            ) VALUES(?,?,?,?,?,?)
            ON CONFLICT(navigation_space_id,layer_key) DO UPDATE SET
              label=excluded.label,
              position=excluded.position,
              visible=excluded.visible,
              labels_mode=excluded.labels_mode
            """,
            (
                layer.navigation_space_id,
                layer.layer_key,
                layer.label,
                layer.position,
                int(layer.visible),
                str(layer.labels_mode),
            ),
        )
        return layer

    def encounter_policies(
        self,
        project_id: str,
        navigation_space_id: str,
    ) -> list[EncounterPolicy]:
        feature_ids = {
            row["id"]
            for row in self.db.fetch_all(
                "SELECT id FROM map_features_current WHERE project_id=? AND navigation_space_id=?",
                (project_id, navigation_space_id),
            )
        }
        rows = self.db.fetch_all(
            """
            SELECT * FROM navigation_encounter_policies_current
            WHERE project_id=?
              AND (navigation_space_id=? OR feature_id IS NOT NULL)
            ORDER BY priority,id
            """,
            (project_id, navigation_space_id),
        )
        result = []
        for row in rows:
            if row.get("feature_id") and row["feature_id"] not in feature_ids:
                continue
            result.append(EncounterPolicy.model_validate({
                "id": row["id"],
                "project_id": row["project_id"],
                "navigation_space_id": row.get("navigation_space_id"),
                "feature_id": row.get("feature_id"),
                "mode": row["mode"],
                "priority": row["priority"],
                "trigger_kind": row.get("trigger_kind") or "distance",
                "rate_per_100_units": row["rate_per_100_units"],
                "probability_per_transition": row.get("probability_per_transition"),
                "minimum_distance": row["minimum_distance"],
                "candidates": json.loads(row.get("candidates_json") or "[]"),
                "conditions": json.loads(row["conditions_json"]) if row.get("conditions_json") else None,
                "enabled": bool(row["enabled"]),
            }))
        return result

    def encounter_policies_for_transition(
        self,
        project_id: str,
        navigation_space_id: str,
        feature_id: str,
    ) -> list[EncounterPolicy]:
        """Policies that can affect traversing one feature from one space.

        Feature-targeted policies must remain visible when a bidirectional
        connector is traversed from its target side, so this query cannot rely
        on the feature being owned by navigation_space_id.
        """
        rows = self.db.fetch_all(
            """
            SELECT * FROM navigation_encounter_policies_current
            WHERE project_id=?
              AND (navigation_space_id=? OR feature_id=?)
            ORDER BY priority,id
            """,
            (project_id, navigation_space_id, feature_id),
        )
        return [
            EncounterPolicy.model_validate({
                "id": row["id"],
                "project_id": row["project_id"],
                "navigation_space_id": row.get("navigation_space_id"),
                "feature_id": row.get("feature_id"),
                "mode": row["mode"],
                "priority": row["priority"],
                "trigger_kind": row.get("trigger_kind") or "distance",
                "rate_per_100_units": row["rate_per_100_units"],
                "probability_per_transition": row.get("probability_per_transition"),
                "minimum_distance": row["minimum_distance"],
                "candidates": json.loads(row.get("candidates_json") or "[]"),
                "conditions": json.loads(row["conditions_json"]) if row.get("conditions_json") else None,
                "enabled": bool(row["enabled"]),
            })
            for row in rows
        ]

    def save_encounter_policy(self, policy: EncounterPolicy) -> EncounterPolicy:
        self.db.execute(
            """
            INSERT INTO navigation_encounter_policies_current(
              id,project_id,navigation_space_id,feature_id,mode,priority,
              trigger_kind,rate_per_100_units,probability_per_transition,
              minimum_distance,candidates_json,conditions_json,enabled,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              navigation_space_id=excluded.navigation_space_id,
              feature_id=excluded.feature_id,
              mode=excluded.mode,
              priority=excluded.priority,
              trigger_kind=excluded.trigger_kind,
              rate_per_100_units=excluded.rate_per_100_units,
              probability_per_transition=excluded.probability_per_transition,
              minimum_distance=excluded.minimum_distance,
              candidates_json=excluded.candidates_json,
              conditions_json=excluded.conditions_json,
              enabled=excluded.enabled,
              updated_at=excluded.updated_at
            """,
            (
                policy.id,
                policy.project_id,
                policy.navigation_space_id,
                policy.feature_id,
                str(policy.mode),
                float(policy.priority),
                str(policy.trigger_kind),
                float(policy.rate_per_100_units),
                policy.probability_per_transition,
                float(policy.minimum_distance),
                json.dumps([item.model_dump(mode="json") for item in policy.candidates]),
                json.dumps(policy.conditions) if policy.conditions is not None else None,
                int(policy.enabled),
                utc_now(),
            ),
        )
        rows = self.encounter_policies(
            policy.project_id,
            policy.navigation_space_id
            or self.db.fetch_one(
                "SELECT navigation_space_id FROM map_features_current WHERE id=?",
                (policy.feature_id,),
            )["navigation_space_id"],
        )
        return next(item for item in rows if item.id == policy.id)

    def delete_encounter_policy(self, policy_id: str) -> None:
        self.db.execute(
            "DELETE FROM navigation_encounter_policies_current WHERE id=?",
            (policy_id,),
        )
