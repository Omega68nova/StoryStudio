import { useEffect, useRef } from "react";

type LiveEvent = {
  type: string;
  payload: Record<string, unknown>;
};

type LiveEventOptions = {
  enabled: boolean;
  projectId?: string | null;
  onRuntime: (state: string, jobId: string | null) => void;
  onToken: (text: string) => void;
  onRefresh: () => void | Promise<void>;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
  onAuthLost: () => void;
  onMusicChanged?: (payload: Record<string, unknown>) => void;
};

const REFRESH_EVENT_TYPES = new Set([
  "story",
  "suggestion",
  "image",
  "memory_changed",
  "world_head",
  "approval_required",
  "planning",
  "npc",
  "encounter",
  "media",
  "music",
  "environment",
  "stats",
  "minigame",
]);

const JOB_REFRESH_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
  "awaiting_review",
  "awaiting_minigame",
]);

export function useLiveEvents(options: LiveEventOptions): void {
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    if (!options.enabled) return;

    let disposed = false;
    let socket: WebSocket | null = null;
    let retryTimer: number | null = null;
    let retryAttempt = 0;
    let hasConnected = false;

    const refresh = () => {
      const current = optionsRef.current;
      if (!current.projectId) return;
      void Promise.resolve(current.onRefresh()).catch((error) => {
        current.onError(
          error instanceof Error ? error.message : String(error),
        );
      });
    };

    const scheduleReconnect = () => {
      if (disposed || retryTimer !== null) return;
      const delay = Math.min(500 * 2 ** retryAttempt, 5000);
      retryAttempt += 1;
      retryTimer = window.setTimeout(() => {
        retryTimer = null;
        connect();
      }, delay);
    };

    const connect = () => {
      if (disposed) return;

      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(
        `${protocol}://${window.location.host}/api/events`,
      );

      socket.onopen = () => {
        const reconnect = hasConnected;
        hasConnected = true;
        retryAttempt = 0;

        // The EventHub is intentionally ephemeral. Anything that happened
        // while disconnected must be recovered from canonical API state.
        if (reconnect) refresh();
      };

      socket.onmessage = (message) => {
        const current = optionsRef.current;

        let event: LiveEvent;
        try {
          event = JSON.parse(message.data) as LiveEvent;
        } catch {
          return;
        }

        if (event.type === "runtime") {
          current.onRuntime(
            String(event.payload.state ?? "idle"),
            event.payload.job_id
              ? String(event.payload.job_id)
              : null,
          );
        }

        if (event.type === "token") {
          current.onToken(String(event.payload.text ?? ""));
        }

        let shouldRefresh = REFRESH_EVENT_TYPES.has(event.type);

        // Generic job events are a safety net. Persistence is canonical, so
        // terminal/interactive state changes should refresh the active project
        // even if a domain-specific event is accidentally omitted later.
        if (
          event.type === "job" &&
          JOB_REFRESH_STATUSES.has(String(event.payload.status ?? ""))
        ) {
          shouldRefresh = true;
        }

        if (shouldRefresh && current.projectId) {
          current.onToken("");
          refresh();
        }

        if (event.type === "error") {
          current.onError(String(event.payload.message ?? "Server error"));
          refresh();
        }

        if (event.type === "notice") {
          current.onNotice(String(event.payload.message ?? ""));
        }

        if (
          event.type === "music" &&
          event.payload.action === "playback_changed"
        ) {
          current.onMusicChanged?.(event.payload);
        }
      };

      socket.onerror = () => {
        // onclose performs the actual reconnect scheduling.
      };

      socket.onclose = (event) => {
        socket = null;
        if (disposed) return;

        if (event.code === 1008) {
          optionsRef.current.onAuthLost();
          return;
        }

        scheduleReconnect();
      };
    };

    connect();

    return () => {
      disposed = true;
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
        retryTimer = null;
      }
      socket?.close();
      socket = null;
    };
  }, [options.enabled]);
}
