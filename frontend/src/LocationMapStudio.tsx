import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  ButtonGroup,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Switch,
  TextField,
} from "@mui/material";
import { api } from "./api";
import type { AbilityDefinition, StatDefinition, WorkflowPreset, WorldEntity, WorldProjection } from "./types";
import { blankConditionExpression, conditionExpressionFromPayload, ConditionExpressionEditor } from "./RuleConditionEditor";
import { SpatialV2Canvas } from "./SpatialV2Canvas";

type Point = [number, number];
type Tool = "select" | "edit" | "surface" | "corridor" | "barrier" | "spot" | "connector";
type FeatureKind = Exclude<Tool, "select" | "edit">;
type RenderLayer = "topology" | "regions" | "roads" | "places" | "barriers" | "connections";
type LabelsMode = "hidden" | "important" | "all";

type TraversalOption = {
  key: string;
  label: string;
  requirements?: Record<string, unknown> | null;
  travel_multiplier: number;
  fixed_minutes?: number | null;
};
type TraversalPolicy = {
  default_allowed: boolean;
  travel_multiplier: number;
  options: TraversalOption[];
};
type NavigationSpace = {
  id: string;
  project_id: string;
  owner_location_id?: string | null;
  navigation_mode: "free" | "routed";
  base_travel_multiplier: number;
  bounds?: { type: "Polygon" | "MultiPolygon"; coordinates: unknown } | null;
  revision: number;
};
type MapFeature = {
  id: string;
  project_id: string;
  navigation_space_id: string;
  semantic_location_id?: string | null;
  feature_kind: FeatureKind;
  name: string;
  geometry:
    | { type: "Point"; coordinates: Point }
    | { type: "LineString"; coordinates: Point[] }
    | { type: "MultiLineString"; coordinates: Point[][] }
    | { type: "Polygon"; coordinates: Point[][] }
    | { type: "MultiPolygon"; coordinates: Point[][][] };
  render_layer: RenderLayer;
  render_order: number;
  movement_priority: number;
  hidden: boolean;
  discovered: boolean;
  enabled: boolean;
  metadata: Record<string, unknown>;
  properties: Record<string, any>;
};
type NavigationLayer = {
  navigation_space_id: string;
  layer_key: string;
  label: string;
  position: number;
  visible: boolean;
  labels_mode: LabelsMode;
};
type EncounterCandidate = {
  location_id: string;
  weight: number;
  requirements?: Record<string, unknown> | null;
};
type EncounterPolicy = {
  id: string;
  project_id: string;
  navigation_space_id?: string | null;
  feature_id?: string | null;
  mode: "augment" | "replace" | "disabled";
  priority: number;
  trigger_kind: "distance" | "transition";
  rate_per_100_units: number;
  probability_per_transition?: number | null;
  minimum_distance: number;
  candidates: EncounterCandidate[];
  conditions?: Record<string, unknown> | null;
  enabled: boolean;
};
type SpaceDetails = {
  space: NavigationSpace;
  features: MapFeature[];
  layers: NavigationLayer[];
  encounter_policies: EncounterPolicy[];
};
type MigrationPreview = {
  spaces?: unknown[];
  features?: unknown[];
  encounter_policies?: unknown[];
  counts?: Record<string, number>;
  [key: string]: unknown;
};
type SpatialPreset = {
  key: string;
  label: string;
  description: string;
  parameters: string[];
  requires_semantic_location?: boolean;
  requires_target_space?: boolean;
};

const renderLayers: RenderLayer[] = ["topology", "regions", "roads", "places", "barriers", "connections"];
const connectorKinds = ["generic", "door", "gate", "stairs", "ladder", "bridge", "climb", "portal"] as const;
const emptyTraversal = (allowed = true): TraversalPolicy => ({ default_allowed: allowed, travel_multiplier: 1, options: [] });
const newId = (prefix: string) => `${prefix}-${crypto.randomUUID()}`;
const parseCsv = (value: string) => value.split(",").map(item => item.trim()).filter(Boolean);
const formatCsv = (value: unknown) => Array.isArray(value) ? value.join(", ") : "";
const presetDefaults = (key: string) => ({
  name: "",
  semantic_location_id: "",
  center_x: 50,
  center_y: 50,
  width: key === "road" ? 6 : key === "river" ? 10 : 60,
  height: 60,
  target_space_id: "",
  target_x: 50,
  target_y: 50,
});
const locationName = (world: WorldProjection | null, id?: string | null) =>
  id ? world?.entities[id]?.name ?? id : "Unbound";

function defaultProperties(kind: FeatureKind): Record<string, any> {
  if (kind === "surface") return { traversal: emptyTraversal(true), ambience_tags: [], environment_tags: [] };
  if (kind === "corridor") return { width: 4, traversal: emptyTraversal(true), ambience_tags: [] };
  if (kind === "barrier") return { traversal: emptyTraversal(false) };
  if (kind === "spot") return { interaction_kind: "generic" };
  return {
    connector_kind: "door",
    source: { navigation_space_id: "", point: [0, 0] as Point },
    target: { navigation_space_id: "", point: [0, 0] as Point },
    traversal: emptyTraversal(true),
    travel_minutes: null,
    bidirectional: true,
  };
}

function defaultLayer(kind: FeatureKind): RenderLayer {
  if (kind === "surface") return "regions";
  if (kind === "corridor") return "roads";
  if (kind === "barrier") return "barriers";
  if (kind === "connector") return "connections";
  return "places";
}

function traversalOf(feature: MapFeature): TraversalPolicy | null {
  return feature.feature_kind === "spot" ? null : feature.properties.traversal ?? emptyTraversal(feature.feature_kind !== "barrier");
}

function TraversalEditor({
  value,
  stats,
  abilities,
  locations,
  onChange,
}: {
  value: TraversalPolicy;
  stats: StatDefinition[];
  abilities: AbilityDefinition[];
  locations: Array<{ id: string; name: string }>;
  onChange: (value: TraversalPolicy) => void;
}) {
  return <section className="panel">
    <h3>Traversal</h3>
    <Stack direction="row" spacing={2} flexWrap="wrap">
      <FormControlLabel control={<Switch checked={value.default_allowed} onChange={event => onChange({ ...value, default_allowed: event.target.checked })}/>} label="Default allowed"/>
      <TextField size="small" type="number" label="Travel multiplier" value={value.travel_multiplier} onChange={event => onChange({ ...value, travel_multiplier: Math.max(.01, Number(event.target.value) || 1) })}/>
    </Stack>
    <h4>Conditional alternatives</h4>
    {value.options.map((option, index) => <Paper key={index} variant="outlined" sx={{ p: 1.5, mb: 1 }}>
      <Stack direction="row" spacing={1} flexWrap="wrap">
        <TextField size="small" label="Key" value={option.key} onChange={event => onChange({ ...value, options: value.options.map((item, itemIndex) => itemIndex === index ? { ...item, key: event.target.value } : item) })}/>
        <TextField size="small" label="Label" value={option.label} onChange={event => onChange({ ...value, options: value.options.map((item, itemIndex) => itemIndex === index ? { ...item, label: event.target.value } : item) })}/>
        <TextField size="small" type="number" label="Multiplier" value={option.travel_multiplier} onChange={event => onChange({ ...value, options: value.options.map((item, itemIndex) => itemIndex === index ? { ...item, travel_multiplier: Math.max(.01, Number(event.target.value) || 1) } : item) })}/>
        <TextField size="small" type="number" label="Fixed minutes" value={option.fixed_minutes ?? ""} onChange={event => onChange({ ...value, options: value.options.map((item, itemIndex) => itemIndex === index ? { ...item, fixed_minutes: event.target.value === "" ? null : Math.max(0, Number(event.target.value)) } : item) })}/>
        <Button color="error" onClick={() => onChange({ ...value, options: value.options.filter((_, itemIndex) => itemIndex !== index) })}>Remove</Button>
      </Stack>
      <div style={{ marginTop: 8 }}>
        {option.requirements
          ? <ConditionExpressionEditor node={conditionExpressionFromPayload(option.requirements as Record<string, unknown>, stats)} stats={stats} abilities={abilities} locations={locations} onChange={requirements => onChange({ ...value, options: value.options.map((item, itemIndex) => itemIndex === index ? { ...item, requirements } : item) })} onRemove={() => onChange({ ...value, options: value.options.map((item, itemIndex) => itemIndex === index ? { ...item, requirements: null } : item) })}/>
          : <Button size="small" onClick={() => onChange({ ...value, options: value.options.map((item, itemIndex) => itemIndex === index ? { ...item, requirements: blankConditionExpression("compare", stats) } : item) })}>Add requirement</Button>}
      </div>
    </Paper>)}
    <Button onClick={() => onChange({ ...value, options: [...value.options, { key: `option_${value.options.length + 1}`, label: "Alternative", requirements: null, travel_multiplier: 1, fixed_minutes: null }] })}>Add traversal option</Button>
  </section>;
}

export function LocationMapStudio({
  projectId,
  revision,
  workflows: _workflows,
  fail,
}: {
  projectId: string;
  revision: number;
  workflows: WorkflowPreset[];
  fail: (message: string) => void;
}) {
  const [world, setWorld] = useState<WorldProjection | null>(null);
  const [ruleData, setRuleData] = useState<{ stats: StatDefinition[]; abilities: AbilityDefinition[] }>({ stats: [], abilities: [] });
  const [spaces, setSpaces] = useState<NavigationSpace[]>([]);
  const [spaceId, setSpaceId] = useState("");
  const [details, setDetails] = useState<SpaceDetails | null>(null);
  const [tool, setTool] = useState<Tool>("select");
  const [draftPoints, setDraftPoints] = useState<Point[]>([]);
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null);
  const [featureDraft, setFeatureDraft] = useState<MapFeature | null>(null);
  const [spaceDraft, setSpaceDraft] = useState<NavigationSpace | null>(null);
  const [createSpaceOpen, setCreateSpaceOpen] = useState(false);
  const [createSpaceLocation, setCreateSpaceLocation] = useState("");
  const [createSpaceMode, setCreateSpaceMode] = useState<"free" | "routed">("free");
  const [connectorPoint, setConnectorPoint] = useState<Point | null>(null);
  const [connectorTargetSpace, setConnectorTargetSpace] = useState("");
  const [connectorTargetPoint, setConnectorTargetPoint] = useState<Point>([50, 50]);
  const [migration, setMigration] = useState<MigrationPreview | null>(null);
  const [presets, setPresets] = useState<SpatialPreset[]>([]);
  const [presetOpen, setPresetOpen] = useState(false);
  const [presetKey, setPresetKey] = useState("open_region");
  const [presetParams, setPresetParams] = useState(presetDefaults("open_region"));
  const [encounterDraft, setEncounterDraft] = useState<EncounterPolicy | null>(null);
  const [draftTemplate, setDraftTemplate] = useState<Partial<MapFeature> | null>(null);
  const [locationDialogOpen, setLocationDialogOpen] = useState(false);
  const [locationNameDraft, setLocationNameDraft] = useState("");
  const [locationAssignTarget, setLocationAssignTarget] = useState<"feature" | "space">("feature");

  const locations = useMemo(
    () => Object.values(world?.entities ?? {}).filter((item: WorldEntity) => item.kind === "location" && !item.state.archived),
    [world],
  );

  const loadSpaces = useCallback(async () => {
    const [nextWorld, nextSpaces, nextRules, nextPresets] = await Promise.all([
      api<WorldProjection>(`/projects/${projectId}/world`),
      api<NavigationSpace[]>(`/projects/${projectId}/spatial-v3/spaces`),
      api<{ stats: StatDefinition[]; abilities: AbilityDefinition[] }>(`/projects/${projectId}/rules`),
      api<SpatialPreset[]>(`/projects/${projectId}/spatial-v3/presets`),
    ]);
    setWorld(nextWorld);
    setSpaces(nextSpaces);
    setRuleData({ stats: nextRules.stats ?? [], abilities: nextRules.abilities ?? [] });
    setPresets(nextPresets);
    setSpaceId(current => current && nextSpaces.some(item => item.id === current) ? current : nextSpaces[0]?.id ?? "");
    if (!nextSpaces.length) {
      try { setMigration(await api<MigrationPreview>(`/projects/${projectId}/spatial-v3/migration-preview`)); }
      catch { setMigration(null); }
    } else setMigration(null);
  }, [projectId]);

  const loadDetails = useCallback(async () => {
    if (!spaceId) { setDetails(null); setSpaceDraft(null); return; }
    const next = await api<SpaceDetails>(`/projects/${projectId}/spatial-v3/spaces/${spaceId}`);
    setDetails(next);
    setSpaceDraft(next.space);
    setSelectedFeatureId(current => current && next.features.some(item => item.id === current) ? current : null);
  }, [projectId, spaceId]);

  useEffect(() => { void loadSpaces().catch(cause => fail(String(cause))); }, [loadSpaces, revision, fail]);
  useEffect(() => { void loadDetails().catch(cause => fail(String(cause))); }, [loadDetails, fail]);
  useEffect(() => {
    const next = selectedFeatureId ? details?.features.find(item => item.id === selectedFeatureId) ?? null : null;
    setFeatureDraft(next ? structuredClone(next) : null);
  }, [selectedFeatureId, details]);

  async function refresh() {
    await loadSpaces();
    await loadDetails();
  }

  async function saveSpace() {
    if (!spaceDraft) return;
    try {
      await api(`/projects/${projectId}/spatial-v3/spaces/${spaceDraft.id}`, { method: "PUT", body: JSON.stringify(spaceDraft) });
      await refresh();
    } catch (cause) { fail(String(cause)); }
  }

  async function createSpace() {
    if (!createSpaceLocation) return;
    const id = newId("space");
    try {
      await api(`/projects/${projectId}/spatial-v3/spaces/${id}`, {
        method: "PUT",
        body: JSON.stringify({
          id,
          project_id: projectId,
          owner_location_id: createSpaceLocation,
          navigation_mode: createSpaceMode,
          base_travel_multiplier: 1,
          bounds: null,
          revision: 1,
        }),
      });
      await api(`/projects/${projectId}/spatial-v3/locations/${createSpaceLocation}/binding`, {
        method: "PUT",
        body: JSON.stringify({
          project_id: projectId,
          location_id: createSpaceLocation,
          navigation_space_id: id,
          entrance_policy: createSpaceMode === "routed" ? "connectors" : "open",
          bounds_mode: "independent",
        }),
      });
      setCreateSpaceOpen(false);
      await loadSpaces();
      setSpaceId(id);
    } catch (cause) { fail(String(cause)); }
  }

  async function materializeLegacy() {
    try {
      await api(`/projects/${projectId}/spatial-v3/materialize`, { method: "POST" });
      await loadSpaces();
    } catch (cause) { fail(String(cause)); }
  }

  async function createFeature(kind: FeatureKind, points = draftPoints) {
    if (!spaceId) return;
    if (kind === "surface" && points.length < 3) return;
    if ((kind === "corridor" || kind === "barrier") && points.length < 2) return;
    const id = newId(kind);
    const properties = defaultProperties(kind);
    let geometry: MapFeature["geometry"];
    if (kind === "surface") {
      const ring = [...points, points[0]];
      geometry = { type: "Polygon", coordinates: [ring] };
    } else if (kind === "spot") geometry = { type: "Point", coordinates: points[0] };
    else geometry = { type: "LineString", coordinates: points };
    const feature: MapFeature = {
      id,
      project_id: projectId,
      navigation_space_id: spaceId,
      semantic_location_id: (draftTemplate?.semantic_location_id as string | null | undefined) ?? null,
      feature_kind: kind,
      name: String(draftTemplate?.name ?? (kind[0].toUpperCase() + kind.slice(1))),
      geometry,
      render_layer: (draftTemplate?.render_layer as RenderLayer | undefined) ?? defaultLayer(kind),
      render_order: Number(draftTemplate?.render_order ?? 0),
      movement_priority: Number(draftTemplate?.movement_priority ?? (kind === "corridor" ? 10 : 0)),
      hidden: false,
      discovered: true,
      enabled: true,
      metadata: {},
      properties: (draftTemplate?.properties as Record<string, any> | undefined) ?? properties,
    };
    try {
      await api(`/projects/${projectId}/spatial-v3/features/${id}`, { method: "PUT", body: JSON.stringify(feature) });
      setDraftPoints([]);
      setDraftTemplate(null);
      setTool("select");
      await loadDetails();
      setSelectedFeatureId(id);
    } catch (cause) { fail(String(cause)); }
  }

  async function createConnector() {
    if (!connectorPoint || !spaceId || !connectorTargetSpace) return;
    const id = newId("connector");
    const feature: MapFeature = {
      id,
      project_id: projectId,
      navigation_space_id: spaceId,
      semantic_location_id: null,
      feature_kind: "connector",
      name: "Connector",
      geometry: { type: "Point", coordinates: connectorPoint },
      render_layer: "connections",
      render_order: 0,
      movement_priority: 100,
      hidden: false,
      discovered: true,
      enabled: true,
      metadata: {},
      properties: {
        ...defaultProperties("connector"),
        source: { navigation_space_id: spaceId, point: connectorPoint },
        target: { navigation_space_id: connectorTargetSpace, point: connectorTargetPoint },
      },
    };
    try {
      await api(`/projects/${projectId}/spatial-v3/features/${id}`, { method: "PUT", body: JSON.stringify(feature) });
      setConnectorPoint(null);
      setTool("select");
      await loadDetails();
      setSelectedFeatureId(id);
    } catch (cause) { fail(String(cause)); }
  }

  async function persistCanvasFeature(next: MapFeature) {
    setFeatureDraft(current => current?.id === next.id ? next : current);
    setDetails(current => current ? {
      ...current,
      features: current.features.map(item => item.id === next.id ? next : item),
    } : current);
    try {
      await api(`/projects/${projectId}/spatial-v3/features/${next.id}`, {
        method: "PUT",
        body: JSON.stringify(next),
      });
    } catch (cause) {
      fail(String(cause));
      await loadDetails();
    }
  }

  async function saveFeature() {
    if (!featureDraft) return;
    try {
      await api(`/projects/${projectId}/spatial-v3/features/${featureDraft.id}`, { method: "PUT", body: JSON.stringify(featureDraft) });
      await loadDetails();
    } catch (cause) { fail(String(cause)); }
  }

  async function deleteFeature() {
    if (!featureDraft) return;
    try {
      await api(`/projects/${projectId}/spatial-v3/features/${featureDraft.id}`, { method: "DELETE" });
      setSelectedFeatureId(null);
      await loadDetails();
    } catch (cause) { fail(String(cause)); }
  }

  function openPreset(key = presets[0]?.key ?? "open_region") {
    setPresetKey(key);
    setPresetParams({
      ...presetDefaults(key),
      semantic_location_id: spaces.find(item => item.id === spaceId)?.owner_location_id ?? "",
      target_space_id: spaces.find(item => item.id !== spaceId)?.id ?? "",
    });
    setPresetOpen(true);
  }

  async function applyPreset() {
    if (!spaceId || !presetKey) return;
    try {
      await api(`/projects/${projectId}/spatial-v3/presets/${presetKey}/apply`, {
        method: "POST",
        body: JSON.stringify({
          navigation_space_id: spaceId,
          ...presetParams,
        }),
      });
      setPresetOpen(false);
      await refresh();
    } catch (cause) { fail(String(cause)); }
  }

  async function createLocationFromMap() {
    const name = locationNameDraft.trim();
    if (!name) return;
    try {
      const created = await api<{ id: string; name: string }>(`/projects/${projectId}/entities`, {
        method: "POST",
        body: JSON.stringify({
          kind: "location",
          name,
          aliases: [],
          tags: [],
          state: { description: "", enabled: true, discovered: true },
        }),
      });
      await loadSpaces();
      if (locationAssignTarget === "feature" && featureDraft) {
        setFeatureDraft({ ...featureDraft, semantic_location_id: created.id });
      } else if (locationAssignTarget === "space") {
        setCreateSpaceLocation(created.id);
      }
      setLocationNameDraft("");
      setLocationDialogOpen(false);
    } catch (cause) { fail(String(cause)); }
  }

  async function saveLayer(layer: NavigationLayer) {
    try {
      await api(`/projects/${projectId}/spatial-v3/spaces/${spaceId}/layers/${layer.layer_key}`, {
        method: "PUT",
        body: JSON.stringify(layer),
      });
      await loadDetails();
    } catch (cause) { fail(String(cause)); }
  }

  async function saveEncounter() {
    if (!encounterDraft) return;
    try {
      await api(`/projects/${projectId}/spatial-v3/encounters/${encounterDraft.id}`, {
        method: "PUT",
        body: JSON.stringify(encounterDraft),
      });
      setEncounterDraft(null);
      await loadDetails();
    } catch (cause) { fail(String(cause)); }
  }

  async function deleteEncounter(policy: EncounterPolicy) {
    try {
      await api(`/projects/${projectId}/spatial-v3/encounters/${policy.id}`, { method: "DELETE" });
      await loadDetails();
    } catch (cause) { fail(String(cause)); }
  }

  const visibleFeatures = useMemo(() => {
    const visibility = new Map((details?.layers ?? []).map(layer => [layer.layer_key, layer.visible]));
    return (details?.features ?? []).filter(feature => feature.enabled && visibility.get(feature.render_layer) !== false);
  }, [details]);

  if (!spaces.length) {
    return <div className="page">
      <header className="page-header"><p className="eyebrow">SPATIAL V3</p><h1>Map editor</h1><p>No branch-authoritative navigation spaces exist yet.</p></header>
      <Paper className="panel" sx={{ p: 2 }}>
        <h2>Start Spatial V3</h2>
        <p>The old map is no longer edited directly. Materialize it into surfaces, corridors, barriers, connectors and navigation spaces, or create a clean V3 space.</p>
        {migration && <pre style={{ maxHeight: 220, overflow: "auto" }}>{JSON.stringify(migration.counts ?? migration, null, 2)}</pre>}
        <Stack direction="row" spacing={1}>
          <Button variant="contained" onClick={() => void materializeLegacy()}>Materialize legacy map</Button>
          <Button onClick={() => { setCreateSpaceLocation(locations[0]?.id ?? ""); setCreateSpaceOpen(true); }}>Create blank space</Button>
        </Stack>
      </Paper>
      {renderCreateSpaceDialog()}
    </div>;
  }

  function renderCreateSpaceDialog() {
    return <Dialog open={createSpaceOpen} onClose={() => setCreateSpaceOpen(false)} maxWidth="sm" fullWidth>
      <DialogTitle>Create navigation space</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ mt: 1 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <TextField select fullWidth label="Semantic owner location" value={createSpaceLocation} onChange={event => setCreateSpaceLocation(event.target.value)}>
            {locations.map(location => <MenuItem key={location.id} value={location.id}>{location.name}</MenuItem>)}
          </TextField>
          <Button onClick={() => { setLocationAssignTarget("space"); setLocationNameDraft(""); setLocationDialogOpen(true); }}>New</Button>
        </Stack>
        <TextField select label="Navigation mode" value={createSpaceMode} onChange={event => setCreateSpaceMode(event.target.value as "free" | "routed")}>
          <MenuItem value="free">FREE — unassigned space is traversable</MenuItem>
          <MenuItem value="routed">ROUTED — only authored surfaces/corridors are traversable</MenuItem>
        </TextField>
      </Stack></DialogContent>
      <DialogActions><Button onClick={() => setCreateSpaceOpen(false)}>Cancel</Button><Button variant="contained" onClick={() => void createSpace()}>Create</Button></DialogActions>
    </Dialog>;
  }

  return <div className="page">
    <header className="page-header">
      <div><p className="eyebrow">SPATIAL V3</p><h1>Navigation map</h1><p>Semantic locations and traversal geometry are separate. Overlapping surfaces/corridors remain simultaneously active.</p></div>
    </header>

    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 2 }}>
      <TextField select size="small" label="Navigation space" value={spaceId} onChange={event => { setSpaceId(event.target.value); setSelectedFeatureId(null); }}>
        {spaces.map(space => <MenuItem key={space.id} value={space.id}>{locationName(world, space.owner_location_id)} · {space.navigation_mode}</MenuItem>)}
      </TextField>
      <Button onClick={() => { setCreateSpaceLocation(locations[0]?.id ?? ""); setCreateSpaceOpen(true); }}>New space</Button>
      <Button variant="outlined" onClick={() => openPreset()}>Apply preset</Button>
      {spaceDraft && <Chip label={spaceDraft.navigation_mode === "free" ? "FREE map" : "ROUTED map"} color={spaceDraft.navigation_mode === "free" ? "success" : "warning"}/>}
    </Stack>

    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 390px", gap: 16, alignItems: "start" }}>
      <Stack spacing={1.5}>
        <Paper className="panel" sx={{ p: 1.5 }}>
          <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
            <ButtonGroup size="small">
              {(["select", "edit", "surface", "corridor", "barrier", "spot", "connector"] as Tool[]).map(value =>
                <Button key={value} variant={tool === value ? "contained" : "outlined"} onClick={() => {
                  setTool(value);
                  if (value !== "corridor") setDraftTemplate(null);
                  setDraftPoints([]);
                }}>{value}</Button>
              )}
            </ButtonGroup>
            <Chip size="small" variant="outlined" label={
              tool === "select" ? "Select: V2 whole-object drag with visible bounds"
              : tool === "edit" ? "Edit: V2 vertex handles · midpoint adds point · right-click vertex menu · hold E + click to extrude"
              : `Drawing ${tool}`
            }/>
            {draftPoints.length > 0 && <>
              <Chip label={`${draftPoints.length} point${draftPoints.length === 1 ? "" : "s"}`}/>
              {(tool === "surface" && draftPoints.length >= 3 || (tool === "corridor" || tool === "barrier") && draftPoints.length >= 2) &&
                <Button variant="contained" onClick={() => void createFeature(tool as FeatureKind)}>Finish</Button>}
              <Button onClick={() => setDraftPoints([])}>Cancel drawing</Button>
            </>}
          </Stack>
        </Paper>

        <Paper className="panel" sx={{ p: 1, overflow: "hidden" }}>
          <SpatialV2Canvas
            features={visibleFeatures}
            tool={tool}
            selectedFeatureId={selectedFeatureId}
            draftPoints={draftPoints}
            onDraftPointsChange={setDraftPoints}
            onSelectFeature={id => setSelectedFeatureId(id)}
            onFeatureChange={feature => void persistCanvasFeature(feature as MapFeature)}
            onCreateFeature={(kind, points) => void createFeature(kind, points)}
            onConnectorPoint={point => {
              setConnectorPoint(point);
              setConnectorTargetSpace(spaces.find(item => item.id !== spaceId)?.id ?? spaceId);
              setConnectorTargetPoint(point);
            }}
          />
        </Paper>

        <Paper className="panel" sx={{ p: 2 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center"><h2 style={{ margin: 0 }}>Layers</h2><small>Rendering only; not feature types.</small></Stack>
          <Stack spacing={1} sx={{ mt: 1 }}>
            {(details?.layers ?? []).map(layer => <Stack key={layer.layer_key} direction="row" spacing={1} alignItems="center">
              <FormControlLabel control={<Switch checked={layer.visible} onChange={event => void saveLayer({ ...layer, visible: event.target.checked })}/>} label={layer.label}/>
              <TextField select size="small" label="Labels" value={layer.labels_mode} onChange={event => void saveLayer({ ...layer, labels_mode: event.target.value as LabelsMode })}>
                {(["hidden", "important", "all"] as LabelsMode[]).map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
              </TextField>
            </Stack>)}
          </Stack>
        </Paper>

        <Paper className="panel" sx={{ p: 2 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <div><h2 style={{ margin: 0 }}>Encounter policies</h2><small>Space or feature scoped; evaluated through Rules V2.</small></div>
            <Button onClick={() => setEncounterDraft({
              id: newId("encounter"), project_id: projectId, navigation_space_id: spaceId, feature_id: null,
              mode: "augment", priority: 0, trigger_kind: "distance", rate_per_100_units: 1,
              probability_per_transition: null, minimum_distance: 0, candidates: [], conditions: null, enabled: true,
            })}>Add</Button>
          </Stack>
          <Stack spacing={1} sx={{ mt: 1 }}>{(details?.encounter_policies ?? []).map(policy => <Paper key={policy.id} variant="outlined" sx={{ p: 1 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center"><div><b>{policy.id}</b><div><small>{policy.trigger_kind} · {policy.mode} · {policy.feature_id ? `feature ${policy.feature_id}` : "space"}</small></div></div><div><Button size="small" onClick={() => setEncounterDraft(structuredClone(policy))}>Edit</Button><Button size="small" color="error" onClick={() => void deleteEncounter(policy)}>Delete</Button></div></Stack>
          </Paper>)}</Stack>
        </Paper>
      </Stack>

      <Stack spacing={1.5}>
        {spaceDraft && <Paper className="panel" sx={{ p: 2 }}>
          <h2>Space</h2>
          <TextField select fullWidth size="small" label="Semantic owner" value={spaceDraft.owner_location_id ?? ""} onChange={event => setSpaceDraft({ ...spaceDraft, owner_location_id: event.target.value || null })}>
            <MenuItem value="">None</MenuItem>{locations.map(location => <MenuItem key={location.id} value={location.id}>{location.name}</MenuItem>)}
          </TextField>
          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
            <TextField select fullWidth size="small" label="Mode" value={spaceDraft.navigation_mode} onChange={event => setSpaceDraft({ ...spaceDraft, navigation_mode: event.target.value as "free" | "routed" })}>
              <MenuItem value="free">FREE</MenuItem><MenuItem value="routed">ROUTED</MenuItem>
            </TextField>
            <TextField fullWidth size="small" type="number" label="Base travel multiplier" value={spaceDraft.base_travel_multiplier} onChange={event => setSpaceDraft({ ...spaceDraft, base_travel_multiplier: Math.max(.01, Number(event.target.value) || 1) })}/>
          </Stack>
          <Button sx={{ mt: 1 }} variant="contained" onClick={() => void saveSpace()}>Save space</Button>
        </Paper>}

        {featureDraft ? <Paper className="panel" sx={{ p: 2 }}>
          <Stack direction="row" justifyContent="space-between"><div><p className="eyebrow">{featureDraft.feature_kind}</p><h2>{featureDraft.name || featureDraft.id}</h2></div><Button color="error" onClick={() => void deleteFeature()}>Delete</Button></Stack>
          <Stack spacing={1.2}>
            <TextField size="small" label="Name" value={featureDraft.name} onChange={event => setFeatureDraft({ ...featureDraft, name: event.target.value })}/>
            <Stack direction="row" spacing={1} alignItems="center">
              <TextField select fullWidth size="small" label="Semantic location" value={featureDraft.semantic_location_id ?? ""} onChange={event => setFeatureDraft({ ...featureDraft, semantic_location_id: event.target.value || null })}>
                <MenuItem value="">None</MenuItem>{locations.map(location => <MenuItem key={location.id} value={location.id}>{location.name}</MenuItem>)}
              </TextField>
              <Button size="small" onClick={() => { setLocationAssignTarget("feature"); setLocationNameDraft(featureDraft.name || ""); setLocationDialogOpen(true); }}>New + assign</Button>
            </Stack>
            <Stack direction="row" spacing={1}>
              <TextField select fullWidth size="small" label="Render layer" value={featureDraft.render_layer} onChange={event => setFeatureDraft({ ...featureDraft, render_layer: event.target.value as RenderLayer })}>{renderLayers.map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField>
              <TextField fullWidth size="small" type="number" label="Render order" value={featureDraft.render_order} onChange={event => setFeatureDraft({ ...featureDraft, render_order: Number(event.target.value) })}/>
            </Stack>
            <TextField size="small" type="number" label="Movement priority" value={featureDraft.movement_priority} onChange={event => setFeatureDraft({ ...featureDraft, movement_priority: Number(event.target.value) })}/>
            <Stack direction="row" flexWrap="wrap">
              <FormControlLabel control={<Switch checked={featureDraft.enabled} onChange={event => setFeatureDraft({ ...featureDraft, enabled: event.target.checked })}/>} label="Enabled"/>
              <FormControlLabel control={<Switch checked={featureDraft.discovered} onChange={event => setFeatureDraft({ ...featureDraft, discovered: event.target.checked })}/>} label="Discovered"/>
              <FormControlLabel control={<Switch checked={featureDraft.hidden} onChange={event => setFeatureDraft({ ...featureDraft, hidden: event.target.checked })}/>} label="Hidden"/>
            </Stack>

            {featureDraft.feature_kind === "corridor" && <TextField size="small" type="number" label="Width" value={featureDraft.properties.width ?? 4} onChange={event => setFeatureDraft({ ...featureDraft, properties: { ...featureDraft.properties, width: Math.max(.1, Number(event.target.value) || 1) } })}/>}
            {(featureDraft.feature_kind === "surface" || featureDraft.feature_kind === "corridor") && <TextField size="small" label="Ambience tags" value={formatCsv(featureDraft.properties.ambience_tags)} onChange={event => setFeatureDraft({ ...featureDraft, properties: { ...featureDraft.properties, ambience_tags: parseCsv(event.target.value) } })}/>}
            {featureDraft.feature_kind === "surface" && <TextField size="small" label="Environment tags" value={formatCsv(featureDraft.properties.environment_tags)} onChange={event => setFeatureDraft({ ...featureDraft, properties: { ...featureDraft.properties, environment_tags: parseCsv(event.target.value) } })}/>}
            {featureDraft.feature_kind === "spot" && <TextField size="small" label="Interaction kind" value={featureDraft.properties.interaction_kind ?? "generic"} onChange={event => setFeatureDraft({ ...featureDraft, properties: { ...featureDraft.properties, interaction_kind: event.target.value } })}/>}
            {featureDraft.feature_kind === "connector" && <>
              <TextField select size="small" label="Connector kind" value={featureDraft.properties.connector_kind ?? "generic"} onChange={event => setFeatureDraft({ ...featureDraft, properties: { ...featureDraft.properties, connector_kind: event.target.value } })}>{connectorKinds.map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField>
              <TextField select size="small" label="Target space" value={featureDraft.properties.target?.navigation_space_id ?? ""} onChange={event => setFeatureDraft({ ...featureDraft, properties: { ...featureDraft.properties, target: { ...featureDraft.properties.target, navigation_space_id: event.target.value } } })}>{spaces.map(space => <MenuItem key={space.id} value={space.id}>{locationName(world, space.owner_location_id)}</MenuItem>)}</TextField>
              <Stack direction="row" spacing={1}><TextField size="small" type="number" label="Target X" value={featureDraft.properties.target?.point?.[0] ?? 0} onChange={event => setFeatureDraft({ ...featureDraft, properties: { ...featureDraft.properties, target: { ...featureDraft.properties.target, point: [Number(event.target.value), featureDraft.properties.target?.point?.[1] ?? 0] } } })}/><TextField size="small" type="number" label="Target Y" value={featureDraft.properties.target?.point?.[1] ?? 0} onChange={event => setFeatureDraft({ ...featureDraft, properties: { ...featureDraft.properties, target: { ...featureDraft.properties.target, point: [featureDraft.properties.target?.point?.[0] ?? 0, Number(event.target.value)] } } })}/></Stack>
              <TextField size="small" type="number" label="Travel minutes override" value={featureDraft.properties.travel_minutes ?? ""} onChange={event => setFeatureDraft({ ...featureDraft, properties: { ...featureDraft.properties, travel_minutes: event.target.value === "" ? null : Math.max(0, Number(event.target.value)) } })}/>
              <FormControlLabel control={<Switch checked={featureDraft.properties.bidirectional !== false} onChange={event => setFeatureDraft({ ...featureDraft, properties: { ...featureDraft.properties, bidirectional: event.target.checked } })}/>} label="Bidirectional"/>
            </>}
            {traversalOf(featureDraft) && <TraversalEditor value={traversalOf(featureDraft)!} stats={ruleData.stats} abilities={ruleData.abilities} locations={locations.map(item => ({ id: item.id, name: item.name }))} onChange={traversal => setFeatureDraft({ ...featureDraft, properties: { ...featureDraft.properties, traversal } })}/>}
            <Button variant="contained" onClick={() => void saveFeature()}>Save feature</Button>
            {featureDraft.semantic_location_id && !spaces.some(space => space.owner_location_id === featureDraft.semantic_location_id) && <Button onClick={() => { setCreateSpaceLocation(featureDraft.semantic_location_id!); setCreateSpaceMode("routed"); setCreateSpaceOpen(true); }}>Create ROUTED interior for this location</Button>}
          </Stack>
        </Paper> : <Paper className="panel" sx={{ p: 2 }}><h2>Feature inspector</h2><p>Select a feature on the map, or choose a drawing tool.</p><ul><li><b>Surface:</b> area membership / terrain / building footprint.</li><li><b>Corridor:</b> thick traversable route such as road, alley, river or hall.</li><li><b>Barrier:</b> crossing blocker such as a wall or cliff.</li><li><b>Connector:</b> door, gate, bridge, stairs or portal between spaces.</li><li><b>Spot:</b> landmark or interaction point.</li></ul></Paper>}
      </Stack>
    </div>

    <Dialog open={presetOpen} onClose={() => setPresetOpen(false)} maxWidth="md" fullWidth>
      <DialogTitle>Apply Spatial V3 preset</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ mt: 1 }}>
        <TextField select label="Preset" value={presetKey} onChange={event => {
          const key = event.target.value;
          setPresetKey(key);
          setPresetParams({
            ...presetDefaults(key),
            semantic_location_id: spaces.find(item => item.id === spaceId)?.owner_location_id ?? "",
            target_space_id: spaces.find(item => item.id !== spaceId)?.id ?? "",
          });
        }}>
          {presets.map(preset => <MenuItem key={preset.key} value={preset.key}>{preset.label}</MenuItem>)}
        </TextField>
        {presets.find(item => item.key === presetKey) && <Alert severity="info">{presets.find(item => item.key === presetKey)!.description}</Alert>}
        {presets.find(item => item.key === presetKey)?.parameters.includes("name") && <TextField label="Name" value={presetParams.name} onChange={event => setPresetParams({ ...presetParams, name: event.target.value })}/>}
        {presets.find(item => item.key === presetKey)?.parameters.includes("semantic_location_id") && <TextField select label="Semantic location" value={presetParams.semantic_location_id} onChange={event => setPresetParams({ ...presetParams, semantic_location_id: event.target.value })}>
          <MenuItem value="">Use space owner / none</MenuItem>
          {locations.map(location => <MenuItem key={location.id} value={location.id}>{location.name}</MenuItem>)}
        </TextField>}
        {(presets.find(item => item.key === presetKey)?.parameters.includes("center_x") || presets.find(item => item.key === presetKey)?.parameters.includes("center_y")) && <Stack direction="row" spacing={1}>
          {presets.find(item => item.key === presetKey)?.parameters.includes("center_x") && <TextField fullWidth type="number" label="Center X" value={presetParams.center_x} onChange={event => setPresetParams({ ...presetParams, center_x: Number(event.target.value) })}/>}
          {presets.find(item => item.key === presetKey)?.parameters.includes("center_y") && <TextField fullWidth type="number" label="Center Y" value={presetParams.center_y} onChange={event => setPresetParams({ ...presetParams, center_y: Number(event.target.value) })}/>}
        </Stack>}
        {(presets.find(item => item.key === presetKey)?.parameters.includes("width") || presets.find(item => item.key === presetKey)?.parameters.includes("height")) && <Stack direction="row" spacing={1}>
          {presets.find(item => item.key === presetKey)?.parameters.includes("width") && <TextField fullWidth type="number" label={presetKey === "road" || presetKey === "river" ? "Corridor width" : "Width"} value={presetParams.width} onChange={event => setPresetParams({ ...presetParams, width: Math.max(.1, Number(event.target.value)) })}/>}
          {presets.find(item => item.key === presetKey)?.parameters.includes("height") && <TextField fullWidth type="number" label="Height" value={presetParams.height} onChange={event => setPresetParams({ ...presetParams, height: Math.max(1, Number(event.target.value)) })}/>}
        </Stack>}
        {presets.find(item => item.key === presetKey)?.parameters.includes("target_space_id") && <TextField select label="Target navigation space" value={presetParams.target_space_id} onChange={event => setPresetParams({ ...presetParams, target_space_id: event.target.value })}>
          {spaces.filter(item => item.id !== spaceId).map(space => <MenuItem key={space.id} value={space.id}>{locationName(world, space.owner_location_id)} · {space.navigation_mode}</MenuItem>)}
        </TextField>}
        {(presets.find(item => item.key === presetKey)?.parameters.includes("target_x") || presets.find(item => item.key === presetKey)?.parameters.includes("target_y")) && <Stack direction="row" spacing={1}>
          <TextField fullWidth type="number" label="Target X" value={presetParams.target_x} onChange={event => setPresetParams({ ...presetParams, target_x: Number(event.target.value) })}/>
          <TextField fullWidth type="number" label="Target Y" value={presetParams.target_y} onChange={event => setPresetParams({ ...presetParams, target_y: Number(event.target.value) })}/>
        </Stack>}
        {presets.find(item => item.key === presetKey)?.requires_semantic_location && !presetParams.semantic_location_id && <Alert severity="warning">This preset requires a semantic location.</Alert>}
        {presets.find(item => item.key === presetKey)?.requires_target_space && !presetParams.target_space_id && <Alert severity="warning">This preset requires another navigation space.</Alert>}
      </Stack></DialogContent>
      <DialogActions>
        <Button onClick={() => setPresetOpen(false)}>Cancel</Button>
        <Button variant="contained" disabled={
          Boolean(presets.find(item => item.key === presetKey)?.requires_semantic_location && !presetParams.semantic_location_id)
          || Boolean(presets.find(item => item.key === presetKey)?.requires_target_space && !presetParams.target_space_id)
        } onClick={() => void applyPreset()}>Apply preset</Button>
      </DialogActions>
    </Dialog>

    {renderCreateSpaceDialog()}

    <Dialog open={locationDialogOpen} onClose={() => setLocationDialogOpen(false)} maxWidth="sm" fullWidth>
      <DialogTitle>Create location</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ mt: 1 }}>
        <TextField autoFocus label="Location name" value={locationNameDraft} onChange={event => setLocationNameDraft(event.target.value)} onKeyDown={event => { if (event.key === "Enter") void createLocationFromMap(); }}/>
        <Alert severity="info">{locationAssignTarget === "feature" ? "The new semantic location will be assigned to the selected map feature." : "The new location will become the owner of the navigation space you create."}</Alert>
      </Stack></DialogContent>
      <DialogActions><Button onClick={() => setLocationDialogOpen(false)}>Cancel</Button><Button variant="contained" disabled={!locationNameDraft.trim()} onClick={() => void createLocationFromMap()}>Create & assign</Button></DialogActions>
    </Dialog>

    <Dialog open={Boolean(connectorPoint)} onClose={() => setConnectorPoint(null)} maxWidth="sm" fullWidth>
      <DialogTitle>Create connector</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ mt: 1 }}>
        <Alert severity="info">Source is {connectorPoint?.join(", ")} in {locationName(world, spaces.find(item => item.id === spaceId)?.owner_location_id)}.</Alert>
        <TextField select label="Target space" value={connectorTargetSpace} onChange={event => setConnectorTargetSpace(event.target.value)}>{spaces.map(space => <MenuItem key={space.id} value={space.id}>{locationName(world, space.owner_location_id)} · {space.navigation_mode}</MenuItem>)}</TextField>
        <Stack direction="row" spacing={1}><TextField fullWidth type="number" label="Target X" value={connectorTargetPoint[0]} onChange={event => setConnectorTargetPoint([Number(event.target.value), connectorTargetPoint[1]])}/><TextField fullWidth type="number" label="Target Y" value={connectorTargetPoint[1]} onChange={event => setConnectorTargetPoint([connectorTargetPoint[0], Number(event.target.value)])}/></Stack>
      </Stack></DialogContent>
      <DialogActions><Button onClick={() => setConnectorPoint(null)}>Cancel</Button><Button variant="contained" onClick={() => void createConnector()}>Create</Button></DialogActions>
    </Dialog>

    <Dialog open={Boolean(encounterDraft)} onClose={() => setEncounterDraft(null)} maxWidth="md" fullWidth>
      <DialogTitle>Encounter policy</DialogTitle>
      <DialogContent>{encounterDraft && <Stack spacing={1.5} sx={{ mt: 1 }}>
        <Stack direction="row" spacing={1}>
          <TextField select fullWidth label="Target" value={encounterDraft.feature_id ? "feature" : "space"} onChange={event => setEncounterDraft(event.target.value === "space" ? { ...encounterDraft, navigation_space_id: spaceId, feature_id: null } : { ...encounterDraft, navigation_space_id: null, feature_id: details?.features[0]?.id ?? null })}><MenuItem value="space">Navigation space</MenuItem><MenuItem value="feature">Feature</MenuItem></TextField>
          {encounterDraft.feature_id != null && <TextField select fullWidth label="Feature" value={encounterDraft.feature_id} onChange={event => setEncounterDraft({ ...encounterDraft, feature_id: event.target.value })}>{(details?.features ?? []).map(feature => <MenuItem key={feature.id} value={feature.id}>{feature.name || feature.id} · {feature.feature_kind}</MenuItem>)}</TextField>}
        </Stack>
        <Stack direction="row" spacing={1}>
          <TextField select fullWidth label="Mode" value={encounterDraft.mode} onChange={event => setEncounterDraft({ ...encounterDraft, mode: event.target.value as EncounterPolicy["mode"] })}>{["augment", "replace", "disabled"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField>
          <TextField select fullWidth label="Trigger" value={encounterDraft.trigger_kind} onChange={event => setEncounterDraft({ ...encounterDraft, trigger_kind: event.target.value as EncounterPolicy["trigger_kind"], probability_per_transition: event.target.value === "transition" ? (encounterDraft.probability_per_transition ?? 1) : null })}><MenuItem value="distance">Distance</MenuItem><MenuItem value="transition">Transition</MenuItem></TextField>
          <TextField fullWidth type="number" label="Priority" value={encounterDraft.priority} onChange={event => setEncounterDraft({ ...encounterDraft, priority: Number(event.target.value) })}/>
        </Stack>
        {encounterDraft.trigger_kind === "distance" ? <Stack direction="row" spacing={1}><TextField fullWidth type="number" label="Rate / 100 units" value={encounterDraft.rate_per_100_units} onChange={event => setEncounterDraft({ ...encounterDraft, rate_per_100_units: Math.max(0, Number(event.target.value)) })}/><TextField fullWidth type="number" label="Minimum distance" value={encounterDraft.minimum_distance} onChange={event => setEncounterDraft({ ...encounterDraft, minimum_distance: Math.max(0, Number(event.target.value)) })}/></Stack> : <TextField type="number" label="Probability per transition (0–1)" value={encounterDraft.probability_per_transition ?? 1} onChange={event => setEncounterDraft({ ...encounterDraft, probability_per_transition: Math.max(0, Math.min(1, Number(event.target.value))) })}/>}
        <div>
          <h3>Policy condition</h3>
          {encounterDraft.conditions
            ? <ConditionExpressionEditor node={conditionExpressionFromPayload(encounterDraft.conditions as Record<string, unknown>, ruleData.stats)} stats={ruleData.stats} abilities={ruleData.abilities} locations={locations.map(item => ({ id: item.id, name: item.name }))} onChange={conditions => setEncounterDraft({ ...encounterDraft, conditions })} onRemove={() => setEncounterDraft({ ...encounterDraft, conditions: null })}/>
            : <Button onClick={() => setEncounterDraft({ ...encounterDraft, conditions: blankConditionExpression("compare", ruleData.stats) })}>Add condition</Button>}
        </div>
        <h3>Candidates</h3>
        {encounterDraft.candidates.map((candidate, index) => <Paper key={index} variant="outlined" sx={{ p: 1 }}>
          <Stack direction="row" spacing={1}>
            <TextField select fullWidth label="Encounter location" value={candidate.location_id} onChange={event => setEncounterDraft({ ...encounterDraft, candidates: encounterDraft.candidates.map((item, itemIndex) => itemIndex === index ? { ...item, location_id: event.target.value } : item) })}>{locations.map(location => <MenuItem key={location.id} value={location.id}>{location.name}</MenuItem>)}</TextField>
            <TextField type="number" label="Weight" value={candidate.weight} onChange={event => setEncounterDraft({ ...encounterDraft, candidates: encounterDraft.candidates.map((item, itemIndex) => itemIndex === index ? { ...item, weight: Math.max(.01, Number(event.target.value) || 1) } : item) })}/>
            <Button color="error" onClick={() => setEncounterDraft({ ...encounterDraft, candidates: encounterDraft.candidates.filter((_, itemIndex) => itemIndex !== index) })}>Remove</Button>
          </Stack>
          <div style={{ marginTop: 8 }}>
            {candidate.requirements
              ? <ConditionExpressionEditor node={conditionExpressionFromPayload(candidate.requirements as Record<string, unknown>, ruleData.stats)} stats={ruleData.stats} abilities={ruleData.abilities} locations={locations.map(item => ({ id: item.id, name: item.name }))} onChange={requirements => setEncounterDraft({ ...encounterDraft, candidates: encounterDraft.candidates.map((item, itemIndex) => itemIndex === index ? { ...item, requirements } : item) })} onRemove={() => setEncounterDraft({ ...encounterDraft, candidates: encounterDraft.candidates.map((item, itemIndex) => itemIndex === index ? { ...item, requirements: null } : item) })}/>
              : <Button size="small" onClick={() => setEncounterDraft({ ...encounterDraft, candidates: encounterDraft.candidates.map((item, itemIndex) => itemIndex === index ? { ...item, requirements: blankConditionExpression("compare", ruleData.stats) } : item) })}>Add requirement</Button>}
          </div>
        </Paper>)}
        <Button onClick={() => setEncounterDraft({ ...encounterDraft, candidates: [...encounterDraft.candidates, { location_id: locations[0]?.id ?? "", weight: 1, requirements: null }] })}>Add candidate</Button>
        <FormControlLabel control={<Switch checked={encounterDraft.enabled} onChange={event => setEncounterDraft({ ...encounterDraft, enabled: event.target.checked })}/>} label="Enabled"/>
      </Stack>}</DialogContent>
      <DialogActions><Button onClick={() => setEncounterDraft(null)}>Cancel</Button><Button variant="contained" onClick={() => void saveEncounter()}>Save</Button></DialogActions>
    </Dialog>
  </div>;
}
