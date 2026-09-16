import { useCallback, useEffect, useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, IconButton, MenuItem, Slider, TextField, Tooltip } from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import KeyboardArrowUpIcon from "@mui/icons-material/KeyboardArrowUp";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { api } from "./api";
import type { MusicTheme, ProjectMusic } from "./types";

export function MusicStudio({ projectId, revision, fail }: { projectId: string; revision: number; fail: (message: string) => void }) {
  const [themes, setThemes] = useState<MusicTheme[]>([]);
  const [settings, setSettings] = useState<ProjectMusic | null>(null);
  const [name, setName] = useState("");
  const [editingTheme, setEditingTheme] = useState<MusicTheme | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [deletingTheme, setDeletingTheme] = useState<MusicTheme | null>(null);
  const load = useCallback(async () => {
    const [library, config] = await Promise.all([api<MusicTheme[]>("/music/themes"), api<ProjectMusic>(`/projects/${projectId}/music`)]);
    setThemes(library); setSettings(config);
  }, [projectId]);
  useEffect(() => { void load().catch((cause) => fail(String(cause))); }, [load, revision, fail]);

  async function save(patch: Partial<ProjectMusic> = {}) {
    if (!settings) return;
    try { setSettings(await api(`/projects/${projectId}/music`, { method: "PUT", body: JSON.stringify({ ...settings, ...patch }) })); }
    catch (cause) { fail(String(cause)); }
  }
  async function createTheme() {
    if (!name.trim()) return;
    try { await api("/music/themes", { method: "POST", body: JSON.stringify({ name, description: "", playback_mode: "shuffle" }) }); setName(""); await load(); }
    catch (cause) { fail(String(cause)); }
  }
  async function upload(themeId: string, file: File) {
    const form = new FormData(); form.append("file", file);
    try { await api(`/music/themes/${themeId}/tracks?title=${encodeURIComponent(file.name.replace(/\.[^.]+$/, ""))}`, { method: "POST", body: form }); await load(); }
    catch (cause) { fail(String(cause)); }
  }
  async function updateTheme(theme: MusicTheme, patch: Partial<MusicTheme>) {
    try { await api(`/music/themes/${theme.id}`, { method: "PUT", body: JSON.stringify({ name: theme.name, description: theme.description, playback_mode: theme.playback_mode, ...patch }) }); await load(); }
    catch (cause) { fail(String(cause)); }
  }
  function editTheme(theme: MusicTheme) { setEditingTheme(theme); setEditName(theme.name); setEditDescription(theme.description); }
  async function removeTheme(theme: MusicTheme) {
    const enabled = settings?.enabled_theme_ids.includes(theme.id) ?? false;
    try { await api(`/music/themes/${theme.id}${enabled ? "?remove_references=true" : ""}`, { method: "DELETE" }); await load(); }
    catch (cause) { fail(String(cause)); }
    finally { setDeletingTheme(null); }
  }
  async function removeTrack(trackId: string) {
    try { await api(`/music/tracks/${trackId}`, { method: "DELETE" }); await load(); }
    catch (cause) { fail(String(cause)); }
  }
  async function moveTrack(theme: MusicTheme, index: number, delta: number) {
    const other = theme.tracks[index + delta], track = theme.tracks[index]; if (!other) return;
    try {
      await Promise.all([
        api(`/music/tracks/${track.id}`, { method: "PUT", body: JSON.stringify({ title: track.title, position: other.position }) }),
        api(`/music/tracks/${other.id}`, { method: "PUT", body: JSON.stringify({ title: other.title, position: track.position }) })
      ]);
      await load();
    } catch (cause) { fail(String(cause)); }
  }
  function play(theme: MusicTheme, trackId: string) { window.dispatchEvent(new CustomEvent("storystudio-play-track", { detail: { themeId: theme.id, trackId } })); }

  return <div className="page"><header className="page-header"><p className="eyebrow">LOCAL SOUNDTRACK</p><h1>Music themes</h1><p>Shared local playlists. Playback continues in the compact player while you work elsewhere.</p></header>
    <section className="panel music-controls"><TextField select size="small" label="Mode" value={settings?.mode ?? "disabled"} onChange={(e) => void save({ mode: e.target.value as ProjectMusic["mode"] })}><MenuItem value="disabled">Disabled</MenuItem><MenuItem value="player_managed">Player managed</MenuItem><MenuItem value="ai_managed">AI managed</MenuItem></TextField><TextField select size="small" label="Manual theme" disabled={settings?.mode !== "player_managed"} value={settings?.manual_theme_id ?? ""} onChange={(e) => void save({ manual_theme_id: e.target.value || null })}><MenuItem value="">Select theme</MenuItem>{themes.filter((theme) => settings?.enabled_theme_ids.includes(theme.id)).map((theme) => <MenuItem key={theme.id} value={theme.id}>{theme.name}</MenuItem>)}</TextField><label className="mui-volume">Volume<Slider size="small" min={0} max={1} step={.05} value={settings?.volume ?? .7} onChange={(_, value) => setSettings(settings ? { ...settings, volume: Number(value) } : settings)} onChangeCommitted={(_, value) => void save({ volume: Number(value) })} /></label></section>
    <div className="theme-grid">{themes.map((theme) => { const enabled = settings?.enabled_theme_ids.includes(theme.id) ?? false; return <section className="panel" key={theme.id}><header className="theme-header"><div><h2>{theme.name}</h2><small>{theme.tracks.length} tracks</small></div><div><Tooltip title="Rename theme"><IconButton size="small" onClick={() => editTheme(theme)}><EditOutlinedIcon fontSize="small" /></IconButton></Tooltip><Tooltip title="Delete theme"><IconButton size="small" color="error" onClick={() => setDeletingTheme(theme)}><DeleteOutlineIcon fontSize="small" /></IconButton></Tooltip><FormControlLabel control={<Checkbox size="small" checked={enabled} onChange={(e) => void save({ enabled_theme_ids: e.target.checked ? [...(settings?.enabled_theme_ids ?? []), theme.id] : (settings?.enabled_theme_ids ?? []).filter((id) => id !== theme.id), manual_theme_id: settings?.manual_theme_id === theme.id && !e.target.checked ? null : settings?.manual_theme_id })} />} label="Enabled" /></div></header><TextField select size="small" fullWidth label="Playback" value={theme.playback_mode} onChange={(e) => void updateTheme(theme, { playback_mode: e.target.value as MusicTheme["playback_mode"] })}><MenuItem value="shuffle">Shuffle until theme changes</MenuItem><MenuItem value="repeat_one">Loop one track</MenuItem><MenuItem value="in_order">Play in order</MenuItem></TextField>{theme.tracks.map((track, index) => <div className="track-row" key={track.id}><Button size="small" startIcon={<PlayArrowIcon />} onClick={() => play(theme, track.id)}>{track.title}</Button><Tooltip title="Move up"><span><IconButton size="small" disabled={index === 0} onClick={() => void moveTrack(theme, index, -1)}><KeyboardArrowUpIcon /></IconButton></span></Tooltip><Tooltip title="Move down"><span><IconButton size="small" disabled={index === theme.tracks.length - 1} onClick={() => void moveTrack(theme, index, 1)}><KeyboardArrowDownIcon /></IconButton></span></Tooltip><Tooltip title="Remove track"><IconButton size="small" color="error" onClick={() => void removeTrack(track.id)}><DeleteOutlineIcon fontSize="small" /></IconButton></Tooltip></div>)}<Button component="label" size="small">Add local track<input hidden type="file" accept=".mp3,.ogg,.wav,.m4a,audio/*" onChange={(e) => e.target.files?.[0] && void upload(theme.id, e.target.files[0])} /></Button></section>; })}</div>
    <section className="panel create-theme"><TextField size="small" fullWidth label="New theme" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ominous ruins" /><Button variant="contained" onClick={createTheme}>Create theme</Button></section>
    <Dialog open={Boolean(editingTheme)} onClose={() => setEditingTheme(null)}><DialogTitle>Edit music theme</DialogTitle><DialogContent className="music-dialog"><TextField autoFocus label="Name" value={editName} onChange={(e) => setEditName(e.target.value)} /><TextField multiline minRows={3} label="Description" value={editDescription} onChange={(e) => setEditDescription(e.target.value)} /></DialogContent><DialogActions><Button onClick={() => setEditingTheme(null)}>Cancel</Button><Button variant="contained" disabled={!editName.trim()} onClick={async () => { if (editingTheme) await updateTheme(editingTheme, { name: editName.trim(), description: editDescription }); setEditingTheme(null); }}>Save</Button></DialogActions></Dialog>
    <Dialog open={Boolean(deletingTheme)} onClose={() => setDeletingTheme(null)}><DialogTitle>Delete {deletingTheme?.name}?</DialogTitle><DialogContent><p>This deletes the theme and its tracks.{deletingTheme && settings?.enabled_theme_ids.includes(deletingTheme.id) ? " It will also be removed from projects that enable it." : ""}</p></DialogContent><DialogActions><Button onClick={() => setDeletingTheme(null)}>Cancel</Button><Button color="error" onClick={() => deletingTheme && void removeTheme(deletingTheme)}>Delete theme</Button></DialogActions></Dialog>
  </div>;
}
