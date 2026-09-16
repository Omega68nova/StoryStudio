import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Stack, Typography } from "@mui/material";

type Line = { id: number; start_ms: number; traversal_ms: number };
type Setup = { lines?: Line[]; sweet_width?: number; duration_ms?: number; damage_per_line?: number };
type AttackEvent = { line_id: number; elapsed_ms: number };
type Result = { events: AttackEvent[]; elapsed_ms: number; timeout: boolean; success: boolean };
const KEYS = new Set(["KeyZ", "Enter", "Space"]);

export function TimedAttackGame({ started, setup, onComplete }: { started: boolean; setup: Setup; onComplete: (result: Result) => void }) {
  const lines = setup.lines ?? [], duration = Number(setup.duration_ms ?? 1000);
  const began = useRef(0), used = useRef(new Set<number>()), events = useRef<AttackEvent[]>([]), completed = useRef(false), completeRef = useRef(onComplete);
  const [elapsed, setElapsed] = useState(0), [usedView, setUsedView] = useState<number[]>([]);
  const signature = JSON.stringify(setup);
  useEffect(() => { completeRef.current = onComplete; }, [onComplete]);
  useEffect(() => { used.current = new Set(); events.current = []; completed.current = false; setElapsed(0); setUsedView([]); }, [signature]);
  useEffect(() => { if (started) began.current = performance.now(); }, [started]);
  function finish(at: number) { if (completed.current) return; completed.current = true; completeRef.current({ events: events.current, elapsed_ms: at, timeout: false, success: true }); }
  function strike() {
    if (!started || completed.current) return;
    const at = performance.now() - began.current;
    const active = lines.flatMap((line) => {
      if (used.current.has(line.id)) return [];
      const progress = (at - line.start_ms) / line.traversal_ms;
      return progress >= 0 && progress <= 1 ? [{ line, progress }] : [];
    });
    if (!active.length) return;
    const selected = active.reduce((rightmost, item) => item.progress > rightmost.progress ? item : rightmost);
    used.current.add(selected.line.id); events.current.push({ line_id: selected.line.id, elapsed_ms: at }); setUsedView([...used.current]);
  }
  function pointerStrike(event: ReactPointerEvent<HTMLDivElement>) { if (event.pointerType === "mouse" && event.button !== 0) return; event.preventDefault(); strike(); }
  useEffect(() => {
    if (!started) return;
    let frame = 0;
    const animate = () => { const at = performance.now() - began.current; setElapsed(Math.min(duration, at)); if (at >= duration) finish(at); else frame = requestAnimationFrame(animate); };
    const key = (event: KeyboardEvent) => { if (KEYS.has(event.code) && !event.repeat) { event.preventDefault(); strike(); } };
    frame = requestAnimationFrame(animate); window.addEventListener("keydown", key);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("keydown", key); };
  }, [started, signature]);
  return <Stack className="timed-attack-game" spacing={1}>
    <div className="attack-bar" role="button" tabIndex={0} aria-label="Strike the rightmost cursor near the center" onPointerDown={pointerStrike}>
      <div className="attack-sweetspot" style={{ width: `${Number(setup.sweet_width ?? .2) * 100}%` }} />
      <div className="attack-center" />
      {lines.map((line) => { const progress = (elapsed - line.start_ms) / line.traversal_ms; return progress >= 0 && progress <= 1 && !usedView.includes(line.id) ? <div key={line.id} className="attack-line" style={{ left: `${progress * 100}%` }} /> : null; })}
    </div>
    <Typography variant="caption">{usedView.length}/{lines.length} strikes · Z, Enter, Space, click, or tap</Typography>
  </Stack>;
}
