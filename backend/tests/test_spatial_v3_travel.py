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
from app.services.spatial_v3 import SpatialV3Service
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
        rate_per_100_units=1,
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
    route = service.pathfinder.plan(
        project_id=project["id"],
        start_space_id="outside-space",
        start=(0, 0),
        target_space_id="inside-space",
        target=(1, 0),
    )
    signature = service._route_signature(route)
    # Simulate resuming after an already-consumed movement encounter at x=50.
    # Pick an ordinal whose next exponential interval is beyond the remaining
    # 50 units, so the next interruption is deterministically the door.
    ordinal = next(
        value
        for value in range(1000)
        if -__import__("math").log(
            1.0 - service._stable_uniform(
                "resume-progress", signature, 0, value, "distance"
            )
        ) / 0.01 > 50
    )
    cursor = service._encode_cursor({
        "route_signature": signature,
        "seed_hash": __import__("hashlib").sha256(b"resume-progress").hexdigest(),
        "unit_index": 0,
        "distance_offset": 50,
        "encounter_ordinal": ordinal,
    })

    result = service.preview(
        project_id=project["id"],
        start_space_id="outside-space",
        start=(0, 0),
        target_space_id="inside-space",
        target=(1, 0),
        seed="resume-progress",
        resume_cursor=cursor,
    )
    assert result["status"] == "interrupted"
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
    from app.domain.spatial_v3 import BarrierProperties
    data.spatial_v3.save_feature(MapFeature(
        id="wall",
        project_id=project["id"],
        navigation_space_id="space",
        feature_kind="barrier",
        geometry={"type": "LineString", "coordinates": [(25, -5), (25, 5)]},
        properties=BarrierProperties(),
    ))

    service = SpatialV3TravelPreview(data.spatial_v3)
    route = service.pathfinder.plan(
        project_id=project["id"],
        start_space_id="space",
        start=(0, 0),
        target_space_id="space",
        target=(50, 0),
    )
    assert len(route["steps"]) > 1
    units = service._units(project["id"], route)
    movement_units = [unit for unit in units if unit["kind"] == "movement"]
    assert len(movement_units) == 1
    assert len(movement_units[0]["parts"]) > 1
    context = service._movement_context(project["id"], movement_units[0])
    assert context["rate_per_100_units"] == 10
    assert "slow-start" in context["policy_ids"]


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


def test_encounter_policy_and_candidate_conditions_use_shared_evaluator(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("conditional encounters")
    for location_id in ("a", "b", "ambush", "blocked"):
        _location(db, project["id"], location_id)
    data.spatial_v3.save_space(NavigationSpace(id="a-space", project_id=project["id"], owner_location_id="a"))
    data.spatial_v3.save_space(NavigationSpace(id="b-space", project_id=project["id"], owner_location_id="b"))
    data.spatial_v3.save_feature(MapFeature(
        id="gate",
        project_id=project["id"],
        navigation_space_id="a-space",
        feature_kind="connector",
        geometry={"type": "Point", "coordinates": (0, 0)},
        properties=ConnectorProperties(
            source=ConnectorEndpoint(navigation_space_id="a-space", point=(0, 0)),
            target=ConnectorEndpoint(navigation_space_id="b-space", point=(0, 0)),
        ),
    ))
    data.spatial_v3.save_encounter_policy(EncounterPolicy(
        id="conditioned",
        project_id=project["id"],
        feature_id="gate",
        trigger_kind="transition",
        probability_per_transition=1,
        conditions={"kind": "has_tag", "tag": "wanted"},
        candidates=[
            EncounterCandidate(
                location_id="ambush",
                requirements={"kind": "has_tag", "tag": "wanted"},
            ),
            EncounterCandidate(
                location_id="blocked",
                requirements={"kind": "has_tag", "tag": "never"},
            ),
        ],
    ))

    seen = []
    service = SpatialV3Service(
        data.spatial_v3,
        condition_evaluator=lambda payload: seen.append(payload) is None and False
        if payload.get("tag") == "never"
        else payload.get("tag") == "wanted",
    )
    context = service.transition_encounter_context(
        project_id=project["id"],
        navigation_space_id="a-space",
        feature_id="gate",
    )
    assert context["enabled"] is True
    assert context["probability"] == 1
    assert [item["location_id"] for item in context["candidates"]] == ["ambush"]
    assert not context["unresolved_conditions"]
    assert not context["unresolved_candidates"]
    assert seen
