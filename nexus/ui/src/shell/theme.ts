import { useSyncExternalStore } from "react";

// Same key and rule as the inline script in index.html, which applies the class before
// first paint: an explicit choice wins, otherwise follow the system setting.
const KEY = "fn-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

export type Theme = "light" | "dark";

const root = document.documentElement;

function storedChoice(): Theme | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function apply(theme: Theme) {
  root.classList.toggle("dark", theme === "dark");
}

// The class on <html> is the single source of truth, so the inline script, the toggle and
// system changes all agree.
function current(): Theme {
  return root.classList.contains("dark") ? "dark" : "light";
}

function subscribe(onChange: () => void) {
  const media = window.matchMedia(DARK_QUERY);
  const followSystem = () => {
    if (!storedChoice()) apply(media.matches ? "dark" : "light");
  };
  media.addEventListener("change", followSystem);
  const observer = new MutationObserver(onChange);
  observer.observe(root, { attributes: true, attributeFilter: ["class"] });
  return () => {
    media.removeEventListener("change", followSystem);
    observer.disconnect();
  };
}

function choose(theme: Theme) {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Private windows and blocked storage: the choice just lasts until reload.
  }
  apply(theme);
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const theme = useSyncExternalStore(subscribe, current);
  return { theme, toggle: () => choose(theme === "dark" ? "light" : "dark") };
}
