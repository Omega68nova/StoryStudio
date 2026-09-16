import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Box, Button, LinearProgress, Stack, Typography } from "@mui/material";

type LightPhase = { color: "green" | "red"; duration_ms: number; warning_ms: number };
type RedLightSetup = { phases?: LightPhase[]; duration_ms?: number; lose_threshold_ms?: number };
type RedLightResult = { violation_ms: number; elapsed_ms: number; success: boolean };

const HOLD_KEYS = new Set(["KeyZ", "Enter", "Space"]);

export function RedLightGame({ started, setup, onComplete }: {
  started: boolean;
  setup: RedLightSetup;
  onComplete: (result: RedLightResult) => void;
}) {
  const phases = setup.phases ?? [];
  const phaseSignature = JSON.stringify(phases);
  const duration = Number(setup.duration_ms ?? phases.reduce((sum, phase) => sum + phase.duration_ms, 0));
  const threshold = Number(setup.lose_threshold_ms ?? 700);
  const [color, setColor] = useState<"green" | "red">(phases[0]?.color ?? "green");
  const [warning, setWarning] = useState(false);
  const [holding, setHolding] = useState(false);
  const [progress, setProgress] = useState(0);
  const [violation, setViolation] = useState(0);
  const heldInputs = useRef(new Set<string>());
  const completed = useRef(false);
  const frame = useRef(0);
  const completeRef = useRef(onComplete);

  useEffect(() => { completeRef.current = onComplete; }, [onComplete]);

  function updateHolding() { setHolding(heldInputs.current.size > 0); }
  function hold(name: string) { heldInputs.current.add(name); updateHolding(); }
  function release(name: string) { heldInputs.current.delete(name); updateHolding(); }
  function pointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!started || (event.pointerType === "mouse" && event.button !== 0)) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    hold(`pointer:${event.pointerId}`);
  }
  function pointerUp(event: ReactPointerEvent<HTMLButtonElement>) { release(`pointer:${event.pointerId}`); }

  useEffect(() => {
    if (!started) return;
    const keyDown = (event: KeyboardEvent) => {
      if (!HOLD_KEYS.has(event.code)) return;
      event.preventDefault();
      if (!event.repeat) hold(`key:${event.code}`);
    };
    const keyUp = (event: KeyboardEvent) => {
      if (!HOLD_KEYS.has(event.code)) return;
      event.preventDefault();
      release(`key:${event.code}`);
    };
    const releaseAll = () => { heldInputs.current.clear(); updateHolding(); };
    window.addEventListener("keydown", keyDown);
    window.addEventListener("keyup", keyUp);
    window.addEventListener("blur", releaseAll);
    return () => {
      window.removeEventListener("keydown", keyDown);
      window.removeEventListener("keyup", keyUp);
      window.removeEventListener("blur", releaseAll);
    };
  }, [started]);

  useEffect(() => {
    if (!started || !phases.length || duration <= 0 || completed.current) return;
    const beganAt = performance.now();
    let lastAt = beganAt;
    let accumulatedViolation = 0;
    const finish = (elapsed: number, success: boolean) => {
      if (completed.current) return;
      completed.current = true;
      cancelAnimationFrame(frame.current);
      heldInputs.current.clear();
      setHolding(false);
      completeRef.current({ violation_ms: Math.round(accumulatedViolation), elapsed_ms: Math.round(elapsed), success });
    };
    const animate = (now: number) => {
      const elapsed = now - beganAt;
      const delta = Math.min(100, now - lastAt);
      lastAt = now;
      let phaseStart = 0;
      let active = phases[phases.length - 1];
      for (const phase of phases) {
        if (elapsed < phaseStart + phase.duration_ms) { active = phase; break; }
        phaseStart += phase.duration_ms;
      }
      const incorrect = (active.color === "green") !== (heldInputs.current.size > 0);
      if (incorrect) accumulatedViolation += delta;
      setColor(active.color);
      setWarning(elapsed >= phaseStart + active.duration_ms - active.warning_ms && elapsed < phaseStart + active.duration_ms);
      setProgress(Math.min(100, elapsed / duration * 100));
      setViolation(accumulatedViolation);
      if (accumulatedViolation >= threshold) { finish(elapsed, false); return; }
      if (elapsed >= duration) { finish(elapsed, true); return; }
      frame.current = requestAnimationFrame(animate);
    };
    frame.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame.current);
  }, [started, duration, phaseSignature, threshold]);

  return <Stack className={`red-light-game ${color}${warning ? " warning" : ""}`} spacing={1.5} alignItems="stretch">
    <Box className="red-light-signal">
      <Typography variant="h4">{warning ? "GET READY…" : color === "green" ? "GREEN — HOLD" : "RED — RELEASE"}</Typography>
      <Typography variant="body2">{holding ? "Holding" : "Released"}</Typography>
    </Box>
    <LinearProgress variant="determinate" value={progress} aria-label="Round progress" />
    <Stack direction="row" alignItems="center" spacing={1}><Typography variant="caption">Mistakes</Typography><LinearProgress color="error" variant="determinate" value={Math.min(100, violation / threshold * 100)} aria-label="Mistake threshold" sx={{ flex: 1 }} /><Typography variant="caption">{Math.round(violation)} / {Math.round(threshold)} ms</Typography></Stack>
    <Button className="red-light-hold" variant="contained" disabled={!started} onPointerDown={pointerDown} onPointerUp={pointerUp} onPointerCancel={pointerUp} onLostPointerCapture={pointerUp}>HOLD</Button>
  </Stack>;
}
