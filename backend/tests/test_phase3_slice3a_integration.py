from app.data.dataProvider import DataProvider
from app.services.routeDataService import RouteDataService


class FakeDb:
    def fetch_one(self, sql: str, parameters=()):
        if "generation_jobs WHERE id" in sql:
            return {
                "id": "j1",
                "project_id": "p1",
                "kind": "story",
                "status": "completed",
                "payload_json": '{"secret":"value"}',
                "result_json": '{"story_node_id":"n1"}',
                "metrics_json": '{}',
                "requested_by_user_id": "u1",
                "requester_name_snapshot": "User",
            }
        return None

    def fetch_all(self, sql: str, parameters=()):
        if "user_project_access" in sql:
            return [{"project_id": "p1"}]
        if "generation_jobs" in sql:
            return [{
                "id": "j1",
                "project_id": "p1",
                "kind": "story",
                "status": "completed",
                "payload_json": '{"secret":"value"}',
                "result_json": '{"story_node_id":"n1"}',
                "metrics_json": '{}',
                "requested_by_user_id": "u1",
                "requester_name_snapshot": "User",
            }]
        return []

    def execute(self, sql: str, parameters=()):
        return None


def test_member_job_list_hides_payload_and_result() -> None:
    service = RouteDataService(DataProvider(FakeDb()))
    jobs = service.list_jobs(admin=False, assigned_project_ids=["p1"])
    assert len(jobs) == 1
    assert "payload" not in jobs[0]
    assert "result" not in jobs[0]


def test_member_cannot_request_unassigned_project_jobs() -> None:
    service = RouteDataService(DataProvider(FakeDb()))
    try:
        service.list_jobs(
            admin=False,
            assigned_project_ids=["p1"],
            requested_project_id="p2",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("Expected PermissionError")


def test_member_get_job_hides_payload_and_result() -> None:
    service = RouteDataService(DataProvider(FakeDb()))
    job = service.get_job("j1", admin=False)
    assert job is not None
    assert "payload" not in job
    assert "result" not in job
