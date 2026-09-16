import { useCallback, useEffect, useState } from "react";
import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Checkbox, Chip, FormControlLabel, MenuItem, OutlinedInput, Select, Stack, Switch, TextField, Tooltip, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { api } from "../api";
import type { MinigameConfig, WorldEntity } from "../types";

const actionOptions = ["story", "say", "do", "guide", "continue"];
const directionOptions = ["player_acts", "acted_on"];
const tagFields = ["required_actor_tags", "forbidden_actor_tags", "required_target_tags", "forbidden_target_tags", "required_location_tags", "forbidden_location_tags"] as const;

export function MinigamesStudio({ projectId, revision, fail }: { projectId: string; revision: number; fail: (message: string) => void }) {
  const [configs, setConfigs] = useState<MinigameConfig[]>([]);
  const [groups, setGroups] = useState<Array<{ key: string; name: string; game_keys: string[] }>>([]);
  const [activeGroup, setActiveGroup] = useState("all");
  const [hasPlayerCharacter, setHasPlayerCharacter] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const load = useCallback(async () => {
    const [games, entities, groupList] = await Promise.all([
      api<MinigameConfig[]>(`/projects/${projectId}/minigames`),
      api<WorldEntity[]>(`/projects/${projectId}/entities`),
      api<Array<{ key: string; name: string; game_keys: string[] }>>("/minigames/groups"),
    ]);
    setConfigs(games);
    setGroups(groupList);
    setHasPlayerCharacter(entities.some((entity) => entity.kind === "character" && Boolean(entity.state.player_controlled)));
  }, [projectId]);
  useEffect(() => { void load().catch((cause) => fail(String(cause))); }, [load, revision, fail]);
  function patch(key: string, values: Partial<MinigameConfig>) { setConfigs((rows) => rows.map((row) => row.game_key === key ? { ...row, ...values } : row)); }
  async function save(config: MinigameConfig) {
    const { manifest: _manifest, project_id: _project, game_key: _key, ...body } = config;
    setSavingKey(config.game_key);
    try { await api(`/projects/${projectId}/minigames/${config.game_key}`, { method: "PUT", body: JSON.stringify(body) }); await load(); }
    catch (cause) { fail(String(cause)); await load().catch(() => undefined); }
    finally { setSavingKey(null); }
  }
  function toggleEnabled(config: MinigameConfig, enabled: boolean) {
    const updated = { ...config, enabled };
    patch(config.game_key, { enabled });
    void save(updated);
  }
  async function toggleGroup(group: { key: string; game_keys: string[] }, enabled: boolean) {
    setSavingKey(`group:${group.key}`);
    try {
      setConfigs(await api(`/projects/${projectId}/minigame-groups/${group.key}`, { method: "PUT", body: JSON.stringify({ enabled }) }));
    } catch (cause) { fail(String(cause)); }
    finally { setSavingKey(null); }
  }
  return <Box className="studio minigames-studio"><Typography variant="h5">Minigames</Typography><Typography color="text.secondary">Only enabled and eligible challenges are shown to the storyteller. Players resolve challenges only when the story invokes one.</Typography>
    {!hasPlayerCharacter && <Alert severity="info" sx={{ mb: 2, maxWidth: 900 }}>No character is marked Player controlled, so eligible games use a generic Player participant. Marking a character as Player controlled makes the storyteller use that character and its context instead.</Alert>}
    <Stack direction="row" flexWrap="wrap" gap={1} sx={{ my: 2 }}><Button variant={activeGroup === "all" ? "contained" : "outlined"} onClick={() => setActiveGroup("all")}>All</Button>{groups.map((group) => { const members = configs.filter((config) => group.game_keys.includes(config.game_key)); const enabled = members.filter((config) => config.enabled).length; return <Stack key={group.key} direction="row" alignItems="center" className="minigame-group-control"><Button variant={activeGroup === group.key ? "contained" : "outlined"} onClick={() => setActiveGroup(group.key)}>{group.name} ({enabled}/{members.length})</Button><Tooltip title={enabled === members.length ? `Disable all ${group.name} games` : `Enable all ${group.name} games`}><Switch checked={Boolean(members.length) && enabled === members.length} disabled={savingKey === `group:${group.key}`} onChange={(event) => void toggleGroup(group, event.target.checked)} /></Tooltip></Stack>; })}</Stack>
    {configs.filter((config) => activeGroup === "all" || config.manifest.group === activeGroup).map((config) => <Accordion key={config.game_key} disableGutters><AccordionSummary expandIcon={<ExpandMoreIcon />}><Stack direction="row" alignItems="center" spacing={1} sx={{ width: "100%" }}><Typography sx={{ flex: 1 }}>{config.manifest.name}</Typography><Chip size="small" label={groups.find((group) => group.key === config.manifest.group)?.name ?? config.manifest.group} /><Chip size="small" label={`v${config.manifest.version}`} /><Tooltip title={config.enabled ? "Disable minigame" : "Enable minigame"}><Switch checked={config.enabled} disabled={savingKey === config.game_key} inputProps={{ "aria-label": `${config.enabled ? "Disable" : "Enable"} ${config.manifest.name}` }} onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()} onChange={(event) => toggleEnabled(config, event.target.checked)} /></Tooltip></Stack></AccordionSummary><AccordionDetails><Stack spacing={2}>
      <TextField label="Description shown to the storyteller" multiline minRows={2} value={config.ai_description} onChange={(event) => patch(config.game_key, { ai_description: event.target.value })} />
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}><TextField type="number" label="Minimum difficulty" value={config.min_difficulty} inputProps={{ min: config.manifest.min_difficulty, max: config.manifest.max_difficulty }} onChange={(event) => patch(config.game_key, { min_difficulty: Number(event.target.value) })} /><TextField type="number" label="Maximum difficulty" value={config.max_difficulty} inputProps={{ min: config.manifest.min_difficulty, max: config.manifest.max_difficulty }} onChange={(event) => patch(config.game_key, { max_difficulty: Number(event.target.value) })} /></Stack>
      {["lockpicking", "hex_circuit", "circled_teeth"].includes(config.game_key) && <TextField select label="Timer policy" value={config.timer_policy} onChange={(event) => patch(config.game_key, { timer_policy: event.target.value as MinigameConfig["timer_policy"] })}><MenuItem value="never">{config.game_key === "circled_teeth" ? "Never timed unless the AI supplies a time override" : "Never timed"}</MenuItem><MenuItem value="ai_allowed">AI chooses from scene pressure</MenuItem><MenuItem value="always">Always timed</MenuItem></TextField>}
      {config.game_key === "lockpicking" && <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems="center"><TextField type="number" label="Default attempts without inventory" value={config.fallback_attempts} inputProps={{ min: 1, max: 10 }} onChange={(event) => patch(config.game_key, { fallback_attempts: Number(event.target.value) })} /><FormControlLabel control={<Switch checked={config.allow_infinite_attempts} onChange={(event) => patch(config.game_key, { allow_infinite_attempts: event.target.checked })} />} label="Allow AI to grant infinite picks" /></Stack>}
      {config.game_key === "circled_teeth" && <Stack spacing={2}>
        <Alert severity="info">Difficulty supplies balanced defaults. Enabled overrides are optional for the storyteller. Teeth plus empty slots must produce 4–24 total slots.</Alert>
        <FormControlLabel control={<Switch checked={config.allow_teeth_override} onChange={(event) => patch(config.game_key, { allow_teeth_override: event.target.checked })} />} label="Allow AI tooth-count override" />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}><TextField type="number" label="Minimum teeth" value={config.min_teeth} inputProps={{ min: 2, max: 23 }} onChange={(event) => patch(config.game_key, { min_teeth: Number(event.target.value) })} /><TextField type="number" label="Maximum teeth" value={config.max_teeth} inputProps={{ min: 2, max: 23 }} onChange={(event) => patch(config.game_key, { max_teeth: Number(event.target.value) })} /></Stack>
        <FormControlLabel control={<Switch checked={config.allow_empty_slots_override} onChange={(event) => patch(config.game_key, { allow_empty_slots_override: event.target.checked })} />} label="Allow AI empty-slot override" />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}><TextField type="number" label="Minimum empty slots" value={config.min_empty_slots} inputProps={{ min: 1, max: 22 }} onChange={(event) => patch(config.game_key, { min_empty_slots: Number(event.target.value) })} /><TextField type="number" label="Maximum empty slots" value={config.max_empty_slots} inputProps={{ min: 1, max: 22 }} onChange={(event) => patch(config.game_key, { max_empty_slots: Number(event.target.value) })} /></Stack>
        <FormControlLabel control={<Switch checked={config.allow_time_override} onChange={(event) => patch(config.game_key, { allow_time_override: event.target.checked })} />} label="Allow AI time override" />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}><TextField type="number" label="Minimum seconds" value={config.min_time_seconds} inputProps={{ min: 1, max: 3600 }} onChange={(event) => patch(config.game_key, { min_time_seconds: Number(event.target.value) })} /><TextField type="number" label="Maximum seconds" value={config.max_time_seconds} inputProps={{ min: 1, max: 3600 }} onChange={(event) => patch(config.game_key, { max_time_seconds: Number(event.target.value) })} /></Stack>
        <FormControlLabel control={<Switch checked={config.allow_direction_reversal} onChange={(event) => patch(config.game_key, { allow_direction_reversal: event.target.checked })} />} label="Allow AI to reverse direction after successful presses" />
        <Typography variant="caption" color="text.secondary">Defaults: difficulty 1 uses 4 teeth, 4 empty slots, 45 seconds, and a 2.8 s revolution; difficulty 10 uses 10 teeth, 4 empty slots, 18 seconds, and a 1.2 s revolution.</Typography>
      </Stack>}
      {config.game_key === "timed_attack" && <Stack spacing={2}>
        <Alert severity="info">Owned ability profiles override these AI fallback ranges. Every resolved volley keeps its original values.</Alert>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}><TextField type="number" label="Minimum attack lines" value={config.min_attack_lines} inputProps={{ min: 1, max: 8 }} onChange={(event) => patch(config.game_key, { min_attack_lines: Number(event.target.value) })} /><TextField type="number" label="Maximum attack lines" value={config.max_attack_lines} inputProps={{ min: 1, max: 8 }} onChange={(event) => patch(config.game_key, { max_attack_lines: Number(event.target.value) })} /></Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}><TextField type="number" label="Minimum damage per line" value={config.min_attack_damage} inputProps={{ min: 0 }} onChange={(event) => patch(config.game_key, { min_attack_damage: Number(event.target.value) })} /><TextField type="number" label="Maximum damage per line" value={config.max_attack_damage} inputProps={{ min: 0 }} onChange={(event) => patch(config.game_key, { max_attack_damage: Number(event.target.value) })} /></Stack>
      </Stack>}
      {config.game_key === "dodge_box" && <Stack spacing={2}>
        <Alert severity="info">Dodge Box uses enabled Bullet Hell attacks, modes, skills, canonical HP, and deterministic server-validated collisions.</Alert>
        <TextField select label="Control mode" value={config.dodge_control_mode} onChange={(event) => patch(config.game_key, { dodge_control_mode: event.target.value as MinigameConfig["dodge_control_mode"] })}><MenuItem value="pointer">Easy · mouse and touch</MenuItem><MenuItem value="keyboard">Hard · WASD and arrow keys</MenuItem></TextField>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}><TextField type="number" label="Minimum fallback HP" value={config.min_fallback_hp} inputProps={{ min: 1 }} onChange={(event) => patch(config.game_key, { min_fallback_hp: Number(event.target.value) })} /><TextField type="number" label="Maximum fallback HP" value={config.max_fallback_hp} inputProps={{ min: 1 }} onChange={(event) => patch(config.game_key, { max_fallback_hp: Number(event.target.value) })} /></Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}><TextField type="number" label="Minimum fallback enemy attack" value={config.min_enemy_attack} inputProps={{ min: 0 }} onChange={(event) => patch(config.game_key, { min_enemy_attack: Number(event.target.value) })} /><TextField type="number" label="Maximum fallback enemy attack" value={config.max_enemy_attack} inputProps={{ min: 0 }} onChange={(event) => patch(config.game_key, { max_enemy_attack: Number(event.target.value) })} /></Stack>
      </Stack>}
      <Select multiple value={config.allowed_directions} input={<OutlinedInput />} renderValue={(selected) => selected.map((value) => value.replaceAll("_", " ")).join(", ")} onChange={(event) => patch(config.game_key, { allowed_directions: event.target.value as MinigameConfig["allowed_directions"] })}>{directionOptions.map((value) => <MenuItem key={value} value={value}><Checkbox checked={config.allowed_directions.includes(value as never)} />{value.replaceAll("_", " ")}</MenuItem>)}</Select>
      <Select multiple value={config.allowed_actions} input={<OutlinedInput />} renderValue={(selected) => `Preferred actions: ${selected.join(", ")}`} onChange={(event) => patch(config.game_key, { allowed_actions: event.target.value as MinigameConfig["allowed_actions"] })}>{actionOptions.map((value) => <MenuItem key={value} value={value}><Checkbox checked={config.allowed_actions.includes(value as never)} />Prefer for {value}</MenuItem>)}</Select>
      {tagFields.map((field) => <TextField key={field} label={field.replaceAll("_", " ")} value={config[field].join(", ")} helperText="Comma-separated; required tags must all match and forbidden tags reject a challenge." onChange={(event) => patch(config.game_key, { [field]: event.target.value.split(",").map((tag) => tag.trim()).filter(Boolean) })} />)}
      <Box><Button variant="contained" disabled={savingKey === config.game_key} onClick={() => void save(config)}>{savingKey === config.game_key ? "Saving…" : `Save ${config.manifest.name}`}</Button></Box>
    </Stack></AccordionDetails></Accordion>)}
  </Box>;
}
