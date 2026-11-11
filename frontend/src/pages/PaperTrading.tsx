import { motion } from "framer-motion";
import { ScrollBox } from "../components/ui/scroll-box";
import { Tabs } from "../components/ui/tabs";
import { ownerOf } from "../lib/owner";
import { Play, Radio } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { toast } from "sonner";
import { KairosMark } from "../components/kairos/KairosMark";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { AnimatedNumber } from "../components/ui/animated-number";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Change } from "../components/ui/change";
import { Pill } from "../components/ui/pill";
import { postJson, type PaperSessionSummary } from "../lib/api";
import { formatDate, formatMoney, formatSignedMoney, MARKET_CURRENCY, MARKET_TZ, TIMEFRAME_LABEL } from "../lib/format";
import { useLive, useLiveConnected } from "../lib/live";
import { spring } from "../lib/motion";
import { useApi } from "../lib/useApi";
import { STATE_WORDS, useThrottledReload } from "./paper/common";
import { FreshnessBadge } from "./paper/Freshness";
import { StartDialog } from "./paper/StartDialog";

function SessionCard({ s }: { s: PaperSessionSummary }) {
  const cur = MARKET_CURRENCY[s.market];
  const st = STATE_WORDS[s.state];
  return (
    <motion.div layout transition={spring}>
      <Link to={s.kind === "kairos" ? `/paper/desk/${s.id}` : `/paper/${s.id}`} className="block rounded-card no-underline focus-visible:outline-2 focus-visible:outline-accent">
        <Card className="gap-4 p-5 transition-shadow hover:shadow-e2">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 flex-col gap-1">
              <p className="m-0 truncate text-heading font-semibold text-fg">{s.name}</p>
              <p className="m-0 text-small text-fg-muted">
                {s.market === "IN" ? "India" : "US"} · {TIMEFRAME_LABEL[s.timeframe]} · {s.account.name}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              {s.kind === "kairos" && (
                <Pill tone="accent" className="h-7 px-2.5 text-tiny">
                  <KairosMark className="size-3.5" />
                  Kairos desk
                </Pill>
              )}
              {s.mode === "replay" && <Pill tone="info" className="h-7 px-2.5 text-tiny">Practice replay</Pill>}
              <Pill tone={st.tone} className="h-7 px-2.5 text-tiny">{st.label}</Pill>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="m-0 text-tiny text-fg-subtle">Money now</p>
              <p className="m-0 text-[20px] font-bold tabular-nums text-fg">
                <AnimatedNumber value={s.equity} format={(n) => formatMoney(n, cur, 0)} />
              </p>
            </div>
            <div>
              <p className="m-0 text-tiny text-fg-subtle">Total return</p>
              <p className="m-0 text-[20px] tabular-nums">
                <Change value={s.total_return} text={`${s.total_return >= 0 ? "+" : "−"}${Math.abs(s.total_return).toFixed(2)}%`} />
              </p>
            </div>
            <div>
              <p className="m-0 text-tiny text-fg-subtle">Today</p>
              <p className="m-0 text-[20px] tabular-nums">
                <Change value={s.day_pnl} text={formatSignedMoney(s.day_pnl, cur, 0)} />
              </p>
            </div>
          </div>
          <div className="flex items-center justify-between gap-3 text-small text-fg-muted">
            <span>
              {s.open_positions} open · {s.trades} closed trade{s.trades === 1 ? "" : "s"} · started {formatDate(s.started_at, MARKET_TZ[s.market])}
            </span>
            {s.state !== "stopped" && <FreshnessBadge f={s.freshness} compact />}
          </div>
        </Card>
      </Link>
    </motion.div>
  );
}

/**
 * Sessions grouped the way the user asked (2026-11-06, D-206): Kairos's desks and Metis's
 * strategies on trial, each by market, then the user's own, then the stopped ones (folded, and
 * clearable: they were 49 older runs of the same desks).
 */
const TF_ORDER: Record<string, number> = { "1d": 0, "1h": 1, "15m": 2, "5m": 3, "1m": 4 };

function tabOf(s: PaperSessionSummary): string {
  if (s.state === "stopped") return "stopped";
  const where = s.market === "IN" ? "india" : "usa";
  const owner = ownerOf(s.name, s.kind);
  return owner === "you" ? "yours" : `${owner}-${where}`;
}

const TABS = [
  { value: "kairos-india", label: "Kairos Desk India" },
  { value: "kairos-usa", label: "Kairos Desk USA" },
  { value: "metis-india", label: "Metis India" },
  { value: "metis-usa", label: "Metis USA" },
  { value: "yours", label: "Yours" },
  { value: "stopped", label: "Stopped" },
];

export default function PaperTrading() {
  const [search, setSearch] = useSearchParams();
  const startParam = search.get("start");
  const [open, setOpen] = useState(startParam !== null);
  const connected = useLiveConnected();
  const sessions = useApi<{ sessions: PaperSessionSummary[]; mode: "live" | "replay" }>("/paper/sessions", connected ? undefined : 10_000);
  const reload = useThrottledReload(sessions.reload);
  useLive(["paper."], reload, sessions.reload);

  const replay = sessions.status === "ready" && sessions.data.mode === "replay";
  const list = sessions.status === "ready" ? sessions.data.sessions : [];
  const counted = TABS.map((t) => ({
    ...t,
    items: list
      .filter((s) => tabOf(s) === t.value)
      .sort((a, b) => (TF_ORDER[a.timeframe] ?? 9) - (TF_ORDER[b.timeframe] ?? 9) || a.name.localeCompare(b.name)),
  }));
  const [picked, setPicked] = useState<string | null>(search.get("tab"));
  const tab = picked ?? counted.find((t) => t.items.length > 0)?.value ?? "kairos-india";
  const [clearing, setClearing] = useState(false);

  async function clearStopped() {
    setClearing(true);
    try {
      const r = await postJson<{ hidden: number }>("/paper/sessions/clear-stopped");
      toast.success(`Cleared ${r.hidden} stopped session${r.hidden === 1 ? "" : "s"}. Their trades still count for Kairos.`);
      sessions.reload();
    } catch {
      toast.error("Couldn't clear the stopped sessions. Try again.");
    } finally {
      setClearing(false);
    }
  }

  function onOpenChange(v: boolean) {
    setOpen(v);
    if (!v && startParam !== null) setSearch({}, { replace: true });
  }

  return (
    <>
      <PageHeader
        title="Paper trading"
        subtitle="Run a strategy live with fake money. It stops when you click Stop or close Agora, and picks up again when you reopen it."
        actions={
          <>
            <Button asChild>
              <Link to="/paper/desk">
                <KairosMark className="size-4" />
                Kairos desk
              </Link>
            </Button>
            <Button variant="primary" onClick={() => setOpen(true)}>
              <Play aria-hidden="true" />
              Start paper trading
            </Button>
          </>
        }
      />
      {sessions.status === "error" && <ErrorState error={sessions.error} onRetry={sessions.reload} />}
      {sessions.status === "loading" && <LoadingRows rows={4} />}
      {sessions.status === "ready" && list.length === 0 && (
        <Card className="min-h-[420px] justify-center">
          <EmptyState
            icon={Radio}
            title="No paper trading sessions"
            body="Each session gets its own paper account. You'll see live equity, today's profit, open positions and every fill."
            action={
              <Button variant="primary" onClick={() => setOpen(true)}>
                Start paper trading
              </Button>
            }
          />
        </Card>
      )}
      {sessions.status === "ready" && list.length > 0 && (
        <Card className="overflow-hidden p-0">
          <Tabs
            label="Paper sessions"
            value={tab}
            onValueChange={setPicked}
            tabs={counted.map((t) => ({
              value: t.value,
              label: (
                <span className="inline-flex items-center gap-1.5">
                  {t.value.startsWith("kairos") && <KairosMark className="size-3.5" />}
                  {t.label}
                  <span className="text-small font-normal text-fg-subtle">{t.items.length}</span>
                </span>
              ),
              content: (
                <div className="flex flex-col gap-3 p-4">
                  {t.value === "stopped" && t.items.length > 0 && (
                    <div className="flex justify-end">
                      <Button onClick={() => void clearStopped()} disabled={clearing}>
                        Clear stopped
                      </Button>
                    </div>
                  )}
                  {t.items.length === 0 ? (
                    <p className="m-0 py-10 text-center text-small text-fg-muted">Nothing here.</p>
                  ) : (
                    <ScrollBox size="page" className="grid grid-cols-2 gap-5 p-1">
                      {t.items.map((s) => (
                        <SessionCard key={s.id} s={s} />
                      ))}
                    </ScrollBox>
                  )}
                </div>
              ),
            }))}
          />
        </Card>
      )}
      <StartDialog open={open} onOpenChange={onOpenChange} replay={replay} initialStrategy={startParam ? Number(startParam) : undefined} />
    </>
  );
}
