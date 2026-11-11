import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { Tooltip } from "../../components/ui/tooltip";
import type { MarketCode, PaperStats } from "../../lib/api";
import { formatDate, formatSignedMoney, MARKET_CURRENCY, MARKET_TZ } from "../../lib/format";
import { cn } from "../../lib/utils";
import { EXIT_WORDS } from "./exitWords";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`);
const tone = (v: number | null | undefined) => (v === null || v === undefined || v === 0 ? "" : v > 0 ? "text-profit" : "text-loss");

function Cell({ label, tip, value, cls }: { label: string; tip: string; value: string; cls?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-tile bg-surface-2 px-3 py-2.5">
      <Tooltip content={tip}>
        <span className="w-fit cursor-help text-small text-fg-muted">{label}</span>
      </Tooltip>
      <span className={cn("text-body font-semibold tabular-nums", cls)}>{value}</span>
    </div>
  );
}

/**
 * The strategy's whole record (D-209): every closed trade, and for a Kairos desk every run it
 * carried its money on from, not only today's run.
 */
export function PerformanceCard({ stats, market, runs, desk }: { stats: PaperStats | undefined; market: MarketCode; runs: number; desk: boolean }) {
  const cur = MARKET_CURRENCY[market];
  const tz = MARKET_TZ[market];
  const money = (v: number | null | undefined) => (v === null || v === undefined ? "—" : formatSignedMoney(v, cur, 0));
  if (!stats || stats.trades === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Performance</CardTitle>
        </CardHeader>
        <CardBody>
          <p className="m-0 text-small text-fg-muted">
            No completed trades yet. The numbers appear after the first trade is opened and closed{desk ? "; trades still open are under Open trades" : ""}.
          </p>
        </CardBody>
      </Card>
    );
  }
  const exits = Object.entries(stats.exits ?? {});
  return (
    <Card>
      <CardHeader className="flex flex-wrap items-baseline justify-between gap-2">
        <CardTitle>Performance</CardTitle>
        <span className="text-small text-fg-subtle">
          {stats.trades} completed trade{stats.trades === 1 ? "" : "s"}
          {stats.first_ts ? `, ${formatDate(stats.first_ts, tz)} to ${formatDate(stats.last_ts ?? stats.first_ts, tz)}` : ""}
          {runs > 1 ? ` · ${runs} runs of this desk` : ""}
        </span>
      </CardHeader>
      <CardBody className="flex flex-col gap-4">
        <div className="grid grid-cols-4 gap-3">
          <Cell label="Win rate" tip="Share of completed trades that made money after charges." value={`${(stats.win_rate ?? 0).toFixed(1)}% (${stats.wins} of ${stats.trades})`} />
          <Cell label="Net profit" tip="All completed trades together, after brokerage, taxes and fees." value={money(stats.net_pnl)} cls={tone(stats.net_pnl)} />
          <Cell label="Profit factor" tip="Money won ÷ money lost. Above 1 means the wins paid for the losses." value={stats.profit_factor != null ? stats.profit_factor.toFixed(2) : "—"} cls={stats.profit_factor != null ? (stats.profit_factor >= 1 ? "text-profit" : "text-loss") : ""} />
          <Cell label="Average trade" tip="Net profit ÷ number of trades, and the average % per trade." value={`${money(stats.avg_pnl)} (${pct(stats.avg_return_pct)})`} cls={tone(stats.avg_pnl)} />
          <Cell label="Biggest win" tip="The single best trade, after charges." value={stats.biggest_win ? `${money(stats.biggest_win)} (${pct(stats.biggest_win_pct)})` : "—"} cls="text-profit" />
          <Cell label="Biggest loss" tip="The single worst trade, after charges." value={stats.biggest_loss ? `${money(stats.biggest_loss)} (${pct(stats.biggest_loss_pct)})` : "—"} cls="text-loss" />
          <Cell label="Average win" tip="What a winning trade made on average." value={money(stats.avg_win)} cls="text-profit" />
          <Cell label="Average loss" tip="What a losing trade lost on average." value={money(stats.avg_loss)} cls="text-loss" />
          <Cell label="Best 10% of trades" tip="The top tenth of trades each made at least this much." value={pct(stats.top10_return_pct)} cls={tone(stats.top10_return_pct)} />
          <Cell label="Middle trade" tip="Half the trades did better than this, half worse (the median)." value={pct(stats.median_return_pct)} cls={tone(stats.median_return_pct)} />
          <Cell label="Worst 10% of trades" tip="The bottom tenth of trades each lost at least this much." value={pct(stats.bottom10_return_pct)} cls={tone(stats.bottom10_return_pct)} />
          <Cell label="Charges paid" tip="Brokerage, STT, stamp duty, GST and exchange fees on these trades." value={money(-(stats.charges ?? 0)).replace(/^[+]/, "")} />
          <Cell label="Longest winning run" tip="Most wins in a row." value={`${stats.best_streak ?? 0}`} />
          <Cell label="Longest losing run" tip="Most losses in a row." value={`${stats.worst_streak ?? 0}`} />
          <Cell label="Candles held" tip="How long a trade stayed open on average, in the strategy's candles." value={(stats.avg_bars_held ?? 0).toFixed(1)} />
          <Cell label="Bought / sold short" tip="Trades that bought first, and trades that sold short first." value={`${stats.longs ?? 0} / ${stats.shorts ?? 0}`} />
        </div>
        {exits.length > 0 && (
          <div className="flex flex-col gap-2">
            <span className="text-small text-fg-muted">How trades ended</span>
            <div className="flex h-2.5 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
              {exits.map(([k, n], i) => (
                <div key={k} style={{ width: `${(100 * n) / stats.trades}%`, opacity: 1 - i * 0.13 }} className="bg-accent" />
              ))}
            </div>
            <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-small text-fg-muted">
              {exits.map(([k, n]) => (
                <li key={k}>
                  {EXIT_WORDS[k] ?? k}: <span className="font-semibold text-fg tabular-nums">{n}</span> ({((100 * n) / stats.trades).toFixed(0)}%)
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
