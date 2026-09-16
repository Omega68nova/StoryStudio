import { describe, expect, it } from "vitest";
import { newestLeaf, storyPath } from "./tree";
import type { StoryNode } from "./types";

const node = (id: string, parent_id: string | null): StoryNode => ({
  id, parent_id, project_id: "p", role: "user", content: id, status: "complete", created_at: id
});

describe("story tree", () => {
  it("returns only the selected ancestry", () => {
    expect(storyPath([node("a", null), node("b", "a"), node("c", "a")], "c").map((n) => n.id)).toEqual(["a", "c"]);
  });

  it("selects the newest leaf", () => {
    expect(newestLeaf([node("a", null), node("b", "a"), node("c", "a")])).toBe("c");
  });
});

