import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { getJson, putJson, type SettingsResponse } from "./api";

export type ThemeChoice = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

interface ThemeValue {
  choice: ThemeChoice;
  resolved: ResolvedTheme;
  setChoice: (choice: ThemeChoice) => void;
}

const ThemeContext = createContext<ThemeValue | null>(null);
const STORAGE_KEY = "agora.theme";

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

function readStored(): ThemeChoice {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    // storage blocked: fall back to the default
  }
  return "light";
}

/**
 * Light by default (D-16). The choice is saved in Agora's settings (so it survives a
 * browser change) and mirrored in localStorage so the first paint already has the right
 * colors instead of flashing.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(readStored);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    getJson<SettingsResponse>("/settings")
      .then((s) => {
        const t = s.values.theme;
        if (t === "light" || t === "dark" || t === "system") setChoiceState(t);
      })
      .catch(() => undefined); // offline: keep the stored choice
  }, []);

  const resolved: ResolvedTheme = choice === "system" ? (systemDark ? "dark" : "light") : choice;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
    try {
      localStorage.setItem(STORAGE_KEY, choice);
    } catch {
      // ignore
    }
  }, [resolved, choice]);

  const setChoice = useCallback((next: ThemeChoice) => {
    setChoiceState(next);
    putJson("/settings", { theme: next }).catch(() => undefined);
  }, []);

  const value = useMemo(() => ({ choice, resolved, setChoice }), [choice, resolved, setChoice]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside ThemeProvider");
  return ctx;
}
