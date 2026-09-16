import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Button, LinearProgress, Stack, Typography } from "@mui/material";

type Skill = {
  id: string;
  behavior: string;
  parameters: Record<string, number>;
};
type Hazard = {
  id: string;
  type: "particle_rain" | "third_beam" | "spear_burst";
  x?: number;
  start_ms?: number;
  speed?: number;
  radius?: number;
  lane?: number;
  direction?: string;
  telegraph_start_ms?: number;
  active_start_ms?: number;
  active_end_ms?: number;
  damage_multiplier: number;
  source_x?: number;
  source_y?: number;
};
type Setup = {
  duration_ms?: number;
  control_mode?: "pointer" | "keyboard";
  initial_hp?: number;
  enemy_attack?: number;
  attack?: { name: string; hit_immunity_ms: number };
  mode?: { name: string };
  skills?: Skill[];
  hazards?: Hazard[];
};
type Sample = { elapsed_ms: number; x: number; y: number; shield_x?: number; shield_y?: number };
type SkillEvent = {
  elapsed_ms: number;
  skill_id: string;
  direction_x: number;
  direction_y: number;
};
type Result = {
  elapsed_ms: number;
  samples: Sample[];
  skill_events: SkillEvent[];
  timeout: boolean;
  success: boolean;
};
const MOVEMENT_KEYS = new Set([
  "KeyW",
  "KeyA",
  "KeyS",
  "KeyD",
  "ArrowUp",
  "ArrowLeft",
  "ArrowDown",
  "ArrowRight",
]);

export function DodgeBoxGame({
  started,
  setup,
  onComplete,
}: {
  started: boolean;
  setup: Setup;
  onComplete: (result: Result) => void;
}) {
  const duration = Number(setup.duration_ms ?? 5000),
    control = setup.control_mode ?? "pointer";
  const gravityMode =
    setup.skills?.some((skill) => skill.behavior === "blue_gravity") ?? false;
  const rollSkill = setup.skills?.find((skill) => skill.behavior === "roll");
  const movementSkill = setup.skills?.find((skill) =>
    ["free_move", "blue_gravity"].includes(skill.behavior),
  );
  const greenMode = Number(movementSkill?.parameters?.green_shield ?? 0) >= 0.5;
  const arena = useRef<HTMLDivElement>(null),
    began = useRef(0),
    previousFrame = useRef(0),
    completed = useRef(false),
    completeRef = useRef(onComplete);
  const held = useRef(new Set<string>()),
    positionRef = useRef({ x: 0.5, y: gravityMode ? 0.945 : 0.5 }),
    velocityY = useRef(0),
    lastDirection = useRef({ x: 1, y: 0 }),
    shieldRef = useRef({ x: 0, y: -1 });
  const samples = useRef<Sample[]>([]),
    skillEvents = useRef<SkillEvent[]>([]),
    lastSample = useRef(-100),
    rollUntil = useRef(0),
    rollReady = useRef(0),
    predictedLastHit = useRef(-1e9),
    predictedHpRef = useRef(Number(setup.initial_hp ?? 1)),
    jumpStarted = useRef(-1),
    predictedBlocks = useRef(new Set<string>());
  const [position, setPosition] = useState(positionRef.current),
    [remaining, setRemaining] = useState(duration),
    [elapsedView, setElapsedView] = useState(0),
    [predictedHp, setPredictedHp] = useState(Number(setup.initial_hp ?? 1)),
    [shield, setShield] = useState(shieldRef.current);
  const signature = JSON.stringify(setup);
  useEffect(() => {
    completeRef.current = onComplete;
  }, [onComplete]);
  useEffect(() => {
    positionRef.current = { x: 0.5, y: gravityMode ? 0.945 : 0.5 };
    shieldRef.current = { x: 0, y: -1 };
    velocityY.current = 0;
    samples.current = [];
    skillEvents.current = [];
    completed.current = false;
    held.current.clear();
    lastSample.current = -100;
    rollUntil.current = 0;
    rollReady.current = 0;
    predictedLastHit.current = -1e9;
    predictedHpRef.current = Number(setup.initial_hp ?? 1);
    jumpStarted.current = -1;
    predictedBlocks.current.clear();
    setPosition(positionRef.current);
    setRemaining(duration);
    setElapsedView(0);
    setPredictedHp(predictedHpRef.current);
    setShield(shieldRef.current);
  }, [signature, gravityMode, duration]);
  useEffect(() => {
    if (started) {
      began.current = performance.now();
      previousFrame.current = began.current;
      samples.current = [{ elapsed_ms: 0, ...positionRef.current, shield_x: shieldRef.current.x, shield_y: shieldRef.current.y }];
    }
  }, [started]);
  function move(next: { x: number; y: number }) {
    const clamped = {
      x: Math.max(0.035, Math.min(0.965, next.x)),
      y: Math.max(0.055, Math.min(0.945, next.y)),
    };
    positionRef.current = clamped;
    setPosition(clamped);
  }
  function point(event: ReactPointerEvent<HTMLDivElement>) {
    if (!started || control !== "pointer" || gravityMode || !arena.current)
      return;
    const rect = arena.current.getBoundingClientRect();
    if (greenMode) {
      const direction = quantizeDirection((event.clientX - rect.left) / rect.width - .5, (event.clientY - rect.top) / rect.height - .5);
      shieldRef.current = direction; setShield(direction); return;
    }
    move({
      x: (event.clientX - rect.left) / rect.width,
      y: (event.clientY - rect.top) / rect.height,
    });
  }
  function roll() {
    if (!started || !rollSkill) return;
    const at = performance.now() - began.current;
    if (at < rollReady.current) return;
    const parameters = rollSkill.parameters ?? {},
      direction = lastDirection.current;
    rollUntil.current = at + Number(parameters.duration_ms ?? 350);
    rollReady.current = at + Number(parameters.cooldown_ms ?? 1000);
    skillEvents.current.push({
      elapsed_ms: at,
      skill_id: rollSkill.id,
      direction_x: direction.x,
      direction_y: direction.y,
    });
  }
  useEffect(() => {
    if (!started) return;
    let frame = 0;
    const animate = (now: number) => {
      const at = now - began.current,
        delta = Math.min(50, now - previousFrame.current);
      previousFrame.current = now;
      const left = Number(
          held.current.has("KeyA") || held.current.has("ArrowLeft"),
        ),
        right = Number(
          held.current.has("KeyD") || held.current.has("ArrowRight"),
        );
      const up = Number(
          held.current.has("KeyW") || held.current.has("ArrowUp"),
        ),
        down = Number(
          held.current.has("KeyS") || held.current.has("ArrowDown"),
        );
      const dx = right - left,
        dy = down - up,
        rolling = at <= rollUntil.current;
      const speed =
        Number(movementSkill?.parameters?.speed ?? 1) *
        (rolling ? Number(rollSkill?.parameters?.speed ?? 2.4) : 1);
      if (greenMode) {
        if (dx || dy) {
          const direction = quantizeDirection(dx, dy);
          shieldRef.current = direction; setShield(direction);
        }
        move({ x: .5, y: .5 });
      } else if (gravityMode) {
        const grounded = positionRef.current.y >= 0.944;
        if (up && grounded && jumpStarted.current < 0) {
          velocityY.current =
            -0.00105 * Number(movementSkill?.parameters?.jump_strength ?? 1);
          jumpStarted.current = at;
        }
        if (
          up &&
          jumpStarted.current >= 0 &&
          at - jumpStarted.current <=
            Number(movementSkill?.parameters?.max_jump_hold_ms ?? 280)
        )
          velocityY.current -=
            0.00000065 *
            delta *
            Number(movementSkill?.parameters?.jump_strength ?? 1);
        if (!up) jumpStarted.current = -1;
        velocityY.current +=
          0.0000025 * delta * Number(movementSkill?.parameters?.gravity ?? 1);
        const horizontal = rolling ? lastDirection.current.x : dx;
        if (dx) lastDirection.current = { x: Math.sign(dx), y: 0 };
        move({
          x: positionRef.current.x + ((horizontal * delta) / 1500) * speed,
          y: positionRef.current.y + velocityY.current * delta,
        });
        if (positionRef.current.y >= 0.944) velocityY.current = 0;
      } else if (dx || dy || rolling) {
        const direction = rolling
          ? lastDirection.current
          : {
              x: dx / Math.max(1, Math.hypot(dx, dy)),
              y: dy / Math.max(1, Math.hypot(dx, dy)),
            };
        if (!rolling) lastDirection.current = direction;
        move({
          x: positionRef.current.x + ((direction.x * delta) / 1400) * speed,
          y: positionRef.current.y + ((direction.y * delta) / 840) * speed,
        });
      }
      if (at - lastSample.current >= 50 && samples.current.length < 256) {
        samples.current.push({ elapsed_ms: at, ...positionRef.current, shield_x: shieldRef.current.x, shield_y: shieldRef.current.y });
        lastSample.current = at;
      }
      if (
        !rolling &&
        at >=
          predictedLastHit.current +
            Number(setup.attack?.hit_immunity_ms ?? 500)
      ) {
        const hit = (setup.hazards ?? []).find((hazard) =>
          !predictedBlocks.current.has(hazard.id) && hazardHits(hazard, at, positionRef.current),
        );
        if (hit) {
          if (greenMode && hit.type === "spear_burst" && shieldBlocks(hit, shieldRef.current)) {
            predictedBlocks.current.add(hit.id);
          } else {
          predictedLastHit.current = at;
          predictedHpRef.current -=
            Number(setup.enemy_attack ?? 0) *
            Number(hit.damage_multiplier ?? 1);
          setPredictedHp(predictedHpRef.current);
          }
        }
      }
      setRemaining(Math.max(0, duration - at));
      setElapsedView(at);
      if (at >= duration || predictedHpRef.current < 1) {
        if (!completed.current) {
          completed.current = true;
          samples.current.push({ elapsed_ms: at, ...positionRef.current, shield_x: shieldRef.current.x, shield_y: shieldRef.current.y });
          completeRef.current({
            elapsed_ms: at,
            samples: samples.current,
            skill_events: skillEvents.current,
            timeout: false,
            success: true,
          });
        }
      } else frame = requestAnimationFrame(animate);
    };
    const down = (event: KeyboardEvent) => {
      if (event.code === "ShiftLeft" || event.code === "ShiftRight") {
        if (!event.repeat) roll();
        return;
      }
      if (MOVEMENT_KEYS.has(event.code)) {
        event.preventDefault();
        held.current.add(event.code);
      }
    };
    const up = (event: KeyboardEvent) => {
      if (MOVEMENT_KEYS.has(event.code)) held.current.delete(event.code);
    };
    frame = requestAnimationFrame(animate);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      held.current.clear();
    };
  }, [started, signature]);
  const virtual = (code: string, active: boolean) =>
    active ? held.current.add(code) : held.current.delete(code);
  return (
    <Stack className="dodge-box-game" spacing={1}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="caption">
          HP {Math.max(0, Math.ceil(predictedHp))}
        </Typography>
        <LinearProgress
          variant="determinate"
          value={(remaining / duration) * 100}
          sx={{ flex: 1 }}
        />
      </Stack>
      <div
        ref={arena}
        className="dodge-arena"
        role="application"
        aria-label={`${setup.mode?.name ?? "Base"} dodge arena`}
        onPointerDown={(event) => {
          if (event.button === 2) roll();
          else point(event);
        }}
        onContextMenu={(event) => event.preventDefault()}
        onPointerMove={point}
      >
        {(setup.hazards ?? []).map((hazard) => (
          <HazardView key={hazard.id} hazard={hazard} elapsed={elapsedView} />
        ))}
        <div
          className={`dodge-player ${elapsedView <= rollUntil.current ? "rolling" : ""}`}
          style={{ left: `${position.x * 100}%`, top: `${position.y * 100}%` }}
        />
        {greenMode && <span className="green-shield" style={{ left: "50%", top: "50%", transform: `translate(-50%, -50%) rotate(${Math.atan2(shield.y, shield.x) * 180 / Math.PI + 90}deg) translateY(-25px)` }} />}
      </div>
      {(greenMode || gravityMode || control === "keyboard") && (
        <Stack
          className="dodge-mobile-controls"
          direction="row"
          justifyContent="center"
          spacing={1}
        >
          <Button
            onPointerDown={() => virtual("ArrowLeft", true)}
            onPointerUp={() => virtual("ArrowLeft", false)}
            onPointerCancel={() => virtual("ArrowLeft", false)}
            onPointerLeave={() => virtual("ArrowLeft", false)}
          >
            Left
          </Button>
          {gravityMode && (
            <Button
              onPointerDown={() => virtual("ArrowUp", true)}
              onPointerUp={() => virtual("ArrowUp", false)}
              onPointerCancel={() => virtual("ArrowUp", false)}
              onPointerLeave={() => virtual("ArrowUp", false)}
            >
              Jump
            </Button>
          )}
          {greenMode && <Button onPointerDown={() => virtual("ArrowUp", true)} onPointerUp={() => virtual("ArrowUp", false)} onPointerCancel={() => virtual("ArrowUp", false)} onPointerLeave={() => virtual("ArrowUp", false)}>Up</Button>}
          <Button
            onPointerDown={() => virtual("ArrowRight", true)}
            onPointerUp={() => virtual("ArrowRight", false)}
            onPointerCancel={() => virtual("ArrowRight", false)}
            onPointerLeave={() => virtual("ArrowRight", false)}
          >
            Right
          </Button>
          {greenMode && <Button onPointerDown={() => virtual("ArrowDown", true)} onPointerUp={() => virtual("ArrowDown", false)} onPointerCancel={() => virtual("ArrowDown", false)} onPointerLeave={() => virtual("ArrowDown", false)}>Down</Button>}
          {rollSkill && <Button onClick={roll}>Roll</Button>}
        </Stack>
      )}
      <Typography variant="caption">
        {setup.attack?.name} · {setup.mode?.name} mode · enemy attack{" "}
        {setup.enemy_attack}
      </Typography>
    </Stack>
  );
}

function hazardHits(
  hazard: Hazard,
  at: number,
  position: { x: number; y: number },
) {
  if (hazard.type === "particle_rain") {
    const age = (at - Number(hazard.start_ms)) / 1000,
      y = age * Number(hazard.speed);
    return (
      age >= 0 &&
      y <= 1.1 &&
      Math.hypot(position.x - Number(hazard.x), position.y - y) <=
        0.03 + Number(hazard.radius)
    );
  }
  if (hazard.type === "spear_burst") {
    const age = (at - Number(hazard.start_ms)) / 1000;
    if (age < 0) return false;
    const distance = .7 - age * Number(hazard.speed);
    const x = .5 + Number(hazard.source_x) * distance;
    const y = .5 + Number(hazard.source_y) * distance;
    return Math.hypot(position.x - x, position.y - y) <= .035 + Number(hazard.radius);
  }
  if (at < Number(hazard.active_start_ms) || at > Number(hazard.active_end_ms))
    return false;
  const coordinate = hazard.direction === "vertical" ? position.x : position.y,
    lane = Number(hazard.lane);
  return coordinate >= lane / 3 && coordinate <= (lane + 1) / 3;
}

function HazardView({ hazard, elapsed }: { hazard: Hazard; elapsed: number }) {
  if (hazard.type === "particle_rain") {
    const age = (elapsed - Number(hazard.start_ms)) / 1000,
      y = age * Number(hazard.speed);
    return age >= 0 && y <= 1.1 ? (
      <span
        className="rain-particle"
        style={{
          left: `${Number(hazard.x) * 100}%`,
          top: `${y * 100}%`,
          width: `${Number(hazard.radius) * 200}%`,
          aspectRatio: "1",
        }}
      />
    ) : null;
  }
  if (hazard.type === "spear_burst") {
    const waiting = elapsed >= Number(hazard.telegraph_start_ms) && elapsed < Number(hazard.start_ms);
    const age = (elapsed - Number(hazard.start_ms)) / 1000;
    const distance = waiting ? .7 : .7 - Math.max(0, age) * Number(hazard.speed);
    if (!waiting && (age < 0 || distance < -.15)) return null;
    const x = .5 + Number(hazard.source_x) * distance;
    const y = .5 + Number(hazard.source_y) * distance;
    const angle = Math.atan2(-Number(hazard.source_y), -Number(hazard.source_x)) * 180 / Math.PI;
    return <span className={`spear-hazard ${waiting ? "warning" : "active"}`} style={{ left: `${x * 100}%`, top: `${y * 100}%`, transform: `translate(-50%, -50%) rotate(${angle}deg)` }} />;
  }
  const warning =
      elapsed >= Number(hazard.telegraph_start_ms) &&
      elapsed < Number(hazard.active_start_ms),
    active =
      elapsed >= Number(hazard.active_start_ms) &&
      elapsed <= Number(hazard.active_end_ms);
  if (!warning && !active) return null;
  const vertical = hazard.direction === "vertical",
    lane = Number(hazard.lane);
  return (
    <span
      className={`third-beam ${warning ? "warning" : "active"}`}
      style={
        vertical
          ? {
              left: `${(lane * 100) / 3}%`,
              width: "33.333%",
              top: 0,
              bottom: 0,
            }
          : {
              top: `${(lane * 100) / 3}%`,
              height: "33.333%",
              left: 0,
              right: 0,
            }
      }
    />
  );
}

function quantizeDirection(x: number, y: number) {
  if (Math.hypot(x, y) < .05) return { x: 0, y: -1 };
  const angle = Math.round(Math.atan2(y, x) / (Math.PI / 4)) * (Math.PI / 4);
  return { x: Math.cos(angle), y: Math.sin(angle) };
}

function shieldBlocks(hazard: Hazard, shield: { x: number; y: number }) {
  if (hazard.type !== "spear_burst") return false;
  return shield.x * Number(hazard.source_x) + shield.y * Number(hazard.source_y) >= Math.cos(Math.PI / 8);
}
