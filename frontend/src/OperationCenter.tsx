import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Box, Chip, Divider, Drawer, IconButton, LinearProgress, Stack, Tooltip, Typography } from "@mui/material";
import BoltIcon from "@mui/icons-material/Bolt";
import CloseIcon from "@mui/icons-material/Close";
import CancelOutlinedIcon from "@mui/icons-material/CancelOutlined";
import { api } from "./api";

type Job = { id: string; kind: string; status: string; phase?: string; progress_message?: string; progress_current?: number | null; progress_total?: number | null; error?: string | null; created_at: string; metrics?: { model_request_count?: number; time_to_first_token_ms?: number; load_count?: number; unload_count?: number; phase_durations_ms?: Record<string, number> } };

export function OperationCenter({ projectId, revision, fail }: { projectId: string; revision: number; fail: (message: string) => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [open, setOpen] = useState(false);
  const load = useCallback(() => api<Job[]>(`/jobs?project_id=${projectId}`).then((rows) => setJobs(rows.slice(0, 20))), [projectId]);
  useEffect(() => { void load().catch((cause) => fail(String(cause))); }, [load, revision, fail]);
  const active = jobs.filter((job) => ["queued", "running", "switching", "awaiting_review", "awaiting_minigame"].includes(job.status));
  const queued = jobs.filter((job) => job.status === "queued");
  useEffect(() => {
    if (!active.length) return;
    const timer = window.setInterval(() => void load(), 1000);
    return () => window.clearInterval(timer);
  }, [active.length, load]);
  const latest = active[0];
  return <>
    <Tooltip title={latest ? `Operations and recovery: ${latest.progress_message || latest.phase?.replaceAll("_", " ") || latest.status}` : "Operations and recovery"}><IconButton size="small" onClick={() => setOpen(true)} aria-label="Open operation center"><Badge badgeContent={queued.length} color="error" overlap="circular"><BoltIcon /></Badge></IconButton></Tooltip>
    <Drawer anchor="right" open={open} onClose={() => setOpen(false)}><Box className="operation-drawer"><Stack direction="row" justifyContent="space-between" alignItems="center"><Typography variant="h6">Operations</Typography><IconButton onClick={() => setOpen(false)} aria-label="Close operation center"><CloseIcon /></IconButton></Stack><Divider />
      {!jobs.length && <Typography color="text.secondary" sx={{ mt: 2 }}>No operations yet.</Typography>}
      {jobs.map((job) => {
        const determinate = Number(job.progress_total) > 0;
        const value = determinate ? Math.min(100, Number(job.progress_current) / Number(job.progress_total) * 100) : 0;
        const running = active.includes(job);
        return <Box key={job.id} sx={{ py: 1.5 }}><Stack direction="row" justifyContent="space-between"><Typography variant="subtitle2">{job.kind.replaceAll("_", " ")}</Typography><Chip size="small" label={job.status} color={job.status === "failed" ? "error" : running ? "warning" : "default"} /></Stack><Typography variant="caption" color="text.secondary">{job.progress_message || job.phase?.replaceAll("_", " ")}</Typography>{job.metrics && <Typography display="block" variant="caption" color="text.secondary">{job.metrics.model_request_count ?? 0} model request(s){job.metrics.time_to_first_token_ms != null ? ` · first token ${(job.metrics.time_to_first_token_ms / 1000).toFixed(1)}s` : ""}{job.metrics.load_count || job.metrics.unload_count ? ` · ${job.metrics.load_count ?? 0} load / ${job.metrics.unload_count ?? 0} unload` : ""}</Typography>}{running && <Stack direction="row" alignItems="center" spacing={1}><LinearProgress sx={{ mt: .5, flex: 1 }} variant={determinate ? "determinate" : "indeterminate"} value={value} /><Tooltip title="Cancel action"><IconButton size="small" color="error" aria-label={`Cancel ${job.kind} action`} onClick={() => void api(`/jobs/${job.id}/cancel`, { method: "POST" }).then(load).catch((cause) => fail(String(cause)))}><CancelOutlinedIcon /></IconButton></Tooltip></Stack>}{job.error && <Alert severity="error" sx={{ mt: .5 }}>{job.error}</Alert>}<Divider sx={{ mt: 1 }} /></Box>;
      })}
    </Box></Drawer>
  </>;
}
