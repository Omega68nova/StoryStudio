import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Snackbar,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
} from "@mui/material";
import type {
  MediaAsset,
  Outfit,
  WorkflowPreset,
  WorldEntity,
  WorldProjection,
} from "./types";
import type { BulletCatalog } from "./BulletHellStudio";

export function WorldStudio({
  projectId,
  revision,
  workflows,
  fail,
}: {
  projectId: string;
  revision: number;
  workflows: WorkflowPreset[];
  fail: (message: string) => void;
}) {
  const [world, setWorld] = useState<WorldProjection | null>(null);
  const [bulletCatalog, setBulletCatalog] = useState<BulletCatalog>({
    skills: [],
    modes: [],
    attacks: [],
  });
  const [bulletSettings, setBulletSettings] = useState<{
    allowed_mode_ids: string[];
    allowed_skill_ids: string[];
  }>({ allowed_mode_ids: [], allowed_skill_ids: [] });
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState("");
  const [entityName, setEntityName] = useState("");
  const [entityAliases, setEntityAliases] = useState("");
  const [entityTags, setEntityTags] = useState("");
  const [history, setHistory] = useState<Array<Record<string, unknown>>>([]);
  const [outfits, setOutfits] = useState<Outfit[]>([]);
  const [media, setMedia] = useState<MediaAsset[]>([]);
  const [route, setRoute] = useState({
    source_id: "",
    target_id: "",
    travel_minutes: 30,
    direction: "",
    modes: "walk",
  });
  const [outfitEdit, setOutfitEdit] = useState<{
    id?: string;
    entity_id?: string;
    name: string;
    description: string;
    equipment: string;
  } | null>(null);
  const [generateEdit, setGenerateEdit] = useState<MediaAsset | null>(null);
  const [generatePrompt, setGeneratePrompt] = useState("");
  const [statEdit, setStatEdit] = useState<{
    key: string;
    value: string;
  } | null>(null);
  const [deleteImpact, setDeleteImpact] = useState<{
    name: string;
    counts: Record<string, number>;
    confirmation: string;
  } | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [notice, setNotice] = useState("");
  const [pendingSelectedId, setPendingSelectedId] = useState<string | null>(
    null,
  );
  const load = useCallback(async () => {
    const [nextWorld, nextCatalog, nextSettings] = await Promise.all([
      api<WorldProjection>(`/projects/${projectId}/world`),
      api<BulletCatalog>("/bullethell/catalog"),
      api<{ allowed_mode_ids: string[]; allowed_skill_ids: string[] }>(
        `/projects/${projectId}/bullethell`,
      ),
    ]);
    setWorld(nextWorld);
    setBulletCatalog(nextCatalog);
    setBulletSettings(nextSettings);
  }, [projectId]);
  useEffect(() => {
    void load().catch((cause) => fail(String(cause)));
  }, [load, revision, fail]);
  const entities = useMemo(
    () =>
      Object.values(world?.entities ?? {}).filter(
        (entity) =>
          (!kind || entity.kind === kind) &&
          (!query ||
            entity.card.search_text
              .toLowerCase()
              .includes(query.toLowerCase())),
      ),
    [world, kind, query],
  );
  const selected = selectedId ? world?.entities[selectedId] : entities[0];
  const dirty = Boolean(
    selected &&
    (editing !== JSON.stringify(selected.state, null, 2) ||
      entityName !== selected.name ||
      entityAliases !== selected.aliases.join(", ") ||
      entityTags !== selected.tags.join(", ")),
  );
  useEffect(() => {
    document.body.dataset.storyStudioUnsaved = String(dirty);
    const warning = (event: BeforeUnloadEvent) => {
      if (dirty) event.preventDefault();
    };
    window.addEventListener("beforeunload", warning);
    return () => {
      window.removeEventListener("beforeunload", warning);
      document.body.dataset.storyStudioUnsaved = "false";
    };
  }, [dirty]);
  useEffect(() => {
    if (!selected) return;
    setEditing(JSON.stringify(selected.state, null, 2));
    setEntityName(selected.name);
    setEntityAliases(selected.aliases.join(", "));
    setEntityTags(selected.tags.join(", "));
    void Promise.all([
      api<Array<Record<string, unknown>>>(
        `/projects/${projectId}/entities/${selected.id}/history`,
      ),
      api<Outfit[]>(`/entities/${selected.id}/outfits`),
      api<MediaAsset[]>(`/entities/${selected.id}/media`),
    ])
      .then(([events, entityOutfits, assets]) => {
        setHistory(events);
        setOutfits(entityOutfits);
        setMedia(assets);
      })
      .catch(() => {
        setHistory([]);
        setOutfits([]);
        setMedia([]);
      });
  }, [selected?.id, projectId]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      await api(`/projects/${projectId}/entities`, {
        method: "POST",
        body: JSON.stringify({
          kind: data.get("kind"),
          name: data.get("name"),
          aliases: [],
          tags: String(data.get("tags") ?? "")
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
          state: {},
        }),
      });
      event.currentTarget.reset();
      await load();
    } catch (cause) {
      fail(cause instanceof Error ? cause.message : String(cause));
    }
  }
  async function save() {
    if (!selected) return;
    try {
      await api(`/projects/${projectId}/entities/${selected.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          patch: JSON.parse(editing),
          name: entityName.trim(),
          aliases: entityAliases
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
          tags: entityTags
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
        }),
      });
      await load();
    } catch (cause) {
      fail(cause instanceof Error ? cause.message : String(cause));
    }
  }
  async function addRoute() {
    try {
      await api(`/projects/${projectId}/mutations`, {
        method: "POST",
        body: JSON.stringify({
          summary: "Mapped travel route",
          mutations: [
            {
              tool: "setRelationship",
              arguments: {
                ...route,
                relation: "route",
                modes: route.modes.split(",").map((x) => x.trim()),
                bidirectional: true,
              },
            },
          ],
        }),
      });
      await load();
    } catch (cause) {
      fail(cause instanceof Error ? cause.message : String(cause));
    }
  }
  async function setNpc(
    autonomy_enabled: boolean,
    intervention_frequency = String(
      selected?.state.intervention_frequency ?? "normal",
    ),
  ) {
    if (!selected) return;
    try {
      await api(`/projects/${projectId}/characters/${selected.id}/npc`, {
        method: "PATCH",
        body: JSON.stringify({ autonomy_enabled, intervention_frequency }),
      });
      await load();
    } catch (cause) {
      fail(String(cause));
    }
  }
  function addOutfit() {
    if (selected)
      setOutfitEdit({
        entity_id: selected.id,
        name: "",
        description: "",
        equipment: "",
      });
  }
  function editOutfit(outfit: Outfit) {
    setOutfitEdit({
      id: outfit.id,
      entity_id: outfit.entity_id,
      name: outfit.name,
      description: outfit.description,
      equipment: outfit.equipment.join(", "),
    });
  }
  async function saveOutfit() {
    if (!outfitEdit?.entity_id || !outfitEdit.name.trim()) return;
    try {
      await api(
        outfitEdit.id
          ? `/outfits/${outfitEdit.id}`
          : `/entities/${outfitEdit.entity_id}/outfits`,
        {
          method: outfitEdit.id ? "PUT" : "POST",
          body: JSON.stringify({
            name: outfitEdit.name,
            description: outfitEdit.description,
            equipment: outfitEdit.equipment
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean),
          }),
        },
      );
      setOutfits(await api(`/entities/${outfitEdit.entity_id}/outfits`));
      setOutfitEdit(null);
    } catch (cause) {
      fail(String(cause));
    }
  }
  async function deleteOutfit(outfit: Outfit) {
    try {
      await api(`/outfits/${outfit.id}`, { method: "DELETE" });
      setOutfits(await api(`/entities/${outfit.entity_id}/outfits`));
    } catch (cause) {
      fail(String(cause));
    }
  }
  async function upload(kind: string, outfitId: string | null, file: File) {
    if (!selected) return;
    const form = new FormData();
    form.append("file", file);
    try {
      await api(
        `/entities/${selected.id}/media/upload?kind=${kind}${outfitId ? `&outfit_id=${outfitId}` : ""}`,
        { method: "POST", body: form },
      );
      setMedia(await api(`/entities/${selected.id}/media`));
    } catch (cause) {
      fail(String(cause));
    }
  }
  function generate(asset: MediaAsset) {
    if (!workflows[0]) {
      fail("Import a ComfyUI workflow first.");
      return;
    }
    setGenerateEdit(asset);
    setGeneratePrompt(asset.prompt);
  }
  async function confirmGenerate() {
    const asset = generateEdit,
      workflow = workflows[0];
    if (!asset || !workflow || !generatePrompt.trim()) return;
    try {
      await api(`/media-assets/${asset.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          prompt: generatePrompt,
          negative_prompt: asset.negative_prompt,
        }),
      });
      await api(`/media-assets/${asset.id}/generate`, {
        method: "POST",
        body: JSON.stringify({
          workflow_preset_id: workflow.id,
          prompt: generatePrompt,
          negative_prompt: asset.negative_prompt,
          width: workflow.mappings.width ? 1024 : null,
          height: workflow.mappings.height ? 1024 : null,
        }),
      });
      setMedia(await api(`/entities/${asset.entity_id}/media`));
      setGenerateEdit(null);
    } catch (cause) {
      fail(String(cause));
    }
  }
  async function removeMedia(asset: MediaAsset) {
    try {
      await api(`/media-assets/${asset.id}`, { method: "DELETE" });
      setMedia(await api(`/entities/${asset.entity_id}/media`));
    } catch (cause) {
      fail(String(cause));
    }
  }
  function correctStat(key: string, current: number) {
    setStatEdit({ key, value: String(current) });
  }
  async function saveStatCorrection() {
    if (!selected || !statEdit || !Number.isFinite(Number(statEdit.value)))
      return;
    try {
      await api(`/projects/${projectId}/stats/adjust`, {
        method: "POST",
        body: JSON.stringify({
          entity_id: selected.id,
          stat_key: statEdit.key,
          operation: "set",
          amount: Number(statEdit.value),
        }),
      });
      setStatEdit(null);
      await load();
    } catch (cause) {
      fail(String(cause));
    }
  }
  async function importBible() {
    try {
      const result = await api<{ imported: number }>(
        `/projects/${projectId}/bible-import`,
        { method: "POST" },
      );
      await load();
      setNotice(`Imported ${result.imported} story-bible documents.`);
    } catch (cause) {
      fail(String(cause));
    }
  }
  async function sync() {
    try {
      const result = await api<{ provider: string }>(
        `/projects/${projectId}/memory/sync`,
        { method: "POST" },
      );
      setNotice(`Memory indexed with ${result.provider}.`);
    } catch (cause) {
      fail(String(cause));
    }
  }
  async function archive() {
    if (!selected) return;
    try {
      await api(
        `/projects/${projectId}/entities/${selected.id}/${selected.state.archived ? "restore" : "archive"}`,
        { method: "POST" },
      );
      await load();
    } catch (cause) {
      fail(String(cause));
    }
  }
  async function hardDelete() {
    if (!selected) return;
    try {
      setDeleteImpact(
        await api(
          `/projects/${projectId}/entities/${selected.id}/delete-impact`,
        ),
      );
      setDeleteConfirm("");
    } catch (cause) {
      fail(String(cause));
    }
  }
  async function confirmHardDelete() {
    if (
      !selected ||
      !deleteImpact ||
      deleteConfirm !== deleteImpact.confirmation
    )
      return;
    try {
      await api(`/projects/${projectId}/entities/${selected.id}`, {
        method: "DELETE",
        body: JSON.stringify({ confirmation: deleteConfirm }),
      });
      setDeleteImpact(null);
      setSelectedId(null);
      await load();
    } catch (cause) {
      fail(String(cause));
    }
  }
  function selectEntity(id: string) {
    if (dirty && id !== selected?.id) setPendingSelectedId(id);
    else setSelectedId(id);
  }

  const locations = Object.values(world?.entities ?? {}).filter(
    (entity) => entity.kind === "location",
  );
  return (
    <>
      <div className="page world-page">
        <header className="page-header world-title">
          <div>
            <p className="eyebrow">BRANCH-AWARE MEMORY</p>
            <h1>World workspace</h1>
            <p>
              {Object.keys(world?.entities ?? {}).length} entities ·{" "}
              {world?.elapsed_minutes ?? 0} elapsed minutes ·{" "}
              {world?.transactions.length ?? 0} transactions
            </p>
          </div>
          <div className="button-row">
            <Button onClick={importBible}>Import story bible</Button>
            <Button onClick={sync}>Sync memory index</Button>
          </div>
        </header>
        {selected?.kind === "character" && (
          <section className="panel entity-identity">
            <TextField
              size="small"
              label="Character name"
              value={entityName}
              onChange={(e) => setEntityName(e.target.value)}
            />
            <TextField
              size="small"
              label="Aliases"
              value={entityAliases}
              onChange={(e) => setEntityAliases(e.target.value)}
            />
            <TextField
              size="small"
              label="Tags"
              value={entityTags}
              onChange={(e) => setEntityTags(e.target.value)}
            />
            <span>Changes commit with the character state below.</span>
          </section>
        )}
        <div className="world-grid">
          <section className="panel entity-browser">
            <h2>Entities</h2>
            <div className="filter-row">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search names, aliases, tags…"
              />
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="">All kinds</option>
                {[
                  "character",
                  "location",
                  "faction",
                  "item",
                  "lore_system",
                  "fact",
                  "relationship",
                  "plot_beat",
                ].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </div>
            <div className="entity-list">
              {entities.map((entity) => (
                <Button
                  className={selected?.id === entity.id ? "active" : ""}
                  key={entity.id}
                  onClick={() => selectEntity(entity.id)}
                >
                  <strong>{entity.name}</strong>
                  <small>{entity.kind.replaceAll("_", " ")}</small>
                </Button>
              ))}
            </div>
            <form className="quick-create" onSubmit={create}>
              <h3>Add entity</h3>
              <input name="name" required placeholder="Name" />
              <select name="kind">
                {[
                  "character",
                  "location",
                  "faction",
                  "item",
                  "lore_system",
                  "fact",
                  "plot_beat",
                ].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
              <input name="tags" placeholder="tags, comma separated" />
              <button>Add</button>
            </form>
          </section>
          <section className="panel entity-sheet">
            {selected ? (
              <>
                <p className="eyebrow">
                  {selected.kind}
                  {selected.state.archived ? " · archived" : ""}
                </p>
                <h2>{selected.name}</h2>
                <p>{selected.card.compact_text}</p>
                {selected.stats && (
                  <div className="stat-strip">
                    {Object.entries(selected.stats).map(([key, value]) => (
                      <button
                        key={key}
                        onClick={() => void correctStat(key, value)}
                        title="Manually correct this branch-relative value"
                      >
                        <b>{key}</b> {value}
                      </button>
                    ))}
                  </div>
                )}
                {selected.active_effects?.length ? (
                  <details className="effect-note">
                    <summary>
                      {selected.active_effects.length} active effect(s)
                    </summary>
                    <pre>
                      {JSON.stringify(selected.active_effects, null, 2)}
                    </pre>
                  </details>
                ) : null}
                {selected.kind === "character" && (
                  <CharacterStateEditor
                    value={editing}
                    onChange={setEditing}
                    locations={locations}
                    modes={bulletCatalog.modes.filter((item) =>
                      bulletSettings.allowed_mode_ids.includes(item.id),
                    )}
                    skills={bulletCatalog.skills.filter((item) =>
                      bulletSettings.allowed_skill_ids.includes(item.id),
                    )}
                  />
                )}
                {selected.kind === "character" &&
                  !selected.state.player_controlled && (
                    <div className="npc-controls">
                      <FormControlLabel
                        control={
                          <Switch
                            checked={Boolean(selected.state.autonomy_enabled)}
                            onChange={(e) => void setNpc(e.target.checked)}
                          />
                        }
                        label="NPC autonomy"
                      />
                      <TextField
                        select
                        size="small"
                        value={String(
                          selected.state.intervention_frequency ?? "normal",
                        )}
                        onChange={(e) =>
                          void setNpc(
                            Boolean(selected.state.autonomy_enabled),
                            e.target.value,
                          )
                        }
                      >
                        {["low", "normal", "high"].map((value) => (
                          <MenuItem key={value} value={value}>
                            {value}
                          </MenuItem>
                        ))}
                      </TextField>
                    </div>
                  )}
                {selected.card.visual_description && (
                  <div className="visual-card">
                    <strong>Scene-era visual</strong>
                    <p>{selected.card.visual_description}</p>
                    <small>{selected.card.image_tags.join(", ")}</small>
                  </div>
                )}
                <div className="profile-media">
                  {media.map((asset) => (
                    <article key={asset.id}>
                      {asset.file_path ? (
                        <img src={`/media/${asset.file_path}`} />
                      ) : (
                        <div className="media-placeholder">{asset.kind}</div>
                      )}
                      <Button onClick={() => void generate(asset)}>
                        Generate
                      </Button>
                      <Button onClick={() => void removeMedia(asset)}>
                        Remove
                      </Button>
                    </article>
                  ))}
                </div>
                {selected.kind === "character" && (
                  <>
                    <div className="sheet-heading">
                      <h3>Outfits</h3>
                      <Button onClick={addOutfit}>Add outfit</Button>
                    </div>
                    {outfits.map((outfit) => (
                      <article className="outfit-row" key={outfit.id}>
                        <strong>{outfit.name}</strong>
                        <span>{outfit.description}</span>
                        <Button onClick={() => void editOutfit(outfit)}>
                          Edit
                        </Button>
                        <Button onClick={() => void deleteOutfit(outfit)}>
                          Delete
                        </Button>
                        <Button
                          disabled={
                            selected.state.active_outfit_id === outfit.id
                          }
                          onClick={async () => {
                            await api(`/outfits/${outfit.id}/activate`, {
                              method: "POST",
                            });
                            await load();
                          }}
                        >
                          {selected.state.active_outfit_id === outfit.id
                            ? "Active"
                            : "Wear"}
                        </Button>
                        <label>
                          Portrait
                          <input
                            type="file"
                            accept="image/png,image/jpeg,image/webp"
                            onChange={(e) =>
                              e.target.files?.[0] &&
                              void upload(
                                "portrait",
                                outfit.id,
                                e.target.files[0],
                              )
                            }
                          />
                        </label>
                        <label>
                          Full body
                          <input
                            type="file"
                            accept="image/png,image/jpeg,image/webp"
                            onChange={(e) =>
                              e.target.files?.[0] &&
                              void upload(
                                "full_body",
                                outfit.id,
                                e.target.files[0],
                              )
                            }
                          />
                        </label>
                      </article>
                    ))}
                  </>
                )}{" "}
                {selected.kind === "location" && (
                  <label className="file-button">
                    Upload location image
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      onChange={(e) =>
                        e.target.files?.[0] &&
                        void upload("location", null, e.target.files[0])
                      }
                    />
                  </label>
                )}
                {selected.kind !== "character" && (
                  <label>
                    Canonical state JSON
                    <textarea
                      className="json-editor"
                      value={editing}
                      onChange={(e) => setEditing(e.target.value)}
                      spellCheck={false}
                    />
                  </label>
                )}
                <div className="button-row">
                  <Button variant="contained" onClick={save}>
                    Commit update
                  </Button>
                  <Button onClick={() => void archive()}>
                    {selected.state.archived ? "Restore" : "Archive"}
                  </Button>
                  <Button color="error" onClick={() => void hardDelete()}>
                    Delete permanently
                  </Button>
                </div>
                <details className="entity-history">
                  <summary>{history.length} historical event(s)</summary>
                  {history.map((event) => (
                    <article key={String(event.id)}>
                      <strong>{String(event.event_type)}</strong>
                      <small>
                        {String(event.provenance)} · sequence{" "}
                        {String(event.branch_sequence)}
                      </small>
                      <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                    </article>
                  ))}
                </details>
              </>
            ) : (
              <p className="muted">Create or select an entity.</p>
            )}
          </section>
          <section className="panel map-panel">
            <h2>Location map</h2>
            <div className="map-canvas">
              {locations.map((location) => (
                <button
                  key={location.id}
                  style={{
                    left: `${50 + Number(location.state.x ?? 0) * 3}%`,
                    top: `${50 - Number(location.state.y ?? 0) * 3}%`,
                  }}
                  onClick={() => setSelectedId(location.id)}
                >
                  {location.name}
                </button>
              ))}
            </div>
            <div className="route-form">
              <select
                value={route.source_id}
                onChange={(e) =>
                  setRoute({ ...route, source_id: e.target.value })
                }
              >
                <option value="">From</option>
                {locations.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
              </select>
              <select
                value={route.target_id}
                onChange={(e) =>
                  setRoute({ ...route, target_id: e.target.value })
                }
              >
                <option value="">To</option>
                {locations.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
              </select>
              <input
                type="number"
                value={route.travel_minutes}
                onChange={(e) =>
                  setRoute({ ...route, travel_minutes: Number(e.target.value) })
                }
                title="Travel minutes"
              />
              <input
                value={route.direction}
                onChange={(e) =>
                  setRoute({ ...route, direction: e.target.value })
                }
                placeholder="north"
              />
              <input
                value={route.modes}
                onChange={(e) => setRoute({ ...route, modes: e.target.value })}
                placeholder="walk, horse"
              />
              <button
                disabled={!route.source_id || !route.target_id}
                onClick={addRoute}
              >
                Add route
              </button>
            </div>
          </section>
          <section className="panel audit-panel">
            <h2>Memory audit</h2>
            {[...(world?.transactions ?? [])].reverse().map((tx) => (
              <article key={String(tx.id)}>
                <strong>{String(tx.summary || "World change")}</strong>
                <small>
                  {String(tx.provenance)}
                  {tx.display_time ? ` · ${String(tx.display_time)}` : ""}
                </small>
              </article>
            ))}
          </section>
        </div>
      </div>
      <Dialog open={Boolean(outfitEdit)} onClose={() => setOutfitEdit(null)}>
        <DialogTitle>{outfitEdit?.id ? "Edit" : "Add"} outfit</DialogTitle>
        <DialogContent className="music-dialog">
          {outfitEdit && (
            <>
              <TextField
                label="Name"
                value={outfitEdit.name}
                onChange={(e) =>
                  setOutfitEdit({ ...outfitEdit, name: e.target.value })
                }
              />
              <TextField
                multiline
                minRows={3}
                label="Visual description"
                value={outfitEdit.description}
                onChange={(e) =>
                  setOutfitEdit({ ...outfitEdit, description: e.target.value })
                }
              />
              <TextField
                label="Equipment, comma separated"
                value={outfitEdit.equipment}
                onChange={(e) =>
                  setOutfitEdit({ ...outfitEdit, equipment: e.target.value })
                }
              />
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOutfitEdit(null)}>Cancel</Button>
          <Button variant="contained" onClick={() => void saveOutfit()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={Boolean(generateEdit)}
        onClose={() => setGenerateEdit(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Generate entity image</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={5}
            label="Historical image prompt"
            value={generatePrompt}
            onChange={(e) => setGeneratePrompt(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setGenerateEdit(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!generatePrompt.trim()}
            onClick={() => void confirmGenerate()}
          >
            Generate
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={Boolean(statEdit)} onClose={() => setStatEdit(null)}>
        <DialogTitle>Correct branch stat</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            type="number"
            label={statEdit?.key}
            value={statEdit?.value ?? ""}
            onChange={(e) =>
              statEdit && setStatEdit({ ...statEdit, value: e.target.value })
            }
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStatEdit(null)}>Cancel</Button>
          <Button variant="contained" onClick={() => void saveStatCorrection()}>
            Commit correction
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={Boolean(deleteImpact)}
        onClose={() => setDeleteImpact(null)}
      >
        <DialogTitle>Permanently delete entity?</DialogTitle>
        <DialogContent>
          <Alert severity="warning">
            This alters historical continuity and removes{" "}
            {deleteImpact &&
              Object.entries(deleteImpact.counts)
                .map(([key, value]) => `${value} ${key.replaceAll("_", " ")}`)
                .join(", ")}
            .
          </Alert>
          <TextField
            fullWidth
            sx={{ mt: 2 }}
            label={`Type ${deleteImpact?.confirmation ?? ""}`}
            value={deleteConfirm}
            onChange={(e) => setDeleteConfirm(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteImpact(null)}>Cancel</Button>
          <Button
            color="error"
            disabled={deleteConfirm !== deleteImpact?.confirmation}
            onClick={() => void confirmHardDelete()}
          >
            Delete permanently
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={Boolean(pendingSelectedId)}
        onClose={() => setPendingSelectedId(null)}
      >
        <DialogTitle>Discard unsaved entity changes?</DialogTitle>
        <DialogContent>
          The selected entity has local edits that have not been committed.
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPendingSelectedId(null)}>
            Keep editing
          </Button>
          <Button
            color="error"
            onClick={() => {
              setSelectedId(pendingSelectedId);
              setPendingSelectedId(null);
            }}
          >
            Discard and switch
          </Button>
        </DialogActions>
      </Dialog>
      <Snackbar
        open={Boolean(notice)}
        autoHideDuration={5000}
        onClose={() => setNotice("")}
        message={notice}
      />
    </>
  );
}

function CharacterStateEditor({
  value,
  onChange,
  locations,
  modes,
  skills,
}: {
  value: string;
  onChange: (value: string) => void;
  locations: WorldEntity[];
  modes: Array<{ id: string; name: string }>;
  skills: Array<{ id: string; name: string }>;
}) {
  const [tab, setTab] = useState(0);
  let state: Record<string, any> = {};
  try {
    state = JSON.parse(value || "{}");
  } catch {
    /* Advanced view preserves invalid text for correction. */
  }
  const set = (key: string, next: unknown) =>
    onChange(JSON.stringify({ ...state, [key]: next }, null, 2));
  const list = (key: string) =>
    Array.isArray(state[key]) ? state[key].join(", ") : "";
  const setList = (key: string, text: string) =>
    set(
      key,
      text
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    );
  const inventory = Array.isArray(state.inventory)
    ? (state.inventory as Array<{ item_id: string; quantity: number }>)
    : [];
  const setInventoryEntry = (
    index: number,
    patch: Partial<{ item_id: string; quantity: number }>,
  ) =>
    set(
      "inventory",
      inventory.map((entry, position) =>
        position === index ? { ...entry, ...patch } : entry,
      ),
    );
  const tabs = [
    "Identity",
    "Personality",
    "Appearance",
    "Wardrobe",
    "Equipment",
    "Abilities",
    "Relationships",
    "Location",
    "Knowledge",
    "Control",
    "Advanced",
  ];
  return (
    <div className="character-editor">
      <Tabs
        value={tab}
        onChange={(_, next) => setTab(next)}
        variant="scrollable"
        scrollButtons="auto"
      >
        {tabs.map((label) => (
          <Tab key={label} label={label} />
        ))}
      </Tabs>
      {tab === 0 && (
        <div className="character-fields">
          <TextField
            label="Identity notes"
            value={state.identity ?? ""}
            onChange={(e) => set("identity", e.target.value)}
          />
          <TextField
            label="Pronouns"
            value={state.pronouns ?? ""}
            onChange={(e) => set("pronouns", e.target.value)}
          />
        </div>
      )}
      {tab === 1 && (
        <div className="character-fields">
          <TextField
            multiline
            minRows={3}
            label="Personality"
            value={state.personality ?? ""}
            onChange={(e) => set("personality", e.target.value)}
          />
          <TextField
            label="Goals"
            value={list("goals")}
            onChange={(e) => setList("goals", e.target.value)}
          />
        </div>
      )}
      {tab === 2 && (
        <div className="character-fields">
          <TextField
            multiline
            minRows={4}
            label="Persistent appearance"
            value={state.appearance ?? ""}
            onChange={(e) => set("appearance", e.target.value)}
          />
        </div>
      )}
      {tab === 3 && (
        <div className="character-fields">
          <TextField
            multiline
            minRows={4}
            label="Wardrobe notes"
            value={state.wardrobe ?? ""}
            onChange={(e) => set("wardrobe", e.target.value)}
          />
          <TextField
            label="Active outfit ID"
            value={state.active_outfit_id ?? ""}
            onChange={(e) => set("active_outfit_id", e.target.value || null)}
          />
        </div>
      )}
      {tab === 4 && (
        <div className="character-fields">
          <TextField
            label="Equipment"
            value={list("equipment")}
            onChange={(e) => setList("equipment", e.target.value)}
          />
          {inventory.map((entry, index) => (
            <Stack
              direction="row"
              spacing={1}
              key={`${entry.item_id}:${index}`}
            >
              <TextField
                label="Inventory item entity ID"
                value={entry.item_id}
                onChange={(e) =>
                  setInventoryEntry(index, { item_id: e.target.value })
                }
              />
              <TextField
                type="number"
                label="Quantity"
                value={entry.quantity}
                inputProps={{ min: 0, step: 1 }}
                onChange={(e) =>
                  setInventoryEntry(index, {
                    quantity: Math.max(
                      0,
                      Math.floor(Number(e.target.value) || 0),
                    ),
                  })
                }
              />
              <Button
                color="error"
                onClick={() =>
                  set(
                    "inventory",
                    inventory.filter((_, position) => position !== index),
                  )
                }
              >
                Remove
              </Button>
            </Stack>
          ))}
          <Button
            onClick={() =>
              set("inventory", [...inventory, { item_id: "", quantity: 1 }])
            }
          >
            Add inventory item
          </Button>
          <small>
            Lockpick items must reference an item entity tagged “lockpick”.
          </small>
        </div>
      )}
      {tab === 5 && (
        <div className="character-fields">
          <TextField
            label="Ability keys"
            value={list("abilities")}
            onChange={(e) => setList("abilities", e.target.value)}
          />
        </div>
      )}
      {tab === 6 && (
        <div className="character-fields">
          <TextField
            multiline
            minRows={4}
            label="Relationship notes"
            value={state.relationships ?? ""}
            onChange={(e) => set("relationships", e.target.value)}
          />
        </div>
      )}
      {tab === 7 && (
        <div className="character-fields">
          <TextField
            select
            label="Current location"
            value={state.current_location_id ?? ""}
            onChange={(e) => set("current_location_id", e.target.value || null)}
          >
            <MenuItem value="">Unknown</MenuItem>
            {locations.map((location) => (
              <MenuItem key={location.id} value={location.id}>
                {location.name}
              </MenuItem>
            ))}
          </TextField>
        </div>
      )}
      {tab === 8 && (
        <div className="character-fields">
          <TextField
            label="Known fact IDs"
            value={list("knowledge")}
            onChange={(e) => setList("knowledge", e.target.value)}
          />
        </div>
      )}
      {tab === 9 && (
        <div className="character-fields">
          <FormControlLabel
            control={
              <Switch
                checked={Boolean(state.player_controlled)}
                onChange={(e) => set("player_controlled", e.target.checked)}
              />
            }
            label="Player controlled"
          />
          <FormControlLabel
            control={
              <Switch
                checked={Boolean(state.autonomy_enabled)}
                onChange={(e) => set("autonomy_enabled", e.target.checked)}
              />
            }
            label="NPC autonomy"
          />
          <TextField
            select
            label="Intervention frequency"
            value={String(state.intervention_frequency ?? "normal")}
            onChange={(e) => set("intervention_frequency", e.target.value)}
          >
            <MenuItem value="low">Low</MenuItem>
            <MenuItem value="normal">Normal</MenuItem>
            <MenuItem value="high">High</MenuItem>
          </TextField>
          <TextField
            select
            label="Default bullet-hell mode"
            value={state.bullethell_default_mode_id ?? ""}
            onChange={(e) =>
              set("bullethell_default_mode_id", e.target.value || null)
            }
          >
            <MenuItem value="">Project default</MenuItem>
            {modes.map((mode) => (
              <MenuItem key={mode.id} value={mode.id}>{mode.name}</MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Enemy forced mode"
            value={state.bullethell_forced_mode_id ?? ""}
            onChange={(e) =>
              set("bullethell_forced_mode_id", e.target.value || null)
            }
          >
            <MenuItem value="">None</MenuItem>
            {modes.map((mode) => (
              <MenuItem key={mode.id} value={mode.id}>{mode.name}</MenuItem>
            ))}
          </TextField>
          <TextField
            label="Direct bullet-hell skill IDs"
            value={list("bullethell_skill_ids")}
            onChange={(e) => setList("bullethell_skill_ids", e.target.value)}
            helperText={skills.length ? `Enabled: ${skills.map((skill) => `${skill.name} (${skill.id})`).join(", ")}` : "Enable skills in Bullet Hell first."}
          />
        </div>
      )}
      {tab === 10 && (
        <TextField
          multiline
          minRows={12}
          fullWidth
          label="Advanced state JSON"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          helperText="Protected entity IDs are validated by the server."
        />
      )}
    </div>
  );
}
