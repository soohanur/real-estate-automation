"use client";

/**
 * Theme preference: "system" | "light" | "dark".
 *
 * "system" is *resolved* to light/dark in JS and stamped onto
 * <html data-theme="...">, so CSS (and Tailwind's `dark:` variant) only
 * ever deals with two concrete states. The preference lives in
 * localStorage and is re-read by the inline script in layout.tsx before
 * first paint (no flash of the wrong theme).
 */
import { useCallback, useEffect, useState } from "react";
import { DEFAULT_THEME, THEME_KEY, type ResolvedTheme, type Theme } from "./theme-init";

export { DEFAULT_THEME, THEME_KEY };
export type { ResolvedTheme, Theme };

export function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function resolveTheme(pref: Theme): ResolvedTheme {
  return pref === "system" ? systemTheme() : pref;
}

export function readTheme(): Theme {
  if (typeof window === "undefined") return DEFAULT_THEME;
  const v = window.localStorage.getItem(THEME_KEY);
  return v === "light" || v === "dark" || v === "system" ? v : DEFAULT_THEME;
}

export function applyTheme(pref: Theme): ResolvedTheme {
  const resolved = resolveTheme(pref);
  document.documentElement.setAttribute("data-theme", resolved);
  return resolved;
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(DEFAULT_THEME);
  const [resolved, setResolved] = useState<ResolvedTheme>("dark");

  // Sync from storage on mount (SSR renders the default).
  useEffect(() => {
    const pref = readTheme();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setThemeState(pref);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setResolved(applyTheme(pref));
  }, []);

  // While on "system", follow OS changes live.
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setResolved(applyTheme("system"));
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  const setTheme = useCallback((pref: Theme) => {
    try {
      window.localStorage.setItem(THEME_KEY, pref);
    } catch {
      /* private mode — theme just won't persist */
    }
    setThemeState(pref);
    setResolved(applyTheme(pref));
  }, []);

  return { theme, resolved, setTheme };
}
