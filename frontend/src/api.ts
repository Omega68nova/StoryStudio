export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = init?.body instanceof FormData ? init?.headers : { "Content-Type": "application/json", ...init?.headers };
  const response = await fetch(`/api${path}`, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  if (response.status === 401) window.dispatchEvent(new Event("storystudio-auth-lost"));
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      const detail = body.detail ?? body;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail.message === "string") {
        const actions = Array.isArray(detail.recovery_actions) && detail.recovery_actions.length
          ? ` (${detail.recovery_actions.map((action: string) => action.replaceAll("_", " ")).join(" or ")})`
          : "";
        message = `${detail.message}${actions}`;
      } else message = JSON.stringify(detail);
    } catch {
      // Keep the HTTP status when the backend did not return JSON.
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
