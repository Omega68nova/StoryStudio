import { useCallback, useEffect, useMemo, useState } from "react";
import type { MouseEvent, PointerEvent as ReactPointerEvent } from "react";
import {
  Button,
  ButtonGroup,
  Chip,
  FormControlLabel,
  MenuItem,
  Paper,
  Switch,
  TextField,
} from "@mui/material";
import { api } from "./api";
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
  x?: number | null;
  y?: number | null;
  discovered?: boolean;
};
type SpatialAnchor = {
  id: string;
  location_id: string;
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
  bidirectional?: boolean;
  lock?: { locked?: boolean };
};
type SpatialBarrier = {
  id: string;
  name: string;
  location_id: string;
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

const clamp = (value: number) => Math.max(0, Math.min(100, value));
const round = (value: number) => Math.round(value * 10) / 10;
const centroid = (points: Point[]): Point => {
  if (!points.length) return { x: 50, y: 50 };
  return {
    x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
    y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
  };
};
const distance = (left: Point, right: Point) => Math.hypot(left.x - right.x, left.y - right.y);
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
  const [routeStartId, setRouteStartId] = useState<string | null>(null);
  const [areaDraft, setAreaDraft] = useState<Point[]>([]);
  const [zoom, setZoom] = useState(1);
  const [dragLocation, setDragLocation] = useState<DragLocation | null>(null);
  const [dragOffset, setDragOffset] = useState<Point>({ x: 0, y: 0 });
  const [vertexDrag, setVertexDrag] = useState<VertexDrag | null>(null);
  const [vertexPreview, setVertexPreview] = useState<Point | null>(null);
  const [editorDraft, setEditorDraft] = useState<EnvironmentLocation | null>(null);
  const [backgrounds, setBackgrounds] = useState<BackgroundRecord[]>([]);
  const [imageBusy, setImageBusy] = useState(false);

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
    });
    map?.anchors.filter(item => item.x == null || item.y == null).forEach(item => {
      messages.push(`${item.name} needs map review: its position is incomplete.`);
    });
    return messages;
  }, [map, world]);

  const selectedSpatial = map?.anchors.find(item => item.id === selectedId)
    ?? map?.barriers.find(item => item.id === selectedId)
    ?? map?.connections.find(item => item.id === selectedId)
    ?? null;

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
        exposure: "outdoor",
        description: "",
        imagegen_description: "",
        tags: [],
        image_tags: [],
        enabled: true,
        random_encounter: false,
        hidden: false,
        discovered: true,
        x: point.x,
        y: point.y,
        topology: "closed",
        occupancy: "direct_allowed",
        boundary_access: "free",
        spatial_kind: "spot",
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
      if (areaDraft.length < 3) return;
      const name = window.prompt("Area name")?.trim();
      if (!name) return;
      const center = centroid(areaDraft);
      await api(`/projects/${projectId}/environment/locations`, {
        method: "POST",
        body: JSON.stringify({
          name,
          parent_location_id: layerId,
          exposure: "outdoor",
          description: "",
          imagegen_description: "",
          tags: [],
          image_tags: [],
          enabled: true,
          random_encounter: false,
          hidden: false,
          discovered: true,
          x: round(center.x),
          y: round(center.y),
          topology: "open",
          occupancy: "direct_allowed",
          boundary_access: "free",
          spatial_kind: "area",
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

  async function createRoute(sourceId: string, targetId: string) {
    const source = world?.entities[sourceId];
    const target = world?.entities[targetId];
    if (!source || !target) return;
    const sourcePoints = geometryPoints(source);
    const targetPoints = geometryPoints(target);
    const sourcePoint = sourcePoints.length ? centroid(sourcePoints) : {
      x: Number(source.state.x ?? 50),
      y: Number(source.state.y ?? 50),
    };
    const targetPoint = targetPoints.length ? centroid(targetPoints) : {
      x: Number(target.state.x ?? 50),
      y: Number(target.state.y ?? 50),
    };
    const [sourceAnchor, targetAnchor] = await Promise.all([
      api<{ id: string }>(`/projects/${projectId}/spatial/anchors`, {
        method: "PUT",
        body: JSON.stringify({
          location_id: sourceId,
          name: `${source.name} route`,
          kind: "waypoint",
          x: sourcePoint.x,
          y: sourcePoint.y,
        }),
      }),
      api<{ id: string }>(`/projects/${projectId}/spatial/anchors`, {
        method: "PUT",
        body: JSON.stringify({
          location_id: targetId,
          name: `${target.name} route`,
          kind: "waypoint",
          x: targetPoint.x,
          y: targetPoint.y,
        }),
      }),
    ]);
    const direction = window.prompt("Route direction", "bidirectional")?.trim().toLocaleLowerCase();
    if (direction == null) return;
    await api(`/projects/${projectId}/spatial/connections`, {
      method: "PUT",
      body: JSON.stringify({
        kind: "route",
        source_anchor_id: sourceAnchor.id,
        target_anchor_id: targetAnchor.id,
        travel_minutes: 0,
        modes: ["walk"],
        bidirectional: direction !== "one-way" && direction !== "oneway",
      }),
    });
    setRouteStartId(null);
    setTool("select");
    await load();
  }

  async function chooseLocation(id: string) {
    if (tool !== "route") {
      setSelectedId(id);
      return;
    }
    if (!routeStartId) {
      setRouteStartId(id);
      setSelectedId(id);
      return;
    }
    if (routeStartId === id) {
      setRouteStartId(null);
      return;
    }
    await createRoute(routeStartId, id);
  }

  async function beginLocationDrag(event: ReactPointerEvent<HTMLElement>, id: string) {
    if (tool !== "drag" || !world) return;
    event.stopPropagation();
    const entity = world.entities[id];
    if (!entity) return;
    const host = event.currentTarget.closest(".location-map-canvas") as HTMLElement | null;
    if (!host) return;
    const start = canvasPoint(event.clientX, event.clientY, host);
    const points = geometryPoints(entity);
    const base = points.length ? centroid(points) : { x: Number(entity.state.x ?? start.x), y: Number(entity.state.y ?? start.y) };
    setDragLocation({
      id,
      start,
      x: Number(entity.state.x ?? base.x),
      y: Number(entity.state.y ?? base.y),
      footprint: points,
    });
    setDragOffset({ x: 0, y: 0 });
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  async function finishLocationDrag() {
    if (!dragLocation || !world) return;
    const entity = world.entities[dragLocation.id];
    if (!entity) return;
    const next = locationDraft(entity);
    next.x = clamp(round(dragLocation.x + dragOffset.x));
    next.y = clamp(round(dragLocation.y + dragOffset.y));
    if (dragLocation.footprint.length) {
      next.footprint = {
        location_id: layerId,
        kind: dragLocation.footprint.length >= 3 ? "polygon" : dragLocation.footprint.length === 1 ? "point" : "polyline",
        points: dragLocation.footprint.map(point => ({
          x: clamp(round(point.x + dragOffset.x)),
          y: clamp(round(point.y + dragOffset.y)),
        })),
      };
    }
    setDragLocation(null);
    setDragOffset({ x: 0, y: 0 });
    await saveLocation(next);
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

  function canvasClick(event: MouseEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget && (event.target as HTMLElement).closest("button")) return;
    const point = canvasPoint(event.clientX, event.clientY, event.currentTarget);
    if (tool === "spot") void createSpot(point);
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
    setRouteStartId(null);
    setDragLocation(null);
    setVertexDrag(null);
  }

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
        {tool === "area" && areaDraft.length >= 3 && <Button size="small" variant="outlined" onClick={() => void finishArea(true)}>
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
        className={`location-map-canvas tool-${tool}`}
        onClick={canvasClick}
        onWheel={event => {
          event.preventDefault();
          setZoom(value => Math.max(.5, Math.min(2, round(value - event.deltaY * .001))));
        }}
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
            {map.locations.map(item => {
              const entity = world?.entities[item.id];
              const points = geometryPoints(entity);
              if (points.length < 3) return null;
              const offset = dragLocation?.id === item.id ? dragOffset : { x: 0, y: 0 };
              const rendered = points.map(point => ({
                x: clamp(point.x + offset.x),
                y: clamp(point.y + offset.y),
              }));
              return <polygon
                key={item.id}
                points={rendered.map(point => `${point.x},${point.y}`).join(" ")}
                className={`location-map-area${selectedId === item.id ? " selected" : ""}`}
              />;
            })}
            {map.barriers.map(item => item.geometry?.points?.length ? <polyline
              key={item.id}
              points={item.geometry.points.map(point => `${point.x},${point.y}`).join(" ")}
              className={`location-map-barrier${item.hidden ? " hidden" : ""}`}
            /> : null)}
            {map.connections.map(item => {
              const source = anchors.get(item.source_anchor_id);
              const target = anchors.get(item.target_anchor_id);
              if (!source || !target || source.x == null || source.y == null || target.x == null || target.y == null) return null;
              return <line
                key={item.id}
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                className={`location-map-connection ${item.kind}${selectedId === item.id ? " selected" : ""}`}
              />;
            })}
            {areaDraft.length > 1 && <polyline
              points={areaDraft.map(point => `${point.x},${point.y}`).join(" ")}
              className="location-map-draft"
            />}
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
              className={`location-map-node ${points.length >= 3 ? "area-node" : "spot-node"}${selectedId === item.id ? " selected" : ""}${routeStartId === item.id ? " route-start" : ""}`}
              style={{ left: `${point.x}%`, top: `${point.y}%` }}
              onClick={event => {
                event.stopPropagation();
                void chooseLocation(item.id);
              }}
              onDoubleClick={event => {
                event.stopPropagation();
                if (tool === "select") setLayerId(item.id);
              }}
              onPointerDown={event => void beginLocationDrag(event, item.id)}
            >
              <b>{item.name}</b>
              <small>{item.spatial_kind ?? "spot"}{entity?.state.parent_location_id ? "" : " · root"}</small>
            </button>;
          })}

          {map.anchors.map((item, index) => {
            const x = Number(item.x ?? 8 + (index * 8) % 80);
            const y = Number(item.y ?? 12 + (index * 7) % 75);
            return <button
              key={item.id}
              className={`location-map-anchor ${item.kind}${selectedId === item.id ? " selected" : ""}`}
              style={{ left: `${x}%`, top: `${y}%` }}
              title={item.name}
              onClick={event => {
                event.stopPropagation();
                setSelectedId(item.id);
              }}
            >{item.kind === "entrance" || item.kind === "exit" ? "▮" : "◇"}</button>;
          })}

          {tool === "edit" && map.locations.flatMap(item => {
            const entity = world?.entities[item.id];
            const points = geometryPoints(entity);
            if (points.length < 3) return [];
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
                    event.stopPropagation();
                    setSelectedId(item.id);
                    setVertexDrag({ locationId: item.id, index });
                    setVertexPreview(point);
                    event.currentTarget.setPointerCapture?.(event.pointerId);
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
            </div>
            <div className="location-map-switches">
              <FormControlLabel control={<Switch size="small" checked={editorDraft.enabled} onChange={event => setEditorDraft({ ...editorDraft, enabled: event.target.checked })} />} label="Enabled" />
              <FormControlLabel control={<Switch size="small" checked={editorDraft.discovered} onChange={event => setEditorDraft({ ...editorDraft, discovered: event.target.checked })} />} label="Discovered" />
              <FormControlLabel control={<Switch size="small" checked={editorDraft.random_encounter} onChange={event => setEditorDraft({ ...editorDraft, random_encounter: event.target.checked })} />} label="Random encounter" />
            </div>
          </div>
          <div className="location-map-inspector-actions">
            <Button onClick={() => setEditorDraft(locationDraft(selectedLocation))}>Reset</Button>
            <Button variant="contained" onClick={() => void saveLocation(editorDraft)}>Save</Button>
          </div>
        </> : selectedSpatial ? <>
          <section className="location-map-inspector-heading">
            <div><p className="eyebrow">MAP OBJECT</p><h3>{"name" in selectedSpatial ? selectedSpatial.name : selectedSpatial.kind}</h3></div>
          </section>
          <div className="location-map-object-summary">
            {"kind" in selectedSpatial && <p><b>Type</b><span>{selectedSpatial.kind}</span></p>}
            {"travel_minutes" in selectedSpatial && <p><b>Travel</b><span>{selectedSpatial.travel_minutes} min</span></p>}
            {"blocked_modes" in selectedSpatial && <p><b>Blocks</b><span>{String((selectedSpatial as any).blocked_modes ?? "walk")}</span></p>}
            <small>Detailed route, door, portal, barrier and lock editors can plug into this inspector without changing the map canvas.</small>
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
  </div>;
}
