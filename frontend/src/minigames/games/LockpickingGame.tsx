import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Box, Button, LinearProgress, Stack, Typography } from "@mui/material";

type Setup = { sweet_center?: number; sweet_width?: number; pick_durability_ms?: number; attempt_limit?: number | null; attempt_source?: string; time_limit_ms?: number | null };
type Result = { broken_picks: number; final_angle: number; lock_rotation: number; elapsed_ms: number; timeout: boolean; success: boolean };
const TORQUE_KEYS = new Set(["KeyZ", "Enter", "Space"]);

export function LockpickingGame({ started, setup, onComplete }: { started: boolean; setup: Setup; onComplete: (result: Result) => void }) {
  const center = Number(setup.sweet_center ?? 0), width = Number(setup.sweet_width ?? 20);
  const durabilityMax = Number(setup.pick_durability_ms ?? 900), limit = setup.attempt_limit;
  const timeLimit = setup.time_limit_ms == null ? null : Number(setup.time_limit_ms);
  const [angle, setAngle] = useState(0), angleRef = useRef(0);
  const [rotation, setRotation] = useState(0), rotationRef = useRef(0);
  const [durability, setDurability] = useState(durabilityMax), durabilityRef = useRef(durabilityMax);
  const [broken, setBroken] = useState(0), brokenRef = useRef(0);
  const [remainingTime, setRemainingTime] = useState(timeLimit);
  const held = useRef(new Set<string>()), frame = useRef(0), completed = useRef(false), completeRef = useRef(onComplete);
  useEffect(() => { completeRef.current = onComplete; }, [onComplete]);

  function setPickAngle(value: number) { const next = Math.max(-90, Math.min(90, value)); angleRef.current = next; setAngle(next); }
  function positionPick(event: ReactPointerEvent<HTMLDivElement>) {
    if (!started || held.current.size) return;
    if (event.pointerType !== "mouse" && !event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.setPointerCapture(event.pointerId);
    const bounds = event.currentTarget.getBoundingClientRect();
    setPickAngle((event.clientX - bounds.left) / bounds.width * 180 - 90);
  }
  function hold(name: string) { if (started) held.current.add(name); }
  function release(name: string) { held.current.delete(name); }
  function torqueDown(event: ReactPointerEvent<HTMLButtonElement>) { if (event.pointerType === "mouse" && event.button !== 0) return; event.currentTarget.setPointerCapture(event.pointerId); hold(`pointer:${event.pointerId}`); }
  function torqueUp(event: ReactPointerEvent<HTMLButtonElement>) { release(`pointer:${event.pointerId}`); }

  useEffect(() => {
    if (!started) return;
    const down = (event: KeyboardEvent) => { if (TORQUE_KEYS.has(event.code)) { event.preventDefault(); if (!event.repeat) hold(`key:${event.code}`); } };
    const up = (event: KeyboardEvent) => { if (TORQUE_KEYS.has(event.code)) { event.preventDefault(); release(`key:${event.code}`); } };
    const releaseAll = () => held.current.clear();
    window.addEventListener("keydown", down); window.addEventListener("keyup", up); window.addEventListener("blur", releaseAll);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); window.removeEventListener("blur", releaseAll); };
  }, [started]);

  useEffect(() => {
    if (!started || completed.current) return;
    const began = performance.now(); let last = began;
    const finish = (success: boolean, timeout = false) => {
      if (completed.current) return; completed.current = true; held.current.clear(); cancelAnimationFrame(frame.current);
      completeRef.current({ broken_picks: brokenRef.current, final_angle: angleRef.current, lock_rotation: rotationRef.current, elapsed_ms: performance.now() - began, timeout, success });
    };
    const animate = (now: number) => {
      const delta = Math.min(50, now - last); last = now;
      const elapsed = now - began;
      if (timeLimit != null) { setRemainingTime(Math.max(0, timeLimit - elapsed)); if (elapsed >= timeLimit) { finish(false, true); return; } }
      const error = Math.abs(angleRef.current - center), half = width / 2;
      const maximum = error <= half ? 90 : Math.max(3, 82 * (1 - Math.min(1, (error - half) / Math.max(1, 90 - half))));
      if (held.current.size) {
        rotationRef.current = Math.min(maximum, rotationRef.current + delta * .09);
        if (rotationRef.current >= 88 && error <= half) { setRotation(rotationRef.current); finish(true); return; }
        if (maximum < 88 && rotationRef.current >= maximum - .5) {
          durabilityRef.current -= delta;
          if (durabilityRef.current <= 0) {
            brokenRef.current += 1; setBroken(brokenRef.current);
            if (limit != null && brokenRef.current >= limit) { durabilityRef.current = 0; setDurability(0); finish(false); return; }
            durabilityRef.current = durabilityMax; rotationRef.current = 0; held.current.clear();
          }
        }
      } else rotationRef.current = Math.max(0, rotationRef.current - delta * .14);
      setRotation(rotationRef.current); setDurability(Math.max(0, durabilityRef.current));
      frame.current = requestAnimationFrame(animate);
    };
    frame.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame.current);
  }, [started, center, width, durabilityMax, limit, timeLimit]);

  return <Stack className="lockpick-game" spacing={1.5}>
    <Box className="lockpick-arc" onPointerDown={positionPick} onPointerMove={positionPick} aria-label="Position the lockpick">
      <div className="lock-cylinder" style={{ transform: `rotate(${rotation}deg)` }} />
      <div className="lock-pick" style={{ transform: `rotate(${angle}deg)` }} />
    </Box>
    <Stack direction="row" spacing={1}><Typography variant="caption">Pick condition</Typography><LinearProgress variant="determinate" value={durability / durabilityMax * 100} color={durability < durabilityMax * .3 ? "error" : "primary"} sx={{ flex: 1 }} /></Stack>
    <Typography variant="body2">Picks: {limit == null ? "∞" : Math.max(0, limit - broken)} · source: {setup.attempt_source ?? "story"}{timeLimit != null ? ` · ${Math.ceil(Number(remainingTime) / 1000)}s` : ""}</Typography>
    <Button className="lock-torque" variant="contained" disabled={!started} onPointerDown={torqueDown} onPointerUp={torqueUp} onPointerCancel={torqueUp} onLostPointerCapture={torqueUp}>HOLD TO TURN</Button>
  </Stack>;
}
