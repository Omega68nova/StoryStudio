import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { LinearProgress, Stack, Typography } from "@mui/material";

type Setup = {
  slot_count?: number; occupied_slots?: number[]; revolution_ms?: number; strike_limit?: number;
  hit_window_fraction?: number; initial_angle?: number; initial_direction?: number;
  reverse_on_success?: boolean; time_limit_ms?: number | null;
};
type PressEvent = { elapsed_ms: number; slot_index: number | null; action: "insert" | "pull_out" | "empty" };
type Result = { events: PressEvent[]; elapsed_ms: number; timeout: boolean; success: boolean };
const KEYS = new Set(["KeyZ", "Enter", "Space"]);

export function CircledTeethGame({ started, setup, onComplete }: { started: boolean; setup: Setup; onComplete: (result: Result) => void }) {
  const slotCount = Number(setup.slot_count ?? 8);
  const occupied = useRef(new Set((setup.occupied_slots ?? []).map(Number)));
  const inserted = useRef(new Set<number>());
  const events = useRef<PressEvent[]>([]);
  const began = useRef(0), anchorElapsed = useRef(0), anchorAngle = useRef(Number(setup.initial_angle ?? 0));
  const direction = useRef(Number(setup.initial_direction ?? 1));
  const completeRef = useRef(onComplete), completed = useRef(false);
  const [angle, setAngle] = useState(anchorAngle.current), [strikes, setStrikes] = useState(0);
  const strikesRef = useRef(0);
  const [insertedView, setInsertedView] = useState<number[]>([]);
  const [remaining, setRemaining] = useState<number | null>(setup.time_limit_ms ?? null);
  const signature = JSON.stringify(setup);

  useEffect(() => { completeRef.current = onComplete; }, [onComplete]);
  useEffect(() => {
    occupied.current = new Set((setup.occupied_slots ?? []).map(Number)); inserted.current = new Set(); events.current = [];
    anchorElapsed.current = 0; anchorAngle.current = Number(setup.initial_angle ?? 0); direction.current = Number(setup.initial_direction ?? 1);
    strikesRef.current = 0; completed.current = false; setStrikes(0); setInsertedView([]); setAngle(anchorAngle.current); setRemaining(setup.time_limit_ms ?? null);
  }, [signature]);
  useEffect(() => {
    if (!started) return;
    began.current = performance.now(); anchorElapsed.current = 0;
  }, [started]);

  function angleAt(elapsed: number) {
    const revolution = Number(setup.revolution_ms ?? 2000);
    return ((anchorAngle.current + direction.current * ((elapsed - anchorElapsed.current) / revolution)) % 1 + 1) % 1;
  }
  function finish(elapsed: number, timeout: boolean, success: boolean) {
    if (completed.current) return;
    completed.current = true;
    completeRef.current({ events: events.current, elapsed_ms: elapsed, timeout, success });
  }
  function press() {
    if (!started || completed.current) return;
    const elapsed = performance.now() - began.current, current = angleAt(elapsed);
    const nearest = Math.floor(current * slotCount + .5) % slotCount;
    const rawDistance = Math.abs(current - nearest / slotCount), distance = Math.min(rawDistance, 1 - rawDistance);
    const insideWindow = distance <= Number(setup.hit_window_fraction ?? .5) / (2 * slotCount);
    let action: PressEvent["action"];
    if (insideWindow && occupied.current.has(nearest)) {
      if (inserted.current.has(nearest)) {
        inserted.current.delete(nearest); strikesRef.current += 1; action = "pull_out";
      } else {
        inserted.current.add(nearest); action = "insert";
        if (setup.reverse_on_success) direction.current *= -1;
      }
    } else {
      strikesRef.current += 1; action = "empty";
    }
    events.current.push({ elapsed_ms: elapsed, slot_index: insideWindow ? nearest : null, action });
    anchorAngle.current = current; anchorElapsed.current = elapsed;
    setAngle(current); setStrikes(strikesRef.current); setInsertedView([...inserted.current]);
    const success = inserted.current.size === occupied.current.size;
    const failed = strikesRef.current >= Number(setup.strike_limit ?? 3);
    if (success || failed) finish(elapsed, false, success);
  }
  function pointerPress(event: ReactPointerEvent<SVGSVGElement>) {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    event.preventDefault(); press();
  }
  useEffect(() => {
    if (!started) return;
    let frame = 0;
    const animate = () => { if (!completed.current) { setAngle(angleAt(performance.now() - began.current)); frame = requestAnimationFrame(animate); } };
    frame = requestAnimationFrame(animate);
    const key = (event: KeyboardEvent) => { if (KEYS.has(event.code) && !event.repeat) { event.preventDefault(); press(); } };
    window.addEventListener("keydown", key);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("keydown", key); };
  }, [started, signature]);
  useEffect(() => {
    if (!started || setup.time_limit_ms == null) return;
    const timer = window.setInterval(() => {
      const elapsed = performance.now() - began.current, left = Number(setup.time_limit_ms) - elapsed;
      setRemaining(Math.max(0, left));
      if (left <= 0) { window.clearInterval(timer); finish(elapsed, true, false); }
    }, 50);
    return () => window.clearInterval(timer);
  }, [started, setup.time_limit_ms, signature]);

  const slots = Array.from({ length: slotCount }, (_, index) => index);
  return <Stack className="circled-teeth-game" spacing={1} alignItems="center">
    {setup.time_limit_ms != null && <Stack direction="row" spacing={1} alignItems="center" sx={{ width: "100%" }}><Typography variant="caption">Time</Typography><LinearProgress variant="determinate" value={Math.max(0, Number(remaining) / Number(setup.time_limit_ms) * 100)} sx={{ flex: 1 }} /></Stack>}
    <svg viewBox="0 0 300 300" role="button" tabIndex={0} aria-label="Activate the tooth under the rotating arrow" onPointerDown={pointerPress}>
      <circle className="teeth-ring" cx="150" cy="150" r="104" />
      {slots.map((slot) => {
        const occupiedSlot = occupied.current.has(slot), isInserted = insertedView.includes(slot);
        return <g key={slot} transform={`rotate(${slot * 360 / slotCount} 150 150)`}>
          <circle className="teeth-slot" cx="150" cy="42" r="4" />
          {occupiedSlot && <rect className={`circle-tooth ${isInserted ? "inserted" : ""}`} x="143" y={isInserted ? 54 : 30} width="14" height="35" rx="3" />}
        </g>;
      })}
      <g className="teeth-arrow" transform={`rotate(${angle * 360} 150 150)`}><path d="M150 10 L140 29 L160 29 Z" /></g>
      <circle className="teeth-core" cx="150" cy="150" r="48" />
      <text x="150" y="145" textAnchor="middle">{insertedView.length}/{occupied.current.size}</text>
      <text x="150" y="164" textAnchor="middle" className="teeth-strikes">{strikes}/{setup.strike_limit ?? 3} strikes</text>
    </svg>
    <Typography variant="caption">Z, Enter, Space, click, or tap when the arrow crosses a tooth.</Typography>
  </Stack>;
}
