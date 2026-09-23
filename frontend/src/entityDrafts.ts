import type { EntityEditorDraft, WorldEntity } from "./types";

export function normalizeStringList(values: unknown[]): string[] {
  const seen = new Set<string>();
  return values.reduce<string[]>((result, raw) => {
    const value = String(raw ?? "").trim(), key = value.toLocaleLowerCase();
    if (value && !seen.has(key)) { seen.add(key); result.push(value); }
    return result;
  }, []);
}

export function entityToDraft(entity: WorldEntity): EntityEditorDraft {
  const state = structuredClone(entity.state ?? {});
  if (entity.kind === "character") {
    if (!String(state.description ?? "").trim() && state.identity) {
      state.description = state.identity;
    }
    if (!String(state.personality ?? "").trim() && state.core_personality) {
      state.personality = state.core_personality;
    }
    if (!String(state.wardrobe_notes ?? "").trim() && state.wardrobe) {
      state.wardrobe_notes = state.wardrobe;
    }
    delete state.identity;
    delete state.core_personality;
    delete state.wardrobe;
    if (state.full_body_height_factor == null) {
      state.full_body_height_factor = 0.5;
    }
    if (state.imagegen_description == null) {
      state.imagegen_description = "";
    }
  }
  return { id: entity.id, kind: entity.kind, name: entity.name, aliases: normalizeStringList(entity.aliases ?? []), tags: normalizeStringList(entity.tags ?? []), state, advancedState: JSON.stringify(state, null, 2) };
}

export function newEntityDraft(kind: string): EntityEditorDraft {
  const state: Record<string, unknown> = kind === "plot_beat" ? { status: "planned" } : {};
  return { kind, name: "", aliases: [], tags: [], state, advancedState: JSON.stringify(state, null, 2) };
}

export function updateDraftState(draft: EntityEditorDraft, patch: Record<string, unknown>): EntityEditorDraft {
  const state = { ...draft.state, ...patch };
  return { ...draft, state, advancedState: JSON.stringify(state, null, 2) };
}

export function applyAdvancedState(draft: EntityEditorDraft, source: string): EntityEditorDraft {
  const parsed = JSON.parse(source);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("Advanced state must be a JSON object");
  return { ...draft, state: parsed, advancedState: JSON.stringify(parsed, null, 2) };
}
