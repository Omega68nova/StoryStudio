import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, Paper, Stack, Typography } from "@mui/material";
import CasinoOutlinedIcon from "@mui/icons-material/CasinoOutlined";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { api } from "../api";
import type { MinigameSession } from "../types";
import { RedLightGame } from "./games/RedLightGame";
import { LockpickingGame } from "./games/LockpickingGame";
import { HexCircuitGame } from "./games/HexCircuitGame";
import { CircledTeethGame } from "./games/CircledTeethGame";
import { TimedAttackGame } from "./games/TimedAttackGame";
import { DodgeBoxGame } from "./bullethell/DodgeBoxGame";

type GameDraft = Record<string, unknown> & { elapsed_ms: number; success: boolean };
const REFLEX_KEYS = new Set(["KeyZ", "Enter", "Space"]);

function resultText(session: MinigameSession): string {
  const result = session.result ?? {};
  if (session.game_key === "roll_d20" || session.game_key === "roll_d6") return `Rolled ${result.roll} against difficulty ${result.difficulty}.`;
  if (session.game_key === "flip_coin") return `Called ${result.choice}; the coin landed ${result.flip}.`;
  if (session.game_key === "timing_hit") return `Marker distance from center: ${Number(result.distance ?? 0).toFixed(3)}.`;
  if (session.game_key === "key_mash") return `${result.count} presses against a target of ${result.target}.`;
  if (session.game_key === "red_light") return `${result.violation_ms} ms of mistakes against a ${result.lose_threshold_ms} ms limit.`;
  if (session.game_key === "lockpicking") return `${result.broken_picks} pick(s) broken${result.timed_out ? "; time expired" : ""}.`;
  if (session.game_key === "hex_circuit") return `${result.move_count} rotations${result.timed_out ? "; time expired" : ""}.`;
  if (session.game_key === "circled_teeth") return `${result.inserted_count}/${result.tooth_count} teeth inserted with ${result.strikes} strike(s)${result.timed_out ? "; time expired" : ""}.`;
  if (session.game_key === "timed_attack") return `${result.lines_hit}/${Number(result.lines_hit) + Number(result.lines_missed)} strikes landed · power ${result.attack_power} · damage ${result.damage}.`;
  if (session.game_key === "dodge_box") return `${result.attack_name ?? "Attack"} in ${result.mode_name ?? "Base"} mode · HP ${result.remaining_hp}/${result.initial_hp} · ${result.collisions ?? 0} hit(s), ${result.rolls ?? 0} roll(s), ${result.shield_blocks ?? 0} shield block(s).`;
  return "Challenge resolved.";
}

export function MinigameResult({ session }: { session: MinigameSession }) {
  return <Paper className="minigame-result" variant="outlined"><CasinoOutlinedIcon fontSize="small" /><span><strong>{session.invocation.challenge_text}</strong><small>{resultText(session)} {session.result?.success ? "Success." : "Failure."}</small></span></Paper>;
}

export function MinigameCheckpoint({ session, reload, fail }: { session: MinigameSession; reload: () => Promise<void>; fail: (message: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState(false);
  const [started, setStarted] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [marker, setMarker] = useState(0);
  const [count, setCount] = useState(0);
  const [draft, setDraft] = useState<GameDraft | null>(null);
  const startAt = useRef(0);
  const frame = useRef(0);
  const countRef = useRef(0);
  const forfeitedSession = useRef<string | null>(null);
  const setup = session.invocation.setup ?? {};
  const reflex = ["timing_hit", "key_mash", "red_light", "lockpicking", "hex_circuit", "circled_teeth", "timed_attack", "dodge_box"].includes(session.game_key);

  function failedReflexResult(): GameDraft {
    if (session.game_key === "timing_hit") return { position: Number(setup.target_start) > 0 ? 0 : 1, elapsed_ms: 0, success: false };
    if (session.game_key === "red_light") return { violation_ms: Number(setup.lose_threshold_ms ?? 1), elapsed_ms: 0, success: false };
    if (session.game_key === "lockpicking") return { broken_picks: 0, final_angle: 0, lock_rotation: 0, elapsed_ms: 0, timeout: true, success: false };
    if (session.game_key === "hex_circuit") return { rotations: setup.rotations ?? Array(7).fill(0), move_count: 0, elapsed_ms: 0, timeout: true, success: false };
    if (session.game_key === "circled_teeth") return { events: [], elapsed_ms: 0, timeout: true, success: false };
    if (session.game_key === "timed_attack") return { events: [], elapsed_ms: 0, timeout: true, success: false };
    if (session.game_key === "dodge_box") return { samples: [{ elapsed_ms: 0, x: .5, y: .5 }], skill_events: [], elapsed_ms: 0, timeout: true, success: false };
    return { count: 0, elapsed_ms: 0, success: false };
  }

  useEffect(() => {
    cancelAnimationFrame(frame.current);
    const interrupted = reflex && session.status === "awaiting_input" && Boolean(session.attempt_started_at);
    setBusy(false);
    setDialog(false);
    setStarted(false);
    setAttempted(interrupted);
    setMarker(0);
    setCount(0);
    countRef.current = 0;
    setDraft(null);
    if (interrupted && forfeitedSession.current !== session.id) {
      forfeitedSession.current = session.id;
      const result = failedReflexResult();
      setDraft(result);
      void resolve(result);
    }
  }, [session.id]);

  async function resolve(body: Record<string, unknown>) {
    if (busy) return;
    setBusy(true);
    try { await api(`/minigames/sessions/${session.id}/resolve`, { method: "POST", body: JSON.stringify(body) }); setDialog(false); await reload(); }
    catch (cause) { fail(String(cause)); } finally { setBusy(false); }
  }
  async function resume() {
    setBusy(true); try { await api(`/minigames/sessions/${session.id}/resume`, { method: "POST" }); await reload(); } catch (cause) { fail(String(cause)); } finally { setBusy(false); }
  }
  async function start() {
    if (attempted || busy) return;
    setBusy(true);
    try {
      const response = await api<{ changed: boolean }>(`/minigames/sessions/${session.id}/start`, { method: "POST" });
      if (!response.changed) {
        const result = failedReflexResult();
        setAttempted(true);
        setDraft(result);
        setBusy(false);
        await resolve(result);
        return;
      }
      cancelAnimationFrame(frame.current);
      setAttempted(true);
      startAt.current = performance.now();
      setStarted(true);
    } catch (cause) {
      fail(String(cause));
    } finally {
      setBusy(false);
    }
  }
  function press() {
    if (!started || draft) return;
    countRef.current += 1;
    setCount(countRef.current);
  }
  function pressPointer(event: ReactPointerEvent) {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    press();
  }
  function timingHit() {
    if (!started || draft) return;
    const elapsed = performance.now() - startAt.current;
    const position = marker;
    const success = position >= Number(setup.target_start) && position <= Number(setup.target_end);
    const result = { position, elapsed_ms: elapsed, success };
    setDraft(result); setStarted(false); cancelAnimationFrame(frame.current);
    void resolve(result);
  }
  function completeGame(result: GameDraft) {
    setDraft(result);
    setStarted(false);
    void resolve(result);
  }
  useEffect(() => {
    if (!dialog || !started || session.game_key !== "timing_hit") return;
    const animate = (now: number) => { const phase = ((now - startAt.current) / Number(setup.traversal_ms ?? 1000)) % 2; setMarker(phase <= 1 ? phase : 2 - phase); frame.current = requestAnimationFrame(animate); };
    frame.current = requestAnimationFrame(animate); return () => cancelAnimationFrame(frame.current);
  }, [dialog, started, session.game_key, setup.traversal_ms]);
  useEffect(() => {
    if (!dialog || !started || session.game_key !== "key_mash") return;
    const duration = Number(setup.duration_ms ?? 4000);
    const finish = window.setTimeout(() => {
      const elapsed = performance.now() - startAt.current;
      const finalCount = countRef.current;
      setStarted(false);
      const result = { count: finalCount, elapsed_ms: elapsed, success: finalCount >= Number(setup.target) };
      setCount(finalCount);
      setDraft(result);
      void resolve(result);
    }, duration);
    const key = (event: KeyboardEvent) => { if (REFLEX_KEYS.has(event.code) && !event.repeat) { event.preventDefault(); press(); } };
    window.addEventListener("keydown", key); return () => { window.clearTimeout(finish); window.removeEventListener("keydown", key); };
  }, [dialog, started, session.game_key, setup.duration_ms, setup.target]);
  useEffect(() => { if (!dialog || session.game_key !== "timing_hit") return; const key = (event: KeyboardEvent) => { if (REFLEX_KEYS.has(event.code) && !event.repeat) { event.preventDefault(); timingHit(); } }; window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key); });

  const waiting = session.status === "awaiting_input";
  return <><Paper className="minigame-checkpoint" elevation={3}><Stack direction="row" spacing={1} alignItems="center"><CasinoOutlinedIcon /><Typography variant="overline">Story challenge</Typography></Stack><Typography variant="h6">{session.invocation.challenge_text}</Typography><Typography variant="body2" color="text.secondary">Difficulty {session.invocation.difficulty}</Typography>
    {waiting && session.game_key === "roll_d20" && <Button variant="contained" disabled={busy} onClick={() => void resolve({})}>Roll d20</Button>}
    {waiting && session.game_key === "roll_d6" && <Button variant="contained" disabled={busy} onClick={() => void resolve({})}>Roll d6</Button>}
    {waiting && session.game_key === "flip_coin" && <Stack direction="row" spacing={1}><Button fullWidth variant="contained" disabled={busy} onClick={() => void resolve({ choice: "heads" })}>Heads</Button><Button fullWidth variant="contained" disabled={busy} onClick={() => void resolve({ choice: "tails" })}>Tails</Button></Stack>}
    {waiting && reflex && <Button variant="contained" startIcon={<PlayArrowIcon />} disabled={attempted} onClick={() => setDialog(true)}>{attempted ? "Attempt in progress" : "Play challenge"}</Button>}
    {!waiting && <Alert severity={session.result?.success ? "success" : "warning"}>{resultText(session)} {session.result?.success ? "Challenge succeeded." : "Challenge failed."} {session.job_status === "interrupted" && <Button disabled={busy} onClick={() => void resume()}>Resume Story</Button>}{["queued", "running"].includes(session.job_status ?? "") && " The storyteller is continuing…"}</Alert>}
  </Paper>
  <Dialog open={dialog} onClose={() => { if (!attempted && !busy) setDialog(false); }} disableEscapeKeyDown={attempted || busy} fullWidth maxWidth="sm"><DialogTitle>{session.game_key === "timing_hit" ? "Timing challenge" : session.game_key === "key_mash" ? "Key-spam challenge" : session.game_key === "red_light" ? "Fishing / red-light challenge" : session.game_key === "lockpicking" ? "Lockpicking challenge" : session.game_key === "circled_teeth" ? "Circled-teeth challenge" : session.game_key === "timed_attack" ? "Timed attack" : session.game_key === "dodge_box" ? "Dodge box" : "Hex-circuit challenge"}</DialogTitle><DialogContent>
    {!["lockpicking", "hex_circuit", "circled_teeth", "timed_attack", "dodge_box"].includes(session.game_key) && <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Use Z, Enter, Space, or left-click.</Typography>}
    {session.game_key === "timing_hit"
      ? <Box className="timing-game" onClick={timingHit} role="button" tabIndex={0} aria-label="Hit the timing marker"><div className="timing-target" style={{ left: `${Number(setup.target_start) * 100}%`, width: `${(Number(setup.target_end) - Number(setup.target_start)) * 100}%` }} /><div className="timing-marker" style={{ left: `calc(${marker * 100}% - 2px)` }} /></Box>
      : session.game_key === "key_mash"
        ? <Stack alignItems="center" spacing={2}><Typography variant="h2">{count}</Typography><Typography>Target: {setup.target} presses in 4 seconds</Typography><Button className="mash-button" variant="contained" disabled={!started} onPointerDown={pressPointer}>PRESS</Button>{started && <LinearProgress sx={{ width: "100%" }} />}</Stack>
        : session.game_key === "red_light"
          ? <RedLightGame started={started} setup={setup} onComplete={completeGame} />
          : session.game_key === "lockpicking"
            ? <LockpickingGame started={started} setup={setup} onComplete={completeGame} />
            : session.game_key === "hex_circuit"
              ? <HexCircuitGame started={started} setup={setup} onComplete={completeGame} />
              : session.game_key === "circled_teeth"
                ? <CircledTeethGame started={started} setup={setup} onComplete={completeGame} />
                : session.game_key === "timed_attack"
                  ? <TimedAttackGame started={started} setup={setup} onComplete={completeGame} />
                  : <DodgeBoxGame started={started} setup={setup as any} onComplete={completeGame} />}
    {draft && <Alert severity={draft.success ? "success" : "warning"} sx={{ mt: 2 }}>{draft.success ? "Success" : "Missed"}</Alert>}
  </DialogContent><DialogActions>{!attempted && <Button onClick={() => setDialog(false)}>Close</Button>}{!attempted && <Button variant="contained" disabled={busy} onClick={() => void start()}>Start</Button>}{draft && !busy && <Button variant="contained" onClick={() => void resolve(draft)}>Retry submission</Button>}</DialogActions></Dialog></>;
}
