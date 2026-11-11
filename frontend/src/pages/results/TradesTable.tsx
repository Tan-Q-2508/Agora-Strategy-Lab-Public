import { ArrowDown, ArrowUp, Download, Sparkles } from "lucide-react";
import { useState } from "react";
import { Button } from "../../components/ui/button";
import { Change } from "../../components/ui/change";
import { Select } from "../../components/ui/input";
import { LoadingRows } from "../../components/states";
import { qs, type MarketCode, type TradeRow } from "../../lib/api";
import { formatDateTime, formatMoney, formatPercent, MARKET_CURRENCY, MARKET_TZ } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { cn } from "../../lib/utils";

const EXIT_WORDS: Record<string, string> = {
  signal: "Exit rule",
  stop: "Stop-loss",
  target: "Take-profit",
  trailing: "Trailing stop",
  time: "Time exit",
  square_off: "Square-off",
  end_of_test: "Still open",
};

type SortKey = "entry_ts" | "net_pnl" | "return_pct" | "bars_held" | "charges";

export function TradesTable({ runId, market, symbols, onExplain }: { runId: number; market: MarketCode; symbols: string[]; onExplain?: (t: TradeRow) => void }) {
  const [sort, setSort] = useState<{ key: SortKey; order: "asc" | "desc" }>({ key: "entry_ts", order: "desc" });
  const [symbol, setSymbol] = useState("");
  const [limit, setLimit] = useState(50);
  const s = useApi<{ trades: TradeRow[]; total: number; next_cursor: number | null }>(
    `/backtests/${runId}/trades${qs({ sort: sort.key, order: sort.order, symbol: symbol || undefined, limit })}`,
  );
  const cur = MARKET_CURRENCY[market];
  const tz = MARKET_TZ[market];

  function header(key: SortKey, label: string, right = false) {
    const active = sort.key === key;
    return (
      <th className={cn("px-3 py-2.5 font-medium", right && "text-right")} aria-sort={active ? (sort.order === "asc" ? "ascending" : "descending") : "none"}>
        <button
          type="button"
          onClick={() => setSort({ key, order: active && sort.order === "desc" ? "asc" : "desc" })}
          className={cn("inline-flex items-center gap-1 hover:text-fg", active && "text-fg")}
        >
          {label}
          {active && (sort.order === "asc" ? <ArrowUp className="size-3" aria-hidden="true" /> : <ArrowDown className="size-3" aria-hidden="true" />)}
        </button>
      </th>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3 px-5">
        <div className="flex items-center gap-2">
          {symbols.length > 1 && (
            <Select aria-label="Filter by stock" value={symbol} onChange={(e) => setSymbol(e.target.value)} className="h-9 w-[180px] text-small">
              <option value="">All stocks</option>
              {symbols.map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </Select>
          )}
          {s.status === "ready" && <span className="text-small text-fg-muted">{s.data.total} trades</span>}
        </div>
        <Button size="sm" variant="ghost" asChild>
          <a href={`/api/backtests/${runId}/trades.csv`} download>
            <Download aria-hidden="true" />
            Export CSV
          </a>
        </Button>
      </div>
      {s.status !== "ready" ? (
        <LoadingRows rows={5} className="px-5" />
      ) : (
        <div className="max-h-[480px] overflow-y-auto">
          <table className="w-full border-collapse text-[14px]">
            <thead className="sticky top-0 z-10 bg-surface text-left text-small text-fg-muted">
              <tr className="border-b border-border">
                <th className="py-2.5 pr-3 pl-5 font-medium">Stock</th>
                {header("entry_ts", "Entry")}
                <th className="px-3 py-2.5 font-medium">Exit</th>
                <th className="px-3 py-2.5 text-right font-medium">Shares</th>
                {header("bars_held", "Candles", true)}
                {header("charges", "Charges", true)}
                {header("net_pnl", "Net P&L", true)}
                {header("return_pct", "Return", true)}
                <th className="py-2.5 pr-5 pl-3 font-medium">Why it ended</th>
                {onExplain && <th className="w-10 pr-4" aria-label="Explain" />}
              </tr>
            </thead>
            <tbody>
              {s.data.trades.map((t) => (
                <tr key={t.id} className="border-b border-hairline last:border-0 hover:bg-surface-2/60">
                  <td className="py-2 pr-3 pl-5">
                    <span className="font-semibold">{t.symbol}</span>
                    <span className={cn("ml-1.5 text-tiny", t.side === "short" ? "text-loss" : "text-fg-subtle")}>{t.side === "short" ? "short" : "long"}</span>
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    <div>{formatMoney(t.entry_price, cur)}</div>
                    <div className="text-tiny text-fg-subtle">{formatDateTime(t.entry_ts, tz)}</div>
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    <div>{t.exit_price !== null ? formatMoney(t.exit_price, cur) : "—"}</div>
                    <div className="text-tiny text-fg-subtle">{t.exit_ts ? formatDateTime(t.exit_ts, tz) : ""}</div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{t.qty}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{t.bars_held}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-fg-muted">{formatMoney(t.charges, cur)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    <Change value={t.net_pnl} text={formatMoney(Math.abs(t.net_pnl), cur)} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    <Change value={t.return_pct} text={formatPercent(t.return_pct / 100)} />
                  </td>
                  <td className="py-2 pr-5 pl-3 text-small text-fg-muted">{EXIT_WORDS[t.exit_reason ?? ""] ?? t.exit_reason}</td>
                  {onExplain && (
                    <td className="pr-4">
                      {t.exit_reason !== "end_of_test" && (
                        <Button size="icon-sm" variant="ghost" aria-label={`Explain the ${t.symbol} trade with AI`} onClick={() => onExplain(t)}>
                          <Sparkles aria-hidden="true" />
                        </Button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {s.data.next_cursor !== null && (
            <div className="flex justify-center p-3">
              <Button size="sm" variant="ghost" onClick={() => setLimit((l) => l + 100)}>
                Show more trades
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
