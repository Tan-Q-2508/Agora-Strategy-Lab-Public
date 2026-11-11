import { useCallback, useEffect, useRef, useState } from "react";
import { getJson, toEnvelope, type ErrorEnvelope } from "./api";

export type ApiState<T> =
  | { status: "loading"; data?: undefined; error?: undefined }
  | { status: "ready"; data: T; error?: undefined; receivedAt: number }
  | { status: "error"; data?: undefined; error: ErrorEnvelope };

/**
 * Fetch JSON from the backend, optionally re-fetching every `refreshMs`.
 * A refresh keeps showing the previous data instead of flashing a skeleton.
 */
export function useApi<T>(path: string | null, refreshMs?: number): ApiState<T> & { reload: () => void } {
  const [state, setState] = useState<ApiState<T>>({ status: "loading" });
  const [tick, setTick] = useState(0);
  const alive = useRef(true);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    alive.current = true;
    if (path === null) return; // nothing to fetch yet
    getJson<T>(path)
      .then((data) => alive.current && setState({ status: "ready", data, receivedAt: Date.now() }))
      .catch((err: unknown) => alive.current && setState({ status: "error", error: toEnvelope(err) }));
    return () => {
      alive.current = false;
    };
  }, [path, tick]);

  useEffect(() => {
    if (!refreshMs || path === null) return;
    const id = setInterval(reload, refreshMs);
    return () => clearInterval(id);
  }, [refreshMs, reload, path]);

  return { ...state, reload };
}
