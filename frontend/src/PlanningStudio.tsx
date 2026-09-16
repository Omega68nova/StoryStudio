import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { PlanningConflict, PlanningResolution, PlanningSession } from "./types";
import { Alert, Box, Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, LinearProgress, MenuItem, Stack, TextField, Tooltip, Typography } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import AutoFixHighIcon from "@mui/icons-material/AutoFixHigh";

const emptyDraft = { summary: "", notes: [], entities: [], relations: [] };

export function PlanningStudio({ projectId, revision, fail }: { projectId: string; revision: number; fail: (message: string) => void }) {
  const [session, setSession] = useState<PlanningSession | null>(null);
  const [counts, setCounts] = useState({ major_locations: 4, secondary_locations: 12, characters: 8, direction: "" });
  const [prompts, setPrompts] = useState<Record<number, string>>({});
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [reopenStage, setReopenStage] = useState<number | null>(null);
  const [conflicts, setConflicts] = useState<PlanningConflict[]>([]);
  const [resolutions, setResolutions] = useState<Record<string, PlanningResolution>>({});
  const [approvalStage, setApprovalStage] = useState<number | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteMode, setDeleteMode] = useState<"keep_world" | "remove_world">("keep_world");
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [automationOpen, setAutomationOpen] = useState(false);
  const [automationPrompt, setAutomationPrompt] = useState("");
  const dirtyDrafts = useRef<Set<number>>(new Set());
  const dirtyPrompts = useRef<Set<number>>(new Set());

  const load = useCallback(async () => {
    const current = await api<PlanningSession | null>(`/projects/${projectId}/planning`);
    setSession(current);
    if (!current) return;
    setPrompts((existing) => {
      const next = { ...existing };
      for (const stage of current.stages) if (!dirtyPrompts.current.has(stage.stage_number)) next[stage.stage_number] = stage.human_prompt ?? "";
      return next;
    });
    setDrafts((existing) => {
      const next = { ...existing };
      for (const stage of current.stages) {
        if (!dirtyDrafts.current.has(stage.stage_number)) next[stage.stage_number] = stage.raw_draft_text ?? JSON.stringify(stage.draft ?? stage.approved ?? emptyDraft, null, 2);
      }
      return next;
    });
  }, [projectId]);

  useEffect(() => { dirtyDrafts.current.clear(); dirtyPrompts.current.clear(); setDrafts({}); setPrompts({}); document.body.dataset.storyStudioUnsaved = "false"; return () => { document.body.dataset.storyStudioUnsaved = "false"; }; }, [projectId]);
  useEffect(() => { void load().catch((cause) => fail(String(cause))); }, [load, revision, fail]);
  useEffect(() => {
    if (!session?.stages.some((stage) => ["queued", "generating"].includes(stage.status))) return;
    const timer = window.setInterval(() => void load().catch((cause) => fail(String(cause))), 750);
    return () => window.clearInterval(timer);
  }, [session, load, fail]);
  useEffect(() => { const warning = (event: BeforeUnloadEvent) => { if (dirtyDrafts.current.size || dirtyPrompts.current.size) event.preventDefault(); }; window.addEventListener("beforeunload", warning); return () => window.removeEventListener("beforeunload", warning); }, []);

  async function create() {
    try { setSession(await api(`/projects/${projectId}/planning`, { method: "POST", body: JSON.stringify(counts) })); }
    catch (cause) { fail(String(cause)); }
  }

  async function generate(stageNumber: number, repair = false, automate = false, sharedPrompt = "") {
    try {
      dirtyDrafts.current.delete(stageNumber); dirtyPrompts.current.delete(stageNumber);
      if (!dirtyDrafts.current.size && !dirtyPrompts.current.size) document.body.dataset.storyStudioUnsaved = "false";
      await api(`/planning/${session!.id}/stages/${stageNumber}/generate`, { method: "POST", body: JSON.stringify({ prompt: sharedPrompt || prompts[stageNumber] || "", repair, automate, automation_prompt: sharedPrompt }) });
      await load();
    } catch (cause) { fail(errorMessage(cause)); }
  }

  async function saveOrApprove(stageNumber: number, approve: boolean) {
    try {
      const draft = JSON.parse(drafts[stageNumber]);
      if (approve) {
        const preflight = await api<{ conflicts: PlanningConflict[] }>(`/planning/${session!.id}/stages/${stageNumber}/preflight`, { method: "POST", body: JSON.stringify({ draft }) });
        if (preflight.conflicts.length) {
          setConflicts(preflight.conflicts); setApprovalStage(stageNumber);
          setResolutions(Object.fromEntries(preflight.conflicts.filter((item) => item.recommended_resolution).map((item) => [item.entity_key, item.recommended_resolution!])))
          return;
        }
      }
      await api(`/planning/${session!.id}/stages/${stageNumber}${approve ? "/approve" : ""}`, { method: approve ? "POST" : "PUT", body: JSON.stringify({ draft }) });
      dirtyDrafts.current.delete(stageNumber);
      if (!dirtyDrafts.current.size && !dirtyPrompts.current.size) document.body.dataset.storyStudioUnsaved = "false";
      await load();
    } catch (cause) { fail(errorMessage(cause)); }
  }

  async function approveResolved() {
    if (approvalStage === null) return;
    try {
      const draft = JSON.parse(drafts[approvalStage]);
      await api(`/planning/${session!.id}/stages/${approvalStage}/approve`, { method: "POST", body: JSON.stringify({ draft, resolutions }) });
      dirtyDrafts.current.delete(approvalStage); setApprovalStage(null); setConflicts([]); setResolutions({}); await load();
    } catch (cause) { fail(errorMessage(cause)); }
  }

  async function deleteSession() {
    try {
      await api(`/planning/${session!.id}`, { method: "DELETE", body: JSON.stringify({ mode: deleteMode, confirmation: deleteConfirmation }) });
      setDeleteOpen(false); setSession(null);
    } catch (cause) { fail(errorMessage(cause)); }
  }

  async function reopen() {
    if (reopenStage === null || !session) return;
    try { await api(`/planning/${session.id}/stages/${reopenStage}/reopen`, { method: "POST" }); setReopenStage(null); await load(); }
    catch (cause) { fail(errorMessage(cause)); }
  }

  if (!session) return <div className="page"><header className="page-header"><p className="eyebrow">WORLD WORKSHOP</p><h1>Preplan the story</h1><p>Build the setting in six editable stages. You may skip this and let the world grow during play.</p></header><section className="panel setup-grid">
    <TextField type="number" label="Major locations" value={counts.major_locations} onChange={(e) => setCounts({ ...counts, major_locations: Number(e.target.value) })} />
    <TextField type="number" label="Secondary locations" value={counts.secondary_locations} onChange={(e) => setCounts({ ...counts, secondary_locations: Number(e.target.value) })} />
    <TextField type="number" label="Significant characters" value={counts.characters} onChange={(e) => setCounts({ ...counts, characters: Number(e.target.value) })} />
    <TextField className="wide" multiline minRows={5} label="Creative direction" value={counts.direction} onChange={(e) => setCounts({ ...counts, direction: e.target.value })} placeholder="Premise, influences, boundaries, or ideas to explore…" />
    <Button variant="contained" onClick={() => void create()}>Start workshop</Button>
  </section></div>;

  return <div className="page planning-page"><header className="page-header"><p className="eyebrow">WORLD WORKSHOP</p><Stack direction="row" justifyContent="space-between" alignItems="center"><h1>Preplanning</h1><Stack direction="row"><Tooltip title="Automatically generate the remaining planning stages"><span><IconButton aria-label="Automate remaining planning stages" disabled={session.status === "completed" || session.stages.some((stage) => ["queued", "generating"].includes(stage.status))} onClick={() => { setAutomationPrompt(String(session.settings.direction ?? "")); setAutomationOpen(true); }}><PlayArrowIcon /></IconButton></span></Tooltip><Button color="error" onClick={() => setDeleteOpen(true)}>Delete workshop</Button></Stack></Stack><p>{session.status === "completed" ? "The approved world plan is now canonical." : `Stage ${session.current_stage} of 6. Each stage keeps your notes separate from the AI draft.`}</p>{session.recovery_warnings?.map((warning) => <Alert severity="warning" key={warning.code}>{warning.message}</Alert>)}</header>
    <div className="stage-list">{session.stages.map((stage) => {
      const locked = stage.stage_number > session.current_stage && stage.status !== "approved";
      const generating = ["queued", "generating"].includes(stage.status);
      const operation = stage.operation;
      const measurable = Number(operation?.progress_total ?? 0) > 0;
      const progress = measurable ? Math.min(100, (Number(operation?.progress_current ?? 0) / Number(operation?.progress_total)) * 100) : 0;
      const elapsed = operation?.created_at ? Math.max(0, Math.round((Date.now() - new Date(operation.created_at).getTime()) / 1000)) : 0;
      return <section className={`panel planning-stage ${stage.status}`} key={stage.id}><header><div><span>{stage.stage_number}</span><h2>{humanize(stage.kind)}</h2></div><b>{stage.status}</b></header>
        {!locked && stage.status !== "approved" && <>
          <TextField fullWidth multiline minRows={3} label="1. Initial human prompt (optional)" value={prompts[stage.stage_number] ?? ""} disabled={generating} onChange={(e) => { dirtyPrompts.current.add(stage.stage_number); document.body.dataset.storyStudioUnsaved = "true"; setPrompts({ ...prompts, [stage.stage_number]: e.target.value }); }} placeholder="Ideas, requirements, exclusions, or leave blank for the AI…" />
          {stage.validation_error && <Alert severity="warning" action={<Button startIcon={<AutoFixHighIcon />} disabled={generating} onClick={() => void generate(stage.stage_number, true)}>Ask AI to repair</Button>}>The AI response was preserved but is not valid structured data: {stage.validation_error}. Edit it below and save, or ask the AI to repair it.</Alert>}
          <div className="button-row">{generating && stage.active_job_id && <Button color="error" onClick={() => void api(`/jobs/${stage.active_job_id}/cancel`, { method: "POST" }).then(load).catch((cause) => fail(errorMessage(cause)))}>Cancel</Button>}<Button variant="outlined" disabled={generating} onClick={() => void generate(stage.stage_number)}>{generating ? "AI is working…" : stage.draft ? "Regenerate AI response" : "Generate AI response"}</Button></div>{generating && <Box sx={{ my: 1 }} role="status" aria-live="polite"><Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1} sx={{ mb: .5 }}><Typography variant="caption">{operation?.progress_message || (stage.status === "queued" ? "Waiting in the operation queue" : "Preparing planning stage")}</Typography><Chip size="small" label={`${elapsed}s`} /></Stack><LinearProgress variant={measurable ? "determinate" : "indeterminate"} value={progress} /><Typography display="block" variant="caption" color="text.secondary" sx={{ mt: .5 }}>{humanize(operation?.phase || stage.status)}{measurable ? ` · approximately ${Math.round(Number(operation?.progress_current ?? 0))}/${Math.round(Number(operation?.progress_total))} output tokens` : ""}</Typography></Box>}
          <strong>2. AI-generated response <small>editable structured cards</small></strong><PlanningDraftEditor value={drafts[stage.stage_number] ?? ""} disabled={generating} onChange={(value) => { dirtyDrafts.current.add(stage.stage_number); document.body.dataset.storyStudioUnsaved = "true"; setDrafts({ ...drafts, [stage.stage_number]: value }); }} />
          <div className="button-row"><Button disabled={generating} onClick={() => void saveOrApprove(stage.stage_number, false)}>Save manual changes</Button><Button variant="contained" disabled={generating} onClick={() => void saveOrApprove(stage.stage_number, true)}>Save & approve stage</Button></div>
        </>}
        {stage.status === "approved" && <><p className="approved-summary">{stage.approved?.summary as string}</p><Button onClick={() => setReopenStage(stage.stage_number)}>Reopen from this stage</Button></>}
        {locked && <p className="muted">Approve the previous stage to unlock this one.</p>}
      </section>;
    })}</div><Dialog open={automationOpen} onClose={() => setAutomationOpen(false)}><DialogTitle>Automate preplanning</DialogTitle><DialogContent sx={{ pt: "12px !important" }}><TextField fullWidth multiline minRows={5} label="Shared direction for every remaining stage" value={automationPrompt} onChange={(event) => setAutomationPrompt(event.target.value)} helperText="StoryStudio will generate and approve unambiguous drafts in order. It pauses for malformed output or conflicts requiring your decision." /></DialogContent><DialogActions><Button onClick={() => setAutomationOpen(false)}>Cancel</Button><Button variant="contained" startIcon={<PlayArrowIcon />} onClick={() => { const stage = session.current_stage; setAutomationOpen(false); void generate(stage, false, true, automationPrompt); }}>Start</Button></DialogActions></Dialog><Dialog open={reopenStage !== null} onClose={() => setReopenStage(null)}><DialogTitle>Reopen planning stage?</DialogTitle><DialogContent><p>Approvals after this stage will be invalidated. Their revisions remain in history, and their world transactions become inactive.</p></DialogContent><DialogActions><Button onClick={() => setReopenStage(null)}>Cancel</Button><Button variant="contained" onClick={() => void reopen()}>Reopen and backtrack</Button></DialogActions></Dialog>
    <Dialog open={approvalStage !== null} onClose={() => setApprovalStage(null)} maxWidth="md" fullWidth><DialogTitle>Resolve existing-world conflicts</DialogTitle><DialogContent>{conflicts.map((conflict) => <Card variant="outlined" sx={{ my: 1 }} key={conflict.entity_key}><CardContent><strong>{String(conflict.proposed.name)}</strong><p>A world entity with this name or alias already exists.</p><TextField select fullWidth label="Resolution" value={resolutions[conflict.entity_key]?.action ?? ""} onChange={(event) => { const action = event.target.value as PlanningResolution["action"]; const candidate = conflict.candidates[0]; setResolutions({ ...resolutions, [conflict.entity_key]: { action, ...(action === "link" || action === "merge" ? { entity_id: candidate?.id } : {}) } }); }}><MenuItem value="link">Link unchanged</MenuItem><MenuItem value="merge">Merge proposed changes</MenuItem><MenuItem value="rename">Create renamed</MenuItem><MenuItem value="omit">Omit from plan</MenuItem></TextField>{["link", "merge"].includes(resolutions[conflict.entity_key]?.action) && <TextField select fullWidth sx={{ mt: 1 }} label="Existing entity" value={resolutions[conflict.entity_key]?.entity_id ?? ""} onChange={(event) => setResolutions({ ...resolutions, [conflict.entity_key]: { ...resolutions[conflict.entity_key], entity_id: event.target.value } })}>{conflict.candidates.map((candidate) => <MenuItem key={candidate.id} value={candidate.id}>{candidate.name} ({candidate.kind})</MenuItem>)}</TextField>}{resolutions[conflict.entity_key]?.action === "rename" && <TextField fullWidth sx={{ mt: 1 }} label="Unique new name" value={resolutions[conflict.entity_key]?.new_name ?? ""} onChange={(event) => setResolutions({ ...resolutions, [conflict.entity_key]: { ...resolutions[conflict.entity_key], new_name: event.target.value } })} />}</CardContent></Card>)}</DialogContent><DialogActions><Button onClick={() => setApprovalStage(null)}>Cancel</Button><Button variant="contained" disabled={conflicts.some((item) => !resolutions[item.entity_key] || (resolutions[item.entity_key].action === "rename" && !resolutions[item.entity_key].new_name?.trim()))} onClick={() => void approveResolved()}>Apply resolutions and approve</Button></DialogActions></Dialog>
    <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)}><DialogTitle>Delete planning workshop</DialogTitle><DialogContent sx={{ display: "grid", gap: 2, pt: "12px !important" }}><TextField select label="Approved world data" value={deleteMode} onChange={(event) => setDeleteMode(event.target.value as typeof deleteMode)}><MenuItem value="keep_world">Keep approved world</MenuItem><MenuItem value="remove_world">Remove linked world data</MenuItem></TextField><Alert severity={deleteMode === "remove_world" ? "warning" : "info"}>{deleteMode === "remove_world" ? "Linked transactions, entities, relations, and lore versions will be permanently removed. Ambiguous legacy links are blocked." : "The workshop and revisions will be deleted; its approved world remains."}</Alert><TextField label="Type DELETE PLANNING" value={deleteConfirmation} onChange={(event) => setDeleteConfirmation(event.target.value)} /></DialogContent><DialogActions><Button onClick={() => setDeleteOpen(false)}>Cancel</Button><Button color="error" disabled={deleteConfirmation !== "DELETE PLANNING"} onClick={() => void deleteSession()}>Delete</Button></DialogActions></Dialog>
  </div>;
}

function humanize(value: string) { return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase()); }
function errorMessage(cause: unknown) { return cause instanceof Error ? cause.message : String(cause); }

function PlanningDraftEditor({ value, disabled, onChange }: { value: string; disabled: boolean; onChange: (value: string) => void }) {
  let draft: any = emptyDraft; try { draft = JSON.parse(value || "{}"); } catch { return <TextField fullWidth multiline minRows={8} error label="Invalid draft JSON" value={value} onChange={(e) => onChange(e.target.value)} />; }
  const update = (next: any) => onChange(JSON.stringify(next, null, 2));
  const entities = Array.isArray(draft.entities) ? draft.entities : []; const relations = Array.isArray(draft.relations) ? draft.relations : []; const notes = Array.isArray(draft.notes) ? draft.notes : [];
  return <div className="planning-structured"><TextField fullWidth multiline minRows={2} label="Stage summary" disabled={disabled} value={draft.summary ?? ""} onChange={(e) => update({ ...draft, summary: e.target.value })} /><TextField fullWidth multiline minRows={2} label="Notes (one per line)" disabled={disabled} value={notes.join("\n")} onChange={(e) => update({ ...draft, notes: e.target.value.split("\n").filter(Boolean) })} /><h3>Entities</h3>{entities.map((entity: any, index: number) => <Card variant="outlined" key={`${entity.key}-${index}`}><CardContent className="planning-card-fields"><TextField label="Stable key" value={entity.key ?? ""} onChange={(e) => { const next=[...entities]; next[index]={...entity,key:e.target.value}; update({...draft,entities:next}); }} /><TextField select label="Kind" value={entity.kind ?? "character"} onChange={(e) => { const next=[...entities]; next[index]={...entity,kind:e.target.value}; update({...draft,entities:next}); }}>{["character","location","faction","item","lore_system","fact","plot_beat"].map((kind) => <MenuItem key={kind} value={kind}>{humanize(kind)}</MenuItem>)}</TextField><TextField label="Name" value={entity.name ?? ""} onChange={(e) => { const next=[...entities]; next[index]={...entity,name:e.target.value}; update({...draft,entities:next}); }} /><Button color="error" onClick={() => update({...draft,entities:entities.filter((_: any,i:number)=>i!==index)})}>Remove</Button></CardContent></Card>)}<Button onClick={() => update({...draft,entities:[...entities,{key:"",kind:"character",name:"",aliases:[],tags:[],state:{}}]})}>Add entity</Button><h3>Routes and relationships</h3>{relations.map((relation:any,index:number)=><Card variant="outlined" key={index}><CardContent className="planning-card-fields"><TextField label="From key" value={relation.source_key ?? ""} onChange={(e)=>{const next=[...relations];next[index]={...relation,source_key:e.target.value};update({...draft,relations:next});}}/><TextField label="To key" value={relation.target_key ?? ""} onChange={(e)=>{const next=[...relations];next[index]={...relation,target_key:e.target.value};update({...draft,relations:next});}}/><TextField label="Relation" value={relation.relation ?? ""} onChange={(e)=>{const next=[...relations];next[index]={...relation,relation:e.target.value};update({...draft,relations:next});}}/><Button color="error" onClick={()=>update({...draft,relations:relations.filter((_:any,i:number)=>i!==index)})}>Remove</Button></CardContent></Card>)}<Button onClick={()=>update({...draft,relations:[...relations,{source_key:"",target_key:"",relation:"route",travel_minutes:0,modes:["walk"],bidirectional:true}]})}>Add relation</Button></div>;
}
