import { Search, Sparkles } from "lucide-react";
import type { Health } from "../../lib/api";
import { useKairos } from "../../lib/kairosChat";
import { KairosMark } from "../kairos/KairosMark";
import { Button } from "../ui/button";
import { useApi } from "../../lib/useApi";
import { Kbd } from "../ui/kbd";
import { Pill } from "../ui/pill";
import { Tooltip } from "../ui/tooltip";
import { Activity } from "./Activity";
import { MarketPills } from "./MarketPills";

function AIPill() {
  const health = useApi<Health>("/health", 60_000);
  if (health.status !== "ready" || health.data.ai.state !== "ready") return null;
  return (
    <Tooltip content="The AI helper on your laptop is ready." side="bottom">
      <Pill tone="accent" tabIndex={0}>
        <Sparkles className="size-3.5" aria-hidden="true" />
        AI ready
      </Pill>
    </Tooltip>
  );
}

function KairosButton() {
  const k = useKairos();
  const isMac = typeof navigator !== "undefined" && /Mac/.test(navigator.platform);
  if (!k) return null;
  return (
    <Tooltip content={`Ask Kairos, your trading agent (${isMac ? "⌘" : "Ctrl"} J)`} side="bottom">
      <Button size="sm" variant={k.open ? "soft" : "secondary"} aria-pressed={k.open} onClick={k.toggle}>
        <KairosMark className="size-4" />
        Kairos
      </Button>
    </Tooltip>
  );
}

export function TopBar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const isMac = typeof navigator !== "undefined" && /Mac/.test(navigator.platform);
  return (
    <header className="flex h-[60px] shrink-0 items-center gap-2.5 border-b border-border bg-canvas px-7">
      <button
        type="button"
        onClick={onOpenPalette}
        className="flex h-10 w-[280px] items-center gap-2.5 rounded-control border border-border bg-surface px-3 text-left text-[14px] text-fg-subtle shadow-e1 hover:border-fg-subtle/40"
      >
        <Search className="size-4" aria-hidden="true" />
        Search or jump to…
        <span className="ml-auto">
          <Kbd>{isMac ? "⌘ K" : "Ctrl K"}</Kbd>
        </span>
      </button>
      <div className="flex-1" />
      <Activity />
      <MarketPills />
      <AIPill />
      <KairosButton />
    </header>
  );
}
