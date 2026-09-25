import { useCallback, useEffect, useState } from "react";
import {
  Button,
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

export function GlobalLibraryStudio({
  projectId,
  fail,
  changed,
}: {
  projectId?: string;
  fail: (message: string) => void;
  changed?: () => void;
}) {
  const [resources, setResources] = useState<LibraryResource[]>([]);
  const [markedOnly, setMarkedOnly] = useState(true);
  const [kind, setKind] = useState("");
  const [search, setSearch] = useState("");
  const [saveStatsOpen, setSaveStatsOpen] = useState(false);
  const [packName, setPackName] = useState("");
  const [packDescription, setPackDescription] = useState("");
  const [packTags, setPackTags] = useState("");

  const load = useCallback(async () => {
    const params = new URLSearchParams();
    if (markedOnly) params.set("marked_only", "true");
    if (kind) params.set("resource_kind", kind);
    if (search.trim()) params.set("search", search.trim());
    setResources(await api<LibraryResource[]>("/library/resources?" + params.toString()));
  }, [markedOnly, kind, search]);

  useEffect(() => {
    void load().catch(cause => fail(String(cause)));
  }, [load, fail]);

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
        <MenuItem value="ability">Abilities</MenuItem>
        <MenuItem value="effect">Effects</MenuItem>
        <MenuItem value="bundle">Bundles</MenuItem>
        <MenuItem value="rule_pack">Rule packs</MenuItem>
      </TextField>
      <TextField size="small" label="Search name, description or tag" value={search} onChange={event => setSearch(event.target.value)} />
    </Paper>

    <Paper className="panel global-library-table">
      <div className="global-library-row header">
        <span>Name</span><span>Type</span><span>Revision</span><span>Children</span><span>Stories</span><span>Imports</span>
      </div>
      {resources.length === 0 && <div className="global-library-empty">No matching library resources.</div>}
      {resources.map(resource => <div className="global-library-row" key={resource.id}>
        <span className="global-library-name">
          <b>{resource.name}</b>
          {resource.description && <small>{resource.description}</small>}
        </span>
        <span><Chip size="small" label={resource.resource_kind.replaceAll("_", " ")} /></span>
        <span>{"r" + resource.revision_count}</span>
        <span>{resource.child_count}</span>
        <span>{resource.referenced_story_count}</span>
        <span>{resource.import_count}</span>
      </div>)}
    </Paper>

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
