import { FormEvent, useCallback, useEffect, useState } from "react";
import { Button, Checkbox, FormControlLabel, MenuItem, Switch, TextField } from "@mui/material";
import { api } from "./api";
import type { AmbientAssignment, AmbientVariant, EnvironmentSettings, LocationMapLayer, WeatherDefinition, WorkflowPreset, WorldProjection } from "./types";

export function EnvironmentStudio({ projectId, revision, workflows, fail }: { projectId: string; revision: number; workflows: WorkflowPreset[]; fail: (message: string) => void }) {
  const [settings, setSettings] = useState<EnvironmentSettings | null>(null);
  const [map, setMap] = useState<LocationMapLayer | null>(null);
  const [parentId, setParentId] = useState<string | null>(null);
  const [ambient, setAmbient] = useState<{ variants: AmbientVariant[]; assignments: AmbientAssignment[] }>({ variants: [], assignments: [] });
  const [world, setWorld] = useState<WorldProjection | null>(null);
  const [selectedLocationId, setSelectedLocationId] = useState<string | null>(null);
  const [locationState, setLocationState] = useState("");
  const [weatherName, setWeatherName] = useState("");
  const [rule, setRule] = useState({ owner_type: "weather", owner_id: "", selector_type: "default", selector_value: "", variant_id: "" });
  const [proposals, setProposals] = useState<Array<{ id: string; name: string; description: string; status: string }>>([]);
  const [derived, setDerived] = useState({ source_path: "", label: "", playback_rate: 2, default_gain: 1 });
  const [background, setBackground] = useState({ weather_id: "", time_phase_id: "", prompt: "" });
  const load = useCallback(async () => {
    const [nextSettings, nextMap, nextAmbient, nextWorld, nextProposals] = await Promise.all([
      api<EnvironmentSettings>(`/projects/${projectId}/environment/settings`),
      api<LocationMapLayer>(`/projects/${projectId}/environment/map${parentId ? `?parent_id=${parentId}` : ""}`),
      api<{ variants: AmbientVariant[]; assignments: AmbientAssignment[] }>(`/projects/${projectId}/environment/ambient`),
      api<WorldProjection>(`/projects/${projectId}/world`),
      api<Array<{ id: string; name: string; description: string; status: string }>>(`/projects/${projectId}/environment/weather-proposals`),
    ]);
    setSettings(nextSettings); setMap(nextMap); setAmbient(nextAmbient); setWorld(nextWorld); setProposals(nextProposals);
  }, [projectId, parentId]);
  useEffect(() => { void load().catch(cause => fail(String(cause))); }, [load, revision, fail]);
  const selectedLocation = selectedLocationId ? world?.entities[selectedLocationId] : null;
  useEffect(() => { if (selectedLocation) setLocationState(JSON.stringify(selectedLocation.state, null, 2)); }, [selectedLocation?.id]);
  async function saveSettings(patch: Partial<EnvironmentSettings>) {
    if (!settings) return;
    try { setSettings(await api(`/projects/${projectId}/environment/settings`, { method: "PUT", body: JSON.stringify({ ...settings, ...patch }) })); }
    catch (cause) { fail(String(cause)); }
  }
  async function createWeather() {
    if (!weatherName.trim()) return;
    try { await api(`/projects/${projectId}/environment/weather`, { method: "POST", body: JSON.stringify({ name: weatherName, description: "", tags: [], image_tags: [], enabled: true }) }); setWeatherName(""); await load(); }
    catch (cause) { fail(String(cause)); }
  }
  async function updateWeather(item: WeatherDefinition, patch: Partial<WeatherDefinition>) {
    try { await api(`/projects/${projectId}/environment/weather/${item.id}`, { method: "PUT", body: JSON.stringify({ ...item, ...patch }) }); await load(); }
    catch (cause) { fail(String(cause)); }
  }
  async function setTransitions(item: WeatherDefinition, values: string[]) {
    try { await api(`/projects/${projectId}/environment/weather/${item.id}/transitions`, { method: "PUT", body: JSON.stringify({ target_weather_ids: values }) }); await load(); }
    catch (cause) { fail(String(cause)); }
  }
  async function savePhases() {
    if (!settings) return;
    try { await api(`/projects/${projectId}/environment/time-phases`, { method: "PUT", body: JSON.stringify({ phases: settings.time_phases }) }); await load(); }
    catch (cause) { fail(String(cause)); }
  }
  async function saveVariant(item: AmbientVariant, patch: Partial<AmbientVariant>) {
    try { await api(`/projects/${projectId}/environment/ambient/variants/${item.id}`, { method: "PUT", body: JSON.stringify({ ...item, ...patch }) }); await load(); }
    catch (cause) { fail(String(cause)); }
  }
  async function addRule() {
    if (!rule.owner_id || !rule.variant_id) return;
    try { await api(`/projects/${projectId}/environment/ambient/assignments`, { method: "POST", body: JSON.stringify({ ...rule, selector_value: rule.selector_value || null }) }); await load(); }
    catch (cause) { fail(String(cause)); }
  }
  async function createLocation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    try { await api(`/projects/${projectId}/entities`, { method: "POST", body: JSON.stringify({ kind: "location", name: form.get("name"), tags: String(form.get("tags") || "").split(",").map(value => value.trim()).filter(Boolean), aliases: [], state: { parent_location_id: parentId, description: form.get("description"), exposure: form.get("exposure"), image_tags: [], random_encounter: form.get("random_encounter") === "on", discovered: form.get("random_encounter") !== "on" } }) }); event.currentTarget.reset(); await load(); }
    catch (cause) { fail(String(cause)); }
  }
  async function saveLocation() {
    if (!selectedLocation) return;
    try { await api(`/projects/${projectId}/entities/${selectedLocation.id}`, { method: "PATCH", body: JSON.stringify({ patch: JSON.parse(locationState) }) }); await load(); }
    catch (cause) { fail(String(cause)); }
  }
  async function moveLocation(id: string, clientX: number, clientY: number, element: HTMLElement) {
    const entity=world?.entities[id], rect=element.parentElement?.getBoundingClientRect(); if(!entity||!rect) return;
    const x=Math.round(((clientX-rect.left)/rect.width*100-10)/21), y=Math.round(((clientY-rect.top)/rect.height*100-12)/24);
    try { await api(`/projects/${projectId}/entities/${id}`, { method:"PATCH", body:JSON.stringify({ patch:{...entity.state,x,y} }) }); await load(); } catch(cause){ fail(String(cause)); }
  }
  async function decideProposal(id: string, action: "approve" | "reject") { try { await api(`/projects/${projectId}/environment/weather-proposals/${id}`, { method: "PUT", body: JSON.stringify({ action }) }); await load(); } catch (cause) { fail(String(cause)); } }
  async function createDerived() { if (!derived.source_path || !derived.label) return; try { await api(`/projects/${projectId}/environment/ambient/variants`, { method: "POST", body: JSON.stringify({ ...derived, tags: [], enabled: true }) }); setDerived({ source_path: "", label: "", playback_rate: 2, default_gain: 1 }); await load(); } catch (cause) { fail(String(cause)); } }
  async function generateBackground() { if (!selectedLocation || !background.prompt.trim() || !settings?.background_workflow_id) return; try { const created=await api<{media_asset_id:string}>(`/projects/${projectId}/environment/locations/${selectedLocation.id}/backgrounds`,{method:"POST",body:JSON.stringify({prompt:background.prompt,negative_prompt:"",weather_id:background.weather_id||null,time_phase_id:background.time_phase_id||null})}); await api(`/media-assets/${created.media_asset_id}/generate`,{method:"POST",body:JSON.stringify({workflow_preset_id:settings.background_workflow_id,prompt:background.prompt,negative_prompt:"",width:null,height:null})}); setBackground({...background,prompt:""}); } catch(cause){ fail(String(cause)); } }
  if (!settings) return null;
  const ownerChoices = rule.owner_type === "weather" ? settings.weather : rule.owner_type === "time" ? settings.time_phases : map?.locations ?? [];
  return <div className="page environment-page">
    <header className="page-header"><p className="eyebrow">SCENE ENVIRONMENT</p><h1>Environment</h1><p>Weather, time, hierarchical places, backgrounds, and ambient loops. Music remains independent.</p></header>
    <section className="panel environment-settings">
      <h2>Behavior</h2>
      <FormControlLabel control={<Switch checked={settings.enabled} onChange={e => void saveSettings({ enabled: e.target.checked })} />} label="Environment enabled" />
      <FormControlLabel control={<Switch checked={settings.ai_create_locations} onChange={e => void saveSettings({ ai_create_locations: e.target.checked })} />} label="AI may create locations" />
      <FormControlLabel control={<Switch checked={settings.ai_propose_weather} onChange={e => void saveSettings({ ai_propose_weather: e.target.checked })} />} label="AI may propose weather" />
      <FormControlLabel control={<Switch checked={settings.auto_generate_backgrounds} onChange={e => void saveSettings({ auto_generate_backgrounds: e.target.checked })} />} label="Generate backgrounds on demand" />
      <TextField select size="small" label="Background workflow" value={settings.background_workflow_id ?? ""} onChange={e => void saveSettings({ background_workflow_id: e.target.value || null, auto_generate_backgrounds: e.target.value ? settings.auto_generate_backgrounds : false })}><MenuItem value="">None</MenuItem>{workflows.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField>
    </section>
    <div className="environment-grid">
      <section className="panel"><h2>Weather</h2><TextField select fullWidth size="small" label="Initial weather" value={settings.initial_weather_id} onChange={e => void saveSettings({ initial_weather_id: e.target.value })}>{settings.weather.filter(item => item.enabled).map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField>
        {settings.weather.map(item => <article className="environment-row" key={item.id}><TextField size="small" label="Name" value={item.name} onChange={e => setSettings({ ...settings, weather: settings.weather.map(value => value.id === item.id ? { ...value, name: e.target.value } : value) })} onBlur={() => void updateWeather(item, {})} /><FormControlLabel control={<Checkbox checked={item.enabled} onChange={e => void updateWeather(item, { enabled: e.target.checked })} />} label="Enabled" /><TextField select SelectProps={{ multiple: true }} size="small" label="Can transition to" value={item.transition_ids} onChange={e => void setTransitions(item, typeof e.target.value === "string" ? e.target.value.split(",") : e.target.value)}>{settings.weather.filter(other => other.enabled && other.id !== item.id).map(other => <MenuItem key={other.id} value={other.id}>{other.name}</MenuItem>)}</TextField></article>)}
        <div className="button-row"><TextField size="small" label="New weather" value={weatherName} onChange={e => setWeatherName(e.target.value)} /><Button onClick={() => void createWeather()}>Add</Button></div>
        {proposals.filter(item => item.status === "pending").map(item => <article className="environment-row" key={item.id}><span><b>Proposed: {item.name}</b><small>{item.description}</small></span><Button onClick={() => void decideProposal(item.id, "approve")}>Approve</Button><Button color="error" onClick={() => void decideProposal(item.id, "reject")}>Reject</Button></article>)}
      </section>
      <section className="panel"><h2>Time cycle</h2>{settings.time_phases.map((item, index) => <div className="environment-row" key={item.id}><TextField size="small" value={item.name} onChange={e => setSettings({ ...settings, time_phases: settings.time_phases.map((value, i) => i === index ? { ...value, name: e.target.value } : value) })} /><TextField size="small" type="number" label="Minutes" value={item.duration_minutes} onChange={e => setSettings({ ...settings, time_phases: settings.time_phases.map((value, i) => i === index ? { ...value, duration_minutes: Number(e.target.value) } : value) })} /><span><Checkbox checked={item.enabled} onChange={e => setSettings({ ...settings, time_phases: settings.time_phases.map((value, i) => i === index ? { ...value, enabled: e.target.checked } : value) })} /><Button disabled={index === 0} onClick={() => { const values=[...settings.time_phases]; [values[index-1],values[index]]=[values[index],values[index-1]]; setSettings({...settings,time_phases:values}); }}>↑</Button><Button disabled={index === settings.time_phases.length-1} onClick={() => { const values=[...settings.time_phases]; [values[index+1],values[index]]=[values[index],values[index+1]]; setSettings({...settings,time_phases:values}); }}>↓</Button><Button color="error" disabled={settings.time_phases.length === 1} onClick={() => setSettings({...settings,time_phases:settings.time_phases.filter((_,i)=>i!==index)})}>Remove</Button></span></div>)}<div className="button-row"><Button onClick={() => setSettings({...settings,time_phases:[...settings.time_phases,{id:`new-${Date.now()}`,name:"New phase",duration_minutes:60,position:settings.time_phases.length,enabled:true}]})}>Add phase</Button><Button onClick={() => void savePhases()}>Save time cycle</Button></div></section>
    </div>
    <section className="panel map-panel"><div className="sheet-heading"><h2>{map?.parent?.name ?? "World locations"}</h2>{map?.parent && <Button onClick={() => setParentId(map.parent?.parent_id ?? null)}>Go back</Button>}</div><div className="environment-map"><MapEdges layer={map} />{map?.locations.map(item => <button draggable key={item.id} style={{ left: `${10 + item.x * 21}%`, top: `${12 + item.y * 24}%` }} onDragEnd={e => void moveLocation(item.id,e.clientX,e.clientY,e.currentTarget)} onClick={() => { setSelectedLocationId(item.id); if (item.has_children) setParentId(item.id); }}><b>{item.name}</b><small>{item.exposure}{item.has_children ? " · enter" : ""}</small></button>)}</div>
      <form className="route-form" onSubmit={createLocation}><TextField size="small" name="name" required label="New location" /><TextField size="small" name="description" label="Description" /><TextField select size="small" name="exposure" defaultValue="outdoor" label="Exposure">{["outdoor","indoor","isolated"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField><TextField size="small" name="tags" label="Tags" /><FormControlLabel control={<Checkbox name="random_encounter" />} label="Random encounter" /><Button type="submit">Add here</Button></form>
      {selectedLocation && <div className="location-editor"><h3>{selectedLocation.name}</h3><p>Edit normalized description, parent, exposure, map x/y, discovery, and image tags.</p><TextField fullWidth multiline minRows={8} value={locationState} onChange={e => setLocationState(e.target.value)} /><Button onClick={() => void saveLocation()}>Save location</Button><label className="file-button">Upload default background<input hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={async e => { const file=e.target.files?.[0]; if (!file) return; const form=new FormData(); form.append("file",file); try { await api(`/entities/${selectedLocation.id}/media/upload?kind=location`,{method:"POST",body:form}); await load(); } catch(cause){ fail(String(cause)); } }} /></label><h4>Generate conditioned background</h4><div className="route-form"><TextField select size="small" label="Weather (optional)" value={background.weather_id} onChange={e=>setBackground({...background,weather_id:e.target.value})}><MenuItem value="">Any</MenuItem>{settings.weather.map(item=><MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField><TextField select size="small" label="Time (optional)" value={background.time_phase_id} onChange={e=>setBackground({...background,time_phase_id:e.target.value})}><MenuItem value="">Any</MenuItem>{settings.time_phases.map(item=><MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField><TextField size="small" label="Prompt" value={background.prompt} onChange={e=>setBackground({...background,prompt:e.target.value})}/><Button disabled={!settings.background_workflow_id||!background.prompt.trim()} onClick={()=>void generateBackground()}>Generate</Button></div></div>}
    </section>
    <section className="panel"><h2>Ambient sound catalog</h2><p>These loops are mixed separately from Music. Create speed variants through the API; each appears as an independent sound.</p>{ambient.variants.map(item => <div className="sound-row" key={item.id}><Button onClick={() => { const audio = new Audio(item.url); audio.playbackRate = item.playback_rate; audio.play(); window.setTimeout(() => audio.pause(), 4000); }}>Preview</Button><span>{item.label}<small>{item.source_path} · {item.playback_rate}×</small></span><Checkbox checked={item.enabled} onChange={e => void saveVariant(item, { enabled: e.target.checked })} /><TextField size="small" type="number" label="Gain" inputProps={{ min: 0, max: 1, step: .05 }} value={item.default_gain} onChange={e => void saveVariant(item, { default_gain: Number(e.target.value) })} /></div>)}
      <h3>Derived speed variant</h3><div className="route-form"><TextField select size="small" label="Source" value={derived.source_path} onChange={e => setDerived({ ...derived, source_path: e.target.value })}>{ambient.variants.filter(item => !item.derived).map(item => <MenuItem key={item.id} value={item.source_path}>{item.label}</MenuItem>)}</TextField><TextField size="small" label="New label" value={derived.label} onChange={e => setDerived({ ...derived, label: e.target.value })} /><TextField size="small" type="number" label="Speed" value={derived.playback_rate} onChange={e => setDerived({ ...derived, playback_rate: Number(e.target.value) })} /><Button onClick={() => void createDerived()}>Create variant</Button></div>
      <h3>Add assignment</h3><div className="route-form"><TextField select size="small" value={rule.owner_type} onChange={e => setRule({ ...rule, owner_type: e.target.value, owner_id: "" })}>{["weather","time","location","action"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField>{rule.owner_type === "action" ? <TextField size="small" label="Action, e.g. running" value={rule.owner_id} onChange={e => setRule({ ...rule, owner_id: e.target.value })} /> : <TextField select size="small" label="Owner" value={rule.owner_id} onChange={e => setRule({ ...rule, owner_id: e.target.value })}>{ownerChoices.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField>}<TextField select size="small" label="Sound" value={rule.variant_id} onChange={e => setRule({ ...rule, variant_id: e.target.value })}>{ambient.variants.filter(item => item.enabled && item.available).map(item => <MenuItem key={item.id} value={item.id}>{item.label}</MenuItem>)}</TextField><Button onClick={() => void addRule()}>Assign</Button></div>
    </section>
  </div>;
}

export function LocationMap({ projectId, fail }: { projectId: string; fail: (message: string) => void }) {
  const [parentId, setParentId] = useState<string | null>(null); const [layer, setLayer] = useState<LocationMapLayer | null>(null);
  useEffect(() => { void api<LocationMapLayer>(`/projects/${projectId}/environment/map${parentId ? `?parent_id=${parentId}` : ""}`).then(setLayer).catch(cause => fail(String(cause))); }, [projectId, parentId, fail]);
  return <div className="player-map"><div className="sheet-heading"><h3>{layer?.parent?.name ?? "World map"}</h3>{layer?.parent && <Button onClick={() => setParentId(layer.parent?.parent_id ?? null)}>Go back</Button>}</div><div className="environment-map"><MapEdges layer={layer} />{layer?.locations.map(item => <button key={item.id} style={{ left: `${10 + item.x * 21}%`, top: `${12 + item.y * 24}%` }} onClick={() => item.has_children && setParentId(item.id)}>{item.name}</button>)}</div></div>;
}

function MapEdges({ layer }: { layer: LocationMapLayer | null }) {
  if (!layer) return null; const byId = new Map(layer.locations.map(item => [item.id, item]));
  return <svg className="map-edges" viewBox="0 0 100 100" preserveAspectRatio="none">{layer.routes.map(route => { const from=byId.get(route.source_id),to=byId.get(route.target_id); return from&&to?<line key={route.id} x1={10+from.x*21} y1={12+from.y*24} x2={10+to.x*21} y2={12+to.y*24} />:null; })}</svg>;
}
