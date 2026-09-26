import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Chip, Paper, Stack } from "@mui/material";
import { api } from "./api";
import type { SceneEnvironment, UserAmbientPreferences, WorldEntity, WorldProjection } from "./types";

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
  movement_priority: number;
  hidden: boolean;
  enabled: boolean;
  properties: Record<string, any>;
};

type Space = {
  id: string;
  owner_location_id: string | null;
  navigation_mode: "free" | "routed";
  bounds?: Geometry | null;
};

type SpaceBinding = {
  location_id: string;
  navigation_space_id: string;
  entrance_policy: "connectors" | "open";
  bounds_mode: "inherit_parent" | "independent";
};

type InheritedContext = {
  source_space_id: string;
  source_location_id: string;
  source_feature_ids: string[];
  source_bounds: [number, number, number, number];
  target_bounds: [number, number, number, number];
  boundary: Geometry;
  features: Feature[];
};

type SpaceDetails = {
  space: Space;
  binding?: SpaceBinding | null;
  inherited_context?: InheritedContext | null;
  features: Feature[];
};

type PlayingAmbient = {
  audio: HTMLAudioElement;
  gain: number;
  target: number;
};

const PLAYER_RADIUS = 0.65;
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

function transformPoint(
  point: Point,
  source: [number, number, number, number],
  target: [number, number, number, number],
): Point {
  const [sMinX, sMinY, sMaxX, sMaxY] = source;
  const [tMinX, tMinY, tMaxX, tMaxY] = target;
  const sw = Math.max(1e-9, sMaxX - sMinX);
  const sh = Math.max(1e-9, sMaxY - sMinY);
  return [
    tMinX + ((point[0] - sMinX) / sw) * (tMaxX - tMinX),
    tMinY + ((point[1] - sMinY) / sh) * (tMaxY - tMinY),
  ];
}

function parentToChild(point: Point, context: InheritedContext): Point {
  return transformPoint(point, context.source_bounds, context.target_bounds);
}

function childToParent(point: Point, context: InheritedContext): Point {
  return transformPoint(point, context.target_bounds, context.source_bounds);
}

function movementWinner(features: Feature[], point: Point) {
  return features
    .filter(feature =>
      feature.enabled
      && (feature.feature_kind === "surface" || feature.feature_kind === "corridor")
      && (feature.feature_kind === "surface"
        ? pointInGeometry(point, feature.geometry)
        : corridorContains(point, feature))
    )
    .sort((a, b) => Number(b.movement_priority ?? 0) - Number(a.movement_priority ?? 0))[0] ?? null;
}

function canOccupyIn(details: SpaceDetails, point: Point) {
  const boundary = details.inherited_context?.boundary ?? details.space.bounds;
  if (boundary && !pointInGeometry(point, boundary)) return false;
  const winner = movementWinner(details.features, point);
  if (winner) return winner.properties.traversal?.default_allowed !== false;
  return details.space.navigation_mode === "free";
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
  const [scene, setScene] = useState<SceneEnvironment | null>(null);
  const [ambientPrefs, setAmbientPrefs] = useState<UserAmbientPreferences>({ enabled: true, master_volume: 1 });
  const [audioArmed, setAudioArmed] = useState(false);
  const keys = useRef(new Set<string>());
  const lastTime = useRef<number | null>(null);
  const activeAmbient = useRef(new Map<string, PlayingAmbient>());

  const locations = useMemo(
    () => new Map(Object.values(world?.entities ?? {}).filter((item: WorldEntity) => item.kind === "location").map(item => [item.id, item])),
    [world],
  );

  const load = useCallback(async () => {
    const [nextWorld, nextSpaces, nextAmbientPrefs] = await Promise.all([
      api<WorldProjection>(`/projects/${projectId}/world`),
      api<Space[]>(`/projects/${projectId}/spatial-v3/spaces`),
      api<UserAmbientPreferences>("/preferences/ambient"),
    ]);
    setAmbientPrefs(nextAmbientPrefs);
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
    () => current?.features.filter(feature => feature.enabled && feature.feature_kind === "barrier") ?? [],
    [current],
  );

  const activeSemanticLocationId = useMemo(() => {
    if (!current) return null;
    const containing = features
      .filter(feature => feature.semantic_location_id)
      .filter(feature =>
        feature.feature_kind === "surface"
          ? pointInGeometry(player, feature.geometry)
          : feature.feature_kind === "corridor"
            ? corridorContains(player, feature)
            : false
      )
      .sort((a, b) =>
        Number(b.movement_priority ?? 0) - Number(a.movement_priority ?? 0)
      );
    return containing[0]?.semantic_location_id
      ?? current.space.owner_location_id
      ?? null;
  }, [current, features, player]);

  useEffect(() => {
    if (!activeSemanticLocationId) {
      setScene(null);
      return;
    }
    let cancelled = false;
    api<SceneEnvironment>(`/projects/${projectId}/environment/locations/${activeSemanticLocationId}/scene`)
      .then(next => { if (!cancelled) setScene(next); })
      .catch(cause => { if (!cancelled) setError(String(cause)); });
    return () => { cancelled = true; };
  }, [activeSemanticLocationId, projectId]);

  useEffect(() => {
    const arm = () => setAudioArmed(true);
    window.addEventListener("pointerdown", arm, { once: true });
    window.addEventListener("keydown", arm, { once: true });
    return () => {
      window.removeEventListener("pointerdown", arm);
      window.removeEventListener("keydown", arm);
    };
  }, []);

  useEffect(() => {
    const desired = new Map(
      scene?.enabled && ambientPrefs.enabled && audioArmed
        ? scene.ambient.map(item => [item.id, item] as const)
        : [],
    );
    for (const [id, item] of desired) {
      let playing = activeAmbient.current.get(id);
      if (!playing) {
        const audio = new Audio(item.url);
        audio.loop = true;
        audio.preload = "auto";
        audio.volume = 0;
        audio.playbackRate = item.playback_rate;
        playing = {
          audio,
          gain: 0,
          target: item.default_gain * ambientPrefs.master_volume,
        };
        activeAmbient.current.set(id, playing);
        void audio.play().catch(() => undefined);
      }
      playing.audio.playbackRate = item.playback_rate;
      playing.target = item.default_gain * ambientPrefs.master_volume;
    }
    for (const [id, playing] of activeAmbient.current) {
      if (!desired.has(id)) playing.target = 0;
    }
  }, [scene, ambientPrefs, audioArmed]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      for (const [id, playing] of activeAmbient.current) {
        const delta = playing.target - playing.gain;
        playing.gain += Math.sign(delta) * Math.min(.04, Math.abs(delta));
        playing.audio.volume = Math.max(0, Math.min(1, playing.gain));
        if (playing.target === 0 && playing.gain === 0) {
          playing.audio.pause();
          playing.audio.src = "";
          activeAmbient.current.delete(id);
        }
      }
    }, 50);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => () => {
    for (const playing of activeAmbient.current.values()) {
      playing.audio.pause();
      playing.audio.src = "";
    }
    activeAmbient.current.clear();
  }, []);

  const canOccupy = useCallback((point: Point) => {
    if (!current) return false;
    return canOccupyIn(current, point);
  }, [current]);

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
          if (!current) return currentPoint;
          const rawCandidate: Point = [
            currentPoint[0] + dx / length * step,
            currentPoint[1] + dy / length * step,
          ];

          // OPEN inherited spaces are continuous with their parent. Walking
          // beyond the inherited child boundary ascends at the equivalent
          // parent coordinate, provided the parent-side segment is legal.
          const context = current.inherited_context;
          if (
            context
            && current.binding?.entrance_policy === "open"
            && pointInGeometry(currentPoint, context.boundary)
            && !pointInGeometry(rawCandidate, context.boundary)
          ) {
            const parent = details[context.source_space_id];
            if (!parent) return currentPoint;
            const parentCurrent = childToParent(currentPoint, context);
            const parentCandidate = childToParent(rawCandidate, context);
            const parentBarriers = parent.features.filter(feature => feature.enabled && feature.feature_kind === "barrier");
            if (crossesBarrier(parentCurrent, parentCandidate, parentBarriers)) return currentPoint;
            if (!canOccupyIn(parent, parentCandidate)) return currentPoint;
            setSpaceId(context.source_space_id);
            setMessage(`Exited to ${locations.get(parent.space.owner_location_id ?? "")?.name ?? context.source_space_id}`);
            return clampPoint(parentCandidate);
          }

          const candidate = clampPoint(rawCandidate);
          if (crossesBarrier(currentPoint, candidate, barriers)) return currentPoint;
          if (!canOccupy(candidate)) return currentPoint;

          // Crossing into an OPEN child footprint automatically descends into
          // its inner Navigation Space at the matching local coordinate.
          const openChildren = Object.values(details)
            .filter(child =>
              child.space.id !== spaceId
              && child.binding?.entrance_policy === "open"
              && child.inherited_context?.source_space_id === spaceId
            )
            .map(child => {
              const childContext = child.inherited_context!;
              const sourceFeatures = current.features.filter(feature => feature.enabled && childContext.source_feature_ids.includes(feature.id));
              const entered = sourceFeatures.some(feature =>
                feature.feature_kind === "surface"
                && pointInGeometry(candidate, feature.geometry)
                && !pointInGeometry(currentPoint, feature.geometry)
              );
              return { child, childContext, sourceFeatures, entered };
            })
            .filter(item => item.entered)
            .sort((a, b) => {
              const area = (items: Feature[]) => items.reduce((sum, feature) => {
                if (feature.geometry.type !== "Polygon") return sum;
                const ring = feature.geometry.coordinates[0] ?? [];
                let value = 0;
                for (let i = 0; i < ring.length - 1; i++) {
                  value += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
                }
                return sum + Math.abs(value / 2);
              }, 0);
              return area(a.sourceFeatures) - area(b.sourceFeatures);
            });

          const descent = openChildren[0];
          if (descent) {
            const childPoint = parentToChild(candidate, descent.childContext);
            if (!canOccupyIn(descent.child, childPoint)) return currentPoint;
            setSpaceId(descent.child.space.id);
            setMessage(`Entered ${locations.get(descent.child.space.owner_location_id ?? "")?.name ?? descent.child.space.id}`);
            return clampPoint(childPoint);
          }

          return candidate;
        });
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [barriers, canOccupy, current, details, features, locations, spaceId]);

  if (!current) return <div className="page"><h1>Spatial playtest</h1>{error ? <Alert severity="error">{error}</Alert> : <p>Loading map…</p>}</div>;

  return <div
    className="page spatial-playtest-page"
    tabIndex={0}
    style={scene?.background?.url ? {
      backgroundImage: `linear-gradient(rgba(244,239,230,.78), rgba(244,239,230,.90)), url(${scene.background.url})`,
      backgroundSize: "cover",
      backgroundPosition: "center",
      backgroundAttachment: "fixed",
    } : undefined}
  >
    <header className="page-header">
      <div>
        <p className="eyebrow">SPATIAL V3 PLAYTEST</p>
        <h1>{locations.get(current.space.owner_location_id ?? "")?.name ?? "Navigation space"}</h1>
        <p>WASD moves · E interacts · open nested areas transition automatically · doors/gates remain explicit · barriers and movement rules still apply.</p>
      </div>
      <Stack direction="row" spacing={1}>
        <Chip label={current.space.navigation_mode.toUpperCase()} />
        {scene?.location?.name && <Chip variant="outlined" label={`Area: ${scene.location.name}`} />}
        <Button onClick={() => window.close()}>Close</Button>
      </Stack>
    </header>

    {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
    <Alert severity="info" sx={{ mb: 1 }}>
      {message}
      {scene?.ambient?.length ? ` · ambience: ${scene.ambient.map(item => item.label).join(", ")}` : ""}
    </Alert>

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
                className={
                  feature.feature_kind === "barrier"
                    ? "location-map-barrier"
                    : feature.feature_kind === "corridor"
                      ? "location-map-corridor"
                      : "location-map-connection"
                }
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
