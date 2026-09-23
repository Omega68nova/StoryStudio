import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
} from "@mui/material";
import { api } from "./api";
import type { AbilityDefinition, StatDefinition } from "./types";
import type { BulletCatalog } from "./BulletHellStudio";

const blankStat = {
  stat_key: "",
  label: "",
  description: "",
  scope: "character",
  default_value: 0,
  minimum: 0,
  maximum: 100,
  minimum_stat_key: null,
  maximum_stat_key: null,
  color: null,
  minimum_color: null,
  maximum_color: null,
  display_style: "compact",
  integer_only: true,
  visibility: "public",
};
const blankAbility = {
  ability_key: "",
  name: "",
  description: "",
  target_type: "self",
  requirements: "{}",
  costs: "{}",
  effects:
    '[{"target":"target","stat_key":"hp","operation":"subtract","amount":10}]',
  attack_profile_enabled: false,
  attack_line_count: 1,
  attack_damage_per_line: 10,
  bullethell_skill_ids: "",
};

export function RulesStudio({
  projectId,
  revision,
  fail,
}: {
  projectId: string;
  revision: number;
  fail: (message: string) => void;
}) {
  const [rules, setRules] = useState<{
    stats: StatDefinition[];
    abilities: AbilityDefinition[];
  }>({ stats: [], abilities: [] });
  const [stat, setStat] = useState<any | null>(null);
  const [ability, setAbility] = useState<any | null>(null);
  const [bulletSkills, setBulletSkills] = useState<Array<{ id: string; name: string }>>([]);
  const load = useCallback(async () => {
    const [nextRules, catalog, settings] = await Promise.all([
      api<typeof rules>(`/projects/${projectId}/rules`), api<BulletCatalog>("/bullethell/catalog"),
      api<{ allowed_skill_ids: string[] }>(`/projects/${projectId}/bullethell`),
    ]);
    setRules(nextRules);
    setBulletSkills(catalog.skills.filter((item) => settings.allowed_skill_ids.includes(item.id)));
  }, [projectId]);
  useEffect(() => {
    void load().catch((cause) => fail(String(cause)));
  }, [load, revision, fail]);

  async function saveStat() {
    try {
      const path = stat.id
        ? `/projects/${projectId}/stats/${stat.id}`
        : `/projects/${projectId}/stats`;
      await api(path, {
        method: stat.id ? "PUT" : "POST",
        body: JSON.stringify(stat),
      });
      setStat(null);
      await load();
    } catch (cause) {
      fail(String(cause));
    }
  }
  async function saveAbility() {
    try {
      const {
        attack_profile_enabled,
        attack_line_count,
        attack_damage_per_line,
        bullethell_skill_ids,
        ...base
      } = ability;
      const linkedSkills = String(bullethell_skill_ids ?? "").split(",").map((item) => item.trim()).filter(Boolean);
      const payload = {
        ...base,
        requirements: JSON.parse(ability.requirements),
        costs: JSON.parse(ability.costs),
        effects: JSON.parse(ability.effects),
        minigame_profile: {
          ...(attack_profile_enabled ? {
              timed_attack: {
                line_count: attack_line_count,
                damage_per_line: attack_damage_per_line,
              },
            } : {}),
          ...(linkedSkills.length ? { bullethell_skill_ids: linkedSkills } : {}),
        },
      };
      const path = ability.id
        ? `/projects/${projectId}/abilities/${ability.id}`
        : `/projects/${projectId}/abilities`;
      await api(path, {
        method: ability.id ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      setAbility(null);
      await load();
    } catch (cause) {
      fail(String(cause));
    }
  }
  function editAbility(item: AbilityDefinition) {
    const profile = item.minigame_profile?.timed_attack;
    setAbility({
      ...item,
      requirements: JSON.stringify(item.requirements ?? {}, null, 2),
      costs: JSON.stringify(item.costs, null, 2),
      effects: JSON.stringify(item.effects, null, 2),
      attack_profile_enabled: Boolean(profile),
      attack_line_count: profile?.line_count ?? 1,
      attack_damage_per_line: profile?.damage_per_line ?? 10,
      bullethell_skill_ids:
        item.minigame_profile?.bullethell_skill_ids?.join(", ") ?? "",
    });
  }

  return (
    <div className="page">
      <header className="page-header">
        <p className="eyebrow">OPTIONAL MECHANICS</p>
        <h1>Stats and abilities</h1>
        <p>
          Rules are project-wide; values, costs, and temporary effects follow
          the active branch.
        </p>
      </header>
      <div className="rules-grid">
        <section className="panel">
          <Stack direction="row" justifyContent="space-between">
            <h2>Stats</h2>
            <Button onClick={() => setStat({ ...blankStat })}>Add stat</Button>
          </Stack>
          {rules.stats.map((item) => (
            <article className="rule-row" key={item.id}>
              <div>
                <strong>{item.label}</strong>
                <small>
                  {item.stat_key} · {item.scope} · {item.minimum}–{item.maximum}
                </small>
              </div>
              <div>
                <Button
                  onClick={() =>
                    setStat({
                      ...item,
                      integer_only: Boolean(item.integer_only),
                    })
                  }
                >
                  Edit
                </Button>
                <Button
                  color="error"
                  onClick={async () => {
                    try {
                      await api(`/projects/${projectId}/stats/${item.id}`, {
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
              </div>
            </article>
          ))}
        </section>
        <section className="panel">
          <Stack direction="row" justifyContent="space-between">
            <h2>Abilities</h2>
            <Button onClick={() => setAbility({ ...blankAbility })}>
              Add ability
            </Button>
          </Stack>
          {rules.abilities.map((item) => (
            <article className="rule-row" key={item.id}>
              <div>
                <strong>{item.name}</strong>
                <small>
                  {item.ability_key} · {item.target_type}
                  {item.minigame_profile?.timed_attack
                    ? ` · ${item.minigame_profile.timed_attack.line_count} attack line(s)`
                    : ""}
                </small>
                <p>{item.description}</p>
              </div>
              <div>
                <Button onClick={() => editAbility(item)}>Edit</Button>
                <Button
                  color="error"
                  onClick={async () => {
                    try {
                      await api(`/projects/${projectId}/abilities/${item.id}`, {
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
              </div>
            </article>
          ))}
        </section>
      </div>
      <Dialog open={Boolean(stat)} onClose={() => setStat(null)}>
        <DialogTitle>{stat?.id ? "Edit" : "Add"} stat</DialogTitle>
        <DialogContent className="music-dialog">
          {stat && (
            <>
              <TextField
                label="Stable key"
                disabled={Boolean(stat.id)}
                value={stat.stat_key}
                onChange={(e) => setStat({ ...stat, stat_key: e.target.value })}
              />
              <TextField
                label="Label"
                value={stat.label}
                onChange={(e) => setStat({ ...stat, label: e.target.value })}
              />
              <TextField
                multiline
                minRows={2}
                label="Description"
                value={stat.description ?? ""}
                helperText="General semantic description used by the editor and AI."
                onChange={(e) => setStat({ ...stat, description: e.target.value })}
              />
              <TextField
                select
                label="Scope"
                value={stat.scope}
                onChange={(e) => setStat({ ...stat, scope: e.target.value })}
              >
                <MenuItem value="character">Character</MenuItem>
                <MenuItem value="relationship">Relationship</MenuItem>
              </TextField>
              <Stack direction="row" spacing={1}>
                <TextField
                  type="number"
                  label="Default"
                  value={stat.default_value}
                  onChange={(e) =>
                    setStat({ ...stat, default_value: Number(e.target.value) })
                  }
                />
                <TextField
                  type="number"
                  label="Minimum"
                  value={stat.minimum}
                  onChange={(e) =>
                    setStat({ ...stat, minimum: Number(e.target.value) })
                  }
                />
                <TextField
                  type="number"
                  label="Maximum"
                  value={stat.maximum}
                  onChange={(e) =>
                    setStat({ ...stat, maximum: Number(e.target.value) })
                  }
                />
              </Stack>
              <Stack direction="row" spacing={1}>
                <TextField
                  select
                  fullWidth
                  label="Minimum from stat"
                  value={stat.minimum_stat_key ?? ""}
                  onChange={(e) => setStat({
                    ...stat,
                    minimum_stat_key: e.target.value || null,
                  })}
                >
                  <MenuItem value="">Use numeric minimum</MenuItem>
                  {rules.stats
                    .filter((item) => item.scope === stat.scope && item.stat_key !== stat.stat_key)
                    .map((item) => <MenuItem key={item.id} value={item.stat_key}>{item.label}</MenuItem>)}
                </TextField>
                <TextField
                  select
                  fullWidth
                  label="Maximum from stat"
                  value={stat.maximum_stat_key ?? ""}
                  onChange={(e) => setStat({
                    ...stat,
                    maximum_stat_key: e.target.value || null,
                  })}
                >
                  <MenuItem value="">Use numeric maximum</MenuItem>
                  {rules.stats
                    .filter((item) => item.scope === stat.scope && item.stat_key !== stat.stat_key)
                    .map((item) => <MenuItem key={item.id} value={item.stat_key}>{item.label}</MenuItem>)}
                </TextField>
              </Stack>
              <TextField
                select
                label="Display style"
                value={stat.display_style ?? "compact"}
                onChange={(e) => setStat({ ...stat, display_style: e.target.value })}
              >
                <MenuItem value="compact">Compact chip</MenuItem>
                <MenuItem value="bar">Value / min / max bar</MenuItem>
              </TextField>
              <Stack direction="row" spacing={1}>
                <TextField
                  label="Main / max color"
                  placeholder="#5a9b63"
                  value={stat.color ?? ""}
                  onChange={(e) => setStat({ ...stat, color: e.target.value || null })}
                />
                <TextField
                  label="Minimum color"
                  placeholder="#b94a48"
                  value={stat.minimum_color ?? ""}
                  onChange={(e) => setStat({ ...stat, minimum_color: e.target.value || null })}
                />
                <TextField
                  label="Maximum color override"
                  value={stat.maximum_color ?? ""}
                  onChange={(e) => setStat({ ...stat, maximum_color: e.target.value || null })}
                />
              </Stack>
              <FormControlLabel
                control={<Switch
                  checked={Boolean(stat.integer_only)}
                  onChange={(e) => setStat({ ...stat, integer_only: e.target.checked })}
                />}
                label="Integer values only"
              />
              <TextField
                select
                label="Visibility"
                value={stat.visibility ?? "public"}
                onChange={(e) => setStat({ ...stat, visibility: e.target.value })}
              >
                <MenuItem value="public">Public</MenuItem>
                <MenuItem value="private">Private</MenuItem>
                <MenuItem value="narrator">Narrator only</MenuItem>
              </TextField>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStat(null)}>Cancel</Button>
          <Button variant="contained" onClick={() => void saveStat()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={Boolean(ability)}
        onClose={() => setAbility(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>{ability?.id ? "Edit" : "Add"} ability</DialogTitle>
        <DialogContent className="music-dialog">
          {ability && (
            <>
              <TextField
                label="Stable key"
                disabled={Boolean(ability.id)}
                value={ability.ability_key}
                onChange={(e) =>
                  setAbility({ ...ability, ability_key: e.target.value })
                }
              />
              <TextField
                label="Name"
                value={ability.name}
                onChange={(e) =>
                  setAbility({ ...ability, name: e.target.value })
                }
              />
              <TextField
                multiline
                label="Description"
                value={ability.description}
                onChange={(e) =>
                  setAbility({ ...ability, description: e.target.value })
                }
              />
              <TextField
                select
                label="Target"
                value={ability.target_type}
                onChange={(e) =>
                  setAbility({ ...ability, target_type: e.target.value })
                }
              >
                <MenuItem value="self">Self</MenuItem>
                <MenuItem value="character">Character</MenuItem>
                <MenuItem value="choice">Chosen character</MenuItem>
                <MenuItem value="relationship">Relationship</MenuItem>
                <MenuItem value="location">Location</MenuItem>
                <MenuItem value="all">Everyone present</MenuItem>
                <MenuItem value="party">Party</MenuItem>
                <MenuItem value="allies">Allies</MenuItem>
                <MenuItem value="enemies">Enemies</MenuItem>
                <MenuItem value="nearby_enemies">Nearby enemies</MenuItem>
                <MenuItem value="faction_members">Nearby faction members</MenuItem>
                <MenuItem value="random">One resolved random target</MenuItem>
              </TextField>
              <TextField
                multiline
                label="Requirements JSON"
                value={ability.requirements}
                onChange={(e) =>
                  setAbility({ ...ability, requirements: e.target.value })
                }
              />
              <TextField
                multiline
                label="Costs JSON"
                value={ability.costs}
                onChange={(e) =>
                  setAbility({ ...ability, costs: e.target.value })
                }
              />
              <TextField
                multiline
                minRows={4}
                label="Effects JSON"
                value={ability.effects}
                onChange={(e) =>
                  setAbility({ ...ability, effects: e.target.value })
                }
              />
              <TextField
                label="Linked bullet-hell skill IDs"
                value={ability.bullethell_skill_ids ?? ""}
                onChange={(e) => setAbility({ ...ability, bullethell_skill_ids: e.target.value })}
                helperText={bulletSkills.length ? `Enabled: ${bulletSkills.map((skill) => `${skill.name} (${skill.id})`).join(", ")}` : "Enable project skills in Bullet Hell first."}
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={ability.attack_profile_enabled}
                    onChange={(e) =>
                      setAbility({
                        ...ability,
                        attack_profile_enabled: e.target.checked,
                      })
                    }
                  />
                }
                label="Use timed-attack profile"
              />
              {ability.attack_profile_enabled && (
                <Stack direction="row" spacing={1}>
                  <TextField
                    type="number"
                    label="Attack lines"
                    value={ability.attack_line_count}
                    inputProps={{ min: 1, max: 8 }}
                    onChange={(e) =>
                      setAbility({
                        ...ability,
                        attack_line_count: Number(e.target.value),
                      })
                    }
                  />
                  <TextField
                    type="number"
                    label="Damage per line"
                    value={ability.attack_damage_per_line}
                    inputProps={{ min: 0 }}
                    onChange={(e) =>
                      setAbility({
                        ...ability,
                        attack_damage_per_line: Number(e.target.value),
                      })
                    }
                  />
                </Stack>
              )}
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAbility(null)}>Cancel</Button>
          <Button variant="contained" onClick={() => void saveAbility()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}
