import { useMemo, useSyncExternalStore } from "react";

const KEY = "fn-token";
let token: string | null = sessionStorage.getItem(KEY);
const listeners = new Set<() => void>();

export function getToken() {
  return token;
}

export function setToken(t: string | null) {
  token = t;
  if (t) sessionStorage.setItem(KEY, t);
  else sessionStorage.removeItem(KEY);
  listeners.forEach((l) => l());
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

// The viewer's groups, as nexus-api reads them from the token (helpers/wrappers.py:token_groups): its
// realm roles and its Keycloak groups. The UI only uses them to grey out what the API would refuse.
export function tokenGroups(t: string | null): Set<string> {
  const payload = t?.split(".")[1];
  if (!payload) return new Set();
  try {
    const claims = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    const roles: string[] = claims.realm_access?.roles ?? [];
    const groups: string[] = (claims.groups ?? []).map((g: string) => g.replace(/^\//, ""));
    return new Set([...roles, ...groups]);
  } catch {
    return new Set();
  }
}

export function useViewerGroups() {
  const t = useToken();
  return useMemo(() => tokenGroups(t), [t]);
}
