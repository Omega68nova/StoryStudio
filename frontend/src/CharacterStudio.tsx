import { useCallback, useEffect, useMemo, useState } from "react";
import { MenuItem, TextField } from "@mui/material";
import { api } from "./api";
import { BoxedMultiselectFilter } from "./customComponents/BoxedMultiselect";
import { RecordDrawer, ResourceButton, ResourceList } from "./customComponents/AdminResourceForms";
import { CharacterEditorForm, type OutfitDraft } from "./CharacterEditorForm";
import { FavoriteLibraryButton } from "./FavoriteLibraryButton";
import { applyAdvancedState, entityToDraft, updateDraftState } from "./entityDrafts";
import type { BulletCatalog } from "./BulletHellStudio";
import type { AbilityDefinition, CharacterEditorDraft, EffectDefinition, MediaAsset, Outfit, StatDefinition, WorkflowPreset, WorldEntity, WorldProjection, WorldRelationship } from "./types";

export function CharacterStudio({ projectId, revision, workflows, fail }: { projectId: string; revision: number; workflows: WorkflowPreset[]; fail: (message: string) => void }) {
  const [world, setWorld] = useState<WorldProjection | null>(null); const [catalog, setCatalog] = useState<BulletCatalog>({ skills: [], modes: [], attacks: [] }); const [bullet, setBullet] = useState({ allowed_mode_ids: [] as string[], allowed_skill_ids: [] as string[] });
  const [rules, setRules] = useState<{ stats: StatDefinition[]; effects: EffectDefinition[]; abilities: AbilityDefinition[] }>({ stats: [], effects: [], abilities: [] });
  const [characterMedia, setCharacterMedia] = useState<Record<string, MediaAsset[]>>({});
  const [query, setQuery] = useState(""); const [control, setControl] = useState(""); const [status, setStatus] = useState("active"); const [locationFilter, setLocationFilter] = useState(""); const [tagFilter, setTagFilter] = useState<string[]>([]);
  const [draft, setDraft] = useState<CharacterEditorDraft | null>(null); const [initial, setInitial] = useState(""); const [error, setError] = useState("");
  const [history, setHistory] = useState<Array<Record<string, unknown>>>([]); const [outfits, setOutfits] = useState<Outfit[]>([]); const [media, setMedia] = useState<MediaAsset[]>([]); const [outfitDraft, setOutfitDraft] = useState<OutfitDraft | null>(null);
  const [mediaJobs, setMediaJobs] = useState<Record<string, { id: string; status: string }>>({});
  const load = useCallback(async () => {
    const [nextWorld, nextCatalog, nextBullet, nextRules] = await Promise.all([
      api<WorldProjection>(`/projects/${projectId}/world`),
      api<BulletCatalog>("/bullethell/catalog"),
      api<{ allowed_mode_ids: string[]; allowed_skill_ids: string[] }>(`/projects/${projectId}/bullethell`),
      api<{ stats: StatDefinition[]; effects: EffectDefinition[]; abilities: AbilityDefinition[] }>(`/projects/${projectId}/rules`),
    ]);
    setWorld(nextWorld);
    setCatalog(nextCatalog);
    setBullet(nextBullet);
    setRules(nextRules);
    const characterIds = Object.values(nextWorld.entities)
      .filter(item => item.kind === "character")
      .map(item => item.id);
    const mediaEntries = await Promise.all(characterIds.map(async id => [
      id,
      await api<MediaAsset[]>(`/entities/${id}/media`).catch(() => [] as MediaAsset[]),
    ] as const));
    setCharacterMedia(Object.fromEntries(mediaEntries));
  }, [projectId]);
  useEffect(() => { void load().catch(cause => fail(String(cause))); }, [load, revision, fail]);
  const entities = useMemo(() => Object.values(world?.entities ?? {}), [world]); const locations = entities.filter(item => item.kind === "location"); const tags = [...new Set(entities.filter(item => item.kind === "character").flatMap(item => item.tags))].sort();
  const characters = entities.filter(item => item.kind === "character" && (!query || item.card.search_text.toLocaleLowerCase().includes(query.toLocaleLowerCase())) && (!control || (control === "player") === Boolean(item.state.player_controlled)) && (status === "all" || (status === "archived") === Boolean(item.state.archived)) && (!locationFilter || item.state.current_location_id === locationFilter) && (!tagFilter.length || tagFilter.every(tag => item.tags.includes(tag))));
  const dirty = Boolean(draft && initial && JSON.stringify(draft) !== initial);
  useEffect(() => { document.body.dataset.storyStudioUnsaved = String(dirty); return () => { document.body.dataset.storyStudioUnsaved = "false"; }; }, [dirty]);

  async function openCharacter(entity: WorldEntity) {
    const next = entityToDraft(entity) as CharacterEditorDraft;
    setDraft(next);
    setInitial(JSON.stringify(next));
    setError("");
    setMediaJobs({});
    try {
      const [events, nextOutfits, assets] = await Promise.all([
        api<Array<Record<string, unknown>>>(`/projects/${projectId}/entities/${entity.id}/history`),
        api<Outfit[]>(`/entities/${entity.id}/outfits`),
        api<MediaAsset[]>(`/entities/${entity.id}/media`),
      ]);
      setHistory(events);
      setOutfits(nextOutfits);
      setMedia(assets);
      setCharacterMedia(previous => ({ ...previous, [entity.id]: assets }));
    } catch (cause) {
      setError(String(cause));
      setHistory([]);
      setOutfits([]);
      setMedia([]);
    }
  }
  function createCharacter() { const state = { description: "", imagegen_description: "", appearance: "", personality: "", wardrobe_notes: "", full_body_height_factor: 0.5, player_controlled: false, autonomy_enabled: false, intervention_frequency: "normal", goals: [], character_secrets: [], secrets_to_character: [], equipment: [], inventory: [], abilities: [], knowledge: [], faction_ids: [], bullethell_skill_ids: [] }; const next: CharacterEditorDraft = { kind: "character", name: "", aliases: [], tags: [], state, advancedState: JSON.stringify(state, null, 2) }; setDraft(next); setInitial(JSON.stringify(next)); setHistory([]); setOutfits([]); setMedia([]); }
  function close(force = false) { if (!force && dirty && !window.confirm("Discard unsaved character changes?")) return; setDraft(null); setInitial(""); setError(""); setOutfitDraft(null); setMediaJobs({}); }
  async function save() { if (!draft || !draft.name.trim()) return setError("Name is required"); try { const normalized = applyAdvancedState(draft, draft.advancedState) as CharacterEditorDraft; if (normalized.state.player_controlled && normalized.state.autonomy_enabled) throw new Error("Player-controlled characters cannot enable NPC autonomy"); if (draft.id) await api(`/projects/${projectId}/entities/${draft.id}`, { method: "PATCH", body: JSON.stringify({ name: draft.name.trim(), aliases: draft.aliases, tags: draft.tags, patch: normalized.state }) }); else await api(`/projects/${projectId}/entities`, { method: "POST", body: JSON.stringify({ kind: "character", name: draft.name.trim(), aliases: draft.aliases, tags: draft.tags, state: normalized.state }) }); await load(); close(true); } catch (cause) { setError(String(cause)); } }
  async function archive() { if (!draft?.id) return; try { await api(`/projects/${projectId}/entities/${draft.id}/${draft.state.archived ? "restore" : "archive"}`, { method: "POST" }); await load(); close(true); } catch (cause) { setError(String(cause)); } }
  async function remove() { if (!draft?.id) return; try { const impact = await api<{ confirmation: string }>(`/projects/${projectId}/entities/${draft.id}/delete-impact`); if (window.prompt(`Type ${impact.confirmation} to permanently delete this character`) !== impact.confirmation) return; await api(`/projects/${projectId}/entities/${draft.id}`, { method: "DELETE", body: JSON.stringify({ confirmation: impact.confirmation }) }); await load(); close(true); } catch (cause) { setError(String(cause)); } }
  async function setStat(key: string, value: number) {
    if (!draft?.id || !Number.isFinite(value)) return;
    try {
      await api(`/projects/${projectId}/stats/adjust`, {
        method: "POST",
        body: JSON.stringify({
          entity_id: draft.id,
          stat_key: key,
          operation: "set",
          amount: value,
        }),
      });
      await load();
    } catch (cause) {
      setError(String(cause));
    }
  }

  async function updateStatDefinition(
    definition: StatDefinition,
    patch: Partial<Pick<StatDefinition, "minimum" | "maximum">>,
  ) {
    try {
      await api(`/projects/${projectId}/stats/${definition.stat_key}`, {
        method: "PUT",
        body: JSON.stringify({
          stat_key: definition.stat_key,
          label: definition.label,
          description: definition.description ?? "",
          compatible_owner_kinds: definition.compatible_owner_kinds,
          default_value: definition.default_value,
          minimum: patch.minimum ?? definition.minimum,
          maximum: patch.maximum ?? definition.maximum,
          minimum_stat_key: definition.minimum_stat_key ?? null,
          maximum_stat_key: definition.maximum_stat_key ?? null,
          color: definition.color ?? null,
          minimum_color: definition.minimum_color ?? null,
          maximum_color: definition.maximum_color ?? null,
          icon: definition.icon ?? null,
          display_style: definition.display_style ?? "compact",
          integer_only: Boolean(definition.integer_only),
          visibility: definition.visibility,
        }),
      });
      await load();
    } catch (cause) {
      setError(String(cause));
    }
  }
  async function removeActiveEffect(id: string) {
    try { await api(`/projects/${projectId}/effects/active/${id}`, { method: "DELETE" }); await load(); }
    catch (cause) { setError(String(cause)); }
  }
  async function saveOutfit() { if (!outfitDraft || !outfitDraft.name.trim()) return; try { await api(outfitDraft.id ? `/outfits/${outfitDraft.id}` : `/entities/${outfitDraft.entity_id}/outfits`, { method: outfitDraft.id ? "PUT" : "POST", body: JSON.stringify({ name: outfitDraft.name, description: outfitDraft.description, imagegen_description: outfitDraft.imagegen_description, equipment: outfitDraft.equipment }) }); setOutfits(await api(`/entities/${outfitDraft.entity_id}/outfits`)); setOutfitDraft(null); } catch (cause) { setError(String(cause)); } }
  async function deleteOutfit(outfit: Outfit) { if (!window.confirm(`Delete outfit ${outfit.name}?`)) return; try { await api(`/outfits/${outfit.id}`, { method: "DELETE" }); setOutfits(await api(`/entities/${outfit.entity_id}/outfits`)); } catch (cause) { setError(String(cause)); } }
  async function activateOutfit(outfit: Outfit) { try { await api(`/outfits/${outfit.id}/activate`, { method: "POST" }); const patch = { active_outfit_id: outfit.id, equipment: outfit.equipment }; if (draft) setDraft(updateDraftState(draft, patch) as CharacterEditorDraft); setInitial(previous => { if (!previous) return previous; const baseline = JSON.parse(previous) as CharacterEditorDraft; return JSON.stringify(updateDraftState(baseline, patch)); }); await load(); } catch (cause) { setError(String(cause)); } }
  async function refreshMedia(entityId: string) {
    const assets = await api<MediaAsset[]>(`/entities/${entityId}/media`);
    setMedia(assets);
    setCharacterMedia(previous => ({ ...previous, [entityId]: assets }));
  }

  useEffect(() => {
    if (!draft?.id) return;
    void refreshMedia(draft.id).catch(cause => setError(String(cause)));
  }, [revision, draft?.id]);

  useEffect(() => {
    const active = Object.entries(mediaJobs).filter(([, job]) =>
      ["queued", "running", "switching"].includes(job.status),
    );
    if (!active.length || !draft?.id) return;

    const timer = window.setInterval(() => {
      void Promise.all(
        active.map(async ([slot, job]) => {
          try {
            const latest = await api<{ id: string; status: string }>(`/jobs/${job.id}`);
            if (["completed", "failed", "cancelled", "interrupted"].includes(latest.status)) {
              await refreshMedia(draft.id!);
              setMediaJobs(current => {
                const next = { ...current };
                delete next[slot];
                return next;
              });
              return;
            }
            setMediaJobs(current => ({
              ...current,
              [slot]: { id: job.id, status: latest.status },
            }));
          } catch (cause) {
            setError(String(cause));
          }
        }),
      );
    }, 700);

    return () => window.clearInterval(timer);
  }, [mediaJobs, draft?.id]);
  async function upload(kind: "portrait" | "full_body", outfitId: string | null, file: File) {
    if (!draft?.id) return;
    const body = new FormData();
    body.append("file", file);
    try {
      await api(`/entities/${draft.id}/media/upload?kind=${kind}${outfitId ? `&outfit_id=${outfitId}` : ""}`, {
        method: "POST",
        body,
      });
      await refreshMedia(draft.id);
    } catch (cause) {
      setError(String(cause));
    }
  }
  function defaultImagePrompt(
    kind: "portrait" | "full_body",
    outfitId: string | null,
  ) {
    const outfit = outfitId
      ? outfits.find(item => item.id === outfitId)
      : null;
    const imagegenDescription = String(draft?.state.imagegen_description ?? "").trim();
    const appearance = imagegenDescription
      || String(draft?.state.appearance ?? "").trim()
      || String(draft?.state.description ?? "").trim();
    const outfitImagegenDescription = String(outfit?.imagegen_description ?? "").trim();
    const outfitVisual = outfitImagegenDescription
      || String(outfit?.description ?? "").trim();
    const parts = [
      draft?.name ? `Character: ${draft.name}` : "",
      appearance,
      outfitVisual ? `Outfit: ${outfitVisual}` : "",
      kind === "portrait"
        ? "character portrait, focus on face and upper body"
        : "full body character image, show the complete character",
    ];
    return parts.filter(Boolean).join(". ");
  }

  async function generateMedia(
    kind: "portrait" | "full_body",
    outfitId: string | null,
    differentPrompt: boolean,
    existingAsset?: MediaAsset | null,
  ) {
    if (!draft?.id) return;
    const workflow = workflows[0];
    if (!workflow) return setError("Import a ComfyUI workflow first.");

    const basePrompt = existingAsset?.prompt?.trim()
      || defaultImagePrompt(kind, outfitId);
    const prompt = differentPrompt
      ? window.prompt("Image prompt", basePrompt)
      : basePrompt;
    if (!prompt?.trim()) return setError("An image prompt is required.");

    try {
      let asset = existingAsset ?? null;
      if (!asset) {
        asset = await api<MediaAsset>(`/entities/${draft.id}/media`, {
          method: "POST",
          body: JSON.stringify({
            kind,
            outfit_id: outfitId,
            prompt,
            negative_prompt: "",
          }),
        });
      } else {
        asset = await api<MediaAsset>(`/media-assets/${asset.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            prompt,
            negative_prompt: asset.negative_prompt,
          }),
        });
      }

      const job = await api<{ id: string; status: string }>(`/media-assets/${asset.id}/generate`, {
        method: "POST",
        body: JSON.stringify({
          workflow_preset_id: workflow.id,
          prompt,
          negative_prompt: asset.negative_prompt ?? "",
        }),
      });
      const slot = `${kind}:${outfitId ?? "default"}`;
      setMediaJobs(current => ({
        ...current,
        [slot]: { id: job.id, status: job.status || "queued" },
      }));
      await refreshMedia(draft.id);
    } catch (cause) {
      setError(String(cause));
    }
  }

  async function removeMedia(asset: MediaAsset) {
    if (!window.confirm("Remove this image?")) return;
    try {
      await api(`/media-assets/${asset.id}`, { method: "DELETE" });
      if (draft?.id) await refreshMedia(draft.id);
    } catch (cause) {
      setError(String(cause));
    }
  }
  async function createRelationship(relation: string, targetId: string, bidirectional: boolean) {
    if (!draft?.id) return;
    try {
      await api(`/projects/${projectId}/mutations`, {
        method: "POST",
        body: JSON.stringify({
          summary: `Added ${relation} relationship for ${draft.name}`,
          mutations: [{
            tool: "setRelationship",
            arguments: {
              source_id: draft.id,
              target_id: targetId,
              relation,
              bidirectional,
            },
          }],
        }),
      });
      await load();
    } catch (cause) {
      setError(String(cause));
    }
  }
  async function removeRelationship(relation: WorldRelationship) {
    if (!relation.id || !window.confirm("Remove this relationship from the current branch?")) return;
    try {
      await api(`/projects/${projectId}/relationships/${relation.id}`, { method: "DELETE" });
      await load();
    } catch (cause) {
      setError(String(cause));
    }
  }

  const listPortrait = (item: WorldEntity) => {
    const assets = characterMedia[item.id] ?? [];
    const activeOutfitId = String(item.state.active_outfit_id ?? "");
    const asset = assets.find(mediaAsset =>
      mediaAsset.kind === "portrait"
      && Boolean(activeOutfitId)
      && mediaAsset.outfit_id === activeOutfitId
      && mediaAsset.file_path)
      ?? assets.find(mediaAsset =>
        mediaAsset.kind === "portrait"
        && !mediaAsset.outfit_id
        && mediaAsset.file_path);
    return asset?.file_path ? `/media/${asset.file_path}` : null;
  };

  return <div className="page world-page"><header className="page-header"><p className="eyebrow">BRANCH-AWARE CAST</p><h1>Characters</h1><p>Player characters, NPCs, state, outfits, portraits, and branch history.</p></header><ResourceList title="Characters" query={query} setQuery={setQuery} onAdd={createCharacter}><div className="character-filter-grid"><TextField select size="small" label="Control" value={control} onChange={event => setControl(event.target.value)}><MenuItem value="">Everyone</MenuItem><MenuItem value="player">Player controlled</MenuItem><MenuItem value="npc">NPC</MenuItem></TextField><TextField select size="small" label="Status" value={status} onChange={event => setStatus(event.target.value)}><MenuItem value="active">Active</MenuItem><MenuItem value="archived">Archived</MenuItem><MenuItem value="all">All</MenuItem></TextField><TextField select size="small" label="Location" value={locationFilter} onChange={event => setLocationFilter(event.target.value)}><MenuItem value="">Every location</MenuItem>{locations.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField><BoxedMultiselectFilter label="Tags" options={tags} value={tagFilter} onChange={(_event, next) => setTagFilter(next)} /></div>{characters.map(item => <div className="resource-favorite-row" key={item.id}><ResourceButton enabled={!item.state.archived} disabledLabel="Archived" title={item.name} subtitle={`${item.state.player_controlled ? "Player" : "NPC"} · ${world?.entities[String(item.state.current_location_id)]?.name ?? "Unknown location"}`} thumbnail={listPortrait(item)} onClick={() => void openCharacter(item)} /><FavoriteLibraryButton projectId={projectId} sourceKind="character" sourceKey={item.id} /></div>)}</ResourceList>
    <RecordDrawer width={1180} title={draft ? `${draft.id ? "Edit" : "Create"} character` : ""} open={Boolean(draft)} dirty={dirty} error={error} onClose={() => close()} onSave={() => void save()} onArchive={draft?.id ? () => void archive() : undefined} archiveLabel={draft?.state.archived ? "Restore" : "Archive"} onDelete={draft?.id ? () => void remove() : undefined}>{draft && <CharacterEditorForm
      projectId={projectId}
      draft={draft}
      setDraft={setDraft}
      entities={entities}
      relations={Object.values(world?.relations ?? {}) as WorldRelationship[]}
      modes={catalog.modes.filter(item => bullet.allowed_mode_ids.includes(item.id))}
      skills={catalog.skills.filter(item => bullet.allowed_skill_ids.includes(item.id))}
      history={history}
      outfits={outfits}
      media={media}
      stats={rules.stats}
      abilities={rules.abilities}
      effects={rules.effects}
      activeEffects={Object.values(world?.active_effects ?? {}).filter(item => item.target_id === draft.id)}
      removeActiveEffect={removeActiveEffect}
      outfitDraft={outfitDraft}
      setOutfitDraft={setOutfitDraft}
      saveOutfit={saveOutfit}
      deleteOutfit={deleteOutfit}
      activateOutfit={activateOutfit}
      upload={upload}
      generateMedia={generateMedia}
      removeMedia={removeMedia}
      mediaJobs={mediaJobs}
      setStat={setStat}
      updateStatDefinition={updateStatDefinition}
      createRelationship={createRelationship}
      removeRelationship={removeRelationship}
    />}</RecordDrawer>
  </div>;
}
