import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Slider,
  Stack,
  Tooltip,
  Typography,
  useTheme,
} from "@mui/material";
import { Rnd } from "react-rnd";
import MusicNoteIcon from "@mui/icons-material/MusicNote";
import RemoveIcon from "@mui/icons-material/Remove";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import PauseIcon from "@mui/icons-material/Pause";
import StopIcon from "@mui/icons-material/Stop";
import SkipNextIcon from "@mui/icons-material/SkipNext";
import SkipPreviousIcon from "@mui/icons-material/SkipPrevious";
import { api } from "./api";
import type { MusicTheme, ProjectMusic } from "./types";

export function MusicPlayer({
  projectId,
  revision,
  fail,
}: {
  projectId: string;
  revision: number;
  fail: (message: string) => void;
}) {
  const muiTheme = useTheme();
  const storageKey = `storystudio-player-${projectId}`;
  const saved = (() => {
    try {
      return JSON.parse(localStorage.getItem(storageKey) || "{}");
    } catch {
      return {};
    }
  })();
  const [themes, setThemes] = useState<MusicTheme[]>([]);
  const [settings, setSettings] = useState<ProjectMusic | null>(null);
  const [trackId, setTrackId] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [minimized, setMinimized] = useState(Boolean(saved.minimized));
  const [position, setPosition] = useState(
    saved.position ?? {
      x: Math.max(12, innerWidth - 500),
      y: Math.max(12, innerHeight - 150),
    },
  );
  const audio = useRef<HTMLAudioElement>(null);
  const previousTheme = useRef<string | null>(null);
  const load = useCallback(async () => {
    const [library, config] = await Promise.all([
      api<MusicTheme[]>("/music/themes"),
      api<ProjectMusic>(`/projects/${projectId}/music`),
    ]);
    let localVolume: number | undefined;
    try {
      const local = JSON.parse(localStorage.getItem(`storystudio-player-${projectId}`) || "{}");
      if (typeof local.volume === "number") localVolume = local.volume;
    } catch { /* Ignore a damaged browser preference. */ }
    setThemes(library);
    setSettings({
      ...config,
      volume: localVolume ?? config.volume,
    });
  }, [projectId]);
  useEffect(() => {
    void load().catch((cause) => fail(String(cause)));
  }, [load, revision, fail]);
  useEffect(() => {
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        minimized,
        position,
        volume: settings?.volume,
      }),
    );
  }, [
    storageKey,
    minimized,
    position,
    settings?.volume,
  ]);
  useEffect(() => {
    const clamp = () =>
      setPosition((current: { x: number; y: number }) =>
        clampPosition(current, minimized),
      );
    clamp();
    window.addEventListener("resize", clamp);
    window.addEventListener("storystudio-layout-change", clamp);
    const observer = new MutationObserver(clamp);
    observer.observe(document.body, {
      attributes: true,
      childList: true,
      subtree: false,
    });
    return () => {
      window.removeEventListener("resize", clamp);
      window.removeEventListener("storystudio-layout-change", clamp);
      observer.disconnect();
    };
  }, [minimized]);
  useEffect(() => {
    audio.current?.pause();
    setPlaying(false);
    setTrackId(null);
    previousTheme.current = null;
  }, [projectId]);
  useEffect(() => {
    const playTrack = (raw: Event) => {
      const detail = (raw as CustomEvent<{ themeId: string; trackId: string }>)
        .detail;
      if (!detail || !themes.some((item) => item.id === detail.themeId)) return;
      setSettings((current) =>
        current ? { ...current, shared_theme_id: detail.themeId, current_track_id: detail.trackId } : current,
      );
      setTrackId(detail.trackId);
      void syncSelection(detail.themeId, detail.trackId);
      setPlaying(true);
      setMinimized(false);
    };
    window.addEventListener("storystudio-play-track", playTrack);
    return () =>
      window.removeEventListener("storystudio-play-track", playTrack);
  }, [themes]);
  const themeId =
    settings?.mode === "ai_managed"
      ? settings.current_theme_id
      : settings?.shared_theme_id ?? settings?.manual_theme_id;
  const theme = themes.find((item) => item.id === themeId);
  const track = useMemo(
    () =>
      themes
        .flatMap((item) => item.tracks)
        .find((item) => item.id === trackId) ?? null,
    [themes, trackId],
  );
  useEffect(() => {
    const selectedTrack = theme?.tracks.find((item) => item.id === settings?.current_track_id)?.id;
    if (previousTheme.current === themeId && (!selectedTrack || selectedTrack === trackId)) return;
    previousTheme.current = themeId ?? null;
    setTrackId(selectedTrack ?? theme?.tracks[0]?.id ?? null);
  }, [themeId, theme, settings?.current_track_id]);
  useEffect(() => {
    const element = audio.current;
    if (!element) return;
    if (!playing || !track) {
      element.pause();
      return;
    }
    element.volume = settings?.volume ?? 0.7;
    void element.play().catch(() => setPlaying(false));
  }, [track?.id, playing, settings?.volume]);
  function syncSelection(selectedThemeId: string, selectedTrackId: string) {
    return api(`/projects/${projectId}/music/playback`, {
      method: "PUT",
      body: JSON.stringify({ theme_id: selectedThemeId, track_id: selectedTrackId }),
    }).catch((cause) => fail(String(cause)));
  }
  function chooseTrack(selectedTrackId: string) {
    if (!themeId) return;
    setTrackId(selectedTrackId);
    setSettings((current) => current ? { ...current, shared_theme_id: themeId, current_track_id: selectedTrackId } : current);
    void syncSelection(themeId, selectedTrackId);
  }
  function adjacent(delta: number) {
    if (!theme?.tracks.length) return;
    const index = Math.max(
      0,
      theme.tracks.findIndex((item) => item.id === trackId),
    );
    chooseTrack(theme.tracks[(index + delta + theme.tracks.length) % theme.tracks.length].id);
  }
  function next() {
    if (!theme?.tracks.length || !audio.current) return;
    if (theme.tracks.length === 1 || theme.playback_mode === "repeat_one") {
      audio.current.currentTime = 0;
      setPlaying(true);
      void audio.current.play().catch(() => setPlaying(false));
      return;
    }
    if (theme.playback_mode === "in_order") {
      adjacent(1);
      return;
    }
    const choices = theme.tracks.filter((item) => item.id !== trackId);
    chooseTrack(choices[Math.floor(Math.random() * choices.length)].id);
  }
  function stop() {
    const element = audio.current;
    if (element) {
      element.pause();
      element.currentTime = 0;
      element.removeAttribute("src");
      element.load();
    }
    setPlaying(false);
    setTrackId(null);
  }
  function selectTheme(value: string) {
    const selected = themes.find((item) => item.id === value);
    const firstTrack = selected?.tracks[0];
    if (!settings || !selected || !firstTrack) return;
    setSettings({ ...settings, shared_theme_id: value, current_track_id: firstTrack.id });
    setTrackId(firstTrack.id);
    void syncSelection(value, firstTrack.id);
  }
  if (!settings || settings.mode === "disabled") return null;
  return (
    <Rnd
      bounds="window"
      position={position}
      size={{
        width: minimized ? 54 : Math.min(470, innerWidth - 16),
        height: minimized ? 54 : 112,
      }}
      enableResizing={false}
      onDragStop={(_, data) =>
        setPosition(clampPosition({ x: data.x, y: data.y }, minimized))
      }
      dragHandleClassName="music-drag-handle"
      cancel=".music-player-click"
      style={{ zIndex: muiTheme.zIndex.fab }}
    >
      <Paper
        className={`music-player-rnd ${minimized ? "minimized music-drag-handle" : ""}`}
        elevation={10}
      >
        <audio
          ref={audio}
          src={track ? `/media/${track.file_path}` : undefined}
          loop={Boolean(theme?.tracks.length === 1)}
          onEnded={next}
        />
        {minimized ? (
          <Tooltip title="Open music player">
            <IconButton
              className="music-player-click"
              aria-label="Open music player"
              onClick={() => setMinimized(false)}
            >
              <MusicNoteIcon color={playing ? "secondary" : "inherit"} />
            </IconButton>
          </Tooltip>
        ) : (
          <>
            <Stack
              className="music-player-header music-drag-handle"
              direction="row"
              alignItems="center"
              spacing={1}
            >
              <MusicNoteIcon />
              <Typography variant="subtitle2" noWrap sx={{ flex: 1 }}>
                {track?.title ?? theme?.name ?? "Music"}
              </Typography>
              <Tooltip title="Minimize">
                <IconButton
                  className="music-player-click"
                  aria-label="Minimize music player"
                  size="small"
                  onClick={() => setMinimized(true)}
                >
                  <RemoveIcon />
                </IconButton>
              </Tooltip>
            </Stack>
            <Divider className="music-player-separator" />
            <Stack
              className="music-player-body"
              direction="row"
              alignItems="center"
              spacing={1}
            >
              <FormControl size="small" sx={{ minWidth: 150 }}>
                <InputLabel>Theme</InputLabel>
                <Select
                  label="Theme"
                  value={themeId ?? ""}
                  disabled={settings.mode !== "player_managed"}
                  onChange={(e) => selectTheme(e.target.value)}
                >
                  {themes
                    .filter((item) =>
                      settings.enabled_theme_ids.includes(item.id),
                    )
                    .map((item) => (
                      <MenuItem key={item.id} value={item.id}>
                        {item.name}
                      </MenuItem>
                    ))}
                </Select>
              </FormControl>
              <IconButton onClick={() => adjacent(-1)}>
                <SkipPreviousIcon />
              </IconButton>
              <IconButton
                onClick={() => {
                  if (!trackId && theme?.tracks[0])
                    setTrackId(theme.tracks[0].id);
                  setPlaying(!playing);
                }}
              >
                {playing ? <PauseIcon /> : <PlayArrowIcon />}
              </IconButton>
              <IconButton onClick={stop}>
                <StopIcon />
              </IconButton>
              <IconButton onClick={next}>
                <SkipNextIcon />
              </IconButton>
              <Slider
                size="small"
                min={0}
                max={1}
                step={0.05}
                value={settings.volume}
                onChange={(_, value) =>
                  setSettings({ ...settings, volume: Number(value) })
                }
                sx={{ width: 85 }}
              />
            </Stack>
          </>
        )}
      </Paper>
    </Rnd>
  );
}

function clampPosition(current: { x: number; y: number }, minimized: boolean) {
  const width = minimized ? 54 : Math.min(470, innerWidth - 16),
    height = minimized ? 54 : 112;
  const stage = document.querySelector(".stage")?.getBoundingClientRect();
  const composer = document.querySelector(".composer")?.getBoundingClientRect();
  const composerToggle = document
    .querySelector(".composer-toggle")
    ?.getBoundingClientRect();
  const drawer = document
    .querySelector(".MuiDrawer-paper")
    ?.getBoundingClientRect();
  const left = (stage?.left ?? 0) + 8,
    right =
      Math.min(stage?.right ?? innerWidth, drawer?.left ?? innerWidth) - 8;
  const top = (stage?.top ?? 0) + 50,
    bottom =
      Math.min(
        stage?.bottom ?? innerHeight,
        composer?.top ?? composerToggle?.top ?? innerHeight,
      ) - 8;
  return {
    x: Math.max(left, Math.min(current.x, right - width)),
    y: Math.max(top, Math.min(current.y, Math.max(top, bottom - height))),
  };
}
