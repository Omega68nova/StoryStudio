import { useState } from "react";
import { Paper, Tab, Tabs } from "@mui/material";
import { BulletHellStudio } from "./BulletHellStudio";
import { CharacterStudio } from "./CharacterStudio";
import { EnvironmentStudio } from "./EnvironmentStudio";
import { LocationMapStudio } from "./LocationMapStudio";
import { MinigamesStudio } from "./minigames/MinigamesStudio";
import { MusicStudio } from "./MusicStudio";
import { PlanningStudio } from "./PlanningStudio";
import { RulesStudio } from "./RulesStudio";
import { WorldStudio } from "./WorldStudio";
import { WorkflowStudio } from "./WorkflowStudio";
import type { WorkflowPreset } from "./types";

export type WorldConfigurationSection =
  | "world"
  | "characters"
  | "environment"
  | "locations"
  | "rules"
  | "generation"
  | "minigames"
  | "bullethell"
  | "music"
  | "workflows";

const sections: Array<{ id: WorldConfigurationSection; label: string }> = [
  { id: "world", label: "World" },
  { id: "characters", label: "Characters" },
  { id: "environment", label: "Environment settings" },
  { id: "locations", label: "Environment & Map" },
  { id: "rules", label: "Rules" },
  { id: "generation", label: "Generation plan" },
  { id: "minigames", label: "Minigames" },
  { id: "bullethell", label: "Bullet Hell" },
  { id: "music", label: "Music" },
  { id: "workflows", label: "Workflows" },
];

export function WorldConfigurationStudio({
  projectId,
  revision,
  workflows,
  fail,
  reloadWorkflows,
}: {
  projectId: string;
  revision: number;
  workflows: WorkflowPreset[];
  fail: (message: string) => void;
  reloadWorkflows: () => Promise<void>;
}) {
  const [section, setSection] = useState<WorldConfigurationSection>("world");
  const [environmentLocationId, setEnvironmentLocationId] = useState<string | null>(null);

  function openSection(next: WorldConfigurationSection): boolean {
    if (next === section) return true;
    if (
      document.body.dataset.storyStudioUnsaved === "true" &&
      !window.confirm("Discard unsaved changes and open another configuration section?")
    ) return false;
    setSection(next);
    return true;
  }

  function openEnvironmentLocation(locationId: string) {
    if (openSection("environment")) setEnvironmentLocationId(locationId);
  }

  return (
    <div className="world-configuration">
      <Paper className="world-configuration-nav" square elevation={0}>
        <Tabs
          value={section}
          onChange={(_event, value: WorldConfigurationSection) => openSection(value)}
          variant="scrollable"
          scrollButtons="auto"
          aria-label="World configuration sections"
        >
          {sections.map((item) => <Tab key={item.id} value={item.id} label={item.label} />)}
        </Tabs>
      </Paper>
      <div className="world-configuration-content">
        {section === "world" && (
          <WorldStudio
            projectId={projectId}
            revision={revision}
            workflows={workflows}
            fail={fail}
            openEnvironmentLocation={openEnvironmentLocation}
          />
        )}
        {section === "characters" && (
          <CharacterStudio projectId={projectId} revision={revision} workflows={workflows} fail={fail} />
        )}
        {section === "environment" && (
          <EnvironmentStudio
            projectId={projectId}
            revision={revision}
            workflows={workflows}
            fail={fail}
            focusLocationId={environmentLocationId}
            onFocusHandled={() => setEnvironmentLocationId(null)}
          />
        )}
        {section === "locations" && <LocationMapStudio projectId={projectId} revision={revision} fail={fail} />}
        {section === "rules" && <RulesStudio projectId={projectId} revision={revision} fail={fail} />}
        {section === "generation" && <PlanningStudio projectId={projectId} revision={revision} fail={fail} />}
        {section === "minigames" && <MinigamesStudio projectId={projectId} revision={revision} fail={fail} />}
        {section === "bullethell" && <BulletHellStudio projectId={projectId} revision={revision} fail={fail} />}
        {section === "music" && <MusicStudio projectId={projectId} revision={revision} fail={fail} />}
        {section === "workflows" && (
          <WorkflowStudio workflows={workflows} reload={reloadWorkflows} fail={fail} />
        )}
      </div>
    </div>
  );
}
