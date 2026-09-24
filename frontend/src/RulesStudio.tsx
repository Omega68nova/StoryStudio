import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, Switch, TextField } from "@mui/material";
import { api } from "./api";
import type { AbilityAction, AbilityCost, AbilityDefinition, EffectDefinition, FormulaNode, RequirementExpression, RuleMigrationWarning, RuleOwnerKind, StatDefinition, WorldProjection } from "./types";
import type { BulletCatalog } from "./BulletHellStudio";

const ownerKinds: RuleOwnerKind[] = ["character", "item", "location", "faction", "lore_system", "fact", "plot_beat", "relationship"];
const blankStat: StatDefinition = { stat_key: "", label: "", description: "", compatible_owner_kinds: ["character"], default_value: 0, minimum: 0, maximum: 100, minimum_stat_key: null, maximum_stat_key: null, color: null, minimum_color: null, maximum_color: null, display_style: "compact", integer_only: true, visibility: "public" };
const blankEffect: EffectDefinition = { effect_key: "", name: "", description: "", target_stat_key: "", operation: "add", formula: { kind: "constant", value: 0 }, clock: "world_actions", duration: 0, tick_interval: 0, evaluation_mode: "snapshot", stacking_policy: "replace", max_stacks: 1, visibility: "public", icon: null, enabled: true };
const blankAbility: AbilityDefinition = { ability_key: "", name: "", description: "", ability_kind: "active", compatible_owner_kinds: ["character"], target_type: "self", requirements: {}, costs: [], actions: [], passive_triggers: [], icon: null, enabled: true, timed_attack_line_count: null, timed_attack_damage_per_line: null, bullethell_skill_ids: [] };

function FormulaEditor({ node, stats, onChange }: { node: FormulaNode; stats: StatDefinition[]; onChange: (next: FormulaNode) => void }) {
  function changeKind(kind: FormulaNode["kind"]) {
    if (kind === "constant") onChange({ kind, value: 0 });
    else if (kind === "stat") onChange({ kind, participant: "source", stat_key: stats[0]?.stat_key ?? "" });
    else if (kind === "negate") onChange({ kind, children: [{ kind: "constant", value: 0 }] });
    else onChange({ kind, children: [{ kind: "constant", value: 0 }, { kind: "constant", value: 0 }] } as FormulaNode);
  }
  return <Stack spacing={1} sx={{ borderLeft: "2px solid", borderColor: "divider", pl: 1 }}>
    <TextField select size="small" label="Expression" value={node.kind} onChange={event => changeKind(event.target.value as FormulaNode["kind"])}>{["constant", "stat", "add", "subtract", "multiply", "divide", "minimum", "maximum", "negate"].map(kind => <MenuItem key={kind} value={kind}>{kind}</MenuItem>)}</TextField>
    {node.kind === "constant" && <TextField size="small" type="number" label="Value" value={node.value} onChange={event => onChange({ ...node, value: Number(event.target.value) })} />}
    {node.kind === "stat" && <Stack direction="row" spacing={1}><TextField select size="small" label="Participant" value={node.participant} onChange={event => onChange({ ...node, participant: event.target.value as "actor" | "source" | "target" })}>{["actor", "source", "target"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField><TextField select size="small" fullWidth label="Stat" value={node.stat_key} onChange={event => onChange({ ...node, stat_key: event.target.value })}>{stats.map(stat => <MenuItem key={stat.stat_key} value={stat.stat_key}>{stat.label}</MenuItem>)}</TextField></Stack>}
    {"children" in node && node.children.map((child, index) => <FormulaEditor key={index} node={child} stats={stats} onChange={next => onChange({ ...node, children: node.children.map((item, childIndex) => childIndex === index ? next : item) } as FormulaNode)} />)}
  </Stack>;
}


function EffectExampleCalculator({ effect }: { effect: EffectDefinition }) {
  const refs = useMemo(() => {
    const found: string[] = [];
    const visit = (node: FormulaNode) => {
      if (node.kind === "stat") found.push(`${node.participant}.${node.stat_key}`);
      if ("children" in node) node.children.forEach(visit);
    };
    visit(effect.formula);
    return [...new Set(found)];
  }, [effect.formula]);
  const [values, setValues] = useState<Record<string, number>>({});
  const evaluate = (node: FormulaNode): number => {
    if (node.kind === "constant") return node.value;
    if (node.kind === "stat") return Number(values[`${node.participant}.${node.stat_key}`] ?? 0);
    if (node.kind === "negate") return -evaluate(node.children[0]);
    const left = evaluate(node.children[0]);
    const right = evaluate(node.children[1]);
    if (node.kind === "add") return left + right;
    if (node.kind === "subtract") return left - right;
    if (node.kind === "multiply") return left * right;
    if (node.kind === "divide") {
      if (right === 0) throw new Error("division by zero");
      return left / right;
    }
    if (node.kind === "minimum") return Math.min(left, right);
    return Math.max(left, right);
  };
  let result: string;
  try {
    const value = evaluate(effect.formula);
    result = Number.isFinite(value) ? String(value) : "invalid";
  } catch (cause) {
    result = cause instanceof Error ? cause.message : "invalid";
  }
  return <Stack spacing={1} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1, p: 1 }}>
    <strong>Example calculator</strong>
    <Stack direction="row" spacing={1} flexWrap="wrap">
      {refs.map(ref => <TextField key={ref} size="small" type="number" label={ref} value={values[ref] ?? 0} onChange={event => setValues(current => ({ ...current, [ref]: Number(event.target.value) }))} />)}
      {refs.length === 0 && <small>This formula uses constants only.</small>}
    </Stack>
    <small>Resolved magnitude: <b>{result}</b></small>
  </Stack>;
}

export function RulesStudio({ projectId, revision, fail }: { projectId: string; revision: number; fail: (message: string) => void }) {
  const [rules, setRules] = useState<{ stats: StatDefinition[]; effects: EffectDefinition[]; abilities: AbilityDefinition[]; migration_warnings: RuleMigrationWarning[] }>({ stats: [], effects: [], abilities: [], migration_warnings: [] });
  const [stat, setStat] = useState<StatDefinition | null>(null);
  const [effect, setEffect] = useState<EffectDefinition | null>(null);
  const [ability, setAbility] = useState<AbilityDefinition | null>(null);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [bulletSkills, setBulletSkills] = useState<Array<{ id: string; name: string }>>([]);
  const [world, setWorld] = useState<WorldProjection | null>(null);
  const load = useCallback(async () => {
    const [next, catalog, settings, nextWorld] = await Promise.all([
      api<typeof rules>(`/projects/${projectId}/rules`),
      api<BulletCatalog>("/bullethell/catalog"),
      api<{ allowed_skill_ids: string[] }>(`/projects/${projectId}/bullethell`),
      api<WorldProjection>(`/projects/${projectId}/world`),
    ]);
    setRules(next);
    setWorld(nextWorld);
    setBulletSkills(catalog.skills.filter(item => settings.allowed_skill_ids.includes(item.id)));
  }, [projectId]);
  useEffect(() => { void load().catch(cause => fail(String(cause))); }, [load, revision, fail]);

  async function save(kind: "stats" | "effects" | "abilities", value: StatDefinition | EffectDefinition | AbilityDefinition) {
    try {
      await api(`/projects/${projectId}/${kind}${editingKey ? `/${editingKey}` : ""}`, { method: editingKey ? "PUT" : "POST", body: JSON.stringify(value) });
      setStat(null); setEffect(null); setAbility(null); setEditingKey(null); await load();
    } catch (cause) { fail(String(cause)); }
  }
  async function remove(kind: "stats" | "effects" | "abilities", key: string) { try { await api(`/projects/${projectId}/${kind}/${key}`, { method: "DELETE" }); await load(); } catch (cause) { fail(String(cause)); } }
  const compatibleBounds = useMemo(() => stat ? rules.stats.filter(item => item.stat_key !== stat.stat_key && item.compatible_owner_kinds.some(kind => stat.compatible_owner_kinds.includes(kind))) : [], [rules.stats, stat]);

  return <div className="page">
    <header className="page-header"><p className="eyebrow">CANONICAL RULES</p><h1>Stats, effects, and abilities</h1><p>Reusable effects calculate against actor, source, and target stats; abilities compose those effects with typed actions.</p></header>
    {rules.migration_warnings.filter(item => !item.acknowledged).map(item => <Alert key={item.id} severity="warning" action={<Button onClick={async () => { await api(`/projects/${projectId}/rules/migration-warnings/${item.id}/acknowledge`, { method: "POST" }); await load(); }}>Acknowledge</Button>}>{item.message}</Alert>)}
    <div className="rules-grid">
      <RuleList title="Stats" add={() => { setEditingKey(null); setStat({ ...blankStat }); }} rows={rules.stats.map(item => ({ key: item.stat_key, title: item.label, subtitle: `${item.stat_key} · ${item.compatible_owner_kinds.join(", ")}`, edit: () => { setEditingKey(item.stat_key); setStat({ ...item }); }, remove: () => void remove("stats", item.stat_key) }))} />
      <RuleList title="Effects" add={() => { setEditingKey(null); setEffect({ ...blankEffect, target_stat_key: rules.stats[0]?.stat_key ?? "" }); }} rows={rules.effects.map(item => ({ key: item.effect_key, title: item.name, subtitle: `${item.operation} ${item.target_stat_key} · ${item.clock}`, edit: () => { setEditingKey(item.effect_key); setEffect(structuredClone(item)); }, remove: () => void remove("effects", item.effect_key) }))} />
      <RuleList title="Abilities" add={() => { setEditingKey(null); setAbility(structuredClone(blankAbility)); }} rows={rules.abilities.map(item => ({ key: item.ability_key, title: item.name, subtitle: `${item.ability_kind} · ${item.target_type} · ${item.actions.length} action(s)`, edit: () => { setEditingKey(item.ability_key); setAbility(structuredClone(item)); }, remove: () => void remove("abilities", item.ability_key) }))} />
    </div>

    <Dialog open={Boolean(stat)} onClose={() => setStat(null)} maxWidth="md" fullWidth><DialogTitle>{editingKey ? "Edit" : "Add"} stat</DialogTitle><DialogContent className="music-dialog">{stat && <>
      <TextField label="Stable key" disabled={Boolean(editingKey)} value={stat.stat_key} onChange={e => setStat({ ...stat, stat_key: e.target.value })}/><TextField label="Label" value={stat.label} onChange={e => setStat({ ...stat, label: e.target.value })}/><TextField multiline label="Description" value={stat.description} onChange={e => setStat({ ...stat, description: e.target.value })}/>
      <Stack direction="row" flexWrap="wrap">{ownerKinds.map(kind => <FormControlLabel key={kind} control={<Checkbox checked={stat.compatible_owner_kinds.includes(kind)} onChange={e => setStat({ ...stat, compatible_owner_kinds: e.target.checked ? [...stat.compatible_owner_kinds, kind] : stat.compatible_owner_kinds.filter(value => value !== kind) })}/>} label={kind.replaceAll("_", " ")}/>)}</Stack>
      <Stack direction="row" spacing={1}><TextField type="number" label="Default" value={stat.default_value} onChange={e => setStat({ ...stat, default_value: Number(e.target.value) })}/><TextField type="number" label="Minimum" value={stat.minimum} onChange={e => setStat({ ...stat, minimum: Number(e.target.value) })}/><TextField type="number" label="Maximum" value={stat.maximum} onChange={e => setStat({ ...stat, maximum: Number(e.target.value) })}/></Stack>
      <Stack direction="row" spacing={1}><TextField select fullWidth label="Minimum from stat" value={stat.minimum_stat_key ?? ""} onChange={e => setStat({ ...stat, minimum_stat_key: e.target.value || null })}><MenuItem value="">Numeric minimum</MenuItem>{compatibleBounds.map(item => <MenuItem key={item.stat_key} value={item.stat_key}>{item.label}</MenuItem>)}</TextField><TextField select fullWidth label="Maximum from stat" value={stat.maximum_stat_key ?? ""} onChange={e => setStat({ ...stat, maximum_stat_key: e.target.value || null })}><MenuItem value="">Numeric maximum</MenuItem>{compatibleBounds.map(item => <MenuItem key={item.stat_key} value={item.stat_key}>{item.label}</MenuItem>)}</TextField></Stack>
      <Stack direction="row" spacing={1}><TextField select label="Display" value={stat.display_style} onChange={e => setStat({ ...stat, display_style: e.target.value as "compact" | "bar" })}><MenuItem value="compact">Compact</MenuItem><MenuItem value="bar">Bar</MenuItem></TextField><TextField select label="Visibility" value={stat.visibility} onChange={e => setStat({ ...stat, visibility: e.target.value as StatDefinition["visibility"] })}>{["public", "private", "narrator"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField><FormControlLabel control={<Switch checked={stat.integer_only} onChange={e => setStat({ ...stat, integer_only: e.target.checked })}/>} label="Integer only"/></Stack>
      <Stack direction="row" spacing={1}><TextField label="Color" value={stat.color ?? ""} onChange={e => setStat({ ...stat, color: e.target.value || null })}/><TextField label="Minimum color" value={stat.minimum_color ?? ""} onChange={e => setStat({ ...stat, minimum_color: e.target.value || null })}/><TextField label="Maximum color" value={stat.maximum_color ?? ""} onChange={e => setStat({ ...stat, maximum_color: e.target.value || null })}/></Stack>
    </>}</DialogContent><DialogActions><Button onClick={() => setStat(null)}>Cancel</Button><Button variant="contained" onClick={() => stat && void save("stats", stat)}>Save</Button></DialogActions></Dialog>

    <Dialog open={Boolean(effect)} onClose={() => setEffect(null)} maxWidth="md" fullWidth><DialogTitle>{editingKey ? "Edit" : "Add"} effect</DialogTitle><DialogContent className="music-dialog">{effect && <>
      <TextField label="Stable key" disabled={Boolean(editingKey)} value={effect.effect_key} onChange={e => setEffect({ ...effect, effect_key: e.target.value })}/><TextField label="Name" value={effect.name} onChange={e => setEffect({ ...effect, name: e.target.value })}/><TextField multiline label="Description" value={effect.description} onChange={e => setEffect({ ...effect, description: e.target.value })}/>
      <Stack direction="row" spacing={1}><TextField select fullWidth label="Target stat" value={effect.target_stat_key} onChange={e => setEffect({ ...effect, target_stat_key: e.target.value })}>{rules.stats.map(item => <MenuItem key={item.stat_key} value={item.stat_key}>{item.label}</MenuItem>)}</TextField><TextField select label="Operation" value={effect.operation} onChange={e => setEffect({ ...effect, operation: e.target.value as EffectDefinition["operation"] })}>{["add", "subtract", "set", "multiply"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField></Stack>
      <FormulaEditor node={effect.formula} stats={rules.stats} onChange={formula => setEffect({ ...effect, formula })}/>
      <EffectExampleCalculator effect={effect}/>
      <Stack direction="row" spacing={1}><TextField select label="Clock" value={effect.clock} onChange={e => setEffect({ ...effect, clock: e.target.value as EffectDefinition["clock"] })}>{["story_minutes", "target_actions", "world_actions"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField><TextField type="number" label="Duration (-1 indefinite)" value={effect.duration} onChange={e => setEffect({ ...effect, duration: Number(e.target.value) })}/><TextField type="number" label="Tick interval" value={effect.tick_interval} onChange={e => setEffect({ ...effect, tick_interval: Number(e.target.value) })}/></Stack>
      <Stack direction="row" spacing={1}><TextField select label="Evaluation" value={effect.evaluation_mode} onChange={e => setEffect({ ...effect, evaluation_mode: e.target.value as EffectDefinition["evaluation_mode"] })}><MenuItem value="snapshot">Snapshot</MenuItem><MenuItem value="live">Live</MenuItem></TextField><TextField select label="Stacking" value={effect.stacking_policy} onChange={e => setEffect({ ...effect, stacking_policy: e.target.value as EffectDefinition["stacking_policy"] })}>{["replace", "refresh", "stack", "independent"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField><TextField type="number" label="Max stacks" value={effect.max_stacks} onChange={e => setEffect({ ...effect, max_stacks: Number(e.target.value) })}/></Stack>
      <Stack direction="row" spacing={1}><TextField select label="Visibility" value={effect.visibility} onChange={e => setEffect({ ...effect, visibility: e.target.value as EffectDefinition["visibility"] })}>{["public", "private", "narrator"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField><TextField label="Semantic icon" value={effect.icon ?? ""} onChange={e => setEffect({ ...effect, icon: e.target.value || null })}/><FormControlLabel control={<Switch checked={effect.enabled} onChange={e => setEffect({ ...effect, enabled: e.target.checked })}/>} label="Enabled"/></Stack>
    </>}</DialogContent><DialogActions><Button onClick={() => setEffect(null)}>Cancel</Button><Button variant="contained" onClick={() => effect && void save("effects", effect)}>Save</Button></DialogActions></Dialog>
    <AbilityDialog ability={ability} editing={Boolean(editingKey)} stats={rules.stats} effects={rules.effects} abilities={rules.abilities} world={world} bulletSkills={bulletSkills} setAbility={setAbility} close={() => setAbility(null)} save={() => ability && void save("abilities", ability)} />
  </div>;
}

function RuleList({ title, add, rows }: { title: string; add: () => void; rows: Array<{ key: string; title: string; subtitle: string; edit: () => void; remove: () => void }> }) { return <section className="panel"><Stack direction="row" justifyContent="space-between"><h2>{title}</h2><Button onClick={add}>Add</Button></Stack>{rows.map(row => <article className="rule-row" key={row.key}><div><strong>{row.title}</strong><small>{row.subtitle}</small></div><div><Button onClick={row.edit}>Edit</Button><Button color="error" onClick={row.remove}>Delete</Button></div></article>)}</section>; }

function RequirementEditor({
  node,
  stats,
  items,
  locations,
  abilities,
  onChange,
  depth = 0,
}: {
  node: RequirementExpression;
  stats: StatDefinition[];
  items: Array<{ id: string; name: string }>;
  locations: Array<{ id: string; name: string }>;
  abilities: AbilityDefinition[];
  onChange: (value: RequirementExpression) => void;
  depth?: number;
}) {
  const kind = node.kind ?? "compare";
  const changeKind = (next: NonNullable<RequirementExpression["kind"]>) => {
    if (next === "and" || next === "or") onChange({ kind: next, children: [{ kind: "compare", target: "actor", stat_key: stats[0]?.stat_key ?? "", comparison: "gte", value: 0 }] });
    else if (next === "not") onChange({ kind: next, child: { kind: "compare", target: "actor", stat_key: stats[0]?.stat_key ?? "", comparison: "gte", value: 0 } });
    else if (next === "compare") onChange({ kind: next, target: "actor", stat_key: stats[0]?.stat_key ?? "", comparison: "gte", value: 0 });
    else if (next === "has_item") onChange({ kind: next, target: "actor", item_id: items[0]?.id ?? "" });
    else if (next === "has_tag") onChange({ kind: next, target: "actor", tag: "" });
    else if (next === "location") onChange({ kind: next, target: "actor", location_id: locations[0]?.id ?? "" });
    else if (next === "has_ability") onChange({ kind: next, target: "actor", ability_key: abilities[0]?.ability_key ?? "" });
    else if (next === "relationship") onChange({ kind: next, target: "actor", relation: "" });
    else if (next === "time") onChange({ kind: next, target: "actor", time_phase_id: "" });
    else onChange({ kind: next, target: "actor", weather_id: "" });
  };
  const targetField = !["and", "or", "not"].includes(kind) && <TextField
    select
    size="small"
    label="Participant"
    value={node.target ?? "actor"}
    onChange={event => onChange({ ...node, target: event.target.value as RequirementExpression["target"] })}
    sx={{ minWidth: 130 }}
  >
    {["actor", "target", "party", "location", "relationship_target"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
  </TextField>;
  return <Stack spacing={1} sx={{ borderLeft: depth ? "2px solid" : undefined, borderColor: "divider", pl: depth ? 1 : 0 }}>
    <Stack direction="row" spacing={1} alignItems="center">
      <TextField select size="small" label="Requirement" value={kind} onChange={event => changeKind(event.target.value as NonNullable<RequirementExpression["kind"]>)} sx={{ minWidth: 150 }}>
        {["and", "or", "not", "compare", "has_item", "has_tag", "relationship", "location", "time", "weather", "has_ability"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
      </TextField>
      {targetField}
      {kind === "compare" && <>
        <TextField select size="small" label="Stat" value={node.stat_key ?? ""} onChange={event => onChange({ ...node, stat_key: event.target.value })} sx={{ minWidth: 150 }}>
          {stats.map(item => <MenuItem key={item.stat_key} value={item.stat_key}>{item.label}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Comparison" value={node.comparison ?? "gte"} onChange={event => onChange({ ...node, comparison: event.target.value as RequirementExpression["comparison"] })}>
          {["eq", "ne", "lt", "lte", "gt", "gte"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
        </TextField>
        <TextField size="small" type="number" label="Value" value={typeof node.value === "number" ? node.value : 0} onChange={event => onChange({ ...node, value: Number(event.target.value) })} />
      </>}
      {kind === "has_item" && <TextField select size="small" label="Item" value={node.item_id ?? ""} onChange={event => onChange({ ...node, item_id: event.target.value })} sx={{ minWidth: 180 }}>
        {items.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
      </TextField>}
      {kind === "has_tag" && <TextField size="small" label="Tag" value={node.tag ?? ""} onChange={event => onChange({ ...node, tag: event.target.value })} />}
      {kind === "relationship" && <TextField size="small" label="Relationship" value={node.relation ?? ""} onChange={event => onChange({ ...node, relation: event.target.value })} />}
      {kind === "location" && <TextField select size="small" label="Location" value={node.location_id ?? ""} onChange={event => onChange({ ...node, location_id: event.target.value })} sx={{ minWidth: 180 }}>
        {locations.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
      </TextField>}
      {kind === "time" && <TextField size="small" label="Time phase ID" value={node.time_phase_id ?? ""} onChange={event => onChange({ ...node, time_phase_id: event.target.value })} />}
      {kind === "weather" && <TextField size="small" label="Weather ID" value={node.weather_id ?? ""} onChange={event => onChange({ ...node, weather_id: event.target.value })} />}
      {kind === "has_ability" && <TextField select size="small" label="Ability" value={node.ability_key ?? ""} onChange={event => onChange({ ...node, ability_key: event.target.value })} sx={{ minWidth: 180 }}>
        {abilities.map(item => <MenuItem key={item.ability_key} value={item.ability_key}>{item.name}</MenuItem>)}
      </TextField>}
    </Stack>
    {(kind === "and" || kind === "or") && <>
      {(node.children ?? []).map((child, index) => <Stack key={index} direction="row" spacing={1} alignItems="flex-start">
        <div style={{ flex: 1 }}><RequirementEditor node={child} stats={stats} items={items} locations={locations} abilities={abilities} depth={depth + 1} onChange={next => onChange({ ...node, children: (node.children ?? []).map((item, childIndex) => childIndex === index ? next : item) })} /></div>
        <Button onClick={() => onChange({ ...node, children: (node.children ?? []).filter((_, childIndex) => childIndex !== index) })}>Remove</Button>
      </Stack>)}
      <Button onClick={() => onChange({ ...node, children: [...(node.children ?? []), { kind: "compare", target: "actor", stat_key: stats[0]?.stat_key ?? "", comparison: "gte", value: 0 }] })}>Add child</Button>
    </>}
    {kind === "not" && <RequirementEditor node={node.child ?? { kind: "compare", target: "actor", stat_key: stats[0]?.stat_key ?? "", comparison: "gte", value: 0 }} stats={stats} items={items} locations={locations} abilities={abilities} depth={depth + 1} onChange={child => onChange({ ...node, child })} />}
  </Stack>;
}

function AbilityDialog({
  ability,
  editing,
  stats,
  effects,
  abilities,
  world,
  bulletSkills,
  setAbility,
  close,
  save,
}: {
  ability: AbilityDefinition | null;
  editing: boolean;
  stats: StatDefinition[];
  effects: EffectDefinition[];
  abilities: AbilityDefinition[];
  world: WorldProjection | null;
  bulletSkills: Array<{ id: string; name: string }>;
  setAbility: (value: AbilityDefinition) => void;
  close: () => void;
  save: () => void;
}) {
  if (!ability) return null;
  const entities = Object.values(world?.entities ?? {}).filter(item => !item.state.archived);
  const items = entities.filter(item => item.kind === "item").map(item => ({ id: item.id, name: item.name }));
  const locations = entities.filter(item => item.kind === "location").map(item => ({ id: item.id, name: item.name }));
  const facts = entities.filter(item => item.kind === "fact").map(item => ({ id: item.id, name: item.name }));
  const characterStats = stats.filter(item => item.compatible_owner_kinds.includes("character"));
  const targetOwner: RuleOwnerKind | null = ability.target_type === "relationship" ? "relationship" : ability.target_type === "location" ? "location" : ["self", "character", "party", "allies", "enemies", "nearby_enemies", "faction_members"].includes(ability.target_type) ? "character" : null;
  const compatibleEffects = targetOwner ? effects.filter(item => stats.find(stat => stat.stat_key === item.target_stat_key)?.compatible_owner_kinds.includes(targetOwner)) : effects;
  const updateCost = (index: number, patch: Partial<AbilityCost>) => setAbility({ ...ability, costs: ability.costs.map((item, i) => i === index ? { ...item, ...patch } : item) });
  const updateAction = (index: number, patch: Partial<AbilityAction>) => setAbility({ ...ability, actions: ability.actions.map((item, i) => i === index ? { ...item, ...patch } : item) });
  const replaceAction = (index: number, kind: AbilityAction["kind"]) => {
    const next: AbilityAction = { kind, target: "target" };
    if (kind === "apply_effect") next.effect_key = compatibleEffects[0]?.effect_key ?? "";
    if (kind === "move") next.destination_id = locations[0]?.id ?? "";
    if (kind === "create") { next.entity_kind = "item"; next.entity_name = ""; next.state = {}; }
    if (kind === "reveal_knowledge") next.fact_id = facts[0]?.id ?? "";
    if (kind === "change_relationship") next.relation = "";
    if (kind === "advance_time") next.minutes = 0;
    if (kind === "play_noise") next.noise_id = "";
    setAbility({ ...ability, actions: ability.actions.map((item, i) => i === index ? next : item) });
  };
  const moveAction = (index: number, delta: number) => {
    const next = [...ability.actions];
    const targetIndex = index + delta;
    if (targetIndex < 0 || targetIndex >= next.length) return;
    [next[index], next[targetIndex]] = [next[targetIndex], next[index]];
    setAbility({ ...ability, actions: next });
  };
  const requirements = ability.requirements?.kind ? ability.requirements : null;
  return <Dialog open onClose={close} maxWidth="lg" fullWidth><DialogTitle>{editing ? "Edit" : "Add"} ability</DialogTitle><DialogContent className="music-dialog">
    <TextField label="Stable key" disabled={editing} value={ability.ability_key} onChange={e => setAbility({ ...ability, ability_key: e.target.value })}/>
    <TextField label="Name" value={ability.name} onChange={e => setAbility({ ...ability, name: e.target.value })}/>
    <TextField multiline label="Description" value={ability.description} onChange={e => setAbility({ ...ability, description: e.target.value })}/>
    <TextField label="Semantic icon" value={ability.icon ?? ""} onChange={e => setAbility({ ...ability, icon: e.target.value || null })} helperText="Short semantic glyph/name used by the UI; this is not image media." />
    <Stack direction="row" spacing={1} flexWrap="wrap">
      <TextField select label="Kind" value={ability.ability_kind} onChange={e => setAbility({ ...ability, ability_kind: e.target.value as "active" | "passive", passive_triggers: e.target.value === "passive" && ability.passive_triggers.length === 0 ? [{ kind: "owner_action" }] : ability.passive_triggers })}>
        <MenuItem value="active">Active</MenuItem><MenuItem value="passive">Passive</MenuItem>
      </TextField>
      <TextField select label="Target" value={ability.target_type} onChange={e => setAbility({ ...ability, target_type: e.target.value as AbilityDefinition["target_type"] })}>
        {["self", "character", "choice", "relationship", "location", "all", "party", "allies", "enemies", "nearby_enemies", "faction_members", "random"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
      </TextField>
      {(["character", "item"] as const).map(kind => <FormControlLabel key={kind} control={<Checkbox checked={ability.compatible_owner_kinds.includes(kind)} onChange={e => setAbility({ ...ability, compatible_owner_kinds: e.target.checked ? [...ability.compatible_owner_kinds, kind] : ability.compatible_owner_kinds.filter(value => value !== kind) })}/>} label={kind}/>)}
    </Stack>

    <h3>Requirements</h3>
    {requirements
      ? <Stack spacing={1}><RequirementEditor node={requirements} stats={stats} items={items} locations={locations} abilities={abilities.filter(item => item.ability_key !== ability.ability_key)} onChange={next => setAbility({ ...ability, requirements: next })}/><Button onClick={() => setAbility({ ...ability, requirements: {} })}>Clear requirements</Button></Stack>
      : <Button onClick={() => setAbility({ ...ability, requirements: { kind: "compare", target: "actor", stat_key: characterStats[0]?.stat_key ?? "", comparison: "gte", value: 0 } })} disabled={!stats.length}>Add requirement</Button>}

    <h3>Costs</h3>
    {ability.costs.map((cost, index) => <Stack key={index} direction="row" spacing={1} alignItems="center">
      <TextField select label="Cost" value={cost.kind} onChange={e => updateCost(index, { kind: e.target.value as AbilityCost["kind"], stat_key: e.target.value === "stat" ? characterStats[0]?.stat_key ?? "" : null, item_id: e.target.value === "consume_fuel" ? items[0]?.id ?? "" : null })}>
        <MenuItem value="stat">Stat</MenuItem>
        {ability.compatible_owner_kinds.includes("item") && <MenuItem value="consume_source">Consume source item</MenuItem>}
        <MenuItem value="consume_fuel">Consume fuel item</MenuItem>
      </TextField>
      {cost.kind === "stat" && <TextField select label="Stat" value={cost.stat_key ?? ""} onChange={e => updateCost(index, { stat_key: e.target.value })}>
        {characterStats.map(item => <MenuItem key={item.stat_key} value={item.stat_key}>{item.label}</MenuItem>)}
      </TextField>}
      {cost.kind === "consume_fuel" && <TextField select label="Fuel item" value={cost.item_id ?? ""} onChange={e => updateCost(index, { item_id: e.target.value })} sx={{ minWidth: 180 }}>
        {items.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
      </TextField>}
      <TextField type="number" label="Amount" value={cost.amount} onChange={e => updateCost(index, { amount: Number(e.target.value) })}/>
      <Button onClick={() => setAbility({ ...ability, costs: ability.costs.filter((_, i) => i !== index) })}>Remove</Button>
    </Stack>)}
    <Button disabled={!characterStats.length} onClick={() => setAbility({ ...ability, costs: [...ability.costs, { kind: "stat", stat_key: characterStats[0]?.stat_key ?? "", amount: 1 }] })}>Add cost</Button>

    <h3>Ordered actions</h3>
    {ability.actions.map((action, index) => <Stack key={index} spacing={1} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1, p: 1 }}>
      <Stack direction="row" spacing={1} alignItems="center">
        <TextField select label="Action" value={action.kind} onChange={e => replaceAction(index, e.target.value as AbilityAction["kind"])}>
          {["apply_effect", "move", "create", "remove", "reveal_knowledge", "change_relationship", "advance_time", "play_noise"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
        </TextField>
        <TextField select label="Target selector" value={action.target} onChange={e => updateAction(index, { target: e.target.value })}>
          {["actor", "target", "party", "location", "nearby_enemies", "faction_members", "relationship_target", "allies", "enemies", "all", "random"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
        </TextField>
        <Button disabled={index === 0} onClick={() => moveAction(index, -1)}>↑</Button>
        <Button disabled={index === ability.actions.length - 1} onClick={() => moveAction(index, 1)}>↓</Button>
        <Button onClick={() => setAbility({ ...ability, actions: ability.actions.filter((_, i) => i !== index) })}>Remove</Button>
      </Stack>
      {action.kind === "apply_effect" && <Stack direction="row" spacing={1}>
        <TextField select fullWidth label="Effect" value={action.effect_key ?? ""} onChange={e => updateAction(index, { effect_key: e.target.value })}>
          {compatibleEffects.map(item => <MenuItem key={item.effect_key} value={item.effect_key}>{item.name} · {item.target_stat_key}</MenuItem>)}
        </TextField>
        <TextField type="number" label="Duration override" value={action.duration_override ?? ""} onChange={e => updateAction(index, { duration_override: e.target.value === "" ? null : Number(e.target.value) })} />
        <TextField type="number" label="Tick override" value={action.tick_override ?? ""} onChange={e => updateAction(index, { tick_override: e.target.value === "" ? null : Number(e.target.value) })} />
      </Stack>}
      {action.kind === "move" && <TextField select label="Destination" value={action.destination_id ?? ""} onChange={e => updateAction(index, { destination_id: e.target.value })}>
        {locations.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
      </TextField>}
      {action.kind === "create" && <Stack direction="row" spacing={1}><TextField select label="Entity kind" value={action.entity_kind ?? "item"} onChange={e => updateAction(index, { entity_kind: e.target.value })}>{["character", "location", "faction", "item", "lore_system", "fact", "plot_beat"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField><TextField label="Entity name" value={action.entity_name ?? ""} onChange={e => updateAction(index, { entity_name: e.target.value })}/><TextField label="Description" value={String(action.state?.description ?? "")} onChange={e => updateAction(index, { state: { ...(action.state ?? {}), description: e.target.value } })}/></Stack>}
      {action.kind === "reveal_knowledge" && <TextField select label="Fact" value={action.fact_id ?? ""} onChange={e => updateAction(index, { fact_id: e.target.value })}>{facts.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField>}
      {action.kind === "change_relationship" && <TextField label="Relationship" value={action.relation ?? ""} onChange={e => updateAction(index, { relation: e.target.value })}/>}
      {action.kind === "advance_time" && <TextField type="number" label="Minutes" value={action.minutes ?? 0} onChange={e => updateAction(index, { minutes: Number(e.target.value) })}/>}
      {action.kind === "play_noise" && <TextField label="Noise ID" value={action.noise_id ?? ""} onChange={e => updateAction(index, { noise_id: e.target.value })}/>}
    </Stack>)}
    <Button disabled={!compatibleEffects.length} onClick={() => setAbility({ ...ability, actions: [...ability.actions, { kind: "apply_effect", target: "target", effect_key: compatibleEffects[0]?.effect_key ?? "" }] })}>Add effect action</Button>
    <Button onClick={() => setAbility({ ...ability, actions: [...ability.actions, { kind: "advance_time", target: "actor", minutes: 0 }] })}>Add other action</Button>

    {ability.ability_kind === "passive" && <><h3>Passive triggers</h3>
      {ability.passive_triggers.map((trigger, index) => <Stack key={index} direction="row" spacing={1}>
        <TextField select label="Trigger" value={trigger.kind} onChange={e => setAbility({ ...ability, passive_triggers: ability.passive_triggers.map((item, i) => i === index ? { kind: e.target.value as AbilityDefinition["passive_triggers"][number]["kind"] } : item) })}>
          {["ability_used", "stat_changed", "damage", "owner_action", "movement", "time_advanced"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
        </TextField>
        {["stat_changed", "damage"].includes(trigger.kind) && <TextField select label="Optional stat filter" value={trigger.stat_key ?? ""} onChange={e => setAbility({ ...ability, passive_triggers: ability.passive_triggers.map((item, i) => i === index ? { ...item, stat_key: e.target.value || null } : item) })}>
          <MenuItem value="">Any stat</MenuItem>{characterStats.map(item => <MenuItem key={item.stat_key} value={item.stat_key}>{item.label}</MenuItem>)}
        </TextField>}
        <Button onClick={() => setAbility({ ...ability, passive_triggers: ability.passive_triggers.filter((_, i) => i !== index) })}>Remove</Button>
      </Stack>)}
      <Button onClick={() => setAbility({ ...ability, passive_triggers: [...ability.passive_triggers, { kind: "owner_action" }] })}>Add trigger</Button>
    </>}

    <h3>Minigames</h3>
    <Stack direction="row" spacing={1}>
      <TextField type="number" label="Timed attack lines" value={ability.timed_attack_line_count ?? ""} onChange={e => setAbility({ ...ability, timed_attack_line_count: e.target.value === "" ? null : Number(e.target.value) })}/>
      <TextField type="number" label="Damage per line" value={ability.timed_attack_damage_per_line ?? ""} onChange={e => setAbility({ ...ability, timed_attack_damage_per_line: e.target.value === "" ? null : Number(e.target.value) })}/>
    </Stack>
    <Stack direction="row" flexWrap="wrap">{bulletSkills.map(skill => <FormControlLabel key={skill.id} control={<Checkbox checked={ability.bullethell_skill_ids.includes(skill.id)} onChange={e => setAbility({ ...ability, bullethell_skill_ids: e.target.checked ? [...ability.bullethell_skill_ids, skill.id] : ability.bullethell_skill_ids.filter(id => id !== skill.id) })}/>} label={skill.name}/>)}</Stack>
    <FormControlLabel control={<Switch checked={ability.enabled} onChange={e => setAbility({ ...ability, enabled: e.target.checked })}/>} label="Enabled"/>
  </DialogContent><DialogActions><Button onClick={close}>Cancel</Button><Button variant="contained" onClick={save}>Save</Button></DialogActions></Dialog>;
}
