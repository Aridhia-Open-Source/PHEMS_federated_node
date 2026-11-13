import { useSyncExternalStore } from "react";

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
