import { useMemo, useSyncExternalStore } from "react";

// The access token is sent as the Bearer; the refresh token only goes to /refresh_token (ADR 0036).
const KEY = "fn-token";
const REFRESH_KEY = "fn-refresh-token";
let token: string | null = sessionStorage.getItem(KEY);
let refreshToken: string | null = sessionStorage.getItem(REFRESH_KEY);
const listeners = new Set<() => void>();

function store(key: string, value: string | null) {
  if (value) sessionStorage.setItem(key, value);
  else sessionStorage.removeItem(key);
}

export function getToken() {
  return token;
}

export function getRefreshToken() {
  return refreshToken;
}

// Both tokens from /login or /refresh_token; null logs out.
export function setToken(t: string | null, refresh: string | null = null) {
  token = t;
  refreshToken = t ? refresh : null;
  store(KEY, token);
  store(REFRESH_KEY, refreshToken);
  listeners.forEach((l) => l());
}

function claims(t: string | null): Record<string, unknown> | null {
  const payload = t?.split(".")[1];
  if (!payload) return null;
  try {
    return JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

// True when the token expires within `marginSeconds` (or has no readable exp).
export function expiresSoon(t: string | null, marginSeconds = 30, now = Date.now()): boolean {
  const exp = claims(t)?.exp;
  return typeof exp !== "number" || exp * 1000 - now < marginSeconds * 1000;
}

export function useToken() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => token,
  );
}

// The viewer's groups from the token: its realm roles and its Keycloak groups. The UI only uses them to
// grey out what the API would refuse.
export function tokenGroups(t: string | null): Set<string> {
  const c = claims(t) as { realm_access?: { roles?: string[] }; groups?: string[] } | null;
  if (!c) return new Set();
  const roles: string[] = c.realm_access?.roles ?? [];
  const groups: string[] = (c.groups ?? []).map((g: string) => g.replace(/^\//, ""));
  return new Set([...roles, ...groups]);
}

export function useViewerGroups() {
  const t = useToken();
  return useMemo(() => tokenGroups(t), [t]);
}
