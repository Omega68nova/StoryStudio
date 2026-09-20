import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  LinearProgress,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import AutoFixHighIcon from "@mui/icons-material/AutoFixHigh";
import CasinoOutlinedIcon from "@mui/icons-material/CasinoOutlined";
import { api } from "./api";
import { BoxedMultiselectFilter, CreatableBoxedMultiselect } from "./customComponents/BoxedMultiselect";
import type {
  AmbientVariant,
  EnvironmentSettings,
  MusicTheme,
  PlanningAssetPlan,
  PlanningConflict,
  PlanningDependencyImpact,
  PlanningResolution,
  PlanningScalePreset,
  PlanningSession,
  PlanningStage,
  WorkflowPreset,
  WorldProjection,
} from "./types";

type Catalogs = {
  world: WorldProjection | null;
  environment: EnvironmentSettings | null;
  ambient: AmbientVariant[];
  minigames: any[];
  music: MusicTheme[];
  workflows: WorkflowPreset[];
  rules: { stats: any[]; abilities: any[] };
  bullet: { modes: any[]; skills: any[]; attacks: any[] };
};
const blankCatalogs: Catalogs = {
  world: null,
  environment: null,
  ambient: [],
  minigames: [],
  music: [],
  workflows: [],
  rules: { stats: [], abilities: [] },
  bullet: { modes: [], skills: [], attacks: [] },
};
const PRESETS: Record<
  PlanningScalePreset,
  {
    major_locations: number;
    minor_locations: number;
    rooms: number;
    characters: number;
  }
> = {
  intimate: { major_locations: 3, minor_locations: 8, rooms: 8, characters: 6 },
  local: { major_locations: 6, minor_locations: 20, rooms: 16, characters: 10 },
  regional: {
    major_locations: 12,
    minor_locations: 40,
    rooms: 24,
    characters: 18,
  },
  global: {
    major_locations: 24,
    minor_locations: 80,
    rooms: 40,
    characters: 30,
  },
};
const STAGE_NAMES = [
  "Foundation",
  "Macro world & weather",
  "Detailed locations",
  "Rules, stats & abilities",
  "Cast",
  "Character details & hooks",
  "Runtime presentation",
  "Images",
];
const STAGE_SECTIONS: Record<number, string[]> = {
  2: ["locations", "weather", "factions", "routes"],
  3: ["locations", "routes"],
  4: ["stats", "abilities", "lore_systems", "items"],
  5: ["characters", "factions", "facts"],
  6: ["character_updates", "outfits", "relationships", "routines", "facts", "plot_beats"],
  7: ["minigames", "bullethell", "ambient", "music"],
};
const STAGE_SECTION_FIELDS: Record<number, Record<string, string[]>> = {
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

export function PlanningStudio({
  projectId,
  revision,
  fail,
}: {
  projectId: string;
  revision: number;
  fail: (message: string) => void;
}) {
  const [session, setSession] = useState<PlanningSession | null>(null);
  const [setup, setSetup] = useState({
    scale_preset: "local" as PlanningScalePreset,
    ...PRESETS.local,
    direction: "",
  });
  const [randomizingDirection, setRandomizingDirection] = useState(false);
  const [randomTheme, setRandomTheme] = useState("");
  const [catalogs, setCatalogs] = useState<Catalogs>(blankCatalogs);
  const [prompts, setPrompts] = useState<Record<number, string>>({});
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [generationSections, setGenerationSections] = useState<Record<number, string>>({});
  const [conflicts, setConflicts] = useState<PlanningConflict[]>([]);
  const [resolutions, setResolutions] = useState<Record<string, PlanningResolution>>({});
  const [approvalStage, setApprovalStage] = useState<number | null>(null);
  const [impact, setImpact] = useState<PlanningDependencyImpact | null>(null);
  const [reopenStage, setReopenStage] = useState<number | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [automationOpen, setAutomationOpen] = useState(false);
  const [automationPrompt, setAutomationPrompt] = useState("");
  const [selectedImages, setSelectedImages] = useState<string[]>([]);
  const dirtyDrafts = useRef(new Set<number>());
  const dirtyPrompts = useRef(new Set<number>());

  const load = useCallback(async () => {
    const current = await api<PlanningSession | null>(`/projects/${projectId}/planning`);
    setSession(current);
    if (!current) return;
    setPrompts((existing) =>
      Object.fromEntries(
        current.stages.map((stage) => [
          stage.stage_number,
          dirtyPrompts.current.has(stage.stage_number)
            ? (existing[stage.stage_number] ?? "")
            : (stage.human_prompt ?? ""),
        ]),
      ),
    );
    setDrafts((existing) =>
      Object.fromEntries(
        current.stages.map((stage) => [
          stage.stage_number,
          dirtyDrafts.current.has(stage.stage_number)
            ? (existing[stage.stage_number] ?? "{}")
            : (stage.raw_draft_text ??
              JSON.stringify(stage.draft ?? stage.approved ?? emptyStage(stage.stage_number), null, 2)),
        ]),
      ),
    );
  }, [projectId]);
  const loadCatalogs = useCallback(async () => {
    const [world, environment, ambient, minigames, music, workflows, rules, bullet] = await Promise.all([
      api<WorldProjection>(`/projects/${projectId}/world`),
      api<EnvironmentSettings>(`/projects/${projectId}/environment/settings`),
      api<{ variants: AmbientVariant[] }>(`/projects/${projectId}/environment/ambient`),
      api<any[]>(`/projects/${projectId}/minigames`),
      api<MusicTheme[]>("/music/themes"),
      api<WorkflowPreset[]>("/workflows"),
      api<{ stats: any[]; abilities: any[] }>(`/projects/${projectId}/rules`),
      api<{ modes: any[]; skills: any[]; attacks: any[] }>("/bullethell/catalog"),
    ]);
    setCatalogs({
      world,
      environment,
      ambient: ambient.variants,
      minigames,
      music,
      workflows,
      rules,
      bullet,
    });
  }, [projectId]);
  useEffect(() => {
    void Promise.all([load(), loadCatalogs()]).catch((cause) => fail(message(cause)));
  }, [load, loadCatalogs, revision, fail]);
  useEffect(() => {
    dirtyDrafts.current.clear();
    dirtyPrompts.current.clear();
    document.body.dataset.storyStudioUnsaved = "false";
    return () => {
      document.body.dataset.storyStudioUnsaved = "false";
    };
  }, [projectId]);
  useEffect(() => {
    if (!session?.stages.some((stage) => ["queued", "generating"].includes(stage.status))) return;
    const timer = window.setInterval(() => void load(), 750);
    return () => clearInterval(timer);
  }, [session, load]);

  function markDraft(stage: number, value: string) {
    dirtyDrafts.current.add(stage);
    document.body.dataset.storyStudioUnsaved = "true";
    setDrafts((current) => ({ ...current, [stage]: value }));
  }
  function clearDirty(stage: number) {
    dirtyDrafts.current.delete(stage);
    dirtyPrompts.current.delete(stage);
    if (!dirtyDrafts.current.size && !dirtyPrompts.current.size) document.body.dataset.storyStudioUnsaved = "false";
  }
  async function create() {
    try {
      setSession(
        await api(`/projects/${projectId}/planning`, {
          method: "POST",
          body: JSON.stringify(setup),
        }),
      );
    } catch (cause) {
      fail(message(cause));
    }
  }
  async function randomizeDirection() {
    setRandomizingDirection(true);
    try {
      const created = await api<{ id: string }>(`/projects/${projectId}/planning/random-direction`, {
        method: "POST",
        body: JSON.stringify({ theme: randomTheme.trim() }),
      });
      for (let attempt = 0; attempt < 240; attempt += 1) {
        await delay(500);
        const job = await api<{
          status: string;
          result?: { direction?: string };
          error?: string;
        }>(`/jobs/${created.id}`);
        if (job.status === "completed") {
          const direction = job.result?.direction?.trim();
          if (!direction) throw new Error("The storyteller returned an empty creative direction.");
          setSetup((current) => ({ ...current, direction }));
          return;
        }
        if (["failed", "cancelled", "interrupted"].includes(job.status))
          throw new Error(job.error || "Random direction generation failed.");
      }
      throw new Error("Random direction generation is still running. Check Operations before trying again.");
    } catch (cause) {
      fail(message(cause));
    } finally {
      setRandomizingDirection(false);
    }
  }
  async function generate(stage: number, repair = false, automate = false, shared = "") {
    try {
      clearDirty(stage);
      await api(`/planning/${session!.id}/stages/${stage}/generate`, {
        method: "POST",
        body: JSON.stringify({
          prompt: shared || prompts[stage] || "",
          repair,
          automate,
          automation_prompt: shared,
        }),
      });
      await load();
    } catch (cause) {
      fail(message(cause));
    }
  }
  async function saveStageDraft(stage: number, draft: any) {
    await api(`/planning/${session!.id}/stages/${stage}`, { method: "PUT", body: JSON.stringify({ draft }) });
    clearDirty(stage);
    setDrafts((current) => ({ ...current, [stage]: JSON.stringify(draft, null, 2) }));
  }
  async function requestSection(stage: number, focus: string) {
    await api(`/planning/${session!.id}/stages/${stage}/generate`, {
      method: "POST",
      body: JSON.stringify({ prompt: prompts[stage] || "", append: true, focus }),
    });
    await load();
  }
  async function acceptCurrentSet(stage: number, generateAfter: boolean) {
    const focus = generationSections[stage] || STAGE_SECTIONS[stage]?.[0];
    if (!focus) return;
    try {
      const draft = JSON.parse(drafts[stage] || "{}");
      await api(`/planning/${session!.id}/stages/${stage}/accept-batch`, {
        method: "POST",
        body: JSON.stringify({ draft, focus }),
      });
      clearDirty(stage);
      if (generateAfter) await requestSection(stage, focus);
      else await Promise.all([load(), loadCatalogs()]);
    } catch (cause) {
      fail(message(cause));
    }
  }
  async function regenerateSection(stage: number) {
    const focus = generationSections[stage] || STAGE_SECTIONS[stage]?.[0];
    if (!focus) return;
    try {
      const draft = clearCurrentSection(stage, focus, JSON.parse(drafts[stage] || "{}"));
      await saveStageDraft(stage, draft);
      await requestSection(stage, focus);
    } catch (cause) {
      fail(message(cause));
    }
  }
  async function saveOrApprove(
    stage: number,
    approve: boolean,
    suppliedResolutions?: Record<string, PlanningResolution>,
  ) {
    try {
      const draft = JSON.parse(drafts[stage] || "{}");
      if (approve && !suppliedResolutions) {
        const result = await api<{ conflicts: PlanningConflict[] }>(
          `/planning/${session!.id}/stages/${stage}/preflight`,
          { method: "POST", body: JSON.stringify({ draft }) },
        );
        if (result.conflicts.length) {
          setConflicts(result.conflicts);
          setApprovalStage(stage);
          setResolutions(
            Object.fromEntries(
              result.conflicts
                .filter((item) => item.recommended_resolution)
                .map((item) => [item.entity_key, item.recommended_resolution!] as const),
            ),
          );
          return;
        }
      }
      await api(`/planning/${session!.id}/stages/${stage}${approve ? "/approve" : ""}`, {
        method: approve ? "POST" : "PUT",
        body: JSON.stringify({
          draft,
          resolutions: suppliedResolutions ?? {},
        }),
      });
      clearDirty(stage);
      setApprovalStage(null);
      setConflicts([]);
      await Promise.all([load(), loadCatalogs()]);
    } catch (cause) {
      fail(message(cause));
    }
  }
  async function skip(stage: number) {
    if (!window.confirm(`Skip ${STAGE_NAMES[stage - 1]}? You can reopen it later.`)) return;
    try {
      await api(`/planning/${session!.id}/stages/${stage}/skip`, {
        method: "POST",
      });
      clearDirty(stage);
      await load();
    } catch (cause) {
      fail(message(cause));
    }
  }
  async function inspectReopen(stage: number) {
    try {
      setImpact(await api(`/planning/${session!.id}/stages/${stage}/dependency-impact`));
      setReopenStage(stage);
    } catch (cause) {
      fail(message(cause));
    }
  }
  async function reopen() {
    if (!reopenStage) return;
    try {
      await api(`/planning/${session!.id}/stages/${reopenStage}/reopen`, {
        method: "POST",
      });
      setImpact(null);
      setReopenStage(null);
      await load();
    } catch (cause) {
      fail(message(cause));
    }
  }
  async function revalidate(stage: number) {
    try {
      await api(`/planning/${session!.id}/stages/${stage}/revalidate`, {
        method: "POST",
      });
      await load();
    } catch (cause) {
      fail(message(cause));
    }
  }
  async function updateImage(plan: PlanningAssetPlan, patch: Partial<PlanningAssetPlan>) {
    try {
      await api(`/planning/image-plans/${plan.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          prompt: plan.prompt,
          negative_prompt: plan.negative_prompt,
          workflow_preset_id: plan.workflow_preset_id,
          width: plan.width,
          height: plan.height,
          ...patch,
        }),
      });
      await load();
    } catch (cause) {
      fail(message(cause));
    }
  }
  async function generateImages(ids: string[]) {
    try {
      await api(`/planning/${session!.id}/images/generate`, {
        method: "POST",
        body: JSON.stringify({ plan_ids: ids }),
      });
      setSelectedImages([]);
      await load();
    } catch (cause) {
      fail(message(cause));
    }
  }
  async function deleteSession() {
    try {
      await api(`/planning/${session!.id}`, {
        method: "DELETE",
        body: JSON.stringify({
          mode: "keep_world",
          confirmation: deleteConfirmation,
        }),
      });
      setDeleteOpen(false);
      setSession(null);
    } catch (cause) {
      fail(message(cause));
    }
  }

  if (!session)
    return (
      <div className="page">
        <header className="page-header">
          <p className="eyebrow">WORLD WORKSHOP</p>
          <h1>Preplan the story</h1>
          <p>Build the story foundation through eight editable, skippable stages.</p>
        </header>
        <section className="panel setup-grid">
          <TextField
            select
            label="Story scale"
            value={setup.scale_preset}
            onChange={(event) => {
              const scale = event.target.value as PlanningScalePreset;
              setSetup({ ...setup, scale_preset: scale, ...PRESETS[scale] });
            }}
          >
            {Object.keys(PRESETS).map((value) => (
              <MenuItem key={value} value={value}>
                {humanize(value)}
              </MenuItem>
            ))}
          </TextField>
          {(["major_locations", "minor_locations", "rooms", "characters"] as const).map((key) => (
            <TextField
              key={key}
              type="number"
              label={humanize(key)}
              value={setup[key]}
              onChange={(event) => setSetup({ ...setup, [key]: Number(event.target.value) })}
            />
          ))}
          <TextField
            className="wide"
            multiline
            minRows={8}
            label="Creative direction"
            value={setup.direction}
            onChange={(event) => setSetup({ ...setup, direction: event.target.value })}
            helperText="Describe your story, or generate a random direction and edit it before starting."
          />
          <Stack
            className="wide"
            direction={{ xs: "column", sm: "row" }}
            spacing={1}
            alignItems={{ xs: "stretch", sm: "center" }}
          >
            <TextField
              size="small"
              label="Theme seed (optional)"
              placeholder="Medieval fantasy, isekai…"
              value={randomTheme}
              onChange={(event) => setRandomTheme(event.target.value)}
              inputProps={{ maxLength: 200 }}
            />
            <Button
              variant="outlined"
              startIcon={<CasinoOutlinedIcon />}
              disabled={randomizingDirection}
              onClick={() => void randomizeDirection()}
            >
              {randomizingDirection ? "Inventing a story…" : "Generate a random direction"}
            </Button>
            <Typography variant="caption" color="text.secondary">
              Uses higher creativity for this request only.
            </Typography>
          </Stack>
          <Button variant="contained" disabled={randomizingDirection} onClick={() => void create()}>
            Start eight-stage workshop
          </Button>
        </section>
      </div>
    );

  return (
    <div className="page planning-page">
      <header className="page-header">
        <p className="eyebrow">WORLD WORKSHOP V2</p>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <div>
            <h1>Preplanning</h1>
            <p>
              {session.status === "completed"
                ? "Every stage is current and canonical."
                : `Stage ${session.current_stage} of 8 · ${humanize(session.settings.scale_preset)} scale`}
            </p>
          </div>
          <Stack direction="row">
            <Tooltip title="Automatically prepare remaining language-model stages">
              <span>
                <IconButton
                  disabled={
                    session.status === "completed" ||
                    session.stages.some((stage) => ["queued", "generating"].includes(stage.status))
                  }
                  onClick={() => {
                    setAutomationPrompt(session.settings.direction);
                    setAutomationOpen(true);
                  }}
                >
                  <PlayArrowIcon />
                </IconButton>
              </span>
            </Tooltip>
            <Button color="error" onClick={() => setDeleteOpen(true)}>
              Delete workshop
            </Button>
          </Stack>
        </Stack>
      </header>
      <div className="planning-step-strip">
        {session.stages.map((stage) => (
          <button
            key={stage.id}
            className={stage.status}
            onClick={() =>
              document.getElementById(`planning-stage-${stage.stage_number}`)?.scrollIntoView({ behavior: "smooth" })
            }
          >
            <b>{stage.stage_number}</b>
            <span>{STAGE_NAMES[stage.stage_number - 1]}</span>
            <small>{stage.status}</small>
          </button>
        ))}
      </div>
      <div className="stage-list">
        {session.stages.map((stage) => {
          const locked =
            stage.stage_number > session.current_stage && !["approved", "skipped", "stale"].includes(stage.status);
          const generating = ["queued", "generating"].includes(stage.status);
          const operation = stage.operation;
          const measurable = Number(operation?.progress_total ?? 0) > 0;
          return (
            <section
              id={`planning-stage-${stage.stage_number}`}
              className={`panel planning-stage ${stage.status}`}
              key={stage.id}
            >
              <header>
                <div>
                  <span>{stage.stage_number}</span>
                  <h2>{STAGE_NAMES[stage.stage_number - 1]}</h2>
                </div>
                <Chip
                  label={stage.status}
                  color={stage.status === "stale" ? "warning" : stage.status === "approved" ? "success" : "default"}
                />
              </header>
              {stage.status === "stale" && (
                <Alert
                  severity="warning"
                  action={<Button onClick={() => void revalidate(stage.stage_number)}>Revalidate</Button>}
                >
                  An approved dependency changed. Canonical data remains active until this stage is redone.
                </Alert>
              )}
              {!locked && !["approved", "skipped", "stale"].includes(stage.status) && (
                <>
                  <TextField
                    fullWidth
                    multiline
                    minRows={2}
                    label="Human direction (optional)"
                    value={prompts[stage.stage_number] ?? ""}
                    disabled={generating || stage.stage_number === 8}
                    onChange={(event) => {
                      dirtyPrompts.current.add(stage.stage_number);
                      document.body.dataset.storyStudioUnsaved = "true";
                      setPrompts({
                        ...prompts,
                        [stage.stage_number]: event.target.value,
                      });
                    }}
                  />
                  {stage.validation_error && (
                    <Alert
                      severity="warning"
                      action={
                        <Button startIcon={<AutoFixHighIcon />} onClick={() => void generate(stage.stage_number, true)}>
                          Ask AI to repair
                        </Button>
                      }
                    >
                      {stage.validation_error}
                    </Alert>
                  )}
                  <div className="button-row">
                    {generating && stage.active_job_id && (
                      <Button
                        color="error"
                        onClick={() =>
                          void api(`/jobs/${stage.active_job_id}/cancel`, {
                            method: "POST",
                          }).then(load)
                        }
                      >
                        Cancel
                      </Button>
                    )}
                    <Button
                      variant="outlined"
                      disabled={generating}
                      onClick={() =>
                        void (STAGE_SECTIONS[stage.stage_number]
                          ? regenerateSection(stage.stage_number)
                          : generate(stage.stage_number))
                      }
                    >
                      {stage.stage_number === 8
                        ? "Prepare deterministic prompts"
                        : generating
                          ? "AI is working…"
                          : STAGE_SECTIONS[stage.stage_number]
                            ? "Regenerate selected section"
                            : stage.draft
                              ? "Regenerate draft"
                              : "Generate draft"}
                    </Button>
                    {STAGE_SECTIONS[stage.stage_number] && (
                      <>
                        <TextField
                          select
                          size="small"
                          label={stage.stage_number === 4 ? "Stage 4 layer" : "Generate section"}
                          value={generationSections[stage.stage_number] || STAGE_SECTIONS[stage.stage_number][0]}
                          disabled={generating}
                          onChange={(event) =>
                            setGenerationSections({
                              ...generationSections,
                              [stage.stage_number]: event.target.value,
                            })
                          }
                        >
                          {STAGE_SECTIONS[stage.stage_number].map((section) => (
                            <MenuItem key={section} value={section}>
                              {stage.stage_number === 4 && section === "stats"
                                ? "1. Stats"
                                : stage.stage_number === 4 && section === "abilities"
                                  ? "2. Abilities (after saving stats)"
                                  : humanize(section)}
                            </MenuItem>
                          ))}
                        </TextField>
                        <Button variant="outlined" disabled={generating} onClick={() => void acceptCurrentSet(stage.stage_number, false)}>
                          {stage.stage_number === 4 ? "Save selected layer" : "Separate & save current"}
                        </Button>
                        <Button variant="outlined" disabled={generating} onClick={() => void acceptCurrentSet(stage.stage_number, true)}>
                          {stage.stage_number === 4 ? "Save layer & generate more" : "Accept & generate more"}
                        </Button>
                      </>
                    )}
                    <Button disabled={generating} onClick={() => void skip(stage.stage_number)}>
                      Skip stage
                    </Button>
                  </div>
                  {generating && (
                    <Box role="status">
                      <Typography variant="caption">{operation?.progress_message || "Preparing stage"}</Typography>
                      <LinearProgress
                        variant={measurable ? "determinate" : "indeterminate"}
                        value={
                          measurable
                            ? Math.min(
                                100,
                                (Number(operation!.progress_current) / Number(operation!.progress_total)) * 100,
                              )
                            : 0
                        }
                      />
                    </Box>
                  )}
                  <StageEditor
                    stage={stage}
                    value={drafts[stage.stage_number] ?? "{}"}
                    disabled={generating}
                    catalogs={catalogs}
                    imagePlans={session.image_plans}
                    selectedImages={selectedImages}
                    setSelectedImages={setSelectedImages}
                    updateImage={updateImage}
                    generateImages={generateImages}
                    onChange={(value) => markDraft(stage.stage_number, value)}
                  />
                  <div className="button-row">
                    <Button onClick={() => void saveOrApprove(stage.stage_number, false)}>Save draft</Button>
                    <Button variant="contained" onClick={() => void saveOrApprove(stage.stage_number, true)}>
                      Approve stage
                    </Button>
                  </div>
                </>
              )}
              {["approved", "skipped", "stale"].includes(stage.status) && (
                <>
                  <p className="approved-summary">
                    {String(
                      stage.approved?.summary ||
                        (stage.status === "skipped" ? "Intentionally skipped." : "Approved stage"),
                    )}
                  </p>
                  <Button onClick={() => void inspectReopen(stage.stage_number)}>Redo stage</Button>
                </>
              )}
              {locked && <p className="muted">Approve or skip the previous stage to unlock this one.</p>}
            </section>
          );
        })}
      </div>
      <Dialog open={reopenStage !== null} onClose={() => setReopenStage(null)}>
        <DialogTitle>Redo stage {reopenStage}?</DialogTitle>
        <DialogContent>
          <p>The current canonical data stays active while you edit.</p>
          {impact?.affected_stages.length ? (
            <Alert severity="warning">
              If published data changes, these stages may become stale:{" "}
              {impact.affected_stages.map((item) => STAGE_NAMES[item.stage_number - 1]).join(", ")}.
            </Alert>
          ) : (
            <Alert severity="info">No later approved stage currently depends on this stage.</Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setReopenStage(null)}>Cancel</Button>
          <Button variant="contained" onClick={() => void reopen()}>
            Open replacement draft
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={approvalStage !== null} onClose={() => setApprovalStage(null)} maxWidth="md" fullWidth>
        <DialogTitle>Resolve canonical conflicts</DialogTitle>
        <DialogContent>
          {conflicts.map((conflict) => {
            const manual = conflict.proposed._planning_conflict === "manual_change";
            const actions = manual ? ["keep_manual", "overwrite", "unlink"] : ["link", "merge", "rename", "omit"];
            return (
              <Card key={conflict.entity_key} variant="outlined" sx={{ my: 1 }}>
                <CardContent>
                  <b>{String(conflict.proposed.name)}</b>
                  {manual && (
                    <Alert severity="warning">This planning-owned record was edited outside the workshop.</Alert>
                  )}
                  <TextField
                    select
                    fullWidth
                    label="Resolution"
                    value={resolutions[conflict.entity_key]?.action ?? ""}
                    onChange={(event) => {
                      const action = event.target.value as PlanningResolution["action"];
                      setResolutions({
                        ...resolutions,
                        [conflict.entity_key]: {
                          action,
                          ...(["link", "merge"].includes(action) ? { entity_id: conflict.candidates[0]?.id } : {}),
                        },
                      });
                    }}
                  >
                    {actions.map((action) => (
                      <MenuItem key={action} value={action}>
                        {humanize(action)}
                      </MenuItem>
                    ))}
                  </TextField>
                  {resolutions[conflict.entity_key]?.action === "rename" && (
                    <TextField
                      fullWidth
                      label="New name"
                      value={resolutions[conflict.entity_key]?.new_name ?? ""}
                      onChange={(event) =>
                        setResolutions({
                          ...resolutions,
                          [conflict.entity_key]: {
                            ...resolutions[conflict.entity_key],
                            new_name: event.target.value,
                          },
                        })
                      }
                    />
                  )}
                </CardContent>
              </Card>
            );
          })}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setApprovalStage(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => approvalStage && void saveOrApprove(approvalStage, true, resolutions)}
          >
            Approve resolutions
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={automationOpen} onClose={() => setAutomationOpen(false)}>
        <DialogTitle>Automate remaining stages</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            multiline
            minRows={5}
            label="Shared direction"
            value={automationPrompt}
            onChange={(event) => setAutomationPrompt(event.target.value)}
            helperText="Automation stops for malformed drafts or conflicts and prepares, but never generates, stage-8 images."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAutomationOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => {
              setAutomationOpen(false);
              void generate(session.current_stage, false, true, automationPrompt);
            }}
          >
            Start
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)}>
        <DialogTitle>Delete workshop?</DialogTitle>
        <DialogContent>
          <Alert severity="info">Approved canonical data is preserved.</Alert>
          <TextField
            fullWidth
            label="Type DELETE PLANNING"
            value={deleteConfirmation}
            onChange={(event) => setDeleteConfirmation(event.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteOpen(false)}>Cancel</Button>
          <Button
            color="error"
            disabled={deleteConfirmation !== "DELETE PLANNING"}
            onClick={() => void deleteSession()}
          >
            Delete workshop
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}

function StageEditor({
  stage,
  value,
  disabled,
  catalogs,
  imagePlans,
  selectedImages,
  setSelectedImages,
  updateImage,
  generateImages,
  onChange,
}: {
  stage: PlanningStage;
  value: string;
  disabled: boolean;
  catalogs: Catalogs;
  imagePlans: PlanningAssetPlan[];
  selectedImages: string[];
  setSelectedImages: (ids: string[]) => void;
  updateImage: (plan: PlanningAssetPlan, patch: Partial<PlanningAssetPlan>) => Promise<void>;
  generateImages: (ids: string[]) => Promise<void>;
  onChange: (value: string) => void;
}) {
  let draft: any;
  try {
    draft = JSON.parse(value || "{}");
  } catch {
    return (
      <TextField
        fullWidth
        multiline
        minRows={12}
        error
        label="Invalid stage JSON"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  const update = (next: any) => onChange(JSON.stringify(next, null, 2));
  const set = (key: string, next: unknown) => update({ ...draft, [key]: next });
  return (
    <div className="planning-structured">
      <TextField
        fullWidth
        multiline
        minRows={2}
        label="Stage summary"
        disabled={disabled}
        value={draft.summary ?? ""}
        onChange={(event) => set("summary", event.target.value)}
      />
      <CreatableBoxedMultiselect
        label="Notes"
        options={strings(draft.notes)}
        value={strings(draft.notes)}
        onChange={(_event, next) => set("notes", next)}
      />
      {stage.stage_number === 1 && (
        <FoundationEditor value={draft.foundation ?? {}} onChange={(foundation) => set("foundation", foundation)} />
      )}
      {stage.stage_number === 2 && (
        <>
          <MapPreview locations={array(draft.locations)} routes={array(draft.routes)} />
          <ResourceListEditor
            title="Major locations"
            kind="location"
            items={array(draft.locations)}
            onChange={(items) => set("locations", items)}
          />
          <ResourceListEditor
            title="Broad factions"
            kind="faction"
            items={array(draft.factions)}
            onChange={(items) => set("factions", items)}
          />
          <WeatherEditor draft={draft} update={update} />
          <JsonCollection
            title="Routes"
            items={array(draft.routes)}
            onChange={(items) => set("routes", items)}
            template={{
              key: "route_key",
              source_key: "",
              target_key: "",
              relation: "route",
              travel_minutes: 30,
              modes: ["walk"],
              bidirectional: true,
            }}
          />
        </>
      )}
      {stage.stage_number === 3 && (
        <>
          <MapPreview locations={array(draft.locations)} routes={array(draft.routes)} />
          <ResourceListEditor
            title="Minor locations and rooms"
            kind="location"
            items={array(draft.locations)}
            onChange={(items) => set("locations", items)}
          />
          <JsonCollection
            title="Routes"
            items={array(draft.routes)}
            onChange={(items) => set("routes", items)}
            template={{
              key: "route_key",
              source_key: "",
              target_key: "",
              relation: "route",
              travel_minutes: 10,
              modes: ["walk"],
              bidirectional: true,
            }}
          />
        </>
      )}
      {stage.stage_number === 4 && (
        <>
          <ResourceListEditor
            title="Lore systems"
            kind="lore_system"
            items={array(draft.lore_systems)}
            onChange={(items) => set("lore_systems", items)}
            descriptionLabel="System description"
          />
          <ResourceListEditor
            title="Important items"
            kind="item"
            items={array(draft.items)}
            onChange={(items) => set("items", items)}
          />
          <JsonCollection
            title="Stat definitions"
            items={array(draft.stats)}
            onChange={(items) => set("stats", items)}
            template={{
              key: "hp",
              stat_key: "hp",
              label: "Health",
              scope: "character",
              default_value: 100,
              minimum: 0,
              maximum: 100,
              integer_only: true,
              visibility: "public",
            }}
          />
          <JsonCollection
            title="Ability definitions"
            items={array(draft.abilities)}
            onChange={(items) => set("abilities", items)}
            template={{
              key: "ability",
              ability_key: "ability",
              name: "Ability",
              target_type: "self",
              requirements: {},
              costs: {},
              effects: [],
              minigame_profile: {},
            }}
          />
        </>
      )}
      {stage.stage_number === 5 && (
        <>
          <ResourceListEditor
            title="Characters"
            kind="character"
            items={array(draft.characters)}
            onChange={(items) => set("characters", items)}
            castRole
          />
          <ResourceListEditor
            title="Factions"
            kind="faction"
            items={array(draft.factions)}
            onChange={(items) => set("factions", items)}
          />
          <ResourceListEditor
            title="Facts and secrets"
            kind="fact"
            items={array(draft.facts)}
            onChange={(items) => set("facts", items)}
          />
          <TextField
            label="Default POV character key"
            value={draft.default_pov_character_key ?? ""}
            onChange={(event) => set("default_pov_character_key", event.target.value)}
          />
        </>
      )}
      {stage.stage_number === 6 && (
        <>
          <JsonCollection
            title="Character updates"
            items={array(draft.character_updates)}
            onChange={(items) => set("character_updates", items)}
            template={{
              key: "character_key",
              name: "Character",
              state: { appearance: "", personality: "", abilities: [] },
            }}
          />
          <JsonCollection
            title="Outfits"
            items={array(draft.outfits)}
            onChange={(items) => set("outfits", items)}
            template={{
              key: "outfit_key",
              character_key: "",
              name: "Outfit",
              description: "",
              equipment: [],
            }}
          />
          <JsonCollection
            title="Relationships"
            items={array(draft.relationships)}
            onChange={(items) => set("relationships", items)}
            template={{
              key: "relationship_key",
              source_key: "",
              target_key: "",
              relation: "friend",
              bidirectional: true,
            }}
          />
          <JsonCollection
            title="Routines"
            items={array(draft.routines)}
            onChange={(items) => set("routines", items)}
            template={{
              key: "routine_key",
              character_key: "",
              location_key: "",
              time_phase_id: null,
              notes: "",
            }}
          />
          <ResourceListEditor
            title="Facts and secrets"
            kind="fact"
            items={array(draft.facts)}
            onChange={(items) => set("facts", items)}
          />
          <ResourceListEditor
            title="Flexible plot beats"
            kind="plot_beat"
            items={array(draft.plot_beats)}
            onChange={(items) => set("plot_beats", items)}
          />
        </>
      )}
      {stage.stage_number === 7 && <RuntimeEditor draft={draft} update={update} catalogs={catalogs} />}
      {stage.stage_number === 8 && (
        <ImagePlanEditor
          plans={imagePlans}
          workflows={catalogs.workflows}
          selected={selectedImages}
          setSelected={setSelectedImages}
          updatePlan={updateImage}
          generate={generateImages}
        />
      )}
      {stage.stage_number !== 8 && (
        <details>
          <summary>Advanced stage JSON</summary>
          <TextField
            fullWidth
            multiline
            minRows={14}
            value={value}
            onChange={(event) => onChange(event.target.value)}
          />
        </details>
      )}
    </div>
  );
}

function FoundationEditor({ value, onChange }: { value: any; onChange: (value: any) => void }) {
  const field = (key: string, next: unknown) => onChange({ ...value, [key]: next });
  return (
    <div className="planning-card-fields">
      <TextField
        multiline
        minRows={3}
        label="Premise"
        value={value.premise ?? ""}
        onChange={(event) => field("premise", event.target.value)}
      />
      <CreatableBoxedMultiselect
        label="Genres"
        options={strings(value.genres)}
        value={strings(value.genres)}
        onChange={(_event, next) => field("genres", next)}
      />
      <CreatableBoxedMultiselect
        label="Themes"
        options={strings(value.themes)}
        value={strings(value.themes)}
        onChange={(_event, next) => field("themes", next)}
      />
      <TextField label="Tone" value={value.tone ?? ""} onChange={(event) => field("tone", event.target.value)} />
      <TextField
        multiline
        label="Writing style"
        value={value.style ?? ""}
        onChange={(event) => field("style", event.target.value)}
      />
      <TextField
        multiline
        minRows={3}
        label="World overview"
        value={value.world_description ?? ""}
        onChange={(event) => field("world_description", event.target.value)}
      />
      <TextField
        multiline
        label="General cast direction"
        value={value.character_description ?? ""}
        onChange={(event) => field("character_description", event.target.value)}
      />
      <TextField
        select
        label="Narration mode"
        value={value.narration_mode ?? "third_limited"}
        onChange={(event) => field("narration_mode", event.target.value)}
      >
        {["first_person", "third_limited", "third_omniscient"].map((item) => (
          <MenuItem key={item} value={item}>
            {humanize(item)}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        select
        label="POV strategy"
        value={value.pov_strategy ?? "first_player"}
        onChange={(event) => field("pov_strategy", event.target.value)}
      >
        {["first_player", "selected_character", "none"].map((item) => (
          <MenuItem key={item} value={item}>
            {humanize(item)}
          </MenuItem>
        ))}
      </TextField>
    </div>
  );
}

function ResourceListEditor({
  title,
  kind,
  items,
  onChange,
  castRole = false,
  descriptionLabel,
}: {
  title: string;
  kind: string;
  items: any[];
  onChange: (items: any[]) => void;
  castRole?: boolean;
  descriptionLabel?: string;
}) {
  return (
    <section>
      <div className="sheet-heading">
        <h3>{title}</h3>
        <Button
          onClick={() =>
            onChange([
              ...items,
              {
                key: `${kind}_${items.length + 1}`,
                name: "",
                aliases: [],
                tags: [],
                state:
                  kind === "location"
                    ? {
                        description: "",
                        imagegen_description: "",
                        exposure: "outdoor",
                        planning_tier: "minor",
                        important: false,
                        enabled: true,
                        discovered: true,
                      }
                    : kind === "character"
                      ? {
                          description: "",
                          identity: "",
                          pronouns: "",
                          appearance: "",
                          personality: "",
                          goals: [],
                          secrets: "",
                          character_secrets: [],
                          secrets_to_character: [],
                          cast_role: "supporting",
                          player_controlled: false,
                          autonomy_enabled: false,
                          intervention_frequency: "normal",
                          current_location_key: null,
                        }
                      : kind === "lore_system"
                        ? { description: "", rules: [], limits: [], costs: [], secrets: [] }
                        : {},
              },
            ])
          }
        >
          Add
        </Button>
      </div>
      {items.map((item, index) => (
        <Card variant="outlined" key={`${item.key}-${index}`}>
          <CardContent className="planning-card-fields">
            <TextField
              label="Stable key"
              value={item.key ?? ""}
              onChange={(event) => replace(items, index, { ...item, key: event.target.value }, onChange)}
            />
            <TextField
              label="Name"
              value={item.name ?? ""}
              onChange={(event) => replace(items, index, { ...item, name: event.target.value }, onChange)}
            />
            <CreatableBoxedMultiselect
              label="Tags"
              options={strings(item.tags)}
              value={strings(item.tags)}
              onChange={(_event, next) => replace(items, index, { ...item, tags: next }, onChange)}
            />
            {descriptionLabel && (
              <TextField
                fullWidth
                multiline
                minRows={3}
                label={descriptionLabel}
                value={item.state?.description ?? ""}
                onChange={(event) =>
                  replace(items, index, { ...item, state: { ...item.state, description: event.target.value } }, onChange)
                }
              />
            )}
            {castRole && (
              <>
                <TextField
                  fullWidth
                  multiline
                  minRows={3}
                  label="Character description"
                  value={item.state?.description ?? ""}
                  onChange={(event) =>
                    replace(items, index, { ...item, state: { ...item.state, description: event.target.value } }, onChange)
                  }
                />
                <TextField
                  fullWidth
                  multiline
                  minRows={2}
                  label="Identity and background"
                  value={item.state?.identity ?? ""}
                  onChange={(event) =>
                    replace(items, index, { ...item, state: { ...item.state, identity: event.target.value } }, onChange)
                  }
                />
                <TextField
                  label="Pronouns"
                  value={item.state?.pronouns ?? ""}
                  onChange={(event) =>
                    replace(items, index, { ...item, state: { ...item.state, pronouns: event.target.value } }, onChange)
                  }
                />
                <TextField
                  fullWidth
                  multiline
                  minRows={3}
                  label="Appearance"
                  value={item.state?.appearance ?? ""}
                  onChange={(event) =>
                    replace(items, index, { ...item, state: { ...item.state, appearance: event.target.value } }, onChange)
                  }
                />
                <TextField
                  fullWidth
                  multiline
                  minRows={3}
                  label="Personality"
                  value={item.state?.personality ?? ""}
                  onChange={(event) =>
                    replace(items, index, { ...item, state: { ...item.state, personality: event.target.value } }, onChange)
                  }
                />
                <CreatableBoxedMultiselect
                  label="Goals"
                  options={strings(item.state?.goals)}
                  value={strings(item.state?.goals)}
                  onChange={(_event, next) =>
                    replace(items, index, { ...item, state: { ...item.state, goals: next } }, onChange)
                  }
                />
                <TextField
                  fullWidth
                  multiline
                  minRows={2}
                  label="General narrator secret notes"
                  value={item.state?.secrets ?? ""}
                  onChange={(event) =>
                    replace(items, index, { ...item, state: { ...item.state, secrets: event.target.value } }, onChange)
                  }
                />
                <TextField
                  select
                  label="Cast role"
                  value={item.state?.cast_role ?? "supporting"}
                  onChange={(event) =>
                    replace(
                      items,
                      index,
                      {
                        ...item,
                        state: {
                          ...item.state,
                          cast_role: event.target.value,
                          player_controlled: event.target.value === "player",
                          autonomy_enabled:
                            event.target.value === "player" ? false : Boolean(item.state?.autonomy_enabled),
                        },
                      },
                      onChange,
                    )
                  }
                >
                  {["player", "active_npc", "supporting", "background"].map((role) => (
                    <MenuItem key={role} value={role}>
                      {humanize(role)}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  label="Starting location key"
                  value={item.state?.current_location_key ?? ""}
                  onChange={(event) =>
                    replace(items, index, {
                      ...item,
                      state: { ...item.state, current_location_key: event.target.value || null },
                    }, onChange)
                  }
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      disabled={item.state?.cast_role === "player"}
                      checked={Boolean(item.state?.autonomy_enabled)}
                      onChange={(event) =>
                        replace(items, index, {
                          ...item,
                          state: { ...item.state, autonomy_enabled: event.target.checked },
                        }, onChange)
                      }
                    />
                  }
                  label="NPC autonomy"
                />
                <TextField
                  select
                  label="Intervention frequency"
                  value={item.state?.intervention_frequency ?? "normal"}
                  onChange={(event) =>
                    replace(items, index, {
                      ...item,
                      state: { ...item.state, intervention_frequency: event.target.value },
                    }, onChange)
                  }
                >
                  {["low", "normal", "high"].map((frequency) => (
                    <MenuItem key={frequency} value={frequency}>{humanize(frequency)}</MenuItem>
                  ))}
                </TextField>
                <CreatableBoxedMultiselect
                  label="Character secrets (known while acting)"
                  options={strings(item.state?.character_secrets)}
                  value={strings(item.state?.character_secrets)}
                  onChange={(_event, next) =>
                    replace(items, index, { ...item, state: { ...item.state, character_secrets: next } }, onChange)
                  }
                />
                <CreatableBoxedMultiselect
                  label="Secrets from character (narrator only)"
                  options={strings(item.state?.secrets_to_character)}
                  value={strings(item.state?.secrets_to_character)}
                  onChange={(_event, next) =>
                    replace(items, index, { ...item, state: { ...item.state, secrets_to_character: next } }, onChange)
                  }
                />
              </>
            )}
            <TextField
              multiline
              minRows={3}
              label="Structured state JSON"
              value={JSON.stringify(item.state ?? {}, null, 2)}
              onChange={(event) => {
                try {
                  replace(items, index, { ...item, state: JSON.parse(event.target.value) }, onChange);
                } catch {
                  /* preserve last valid state */
                }
              }}
            />
            <Button color="error" onClick={() => onChange(items.filter((_, position) => position !== index))}>
              Remove
            </Button>
          </CardContent>
        </Card>
      ))}
    </section>
  );
}

function WeatherEditor({ draft, update }: { draft: any; update: (draft: any) => void }) {
  const weather = array(draft.weather);
  const transitions = array(draft.weather_transitions);
  return (
    <section>
      <ResourceListEditor
        title="Weather patterns"
        kind="weather"
        items={weather.map((item) => ({
          ...item,
          state: {
            description: item.description,
            imagegen_description: item.imagegen_description,
            enabled: item.enabled,
            image_tags: item.image_tags,
          },
        }))}
        onChange={(items) =>
          update({
            ...draft,
            weather: items.map((item) => ({
              key: item.key,
              name: item.name,
              tags: item.tags,
              description: item.state?.description ?? "",
              imagegen_description: item.state?.imagegen_description ?? "",
              image_tags: item.state?.image_tags ?? [],
              enabled: item.state?.enabled !== false,
            })),
          })
        }
      />
      <h3>Directed transitions</h3>
      {weather.map((source) => (
        <BoxedMultiselectFilter
          key={source.key}
          label={`${source.name || source.key} can transition to`}
          options={weather.filter((target) => target.key !== source.key && target.enabled !== false)}
          value={weather.filter((target) =>
            transitions.some((edge) => edge.source_key === source.key && edge.target_key === target.key),
          )}
          getOptionLabel={(item: any) => item.name || item.key}
          isOptionEqualToValue={(left: any, right: any) => left.key === right.key}
          onChange={(_event, next) =>
            update({
              ...draft,
              weather_transitions: [
                ...transitions.filter((edge) => edge.source_key !== source.key),
                ...next.map((target: any) => ({
                  source_key: source.key,
                  target_key: target.key,
                })),
              ],
            })
          }
        />
      ))}
      <TextField
        label="Initial weather key"
        value={draft.initial_weather_key ?? ""}
        onChange={(event) => update({ ...draft, initial_weather_key: event.target.value })}
      />
    </section>
  );
}

function JsonCollection({
  title,
  items,
  onChange,
  template,
}: {
  title: string;
  items: any[];
  onChange: (items: any[]) => void;
  template: any;
}) {
  return (
    <section>
      <div className="sheet-heading">
        <h3>{title}</h3>
        <Button onClick={() => onChange([...items, structuredClone(template)])}>Add</Button>
      </div>
      {items.map((item, index) => (
        <Card key={index} variant="outlined">
          <CardContent>
            <TextField
              fullWidth
              multiline
              minRows={5}
              label={`${title} record`}
              value={JSON.stringify(item, null, 2)}
              onChange={(event) => {
                try {
                  replace(items, index, JSON.parse(event.target.value), onChange);
                } catch {
                  /* preserve last valid object */
                }
              }}
            />
            <Button color="error" onClick={() => onChange(items.filter((_, position) => position !== index))}>
              Remove
            </Button>
          </CardContent>
        </Card>
      ))}
    </section>
  );
}

function RuntimeEditor({ draft, update, catalogs }: { draft: any; update: (draft: any) => void; catalogs: Catalogs }) {
  const minigames = catalogs.minigames.map((game) => ({
    ...game,
    ...(array(draft.minigames).find((item) => item.game_key === game.game_key) ?? {}),
  }));
  const bullet = draft.bullethell ?? {};
  const music = draft.music ?? {};
  return (
    <div className="character-fields">
      <h3>Minigames</h3>
      {minigames.map((game) => (
        <FormControlLabel
          key={game.game_key}
          control={
            <Checkbox
              checked={Boolean(game.enabled)}
              onChange={(event) =>
                update({
                  ...draft,
                  minigames: minigames.map((item) => ({
                    ...item,
                    enabled: item.game_key === game.game_key ? event.target.checked : Boolean(item.enabled),
                  })),
                })
              }
            />
          }
          label={humanize(game.game_key)}
        />
      ))}
      <BoxedMultiselectFilter
        label="Bullet-hell modes"
        options={catalogs.bullet.modes}
        value={catalogs.bullet.modes.filter((item) => strings(bullet.mode_ids).includes(item.id))}
        onChange={(_event, next) =>
          update({
            ...draft,
            bullethell: {
              ...bullet,
              mode_ids: next.map((item: any) => item.id),
            },
          })
        }
      />
      <BoxedMultiselectFilter
        label="Bullet-hell skills"
        options={catalogs.bullet.skills}
        value={catalogs.bullet.skills.filter((item) => strings(bullet.skill_ids).includes(item.id))}
        onChange={(_event, next) =>
          update({
            ...draft,
            bullethell: {
              ...bullet,
              skill_ids: next.map((item: any) => item.id),
            },
          })
        }
      />
      <BoxedMultiselectFilter
        label="Bullet-hell attacks"
        options={catalogs.bullet.attacks}
        value={catalogs.bullet.attacks.filter((item) => strings(bullet.attack_ids).includes(item.id))}
        onChange={(_event, next) =>
          update({
            ...draft,
            bullethell: {
              ...bullet,
              attack_ids: next.map((item: any) => item.id),
            },
          })
        }
      />
      <AmbientRuleEditor
        rules={array(draft.ambient)}
        sounds={catalogs.ambient}
        onChange={(ambient) => update({ ...draft, ambient })}
      />
      <h3>Music (separate from Ambient)</h3>
      <TextField
        select
        label="Music mode"
        value={music.mode ?? "disabled"}
        onChange={(event) => update({ ...draft, music: { ...music, mode: event.target.value } })}
      >
        {["disabled", "player_managed", "ai_managed"].map((mode) => (
          <MenuItem key={mode} value={mode}>
            {humanize(mode)}
          </MenuItem>
        ))}
      </TextField>
      <BoxedMultiselectFilter
        label="Enabled Music themes"
        options={catalogs.music}
        value={catalogs.music.filter((theme) => strings(music.enabled_theme_ids).includes(theme.id))}
        onChange={(_event, next) =>
          update({
            ...draft,
            music: {
              ...music,
              enabled_theme_ids: next.map((item: MusicTheme) => item.id),
            },
          })
        }
        getOptionSecondaryText={(item: MusicTheme) => item.description}
      />
      {array(draft.recommendations).length > 0 && (
        <Alert severity="warning">{array(draft.recommendations).map(String).join(" · ")}</Alert>
      )}
    </div>
  );
}

function AmbientRuleEditor({
  rules,
  sounds,
  onChange,
}: {
  rules: any[];
  sounds: AmbientVariant[];
  onChange: (rules: any[]) => void;
}) {
  return (
    <section className="wide">
      <div className="sheet-heading">
        <div>
          <h3>Ambient sound rules</h3>
          <p className="muted">Loop assignments only. Music configuration is handled below.</p>
        </div>
        <Button
          onClick={() =>
            onChange([
              ...rules,
              {
                owner_type: "location",
                owner_key: "",
                variant_ids: [],
                sets: [],
              },
            ])
          }
        >
          Add ambient rule
        </Button>
      </div>
      {rules.map((rule, index) => (
        <Card key={index} variant="outlined">
          <CardContent className="planning-card-fields">
            <TextField
              select
              label="Owner type"
              value={rule.owner_type ?? "location"}
              onChange={(event) => replace(rules, index, { ...rule, owner_type: event.target.value }, onChange)}
            >
              {["weather", "time", "location", "action"].map((type) => (
                <MenuItem key={type} value={type}>
                  {humanize(type)}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Stable owner key / ID"
              value={rule.owner_key ?? ""}
              onChange={(event) => replace(rules, index, { ...rule, owner_key: event.target.value }, onChange)}
            />
            <BoxedMultiselectFilter
              label="Default ambient sounds"
              options={sounds}
              value={sounds.filter((sound) => strings(rule.variant_ids).includes(sound.id))}
              getOptionLabel={(sound: AmbientVariant) => sound.label}
              isOptionEqualToValue={(left: AmbientVariant, right: AmbientVariant) => left.id === right.id}
              getOptionDisabled={(sound: AmbientVariant) => !sound.enabled || !sound.available}
              getOptionSecondaryText={(sound: AmbientVariant) =>
                `${sound.playback_rate}x · gain ${sound.default_gain}${!sound.available ? " · missing" : !sound.enabled ? " · disabled" : ""}`
              }
              onChange={(_event, next) =>
                replace(
                  rules,
                  index,
                  {
                    ...rule,
                    variant_ids: next.map((sound: AmbientVariant) => sound.id),
                  },
                  onChange,
                )
              }
            />
            <JsonCollection
              title="Conditional ambient sets"
              items={array(rule.sets)}
              onChange={(sets) => replace(rules, index, { ...rule, sets }, onChange)}
              template={{
                selector_type: "default",
                selector_value: null,
                weather_key: null,
                time_phase_id: null,
                variant_ids: [],
              }}
            />
            <Button color="error" onClick={() => onChange(rules.filter((_, position) => position !== index))}>
              Remove rule
            </Button>
          </CardContent>
        </Card>
      ))}
    </section>
  );
}

function MapPreview({ locations, routes }: { locations: any[]; routes: any[] }) {
  if (!locations.length)
    return (
      <Alert severity="info">
        Add locations to see a compact map preview. Missing coordinates use a deterministic grid.
      </Alert>
    );
  return (
    <section>
      <div className="sheet-heading">
        <h3>Map preview</h3>
        <Chip size="small" label={`${locations.length} places · ${routes.length} routes`} />
      </div>
      <div className="planning-map-preview">
        {locations.map((location, index) => {
          const x = Number(location.state?.x ?? index % 4);
          const y = Number(location.state?.y ?? Math.floor(index / 4));
          return (
            <div
              className="planning-map-node"
              key={location.key || index}
              style={{
                gridColumn: Math.max(1, Math.round(x) + 1),
                gridRow: Math.max(1, Math.round(y) + 1),
              }}
            >
              <b>{location.name || location.key || "Unnamed"}</b>
              <small>
                {location.state?.parent_location_key ? `inside ${location.state.parent_location_key}` : "top level"}
              </small>
            </div>
          );
        })}
      </div>
      <div className="planning-route-list">
        {routes.slice(0, 12).map((route, index) => (
          <Chip
            key={route.key || index}
            size="small"
            label={`${route.source_key || "?"} → ${route.target_key || "?"} · ${route.travel_minutes ?? 0} min`}
          />
        ))}
      </div>
    </section>
  );
}

function ImagePlanEditor({
  plans,
  workflows,
  selected,
  setSelected,
  updatePlan,
  generate,
}: {
  plans: PlanningAssetPlan[];
  workflows: WorkflowPreset[];
  selected: string[];
  setSelected: (ids: string[]) => void;
  updatePlan: (plan: PlanningAssetPlan, patch: Partial<PlanningAssetPlan>) => Promise<void>;
  generate: (ids: string[]) => Promise<void>;
}) {
  return (
    <div>
      <div className="button-row">
        <Button disabled={!selected.length} onClick={() => void generate(selected)}>
          Generate selected
        </Button>
        <Button onClick={() => void generate([])}>Generate all ready</Button>
      </div>
      <div className="planning-image-grid">
        {plans.map((plan) => (
          <Card key={plan.id} variant="outlined">
            <CardContent className="planning-card-fields">
              <FormControlLabel
                control={
                  <Checkbox
                    checked={selected.includes(plan.id)}
                    onChange={(event) =>
                      setSelected(
                        event.target.checked ? [...selected, plan.id] : selected.filter((id) => id !== plan.id),
                      )
                    }
                  />
                }
                label={`${plan.kind} · ${plan.status}`}
              />
              <TextField
                multiline
                minRows={4}
                label="Prompt"
                defaultValue={plan.prompt}
                onBlur={(event) => {
                  if (event.target.value !== plan.prompt) void updatePlan(plan, { prompt: event.target.value });
                }}
              />
              <TextField
                multiline
                minRows={2}
                label="Negative prompt"
                defaultValue={plan.negative_prompt}
                onBlur={(event) => {
                  if (event.target.value !== plan.negative_prompt)
                    void updatePlan(plan, {
                      negative_prompt: event.target.value,
                    });
                }}
              />
              <TextField
                select
                label="Workflow"
                value={plan.workflow_preset_id ?? ""}
                onChange={(event) =>
                  void updatePlan(plan, {
                    workflow_preset_id: event.target.value || null,
                  })
                }
              >
                <MenuItem value="">Select workflow</MenuItem>
                {workflows.map((workflow) => (
                  <MenuItem key={workflow.id} value={workflow.id} disabled={workflow.validation_status !== "valid"}>
                    {workflow.name}
                    {workflow.validation_status !== "valid" ? " (not valid)" : ""}
                  </MenuItem>
                ))}
              </TextField>
              <Button
                disabled={plan.status !== "ready" && plan.status !== "failed"}
                onClick={() => void generate([plan.id])}
              >
                Generate
              </Button>
              {plan.error && <Alert severity="error">{plan.error}</Alert>}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function clearCurrentSection(stage: number, focus: string, draft: any): any {
  const next = structuredClone(draft);
  const blank = emptyStage(stage);
  for (const field of STAGE_SECTION_FIELDS[stage]?.[focus] ?? [focus]) next[field] = structuredClone(blank[field]);
  return next;
}

function emptyStage(stage: number): any {
  const common = { summary: "", notes: [] };
  return stage === 1
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
    : stage === 2
      ? {
          ...common,
          locations: [],
          routes: [],
          factions: [],
          weather: [],
          weather_transitions: [],
          initial_weather_key: "",
        }
      : stage === 3
        ? { ...common, locations: [], routes: [] }
        : stage === 4
          ? { ...common, lore_systems: [], stats: [], abilities: [], items: [] }
          : stage === 5
            ? {
                ...common,
                characters: [],
                factions: [],
                facts: [],
                default_pov_character_key: "",
              }
            : stage === 6
              ? {
                  ...common,
                  character_updates: [],
                  outfits: [],
                  relationships: [],
                  routines: [],
                  facts: [],
                  plot_beats: [],
                }
              : stage === 7
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
const array = (value: unknown): any[] => (Array.isArray(value) ? value : []);
const strings = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : []);
function replace(items: any[], index: number, item: any, onChange: (items: any[]) => void) {
  const next = [...items];
  next[index] = item;
  onChange(next);
}
function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}
function message(cause: unknown) {
  return cause instanceof Error ? cause.message : String(cause);
}
function delay(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
