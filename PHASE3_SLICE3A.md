# Phase 3 — Slice 3A: Route Data Boundaries

Slice 3 is intentionally split into 3A and 3B.

## Why split it

`planning_v2.py` does much more than CRUD. It performs multi-table publishing,
resource-key resolution, validation, and world transaction coordination.
Moving it at the same time as ordinary HTTP route queries would make the
change much harder to verify.

## Slice 3A adds

- `ProjectRepository`
- `StoryRepository`
- `JobRepository`
- `PlanningRepository` read boundary
- expanded `DataProvider`
- `RouteDataService`

The service composes repository reads into the same project/job payload shapes
that `main.py` currently builds manually.

## Transitional methods

`ProjectRepository`, `StoryRepository`, and `JobRepository` currently delegate
project creation, story-node creation, story-path traversal, and job creation to
the existing `Database` methods. Those methods already contain tested atomic
behavior. They will be moved into repositories after route integration is
verified, rather than duplicated in one large step.

## main.py integration

This package deliberately does not replace the giant `main.py`.

The next small integration step should instantiate once:

    data = DataProvider(db)
    route_data = RouteDataService(
        data,
        minigame_loader=scheduler.minigames.get_session,
    )

Then migrate endpoint groups one at a time:
1. `/api/projects` list/get/story-settings/title/bible
2. `/api/jobs`
3. `/api/workflows` using `data.workflows`
4. story revision/subtree/head helpers using `data.stories`

After each group, run tests and smoke-test the app.

## Slice 3B

- move planning session/stage persistence behind `PlanningRepository`
- keep planning domain validation/publishing in planning services
- isolate planning transaction boundaries
- remove raw SQL from route-level planning endpoints

## Validation

From `backend/`:

    python -m pytest \
      tests/test_phase3_data_provider.py \
      tests/test_phase3_slice2.py \
      tests/test_phase3_slice3a.py

    python -m compileall app
