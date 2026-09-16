import { useEffect, useState } from "react";
import { Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Paper, Stack, TextField } from "@mui/material";
import { api } from "./api";
import type { AuthUser, ProjectSummary } from "./types";

export function UsersStudio({ projects, fail }: { projects: ProjectSummary[]; fail: (message: string) => void }) {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "member">("member");
  const [resetUser, setResetUser] = useState<AuthUser | null>(null);
  const [deleteUser, setDeleteUser] = useState<AuthUser | null>(null);
  const [resetPassword, setResetPassword] = useState("");

  async function load() {
    try { setUsers(await api<AuthUser[]>("/admin/users")); }
    catch (cause) { fail(cause instanceof Error ? cause.message : String(cause)); }
  }
  useEffect(() => { void load(); }, []);

  async function create() {
    try {
      await api("/admin/users", { method: "POST", body: JSON.stringify({ username, password, role }) });
      setUsername(""); setPassword(""); setRole("member"); await load();
    } catch (cause) { fail(cause instanceof Error ? cause.message : String(cause)); }
  }
  async function update(user: AuthUser, changes: Record<string, unknown>) {
    try { await api(`/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify(changes) }); await load(); }
    catch (cause) { fail(cause instanceof Error ? cause.message : String(cause)); }
  }
  async function assign(user: AuthUser, projectId: string, checked: boolean) {
    const ids = new Set(user.project_ids ?? []);
    if (checked) ids.add(projectId); else ids.delete(projectId);
    try { await api(`/admin/users/${user.id}/projects`, { method: "PUT", body: JSON.stringify({ project_ids: [...ids] }) }); await load(); }
    catch (cause) { fail(cause instanceof Error ? cause.message : String(cause)); }
  }
  async function reset() {
    if (!resetUser) return;
    try {
      await api(`/admin/users/${resetUser.id}/reset-password`, { method: "POST", body: JSON.stringify({ password: resetPassword }) });
      setResetUser(null); setResetPassword("");
    } catch (cause) { fail(cause instanceof Error ? cause.message : String(cause)); }
  }
  async function remove() {
    if (!deleteUser) return;
    try { await api(`/admin/users/${deleteUser.id}`, { method: "DELETE" }); setDeleteUser(null); await load(); }
    catch (cause) { fail(cause instanceof Error ? cause.message : String(cause)); }
  }

  return <section className="settings-panel users-studio">
    <h2>Users</h2>
    <Alert severity="info">Members can open only assigned stories. Password resets revoke every active session for that account.</Alert>
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1}>
        <TextField label="Username" value={username} onChange={event => setUsername(event.target.value)} />
        <TextField label="Temporary password" type="password" value={password} onChange={event => setPassword(event.target.value)} />
        <TextField select label="Role" value={role} onChange={event => setRole(event.target.value as typeof role)}>
          <MenuItem value="member">Member</MenuItem><MenuItem value="admin">Administrator</MenuItem>
        </TextField>
        <Button variant="contained" disabled={!username.trim() || password.length < 8} onClick={() => void create()}>Create account</Button>
      </Stack>
    </Paper>
    <div className="users-list">
      {users.map(user => <Paper variant="outlined" sx={{ p: 2 }} key={user.id}>
        <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
          <strong>{user.username}</strong>
          <TextField select size="small" label="Role" value={user.role} onChange={event => void update(user, { role: event.target.value })}>
            <MenuItem value="member">Member</MenuItem><MenuItem value="admin">Administrator</MenuItem>
          </TextField>
          <FormControlLabel control={<Checkbox checked={user.enabled !== false} onChange={event => void update(user, { enabled: event.target.checked })} />} label="Enabled" />
          <Button onClick={() => setResetUser(user)}>Reset password</Button>
          <Button color="error" onClick={() => setDeleteUser(user)}>Delete</Button>
        </Stack>
        <div>
          {projects.map(project => <FormControlLabel key={project.id} control={<Checkbox checked={(user.project_ids ?? []).includes(project.id)} onChange={event => void assign(user, project.id, event.target.checked)} />} label={project.title} />)}
        </div>
      </Paper>)}
    </div>
    <Dialog open={Boolean(resetUser)} onClose={() => setResetUser(null)}>
      <DialogTitle>Reset {resetUser?.username}&apos;s password</DialogTitle>
      <DialogContent><TextField autoFocus sx={{ mt: 1 }} label="New password" type="password" value={resetPassword} onChange={event => setResetPassword(event.target.value)} /></DialogContent>
      <DialogActions><Button onClick={() => setResetUser(null)}>Cancel</Button><Button variant="contained" disabled={resetPassword.length < 8} onClick={() => void reset()}>Reset and revoke sessions</Button></DialogActions>
    </Dialog>
    <Dialog open={Boolean(deleteUser)} onClose={() => setDeleteUser(null)}>
      <DialogTitle>Delete {deleteUser?.username}?</DialogTitle>
      <DialogContent>The account and its sessions will be removed. Existing story passages keep the username snapshot.</DialogContent>
      <DialogActions><Button onClick={() => setDeleteUser(null)}>Cancel</Button><Button color="error" variant="contained" onClick={() => void remove()}>Delete account</Button></DialogActions>
    </Dialog>
  </section>;
}
