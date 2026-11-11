import { useEffect, useRef, useState } from "react";
import { getJson, postJson, toEnvelope, type Job } from "./api";

/**
 * Follow a background job until it finishes. Polls twice a second; the UI shows the
 * job's own plain-English message and progress.
 */
export function useJob<R = unknown>(jobId: string | null, onFinish?: (job: Job<R>) => void) {
  const [state, setState] = useState<{ id: string; job: Job<R> } | null>(null);
  const finished = useRef(onFinish);
  useEffect(() => {
    finished.current = onFinish;
  });

  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const j = await getJson<Job<R>>(`/jobs/${jobId}`);
        if (!alive) return;
        setState({ id: jobId, job: j });
        if (j.status === "done" || j.status === "failed" || j.status === "cancelled") {
          finished.current?.(j);
          return;
        }
      } catch (err) {
        if (!alive) return;
        const e = toEnvelope(err);
        setState((prev) => (prev && prev.id === jobId ? { id: jobId, job: { ...prev.job, status: "failed", error: e, message: e.message } } : prev));
        return;
      }
      timer = setTimeout(poll, 500);
    };
    void poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [jobId]);

  const job = state && state.id === jobId ? state.job : null;
  const cancel = () => (jobId ? postJson(`/jobs/${jobId}/cancel`).catch(() => undefined) : undefined);
  return { job, cancel };
}

/**
 * The id of the job a screen is following, found again after the user leaves the screen and
 * comes back (the user's request 2026-10-24, D-107). Jobs keep running on the backend when a
 * screen closes; without this the screen forgot them and the progress vanished.
 *
 * `kinds` is one job kind or several separated by commas; `key` narrows it to one thing
 * ("strategy:12", "portfolio:3"). Pass `null` as kinds to skip the look-up.
 */
export function useJobId(kinds: string | null, key?: string | null, initial: string | null = null) {
  const [jobId, setJobId] = useState<string | null>(initial);
  useEffect(() => {
    if (!kinds || key === null) return;
    let alive = true;
    const params = new URLSearchParams({ kind: kinds, active: "true" });
    if (key) params.set("key", key);
    getJson<{ jobs: Job[] }>(`/jobs?${params.toString()}`)
      .then((r) => {
        const running = r.jobs?.[0];
        if (alive && running) setJobId((cur) => cur ?? running.job_id);
      })
      .catch(() => undefined); // nothing to resume
    return () => {
      alive = false;
    };
  }, [kinds, key]);
  return [jobId, setJobId] as const;
}
