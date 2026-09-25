# StoryStudio Phase 3 — Final Cleanup

This package closes the repository-refactor phase without pretending that every
SQL statement in the application belongs in a single generic repository.

Included:
- AuthRepository + repository-backed AuthService
- LifecycleRepository + repository-backed DataLifecycle
- DataProvider wiring for auth/lifecycle
- migration of the five stale regression tests identified after the refactor
- Phase 3 architectural boundary guard

The five test migrations preserve behavior:
- workflow deletion test now patches DataProvider with the test DB
- multiplayer project-list test now patches DataProvider/RouteDataService
- raw planning retry test targets PlanningJobHandler
- story cancellation now asserts all streamed prose is preserved
- obsolete sentence-truncation helper test is removed

Apply from the repository root:

    python apply_phase3_final_cleanup.py

Then:

    cd backend
    python -m compileall app
    python -m pytest -q

Expected result: the previously reported 5 failures should be gone.

Phase 3 completion criteria used here:
- managers no longer own persistence SQL
- typed repositories exist for project/story/job/planning/workflow/media/review/
  environment/music/sound/world/auth/lifecycle
- WorldEngine retains semantics while storage is repository-backed
- Planning control persistence is repository-backed
- route-level repository/service boundaries are established
- regression suite reflects the new ownership boundaries

Residual raw SQL in specialized domain services/routes is intentionally not
moved into a generic repository merely to make an audit count reach zero.
Future domain work (BatchGeneration, typed world model, minigames/bullethell)
can move those statements into their own repositories when those domains are
reworked.
