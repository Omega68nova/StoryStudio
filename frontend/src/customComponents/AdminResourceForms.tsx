import type { ReactNode } from "react";
import { Alert, Button, Drawer, IconButton, TextField } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";

export function ResourceList({ title, query, setQuery, onAdd, addLabel = "Create", children }: { title: string; query: string; setQuery: (value: string) => void; onAdd?: () => void; addLabel?: string; children: ReactNode }) {
  return <section className="panel environment-resource"><div className="sheet-heading"><h2>{title}</h2>{onAdd && <Button onClick={onAdd}>{addLabel}</Button>}</div><TextField fullWidth size="small" label={`Search ${title.toLocaleLowerCase()}`} value={query} onChange={event => setQuery(event.target.value)} /><div className="environment-resource-list">{children}</div></section>;
}

export function ResourceButton({ enabled = true, active = false, title, subtitle, enabledLabel = "Enabled", disabledLabel = "Disabled", thumbnail, onClick }: { enabled?: boolean; active?: boolean; title: string; subtitle: string; enabledLabel?: string; disabledLabel?: string; thumbnail?: string | null; onClick: () => void }) {
  return <button className={`environment-resource-button${enabled ? "" : " disabled"}${active ? " active" : ""}`} onClick={onClick}>{thumbnail && <img className="resource-button-thumbnail" src={thumbnail} alt="" />}<span><b>{title}</b><small>{subtitle}</small></span><small>{enabled ? enabledLabel : disabledLabel}</small></button>;
}

export function RecordDrawer({ title, open, dirty, error, onClose, onSave, onArchive, archiveLabel, onDelete, children, width = 760 }: { title: string; open: boolean; dirty: boolean; error?: string; onClose: () => void; onSave: () => void; onArchive?: () => void; archiveLabel?: string; onDelete?: () => void; children: ReactNode; width?: number }) {
  return <Drawer anchor="right" open={open} onClose={onClose} PaperProps={{ className: "environment-editor-drawer", sx: { width: `min(${width}px, 100vw)` } }}><header><div><p className="eyebrow">ADMIN RECORD</p><h2>{title}</h2></div><IconButton aria-label="Close editor" onClick={onClose}><CloseIcon /></IconButton></header><div className="environment-editor-body">{error && <Alert severity="error">{error}</Alert>}{children}</div><footer>{dirty && <small>Unsaved changes</small>}<span>{onDelete && <Button color="error" startIcon={<DeleteOutlineIcon />} onClick={onDelete}>Delete</Button>}{onArchive && <Button color="warning" onClick={onArchive}>{archiveLabel ?? "Archive"}</Button>}<Button onClick={onClose}>Cancel</Button><Button variant="contained" onClick={onSave}>Save</Button></span></footer></Drawer>;
}
