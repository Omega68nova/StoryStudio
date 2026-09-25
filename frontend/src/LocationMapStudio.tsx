import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent, PointerEvent as ReactPointerEvent } from "react";
import {
  Button,
  ButtonGroup,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Menu,
  MenuItem,
  Paper,
  Switch,
  TextField,
} from "@mui/material";
import { api } from "./api";
import { FavoriteLibraryButton } from "./FavoriteLibraryButton";
import { EntityImageSurface } from "./customComponents/EntityImageSurface";
import type {
  EnvironmentLocation,
  EnvironmentSettings,
  MediaAsset,
  WorldEntity,
  WorldProjection,
} from "./types";

type Tool = "select" | "drag" | "spot" | "area" | "route" | "edit";
type Point = { x: number; y: number };
type Geometry = { location_id?: string; kind?: "point" | "polyline" | "polygon"; points?: Point[] };
type SpatialLocation = {
  id: string;
  name: string;
  parent_location_id?: string | null;
  topology?: string;
  occupancy?: string;
  boundary_access?: string;
  spatial_kind?: string;
  priority_layer?: number;
  x?: number | null;
  y?: number | null;
  discovered?: boolean;
};
type SpatialAnchor = {
  id: string;
  location_id: string;
  coordinate_space_id?: string | null;
  binding_kind?: "coordinate" | "area" | "area_border" | "spot";
  binding_target_id?: string | null;
  binding_offset_x?: number | null;
  binding_offset_y?: number | null;
  binding_segment_index?: number | null;
  binding_segment_t?: number | null;
  name: string;
  kind: string;
  x?: number | null;
  y?: number | null;
  hidden?: boolean;
  discovered?: boolean;
};
type SpatialConnection = {
  id: string;
  kind: "route" | "door" | "portal";
  source_anchor_id: string;
  target_anchor_id: string;
  travel_minutes: number;
  modes?: string[];
  bidirectional?: boolean;
  requirements?: Record<string, unknown> | null;
  lock?: { locked?: boolean; minigame_key?: string | null; difficulty?: number; success_behavior?: string } | null;
  hidden?: boolean;
  discovered?: boolean;
  enabled?: boolean;
  source_location_id?: string;
  target_location_id?: string;
};
type SpatialBarrier = {
  id: string;
  name: string;
  location_id: string;
  blocked_modes?: string[];
  hidden?: boolean;
  discovered?: boolean;
  geometry?: Geometry;
};
type SpatialMap = {
  enabled: boolean;
  root_location_id: string | null;
  location_id?: string;
  topology?: "open" | "closed";
  blocked_reason?: string;
  locations: SpatialLocation[];
  anchors: SpatialAnchor[];
  connections: SpatialConnection[];
  barriers: SpatialBarrier[];
};
type BackgroundRecord = {
  media_asset_id: string;
  file_path?: string | null;
  status: string;
  prompt: string;
  negative_prompt: string;
  weather_id?: string | null;
  time_phase_id?: string | null;
};
type DragLocation = {
  id: string;
  start: Point;
  x: number;
  y: number;
  footprint: Point[];
};
type VertexDrag = { locationId: string; index: number };
type VertexMenuState = { mouseX: number; mouseY: number; locationId: string; index: number } | null;
type EndpointKind = "coordinate" | "area" | "area_border" | "spot";
type EndpointChoice = {
  key: string;
  kind: EndpointKind;
  label: string;
  targetId?: string | null;
  point: Point;
  offsetX?: number;
  offsetY?: number;
  segmentIndex?: number;
  segmentT?: number;
};
type RouteDialogState = {
  points: [Point, Point];
  options: [EndpointChoice[], EndpointChoice[]];
  selections: [string, string];
  kind: SpatialConnection["kind"];
  travelMinutes: number;
  modes: string;
  bidirectional: boolean;
  enabled: boolean;
  discovered: boolean;
  hidden: boolean;
} | null;
type ConnectionDraft = {
  kind: SpatialConnection["kind"];
  travelMinutes: number;
  modes: string;
  bidirectional: boolean;
  hidden: boolean;
  discovered: boolean;
  enabled: boolean;
  locked: boolean;
  minigameKey: string;
  difficulty: number;
};
type HitCandidate = { id: string; label: string; detail: string };
type HitMenuState = { mouseX: number; mouseY: number; candidates: HitCandidate[] } | null;
type LocationAuthoringDefaults = {
  exposure: EnvironmentLocation["exposure"];
  enabled: boolean;
  discovered: boolean;
  hidden: boolean;
  randomEncounter: boolean;
};
type ConnectionAuthoringDefaults = {
  kind: SpatialConnection["kind"];
  bidirectional: boolean;
  enabled: boolean;
  discovered: boolean;
  hidden: boolean;
};

const clamp = (value: number) => Math.max(0, Math.min(100, value));
const round = (value: number) => Math.round(value * 10) / 10;
const centroid = (points: Point[]): Point => {
  if (!points.length) return { x: 50, y: 50 };
  return {
    x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
    y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
  };
};
const triangleAt = (center: Point, radius = 4): Point[] => [
  { x: clamp(round(center.x)), y: clamp(round(center.y - radius)) },
  { x: clamp(round(center.x - radius)), y: clamp(round(center.y + radius)) },
  { x: clamp(round(center.x + radius)), y: clamp(round(center.y + radius)) },
];
const distance = (left: Point, right: Point) => Math.hypot(left.x - right.x, left.y - right.y);
const pointInPolygon = (point: Point, polygon: Point[]) => {
  if (polygon.length < 3) return false;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i], b = polygon[j];
    const intersects = ((a.y > point.y) !== (b.y > point.y))
      && point.x < ((b.x - a.x) * (point.y - a.y)) / ((b.y - a.y) || Number.EPSILON) + a.x;
    if (intersects) inside = !inside;
  }
  return inside;
};
const closestPointOnSegment = (point: Point, a: Point, b: Point): Point => {
  const dx = b.x - a.x, dy = b.y - a.y;
  const lengthSq = dx * dx + dy * dy;
  if (!lengthSq) return a;
  const t = Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSq));
  return { x: round(a.x + t * dx), y: round(a.y + t * dy) };
};
const closestBorderPoint = (point: Point, points: Point[]): { point: Point; distance: number; segmentIndex: number; segmentT: number } | null => {
  if (points.length < 2) return null;
  let best: { point: Point; distance: number; segmentIndex: number; segmentT: number } | null = null;
  for (let index = 0; index < points.length; index++) {
    const left = points[index], right = points[(index + 1) % points.length];
    const dx = right.x - left.x, dy = right.y - left.y;
    const lengthSq = dx * dx + dy * dy;
    const segmentT = lengthSq
      ? Math.max(0, Math.min(1, ((point.x - left.x) * dx + (point.y - left.y) * dy) / lengthSq))
      : 0;
    const candidate = { x: round(left.x + segmentT * dx), y: round(left.y + segmentT * dy) };
    const candidateDistance = distance(point, candidate);
    if (!best || candidateDistance < best.distance) best = { point: candidate, distance: candidateDistance, segmentIndex: index, segmentT };
  }
  return best;
};
const distanceToSegment = (point: Point, left: Point, right: Point) => distance(point, closestPointOnSegment(point, left, right));
const areaPriority = (entity?: WorldEntity | null) => Number(entity?.state.priority_layer ?? 0);
const compareAreaPriority = (left: WorldEntity, right: WorldEntity) => {
  const priority = areaPriority(left) - areaPriority(right);
  if (priority) return priority;
  if (left.name !== right.name) return left.name < right.name ? -1 : 1;
  return left.id === right.id ? 0 : left.id < right.id ? -1 : 1;
};
const connectionKindLabel = (kind: SpatialConnection["kind"]) =>
  kind === "route" ? "Route / shortcut" : kind === "portal" ? "Portal / teleporter" : "Door";
const geometryPoints = (entity?: WorldEntity | null): Point[] => {
  const raw = entity?.state.footprint as Geometry | null | undefined;
  return Array.isArray(raw?.points)
    ? raw.points.filter(point => typeof point?.x === "number" && typeof point?.y === "number")
    : [];
};
const locationDraft = (entity: WorldEntity): EnvironmentLocation => {
  const state = entity.state;
  return {
    id: entity.id,
    name: entity.name,
    tags: entity.tags ?? [],
    parent_location_id: String(state.parent_location_id || "") || null,
    exposure: state.exposure === "indoor" || state.exposure === "isolated" ? state.exposure : "outdoor",
    description: String(state.description ?? ""),
    imagegen_description: String(state.imagegen_description ?? ""),
    image_tags: Array.isArray(state.image_tags) ? state.image_tags.map(String) : [],
    enabled: state.enabled !== false,
    random_encounter: Boolean(state.random_encounter),
    hidden: Boolean(state.hidden),
    discovered: state.discovered == null ? !state.random_encounter : Boolean(state.discovered),
    x: typeof state.x === "number" ? state.x : null,
    y: typeof state.y === "number" ? state.y : null,
    topology: state.topology === "open" ? "open" : "closed",
    occupancy: state.occupancy === "child_required" ? "child_required" : "direct_allowed",
    boundary_access: state.boundary_access === "connection_required" ? "connection_required" : "free",
    spatial_kind: state.spatial_kind === "area" ? "area" : "spot",
    priority_layer: typeof state.priority_layer === "number" ? state.priority_layer : 0,
    minutes_per_unit: typeof state.minutes_per_unit === "number" ? state.minutes_per_unit : 1,
    base_visibility_units: typeof state.base_visibility_units === "number" ? state.base_visibility_units : null,
    encounter_rate: typeof state.encounter_rate === "number" ? state.encounter_rate : 0,
    footprint: state.footprint && typeof state.footprint === "object" ? state.footprint as Record<string, unknown> : null,
    local_bounds: state.local_bounds && typeof state.local_bounds === "object" ? state.local_bounds as Record<string, unknown> : null,
  };
};

export function LocationMapStudio({
  projectId,
  revision,
  fail,
}: {
  projectId: string;
  revision: number;
  fail: (message: string) => void;
}) {
  const [map, setMap] = useState<SpatialMap | null>(null);
  const [world, setWorld] = useState<WorldProjection | null>(null);
  const [environmentSettings, setEnvironmentSettings] = useState<EnvironmentSettings | null>(null);
  const [layerId, setLayerId] = useState<string | null>(null);
  const [tool, setTool] = useState<Tool>("select");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [routePoints, setRoutePoints] = useState<Point[]>([]);
  const [routeDialog, setRouteDialog] = useState<RouteDialogState>(null);
  const [vertexMenu, setVertexMenu] = useState<VertexMenuState>(null);
  const [areaDraft, setAreaDraft] = useState<Point[]>([]);
  const [zoom, setZoom] = useState(1);
  const [dragLocation, setDragLocation] = useState<DragLocation | null>(null);
  const [dragOffset, setDragOffset] = useState<Point>({ x: 0, y: 0 });
  const [vertexDrag, setVertexDrag] = useState<VertexDrag | null>(null);
  const [vertexPreview, setVertexPreview] = useState<Point | null>(null);
  const [editorDraft, setEditorDraft] = useState<EnvironmentLocation | null>(null);
  const [backgrounds, setBackgrounds] = useState<BackgroundRecord[]>([]);
  const [imageBusy, setImageBusy] = useState(false);
  const [connectionDraft, setConnectionDraft] = useState<ConnectionDraft | null>(null);
  const [hitMenu, setHitMenu] = useState<HitMenuState>(null);
  const [locationDefaults, setLocationDefaults] = useState<LocationAuthoringDefaults>({
    exposure: "outdoor",
    enabled: true,
    discovered: true,
    hidden: false,
    randomEncounter: false,
  });
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [connectionDefaults, setConnectionDefaults] = useState<ConnectionAuthoringDefaults>({
    kind: "route",
    bidirectional: true,
    enabled: true,
    discovered: true,
    hidden: false,
  });

  useEffect(() => {
    const node = canvasRef.current;
    if (!node) return;
    const handleWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      event.stopPropagation();
      setZoom(value => Math.max(.5, Math.min(2, round(value - event.deltaY * .001))));
    };
    node.addEventListener("wheel", handleWheel, { passive: false });
    return () => node.removeEventListener("wheel", handleWheel);
  }, []);

  const load = useCallback(async () => {
    const [nextMap, nextWorld, nextSettings] = await Promise.all([
      api<SpatialMap>(`/projects/${projectId}/spatial/map${layerId ? `?location_id=${layerId}` : ""}`),
      api<WorldProjection>(`/projects/${projectId}/world`),
      api<EnvironmentSettings>(`/projects/${projectId}/environment/settings`),
    ]);
    setMap(nextMap);
    setWorld(nextWorld);
    setEnvironmentSettings(nextSettings);
    if (!layerId && nextMap.root_location_id) setLayerId(nextMap.root_location_id);
  }, [projectId, layerId]);

  useEffect(() => {
    void load().catch(cause => fail(String(cause)));
  }, [load, revision, fail]);

  const currentLayer = layerId ? world?.entities[layerId] : null;
  const selectedEntity = selectedId ? world?.entities[selectedId] : null;
  const selectedLocation = selectedEntity?.kind === "location" ? selectedEntity : null;

  useEffect(() => {
    setEditorDraft(selectedLocation ? locationDraft(selectedLocation) : null);
  }, [selectedLocation?.id, world]);

  const loadBackgrounds = useCallback(async (locationId: string) => {
    const rows = await api<BackgroundRecord[]>(`/projects/${projectId}/environment/locations/${locationId}/backgrounds`);
    setBackgrounds(rows);
  }, [projectId]);

  useEffect(() => {
    if (!selectedLocation) {
      setBackgrounds([]);
      return;
    }
    void loadBackgrounds(selectedLocation.id).catch(cause => fail(String(cause)));
  }, [selectedLocation?.id, loadBackgrounds, fail]);

  const breadcrumbs = useMemo(() => {
    const result: Array<{ id: string; name: string }> = [];
    const seen = new Set<string>();
    let current = currentLayer;
    while (current && !seen.has(current.id)) {
      seen.add(current.id);
      result.unshift({ id: current.id, name: current.name });
      current = world?.entities[String(current.state.parent_location_id || "")];
    }
    return result;
  }, [currentLayer, world]);

  const validation = useMemo(() => {
    if (!world) return [];
    const locations = Object.values(world.entities).filter(item => item.kind === "location" && !item.state.archived);
    const ids = new Set(locations.map(item => item.id));
    const messages: string[] = [];
    if (!map?.root_location_id) messages.push("Missing world root: placement and travel are disabled.");
    locations.forEach(item => {
      const parent = String(item.state.parent_location_id || "");
      if (parent && !ids.has(parent)) messages.push(`${item.name} has an unavailable parent.`);
      if (item.state.occupancy === "child_required" && !locations.some(child => child.state.parent_location_id === item.id)) {
        messages.push(`${item.name} requires a child but has none.`);
      }
      const points = geometryPoints(item);
      if (!points.length && (typeof item.state.x !== "number" || typeof item.state.y !== "number")) {
        messages.push(`${item.name} has no canonical map position; drag it once to adopt its drop coordinates.`);
      }
    });
    map?.anchors.filter(item => (item.binding_kind ?? "coordinate") === "coordinate" && (item.x == null || item.y == null)).forEach(item => {
      messages.push(`${item.name} needs map review: its position is incomplete.`);
    });
    return messages;
  }, [map, world]);

  const selectedSpatial = map?.anchors.find(item => item.id === selectedId)
    ?? map?.barriers.find(item => item.id === selectedId)
    ?? map?.connections.find(item => item.id === selectedId)
    ?? null;
  const selectedConnection = map?.connections.find(item => item.id === selectedId) ?? null;

  useEffect(() => {
    if (!selectedConnection) {
      setConnectionDraft(null);
      return;
    }
    setConnectionDraft({
      kind: selectedConnection.kind,
      travelMinutes: selectedConnection.travel_minutes,
      modes: (selectedConnection.modes ?? ["walk"]).join(", "),
      bidirectional: selectedConnection.bidirectional !== false,
      hidden: Boolean(selectedConnection.hidden),
      discovered: selectedConnection.discovered !== false,
      enabled: selectedConnection.enabled !== false,
      locked: Boolean(selectedConnection.lock?.locked),
      minigameKey: selectedConnection.lock?.minigame_key ?? "",
      difficulty: Number(selectedConnection.lock?.difficulty ?? 1),
    });
  }, [selectedConnection]);

  const backgroundAsset = useMemo<MediaAsset | null>(() => {
    if (!selectedLocation || !backgrounds.length) return null;
    const row = backgrounds[0];
    return {
      id: row.media_asset_id,
      entity_id: selectedLocation.id,
      kind: "location",
      status: row.status,
      file_path: row.file_path,
      prompt: row.prompt,
      negative_prompt: row.negative_prompt,
    };
  }, [backgrounds, selectedLocation]);

  function canvasPoint(clientX: number, clientY: number, element: HTMLElement): Point {
    const rect = element.getBoundingClientRect();
    return {
      x: clamp(round(((clientX - rect.left) / rect.width) * 100 / zoom)),
      y: clamp(round(((clientY - rect.top) / rect.height) * 100 / zoom)),
    };
  }

  async function migrate() {
    await api(`/projects/${projectId}/spatial/migrate`, { method: "POST" });
    await load();
  }

  async function createRoot() {
    const name = window.prompt("Root location name", "World")?.trim();
    if (!name) return;
    await api(`/projects/${projectId}/spatial/root`, {
      method: "POST",
      body: JSON.stringify({ name, topology: "closed", occupancy: "child_required", extend_scope: true }),
    });
    setLayerId(null);
    await load();
  }

  async function createSpot(point: Point) {
    if (!layerId) return;
    const name = window.prompt("Spot name")?.trim();
    if (!name) return;
    await api(`/projects/${projectId}/environment/locations`, {
      method: "POST",
      body: JSON.stringify({
        name,
        parent_location_id: layerId,
        exposure: locationDefaults.exposure,
        description: "",
        imagegen_description: "",
        tags: [],
        image_tags: [],
        enabled: locationDefaults.enabled,
        random_encounter: locationDefaults.randomEncounter,
        hidden: locationDefaults.hidden,
        discovered: locationDefaults.discovered,
        x: point.x,
        y: point.y,
        topology: "closed",
        occupancy: "direct_allowed",
        boundary_access: "free",
        spatial_kind: "spot",
        priority_layer: 0,
        minutes_per_unit: 1,
        base_visibility_units: null,
        encounter_rate: 0,
        footprint: { location_id: layerId, kind: "point", points: [point] },
        local_bounds: null,
      }),
    });
    setTool("select");
    await load();
  }

  async function finishArea(closed: boolean) {
    if (!layerId || areaDraft.length < 2) return;
    if (!closed) {
      const name = window.prompt("Wall / barrier name", "Wall")?.trim();
      if (!name) return;
      await api(`/projects/${projectId}/spatial/barriers`, {
        method: "PUT",
        body: JSON.stringify({
          location_id: layerId,
          name,
          blocked_modes: ["walk"],
          geometry: { location_id: layerId, kind: "polyline", points: areaDraft },
        }),
      });
    } else {
      const name = window.prompt("Area name")?.trim();
      if (!name) return;
      const center = centroid(areaDraft);
      await api(`/projects/${projectId}/environment/locations`, {
        method: "POST",
        body: JSON.stringify({
          name,
          parent_location_id: layerId,
          exposure: locationDefaults.exposure,
          description: "",
          imagegen_description: "",
          tags: [],
          image_tags: [],
          enabled: locationDefaults.enabled,
          random_encounter: locationDefaults.randomEncounter,
          hidden: locationDefaults.hidden,
          discovered: locationDefaults.discovered,
          x: round(center.x),
          y: round(center.y),
          topology: "open",
          occupancy: "direct_allowed",
          boundary_access: "free",
          spatial_kind: "area",
          priority_layer: 0,
          minutes_per_unit: 1,
          base_visibility_units: null,
          encounter_rate: 0,
          footprint: { location_id: layerId, kind: "polygon", points: areaDraft },
          local_bounds: null,
        }),
      });
    }
    setAreaDraft([]);
    setTool("select");
    await load();
  }

  async function saveLocation(value: EnvironmentLocation) {
    if (!value.id) return;
    await api(`/projects/${projectId}/environment/locations/${value.id}`, {
      method: "PUT",
      body: JSON.stringify(value),
    });
    await load();
  }

  function fallbackLocationPoint(entity: WorldEntity): Point {
    const itemIndex = Math.max(0, map?.locations.findIndex(item => item.id === entity.id) ?? 0);
    const points = geometryPoints(entity);
    if (points.length) return centroid(points);
    if (typeof entity.state.x === "number" && typeof entity.state.y === "number") {
      return { x: Number(entity.state.x), y: Number(entity.state.y) };
    }
    return {
      x: 12 + (itemIndex * 11) % 75,
      y: 16 + (itemIndex * 9) % 68,
    };
  }

  async function convertLocationKind(entity: WorldEntity, kind: "spot" | "area") {
    const current = editorDraft?.id === entity.id ? editorDraft : locationDraft(entity);
    if (current.spatial_kind === kind) return;
    const points = geometryPoints(entity);
    const center = points.length ? centroid(points) : fallbackLocationPoint(entity);
    const next: EnvironmentLocation = {
      ...current,
      spatial_kind: kind,
      x: round(center.x),
      y: round(center.y),
      footprint: kind === "area"
        ? { location_id: layerId, kind: "polygon", points: triangleAt(center) }
        : { location_id: layerId, kind: "point", points: [{ x: round(center.x), y: round(center.y) }] },
    };
    await saveLocation(next);
    setEditorDraft(next);
  }

  async function deleteLocation(entity: WorldEntity) {
    const confirmed = window.confirm(
      `Delete "${entity.name}"? Connected map paths/endpoints will also be removed. Child locations and occupied locations must be cleared first.`
    );
    if (!confirmed) return;
    await api(`/projects/${projectId}/environment/locations/${entity.id}`, { method: "DELETE" });
    setSelectedId(null);
    setEditorDraft(null);
    await load();
  }

  async function deleteSpatialObject(kind: "anchor" | "barrier", id: string) {
    await api(`/projects/${projectId}/spatial/${kind}/${id}`, { method: "DELETE" });
    setSelectedId(null);
    await load();
  }

  function routeEndpointOptions(point: Point): EndpointChoice[] {
    if (!layerId || !world || !map) return [{
      key: "coordinate",
      kind: "coordinate",
      label: `Free coordinates (${point.x}, ${point.y})`,
      point,
    }];
    const options: EndpointChoice[] = [{
      key: "coordinate",
      kind: "coordinate",
      label: `Free coordinates (${point.x}, ${point.y})`,
      point,
    }];
    const areaEntities = map.locations
      .map(item => world.entities[item.id])
      .filter((item): item is WorldEntity => Boolean(item && item.kind === "location" && item.state.spatial_kind === "area"))
      .sort(compareAreaPriority);

    for (const entity of areaEntities) {
      const points = geometryPoints(entity);
      if (pointInPolygon(point, points)) {
        const center = centroid(points);
        options.push({
          key: `area:${entity.id}`,
          kind: "area",
          targetId: entity.id,
          label: `Inside area · ${entity.name} (priority ${areaPriority(entity)})`,
          point,
          offsetX: round(point.x - center.x),
          offsetY: round(point.y - center.y),
        });
      }
      const border = closestBorderPoint(point, points);
      if (border && border.distance <= 2.2) {
        options.push({
          key: `area_border:${entity.id}`,
          kind: "area_border",
          targetId: entity.id,
          label: `Area border · ${entity.name}`,
          point: border.point,
          segmentIndex: border.segmentIndex,
          segmentT: border.segmentT,
        });
      }
    }

    for (const item of map.locations) {
      const entity = world.entities[item.id];
      if (!entity || entity.state.spatial_kind === "area") continue;
      const points = geometryPoints(entity);
      const spot = points[0] ?? { x: Number(item.x ?? entity.state.x ?? 0), y: Number(item.y ?? entity.state.y ?? 0) };
      if (distance(point, spot) <= 2.6) {
        options.push({
          key: `spot:${entity.id}`,
          kind: "spot",
          targetId: entity.id,
          label: `Spot · ${entity.name}`,
          point: { x: round(spot.x), y: round(spot.y) },
        });
      }
    }
    return options;
  }

  function preferredEndpoint(options: EndpointChoice[]) {
    return options.find(item => item.kind === "spot")
      ?? options.find(item => item.kind === "area_border")
      ?? options.find(item => item.kind === "area")
      ?? options[0];
  }

  function beginRouteDialog(first: Point, second: Point) {
    const firstOptions = routeEndpointOptions(first);
    const secondOptions = routeEndpointOptions(second);
    setRouteDialog({
      points: [first, second],
      options: [firstOptions, secondOptions],
      selections: [preferredEndpoint(firstOptions).key, preferredEndpoint(secondOptions).key],
      kind: connectionDefaults.kind,
      travelMinutes: 0,
      modes: "walk",
      bidirectional: connectionDefaults.bidirectional,
      enabled: connectionDefaults.enabled,
      discovered: connectionDefaults.discovered,
      hidden: connectionDefaults.hidden,
    });
  }

  async function createConfiguredRoute() {
    if (!routeDialog || !layerId) return;
    const sourceChoice = routeDialog.options[0].find(item => item.key === routeDialog.selections[0]) ?? routeDialog.options[0][0];
    const targetChoice = routeDialog.options[1].find(item => item.key === routeDialog.selections[1]) ?? routeDialog.options[1][0];
    const choices: [EndpointChoice, EndpointChoice] = [sourceChoice, targetChoice];

    const makeAnchor = async (choice: EndpointChoice, side: "A" | "B") => {
      const target = choice.targetId ? world?.entities[choice.targetId] : null;
      return api<{ id: string }>(`/projects/${projectId}/spatial/anchors`, {
        method: "PUT",
        body: JSON.stringify({
          location_id: choice.targetId ?? layerId,
          coordinate_space_id: layerId,
          binding_kind: choice.kind,
          binding_target_id: choice.targetId ?? null,
          binding_offset_x: choice.offsetX ?? null,
          binding_offset_y: choice.offsetY ?? null,
          binding_segment_index: choice.segmentIndex ?? null,
          binding_segment_t: choice.segmentT ?? null,
          name: `${target?.name ?? currentLayer?.name ?? "Map"} route ${side}`,
          kind: "waypoint",
          x: choice.kind === "coordinate" ? choice.point.x : null,
          y: choice.kind === "coordinate" ? choice.point.y : null,
        }),
      });
    };

    const sourceAnchor = await makeAnchor(choices[0], "A");
    const targetAnchor = await makeAnchor(choices[1], "B");
    const connection = await api<{ id: string }>(`/projects/${projectId}/spatial/connections`, {
      method: "PUT",
      body: JSON.stringify({
        kind: routeDialog.kind,
        source_anchor_id: sourceAnchor.id,
        target_anchor_id: targetAnchor.id,
        travel_minutes: Math.max(0, Math.round(routeDialog.travelMinutes)),
        modes: routeDialog.modes.split(",").map(item => item.trim()).filter(Boolean).length
          ? routeDialog.modes.split(",").map(item => item.trim()).filter(Boolean)
          : ["walk"],
        bidirectional: routeDialog.bidirectional,
        enabled: routeDialog.enabled,
        discovered: routeDialog.discovered,
        hidden: routeDialog.hidden,
      }),
    });
    setRouteDialog(null);
    setRoutePoints([]);
    setTool("select");
    setSelectedId(connection.id);
    await load();
  }

  async function removeVertex(locationId: string, index: number) {
    if (!world) return;
    const entity = world.entities[locationId];
    if (!entity) return;
    const points = geometryPoints(entity);
    if (points.length <= 2) return;
    points.splice(index, 1);
    const next = locationDraft(entity);
    const center = centroid(points);
    next.x = round(center.x);
    next.y = round(center.y);
    next.footprint = { location_id: layerId, kind: "polygon", points };
    setVertexMenu(null);
    await saveLocation(next);
  }

  async function createConnectedVertex() {
    if (!vertexMenu || !world) return;
    const entity = world.entities[vertexMenu.locationId];
    if (!entity) return;
    const points = geometryPoints(entity);
    if (!points.length) return;
    const point = points[vertexMenu.index];
    const next = points[(vertexMenu.index + 1) % points.length];
    const middle = { x: round((point.x + next.x) / 2), y: round((point.y + next.y) / 2) };
    const { locationId, index } = vertexMenu;
    setVertexMenu(null);
    await insertVertex(locationId, index, middle);
  }

  async function saveConnection(connection: SpatialConnection) {
    if (!connectionDraft) return;
    await api(`/projects/${projectId}/spatial/connections`, {
      method: "PUT",
      body: JSON.stringify({
        id: connection.id,
        kind: connectionDraft.kind,
        source_anchor_id: connection.source_anchor_id,
        target_anchor_id: connection.target_anchor_id,
        travel_minutes: Math.max(0, Math.round(connectionDraft.travelMinutes)),
        modes: connectionDraft.modes.split(",").map(item => item.trim()).filter(Boolean).length
          ? connectionDraft.modes.split(",").map(item => item.trim()).filter(Boolean)
          : ["walk"],
        bidirectional: connectionDraft.bidirectional,
        requirements: connection.requirements ?? null,
        lock: connectionDraft.locked ? {
          locked: true,
          minigame_key: connectionDraft.minigameKey || null,
          difficulty: Math.max(0, Math.round(connectionDraft.difficulty)),
          success_behavior: connection.lock?.success_behavior ?? "persistent",
        } : null,
        hidden: connectionDraft.hidden,
        discovered: connectionDraft.discovered,
        enabled: connectionDraft.enabled,
      }),
    });
    await load();
  }

  async function deleteConnection(connection: SpatialConnection) {
    await api(`/projects/${projectId}/spatial/connection/${connection.id}`, { method: "DELETE" });
    for (const anchorId of [connection.source_anchor_id, connection.target_anchor_id]) {
      await api(`/projects/${projectId}/spatial/anchor/${anchorId}`, { method: "DELETE" }).catch(() => undefined);
    }
    setSelectedId(null);
    await load();
  }

  function chooseLocation(id: string) {
    setSelectedId(id);
  }

  async function beginLocationDrag(event: ReactPointerEvent<HTMLElement>, id: string) {
    if ((tool !== "drag" && tool !== "select") || !world || event.button !== 0) return;
    event.stopPropagation();
    const entity = world.entities[id];
    if (!entity) return;
    const host = event.currentTarget.closest(".location-map-canvas") as HTMLElement | null;
    if (!host) return;
    const start = canvasPoint(event.clientX, event.clientY, host);
    const points = geometryPoints(entity);
    const base = fallbackLocationPoint(entity);
    setDragLocation({
      id,
      start,
      x: base.x,
      y: base.y,
      footprint: points,
    });
    setDragOffset({ x: 0, y: 0 });
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  async function finishLocationDrag() {
    if (!dragLocation || !world) return;
    const entity = world.entities[dragLocation.id];
    if (!entity) return;
    if (Math.abs(dragOffset.x) < .1 && Math.abs(dragOffset.y) < .1) {
      setDragLocation(null);
      setDragOffset({ x: 0, y: 0 });
      return;
    }
    const next = locationDraft(entity);
    next.x = clamp(round(dragLocation.x + dragOffset.x));
    next.y = clamp(round(dragLocation.y + dragOffset.y));
    if (dragLocation.footprint.length) {
      next.footprint = {
        location_id: layerId,
        kind: next.spatial_kind === "area" ? "polygon" : "point",
        points: dragLocation.footprint.map(point => ({
          x: clamp(round(point.x + dragOffset.x)),
          y: clamp(round(point.y + dragOffset.y)),
        })),
      };
    } else {
      // Legacy locations can exist without x/y or footprint geometry. Their
      // first drag adopts the drop point as canonical map geometry.
      const center = { x: next.x, y: next.y };
      next.footprint = next.spatial_kind === "area"
        ? { location_id: layerId, kind: "polygon", points: triangleAt(center) }
        : { location_id: layerId, kind: "point", points: [center] };
    }
    const footprint = next.footprint;
    setDragLocation(null);
    setDragOffset({ x: 0, y: 0 });
    if (!footprint) return;
    await api(`/projects/${projectId}/spatial/locations/${entity.id}/placement`, {
      method: "PUT",
      body: JSON.stringify({
        x: next.x,
        y: next.y,
        spatial_kind: next.spatial_kind,
        footprint,
      }),
    });
    await load();
  }

  async function finishVertexDrag() {
    if (!vertexDrag || !vertexPreview || !world) return;
    const entity = world.entities[vertexDrag.locationId];
    if (!entity) return;
    const points = geometryPoints(entity);
    if (!points[vertexDrag.index]) return;
    points[vertexDrag.index] = vertexPreview;
    const next = locationDraft(entity);
    const center = centroid(points);
    next.x = round(center.x);
    next.y = round(center.y);
    next.footprint = { location_id: layerId, kind: "polygon", points };
    setVertexDrag(null);
    setVertexPreview(null);
    await saveLocation(next);
  }

  async function insertVertex(locationId: string, index: number, point: Point) {
    if (!world) return;
    const entity = world.entities[locationId];
    if (!entity) return;
    const points = geometryPoints(entity);
    points.splice(index + 1, 0, point);
    const next = locationDraft(entity);
    const center = centroid(points);
    next.x = round(center.x);
    next.y = round(center.y);
    next.footprint = { location_id: layerId, kind: "polygon", points };
    await saveLocation(next);
  }

  async function generateBackground(customPrompt: boolean, asset?: MediaAsset | null) {
    if (!selectedLocation) return;
    const workflowId = environmentSettings?.background_workflow_id;
    if (!workflowId) {
      fail("Choose a background workflow in Environment before generating location images.");
      return;
    }
    const fallback = String(selectedLocation.state.imagegen_description || selectedLocation.state.description || selectedLocation.name);
    const prompt = customPrompt ? window.prompt("Background prompt", asset?.prompt || fallback)?.trim() : (asset?.prompt || fallback).trim();
    if (!prompt) return;
    setImageBusy(true);
    try {
      let mediaId = asset?.id;
      if (!mediaId) {
        const created = await api<{ media_asset_id: string }>(
          `/projects/${projectId}/environment/locations/${selectedLocation.id}/backgrounds`,
          {
            method: "POST",
            body: JSON.stringify({ prompt, negative_prompt: "", weather_id: null, time_phase_id: null }),
          },
        );
        mediaId = created.media_asset_id;
      }
      await api(`/media-assets/${mediaId}/generate`, {
        method: "POST",
        body: JSON.stringify({
          workflow_preset_id: workflowId,
          prompt,
          negative_prompt: asset?.negative_prompt ?? "",
          width: null,
          height: null,
        }),
      });
      await loadBackgrounds(selectedLocation.id);
    } finally {
      setImageBusy(false);
    }
  }

  async function uploadBackground(file: File) {
    if (!selectedLocation) return;
    const form = new FormData();
    form.append("file", file);
    setImageBusy(true);
    try {
      await api(`/entities/${selectedLocation.id}/media/upload?kind=location`, { method: "POST", body: form });
      await loadBackgrounds(selectedLocation.id);
    } finally {
      setImageBusy(false);
    }
  }

  async function deleteBackground(asset: MediaAsset) {
    if (!selectedLocation) return;
    await api(`/media-assets/${asset.id}`, { method: "DELETE" });
    await loadBackgrounds(selectedLocation.id);
  }

  function renderedGeometryPoints(entity?: WorldEntity | null): Point[] {
    if (!entity) return [];
    const points = geometryPoints(entity).map(point => ({ ...point }));
    if (dragLocation?.id === entity.id) {
      return points.map(point => ({
        x: clamp(round(point.x + dragOffset.x)),
        y: clamp(round(point.y + dragOffset.y)),
      }));
    }
    if (vertexDrag?.locationId === entity.id && vertexPreview && points[vertexDrag.index]) {
      points[vertexDrag.index] = vertexPreview;
    }
    return points;
  }

  function resolvedAnchorPoint(anchor?: SpatialAnchor | null): Point | null {
    if (!anchor) return null;
    const fallback = anchor.x != null && anchor.y != null ? { x: Number(anchor.x), y: Number(anchor.y) } : null;
    if (!anchor.binding_target_id || !anchor.binding_kind || anchor.binding_kind === "coordinate" || !world) return fallback;
    const target = world.entities[anchor.binding_target_id];
    if (!target) return fallback;
    const points = renderedGeometryPoints(target);

    if (anchor.binding_kind === "spot") {
      if (points.length) return points[0];
      if (typeof target.state.x === "number" && typeof target.state.y === "number") {
        const offset = dragLocation?.id === target.id ? dragOffset : { x: 0, y: 0 };
        return { x: round(target.state.x + offset.x), y: round(target.state.y + offset.y) };
      }
      return fallback;
    }

    if (anchor.binding_kind === "area" && points.length) {
      const center = centroid(points);
      if (typeof anchor.binding_offset_x === "number" && typeof anchor.binding_offset_y === "number") {
        return {
          x: round(center.x + anchor.binding_offset_x),
          y: round(center.y + anchor.binding_offset_y),
        };
      }
      return fallback;
    }

    if (anchor.binding_kind === "area_border" && points.length >= 2) {
      const index = anchor.binding_segment_index;
      const ratio = anchor.binding_segment_t;
      if (typeof index === "number" && typeof ratio === "number") {
        const left = points[index % points.length];
        const right = points[(index + 1) % points.length];
        return {
          x: round(left.x + (right.x - left.x) * ratio),
          y: round(left.y + (right.y - left.y) * ratio),
        };
      }
      if (fallback) return closestBorderPoint(fallback, points)?.point ?? fallback;
    }
    return fallback;
  }

  function hitCandidates(point: Point): HitCandidate[] {
    if (!map || !world) return [];
    const candidates: HitCandidate[] = [];
    for (const item of map.locations) {
      const entity = world.entities[item.id];
      if (!entity) continue;
      const points = renderedGeometryPoints(entity);
      if (entity.state.spatial_kind === "area") {
        const border = closestBorderPoint(point, points);
        if (pointInPolygon(point, points) || (border && border.distance <= 1.8)) {
          candidates.push({ id: item.id, label: item.name, detail: "area" });
        }
      } else {
        const spot = points[0] ?? { x: Number(item.x ?? entity.state.x ?? 0), y: Number(item.y ?? entity.state.y ?? 0) };
        if (distance(point, spot) <= 2.7) candidates.push({ id: item.id, label: item.name, detail: "spot" });
      }
    }
    for (const anchor of map.anchors) {
      if ((anchor.binding_kind ?? "coordinate") !== "coordinate") continue;
      const anchorPoint = resolvedAnchorPoint(anchor);
      if (anchorPoint && distance(point, anchorPoint) <= 2.2) {
        candidates.push({ id: anchor.id, label: anchor.name, detail: "coordinate endpoint" });
      }
    }
    for (const connection of map.connections) {
      const source = resolvedAnchorPoint(map.anchors.find(anchor => anchor.id === connection.source_anchor_id));
      const target = resolvedAnchorPoint(map.anchors.find(anchor => anchor.id === connection.target_anchor_id));
      if (source && target && distanceToSegment(point, source, target) <= 1.4) {
        const label = connectionKindLabel(connection.kind);
        candidates.push({ id: connection.id, label, detail: "connection" });
      }
    }
    for (const barrier of map.barriers) {
      const points = barrier.geometry?.points ?? [];
      if (points.some((segmentStart, index) =>
        index < points.length - 1 && distanceToSegment(point, segmentStart, points[index + 1]) <= 1.4
      )) {
        candidates.push({ id: barrier.id, label: barrier.name, detail: "barrier" });
      }
    }
    return candidates;
  }

  function openShiftHitMenu(event: MouseEvent<HTMLDivElement>) {
    if (!event.shiftKey) return;
    event.preventDefault();
    event.stopPropagation();
    const point = canvasPoint(event.clientX, event.clientY, event.currentTarget);
    const candidates = hitCandidates(point);
    if (candidates.length === 1) {
      setSelectedId(candidates[0].id);
      setHitMenu(null);
      return;
    }
    if (candidates.length > 1) {
      setHitMenu({ mouseX: event.clientX + 2, mouseY: event.clientY - 6, candidates });
    }
  }

  function canvasClick(event: MouseEvent<HTMLDivElement>) {
    if (tool !== "route" && event.target !== event.currentTarget && (event.target as HTMLElement).closest("button")) return;
    const point = canvasPoint(event.clientX, event.clientY, event.currentTarget);
    if (tool === "spot") void createSpot(point);
    if (tool === "route") {
      if (routePoints.length === 0) setRoutePoints([point]);
      else {
        beginRouteDialog(routePoints[0], point);
        setRoutePoints([]);
      }
    }
    if (tool === "area") {
      if (areaDraft.length >= 3 && distance(point, areaDraft[0]) < 2.5) {
        void finishArea(true);
      } else {
        setAreaDraft(current => [...current, point]);
      }
    }
  }

  function changeTool(next: Tool) {
    setTool(next);
    setAreaDraft([]);
    setRoutePoints([]);
    setRouteDialog(null);
    setDragLocation(null);
    setVertexDrag(null);
  }

  const areaContents = useMemo(() => {
    const result: Record<string, SpatialLocation[]> = {};
    if (!map || !world) return result;
    for (const area of map.locations) {
      const entity = world.entities[area.id];
      if (!entity || entity.state.spatial_kind !== "area") continue;
      result[area.id] = Object.values(world.entities)
        .filter(item =>
          item.kind === "location"
          && !item.state.archived
          && String(item.state.parent_location_id || "") === area.id
        )
        .map(item => ({
          id: item.id,
          name: item.name,
          parent_location_id: area.id,
          spatial_kind: item.state.spatial_kind === "area" ? "area" : "spot",
          priority_layer: Number(item.state.priority_layer ?? 0),
          x: typeof item.state.x === "number" ? item.state.x : null,
          y: typeof item.state.y === "number" ? item.state.y : null,
        }))
        .sort((left, right) => left.name < right.name ? -1 : left.name > right.name ? 1 : left.id < right.id ? -1 : 1);
    }
    return result;
  }, [map, world]);

  if (!map) return <p>Loading location map…</p>;
  if (!map.enabled) {
    return <Paper className="panel">
      <h2>Location Map</h2>
      <p>Create a root to enable mapping and travel. Weather, time, ambient sound, and music remain available without one.</p>
      <Button onClick={() => void migrate()}>Adopt existing locations</Button>
      <Button onClick={() => void createRoot()}>Create world root</Button>
    </Paper>;
  }

  const parentId = String(currentLayer?.state.parent_location_id || "");
  const anchors = new Map(map.anchors.map(anchor => [anchor.id, anchor]));
  const localBoundsRaw = currentLayer?.state.local_bounds as Geometry | null | undefined;
  const localBoundsPoints = Array.isArray(localBoundsRaw?.points) ? localBoundsRaw.points : [];
  const priorityOrderedAreas = map.locations
    .filter(item => world?.entities[item.id]?.state.spatial_kind === "area")
    .sort((left, right) => {
      const leftEntity = world?.entities[left.id];
      const rightEntity = world?.entities[right.id];
      if (!leftEntity || !rightEntity) return 0;
      return compareAreaPriority(rightEntity, leftEntity);
    });
  const toolLabels: Array<{ id: Tool; label: string }> = [
    { id: "select", label: "Select" },
    { id: "drag", label: "Drag" },
    { id: "spot", label: "New Spot" },
    { id: "area", label: "New Area" },
    { id: "route", label: "New Route" },
    { id: "edit", label: "Edit Positions" },
  ];

  return <div className="location-map-v2">
    <header className="location-map-header">
      <div className="location-map-heading">
        <div>
          <p className="eyebrow">SPATIAL AUTHORING</p>
          <h2>{currentLayer?.name ?? "Location Map"}</h2>
        </div>
        <Chip size="small" label={`${map.topology ?? "closed"} layer`} />
      </div>
      <div className="location-map-breadcrumbs">
        <Button size="small" disabled={!parentId} onClick={() => parentId && setLayerId(parentId)}>↑ Up</Button>
        {breadcrumbs.map((item, index) => <span key={item.id}>
          {index > 0 && <b>›</b>}
          <Button size="small" onClick={() => setLayerId(item.id)}>{item.name}</Button>
        </span>)}
      </div>
      <div className="location-map-quick-settings">
        {(tool === "spot" || tool === "area") ? <>
          <span className="location-map-quick-label">{tool === "spot" ? "New spot defaults" : "New area defaults"}</span>
          <TextField
            select
            size="small"
            label="Exposure"
            value={locationDefaults.exposure}
            onChange={event => setLocationDefaults({ ...locationDefaults, exposure: event.target.value as EnvironmentLocation["exposure"] })}
          >
            <MenuItem value="outdoor">Outdoor</MenuItem>
            <MenuItem value="indoor">Indoor</MenuItem>
            <MenuItem value="isolated">Sealed / isolated</MenuItem>
          </TextField>
          <FormControlLabel control={<Switch size="small" checked={locationDefaults.enabled} onChange={event => setLocationDefaults({ ...locationDefaults, enabled: event.target.checked })} />} label="Enabled" />
          <FormControlLabel control={<Switch size="small" checked={locationDefaults.discovered} onChange={event => setLocationDefaults({ ...locationDefaults, discovered: event.target.checked })} />} label="Discovered" />
          <FormControlLabel control={<Switch size="small" checked={locationDefaults.hidden} onChange={event => setLocationDefaults({ ...locationDefaults, hidden: event.target.checked })} />} label="Hidden" />
          <FormControlLabel control={<Switch size="small" checked={locationDefaults.randomEncounter} onChange={event => setLocationDefaults({ ...locationDefaults, randomEncounter: event.target.checked })} />} label="Random encounter" />
        </> : tool === "route" ? <>
          <span className="location-map-quick-label">New connection defaults</span>
          <TextField
            select
            size="small"
            label="Type"
            value={connectionDefaults.kind}
            onChange={event => setConnectionDefaults({ ...connectionDefaults, kind: event.target.value as SpatialConnection["kind"] })}
          >
            <MenuItem value="route">Route / shortcut</MenuItem>
            <MenuItem value="door">Door</MenuItem>
            <MenuItem value="portal">Portal / teleporter</MenuItem>
          </TextField>
          <FormControlLabel control={<Switch size="small" checked={connectionDefaults.bidirectional} onChange={event => setConnectionDefaults({ ...connectionDefaults, bidirectional: event.target.checked })} />} label="Bidirectional" />
          <FormControlLabel control={<Switch size="small" checked={connectionDefaults.enabled} onChange={event => setConnectionDefaults({ ...connectionDefaults, enabled: event.target.checked })} />} label="Enabled" />
          <FormControlLabel control={<Switch size="small" checked={connectionDefaults.discovered} onChange={event => setConnectionDefaults({ ...connectionDefaults, discovered: event.target.checked })} />} label="Discovered" />
          <FormControlLabel control={<Switch size="small" checked={connectionDefaults.hidden} onChange={event => setConnectionDefaults({ ...connectionDefaults, hidden: event.target.checked })} />} label="Hidden" />
        </> : <span className="location-map-quick-hint">
          {tool === "select" ? "Select mode · drag location labels to move them · Shift-click overlaps to choose an object" : tool === "edit" ? "Edit geometry · drag vertices or right-click them for point actions" : "Map authoring"}
        </span>}
      </div>
      <div className="location-map-toolbar">
        <ButtonGroup size="small">
          {toolLabels.map(item => <Button
            key={item.id}
            variant={tool === item.id ? "contained" : "outlined"}
            onClick={() => changeTool(item.id)}
          >{item.label}</Button>)}
        </ButtonGroup>
        <span className="location-map-toolbar-spacer" />
        {tool === "area" && areaDraft.length >= 2 && <Button size="small" onClick={() => void finishArea(false)}>
          Finish as wall
        </Button>}
        {tool === "area" && areaDraft.length >= 2 && <Button size="small" variant="outlined" onClick={() => void finishArea(true)}>
          Close as area
        </Button>}
        {tool === "area" && areaDraft.length > 0 && <Button size="small" onClick={() => setAreaDraft([])}>Cancel drawing</Button>}
        <TextField
          select
          size="small"
          label="Zoom"
          value={zoom}
          onChange={event => setZoom(Number(event.target.value))}
          className="location-map-zoom"
        >
          {[.5, .75, 1, 1.25, 1.5, 2].map(value => <MenuItem key={value} value={value}>{Math.round(value * 100)}%</MenuItem>)}
        </TextField>
      </div>
    </header>

    <div className="location-map-body">
      <div
        ref={canvasRef}
        className={`location-map-canvas tool-${tool}`}
        onClickCapture={openShiftHitMenu}
        onClick={canvasClick}
        onPointerMove={event => {
          const point = canvasPoint(event.clientX, event.clientY, event.currentTarget);
          if (dragLocation) {
            setDragOffset({
              x: round(point.x - dragLocation.start.x),
              y: round(point.y - dragLocation.start.y),
            });
          }
          if (vertexDrag) setVertexPreview(point);
        }}
        onPointerUp={() => {
          if (dragLocation) void finishLocationDrag();
          if (vertexDrag) void finishVertexDrag();
        }}
      >
        <div className="location-map-world" style={{ transform: `scale(${zoom})` }}>
          <svg className="location-map-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
            {localBoundsPoints.length >= 3
              ? <polygon
                  points={localBoundsPoints.map(point => `${point.x},${point.y}`).join(" ")}
                  className="location-map-space-boundary"
                />
              : localBoundsPoints.length === 2
                ? <polyline
                    points={localBoundsPoints.map(point => `${point.x},${point.y}`).join(" ")}
                    className="location-map-space-boundary"
                  />
                : <rect x=".45" y=".45" width="99.1" height="99.1" className="location-map-space-boundary" />}
            {priorityOrderedAreas.map(item => {
              const entity = world?.entities[item.id];
              const points = geometryPoints(entity);
              if (points.length < 2) return null;
              const offset = dragLocation?.id === item.id ? dragOffset : { x: 0, y: 0 };
              const rendered = points.map(point => ({
                x: clamp(point.x + offset.x),
                y: clamp(point.y + offset.y),
              }));
              return rendered.length >= 3
                ? <polygon
                    key={item.id}
                    points={rendered.map(point => `${point.x},${point.y}`).join(" ")}
                    className={`location-map-area${selectedId === item.id ? " selected" : ""}`}
                  />
                : <polyline
                    key={item.id}
                    points={rendered.map(point => `${point.x},${point.y}`).join(" ")}
                    className={`location-map-area degenerate${selectedId === item.id ? " selected" : ""}`}
                  />;
            })}
            {map.barriers.map(item => item.geometry?.points?.length ? <polyline
              key={item.id}
              points={item.geometry.points.map(point => `${point.x},${point.y}`).join(" ")}
              className={`location-map-barrier${item.hidden ? " hidden" : ""}`}
            /> : null)}
            {map.connections.map(item => {
              const source = resolvedAnchorPoint(anchors.get(item.source_anchor_id));
              const target = resolvedAnchorPoint(anchors.get(item.target_anchor_id));
              if (!source || !target) return null;
              return <g key={item.id}>
                <line
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  className="location-map-connection-hitbox"
                  onClick={event => {
                    event.stopPropagation();
                    setSelectedId(item.id);
                  }}
                />
                <line
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  className={`location-map-connection ${item.kind}${selectedId === item.id ? " selected" : ""}`}
                  onClick={event => {
                    event.stopPropagation();
                    setSelectedId(item.id);
                  }}
                />
              </g>;
            })}
            {areaDraft.length > 1 && <polyline
              points={areaDraft.map(point => `${point.x},${point.y}`).join(" ")}
              className="location-map-draft"
            />}
            {routePoints.length === 1 && <circle cx={routePoints[0].x} cy={routePoints[0].y} r="1.1" className="location-map-route-draft-point" />}
          </svg>

          {map.locations.map((item, index) => {
            const entity = world?.entities[item.id];
            const points = geometryPoints(entity);
            const base = points.length
              ? centroid(points)
              : { x: Number(item.x ?? 12 + (index * 11) % 75), y: Number(item.y ?? 16 + (index * 9) % 68) };
            const offset = dragLocation?.id === item.id ? dragOffset : { x: 0, y: 0 };
            const point = { x: clamp(base.x + offset.x), y: clamp(base.y + offset.y) };
            return <button
              key={item.id}
              className={`location-map-node ${entity?.state.spatial_kind === "area" ? "area-node" : "spot-node"}${selectedId === item.id ? " selected" : ""}`}
              style={{ left: `${point.x}%`, top: `${point.y}%` }}
              onClick={event => {
                if (tool === "route") return;
                event.stopPropagation();
                chooseLocation(item.id);
              }}
              onDoubleClick={event => {
                event.stopPropagation();
                if (tool === "select") setLayerId(item.id);
              }}
              onPointerDown={event => void beginLocationDrag(event, item.id)}
            >
              <b>{item.name}</b>
              <small>
                {item.spatial_kind ?? "spot"}
                {entity?.state.spatial_kind === "area" ? ` · p${areaPriority(entity)} · ${areaContents[item.id]?.length ?? 0} inside` : ""}
                {entity?.state.parent_location_id ? "" : " · root"}
              </small>
              {entity?.state.spatial_kind === "area" && (areaContents[item.id]?.length ?? 0) > 0 && <span className="location-map-node-contents">
                {areaContents[item.id].slice(0, 3).map(child => child.name).join(" · ")}
                {areaContents[item.id].length > 3 ? ` +${areaContents[item.id].length - 3}` : ""}
              </span>}
            </button>;
          })}

          {map.anchors.map((item, index) => {
            if ((item.binding_kind ?? "coordinate") !== "coordinate") return null;
            const point = resolvedAnchorPoint(item) ?? {
              x: Number(item.x ?? 8 + (index * 8) % 80),
              y: Number(item.y ?? 12 + (index * 7) % 75),
            };
            return <button
              key={item.id}
              className={`location-map-anchor ${item.kind}${selectedId === item.id ? " selected" : ""}`}
              style={{ left: `${point.x}%`, top: `${point.y}%` }}
              title={item.name}
              onClick={event => {
                if (tool === "route") return;
                event.stopPropagation();
                setSelectedId(item.id);
              }}
            >{item.kind === "entrance" || item.kind === "exit" ? "▮" : "◇"}</button>;
          })}

          {tool === "edit" && map.locations.flatMap(item => {
            const entity = world?.entities[item.id];
            const points = geometryPoints(entity);
            if (points.length < 2) return [];
            return points.flatMap((point, index) => {
              const next = points[(index + 1) % points.length];
              const shownPoint = vertexDrag?.locationId === item.id && vertexDrag.index === index && vertexPreview ? vertexPreview : point;
              const middle = { x: (point.x + next.x) / 2, y: (point.y + next.y) / 2 };
              return [
                <button
                  key={`${item.id}:vertex:${index}`}
                  className="location-map-vertex"
                  style={{ left: `${shownPoint.x}%`, top: `${shownPoint.y}%` }}
                  title="Drag vertex"
                  onPointerDown={event => {
                    if (event.button !== 0) return;
                    event.stopPropagation();
                    setSelectedId(item.id);
                    setVertexDrag({ locationId: item.id, index });
                    setVertexPreview(point);
                    event.currentTarget.setPointerCapture?.(event.pointerId);
                  }}
                  onContextMenu={event => {
                    event.preventDefault();
                    event.stopPropagation();
                    setSelectedId(item.id);
                    setVertexMenu({ mouseX: event.clientX + 2, mouseY: event.clientY - 6, locationId: item.id, index });
                  }}
                />,
                <button
                  key={`${item.id}:mid:${index}`}
                  className="location-map-midpoint"
                  style={{ left: `${middle.x}%`, top: `${middle.y}%` }}
                  title="Add vertex"
                  onClick={event => {
                    event.stopPropagation();
                    void insertVertex(item.id, index, middle);
                  }}
                />,
              ];
            });
          })}

          {areaDraft.map((point, index) => <span
            key={`draft-${index}`}
            className="location-map-draft-point"
            style={{ left: `${point.x}%`, top: `${point.y}%` }}
          />)}
        </div>
      </div>

      <aside className="location-map-inspector">
        {selectedLocation && editorDraft ? <>
          <section className="location-map-inspector-heading">
            <div>
              <p className="eyebrow">LOCATION</p>
              <h3>{selectedLocation.name}</h3>
            </div>
            <Chip size="small" label={editorDraft.spatial_kind} />
          </section>

          <EntityImageSurface
            asset={backgroundAsset}
            alt={`${selectedLocation.name} background`}
            className="location-map-background-surface"
            placeholder="Background"
            onGenerate={() => void generateBackground(false, null)}
            onGenerateWithPrompt={() => void generateBackground(true, null)}
            onRegenerate={asset => void generateBackground(false, asset)}
            onRegenerateWithPrompt={asset => void generateBackground(true, asset)}
            onDelete={asset => void deleteBackground(asset)}
            onUpload={file => void uploadBackground(file)}
            loading={imageBusy}
            loadingLabel="Working on background…"
          />

          <div className="location-map-inspector-form">
            <TextField
              size="small"
              label="Name"
              value={editorDraft.name}
              onChange={event => setEditorDraft({ ...editorDraft, name: event.target.value })}
            />
            <TextField
              size="small"
              multiline
              minRows={3}
              label="Description"
              value={editorDraft.description}
              onChange={event => setEditorDraft({ ...editorDraft, description: event.target.value })}
            />
            <TextField
              size="small"
              multiline
              minRows={2}
              label="Image generation description"
              value={editorDraft.imagegen_description}
              onChange={event => setEditorDraft({ ...editorDraft, imagegen_description: event.target.value })}
            />
            <TextField
              select
              size="small"
              label="Parent location"
              value={editorDraft.parent_location_id ?? ""}
              onChange={event => setEditorDraft({ ...editorDraft, parent_location_id: event.target.value || null })}
            >
              <MenuItem value="">No parent</MenuItem>
              {Object.values(world?.entities ?? {})
                .filter(item => item.kind === "location" && item.id !== selectedLocation.id && !item.state.archived)
                .map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
            </TextField>
            <TextField
              select
              size="small"
              label="Map representation"
              helperText="Canonical backend type: spot or area."
              value={editorDraft.spatial_kind}
              onChange={event => void convertLocationKind(selectedLocation, event.target.value as "spot" | "area")}
            >
              <MenuItem value="spot">Spot</MenuItem>
              <MenuItem value="area">Area</MenuItem>
            </TextField>
            <div className="location-map-two-column">
              <TextField select size="small" label="Topology" value={editorDraft.topology} onChange={event => setEditorDraft({ ...editorDraft, topology: event.target.value as EnvironmentLocation["topology"] })}>
                <MenuItem value="open">Open</MenuItem>
                <MenuItem value="closed">Closed / routed</MenuItem>
              </TextField>
              <TextField select size="small" label="Occupancy" value={editorDraft.occupancy} onChange={event => setEditorDraft({ ...editorDraft, occupancy: event.target.value as EnvironmentLocation["occupancy"] })}>
                <MenuItem value="direct_allowed">Direct occupancy allowed</MenuItem>
                <MenuItem value="child_required">Child required</MenuItem>
              </TextField>
              <TextField select size="small" label="Boundary access" value={editorDraft.boundary_access} onChange={event => setEditorDraft({ ...editorDraft, boundary_access: event.target.value as EnvironmentLocation["boundary_access"] })}>
                <MenuItem value="free">Free boundary</MenuItem>
                <MenuItem value="connection_required">Connection required</MenuItem>
              </TextField>
              <TextField select size="small" label="Exposure" value={editorDraft.exposure} onChange={event => setEditorDraft({ ...editorDraft, exposure: event.target.value as EnvironmentLocation["exposure"] })}>
                <MenuItem value="indoor">Indoor</MenuItem>
                <MenuItem value="outdoor">Outdoor</MenuItem>
                <MenuItem value="isolated">Isolated</MenuItem>
              </TextField>
              <TextField size="small" type="number" label="Minutes per map unit" value={editorDraft.minutes_per_unit} onChange={event => setEditorDraft({ ...editorDraft, minutes_per_unit: Number(event.target.value) })} />
              <TextField size="small" type="number" label="Visibility radius" value={editorDraft.base_visibility_units ?? ""} onChange={event => setEditorDraft({ ...editorDraft, base_visibility_units: event.target.value === "" ? null : Number(event.target.value) })} />
              <TextField size="small" type="number" label="Encounter rate" value={editorDraft.encounter_rate} onChange={event => setEditorDraft({ ...editorDraft, encounter_rate: Number(event.target.value) })} />
              {editorDraft.spatial_kind === "area" && <TextField
                size="small"
                type="number"
                label="Priority layer"
                helperText="Lower wins overlaps; ties use raw name, then id."
                value={editorDraft.priority_layer}
                onChange={event => setEditorDraft({ ...editorDraft, priority_layer: Number(event.target.value) })}
              />}
            </div>
            <div className="location-map-switches">
              <FormControlLabel control={<Switch size="small" checked={editorDraft.enabled} onChange={event => setEditorDraft({ ...editorDraft, enabled: event.target.checked })} />} label="Enabled" />
              <FormControlLabel control={<Switch size="small" checked={editorDraft.discovered} onChange={event => setEditorDraft({ ...editorDraft, discovered: event.target.checked })} />} label="Discovered" />
              <FormControlLabel control={<Switch size="small" checked={editorDraft.hidden} onChange={event => setEditorDraft({ ...editorDraft, hidden: event.target.checked })} />} label="Hidden" />
              <FormControlLabel control={<Switch size="small" checked={editorDraft.random_encounter} onChange={event => setEditorDraft({ ...editorDraft, random_encounter: event.target.checked })} />} label="Random encounter" />
            </div>
          </div>
          {editorDraft.spatial_kind === "area" && <section className="location-map-contents">
            <div className="location-map-contents-heading">
              <div><p className="eyebrow">CONTENTS</p><h4>Resolved contents</h4></div>
              <Chip size="small" label={areaContents[selectedLocation.id]?.length ?? 0} />
            </div>
            {(areaContents[selectedLocation.id] ?? []).length
              ? (areaContents[selectedLocation.id] ?? []).map(item => <div className="location-map-content-row" key={item.id}>
                  <span><b>{item.name}</b><small>{item.spatial_kind ?? "spot"}</small></span>
                  <small>Read only · double-click area to enter</small>
                </div>)
              : <p className="location-map-content-empty">No child locations are configured inside this area.</p>}
          </section>}
          <div className="location-map-inspector-actions">
            <FavoriteLibraryButton projectId={projectId} sourceKind="location" sourceKey={selectedLocation.id} compact={false} />
            <Button color="error" onClick={() => void deleteLocation(selectedLocation)}>Delete location</Button>
            <Button onClick={() => setEditorDraft(locationDraft(selectedLocation))}>Reset</Button>
            <Button variant="contained" onClick={() => void saveLocation(editorDraft)}>Save</Button>
          </div>
        </> : selectedConnection && connectionDraft ? <>
          <section className="location-map-inspector-heading">
            <div><p className="eyebrow">CONNECTION</p><h3>{connectionKindLabel(selectedConnection.kind)}</h3><small>backend kind: <code>{selectedConnection.kind}</code></small></div>
            <Chip size="small" label={connectionDraft.bidirectional ? "two-way" : "one-way"} />
          </section>
          <div className="location-map-route-endpoints">
            {([
              ["A", anchors.get(selectedConnection.source_anchor_id)],
              ["B", anchors.get(selectedConnection.target_anchor_id)],
            ] as const).map(([side, anchor]) => <div className="location-map-route-endpoint" key={side}>
              <b>Endpoint {side}</b>
              <span>{anchor?.name ?? "Missing anchor"}</span>
              <small>{(anchor?.binding_kind ?? "coordinate").replaceAll("_", " ")}{anchor?.binding_target_id && world?.entities[anchor.binding_target_id] ? ` · ${world.entities[anchor.binding_target_id].name}` : ""}</small>
              {anchor?.x != null && anchor?.y != null && <small>{round(anchor.x)}, {round(anchor.y)}</small>}
            </div>)}
          </div>
          <div className="location-map-inspector-form">
            <TextField
              select
              size="small"
              label="Connection type"
              value={connectionDraft.kind}
              onChange={event => setConnectionDraft({ ...connectionDraft, kind: event.target.value as SpatialConnection["kind"] })}
            >
              <MenuItem value="route">Route / shortcut</MenuItem>
              <MenuItem value="door">Door</MenuItem>
              <MenuItem value="portal">Portal / teleporter</MenuItem>
            </TextField>
            <TextField size="small" type="number" label="Travel minutes" value={connectionDraft.travelMinutes} onChange={event => setConnectionDraft({ ...connectionDraft, travelMinutes: Number(event.target.value) })} />
            <TextField size="small" label="Travel modes" helperText="Comma separated, e.g. walk, fly" value={connectionDraft.modes} onChange={event => setConnectionDraft({ ...connectionDraft, modes: event.target.value })} />
            <div className="location-map-switches">
              <FormControlLabel control={<Switch size="small" checked={connectionDraft.bidirectional} onChange={event => setConnectionDraft({ ...connectionDraft, bidirectional: event.target.checked })} />} label="Bidirectional" />
              <FormControlLabel control={<Switch size="small" checked={connectionDraft.enabled} onChange={event => setConnectionDraft({ ...connectionDraft, enabled: event.target.checked })} />} label="Enabled" />
              <FormControlLabel control={<Switch size="small" checked={connectionDraft.discovered} onChange={event => setConnectionDraft({ ...connectionDraft, discovered: event.target.checked })} />} label="Discovered" />
              <FormControlLabel control={<Switch size="small" checked={connectionDraft.hidden} onChange={event => setConnectionDraft({ ...connectionDraft, hidden: event.target.checked })} />} label="Hidden" />
              <FormControlLabel control={<Switch size="small" checked={connectionDraft.locked} onChange={event => setConnectionDraft({ ...connectionDraft, locked: event.target.checked })} />} label="Locked" />
            </div>
            {connectionDraft.locked && <div className="location-map-two-column">
              <TextField size="small" label="Lock minigame" value={connectionDraft.minigameKey} onChange={event => setConnectionDraft({ ...connectionDraft, minigameKey: event.target.value })} />
              <TextField size="small" type="number" label="Difficulty" value={connectionDraft.difficulty} onChange={event => setConnectionDraft({ ...connectionDraft, difficulty: Number(event.target.value) })} />
            </div>}
          </div>
          <div className="location-map-object-summary">
            <p><b>Source owner</b><span>{world?.entities[selectedConnection.source_location_id ?? ""]?.name ?? selectedConnection.source_location_id ?? "Map"}</span></p>
            <p><b>Target owner</b><span>{world?.entities[selectedConnection.target_location_id ?? ""]?.name ?? selectedConnection.target_location_id ?? "Map"}</span></p>
            <small>Endpoint bindings preserve whether each point is free, inside an area, on an area border, or attached to a spot.</small>
          </div>
          <div className="location-map-inspector-actions">
            <Button color="error" onClick={() => void deleteConnection(selectedConnection)}>Delete connection</Button>
            <Button variant="contained" onClick={() => void saveConnection(selectedConnection)}>Save route</Button>
          </div>
        </> : selectedSpatial ? <>
          <section className="location-map-inspector-heading">
            <div><p className="eyebrow">MAP OBJECT</p><h3>{"name" in selectedSpatial ? selectedSpatial.name : selectedSpatial.kind}</h3></div>
          </section>
          <div className="location-map-object-summary">
            {"kind" in selectedSpatial && <p><b>Type</b><span>{selectedSpatial.kind}</span></p>}
            {"blocked_modes" in selectedSpatial && <p><b>Blocks</b><span>{String((selectedSpatial as SpatialBarrier).blocked_modes ?? "walk")}</span></p>}
            {"binding_kind" in selectedSpatial && <p><b>Binding</b><span>{String((selectedSpatial as SpatialAnchor).binding_kind ?? "coordinate").replaceAll("_", " ")}</span></p>}
          </div>
          <div className="location-map-inspector-actions">
            {"blocked_modes" in selectedSpatial && <Button color="error" onClick={() => void deleteSpatialObject("barrier", selectedSpatial.id)}>Delete barrier</Button>}
            {"binding_kind" in selectedSpatial && <Button color="error" onClick={() => void deleteSpatialObject("anchor", selectedSpatial.id)}>Delete endpoint</Button>}
          </div>
        </> : <>
          <section className="location-map-inspector-heading">
            <div><p className="eyebrow">INSPECTOR</p><h3>Nothing selected</h3></div>
          </section>
          <div className="location-map-empty">
            <p>Click a spot or area to edit it.</p>
            <p>Double-click a location to enter its child layer.</p>
            <p>Parent/child hierarchy is separate from map geometry: children are shown on their parent layer, not drawn inside the parent's polygon.</p>
          </div>
        </>}

        <section className="location-map-validation">
          <h4>Validation</h4>
          {validation.length
            ? validation.map(message => <p key={message}>⚠ {message}</p>)
            : <p>No structural issues detected in this layer.</p>}
        </section>
      </aside>
    </div>

    <Menu
      open={Boolean(hitMenu)}
      onClose={() => setHitMenu(null)}
      anchorReference="anchorPosition"
      anchorPosition={hitMenu ? { top: hitMenu.mouseY, left: hitMenu.mouseX } : undefined}
    >
      {hitMenu?.candidates.map(candidate => <MenuItem
        key={candidate.id}
        onClick={() => {
          setSelectedId(candidate.id);
          setHitMenu(null);
        }}
      >
        <span className="location-map-hit-choice">
          <b>{candidate.label}</b>
          <small>{candidate.detail}</small>
        </span>
      </MenuItem>)}
    </Menu>

    <Menu
      open={Boolean(vertexMenu)}
      onClose={() => setVertexMenu(null)}
      anchorReference="anchorPosition"
      anchorPosition={vertexMenu ? { top: vertexMenu.mouseY, left: vertexMenu.mouseX } : undefined}
    >
      <MenuItem onClick={() => void createConnectedVertex()}>Create connected point</MenuItem>
      <MenuItem
        disabled={!vertexMenu || geometryPoints(world?.entities[vertexMenu.locationId]).length <= 2}
        onClick={() => vertexMenu && void removeVertex(vertexMenu.locationId, vertexMenu.index)}
      >
        Remove point
      </MenuItem>
    </Menu>

    <Dialog open={Boolean(routeDialog)} onClose={() => { setRouteDialog(null); setRoutePoints([]); }} fullWidth maxWidth="sm">
      <DialogTitle>Configure route endpoints</DialogTitle>
      <DialogContent>
        <div className="location-map-route-dialog">
          <p className="location-map-route-dialog-intro">Only map objects colliding with each placed endpoint are offered. Overlapping areas are ordered by priority, then raw name, then id.</p>
          {routeDialog && ([0, 1] as const).map(index => <section className="location-map-endpoint-choice" key={index}>
            <div><p className="eyebrow">ENDPOINT {index === 0 ? "A" : "B"}</p><b>{routeDialog.points[index].x}, {routeDialog.points[index].y}</b></div>
            <TextField
              select
              fullWidth
              size="small"
              label="Lock endpoint to"
              value={routeDialog.selections[index]}
              onChange={event => {
                const selections: [string, string] = [routeDialog.selections[0], routeDialog.selections[1]];
                selections[index] = event.target.value;
                setRouteDialog({ ...routeDialog, selections });
              }}
            >
              {routeDialog.options[index].map(option => <MenuItem key={option.key} value={option.key}>{option.label}</MenuItem>)}
            </TextField>
          </section>)}
          {routeDialog && <div className="location-map-route-dialog-settings">
            <TextField
              select
              size="small"
              label="Connection type"
              value={routeDialog.kind}
              onChange={event => setRouteDialog({ ...routeDialog, kind: event.target.value as SpatialConnection["kind"] })}
            >
              <MenuItem value="route">Route / shortcut</MenuItem>
              <MenuItem value="door">Door</MenuItem>
              <MenuItem value="portal">Portal / teleporter</MenuItem>
            </TextField>
            <TextField size="small" type="number" label="Travel minutes" value={routeDialog.travelMinutes} onChange={event => setRouteDialog({ ...routeDialog, travelMinutes: Number(event.target.value) })} />
            <TextField size="small" label="Modes" value={routeDialog.modes} onChange={event => setRouteDialog({ ...routeDialog, modes: event.target.value })} />
            <FormControlLabel control={<Switch checked={routeDialog.bidirectional} onChange={event => setRouteDialog({ ...routeDialog, bidirectional: event.target.checked })} />} label="Bidirectional" />
            <FormControlLabel control={<Switch checked={routeDialog.enabled} onChange={event => setRouteDialog({ ...routeDialog, enabled: event.target.checked })} />} label="Enabled" />
            <FormControlLabel control={<Switch checked={routeDialog.discovered} onChange={event => setRouteDialog({ ...routeDialog, discovered: event.target.checked })} />} label="Discovered" />
            <FormControlLabel control={<Switch checked={routeDialog.hidden} onChange={event => setRouteDialog({ ...routeDialog, hidden: event.target.checked })} />} label="Hidden" />
          </div>}
        </div>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => { setRouteDialog(null); setRoutePoints([]); }}>Cancel</Button>
        <Button variant="contained" onClick={() => void createConfiguredRoute()}>Create route</Button>
      </DialogActions>
    </Dialog>
  </div>;
}
