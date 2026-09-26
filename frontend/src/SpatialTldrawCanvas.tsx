import { useEffect, useRef, useState } from "react";
import {
  Circle2d,
  createShapeId,
  Editor,
  getIndices,
  Group2d,
  Point2d,
  Polygon2d,
  Polyline2d,
  ShapeUtil,
  SVGContainer,
  T,
  TLHandle,
  TLHandleDragInfo,
  TLShape,
  TLShapeId,
  Tldraw,
  Vec,
} from "tldraw";
import "tldraw/tldraw.css";

export type SpatialCanvasPoint = [number, number];
export type SpatialCanvasTool = "select" | "edit" | "surface" | "corridor" | "barrier" | "spot" | "connector";
export type SpatialCanvasFeatureKind = Exclude<SpatialCanvasTool, "select" | "edit">;

export type SpatialCanvasGeometry =
  | { type: "Point"; coordinates: SpatialCanvasPoint }
  | { type: "LineString"; coordinates: SpatialCanvasPoint[] }
  | { type: "MultiLineString"; coordinates: SpatialCanvasPoint[][] }
  | { type: "Polygon"; coordinates: SpatialCanvasPoint[][] }
  | { type: "MultiPolygon"; coordinates: SpatialCanvasPoint[][][] };

export type SpatialCanvasFeature = {
  id: string;
  feature_kind: SpatialCanvasFeatureKind;
  name: string;
  geometry: SpatialCanvasGeometry;
  hidden: boolean;
  enabled: boolean;
  properties: Record<string, any>;
};

type LocalGeometry = SpatialCanvasGeometry;

type SpatialShapeProps = {
  featureId: string;
  featureKind: SpatialCanvasFeatureKind;
  name: string;
  geometryJson: string;
  width: number;
  editing: boolean;
  hidden: boolean;
  draft: boolean;
};

declare module "tldraw" {
  interface TLGlobalShapePropsMap {
    "spatial-feature": SpatialShapeProps;
  }
}

type SpatialShape = TLShape<"spatial-feature">;

const SPATIAL_SHAPE = "spatial-feature" as const;
const POINT_RADIUS = 6;

const spatialShapeProps = {
  featureId: T.string,
  featureKind: T.string,
  name: T.string,
  geometryJson: T.string,
  width: T.number,
  editing: T.boolean,
  hidden: T.boolean,
  draft: T.boolean,
};

function samePoint(a: SpatialCanvasPoint, b: SpatialCanvasPoint) {
  return Math.abs(a[0] - b[0]) < 0.0001 && Math.abs(a[1] - b[1]) < 0.0001;
}

function stripClosingRing(ring: SpatialCanvasPoint[]) {
  return ring.length > 1 && samePoint(ring[0], ring[ring.length - 1]) ? ring.slice(0, -1) : ring;
}

function geometryPoints(geometry: SpatialCanvasGeometry): SpatialCanvasPoint[] {
  if (geometry.type === "Point") return [geometry.coordinates];
  if (geometry.type === "LineString") return geometry.coordinates;
  if (geometry.type === "MultiLineString") return geometry.coordinates.flat();
  if (geometry.type === "Polygon") return geometry.coordinates.flat();
  return geometry.coordinates.flat(2);
}

function mapGeometry(geometry: SpatialCanvasGeometry, map: (point: SpatialCanvasPoint) => SpatialCanvasPoint): SpatialCanvasGeometry {
  if (geometry.type === "Point") return { ...geometry, coordinates: map(geometry.coordinates) };
  if (geometry.type === "LineString") return { ...geometry, coordinates: geometry.coordinates.map(map) };
  if (geometry.type === "MultiLineString") return { ...geometry, coordinates: geometry.coordinates.map(line => line.map(map)) };
  if (geometry.type === "Polygon") return { ...geometry, coordinates: geometry.coordinates.map(ring => ring.map(map)) };
  return { ...geometry, coordinates: geometry.coordinates.map(polygon => polygon.map(ring => ring.map(map))) };
}

function boundsOf(geometry: SpatialCanvasGeometry) {
  const points = geometryPoints(geometry);
  if (!points.length) return { minX: 0, minY: 0, maxX: 1, maxY: 1 };
  return {
    minX: Math.min(...points.map(point => point[0])),
    minY: Math.min(...points.map(point => point[1])),
    maxX: Math.max(...points.map(point => point[0])),
    maxY: Math.max(...points.map(point => point[1])),
  };
}

function localizeGeometry(geometry: SpatialCanvasGeometry) {
  if (geometry.type === "Point") {
    const [x, y] = geometry.coordinates;
    return {
      x: x - POINT_RADIUS,
      y: y - POINT_RADIUS,
      geometry: { type: "Point", coordinates: [POINT_RADIUS, POINT_RADIUS] } as LocalGeometry,
    };
  }
  const bounds = boundsOf(geometry);
  return {
    x: bounds.minX,
    y: bounds.minY,
    geometry: mapGeometry(geometry, point => [point[0] - bounds.minX, point[1] - bounds.minY]),
  };
}

function absoluteGeometry(shape: SpatialShape): SpatialCanvasGeometry {
  const local = JSON.parse(shape.props.geometryJson) as LocalGeometry;
  return mapGeometry(local, point => [point[0] + shape.x, point[1] + shape.y]);
}

function shapeForFeature(feature: SpatialCanvasFeature, editing: boolean) {
  const localized = localizeGeometry(feature.geometry);
  return {
    id: createShapeId(feature.id),
    type: SPATIAL_SHAPE,
    x: localized.x,
    y: localized.y,
    props: {
      featureId: feature.id,
      featureKind: feature.feature_kind,
      name: feature.name,
      geometryJson: JSON.stringify(localized.geometry),
      width: feature.feature_kind === "corridor" ? Math.max(1, Number(feature.properties.width ?? 4)) : feature.feature_kind === "barrier" ? 1.5 : 1,
      editing,
      hidden: feature.hidden || !feature.enabled,
      draft: false,
    },
    meta: { spatial: true },
  } as const;
}

function parseGeometry(shape: SpatialShape) {
  return JSON.parse(shape.props.geometryJson) as LocalGeometry;
}

function simpleEditablePoints(shape: SpatialShape): { points: SpatialCanvasPoint[]; closed: boolean } | null {
  const geometry = parseGeometry(shape);
  if (geometry.type === "LineString") return { points: geometry.coordinates, closed: false };
  if (geometry.type === "Polygon" && geometry.coordinates.length === 1) {
    return { points: stripClosingRing(geometry.coordinates[0]), closed: true };
  }
  return null;
}

function replaceSimplePoints(shape: SpatialShape, points: SpatialCanvasPoint[], closed: boolean) {
  const geometry = parseGeometry(shape);
  let next: LocalGeometry;
  if (geometry.type === "LineString") next = { type: "LineString", coordinates: points };
  else if (geometry.type === "Polygon") next = { type: "Polygon", coordinates: [[...points, ...(closed && points.length ? [points[0]] : [])]] };
  else return shape.props.geometryJson;
  return JSON.stringify(next);
}

function pathForGeometry(geometry: LocalGeometry): string {
  const line = (points: SpatialCanvasPoint[], close = false) => {
    if (!points.length) return "";
    const usable = close ? stripClosingRing(points) : points;
    if (!usable.length) return "";
    return `M ${usable.map(point => `${point[0]} ${point[1]}`).join(" L ")}${close ? " Z" : ""}`;
  };
  if (geometry.type === "Point") return "";
  if (geometry.type === "LineString") return line(geometry.coordinates);
  if (geometry.type === "MultiLineString") return geometry.coordinates.map(points => line(points)).join(" ");
  if (geometry.type === "Polygon") return geometry.coordinates.map(points => line(points, true)).join(" ");
  return geometry.coordinates.flatMap(polygon => polygon.map(points => line(points, true))).join(" ");
}

function geometry2d(shape: SpatialShape) {
  const geometry = parseGeometry(shape);
  if (geometry.type === "Point") {
    return new Circle2d({ radius: POINT_RADIUS, isFilled: true });
  }
  if (geometry.type === "LineString") {
    const points = geometry.coordinates.map(point => new Vec(point[0], point[1]));
    return points.length >= 2 ? new Polyline2d({ points }) : new Point2d({ point: points[0] ?? new Vec(0, 0), margin: 1 });
  }
  if (geometry.type === "Polygon") {
    const ring = stripClosingRing(geometry.coordinates[0] ?? []);
    const points = ring.map(point => new Vec(point[0], point[1]));
    return points.length >= 3 ? new Polygon2d({ points, isFilled: true }) : new Point2d({ point: points[0] ?? new Vec(0, 0), margin: 1 });
  }
  if (geometry.type === "MultiLineString") {
    return new Group2d({
      children: geometry.coordinates.map(line => {
        const points = line.map(point => new Vec(point[0], point[1]));
        return points.length >= 2 ? new Polyline2d({ points }) : new Point2d({ point: points[0] ?? new Vec(0, 0), margin: 1 });
      }),
    });
  }
  return new Group2d({
    children: geometry.coordinates.flatMap(polygon => polygon.map(ring => {
      const points = stripClosingRing(ring).map(point => new Vec(point[0], point[1]));
      return points.length >= 3 ? new Polygon2d({ points, isFilled: true }) : new Point2d({ point: points[0] ?? new Vec(0, 0), margin: 1 });
    })),
  });
}

function renderStyle(kind: SpatialCanvasFeatureKind, draft: boolean) {
  if (kind === "surface") return { stroke: draft ? "#8ab4f8" : "#93a8bf", fill: draft ? "rgba(138,180,248,.12)" : "rgba(147,168,191,.16)" };
  if (kind === "corridor") return { stroke: draft ? "#8ab4f8" : "#9aa6b2", fill: "none" };
  if (kind === "barrier") return { stroke: draft ? "#8ab4f8" : "#d0a5a5", fill: "none" };
  if (kind === "connector") return { stroke: "#d8c38d", fill: "#d8c38d" };
  return { stroke: "#a9b6c5", fill: "#a9b6c5" };
}

class SpatialFeatureShapeUtil extends ShapeUtil<SpatialShape> {
  static override type = SPATIAL_SHAPE;
  static override props = spatialShapeProps;

  override getDefaultProps(): SpatialShape["props"] {
    return {
      featureId: "",
      featureKind: "spot",
      name: "",
      geometryJson: JSON.stringify({ type: "Point", coordinates: [POINT_RADIUS, POINT_RADIUS] }),
      width: 1,
      editing: false,
      hidden: false,
      draft: false,
    };
  }

  override canResize() { return false; }

  override getGeometry(shape: SpatialShape) {
    return geometry2d(shape);
  }

  override component(shape: SpatialShape) {
    const geometry = parseGeometry(shape);
    const style = renderStyle(shape.props.featureKind, shape.props.draft);
    if (geometry.type === "Point") {
      return <SVGContainer>
        <circle cx={POINT_RADIUS} cy={POINT_RADIUS} r={POINT_RADIUS} fill={style.fill} stroke={style.stroke} strokeWidth={1.2}/>
        {shape.props.name && <text x={POINT_RADIUS + 8} y={POINT_RADIUS - 7} fontSize={11} fill="currentColor">{shape.props.name}</text>}
      </SVGContainer>;
    }
    return <SVGContainer>
      <path
        d={pathForGeometry(geometry)}
        fill={shape.props.featureKind === "surface" ? style.fill : "none"}
        stroke={style.stroke}
        strokeWidth={shape.props.featureKind === "corridor" ? shape.props.width : shape.props.featureKind === "barrier" ? 2 : 1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray={shape.props.draft ? "5 4" : undefined}
      />
    </SVGContainer>;
  }

  override getIndicatorPath(shape: SpatialShape) {
    const geometry = parseGeometry(shape);
    const path = new Path2D();
    const line = (points: SpatialCanvasPoint[], close: boolean) => {
      const usable = close ? stripClosingRing(points) : points;
      if (!usable.length) return;
      path.moveTo(usable[0][0], usable[0][1]);
      for (const point of usable.slice(1)) path.lineTo(point[0], point[1]);
      if (close) path.closePath();
    };
    if (geometry.type === "Point") {
      path.arc(POINT_RADIUS, POINT_RADIUS, POINT_RADIUS, 0, Math.PI * 2);
    } else if (geometry.type === "LineString") line(geometry.coordinates, false);
    else if (geometry.type === "MultiLineString") geometry.coordinates.forEach(points => line(points, false));
    else if (geometry.type === "Polygon") geometry.coordinates.forEach(points => line(points, true));
    else geometry.coordinates.forEach(polygon => polygon.forEach(points => line(points, true)));
    return path;
  }

  override getHandles(shape: SpatialShape): TLHandle[] {
    if (!shape.props.editing || shape.props.draft) return [];
    const editable = simpleEditablePoints(shape);
    if (!editable || editable.points.length < 2) return [];
    const segmentCount = editable.closed ? editable.points.length : editable.points.length - 1;
    const indices = getIndices(editable.points.length + segmentCount);
    const handles: TLHandle[] = [];
    for (let index = 0; index < editable.points.length; index += 1) {
      const point = editable.points[index];
      handles.push({
        id: `vertex:${index}`,
        type: "vertex",
        index: indices[index * 2],
        x: point[0],
        y: point[1],
        snapType: "point",
      });
      const nextIndex = index + 1;
      if (nextIndex < editable.points.length || editable.closed) {
        const next = editable.points[nextIndex % editable.points.length];
        handles.push({
          id: `create:${index}`,
          type: "create",
          index: indices[index * 2 + 1],
          x: (point[0] + next[0]) / 2,
          y: (point[1] + next[1]) / 2,
          snapType: "point",
        });
      }
    }
    return handles;
  }

  override onHandleDrag(shape: SpatialShape, { handle, initial }: TLHandleDragInfo<SpatialShape>) {
    const editable = simpleEditablePoints(initial ?? shape);
    if (!editable) return;
    const points = editable.points.map(point => [...point] as SpatialCanvasPoint);
    const [kind, rawIndex] = handle.id.split(":");
    const index = Number(rawIndex);
    if (!Number.isInteger(index)) return;
    if (kind === "vertex" && points[index]) {
      points[index] = [handle.x, handle.y];
    } else if (kind === "create") {
      points.splice(index + 1, 0, [handle.x, handle.y]);
    } else return;
    return {
      id: shape.id,
      type: SPATIAL_SHAPE,
      props: { geometryJson: replaceSimplePoints(shape, points, editable.closed) },
    };
  }
}

const shapeUtils = [SpatialFeatureShapeUtil];
const hiddenComponents = { ContextMenu: null };

function featureFromShape(shape: SpatialShape, previous: SpatialCanvasFeature): SpatialCanvasFeature {
  const geometry = absoluteGeometry(shape);
  const next = structuredClone(previous);
  next.geometry = geometry;
  if (next.feature_kind === "connector" && geometry.type === "Point") {
    next.properties = {
      ...next.properties,
      source: { ...next.properties.source, point: geometry.coordinates },
    };
  }
  return next;
}

function nearestSegment(points: SpatialCanvasPoint[], point: SpatialCanvasPoint, closed: boolean) {
  const count = closed ? points.length : points.length - 1;
  let best = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < count; index += 1) {
    const a = points[index];
    const b = points[(index + 1) % points.length];
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const length = dx * dx + dy * dy;
    const t = length ? Math.max(0, Math.min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length)) : 0;
    const x = a[0] + t * dx, y = a[1] + t * dy;
    const distance = (point[0] - x) ** 2 + (point[1] - y) ** 2;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = index;
    }
  }
  return best;
}

export function SpatialTldrawCanvas({
  features,
  tool,
  selectedFeatureId,
  draftPoints,
  onDraftPointsChange,
  onSelectFeature,
  onFeatureChange,
  onCreateFeature,
  onConnectorPoint,
  onExtrudeCorridor,
}: {
  features: SpatialCanvasFeature[];
  tool: SpatialCanvasTool;
  selectedFeatureId: string | null;
  draftPoints: SpatialCanvasPoint[];
  onDraftPointsChange: (points: SpatialCanvasPoint[]) => void;
  onSelectFeature: (featureId: string | null) => void;
  onFeatureChange: (feature: SpatialCanvasFeature) => void;
  onCreateFeature: (kind: SpatialCanvasFeatureKind, points: SpatialCanvasPoint[]) => void;
  onConnectorPoint: (point: SpatialCanvasPoint) => void;
  onExtrudeCorridor: (feature: SpatialCanvasFeature, point: SpatialCanvasPoint) => void;
}) {
  const editorRef = useRef<Editor | null>(null);
  const featuresRef = useRef(features);
  const toolRef = useRef(tool);
  const draftRef = useRef(draftPoints);
  const eHeldRef = useRef(false);
  const timersRef = useRef(new Map<string, number>());
  const [mounted, setMounted] = useState(false);

  featuresRef.current = features;
  toolRef.current = tool;
  draftRef.current = draftPoints;

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const selected = selectedFeatureId ? createShapeId(selectedFeatureId) : null;
    editor.store.mergeRemoteChanges(() => {
      for (const feature of features) {
        const id = createShapeId(feature.id);
        const existing = editor.getShape(id);
        const next = shapeForFeature(feature, tool === "edit" && feature.id === selectedFeatureId);
        if (!existing) editor.createShape(next);
        else editor.updateShape({ ...next, id, type: SPATIAL_SHAPE });
      }
      for (const shape of editor.getCurrentPageShapes()) {
        if (shape.type !== SPATIAL_SHAPE) continue;
        const spatial = shape as SpatialShape;
        if (spatial.props.draft) continue;
        if (!features.some(feature => feature.id === spatial.props.featureId)) editor.deleteShape(shape.id);
      }
    });
    if (selected && editor.getShape(selected)) editor.select(selected);
    else if (!selectedFeatureId) editor.selectNone();
  }, [features, selectedFeatureId, tool, mounted]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const draftId = createShapeId("__spatial_draft__");
    editor.store.mergeRemoteChanges(() => {
      if (!draftPoints.length || !["surface", "corridor", "barrier"].includes(tool)) {
        if (editor.getShape(draftId)) editor.deleteShape(draftId);
        return;
      }
      const kind = tool as SpatialCanvasFeatureKind;
      let geometry: SpatialCanvasGeometry;
      if (kind === "surface") geometry = { type: "Polygon", coordinates: [[...draftPoints, ...(draftPoints.length > 2 ? [draftPoints[0]] : [])]] };
      else geometry = { type: "LineString", coordinates: draftPoints };
      const localized = localizeGeometry(geometry);
      const shape = {
        id: draftId,
        type: SPATIAL_SHAPE,
        x: localized.x,
        y: localized.y,
        props: {
          featureId: "__draft__",
          featureKind: kind,
          name: "",
          geometryJson: JSON.stringify(localized.geometry),
          width: kind === "corridor" ? 4 : 1.5,
          editing: false,
          hidden: false,
          draft: true,
        },
        meta: { spatial: true },
      } as const;
      if (editor.getShape(draftId)) editor.updateShape(shape);
      else editor.createShape(shape);
    });
  }, [draftPoints, tool, mounted]);

  function handleMount(editor: Editor) {
    editorRef.current = editor;
    editor.setCurrentTool("select");
    setMounted(true);

    const saveChangedShape = (shape: SpatialShape) => {
      if (shape.props.draft) return;
      const feature = featuresRef.current.find(item => item.id === shape.props.featureId);
      if (!feature) return;
      const previousTimer = timersRef.current.get(feature.id);
      if (previousTimer) window.clearTimeout(previousTimer);
      const timer = window.setTimeout(() => {
        onFeatureChange(featureFromShape(shape, feature));
        timersRef.current.delete(feature.id);
      }, 180);
      timersRef.current.set(feature.id, timer);
    };

    const unlistenStore = editor.store.listen(entry => {
      for (const [, next] of Object.values(entry.changes.updated)) {
        if (next.typeName === "shape" && next.type === SPATIAL_SHAPE) saveChangedShape(next as SpatialShape);
      }
    }, { source: "user", scope: "document" });

    const handleEditorEvent = (info: Parameters<Parameters<Editor["on"]>[1]>[0]) => {
      if (info.type === "keyboard") {
        if (info.key?.toLowerCase() === "e") eHeldRef.current = info.name !== "key_up";
        return;
      }
      if (info.type !== "pointer") return;

      if (info.name === "pointer_up") {
        const shape = editor.getOnlySelectedShape();
        onSelectFeature(shape?.type === SPATIAL_SHAPE && !(shape as SpatialShape).props.draft ? (shape as SpatialShape).props.featureId : null);
        return;
      }

      const currentTool = toolRef.current;
      if (info.name === "pointer_down" && info.target === "canvas" && ["surface", "corridor", "barrier", "spot", "connector"].includes(currentTool)) {
        const page = editor.screenToPage(info.point);
        const point: SpatialCanvasPoint = [page.x, page.y];
        if (currentTool === "spot") onCreateFeature("spot", [point]);
        else if (currentTool === "connector") onConnectorPoint(point);
        else onDraftPointsChange([...draftRef.current, point]);
        return;
      }

      if (currentTool !== "edit") return;
      if (info.name === "right_click" && info.target === "shape" && info.shape?.type === SPATIAL_SHAPE) {
        const shape = info.shape as SpatialShape;
        const editable = simpleEditablePoints(shape);
        if (!editable) return;
        const page = editor.screenToPage(info.point);
        const local = editor.getPointInShapeSpace(shape, page);
        const point: SpatialCanvasPoint = [local.x, local.y];
        const segment = nearestSegment(editable.points, point, editable.closed);
        const points = editable.points.map(item => [...item] as SpatialCanvasPoint);
        points.splice(segment + 1, 0, point);
        editor.updateShape({
          id: shape.id,
          type: SPATIAL_SHAPE,
          props: { geometryJson: replaceSimplePoints(shape, points, editable.closed) },
        });
        return;
      }

      if (info.name === "pointer_down" && info.target === "handle" && eHeldRef.current && info.shape?.type === SPATIAL_SHAPE && info.handle?.id.startsWith("vertex:")) {
        const shape = info.shape as SpatialShape;
        const editable = simpleEditablePoints(shape);
        if (!editable) return;
        const index = Number(info.handle.id.split(":")[1]);
        const localPoint = editable.points[index];
        if (!localPoint) return;
        const point: SpatialCanvasPoint = [shape.x + localPoint[0], shape.y + localPoint[1]];
        const feature = featuresRef.current.find(item => item.id === shape.props.featureId);
        if (!feature) return;
        if (feature.feature_kind === "corridor") {
          onExtrudeCorridor(feature, point);
          return;
        }
        if (feature.feature_kind === "surface") {
          const centroid: SpatialCanvasPoint = [
            editable.points.reduce((sum, item) => sum + item[0], 0) / editable.points.length,
            editable.points.reduce((sum, item) => sum + item[1], 0) / editable.points.length,
          ];
          const dx = localPoint[0] - centroid[0], dy = localPoint[1] - centroid[1];
          const length = Math.hypot(dx, dy) || 1;
          const extruded: SpatialCanvasPoint = [localPoint[0] + dx / length * 18, localPoint[1] + dy / length * 18];
          const points = editable.points.map(item => [...item] as SpatialCanvasPoint);
          points.splice(index + 1, 0, extruded);
          editor.updateShape({
            id: shape.id,
            type: SPATIAL_SHAPE,
            props: { geometryJson: replaceSimplePoints(shape, points, true) },
          });
        }
      }
    };
    editor.on("event", handleEditorEvent);

    editor.zoomToFit({ animation: { duration: 0 } });

    return () => {
      unlistenStore();
      editor.off("event", handleEditorEvent);
      for (const timer of timersRef.current.values()) window.clearTimeout(timer);
      timersRef.current.clear();
      editorRef.current = null;
    };
  }

  return <div
    style={{ height: 620, minHeight: 420, borderRadius: 8, overflow: "hidden", position: "relative" }}
    onKeyDownCapture={event => {
      if (event.key.toLowerCase() === "e") {
        eHeldRef.current = true;
        event.preventDefault();
        event.stopPropagation();
      }
    }}
    onKeyUpCapture={event => {
      if (event.key.toLowerCase() === "e") {
        eHeldRef.current = false;
        event.preventDefault();
        event.stopPropagation();
      }
    }}
  >
    <Tldraw
      hideUi
      shapeUtils={shapeUtils}
      components={hiddenComponents}
      options={{ enableToolbarKeyboardShortcuts: false }}
      onMount={handleMount}
      getShapeVisibility={shape => shape.type === SPATIAL_SHAPE && (shape as SpatialShape).props.hidden ? "hidden" : "inherit"}
    />
  </div>;
}
