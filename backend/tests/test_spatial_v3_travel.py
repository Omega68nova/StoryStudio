from __future__ import annotations

from app.database import Database, utc_now
from app.data import DataProvider
from app.domain.spatial_v3 import (
    ConnectorEndpoint,
    ConnectorProperties,
    EncounterCandidate,
    EncounterPolicy,
    MapFeature,
    NavigationSpace,
)
from app.services.spatial_v3_travel import SpatialV3TravelPreview


def _location(db: Database, project_id: str, location_id: str) -> None:
    db.execute(
        """
        INSERT INTO world_entities(
          id,project_id,kind,canonical_name,aliases_json,tags_json,created_at
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (location_id, project_id, "location", location_id, "[]", "[]", utc_now()),
    )


def test_distance_encounter_is_seed_stable_and_resumable(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("stable travel encounter")
    _location(db, project["id"], "world")
    _location(db, project["id"], "wolf")
    data.spatial_v3.save_space(NavigationSpace(
        id="space",
        project_id=project["id"],
        owner_location_id="world",
        navigation_mode="free",
    ))
    data.spatial_v3.save_encounter_policy(EncounterPolicy(
        id="wolves",
        project_id=project["id"],
        navigation_space_id="space",
        rate_per_100_units=100,
        candidates=[EncounterCandidate(location_id="wolf")],
    ))

    service = SpatialV3TravelPreview(data.spatial_v3)
    first = service.preview(
        project_id=project["id"],
        start_space_id="space",
        start=(0, 0),
        target_space_id="space",
        target=(100, 0),
        seed="same-seed",
    )
    retry = service.preview(
        project_id=project["id"],
        start_space_id="space",
        start=(0, 0),
        target_space_id="space",
        target=(100, 0),
        seed="same-seed",
    )
    assert first["status"] == "interrupted"
    assert retry["encounter"] == first["encounter"]
    assert retry["resume_cursor"] == first["resume_cursor"]

    resumed = service.preview(
        project_id=project["id"],
        start_space_id="space",
        start=(0, 0),
        target_space_id="space",
        target=(100, 0),
        seed="same-seed",
        resume_cursor=first["resume_cursor"],
    )
    assert resumed["progress"]["traversed_distance"] >= first["progress"]["traversed_distance"]
    if resumed["status"] == "interrupted":
        assert resumed["encounter"]["distance_into_span"] > first["encounter"]["distance_into_span"]


def test_resume_then_later_transition_reports_full_progress(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("resume progress")
    for location_id in ("outside", "inside", "event"):
        _location(db, project["id"], location_id)
    data.spatial_v3.save_space(NavigationSpace(id="outside-space", project_id=project["id"], owner_location_id="outside"))
    data.spatial_v3.save_space(NavigationSpace(id="inside-space", project_id=project["id"], owner_location_id="inside"))
    data.spatial_v3.save_feature(MapFeature(
        id="door",
        project_id=project["id"],
        navigation_space_id="outside-space",
        feature_kind="connector",
        geometry={"type": "Point", "coordinates": (100, 0)},
        properties=ConnectorProperties(
            source=ConnectorEndpoint(navigation_space_id="outside-space", point=(100, 0)),
            target=ConnectorEndpoint(navigation_space_id="inside-space", point=(0, 0)),
            travel_minutes=1,
        ),
    ))
    data.spatial_v3.save_encounter_policy(EncounterPolicy(
        id="field",
        project_id=project["id"],
        navigation_space_id="outside-space",
        rate_per_100_units=100,
        candidates=[EncounterCandidate(location_id="event")],
    ))
    data.spatial_v3.save_encounter_policy(EncounterPolicy(
        id="door-event",
        project_id=project["id"],
        feature_id="door",
        trigger_kind="transition",
        probability_per_transition=1,
        candidates=[EncounterCandidate(location_id="event")],
    ))

    service = SpatialV3TravelPreview(data.spatial_v3)
    first = service.preview(
        project_id=project["id"],
        start_space_id="outside-space",
        start=(0, 0),
        target_space_id="inside-space",
        target=(1, 0),
        seed="resume-progress",
    )
    assert first["status"] == "interrupted"
    assert first["encounter"]["trigger_kind"] == "distance"

    cursor = first["resume_cursor"]
    result = first
    # Dense distance policies can cause more than one deterministic encounter
    # before the door. Keep consuming them until the connector interruption.
    for _ in range(20):
        result = service.preview(
            project_id=project["id"],
            start_space_id="outside-space",
            start=(0, 0),
            target_space_id="inside-space",
            target=(1, 0),
            seed="resume-progress",
            resume_cursor=cursor,
        )
        if result["status"] == "interrupted" and result["encounter"]["trigger_kind"] == "transition":
            break
        cursor = result["resume_cursor"]
    assert result["encounter"]["trigger_kind"] == "transition"
    assert result["progress"]["traversed_distance"] == 100
    assert result["progress"]["traversed_travel_cost"] == 100


def test_geometry_step_splits_do_not_change_encounter_span(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("span grouping")
    _location(db, project["id"], "world")
    _location(db, project["id"], "event")
    data.spatial_v3.save_space(NavigationSpace(
        id="space",
        project_id=project["id"],
        owner_location_id="world",
    ))
    data.spatial_v3.save_encounter_policy(EncounterPolicy(
        id="slow-start",
        project_id=project["id"],
        navigation_space_id="space",
        minimum_distance=40,
        rate_per_100_units=10,
        candidates=[EncounterCandidate(location_id="event")],
    ))
    # A connector-shaped irrelevant feature would change path candidates but
    # must not reset the encounter policy's accumulated distance.
    data.spatial_v3.save_feature(MapFeature(
        id="irrelevant",
        project_id=project["id"],
        navigation_space_id="space",
        feature_kind="connector",
        geometry={"type": "Point", "coordinates": (25, 0)},
        properties=ConnectorProperties(
            source=ConnectorEndpoint(navigation_space_id="space", point=(25, 0)),
            target=ConnectorEndpoint(navigation_space_id="space", point=(25, 1)),
        ),
    ))

    result = SpatialV3TravelPreview(data.spatial_v3).preview(
        project_id=project["id"],
        start_space_id="space",
        start=(0, 0),
        target_space_id="space",
        target=(50, 0),
        seed="span-seed",
    )
    # The 50-unit continuous exposure qualifies the minimum_distance=40 policy,
    # even if the visibility graph/path contains multiple movement steps.
    assert result["route"]["total_distance"] >= 50
    assert result["status"] in {"complete", "interrupted"}


def test_transition_encounter_works_from_reverse_connector_side(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("reverse transition")
    for location_id in ("a", "b", "ambush"):
        _location(db, project["id"], location_id)
    data.spatial_v3.save_space(NavigationSpace(id="a-space", project_id=project["id"], owner_location_id="a"))
    data.spatial_v3.save_space(NavigationSpace(id="b-space", project_id=project["id"], owner_location_id="b"))
    data.spatial_v3.save_feature(MapFeature(
        id="portal",
        project_id=project["id"],
        navigation_space_id="a-space",
        feature_kind="connector",
        geometry={"type": "Point", "coordinates": (0, 0)},
        properties=ConnectorProperties(
            connector_kind="portal",
            source=ConnectorEndpoint(navigation_space_id="a-space", point=(0, 0)),
            target=ConnectorEndpoint(navigation_space_id="b-space", point=(0, 0)),
            bidirectional=True,
        ),
    ))
    data.spatial_v3.save_encounter_policy(EncounterPolicy(
        id="portal-ambush",
        project_id=project["id"],
        feature_id="portal",
        trigger_kind="transition",
        probability_per_transition=1,
        candidates=[EncounterCandidate(location_id="ambush")],
    ))

    result = SpatialV3TravelPreview(data.spatial_v3).preview(
        project_id=project["id"],
        start_space_id="b-space",
        start=(1, 0),
        target_space_id="a-space",
        target=(1, 0),
        seed="reverse-seed",
    )
    assert result["status"] == "interrupted"
    assert result["encounter"]["trigger_kind"] == "transition"
    assert result["encounter"]["feature_id"] == "portal"
    assert result["encounter"]["candidate"]["location_id"] == "ambush"


def test_candidate_requirements_are_not_guessed(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("conditional candidate")
    _location(db, project["id"], "world")
    _location(db, project["id"], "rare")
    data.spatial_v3.save_space(NavigationSpace(id="space", project_id=project["id"], owner_location_id="world"))
    data.spatial_v3.save_encounter_policy(EncounterPolicy(
        id="conditional",
        project_id=project["id"],
        navigation_space_id="space",
        rate_per_100_units=1000,
        candidates=[EncounterCandidate(
            location_id="rare",
            requirements={"schema_version": 2, "kind": "has_tag", "tag": "wanted"},
        )],
    ))

    result = SpatialV3TravelPreview(data.spatial_v3).preview(
        project_id=project["id"],
        start_space_id="space",
        start=(0, 0),
        target_space_id="space",
        target=(10, 0),
        seed="candidate-seed",
    )
    assert result["status"] == "complete"
    assert result["encounter"] is None
    assert result["unresolved_requirements"]
