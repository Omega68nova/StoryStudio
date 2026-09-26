import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Chip, Paper, Stack } from "@mui/material";
import { api } from "./api";
import type { WorldEntity, WorldProjection } from "./types";

type Point = [number, number];
type Geometry =
  | { type: "Point"; coordinates: Point }
  | { type: "LineString"; coordinates: Point[] }
  | { type: "MultiLineString"; coordinates: Point[][] }
  | { type: "Polygon"; coordinates: Point[][] }
  | { type: "MultiPolygon"; coordinates: Point[][][] };

type Feature = {
  id: string;
  navigation_space_id: string;
  semantic_location_id: string | null;
  feature_kind: "surface" | "corridor" | "barrier" | "connector" | "spot";
  name: string;
  geometry: Geometry;
  hidden: boolean;
  enabled: boolean;
  properties: Record<string, any>;
};

type Space = {
  id: string;
  owner_location_id: string | null;
  navigation_mode: "free" | "routed";
};

type SpaceDetails = {
  space: Space;
  features: Feature[];
};

const PLAYER_RADIUS = 1.3;
const MOVE_SPEED = 18;
const INTERACT_DISTANCE = 5;

function pointInRing(point: Point, ring: Point[]) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    const intersects = ((yi > point[1]) !== (yj > point[1]))
      && (point[0] < ((xj - xi) * (point[1] - yi)) / ((yj - yi) || 1e-9) + xi);
    if (intersects) inside = !inside;
  }
  return inside;
}

function pointInGeometry(point: Point, geometry: Geometry) {
  if (geometry.type === "Polygon") {
    const [outer, ...holes] = geometry.coordinates;
    return Boolean(outer?.length) && pointInRing(point, outer) && !holes.some(ring => pointInRing(point, ring));
  }
  if (geometry.type === "MultiPolygon") {
    return geometry.coordinates.some(polygon => {
      const [outer, ...holes] = polygon;
      return Boolean(outer?.length) && pointInRing(point, outer) && !holes.some(ring => pointInRing(point, ring));
    });
  }
  return false;
}

function pointSegmentDistance(point: Point, a: Point, b: Point) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const length = dx * dx + dy * dy;
  const t = length ? Math.max(0, Math.min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length)) : 0;
  const x = a[0] + t * dx, y = a[1] + t * dy;
  return Math.hypot(point[0] - x, point[1] - y);
}

function linesOf(geometry: Geometry): Point[][] {
  if (geometry.type === "LineString") return [geometry.coordinates];
  if (geometry.type === "MultiLineString") return geometry.coordinates;
  return [];
}

function corridorContains(point: Point, feature: Feature) {
  if (feature.geometry.type !== "LineString" && feature.geometry.type !== "MultiLineString") return false;
  const radius = Math.max(.5, Number(feature.properties.width ?? 4) / 2);
  return linesOf(feature.geometry).some(line =>
    line.slice(0, -1).some((start, index) => pointSegmentDistance(point, start, line[index + 1]) <= radius)
  );
}

function orientation(a: Point, b: Point, c: Point) {
  return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}

function segmentsIntersect(a: Point, b: Point, c: Point, d: Point) {
  const o1 = orientation(a, b, c), o2 = orientation(a, b, d);
  const o3 = orientation(c, d, a), o4 = orientation(c, d, b);
  if (((o1 > 0 && o2 < 0) || (o1 < 0 && o2 > 0)) && ((o3 > 0 && o4 < 0) || (o3 < 0 && o4 > 0))) return true;
  const eps = 1e-7;
  const on = (p: Point, q: Point, r: Point) => Math.abs(orientation(p, q, r)) < eps
    && q[0] >= Math.min(p[0], r[0]) - eps && q[0] <= Math.max(p[0], r[0]) + eps
    && q[1] >= Math.min(p[1], r[1]) - eps && q[1] <= Math.max(p[1], r[1]) + eps;
  return on(a, c, b) || on(a, d, b) || on(c, a, d) || on(c, b, d);
}

function crossesBarrier(from: Point, to: Point, barriers: Feature[]) {
  return barriers.some(feature => linesOf(feature.geometry).some(line =>
    line.slice(0, -1).some((start, index) => segmentsIntersect(from, to, start, line[index + 1]))
  ));
}

function clampPoint(point: Point): Point {
  return [Math.max(0, Math.min(100, point[0])), Math.max(0, Math.min(100, point[1]))];
}

function featureCenter(feature: Feature): Point {
  if (feature.geometry.type === "Point") return feature.geometry.coordinates;
  const points = feature.geometry.type === "LineString" ? feature.geometry.coordinates
    : feature.geometry.type === "MultiLineString" ? feature.geometry.coordinates.flat()
    : feature.geometry.type === "Polygon" ? feature.geometry.coordinates[0] ?? []
    : feature.geometry.coordinates[0]?.[0] ?? [];
  if (!points.length) return [50, 50];
  return [
    points.reduce((sum, point) => sum + point[0], 0) / points.length,
    points.reduce((sum, point) => sum + point[1], 0) / points.length,
  ];
}

function nameOf(feature: Feature, locations: Map<string, WorldEntity>) {
  if (feature.semantic_location_id) {
    return (locations.get(feature.semantic_location_id)?.name ?? feature.name) || feature.feature_kind;
  }
  return feature.name || feature.feature_kind;
}

export function SpatialPlaytestPage({
  projectId,
  initialSpaceId,
}: {
  projectId: string;
  initialSpaceId: string;
}) {
  const [world, setWorld] = useState<WorldProjection | null>(null);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [details, setDetails] = useState<Record<string, SpaceDetails>>({});
  const [spaceId, setSpaceId] = useState(initialSpaceId);
  const [player, setPlayer] = useState<Point>([50, 50]);
  const [message, setMessage] = useState("WASD to move · E to interact");
  const [error, setError] = useState("");
  const keys = useRef(new Set<string>());
  const lastTime = useRef<number | null>(null);

  const locations = useMemo(
    () => new Map(Object.values(world?.entities ?? {}).filter((item: WorldEntity) => item.kind === "location").map(item => [item.id, item])),
    [world],
  );

  const load = useCallback(async () => {
    const [nextWorld, nextSpaces] = await Promise.all([
      api<WorldProjection>(`/projects/${projectId}/world`),
      api<Space[]>(`/projects/${projectId}/spatial-v3/spaces`),
    ]);
    const pairs = await Promise.all(nextSpaces.map(async space => [
      space.id,
      await api<SpaceDetails>(`/projects/${projectId}/spatial-v3/spaces/${space.id}`),
    ] as const));
    setWorld(nextWorld);
    setSpaces(nextSpaces);
    setDetails(Object.fromEntries(pairs));
    if (!nextSpaces.some(space => space.id === initialSpaceId) && nextSpaces[0]) setSpaceId(nextSpaces[0].id);
  }, [projectId, initialSpaceId]);

  useEffect(() => { void load().catch(cause => setError(String(cause))); }, [load]);

  const current = details[spaceId];
  const features = useMemo(
    () => current?.features.filter(feature => feature.enabled && !feature.hidden) ?? [],
    [current],
  );
  const barriers = useMemo(
    () => features.filter(feature => feature.feature_kind === "barrier"),
    [features],
  );

  const canOccupy = useCallback((point: Point) => {
    if (!current) return false;
    if (current.space.navigation_mode === "free") return true;
    return features.some(feature =>
      feature.feature_kind === "surface" ? pointInGeometry(point, feature.geometry)
      : feature.feature_kind === "corridor" ? corridorContains(point, feature)
      : false
    );
  }, [current, features]);

  const enterSpace = useCallback((targetSpaceId: string, targetPoint: Point = [50, 50], reason = "Entered") => {
    if (!details[targetSpaceId]) return;
    setSpaceId(targetSpaceId);
    setPlayer(clampPoint(targetPoint));
    setMessage(`${reason} ${locations.get(details[targetSpaceId].space.owner_location_id ?? "")?.name ?? targetSpaceId}`);
  }, [details, locations]);

  const interact = useCallback(() => {
    if (!current) return;
    const candidates: Array<{ distance: number; action: () => void }> = [];

    for (const feature of features) {
      const center = featureCenter(feature);
      const distance = Math.hypot(center[0] - player[0], center[1] - player[1]);
      if (feature.feature_kind === "connector" && distance <= INTERACT_DISTANCE) {
        const targetSpaceId = String(feature.properties.target?.navigation_space_id ?? "");
        const targetPoint = (feature.properties.target?.point ?? [50, 50]) as Point;
        if (targetSpaceId && details[targetSpaceId]) {
          candidates.push({
            distance,
            action: () => enterSpace(targetSpaceId, targetPoint, `Used ${nameOf(feature, locations)} →`),
          });
        }
      }

      if (feature.semantic_location_id) {
        const childSpace = spaces.find(space => space.owner_location_id === feature.semantic_location_id && space.id !== spaceId);
        const insideOrNear = feature.feature_kind === "surface"
          ? pointInGeometry(player, feature.geometry) || distance <= INTERACT_DISTANCE
          : distance <= INTERACT_DISTANCE;
        if (childSpace && insideOrNear) {
          candidates.push({
            distance: pointInGeometry(player, feature.geometry) ? 0 : distance,
            action: () => enterSpace(childSpace.id, [50, 50], "Entered"),
          });
        }
      }
    }

    for (const [otherSpaceId, other] of Object.entries(details)) {
      if (otherSpaceId === spaceId) continue;
      for (const feature of other.features) {
        if (feature.feature_kind !== "connector" || feature.properties.target?.navigation_space_id !== spaceId) continue;
        const targetPoint = feature.properties.target?.point as Point | undefined;
        if (!targetPoint) continue;
        const distance = Math.hypot(targetPoint[0] - player[0], targetPoint[1] - player[1]);
        if (distance <= INTERACT_DISTANCE) {
          const sourcePoint = (feature.properties.source?.point ?? featureCenter(feature)) as Point;
          candidates.push({
            distance,
            action: () => enterSpace(otherSpaceId, sourcePoint, `Used ${nameOf(feature, locations)} →`),
          });
        }
      }
    }

    candidates.sort((a, b) => a.distance - b.distance);
    if (candidates[0]) candidates[0].action();
    else setMessage("Nothing nearby to interact with.");
  }, [current, details, enterSpace, features, locations, player, spaceId, spaces]);

  useEffect(() => {
    const down = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if (["w", "a", "s", "d", "e"].includes(key)) event.preventDefault();
      keys.current.add(key);
      if (key === "e" && !event.repeat) interact();
    };
    const up = (event: KeyboardEvent) => keys.current.delete(event.key.toLowerCase());
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [interact]);

  useEffect(() => {
    let frame = 0;
    const tick = (time: number) => {
      const previous = lastTime.current ?? time;
      lastTime.current = time;
      const dt = Math.min(.05, Math.max(0, (time - previous) / 1000));
      let dx = 0, dy = 0;
      if (keys.current.has("a")) dx -= 1;
      if (keys.current.has("d")) dx += 1;
      if (keys.current.has("w")) dy -= 1;
      if (keys.current.has("s")) dy += 1;
      if (dx || dy) {
        const length = Math.hypot(dx, dy) || 1;
        const step = MOVE_SPEED * dt;
        setPlayer(currentPoint => {
          const candidate = clampPoint([currentPoint[0] + dx / length * step, currentPoint[1] + dy / length * step]);
          if (crossesBarrier(currentPoint, candidate, barriers)) return currentPoint;
          if (!canOccupy(candidate)) return currentPoint;
          return candidate;
        });
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [barriers, canOccupy]);

  if (!current) return <div className="page"><h1>Spatial playtest</h1>{error ? <Alert severity="error">{error}</Alert> : <p>Loading map…</p>}</div>;

  return <div className="page spatial-playtest-page" tabIndex={0}>
    <header className="page-header">
      <div>
        <p className="eyebrow">SPATIAL V3 PLAYTEST</p>
        <h1>{locations.get(current.space.owner_location_id ?? "")?.name ?? "Navigation space"}</h1>
        <p>WASD moves · E interacts · barriers block movement · ROUTED spaces only allow authored traversable geometry.</p>
      </div>
      <Stack direction="row" spacing={1}>
        <Chip label={current.space.navigation_mode.toUpperCase()} />
        <Button onClick={() => window.close()}>Close</Button>
      </Stack>
    </header>

    {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
    <Alert severity="info" sx={{ mb: 1 }}>{message}</Alert>

    <Paper className="panel" sx={{ p: 1 }}>
      <div className="spatial-playtest-canvas">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none">
          <rect x=".5" y=".5" width="99" height="99" className="location-map-space-boundary"/>
          {features.map(feature => {
            const label = nameOf(feature, locations);
            if (feature.geometry.type === "Polygon") {
              return <g key={feature.id}>
                <polygon points={(feature.geometry.coordinates[0] ?? []).map(point => point.join(",")).join(" ")} className="location-map-area"/>
                <text x={featureCenter(feature)[0]} y={featureCenter(feature)[1]} className="spatial-playtest-label">{label}</text>
              </g>;
            }
            if (feature.geometry.type === "MultiPolygon") {
              return <g key={feature.id}>{feature.geometry.coordinates.map((polygon, index) =>
                <polygon key={index} points={(polygon[0] ?? []).map(point => point.join(",")).join(" ")} className="location-map-area"/>
              )}<text x={featureCenter(feature)[0]} y={featureCenter(feature)[1]} className="spatial-playtest-label">{label}</text></g>;
            }
            const lines = linesOf(feature.geometry);
            if (lines.length) {
              const width = feature.feature_kind === "corridor" ? Math.max(.8, Number(feature.properties.width ?? 4)) : feature.feature_kind === "barrier" ? 1.2 : .8;
              return <g key={feature.id}>{lines.map((line, index) => <polyline
                key={index}
                points={line.map(point => point.join(",")).join(" ")}
                fill="none"
                className={feature.feature_kind === "barrier" ? "location-map-barrier" : "location-map-connection"}
                strokeWidth={width}
                strokeLinecap="round"
                strokeLinejoin="round"
              />)}<text x={featureCenter(feature)[0]} y={featureCenter(feature)[1]} className="spatial-playtest-label">{label}</text></g>;
            }
            if (feature.geometry.type === "Point") {
              return <g key={feature.id}>
                <circle cx={feature.geometry.coordinates[0]} cy={feature.geometry.coordinates[1]} r="1.5" className="spatial-playtest-interaction"/>
                <text x={feature.geometry.coordinates[0] + 2} y={feature.geometry.coordinates[1] - 2} className="spatial-playtest-label">{label}</text>
              </g>;
            }
            return null;
          })}
          <circle cx={player[0]} cy={player[1]} r={PLAYER_RADIUS} className="spatial-playtest-player"/>
        </svg>
      </div>
    </Paper>

    <Paper className="panel" sx={{ p: 1.5, mt: 1 }}>
      <b>Current memberships</b>
      <div>
        {features.filter(feature => feature.semantic_location_id && (
          feature.feature_kind === "surface" ? pointInGeometry(player, feature.geometry)
          : feature.feature_kind === "corridor" ? corridorContains(player, feature)
          : false
        )).map(feature => <Chip key={feature.id} size="small" sx={{ mr: .5, mt: .5 }} label={nameOf(feature, locations)}/>)}
      </div>
    </Paper>
  </div>;
}
