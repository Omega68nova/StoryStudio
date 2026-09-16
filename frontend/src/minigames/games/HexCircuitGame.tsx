import { useEffect, useRef, useState } from "react";
import { LinearProgress, Stack, Typography } from "@mui/material";

type Setup = { masks?: number[]; rotations?: number[]; coordinates?: Array<[number, number]>; time_limit_ms?: number | null };
type Result = { rotations: number[]; move_count: number; elapsed_ms: number; timeout: boolean; success: boolean };
const KEYS = new Set(["KeyZ", "Enter", "Space"]);
const DIRECTIONS = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];

function solved(masks: number[], rotations: number[], coordinates: Array<[number, number]>): boolean {
  const byCoord = new Map(coordinates.map((coordinate, index) => [`${coordinate[0]},${coordinate[1]}`, index]));
  const shown = masks.map((mask, tile) => new Set(Array.from({ length: 6 }, (_, direction) => direction).filter((direction) => mask & (1 << direction)).map((direction) => (direction + rotations[tile]) % 6)));
  return shown.every((directions, tile) => [...directions].every((direction) => {
    const [dq, dr] = DIRECTIONS[direction], [q, r] = coordinates[tile];
    const neighbor = byCoord.get(`${q + dq},${r + dr}`);
    return neighbor != null && shown[neighbor].has((direction + 3) % 6);
  }));
}

export function HexCircuitGame({ started, setup, onComplete }: { started: boolean; setup: Setup; onComplete: (result: Result) => void }) {
  const masks = setup.masks ?? [], coordinates = setup.coordinates ?? [];
  const signature = JSON.stringify([masks, coordinates]);
  const [rotations, setRotations] = useState(setup.rotations ?? Array(7).fill(0));
  const rotationsRef = useRef(rotations), moves = useRef(0), began = useRef(0), completed = useRef(false), completeRef = useRef(onComplete);
  const [remaining, setRemaining] = useState(setup.time_limit_ms ?? null);
  const touch = useRef<{ tile: number; at: number; timer: number } | null>(null);
  useEffect(() => { completeRef.current = onComplete; }, [onComplete]);
  useEffect(() => { rotationsRef.current = setup.rotations ?? Array(7).fill(0); setRotations(rotationsRef.current); moves.current = 0; }, [signature]);
  useEffect(() => { if (started) began.current = performance.now(); }, [started]);

  function finish(final: number[], timeout = false) {
    if (completed.current) return; completed.current = true;
    completeRef.current({ rotations: final, move_count: moves.current, elapsed_ms: performance.now() - began.current, timeout, success: !timeout && solved(masks, final, coordinates) });
  }
  function rotate(tile: number, left: boolean) {
    if (!started || completed.current) return;
    const next = rotationsRef.current.map((value, index) => index === tile ? (value + (left ? 1 : 5)) % 6 : value);
    rotationsRef.current = next; moves.current += 1; setRotations(next);
    if (solved(masks, next, coordinates)) finish(next);
  }
  function touchTile(tile: number) {
    const now = performance.now(), previous = touch.current;
    if (previous && previous.tile === tile && now - previous.at <= 280) {
      window.clearTimeout(previous.timer); touch.current = null; rotate(tile, false); return;
    }
    const timer = window.setTimeout(() => { rotate(tile, true); touch.current = null; }, 280);
    touch.current = { tile, at: now, timer };
  }
  useEffect(() => {
    if (!started || setup.time_limit_ms == null) return;
    const timer = window.setInterval(() => {
      const left = Number(setup.time_limit_ms) - (performance.now() - began.current); setRemaining(Math.max(0, left));
      if (left <= 0) { window.clearInterval(timer); finish(rotationsRef.current, true); }
    }, 50);
    return () => window.clearInterval(timer);
  }, [started, setup.time_limit_ms]);

  const centers = coordinates.map(([q, r]) => ({ x: 150 + q * 72 + r * 36, y: 150 + r * 64 }));
  return <Stack className="hex-circuit-game" spacing={1} alignItems="center">
    {setup.time_limit_ms != null && <Stack direction="row" spacing={1} alignItems="center" sx={{ width: "100%" }}><Typography variant="caption">Time</Typography><LinearProgress variant="determinate" value={Number(remaining) / Number(setup.time_limit_ms) * 100} sx={{ flex: 1 }} /></Stack>}
    <svg viewBox="0 0 300 300" role="group" aria-label="Seven tile hex circuit">
      {centers.map((center, tile) => <g key={tile} className="hex-tile" tabIndex={0} role="button" aria-label={`Circuit tile ${tile + 1}`} transform={`translate(${center.x} ${center.y})`} onContextMenu={(event) => event.preventDefault()} onPointerUp={(event) => { if (event.pointerType === "touch") touchTile(tile); else if (event.button === 0) rotate(tile, true); else if (event.button === 2) rotate(tile, false); }} onKeyDown={(event) => { if (KEYS.has(event.code) && !event.repeat) { event.preventDefault(); rotate(tile, !event.shiftKey); } }}>
        <g transform={`rotate(${-rotations[tile] * 60})`}><polygon points="0,-38 33,-19 33,19 0,38 -33,19 -33,-19" />{Array.from({ length: 6 }, (_, direction) => masks[tile] & (1 << direction) ? <line key={direction} x1="0" y1="0" x2={Math.cos(-direction * Math.PI / 3) * 30} y2={Math.sin(-direction * Math.PI / 3) * 30} /> : null)}</g>
      </g>)}
    </svg>
    <Typography variant="caption">{moves.current} moves · click left/right, double-touch for right</Typography>
  </Stack>;
}
