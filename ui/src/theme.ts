// Light / dark / system theme. "system" is the default: no data-theme on <html>, the OS decides.
// A stored choice wins. Storage can be missing or throw (private window, blocked data): never rely on it.
import { ref } from "vue";

export type ThemeMode = "system" | "light" | "dark";
export const THEME_KEY = "moshfilm.theme";
export const THEME_MODES: ThemeMode[] = ["system", "light", "dark"];

export function loadTheme(): ThemeMode {
  try {
    const raw = localStorage.getItem(THEME_KEY);
    return raw === "light" || raw === "dark" ? raw : "system";
  } catch {
    return "system";
  }
}

export function saveTheme(mode: ThemeMode): void {
  try {
    if (mode === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, mode);
  } catch {
    /* not remembered; the switch still works for this visit */
  }
}

export function applyTheme(mode: ThemeMode): void {
  const root = document.documentElement;
  if (mode === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", mode);
}

const mode = ref<ThemeMode>("system");

/** Read the stored choice and apply it. Call once at startup (the inline script in index.html already did it before first paint). */
export function initTheme(): ThemeMode {
  mode.value = loadTheme();
  applyTheme(mode.value);
  return mode.value;
}

export function useTheme(): { mode: typeof mode; set(next: ThemeMode): void } {
  return {
    mode,
    set(next) {
      mode.value = next;
      applyTheme(next);
      saveTheme(next);
    },
  };
}
