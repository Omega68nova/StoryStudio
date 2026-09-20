import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Checkbox, FormControlLabel, MenuItem, Switch, Tab, Tabs, TextField } from "@mui/material";
import { api } from "./api";
import { BoxedMultiselectFilter, CreatableBoxedMultiselect } from "./customComponents/BoxedMultiselect";
import { RecordDrawer, ResourceButton, ResourceList } from "./customComponents/AdminResourceForms";
import { applyAdvancedState, entityToDraft, newEntityDraft, updateDraftState } from "./entityDrafts";
import type { EntityEditorDraft, WorldEntity, WorldProjection, WorldRelationship, WorkflowPreset } from "./types";

const GENERAL_KINDS = ["faction", "item", "lore_system", "fact", "plot_beat"];
const humanize = (value: string) => value.replaceAll("_", " ").replace(/^./, letter => letter.toUpperCase());

export function WorldStudio({ projectId, revision, fail, openEnvironmentLocation }: { projectId: string; revision: number; workflows: WorkflowPreset[]; fail: (message: string) => void; openEnvironmentLocation?: (locationId: string) => void }) {
  const [world, setWorld] = useState<WorldProjection | null>(null);
  const [query, setQuery] = useState(""); const [kind, setKind] = useState(""); const [relationQuery, setRelationQuery] = useState("");
  const [draft, setDraft] = useState<EntityEditorDraft | null>(null); const [initial, setInitial] = useState(""); const [history, setHistory] = useState<Array<Record<string, unknown>>>([]);
  const [relation, setRelation] = useState<WorldRelationship | null>(null); const [relationOriginal, setRelationOriginal] = useState<WorldRelationship | null>(null); const [relationAdvanced, setRelationAdvanced] = useState("{}"); const [relationInitial, setRelationInitial] = useState("");
  const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const load = useCallback(async () => setWorld(await api<WorldProjection>(`/projects/${projectId}/world`)), [projectId]);
  useEffect(() => { void load().catch(cause => fail(String(cause))); }, [load, revision, fail]);
  const entities = useMemo(() => Object.values(world?.entities ?? {}), [world]);
  const general = useMemo(() => entities.filter(item => item.kind !== "character" && item.kind !== "relationship" && (!kind || item.kind === kind) && (!query || item.card.search_text.toLocaleLowerCase().includes(query.toLocaleLowerCase()))), [entities, kind, query]);
  const legacy = entities.filter(item => item.kind === "relationship");
  const relations = useMemo(() => Object.values(world?.relations ?? {}).map(item => item as WorldRelationship).filter(item => !relationQuery || relationLabel(item, world).toLocaleLowerCase().includes(relationQuery.toLocaleLowerCase())), [world, relationQuery]);
  const relationDirty = Boolean(relation && relationInitial && JSON.stringify({ relation, relationAdvanced }) !== relationInitial);
  const dirty = Boolean(draft && initial && JSON.stringify(draft) !== initial) || relationDirty;
  useEffect(() => { document.body.dataset.storyStudioUnsaved = String(dirty); return () => { document.body.dataset.storyStudioUnsaved = "false"; }; }, [dirty]);

  async function openEntity(entity: WorldEntity) { const next = entityToDraft(entity); setDraft(next); setInitial(JSON.stringify(next)); setError(""); try { setHistory(await api(`/projects/${projectId}/entities/${entity.id}/history`)); } catch { setHistory([]); } }
  function closeEntity(force = false) { if (!force && dirty && !window.confirm("Discard unsaved entity changes?")) return; setDraft(null); setInitial(""); setError(""); }
  async function saveEntity() {
    if (!draft || !draft.name.trim()) return setError("Name is required");
    try {
      const normalized = applyAdvancedState(draft, draft.advancedState);
      if (draft.id) await api(`/projects/${projectId}/entities/${draft.id}`, { method: "PATCH", body: JSON.stringify({ name: draft.name.trim(), aliases: draft.aliases, tags: draft.tags, patch: draft.kind === "location" ? {} : normalized.state }) });
      else await api(`/projects/${projectId}/entities`, { method: "POST", body: JSON.stringify({ kind: draft.kind, name: draft.name.trim(), aliases: draft.aliases, tags: draft.tags, state: normalized.state }) });
      await load(); closeEntity(true);
    } catch (cause) { setError(String(cause)); }
  }
  async function archiveEntity() { if (!draft?.id) return; 
    try { await api(`/projects/${projectId}/entities/${draft.id}/${draft.state.archived ? "restore" : "archive"}`, { method: "POST" }); await load(); closeEntity(true); } catch (cause) { setError(String(cause)); } }
  async function deleteEntity() { if (!draft?.id) return; 
    try { const impact = await api<{ confirmation: string }>
    (`/projects/${projectId}/entities/${draft.id}/delete-impact`); 

    await api(`/projects/${projectId}/entities/${draft.id}`, { method: "DELETE", body: JSON.stringify({ confirmation: impact.confirmation }) }); await load(); closeEntity(true); } catch (cause) { setError(String(cause)); } }
  function openRelation(value?: WorldRelationship) { const next = value ? structuredClone(value) : { source_id: "", target_id: "", relation: "", bidirectional: true, major: false, blocked: false, travel_minutes: 0, direction: "", modes: [] }; const advanced = JSON.stringify(next, null, 2); setRelation(next); setRelationOriginal(value ? structuredClone(value) : null); setRelationAdvanced(advanced); setRelationInitial(JSON.stringify({ relation: next, relationAdvanced: advanced })); setError(""); }
  function closeRelation(force = false) { if (!force && relationDirty && !window.confirm("Discard unsaved relationship changes?")) return; setRelation(null); setRelationOriginal(null); setRelationInitial(""); setError(""); }
  async function saveRelation() {
    if (!relation?.source_id || !relation.target_id || !relation.relation.trim()) return setError("Source, target, and relationship type are required");
    try {
      const parsed = JSON.parse(relationAdvanced); if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("Advanced relationship JSON must be an object");
      const identityChanged = relationOriginal && (relationOriginal.source_id !== relation.source_id || relationOriginal.target_id !== relation.target_id || relationOriginal.relation !== relation.relation);
      const value = { ...parsed, ...relation }; if (identityChanged) delete value.id;
      const mutations = [...(identityChanged && relationOriginal?.id ? [{ tool: "removeRelationship", arguments: { relationship_id: relationOriginal.id } }] : []), { tool: "setRelationship", arguments: value }];
      await api(`/projects/${projectId}/mutations`, { method: "POST", body: JSON.stringify({ summary: relationOriginal ? "Updated relationship" : "Created relationship", mutations }) }); await load(); closeRelation(true);
    } catch (cause) { setError(String(cause)); }
  }
  async function deleteRelation() { if (!relation?.id || !window.confirm("Remove this relationship from the current branch?")) return; try { await api(`/projects/${projectId}/relationships/${relation.id}`, { method: "DELETE" }); await load(); closeRelation(true); } catch (cause) { setError(String(cause)); } }
  async function importBible() { try { const result = await api<{ imported: number }>(`/projects/${projectId}/bible-import`, { method: "POST" }); await load(); setNotice(`Imported ${result.imported} story-bible documents.`); } catch (cause) { fail(String(cause)); } }
  async function sync() { try { const result = await api<{ provider: string }>(`/projects/${projectId}/memory/sync`, { method: "POST" }); setNotice(`Memory indexed with ${result.provider}.`); } catch (cause) { fail(String(cause)); } }

  return <div className="page world-page"><header className="page-header world-title"><div><p className="eyebrow">BRANCH-AWARE MEMORY</p><h1>World</h1><p>{general.length} general entities · {relations.length} relationships · {world?.transactions.length ?? 0} transactions</p></div><div className="button-row"><Button onClick={() => void importBible()}>Import story bible</Button><Button onClick={() => void sync()}>Sync memory index</Button></div></header>{notice && <p className="notice">{notice}</p>}
    <div className="environment-resource-grid"><ResourceList title="Entities" query={query} setQuery={setQuery} onAdd={() => { const next = newEntityDraft("faction"); setDraft(next); setInitial(JSON.stringify(next)); setHistory([]); }}><TextField select size="small" fullWidth label="Kind" value={kind} onChange={event => setKind(event.target.value)}><MenuItem value="">All general kinds</MenuItem>{[...GENERAL_KINDS, "location"].map(value => <MenuItem key={value} value={value}>{humanize(value)}</MenuItem>)}</TextField>{general.map(item => <ResourceButton key={item.id} enabled={!item.state.archived} disabledLabel="Archived" title={item.name} subtitle={humanize(item.kind)} onClick={() => void openEntity(item)} />)}</ResourceList>
      <ResourceList title="Relationships" query={relationQuery} setQuery={setRelationQuery} onAdd={() => openRelation()}>{relations.map(item => <ResourceButton key={String(item.id)} title={relationLabel(item, world)} subtitle={String(item.relation)} enabledLabel="Branch edge" onClick={() => openRelation(item)} />)}</ResourceList>
    </div>
    {legacy.length > 0 && <details className="panel"><summary>Legacy relationship entities ({legacy.length})</summary><div className="environment-resource-list">{legacy.map(item => <ResourceButton key={item.id} enabled={!item.state.archived} disabledLabel="Archived" title={item.name} subtitle="Legacy relationship entity" onClick={() => void openEntity(item)} />)}</div></details>}
    <section className="panel audit-panel"><h2>Memory audit</h2>{[...(world?.transactions ?? [])].reverse().slice(0, 50).map(tx => <article key={String(tx.id)}><strong>{String(tx.summary || "World change")}</strong><small>{String(tx.provenance)}{tx.display_time ? ` · ${String(tx.display_time)}` : ""}</small></article>)}</section>
    <RecordDrawer 
      title={draft ? `${draft.id ? "Edit" : "Create"} ${humanize(draft.kind)}` : ""} 
      open={Boolean(draft)} 
      dirty={dirty} 
      error={error} 
      onClose={() => closeEntity()} 
      onSave={() => void saveEntity()} 
      onArchive={draft?.id  ? () => void archiveEntity() : undefined} 
      archiveLabel={draft?.state.archived ? "Restore" : "Archive"} 
      onDelete={draft?.id ? () => void deleteEntity() : undefined}
    >
      {draft && <EntityForm draft={draft} setDraft={setDraft} entities={entities} history={history} openEnvironmentLocation={openEnvironmentLocation} />}</RecordDrawer>
    <RecordDrawer title={relation?.id ? "Edit relationship" : "Create relationship"} open={Boolean(relation)} dirty={relationDirty} error={error} onClose={() => closeRelation()} onSave={() => void saveRelation()} onDelete={relation?.id ? () => void deleteRelation() : undefined}>{relation && <RelationshipForm value={relation} setValue={next => { setRelation(next); setRelationAdvanced(JSON.stringify(next, null, 2)); }} entities={entities} advanced={relationAdvanced} setAdvanced={setRelationAdvanced} />}</RecordDrawer>
  </div>;
}

function EntityForm({ draft, setDraft, entities, history, openEnvironmentLocation }: { draft: EntityEditorDraft; setDraft: (value: EntityEditorDraft) => void; entities: WorldEntity[]; history: Array<Record<string, unknown>>; openEnvironmentLocation?: (id: string) => void }) {
  const setState = (patch: Record<string, unknown>) => setDraft(updateDraftState(draft, patch)); const state = draft.state; const [tab, setTab] = useState(0);
  const characters = entities.filter(item => item.kind === "character"), factions = entities.filter(item => item.kind === "faction"), locations = entities.filter(item => item.kind === "location");
  const entitySelect = (label: string, values: unknown, options: WorldEntity[], key: string) => <BoxedMultiselectFilter label={label} options={options} value={options.filter(item => (Array.isArray(values) ? values : []).includes(item.id))} onChange={(_event, next) => setState({ [key]: next.map(item => item.id) })} />;
  return <><TextField select disabled={Boolean(draft.id)} label="Entity kind" value={draft.kind} onChange={event => { const next = newEntityDraft(event.target.value); setDraft({ ...next, name: draft.name, aliases: draft.aliases, tags: draft.tags }); }}>{draft.kind === "relationship" && <MenuItem value="relationship">Legacy relationship</MenuItem>}{GENERAL_KINDS.map(value => <MenuItem key={value} value={value}>{humanize(value)}</MenuItem>)}</TextField><TextField required label="Name" value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} /><CreatableBoxedMultiselect label="Aliases" options={draft.aliases} value={draft.aliases} onChange={(_event, next) => setDraft({ ...draft, aliases: next })} /><CreatableBoxedMultiselect label="Tags" options={draft.tags} value={draft.tags} onChange={(_event, next) => setDraft({ ...draft, tags: next })} />
    {draft.kind === "location" ? <>
    <p>Location structure, descriptions, backgrounds, discovery, and ambient rules are managed in Environment.</p>
    {draft.id && openEnvironmentLocation && <Button onClick={() => openEnvironmentLocation(draft.id!)}>Edit structure in Environment</Button>}
      <details>
        <summary>Branch history ({history.length})</summary>
        <div className="entity-history">
          {history.map(event => 
            <article key={String(event.id)}><strong>{String(event.event_type)}</strong>
            <pre>{JSON.stringify(event.payload, null, 2)}</pre></article>)
          }
        </div>
      </details>
    </> : 
    <>
    <Tabs value={tab} onChange={(_event, value) => setTab(value)} variant="scrollable">
      <Tab label="Details" />
      <Tab label="Advanced" />
      <Tab label={`History (${history.length})`} />
      </Tabs>{tab === 0 && 
      <div className="character-fields">
        <TextField multiline minRows={3} label="Summary" value={String(state.summary ?? "")} onChange={event => setState({ summary: event.target.value })} />
        <TextField multiline minRows={4} label="Description" value={String(state.description ?? "")} onChange={event => setState({ description: event.target.value })} />
        {["fact"].includes(draft.kind) && 
          <TextField select label="Visibility" value={String(state.visibility ?? "public")} onChange={event => setState({ visibility: event.target.value })}>
            <MenuItem value="public">Public</MenuItem>
            <MenuItem value="private">Private</MenuItem>
            <MenuItem value="narrator">Narrator only</MenuItem>
          </TextField>}{draft.kind === "faction" && <>
          <TextField multiline label="Culture" value={String(state.culture ?? "")} onChange={event => setState({ culture: event.target.value })} />
          <CreatableBoxedMultiselect 
            label="Goals" 
            options={arrayStrings(state.goals)} 
            value={arrayStrings(state.goals)} 
            onChange={(_event, next) => setState({ goals: next })} 
          />
          <TextField multiline label="Secrets" value={String(state.secrets ?? "")} onChange={event => setState({ secrets: event.target.value })} />
          <TextField label="Status" value={String(state.status ?? "")} onChange={event => setState({ status: event.target.value })} /></>
          }{draft.kind === "item" && 
          <>
            <TextField multiline label="Appearance" value={String(state.appearance ?? "")} onChange={event => setState({ appearance: event.target.value })} />
            <TextField label="Status" value={String(state.status ?? "")} onChange={event => setState({ status: event.target.value })} />
            <CreatableBoxedMultiselect label="Abilities or effects" options={arrayStrings(state.abilities)} value={arrayStrings(state.abilities)} onChange={(_event, next) => setState({ abilities: next })} />
            <TextField select label="Current location" value={String(state.current_location_id ?? "")} onChange={event => setState({ current_location_id: event.target.value || null })}><MenuItem value="">None</MenuItem>{locations.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField>
          </>}
          {draft.kind === "lore_system" && 
          <>
          <TextField multiline minRows={4} label="Rules" value={String(state.rules ?? "")} onChange={event => setState({ rules: event.target.value })} />
            <TextField multiline label="Limits" value={String(state.limits ?? "")} onChange={event => setState({ limits: event.target.value })} />
              <TextField multiline label="Costs" value={String(state.costs ?? "")} onChange={event => setState({ costs: event.target.value })} />
            <TextField multiline label="Secrets" value={String(state.secrets ?? "")} onChange={event => setState({ secrets: event.target.value })} />
              </>}
              {draft.kind === "fact" &&
               <>
               <FormControlLabel control={<Switch checked={Boolean(state.revealed)} onChange={event => setState({ revealed: event.target.checked })} />} label="Revealed" />
                {entitySelect("Known by characters", state.known_character_ids, characters, "known_character_ids")}
                {entitySelect("Known by factions", state.known_faction_ids, factions, "known_faction_ids")}
              </>}
              {draft.kind === "plot_beat" && 
              <>
                <TextField select label="Status" value={String(state.status ?? "planned")} onChange={event => setState({ status: event.target.value })}>
                  {["planned", "available", "active", "resolved", "abandoned"].map(value => 
                    <MenuItem key={value} value={value}> {humanize(value)}</MenuItem>)}</TextField>
                    <CreatableBoxedMultiselect label="Goals" options={arrayStrings(state.goals)} value={arrayStrings(state.goals)} onChange={(_event, next) => setState({ goals: next })} />
                  </>}
        </div>}
          {tab === 1 && <TextField fullWidth multiline minRows={16} label="Advanced state JSON" value={draft.advancedState} onChange={event => setDraft({ ...draft, advancedState: event.target.value })} />}
          {tab === 2 && <div className="entity-history">{history.map(event => <article key={String(event.id)}><strong>{String(event.event_type)}</strong><pre>{JSON.stringify(event.payload, null, 2)}</pre></article>)}</div>}</>}
          </>;
}

function RelationshipForm({ value, setValue, entities, advanced, setAdvanced }: { value: WorldRelationship; setValue: (value: WorldRelationship) => void; entities: WorldEntity[]; advanced: string; setAdvanced: (value: string) => void }) {
  return <><TextField select label="Source" value={value.source_id} onChange={event => setValue({ ...value, source_id: event.target.value })}>{entities.map(item => <MenuItem key={item.id} value={item.id}>{item.name} · {humanize(item.kind)}</MenuItem>)}</TextField><TextField select label="Target" value={value.target_id} onChange={event => setValue({ ...value, target_id: event.target.value })}>{entities.map(item => <MenuItem key={item.id} value={item.id}>{item.name} · {humanize(item.kind)}</MenuItem>)}</TextField><TextField label="Relationship type" value={value.relation} onChange={event => setValue({ ...value, relation: event.target.value })} /><div className="environment-toggle-row"><FormControlLabel control={<Checkbox checked={value.bidirectional !== false} onChange={event => setValue({ ...value, bidirectional: event.target.checked })} />} label="Bidirectional" /><FormControlLabel control={<Checkbox checked={Boolean(value.major)} onChange={event => setValue({ ...value, major: event.target.checked })} />} label="Major" /><FormControlLabel control={<Checkbox checked={Boolean(value.blocked)} onChange={event => setValue({ ...value, blocked: event.target.checked })} />} label="Blocked" /></div><TextField type="number" label="Travel minutes" value={Number(value.travel_minutes ?? 0)} onChange={event => setValue({ ...value, travel_minutes: Number(event.target.value) })} /><TextField label="Direction" value={String(value.direction ?? "")} onChange={event => setValue({ ...value, direction: event.target.value })} /><CreatableBoxedMultiselect label="Travel modes" options={arrayStrings(value.modes)} value={arrayStrings(value.modes)} onChange={(_event, next) => setValue({ ...value, modes: next })} /><TextField fullWidth multiline minRows={10} label="Advanced relationship JSON" value={advanced} onChange={event => setAdvanced(event.target.value)} /></>;
}

const arrayStrings = (value: unknown): string[] => Array.isArray(value) ? value.map(String) : [];
function relationLabel(relation: WorldRelationship, world: WorldProjection | null): string { return `${world?.entities[relation.source_id]?.name ?? relation.source_id} → ${world?.entities[relation.target_id]?.name ?? relation.target_id}`; }
