import { Command } from "cmdk";
import { Blocks, Bot, Code, FlaskConical, Keyboard, LayoutGrid, Moon, Play, Radio, Sparkles, Stethoscope, Sun, SunMoon } from "lucide-react";
import { Dialog } from "radix-ui";
import { useEffect } from "react";
import { useNavigate } from "react-router";
import { useKairos } from "../../lib/kairosChat";
import { KairosMark } from "../kairos/KairosMark";
import type { BacktestBrief, PaperSessionSummary, StrategySummary } from "../../lib/api";
import { useTheme } from "../../lib/theme";
import { useApi } from "../../lib/useApi";
import { NAV, SETTINGS_NAV } from "./nav";

const itemClass =
  "flex h-11 cursor-pointer items-center gap-3 rounded-control px-3 text-[14px] text-fg data-[selected=true]:bg-surface-2 [&_svg]:size-4 [&_svg]:text-fg-muted";

const groupClass = "text-tiny text-fg-subtle [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2";

const ACTIONS = [
  { label: "New strategy with blocks", to: "/strategies/new", icon: Blocks, keywords: "create build rules" },
  { label: "New strategy in code", to: "/strategies/new?kind=code", icon: Code, keywords: "python editor" },
  { label: "Describe a strategy to the AI helper", to: "/strategies/new?kind=ai", icon: Sparkles, keywords: "idea draft ai" },
  { label: "Start from a template", to: "/strategies#templates", icon: LayoutGrid, keywords: "starter ready-made" },
  { label: "Run a backtest", to: "/backtests/new", icon: FlaskConical, keywords: "test history" },
  { label: "Start paper trading", to: "/paper?start=", icon: Play, keywords: "live fake money session" },
  { label: "Set up the AI helper", to: "/settings?tab=ai", icon: Bot, keywords: "ollama model download" },
  { label: "Diagnostics and support bundle", to: "/settings?tab=diagnostics", icon: Stethoscope, keywords: "logs help problem" },
];

/** Ctrl/Cmd+K: jump to any screen, open a recent item, or run a quick action (SPEC §9). */
export function CommandPalette({ open, onOpenChange, onShowShortcuts }: { open: boolean; onOpenChange: (open: boolean) => void; onShowShortcuts?: () => void }) {
  const navigate = useNavigate();
  const { setChoice } = useTheme();
  const strategies = useApi<{ strategies: StrategySummary[] }>(open ? "/strategies" : null);
  const backtests = useApi<{ backtests: BacktestBrief[] }>(open ? "/backtests?limit=8" : null);
  const sessions = useApi<{ sessions: PaperSessionSummary[] }>(open ? "/paper/sessions" : null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange(!open);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  const kairos = useKairos();

  function run(action: () => void) {
    onOpenChange(false);
    action();
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/25 backdrop-blur-[2px]" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-[18%] left-1/2 z-50 w-[min(560px,92vw)] -translate-x-1/2 overflow-hidden rounded-card border border-border bg-surface shadow-e3"
        >
          <Dialog.Title className="sr-only">Search or jump to</Dialog.Title>
          <Command label="Search or jump to" className="flex flex-col">
            <Command.Input
              autoFocus
              placeholder="Search or jump to…"
              className="h-13 border-b border-hairline bg-transparent px-4 text-body text-fg outline-none placeholder:text-fg-subtle"
            />
            <Command.List className="max-h-80 overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-small text-fg-muted">Nothing matches that.</Command.Empty>
              <Command.Group heading="Go to" className={groupClass}>
                {[...NAV, SETTINGS_NAV].map((item) => {
                  const Icon = item.icon;
                  return (
                    <Command.Item key={item.to} value={`${item.label} ${item.keywords ?? ""}`} onSelect={() => run(() => navigate(item.to))} className={itemClass}>
                      <Icon aria-hidden="true" />
                      {item.label}
                    </Command.Item>
                  );
                })}
              </Command.Group>
              <Command.Group heading="Actions" className={groupClass}>
                {kairos && (
                  <Command.Item value="Ask Kairos trading agent chat assistant" onSelect={() => run(() => kairos.setOpen(true))} className={itemClass}>
                    <KairosMark />
                    Ask Kairos, your trading agent
                  </Command.Item>
                )}
                {ACTIONS.map((a) => {
                  const Icon = a.icon;
                  return (
                    <Command.Item key={a.label} value={`${a.label} ${a.keywords}`} onSelect={() => run(() => navigate(a.to))} className={itemClass}>
                      <Icon aria-hidden="true" />
                      {a.label}
                    </Command.Item>
                  );
                })}
                {onShowShortcuts && (
                  <Command.Item value="keyboard shortcuts keys help" onSelect={() => run(onShowShortcuts)} className={itemClass}>
                    <Keyboard aria-hidden="true" />
                    Keyboard shortcuts
                  </Command.Item>
                )}
              </Command.Group>
              {strategies.status === "ready" && strategies.data.strategies.length > 0 && (
                <Command.Group heading="Your strategies" className={groupClass}>
                  {strategies.data.strategies.filter((x) => !x.archived).slice(0, 20).map((x) => (
                    <Command.Item key={`s${x.id}`} value={`strategy ${x.name} ${x.id}`} onSelect={() => run(() => navigate(`/strategies/${x.id}`))} className={itemClass}>
                      <LayoutGrid aria-hidden="true" />
                      {x.name}
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              {backtests.status === "ready" && backtests.data.backtests.length > 0 && (
                <Command.Group heading="Recent backtests" className={groupClass}>
                  {backtests.data.backtests.map((b) => (
                    <Command.Item key={`b${b.id}`} value={`backtest ${b.strategy_name} ${b.id}`} onSelect={() => run(() => navigate(`/backtests/${b.id}`))} className={itemClass}>
                      <FlaskConical aria-hidden="true" />
                      {b.strategy_name} <span className="text-fg-subtle">· backtest #{b.id}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              {sessions.status === "ready" && sessions.data.sessions.some((x) => x.state !== "stopped") && (
                <Command.Group heading="Paper trading" className={groupClass}>
                  {sessions.data.sessions.filter((x) => x.state !== "stopped").map((x) => (
                    <Command.Item key={`p${x.id}`} value={`paper session ${x.name} ${x.id}`} onSelect={() => run(() => navigate(`/paper/${x.id}`))} className={itemClass}>
                      <Radio aria-hidden="true" />
                      {x.name} <span className="text-fg-subtle">· paper session</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              <Command.Group heading="Appearance" className={groupClass}>
                <Command.Item value="light theme" onSelect={() => run(() => setChoice("light"))} className={itemClass}>
                  <Sun aria-hidden="true" />
                  Use light theme
                </Command.Item>
                <Command.Item value="dark theme" onSelect={() => run(() => setChoice("dark"))} className={itemClass}>
                  <Moon aria-hidden="true" />
                  Use dark theme
                </Command.Item>
                <Command.Item value="system theme automatic" onSelect={() => run(() => setChoice("system"))} className={itemClass}>
                  <SunMoon aria-hidden="true" />
                  Match my computer's theme
                </Command.Item>
              </Command.Group>
            </Command.List>
          </Command>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
