import createClient, { type Middleware } from "openapi-fetch";
import type { paths, components } from "./schema";
import { expiresSoon, getRefreshToken, getToken, setToken } from "./auth";
import { showToast } from "../shared/toast";

export type Schemas = components["schemas"];
// The API's paged lists (fastapi-pagination: query params page and size)
export type Page<T> = { items: T[]; page: number; size: number; total: number; pages: number };

export const API_BASE = `${import.meta.env.BASE_URL}api`;

// Turns a failed response into the toast text: {"error"} plus "details" when present,
// or the status text when the body isn't JSON (e.g. an nginx 502 page).
export async function errorText(response: Response): Promise<string> {
  if (response.status === 403) return "Not allowed";
  try {
    const body = await response.clone().json();
    const details = body.details ? ` (${typeof body.details === "string" ? body.details : JSON.stringify(body.details)})` : "";
    return `${body.error ?? JSON.stringify(body)}${details}`;
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

// Swaps the refresh token for a new pair; on failure the session ends. Concurrent callers share one call.
let refreshing: Promise<void> | null = null;
export function refreshSession(): Promise<void> {
  refreshing ??= (async () => {
    const response = await fetch(`${API_BASE}/refresh_token`, {
      method: "POST",
      headers: { Authorization: `Bearer ${getRefreshToken()}` },
    });
    if (!response.ok) {
      setToken(null);
      return;
    }
    const body = await response.json();
    setToken(body.token, body.refresh_token);
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

// Access tokens live 5 minutes: refresh just before one expires, then send it.
const auth: Middleware = {
  async onRequest({ request }) {
    if (getToken() && getRefreshToken() && expiresSoon(getToken())) await refreshSession();
    const t = getToken();
    if (t) request.headers.set("Authorization", `Bearer ${t}`);
    return request;
  },
};

const errors: Middleware = {
  async onResponse({ request, response }) {
    if (response.ok) return response;
    if (response.status === 401 && !request.url.endsWith("/login")) {
      setToken(null);
      showToast("Session expired, log in again");
      return response;
    }
    showToast(await errorText(response));
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: API_BASE });
api.use(auth, errors);

// Same as `api` without the error toasts, for calls where a 4xx is an expected answer
// (a task created by hand has no pull request trigger: 404).
export const quietApi = createClient<paths>({ baseUrl: API_BASE });
quietApi.use(auth);

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Unwraps an openapi-fetch result for TanStack Query: data on success, throws otherwise.
// The middleware has already shown the toast.
export async function call<T>(
  p: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, response } = await p;
  if (!response.ok) throw new ApiError(response.status, response.statusText);
  return data as T;
}
