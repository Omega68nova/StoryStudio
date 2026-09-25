# Phase 7 Slice 1 — Remaining typed entity contracts

The world projection adapter now returns explicit domain models for every
ordinary entity kind:

- Character
- Location
- Faction
- Item
- LoreSystem
- Fact
- PlotBeat

Faction, Item, LoreSystem, Fact, and PlotBeat no longer fall through the
generic entity model. Their state models cover the fields already produced or
consumed by WorldStudio and planning while continuing to preserve unknown
extension/plugin data. Sparse projections still round-trip without inferred
defaults being written back.

Item location and Fact knowledge lists expose canonical typed references.
PlotBeat status is constrained to the statuses already supported by the
editor and runtime.

## Compatibility boundary

This slice changes structural parsing only. It does not change database rows,
world events, projections, API payloads, planner schemas, or mutation
execution. Legacy relationship entities still use the generic fallback while
canonical relationship edges retain the dedicated Relationship model.

## Remaining data-contract work

The wider plan is not complete. The next dependent work is to finish and
verify canonical Character semantics, followed by Item/equipment and Ability
contracts, typed relationship definitions, semantic media slots, domain API
DTO adoption, storage normalization, and finally planner schema adoption.
