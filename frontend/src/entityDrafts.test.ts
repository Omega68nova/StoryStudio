import { describe, expect, it } from "vitest";
import { applyAdvancedState, entityToDraft, normalizeStringList, updateDraftState } from "./entityDrafts";
import type { WorldEntity } from "./types";

const entity: WorldEntity = {
  id: "character-1",
  kind: "character",
  name: "Mara",
  aliases: ["  Captain ", "captain", "Mara"],
  tags: [" Hero ", "hero", "Pilot"],
  state: { personality: "Patient", custom_plugin_state: { rank: 7 } },
  card: { compact_text: "Mara", visual_description: "", image_tags: [], search_text: "mara" },
};

describe("entity editor drafts", () => {
  it("normalizes aliases and tags with trimmed case-insensitive uniqueness", () => {
    expect(normalizeStringList([" Hero ", "hero", "PILOT", "pilot", ""])).toEqual(["Hero", "PILOT"]);
    const draft = entityToDraft(entity);
    expect(draft.aliases).toEqual(["Captain", "Mara"]);
    expect(draft.tags).toEqual(["Hero", "Pilot"]);
  });

  it("preserves unknown state fields across structured and advanced edits", () => {
    const structured = updateDraftState(entityToDraft(entity), { personality: "Bold" });
    expect(structured.state.custom_plugin_state).toEqual({ rank: 7 });
    const advanced = applyAdvancedState(structured, structured.advancedState);
    expect(advanced.state).toMatchObject({ personality: "Bold", custom_plugin_state: { rank: 7 } });
  });

  it("does not replace the last valid state when advanced JSON is invalid", () => {
    const draft = entityToDraft(entity);
    expect(() => applyAdvancedState(draft, "{invalid")).toThrow();
    expect(draft.state.custom_plugin_state).toEqual({ rank: 7 });
  });
});
