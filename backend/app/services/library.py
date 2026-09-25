from __future__ import annotations

from typing import Any

from app.data.dataProvider import DataProvider
from app.domain.world import Stat


class GlobalLibraryService:
    """Semantic operations over reusable global-library resources.

    Library revisions are immutable snapshots. Applying one always creates or
    updates project-local canonical records; a story never shares mutable rows
    with the global library.
    """

    def __init__(self, data: DataProvider) -> None:
        self.data = data

    def save_stat_pack(
        self,
        project_id: str,
        *,
        name: str,
        stat_keys: list[str] | None = None,
        resource_id: str | None = None,
        description: str = "",
        marked: bool = True,
        tags: list[str] | None = None,
        source_story_node_id: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        stats = self.data.rules.stats(project_id)
        if stat_keys is not None:
            requested = set(stat_keys)
            stats = [item for item in stats if item.stat_key in requested]
            missing = requested.difference(item.stat_key for item in stats)
            if missing:
                raise ValueError(f"Unknown stat(s): {', '.join(sorted(missing))}")
        if not stats:
            raise ValueError("A stat pack must contain at least one stat")

        if resource_id:
            resource = self.data.library.resource(resource_id)
            if not resource:
                raise ValueError("Library resource not found")
            if resource["resource_kind"] != "stat_pack":
                raise ValueError("Only stat_pack resources can receive stat-pack revisions")
            self.data.library.update_resource(
                resource_id,
                name=name,
                description=description,
                marked=marked,
                tags=tags or resource.get("tags", []),
            )
        else:
            resource = self.data.library.create_resource(
                resource_kind="stat_pack",
                name=name,
                description=description,
                marked=marked,
                tags=tags or [],
            )
            resource_id = resource["id"]

        snapshot = {
            "schema_version": 1,
            "resource_kind": "stat_pack",
            "stats": [
                item.model_dump(mode="json")
                for item in self.data.rules.dependency_ordered_stats(stats)
            ],
        }
        revision = self.data.library.add_revision(
            resource_id,
            snapshot,
            source_project_id=project_id,
            source_story_node_id=source_story_node_id,
            source_kind="stat_pack",
            note=note,
        )
        return {
            "resource": self.data.library.resource(resource_id),
            "revision": revision,
        }

    def stat_pack_snapshot(
        self,
        resource_id: str,
        revision_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        resource = self.data.library.resource(resource_id)
        if not resource or resource["resource_kind"] != "stat_pack":
            raise ValueError("Stat pack not found")
        selected_revision_id = revision_id or resource.get("current_revision_id")
        if not selected_revision_id:
            raise ValueError("Stat pack has no revision")
        revision = self.data.library.revision(selected_revision_id)
        if not revision or revision["resource_id"] != resource_id:
            raise ValueError("Revision does not belong to this stat pack")
        snapshot = revision["snapshot"]
        if snapshot.get("resource_kind") != "stat_pack" or snapshot.get("schema_version") != 1:
            raise ValueError("Unsupported stat-pack snapshot")
        stats = snapshot.get("stats")
        if not isinstance(stats, list) or not stats:
            raise ValueError("Stat pack has no stat definitions")
        parsed = [Stat.model_validate(raw) for raw in stats]
        ordered = self.data.rules.dependency_ordered_stats(parsed)
        by_key = {item.stat_key: item for item in ordered}
        for stat in ordered:
            owners = set(map(str, stat.compatible_owner_kinds))
            for dependency_key in (stat.minimum_stat_key, stat.maximum_stat_key):
                if not dependency_key:
                    continue
                dependency = by_key.get(dependency_key)
                if not dependency:
                    raise ValueError(
                        f"Stat pack is not self-contained; {stat.stat_key} references missing stat {dependency_key}"
                    )
                missing = owners.difference(map(str, dependency.compatible_owner_kinds))
                if missing:
                    raise ValueError(
                        f"Stat pack has incompatible bounds: {stat.stat_key} -> {dependency_key}"
                    )
        return resource, revision, snapshot

    def apply_stat_pack(
        self,
        resource_id: str,
        project_id: str,
        *,
        revision_id: str | None = None,
        conflict_policy: str = "error",
        source_story_node_id: str | None = None,
    ) -> dict[str, Any]:
        _resource, revision, snapshot = self.stat_pack_snapshot(resource_id, revision_id)
        selected_revision_id = revision["id"]
        if conflict_policy not in {"error", "skip"}:
            raise ValueError("conflict_policy must be error or skip")

        existing = {item.stat_key: item for item in self.data.rules.stats(project_id)}
        incoming = [
            Stat.model_validate({**raw, "project_id": project_id})
            for raw in snapshot.get("stats", [])
        ]
        incoming_by_key = {item.stat_key: item for item in incoming}
        collisions = sorted(set(existing).intersection(incoming_by_key))
        if collisions and conflict_policy == "error":
            raise ValueError(f"Stat already exists: {', '.join(collisions)}")

        final_definitions = dict(existing)
        for key, stat in incoming_by_key.items():
            if key not in existing:
                final_definitions[key] = stat
        for stat in incoming:
            if stat.stat_key in existing and conflict_policy == "skip":
                continue
            owners = set(map(str, stat.compatible_owner_kinds))
            for dependency_key in (stat.minimum_stat_key, stat.maximum_stat_key):
                if not dependency_key:
                    continue
                dependency = final_definitions.get(dependency_key)
                if not dependency:
                    raise ValueError(f"Imported stat {stat.stat_key} references missing stat {dependency_key}")
                if owners.difference(map(str, dependency.compatible_owner_kinds)):
                    raise ValueError(
                        f"Imported stat {stat.stat_key} is incompatible with existing bound stat {dependency_key}"
                    )

        ordered = self.data.rules.dependency_ordered_stats(
            incoming,
            available=set(existing),
        )
        applied: list[str] = []
        skipped: list[str] = []
        for stat in ordered:
            if stat.stat_key in existing:
                skipped.append(stat.stat_key)
                continue
            self.data.rules.save_stat(stat)
            existing[stat.stat_key] = stat
            applied.append(stat.stat_key)

        self.data.library.record_import(
            resource_id=resource_id,
            revision_id=selected_revision_id,
            project_id=project_id,
            target_kind="stat_pack",
            target_key=",".join(applied) if applied else None,
            source_story_node_id=source_story_node_id,
        )
        return {
            "resource_id": resource_id,
            "revision_id": selected_revision_id,
            "applied": applied,
            "skipped": skipped,
        }
