import { LineChart } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { PriceChart, type Candle, type TradeMarker } from "../../components/charts/PriceChart";
import { EmptyState, ErrorState } from "../../components/states";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { Select } from "../../components/ui/input";
import { Skeleton } from "../../components/ui/skeleton";
import { postJson, toEnvelope, type ErrorEnvelope, type Instrument } from "../../lib/api";
import { MARKET_TZ } from "../../lib/format";
import type { Definition } from "../../lib/strategy";
import { useApi } from "../../lib/useApi";

interface PreviewResponse {
  ok: boolean;
  bars: { ts: number; open: number; high: number; low: number; close: number; volume: number }[];
  signals: { ts: number; action: "buy" | "short" | "sell" | "cover"; reason: string; price: number }[];
  note?: string;
}

const PERIODS = [
  { days: 90, label: "3 months" },
  { days: 180, label: "6 months" },
  { days: 365, label: "1 year" },
  { days: 1095, label: "3 years" },
];

/** Where the rules would have fired recently on one stock (SPEC §5.2). */
export function PreviewPanel({ d, valid }: { d: Definition; valid: boolean }) {
  const insts = useApi<{ instruments: Instrument[] }>(`/instruments?market=${d.market}`);
  const [symbol, setSymbol] = useState<string | null>(null);
  const [days, setDays] = useState(d.timeframe === "1d" ? 365 : 30);
  const [state, setState] = useState<{ key: string; data?: PreviewResponse; error?: ErrorEnvelope } | null>(null);

  const candidates = useMemo(() => {
    const all = insts.status === "ready" ? insts.data.instruments.filter((i) => i.type !== "index") : [];
    if (d.universe.kind === "symbols") return all.filter((i) => d.universe.symbols.includes(i.symbol));
    return all;
  }, [insts, d.universe]);
  // Default to the market's best-known stock (most likely to have prices saved).
  const fallback = candidates.find((i) => i.symbol === (d.market === "IN" ? "RELIANCE" : "SPY")) ?? candidates[0];
  const chosen = candidates.find((i) => i.symbol === symbol) ?? fallback;
  const effectiveDays = d.timeframe === "1d" ? days : Math.min(days, 59);
  const body = useMemo(() => JSON.stringify({ definition: d, instrument_id: chosen?.id, days: effectiveDays }), [d, chosen, effectiveDays]);

  useEffect(() => {
    if (!valid || !chosen) return;
    let alive = true;
    const t = setTimeout(() => {
      postJson<PreviewResponse>("/strategies/preview", JSON.parse(body))
        .then((data) => alive && setState({ key: body, data }))
        .catch((err: unknown) => alive && setState({ key: body, error: toEnvelope(err) }));
    }, 600);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [body, valid, chosen]);

  const loading = valid && chosen && state?.key !== body;
  const data = state?.data;
  const candles: Candle[] = useMemo(() => (data ? data.bars.map((b) => ({ time: b.ts / 1000, ...b })) : []), [data]);
  const markers: TradeMarker[] = useMemo(
    () => (data ? data.signals.map((s) => ({ time: s.ts / 1000, kind: s.action === "buy" || s.action === "cover" ? "buy" : "sell", text: s.action === "short" ? "Short" : s.action === "cover" ? "Cover" : s.action === "buy" ? "Buy" : "Sell" })) : []),
    [data],
  );
  const entries = data?.signals.filter((s) => s.action === "buy" || s.action === "short").length ?? 0;

  return (
    <Card>
      <CardHeader className="flex-wrap">
        <CardTitle>Preview</CardTitle>
        <div className="flex gap-2">
          <Select aria-label="Preview stock" value={chosen?.symbol ?? ""} onChange={(e) => setSymbol(e.target.value)} className="h-9 w-[150px] text-small">
            {candidates.map((i) => (
              <option key={i.id} value={i.symbol}>
                {i.symbol}
              </option>
            ))}
          </Select>
          <Select aria-label="Preview period" value={days} onChange={(e) => setDays(Number(e.target.value))} className="h-9 w-[120px] text-small">
            {PERIODS.map((p) => (
              <option key={p.days} value={p.days}>
                {p.label}
              </option>
            ))}
          </Select>
        </div>
      </CardHeader>
      <CardBody>
        <div className="h-[300px]">
          {!valid ? (
            <EmptyState icon={LineChart} title="Fix the rules to see a preview" body="The chart shows where the rules would have bought and sold once there are no problems left." className="h-full" />
          ) : loading && !data ? (
            <Skeleton className="h-full w-full rounded-tile" />
          ) : state?.error ? (
            <ErrorState error={state.error} />
          ) : candles.length ? (
            <PriceChart
              candles={candles}
              markers={markers}
              timeZone={MARKET_TZ[d.market]}
              intraday={d.timeframe !== "1d"}
              height={260}
              caption={`${entries} trade${entries === 1 ? "" : "s"} would have started on ${chosen?.symbol}. Arrows mark entries and exits (filled at the next candle's open in a backtest).`}
              ariaLabel={`Preview chart of ${chosen?.symbol} with the strategy's signals`}
            />
          ) : (
            <EmptyState icon={LineChart} title="No prices to preview" body={data?.note ?? "Download prices for this stock on the Data screen."} className="h-full" />
          )}
        </div>
      </CardBody>
    </Card>
  );
}
