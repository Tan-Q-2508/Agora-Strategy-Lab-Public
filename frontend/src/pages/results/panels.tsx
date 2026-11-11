import { AlertTriangle, Info, ShieldCheck } from "lucide-react";
import { Change } from "../../components/ui/change";
import type { MarketCode, Metrics, Warning } from "../../lib/api";
import { formatMoney, formatPercent, MARKET_CURRENCY } from "../../lib/format";
import { cn } from "../../lib/utils";
import { ScrollBox } from "../../components/ui/scroll-box";

export function HonestyPanel({ warnings }: { warnings: Warning[] }) {
  const warns = warnings.filter((w) => w.level === "warn");
  return (
    <div className="flex flex-col gap-2">
      <p className={cn("m-0 flex items-center gap-2 text-small font-semibold", warns.length ? "text-warning" : "text-profit")}>
        {warns.length ? <AlertTriangle className="size-4" aria-hidden="true" /> : <ShieldCheck className="size-4" aria-hidden="true" />}
        {warns.length ? `${warns.length} thing${warns.length === 1 ? "" : "s"} to keep in mind` : "No warnings"}
      </p>
      <ScrollBox size="md">
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {[...warns, ...warnings.filter((w) => w.level !== "warn")].map((w) => (
            <li key={w.code} className={cn("flex gap-2.5 rounded-tile p-2.5 text-small", w.level === "warn" ? "bg-warning-soft text-warning-soft-fg" : "bg-surface-2 text-fg-muted")}>
              {w.level === "warn" ? <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> : <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />}
              <div>
                <p className="m-0 font-semibold">{w.title}</p>
                <p className="m-0">{w.text}</p>
              </div>
            </li>
          ))}
        </ul>
      </ScrollBox>
    </div>
  );
}

type Fmt = "pct" | "spct" | "ratio" | "money" | "smoney" | "count" | "days";

function fmt(v: unknown, kind: Fmt, market: MarketCode): string {
  if (v === null || v === undefined || (typeof v === "number" && !Number.isFinite(v))) return "—";
  const n = Number(v);
  const cur = MARKET_CURRENCY[market];
  switch (kind) {
    case "pct":
      return `${(n * 100).toFixed(1)}%`;
    case "spct":
      return formatPercent(n);
    case "ratio":
      return n.toFixed(2);
    case "money":
      return formatMoney(n, cur);
    case "smoney":
      return (n < 0 ? "−" : n > 0 ? "+" : "") + formatMoney(Math.abs(n), cur);
    case "count":
      return String(Math.round(n));
    case "days":
      return `${n.toFixed(n < 10 ? 1 : 0)} days`;
  }
}

const ROWS: [string, string, Fmt, string][] = [
  ["total_return", "Total return", "spct", "How much the money grew or shrank overall."],
  ["cagr", "Yearly return (CAGR)", "spct", "The average growth per year, compounded."],
  ["volatility", "Volatility (yearly)", "pct", "How much the daily returns swing, scaled to a year."],
  ["sharpe", "Sharpe ratio", "ratio", "Return per unit of ups and downs. Above 1 is good; above 2 is very good."],
  ["sortino", "Sortino ratio", "ratio", "Like Sharpe, but only counts the bad swings."],
  ["calmar", "Calmar ratio", "ratio", "Yearly return divided by the worst drop."],
  ["max_drawdown", "Worst drop (max drawdown)", "pct", "The biggest fall from a high point before recovering."],
  ["max_drawdown_days", "Longest time below a high", "days", "The longest stretch spent under a previous peak."],
  ["trades", "Completed trades", "count", "Trades still open at the end aren't counted here."],
  ["win_rate", "Win rate", "pct", "The share of trades that made money."],
  ["profit_factor", "Profit factor", "ratio", "Money made on winners ÷ money lost on losers. Above 1.5 is healthy."],
  ["expectancy", "Average per trade", "smoney", "What a typical trade made or lost after costs."],
  ["avg_win", "Average win", "smoney", ""],
  ["avg_loss", "Average loss", "smoney", ""],
  ["largest_win", "Largest win", "smoney", ""],
  ["largest_loss", "Largest loss", "smoney", ""],
  ["avg_bars_held", "Average candles held", "ratio", ""],
  ["avg_hold_days", "Average holding time", "days", ""],
  ["time_in_market", "Time in the market", "pct", "Share of the time at least one trade was open."],
  ["turnover", "Turnover (per year)", "ratio", "Value traded each year ÷ average account size."],
  ["charges_total", "Total charges", "money", "Brokerage, taxes and exchange fees paid."],
  ["charges_pct_of_gross_profit", "Charges as % of gross profit", "pct", "How much of the trading profit the charges ate."],
];

export function MetricsTable({ m, market }: { m: Metrics; market: MarketCode }) {
  return (
    <dl className="m-0 grid grid-cols-2 gap-x-8">
      {ROWS.map(([key, label, kind, tip]) => (
        <div key={key} className="flex items-baseline justify-between gap-3 border-b border-hairline py-2" title={tip || undefined}>
          <dt className="text-small text-fg-muted">{label}</dt>
          <dd className="m-0 text-[14px] font-semibold tabular-nums">{fmt(m[key], kind, market)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PerSymbolTable({ rows, market }: { rows: NonNullable<Metrics["per_symbol"]>; market: MarketCode }) {
  const cur = MARKET_CURRENCY[market];
  return (
    <div className="max-h-[360px] overflow-y-auto">
      <table className="w-full border-collapse text-[14px]">
        <thead className="sticky top-0 bg-surface text-left text-small text-fg-muted">
          <tr className="border-b border-border">
            <th className="py-2 pr-3 pl-5 font-medium">Stock</th>
            <th className="px-3 py-2 text-right font-medium">Trades</th>
            <th className="px-3 py-2 text-right font-medium">Win rate</th>
            <th className="px-3 py-2 text-right font-medium">Charges</th>
            <th className="py-2 pr-5 pl-3 text-right font-medium">Net P&L</th>
          </tr>
        </thead>
        <tbody>
          {[...rows]
            .sort((a, b) => b.net_pnl - a.net_pnl)
            .map((r) => (
              <tr key={r.symbol} className="border-b border-hairline last:border-0">
                <td className="py-2 pr-3 pl-5 font-semibold">{r.symbol}</td>
                <td className="px-3 py-2 text-right tabular-nums">{r.trades}</td>
                <td className="px-3 py-2 text-right tabular-nums">{r.win_rate === null ? "—" : `${Math.round(r.win_rate * 100)}%`}</td>
                <td className="px-3 py-2 text-right tabular-nums text-fg-muted">{formatMoney(r.charges, cur)}</td>
                <td className="py-2 pr-5 pl-3 text-right tabular-nums">
                  <Change value={r.net_pnl} text={formatMoney(Math.abs(r.net_pnl), cur)} />
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}
