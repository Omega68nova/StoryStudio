import { Button, MenuItem, Paper, Stack, TextField } from "@mui/material";
import type {
  AbilityDefinition,
  ConditionExpression,
  RuleObjectSelector,
  RuleOwnerKind,
  RuleSelectorKind,
  StatDefinition,
  ValueExpression,
} from "./types";

export const ruleOwnerKinds: RuleOwnerKind[] = [
  "character", "item", "location", "faction", "lore_system", "fact", "plot_beat",
  "relationship", "ability", "effect", "weather", "outfit", "navigation_space", "map_feature",
];
export const selectorKinds: RuleSelectorKind[] = [
  "actor", "source", "target", "current_location", "ability", "effect", "explicit", "relationship_target",
];
export const conditionKinds: ConditionExpression["kind"][] = [
  "and", "or", "not", "compare", "exists", "has_tag", "has_item", "has_ability",
  "relationship", "location", "time", "weather",
];

export function blankSelector(kind: RuleSelectorKind = "target"): RuleObjectSelector {
  return kind === "explicit" ? { kind, object_kind: "location", object_id: "" } : { kind };
}

export function blankValueExpression(
  kind: ValueExpression["kind"] = "constant",
  stats: StatDefinition[] = [],
): ValueExpression {
  if (kind === "constant") return { kind, value: 0 };
  if (kind === "stat") return { kind, selector: blankSelector("target"), stat_key: stats[0]?.stat_key ?? "" };
  if (kind === "negate") return { kind, children: [{ kind: "constant", value: 0 }] };
  return { kind, children: [{ kind: "constant", value: 0 }, { kind: "constant", value: 0 }] };
}

export function blankConditionExpression(
  kind: ConditionExpression["kind"] = "compare",
  stats: StatDefinition[] = [],
): ConditionExpression {
  if (kind === "and" || kind === "or") return { kind, children: [blankConditionExpression("compare", stats)] };
  if (kind === "not") return { kind, child: blankConditionExpression("compare", stats) };
  if (kind === "compare") return {
    kind,
    left: { kind: "stat", selector: blankSelector("actor"), stat_key: stats[0]?.stat_key ?? "" },
    comparison: "gte",
    right: { kind: "constant", value: 0 },
  };
  if (kind === "time") return { kind, time_phase_id: "" };
  if (kind === "weather") return { kind, weather_id: "" };
  const selector = blankSelector("actor");
  if (kind === "exists") return { kind, selector };
  if (kind === "has_tag") return { kind, selector, tag: "" };
  if (kind === "has_item") return { kind, selector, item_id: "" };
  if (kind === "has_ability") return { kind, selector, ability_key: "" };
  if (kind === "relationship") return { kind, selector, relation: "" };
  return { kind, selector, location_id: "" };
}

export function conditionExpressionFromPayload(
  payload: Record<string, unknown>,
  stats: StatDefinition[] = [],
): ConditionExpression {
  const kind = String(payload.kind ?? "compare") as ConditionExpression["kind"];
  if (kind === "and" || kind === "or") {
    return {
      kind,
      children: Array.isArray(payload.children)
        ? payload.children.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object").map(item => conditionExpressionFromPayload(item, stats))
        : [blankConditionExpression("compare", stats)],
    };
  }
  if (kind === "not") {
    const child = payload.child && typeof payload.child === "object"
      ? conditionExpressionFromPayload(payload.child as Record<string, unknown>, stats)
      : blankConditionExpression("compare", stats);
    return { kind, child };
  }
  if (kind === "compare") {
    if (payload.left && payload.right) return payload as unknown as ConditionExpression;
    const target = payload.target === "target" ? "target" : "actor";
    return {
      kind,
      left: { kind: "stat", selector: blankSelector(target), stat_key: String(payload.stat_key ?? stats[0]?.stat_key ?? "") },
      comparison: (payload.comparison as ConditionExpression["comparison"]) ?? "gte",
      right: { kind: "constant", value: Number(payload.value ?? 0) },
    };
  }
  if (kind === "time") return { kind, time_phase_id: String(payload.time_phase_id ?? "") };
  if (kind === "weather") return { kind, weather_id: String(payload.weather_id ?? "") };
  if (kind === "exists") return payload as unknown as ConditionExpression;

  if (payload.selector) return payload as unknown as ConditionExpression;
  const selector = blankSelector(payload.target === "target" ? "target" : "actor");
  if (kind === "has_tag") return { kind, selector, tag: String(payload.tag ?? "") };
  if (kind === "has_item") return { kind, selector, item_id: String(payload.item_id ?? "") };
  if (kind === "has_ability") return { kind, selector, ability_key: String(payload.ability_key ?? "") };
  if (kind === "relationship") return { kind, selector, relation: String(payload.relation ?? "") };
  if (kind === "location") return { kind, selector, location_id: String(payload.location_id ?? "") };
  return blankConditionExpression("compare", stats);
}

export function SelectorEditor({
  selector,
  onChange,
}: {
  selector: RuleObjectSelector;
  onChange: (value: RuleObjectSelector) => void;
}) {
  return <Stack direction="row" spacing={1} flexWrap="wrap">
    <TextField select size="small" label="Object" value={selector.kind} onChange={event => onChange(blankSelector(event.target.value as RuleSelectorKind))}>
      {selectorKinds.map(value => <MenuItem key={value} value={value}>{value.replaceAll("_", " ")}</MenuItem>)}
    </TextField>
    {selector.kind === "explicit" && <>
      <TextField select size="small" label="Object kind" value={selector.object_kind ?? "location"} onChange={event => onChange({ ...selector, object_kind: event.target.value as RuleOwnerKind })}>
        {ruleOwnerKinds.map(value => <MenuItem key={value} value={value}>{value.replaceAll("_", " ")}</MenuItem>)}
      </TextField>
      <TextField size="small" label="Object ID/key" value={selector.object_id ?? ""} onChange={event => onChange({ ...selector, object_id: event.target.value })}/>
    </>}
  </Stack>;
}

export function ValueExpressionEditor({
  node,
  stats,
  onChange,
}: {
  node: ValueExpression;
  stats: StatDefinition[];
  onChange: (value: ValueExpression) => void;
}) {
  return <section className="panel formula-node">
    <TextField select size="small" label="Value node" value={node.kind} onChange={event => onChange(blankValueExpression(event.target.value as ValueExpression["kind"], stats))}>
      {["constant", "stat", "add", "subtract", "multiply", "divide", "minimum", "maximum", "negate"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
    </TextField>
    {node.kind === "constant" && <TextField size="small" type="number" label="Value" value={node.value} onChange={event => onChange({ ...node, value: Number(event.target.value) })}/>}
    {node.kind === "stat" && <Stack spacing={1}>
      <SelectorEditor selector={node.selector} onChange={selector => onChange({ ...node, selector })}/>
      <TextField select size="small" label="Stat" value={node.stat_key} onChange={event => onChange({ ...node, stat_key: event.target.value })}>
        {stats.map(item => <MenuItem key={item.stat_key} value={item.stat_key}>{item.label} · {item.compatible_owner_kinds.join(", ")}</MenuItem>)}
      </TextField>
    </Stack>}
    {"children" in node && node.children.map((child, index) =>
      <ValueExpressionEditor
        key={index}
        node={child}
        stats={stats}
        onChange={next => onChange({ ...node, children: node.children.map((value, childIndex) => childIndex === index ? next : value) } as ValueExpression)}
      />
    )}
  </section>;
}

export function ConditionExpressionEditor({
  node,
  stats,
  abilities = [],
  locations = [],
  onChange,
  onRemove,
}: {
  node: ConditionExpression;
  stats: StatDefinition[];
  abilities?: AbilityDefinition[];
  locations?: Array<{ id: string; name: string }>;
  onChange: (value: ConditionExpression) => void;
  onRemove?: () => void;
}) {
  const selector = node.selector ?? blankSelector("actor");
  const children = node.children ?? [];
  return <Paper variant="outlined" sx={{ p: 1.5 }}>
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="flex-start">
      <TextField select size="small" label="Condition" value={node.kind} onChange={event => onChange(blankConditionExpression(event.target.value as ConditionExpression["kind"], stats))}>
        {conditionKinds.map(value => <MenuItem key={value} value={value}>{value.replaceAll("_", " ")}</MenuItem>)}
      </TextField>
      {onRemove && <Button color="error" size="small" onClick={onRemove}>Remove</Button>}
    </Stack>

    {(node.kind === "and" || node.kind === "or") && <Stack spacing={1} sx={{ mt: 1 }}>
      {children.map((child, index) => <ConditionExpressionEditor
        key={index}
        node={child}
        stats={stats}
        abilities={abilities}
        locations={locations}
        onChange={next => onChange({ ...node, children: children.map((value, childIndex) => childIndex === index ? next : value) })}
        onRemove={() => onChange({ ...node, children: children.filter((_, childIndex) => childIndex !== index) })}
      />)}
      <Button size="small" onClick={() => onChange({ ...node, children: [...children, blankConditionExpression("compare", stats)] })}>Add condition</Button>
    </Stack>}

    {node.kind === "not" && <Stack sx={{ mt: 1 }}>
      <ConditionExpressionEditor
        node={node.child ?? blankConditionExpression("compare", stats)}
        stats={stats}
        abilities={abilities}
        locations={locations}
        onChange={child => onChange({ ...node, child })}
      />
    </Stack>}

    {node.kind === "compare" && <Stack spacing={1} sx={{ mt: 1 }}>
      <div><b>Left value</b><ValueExpressionEditor node={node.left ?? blankValueExpression("constant", stats)} stats={stats} onChange={left => onChange({ ...node, left })}/></div>
      <TextField select size="small" label="Comparison" value={node.comparison ?? "gte"} onChange={event => onChange({ ...node, comparison: event.target.value as ConditionExpression["comparison"] })}>
        {["eq", "ne", "lt", "lte", "gt", "gte"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
      </TextField>
      <div><b>Right value</b><ValueExpressionEditor node={node.right ?? blankValueExpression("constant", stats)} stats={stats} onChange={right => onChange({ ...node, right })}/></div>
    </Stack>}

    {(["exists", "has_tag", "has_item", "has_ability", "relationship", "location"] as string[]).includes(node.kind) && <Stack spacing={1} sx={{ mt: 1 }}>
      <SelectorEditor selector={selector} onChange={next => onChange({ ...node, selector: next })}/>
      {node.kind === "has_tag" && <TextField size="small" label="Tag" value={node.tag ?? ""} onChange={event => onChange({ ...node, tag: event.target.value })}/>}
      {node.kind === "has_item" && <TextField size="small" label="Item ID" value={node.item_id ?? ""} onChange={event => onChange({ ...node, item_id: event.target.value })}/>}
      {node.kind === "has_ability" && (abilities.length
        ? <TextField select size="small" label="Ability" value={node.ability_key ?? ""} onChange={event => onChange({ ...node, ability_key: event.target.value })}>{abilities.map(item => <MenuItem key={item.ability_key} value={item.ability_key}>{item.name}</MenuItem>)}</TextField>
        : <TextField size="small" label="Ability key" value={node.ability_key ?? ""} onChange={event => onChange({ ...node, ability_key: event.target.value })}/>)}
      {node.kind === "relationship" && <TextField size="small" label="Relationship" value={node.relation ?? ""} onChange={event => onChange({ ...node, relation: event.target.value })}/>}
      {node.kind === "location" && (locations.length
        ? <TextField select size="small" label="Location" value={node.location_id ?? ""} onChange={event => onChange({ ...node, location_id: event.target.value })}>{locations.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField>
        : <TextField size="small" label="Location ID" value={node.location_id ?? ""} onChange={event => onChange({ ...node, location_id: event.target.value })}/>)}
    </Stack>}

    {node.kind === "time" && <TextField sx={{ mt: 1 }} size="small" label="Time phase ID" value={node.time_phase_id ?? ""} onChange={event => onChange({ ...node, time_phase_id: event.target.value })}/>}
    {node.kind === "weather" && <TextField sx={{ mt: 1 }} size="small" label="Weather ID" value={node.weather_id ?? ""} onChange={event => onChange({ ...node, weather_id: event.target.value })}/>}
  </Paper>;
}
