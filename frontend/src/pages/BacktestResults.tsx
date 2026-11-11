import { ArrowLeft, Copy, FlaskConical, Pencil, Radio, Sparkles, Star } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";
import { JobProgress } from "../components/JobProgress";
import { ErrorState, LoadingRows } from "../components/states";
import { AnimatedNumber } from "../components/ui/animated-number";
import { Button } from "../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Change } from "../components/ui/change";
import { Pill } from "../components/ui/pill";
import { Tabs } from "../components/ui/tabs";
import { Tooltip } from "../components/ui/tooltip";
import { patchJson, postJson, type BacktestDetail, type EquityResponse, type TradeRow } from "../lib/api";
import { formatDate, formatMoney, formatPercent, MARKET_CURRENCY, MARKET_TZ, TIMEFRAME_LABEL } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ChargesDonut, DrawdownChart, EquityChart, MonthlyHeatmap, PnlDistribution } from "./results/charts";
import { HonestyPanel, MetricsTable, PerSymbolTable } from "./results/panels";
import { PeriodsView, SweepView, WalkForwardView } from "./results/robustness";
import { TearSheet, type TearSheetData } from "./results/TearSheet";
import { TradeChart } from "./results/TradeChart";
import { TradesTable } from "./results/TradesTable";
import { AIExplain } from "../components/ai/AIExplain";
import { Dialog } from "../components/ui/dialog";
import { TradeCheckNote, TradeReview, type TradeCheckSummary } from "../components/kairos/TradeReview";

const BENCH = { IN: "Nifty 50", US: "S&P 500 (SPY)" } as const;
const MODE_WORDS = { single: "Standard", oos: "In / out of sample", sweep: "Parameter sweep", walk_forward: "Walk-forward" } as const;

function Headline({ label, tip, value, format, signed }: { label: string; tip: string; value: number | null | undefined; format: (n: number) => string; signed?: boolean }) {
  return (
    <Card className="gap-1 p-4">
      <Tooltip content={tip}>
        <p className="m-0 w-fit cursor-help text-small text-fg-muted underline decoration-dotted decoration-fg-subtle/50 underline-offset-4" tabIndex={0}>
          {label}
        </p>
      </Tooltip>
      <p className="m-0 text-[22px] leading-8 font-bold tracking-tight tabular-nums min-[1500px]:text-[26px]">
        {value === null || value === undefined ? (
          <span className="text-fg-subtle">—</span>
        ) : signed ? (
          <Change value={value} text={format(value)} />
        ) : (
          <AnimatedNumber value={value} format={format} />
        )}
      </p>
    </Card>
  );
}

function Running({ run, onDone }: { run: BacktestDetail; onDone: () => void }) {
  useEffect(() => {
    const id = setInterval(onDone, 1000);
    return () => clearInterval(id);
  }, [onDone]);
  const cancel = () => postJson(`/backtests/${run.id}/cancel`).catch(() => undefined);
  return (
    <Card className="p-6">
      {run.job ? <JobProgress job={run.job} onCancel={cancel} /> : <LoadingRows rows={2} />}
    </Card>
  );
}

function Results({ run }: { run: BacktestDetail }) {
  const m = run.metrics ?? {};
  const market = run.market;
  const cur = MARKET_CURRENCY[market];
  const eq = useApi<EquityResponse>(`/backtests/${run.id}/equity`);
  const allTrades = useApi<{ trades: TradeRow[] }>(`/backtests/${run.id}/trades?limit=5000`);
  const [tab, setTab] = useState("trades");
  const [explainTrade, setExplainTrade] = useState<TradeRow | null>(null);
  const bench = m.benchmark?.total_return ?? null;
  const symbols = useMemo(() => (m.per_symbol ?? []).map((r) => r.symbol), [m.per_symbol]);
  const tradedSymbols = symbols.length ? symbols : run.symbols;
  const periods = m.periods as Parameters<typeof PeriodsView>[0]["periods"] | undefined;
  const sweep = m.sweep as Parameters<typeof SweepView>[0]["sweep"] | undefined;
  const wf = m.walk_forward as Parameters<typeof WalkForwardView>[0]["wf"] | undefined;

  return (
    <>
      <div className="grid grid-cols-7 gap-4">
        <Headline label="Total return" tip="How much the money grew or shrank overall." value={m.total_return} format={(n) => formatPercent(n)} signed />
        <Headline label="Yearly return" tip="The average growth per year, compounded (CAGR)." value={m.cagr} format={(n) => formatPercent(n)} signed />
        <Headline label="Worst drop" tip="The biggest fall from a high point before recovering (max drawdown)." value={m.max_drawdown} format={(n) => `${(n * 100).toFixed(1)}%`} />
        <Headline label="Sharpe ratio" tip="Return per unit of ups and downs. Above 1 is good; above 2 is very good." value={m.sharpe} format={(n) => n.toFixed(2)} />
        <Headline label="Win rate" tip="The share of completed trades that made money." value={m.win_rate as number | null} format={(n) => `${Math.round(n * 100)}%`} />
        <Headline label="Trades" tip="Completed trades. Fewer than 30 is too few to trust." value={m.trades as number | null} format={(n) => String(Math.round(n))} />
        <Headline label={`vs ${BENCH[market]}`} tip={`Your total return minus simply holding the ${BENCH[market]} over the same dates (${bench !== null ? formatPercent(bench) : "—"}).`} value={m.vs_benchmark as number | null} format={(n) => formatPercent(n)} signed />
      </div>
      {run.summary && (
        <Card className="flex-row items-start gap-3 p-5">
          <Sparkles className="mt-1 size-4 shrink-0 text-accent" aria-hidden="true" />
          <div className="flex flex-col gap-2">
            <p className="m-0 text-body">{run.summary}</p>
            <p className="m-0 text-tiny text-fg-subtle">Written by rules from the numbers above. Final money: {formatMoney(Number(m.final_equity ?? 0), cur, 0)} from {formatMoney(run.capital, cur, 0)}.</p>
          </div>
        </Card>
      )}
      {m.trade_check ? <TradeCheckNote tc={m.trade_check as TradeCheckSummary} /> : null}
      <Card>
        <CardHeader>
          <CardTitle>Ask the AI helper</CardTitle>
        </CardHeader>
        <CardBody className="flex flex-col gap-4">
          <AIExplain kind="backtest" id={run.id} label="Explain this backtest" />
          <AIExplain kind="metric" id={run.id} label="Ask" ask placeholder="Ask about a number, e.g. what does my Sharpe ratio mean?" />
        </CardBody>
      </Card>
      <div className="grid grid-cols-[minmax(0,1fr)_360px] items-start gap-5">
        <Card>
          <CardHeader>
            <CardTitle>Money over time</CardTitle>
          </CardHeader>
          <CardBody>{eq.status === "ready" ? <EquityChart data={eq.data} market={market} benchmarkName={BENCH[market]} /> : <LoadingRows rows={4} />}</CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>How much to trust this</CardTitle>
          </CardHeader>
          <CardBody>
            <HonestyPanel warnings={run.warnings} />
          </CardBody>
        </Card>
      </div>
      {run.parent_run_id === null && <TradeReview kind="backtest" refId={run.id} market={market} strategyId={run.strategy_id} canImprove />}
      {periods && (
        <Card>
          <CardHeader>
            <CardTitle>In-sample vs out-of-sample</CardTitle>
          </CardHeader>
          <CardBody>
            <PeriodsView periods={periods} market={market} />
          </CardBody>
        </Card>
      )}
      {sweep && (
        <Card>
          <CardHeader>
            <CardTitle>Parameter sweep</CardTitle>
          </CardHeader>
          <CardBody>
            <SweepView sweep={sweep} />
          </CardBody>
        </Card>
      )}
      {wf && (
        <Card>
          <CardHeader>
            <CardTitle>Walk-forward windows</CardTitle>
          </CardHeader>
          <CardBody>
            <WalkForwardView wf={wf} market={market} />
          </CardBody>
        </Card>
      )}
      <TearSheet runId={run.id} saved={m.tear_sheet as TearSheetData | undefined} />
      <div className="grid grid-cols-2 gap-5">
        <Card>
          <CardHeader>
            <CardTitle>Drops along the way</CardTitle>
          </CardHeader>
          <CardBody>{eq.status === "ready" ? <DrawdownChart data={eq.data} market={market} /> : <LoadingRows rows={3} />}</CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Monthly returns</CardTitle>
          </CardHeader>
          <CardBody>{m.monthly_returns ? <MonthlyHeatmap monthly={m.monthly_returns} /> : null}</CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Trade results</CardTitle>
          </CardHeader>
          <CardBody>{allTrades.status === "ready" ? <PnlDistribution trades={allTrades.data.trades} /> : <LoadingRows rows={3} />}</CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Charges</CardTitle>
            <span className="text-small font-semibold tabular-nums">{formatMoney(Number(m.charges_total ?? 0), cur)}</span>
          </CardHeader>
          <CardBody>
            {m.charges_by_type && Object.keys(m.charges_by_type).length ? (
              <ChargesDonut byType={m.charges_by_type} market={market} />
            ) : (
              <p className="m-0 text-small text-fg-muted">No charges were paid.</p>
            )}
          </CardBody>
        </Card>
      </div>
      <Card className="min-h-[300px]">
        <Tabs
          label="Details"
          value={tab}
          onValueChange={setTab}
          tabs={[
            { value: "trades", label: "Trades", content: <div className="py-4"><TradesTable runId={run.id} market={market} symbols={tradedSymbols} onExplain={setExplainTrade} /></div> },
            { value: "chart", label: "Price chart", content: <div className="p-5"><TradeChart runId={run.id} market={market} timeframe={run.timeframe} symbols={tradedSymbols} start={run.start} end={run.end} /></div> },
            { value: "symbols", label: "By stock", content: <div className="py-4">{m.per_symbol ? <PerSymbolTable rows={m.per_symbol} market={market} /> : null}</div> },
            { value: "metrics", label: "All numbers", content: <div className="p-5"><MetricsTable m={m} market={market} /></div> },
            { value: "orders", label: "Skipped orders", content: <div className="p-5"><SkippedOrders runId={run.id} market={market} /></div> },
          ]}
        />
      </Card>
      <Dialog open={explainTrade !== null} onOpenChange={(o) => !o && setExplainTrade(null)} title={explainTrade ? `The ${explainTrade.symbol} trade` : "Trade"} description="Why the strategy opened and closed this trade, in plain English.">
        {explainTrade && <AIExplain key={explainTrade.id} kind="trade" id={explainTrade.id} label="Explain this trade" autoStart />}
      </Dialog>
    </>
  );
}

function SkippedOrders({ runId, market }: { runId: number; market: "IN" | "US" }) {
  const s = useApi<{ orders: { ts: number; symbol: string; side: string; reason: string }[] }>(`/backtests/${runId}/orders?status=rejected`);
  if (s.status !== "ready") return <LoadingRows rows={3} />;
  if (!s.data.orders.length) return <p className="m-0 text-small text-fg-muted">Every order the strategy asked for was filled.</p>;
  return (
    <ul className="m-0 flex max-h-[360px] list-none flex-col gap-1.5 overflow-y-auto p-0 text-small">
      {s.data.orders.map((o, i) => (
        <li key={i} className="flex gap-3">
          <span className="w-28 shrink-0 tabular-nums text-fg-subtle">{formatDate(o.ts, MARKET_TZ[market])}</span>
          <span className="w-24 shrink-0 font-semibold">{o.symbol}</span>
          <span className="text-fg-muted">{o.reason}</span>
        </li>
      ))}
    </ul>
  );
}

export default function BacktestResults() {
  const { id } = useParams();
  const s = useApi<BacktestDetail>(`/backtests/${id}`);
  const [starred, setStarred] = useState<boolean | null>(null);
  if (s.status === "loading") return <LoadingRows rows={6} />;
  if (s.status === "error") return <ErrorState error={s.error} onRetry={s.reload} />;
  const run = s.data;
  const isStarred = starred ?? run.starred;
  const tz = MARKET_TZ[run.market];

  async function star() {
    const next = !isStarred;
    setStarred(next);
    await patchJson(`/backtests/${run.id}`, { starred: next }).catch(() => setStarred(!next));
    toast.success(next ? "Starred. Starred backtests keep their full order log." : "Star removed.");
  }

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <Link to="/backtests" className="flex w-fit items-center gap-1 text-small text-fg-muted no-underline hover:text-fg">
            <ArrowLeft className="size-3.5" aria-hidden="true" />
            All backtests
          </Link>
          <h1 className="m-0 text-title font-bold tracking-tight">
            {run.name ?? run.strategy_name} <span className="text-fg-subtle">· v{run.version}</span>
          </h1>
          <div className="flex flex-wrap items-center gap-2 text-small text-fg-muted">
            <Pill className="h-6 px-2 text-tiny">{run.market === "IN" ? "India" : "US"}</Pill>
            <Pill className="h-6 px-2 text-tiny">{TIMEFRAME_LABEL[run.timeframe]}</Pill>
            <Pill className="h-6 px-2 text-tiny">{MODE_WORDS[run.mode]}</Pill>
            <span>
              {formatDate(run.start, tz)} – {formatDate(run.end - 1, tz)} · {run.symbols.length} stock{run.symbols.length === 1 ? "" : "s"}
            </span>
          </div>
        </div>
        <div className="flex gap-2.5">
          <Button variant="ghost" onClick={star} aria-pressed={isStarred}>
            <Star aria-hidden="true" className={isStarred ? "fill-accent text-accent" : ""} />
            {isStarred ? "Starred" : "Star"}
          </Button>
          <Button variant="ghost" asChild>
            <Link to={`/strategies/${run.strategy_id}`}>
              <Pencil aria-hidden="true" />
              Edit strategy
            </Link>
          </Button>
          <Button asChild>
            <Link to={`/compare?runs=${run.id}`}>
              <Copy aria-hidden="true" />
              Compare
            </Link>
          </Button>
          {run.status === "done" && (
            <Button asChild>
              <Link to={`/paper?start=${run.strategy_id}`}>
                <Radio aria-hidden="true" />
                Paper trade
              </Link>
            </Button>
          )}
          <Button variant="primary" asChild>
            <Link to={`/backtests/new?strategy=${run.strategy_id}`}>
              <FlaskConical aria-hidden="true" />
              Run again
            </Link>
          </Button>
        </div>
      </div>
      {(run.status === "running" || run.status === "queued") && <Running run={run} onDone={s.reload} />}
      {run.status === "failed" && <ErrorState error={{ code: "BACKTEST_FAILED", message: run.error ?? "The backtest failed.", action: "", detail: run.error_detail ?? "" }} />}
      {run.status === "cancelled" && <Card className="p-5 text-small text-fg-muted">This backtest was cancelled.</Card>}
      {run.status === "done" && <Results run={run} />}
    </>
  );
}
