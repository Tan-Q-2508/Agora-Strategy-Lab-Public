import { Bot, Database, FlaskConical, Newspaper, Radio } from "lucide-react";
import { KairosMark } from "../components/kairos/KairosMark";
import type { AutopilotStatus } from "../lib/world";
import { Link } from "react-router";
import { PageHeader } from "../components/PageHeader";
import { WholeMarket } from "../components/WholeMarket";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Change } from "../components/ui/change";
import { Dot } from "../components/ui/pill";
import { AnimatedNumber } from "../components/ui/animated-number";
import { Skeleton } from "../components/ui/skeleton";
import type { BacktestBrief, CoverageResponse, MarketStatus, PaperSessionSummary } from "../lib/api";
import { formatAgo, formatCountdown, formatMoney, formatPercent, formatSignedMoney, MARKET_CURRENCY } from "../lib/format";
import { useLive, useLiveConnected } from "../lib/live";
import { useApi } from "../lib/useApi";
import type { LiveNews } from "../lib/kairos";
import { guardWords, RISK_TONE } from "../lib/newsRisk";
import { RiskMeter } from "../components/news/RiskMeter";
import { Pill } from "../components/ui/pill";
import { STATE_WORDS, useThrottledReload } from "./paper/common";
import { ScrollBox } from "../components/ui/scroll-box";

function greeting(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function MarketCard({ m }: { m: MarketStatus }) {
  return (
    <Card className="gap-1 p-5">
      <div className="flex items-center gap-2 text-small text-fg-muted">
        <Dot tone={m.is_open ? "profit" : "neutral"} live={m.is_open} />
        {m.name === "India" ? "India (NSE)" : "US (NYSE / Nasdaq)"}
      </div>
      <p className="m-0 text-title font-bold tracking-tight">{m.is_open ? "Open" : "Closed"}</p>
      <p className="m-0 text-small text-fg-muted">
        {m.next_change_display} · in {formatCountdown(m.seconds_to_change)}
      </p>
    </Card>
  );
}

function Markets() {
  const s = useApi<{ markets: MarketStatus[] }>("/markets/status", 60_000);
  if (s.status === "loading") {
    return (
      <div className="grid grid-cols-2 gap-5">
        <Skeleton className="h-[118px] rounded-card" />
        <Skeleton className="h-[118px] rounded-card" />
      </div>
    );
  }
  if (s.status === "error") return <ErrorState error={s.error} onRetry={s.reload} />;
  return (
    <div className="grid grid-cols-2 gap-5">
      {s.data.markets.map((m) => (
        <MarketCard key={m.market} m={m} />
      ))}
    </div>
  );
}

function DataHealth() {
  const s = useApi<CoverageResponse>("/data/coverage?timeframe=1d", 60_000);
  return (
    <Card className="min-h-[260px]">
      <CardHeader>
        <CardTitle>Data health</CardTitle>
        <Button size="sm" variant="ghost" asChild>
          <Link to="/data">Open Data</Link>
        </Button>
      </CardHeader>
      {s.status === "loading" && <LoadingRows rows={3} className="px-5" />}
      {s.status === "error" && <ErrorState error={s.error} onRetry={s.reload} className="mx-5" />}
      {s.status === "ready" && s.data.totals.empty === s.data.totals.symbols && (
        <EmptyState
          icon={Database}
          title="No prices downloaded yet"
          body="Agora will download years of daily prices for the Nifty 50 and your US watchlist."
          action={
            <Button variant="soft" asChild>
              <Link to="/data">Open Data</Link>
            </Button>
          }
        />
      )}
      {s.status === "ready" && s.data.totals.empty < s.data.totals.symbols && (
        <CardBody className="flex flex-col gap-3">
          <p className="m-0 text-title font-bold tabular-nums">
            {s.data.totals.ok}
            <span className="text-body font-normal text-fg-muted"> of {s.data.totals.symbols} stocks up to date</span>
          </p>
          <ScrollBox size="sm">
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-small">
              <li className="flex items-center gap-2">
                <Dot tone={s.data.totals.gaps + s.data.totals.stale ? "warning" : "profit"} />
                {s.data.totals.gaps + s.data.totals.stale} need attention
              </li>
              <li className="flex items-center gap-2">
                <Dot tone="neutral" />
                {s.data.totals.empty} not downloaded
              </li>
              {s.data.last_update && (
                <li className="text-fg-muted">Last download {formatAgo(s.data.last_update)}</li>
              )}
            </ul>
          </ScrollBox>
          <WholeMarket />
        </CardBody>
      )}
    </Card>
  );
}

function PaperCard() {
  const connected = useLiveConnected();
  const s = useApi<{ sessions: PaperSessionSummary[] }>("/paper/sessions", connected ? undefined : 15_000);
  const reload = useThrottledReload(s.reload);
  useLive(["paper."], reload, s.reload);
  const active = s.status === "ready" ? s.data.sessions.filter((x) => x.state !== "stopped") : [];
  return (
    <Card className="col-span-2 min-h-[260px]">
      <CardHeader>
        <CardTitle>Paper trading</CardTitle>
        {active.length > 0 && (
          <Button size="sm" variant="ghost" asChild>
            <Link to="/paper">See all</Link>
          </Button>
        )}
      </CardHeader>
      {s.status === "loading" && (
        <CardBody>
          <LoadingRows rows={2} />
        </CardBody>
      )}
      {s.status !== "loading" && active.length === 0 && (
        <EmptyState
          icon={Radio}
          title="Nothing is paper trading yet"
          body="Once a strategy looks good in a backtest, start paper trading it here to watch it run live with fake money."
          action={
            <Button variant="soft" asChild>
              <Link to="/paper">Go to paper trading</Link>
            </Button>
          }
        />
      )}
      {active.length > 0 && (
        <CardBody>
          <ScrollBox size="md">
            <ul className="m-0 flex list-none flex-col p-0">
              {active.slice(0, 4).map((x) => (
                <li key={x.id} className="border-b border-hairline last:border-0">
                  <Link to={`/paper/${x.id}`} className="flex items-center justify-between gap-4 py-3 text-fg no-underline hover:text-accent-strong">
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-semibold">{x.name}</span>
                      <span className="text-tiny text-fg-subtle">
                        {x.market === "IN" ? "India" : "US"} · {x.open_positions} open · {x.mode === "replay" ? "practice replay" : STATE_WORDS[x.state].label.toLowerCase()}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-5 text-small tabular-nums">
                      <AnimatedNumber value={x.equity} format={(n) => formatMoney(n, MARKET_CURRENCY[x.market], 0)} />
                      <Change value={x.day_pnl} text={`${formatSignedMoney(x.day_pnl, MARKET_CURRENCY[x.market], 0)} today`} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </ScrollBox>
        </CardBody>
      )}
    </Card>
  );
}

function NewsRisk() {
  const s = useApi<{ risk: LiveNews["risk"]; guard: LiveNews["guard"]; enabled: boolean }>("/news/live?limit=1", 120_000);
  return (
    <Card>
      <CardHeader>
        <CardTitle>News risk</CardTitle>
        <Button size="sm" variant="ghost" asChild>
          <Link to="/news">Open News</Link>
        </Button>
      </CardHeader>
      <CardBody className="flex flex-col gap-4">
        {s.status === "loading" && <LoadingRows rows={2} />}
        {s.status === "error" && <ErrorState error={s.error} onRetry={s.reload} />}
        {s.status === "ready" && !s.data.enabled && (
          <EmptyState icon={Newspaper} title="News is turned off" body="Turn it on in Settings → Kairos to see how risky the news is for markets." className="py-4" />
        )}
        {s.status === "ready" && s.data.enabled &&
          (["IN", "US"] as const).map((m) => {
            const r = s.data.risk[m];
            return (
              <div key={m} className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between gap-3 text-small">
                  <span className="font-semibold">{m === "IN" ? "India" : "US"}</span>
                  <span className="flex items-center gap-2 tabular-nums">
                    {Math.round(r.level)}/100
                    <Pill tone={RISK_TONE[r.name]} className="h-6 px-2 text-tiny capitalize">{r.name}</Pill>
                  </span>
                </div>
                <RiskMeter level={r.level} name={r.name} />
                <span className="truncate text-tiny text-fg-subtle">{r.drivers[0]?.title ?? guardWords(r.level, s.data.guard)}</span>
              </div>
            );
          })}
      </CardBody>
    </Card>
  );
}

/** Kairos and Metis working on their own (D-99): what they're doing, the desks, the AI helper. */
function Autopilot() {
  const s = useApi<AutopilotStatus>("/autopilot", 30_000);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KairosMark />
          Kairos and Metis
        </CardTitle>
        <Button size="sm" variant="ghost" asChild>
          <Link to="/settings?tab=kairos">Settings</Link>
        </Button>
      </CardHeader>
      <CardBody className="flex flex-col gap-3">
        {s.status === "loading" && <LoadingRows rows={2} />}
        {s.status === "error" && <ErrorState error={s.error} onRetry={s.reload} />}
        {s.status === "ready" && !s.data.on && (
          <EmptyState icon={Bot} title="Working on their own is off" body="Turn on “Work on their own” in Settings → Kairos and they start whenever Agora opens." className="py-4" />
        )}
        {s.status === "ready" && s.data.on && (
          <>
            <p className="m-0 flex items-center gap-2 text-small">
              <Dot tone={s.data.running ? "profit" : "neutral"} live={!!s.data.doing} />
              {s.data.doing || (s.data.running ? "Working on their own while Agora is open." : "Starts on its own on your laptop when Agora opens.")}
            </p>
            <ScrollBox size="sm">
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-small">
                {s.data.desks.length === 0 && <li className="text-fg-muted">Kairos will pick its stocks and start its paper desks once prices are in.</li>}
                {s.data.desks.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-2">
                    <Link to={`/paper/desk/${d.id}`} className="truncate font-semibold text-fg no-underline hover:underline">
                      {d.name}
                    </Link>
                    <span className="shrink-0 text-tiny text-fg-subtle">{d.auto ? "started on its own" : "started by you"}</span>
                  </li>
                ))}
                <li className="flex items-center justify-between gap-2">
                  <Link to="/metis" className="font-semibold text-fg no-underline hover:underline">
                    Metis
                  </Link>
                  <span className="text-tiny text-fg-subtle">{!s.data.metis.on ? "off" : s.data.metis.ai_ready ? "researching with the AI helper" : s.data.metis.why.includes("switched off") ? "working from its playbook; its own ideas are off" : "working from its playbook until Ollama is ready"}</span>
                </li>
              </ul>
            </ScrollBox>
            {Object.entries(s.data.prices).map(([m, p]) =>
              p && p.have < p.want ? (
                <p key={m} className="m-0 text-tiny text-fg-subtle">
                  {m === "IN" ? "India" : "US"}: prices for {p.have} of {p.want} stocks so far (a batch each round).
                </p>
              ) : null,
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}

function RecentBacktests() {
  const s = useApi<{ backtests: BacktestBrief[] }>("/backtests?limit=5");
  const items = s.status === "ready" ? s.data.backtests : [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent backtests</CardTitle>
        {items.length > 0 && (
          <Button size="sm" variant="ghost" asChild>
            <Link to="/backtests">See all</Link>
          </Button>
        )}
      </CardHeader>
      <CardBody>
        {s.status === "loading" && <LoadingRows rows={2} />}
        {s.status === "ready" && items.length === 0 && (
          <EmptyState
            icon={FlaskConical}
            title="No backtests yet"
            body="Your latest results will appear here with their return and worst drop."
            className="py-6"
          />
        )}
        {items.length > 0 && (
          <ScrollBox size="md">
            <ul className="m-0 flex list-none flex-col p-0">
              {items.map((b) => (
                <li key={b.id} className="border-b border-hairline last:border-0">
                  <Link to={`/backtests/${b.id}`} className="flex items-center justify-between gap-4 py-2.5 text-fg no-underline hover:text-accent-strong">
                    <span className="min-w-0 truncate font-semibold">
                      {b.strategy_name} <span className="font-normal text-fg-subtle">v{b.version} · {b.market === "IN" ? "India" : "US"}</span>
                      {b.symbols.length >= 30 && <span className="font-normal text-fg-subtle" title="This ran on today's most traded stocks, which went up to get there, so the figure is too high."> · today's list, flattered</span>}
                    </span>
                    <span className="flex shrink-0 items-center gap-4 text-small tabular-nums">
                      {b.status === "done" && b.headline.total_return != null ? (
                        <Change value={b.headline.total_return} text={formatPercent(b.headline.total_return)} />
                      ) : (
                        <span className="text-fg-muted">{b.status === "running" ? `Running ${Math.round(b.progress)}%` : b.status}</span>
                      )}
                      <span className="w-20 text-right text-fg-subtle">{formatAgo(b.created_at)}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </ScrollBox>
        )}
      </CardBody>
    </Card>
  );
}

interface Alarm {
  level: "error" | "warn" | "info";
  what: string;
  next: string;
  key: string;
}

/** What should have happened and didn't (D-222). Nothing shows when all is well. */
function Alarms() {
  const state = useApi<{ alarms: Alarm[] }>("/alarms", 60_000);
  if (state.status !== "ready" || state.data.alarms.length === 0) return null;
  return (
    <Card className="gap-2 p-4" role="status" aria-label="Things that need a look">
      {state.data.alarms.map((a) => (
        <p key={a.key} className="m-0 flex items-start gap-2 text-small">
          <span className="mt-1.5"><Dot tone={a.level === "error" ? "loss" : a.level === "warn" ? "warning" : "neutral"} /></span>
          <span><strong className="font-semibold">{a.what}</strong> <span className="text-fg-muted">{a.next}</span></span>
        </p>
      ))}
    </Card>
  );
}

export default function Home() {
  return (
    <>
      <PageHeader
        title={greeting(new Date().getHours())}
        subtitle="Build a strategy, test it on past prices, then paper trade it with fake money."
        actions={
          <>
            <Button asChild>
              <Link to="/backtests">Run a backtest</Link>
            </Button>
            <Button variant="primary" asChild>
              <Link to="/strategies">New strategy</Link>
            </Button>
          </>
        }
      />
      <Alarms />
      <Markets />
      <div className="grid grid-cols-3 gap-5">
        <PaperCard />
        <Autopilot />
      </div>
      <div className="grid grid-cols-3 gap-5">
        <div className="col-span-2">
          <RecentBacktests />
        </div>
        <NewsRisk />
      </div>
      <div className="grid grid-cols-3 gap-5">
        <DataHealth />
      </div>
    </>
  );
}
