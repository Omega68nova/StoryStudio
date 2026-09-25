# StoryStudio Phase 3 Closure

Grounded against GitHub master commit:

    be19bbc3d6329fb05fdfe8cfc5affe1d012bc63f

The final failing boundary test was partly a false positive:
- aiManager.py contained the English phrase `Update llama.cpp`
- musicManager.py contained the English phrase `Select an enabled theme`

storyManager.py did still contain two genuine DB reads.

This patch:
- adds RuntimeRepository
- wires it into DataProvider
- adds StoryRepository.branch_summary_for_path()
- moves StoryManager story-path, branch-summary, and runtime-settings reads
  behind repositories
- replaces the substring-based manager SQL test with an AST-based test that
  checks actual direct db.fetch_one/db.fetch_all/db.execute calls

Apply from repository root:

    python apply_phase3_closure.py

Then:

    cd backend
    python -m compileall app
    python -m pytest -q

Expected from the current state: all 149 tests should pass.
