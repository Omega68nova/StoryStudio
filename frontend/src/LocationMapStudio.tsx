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
import type { WorkflowPreset, WorldEntity, WorldProjection } from "./types";

type Point = [number, number];
type Tool = "select" | "surface" | "corridor" | "barrier" | "spot" | "connector";
type FeatureKind = Exclude<Tool, "select">;
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

const renderLayers: RenderLayer[] = ["topology", "regions", "roads", "places", "barriers", "connections"];
const connectorKinds = ["generic", "door", "gate", "stairs", "ladder", "bridge", "climb", "portal"] as const;
const emptyTraversal = (allowed = true): TraversalPolicy => ({ default_allowed: allowed, travel_multiplier: 1, options: [] });
const newId = (prefix: string) => `${prefix}-${crypto.randomUUID()}`;
const round = (value: number) => Math.round(value * 10) / 10;
const parseCsv = (value: string) => value.split(",").map(item => item.trim()).filter(Boolean);
const formatCsv = (value: unknown) => Array.isArray(value) ? value.join(", ") : "";
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

function featurePoints(feature: MapFeature): Point[] {
  if (feature.geometry.type === "Point") return [feature.geometry.coordinates];
  if (feature.geometry.type === "LineString") return feature.geometry.coordinates;
  if (feature.geometry.type === "Polygon") return feature.geometry.coordinates[0] ?? [];
  if (feature.geometry.type === "MultiLineString") return feature.geometry.coordinates.flat();
  return feature.geometry.coordinates.flat(2) as Point[];
}

function JsonConditionField({
  label,
  value,
  onChange,
}: {
  label: string;
  value?: Record<string, unknown> | null;
  onChange: (value: Record<string, unknown> | null) => void;
}) {
  const [text, setText] = useState(value ? JSON.stringify(value, null, 2) : "");
  useEffect(() => setText(value ? JSON.stringify(value, null, 2) : ""), [value]);
  return <TextField
    fullWidth
    multiline
    minRows={3}
    label={label}
    value={text}
    helperText="Rules V2 condition JSON. Leave blank for unconditional."
    onChange={event => setText(event.target.value)}
    onBlur={() => {
      if (!text.trim()) return onChange(null);
      try { onChange(JSON.parse(text) as Record<string, unknown>); } catch { /* keep draft for correction */ }
    }}
  />;
}

function TraversalEditor({
  value,
  onChange,
}: {
  value: TraversalPolicy;
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
      <JsonConditionField label="Requirements" value={option.requirements} onChange={requirements => onChange({ ...value, options: value.options.map((item, itemIndex) => itemIndex === index ? { ...item, requirements } : item) })}/>
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
  const [encounterDraft, setEncounterDraft] = useState<EncounterPolicy | null>(null);
  const [vertexDrag, setVertexDrag] = useState<number | null>(null);

  const locations = useMemo(
    () => Object.values(world?.entities ?? {}).filter((item: WorldEntity) => item.kind === "location" && !item.state.archived),
    [world],
  );

  const loadSpaces = useCallback(async () => {
    const [nextWorld, nextSpaces] = await Promise.all([
      api<WorldProjection>(`/projects/${projectId}/world`),
      api<NavigationSpace[]>(`/projects/${projectId}/spatial-v3/spaces`),
    ]);
    setWorld(nextWorld);
    setSpaces(nextSpaces);
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

  function canvasPoint(clientX: number, clientY: number, element: SVGSVGElement): Point {
    const rect = element.getBoundingClientRect();
    return [
      round(((clientX - rect.left) / rect.width) * 100),
      round(((clientY - rect.top) / rect.height) * 100),
    ];
  }

  function updateFeatureVertex(index: number, point: Point) {
    if (!featureDraft) return;
    const geometry = structuredClone(featureDraft.geometry);
    if (geometry.type === "Point") geometry.coordinates = point;
    else if (geometry.type === "LineString") geometry.coordinates[index] = point;
    else if (geometry.type === "Polygon") {
      const ring = geometry.coordinates[0];
      if (!ring?.length) return;
      ring[index] = point;
      if (index === 0) ring[ring.length - 1] = point;
    } else return;
    setFeatureDraft({ ...featureDraft, geometry });
  }

  function canvasPointerMove(event: React.PointerEvent<SVGSVGElement>) {
    if (vertexDrag == null) return;
    updateFeatureVertex(vertexDrag, canvasPoint(event.clientX, event.clientY, event.currentTarget));
  }

  function canvasClick(event: React.MouseEvent<SVGSVGElement>) {
    if (tool === "select") return;
    const point = canvasPoint(event.clientX, event.clientY, event.currentTarget);
    if (tool === "spot") {
      void createFeature("spot", [point]);
      return;
    }
    if (tool === "connector") {
      setConnectorPoint(point);
      setConnectorTargetSpace(spaces.find(item => item.id !== spaceId)?.id ?? spaceId);
      setConnectorTargetPoint(point);
      return;
    }
    setDraftPoints(points => [...points, point]);
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
      semantic_location_id: null,
      feature_kind: kind,
      name: kind[0].toUpperCase() + kind.slice(1),
      geometry,
      render_layer: defaultLayer(kind),
      render_order: 0,
      movement_priority: kind === "corridor" ? 10 : 0,
      hidden: false,
      discovered: true,
      enabled: true,
      metadata: {},
      properties,
    };
    try {
      await api(`/projects/${projectId}/spatial-v3/features/${id}`, { method: "PUT", body: JSON.stringify(feature) });
      setDraftPoints([]);
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
        <TextField select label="Semantic owner location" value={createSpaceLocation} onChange={event => setCreateSpaceLocation(event.target.value)}>
          {locations.map(location => <MenuItem key={location.id} value={location.id}>{location.name}</MenuItem>)}
        </TextField>
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
      {spaceDraft && <Chip label={spaceDraft.navigation_mode === "free" ? "FREE map" : "ROUTED map"} color={spaceDraft.navigation_mode === "free" ? "success" : "warning"}/>}
    </Stack>

    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 390px", gap: 16, alignItems: "start" }}>
      <Stack spacing={1.5}>
        <Paper className="panel" sx={{ p: 1.5 }}>
          <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
            <ButtonGroup size="small">
              {(["select", "surface", "corridor", "barrier", "spot", "connector"] as Tool[]).map(value =>
                <Button key={value} variant={tool === value ? "contained" : "outlined"} onClick={() => { setTool(value); setDraftPoints([]); }}>{value}</Button>
              )}
            </ButtonGroup>
            {draftPoints.length > 0 && <>
              <Chip label={`${draftPoints.length} point${draftPoints.length === 1 ? "" : "s"}`}/>
              {(tool === "surface" && draftPoints.length >= 3 || (tool === "corridor" || tool === "barrier") && draftPoints.length >= 2) &&
                <Button variant="contained" onClick={() => void createFeature(tool as FeatureKind)}>Finish</Button>}
              <Button onClick={() => setDraftPoints([])}>Cancel drawing</Button>
            </>}
          </Stack>
        </Paper>

        <Paper className="panel" sx={{ p: 1, overflow: "hidden" }}>
          <svg
            viewBox="0 0 100 100"
            onClick={canvasClick}
            onPointerMove={canvasPointerMove}
            onPointerUp={() => setVertexDrag(null)}
            onPointerLeave={() => setVertexDrag(null)}
            style={{ width: "100%", aspectRatio: "1.6", background: "var(--surface, #16191f)", cursor: vertexDrag != null ? "grabbing" : tool === "select" ? "default" : "crosshair", display: "block", touchAction: "none" }}
          >
            <defs>
              <pattern id="v3grid" width="5" height="5" patternUnits="userSpaceOnUse"><path d="M 5 0 L 0 0 0 5" fill="none" stroke="currentColor" strokeOpacity=".08" strokeWidth=".2"/></pattern>
            </defs>
            <rect width="100" height="100" fill="url(#v3grid)"/>
            {visibleFeatures.map(feature => {
              const selected = feature.id === selectedFeatureId;
              const rendered = selected && featureDraft ? featureDraft : feature;
              const common = { onClick: (event: React.MouseEvent) => { event.stopPropagation(); setTool("select"); setSelectedFeatureId(feature.id); } };
              if (rendered.geometry.type === "Polygon") {
                const points = (rendered.geometry.coordinates[0] ?? []).map(point => point.join(",")).join(" ");
                return <polygon key={feature.id} {...common} points={points} fill={selected ? "rgba(255,255,255,.24)" : "rgba(255,255,255,.11)"} stroke="currentColor" strokeWidth={selected ? .8 : .35}/>;
              }
              if (rendered.geometry.type === "LineString") {
                const points = rendered.geometry.coordinates.map(point => point.join(",")).join(" ");
                const width = rendered.feature_kind === "corridor" ? Math.max(.8, Number(rendered.properties.width ?? 4)) : rendered.feature_kind === "barrier" ? 1 : .7;
                return <polyline key={feature.id} {...common} points={points} fill="none" stroke="currentColor" strokeOpacity={selected ? 1 : .7} strokeWidth={selected ? width + .5 : width} strokeLinecap="round" strokeLinejoin="round"/>;
              }
              if (rendered.geometry.type === "Point") {
                const [x, y] = rendered.geometry.coordinates;
                return <g key={feature.id} {...common}><circle cx={x} cy={y} r={selected ? 2.1 : 1.5} fill="currentColor"/>{rendered.name && <text x={x + 2} y={y - 2} fontSize="2.2" fill="currentColor">{rendered.name}</text>}</g>;
              }
              return null;
            })}
            {featureDraft && featureDraft.geometry.type !== "MultiLineString" && featureDraft.geometry.type !== "MultiPolygon" && featurePoints(featureDraft)
              .filter((_point, index) => featureDraft.geometry.type !== "Polygon" || index < featurePoints(featureDraft).length - 1)
              .map((point, index) => <circle
                key={`handle-${index}`}
                cx={point[0]}
                cy={point[1]}
                r="1.15"
                fill="var(--background, #111)"
                stroke="currentColor"
                strokeWidth=".45"
                style={{ cursor: "grab" }}
                onClick={event => event.stopPropagation()}
                onPointerDown={event => { event.stopPropagation(); (event.currentTarget as SVGCircleElement).setPointerCapture(event.pointerId); setVertexDrag(index); }}
              />)}
            {draftPoints.length > 0 && <>
              <polyline points={draftPoints.map(point => point.join(",")).join(" ")} fill={tool === "surface" ? "rgba(255,255,255,.08)" : "none"} stroke="currentColor" strokeDasharray="1 1" strokeWidth=".5"/>
              {draftPoints.map((point, index) => <circle key={index} cx={point[0]} cy={point[1]} r=".8" fill="currentColor"/>)}
            </>}
          </svg>
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
            <TextField select size="small" label="Semantic location" value={featureDraft.semantic_location_id ?? ""} onChange={event => setFeatureDraft({ ...featureDraft, semantic_location_id: event.target.value || null })}>
              <MenuItem value="">None</MenuItem>{locations.map(location => <MenuItem key={location.id} value={location.id}>{location.name}</MenuItem>)}
            </TextField>
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
            {traversalOf(featureDraft) && <TraversalEditor value={traversalOf(featureDraft)!} onChange={traversal => setFeatureDraft({ ...featureDraft, properties: { ...featureDraft.properties, traversal } })}/>}
            <Button variant="contained" onClick={() => void saveFeature()}>Save feature</Button>
            {featureDraft.semantic_location_id && !spaces.some(space => space.owner_location_id === featureDraft.semantic_location_id) && <Button onClick={() => { setCreateSpaceLocation(featureDraft.semantic_location_id!); setCreateSpaceMode("routed"); setCreateSpaceOpen(true); }}>Create ROUTED interior for this location</Button>}
          </Stack>
        </Paper> : <Paper className="panel" sx={{ p: 2 }}><h2>Feature inspector</h2><p>Select a feature on the map, or choose a drawing tool.</p><ul><li><b>Surface:</b> area membership / terrain / building footprint.</li><li><b>Corridor:</b> thick traversable route such as road, alley, river or hall.</li><li><b>Barrier:</b> crossing blocker such as a wall or cliff.</li><li><b>Connector:</b> door, gate, bridge, stairs or portal between spaces.</li><li><b>Spot:</b> landmark or interaction point.</li></ul></Paper>}
      </Stack>
    </div>

    {renderCreateSpaceDialog()}

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
        <JsonConditionField label="Policy condition" value={encounterDraft.conditions} onChange={conditions => setEncounterDraft({ ...encounterDraft, conditions })}/>
        <h3>Candidates</h3>
        {encounterDraft.candidates.map((candidate, index) => <Paper key={index} variant="outlined" sx={{ p: 1 }}>
          <Stack direction="row" spacing={1}>
            <TextField select fullWidth label="Encounter location" value={candidate.location_id} onChange={event => setEncounterDraft({ ...encounterDraft, candidates: encounterDraft.candidates.map((item, itemIndex) => itemIndex === index ? { ...item, location_id: event.target.value } : item) })}>{locations.map(location => <MenuItem key={location.id} value={location.id}>{location.name}</MenuItem>)}</TextField>
            <TextField type="number" label="Weight" value={candidate.weight} onChange={event => setEncounterDraft({ ...encounterDraft, candidates: encounterDraft.candidates.map((item, itemIndex) => itemIndex === index ? { ...item, weight: Math.max(.01, Number(event.target.value) || 1) } : item) })}/>
            <Button color="error" onClick={() => setEncounterDraft({ ...encounterDraft, candidates: encounterDraft.candidates.filter((_, itemIndex) => itemIndex !== index) })}>Remove</Button>
          </Stack>
          <JsonConditionField label="Candidate requirement" value={candidate.requirements} onChange={requirements => setEncounterDraft({ ...encounterDraft, candidates: encounterDraft.candidates.map((item, itemIndex) => itemIndex === index ? { ...item, requirements } : item) })}/>
        </Paper>)}
        <Button onClick={() => setEncounterDraft({ ...encounterDraft, candidates: [...encounterDraft.candidates, { location_id: locations[0]?.id ?? "", weight: 1, requirements: null }] })}>Add candidate</Button>
        <FormControlLabel control={<Switch checked={encounterDraft.enabled} onChange={event => setEncounterDraft({ ...encounterDraft, enabled: event.target.checked })}/>} label="Enabled"/>
      </Stack>}</DialogContent>
      <DialogActions><Button onClick={() => setEncounterDraft(null)}>Cancel</Button><Button variant="contained" onClick={() => void saveEncounter()}>Save</Button></DialogActions>
    </Dialog>
  </div>;
}
