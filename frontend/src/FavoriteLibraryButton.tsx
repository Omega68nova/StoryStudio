import { useMemo, useState } from "react";
import {
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
} from "@mui/material";
import FavoriteBorderOutlinedIcon from "@mui/icons-material/FavoriteBorderOutlined";
import FavoriteOutlinedIcon from "@mui/icons-material/FavoriteOutlined";
import { api } from "./api";

export type FavoriteSourceKind =
  | "character"
  | "location"
  | "item"
  | "outfit"
  | "faction"
  | "lore_system"
  | "fact"
  | "plot_beat"
  | "stat"
  | "effect"
  | "ability";

type FavoriteDependency = {
  token: string;
  source_kind: FavoriteSourceKind;
  source_key: string;
  name: string;
  relation: string;
  default_selected: boolean;
  has_changed: boolean;
  original_available: boolean;
  parent_token: string;
  depth: number;
};

type FavoritePreview = {
  source_kind: FavoriteSourceKind;
  source_key: string;
  token: string;
  name: string;
  description: string;
  tags: string[];
  has_changed: boolean;
  original_available: boolean;
  already_favorited: boolean;
  library_resource_id?: string | null;
  dependencies: FavoriteDependency[];
};

type VersionChoice = "original" | "latest" | "both";

export function FavoriteLibraryButton({
  projectId,
  sourceKind,
  sourceKey,
  compact = true,
  onFavorited,
}: {
  projectId: string;
  sourceKind: FavoriteSourceKind;
  sourceKey: string;
  compact?: boolean;
  onFavorited?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<FavoritePreview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [version, setVersion] = useState<VersionChoice>("latest");
  const [dependencyVersions, setDependencyVersions] = useState<Record<string, VersionChoice>>({});
  const [error, setError] = useState("");
  const [favorited, setFavorited] = useState(false);

  const selectedCount = selected.size;
  const allSelected = useMemo(
    () => Boolean(preview?.dependencies.length) && preview!.dependencies.every(item => selected.has(item.token)),
    [preview, selected],
  );

  async function inspect() {
    setLoading(true);
    setError("");
    try {
      const next = await api<FavoritePreview>("/projects/" + projectId + "/library/favorite-preview", {
        method: "POST",
        body: JSON.stringify({ source_kind: sourceKind, source_key: sourceKey }),
      });
      setPreview(next);
      setFavorited(next.already_favorited);
      setVersion("latest");
      setSelected(new Set(next.dependencies.filter(item => item.default_selected).map(item => item.token)));
      setDependencyVersions(Object.fromEntries(
        next.dependencies.map(item => [item.token, "latest" as VersionChoice]),
      ));
      setOpen(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setOpen(true);
    } finally {
      setLoading(false);
    }
  }

  async function publish() {
    if (!preview) return;
    setLoading(true);
    setError("");
    try {
      await api("/projects/" + projectId + "/library/favorite", {
        method: "POST",
        body: JSON.stringify({
          source_kind: sourceKind,
          source_key: sourceKey,
          version,
          dependency_tokens: [...selected],
          dependency_versions: dependencyVersions,
          tags: preview.tags ?? [],
        }),
      });
      setFavorited(true);
      setOpen(false);
      onFavorited?.();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }

  function toggle(token: string, checked: boolean) {
    setSelected(current => {
      const next = new Set(current);
      if (checked) next.add(token);
      else {
        next.delete(token);
        if (preview) {
          let changed = true;
          while (changed) {
            changed = false;
            for (const item of preview.dependencies) {
              if (next.has(item.token) && !next.has(item.parent_token) && item.parent_token !== preview.token) {
                next.delete(item.token);
                changed = true;
              }
            }
          }
        }
      }
      return next;
    });
  }

  return <>
    <Tooltip title={favorited ? "Update favorite in Global Library" : "Favorite to Global Library"}>
      <span>
        <IconButton
          size={compact ? "small" : "medium"}
          aria-label="Favorite to Global Library"
          disabled={loading}
          onClick={event => {
            event.stopPropagation();
            void inspect();
          }}
        >
          {favorited ? <FavoriteOutlinedIcon fontSize="small" /> : <FavoriteBorderOutlinedIcon fontSize="small" />}
        </IconButton>
      </span>
    </Tooltip>

    <Dialog open={open} onClose={() => !loading && setOpen(false)} maxWidth="md" fullWidth>
      <DialogTitle>Favorite {preview?.name ?? sourceKey}</DialogTitle>
      <DialogContent className="favorite-library-dialog">
        {error && <p className="favorite-library-error">{error}</p>}
        {preview && <>
          <p>
            Save this record as a reusable Global Library resource. Dependencies become an explicit tree and remain independent from this story after import.
          </p>

          {preview.has_changed && preview.original_available ? <TextField
            select
            fullWidth
            size="small"
            label="Version to favorite"
            value={version}
            onChange={event => setVersion(event.target.value as VersionChoice)}
          >
            <MenuItem value="original">Original version</MenuItem>
            <MenuItem value="latest">Latest version on this branch</MenuItem>
            <MenuItem value="both">Both as separate revisions</MenuItem>
          </TextField> : <small className="favorite-library-version-note">
            This record has no distinct earlier branch version, so the latest version will be saved.
          </small>}

          <section className="favorite-library-dependencies">
            <header>
              <div>
                <b>Dependencies</b>
                <small>{selectedCount} selected · uncheck anything you do not want bundled with the parent.</small>
              </div>
              <Stack direction="row" spacing={1}>
                <Button size="small" onClick={() => setSelected(new Set())}>None</Button>
                <Button
                  size="small"
                  onClick={() => preview && setSelected(new Set(preview.dependencies.map(item => item.token)))}
                >
                  {allSelected ? "All selected" : "All"}
                </Button>
              </Stack>
            </header>

            {preview.dependencies.length === 0 && <p className="muted">No reusable dependencies were detected.</p>}
            {preview.dependencies.map(item => {
              const parentMissing = item.parent_token !== preview.token && !selected.has(item.parent_token);
              const checked = selected.has(item.token);
              return <div
                className={"favorite-library-dependency" + (parentMissing ? " parent-missing" : "")}
                key={item.token}
                style={{ paddingLeft: String(Math.min(item.depth, 5) * 18) + "px" }}
              >
                <FormControlLabel
                  control={<Checkbox
                    checked={checked}
                    disabled={parentMissing}
                    onChange={event => toggle(item.token, event.target.checked)}
                  />}
                  label={<span>
                    <b>{item.name}</b>
                    <small>{item.source_kind.replaceAll("_", " ")} · {item.relation.replaceAll("_", " ")}</small>
                  </span>}
                />
                {checked && item.has_changed && item.original_available && <TextField
                  select
                  size="small"
                  label="Version"
                  value={dependencyVersions[item.token] ?? "latest"}
                  onChange={event => setDependencyVersions(current => ({
                    ...current,
                    [item.token]: event.target.value as VersionChoice,
                  }))}
                >
                  <MenuItem value="original">Original</MenuItem>
                  <MenuItem value="latest">Latest</MenuItem>
                  <MenuItem value="both">Both</MenuItem>
                </TextField>}
              </div>;
            })}
          </section>
        </>}
      </DialogContent>
      <DialogActions>
        <Button disabled={loading} onClick={() => setOpen(false)}>Cancel</Button>
        <Button variant="contained" disabled={loading || !preview} onClick={() => void publish()}>
          {favorited ? "Update favorite" : "Favorite"}
        </Button>
      </DialogActions>
    </Dialog>
  </>;
}
