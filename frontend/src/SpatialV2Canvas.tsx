import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { Menu, MenuItem, TextField } from "@mui/material";

export type V2Point = [number, number];
export type V2Tool = "select" | "edit" | "surface" | "corridor" | "barrier" | "spot" | "connector";
export type V2FeatureKind = Exclude<V2Tool, "select" | "edit">;

export type V2Geometry =
  | { type: "Point"; coordinates: V2Point }
  | { type: "LineString"; coordinates: V2Point[] }
  | { type: "MultiLineString"; coordinates: V2Point[][] }
  | { type: "Polygon"; coordinates: V2Point[][] }
  | { type: "MultiPolygon"; coordinates: V2Point[][][] };

export type V2CanvasFeature = {
  id: string;
  feature_kind: V2FeatureKind;
  render_layer?: string;
  semantic_location_id?: string | null;
  name: string;
  geometry: V2Geometry;
  hidden: boolean;
  enabled: boolean;
  properties: Record<string, any>;
};

type DragFeature = {
  id: string;
  start: V2Point;
  geometry: V2Geometry;
};

type VertexRef = {
  featureId: string;
  part: number;
  index: number;
};

type VertexMenu = {
  mouseX: number;
  mouseY: number;
  ref: VertexRef;
} | null;

const clamp = (value: number) => Math.max(0, Math.min(100, value));
const round = (value: number) => Math.round(value * 10) / 10;
const samePoint = (a: V2Point, b: V2Point) => Math.abs(a[0] - b[0]) < .0001 && Math.abs(a[1] - b[1]) < .0001;

function stripClosure(points: V2Point[]) {
  return points.length > 1 && samePoint(points[0], points[points.length - 1]) ? points.slice(0, -1) : points;
}

function allPoints(geometry: V2Geometry): V2Point[] {
  if (geometry.type === "Point") return [geometry.coordinates];
  if (geometry.type === "LineString") return geometry.coordinates;
  if (geometry.type === "MultiLineString") return geometry.coordinates.flat();
  if (geometry.type === "Polygon") return geometry.coordinates.flat();
  return geometry.coordinates.flat(2);
}

function centroid(geometry: V2Geometry): V2Point {
  const points = allPoints(geometry);
  if (!points.length) return [50, 50];
  return [
    points.reduce((sum, point) => sum + point[0], 0) / points.length,
    points.reduce((sum, point) => sum + point[1], 0) / points.length,
  ];
}

function bounds(geometry: V2Geometry) {
  const points = allPoints(geometry);
  if (!points.length) return { minX: 0, minY: 0, maxX: 0, maxY: 0 };
  return {
    minX: Math.min(...points.map(point => point[0])),
    minY: Math.min(...points.map(point => point[1])),
    maxX: Math.max(...points.map(point => point[0])),
    maxY: Math.max(...points.map(point => point[1])),
  };
}

function mapGeometry(geometry: V2Geometry, fn: (point: V2Point) => V2Point): V2Geometry {
  if (geometry.type === "Point") return { ...geometry, coordinates: fn(geometry.coordinates) };
  if (geometry.type === "LineString") return { ...geometry, coordinates: geometry.coordinates.map(fn) };
  if (geometry.type === "MultiLineString") return { ...geometry, coordinates: geometry.coordinates.map(line => line.map(fn)) };
  if (geometry.type === "Polygon") return { ...geometry, coordinates: geometry.coordinates.map(ring => ring.map(fn)) };
  return { ...geometry, coordinates: geometry.coordinates.map(polygon => polygon.map(ring => ring.map(fn))) };
}

function translatedGeometry(geometry: V2Geometry, dx: number, dy: number): V2Geometry {
  const box = bounds(geometry);
  const safeDx = Math.max(-box.minX, Math.min(100 - box.maxX, dx));
  const safeDy = Math.max(-box.minY, Math.min(100 - box.maxY, dy));
  return mapGeometry(geometry, point => [round(point[0] + safeDx), round(point[1] + safeDy)]);
}

function editableParts(geometry: V2Geometry): Array<{ part: number; points: V2Point[]; closed: boolean }> {
  if (geometry.type === "LineString") return [{ part: 0, points: geometry.coordinates, closed: false }];
  if (geometry.type === "MultiLineString") return geometry.coordinates.map((points, part) => ({ part, points, closed: false }));
  if (geometry.type === "Polygon" && geometry.coordinates.length) return [{ part: 0, points: stripClosure(geometry.coordinates[0]), closed: true }];
  return [];
}

function replacePart(geometry: V2Geometry, part: number, points: V2Point[], closed: boolean): V2Geometry {
  if (geometry.type === "LineString") return { ...geometry, coordinates: points };
  if (geometry.type === "MultiLineString") {
    const coordinates = geometry.coordinates.map(line => line.map(point => [...point] as V2Point));
    coordinates[part] = points;
    return { ...geometry, coordinates };
  }
  if (geometry.type === "Polygon") {
    const coordinates = geometry.coordinates.map(ring => ring.map(point => [...point] as V2Point));
    coordinates[part] = closed && points.length ? [...points, points[0]] : points;
    return { ...geometry, coordinates };
  }
  return geometry;
}

function pointForRef(geometry: V2Geometry, ref: VertexRef): V2Point | null {
  const part = editableParts(geometry).find(item => item.part === ref.part);
  return part?.points[ref.index] ?? null;
}

function updateVertex(geometry: V2Geometry, ref: VertexRef, point: V2Point, linkCoincident = false): V2Geometry {
  const original = pointForRef(geometry, ref);
  const part = editableParts(geometry).find(item => item.part === ref.part);
  if (!part || !original || !part.points[ref.index]) return geometry;
  if (linkCoincident && geometry.type === "MultiLineString") {
    return {
      ...geometry,
      coordinates: geometry.coordinates.map(line => line.map(item => samePoint(item, original) ? point : item)),
    };
  }
  const points = part.points.map(item => [...item] as V2Point);
  points[ref.index] = point;
  return replacePart(geometry, ref.part, points, part.closed);
}

function insertAfter(geometry: V2Geometry, ref: VertexRef, point: V2Point): V2Geometry {
  const part = editableParts(geometry).find(item => item.part === ref.part);
  if (!part) return geometry;
  const points = part.points.map(item => [...item] as V2Point);
  points.splice(ref.index + 1, 0, point);
  return replacePart(geometry, ref.part, points, part.closed);
}

function removeVertex(geometry: V2Geometry, ref: VertexRef): V2Geometry {
  const part = editableParts(geometry).find(item => item.part === ref.part);
  if (!part || part.points.length <= (part.closed ? 3 : 2)) return geometry;
  const points = part.points.map(item => [...item] as V2Point);
  points.splice(ref.index, 1);
  return replacePart(geometry, ref.part, points, part.closed);
}

function roadBranch(geometry: V2Geometry, ref: VertexRef): V2Geometry {
  const origin = pointForRef(geometry, ref);
  if (!origin) return geometry;
  const part = editableParts(geometry).find(item => item.part === ref.part);
  const before = part?.points[Math.max(0, ref.index - 1)] ?? origin;
  const after = part?.points[Math.min((part?.points.length ?? 1) - 1, ref.index + 1)] ?? origin;
  const tangent: V2Point = [after[0] - before[0], after[1] - before[1]];
  const length = Math.hypot(tangent[0], tangent[1]) || 1;
  const normal: V2Point = [-tangent[1] / length, tangent[0] / length];
  const endpoint: V2Point = [clamp(round(origin[0] + normal[0] * 8)), clamp(round(origin[1] + normal[1] * 8))];
  if (geometry.type === "LineString") {
    return { type: "MultiLineString", coordinates: [geometry.coordinates, [origin, endpoint]] };
  }
  if (geometry.type === "MultiLineString") {
    return { ...geometry, coordinates: [...geometry.coordinates, [origin, endpoint]] };
  }
  return geometry;
}

function areaExtrusion(geometry: V2Geometry, ref: VertexRef): V2Geometry {
  const part = editableParts(geometry).find(item => item.part === ref.part);
  if (!part?.closed) return geometry;
  const point = part.points[ref.index];
  const center: V2Point = [
    part.points.reduce((sum, item) => sum + item[0], 0) / part.points.length,
    part.points.reduce((sum, item) => sum + item[1], 0) / part.points.length,
  ];
  const dx = point[0] - center[0], dy = point[1] - center[1];
  const length = Math.hypot(dx, dy) || 1;
  return insertAfter(geometry, ref, [
    clamp(round(point[0] + dx / length * 7)),
    clamp(round(point[1] + dy / length * 7)),
  ]);
}

function renderGeometry(
  feature: V2CanvasFeature,
  geometry: V2Geometry,
  selected: boolean,
  textured: boolean,
  editable: boolean,
  onSelect: () => void,
) {
  const className = selected ? " selected" : "";
  if (geometry.type === "Polygon") {
    const ring = geometry.coordinates[0] ?? [];
    return <polygon
      points={ring.map(point => point.join(",")).join(" ")}
      className={`location-map-area${className}`}
      style={{ pointerEvents: editable ? "auto" : "none", cursor: editable ? "pointer" : "default", fill: textured ? undefined : "none" }}
      onClick={event => { event.stopPropagation(); onSelect(); }}
    />;
  }
  if (geometry.type === "MultiPolygon") {
    return <g>{geometry.coordinates.map((polygon, index) => <polygon
      key={index}
      points={(polygon[0] ?? []).map(point => point.join(",")).join(" ")}
      className={`location-map-area${className}`}
      style={{ pointerEvents: editable ? "auto" : "none", cursor: editable ? "pointer" : "default", fill: textured ? undefined : "none" }}
      onClick={event => { event.stopPropagation(); onSelect(); }}
    />)}</g>;
  }
  const lines = geometry.type === "LineString" ? [geometry.coordinates] : geometry.type === "MultiLineString" ? geometry.coordinates : [];
  if (lines.length) {
    const width = feature.feature_kind === "corridor" ? Math.max(.8, Number(feature.properties.width ?? 4)) : .8;
    return <g>{lines.map((line, index) => <g key={index}>
      <polyline
        points={line.map(point => point.join(",")).join(" ")}
        fill="none"
        stroke="transparent"
        strokeWidth={Math.max(4, width + 3)}
        style={{ pointerEvents: editable ? "stroke" : "none", cursor: editable ? "pointer" : "default" }}
        onClick={event => { event.stopPropagation(); onSelect(); }}
      />
      <polyline
        points={line.map(point => point.join(",")).join(" ")}
        fill="none"
        className={feature.feature_kind === "barrier" ? "location-map-barrier" : "location-map-connection"}
        strokeWidth={width}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ pointerEvents: "none", strokeWidth: textured ? width : Math.min(width, 1.2), strokeDasharray: textured ? undefined : "2 1.4" }}
      />
    </g>)}</g>;
  }
  return null;
}

export function SpatialV2Canvas({
  features,
  tool,
  selectedFeatureId,
  draftPoints,
  onDraftPointsChange,
  onSelectFeature,
  onFeatureChange,
  onCreateFeature,
  onConnectorPoint,
  layerSettings,
}: {
  features: V2CanvasFeature[];
  tool: V2Tool;
  selectedFeatureId: string | null;
  draftPoints: V2Point[];
  onDraftPointsChange: (points: V2Point[]) => void;
  onSelectFeature: (featureId: string | null) => void;
  onFeatureChange: (feature: V2CanvasFeature) => void;
  onCreateFeature: (kind: V2FeatureKind, points: V2Point[]) => void;
  onConnectorPoint: (point: V2Point) => void;
  layerSettings: Record<string, { textured: boolean; editable: boolean; labels_mode: "hidden" | "important" | "all" }>;
}) {
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const [dragFeature, setDragFeature] = useState<DragFeature | null>(null);
  const [dragOffset, setDragOffset] = useState<V2Point>([0, 0]);
  const [vertexDrag, setVertexDrag] = useState<VertexRef | null>(null);
  const [vertexPreview, setVertexPreview] = useState<V2Point | null>(null);
  const [vertexMenu, setVertexMenu] = useState<VertexMenu>(null);
  const [eHeld, setEHeld] = useState(false);

  const selected = features.find(item => item.id === selectedFeatureId) ?? null;

  useEffect(() => {
    const node = canvasRef.current;
    if (!node) return;
    const wheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      event.stopPropagation();
      setZoom(value => Math.max(.5, Math.min(2, round(value - event.deltaY * .001))));
    };
    node.addEventListener("wheel", wheel, { passive: false });
    return () => node.removeEventListener("wheel", wheel);
  }, []);

  useEffect(() => {
    const down = (event: KeyboardEvent) => { if (event.key.toLowerCase() === "e") setEHeld(true); };
    const up = (event: KeyboardEvent) => { if (event.key.toLowerCase() === "e") setEHeld(false); };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  function canvasPoint(clientX: number, clientY: number, element: HTMLElement): V2Point {
    const rect = element.getBoundingClientRect();
    return [
      clamp(round(((clientX - rect.left) / rect.width) * 100 / zoom)),
      clamp(round(((clientY - rect.top) / rect.height) * 100 / zoom)),
    ];
  }

  function displayedGeometry(feature: V2CanvasFeature): V2Geometry {
    if (dragFeature?.id === feature.id) return translatedGeometry(dragFeature.geometry, dragOffset[0], dragOffset[1]);
    if (vertexDrag?.featureId === feature.id && vertexPreview) return updateVertex(feature.geometry, vertexDrag, vertexPreview, feature.feature_kind === "corridor");
    return feature.geometry;
  }

  function startDrag(event: ReactPointerEvent<HTMLElement>, feature: V2CanvasFeature) {
    const settings = layerSettings[feature.render_layer ?? ""];
    if (tool !== "select" || event.button !== 0 || settings?.editable === false) return;
    event.stopPropagation();
    const host = canvasRef.current;
    if (!host) return;
    setDragFeature({ id: feature.id, start: canvasPoint(event.clientX, event.clientY, host), geometry: structuredClone(feature.geometry) });
    setDragOffset([0, 0]);
    onSelectFeature(feature.id);
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function finishDrag() {
    if (dragFeature) {
      const feature = features.find(item => item.id === dragFeature.id);
      if (feature && (Math.abs(dragOffset[0]) >= .1 || Math.abs(dragOffset[1]) >= .1)) {
        const next = structuredClone(feature);
        next.geometry = translatedGeometry(dragFeature.geometry, dragOffset[0], dragOffset[1]);
        if (next.feature_kind === "connector" && next.geometry.type === "Point") {
          next.properties = { ...next.properties, source: { ...next.properties.source, point: next.geometry.coordinates } };
        }
        onFeatureChange(next);
      }
    }
    if (vertexDrag && vertexPreview) {
      const feature = features.find(item => item.id === vertexDrag.featureId);
      if (feature) {
        const next = structuredClone(feature);
        next.geometry = updateVertex(feature.geometry, vertexDrag, vertexPreview, feature.feature_kind === "corridor");
        onFeatureChange(next);
      }
    }
    setDragFeature(null);
    setDragOffset([0, 0]);
    setVertexDrag(null);
    setVertexPreview(null);
  }

  function canvasClick(event: React.MouseEvent<HTMLDivElement>) {
    if (event.defaultPrevented) return;
    const point = canvasPoint(event.clientX, event.clientY, event.currentTarget);
    if (tool === "select" || tool === "edit") {
      if (event.target === event.currentTarget) onSelectFeature(null);
      return;
    }
    if (tool === "spot") {
      onCreateFeature("spot", [point]);
      return;
    }
    if (tool === "connector") {
      onConnectorPoint(point);
      return;
    }
    onDraftPointsChange([...draftPoints, point]);
  }

  function extrude(feature: V2CanvasFeature, ref: VertexRef) {
    const next = structuredClone(feature);
    if (feature.feature_kind === "corridor") next.geometry = roadBranch(feature.geometry, ref);
    else if (feature.feature_kind === "surface") next.geometry = areaExtrusion(feature.geometry, ref);
    else return;
    onFeatureChange(next);
  }

  function addConnectedPoint(feature: V2CanvasFeature, ref: VertexRef) {
    const part = editableParts(feature.geometry).find(item => item.part === ref.part);
    const point = part?.points[ref.index];
    if (!part || !point) return;
    const nextPoint = part.points[(ref.index + 1) % part.points.length];
    const middle: V2Point = [round((point[0] + nextPoint[0]) / 2), round((point[1] + nextPoint[1]) / 2)];
    const next = structuredClone(feature);
    next.geometry = feature.feature_kind === "corridor" ? roadBranch(feature.geometry, ref) : insertAfter(feature.geometry, ref, middle);
    onFeatureChange(next);
    setVertexMenu(null);
  }

  const selectedBounds = selected ? bounds(displayedGeometry(selected)) : null;

  return <div>
    <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
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

    <div
      ref={canvasRef}
      className={`location-map-canvas tool-${tool}`}
      style={{ height: 620, minHeight: 420 }}
      onClick={canvasClick}
      onPointerMove={event => {
        const point = canvasPoint(event.clientX, event.clientY, event.currentTarget);
        if (dragFeature) setDragOffset([round(point[0] - dragFeature.start[0]), round(point[1] - dragFeature.start[1])]);
        if (vertexDrag) setVertexPreview(point);
      }}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
    >
      <div className="location-map-world" style={{ transform: `scale(${zoom})` }}>
        <svg className="location-map-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
          <rect x=".45" y=".45" width="99.1" height="99.1" className="location-map-space-boundary"/>

          {features.map(feature => {
            const geometry = displayedGeometry(feature);
            return <g key={feature.id}>
              {renderGeometry(
                feature,
                geometry,
                feature.id === selectedFeatureId,
                layerSettings[feature.render_layer ?? ""]?.textured !== false,
                layerSettings[feature.render_layer ?? ""]?.editable !== false,
                () => onSelectFeature(feature.id),
              )}
            </g>;
          })}

          {selectedBounds && <rect
            x={selectedBounds.minX}
            y={selectedBounds.minY}
            width={Math.max(.1, selectedBounds.maxX - selectedBounds.minX)}
            height={Math.max(.1, selectedBounds.maxY - selectedBounds.minY)}
            className="location-map-selection-bounds"
          />}

          {draftPoints.length > 1 && <polyline
            points={draftPoints.map(point => point.join(",")).join(" ")}
            className="location-map-draft"
          />}
        </svg>

        {features.map(feature => {
          const geometry = displayedGeometry(feature);
          const center = centroid(geometry);
          const settings = layerSettings[feature.render_layer ?? ""];
          const editable = settings?.editable !== false;
          const showLabel = settings?.labels_mode === "all"
            || (settings?.labels_mode !== "hidden" && (feature.id === selectedFeatureId || Boolean(feature.semantic_location_id)));
          if (feature.geometry.type === "Point") {
            return <button
              key={`${feature.id}:node`}
              className={`location-map-anchor ${feature.feature_kind}${feature.id === selectedFeatureId ? " selected" : ""}`}
              title={showLabel ? feature.name : feature.feature_kind}
              onClick={event => { event.stopPropagation(); onSelectFeature(feature.id); }}
              onPointerDown={event => startDrag(event, feature)}
              style={{ left: `${center[0]}%`, top: `${center[1]}%`, pointerEvents: editable ? "auto" : "none", opacity: showLabel ? 1 : .55 }}
            >{feature.feature_kind === "connector" ? "▮" : "◇"}</button>;
          }
          if (!showLabel) return null;
          return <button
            key={`${feature.id}:label`}
            className={`location-map-node v3-feature-node${feature.id === selectedFeatureId ? " selected" : ""}`}
            onClick={event => { event.stopPropagation(); onSelectFeature(feature.id); }}
            onPointerDown={event => startDrag(event, feature)}
            disabled={!editable}
            style={{ left: `${center[0]}%`, top: `${center[1]}%`, pointerEvents: editable ? "auto" : "none" }}
          >
            <b>{feature.name || feature.feature_kind}</b>
            <small>{feature.feature_kind}</small>
          </button>;
        })}

        {tool === "edit" && selected && layerSettings[selected.render_layer ?? ""]?.editable !== false && editableParts(displayedGeometry(selected)).flatMap(part => part.points.flatMap((point, index) => {
          const next = part.points[(index + 1) % part.points.length];
          const hasNext = part.closed || index < part.points.length - 1;
          const ref: VertexRef = { featureId: selected.id, part: part.part, index };
          const midpoint: V2Point = next ? [(point[0] + next[0]) / 2, (point[1] + next[1]) / 2] : point;
          return [
            <button
              key={`${selected.id}:p${part.part}:vertex:${index}`}
              className="location-map-vertex"
              style={{ left: `${point[0]}%`, top: `${point[1]}%` }}
              title={eHeld && (selected.feature_kind === "corridor" || selected.feature_kind === "surface") ? "E: extrude" : "Drag vertex"}
              onPointerDown={event => {
                if (event.button !== 0) return;
                event.stopPropagation();
                if (eHeld && (selected.feature_kind === "corridor" || selected.feature_kind === "surface")) {
                  extrude(selected, ref);
                  return;
                }
                setVertexDrag(ref);
                setVertexPreview(point);
                event.currentTarget.setPointerCapture?.(event.pointerId);
              }}
              onContextMenu={event => {
                event.preventDefault();
                event.stopPropagation();
                setVertexMenu({ mouseX: event.clientX + 2, mouseY: event.clientY - 6, ref });
              }}
            />,
            hasNext ? <button
              key={`${selected.id}:p${part.part}:mid:${index}`}
              className="location-map-midpoint"
              style={{ left: `${midpoint[0]}%`, top: `${midpoint[1]}%` }}
              title="Add vertex"
              onClick={event => {
                event.stopPropagation();
                const nextFeature = structuredClone(selected);
                nextFeature.geometry = insertAfter(selected.geometry, ref, [round(midpoint[0]), round(midpoint[1])]);
                onFeatureChange(nextFeature);
              }}
            /> : null,
          ];
        }))}

        {draftPoints.map((point, index) => <span
          key={index}
          className="location-map-draft-point"
          style={{ left: `${point[0]}%`, top: `${point[1]}%` }}
        />)}
      </div>
    </div>

    <Menu
      open={Boolean(vertexMenu)}
      onClose={() => setVertexMenu(null)}
      anchorReference="anchorPosition"
      anchorPosition={vertexMenu ? { top: vertexMenu.mouseY, left: vertexMenu.mouseX } : undefined}
    >
      <MenuItem onClick={() => {
        if (!vertexMenu || !selected) return;
        addConnectedPoint(selected, vertexMenu.ref);
      }}>Create connected point</MenuItem>
      <MenuItem onClick={() => {
        if (!vertexMenu || !selected) return;
        const next = structuredClone(selected);
        next.geometry = removeVertex(selected.geometry, vertexMenu.ref);
        onFeatureChange(next);
        setVertexMenu(null);
      }}>Remove point</MenuItem>
    </Menu>
  </div>;
}
