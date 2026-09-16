import { useCallback, useEffect, useRef, useState } from "react";
import { FormControlLabel, Slider, Switch } from "@mui/material";
import { api } from "./api";
import type { SceneEnvironment, UserAmbientPreferences } from "./types";

type Playing = { audio: HTMLAudioElement; gain: number; target: number };

export function AmbientPlayer({ projectId, revision, onScene }: { projectId: string; revision: number; onScene?: (scene: SceneEnvironment) => void }) {
  const active = useRef(new Map<string, Playing>());
  const [armed, setArmed] = useState(false);
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
    window.addEventListener("storystudio-ambient-preferences", refresh);
    return () => { window.removeEventListener("pointerdown", arm); window.removeEventListener("keydown", arm); window.removeEventListener("storystudio-ambient-preferences", refresh); };
  }, [load]);
  useEffect(() => {
    const desired = new Map((scene?.enabled && prefs.enabled && armed ? scene.ambient : []).map(item => [item.id, item]));
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
  }, [scene, prefs, armed]);
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
  useEffect(() => { void api<UserAmbientPreferences>("/preferences/ambient").then(setPrefs).catch(cause => fail(String(cause))); }, [fail]);
  async function save(next: UserAmbientPreferences) {
    setPrefs(next);
    try {
      setPrefs(await api("/preferences/ambient", { method: "PUT", body: JSON.stringify(next) }));
      window.dispatchEvent(new Event("storystudio-ambient-preferences"));
    } catch (cause) { fail(String(cause)); }
  }
  return <section className="ambient-preferences">
    <h3>Ambient sound</h3>
    <p>Separate looping environment sounds. Music settings are unaffected.</p>
    <FormControlLabel control={<Switch checked={prefs.enabled} onChange={event => void save({ ...prefs, enabled: event.target.checked })} />} label="Enable ambient sound" />
    <label>Master ambient volume<Slider min={0} max={1} step={.05} value={prefs.master_volume} onChange={(_, value) => setPrefs({ ...prefs, master_volume: Number(value) })} onChangeCommitted={(_, value) => void save({ ...prefs, master_volume: Number(value) })} /></label>
  </section>;
}
