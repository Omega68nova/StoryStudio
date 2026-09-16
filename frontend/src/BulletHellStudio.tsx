import { useCallback, useEffect, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { api } from "./api";

export type BulletDefinition = Record<string, any> & {
  id: string;
  definition_key: string;
  name: string;
  built_in: boolean;
};
export type BulletCatalog = {
  skills: BulletDefinition[];
  modes: BulletDefinition[];
  attacks: BulletDefinition[];
};
type Settings = {
  default_mode_id: string;
  allowed_mode_ids: string[];
  allowed_skill_ids: string[];
  allowed_attack_ids: string[];
};

export function BulletHellStudio({
  projectId,
  revision,
  fail,
}: {
  projectId: string;
  revision: number;
  fail: (message: string) => void;
}) {
  const [catalog, setCatalog] = useState<BulletCatalog>({
    skills: [],
    modes: [],
    attacks: [],
  });
  const [settings, setSettings] = useState<Settings>({
    default_mode_id: "builtin:base",
    allowed_mode_ids: [],
    allowed_skill_ids: [],
    allowed_attack_ids: [],
  });
  const [tab, setTab] = useState(0),
    [editing, setEditing] = useState<{
      kind: keyof BulletCatalog;
      value: BulletDefinition;
    } | null>(null),
    [clone, setClone] = useState<{
      kind: keyof BulletCatalog;
      source: BulletDefinition;
      definition_key: string;
      name: string;
    } | null>(null);
  const load = useCallback(async () => {
    const [nextCatalog, nextSettings] = await Promise.all([
      api<BulletCatalog>("/bullethell/catalog"),
      api<Settings>(`/projects/${projectId}/bullethell`),
    ]);
    setCatalog(nextCatalog);
    setSettings(nextSettings);
  }, [projectId]);
  useEffect(() => {
    void load().catch((cause) => fail(String(cause)));
  }, [load, revision, fail]);
  const kind = (["attacks", "skills", "modes"] as const)[tab];
  function toggle(
    field: keyof Pick<
      Settings,
      "allowed_mode_ids" | "allowed_skill_ids" | "allowed_attack_ids"
    >,
    id: string,
  ) {
    setSettings((value) => {
      const removing = value[field].includes(id);
      const next = { ...value, [field]: removing ? value[field].filter((item) => item !== id) : [...value[field], id] };
      if (field === "allowed_mode_ids") {
        const enabledModes = next.allowed_mode_ids;
        if (!removing) {
          const movement = catalog.modes.find((mode) => mode.id === id)?.movement_skill_id;
          if (movement && !next.allowed_skill_ids.includes(movement)) next.allowed_skill_ids = [...next.allowed_skill_ids, movement];
        }
        if (!enabledModes.includes(next.default_mode_id)) next.default_mode_id = enabledModes[0] ?? "builtin:base";
      }
      return next;
    });
  }
  async function saveSettings() {
    try {
      await api(`/projects/${projectId}/bullethell`, {
        method: "PUT",
        body: JSON.stringify(settings),
      });
      await load();
    } catch (cause) {
      fail(String(cause));
    }
  }
  async function cloneDefinition() {
    if (!clone) return;
    try {
      await api(`/bullethell/${clone.kind}/${clone.source.id}/clone`, {
        method: "POST",
        body: JSON.stringify({
          definition_key: clone.definition_key,
          name: clone.name,
        }),
      });
      setClone(null);
      await load();
    } catch (cause) {
      fail(String(cause));
    }
  }
  async function saveDefinition(next?: {
    kind: keyof BulletCatalog;
    value: BulletDefinition;
  }) {
    const target = next ?? editing;
    if (!target) return;
    try {
      await api(`/bullethell/${target.kind}/${target.value.id}`, {
        method: "PUT",
        body: JSON.stringify(target.value),
      });
      setEditing(null);
      await load();
    } catch (cause) {
      fail(String(cause));
    }
  }
  const allowField =
    kind === "attacks"
      ? "allowed_attack_ids"
      : kind === "modes"
        ? "allowed_mode_ids"
        : "allowed_skill_ids";
  return (
    <Box className="studio minigames-studio">
      <Typography variant="h5">Bullet Hell</Typography>
      <Typography color="text.secondary">
        Shared definitions are globally reusable. Enable only the attacks,
        skills, and modes this story may use.
      </Typography>
      <Alert severity="info" sx={{ my: 2 }}>
        Built-ins are immutable. Clone a template to create an editable shared
        definition. Checkpoints retain snapshots of later edits.
      </Alert>
      <Tabs value={tab} onChange={(_, value) => setTab(value)}>
        <Tab label="Attacks" />
        <Tab label="Skills" />
        <Tab label="Modes" />
      </Tabs>
      <Stack spacing={1} sx={{ my: 2 }}>
        {catalog[kind].map((item) => (
          <Accordion key={item.id} disableGutters>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <FormControlLabel
                onClick={(event) => event.stopPropagation()}
                control={
                  <Checkbox
                    checked={settings[allowField].includes(item.id)}
                    onChange={() => toggle(allowField, item.id)}
                  />
                }
                label={item.name}
              />
              <Typography variant="caption" sx={{ ml: "auto", mr: 1 }}>
                {item.built_in ? "built-in" : `v${item.version}`}
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <pre className="bullet-definition-preview">
                {JSON.stringify(item, null, 2)}
              </pre>
              <Stack direction="row" spacing={1}>
                <Button
                  onClick={() =>
                    setClone({
                      kind,
                      source: item,
                      definition_key: `${item.definition_key}_copy`,
                      name: `${item.name} Copy`,
                    })
                  }
                >
                  Clone
                </Button>
                {!item.built_in && (
                  <>
                    <Button
                      onClick={() =>
                        setEditing({
                          kind,
                          value: {
                            ...item,
                            parameters_text: JSON.stringify(
                              item.parameters ?? {},
                              null,
                              2,
                            ),
                            phases_text: JSON.stringify(
                              item.phases ?? [],
                              null,
                              2,
                            ),
                            allowed_text: (item.allowed_skill_ids ?? []).join(
                              ", ",
                            ),
                            tags_text: (item.tags ?? []).join(", "),
                          },
                        })
                      }
                    >
                      Edit
                    </Button>
                    <Button
                      color="error"
                      onClick={async () => {
                        try {
                          await api(`/bullethell/${kind}/${item.id}`, {
                            method: "DELETE",
                          });
                          await load();
                        } catch (cause) {
                          fail(String(cause));
                        }
                      }}
                    >
                      Delete
                    </Button>
                  </>
                )}
              </Stack>
            </AccordionDetails>
          </Accordion>
        ))}
      </Stack>
      <TextField
        select
        label="Project fallback mode"
        value={settings.default_mode_id ?? ""}
        onChange={(event) =>
          setSettings({ ...settings, default_mode_id: event.target.value })
        }
        sx={{ minWidth: 260 }}
      >
        <MenuItem value="">Select enabled mode</MenuItem>
        {catalog.modes
          .filter((item) => settings.allowed_mode_ids.includes(item.id))
          .map((item) => (
            <MenuItem key={item.id} value={item.id}>
              {item.name}
            </MenuItem>
          ))}
      </TextField>
      <Button
        variant="contained"
        sx={{ ml: 2 }}
        onClick={() => void saveSettings()}
      >
        Save project allowlists
      </Button>
      <Dialog open={Boolean(clone)} onClose={() => setClone(null)}>
        <DialogTitle>Clone shared definition</DialogTitle>
        <DialogContent className="music-dialog">
          {clone && (
            <>
              <TextField
                label="Stable key"
                value={clone.definition_key}
                onChange={(event) =>
                  setClone({ ...clone, definition_key: event.target.value })
                }
              />
              <TextField
                label="Name"
                value={clone.name}
                onChange={(event) =>
                  setClone({ ...clone, name: event.target.value })
                }
              />
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setClone(null)}>Cancel</Button>
          <Button variant="contained" onClick={() => void cloneDefinition()}>
            Clone
          </Button>
        </DialogActions>
      </Dialog>
      <DefinitionDialog
        editing={editing}
        catalog={catalog}
        setEditing={setEditing}
        save={saveDefinition}
      />
    </Box>
  );
}

function DefinitionDialog({
  editing,
  catalog,
  setEditing,
  save,
}: {
  editing: { kind: keyof BulletCatalog; value: BulletDefinition } | null;
  catalog: BulletCatalog;
  setEditing: (value: any) => void;
  save: (value: {
    kind: keyof BulletCatalog;
    value: BulletDefinition;
  }) => Promise<void>;
}) {
  const value = editing?.value;
  function patch(next: Record<string, unknown>) {
    if (editing)
      setEditing({ ...editing, value: { ...editing.value, ...next } });
  }
  function prepare() {
    if (!editing || !value) return;
    try {
      const next = { ...value };
      if (editing.kind === "skills")
        next.parameters = JSON.parse(value.parameters_text);
      if (editing.kind === "modes") {
        next.parameters = JSON.parse(value.parameters_text);
        next.allowed_skill_ids = value.allowed_text
          .split(",")
          .map((item: string) => item.trim())
          .filter(Boolean);
      }
      if (editing.kind === "attacks") {
        next.phases = JSON.parse(value.phases_text);
        next.tags = value.tags_text
          .split(",")
          .map((item: string) => item.trim())
          .filter(Boolean);
      }
      void save({ ...editing, value: next });
    } catch {
      /* invalid JSON remains editable */
    }
  }
  return (
    <Dialog
      open={Boolean(editing)}
      onClose={() => setEditing(null)}
      maxWidth="md"
      fullWidth
    >
      <DialogTitle>Edit {editing?.kind.slice(0, -1)}</DialogTitle>
      <DialogContent className="music-dialog">
        {value && (
          <>
            <TextField
              label="Name"
              value={value.name}
              onChange={(event) => patch({ name: event.target.value })}
            />
            {editing?.kind === "skills" && (
              <>
                <TextField
                  select
                  label="Behavior"
                  value={value.behavior}
                  onChange={(event) => patch({ behavior: event.target.value })}
                >
                  {["free_move", "blue_gravity", "roll"].map((item) => (
                    <MenuItem key={item} value={item}>
                      {item.replaceAll("_", " ")}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  multiline
                  minRows={5}
                  label="Bounded parameters JSON"
                  value={value.parameters_text}
                  onChange={(event) =>
                    patch({ parameters_text: event.target.value })
                  }
                />
              </>
            )}
            {editing?.kind === "modes" && (
              <>
                <TextField
                  select
                  label="Movement skill"
                  value={value.movement_skill_id}
                  onChange={(event) =>
                    patch({ movement_skill_id: event.target.value })
                  }
                >
                  {catalog.skills
                    .filter((item) => item.behavior !== "roll")
                    .map((item) => (
                      <MenuItem key={item.id} value={item.id}>
                        {item.name}
                      </MenuItem>
                    ))}
                </TextField>
                <TextField
                  label="Allowed skill IDs"
                  value={value.allowed_text}
                  onChange={(event) =>
                    patch({ allowed_text: event.target.value })
                  }
                />
                <TextField
                  multiline
                  label="Parameters JSON"
                  value={value.parameters_text}
                  onChange={(event) =>
                    patch({ parameters_text: event.target.value })
                  }
                />
              </>
            )}
            {editing?.kind === "attacks" && (
              <>
                <TextField
                  multiline
                  label="AI description"
                  value={value.ai_description}
                  onChange={(event) =>
                    patch({ ai_description: event.target.value })
                  }
                />
                <TextField
                  label="Tags"
                  value={value.tags_text}
                  onChange={(event) => patch({ tags_text: event.target.value })}
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={Boolean(value.uses_enemy_forced_mode)}
                      onChange={(event) =>
                        patch({ uses_enemy_forced_mode: event.target.checked })
                      }
                    />
                  }
                  label="Apply enemy forced mode"
                />
                <TextField
                  type="number"
                  label="Hit immunity (ms)"
                  value={value.hit_immunity_ms}
                  onChange={(event) =>
                    patch({ hit_immunity_ms: Number(event.target.value) })
                  }
                />
                <TextField
                  multiline
                  minRows={10}
                  label="Composable phases JSON"
                  value={value.phases_text}
                  onChange={(event) =>
                    patch({ phases_text: event.target.value })
                  }
                />
              </>
            )}
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setEditing(null)}>Cancel</Button>
        <Button variant="contained" onClick={prepare}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
