import { FormEvent, ReactNode, useEffect, useRef } from "react";
import { Fab, IconButton, MenuItem, TextField, ToggleButton, ToggleButtonGroup, Tooltip } from "@mui/material";
import AutoStoriesIcon from "@mui/icons-material/AutoStories";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import DirectionsRunIcon from "@mui/icons-material/DirectionsRun";
import EditIcon from "@mui/icons-material/Edit";
import ExploreOutlinedIcon from "@mui/icons-material/ExploreOutlined";
import ImageOutlinedIcon from "@mui/icons-material/ImageOutlined";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import ReplayIcon from "@mui/icons-material/Replay";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import ArrowForwardIcon from "@mui/icons-material/ArrowForward";

export type StoryAction = "story" | "say" | "do" | "guide";
export type GenerationMode = "direct" | "low" | "smart";

type StoryComposerProps = {
  expanded: boolean;
  message: string;
  action: StoryAction;
  generationMode: GenerationMode;
  runtime: string;
  busy: boolean;
  setExpanded: (expanded: boolean) => void;
  setMessage: (message: string) => void;
  setAction: (action: StoryAction) => void;
  setGenerationMode: (mode: GenerationMode) => void;
  submit: (event?: FormEvent, requestedAction?: StoryAction | "continue") => void | Promise<void>;
  see: () => void | Promise<void>;
  retry: () => void | Promise<void>;
  retryWithGuide: () => void;
  erase: () => void | Promise<void>;
};

export function StoryComposer(props: StoryComposerProps) {
  const { expanded, message, action, generationMode, runtime, busy, setExpanded, setMessage, setAction, setGenerationMode, submit, see, retry, retryWithGuide, erase } = props;
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const wasExpanded = useRef(expanded);

  useEffect(() => {
    if (expanded && !wasExpanded.current) requestAnimationFrame(() => inputRef.current?.focus());
    wasExpanded.current = expanded;
  }, [expanded]);

  if (!expanded) {
    return <Tooltip title="Open story input">
      <Fab className="composer-toggle" size="medium" color="primary" aria-label="Open story input" onClick={() => setExpanded(true)}>
        <EditIcon />
      </Fab>
    </Tooltip>;
  }

  const actions: Array<[StoryAction, ReactNode, string]> = [
    ["story", <AutoStoriesIcon />, "Story"],
    ["say", <ChatBubbleOutlineIcon />, "Say"],
    ["do", <DirectionsRunIcon />, "Do"],
    ["guide", <ExploreOutlinedIcon />, "Guide"]
  ];

  const hasMessage = Boolean(message.trim());

  return <form className="composer" onSubmit={(event) => void submit(event, hasMessage ? action : "continue")}>
    <div className="action-toolbar">
      <ToggleButtonGroup exclusive size="small" value={action} onChange={(_, value) => value && setAction(value)}>
        {actions.map(([value, icon, tip]) => <Tooltip key={value} title={tip}>
          <ToggleButton value={value} aria-label={value}>{icon}</ToggleButton>
        </Tooltip>)}
      </ToggleButtonGroup>
      <TextField select size="small" value={generationMode} onChange={(event) => setGenerationMode(event.target.value as GenerationMode)} inputProps={{ "aria-label": "Story planning mode" }} sx={{ minWidth: 86 }}>
        <MenuItem value="direct">Direct</MenuItem><MenuItem value="low">Low</MenuItem><MenuItem value="smart">Smart</MenuItem>
      </TextField>
      <Tooltip title="Generate an image of the current scene"><IconButton type="button" onClick={() => void see()}><ImageOutlinedIcon /></IconButton></Tooltip>
      <Tooltip title="Retry"><span><IconButton type="button" aria-label="Retry" disabled={busy} onClick={() => void retry()}><ReplayIcon /></IconButton></span></Tooltip>
      <Tooltip title="Retry with guide"><span><IconButton type="button" aria-label="Retry with guide" disabled={busy} onClick={retryWithGuide}><span className="retry-guide-icon"><ReplayIcon /><b>e</b></span></IconButton></span></Tooltip>
      <Tooltip title="Erase"><span><IconButton type="button" aria-label="Erase" disabled={busy} onClick={() => void erase()}><DeleteOutlineIcon /></IconButton></span></Tooltip>
      <span className="composer-toolbar-spacer" />
      <Tooltip title="Minimize story input"><IconButton type="button" aria-label="Minimize story input" onClick={() => setExpanded(false)}><KeyboardArrowDownIcon /></IconButton></Tooltip>
    </div>
    <textarea ref={inputRef} value={message} onChange={(event) => setMessage(event.target.value)} placeholder={actionPlaceholder(action)} rows={3} onKeyDown={(event) => {
      if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); }
    }} />
    <footer><span className="composer-hint">Enter to submit · Shift+Enter for a new line</span><Tooltip title={hasMessage ? `Submit ${action}` : "Continue story"}><span><IconButton type="submit" color="primary" aria-label={hasMessage ? `Submit ${action}` : "Continue story"} disabled={busy}><ArrowForwardIcon /></IconButton></span></Tooltip></footer>
    {runtime === "generating_image" && <div className="queue-note">Your story request will wait until image generation finishes.</div>}
  </form>;
}

function actionPlaceholder(action: StoryAction) {
  return ({ story: "Write the next passage yourself…", say: "What does your character say?", do: "What does your character attempt?", guide: "Guide the storyteller's next response…" })[action];
}
