/**
 * A window left open across an update still runs the old screens, which ask for page files the
 * new build no longer has, so every page after that stays blank. When a page file fails to load,
 * reload once to pick up the new build (at most once a minute, so a real outage can't loop).
 */
const KEY = "agora.staleReloadAt";
const GAP_MS = 60_000;

export function shouldReload(now: number, storage: Pick<Storage, "getItem" | "setItem">): boolean {
  try {
    const last = Number(storage.getItem(KEY) ?? 0);
    if (now - last < GAP_MS) return false;
    storage.setItem(KEY, String(now));
    return true;
  } catch {
    return false; // storage blocked: let the page show its own error
  }
}

export function reloadOnStaleBuild(): void {
  window.addEventListener("vite:preloadError", (event) => {
    if (shouldReload(Date.now(), window.sessionStorage)) {
      event.preventDefault();
      window.location.reload();
    }
  });
}
