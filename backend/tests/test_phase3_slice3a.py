from app.data.dataProvider import DataProvider
from app.services.routeDataService import RouteDataService


class FakeDb:
    def fetch_one(self, sql: str, parameters=()):
        if "FROM projects WHERE id" in sql:
            return {
                "id": "p1",
                "title": "Test",
                "active_node_id": None,
            }
        if "project_story_settings" in sql:
            return {
                "default_generation_mode": "low",
                "response_max_tokens": 300,
                "ai_instructions": "secret",
            }
        return None

    def fetch_all(self, sql: str, parameters=()):
        return []

    def execute(self, sql: str, parameters=()):
        return None

    def story_path(self, leaf_id):
        return []

    def create_job(self, *args, **kwargs):
        return {"id": "j1", "project_id": args[0], "kind": args[1]}

    def create_story_node(self, *args, **kwargs):
        return {"id": "n1", "project_id": args[0]}


def test_data_provider_exposes_slice3_repositories() -> None:
    data = DataProvider(FakeDb())
    assert data.projects.db is data.db
    assert data.stories.db is data.db
    assert data.jobs.db is data.db


def test_route_data_hides_ai_instructions_for_members() -> None:
    service = RouteDataService(DataProvider(FakeDb()))
    settings = service.story_settings(
        "p1",
        include_ai_instructions=False,
    )
    assert "ai_instructions" not in settings


def test_route_data_project_bundle_has_no_sql_dependency() -> None:
    service = RouteDataService(DataProvider(FakeDb()))
    bundle = service.project_bundle(
        "p1",
        admin=True,
        user_id="u1",
    )
    assert bundle is not None
    assert bundle["title"] == "Test"
    assert bundle["story_nodes"] == []
    assert bundle["active_jobs"] == []
