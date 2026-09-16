import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, Stack, TextField, Typography } from "@mui/material";
import DeleteSweepIcon from "@mui/icons-material/DeleteSweep";
import CleaningServicesIcon from "@mui/icons-material/CleaningServices";
import { api } from "./api";
import type { DataSummary } from "./types";

type DestructiveAction = "story" | "factory" | "bible" | "jobs" | "jobs_all" | "planning_history" | null;

export function DataStudio({ projectId, revision, fail, changed }: { projectId?: string; revision: number; fail: (message: string) => void; changed: () => void }) {
  const [summary, setSummary] = useState<DataSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState<DestructiveAction>(null);
  const [confirmation, setConfirmation] = useState("");
  const load = useCallback(() => api<DataSummary>("/data/summary").then(setSummary), []);
  useEffect(() => { void load().catch((cause) => fail(String(cause))); }, [load, revision, fail]);

  const required = action === "factory" ? "DELETE ALL LOCAL DATA" : action === "story" ? "DELETE STORY CONTENT" : "CLEAR";
  async function execute() {
    if (!action || confirmation !== required) return;
    setBusy(true);
    try {
      if (action === "story") await api("/data/delete-story-content", { method: "POST", body: JSON.stringify({ confirmation }) });
      if (action === "factory") await api("/data/factory-reset", { method: "POST", body: JSON.stringify({ confirmation }) });
      if (action === "bible" && projectId) await api(`/projects/${projectId}/bible/clear`, { method: "POST" });
      if (action === "jobs") await api(`/jobs/history${projectId ? `?project_id=${projectId}` : ""}`, { method: "DELETE" });
      if (action === "jobs_all") await api("/jobs/history", { method: "DELETE" });
      if (action === "planning_history" && projectId) {
        const session = await api<{ id: string } | null>(`/projects/${projectId}/planning`);
        if (session) await api(`/planning/${session.id}/revisions`, { method: "DELETE" });
      }
      setAction(null); setConfirmation(""); changed(); await load();
    } catch (cause) { fail(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  }

  async function collect() {
    setBusy(true);
    try { await api("/data/garbage-collect", { method: "POST" }); await load(); }
    catch (cause) { fail(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  }

  return <div className="page data-page"><header className="page-header"><p className="eyebrow">LOCAL STORAGE</p><h1>Data management</h1><p>Inspect, recover, clear, or permanently remove StoryStudio-owned data. External models and runtimes are never touched.</p></header>
    {busy && <LinearProgress />}
    {summary && <>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 2 }}>
        <Chip label={`${formatBytes(summary.managed_disk_bytes)} managed media`} />
        <Chip color={summary.active_jobs.length ? "warning" : "success"} label={`${summary.active_jobs.length} active jobs`} />
        <Chip label={`${summary.trashed_story_nodes} trashed turns`} />
        <Chip color={summary.orphan_files.length || summary.dangling_fts_rows ? "warning" : "default"} label={`${summary.orphan_files.length} orphan files · ${summary.dangling_fts_rows} dangling search rows`} />
      </Stack>
      {(summary.orphan_files.length > 0 || summary.dangling_fts_rows > 0 || summary.file_failures.length > 0) && <Alert severity="warning" action={<Button onClick={() => void collect()} startIcon={<CleaningServicesIcon />}>Retry cleanup</Button>}>Integrity cleanup is available. Failed file removals remain listed and can be retried safely.</Alert>}
      <section className="data-grid">{Object.entries(summary.counts).map(([name, count]) => <Card variant="outlined" key={name}><CardContent><Typography variant="overline">{humanize(name)}</Typography><Typography variant="h4">{count}</Typography></CardContent></Card>)}</section>
      <section className="panel data-actions"><h2>Granular cleanup</h2><p>Object-specific archive and purge actions remain in Story, World, Music, and Workflows. These shortcuts clear non-canonical history without deleting your active world.</p><Stack direction="row" spacing={1} useFlexGap flexWrap="wrap"><Button onClick={() => setAction("jobs")}>Clear this story's terminal jobs</Button><Button onClick={() => setAction("jobs_all")}>Clear all terminal jobs</Button><Button disabled={!projectId} onClick={() => setAction("planning_history")}>Clear planning revisions</Button><Button disabled={!projectId} onClick={() => setAction("bible")}>Clear story bible text</Button><Button onClick={() => void collect()}>Remove orphaned files/index rows</Button></Stack></section>
      <section className="panel danger-zone"><h2>Bulk deletion</h2><p>Deleting story content keeps runtime settings, shared music, and workflow presets. Factory reset removes all StoryStudio-owned data and restores runtime settings.</p><Stack direction="row" spacing={1}><Button color="error" startIcon={<DeleteSweepIcon />} onClick={() => setAction("story")}>Delete all story content</Button><Button color="error" variant="contained" onClick={() => setAction("factory")}>Factory reset</Button></Stack></section>
    </>}
    <Dialog open={action !== null} onClose={() => !busy && setAction(null)}><DialogTitle>Confirm destructive action</DialogTitle><DialogContent><p>This cannot be undone. Type <strong>{required}</strong>.</p><TextField autoFocus fullWidth value={confirmation} onChange={(event) => setConfirmation(event.target.value)} label="Confirmation" /></DialogContent><DialogActions><Button onClick={() => setAction(null)}>Cancel</Button><Button color="error" variant="contained" disabled={confirmation !== required || busy} onClick={() => void execute()}>Confirm</Button></DialogActions></Dialog>
  </div>;
}

function formatBytes(value: number) { return value < 1024 * 1024 ? `${Math.round(value / 1024)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`; }
function humanize(value: string) { return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase()); }
