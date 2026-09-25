import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Paper,
  Switch,
  TextField,
} from "@mui/material";
import { api } from "./api";

type LibraryResource = {
  id: string;
  resource_kind: string;
  name: string;
  description: string;
  marked: number | boolean;
  current_revision_id?: string | null;
  revision_count: number;
  child_count: number;
  referenced_story_count: number;
  import_count: number;
};

type LibraryExport = {
  schema: string;
  schema_version: number;
  resources: unknown[];
};

export function GlobalLibraryStudio({
  projectId,
  sourceStoryNodeId,
  fail,
  changed,
}: {
  projectId?: string;
  sourceStoryNodeId?: string | null;
  fail: (message: string) => void;
  changed?: () => void;
}) {
  const [resources, setResources] = useState<LibraryResource[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [markedOnly, setMarkedOnly] = useState(true);
  const [kind, setKind] = useState("");
  const [search, setSearch] = useState("");
  const [saveStatsOpen, setSaveStatsOpen] = useState(false);
  const [packName, setPackName] = useState("");
  const [packDescription, setPackDescription] = useState("");
  const [packTags, setPackTags] = useState("");
  const [applyResource, setApplyResource] = useState<LibraryResource | null>(null);
  const [conflictPolicy, setConflictPolicy] = useState<"error" | "skip">("error");
  const [presetOpen, setPresetOpen] = useState(false);
  const [presetMembers, setPresetMembers] = useState<string[]>([]);
  const [presetName, setPresetName] = useState("");
  const [presetDescription, setPresetDescription] = useState("");
  const [presetTags, setPresetTags] = useState("");

  const load = useCallback(async () => {
    const params = new URLSearchParams();
    if (markedOnly) params.set("marked_only", "true");
    if (kind) params.set("resource_kind", kind);
    if (search.trim()) params.set("search", search.trim());
    const next = await api<LibraryResource[]>("/library/resources?" + params.toString());
    setResources(next);
    setSelected(current => new Set([...current].filter(id => next.some(item => item.id === id))));
  }, [markedOnly, kind, search]);

  useEffect(() => {
    void load().catch(cause => fail(String(cause)));
  }, [load, fail]);

  const allVisibleSelected = useMemo(
    () => resources.length > 0 && resources.every(item => selected.has(item.id)),
    [resources, selected],
  );

  async function saveStats() {
    if (!projectId || !packName.trim()) return;
    try {
      await api("/projects/" + projectId + "/library/stat-packs", {
        method: "POST",
        body: JSON.stringify({
          name: packName.trim(),
          description: packDescription.trim(),
          stat_keys: null,
          marked: true,
          tags: packTags.split(",").map(item => item.trim()).filter(Boolean),
          source_story_node_id: sourceStoryNodeId || null,
        }),
      });
      setSaveStatsOpen(false);
      setPackName("");
      setPackDescription("");
      setPackTags("");
      await load();
      changed?.();
    } catch (cause) {
      fail(String(cause));
    }
  }

  async function applyStatPack() {
    if (!projectId || !applyResource) return;
    try {
      await api("/projects/" + projectId + "/library/stat-packs/" + applyResource.id + "/apply", {
        method: "POST",
        body: JSON.stringify({
          conflict_policy: conflictPolicy,
          source_story_node_id: sourceStoryNodeId || null,
        }),
      });
      setApplyResource(null);
      changed?.();
      await load();
    } catch (cause) {
      fail(String(cause));
    }
  }

  async function setMarked(resourceIds: string[], marked: boolean) {
    if (!resourceIds.length) return;
    try {
      await api("/library/resources/mark", {
        method: "POST",
        body: JSON.stringify({ resource_ids: resourceIds, marked }),
      });
      setSelected(current => {
        const next = new Set(current);
        resourceIds.forEach(id => next.delete(id));
        return next;
      });
      await load();
      changed?.();
    } catch (cause) {
      fail(String(cause));
    }
  }

  function openPreset(resourceIds: string[]) {
    setPresetMembers([...new Set(resourceIds)]);
    setPresetName("");
    setPresetDescription("");
    setPresetTags("");
    setPresetOpen(true);
  }

  async function createPreset() {
    if (!presetName.trim() || !presetMembers.length) return;
    try {
      await api("/library/presets", {
        method: "POST",
        body: JSON.stringify({
          name: presetName.trim(),
          description: presetDescription.trim(),
          resource_ids: presetMembers,
          tags: presetTags.split(",").map(item => item.trim()).filter(Boolean),
        }),
      });
      setPresetOpen(false);
      setSelected(new Set());
      await load();
      changed?.();
    } catch (cause) {
      fail(String(cause));
    }
  }

  async function exportJson(resourceIds: string[]) {
    if (!resourceIds.length) return;
    try {
      const payload = await api<LibraryExport>("/library/export", {
        method: "POST",
        body: JSON.stringify({ resource_ids: resourceIds, include_revisions: true }),
      });
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const stamp = new Date().toISOString().replaceAll(":", "-").replace(/\..+$/, "");
      link.href = url;
      link.download = resourceIds.length === 1
        ? "storystudio-library-" + (resources.find(item => item.id === resourceIds[0])?.name ?? "resource").replace(/[^a-z0-9_-]+/gi, "_") + ".json"
        : "storystudio-library-export-" + stamp + ".json";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (cause) {
      fail(String(cause));
    }
  }

  function toggleSelected(id: string, checked: boolean) {
    setSelected(current => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  return <div className="global-library-studio">
    <header className="global-library-header">
      <div>
        <p className="eyebrow">REUSABLE RESOURCES</p>
        <h2>Global Library</h2>
        <p>Revisioned snapshots stay independent from live story branches. Importing creates project-local canonical records.</p>
      </div>
      {projectId && <Button variant="contained" onClick={() => setSaveStatsOpen(true)}>Save current stats as pack</Button>}
    </header>

    <Paper className="panel global-library-toolbar">
      <FormControlLabel
        control={<Switch checked={markedOnly} onChange={event => setMarkedOnly(event.target.checked)} />}
        label={markedOnly ? "Marked only" : "All entries"}
      />
      <TextField
        size="small"
        select
        label="Type"
        value={kind}
        onChange={event => setKind(event.target.value)}
      >
        <MenuItem value="">All types</MenuItem>
        <MenuItem value="stat_pack">Stat packs</MenuItem>
        <MenuItem value="character">Characters</MenuItem>
        <MenuItem value="location">Locations</MenuItem>
        <MenuItem value="item">Items</MenuItem>
        <MenuItem value="outfit">Outfits</MenuItem>
        <MenuItem value="faction">Factions</MenuItem>
        <MenuItem value="lore_system">Lore systems</MenuItem>
        <MenuItem value="fact">Facts</MenuItem>
        <MenuItem value="plot_beat">Plot beats</MenuItem>
        <MenuItem value="stat">Stats</MenuItem>
        <MenuItem value="ability">Abilities</MenuItem>
        <MenuItem value="effect">Effects</MenuItem>
        <MenuItem value="bundle">Bundles / presets</MenuItem>
        <MenuItem value="rule_pack">Rule packs</MenuItem>
      </TextField>
      <TextField size="small" label="Search name, description or tag" value={search} onChange={event => setSearch(event.target.value)} />
    </Paper>

    {selected.size > 0 && <Paper className="panel global-library-batchbar">
      <b>{selected.size} selected</b>
      <Button size="small" onClick={() => void setMarked([...selected], false)}>Remove from favorites</Button>
      <Button size="small" onClick={() => openPreset([...selected])}>Group into preset</Button>
      <Button size="small" onClick={() => void exportJson([...selected])}>Export JSON</Button>
      <Button size="small" onClick={() => setSelected(new Set())}>Clear</Button>
    </Paper>}

    <Paper className="panel global-library-table">
      <div className="global-library-row header">
        <span><Checkbox
          size="small"
          checked={allVisibleSelected}
          indeterminate={selected.size > 0 && !allVisibleSelected}
          onChange={event => setSelected(event.target.checked ? new Set(resources.map(item => item.id)) : new Set())}
        /></span>
        <span>Name</span><span>Type</span><span>Revision</span><span>Children</span><span>Stories</span><span>Imports</span><span>Actions</span>
      </div>
      {resources.length === 0 && <div className="global-library-empty">No matching library resources.</div>}
      {resources.map(resource => <div className="global-library-row" key={resource.id}>
        <span><Checkbox
          size="small"
          checked={selected.has(resource.id)}
          onChange={event => toggleSelected(resource.id, event.target.checked)}
        /></span>
        <span className="global-library-name">
          <b>{resource.name}</b>
          {resource.description && <small>{resource.description}</small>}
        </span>
        <span><Chip size="small" label={resource.resource_kind.replaceAll("_", " ")} /></span>
        <span>{"r" + resource.revision_count}</span>
        <span>{resource.child_count}</span>
        <span>{resource.referenced_story_count}</span>
        <span>{resource.import_count}</span>
        <span className="global-library-row-actions">
          {projectId && resource.resource_kind === "stat_pack" && <Button size="small" onClick={() => { setConflictPolicy("error"); setApplyResource(resource); }}>Apply</Button>}
          <Button size="small" onClick={() => void setMarked([resource.id], !Boolean(resource.marked))}>
            {resource.marked ? "Unfavorite" : "Favorite"}
          </Button>
          <Button size="small" onClick={() => openPreset([resource.id])}>Preset</Button>
          <Button size="small" onClick={() => void exportJson([resource.id])}>JSON</Button>
        </span>
      </div>)}
    </Paper>

    <Dialog open={presetOpen} onClose={() => setPresetOpen(false)} fullWidth maxWidth="sm">
      <DialogTitle>Group into named preset</DialogTitle>
      <DialogContent sx={{ display: "grid", gap: 2, pt: "12px !important" }}>
        <TextField autoFocus label="Preset name" value={presetName} onChange={event => setPresetName(event.target.value)} />
        <TextField multiline minRows={2} label="Description" value={presetDescription} onChange={event => setPresetDescription(event.target.value)} />
        <TextField label="Tags" helperText="Comma separated" value={presetTags} onChange={event => setPresetTags(event.target.value)} />
        <small>{presetMembers.length} resource{presetMembers.length === 1 ? "" : "s"} will be linked as members. Existing resources are not copied or modified.</small>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setPresetOpen(false)}>Cancel</Button>
        <Button variant="contained" disabled={!presetName.trim() || !presetMembers.length} onClick={() => void createPreset()}>Create preset</Button>
      </DialogActions>
    </Dialog>

    <Dialog open={Boolean(applyResource)} onClose={() => setApplyResource(null)} fullWidth maxWidth="xs">
      <DialogTitle>Apply {applyResource?.name}</DialogTitle>
      <DialogContent sx={{ display: "grid", gap: 2, pt: "12px !important" }}>
        <TextField
          select
          label="If a stat key already exists"
          value={conflictPolicy}
          onChange={event => setConflictPolicy(event.target.value as "error" | "skip")}
        >
          <MenuItem value="error">Stop and report conflict</MenuItem>
          <MenuItem value="skip">Keep existing stat</MenuItem>
        </TextField>
        <small>The imported definitions become independent project-local rules. Future library revisions do not update this story automatically.</small>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setApplyResource(null)}>Cancel</Button>
        <Button variant="contained" onClick={() => void applyStatPack()}>Apply pack</Button>
      </DialogActions>
    </Dialog>

    <Dialog open={saveStatsOpen} onClose={() => setSaveStatsOpen(false)} fullWidth maxWidth="sm">
      <DialogTitle>Save reusable stat pack</DialogTitle>
      <DialogContent sx={{ display: "grid", gap: 2, pt: "12px !important" }}>
        <TextField autoFocus label="Pack name" value={packName} onChange={event => setPackName(event.target.value)} />
        <TextField multiline minRows={2} label="Description" value={packDescription} onChange={event => setPackDescription(event.target.value)} />
        <TextField label="Tags" helperText="Comma separated" value={packTags} onChange={event => setPackTags(event.target.value)} />
        <small>This saves the current canonical stat definitions as an immutable library revision. Runtime character values are not included.</small>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setSaveStatsOpen(false)}>Cancel</Button>
        <Button variant="contained" disabled={!packName.trim()} onClick={() => void saveStats()}>Save pack</Button>
      </DialogActions>
    </Dialog>
  </div>;
}
