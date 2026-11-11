/** Keyboard shortcuts (DESIGN_BRIEF §9: full keyboard use). Shown with "?" anywhere. */
import { useEffect } from "react";

export const GO_KEYS: { key: string; to: string; label: string }[] = [
  { key: "h", to: "/", label: "Home" },
  { key: "s", to: "/strategies", label: "Strategies" },
  { key: "b", to: "/backtests", label: "Backtests" },
  { key: "c", to: "/compare", label: "Compare" },
  { key: "p", to: "/paper", label: "Paper trading" },
  { key: "t", to: "/charts", label: "Charts" },
  { key: "d", to: "/data", label: "Data" },
  { key: ",", to: "/settings", label: "Settings" },
];

export const SHORTCUT_HELP: { keys: string[]; label: string }[] = [
  { keys: ["Ctrl", "K"], label: "Search or jump to anything" },
  { keys: ["Ctrl", "J"], label: "Ask Kairos, your trading agent" },
  { keys: ["?"], label: "Show these shortcuts" },
  { keys: ["N"], label: "New strategy" },
  ...GO_KEYS.map((g) => ({ keys: ["G", g.key === "," ? "," : g.key.toUpperCase()], label: `Go to ${g.label}` })),
  { keys: ["Ctrl", "S"], label: "Save (strategy builder)" },
  { keys: ["Ctrl", "Enter"], label: "Backtest this (strategy builder)" },
  { keys: ["Esc"], label: "Close a dialog" },
];

/** True while the user is typing somewhere, so single-key shortcuts stay out of the way. */
export function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

export function useGlobalShortcuts({ go, help, newStrategy }: { go: (to: string) => void; help: () => void; newStrategy: () => void }) {
  useEffect(() => {
    let pendingG = 0;
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return;
      if (document.querySelector("[role=dialog]")) return;
      const now = Date.now();
      if (pendingG && now - pendingG < 1200) {
        pendingG = 0;
        const hit = GO_KEYS.find((g) => g.key === e.key.toLowerCase());
        if (hit) {
          e.preventDefault();
          go(hit.to);
        }
        return;
      }
      if (e.key === "g" || e.key === "G") {
        pendingG = now;
      } else if (e.key === "?") {
        e.preventDefault();
        help();
      } else if (e.key === "n" || e.key === "N") {
        e.preventDefault();
        newStrategy();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, help, newStrategy]);
}
