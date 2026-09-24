import { useCallback, useEffect, useMemo, useState } from "react";
import type { MouseEvent } from "react";
import { Button, ButtonGroup, Chip, MenuItem, Paper, TextField } from "@mui/material";
import { api } from "./api";
import type { WorldProjection } from "./types";

type Tool = "select" | "spot" | "area" | "anchor" | "barrier" | "route" | "door" | "portal";
type Point = { x: number; y: number };
type SpatialMap = {
  enabled: boolean; root_location_id: string | null; location_id?: string; topology?: "open" | "closed";
  blocked_reason?: string;
  locations: Array<{ id: string; name: string; parent_location_id?: string | null; topology?: string; occupancy?: string; boundary_access?: string; spatial_kind?: string; x?: number | null; y?: number | null; discovered?: boolean }>;
  anchors: Array<{ id: string; location_id: string; name: string; kind: string; x?: number | null; y?: number | null; hidden?: boolean; discovered?: boolean }>;
  connections: Array<{ id: string; kind: "route" | "door" | "portal"; source_anchor_id: string; target_anchor_id: string; travel_minutes: number; lock?: { locked?: boolean } }>;
  barriers: Array<{ id: string; name: string; location_id: string; hidden?: boolean; discovered?: boolean; geometry?: { points?: Point[] } }>;
};

const tools: Tool[] = ["select", "spot", "area", "anchor", "barrier", "route", "door", "portal"];
const screenPoint = (event: MouseEvent<HTMLElement>): Point => { const rect = event.currentTarget.getBoundingClientRect(); return { x: Math.round(((event.clientX - rect.left) / rect.width) * 1000) / 10, y: Math.round(((event.clientY - rect.top) / rect.height) * 1000) / 10 }; };

export function LocationMapStudio({ projectId, revision, fail }: { projectId: string; revision: number; fail: (message: string) => void }) {
  const [map, setMap] = useState<SpatialMap | null>(null);
  const [world, setWorld] = useState<WorldProjection | null>(null);
  const [layerId, setLayerId] = useState<string | null>(null);
  const [tool, setTool] = useState<Tool>("select");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [connectionStart, setConnectionStart] = useState<string | null>(null);
  const [barrierPoints, setBarrierPoints] = useState<Point[]>([]);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [drag, setDrag] = useState<Point | null>(null);

  const load = useCallback(async () => {
    const [nextMap, nextWorld] = await Promise.all([
      api<SpatialMap>(`/projects/${projectId}/spatial/map${layerId ? `?location_id=${layerId}` : ""}`),
      api<WorldProjection>(`/projects/${projectId}/world`),
    ]);
    setMap(nextMap); setWorld(nextWorld);
    if (!layerId && nextMap.root_location_id) setLayerId(nextMap.root_location_id);
  }, [projectId, layerId]);
  useEffect(() => { void load().catch(cause => fail(String(cause))); }, [load, revision, fail]);

  const location = layerId ? world?.entities[layerId] : null;
  const breadcrumbs = useMemo(() => { const result: Array<{ id: string; name: string }> = []; const seen = new Set<string>(); let current = location; while (current && !seen.has(current.id)) { seen.add(current.id); result.unshift({ id: current.id, name: current.name }); current = world?.entities[String(current.state.parent_location_id || "")]; } return result; }, [location, world]);
  const validation = useMemo(() => {
    if (!world) return [];
    const locations = Object.values(world.entities).filter(item => item.kind === "location" && !item.state.archived);
    const ids = new Set(locations.map(item => item.id));
    const messages: string[] = [];
    if (!map?.root_location_id) messages.push("Missing world root: placement and travel are disabled.");
    locations.forEach(item => { const parent = String(item.state.parent_location_id || ""); if (parent && !ids.has(parent)) messages.push(`${item.name} has an unavailable parent.`); if (item.state.occupancy === "child_required" && !locations.some(child => child.state.parent_location_id === item.id)) messages.push(`${item.name} requires a child but has none.`); });
    map?.anchors.filter(item => item.x == null || item.y == null).forEach(item => messages.push(`${item.name} needs map review: its position is incomplete.`));
    return messages;
  }, [map, world]);

  async function migrate() { await api(`/projects/${projectId}/spatial/migrate`, { method: "POST" }); await load(); }
  async function createRoot() { const name = window.prompt("Root location name", "World")?.trim(); if (!name) return; await api(`/projects/${projectId}/spatial/root`, { method: "POST", body: JSON.stringify({ name, topology: "closed", occupancy: "child_required", extend_scope: true }) }); setLayerId(null); await load(); }
  async function createLocation(point: Point, kind: "spot" | "area") { if (!layerId) return; const name = window.prompt(`${kind === "area" ? "Area" : "Spot"} name`)?.trim(); if (!name) return; await api(`/projects/${projectId}/environment/locations`, { method: "POST", body: JSON.stringify({ name, parent_location_id: layerId, exposure: "outdoor", description: "", imagegen_description: "", tags: [], image_tags: [], enabled: true, random_encounter: false, hidden: false, discovered: true, x: point.x, y: point.y, topology: kind === "area" ? "open" : "closed", occupancy: "direct_allowed", boundary_access: "free", spatial_kind: kind, minutes_per_unit: 1, base_visibility_units: null, encounter_rate: 0 }) }); await load(); }
  async function createAnchor(point: Point) { if (!layerId) return; const name = window.prompt("Anchor name")?.trim(); if (!name) return; await api(`/projects/${projectId}/spatial/anchors`, { method: "PUT", body: JSON.stringify({ location_id: layerId, name, kind: "waypoint", x: point.x, y: point.y }) }); await load(); }
  async function finishBarrier() { if (!layerId || barrierPoints.length < 2) return; const name = window.prompt("Barrier name", "Obstacle")?.trim(); if (!name) return; await api(`/projects/${projectId}/spatial/barriers`, { method: "PUT", body: JSON.stringify({ location_id: layerId, name, blocked_modes: ["walk"], geometry: { location_id: layerId, kind: barrierPoints.length > 2 ? "polygon" : "polyline", points: barrierPoints } }) }); setBarrierPoints([]); setTool("select"); await load(); }
  async function chooseAnchor(anchorId: string) { if (!["route", "door", "portal"].includes(tool)) { setSelectedId(anchorId); return; } if (!connectionStart) { setConnectionStart(anchorId); return; } if (connectionStart === anchorId) { setConnectionStart(null); return; } await api(`/projects/${projectId}/spatial/connections`, { method: "PUT", body: JSON.stringify({ kind: tool, source_anchor_id: connectionStart, target_anchor_id: anchorId, travel_minutes: 0, modes: ["walk"], bidirectional: true }) }); setConnectionStart(null); setTool("select"); await load(); }
  function canvasClick(event: MouseEvent<HTMLDivElement>) { const point = screenPoint(event); if (tool === "spot" || tool === "area") void createLocation(point, tool); else if (tool === "anchor") void createAnchor(point); else if (tool === "barrier") setBarrierPoints(current => [...current, point]); }

  if (!map) return <p>Loading location map…</p>;
  if (!map.enabled) return <Paper className="panel"><h2>Location Map</h2><p>Create a root to enable mapping and travel. Weather, time, ambient sound, and music remain available without one.</p><Button onClick={() => void migrate()}>Adopt existing locations</Button><Button onClick={() => void createRoot()}>Create world root</Button></Paper>;
  const selected = map.locations.find(item => item.id === selectedId) ?? map.anchors.find(item => item.id === selectedId) ?? map.barriers.find(item => item.id === selectedId);
  return <div className="location-map-studio">
    <Paper className="panel"><div className="sheet-heading"><div><h2>Location Map</h2><div>{breadcrumbs.map(item => <Button size="small" key={item.id} onClick={() => setLayerId(item.id)}>{item.name}</Button>)}</div></div><Chip label={`${map.topology ?? "closed"} layer`} color={map.topology === "open" ? "success" : "default"} /></div>
      <ButtonGroup size="small" sx={{ flexWrap: "wrap" }}>{tools.map(item => <Button variant={tool === item ? "contained" : "outlined"} key={item} onClick={() => { setTool(item); setBarrierPoints([]); setConnectionStart(null); }}>{item}</Button>)}</ButtonGroup>{tool === "barrier" && <Button disabled={barrierPoints.length < 2} onClick={() => void finishBarrier()}>Finish barrier ({barrierPoints.length})</Button>}
    </Paper>
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 300px", gap: 16 }}>
      <div style={{ height: 620, overflow: "hidden", border: "1px solid var(--border-color)", touchAction: "none", position: "relative" }} onWheel={event => { event.preventDefault(); setZoom(value => Math.max(.5, Math.min(3, value - event.deltaY * .001))); }} onPointerDown={event => setDrag({ x: event.clientX - pan.x, y: event.clientY - pan.y })} onPointerMove={event => { if (drag && tool === "select") setPan({ x: event.clientX - drag.x, y: event.clientY - drag.y }); }} onPointerUp={() => setDrag(null)}>
        <div onClick={canvasClick} style={{ position: "absolute", inset: 0, transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transformOrigin: "0 0", backgroundImage: "linear-gradient(#8882 1px,transparent 1px),linear-gradient(90deg,#8882 1px,transparent 1px)", backgroundSize: "25px 25px" }}>
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}>{map.barriers.map(item => item.geometry?.points?.length ? <polyline key={item.id} points={item.geometry.points.map(point => `${point.x},${point.y}`).join(" ")} fill="none" stroke={item.hidden ? "#888" : "#d55"} strokeDasharray={item.hidden ? "3 2" : undefined} /> : null)}{barrierPoints.length > 1 && <polyline points={barrierPoints.map(point => `${point.x},${point.y}`).join(" ")} fill="none" stroke="#e90" />}</svg>
          {map.locations.map((item, index) => <button key={item.id} onClick={event => { event.stopPropagation(); setSelectedId(item.id); }} onDoubleClick={() => setLayerId(item.id)} style={{ position: "absolute", left: `${item.x ?? 10 + index * 8}%`, top: `${item.y ?? 15 + index * 7}%` }}>{item.name}<small style={{ display: "block" }}>{item.spatial_kind} · {item.occupancy}</small></button>)}
          {map.anchors.map((item, index) => <button aria-label={`Anchor ${item.name}`} key={item.id} onClick={event => { event.stopPropagation(); void chooseAnchor(item.id); }} style={{ position: "absolute", left: `${item.x ?? 5 + index * 6}%`, top: `${item.y ?? 8 + index * 6}%`, borderRadius: "50%" }}>{connectionStart === item.id ? "◎" : "◇"}</button>)}
        </div>
      </div>
      <div><Paper className="panel"><h3>Inspector</h3>{selected ? <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(selected, null, 2)}</pre> : <p>Select a map object. Double-click a location to enter its layer.</p>}<TextField select fullWidth size="small" label="Zoom" value={zoom} onChange={event => setZoom(Number(event.target.value))}>{[.5, 1, 1.5, 2, 3].map(value => <MenuItem key={value} value={value}>{value}×</MenuItem>)}</TextField></Paper><Paper className="panel"><h3>Validation</h3>{validation.length ? validation.map(message => <p key={message}>⚠ {message}</p>) : <p>No structural issues detected in this layer.</p>}</Paper></div>
    </div>
  </div>;
}
