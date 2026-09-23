# Phase 6 Slice 1 — World configuration workspace

Phase 6 begins by consolidating navigation, not by redesigning working domain
editors. The application now exposes one project-scoped **World
configuration** entry point with sections for:

- world entities and relationships
- characters
- environment and locations
- rules
- GenerationPlan-based project planning
- minigames
- Bullet Hell configuration
- music
- workflows

The existing studio components remain the owners of their forms, requests,
validation, and unsaved-state tracking. Their HTTP contracts and backend
behavior are unchanged. Location links from the world editor now switch to the
environment section inside the consolidated workspace.

Application-wide runtime settings, data management, user administration, and
the story workspace remain separate top-level destinations. They are not
world configuration.

## Compatibility boundary

This slice removes the separate top-level navigation entries but does not
remove or rewrite any editor component. Switching configuration sections
honors the existing global unsaved-state signal and asks before unmounting a
dirty editor.

## Next extraction work

Phase 6 should continue as a modularization effort:

1. Extract the workflow editor and other remaining large UI blocks from
   `App.tsx` into focused modules.
2. Identify duplicated list, filter, drawer, save, and validation behavior
   across the configuration studios and move it into shared components/hooks.
3. Normalize configuration section headers and loading/error presentation.
4. Remove compatibility UI only when the consolidated replacement covers the
   same behavior.

No backend schema, persistence, generation, or runtime behavior changed in
this slice.
