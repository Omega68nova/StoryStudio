import { describe, expect, it } from "vitest";
import { normalizeCreatableValues } from "./BoxedMultiselect";

describe("creatable boxed multiselect", () => {
  it("trims tags and deduplicates them without regard to case", () => {
    expect(normalizeCreatableValues([" rain ", "Rain", "", "wind"])).toEqual(["rain", "wind"]);
  });
});
