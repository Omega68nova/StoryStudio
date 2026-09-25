from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from app.data.dataProvider import DataProvider
from app.database import Database
from app.domain.world import Stat
from app.services.library import GlobalLibraryService


def setup_library(path: Path):
    db = Database(path)
    db.initialize()
    data = DataProvider(db)
    return db, data, GlobalLibraryService(data)


def test_stat_pack_round_trip_is_revisioned_and_project_local(tmp_path: Path) -> None:
    db, data, library = setup_library(tmp_path)
    source = db.create_project("Source")
    data.rules.save_stat(Stat(
        project_id=source["id"],
        stat_key="max_hp",
        label="Max HP",
        compatible_owner_kinds=["character"],
        default_value=100,
        minimum=1,
        maximum=999,
    ))
    data.rules.save_stat(Stat(
        project_id=source["id"],
        stat_key="hp",
        label="HP",
        compatible_owner_kinds=["character"],
        default_value=100,
        minimum=0,
        maximum=100,
        maximum_stat_key="max_hp",
    ))
    node = db.create_story_node(source["id"], None, "user", "Keep these rules")

    saved = library.save_stat_pack(
        source["id"],
        name="Core health",
        source_story_node_id=node["id"],
        tags=["RPG", "health"],
    )
    resource = saved["resource"]
    revision = saved["revision"]
    assert resource["resource_kind"] == "stat_pack"
    assert revision["revision_number"] == 1
    assert revision["source_project_id"] == source["id"]
    assert revision["source_story_node_id"] == node["id"]
    assert [item["stat_key"] for item in revision["snapshot"]["stats"]] == ["max_hp", "hp"]

    target = db.create_project("Target")
    applied = library.apply_stat_pack(resource["id"], target["id"])
    assert applied["applied"] == ["max_hp", "hp"]
    target_hp = data.rules.stat(target["id"], "hp")
    assert target_hp is not None
    assert target_hp.project_id == target["id"]
    assert target_hp.maximum_stat_key == "max_hp"

    refreshed = data.library.resource(resource["id"])
    assert refreshed is not None
    assert refreshed["referenced_story_count"] == 1
    assert refreshed["import_count"] == 1


def test_publishing_new_stat_pack_revision_does_not_mutate_old_revision(tmp_path: Path) -> None:
    db, data, library = setup_library(tmp_path)
    project = db.create_project("Rules")
    data.rules.save_stat(Stat(
        project_id=project["id"],
        stat_key="focus",
        label="Focus",
        compatible_owner_kinds=["character"],
        default_value=5,
        minimum=0,
        maximum=10,
    ))
    first = library.save_stat_pack(project["id"], name="Focus rules")
    resource_id = first["resource"]["id"]
    first_revision_id = first["revision"]["id"]

    data.rules.save_stat(Stat(
        project_id=project["id"],
        stat_key="focus",
        label="Focus",
        compatible_owner_kinds=["character"],
        default_value=7,
        minimum=0,
        maximum=20,
    ))
    second = library.save_stat_pack(
        project["id"],
        resource_id=resource_id,
        name="Focus rules",
        note="Expanded range",
    )

    original = data.library.revision(first_revision_id)
    assert original is not None
    assert original["snapshot"]["stats"][0]["maximum"] == 10
    assert second["revision"]["revision_number"] == 2
    assert second["revision"]["snapshot"]["stats"][0]["maximum"] == 20


def test_library_resources_form_explicit_dependency_trees(tmp_path: Path) -> None:
    _, data, _ = setup_library(tmp_path)
    character = data.library.create_resource(
        resource_kind="character",
        name="Reusable Hero",
        marked=True,
        tags=["hero"],
    )
    outfit = data.library.create_resource(resource_kind="outfit", name="Travel coat")
    ability = data.library.create_resource(resource_kind="ability", name="Dash")

    data.library.set_children(character["id"], [
        {"child_resource_id": outfit["id"], "relation_kind": "outfit", "required": True},
        {"child_resource_id": ability["id"], "relation_kind": "ability", "required": False},
    ])

    loaded = data.library.resource(character["id"])
    assert loaded is not None
    assert [item["relation_kind"] for item in loaded["children"]] == ["outfit", "ability"]
    assert [item["name"] for item in loaded["children"]] == ["Travel coat", "Dash"]


def test_library_resource_tree_rejects_cycles(tmp_path: Path) -> None:
    _, data, _ = setup_library(tmp_path)
    parent = data.library.create_resource(resource_kind="bundle", name="Parent")
    child = data.library.create_resource(resource_kind="bundle", name="Child")
    data.library.set_children(parent["id"], [{"child_resource_id": child["id"]}])
    with pytest.raises(ValueError, match="cycles"):
        data.library.set_children(child["id"], [{"child_resource_id": parent["id"]}])


def test_library_revision_provenance_rejects_cross_project_story_node(tmp_path: Path) -> None:
    db, data, _ = setup_library(tmp_path)
    first = db.create_project("First")
    second = db.create_project("Second")
    node = db.create_story_node(first["id"], None, "user", "branch")
    resource = data.library.create_resource(resource_kind="bundle", name="Bundle")
    with pytest.raises(ValueError, match="does not belong"):
        data.library.add_revision(
            resource["id"],
            {"schema_version": 1},
            source_project_id=second["id"],
            source_story_node_id=node["id"],
        )


def test_library_revision_rows_are_immutable(tmp_path: Path) -> None:
    db, data, _ = setup_library(tmp_path)
    resource = data.library.create_resource(resource_kind="bundle", name="Immutable")
    revision = data.library.add_revision(resource["id"], {"schema_version": 1, "value": "first"})
    with pytest.raises(sqlite3.IntegrityError, match="library revisions are immutable"):
        db.execute(
            "UPDATE library_resource_revisions SET snapshot_json=? WHERE id=?",
            ('{"schema_version":1,"value":"changed"}', revision["id"]),
        )
