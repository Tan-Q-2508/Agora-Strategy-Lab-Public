import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";
import type { SettingsResponse } from "../../lib/api";
import { useApi } from "../../lib/useApi";
import { pageTransition } from "../../lib/motion";
import { ErrorBoundary } from "../ErrorBoundary";
import { KairosProvider } from "../../lib/kairosChat";
import { useGlobalShortcuts } from "../../lib/shortcuts";
import { KairosDrawer } from "../kairos/KairosDrawer";
import { CommandPalette } from "./CommandPalette";
import { ShortcutsDialog } from "./ShortcutsDialog";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

const COLLAPSE_KEY = "agora.sidebar.collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Fixed frame: sidebar + top bar never move; only the page area scrolls (DESIGN_BRIEF §4).
 */
export function AppShell() {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const settings = useApi<SettingsResponse>("/settings");
  const needsOnboarding = settings.status === "ready" && settings.data.values.onboarding_done === false;

  // First launch: show the setup tour once (it sets onboarding_done when finished or skipped).
  useEffect(() => {
    if (needsOnboarding) navigate("/welcome", { replace: true });
  }, [needsOnboarding, navigate]);

  const go = useCallback((to: string) => navigate(to), [navigate]);
  const help = useCallback(() => setHelpOpen(true), []);
  const newStrategy = useCallback(() => navigate("/strategies/new"), [navigate]);
  useGlobalShortcuts({ go, help, newStrategy });

  function toggle() {
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        // ignore
      }
      return !c;
    });
  }

  return (
    <KairosProvider>
    <div className="relative flex h-screen min-w-[1280px] overflow-hidden bg-canvas text-fg">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-control focus:bg-surface focus:p-3">
        Skip to content
      </a>
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onOpenPalette={() => setPaletteOpen(true)} />
        <main id="main" className="relative min-h-0 flex-1 overflow-y-auto">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={location.pathname} {...pageTransition} className="mx-auto flex max-w-[1520px] flex-col gap-6 px-7 py-7">
              <ErrorBoundary resetKey={location.pathname}>
                <Outlet />
              </ErrorBoundary>
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} onShowShortcuts={help} />
      <ShortcutsDialog open={helpOpen} onOpenChange={setHelpOpen} />
      <KairosDrawer />
    </div>
    </KairosProvider>
  );
}
