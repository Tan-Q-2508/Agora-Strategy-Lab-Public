import { useCallback, useRef } from "react";
import type { PaperState } from "../../lib/api";

export const STATE_WORDS: Record<PaperState, { label: string; tone: "profit" | "warning" | "neutral" | "info" }> = {
  starting: { label: "Starting", tone: "info" },
  running: { label: "Running", tone: "profit" },
  paused_data: { label: "Waiting for prices", tone: "warning" },
  paused_user: { label: "Paused", tone: "warning" },
  stopped: { label: "Stopped", tone: "neutral" },
};

/** Re-fetch at most once a second while live messages stream in. */
export function useThrottledReload(reload: () => void) {
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  return useCallback(() => {
    if (pending.current) return;
    pending.current = setTimeout(() => {
      pending.current = null;
      reload();
    }, 1000);
  }, [reload]);
}
