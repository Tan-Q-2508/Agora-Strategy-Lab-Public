import { ArrowLeft, Pause, Play, Square } from "lucide-react";
import { useCallback, useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";
import { AIExplain } from "../components/ai/AIExplain";
import { ErrorState, LoadingRows } from "../components/states";
import { AnimatedNumber } from "../components/ui/animated-number";
import { Button } from "../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { TradeReview } from "../components/kairos/TradeReview";
import { Change } from "../components/ui/change";
import { Dialog } from "../components/ui/dialog";
import { Pill } from "../components/ui/pill";
import { Tabs } from "../components/ui/tabs";
import { Tooltip } from "../components/ui/tooltip";
import { postJson, toEnvelope, type PaperSessionDetail, type PaperTick } from "../lib/api";
import { formatDateTime, formatMoney, formatSignedMoney, MARKET_CURRENCY, MARKET_TZ, TIMEFRAME_LABEL } from "../lib/format";
import { useLive, useLiveConnected, type LiveMessage } from "../lib/live";
import { useApi } from "../lib/useApi";
import { STATE_WORDS, useThrottledReload } from "./paper/common";
import { FreshnessBadge } from "./paper/Freshness";
import { PerformanceCard } from "./paper/PerformanceCard";
import { KairosMark } from "../components/kairos/KairosMark";
import type { DeskDetail } from "../lib/desk";
import { Journal, LearnedCard } from "./paper/DeskPanels";
import { ActivityLog, ClosedTrades, FillsFeed, LiveEquityChart, PositionsTable, RejectedOrders, SessionPriceChart, VsBacktestPanel } from "./paper/panels";

function Stat({ label, tip, children }: { label: string; tip: string; children: React.ReactNode }) {
  return (
    <Card className="gap-1 p-4">
      <Tooltip content={tip}>
        <p className="m-0 w-fit cursor-help text-small text-fg-muted underline decoration-dotted decoration-fg-subtle/50 underline-offset-4" tabIndex={0}>
          {label}
        </p>
      </Tooltip>
      <p className="m-0 text-[26px] leading-8 font-bold tracking-tight tabular-nums">{children}</p>
    </Card>
  );
}

export default function PaperSession() {
  const { id } = useParams();
  const sid = Number(id);
  const connected = useLiveConnected();
  const detail = useApi<{ session: PaperSessionDetail }>(`/paper/sessions/${sid}`, connected ? 30_000 : 5_000);
  const reload = useThrottledReload(detail.reload);
  const [tick, setTick] = useState<PaperTick | null>(null);
  const [version, setVersion] = useState(0);
  const [confirmStop, setConfirmStop] = useState(false);
  const [busy, setBusy] = useState(false);

  const onLive = useCallback(
    (msg: LiveMessage) => {
      if (Number(msg.data.session_id) !== sid) return;
      if (msg.type === "paper.tick") {
        setTick(msg.data as unknown as PaperTick);
        setVersion((v) => v + 1);
      }
      reload();
    },
    [sid, reload],
  );
  useLive(["paper."], onLive, detail.reload);

  async function control(action: "pause" | "resume" | "stop") {
    setBusy(true);
    try {
      await postJson(`/paper/sessions/${sid}/${action}`);
      setTick(null);
      detail.reload();
      toast.success({ pause: "Paused. Open trades are still watched.", resume: "Resumed.", stop: "Paper trading stopped." }[action]);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    } finally {
      setBusy(false);
      setConfirmStop(false);
    }
  }

  if (detail.status === "error") return <ErrorState error={detail.error} onRetry={detail.reload} />;
  if (detail.status === "loading") return <LoadingRows rows={6} />;
  const s = detail.data.session;
  const live = tick && tick.session_id === s.id && s.state !== "stopped" ? tick : null;
  const state = live?.state ?? s.state;
  const equity = live?.equity ?? s.equity;
  const dayPnl = live?.day_pnl ?? s.day_pnl;
  const positions = live?.positions ?? s.positions;
  const freshness = live?.freshness ?? s.freshness;
  const problem = live?.problem ?? s.problem;
  const cur = MARKET_CURRENCY[s.market];
  const tz = MARKET_TZ[s.market];
  // counted from the money the desk's first run started with, less money a portfolio moved (D-146)
  const capital = s.first_capital ?? s.account.starting_capital;
  const totalReturn = 100 * ((equity - (s.moved ?? 0)) / capital - 1);
  const st = STATE_WORDS[state];
  const running = state !== "stopped";
  const curve = live && live.equity !== null && s.equity_curve.length && live.now > s.equity_curve[s.equity_curve.length - 1]!.ts ? [...s.equity_curve, { ts: live.now, equity: live.equity, cash: live.cash ?? 0 }] : s.equity_curve;
  const chartVersion = (s.last_bar_ts ?? 0) + s.fills.length;
  const desk = s.kind === "kairos";

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-2">
          <Link to={desk ? "/paper/desk" : "/paper"} className="flex w-fit items-center gap-1.5 text-small text-fg-muted no-underline hover:text-fg">
            <ArrowLeft className="size-4" aria-hidden="true" />
            {desk ? "Kairos desk" : "Paper trading"}
          </Link>
          <h1 className="m-0 flex items-center gap-2.5 text-title font-bold tracking-tight">
            {desk && <KairosMark className="size-7" />}
            {s.name}
          </h1>
          <div className="flex flex-wrap items-center gap-2 text-small text-fg-muted">
            <Pill tone={st.tone} className="h-7 px-2.5 text-tiny">{st.label}</Pill>
            {desk && <Pill tone="accent" className="h-7 px-2.5 text-tiny">Kairos trades this on its own</Pill>}
            {s.mode === "replay" && <Pill tone="info" className="h-7 px-2.5 text-tiny">Practice replay</Pill>}
            <span>
              {s.market === "IN" ? "India" : "US"} · {TIMEFRAME_LABEL[s.timeframe]} · version {s.version} · {s.account.name} · started {formatDateTime(s.started_at, tz)}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          {running && <FreshnessBadge f={freshness} />}
          {running && state === "paused_user" && (
            <Button onClick={() => void control("resume")} disabled={busy}>
              <Play aria-hidden="true" />
              Resume
            </Button>
          )}
          {running && state !== "paused_user" && (
            <Button onClick={() => void control("pause")} disabled={busy || state === "starting"}>
              <Pause aria-hidden="true" />
              Pause
            </Button>
          )}
          {running && (
            <Button variant="danger" onClick={() => setConfirmStop(true)} disabled={busy}>
              <Square aria-hidden="true" />
              Stop
            </Button>
          )}
        </div>
      </div>

      {problem && running && (
        <Card role="status" className="flex-row items-start gap-3 bg-warning-soft p-4 text-warning-soft-fg">
          <p className="m-0 text-[14px]">{problem}</p>
        </Card>
      )}
      {s.mode === "replay" && running && (
        <p className="m-0 text-small text-fg-muted">
          Practice data is on, so this session replays past practice prices a few candles per second. With real data, a session follows live prices during market hours.
        </p>
      )}
      {s.gaps.length > 0 && (
        <p className="m-0 text-small text-fg-muted">
          Agora was closed {s.gaps.length} time{s.gaps.length === 1 ? "" : "s"} during this session; trades it would have made then were not simulated. See Activity for the times.
        </p>
      )}

      <div className="grid grid-cols-5 gap-4">
        <Stat label="Money now" tip="The paper account's cash plus the value of open trades.">
          <AnimatedNumber value={equity} format={(n) => formatMoney(n, cur, 0)} />
        </Stat>
        <Stat label="Today" tip="Profit or loss since today's first candle.">
          <Change value={dayPnl} text={formatSignedMoney(dayPnl, cur, 0)} />
        </Stat>
        <Stat label="Total return" tip="How much the money grew or shrank since the session started.">
          <Change value={totalReturn} text={`${totalReturn >= 0 ? "+" : "−"}${Math.abs(totalReturn).toFixed(2)}%`} />
        </Stat>
        <Stat label="Open trades" tip="Trades bought and not yet sold.">
          {positions.length}
        </Stat>
        <Stat label="Completed trades" tip={desk ? "Trades opened and closed, over all of this desk's runs." : "Trades that were opened and closed in this session."}>
          {s.stats?.trades ?? s.trades}
        </Stat>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_400px] items-start gap-5">
        <div className="flex min-w-0 flex-col gap-5">
          <Card>
            <CardHeader>
              <CardTitle>Prices and trades</CardTitle>
            </CardHeader>
            <CardBody>
              <SessionPriceChart sessionId={s.id} instruments={s.instruments} market={s.market} timeframe={s.timeframe} version={chartVersion} />
            </CardBody>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Money over time</CardTitle>
            </CardHeader>
            <CardBody>
              <LiveEquityChart points={curve} market={s.market} capital={capital} intraday={s.timeframe !== "1d"} />
            </CardBody>
          </Card>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Recent fills</CardTitle>
          </CardHeader>
          <CardBody>
            <FillsFeed fills={s.fills} market={s.market} />
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Open trades</CardTitle>
        </CardHeader>
        <PositionsTable positions={positions} market={s.market} />
      </Card>

      {desk && <DeskSection sid={s.id} version={s.trades + positions.length} />}

      <PerformanceCard stats={s.stats} market={s.market} runs={s.runs ?? 1} desk={desk} />

      <SessionTabs s={s} />

      {s.last_bar_ts !== null && (
        <Card>
          <CardHeader>
            <CardTitle>The day in plain English</CardTitle>
          </CardHeader>
          <CardBody>
            <AIExplain kind="paper_day" id={s.id} label="Summarize the latest day" />
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Backtest vs live</CardTitle>
        </CardHeader>
        <CardBody>
          <VsBacktestPanel sessionId={s.id} market={s.market} version={running ? Math.floor(version / 20) : -1} />
        </CardBody>
      </Card>

      {s.trades > 0 && <TradeReview kind="paper" refId={s.id} market={s.market} />}

      <Dialog
        open={confirmStop}
        onOpenChange={setConfirmStop}
        title="Stop paper trading?"
        description="The session ends for good. Open trades stay as they are in the results; start a new session to paper trade again."
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmStop(false)}>
              Keep running
            </Button>
            <Button variant="danger" onClick={() => void control("stop")} disabled={busy}>
              Stop paper trading
            </Button>
          </>
        }
      >
        <p className="m-0 text-small text-fg-muted">Tip: use Pause instead to stop new trades for a while without ending the session.</p>
      </Dialog>
    </>
  );
}

function SessionTabs({ s }: { s: PaperSessionDetail }) {
  const [tab, setTab] = useState("activity");
  return (
    <Card className="p-0">
      <Tabs
        label="Session details"
        value={tab}
        onValueChange={setTab}
        tabs={[
          { value: "activity", label: "Activity", content: <ActivityLog events={s.events} market={s.market} /> },
          { value: "trades", label: `Completed trades (${s.stats?.trades ?? s.closed_trades.length})`, content: <ClosedTrades trades={s.closed_trades} market={s.market} /> },
          { value: "rejected", label: `Turned-down orders (${s.rejected.length})`, content: <RejectedOrders rows={s.rejected} market={s.market} /> },
        ]}
      />
    </Card>
  );
}

/** A Kairos desk's diary and what it learned (refreshed as trades open and close). */
function DeskSection({ sid, version }: { sid: number; version: number }) {
  const d = useApi<DeskDetail>(`/kairos/desk/${sid}?v=${version}`);
  if (d.status !== "ready") return null;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_420px] items-start gap-5">
      <Card>
        <CardHeader>
          <CardTitle>Kairos's diary</CardTitle>
        </CardHeader>
        <CardBody>
          <Journal entries={d.data.journal} market={d.data.market} />
        </CardBody>
      </Card>
      <LearnedCard learned={d.data.learned} lessons={d.data.lessons} onRetrained={d.reload} />
    </div>
  );
}
