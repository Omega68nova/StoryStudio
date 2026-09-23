import { useEffect, useMemo, useState } from "react";
import {
  Button,
  FormControlLabel,
  MenuItem,
  Switch,
  Tab,
  Tabs,
  TextField,
  Tooltip,
} from "@mui/material";
import { BoxedMultiselectFilter, CreatableBoxedMultiselect } from "./customComponents/BoxedMultiselect";
import { EntityImageSurface } from "./customComponents/EntityImageSurface";
import { updateDraftState } from "./entityDrafts";
import type {
  AbilityDefinition,
  CharacterEditorDraft,
  MediaAsset,
  Outfit,
  StatDefinition,
  WorldEntity,
  WorldRelationship,
} from "./types";

export type OutfitDraft = {
  id?: string;
  entity_id: string;
  name: string;
  description: string;
  equipment: string[];
};

const array = (value: unknown): string[] => Array.isArray(value) ? value.map(String) : [];

const RELATION_TYPES = [
  { value: "friend", label: "Friend", kinds: ["character"], bidirectional: true },
  { value: "rival", label: "Rival", kinds: ["character"], bidirectional: true },
  { value: "knows", label: "Knows", kinds: ["character"], bidirectional: false },
  { value: "home", label: "Home", kinds: ["location"], bidirectional: false },
  { value: "works_at", label: "Works at", kinds: ["location"], bidirectional: false },
  { value: "member_of", label: "Member of", kinds: ["faction"], bidirectional: false },
  { value: "owns", label: "Owns", kinds: ["item"], bidirectional: false },
] as const;

type Props = {
  draft: CharacterEditorDraft;
  setDraft: (value: CharacterEditorDraft) => void;
  entities: WorldEntity[];
  relations: WorldRelationship[];
  modes: Array<{ id: string; name: string }>;
  skills: Array<{ id: string; name: string }>;
  history: Array<Record<string, unknown>>;
  outfits: Outfit[];
  media: MediaAsset[];
  stats: StatDefinition[];
  abilities: AbilityDefinition[];
  outfitDraft: OutfitDraft | null;
  setOutfitDraft: (value: OutfitDraft | null) => void;
  saveOutfit: () => Promise<void>;
  deleteOutfit: (value: Outfit) => Promise<void>;
  activateOutfit: (value: Outfit) => Promise<void>;
  upload: (kind: "portrait" | "full_body", outfitId: string | null, file: File) => Promise<void>;
  generateMedia: (
    kind: "portrait" | "full_body",
    outfitId: string | null,
    differentPrompt: boolean,
    asset?: MediaAsset | null,
  ) => Promise<void>;
  removeMedia: (value: MediaAsset) => Promise<void>;
  mediaJobs: Record<string, { id: string; status: string }>;
  setStat: (key: string, value: number) => Promise<void>;
  updateStatDefinition: (
    definition: StatDefinition,
    patch: Partial<Pick<StatDefinition, "minimum" | "maximum">>,
  ) => Promise<void>;
  createRelationship: (relation: string, targetId: string, bidirectional: boolean) => Promise<void>;
  removeRelationship: (relation: WorldRelationship) => Promise<void>;
};

export function CharacterEditorForm({
  draft,
  setDraft,
  entities,
  relations,
  modes,
  skills,
  history,
  outfits,
  media,
  stats,
  abilities,
  outfitDraft,
  setOutfitDraft,
  saveOutfit,
  deleteOutfit,
  activateOutfit,
  upload,
  generateMedia,
  removeMedia,
  mediaJobs,
  setStat,
  updateStatDefinition,
  createRelationship,
  removeRelationship,
}: Props) {
  const state = draft.state as Record<string, any>;
  const setState = (patch: Record<string, unknown>) =>
    setDraft(updateDraftState(draft, patch) as CharacterEditorDraft);

  const [tab, setTab] = useState(0);
  const [viewOutfitId, setViewOutfitId] = useState(String(state.active_outfit_id ?? ""));
  const [equipmentCandidate, setEquipmentCandidate] = useState("");
  const [abilityCandidate, setAbilityCandidate] = useState("");
  const [relationType, setRelationType] = useState("");
  const [relationTarget, setRelationTarget] = useState("");

  useEffect(() => {
    setViewOutfitId(String(state.active_outfit_id ?? ""));
  }, [draft.id]);

  const character = entities.find(item => item.id === draft.id);
  const locations = entities.filter(item => item.kind === "location");
  const items = entities.filter(item => item.kind === "item");
  const facts = entities.filter(item => item.kind === "fact");
  const factions = entities.filter(item => item.kind === "faction");
  const inventory = Array.isArray(state.inventory)
    ? state.inventory as Array<{ item_id: string; quantity: number }>
    : [];

  const selectedOutfit = outfits.find(item => item.id === viewOutfitId) ?? null;
  const activeOutfit = outfits.find(item => item.id === String(state.active_outfit_id ?? "")) ?? null;

  const selectedMedia = (kind: "portrait" | "full_body") => {
    const outfitSpecific = viewOutfitId
      ? media.find(asset => asset.kind === kind && asset.outfit_id === viewOutfitId)
      : undefined;
    return outfitSpecific
      ?? media.find(asset => asset.kind === kind && !asset.outfit_id)
      ?? null;
  };

  const portrait = selectedMedia("portrait");
  const fullBody = selectedMedia("full_body");
  const portraitJob = mediaJobs[`portrait:${viewOutfitId || "default"}`];
  const fullBodyJob = mediaJobs[`full_body:${viewOutfitId || "default"}`];
  const entityMulti = (label: string, ids: unknown, options: WorldEntity[], key: string) => {
    const values = array(ids);
    const selected = options.filter(item => values.includes(item.id));
    const missing = values
      .filter(id => !options.some(item => item.id === id))
      .map(id => ({
        id,
        name: `Unavailable (${id})`,
        kind: "missing",
        aliases: [],
        tags: [],
        state: {},
        card: {
          compact_text: "",
          visual_description: "",
          image_tags: [],
          search_text: "",
        },
      } as WorldEntity));
    return <BoxedMultiselectFilter
      label={label}
      options={[...options, ...missing]}
      value={[...selected, ...missing]}
      getOptionDisabled={item => item.kind === "missing" || Boolean(item.state.archived)}
      onChange={(_event, next) => setState({ [key]: next.map(item => item.id) })}
    />;
  };

  function chooseViewOutfit(id: string) {
    setViewOutfitId(id);
    const outfit = outfits.find(item => item.id === id);
    setOutfitDraft(outfit ? {
      id: outfit.id,
      entity_id: outfit.entity_id,
      name: outfit.name,
      description: outfit.description,
      equipment: outfit.equipment,
    } : null);
  }

  const related = relations.filter(
    item => item.source_id === draft.id || item.target_id === draft.id,
  );

  const relationDefinition = RELATION_TYPES.find(item => item.value === relationType);
  const compatibleTargets = relationDefinition
    ? entities.filter(item =>
      item.id !== draft.id
      && (relationDefinition.kinds as readonly string[]).includes(item.kind)
      && !item.state.archived)
    : [];

  const tabs = [
    "Personality",
    "Wardrobe",
    "Equipment",
    "Abilities",
    "Relationships",
    "Context",
    "Advanced",
    "History",
  ];

  return <div className="character-editor-layout">
    <aside className="character-editor-left-rail">
      <EntityImageSurface
        asset={portrait}
        alt={`${draft.name || "Character"} portrait`}
        className="character-portrait-surface"
        placeholder="Portrait"
        onGenerate={() => void generateMedia("portrait", viewOutfitId || null, false, portrait)}
        onGenerateWithPrompt={() => void generateMedia("portrait", viewOutfitId || null, true, portrait)}
        onRegenerate={asset => void generateMedia("portrait", viewOutfitId || null, false, asset)}
        onRegenerateWithPrompt={asset => void generateMedia("portrait", viewOutfitId || null, true, asset)}
        onDelete={asset => void removeMedia(asset)}
        onUpload={draft.id ? file => void upload("portrait", viewOutfitId || null, file) : undefined}
        loading={Boolean(portraitJob)}
        loadingLabel={portraitJob ? `Generating portrait · ${portraitJob.status}` : undefined}
      />
      <CharacterStatRail
        definitions={stats}
        values={character?.stats ?? {}}
        onSetStat={setStat}
        onUpdateDefinition={updateStatDefinition}
      />
    </aside>

    <main className="character-editor-main">
      <section className="character-editor-identity">
        <div className="character-editor-name-row">
          <TextField
            required
            label="Name"
            value={draft.name}
            onChange={event => setDraft({ ...draft, name: event.target.value })}
          />
          <CreatableBoxedMultiselect
            label="Aliases"
            options={draft.aliases}
            value={draft.aliases}
            onChange={(_event, next) => setDraft({ ...draft, aliases: next })}
          />
          <TextField
            label="Pronouns"
            value={String(state.pronouns ?? "")}
            onChange={event => setState({ pronouns: event.target.value })}
          />
        </div>
        <TextField
          multiline
          minRows={3}
          label="Description"
          value={String(state.description ?? "")}
          onChange={event => setState({ description: event.target.value })}
        />
        <TextField
          multiline
          minRows={3}
          label="Appearance"
          value={String(state.appearance ?? "")}
          onChange={event => setState({ appearance: event.target.value })}
        />
      </section>

      <Tabs
        className="character-editor-tabs"
        value={tab}
        onChange={(_event, value) => setTab(value)}
        variant="scrollable"
        scrollButtons="auto"
      >
        {tabs.map(label => <Tab key={label} label={label} />)}
      </Tabs>

      <section className="character-editor-tab-body">
        {tab === 0 && <div className="character-fields">
          <TextField
            multiline
            minRows={4}
            label="Personality"
            value={String(state.personality ?? "")}
            onChange={event => setState({ personality: event.target.value })}
          />
          <CreatableBoxedMultiselect
            label="Goals"
            options={array(state.goals)}
            value={array(state.goals)}
            onChange={(_event, next) => setState({ goals: next })}
          />
          <CreatableBoxedMultiselect
            label="Character secrets (known while acting)"
            options={array(state.character_secrets)}
            value={array(state.character_secrets)}
            onChange={(_event, next) => setState({ character_secrets: next })}
          />
          <CreatableBoxedMultiselect
            label="Secrets from character (narrator only)"
            options={array(state.secrets_to_character)}
            value={array(state.secrets_to_character)}
            onChange={(_event, next) => setState({ secrets_to_character: next })}
          />
        </div>}

        {tab === 1 && <div className="character-fields">
          <TextField
            multiline
            minRows={4}
            label="Wardrobe notes"
            value={String(state.wardrobe ?? "")}
            onChange={event => setState({ wardrobe: event.target.value })}
          />
          <TextField
            select
            label="Active outfit"
            value={String(state.active_outfit_id ?? "")}
            onChange={event => setState({ active_outfit_id: event.target.value || null })}
          >
            <MenuItem value="">No outfit</MenuItem>
            {outfits.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
          </TextField>

          {!selectedOutfit && draft.id && <Button
            onClick={() => setOutfitDraft({
              entity_id: draft.id!,
              name: "",
              description: "",
              equipment: [],
            })}
          >Create outfit</Button>}

          {selectedOutfit && !outfitDraft && <Button
            onClick={() => chooseViewOutfit(selectedOutfit.id)}
          >Edit {selectedOutfit.name}</Button>}

          {outfitDraft && <div className="character-outfit-editor">
            <TextField
              label="Outfit name"
              value={outfitDraft.name}
              onChange={event => setOutfitDraft({ ...outfitDraft, name: event.target.value })}
            />
            <TextField
              multiline
              minRows={4}
              label="Outfit appearance"
              value={outfitDraft.description}
              onChange={event => setOutfitDraft({ ...outfitDraft, description: event.target.value })}
            />
            <CreatableBoxedMultiselect
              label="Equipment"
              options={outfitDraft.equipment}
              value={outfitDraft.equipment}
              onChange={(_event, next) => setOutfitDraft({ ...outfitDraft, equipment: next })}
            />
            <div className="button-row">
              <Button variant="contained" onClick={() => void saveOutfit()}>Save outfit</Button>
              {outfitDraft.id && <Button
                color="error"
                onClick={() => {
                  const outfit = outfits.find(item => item.id === outfitDraft.id);
                  if (outfit) void deleteOutfit(outfit);
                }}
              >Delete outfit</Button>}
            </div>
          </div>}
        </div>}

        {tab === 2 && <div className="character-linked-section">
          <LinkedResourceList
            title="Equipped"
            ids={array(state.equipment)}
            options={items}
            onRemove={id => setState({
              equipment: array(state.equipment).filter(value => value !== id),
            })}
          />
          <div className="character-add-row">
            <TextField
              select
              size="small"
              label="Add equipment"
              value={equipmentCandidate}
              onChange={event => setEquipmentCandidate(event.target.value)}
            >
              <MenuItem value="">Select item</MenuItem>
              {items
                .filter(item => !array(state.equipment).includes(item.id))
                .map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
            </TextField>
            <Button
              disabled={!equipmentCandidate}
              onClick={() => {
                setState({ equipment: [...array(state.equipment), equipmentCandidate] });
                setEquipmentCandidate("");
              }}
            >Add</Button>
            <Button disabled title="Manual item creation will be wired to the typed Item editor">Create item</Button>
            <Button disabled title="AI item creation will be wired to domain generation tools">Create with AI</Button>
          </div>

          <h4>Carried inventory</h4>
          {inventory.map((entry, index) => {
            const selectedItem = items.find(item => item.id === entry.item_id);
            return <div className="environment-condition-row" key={index}>
              <TextField
                select
                size="small"
                label="Item"
                value={entry.item_id}
                onChange={event => setState({
                  inventory: inventory.map((value, position) =>
                    position === index ? { ...value, item_id: event.target.value } : value),
                })}
              >
                {!selectedItem && entry.item_id && <MenuItem value={entry.item_id} disabled>
                  Unavailable ({entry.item_id})
                </MenuItem>}
                {items.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
              </TextField>
              <TextField
                size="small"
                type="number"
                label="Quantity"
                value={entry.quantity}
                onChange={event => setState({
                  inventory: inventory.map((value, position) =>
                    position === index
                      ? { ...value, quantity: Math.max(0, Math.floor(Number(event.target.value) || 0)) }
                      : value),
                })}
              />
              <Button
                color="error"
                onClick={() => setState({
                  inventory: inventory.filter((_, position) => position !== index),
                })}
              >Remove</Button>
            </div>;
          })}
          <Button
            disabled={!items.some(item => !item.state.archived)}
            onClick={() => setState({
              inventory: [
                ...inventory,
                { item_id: items.find(item => !item.state.archived)?.id ?? "", quantity: 1 },
              ],
            })}
          >Add inventory item</Button>
        </div>}

        {tab === 3 && <div className="character-linked-section">
          <AbilityList
            keys={array(state.abilities)}
            abilities={abilities}
            onRemove={key => setState({
              abilities: array(state.abilities).filter(value => value !== key),
            })}
          />
          <div className="character-add-row">
            <TextField
              select
              size="small"
              label="Add ability"
              value={abilityCandidate}
              onChange={event => setAbilityCandidate(event.target.value)}
            >
              <MenuItem value="">Select ability</MenuItem>
              {abilities
                .filter(item => !array(state.abilities).includes(item.ability_key))
                .map(item => <MenuItem key={item.id} value={item.ability_key}>{item.name}</MenuItem>)}
            </TextField>
            <Button
              disabled={!abilityCandidate}
              onClick={() => {
                setState({ abilities: [...array(state.abilities), abilityCandidate] });
                setAbilityCandidate("");
              }}
            >Add</Button>
            <Button disabled title="Manual ability creation remains in Rules until the typed Ability editor is shared">Create ability</Button>
            <Button disabled title="AI ability creation will use domain generation tools">Create with AI</Button>
          </div>
          <BoxedMultiselectFilter
            label="Bullet-hell skills"
            options={skills}
            value={skills.filter(item => array(state.bullethell_skill_ids).includes(item.id))}
            onChange={(_event, next) => setState({
              bullethell_skill_ids: next.map(item => item.id),
            })}
          />
        </div>}

        {tab === 4 && <div className="character-relationship-section">
          <div className="character-relationship-list">
            {related.map(relation => {
              const targetId = relation.source_id === draft.id
                ? relation.target_id
                : relation.source_id;
              const target = entities.find(entity => entity.id === targetId);
              return <div className="character-linked-card" key={String(relation.id)}>
                <span className="character-linked-icon">{target?.name?.slice(0, 1).toUpperCase() ?? "?"}</span>
                <span>
                  <b>{target?.name ?? "Unavailable object"}</b>
                  <small>{String(relation.relation)}</small>
                </span>
                <Button color="error" onClick={() => void removeRelationship(relation)}>Remove</Button>
              </div>;
            })}
          </div>
          <div className="character-add-row">
            <TextField
              select
              size="small"
              label="Relationship"
              value={relationType}
              onChange={event => {
                setRelationType(event.target.value);
                setRelationTarget("");
              }}
            >
              <MenuItem value="">Select relationship</MenuItem>
              {RELATION_TYPES.map(item =>
                <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
            </TextField>
            <TextField
              select
              size="small"
              label="Compatible object"
              value={relationTarget}
              disabled={!relationType}
              onChange={event => setRelationTarget(event.target.value)}
            >
              <MenuItem value="">Select object</MenuItem>
              {compatibleTargets.map(item =>
                <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
            </TextField>
            <Button
              disabled={!relationDefinition || !relationTarget}
              onClick={() => {
                if (!relationDefinition || !relationTarget) return;
                void createRelationship(
                  relationDefinition.value,
                  relationTarget,
                  relationDefinition.bidirectional,
                );
                setRelationTarget("");
              }}
            >Add</Button>
          </div>
        </div>}

        {tab === 5 && <div className="character-fields">
          <TextField
            select
            label="Current location"
            value={String(state.current_location_id ?? "")}
            onChange={event => setState({ current_location_id: event.target.value || null })}
          >
            <MenuItem value="">Unknown</MenuItem>
            {locations.map(item => <MenuItem
              key={item.id}
              value={item.id}
              disabled={item.state.enabled === false || Boolean(item.state.archived)}
            >{item.name}</MenuItem>)}
          </TextField>
          {entityMulti("Known facts", state.knowledge, facts, "knowledge")}
          {entityMulti("Faction memberships", state.faction_ids, factions, "faction_ids")}
          <FormControlLabel
            control={<Switch
              checked={Boolean(state.player_controlled)}
              onChange={event => setState({
                player_controlled: event.target.checked,
                autonomy_enabled: event.target.checked
                  ? false
                  : Boolean(state.autonomy_enabled),
              })}
            />}
            label="Player controlled"
          />
          <FormControlLabel
            control={<Switch
              disabled={Boolean(state.player_controlled)}
              checked={Boolean(state.autonomy_enabled)}
              onChange={event => setState({ autonomy_enabled: event.target.checked })}
            />}
            label="NPC autonomy"
          />
          <TextField
            select
            label="Intervention frequency"
            value={String(state.intervention_frequency ?? "normal")}
            onChange={event => setState({ intervention_frequency: event.target.value })}
          >
            {["low", "normal", "high"].map(value =>
              <MenuItem key={value} value={value}>{value}</MenuItem>)}
          </TextField>
          <TextField
            select
            label="Default bullet-hell mode"
            value={String(state.bullethell_default_mode_id ?? "")}
            onChange={event => setState({
              bullethell_default_mode_id: event.target.value || null,
            })}
          >
            <MenuItem value="">Project default</MenuItem>
            {modes.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
          </TextField>
          <TextField
            select
            label="Enemy forced mode"
            value={String(state.bullethell_forced_mode_id ?? "")}
            onChange={event => setState({
              bullethell_forced_mode_id: event.target.value || null,
            })}
          >
            <MenuItem value="">None</MenuItem>
            {modes.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
          </TextField>
        </div>}

        {tab === 6 && <div className="character-fields">
          <TextField
            type="number"
            label="Full-body height factor"
            value={Number(state.full_body_height_factor ?? 0.5)}
            inputProps={{ min: 0, max: 1, step: 0.05 }}
            helperText="0 = child canvas (784×1552), 1 = tall canvas (784×2048); values between interpolate the height."
            onChange={event => {
              const value = Number(event.target.value);
              if (Number.isFinite(value)) {
                setState({ full_body_height_factor: Math.max(0, Math.min(1, value)) });
              }
            }}
          />
          <CreatableBoxedMultiselect
            label="Tags"
            options={draft.tags}
            value={draft.tags}
            onChange={(_event, next) => setDraft({ ...draft, tags: next })}
          />
          <TextField
            fullWidth
            multiline
            minRows={16}
            label="Advanced state JSON"
            value={draft.advancedState}
            onChange={event => setDraft({ ...draft, advancedState: event.target.value })}
          />
        </div>}

        {tab === 7 && <div className="entity-history">
          {history.map(event => <article key={String(event.id)}>
            <b>{String(event.event_type)}</b>
            <pre>{JSON.stringify(event.payload, null, 2)}</pre>
          </article>)}
        </div>}
      </section>
    </main>

    <aside className="character-editor-right-rail">
      <EntityImageSurface
        asset={fullBody}
        alt={`${draft.name || "Character"} full body`}
        className="character-fullbody-surface"
        placeholder="Full body"
        onGenerate={() => void generateMedia("full_body", viewOutfitId || null, false, fullBody)}
        onGenerateWithPrompt={() => void generateMedia("full_body", viewOutfitId || null, true, fullBody)}
        onRegenerate={asset => void generateMedia("full_body", viewOutfitId || null, false, asset)}
        onRegenerateWithPrompt={asset => void generateMedia("full_body", viewOutfitId || null, true, asset)}
        onDelete={asset => void removeMedia(asset)}
        onUpload={draft.id ? file => void upload("full_body", viewOutfitId || null, file) : undefined}
        loading={Boolean(fullBodyJob)}
        loadingLabel={fullBodyJob ? `Generating full body · ${fullBodyJob.status}` : undefined}
      />
      <div className="character-outfit-switcher">
        <button
          type="button"
          className="character-outfit-name"
          disabled={!selectedOutfit}
          onClick={() => {
            if (!selectedOutfit) return;
            chooseViewOutfit(selectedOutfit.id);
            setTab(1);
          }}
        >
          {selectedOutfit?.name ?? "No outfit"}
        </button>
        <TextField
          select
          size="small"
          aria-label="Viewed outfit"
          value={viewOutfitId}
          onChange={event => chooseViewOutfit(event.target.value)}
        >
          <MenuItem value="">No outfit look</MenuItem>
          {outfits.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
        </TextField>
        <Button
          className="character-outfit-segment"
          disabled={!selectedOutfit || activeOutfit?.id === selectedOutfit.id}
          onClick={() => selectedOutfit && void activateOutfit(selectedOutfit)}
        >
          {activeOutfit?.id === selectedOutfit?.id ? "Current" : "Wear"}
        </Button>
        <Button
          className="character-outfit-segment"
          disabled={!selectedOutfit}
          onClick={() => {
            if (!selectedOutfit) return;
            chooseViewOutfit(selectedOutfit.id);
            setTab(1);
          }}
        >Open</Button>
      </div>
    </aside>
  </div>;
}

function CharacterStatRail({
  definitions,
  values,
  onSetStat,
  onUpdateDefinition,
}: {
  definitions: StatDefinition[];
  values: Record<string, number>;
  onSetStat: (key: string, value: number) => Promise<void>;
  onUpdateDefinition: (
    definition: StatDefinition,
    patch: Partial<Pick<StatDefinition, "minimum" | "maximum">>,
  ) => Promise<void>;
}) {
  const [editing, setEditing] = useState<{
    id: string;
    value: string;
    save: (value: number) => Promise<void>;
  } | null>(null);

  const definitionsByKey = useMemo(
    () => Object.fromEntries(definitions.map(item => [item.stat_key, item])),
    [definitions],
  );

  const isRanged = (definition: StatDefinition) =>
    definition.display_style === "bar"
    || Boolean(definition.maximum_stat_key)
    || Boolean(definition.minimum_stat_key)
    || /^(hp|mp|health|mana|stamina|energy)$/i.test(definition.stat_key);

  const ordered = useMemo(() => {
    const known = definitions.filter(
      item => item.scope === "character" && item.stat_key in values,
    );
    const missingDefinitions = Object.keys(values)
      .filter(key => !definitionsByKey[key])
      .map(key => ({
        id: key,
        stat_key: key,
        label: key,
        scope: "character" as const,
        default_value: 0,
        minimum: 0,
        maximum: 100,
        integer_only: 0,
        visibility: "public",
      } as StatDefinition));

    return [...known, ...missingDefinitions].sort((a, b) => {
      const ranged = Number(isRanged(b)) - Number(isRanged(a));
      return ranged || a.label.localeCompare(b.label);
    });
  }, [definitions, definitionsByKey, values]);

  function bounds(definition: StatDefinition) {
    const minKey = definition.minimum_stat_key ?? undefined;
    const maxKey = definition.maximum_stat_key ?? undefined;
    const minimum = minKey && Number.isFinite(values[minKey])
      ? Number(values[minKey])
      : Number(definition.minimum);
    const maximum = maxKey && Number.isFinite(values[maxKey])
      ? Number(values[maxKey])
      : Number(definition.maximum);
    return { minimum, maximum, minKey, maxKey };
  }

  function beginEdit(
    id: string,
    value: number,
    save: (next: number) => Promise<void>,
  ) {
    setEditing({ id, value: String(value), save });
  }

  async function finishEdit() {
    if (!editing) return;
    const current = editing;
    setEditing(null);
    const value = Number(current.value);
    if (!Number.isFinite(value)) return;
    await current.save(value);
  }

  function chip(
    id: string,
    label: string,
    value: number,
    save: (next: number) => Promise<void>,
    title?: string,
  ) {
    if (editing?.id === id) {
      return <TextField
        key={id}
        className="character-stat-editor"
        size="small"
        autoFocus
        type="number"
        label={label}
        value={editing.value}
        onChange={event => setEditing({ ...editing, value: event.target.value })}
        onBlur={() => void finishEdit()}
        onKeyDown={event => {
          if (event.key === "Enter") void finishEdit();
          if (event.key === "Escape") setEditing(null);
        }}
      />;
    }
    return <Tooltip key={id} title={title ?? `${label}: ${value}`} arrow>
      <button
        type="button"
        className="character-stat-chip"
        onClick={() => beginEdit(id, value, save)}
      >
        <span className="character-stat-chip-label">{label}</span>
        <span className="character-stat-chip-value">{value}</span>
      </button>
    </Tooltip>;
  }

  return <div className="character-stat-box">
    <div className="character-stat-grid">
      {ordered.map(definition => {
        const value = Number(
          values[definition.stat_key] ?? definition.default_value ?? 0,
        );
        const { minimum, maximum, minKey, maxKey } = bounds(definition);
        const ranged = isRanged(definition);
        if (!ranged) {
          return chip(
            `${definition.stat_key}:value`,
            definition.label,
            value,
            next => onSetStat(definition.stat_key, next),
          );
        }

        const span = maximum - minimum;
        const ratio = span > 0
          ? Math.max(0, Math.min(1, (value - minimum) / span))
          : 0;
        const minimumColor = definition.minimum_color
          ?? (minKey ? definitionsByKey[minKey]?.color : null)
          ?? "#b94a48";
        const maximumColor = definition.maximum_color
          ?? (maxKey ? definitionsByKey[maxKey]?.color : null)
          ?? definition.color
          ?? "#5a9b63";
        const minDefinition = minKey ? definitionsByKey[minKey] : undefined;
        const maxDefinition = maxKey ? definitionsByKey[maxKey] : undefined;
        const tooltip = [
          `${definition.label}: ${value}`,
          `Minimum: ${minKey ? `${minDefinition?.label ?? minKey} = ` : ""}${minimum}`,
          `Maximum: ${maxKey ? `${maxDefinition?.label ?? maxKey} = ` : ""}${maximum}`,
        ].join("\n");

        return <Tooltip
          key={definition.stat_key}
          title={<span style={{ whiteSpace: "pre-line" }}>{tooltip}</span>}
          arrow
        >
          <div className="character-stat-group">
            <div className="character-stat-group-header">
              <b>{definition.label}</b>
              <span>{value} / {maximum}</span>
            </div>
            <span className="character-stat-track grouped">
              <span
                className="character-stat-fill"
                style={{
                  width: `${ratio * 100}%`,
                  background: `linear-gradient(90deg, ${minimumColor}, ${maximumColor})`,
                }}
              />
            </span>
            <div className="character-stat-group-chips">
              {chip(
                `${definition.stat_key}:value`,
                "Value",
                value,
                next => onSetStat(definition.stat_key, next),
                `${definition.label} value: ${value}`,
              )}
              {chip(
                `${definition.stat_key}:minimum`,
                minDefinition?.label ?? "Min",
                minimum,
                minKey
                  ? next => onSetStat(minKey, next)
                  : next => onUpdateDefinition(definition, { minimum: next }),
                minKey
                  ? `Minimum comes from stat ${minDefinition?.label ?? minKey}`
                  : `Raw minimum for ${definition.label}`,
              )}
              {chip(
                `${definition.stat_key}:maximum`,
                maxDefinition?.label ?? "Max",
                maximum,
                maxKey
                  ? next => onSetStat(maxKey, next)
                  : next => onUpdateDefinition(definition, { maximum: next }),
                maxKey
                  ? `Maximum comes from stat ${maxDefinition?.label ?? maxKey}`
                  : `Raw maximum for ${definition.label}`,
              )}
            </div>
          </div>
        </Tooltip>;
      })}
    </div>
  </div>;
}

function LinkedResourceList({
  title,
  ids,
  options,
  onRemove,
}: {
  title: string;
  ids: string[];
  options: WorldEntity[];
  onRemove: (id: string) => void;
}) {
  return <div>
    <h4>{title}</h4>
    <div className="character-linked-list">
      {ids.length === 0 && <small className="character-empty-note">Nothing selected.</small>}
      {ids.map(id => {
        const item = options.find(option => option.id === id);
        return <div className="character-linked-card" key={id}>
          <ResourceIcon
            name={item?.name ?? id}
            url={typeof item?.state.icon_url === "string" ? item.state.icon_url : undefined}
          />
          <span><b>{item?.name ?? `Unavailable (${id})`}</b><small>{item?.kind ?? "item"}</small></span>
          <Button color="error" onClick={() => onRemove(id)}>Remove</Button>
        </div>;
      })}
    </div>
  </div>;
}

function AbilityList({
  keys,
  abilities,
  onRemove,
}: {
  keys: string[];
  abilities: AbilityDefinition[];
  onRemove: (key: string) => void;
}) {
  return <div>
    <h4>Abilities</h4>
    <div className="character-linked-list">
      {keys.length === 0 && <small className="character-empty-note">No abilities assigned.</small>}
      {keys.map(key => {
        const ability = abilities.find(item => item.ability_key === key);
        return <div className="character-linked-card" key={key}>
          <ResourceIcon
            name={ability?.name ?? key}
            url={ability?.icon_url ?? undefined}
          />
          <span>
            <b>{ability?.name ?? key}</b>
            <small>{ability?.description || ability?.target_type || "Ability"}</small>
          </span>
          <Button color="error" onClick={() => onRemove(key)}>Remove</Button>
        </div>;
      })}
    </div>
  </div>;
}


function ResourceIcon({ name, url }: { name: string; url?: string }) {
  return <span className="character-linked-icon">
    {url
      ? <img src={url} alt="" />
      : name.slice(0, 1).toUpperCase()}
  </span>;
}
