from app.data.dataProvider import DataProvider
from app.handlers.storyFinalizer import StoryFinalizer
from app.services.environment import EnvironmentService


class FakeDb:
    def fetch_one(self, sql: str, parameters=()):
        if "project_environment_settings" in sql:
            return {
                "project_id": "p1",
                "enabled": 1,
                "ai_create_locations": 0,
                "ai_propose_weather": 0,
                "auto_generate_backgrounds": 0,
                "initial_weather_id": "w1",
                "revision": 1,
            }
        return None

    def fetch_all(self, sql: str, parameters=()):
        if "weather_definitions" in sql and "ORDER BY name COLLATE NOCASE" in sql:
            return [{
                "id": "w1",
                "project_id": "p1",
                "name": "Sunny",
                "description": "Clear",
                "tags_json": "[]",
                "image_tags_json": "[]",
                "enabled": 1,
            }]
        if "time_phases" in sql:
            return []
        return []

    def execute(self, sql: str, parameters=()):
        return None


class FakeWorld:
    def projection(self, project_id: str, head_node_id=None):
        return {"entities": {}, "relations": {}, "elapsed_minutes": 0}


def test_data_provider_slice2_repositories_exist() -> None:
    data = DataProvider(FakeDb())
    assert data.media.db is data.db
    assert data.reviews.db is data.db
    assert data.workflows.db is data.db


def test_environment_service_reads_through_repository() -> None:
    service = EnvironmentService(FakeDb())
    settings = service.settings("p1")
    assert settings["enabled"] is True
    assert settings["weather"][0]["name"] == "Sunny"


def test_story_finalizer_accepts_data_provider() -> None:
    db = FakeDb()
    data = DataProvider(db)
    finalizer = StoryFinalizer(
        db,
        events=object(),
        world=FakeWorld(),
        enqueue=lambda _: None,
        data_provider=data,
    )
    assert finalizer.media is data.media
    assert finalizer.reviews is data.reviews
