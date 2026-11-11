import { MotionConfig } from "framer-motion";
import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router";
import { Toaster } from "sonner";
import { AppShell } from "./components/shell/AppShell";
import { LoadingRows } from "./components/states";
import { TooltipProvider } from "./components/ui/tooltip";
import { useLive } from "./lib/live";
import { useTheme } from "./lib/theme";
import Backtests from "./pages/Backtests";
import BacktestSetup from "./pages/BacktestSetup";
import Data from "./pages/Data";
import Home from "./pages/Home";
import NotFound from "./pages/NotFound";
import Onboarding from "./pages/Onboarding";
import PaperTrading from "./pages/PaperTrading";
import Strategies from "./pages/Strategies";


// Chart-heavy screens load on demand so the first screen appears fast.
const Charts = lazy(() => import("./pages/Charts"));
const StrategyBuilder = lazy(() => import("./pages/StrategyBuilder"));
const BacktestResults = lazy(() => import("./pages/BacktestResults"));
const Compare = lazy(() => import("./pages/Compare"));
const PaperSession = lazy(() => import("./pages/PaperSession"));
const KairosDesk = lazy(() => import("./pages/KairosDesk"));
const Metis = lazy(() => import("./pages/Metis"));
const Portfolio = lazy(() => import("./pages/Portfolio"));
const Settings = lazy(() => import("./pages/Settings"));
const News = lazy(() => import("./pages/News"));
const Watchlists = lazy(() => import("./pages/Watchlists"));
const World = lazy(() => import("./pages/World"));
const Indices = lazy(() => import("./pages/Indices"));
const Logs = lazy(() => import("./pages/Logs"));
const Combine = lazy(() => import("./pages/Combine"));

const noop = () => undefined;

export default function App() {
  const { resolved } = useTheme();
  // Keep the live channel open on every screen: when Agora restarts, this tab reconnects
  // and reloads itself, and the launcher doesn't open another tab (D-111).
  useLive(["app."], noop);
  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider>
        <Suspense fallback={<LoadingRows rows={4} className="p-7" />}>
          <Routes>
            <Route path="/welcome" element={<Onboarding />} />
            <Route element={<AppShell />}>
              <Route index element={<Home />} />
              <Route path="strategies" element={<Strategies />} />
              <Route path="strategies/new" element={<StrategyBuilder />} />
              <Route path="strategies/combine" element={<Combine />} />
              <Route path="strategies/:id" element={<StrategyBuilder />} />
              <Route path="backtests" element={<Backtests />} />
              <Route path="backtests/new" element={<BacktestSetup />} />
              <Route path="backtests/:id" element={<BacktestResults />} />
              <Route path="compare" element={<Compare />} />
              <Route path="paper" element={<PaperTrading />} />
              <Route path="paper/desk" element={<KairosDesk />} />
              <Route path="paper/desk/:id" element={<PaperSession />} />
              <Route path="paper/:id" element={<PaperSession />} />
              <Route path="metis" element={<Metis />} />
              <Route path="portfolio" element={<Portfolio />} />
              <Route path="portfolio/:id" element={<Portfolio />} />
              <Route path="charts" element={<Charts />} />
              <Route path="news" element={<News />} />
              <Route path="indices" element={<Indices />} />
              <Route path="world" element={<World />} />
              <Route path="watchlists" element={<Watchlists />} />
              <Route path="watchlists/:id" element={<Watchlists />} />
              <Route path="data" element={<Data />} />
              <Route path="logs" element={<Logs />} />
              <Route path="settings" element={<Settings />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </Suspense>
        <Toaster theme={resolved} position="bottom-right" toastOptions={{ className: "!rounded-card !border-border !bg-surface !text-fg !shadow-e3 !font-sans" }} />
      </TooltipProvider>
    </MotionConfig>
  );
}
