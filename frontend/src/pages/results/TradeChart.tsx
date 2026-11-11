import { useMemo, useState } from "react";
import { PriceChart, type Candle, type TradeMarker } from "../../components/charts/PriceChart";
import { Select } from "../../components/ui/input";
import { Skeleton } from "../../components/ui/skeleton";
import { qs, type CandlesResponse, type Instrument, type MarketCode, type Timeframe, type TradeRow } from "../../lib/api";
import { MARKET_TZ } from "../../lib/format";
import { useApi } from "../../lib/useApi";

/** One stock's prices (as traded, not split-adjusted, so fills line up) with its trades. */
export function TradeChart({ runId, market, timeframe, symbols, start, end }: { runId: number; market: MarketCode; timeframe: Timeframe; symbols: string[]; start: number; end: number }) {
  const [symbol, setSymbol] = useState(symbols[0] ?? "");
  const insts = useApi<{ instruments: Instrument[] }>(`/instruments?market=${market}`);
  const inst = insts.status === "ready" ? insts.data.instruments.find((i) => i.symbol === symbol) : undefined;
  const candles = useApi<CandlesResponse>(inst ? `/candles${qs({ instrument_id: inst.id, timeframe, start, end, adjusted: false, limit: 50000 })}` : null);
  const trades = useApi<{ trades: TradeRow[] }>(symbol ? `/backtests/${runId}/trades${qs({ symbol, limit: 5000 })}` : null);

  const data: Candle[] = useMemo(
    () => (candles.status === "ready" ? candles.data.bars.map((b) => ({ time: b.ts / 1000, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume })) : []),
    [candles],
  );
  const markers: TradeMarker[] = useMemo(() => {
    if (trades.status !== "ready") return [];
    const out: TradeMarker[] = [];
    for (const t of trades.data.trades) {
      out.push({ time: t.entry_ts / 1000, kind: t.side === "long" ? "buy" : "sell", text: t.side === "long" ? "Buy" : "Short" });
      if (t.exit_ts && t.exit_reason !== "end_of_test") out.push({ time: t.exit_ts / 1000, kind: t.side === "long" ? "sell" : "buy", text: t.side === "long" ? "Sell" : "Cover" });
    }
    return out;
  }, [trades]);

  return (
    <div className="flex flex-col gap-3">
      {symbols.length > 1 && (
        <Select aria-label="Stock to chart" value={symbol} onChange={(e) => setSymbol(e.target.value)} className="h-9 w-[200px] text-small">
          {symbols.map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </Select>
      )}
      {data.length ? (
        <PriceChart
          key={symbol}
          candles={data}
          markers={markers}
          timeZone={MARKET_TZ[market]}
          intraday={timeframe !== "1d"}
          height={380}
          caption={`${symbol} prices as traded, with every entry and exit. Arrows sit on the candle where the order filled.`}
          ariaLabel={`Price chart of ${symbol} with trade markers`}
        />
      ) : (
        <Skeleton className="h-[380px] w-full rounded-tile" />
      )}
    </div>
  );
}
