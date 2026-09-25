# Phase 3 — Slice 3A Integration

Safe route integration only.

Integrated:
- project listing
- workflow listing
- workflow delete and delete-impact
- job listing/get/cancel/history

Deferred:
- full project bundle/minigame assembly
- workflow create/update graph validation
- planning transactions (Slice 3B)
- WorldEngine persistence (Slice 4)

Apply from repository root:

    python apply_phase3a_integration.py

Then from backend:

    python -m pytest tests/test_phase3_slice3a.py tests/test_phase3_slice3a_integration.py
    python -m compileall app
