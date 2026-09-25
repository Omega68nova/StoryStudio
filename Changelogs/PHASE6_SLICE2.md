# Phase 6 Slice 2 — Workflow editor extraction

The ComfyUI workflow preset editor now lives in `frontend/src/WorkflowStudio.tsx`
instead of the application root. `WorldConfigurationStudio` renders it
directly and receives only the existing workflow list, reload callback, and
error callback.

This is a behavior-preserving extraction. It retains:

- API- and UI-format JSON import
- automatic mapping suggestions
- ComfyUI metadata-assisted input selection
- normal and transparent output mapping
- workflow creation, update, validation, and deletion
- existing API routes and payload shapes

No backend, persistence, or workflow schema changed. The extraction removes a
large configuration responsibility from `App.tsx` without introducing a new
state owner or compatibility facade.

The next Phase 6 slice should extract another coherent responsibility from
`App.tsx`—preferably runtime settings—or consolidate repeated configuration
editor behavior only where two or more existing studios already implement the
same contract.
