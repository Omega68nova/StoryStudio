from __future__ import annotations

import json
from typing import Any

from app.data.dataProvider import DataProvider
from app.domain.world import Stat


class GlobalLibraryService:
    """Semantic operations over reusable global-library resources.

    Library revisions are immutable snapshots. Applying one always creates or
    updates project-local canonical records; a story never shares mutable rows
    with the global library.
    """

    def __init__(self, data: DataProvider, world: Any | None = None) -> None:
        self.data = data
        self.world = world

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


    # ------------------------------------------------------------------
    # Favorite/reusable resource trees
    # ------------------------------------------------------------------

    @staticmethod
    def _token(source_kind: str, source_key: str) -> str:
        return f"{source_kind}:{source_key}"

    @staticmethod
    def _entity_snapshot(entity: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(entity["id"]),
            "kind": str(entity["kind"]),
            "name": str(entity.get("name") or ""),
            "aliases": list(entity.get("aliases") or []),
            "tags": list(entity.get("tags") or []),
            "state": dict(entity.get("state") or {}),
        }

    def _entity_original(
        self,
        project_id: str,
        entity_id: str,
        head_node_id: str | None,
    ) -> dict[str, Any] | None:
        ancestry = {
            node["id"] for node in self.data.db.story_path(head_node_id)
        } if head_node_id else set()
        for transaction in self.data.world.committed_transactions(project_id):
            story_node_id = transaction.get("story_node_id")
            if story_node_id is not None and story_node_id not in ancestry:
                continue
            for event in self.data.world.transaction_events(transaction["id"]):
                if event.get("event_type") != "entity.created":
                    continue
                payload = json.loads(event.get("payload_json") or "{}")
                entity = payload.get("entity")
                if isinstance(entity, dict) and str(entity.get("id")) == entity_id:
                    return self._entity_snapshot(entity)
        return None

    def _source_versions(
        self,
        project_id: str,
        source_kind: str,
        source_key: str,
        head_node_id: str | None,
    ) -> dict[str, Any]:
        entity_kinds = {
            "character", "location", "item", "faction",
            "lore_system", "fact", "plot_beat",
        }
        if source_kind in entity_kinds:
            if self.world is None:
                raise ValueError("World projection service is unavailable")
            projection = self.world.projection(project_id, head_node_id)
            entity = projection.get("entities", {}).get(source_key)
            if not entity or entity.get("kind") != source_kind:
                raise ValueError(f"{source_kind.replace('_', ' ').title()} not found")
            latest = self._entity_snapshot(entity)
            original_record = self._entity_original(project_id, source_key, head_node_id)
            original = original_record or latest
            state = latest.get("state", {})
            return {
                "name": latest["name"],
                "description": str(state.get("description") or state.get("summary") or ""),
                "tags": list(latest.get("tags") or []),
                "original": original,
                "latest": latest,
                "original_available": original_record is not None,
                "has_changed": original_record is not None and original != latest,
            }

        if source_kind == "outfit":
            row = self.data.db.fetch_one(
                "SELECT * FROM entity_outfits WHERE id=?",
                (source_key,),
            )
            if not row:
                raise ValueError("Outfit not found")
            entity = self.data.db.fetch_one(
                "SELECT project_id,name FROM world_entities WHERE id=?",
                (row["entity_id"],),
            )
            if not entity or entity["project_id"] != project_id:
                raise ValueError("Outfit does not belong to this project")
            snapshot = dict(row)
            if "equipment_json" in snapshot:
                snapshot["equipment"] = json.loads(snapshot.pop("equipment_json") or "[]")
            return {
                "name": row["name"],
                "description": str(row.get("description") or ""),
                "tags": [str(entity.get("name") or "")],
                "original": snapshot,
                "latest": snapshot,
                "original_available": False,
                "has_changed": False,
            }

        if source_kind == "stat":
            item = self.data.rules.stat(project_id, source_key)
            if not item:
                raise ValueError("Stat not found")
            snapshot = item.model_dump(mode="json")
            return {
                "name": item.label,
                "description": item.description,
                "tags": [],
                "original": snapshot,
                "latest": snapshot,
                "original_available": False,
                "has_changed": False,
            }

        if source_kind == "effect":
            item = self.data.rules.effect(project_id, source_key)
            if not item:
                raise ValueError("Effect not found")
            snapshot = item.model_dump(mode="json")
            return {
                "name": item.name,
                "description": item.description,
                "tags": [],
                "original": snapshot,
                "latest": snapshot,
                "original_available": False,
                "has_changed": False,
            }

        if source_kind == "ability":
            item = self.data.rules.ability(project_id, source_key)
            if not item:
                raise ValueError("Ability not found")
            snapshot = item.model_dump(mode="json")
            return {
                "name": item.name,
                "description": item.description,
                "tags": [],
                "original": snapshot,
                "latest": snapshot,
                "original_available": False,
                "has_changed": False,
            }
        raise ValueError(f"Unsupported library source kind: {source_kind}")

    @staticmethod
    def _formula_stat_keys(node: Any) -> set[str]:
        if hasattr(node, "model_dump"):
            node = node.model_dump(mode="json")
        if not isinstance(node, dict):
            return set()
        result = {str(node["stat_key"])} if node.get("stat_key") else set()
        for child in node.get("children") or []:
            result.update(GlobalLibraryService._formula_stat_keys(child))
        return result

    @staticmethod
    def _requirement_refs(node: Any) -> dict[str, set[str]]:
        if hasattr(node, "model_dump"):
            node = node.model_dump(mode="json")
        refs = {"stat": set(), "ability": set(), "item": set(), "location": set(), "fact": set()}
        if not isinstance(node, dict):
            return refs
        mapping = {
            "stat_key": "stat",
            "ability_key": "ability",
            "item_id": "item",
            "location_id": "location",
            "fact_id": "fact",
        }
        for field, kind in mapping.items():
            if node.get(field):
                refs[kind].add(str(node[field]))
        for child in node.get("children") or []:
            child_refs = GlobalLibraryService._requirement_refs(child)
            for kind, values in child_refs.items():
                refs[kind].update(values)
        if node.get("child"):
            child_refs = GlobalLibraryService._requirement_refs(node["child"])
            for kind, values in child_refs.items():
                refs[kind].update(values)
        return refs

    def _direct_dependencies(
        self,
        project_id: str,
        source_kind: str,
        source_key: str,
        head_node_id: str | None,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        def add(kind: str, key: Any, relation: str, *, selected: bool = True) -> None:
            if key in (None, ""):
                return
            token = self._token(kind, str(key))
            if token == self._token(source_kind, source_key):
                return
            if any(item["token"] == token for item in result):
                return
            try:
                versions = self._source_versions(project_id, kind, str(key), head_node_id)
            except ValueError:
                return
            result.append({
                "token": token,
                "source_kind": kind,
                "source_key": str(key),
                "name": versions["name"],
                "relation": relation,
                "default_selected": selected,
                "has_changed": bool(versions["has_changed"]),
                "original_available": bool(versions["original_available"]),
            })

        if source_kind in {"character", "location", "item", "faction", "lore_system", "fact", "plot_beat"}:
            versions = self._source_versions(project_id, source_kind, source_key, head_node_id)
            entity = versions["latest"]
            state = entity.get("state", {})
            for stat_key in (entity.get("stats") or {}):
                add("stat", stat_key, "stat")
            # Runtime projections keep current stat values outside the reusable
            # state; definitions referenced by keys remain reusable dependencies.
            if self.world is not None:
                current = self.world.projection(project_id, head_node_id).get("entities", {}).get(source_key, {})
                for stat_key in (current.get("stats") or {}):
                    add("stat", stat_key, "stat")
            for ability_key in state.get("abilities") or []:
                add("ability", ability_key, "ability")
            if source_kind == "character":
                for row in self.data.db.fetch_all(
                    "SELECT id,name FROM entity_outfits WHERE entity_id=? ORDER BY name,id",
                    (source_key,),
                ):
                    add("outfit", row["id"], "outfit")
                add("location", state.get("home_location_id"), "home")
                for faction_id in state.get("faction_ids") or []:
                    add("faction", faction_id, "faction")
                for entry in state.get("inventory") or []:
                    if isinstance(entry, dict):
                        add("item", entry.get("item_id"), "inventory")
            if source_kind == "item":
                add("location", state.get("home_location_id"), "home")
            if source_kind == "location" and self.world is not None:
                projection = self.world.projection(project_id, head_node_id)
                for candidate in projection.get("entities", {}).values():
                    if candidate.get("kind") == "location" and str(candidate.get("state", {}).get("parent_location_id") or "") == source_key:
                        add("location", candidate["id"], "child_location", selected=True)
            # Current placement is usually runtime state, so expose it but leave
            # it unselected by default.
            add("location", state.get("current_location_id"), "current_location", selected=False)

        elif source_kind == "stat":
            item = self.data.rules.stat(project_id, source_key)
            if item:
                add("stat", item.minimum_stat_key, "minimum_bound")
                add("stat", item.maximum_stat_key, "maximum_bound")

        elif source_kind == "effect":
            item = self.data.rules.effect(project_id, source_key)
            if item:
                add("stat", item.target_stat_key, "target_stat")
                for stat_key in self._formula_stat_keys(item.formula):
                    add("stat", stat_key, "formula_stat")

        elif source_kind == "ability":
            item = self.data.rules.ability(project_id, source_key)
            if item:
                refs = self._requirement_refs(item.requirements)
                for kind, values in refs.items():
                    for key in values:
                        add(kind, key, f"requirement_{kind}")
                for cost in item.costs:
                    add("stat", getattr(cost, "stat_key", None), "cost_stat")
                    add("item", getattr(cost, "item_id", None), "cost_item")
                for trigger in item.passive_triggers:
                    add("stat", getattr(trigger, "stat_key", None), "trigger_stat")
                for action in item.actions:
                    add("effect", getattr(action, "effect_key", None), "effect")
                    add("location", getattr(action, "destination_id", None), "destination")
                    add("fact", getattr(action, "fact_id", None), "fact")

        elif source_kind == "outfit":
            row = self.data.db.fetch_one("SELECT entity_id FROM entity_outfits WHERE id=?", (source_key,))
            if row:
                add("character", row["entity_id"], "owner", selected=False)
        return result

    def favorite_preview(
        self,
        project_id: str,
        *,
        source_kind: str,
        source_key: str,
        source_story_node_id: str | None = None,
    ) -> dict[str, Any]:
        if source_story_node_id is None:
            source_story_node_id = (self.data.db.get_project(project_id) or {}).get("active_node_id")
        versions = self._source_versions(project_id, source_kind, source_key, source_story_node_id)
        root_token = self._token(source_kind, source_key)
        dependencies: list[dict[str, Any]] = []
        seen = {root_token}
        queue: list[tuple[str, str, str, int, str]] = [
            (source_kind, source_key, root_token, 0, "")
        ]
        while queue and len(dependencies) < 500:
            kind, key, parent_token, depth, _relation = queue.pop(0)
            for dependency in self._direct_dependencies(project_id, kind, key, source_story_node_id):
                token = dependency["token"]
                if token in seen:
                    continue
                seen.add(token)
                entry = {
                    **dependency,
                    "parent_token": parent_token,
                    "depth": depth + 1,
                }
                dependencies.append(entry)
                queue.append((
                    dependency["source_kind"],
                    dependency["source_key"],
                    token,
                    depth + 1,
                    dependency["relation"],
                ))
        existing = self.data.library.resource_for_source(
            source_project_id=project_id,
            source_kind=source_kind,
            source_key=source_key,
        )
        return {
            "source_kind": source_kind,
            "source_key": source_key,
            "token": root_token,
            "name": versions["name"],
            "description": versions["description"],
            "tags": versions["tags"],
            "has_changed": bool(versions["has_changed"]),
            "original_available": bool(versions["original_available"]),
            "already_favorited": bool(existing),
            "library_resource_id": existing.get("id") if existing else None,
            "dependencies": dependencies,
        }

    def _ensure_favorite_resource(
        self,
        project_id: str,
        source_kind: str,
        source_key: str,
        head_node_id: str | None,
        version: str,
        extra_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        versions = self._source_versions(project_id, source_kind, source_key, head_node_id)
        resource = self.data.library.resource_for_source(
            source_project_id=project_id,
            source_kind=source_kind,
            source_key=source_key,
        )
        tags = list(dict.fromkeys([*versions["tags"], *(extra_tags or [])]))
        if resource:
            resource = self.data.library.update_resource(
                resource["id"],
                name=versions["name"],
                description=versions["description"],
                marked=True,
                tags=tags,
            )
        else:
            resource = self.data.library.create_resource(
                resource_kind=source_kind,
                name=versions["name"],
                description=versions["description"],
                marked=True,
                tags=tags,
            )

        requested: list[tuple[str, dict[str, Any]]] = []
        if version in {"original", "both"}:
            if not versions["original_available"]:
                if version == "original":
                    requested.append(("latest", versions["latest"]))
            else:
                requested.append(("original", versions["original"]))
        if version in {"latest", "both"}:
            requested.append(("latest", versions["latest"]))

        known_snapshots = [
            item.get("snapshot")
            for item in self.data.library.revisions(resource["id"])
        ]
        for label, payload in requested:
            snapshot = {
                "schema_version": 1,
                "resource_kind": source_kind,
                "source_variant": label,
                "payload": payload,
            }
            if snapshot in known_snapshots:
                continue
            self.data.library.add_revision(
                resource["id"],
                snapshot,
                source_project_id=project_id,
                source_story_node_id=head_node_id,
                source_kind=source_kind,
                source_key=source_key,
                note=f"Favorited {label} version",
            )
            known_snapshots.append(snapshot)
        return self.data.library.resource(resource["id"]) or resource

    def favorite_resource_tree(
        self,
        project_id: str,
        *,
        source_kind: str,
        source_key: str,
        source_story_node_id: str | None = None,
        version: str = "latest",
        dependency_tokens: list[str] | None = None,
        dependency_versions: dict[str, str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        if source_story_node_id is None:
            source_story_node_id = (self.data.db.get_project(project_id) or {}).get("active_node_id")
        preview = self.favorite_preview(
            project_id,
            source_kind=source_kind,
            source_key=source_key,
            source_story_node_id=source_story_node_id,
        )
        selected = set(dependency_tokens or [])
        allowed = {item["token"]: item for item in preview["dependencies"]}
        unknown = selected.difference(allowed)
        if unknown:
            raise ValueError(f"Unknown favorite dependency: {sorted(unknown)[0]}")
        for token in selected:
            parent_token = allowed[token]["parent_token"]
            if parent_token != preview["token"] and parent_token not in selected:
                raise ValueError(f"Favorite dependency requires its parent: {token}")

        resources: dict[str, dict[str, Any]] = {}
        root_token = preview["token"]
        resources[root_token] = self._ensure_favorite_resource(
            project_id,
            source_kind,
            source_key,
            source_story_node_id,
            version,
            tags,
        )
        dependency_versions = dependency_versions or {}
        for token in selected:
            item = allowed[token]
            resources[token] = self._ensure_favorite_resource(
                project_id,
                item["source_kind"],
                item["source_key"],
                source_story_node_id,
                dependency_versions.get(token, "latest"),
            )

        for parent_token, parent_resource in list(resources.items()):
            children: list[dict[str, Any]] = []
            for token, item in allowed.items():
                if token not in selected:
                    continue
                effective_parent = item["parent_token"]
                if effective_parent not in resources:
                    effective_parent = root_token
                if effective_parent != parent_token:
                    continue
                children.append({
                    "child_resource_id": resources[token]["id"],
                    "relation_kind": item["relation"],
                    "required": bool(item.get("default_selected", True)),
                })
            self.data.library.set_children(parent_resource["id"], children)

        return {
            "resource": self.data.library.resource(resources[root_token]["id"]),
            "published_resource_ids": [item["id"] for item in resources.values()],
            "dependency_count": len(resources) - 1,
        }
