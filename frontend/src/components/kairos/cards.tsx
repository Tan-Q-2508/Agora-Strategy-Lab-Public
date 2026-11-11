import { ArrowUpRight, ExternalLink } from "lucide-react";
import { Link } from "react-router";
import { formatAgo, formatPercent } from "../../lib/format";
import type { Card } from "../../lib/kairosChat";
import { cn } from "../../lib/utils";
import { Pill } from "../ui/pill";
import { KairosMark } from "./KairosMark";
import { ScrollBox } from "../ui/scroll-box";

type Bias = "bullish" | "bearish" | "neutral";
const BIAS_TONE: Record<Bias, "profit" | "loss" | "neutral"> = { bullish: "profit", bearish: "loss", neutral: "neutral" };
const TONE_DOT: Record<string, string> = { positive: "bg-profit", negative: "bg-loss", neutral: "bg-neutral-dot" };

function money(v: number, market: string): string {
  const sym = market === "IN" ? "₹" : "$";
  return `${v < 0 ? "−" : ""}${sym}${Math.abs(v).toLocaleString(market === "IN" ? "en-IN" : "en-US", { maximumFractionDigits: 2 })}`;
}

function pct(v: unknown, digits = 1): string {
  return typeof v === "number" ? formatPercent(v, digits) : "—";
}

/** A size, not a change: no plus sign ("12.4%"). */
function plain(v: unknown, digits = 1): string {
  return typeof v === "number" ? `${(Math.abs(v) * 100).toFixed(digits)}%` : "—";
}

function Open({ to, label }: { to: string; label: string }) {
  return (
    <Link to={to} className="inline-flex items-center gap-1 text-small font-semibold text-accent-soft-fg hover:underline">
      {label}
      <ArrowUpRight className="size-3.5" aria-hidden="true" />
    </Link>
  );
}

function Shell({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("flex flex-col gap-2 rounded-tile border border-hairline bg-surface-2/60 p-3", className)}>{children}</div>;
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "profit" | "loss" }) {
  return (
    <div className="rounded-control bg-surface px-2 py-1.5">
      <p className="m-0 text-tiny text-fg-subtle">{label}</p>
      <p className={cn("m-0 text-small font-semibold tabular-nums", tone === "profit" && "text-profit", tone === "loss" && "text-loss")}>{value}</p>
    </div>
  );
}

const signTone = (v: unknown): "profit" | "loss" | undefined => (typeof v === "number" ? (v > 0 ? "profit" : v < 0 ? "loss" : undefined) : undefined);

function ChartCard({ c }: { c: Card }) {
  const bias = (c.bias as Bias) ?? "neutral";
  return (
    <Shell>
      <div className="flex items-center justify-between gap-2">
        <span className="text-small font-semibold">
          {String(c.symbol)} <span className="font-normal text-fg-subtle">· {String(c.timeframe)}</span>
        </span>
        <Pill tone={BIAS_TONE[bias]} className="h-6 px-2 text-tiny">
          {bias} · {Number(c.score) > 0 ? "+" : ""}
          {Number(c.score).toFixed(0)}
        </Pill>
      </div>
      <p className="m-0 text-small text-fg">{String(c.headline)}</p>
      {Array.isArray(c.lines) && (
        <ul className="m-0 flex list-disc flex-col gap-1 pl-4 text-small text-fg-muted">
          {(c.lines as string[]).map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}
      {typeof c.forecast === "string" && <p className="m-0 text-small text-fg-muted">{c.forecast}</p>}
      {typeof c.idea === "string" && <p className="m-0 rounded-control bg-accent-soft/60 px-2 py-1.5 text-small text-fg">{c.idea}</p>}
      {c.link && <Open to={c.link} label="Open the chart with Kairos's drawings" />}
    </Shell>
  );
}

function ForecastCard({ c }: { c: Card }) {
  return (
    <Shell>
      <p className="m-0 text-small text-fg">{String(c.text)}</p>
      <p className="m-0 text-tiny text-fg-muted">{String(c.verdict)}</p>
      {c.link && <Open to={c.link} label="See the range on the chart" />}
    </Shell>
  );
}

interface ScanRow {
  symbol: string;
  market: string;
  score: number;
  bias: Bias;
  headline: string;
  rsi: number;
  link: string;
}

function ScanCard({ c }: { c: Card }) {
  const rows = (c.rows as ScanRow[]) ?? [];
  return (
    <Shell className="p-0">
      <ScrollBox size="md">
        <table className="w-full border-collapse text-small">
          <thead>
            <tr className="text-left text-tiny text-fg-subtle">
              <th className="px-3 pt-2 pb-1 font-normal">Stock</th>
              <th className="px-2 pt-2 pb-1 font-normal">Score</th>
              <th className="px-3 pt-2 pb-1 font-normal">Reading</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.market}-${r.symbol}`} className="border-t border-hairline align-top">
                <td className="px-3 py-1.5 font-semibold">
                  <Link to={r.link} className="hover:underline">
                    {r.symbol}
                  </Link>
                </td>
                <td className={cn("px-2 py-1.5 tabular-nums", r.bias === "bullish" ? "text-profit" : r.bias === "bearish" ? "text-loss" : "text-fg-muted")}>
                  {r.score > 0 ? "+" : ""}
                  {r.score.toFixed(0)}
                </td>
                <td className="px-3 py-1.5 text-fg-muted">{r.headline}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollBox>
      {Array.isArray(c.missing) && (c.missing as string[]).length > 0 && (
        <p className="m-0 px-3 pb-2 text-tiny text-fg-subtle">No saved prices yet for {(c.missing as string[]).length} stocks (download them on the Data screen).</p>
      )}
    </Shell>
  );
}

interface NewsRow {
  title: string;
  link: string;
  tone: string;
  publisher: string;
  published_at: number;
}

function NewsList({ items }: { items: NewsRow[] }) {
  return (
    <ScrollBox size="md">
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
        {items.map((i) => (
          <li key={i.link}>
            <a href={i.link} target="_blank" rel="noopener noreferrer" className="group flex gap-2">
              <span aria-hidden="true" className={cn("mt-1.5 size-2 shrink-0 rounded-full", TONE_DOT[i.tone] ?? "bg-neutral-dot")} />
              <span className="min-w-0">
                <span className="block text-small text-fg group-hover:underline">{i.title}</span>
                <span className="text-tiny text-fg-subtle">
                  {i.publisher || "News"} · {formatAgo(i.published_at)}
                </span>
              </span>
              <ExternalLink className="mt-1 size-3 shrink-0 text-fg-subtle opacity-0 group-hover:opacity-100" aria-hidden="true" />
            </a>
          </li>
        ))}
      </ul>
    </ScrollBox>
  );
}

function NewsCard({ c }: { c: Card }) {
  const items = (c.items as NewsRow[]) ?? [];
  return <Shell>{items.length ? <NewsList items={items.slice(0, 8)} /> : <p className="m-0 text-small text-fg-muted">No recent headlines.</p>}</Shell>;
}

function BacktestCard({ c }: { c: Card }) {
  const warnings = (c.warnings as string[]) ?? [];
  return (
    <Shell>
      <div className="flex items-center justify-between gap-2">
        <span className="text-small font-semibold">
          {String(c.strategy)} <span className="font-normal text-fg-subtle">· #{String(c.id)}</span>
        </span>
        {c.mode === "walk_forward" && <Pill className="h-6 px-2 text-tiny">walk-forward</Pill>}
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        <Metric label="Return" value={pct(c.total_return)} tone={signTone(c.total_return)} />
        <Metric label="CAGR" value={pct(c.cagr)} tone={signTone(c.cagr)} />
        <Metric label="Worst drop" value={plain(c.max_drawdown)} tone="loss" />
        <Metric label="Sharpe" value={typeof c.sharpe === "number" ? c.sharpe.toFixed(2) : "—"} />
        <Metric label="Trades" value={String(c.trades ?? "—")} />
        <Metric label="Win rate" value={plain(c.win_rate, 0)} />
      </div>
      {typeof c.vs_benchmark === "number" && (
        <p className="m-0 text-small text-fg-muted">
          {c.vs_benchmark >= 0 ? "Beat" : "Trailed"} buying and holding the index by {plain(c.vs_benchmark)}.
        </p>
      )}
      {warnings.length > 0 && <p className="m-0 text-tiny text-warning">{warnings.join(" · ")}</p>}
      {c.link && <Open to={c.link} label="Open the full results" />}
    </Shell>
  );
}

function StrategyCard({ c }: { c: Card }) {
  const symbols = (c.symbols as string[]) ?? [];
  return (
    <Shell>
      <span className="text-small font-semibold">{String(c.name)}</span>
      <span className="text-tiny text-fg-subtle">
        {String(c.market)} · {String(c.timeframe)} · {symbols.length ? symbols.join(", ") : "whole market"}
      </span>
      {typeof c.description === "string" && <p className="m-0 text-small text-fg-muted">{c.description}</p>}
      {c.link && <Open to={c.link} label="Open in the strategy builder" />}
    </Shell>
  );
}

function PaperCard({ c }: { c: Card }) {
  const symbols = (c.symbols as string[]) ?? [];
  return (
    <Shell>
      <span className="text-small font-semibold">
        Paper session #{String(c.id)} <span className="font-normal text-fg-subtle">· {String(c.strategy)}</span>
      </span>
      <span className="text-tiny text-fg-subtle">
        {symbols.join(", ") || "whole market"} · {money(Number(c.capital), String(c.market))} paper money{c.mode === "replay" ? " · practice replay" : ""}
      </span>
      {c.link && <Open to={c.link} label="Watch it live" />}
    </Shell>
  );
}

function DeskCard({ c }: { c: Card }) {
  const symbols = (c.symbols as string[]) ?? [];
  const ret = typeof c.total_return === "number" ? c.total_return : null;
  return (
    <Shell>
      <span className="flex items-center gap-1.5 text-small font-semibold">
        <KairosMark className="size-4" />
        Kairos desk #{String(c.id)}
        {ret !== null && <span className={ret >= 0 ? "text-profit" : "text-loss"}>{`${ret >= 0 ? "+" : "−"}${Math.abs(ret).toFixed(2)}%`}</span>}
      </span>
      <span className="text-tiny text-fg-subtle">
        Watching {symbols.join(", ")} · {money(Number(c.capital), String(c.market))} paper money{c.mode === "replay" ? " · practice replay" : ""}
      </span>
      {c.link && <Open to={c.link} label="Open the desk" />}
    </Shell>
  );
}

function ListCard({ c }: { c: Card }) {
  const items = (c.items as { label: string; sub?: string; link?: string }[]) ?? [];
  return (
    <Shell>
      {typeof c.title === "string" && <span className="text-tiny font-semibold tracking-wide text-fg-subtle uppercase">{c.title}</span>}
      <ScrollBox size="md">
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {items.map((i) => (
            <li key={`${i.label}-${i.sub ?? ""}`} className="text-small">
              {i.link ? (
                <Link to={i.link} className="font-semibold hover:underline">
                  {i.label}
                </Link>
              ) : (
                <span className={i.sub ? "font-semibold" : "text-fg"}>{i.label}</span>
              )}
              {i.sub && <span className="text-fg-subtle"> · {i.sub}</span>}
            </li>
          ))}
        </ul>
      </ScrollBox>
      {typeof c.link === "string" && <Open to={c.link} label="Open" />}
    </Shell>
  );
}

function OverviewCard({ c }: { c: Card }) {
  const index = c.index as { symbol: string; headline: string; score: number; change_pct: number; link: string } | undefined;
  const gainers = (c.gainers as [string, number][]) ?? [];
  const losers = (c.losers as [string, number][]) ?? [];
  return (
    <Shell>
      {index && (
        <div className="flex items-center justify-between gap-2">
          <Link to={index.link} className="text-small font-semibold hover:underline">
            {index.symbol}
          </Link>
          <span className={cn("text-small tabular-nums", index.change_pct >= 0 ? "text-profit" : "text-loss")}>
            {index.change_pct >= 0 ? "+" : ""}
            {index.change_pct.toFixed(2)}% today
          </span>
        </div>
      )}
      {index && <p className="m-0 text-small text-fg-muted">{index.headline}</p>}
      {typeof c.stocks === "number" && (
        <p className="m-0 text-small text-fg-muted">
          {String(c.advancers)} of {String(c.stocks)} rose · {String(c.above_50dma)} above their 50-day average
        </p>
      )}
      {gainers.length > 0 && (
        <div className="grid grid-cols-2 gap-2 text-small">
          <div>
            <p className="m-0 text-tiny text-fg-subtle">Gainers</p>
            {gainers.map(([s, m]) => (
              <p key={s} className="m-0 tabular-nums text-profit">
                {s} {formatPercent(m, 1)}
              </p>
            ))}
          </div>
          <div>
            <p className="m-0 text-tiny text-fg-subtle">Losers</p>
            {losers.map(([s, m]) => (
              <p key={s} className="m-0 tabular-nums text-loss">
                {s} {formatPercent(m, 1)}
              </p>
            ))}
          </div>
        </div>
      )}
      {Array.isArray(c.news) && <NewsList items={c.news as NewsRow[]} />}
    </Shell>
  );
}

/** Profit or loss at expiry (solid) and today (dashed) across prices: green above zero, red below. */
function Payoff({ grid, expiry, today, spot, breakevens }: { grid: number[]; expiry: number[]; today: number[]; spot: number; breakevens: number[] }) {
  const W = 280;
  const H = 96;
  // Show the useful middle: ±25% around the price.
  const keep = grid.map((x, i) => [x, i] as const).filter(([x]) => x >= spot * 0.75 && x <= spot * 1.25);
  if (keep.length < 3) return null;
  const xs = keep.map(([x]) => x);
  const ys = keep.flatMap(([, i]) => [expiry[i] ?? 0, today[i] ?? 0]);
  const lo = Math.min(...ys, 0);
  const hi = Math.max(...ys, 0);
  const x0 = xs[0] ?? 0;
  const x1 = xs.at(-1) ?? 1;
  const px = (x: number) => ((x - x0) / (x1 - x0 || 1)) * W;
  const py = (y: number) => H - 4 - ((y - lo) / (hi - lo || 1)) * (H - 8);
  const line = (vals: number[]) => keep.map(([x, i], k) => `${k ? "L" : "M"}${px(x).toFixed(1)},${py(vals[i] ?? 0).toFixed(1)}`).join(" ");
  const zero = py(0);
  const area = `${line(expiry)} L${W},${zero} L0,${zero} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-24 w-full" role="img" aria-label="Profit or loss at expiry across prices">
      <defs>
        <clipPath id="above">
          <rect x="0" y="0" width={W} height={zero} />
        </clipPath>
        <clipPath id="below">
          <rect x="0" y={zero} width={W} height={H - zero} />
        </clipPath>
      </defs>
      <path d={area} clipPath="url(#above)" className="fill-profit/20" />
      <path d={area} clipPath="url(#below)" className="fill-loss/20" />
      <line x1="0" x2={W} y1={zero} y2={zero} className="stroke-border" strokeWidth="1" />
      <line x1={px(spot)} x2={px(spot)} y1="0" y2={H} className="stroke-fg-subtle" strokeDasharray="2 3" strokeWidth="1" />
      {breakevens.filter((b) => b >= x0 && b <= x1).map((b) => (
        <circle key={b} cx={px(b)} cy={zero} r="2.5" className="fill-fg" />
      ))}
      <path d={line(today)} fill="none" className="stroke-info" strokeDasharray="4 3" strokeWidth="1.25" />
      <path d={line(expiry)} fill="none" className="stroke-fg" strokeWidth="1.75" />
    </svg>
  );
}

function OptionsCard({ c }: { c: Card }) {
  const m = String(c.market);
  const legs = (c.legs as { label: string; premium: number | null }[]) ?? [];
  const show = (v: unknown) => (typeof v === "number" ? money(v, m) : "Unlimited");
  const net = Number(c.net ?? 0);
  return (
    <Shell>
      <div className="flex items-center justify-between gap-2">
        <span className="text-small font-semibold">{String(c.title)}</span>
        <Pill tone="info" className="h-6 px-2 text-tiny">
          {Math.round(Number(c.pop) * 100)}% chance of profit
        </Pill>
      </div>
      <ScrollBox size="sm">
        <ul className="m-0 flex list-none flex-col gap-0.5 p-0 text-small text-fg-muted">
          {legs.map((l) => (
            <li key={l.label}>
              {l.label}
              {l.premium !== null && <span className="tabular-nums text-fg-subtle"> · ≈{l.premium.toFixed(2)}</span>}
            </li>
          ))}
        </ul>
      </ScrollBox>
      <Payoff grid={c.grid as number[]} expiry={c.at_expiry as number[]} today={c.today as number[]} spot={Number(c.spot)} breakevens={(c.breakevens as number[]) ?? []} />
      <div className="grid grid-cols-3 gap-2">
        <Metric label={net >= 0 ? "Costs" : "Collects"} value={money(Math.abs(net), m)} />
        <Metric label="Most profit" value={show(c.max_profit)} tone="profit" />
        <Metric label="Most loss" value={show(c.max_loss)} tone="loss" />
      </div>
      <p className="m-0 text-tiny text-fg-subtle">
        Break-even {((c.breakevens as number[]) ?? []).map((b) => b.toLocaleString()).join(" and ") || "—"} · {String(c.days)} days · volatility {Math.round(Number(c.vol) * 100)}% · {Number(c.lot) > 1 ? `per lot of ${String(c.lot)}` : "per share"}. Premiums are model estimates.
      </p>
    </Shell>
  );
}

/** The result card for a step, by its type. */
export function ResultCard({ card }: { card: Card }) {
  switch (card.type) {
    case "chart":
      return <ChartCard c={card} />;
    case "forecast":
      return <ForecastCard c={card} />;
    case "scan":
      return <ScanCard c={card} />;
    case "news":
      return <NewsCard c={card} />;
    case "backtest":
      return <BacktestCard c={card} />;
    case "strategy":
      return <StrategyCard c={card} />;
    case "paper":
      return <PaperCard c={card} />;
    case "desk":
      return <DeskCard c={card} />;
    case "list":
      return <ListCard c={card} />;
    case "options":
      return <OptionsCard c={card} />;
    case "overview":
      return <OverviewCard c={card} />;
    case "link":
      return card.link ? <Open to={card.link} label={String(card.label ?? "Open")} /> : null;
    default:
      return null;
  }
}
