import { useCallback, useEffect, useRef, useState } from "react";
import { FormControlLabel, Slider, Switch } from "@mui/material";
import { api } from "./api";
import type { NoiseEvent, SceneEnvironment, UserAmbientPreferences, UserNoisePreferences } from "./types";

type Playing = { audio: HTMLAudioElement; gain: number; target: number };

export function AmbientPlayer({ projectId, revision, onScene }: { projectId: string; revision: number; onScene?: (scene: SceneEnvironment) => void }) {
  const active = useRef(new Map<string, Playing>());
  const [armed, setArmed] = useState(false);
  const [previewActive, setPreviewActive] = useState(false);
  const [prefs, setPrefs] = useState<UserAmbientPreferences>({ enabled: true, master_volume: 1 });
  const [scene, setScene] = useState<SceneEnvironment | null>(null);
  const load = useCallback(async () => {
    const [nextScene, nextPrefs] = await Promise.all([
      api<SceneEnvironment>(`/projects/${projectId}/environment/scene`),
      api<UserAmbientPreferences>("/preferences/ambient"),
    ]);
    setScene(nextScene); setPrefs(nextPrefs); onScene?.(nextScene);
  }, [projectId, onScene]);
  useEffect(() => { void load(); }, [load, revision]);
  useEffect(() => {
    const arm = () => setArmed(true);
    window.addEventListener("pointerdown", arm, { once: true });
    window.addEventListener("keydown", arm, { once: true });
    const refresh = () => void load();
    const preview = (raw: Event) => setPreviewActive(Boolean((raw as CustomEvent<boolean>).detail));
    window.addEventListener("storystudio-ambient-preferences", refresh);
    window.addEventListener("storystudio-ambient-preview-active", preview);
    return () => {
      window.removeEventListener("pointerdown", arm);
      window.removeEventListener("keydown", arm);
      window.removeEventListener("storystudio-ambient-preferences", refresh);
      window.removeEventListener("storystudio-ambient-preview-active", preview);
    };
  }, [load]);
  useEffect(() => {
    const desired = new Map((scene?.enabled && prefs.enabled && armed && !previewActive ? scene.ambient : []).map(item => [item.id, item]));
    for (const [id, item] of desired) {
      let playing = active.current.get(id);
      if (!playing) {
        const audio = new Audio(item.url); audio.loop = true; audio.preload = "auto"; audio.volume = 0; audio.playbackRate = item.playback_rate;
        playing = { audio, gain: 0, target: item.default_gain * prefs.master_volume };
        active.current.set(id, playing); void audio.play().catch(() => undefined);
      }
      playing.audio.playbackRate = item.playback_rate;
      playing.target = item.default_gain * prefs.master_volume;
    }
    for (const [id, playing] of active.current) if (!desired.has(id)) playing.target = 0;
  }, [scene, prefs, armed, previewActive]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      for (const [id, playing] of active.current) {
        playing.gain += Math.sign(playing.target - playing.gain) * Math.min(.05, Math.abs(playing.target - playing.gain));
        playing.audio.volume = Math.max(0, Math.min(1, playing.gain));
        if (playing.target === 0 && playing.gain === 0) { playing.audio.pause(); playing.audio.src = ""; active.current.delete(id); }
      }
    }, 50);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => () => { for (const item of active.current.values()) item.audio.pause(); active.current.clear(); }, [projectId]);
  return null;
}

export function AmbientPreferences({ fail }: { fail: (message: string) => void }) {
  const [prefs, setPrefs] = useState<UserAmbientPreferences>({ enabled: true, master_volume: 1 });
  const [noisePrefs, setNoisePrefs] = useState<UserNoisePreferences>({ enabled: true, master_volume: 1 });
  useEffect(() => { void Promise.all([api<UserAmbientPreferences>("/preferences/ambient"), api<UserNoisePreferences>("/preferences/noises")]).then(([ambient, noises]) => { setPrefs(ambient); setNoisePrefs(noises); }).catch(cause => fail(String(cause))); }, [fail]);
  async function save(next: UserAmbientPreferences) {
    setPrefs(next);
    try {
      setPrefs(await api("/preferences/ambient", { method: "PUT", body: JSON.stringify(next) }));
      window.dispatchEvent(new Event("storystudio-ambient-preferences"));
    } catch (cause) { fail(String(cause)); }
  }
  async function saveNoises(next: UserNoisePreferences) {
    setNoisePrefs(next);
    try {
      setNoisePrefs(await api("/preferences/noises", { method: "PUT", body: JSON.stringify(next) }));
      window.dispatchEvent(new Event("storystudio-noise-preferences"));
    } catch (cause) { fail(String(cause)); }
  }
  return <section className="ambient-preferences">
    <h3>Ambient sound</h3>
    <p>Separate looping environment sounds. Music settings are unaffected.</p>
    <FormControlLabel control={<Switch checked={prefs.enabled} onChange={event => void save({ ...prefs, enabled: event.target.checked })} />} label="Enable ambient sound" />
    <label>Master ambient volume<Slider min={0} max={1} step={.05} value={prefs.master_volume} onChange={(_, value) => setPrefs({ ...prefs, master_volume: Number(value) })} onChangeCommitted={(_, value) => void save({ ...prefs, master_volume: Number(value) })} /></label>
    <h3>Story noises</h3>
    <p>Separate one-shot effects requested by the story or minigames.</p>
    <FormControlLabel control={<Switch checked={noisePrefs.enabled} onChange={event => void saveNoises({ ...noisePrefs, enabled: event.target.checked })} />} label="Enable story noises" />
    <label>Noise volume<Slider min={0} max={1} step={.05} value={noisePrefs.master_volume} onChange={(_, value) => setNoisePrefs({ ...noisePrefs, master_volume: Number(value) })} onChangeCommitted={(_, value) => void saveNoises({ ...noisePrefs, master_volume: Number(value) })} /></label>
  </section>;
}

export function NoisePlayer({ projectId }: { projectId: string }) {
  const preferences = useRef<UserNoisePreferences>({ enabled: true, master_volume: 1 });
  const pending = useRef<NoiseEvent[]>([]);
  useEffect(() => {
    const load = () => void api<UserNoisePreferences>("/preferences/noises").then(value => { preferences.current = value; });
    const playNow = (noise: NoiseEvent, retry = true) => {
      const prefs = preferences.current;
      if (noise.project_id !== projectId || !prefs.enabled) return;
      const audio = new Audio(noise.url);
      audio.preload = "auto";
      audio.playbackRate = noise.playback_rate;
      audio.volume = Math.max(0, Math.min(1, noise.gain * prefs.master_volume));
      void audio.play().catch(() => { if (retry) pending.current.push(noise); });
    };
    const play = (raw: Event) => {
      const event = raw as CustomEvent<NoiseEvent>;
      const noise = event.detail;
      if (noise) playNow(noise);
    };
    const flush = () => {
      const queued = pending.current.splice(0);
      queued.forEach((noise) => playNow(noise, false));
    };
    load();
    window.addEventListener("storystudio-noise", play);
    window.addEventListener("storystudio-noise-preferences", load);
    window.addEventListener("pointerdown", flush);
    window.addEventListener("keydown", flush);
    return () => {
      window.removeEventListener("storystudio-noise", play);
      window.removeEventListener("storystudio-noise-preferences", load);
      window.removeEventListener("pointerdown", flush);
      window.removeEventListener("keydown", flush);
      pending.current = [];
    };
  }, [projectId]);
  return null;
}
