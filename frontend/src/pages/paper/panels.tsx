import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Inbox, Info, XCircle } from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EChart, type OptionBuilder } from "../../components/charts/EChart";
import { PriceChart, type Candle, type TradeMarker } from "../../components/charts/PriceChart";
import { alpha } from "../../components/charts/tokens";
import { EmptyState, LoadingRows } from "../../components/states";
import { Change } from "../../components/ui/change";
import { Select } from "../../components/ui/input";
import { Segmented } from "../../components/ui/segmented";
import { Skeleton } from "../../components/ui/skeleton";
import type { MarketCode, PaperEventRow, PaperFillRow, PaperPosition, PaperTradeRow, Timeframe, VsBacktest } from "../../lib/api";
import { formatCompactMoney, formatDate, formatDateTime, formatMoney, formatSignedMoney, MARKET_CURRENCY, MARKET_TZ } from "../../lib/format";
import { duration, ease } from "../../lib/motion";
import { useApi } from "../../lib/useApi";
import { cn } from "../../lib/utils";
import { EXIT_WORDS } from "./exitWords";
import { bucketEquity, defaultView, HOURS_DAYS, yRange, type EquityView } from "./equityView";
import { ScrollBox } from "../../components/ui/scroll-box";

const th = "px-4 py-2.5 text-left text-tiny font-medium tracking-wide text-fg-subtle uppercase";
const td = "px-4 py-2.5 tabular-nums";

/** Briefly tint a cell when its value changes (DESIGN_BRIEF: "live P&L flashes, subtle"). */
function Flash({ value, children }: { value: number; children: React.ReactNode }) {
  const prev = useRef(value);
  const [dir, setDir] = useState<"up" | "down" | null>(null);
  useEffect(() => {
    if (value === prev.current) return;
    const d = value > prev.current ? "up" : "down";
    prev.current = value;
    const show = setTimeout(() => setDir(d), 0);
    const hide = setTimeout(() => setDir(null), 700);
    return () => {
      clearTimeout(show);
      clearTimeout(hide);
    };
  }, [value]);
  return (
    <span className={cn("rounded px-1 transition-colors duration-700", dir === "up" && "bg-profit-soft", dir === "down" && "bg-loss-soft")}>{children}</span>
  );
}

export function PositionsTable({ positions, market }: { positions: PaperPosition[]; market: MarketCode }) {
  const cur = MARKET_CURRENCY[market];
  const tz = MARKET_TZ[market];
  if (!positions.length) {
    return <EmptyState icon={Inbox} title="No open trades" body="When the strategy buys, the trade appears here with its live profit or loss." className="py-8" />;
  }
  return (
    <ScrollBox size="lg" className="overflow-x-auto">
      <table className="w-full border-collapse text-[14px]">
        <thead>
          <tr className="border-b border-hairline">
            <th className={th}>Stock</th>
            <th className={th}>Side</th>
            <th className={cn(th, "text-right")}>Shares</th>
            <th className={cn(th, "text-right")}>Bought at</th>
            <th className={cn(th, "text-right")}>Price now</th>
            <th className={cn(th, "text-right")}>Profit / loss</th>
            <th className={cn(th, "text-right")}>Stop-loss</th>
            <th className={cn(th, "text-right")}>Take-profit</th>
            <th className={cn(th, "text-right")}>Partial profit at</th>
            <th className={th}>Since</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.instrument_id} className="border-b border-hairline last:border-0">
              <td className={cn(td, "font-semibold")}>{p.symbol}</td>
              <td className={td}>{p.side === "long" ? "Bought" : "Short"}</td>
              <td className={cn(td, "text-right")}>{p.qty.toLocaleString()}</td>
              <td className={cn(td, "text-right")}>{formatMoney(p.entry_price, cur)}</td>
              <td className={cn(td, "text-right")}>{p.last_price !== null ? <Flash value={p.last_price}>{formatMoney(p.last_price, cur)}</Flash> : "—"}</td>
              <td className={cn(td, "text-right")}>
                {p.unrealized !== null ? (
                  <Flash value={p.unrealized}>
                    <Change value={p.unrealized} text={`${formatSignedMoney(p.unrealized, cur, 0)} (${(p.unrealized_pct ?? 0).toFixed(2)}%)`} />
                  </Flash>
                ) : (
                  "—"
                )}
              </td>
              <td className={cn(td, "text-right text-fg-muted")}>
                {p.stop !== null ? formatMoney(p.stop, cur) : "None"}
                {p.trailing && <span className="block text-[12px] text-fg-subtle">{p.trail_on ? "trailing, moved up" : "trails the price"}</span>}
              </td>
              <td className={cn(td, "text-right text-fg-muted")}>{p.target !== null ? formatMoney(p.target, cur) : "None"}</td>
              <td className={cn(td, "text-right text-fg-muted")}>{p.partial_at != null ? formatMoney(p.partial_at, cur) : p.trailing === undefined ? "—" : "None"}</td>
              <td className={cn(td, "text-fg-muted")}>{formatDateTime(p.entry_ts, tz)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollBox>
  );
}

export function FillsFeed({ fills, market }: { fills: PaperFillRow[]; market: MarketCode }) {
  const cur = MARKET_CURRENCY[market];
  const tz = MARKET_TZ[market];
  if (!fills.length) {
    return <EmptyState icon={Inbox} title="No fills yet" body="Every simulated buy and sell shows up here as it happens, with its reason." className="py-8" />;
  }
  return (
    <ul className="m-0 flex max-h-[420px] list-none flex-col gap-2 overflow-y-auto p-0" aria-label="Recent fills">
      <AnimatePresence initial={false}>
        {fills.slice(0, 50).map((f) => (
          <motion.li
            key={f.id}
            layout
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: duration.base, ease }}
            className="flex items-start gap-3 rounded-tile border border-hairline px-3 py-2.5"
          >
            <span className={cn("mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full", f.side === "buy" ? "bg-profit-soft text-profit" : "bg-loss-soft text-loss")}>
              {f.side === "buy" ? <ArrowUpRight className="size-4" aria-hidden="true" /> : <ArrowDownRight className="size-4" aria-hidden="true" />}
            </span>
            <div className="flex min-w-0 flex-1 flex-col">
              <p className="m-0 text-[14px]">
                <span className="font-semibold">{f.side === "buy" ? "Bought" : "Sold"}</span> {f.qty.toLocaleString()} {f.symbol} at {formatMoney(f.price, cur)}
              </p>
              <p className="m-0 truncate text-tiny text-fg-muted">
                {f.reason} · charges {formatMoney(f.charges, cur)}
              </p>
            </div>
            <time className="shrink-0 text-tiny text-fg-subtle tabular-nums">{formatDateTime(f.ts, tz)}</time>
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}

const LEVEL_ICON = { info: Info, warn: AlertTriangle, error: XCircle } as const;

export function ActivityLog({ events, market }: { events: PaperEventRow[]; market: MarketCode }) {
  const tz = MARKET_TZ[market];
  if (!events.length) return <p className="m-0 px-5 py-6 text-small text-fg-muted">Nothing has happened yet.</p>;
  return (
    <ul className="m-0 flex max-h-[420px] list-none flex-col overflow-y-auto p-0" aria-label="Activity">
      {events.map((e) => {
        const Icon = LEVEL_ICON[e.level];
        return (
          <li key={e.id} className="flex items-start gap-3 border-b border-hairline px-5 py-3 last:border-0">
            <Icon className={cn("mt-0.5 size-4 shrink-0", e.level === "info" ? "text-fg-subtle" : e.level === "warn" ? "text-warning" : "text-loss")} aria-hidden="true" />
            <p className="m-0 flex-1 text-[14px]">{e.message_plain}</p>
            <time className="shrink-0 text-tiny text-fg-subtle tabular-nums">{formatDateTime(e.ts, tz)}</time>
          </li>
        );
      })}
    </ul>
  );
}


interface Story {
  plan: string;
  known_at_entry: { score: number | null; for: string[]; against: string[]; sector: string };
  market_did: { best_pct: number; worst_pct: number; after_exit_pct: number | null };
  kairos_concluded: string;
  lesson: { kind: string; text: string };
}

/** Why a trade happened and what did or didn't work (the user, 2026-11-06). */
function TradeStory({ id }: { id: number }) {
  const s = useApi<Story>(`/paper/trades/${id}/story`);
  if (s.status === "loading") return <p className="m-0 text-small text-fg-muted">Reading the trade…</p>;
  if (s.status === "error") return <p className="m-0 text-small text-fg-muted">{s.error.message}</p>;
  const { plan, known_at_entry: k, market_did: m, kairos_concluded: done, lesson } = s.data;
  const row = (label: string, text: string) => (
    <>
      <dt className="text-fg-muted">{label}</dt>
      <dd className="m-0">{text}</dd>
    </>
  );
  return (
    <dl className="m-0 grid grid-cols-[130px_1fr] gap-x-3 gap-y-1.5 text-small">
      {row("The lesson", lesson.text)}
      {row("The plan", plan)}
      {k.for.length > 0 && row("In its favour", k.for.join(", "))}
      {k.against.length > 0 && row("Against it", k.against.join(", "))}
      {k.sector && row("Sector", k.sector)}
      {row("What the market did", `Best ${m.best_pct.toFixed(2)}%, worst ${m.worst_pct.toFixed(2)}%${m.after_exit_pct === null ? "" : `; after it closed, ${m.after_exit_pct.toFixed(2)}% more its way`}`)}
      {done && row("Kairos concluded", done)}
    </dl>
  );
}

export function ClosedTrades({ trades, market }: { trades: PaperTradeRow[]; market: MarketCode }) {
  const [open, setOpen] = useState<number | null>(null);
  const cur = MARKET_CURRENCY[market];
  const tz = MARKET_TZ[market];
  if (!trades.length) return <p className="m-0 px-5 py-6 text-small text-fg-muted">No completed trades yet.</p>;
  return (
    <div className="max-h-[420px] overflow-auto">
      <table className="w-full border-collapse text-[14px]">
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-hairline">
            <th className={th}>Stock</th>
            <th className={th}>Opened</th>
            <th className={th}>Closed</th>
            <th className={cn(th, "text-right")}>Profit / loss</th>
            <th className={th}>Why it closed</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <Fragment key={t.id}>
              <tr className="cursor-pointer border-b border-hairline last:border-0 hover:bg-surface-2/60" onClick={() => setOpen(open === t.id ? null : t.id)}>
                <td className={cn(td, "font-semibold")}>
                  {t.symbol} <span className="font-normal text-fg-subtle">{t.side === "short" ? "short" : ""}</span>
                </td>
                <td className={cn(td, "text-fg-muted")}>{formatDateTime(t.entry_ts, tz)}</td>
                <td className={cn(td, "text-fg-muted")}>{t.exit_ts ? formatDateTime(t.exit_ts, tz) : "—"}</td>
                <td className={cn(td, "text-right")}>
                  <Change value={t.net_pnl} text={`${formatSignedMoney(t.net_pnl, cur, 0)} (${t.return_pct.toFixed(2)}%)`} />
                </td>
                <td className={cn(td, "text-fg-muted")}>{EXIT_WORDS[t.exit_reason ?? ""] ?? t.exit_reason}</td>
              </tr>
              {open === t.id && (
                <tr>
                  <td colSpan={5} className="bg-surface-2/60 px-5 py-3">
                    <TradeStory id={t.id} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RejectedOrders({ rows, market }: { rows: { id: number; ts: number; symbol: string; side: string; reason: string }[]; market: MarketCode }) {
  const tz = MARKET_TZ[market];
  if (!rows.length) return <p className="m-0 px-5 py-6 text-small text-fg-muted">No orders were turned down.</p>;
  return (
    <ul className="m-0 flex max-h-[420px] list-none flex-col overflow-y-auto p-0">
      {rows.map((r) => (
        <li key={r.id} className="flex items-start gap-3 border-b border-hairline px-5 py-3 last:border-0">
          <span className="w-20 shrink-0 font-semibold">{r.symbol}</span>
          <p className="m-0 flex-1 text-[14px] text-fg-muted">{r.reason}</p>
          <time className="shrink-0 text-tiny text-fg-subtle tabular-nums">{formatDateTime(r.ts, tz)}</time>
        </li>
      ))}
    </ul>
  );
}

const VIEW_WORDS: Record<EquityView, string> = { hours: "each hour", days: "each trading day", months: "each month" };

export function LiveEquityChart({ points, market, capital, intraday }: { points: { ts: number; equity: number }[]; market: MarketCode; capital: number; intraday: boolean }) {
  const cur = MARKET_CURRENCY[market];
  const tz = MARKET_TZ[market];
  // hours, days or months (D-207): the history stays readable while the market is closed
  const [picked, setPicked] = useState<EquityView | null>(null);
  const view: EquityView = picked ?? (intraday ? defaultView(points, tz) : "days");
  const shown = useMemo(() => bucketEquity(points, view, tz), [points, view, tz]);
  const values = shown.map((p) => p.equity);
  const range = yRange(values.length ? values : [capital], capital);
  const spread = (range.max - range.min) / Math.max(1, Math.abs(capital));
  const label = useCallback(
    (v: number) => (view === "hours" ? formatDateTime(v, tz) : view === "days" ? formatDate(v, tz) : formatDate(v, tz).replace(/^\d+ /, "")),
    [view, tz],
  );
  const build: OptionBuilder = useCallback(
    (t) => ({
      animationDuration: 300,
      tooltip: { trigger: "axis", valueFormatter: (v: unknown) => formatMoney(Number(v), cur, 0) },
      grid: { top: 12, left: 8, right: 12, bottom: 8, containLabel: true },
      xAxis: { type: "time", axisLabel: { hideOverlap: true, formatter: (v: number) => (view === "days" ? label(v).replace(/ \d{4}$/, "") : label(v)) } },
      yAxis: { type: "value", min: range.min, max: range.max, axisLabel: { formatter: (v: number) => (spread < 0.05 ? formatMoney(v, cur, 0) : formatCompactMoney(v, cur)) } },
      series: [
        {
          name: "Money",
          type: "line",
          showSymbol: shown.length <= 40,
          symbolSize: 5,
          lineStyle: { width: 2, color: t.accent },
          itemStyle: { color: t.accent },
          areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: alpha(t.accent, 0.2) }, { offset: 1, color: alpha(t.accent, 0) }] } },
          markLine: { silent: true, symbol: "none", lineStyle: { color: t.fgSubtle, type: "dashed" }, label: { show: false }, data: [{ yAxis: capital }] },
          data: shown.map((p) => [p.ts, p.equity]),
        },
      ],
    }),
    [shown, cur, capital, view, label, range.min, range.max, spread],
  );
  const options = (intraday ? (["hours", "days", "months"] as const) : (["days", "months"] as const)).map((v) => ({ value: v, label: v[0]!.toUpperCase() + v.slice(1) }));
  const first = shown[0];
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented<EquityView> label="Show money by" value={view} onChange={setPicked} options={options} />
        {first && <span className="text-small text-fg-subtle">Since {formatDate(first.ts, tz)}</span>}
      </div>
      {points.length < 2 ? (
        <Skeleton className="h-[260px] w-full rounded-tile" />
      ) : shown.length < 2 ? (
        <p className="m-0 flex h-[260px] items-center justify-center rounded-tile bg-surface-2 text-small text-fg-muted">
          {view === "months" ? "Less than a month of history so far. Try Days." : "Only one trading day so far. Try Hours."}
        </p>
      ) : (
        <EChart
          build={build}
          height={260}
          caption={`The paper account's money at the end of ${VIEW_WORDS[view]}${view === "hours" ? ` (the last ${HOURS_DAYS} trading days)` : ""}. The dashed line is the starting money.`}
          ariaLabel="Paper account money over time"
        />
      )}
    </div>
  );
}

interface SessionCandles {
  bars: { ts: number; open: number; high: number; low: number; close: number; volume: number }[];
  markers: { ts: number; side: "buy" | "sell"; price: number; qty: number; reason: string }[];
}

export function SessionPriceChart({
  sessionId,
  instruments,
  market,
  timeframe,
  version,
}: {
  sessionId: number;
  instruments: { id: number; symbol: string }[];
  market: MarketCode;
  timeframe: Timeframe;
  version: number;
}) {
  const [picked, setPicked] = useState<number | null>(null);
  const instId = picked ?? instruments[0]?.id ?? null;
  const symbol = instruments.find((i) => i.id === instId)?.symbol ?? "";
  const data = useApi<SessionCandles>(instId !== null ? `/paper/sessions/${sessionId}/candles?instrument_id=${instId}&limit=${timeframe === "1d" ? 160 : 300}&v=${version}` : null);
  const candles: Candle[] = useMemo(
    () => (data.status === "ready" ? data.data.bars.map((b) => ({ time: b.ts / 1000, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume })) : []),
    [data],
  );
  const markers: TradeMarker[] = useMemo(
    () => (data.status === "ready" ? data.data.markers.map((m) => ({ time: m.ts / 1000, kind: m.side, text: m.side === "buy" ? "Buy" : "Sell" })) : []),
    [data],
  );
  return (
    <div className="flex flex-col gap-3">
      {instruments.length > 1 && (
        <Select aria-label="Stock to chart" value={instId ?? ""} onChange={(e) => setPicked(Number(e.target.value))} className="h-9 w-[200px] text-small">
          {instruments.map((i) => (
            <option key={i.id} value={i.id}>
              {i.symbol}
            </option>
          ))}
        </Select>
      )}
      {candles.length ? (
        <PriceChart
          key={`${instId}`}
          candles={candles}
          markers={markers}
          timeZone={MARKET_TZ[market]}
          intraday={timeframe !== "1d"}
          height={360}
          caption={`${symbol}'s latest candles with this session's buys and sells.`}
          ariaLabel={`Price chart of ${symbol} with paper trades`}
        />
      ) : data.status === "loading" || instId === null ? (
        <Skeleton className="h-[360px] w-full rounded-tile" />
      ) : (
        <p className="m-0 py-10 text-center text-small text-fg-muted">No prices for {symbol} yet.</p>
      )}
    </div>
  );
}

export function VsBacktestPanel({ sessionId, market, version }: { sessionId: number; market: MarketCode; version: number }) {
  const cmp = useApi<VsBacktest>(`/paper/sessions/${sessionId}/vs-backtest?v=${version}`);
  const cur = MARKET_CURRENCY[market];
  const tz = MARKET_TZ[market];
  const series = cmp.status === "ready" ? cmp.data.series : undefined;
  const build: OptionBuilder = useCallback(
    (t) => ({
      tooltip: { trigger: "axis", valueFormatter: (v: unknown) => Number(v).toFixed(2) },
      legend: { top: 0, right: 0, textStyle: { color: t.fgMuted } },
      grid: { top: 32, left: 8, right: 12, bottom: 8, containLabel: true },
      xAxis: { type: "time", axisLabel: { hideOverlap: true, formatter: (v: number) => formatDate(v, tz).replace(/ \d{4}$/, "") } },
      yAxis: { type: "value", scale: true },
      series: (series ?? []).map((s, i) => ({
        name: s.label,
        type: "line",
        showSymbol: false,
        lineStyle: { width: i === 0 ? 2 : 1.5, color: i === 0 ? t.accent : t.benchmark, type: i === 0 ? "solid" : "dashed" },
        itemStyle: { color: i === 0 ? t.accent : t.benchmark },
        data: s.points.map((p) => [p.ts, p.value]),
      })),
    }),
    [series, tz],
  );
  if (cmp.status === "loading") return <LoadingRows rows={3} />;
  if (cmp.status === "error") return <p className="m-0 text-small text-fg-muted">{cmp.error.message}</p>;
  const c = cmp.data;
  if (!c.ready || !c.live || !c.backtest) return <p className="m-0 text-small text-fg-muted">{c.message}</p>;
  const rows: [string, string, string][] = [
    ["Total return", `${c.live.total_return >= 0 ? "+" : ""}${c.live.total_return.toFixed(2)}%`, `${c.backtest.total_return >= 0 ? "+" : ""}${c.backtest.total_return.toFixed(2)}%`],
    ["Money now", formatMoney(c.live.final_equity, cur, 0), formatMoney(c.backtest.final_equity, cur, 0)],
    ["Completed trades", String(c.live.trades), String(c.backtest.trades)],
    ["Win rate", c.live.win_rate !== null ? `${Math.round(c.live.win_rate * 100)}%` : "—", c.backtest.win_rate !== null ? `${Math.round(c.backtest.win_rate * 100)}%` : "—"],
  ];
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_380px] items-start gap-6">
      <EChart build={build} height={260} caption="Both start at 100. If they match, paper trading did exactly what the backtest predicted." ariaLabel="Paper trading compared with a backtest of the same days" />
      <div className="flex flex-col gap-4">
        <table className="w-full border-collapse text-[14px]">
          <thead>
            <tr className="border-b border-hairline">
              <th className={cn(th, "px-0")} />
              <th className={cn(th, "text-right")}>Paper</th>
              <th className={cn(th, "pr-0 text-right")}>Backtest</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, a, b]) => (
              <tr key={label} className="border-b border-hairline last:border-0">
                <td className="py-2 text-fg-muted">{label}</td>
                <td className="py-2 text-right font-semibold tabular-nums">{a}</td>
                <td className="py-2 text-right tabular-nums">{b}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <ScrollBox size="xs">
          <ul className="m-0 flex list-disc flex-col gap-1.5 pl-5 text-small text-fg-muted">
            {(c.reasons ?? []).map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </ScrollBox>
        {(c.only_backtest?.length ?? 0) > 0 && (
          <p className="m-0 text-tiny text-fg-subtle">
            Only in the backtest: {c.only_backtest!.slice(0, 5).map((t) => `${t.symbol} ${formatDate(t.entry_ts, tz)}`).join(", ")}
          </p>
        )}
      </div>
    </div>
  );
}
