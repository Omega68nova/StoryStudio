# StoryStudio Phase 3 Cleanup Audit

This report is generated from the current local checkout, not from the GitHub baseline.

## Test inventory

- Total test files: 31
- Phase 3 test files: 7
- Legacy test files: 24

## Pytest result

- Return code: 2
- Failed nodes: 0

## Raw SQL outside repositories/database

Found 526 SQL literals requiring review.

| File | SQL literals |
|---|---:|
| `app/main.py` | 290 |
| `app/services/planning_v2.py` | 53 |
| `app/services/planning.py` | 43 |
| `app/services/lifecycle.py` | 27 |
| `app/services/minigames/bullethell/catalog.py` | 24 |
| `app/services/world.py` | 17 |
| `app/handlers/storyJobHandler.py` | 13 |
| `app/services/auth.py` | 13 |
| `app/handlers/imageJobHandler.py` | 11 |
| `app/services/minigames/service.py` | 11 |
| `app/services/story_planner.py` | 5 |
| `app/handlers/planningJobHandler.py` | 4 |
| `app/bootstrap_admin.py` | 2 |
| `app/managers/musicManager.py` | 2 |
| `app/managers/storyManager.py` | 2 |
| `app/services/memory.py` | 2 |
| `app/services/runtimes.py` | 2 |
| `app/services/scheduler.py` | 2 |
| `app/handlers/storyInlineActions.py` | 1 |
| `app/managers/aiManager.py` | 1 |
| `app/services/image_prompt.py` | 1 |

## Transitional Database facade calls

Found 549 calls outside repositories/database.

| Method | Count |
|---|---:|
| `fetch_one` | 200 |
| `execute` | 157 |
| `fetch_all` | 89 |
| `update_job` | 22 |
| `get_job` | 17 |
| `connect` | 17 |
| `create_job` | 12 |
| `update_job_progress` | 9 |
| `story_path` | 9 |
| `update_job_partial_output` | 4 |
| `update_job_payload` | 4 |
| `get_project` | 3 |
| `update_job_metrics` | 2 |
| `finish_transaction` | 2 |
| `create_story_node` | 1 |
| `begin_transaction` | 1 |

### Files with the most facade calls

- `app/main.py` — 293
- `app/services/planning_v2.py` — 54
- `app/services/planning.py` — 35
- `app/services/minigames/bullethell/catalog.py` — 21
- `app/handlers/imageJobHandler.py` — 20
- `app/services/world.py` — 20
- `app/handlers/planningJobHandler.py` — 17
- `app/services/lifecycle.py` — 16
- `app/handlers/storyJobHandler.py` — 15
- `app/services/scheduler.py` — 15
- `app/services/auth.py` — 13
- `app/services/minigames/service.py` — 11
- `app/services/story_planner.py` — 5
- `app/handlers/storyFinalizer.py` — 4
- `app/managers/storyManager.py` — 3
- `app/services/memory.py` — 3
- `app/bootstrap_admin.py` — 2
- `app/handlers/storyInlineActions.py` — 1
- `app/services/image_prompt.py` — 1

## Recommended interpretation

- A legacy test is safe to update/remove only when its failure is caused by an intentionally removed persistence boundary or constructor assumption.
- Behavioral assertions should be preserved and redirected through repositories/services rather than deleted.
- SQL still present in managers/handlers/services should normally move to an existing typed repository or a new narrow domain repository.
- `connect`, `begin_transaction`, and `finish_transaction` calls are lower priority when they guard a domain-level atomic operation, but should still be reviewed.
- Do not move unrelated domain SQL into `WorldRepository` or `PlanningRepository` merely to make this report smaller.
