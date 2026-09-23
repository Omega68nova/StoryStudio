import type { PlanningSession, PlanningStage } from "./types";

/**
 * Planning specialization metadata for GenerationPlan tasks.
 *
 * Planning's fixed eight-task specialization now consumes the same task wire
 * vocabulary as every other GenerationPlan client.
 */
export const PLANNING_TASK_NAMES = [
  "Foundation",
  "Macro world & weather",
  "Detailed locations",
  "Rules, stats & abilities",
  "Cast",
  "Character details & hooks",
  "Runtime presentation",
  "Images",
];

export const PLANNING_TASK_SECTIONS: Record<number, string[]> = {
  2: ["locations", "weather", "factions", "routes"],
  3: ["locations", "routes"],
  4: ["stats", "abilities", "lore_systems", "items"],
  5: ["characters", "factions", "facts"],
  6: ["character_updates", "outfits", "relationships", "routines", "facts", "plot_beats"],
  7: ["minigames", "bullethell", "ambient", "music"],
};

export const PLANNING_TASK_SECTION_FIELDS: Record<number, Record<string, string[]>> = {
  2: {
    locations: ["locations", "routes"],
    weather: ["weather", "weather_transitions", "initial_weather_key"],
    factions: ["factions"],
    routes: ["routes"],
  },
  3: { locations: ["locations", "routes"], routes: ["routes"] },
  4: { lore_systems: ["lore_systems"], stats: ["stats"], abilities: ["abilities"], items: ["items"] },
  5: { characters: ["characters", "default_pov_character_key"], factions: ["factions"], facts: ["facts"] },
  6: {
    character_updates: ["character_updates"],
    outfits: ["outfits"],
    relationships: ["relationships"],
    routines: ["routines"],
    facts: ["facts"],
    plot_beats: ["plot_beats"],
  },
  7: { minigames: ["minigames"], bullethell: ["bullethell"], ambient: ["ambient"], music: ["music"] },
};

export type PlanningGenerationPlanView = PlanningSession & {
  tasks: PlanningStage[];
  current_task: number;
};

export function planningGenerationPlanView(
  wire: PlanningSession,
): PlanningGenerationPlanView {
  return wire;
}

export function clearPlanningTaskSection(taskNumber: number, focus: string, draft: any): any {
  const next = structuredClone(draft);
  const blank = emptyPlanningTask(taskNumber);
  for (const field of PLANNING_TASK_SECTION_FIELDS[taskNumber]?.[focus] ?? [focus]) {
    next[field] = structuredClone(blank[field]);
  }
  return next;
}

export function emptyPlanningTask(taskNumber: number): any {
  const common = { summary: "", notes: [] };
  return taskNumber === 1
    ? {
        ...common,
        foundation: {
          premise: "",
          genres: [],
          themes: [],
          tone: "",
          style: "",
          world_description: "",
          character_description: "",
          narration_mode: "third_limited",
          pov_strategy: "first_player",
        },
      }
    : taskNumber === 2
      ? {
          ...common,
          locations: [],
          routes: [],
          factions: [],
          weather: [],
          weather_transitions: [],
          initial_weather_key: "",
        }
      : taskNumber === 3
        ? { ...common, locations: [], routes: [] }
        : taskNumber === 4
          ? { ...common, lore_systems: [], stats: [], abilities: [], items: [] }
          : taskNumber === 5
            ? {
                ...common,
                characters: [],
                factions: [],
                facts: [],
                default_pov_character_key: "",
              }
            : taskNumber === 6
              ? {
                  ...common,
                  character_updates: [],
                  outfits: [],
                  relationships: [],
                  routines: [],
                  facts: [],
                  plot_beats: [],
                }
              : taskNumber === 7
                ? {
                    ...common,
                    minigames: [],
                    bullethell: { mode_ids: [], skill_ids: [], attack_ids: [] },
                    ambient: [],
                    music: {
                      mode: "disabled",
                      enabled_theme_ids: [],
                      manual_theme_id: null,
                    },
                    recommendations: [],
                  }
                : { ...common, assets: [] };
}
