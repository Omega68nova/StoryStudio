import {
  FormEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useLiveEvents } from "./useLiveEvents";
import { api } from "./api";
import { MusicPlayer } from "./MusicPlayer";
import { AmbientPlayer, AmbientPreferences, NoisePlayer } from "./AmbientPlayer";
import { LocationMap } from "./EnvironmentStudio";
import { OperationCenter } from "./OperationCenter";
import { DataStudio } from "./DataStudio";
import { UsersStudio } from "./UsersStudio";
import { WorldConfigurationStudio } from "./WorldConfigurationStudio";
import { MinigameCheckpoint, MinigameResult } from "./minigames/MinigameCheckpoint";
import {
  StoryComposer,
  type GenerationMode,
  type StoryAction,
} from "./StoryComposer";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Drawer,
  IconButton,
  LinearProgress,
  Menu,
  MenuItem,
  Paper,
  Popover,
  Snackbar,
  TextField,
  Tooltip,
} from "@mui/material";
import SettingsIcon from "@mui/icons-material/Settings";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import MenuOpenIcon from "@mui/icons-material/MenuOpen";
import MenuIcon from "@mui/icons-material/Menu";
import TuneIcon from "@mui/icons-material/Tune";
import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import MenuBookOutlinedIcon from "@mui/icons-material/MenuBookOutlined";
import RedoIcon from "@mui/icons-material/Redo";
import UndoIcon from "@mui/icons-material/Undo";
import CloseIcon from "@mui/icons-material/Close";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import ImageOutlinedIcon from "@mui/icons-material/ImageOutlined";
import SaveOutlinedIcon from "@mui/icons-material/SaveOutlined";
import CancelOutlinedIcon from "@mui/icons-material/CancelOutlined";
import AccountCircleOutlinedIcon from "@mui/icons-material/AccountCircleOutlined";
import PublicOutlinedIcon from "@mui/icons-material/PublicOutlined";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import { childCount, newestLeaf, storyPath } from "./tree";
import type {
  AppEvent,
  BibleDocument,
  ImageSuggestion,
  Project,
  ProjectSummary,
  RuntimeSettings,
  StoryNode,
  PendingReview,
  WorldEntity,
  WorldProjection,
  AbilityDefinition,
  MediaAsset,
  SceneAppearance,
  WorkflowPreset,
  MinigameSession,
  AuthUser,
  SceneEnvironment,
} from "./types";

const defaultSettings: RuntimeSettings = {
  data_dir: "",
  llama_executable: "",
  storyteller_model_path: "",
  storyteller_model_id: "",
  llama_url: "http://127.0.0.1:8080",
  llama_extra_args: [],
  comfy_command: [],
  comfy_workdir: "",
  comfy_url: "http://127.0.0.1:8188",
  context_tokens: 8192,
  planning_context_tokens: 8192,
  memory_provider: "builtin",
  portrait_prompt_prefix: "portrait, anime style, full color, clean lineart, soft shading, looking at viewer, simple background, white background,",
  full_body_prompt_prefix: "full body, standing, anime style, full color, clean lineart, soft shading, looking at viewer, simple background, white background,",
  icon_prompt_prefix: "(((no humans))),simple background, white background,",
};
const expectedBackendVersion = "0.17.0-environment";

type View =
  | "story"
  | "configuration"
  | "settings"
  | "data"
  | "users";
type MobileScale = "comfortable" | "compact" | "dense" | "tiny";

const viewLabels: Record<View, string> = {
  story: "Story",
  configuration: "World configuration",
  settings: "Settings",
  data: "Data management",
  users: "Users",
};

export default function App() {
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [leafId, setLeafId] = useState<string | null>(null);
  const [workflows, setWorkflows] = useState<WorkflowPreset[]>([]);
  const [view, setView] = useState<View>("story");
  const [runtime, setRuntime] = useState("idle");
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [streamText, setStreamText] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [deleteProjectOpen, setDeleteProjectOpen] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [railCollapsed, setRailCollapsed] = useState(() => {
    const saved = localStorage.getItem("storystudio.railCollapsed");
    return saved === null
      ? window.matchMedia("(max-width: 720px)").matches
      : saved === "true";
  });
  const [mobileScale, setMobileScaleState] = useState<MobileScale>(
    () =>
      (localStorage.getItem("storystudio.mobileScale") as MobileScale | null) ??
      "compact",
  );
  const [createOpen, setCreateOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("Untitled story");
  const [newPreset, setNewPreset] = useState("none");
  const [pendingView, setPendingView] = useState<View | null>(null);
  const [pendingProjectId, setPendingProjectId] = useState<string | null>(null);
  const [navigationAnchor, setNavigationAnchor] = useState<HTMLElement | null>(
    null,
  );
  const [accountAnchor, setAccountAnchor] = useState<HTMLElement | null>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPasswordValue, setNewPasswordValue] = useState("");
  const [storyToolbarHost, setStoryToolbarHost] =
    useState<HTMLDivElement | null>(null);
  const [ambientOpen, setAmbientOpen] = useState(false);
  const [mapOpen, setMapOpen] = useState(false);
  const [sceneEnvironment, setSceneEnvironment] = useState<SceneEnvironment | null>(null);

  function toggleRail() {
    const value = !railCollapsed;
    setRailCollapsed(value);
    localStorage.setItem("storystudio.railCollapsed", String(value));
    requestAnimationFrame(() =>
      window.dispatchEvent(new Event("storystudio-layout-change")),
    );
  }

  function setMobileScale(value: MobileScale) {
    setMobileScaleState(value);
    localStorage.setItem("storystudio.mobileScale", value);
  }

  function requestView(next: View) {
    if (document.body.dataset.storyStudioUnsaved === "true" && next !== view)
      setPendingView(next);
    else setView(next);
  }
  function requestProject(id: string) {
    if (
      document.body.dataset.storyStudioUnsaved === "true" &&
      id !== project?.id
    )
      setPendingProjectId(id);
    else {
      void loadProject(id);
      setView("story");
    }
  }

  const loadProjects = useCallback(async () => {
    const list = await api<ProjectSummary[]>("/projects");
    setProjects(list);
    return list;
  }, []);

  const loadProject = useCallback(async (id: string) => {
    const loaded = await api<Project>(`/projects/${id}`);
    setProject(loaded);
    setLeafId(
      loaded.active_node_id === undefined
        ? newestLeaf(loaded.story_nodes)
        : loaded.active_node_id,
    );
  }, []);

  const loadWorkflows = useCallback(async () => {
    setWorkflows(await api<WorkflowPreset[]>("/workflows"));
  }, []);

  useEffect(() => {
    api<{ user: AuthUser }>("/auth/me")
      .then(({ user }) => setAuthUser(user))
      .catch(() => setAuthUser(null))
      .finally(() => setAuthChecked(true));
    const lost = () => { setAuthUser(null); setAuthChecked(true); };
    window.addEventListener("storystudio-auth-lost", lost);
    return () => window.removeEventListener("storystudio-auth-lost", lost);
  }, []);

  useEffect(() => {
    if (!authUser) return;
    Promise.all([loadProjects(), loadWorkflows()])
      .then(([list]) => list[0] && loadProject(list[0].id))
      .catch((cause) => setError(String(cause.message ?? cause)));
  }, [authUser, loadProject, loadProjects, loadWorkflows]);

  useEffect(() => {
    api<{ version: string }>("/version")
      .then(({ version }) => {
        if (version !== expectedBackendVersion)
          setError(
            `StoryStudio's backend is out of date (${version}). Restart StoryStudio before using workflow editing or generation.`,
          );
      })
      .catch(() =>
        setError(
          "Restart StoryStudio to load the updated backend before using workflow editing or generation.",
        ),
      );
  }, []);

    useLiveEvents({
      enabled: Boolean(authUser),
      projectId: project?.id,
      onRuntime: (state, jobId) => {
        setRuntime(state);
        setCurrentJobId(jobId);
      },
      onToken: (text) => {
        if (text) setStreamText((current) => current + text);
        else setStreamText("");
      },
      onRefresh: async () => {
        if (!project?.id) return;
        setStreamText("");
        setRevision((value) => value + 1);
        await loadProject(project.id);
      },
      onError: (message) => {
        setError(message);
        setRevision((value) => value + 1);
      },
      onNotice: setNotice,
      onAuthLost: () => {
        setAuthUser(null);
        setAuthChecked(true);
      },
      onMusicChanged: (payload) => {
        setNotice(
          `${String(payload.playback_updated_by ?? "A player")} switched music to ${String(payload.theme_name ?? "theme")} · ${String(payload.track_title ?? "track")}`,
        );
      },
    });

  async function logout() {
    try { await api("/auth/logout", { method: "POST" }); } catch { /* Clear the local session view even if the server already revoked it. */ }
    setAuthUser(null); setProject(null); setProjects([]); setAccountAnchor(null);
  }

  async function changePassword() {
    try {
      await api("/auth/password", { method: "PUT", body: JSON.stringify({ current_password: currentPassword, new_password: newPasswordValue }) });
      setPasswordOpen(false); setCurrentPassword(""); setNewPasswordValue(""); setAuthUser(null);
    } catch (cause) { setError(errorMessage(cause)); }
  }

  async function createProject() {
    const title = newTitle.trim();
    if (!title) return;
    const stats_preset = newPreset;
    try {
      const created = await api<ProjectSummary>("/projects", {
        method: "POST",
        body: JSON.stringify({ title, stats_preset }),
      });
      await loadProjects();
      await loadProject(created.id);
      setView("story");
      setCreateOpen(false);
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

  async function deleteProject() {
    if (!project || deleteConfirmation !== project.title) return;
    try {
      await api(`/projects/${project.id}/purge`, {
        method: "DELETE",
        body: JSON.stringify({ confirmation: deleteConfirmation }),
      });
      const remaining = await loadProjects();
      setProject(null);
      setLeafId(null);
      setDeleteProjectOpen(false);
      setDeleteConfirmation("");
      if (remaining[0]) await loadProject(remaining[0].id);
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

  if (!authChecked) return <div className="login-shell"><LinearProgress /><p>Opening StoryStudio…</p></div>;
  if (!authUser) return <LoginScreen onLogin={setAuthUser} />;

  const isAdmin = authUser.role === "admin";
  return (
    <div
      className={`app-shell ${railCollapsed ? "rail-collapsed" : ""}`}
      data-mobile-scale={mobileScale}
    >
      <aside className="rail">
        <header className="brand">
          <span className="brand-mark">S</span>
          <div>
            <strong>StoryStudio</strong>
            <small>Local narrative workshop</small>
          </div>
        </header>
        {isAdmin && <Button className="new-project" onClick={() => setCreateOpen(true)}>
          ＋ New story
        </Button>}
        <nav className="projects" aria-label="Projects">
          {projects.map((item) => (
            <div className="project-row" key={item.id}>
              <Button
                className={`project-select ${project?.id === item.id ? "active" : ""}`}
                onClick={() => requestProject(item.id)}
              >
                <span>{item.title.slice(0, 1).toUpperCase()}</span>
                <span className="project-title">{item.title}</span>
              </Button>
              {isAdmin && project?.id === item.id && (
                <Tooltip title="Delete story">
                  <IconButton
                    size="small"
                    onClick={() => setDeleteProjectOpen(true)}
                  >
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
            </div>
          ))}
        </nav>
        <div
          className={`runtime-pill ${runtime === "runtime_error" ? "bad" : ""}`}
        >
          <i />
          {humanize(runtime)}
        </div>
      </aside>

      <main className={`stage ${view === "story" && sceneEnvironment?.background?.url ? "has-scene-background" : ""}`} style={view === "story" && sceneEnvironment?.background?.url ? { backgroundImage: `linear-gradient(rgba(8,12,18,.62), rgba(8,12,18,.78)), url(${sceneEnvironment.background.url})` } : undefined}>
        <header className="app-topbar">
          <Tooltip title={railCollapsed ? "Show stories" : "Hide stories"}>
            <IconButton
              size="small"
              aria-label={railCollapsed ? "Show stories" : "Hide stories"}
              onClick={toggleRail}
            >
              {railCollapsed ? <MenuIcon /> : <MenuOpenIcon />}
            </IconButton>
          </Tooltip>
          <div className="app-topbar-title">
            <h1>{project?.title ?? "StoryStudio"}</h1>
            {view !== "story" && <span>{viewLabels[view]}</span>}
          </div>
          <div className="app-topbar-spacer" />
          {view === "story" && (
            <div className="story-toolbar-host" ref={setStoryToolbarHost} />
          )}
          {project && <Tooltip title="Location map"><IconButton size="small" onClick={() => setMapOpen(true)}><PublicOutlinedIcon /></IconButton></Tooltip>}
          {project && isAdmin && (
            <OperationCenter
              projectId={project.id}
              revision={revision}
              fail={setError}
            />
          )}
          <Tooltip title={isAdmin ? "Open workspaces and settings" : "Preferences"}>
            <IconButton
              size="small"
              aria-label="Open workspaces and settings"
              onClick={(event) => isAdmin ? setNavigationAnchor(event.currentTarget) : setAmbientOpen(true)}
            >
              <SettingsIcon />
            </IconButton>
          </Tooltip>
          <Menu
            anchorEl={navigationAnchor}
            open={Boolean(navigationAnchor)}
            onClose={() => setNavigationAnchor(null)}
            anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
            transformOrigin={{ vertical: "top", horizontal: "right" }}
          >
            {(Object.keys(viewLabels) as View[]).map((item) => (
              <MenuItem
                key={item}
                selected={view === item}
                disabled={
                  !project &&
                  item === "configuration"
                }
                onClick={() => {
                  setNavigationAnchor(null);
                  requestView(item);
                }}
              >
                {viewLabels[item]}
              </MenuItem>
            ))}
            <MenuItem onClick={() => { setNavigationAnchor(null); setAmbientOpen(true); }}>Ambient preferences</MenuItem>
          </Menu>
          <Tooltip title={`${authUser.username} account`}>
            <IconButton size="small" aria-label="Account" onClick={(event) => setAccountAnchor(event.currentTarget)}>
              <AccountCircleOutlinedIcon />
            </IconButton>
          </Tooltip>
          <Menu anchorEl={accountAnchor} open={Boolean(accountAnchor)} onClose={() => setAccountAnchor(null)}>
            <MenuItem disabled>{authUser.username} · {isAdmin ? "Administrator" : "Member"}</MenuItem>
            <MenuItem onClick={() => { setAccountAnchor(null); setPasswordOpen(true); }}>Change password</MenuItem>
            <MenuItem onClick={() => void logout()}><LogoutOutlinedIcon fontSize="small" sx={{ mr: 1 }} />Log out</MenuItem>
          </Menu>
        </header>
        <Snackbar
          open={Boolean(error)}
          autoHideDuration={10000}
          onClose={() => setError("")}
          anchorOrigin={{ vertical: "top", horizontal: "center" }}
        >
          <Alert
            severity="error"
            onClose={() => setError("")}
            sx={{ maxWidth: 720 }}
          >
            {error}
          </Alert>
        </Snackbar>
        <Snackbar
          open={Boolean(notice)}
          autoHideDuration={6000}
          onClose={() => setNotice("")}
          anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
        >
          <Alert
            severity="warning"
            onClose={() => setNotice("")}
            sx={{ maxWidth: 720 }}
          >
            {notice}
          </Alert>
        </Snackbar>
        {view === "story" &&
          (project ? (
            <StoryWorkspace
              project={project}
              leafId={leafId}
              setLeafId={setLeafId}
              workflows={workflows}
              streamText={streamText}
              runtime={runtime}
              currentJobId={currentJobId}
              reload={() => loadProject(project.id)}
              fail={setError}
              revision={revision}
              toolbarHost={storyToolbarHost}
              isAdmin={isAdmin}
            />
          ) : (
            isAdmin ? <EmptyState create={createProject} /> : <div className="opening"><h2>No assigned stories</h2><p>An administrator can grant access from the Users workspace.</p></div>
          ))}
        {view === "configuration" && project && (
          <WorldConfigurationStudio
            projectId={project.id}
            revision={revision}
            workflows={workflows}
            fail={setError}
            reloadWorkflows={loadWorkflows}
          />
        )}
        {view === "settings" && (
          <SettingsPanel
            runtime={runtime}
            fail={setError}
            mobileScale={mobileScale}
            setMobileScale={setMobileScale}
          />
        )}
        {view === "data" && (
          <DataStudio
            projectId={project?.id}
            revision={revision}
            fail={setError}
            changed={() => {
              setRevision((value) => value + 1);
              void loadProjects();
              if (project)
                void loadProject(project.id).catch(() => setProject(null));
            }}
          />
        )}
        {view === "users" && isAdmin && (
          <UsersStudio projects={projects} fail={setError} />
        )}
      </main>
      {project && (
        <><MusicPlayer
            projectId={project.id}
            revision={revision}
            fail={setError}
          /><AmbientPlayer projectId={project.id} revision={revision} onScene={setSceneEnvironment} /><NoisePlayer projectId={project.id} /></>
      )}
      <Dialog open={ambientOpen} onClose={() => setAmbientOpen(false)}><DialogTitle>Preferences</DialogTitle><DialogContent><AmbientPreferences fail={setError} /></DialogContent><DialogActions><Button onClick={() => setAmbientOpen(false)}>Close</Button></DialogActions></Dialog>
      <Dialog fullWidth maxWidth="md" open={mapOpen} onClose={() => setMapOpen(false)}><DialogTitle>Locations</DialogTitle><DialogContent>{project && <LocationMap projectId={project.id} fail={setError} />}</DialogContent><DialogActions><Button onClick={() => setMapOpen(false)}>Close</Button></DialogActions></Dialog>
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)}>
        <DialogTitle>Create story</DialogTitle>
        <DialogContent
          sx={{ display: "grid", gap: 2, pt: "12px !important", minWidth: 360 }}
        >
          <TextField
            autoFocus
            label="Story title"
            value={newTitle}
            onChange={(event) => setNewTitle(event.target.value)}
          />
          <TextField
            select
            label="Stats preset"
            value={newPreset}
            onChange={(event) => setNewPreset(event.target.value)}
          >
            <MenuItem value="none">No stats</MenuItem>
            <MenuItem value="adventure">Adventure (HP and mana)</MenuItem>
            <MenuItem value="romance">Romance (favorability)</MenuItem>
          </TextField>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!newTitle.trim()}
            onClick={() => void createProject()}
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={passwordOpen} onClose={() => setPasswordOpen(false)}>
        <DialogTitle>Change password</DialogTitle>
        <DialogContent sx={{ display: "grid", gap: 2, pt: "12px !important", minWidth: 320 }}>
          <TextField autoFocus type="password" autoComplete="current-password" label="Current password" value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} />
          <TextField type="password" autoComplete="new-password" label="New password" value={newPasswordValue} onChange={event => setNewPasswordValue(event.target.value)} helperText="At least eight characters" />
        </DialogContent>
        <DialogActions><Button onClick={() => setPasswordOpen(false)}>Cancel</Button><Button variant="contained" disabled={!currentPassword || newPasswordValue.length < 8} onClick={() => void changePassword()}>Change and sign out</Button></DialogActions>
      </Dialog>
      <Dialog
        open={pendingView !== null || pendingProjectId !== null}
        onClose={() => {
          setPendingView(null);
          setPendingProjectId(null);
        }}
      >
        <DialogTitle>Discard unsaved changes?</DialogTitle>
        <DialogContent>
          Save the current editor before switching, or discard its unsaved
          changes.
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setPendingView(null);
              setPendingProjectId(null);
            }}
          >
            Keep editing
          </Button>
          <Button
            color="error"
            onClick={() => {
              document.body.dataset.storyStudioUnsaved = "false";
              if (pendingProjectId) {
                void loadProject(pendingProjectId);
                setView("story");
              } else if (pendingView) setView(pendingView);
              setPendingView(null);
              setPendingProjectId(null);
            }}
          >
            Discard and switch
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={deleteProjectOpen}
        onClose={() => setDeleteProjectOpen(false)}
      >
        <DialogTitle>Delete story permanently?</DialogTitle>
        <DialogContent>
          <p>
            This removes the story, world memory, and managed images. Active
            generation must be cancelled first.
          </p>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteProjectOpen(false)}>Cancel</Button>
          <Button
            color="error"
            onClick={() => void deleteProject()}
          >
            Delete permanently
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}

function StoryWorkspace(props: {
  project: Project;
  leafId: string | null;
  setLeafId: (id: string | null) => void;
  workflows: WorkflowPreset[];
  streamText: string;
  runtime: string;
  currentJobId: string | null;
  reload: () => Promise<void>;
  fail: (message: string) => void;
  revision: number;
  toolbarHost: HTMLDivElement | null;
  isAdmin: boolean;
}) {
  const {
    project,
    leafId,
    setLeafId,
    workflows,
    streamText,
    runtime,
    currentJobId,
    reload,
    fail,
    revision,
    toolbarHost,
    isAdmin,
  } = props;
  const path = useMemo(
    () => storyPath(project.story_nodes, leafId),
    [project.story_nodes, leafId],
  );
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [pendingJobId, setPendingJobId] = useState<string | null>(null);
  const [action, setAction] = useState<StoryAction>("do");
  const [generationMode, setGenerationModeState] = useState<GenerationMode>(
    project.story_settings?.default_generation_mode ?? "low",
  );
  const [responseMaxTokens, setResponseMaxTokens] = useState(
    project.story_settings?.response_max_tokens ?? 300,
  );
  const [responseTokenInput, setResponseTokenInput] = useState(
    String(project.story_settings?.response_max_tokens ?? 300),
  );
  const [aiInstructions, setAiInstructions] = useState(
    project.story_settings?.ai_instructions ?? "",
  );
  const [composerExpanded, setComposerExpandedState] = useState(
    () => localStorage.getItem("storystudio.composerExpanded") !== "false",
  );
  const transcriptRef = useRef<HTMLDivElement>(null);
  const transcriptPinned = useRef(true);
  const [settingsAnchor, setSettingsAnchor] = useState<HTMLElement | null>(
    null,
  );
  const [editingNode, setEditingNode] = useState<StoryNode | null>(null);
  const [editedText, setEditedText] = useState("");
  const [revisionNode, setRevisionNode] = useState<StoryNode | null>(null);
  const [textRevisions, setTextRevisions] = useState<
    Array<{
      id: string;
      previous_content: string;
      content: string;
      created_at: string;
    }>
  >([]);
  const [showTree, setShowTree] = useState(false);
  const [entities, setEntities] = useState<WorldEntity[]>([]);
  const [characterMedia, setCharacterMedia] = useState<Record<string, MediaAsset[]>>({});
  const [reviews, setReviews] = useState<PendingReview[]>([]);
  const [abilities, setAbilities] = useState<AbilityDefinition[]>([]);
  const [requestedAbility, setRequestedAbility] = useState("");
  const [requestedTarget, setRequestedTarget] = useState("");
  const [retryGuideOpen, setRetryGuideOpen] = useState(false);
  const [retryGuide, setRetryGuide] = useState("");
  const [bibleOpen, setBibleOpen] = useState(() => {
    const saved = localStorage.getItem("storystudio.bibleOpen");
    return saved === null
      ? !window.matchMedia("(max-width: 720px)").matches
      : saved !== "false";
  });
  const activeNode = project.story_nodes.find((node) => node.id === leafId);
  const currentBranches = activeNode
    ? project.story_nodes.filter(
        (node) =>
          node.parent_id === activeNode.parent_id &&
          node.role === activeNode.role,
      )
    : project.story_nodes.filter((node) => node.parent_id === null);
  const currentTrashedBranches = activeNode
    ? (project.trashed_story_nodes ?? []).filter(
        (node) =>
          node.parent_id === activeNode.parent_id &&
          node.role === activeNode.role,
      )
    : (project.trashed_story_nodes ?? []).filter(
        (node) => node.parent_id === null,
      );
  const [pov, setPov] = useState(activeNode?.pov_character_id ?? "");
  const [narration, setNarration] = useState(
    activeNode?.narration_mode ?? "third_omniscient",
  );
  function setComposerExpanded(expanded: boolean) {
    setComposerExpandedState(expanded);
    localStorage.setItem("storystudio.composerExpanded", String(expanded));
    requestAnimationFrame(() =>
      window.dispatchEvent(new Event("storystudio-layout-change")),
    );
  }
  useEffect(() => {
    transcriptPinned.current = true;
  }, [project.id]);
  useEffect(() => {
    setGenerationModeState(
      project.story_settings?.default_generation_mode ?? "low",
    );
    setResponseMaxTokens(project.story_settings?.response_max_tokens ?? 300);
    setResponseTokenInput(String(project.story_settings?.response_max_tokens ?? 300));
    setAiInstructions(project.story_settings?.ai_instructions ?? "");
  }, [project.id]);

  async function saveStorySettings(
    mode = generationMode,
    tokens = responseMaxTokens,
    instructions = aiInstructions,
  ) {
    if (!isAdmin) return;
    try {
      await api(`/projects/${project.id}/story-settings`, {
        method: "PUT",
        body: JSON.stringify({
          default_generation_mode: mode,
          response_max_tokens: tokens,
          ai_instructions: instructions,
        }),
      });
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  function setGenerationMode(mode: GenerationMode) {
    setGenerationModeState(mode);
    if (isAdmin) void saveStorySettings(mode, responseMaxTokens);
  }
  useLayoutEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript && transcriptPinned.current)
      transcript.scrollTop = transcript.scrollHeight;
  }, [path.length, streamText, reviews.length, composerExpanded, project.id]);
  useEffect(() => {
    const query = leafId ? `?head_node_id=${encodeURIComponent(leafId)}` : "";
    api<WorldProjection>(`/projects/${project.id}/world${query}`)
      .then(world => setEntities(Object.values(world.entities)))
      .catch((cause) => fail(errorMessage(cause)));
  }, [project.id, revision, leafId, fail]);
  useEffect(() => {
    if (!isAdmin) {
      setReviews([]);
      setAbilities([]);
      return;
    }
    Promise.all([
      api<PendingReview[]>(`/projects/${project.id}/reviews`),
      api<{ abilities: AbilityDefinition[] }>(`/projects/${project.id}/rules`),
    ])
      .then(([pending, rules]) => {
        setReviews(pending);
        setAbilities(rules.abilities);
      })
      .catch((cause) => fail(errorMessage(cause)));
  }, [project.id, revision, fail, isAdmin]);

  const currentAssistant = [...path].reverse().find(node => node.role === "assistant");
  const currentSceneAppearances = currentAssistant
    ? project.scene_appearances.filter(
        item => item.story_node_id === currentAssistant.id && item.encounter_kind.endsWith("character"),
      )
    : [];
  const currentActorId = currentAssistant?.pov_character_id ?? [...path].reverse().find(node => node.pov_character_id)?.pov_character_id ?? null;
  const currentActor = entities.find(entity => entity.id === currentActorId);
  const currentPartyValue = currentActor?.state.party_ids;
  const currentPartyIds = new Set(
    Array.isArray(currentPartyValue) ? currentPartyValue.map(String) : [],
  );

  useEffect(() => {
    const ids = new Set<string>();
    path.forEach(node => {
      if (node.pov_character_id) ids.add(node.pov_character_id);
    });
    currentSceneAppearances.forEach(item => ids.add(item.entity_id));
    const missing = [...ids].filter(id => !characterMedia[id]);
    if (!missing.length) return;
    void Promise.all(
      missing.map(async id => [id, await api<MediaAsset[]>(`/entities/${id}/media`).catch(() => [] as MediaAsset[])] as const),
    ).then(entries => setCharacterMedia(current => ({ ...current, ...Object.fromEntries(entries) })));
  }, [path, currentSceneAppearances, characterMedia]);

  function characterAsset(entityId: string, kind: "portrait" | "full_body", outfitId?: string | null) {
    const assets = characterMedia[entityId] ?? [];
    return assets.find(asset => asset.kind === kind && Boolean(outfitId) && asset.outfit_id === outfitId && asset.file_path)
      ?? assets.find(asset => asset.kind === kind && !asset.outfit_id && asset.file_path)
      ?? assets.find(asset => asset.kind === kind && asset.file_path)
      ?? null;
  }

  async function submit(
    event?: FormEvent,
    requestedAction: "story" | "say" | "do" | "guide" | "continue" = action,
  ) {
    event?.preventDefault();
    if (submitting) return;
    const content = message.trim();
    const effectiveAction = content ? requestedAction : "continue";
    setSubmitting(true);
    setMessage("");
    try {
      const response = await api<{ user_node?: StoryNode; node?: StoryNode; job?: { id: string } }>(
        `/projects/${project.id}/turns`,
        {
          method: "POST",
          body: JSON.stringify({
            parent_id: leafId,
            content,
            action: effectiveAction,
            generation_mode: generationMode,
            pov_character_id: pov || null,
            narration_mode: narration,
            requested_ability:
              requestedAbility && pov
                ? {
                    actor_id: pov,
                    ability_key: requestedAbility,
                    target_id: requestedTarget || pov,
                  }
                : null,
          }),
        },
      );
      const created = response.user_node ?? response.node;
      if (created) setLeafId(created.id);
      if (response.job?.id) setPendingJobId(response.job.id);
      setRequestedAbility("");
      setRequestedTarget("");
      await reload();
    } catch (cause) {
      setMessage(content);
      fail(errorMessage(cause));
    } finally {
      setSubmitting(false);
    }
  }

  async function regenerate(node: StoryNode) {
    try {
      const response = await api<{ id?: string; job?: { id: string } }>(`/story-nodes/${node.id}/regenerate`, { method: "POST" });
      if (response.job?.id ?? response.id) setPendingJobId(response.job?.id ?? response.id ?? null);
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  async function selectBranch(id: string) {
    try {
      await api(`/projects/${project.id}/head`, {
        method: "PUT",
        body: JSON.stringify({ node_id: id }),
      });
      setLeafId(id);
      setShowTree(false);
      await reload();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  async function undo() {
    try {
      const result = await api<{ node_id: string | null }>(
        `/projects/${project.id}/undo`,
        { method: "POST" },
      );
      setLeafId(result.node_id);
      await reload();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  async function redo() {
    try {
      const result = await api<{ node_id: string | null }>(
        `/projects/${project.id}/redo`,
        { method: "POST" },
      );
      setLeafId(result.node_id);
      await reload();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  async function retry(guide = "") {
    const target = [...path]
      .reverse()
      .find(
        (node) =>
          node.role === "assistant" && node.action_kind !== "manual_story",
      );
    if (!target) {
      fail("There is no storyteller response to retry.");
      return;
    }
    try {
      const response = await api<{ id?: string; job?: { id: string } }>(`/story-nodes/${target.id}/regenerate`, {
        method: "POST",
        body: JSON.stringify({ guide, generation_mode: generationMode }),
      });
      if (response.job?.id ?? response.id) setPendingJobId(response.job?.id ?? response.id ?? null);
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  async function retryWithGuide() {
    if (!retryGuide.trim()) return;
    await retry(retryGuide.trim());
    setRetryGuideOpen(false);
    setRetryGuide("");
  }

  async function see() {
    const workflow = workflows[0];
    if (!workflow) {
      fail("Import a ComfyUI workflow before using See.");
      return;
    }
    try {
      await api(`/projects/${project.id}/see`, {
        method: "POST",
        body: JSON.stringify({
          workflow_preset_id: workflow.id,
          node_id: leafId,
          prompt: "",
          negative_prompt: "",
          seed: Math.floor(Math.random() * 2_147_483_647),
          width: workflow.mappings.width ? 1024 : null,
          height: workflow.mappings.height ? 1024 : null,
        }),
      });
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  async function erase() {
    if (message) {
      setMessage("");
      return;
    }
    await undo();
  }

  async function stopGeneration() {
    const jobId = pendingJobId ?? currentJobId;
    if (!jobId) return;
    try {
      await api(`/jobs/${jobId}/cancel`, { method: "POST" });
      if (pendingJobId === jobId) setPendingJobId(null);
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  async function saveTextEdit() {
    if (!editingNode || !editedText.trim()) return;
    try {
      await api(`/story-nodes/${editingNode.id}`, {
        method: "PATCH",
        body: JSON.stringify({ content: editedText }),
      });
      setEditingNode(null);
      await reload();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  async function trash(node: StoryNode) {
    try {
      const result = await api<{ node_id: string | null }>(
        `/story-nodes/${node.id}`,
        { method: "DELETE" },
      );
      setLeafId(result.node_id);
      await reload();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  async function restore(node: StoryNode) {
    try {
      await api(`/story-nodes/${node.id}/restore`, { method: "POST" });
      setLeafId(node.id);
      await reload();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  async function showRevisions(node: StoryNode) {
    try {
      setRevisionNode(node);
      setTextRevisions(await api(`/story-nodes/${node.id}/revisions`));
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  async function revertRevision(id: string) {
    try {
      await api(`/story-revisions/${id}/revert`, { method: "POST" });
      setRevisionNode(null);
      await reload();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  async function decide(
    review: PendingReview,
    accept: boolean,
    mutations?: Array<Record<string, unknown>>,
  ) {
    const action =
      review.phase === "pre_prose"
        ? accept
          ? "approve"
          : "reject_replan"
        : accept
          ? "accept_reconciliation"
          : "reject_regenerate";
    try {
      await api(`/reviews/${review.id}`, {
        method: "POST",
        body: JSON.stringify({ action, mutations }),
      });
      await reload();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }

  const activeStoryJobId = pendingJobId ?? currentJobId;
  const activeStoryJob = (project.active_jobs ?? []).find((job) => job.id === activeStoryJobId);
  const persistedStream = (project.active_jobs ?? []).find((job) => job.kind === "story" && job.status === "running")?.partial_output ?? "";
  const visibleStream = persistedStream && !streamText.startsWith(persistedStream) ? persistedStream + streamText : streamText || persistedStream;
  const storyWorking = submitting || Boolean(pendingJobId) || [
    "loading_storyteller", "preparing_context", "thinking_low", "thinking_smart",
    "generating_story", "validating_action", "repairing_action", "finalizing_story",
  ].includes(runtime);
  useEffect(() => {
    if (!currentJobId && runtime === "idle" && revision) setPendingJobId(null);
  }, [currentJobId, runtime, revision]);

  return (
    <div className={`workspace ${bibleOpen ? "" : "bible-collapsed"}`}>
      {toolbarHost &&
        createPortal(
          <div className="header-actions">
            {isAdmin && <>
            <Tooltip title="Undo">
              <span>
                <IconButton
                  size="small"
                  aria-label="Undo"
                  disabled={!leafId}
                  onClick={undo}
                >
                  <UndoIcon />
                </IconButton>
              </span>
            </Tooltip>
            <Tooltip title="Redo">
              <IconButton size="small" aria-label="Redo" onClick={redo}>
                <RedoIcon />
              </IconButton>
            </Tooltip>
            <Tooltip
              title={`Branches for current action (${currentBranches.length})`}
            >
              <IconButton
                size="small"
                aria-label="Branches for current action"
                onClick={() => setShowTree(!showTree)}
              >
                <AccountTreeOutlinedIcon />
              </IconButton>
            </Tooltip>
            </>}
            <Tooltip
              title={bibleOpen ? "Hide story bible" : "Show story bible"}
            >
              <IconButton
                size="small"
                aria-label={bibleOpen ? "Hide story bible" : "Show story bible"}
                onClick={() => {
                  const value = !bibleOpen;
                  setBibleOpen(value);
                  localStorage.setItem("storystudio.bibleOpen", String(value));
                }}
              >
                <MenuBookOutlinedIcon />
              </IconButton>
            </Tooltip>
            {isAdmin &&
            <Tooltip title="Narration and point of view">
              <IconButton
                size="small"
                aria-label="Narration and point of view"
                onClick={(e) => setSettingsAnchor(e.currentTarget)}
              >
                <TuneIcon />
              </IconButton>
            </Tooltip>}
          </div>,
          toolbarHost,
        )}
      <section className="story-column">
        <Popover
          open={Boolean(settingsAnchor)}
          anchorEl={settingsAnchor}
          onClose={() => setSettingsAnchor(null)}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        >
          <div className="scene-settings">
            <TextField
              select
              label="Narration"
              value={narration}
              onChange={(e) => setNarration(e.target.value as typeof narration)}
            >
              <MenuItem value="third_omniscient">
                Third-person omniscient
              </MenuItem>
              <MenuItem value="third_limited">Third-person limited</MenuItem>
              <MenuItem value="first_person">First person</MenuItem>
            </TextField>
            <TextField
              select
              label="POV character"
              value={pov}
              onChange={(e) => setPov(e.target.value)}
            >
              <MenuItem value="">Narrator / inherit</MenuItem>
              {entities
                .filter((entity) => entity.kind === "character")
                .map((entity) => (
                  <MenuItem key={entity.id} value={entity.id}>
                    {entity.name}
                  </MenuItem>
                ))}
            </TextField>
            <TextField
              type="number"
              label="Response tokens"
              value={responseTokenInput}
              inputProps={{ min: 64, max: 1400 }}
              onChange={(event) => setResponseTokenInput(event.target.value)}
              onBlur={() => {
                const parsed = Number(responseTokenInput);
                if (!Number.isInteger(parsed) || parsed < 64 || parsed > 1400) {
                  setResponseTokenInput(String(responseMaxTokens));
                  return;
                }
                setResponseMaxTokens(parsed);
                setResponseTokenInput(String(parsed));
                void saveStorySettings(generationMode, parsed);
              }}
              helperText="64–1400; applies to new jobs"
            />
            <TextField
              multiline
              minRows={5}
              label="Storyteller context"
              value={aiInstructions}
              onChange={(event) => setAiInstructions(event.target.value)}
              helperText="Persistent project instructions, including preferred minigame behavior. Canonical state and validation take precedence."
            />
            <Button variant="contained" onClick={() => void saveStorySettings(generationMode, responseMaxTokens, aiInstructions)}>
              Save storyteller context
            </Button>
          </div>
        </Popover>
        <Drawer
          anchor="right"
          open={showTree}
          onClose={() => setShowTree(false)}
        >
          <Box sx={{ width: 390, maxWidth: "42vw", p: 2 }}>
            <h2>Branches for current action</h2>
            <BranchNavigator
              nodes={currentBranches}
              trashed={currentTrashedBranches}
              selected={leafId}
              select={(id) => void selectBranch(id)}
              restore={(node) => void restore(node)}
            />
          </Box>
        </Drawer>
        <SceneCastLayer
          appearances={currentSceneAppearances}
          entities={entities}
          actorId={currentActorId}
          partyIds={currentPartyIds}
          assetFor={characterAsset}
        />
        <div
          className="transcript"
          ref={transcriptRef}
          onScroll={(event) => {
            const element = event.currentTarget;
            transcriptPinned.current =
              element.scrollHeight - element.scrollTop - element.clientHeight <
              80;
          }}
        >
          {!!reviews.length && (
            <div className="review-stack">
              {reviews.map((review) => (
                <ReviewCard
                  key={review.id}
                  review={review}
                  decide={decide}
                  fail={fail}
                />
              ))}
            </div>
          )}
          {!path.length && (
            <div className="opening">
              <span>✦</span>
              <h2>Where does our story begin?</h2>
              <p>
                Describe a scene, a character, or a spark of conflict. Your
                storyteller will carry it forward.
              </p>
            </div>
          )}
          {path
            .filter(
              (node) => !["guide", "continue"].includes(node.action_kind ?? ""),
            )
            .map((node) => (
              <article
                key={node.id}
                className={`turn ${node.role}`}
                onDoubleClick={() => {
                  if (!isAdmin) return;
                  setEditingNode(node);
                  setEditedText(node.content);
                }}
              >
                <div className={`turn-label ${node.role === "user" ? "with-actor" : ""}`}>
                  {node.role === "user" && (() => {
                    const actor = entities.find(entity => entity.id === node.pov_character_id);
                    const outfitId = typeof actor?.state.active_outfit_id === "string" ? actor.state.active_outfit_id : null;
                    const portrait = node.pov_character_id ? characterAsset(node.pov_character_id, "portrait", outfitId) : null;
                    return <span className="turn-actor-icon" title={actor?.name ?? "Acting character"}>
                      {portrait?.file_path ? <img src={`/media/${portrait.file_path}`} alt="" /> : <span>{(actor?.name ?? node.author_name_snapshot ?? "?").slice(0, 1).toUpperCase()}</span>}
                    </span>;
                  })()}
                  <span>{node.author_name_snapshot && node.role === "user" ? `${node.author_name_snapshot} · ${humanize(node.action_kind ?? "input")}` : node.action_kind === "manual_story"
                    ? `${node.author_name_snapshot ?? "Player"} story`
                    : node.role === "user"
                      ? humanize(node.action_kind ?? "input")
                      : "Storyteller"}</span>
                </div>
                {node.role === "assistant" &&
                  project.npc_interventions
                    .filter((item) => item.story_node_id === node.id)
                    .map((item) => (
                      <div className="npc-attempt" key={item.id}>
                        <strong>
                          {entities.find((entity) => entity.id === item.npc_id)
                            ?.name ?? "NPC"}
                        </strong>
                        {item.dialogue && <q>{item.dialogue}</q>}
                        <span>{item.attempted_action}</span>
                        {item.ability_key && (
                          <small>Ability: {item.ability_key}</small>
                        )}
                      </div>
                    ))}
                <StoryProse
                  node={node}
                  minigames={(project.minigame_sessions ?? []).filter(
                    (item) =>
                      item.story_node_id === node.id && item.active_on_branch,
                  )}
                />
                {node.role === "assistant" &&
                  project.scene_appearances
                    .filter((item) => item.story_node_id === node.id && ["character", "location"].includes(item.encounter_kind))
                    .map((item) => (
                      <EncounterCard
                        key={item.id}
                        appearance={item}
                        entity={entities.find(
                          (entity) => entity.id === item.entity_id,
                        )}
                        workflows={workflows}
                        fail={fail}
                        editable={isAdmin}
                      />
                    ))}
                {isAdmin && <div className="turn-actions">
                  <Button
                    onClick={() => {
                      setEditingNode(node);
                      setEditedText(node.content);
                    }}
                  >
                    Edit text
                  </Button>
                  <Button onClick={() => void showRevisions(node)}>
                    History
                  </Button>
                  {node.role === "assistant" &&
                    node.action_kind !== "manual_story" && (
                      <Button onClick={() => regenerate(node)}>
                        Regenerate
                      </Button>
                    )}
                  <Button onClick={() => void trash(node)}>Erase branch</Button>
                  {childCount(project.story_nodes, node.id) > 1 && (
                    <span>
                      {childCount(project.story_nodes, node.id)} branches
                    </span>
                  )}
                </div>}
                {node.role === "assistant" &&
                  project.suggestions
                    .filter((item) => item.story_node_id === node.id)
                    .map((suggestion) => (
                      <SuggestionCard
                        key={suggestion.id}
                        suggestion={suggestion}
                        workflows={workflows}
                        reload={reload}
                        fail={fail}
                        canDelete={isAdmin}
                      />
                    ))}
              </article>
            ))}
          {(project.active_jobs ?? []).filter((job) => job.kind === "story" && job.status === "queued").map((job) => (
            <article className="turn queued-action" key={job.id}>
              <div className="turn-label">{job.requester_name_snapshot ?? "Player"} · queued #{job.queue_position}</div>
              <div className="prose">{humanize(job.action_type ?? "continue")}{job.action_type !== "guide" && job.input_preview ? `: ${job.input_preview}` : ""}</div>
              {job.can_cancel && <Button size="small" color="error" startIcon={<CancelOutlinedIcon />} onClick={() => void api(`/jobs/${job.id}/cancel`, { method: "POST" }).then(reload).catch(cause => fail(errorMessage(cause)))}>Cancel queued action</Button>}
            </article>
          ))}
          {project.active_minigame && (
            <article className="turn assistant checkpoint-turn">
              <div className="turn-label">Storyteller</div>
              {project.active_minigame.partial_prose && (
                <div className="prose">
                  {project.active_minigame.partial_prose}
                </div>
              )}
              <MinigameCheckpoint
                session={project.active_minigame}
                reload={reload}
                fail={fail}
              />
            </article>
          )}
          {!project.active_minigame && (visibleStream || storyWorking) && (
            <article className="turn assistant streaming">
              <div className="turn-label">Storyteller</div>
              {visibleStream && <div className="prose">{visibleStream}<i className="cursor" /></div>}
              <div className="inline-story-operation" role="status" aria-live="polite">
                <LinearProgress />
                <span>{runtime === "idle" && pendingJobId ? "Queued" : humanize(runtime === "idle" && submitting ? "preparing_context" : runtime)}</span>
                {activeStoryJobId && storyWorking && (isAdmin || activeStoryJob?.can_cancel) && <Button size="small" color="error" startIcon={<CancelOutlinedIcon />} onClick={() => void stopGeneration()}>Cancel</Button>}
              </div>
            </article>
          )}
        </div>
        <StoryComposer
          expanded={composerExpanded}
          message={message}
          action={action}
          generationMode={generationMode}
          runtime={runtime}
          busy={
            submitting ||
            Boolean(project.active_minigame) ||
            runtime === "awaiting_review"
          }
          setExpanded={setComposerExpanded}
          setMessage={setMessage}
          setAction={setAction}
          setGenerationMode={setGenerationMode}
          submit={submit}
          see={see}
          retry={retry}
          retryWithGuide={() => setRetryGuideOpen(true)}
          erase={erase}
        />
      </section>
      {bibleOpen && (
        <BiblePanel
          documents={project.bible_documents}
          reload={reload}
          fail={fail}
        />
      )}
      <Dialog
        open={Boolean(editingNode)}
        onClose={() => setEditingNode(null)}
        fullWidth
        maxWidth="md"
      >
        <DialogTitle>
          Edit {editingNode?.role === "assistant" ? "story prose" : "input"}
        </DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            multiline
            minRows={8}
            fullWidth
            value={editedText}
            onChange={(e) => setEditedText(e.target.value)}
            helperText="Text-only edit: existing descendants and world memory stay unchanged."
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditingNode(null)}>Cancel</Button>
          <Button variant="contained" onClick={() => void saveTextEdit()}>
            Save revision
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={Boolean(revisionNode)}
        onClose={() => setRevisionNode(null)}
        fullWidth
        maxWidth="md"
      >
        <DialogTitle>Revision history</DialogTitle>
        <DialogContent>
          {!textRevisions.length && (
            <p className="muted">No earlier revisions.</p>
          )}
          {textRevisions.map((item) => (
            <article className="revision-row" key={item.id}>
              <small>{new Date(item.created_at).toLocaleString()}</small>
              <p>{item.previous_content}</p>
              <Button size="small" onClick={() => void revertRevision(item.id)}>
                Revert to this text
              </Button>
            </article>
          ))}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRevisionNode(null)}>Close</Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={retryGuideOpen}
        onClose={() => setRetryGuideOpen(false)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Retry with guidance</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={3}
            label="How should the storyteller change the retry?"
            value={retryGuide}
            onChange={(event) => setRetryGuide(event.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRetryGuideOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!retryGuide.trim()}
            onClick={() => void retryWithGuide()}
          >
            Retry
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}

function SceneCastLayer({
  appearances,
  entities,
  actorId,
  partyIds,
  assetFor,
}: {
  appearances: SceneAppearance[];
  entities: WorldEntity[];
  actorId: string | null | undefined;
  partyIds: Set<string>;
  assetFor: (entityId: string, kind: "portrait" | "full_body", outfitId?: string | null) => MediaAsset | null;
}) {
  const characters = appearances
    .map(appearance => ({
      appearance,
      entity: entities.find(entity => entity.id === appearance.entity_id),
      asset: assetFor(appearance.entity_id, "full_body", appearance.outfit_id),
    }))
    .filter(item => item.entity?.kind === "character" && item.asset?.file_path);
  if (!characters.length) return null;
  const left = characters.filter(item => item.entity!.id !== actorId && !partyIds.has(item.entity!.id));
  const right = characters.filter(item => item.entity!.id === actorId || partyIds.has(item.entity!.id));
  right.sort((a, b) => Number(a.entity!.id === actorId) - Number(b.entity!.id === actorId));
  return <div className="scene-cast-layer" aria-hidden="true">
    <div className="scene-cast-side scene-cast-left">
      {left.map((item, index) => <img
        key={item.appearance.id}
        className="scene-character"
        src={`/media/${item.asset!.file_path}`}
        alt=""
        style={{ zIndex: 20 + index }}
      />)}
    </div>
    <div className="scene-cast-side scene-cast-right">
      {right.map((item, index) => {
        const actor = item.entity!.id === actorId;
        return <img
          key={item.appearance.id}
          className={`scene-character facing-left ${actor ? "actor" : "party"}`}
          src={`/media/${item.asset!.file_path}`}
          alt=""
          style={{ zIndex: actor ? 60 : 30 + index }}
        />;
      })}
    </div>
  </div>;
}

function StoryProse({
  node,
  minigames,
}: {
  node: StoryNode;
  minigames: MinigameSession[];
}) {
  if (!minigames.length) return <div className="prose">{node.content}</div>;
  const ordered = [...minigames].sort(
    (left, right) => left.partial_prose.length - right.partial_prose.length,
  );
  const positioned = ordered.filter(
    (session) =>
      session.partial_prose && node.content.startsWith(session.partial_prose),
  );
  if (!positioned.length)
    return (
      <>
        {ordered.map((session) => (
          <MinigameResult key={session.id} session={session} />
        ))}
        <div className="prose">{node.content}</div>
      </>
    );
  let cursor = 0;
  return (
    <>
      {positioned.map((session) => {
        const end = session.partial_prose.length;
        const prose = node.content.slice(cursor, end);
        cursor = Math.max(cursor, end);
        return (
          <div className="minigame-story-segment" key={session.id}>
            {prose && <div className="prose">{prose}</div>}
            <MinigameResult session={session} />
          </div>
        );
      })}
      <div className="prose">{node.content.slice(cursor).trimStart()}</div>
    </>
  );
}

function ReviewCard({
  review,
  decide,
  fail,
}: {
  review: PendingReview;
  decide: (
    review: PendingReview,
    accept: boolean,
    mutations?: Array<Record<string, unknown>>,
  ) => Promise<void>;
  fail: (message: string) => void;
}) {
  const [mutations, setMutations] = useState(
    JSON.stringify(review.mutations, null, 2),
  );
  async function approve() {
    try {
      const edited = JSON.parse(mutations) as Array<Record<string, unknown>>;
      await decide(review, true, edited);
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }
  return (
    <section className="review-card">
      <strong>
        {review.phase === "pre_prose"
          ? "Major change needs approval before writing"
          : "Story and memory need reconciliation"}
      </strong>
      <p>{review.reason}</p>
      <details>
        <summary>
          Inspect or edit {review.mutations.length} staged change(s)
        </summary>
        <textarea
          className="json-editor"
          value={mutations}
          onChange={(e) => setMutations(e.target.value)}
          spellCheck={false}
        />
      </details>
      <div>
        <button onClick={() => void decide(review, false)}>
          {review.phase === "pre_prose"
            ? "Reject & replan"
            : "Reject & regenerate"}
        </button>
        <button className="primary" onClick={() => void approve()}>
          Approve edited changes
        </button>
      </div>
    </section>
  );
}

function EncounterCard({
  appearance,
  entity,
  workflows,
  fail,
  editable,
}: {
  appearance: SceneAppearance;
  entity?: WorldEntity;
  workflows: WorkflowPreset[];
  fail: (message: string) => void;
  editable: boolean;
}) {
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [generateAsset, setGenerateAsset] = useState<MediaAsset | null>(null);
  const [imagePrompt, setImagePrompt] = useState("");
  const load = useCallback(
    () =>
      api<MediaAsset[]>(`/entities/${appearance.entity_id}/media`).then(
        setAssets,
      ),
    [appearance.entity_id],
  );
  useEffect(() => {
    void load().catch((cause) => fail(errorMessage(cause)));
  }, [load, fail]);
  async function upload(asset: MediaAsset, file: File) {
    const form = new FormData();
    form.append("file", file);
    try {
      await api(
        `/entities/${appearance.entity_id}/media/upload?kind=${asset.kind}${appearance.outfit_id ? `&outfit_id=${appearance.outfit_id}` : ""}`,
        { method: "POST", body: form },
      );
      await load();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }
  async function generate(asset: MediaAsset) {
    const preset = workflows[0];
    if (!preset) {
      fail("Import a ComfyUI workflow first.");
      return;
    }
    setGenerateAsset(asset);
    setImagePrompt(asset.prompt);
  }
  async function confirmGenerate() {
    const asset = generateAsset,
      preset = workflows[0];
    if (!asset || !preset || !imagePrompt.trim()) return;
    try {
      await api(`/media-assets/${asset.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          prompt: imagePrompt,
          negative_prompt: asset.negative_prompt,
        }),
      });
      await api(`/media-assets/${asset.id}/generate`, {
        method: "POST",
        body: JSON.stringify({
          workflow_preset_id: preset.id,
          prompt: imagePrompt,
          negative_prompt: asset.negative_prompt,
          width: preset.mappings.width ? 1024 : null,
          height: preset.mappings.height ? 1024 : null,
        }),
      });
      setGenerateAsset(null);
      await load();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }
  return (
    <>
      <section className="encounter-card">
        <strong>
          First encounter · {entity?.name ?? appearance.encounter_kind}
        </strong>
        <div>
          {assets.map((asset) => (
            <article key={asset.id}>
              {asset.file_path ? (
                <img
                  src={`/media/${asset.file_path}`}
                  alt={`${entity?.name ?? "Entity"} ${asset.kind}`}
                />
              ) : (
                <div className="media-placeholder">{humanize(asset.kind)}</div>
              )}
              <footer>
                <span>{humanize(asset.kind)}</span>
                {editable && <Button component="label">
                  Upload
                  <input
                    hidden
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    onChange={(e) =>
                      e.target.files?.[0] &&
                      void upload(asset, e.target.files[0])
                    }
                  />
                </Button>}
                {editable && <Button
                  disabled={asset.status === "queued"}
                  onClick={() => void generate(asset)}
                >
                  {asset.status === "queued" ? "Queued" : "Generate"}
                </Button>}
              </footer>
            </article>
          ))}
        </div>
      </section>
      <Dialog
        open={Boolean(generateAsset)}
        onClose={() => setGenerateAsset(null)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Generate encounter image</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={5}
            label="Historical image prompt"
            value={imagePrompt}
            onChange={(event) => setImagePrompt(event.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setGenerateAsset(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!imagePrompt.trim()}
            onClick={() => void confirmGenerate()}
          >
            Generate
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

function BranchNavigator({
  nodes,
  trashed,
  selected,
  select,
  restore,
}: {
  nodes: StoryNode[];
  trashed: StoryNode[];
  selected: string | null;
  select: (id: string) => void;
  restore: (node: StoryNode) => void;
}) {
  const depths = new Map<string, number>();
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const depth = (node: StoryNode): number => {
    if (depths.has(node.id)) return depths.get(node.id)!;
    const value =
      node.parent_id && byId.has(node.parent_id)
        ? depth(byId.get(node.parent_id)!) + 1
        : 0;
    depths.set(node.id, value);
    return value;
  };
  return (
    <div className="branch-list">
      {nodes.map((node) => (
        <button
          key={node.id}
          className={selected === node.id ? "active" : ""}
          style={{ paddingLeft: `${12 + Math.min(depth(node), 8) * 10}px` }}
          onClick={() => select(node.id)}
        >
          <span>{node.role === "assistant" ? "✦" : "›"}</span>
          {node.content.slice(0, 64)}
        </button>
      ))}
      {trashed.length > 0 && (
        <details className="trash-list">
          <summary>Trash ({trashed.length})</summary>
          {trashed
            .filter(
              (node) =>
                !node.parent_id ||
                !trashed.some((item) => item.id === node.parent_id),
            )
            .map((node) => (
              <div key={node.id}>
                <span>{node.content.slice(0, 64)}</span>
                <Button size="small" onClick={() => restore(node)}>
                  Restore subtree
                </Button>
              </div>
            ))}
        </details>
      )}
    </div>
  );
}

function BiblePanel({
  documents,
  reload,
  fail,
}: {
  documents: BibleDocument[];
  reload: () => Promise<void>;
  fail: (message: string) => void;
}) {
  const [selectedId, setSelectedId] = useState(documents[0]?.id ?? "");
  const selected =
    documents.find((document) => document.id === selectedId) ?? documents[0];
  const [content, setContent] = useState(selected?.content ?? "");
  const [pendingDocument, setPendingDocument] = useState<string | null>(null);
  useEffect(
    () => setContent(selected?.content ?? ""),
    [selected?.id, selected?.content],
  );
  useEffect(() => {
    document.body.dataset.storyStudioUnsaved = String(
      Boolean(selected && content !== selected.content),
    );
    return () => {
      document.body.dataset.storyStudioUnsaved = "false";
    };
  }, [content, selected]);
  useEffect(() => {
    const warning = (event: BeforeUnloadEvent) => {
      if (selected && content !== selected.content) event.preventDefault();
    };
    window.addEventListener("beforeunload", warning);
    return () => window.removeEventListener("beforeunload", warning);
  }, [content, selected]);
  if (!selected) return null;
  async function save() {
    try {
      await api(`/bible/${selected.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title: selected.title, content }),
      });
      await reload();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }
  function switchDocument(id: string) {
    if (content !== selected.content) setPendingDocument(id);
    else setSelectedId(id);
  }
  return (
    <aside className="bible-panel">
      <header>
        <p className="eyebrow">STORY BIBLE</p>
        <span>Continuity context</span>
      </header>
      <div className="bible-tabs">
        {documents.map((document) => (
          <Button
            key={document.id}
            variant={selected.id === document.id ? "contained" : "outlined"}
            onClick={() => switchDocument(document.id)}
          >
            {document.title}
          </Button>
        ))}
      </div>
      <TextField
        multiline
        value={content}
        onChange={(event) => setContent(event.target.value)}
        placeholder={`Record ${selected.title.toLowerCase()} notes here…`}
      />
      <Button
        variant="contained"
        disabled={content === selected.content}
        onClick={() => void save()}
      >
        Save {selected.title}
      </Button>
      <p className="aside-note">
        Use World → Import story bible to explicitly convert these notes into
        deterministic memory.
      </p>
      <Dialog
        open={Boolean(pendingDocument)}
        onClose={() => setPendingDocument(null)}
      >
        <DialogTitle>Discard unsaved bible changes?</DialogTitle>
        <DialogContent>
          Your edits to {selected.title} have not been saved.
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPendingDocument(null)}>Keep editing</Button>
          <Button
            color="error"
            onClick={() => {
              setSelectedId(pendingDocument!);
              setPendingDocument(null);
            }}
          >
            Discard and switch
          </Button>
        </DialogActions>
      </Dialog>
    </aside>
  );
}

function SuggestionCard({
  suggestion,
  workflows,
  reload,
  fail,
  canDelete,
}: {
  suggestion: ImageSuggestion;
  workflows: WorkflowPreset[];
  reload: () => Promise<void>;
  fail: (message: string) => void;
  canDelete: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(suggestion.title);
  const [prompt, setPrompt] = useState(suggestion.prompt);
  const [negative, setNegative] = useState(suggestion.negative_prompt);
  const [workflowId, setWorkflowId] = useState(workflows[0]?.id ?? "");
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const selectedWorkflow = workflows.find(
    (workflow) => workflow.id === workflowId,
  );
  async function save() {
    await api(`/suggestions/${suggestion.id}`, {
      method: "PATCH",
      body: JSON.stringify({ title, prompt, negative_prompt: negative }),
    });
    setEditing(false);
    await reload();
  }
  async function generate() {
    if (!workflowId) {
      fail("Import a ComfyUI workflow before generating an illustration.");
      return;
    }
    try {
      await save();
      await api(`/suggestions/${suggestion.id}/generate`, {
        method: "POST",
        body: JSON.stringify({
          workflow_preset_id: workflowId,
          prompt,
          negative_prompt: negative,
          seed: Math.floor(Math.random() * 2_147_483_647),
          width: selectedWorkflow?.mappings.width ? width : null,
          height: selectedWorkflow?.mappings.height ? height : null,
        }),
      });
      await reload();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }
  if (suggestion.image_path && !editing)
    return (
      <section className="suggestion-card generated">
        <img src={`/media/${suggestion.image_path}`} alt={suggestion.title} />
        <ImageJobProgress suggestion={suggestion} reload={reload} />
        <div className="suggestion-actions">
          <Tooltip title="Edit illustration">
            <IconButton
              size="small"
              aria-label="Edit illustration"
              onClick={() => setEditing(true)}
            >
              <EditOutlinedIcon />
            </IconButton>
          </Tooltip>
          {canDelete && <SuggestionDeleteButton
            suggestion={suggestion}
            reload={reload}
            fail={fail}
          />}
        </div>
      </section>
    );
  return (
    <section className="suggestion-card">
      <header>
        <span>▧ Illustration idea</span>
        <div>
          <Tooltip
            title={
              editing ? "Close illustration editor" : "Edit illustration idea"
            }
          >
            <IconButton
              size="small"
              aria-label={
                editing ? "Close illustration editor" : "Edit illustration idea"
              }
              onClick={() => setEditing(!editing)}
            >
              {editing ? <CloseIcon /> : <EditOutlinedIcon />}
            </IconButton>
          </Tooltip>
          {canDelete && <SuggestionDeleteButton
            suggestion={suggestion}
            reload={reload}
            fail={fail}
          />}
        </div>
      </header>
      <ImageJobProgress suggestion={suggestion} reload={reload} />
      <strong>{title}</strong>
      {editing ? (
        <>
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe the scene; use {{Exact Name}} to include a world entity's visual description"
          />
          <small className="template-hint">
            Use references such as {"{{Kael}}"}, {"{{Old Tavern}}"}, or{" "}
            {"{{Silver Sword}}"} to inject their branch-correct visual
            descriptions.
          </small>
          <textarea
            value={negative}
            onChange={(e) => setNegative(e.target.value)}
            placeholder="Negative prompt (optional)"
          />
        </>
      ) : (
        <p>{prompt}</p>
      )}
      {suggestion.image_path && (
        <img src={`/media/${suggestion.image_path}`} alt={suggestion.title} />
      )}
      {(selectedWorkflow?.mappings.width ||
        selectedWorkflow?.mappings.height) && (
        <div className="image-options">
          {selectedWorkflow.mappings.width && (
            <label>
              Width
              <input
                type="number"
                min="64"
                max="8192"
                step="64"
                value={width}
                onChange={(e) => setWidth(Number(e.target.value))}
              />
            </label>
          )}
          {selectedWorkflow.mappings.height && (
            <label>
              Height
              <input
                type="number"
                min="64"
                max="8192"
                step="64"
                value={height}
                onChange={(e) => setHeight(Number(e.target.value))}
              />
            </label>
          )}
        </div>
      )}
      <footer>
        <select
          value={workflowId}
          onChange={(e) => setWorkflowId(e.target.value)}
        >
          <option value="">Select workflow</option>
          {workflows.map((workflow) => (
            <option key={workflow.id} value={workflow.id}>
              {workflow.name}
            </option>
          ))}
        </select>
        {editing && (
          <Tooltip title="Save illustration changes">
            <IconButton
              aria-label="Save illustration changes"
              onClick={() => void save()}
            >
              <SaveOutlinedIcon />
            </IconButton>
          </Tooltip>
        )}
        <Tooltip
          title={
            suggestion.status === "queued"
              ? "Image generation is queued"
              : "Generate image"
          }
        >
          <span>
            <IconButton
              className="generate"
              aria-label="Generate image"
              disabled={suggestion.status === "queued"}
              onClick={generate}
            >
              <ImageOutlinedIcon />
            </IconButton>
          </span>
        </Tooltip>
      </footer>
    </section>
  );
}

type ImageJobState = {
  id: string;
  status: string;
  phase?: string | null;
  progress_current?: number | null;
  progress_total?: number | null;
  progress_message?: string | null;
};

function ImageJobProgress({
  suggestion,
  reload,
}: {
  suggestion: ImageSuggestion;
  reload: () => Promise<void>;
}) {
  const [job, setJob] = useState<ImageJobState | null>(() =>
    suggestion.image_job_id
      ? {
          id: suggestion.image_job_id,
          status: suggestion.image_job_status ?? "queued",
          phase: suggestion.image_job_phase,
          progress_current: suggestion.image_progress_current,
          progress_total: suggestion.image_progress_total,
          progress_message: suggestion.image_progress_message,
        }
      : null,
  );
  useEffect(() => {
    if (!suggestion.image_job_id) {
      setJob(null);
      return;
    }
    setJob({
      id: suggestion.image_job_id,
      status: suggestion.image_job_status ?? "queued",
      phase: suggestion.image_job_phase,
      progress_current: suggestion.image_progress_current,
      progress_total: suggestion.image_progress_total,
      progress_message: suggestion.image_progress_message,
    });
  }, [
    suggestion.image_job_id,
    suggestion.image_job_status,
    suggestion.image_job_phase,
    suggestion.image_progress_current,
    suggestion.image_progress_total,
    suggestion.image_progress_message,
  ]);
  useEffect(() => {
    if (!job || !["queued", "running", "switching"].includes(job.status))
      return;
    const timer = window.setInterval(
      () =>
        void api<ImageJobState>(`/jobs/${job.id}`)
          .then((next) => {
            setJob(next);
            if (!["queued", "running", "switching"].includes(next.status))
              void reload();
          })
          .catch(() => undefined),
      700,
    );
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status, reload]);
  if (!job || !["queued", "running", "switching"].includes(job.status))
    return null;
  const current = Number(job.progress_current);
  const total = Number(job.progress_total);
  const determinate =
    Number.isFinite(current) && Number.isFinite(total) && total > 0;
  const percentage = determinate
    ? Math.min(100, Math.max(0, (current / total) * 100))
    : 0;
  const phase = job.phase ?? "queued";
  const label =
    phase === "generating_image" && determinate
      ? `Sampling — ${current} / ${total} steps (${Math.round(percentage)}%)`
      : phase === "switching_to_image" || job.status === "switching"
        ? "Switching models"
        : phase === "restoring_storyteller"
          ? "Restoring storyteller"
          : phase === "saving_image"
            ? "Saving image"
            : job.status === "queued"
              ? "Queued for image generation"
              : job.progress_message || "Generating image";
  return (
    <div className="illustration-progress" role="status" aria-label={label}>
      <span>{label}</span>
      <LinearProgress
        variant={determinate ? "determinate" : "indeterminate"}
        value={percentage}
      />
    </div>
  );
}

function SuggestionDeleteButton({
  suggestion,
  reload,
  fail,
}: {
  suggestion: ImageSuggestion;
  reload: () => Promise<void>;
  fail: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [impact, setImpact] = useState<{
    has_managed_image: boolean;
    final_file_reference: boolean;
    active_job_id?: string | null;
  } | null>(null);
  async function inspect() {
    try {
      setImpact(await api(`/suggestions/${suggestion.id}/delete-impact`));
      setOpen(true);
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }
  async function remove() {
    try {
      await api(`/suggestions/${suggestion.id}`, { method: "DELETE" });
      setOpen(false);
      await reload();
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }
  return (
    <>
      <Tooltip title="Delete illustration">
        <span>
          <IconButton
            size="small"
            color="error"
            aria-label="Delete illustration"
            onClick={() => void inspect()}
          >
            <DeleteOutlineIcon />
          </IconButton>
        </span>
      </Tooltip>
      <Dialog open={open} onClose={() => setOpen(false)}>
        <DialogTitle>Delete illustration?</DialogTitle>
        <DialogContent>
          {impact?.active_job_id
            ? "This illustration is currently generating. Cancel its image operation before deleting it."
            : impact?.final_file_reference
              ? "This also permanently removes the managed image file because nothing else uses it."
              : impact?.has_managed_image
                ? "The image file is shared and will remain available to its other references."
                : "The ungenerated illustration idea will be removed."}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          {impact?.active_job_id ? (
            <Button
              color="error"
              variant="contained"
              onClick={() =>
                void api(`/jobs/${impact.active_job_id}/cancel`, {
                  method: "POST",
                })
                  .then(() => {
                    setOpen(false);
                    fail(
                      "Image cancellation requested. Delete the illustration again when cancellation completes.",
                    );
                  })
                  .catch((cause) => fail(errorMessage(cause)))
              }
            >
              Cancel generation
            </Button>
          ) : (
            <Button
              color="error"
              variant="contained"
              onClick={() => void remove()}
            >
              Delete
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </>
  );
}

function SettingsPanel({
  runtime,
  fail,
  mobileScale,
  setMobileScale,
}: {
  runtime: string;
  fail: (message: string) => void;
  mobileScale: MobileScale;
  setMobileScale: (value: MobileScale) => void;
}) {
  const [settings, setSettings] = useState<RuntimeSettings>(defaultSettings);
  const [contextTokenInput, setContextTokenInput] = useState(String(defaultSettings.context_tokens));
  const [planningContextTokenInput, setPlanningContextTokenInput] = useState(String(defaultSettings.planning_context_tokens));
  const [report, setReport] = useState("");
  useEffect(() => {
    api<RuntimeSettings>("/settings")
      .then((next) => {
        setSettings(next);
        setContextTokenInput(String(next.context_tokens));
        setPlanningContextTokenInput(String(next.planning_context_tokens));
      })
      .catch((cause) => fail(errorMessage(cause)));
  }, [fail]);
  const set = <K extends keyof RuntimeSettings>(
    key: K,
    value: RuntimeSettings[K],
  ) => setSettings((current) => ({ ...current, [key]: value }));
  async function save() {
    try {
      setSettings(
        await api<RuntimeSettings>("/settings", {
          method: "PUT",
          body: JSON.stringify(settings),
        }),
      );
      setReport("Settings saved.");
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }
  async function validate() {
    try {
      const result = await api<{
        valid: boolean;
        issues: string[];
        llama_online: boolean;
        comfy_online: boolean;
      }>("/settings/validate", {
        method: "POST",
        body: JSON.stringify(settings),
      });
      setReport(
        `${result.valid ? "Paths look valid." : result.issues.join(" · ")} llama: ${result.llama_online ? "online" : "offline"}; ComfyUI: ${result.comfy_online ? "online" : "offline"}.`,
      );
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }
  async function start() {
    try {
      await api("/runtime/start", { method: "POST" });
      setReport("Both runtimes are ready; the storyteller owns the GPU.");
    } catch (cause) {
      fail(errorMessage(cause));
    }
  }
  return (
    <div className="page settings-page">
      <header className="page-header">
        <p className="eyebrow">LOCAL INFERENCE</p>
        <h1>Runtime settings</h1>
        <p>
          StoryStudio validates and supervises your existing installations. It
          never downloads models or custom nodes.
        </p>
      </header>
      <section className="panel settings-form">
        <h2>Interface</h2>
        <TextField
          select
          fullWidth
          size="small"
          label="Phone story interface size"
          value={mobileScale}
          onChange={(event) =>
            setMobileScale(event.target.value as MobileScale)
          }
          helperText="Applied only to the Story workspace at phone widths and stored in this browser."
        >
          <MenuItem value="comfortable">Comfortable (100%)</MenuItem>
          <MenuItem value="compact">Compact (80%)</MenuItem>
          <MenuItem value="dense">Dense (65%)</MenuItem>
          <MenuItem value="tiny">Tiny (50%)</MenuItem>
        </TextField>
        <h2>Application data</h2>
        <label>
          Data directory
          <input
            value={settings.data_dir}
            onChange={(e) => set("data_dir", e.target.value)}
            placeholder="C:\Users\You\AppData\Local\StoryStudio"
          />
        </label>
        <p className="muted">
          Changing this copies the current database and images to an empty
          directory; the original remains as a recovery copy.
        </p>
        <h2>Storyteller · llama.cpp</h2>
        <label>
          llama-server executable
          <input
            value={settings.llama_executable}
            onChange={(e) => set("llama_executable", e.target.value)}
            placeholder="C:\AI\llama.cpp\llama-server.exe"
          />
        </label>
        <label>
          GGUF model path
          <input
            value={settings.storyteller_model_path}
            onChange={(e) => set("storyteller_model_path", e.target.value)}
            placeholder="C:\AI\models\storyteller.gguf"
          />
        </label>
        <div className="field-pair">
          <label>
            Model ID override
            <input
              value={settings.storyteller_model_id}
              onChange={(e) => set("storyteller_model_id", e.target.value)}
              placeholder="Defaults to filename"
            />
          </label>
          <label>
            Server URL
            <input
              value={settings.llama_url}
              onChange={(e) => set("llama_url", e.target.value)}
            />
          </label>
        </div>
        <label>
          Extra arguments, one per line
          <textarea
            value={settings.llama_extra_args.join("\n")}
            onChange={(e) =>
              set(
                "llama_extra_args",
                e.target.value.split("\n").filter(Boolean),
              )
            }
          />
        </label>
        <h2>Illustrator · ComfyUI</h2>
        <label>
          Launch command, one argument per line
          <textarea
            value={settings.comfy_command.join("\n")}
            onChange={(e) =>
              set("comfy_command", e.target.value.split("\n").filter(Boolean))
            }
            placeholder={
              "C:\\AI\\ComfyUI\\venv\\Scripts\\python.exe\nmain.py\n--listen\n127.0.0.1"
            }
          />
        </label>
        <div className="field-pair">
          <label>
            Working directory
            <input
              value={settings.comfy_workdir}
              onChange={(e) => set("comfy_workdir", e.target.value)}
            />
          </label>
          <label>
            Server URL
            <input
              value={settings.comfy_url}
              onChange={(e) => set("comfy_url", e.target.value)}
            />
          </label>
        </div>
        <h3>Semantic image profiles</h3>
        <label>
          Portrait required prefix
          <textarea
            value={settings.portrait_prompt_prefix}
            onChange={(e) => set("portrait_prompt_prefix", e.target.value)}
          />
        </label>
        <label>
          Full-body required prefix
          <textarea
            value={settings.full_body_prompt_prefix}
            onChange={(e) => set("full_body_prompt_prefix", e.target.value)}
          />
        </label>
        <label>
          Icon required prefix
          <textarea
            value={settings.icon_prompt_prefix}
            onChange={(e) => set("icon_prompt_prefix", e.target.value)}
          />
        </label>
        <p className="muted">
          StoryStudio prepends these to typed portrait, full-body, and icon prompts. Portraits, full-body images, and icons require the workflow&apos;s transparent output; backgrounds use the normal output.
        </p>
        <label>
          Story context tokens
          <input
            type="number"
            min="2048"
            max="131072"
            value={contextTokenInput}
            onChange={(e) => setContextTokenInput(e.target.value)}
            onBlur={() => {
              const parsed = Number(contextTokenInput);
              if (!Number.isInteger(parsed) || parsed < 2048 || parsed > 131072) {
                setContextTokenInput(String(settings.context_tokens));
                return;
              }
              set("context_tokens", parsed);
              if (settings.planning_context_tokens < parsed) {
                set("planning_context_tokens", parsed);
                setPlanningContextTokenInput(String(parsed));
              }
              setContextTokenInput(String(parsed));
            }}
          />
        </label>
        <label>
          Preplanning context tokens
          <input
            type="number"
            min={settings.context_tokens}
            max="131072"
            value={planningContextTokenInput}
            onChange={(e) => setPlanningContextTokenInput(e.target.value)}
            onBlur={() => {
              const parsed = Number(planningContextTokenInput);
              if (!Number.isInteger(parsed) || parsed < settings.context_tokens || parsed > 131072) {
                setPlanningContextTokenInput(String(settings.planning_context_tokens));
                return;
              }
              set("planning_context_tokens", parsed);
              setPlanningContextTokenInput(String(parsed));
            }}
          />
        </label>
        <div className="button-row">
          <button
            type="button"
            onClick={() => {
              const recommended = Math.max(32768, settings.context_tokens);
              set("planning_context_tokens", recommended);
              setPlanningContextTokenInput(String(recommended));
            }}
          >
            Use recommended 32K
          </button>
        </div>
        <p className="muted">
          Larger planning contexts increase llama.cpp KV-cache memory. Do not exceed the model&apos;s native context unless its RoPE settings are configured deliberately. StoryStudio switches back before ordinary story generation.
        </p>
        <h2>World memory</h2>
        <label>
          Retrieval provider
          <select
            value={settings.memory_provider}
            onChange={(e) =>
              set(
                "memory_provider",
                e.target.value as RuntimeSettings["memory_provider"],
              )
            }
          >
            <option value="builtin">Built-in SQLite FTS + graph</option>
            <option value="cognee">Cognee (optional CPU index)</option>
          </select>
        </label>
        <p className="muted">
          SQLite remains canonical. Cognee only proposes candidates and falls
          back safely if unavailable.
        </p>
        {report && <p className="validation-report">{report}</p>}
        <div className="button-row">
          <button onClick={validate}>Validate</button>
          <button onClick={save}>Save settings</button>
          <button
            className="primary"
            disabled={
              !settings.llama_executable ||
              !settings.comfy_command.length ||
              runtime === "loading_storyteller"
            }
            onClick={start}
          >
            Start runtimes
          </button>
        </div>
      </section>
    </div>
  );
}

function LoginScreen({ onLogin }: { onLogin: (user: AuthUser) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setFailure("");
    try {
      const result = await api<{ user: AuthUser }>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
      setPassword(""); onLogin(result.user);
    } catch (cause) { setFailure(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  return <main className="login-shell">
    <Paper component="form" className="login-card" elevation={10} onSubmit={submit}>
      <span className="brand-mark">S</span><h1>StoryStudio</h1><p>Sign in to join the story.</p>
      {failure && <Alert severity="error">{failure}</Alert>}
      <TextField autoFocus autoComplete="username" label="Username" value={username} onChange={event => setUsername(event.target.value)} />
      <TextField autoComplete="current-password" type="password" label="Password" value={password} onChange={event => setPassword(event.target.value)} />
      <Button type="submit" variant="contained" disabled={busy || !username.trim() || !password}>{busy ? "Signing in…" : "Sign in"}</Button>
      <small>First start: run bootstrap-admin.ps1 locally.</small>
    </Paper>
  </main>;
}

function EmptyState({ create }: { create: () => void }) {
  return (
    <div className="empty-state">
      <span>✦</span>
      <h1>Your stories live here</h1>
      <p>
        Create the first project, shape its story bible, then begin writing with
        your local storyteller.
      </p>
      <button className="primary" onClick={create}>
        Create a story
      </button>
    </div>
  );
}
function humanize(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}
function errorMessage(cause: unknown) {
  return cause instanceof Error ? cause.message : String(cause);
}
