import { LineChart, Plus, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { PriceChart, type Candle, type Overlay } from "../components/charts/PriceChart";
import { readChartTokens } from "../components/charts/tokens";
import { KairosMark } from "../components/kairos/KairosMark";
import { InstrumentSelect } from "../components/InstrumentSelect";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState } from "../components/states";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Pill } from "../components/ui/pill";
import { Segmented } from "../components/ui/segmented";
import { Skeleton } from "../components/ui/skeleton";
import { Button } from "../components/ui/button";
import { NumberInput } from "../components/ui/input";
import { Menu } from "../components/ui/menu";
import { getJson, qs, type CandlesResponse, type Instrument, type Timeframe } from "../lib/api";
import type { IndicatorInfo } from "../lib/strategy";
import { MARKET_TZ, TIMEFRAME_LABEL } from "../lib/format";
import { DEFAULT_LAYERS, type ChartReading, type KairosLayer } from "../lib/kairos";
import { useKairos } from "../lib/kairosChat";
import { kairosDrawings } from "../lib/kairosDrawings";
import { useTheme } from "../lib/theme";
import { useApi } from "../lib/useApi";
import { cn } from "../lib/utils";
import { KairosPanel } from "./charts/KairosPanel";

const TIMEFRAMES: Timeframe[] = ["1d", "1h", "15m", "5m", "1m"];
// The chart loads all the history there is, but opens zoomed to this recent stretch
// (scroll or pinch to go further back). Kairos reads the same recent stretch.
const VIEW_DAYS: Record<Timeframe, number> = { "1d": 730, "1h": 120, "15m": 30, "5m": 10, "1m": 3 };

interface Line {
  id: number;
  key: string;
  params: Record<string, number>;
}

const COLORS: Overlay["color"][] = ["accent", "info", "benchmark", "warning"];
const LAYERS_KEY = "agora.kairos.layers";

function savedLayers(): Record<KairosLayer, boolean> {
  try {
    const raw = localStorage.getItem(LAYERS_KEY);
    return raw ? { ...DEFAULT_LAYERS, ...(JSON.parse(raw) as Partial<Record<KairosLayer, boolean>>) } : DEFAULT_LAYERS;
  } catch {
    return DEFAULT_LAYERS;
  }
}

function KairosLoading() {
  return (
    <div className="flex h-[540px] flex-col gap-3 rounded-card border border-hairline bg-surface p-4" aria-busy="true">
      <div className="flex items-center gap-2 text-small text-fg-muted">
        <KairosMark className="animate-pulse" />
        Kairos is reading the chart…
      </div>
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-2 w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-4 w-4/6" />
    </div>
  );
}

function lineLabel(l: Line, info?: IndicatorInfo): string {
  const args = info ? info.params.map((p) => l.params[p.name] ?? p.default) : Object.values(l.params);
  return `${info?.label ?? l.key}${args.length ? ` (${args.join(", ")})` : ""}`;
}

/** Indicator lines drawn over the candles (overlay indicators only: they share the price scale). */
function useOverlays(lines: Line[], inst: Instrument, timeframe: Timeframe, start: number | null) {
  const [data, setData] = useState<Record<string, Overlay[]>>({});
  const want = useMemo(() => lines.map((l) => ({ l, k: `${l.key}:${JSON.stringify(l.params)}` })), [lines]);
  useEffect(() => {
    let alive = true;
    if (start === null) return; // wait for the candles, so the lines cover the same stretch
    for (const { l, k } of want) {
      if (data[k]) continue;
      getJson<{ outputs: Record<string, { ts: number; value: number }[]> }>(
        `/indicators/${l.key}/values${qs({ instrument_id: inst.id, timeframe, start, params: JSON.stringify(l.params) })}`,
      )
        .then((r) => {
          if (!alive) return;
          const out = Object.entries(r.outputs).map(([name, pts]) => ({ id: `${k}:${name}`, label: name, points: pts.map((p) => ({ time: p.ts / 1000, value: p.value })) }));
          setData((d) => ({ ...d, [k]: out }));
        })
        .catch(() => undefined);
    }
    return () => {
      alive = false;
    };
  }, [want, data, inst.id, timeframe, start]);
  return want.flatMap(({ k }, i) => (data[k] ?? []).map((o) => ({ ...o, color: COLORS[i % COLORS.length] })));
}

function PriceView({
  inst,
  timeframe,
  lines,
  kairos,
  layers,
  onLayer,
}: {
  inst: Instrument;
  timeframe: Timeframe;
  lines: Line[];
  kairos: boolean;
  layers: Record<KairosLayer, boolean>;
  onLayer: (layer: KairosLayer, on: boolean) => void;
}) {
  // All the history there is (what the source still serves plus what Agora saved earlier);
  // the chart opens on the recent stretch and Kairos reads only that.
  const [start] = useState(() => Date.now() - VIEW_DAYS[timeframe] * 86_400_000);
  const s = useApi<CandlesResponse>(`/candles${qs({ instrument_id: inst.id, timeframe, full: true, fetch: true, limit: 50_000 })}`);
  const candles: Candle[] = useMemo(
    () =>
      s.status === "ready"
        ? s.data.bars.map((b) => ({ time: b.ts / 1000, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume }))
        : [],
    [s],
  );
  const overlays = useOverlays(lines, inst, timeframe, s.status === "ready" ? (s.data.bars[0]?.ts ?? start) : null);
  // Kairos reads the same window, once the candles (and any download) are in.
  const reading = useApi<ChartReading>(kairos && candles.length ? `/analysis/chart${qs({ instrument_id: inst.id, timeframe, start })}` : null);
  const { resolved } = useTheme();
  const drawings = useMemo(
    () => (kairos && reading.status === "ready" ? kairosDrawings(reading.data, layers, readChartTokens()) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-read tokens when the theme changes
    [kairos, reading, layers, resolved],
  );
  if (s.status === "loading") return <Skeleton className="h-[480px] w-full rounded-card" />;
  if (s.status === "error") return <ErrorState error={s.error} onRetry={s.reload} />;
  if (s.status !== "ready") return null;
  if (!candles.length) {
    return (
      <EmptyState
        icon={LineChart}
        title="No prices for this view yet"
        body={s.data.note ?? "Agora couldn't find saved prices for this stock and timeframe. Try the Data screen to download them."}
      />
    );
  }
  const chart = (
    <PriceChart
      candles={candles}
      overlays={overlays}
      drawings={drawings}
      timeZone={MARKET_TZ[inst.market]}
      intraday={timeframe !== "1d"}
      initialFrom={start / 1000}
      height={480}
      caption={
        kairos
          ? `${inst.symbol} with Kairos's reading: shaded zones are support (green) and resistance (red), the orange cone is the likely range ahead.`
          : `${inst.symbol} ${TIMEFRAME_LABEL[timeframe].toLowerCase()} prices, adjusted for splits. Hover to see each candle's open, high, low and close.`
      }
      ariaLabel={`Candlestick chart of ${inst.symbol}${kairos ? " with Kairos's drawings" : ""}`}
    />
  );
  return (
    <div className="flex flex-col gap-2">
      {s.data.note && <p className="m-0 text-small text-warning">{s.data.note}</p>}
      {kairos ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0">{chart}</div>
          {reading.status === "ready" ? (
            <KairosPanel reading={reading.data} layers={layers} onLayer={onLayer} />
          ) : reading.status === "error" ? (
            <ErrorState error={reading.error} onRetry={reading.reload} />
          ) : (
            <KairosLoading />
          )}
        </div>
      ) : (
        chart
      )}
    </div>
  );
}

export default function Charts() {
  const [search, setSearch] = useSearchParams();
  const [inst, setInst] = useState<Instrument | null>(null);
  const [timeframe, setTimeframe] = useState<Timeframe>(() => {
    const tf = search.get("tf");
    return TIMEFRAMES.includes(tf as Timeframe) ? (tf as Timeframe) : "1d";
  });
  const [lines, setLines] = useState<Line[]>([]);
  const [kairosOn, setKairos] = useState(() => search.get("kairos") === "1");
  const kairosApi = useKairos();
  const kairos = kairosOn && kairosApi !== null; // off when Kairos is switched off in Settings
  const [layers, setLayers] = useState(savedLayers);
  const onLayer = useCallback((layer: KairosLayer, on: boolean) => {
    setLayers((l) => {
      const next = { ...l, [layer]: on };
      try {
        localStorage.setItem(LAYERS_KEY, JSON.stringify(next));
      } catch {
        /* private window: the switch still works for this visit */
      }
      return next;
    });
  }, []);
  // A link like /charts?symbol=RELIANCE&market=IN&tf=1d&kairos=1 opens that chart directly
  // (Kairos sends the user to charts this way). Applied once per new link, during render.
  const wanted = search.get("symbol");
  const all = useApi<{ instruments: Instrument[] }>(wanted ? "/instruments" : null);
  const linkKey = `${search.toString()}|${all.status}`;
  const [appliedLink, setAppliedLink] = useState("");
  if (linkKey !== appliedLink && (!wanted || all.status !== "loading")) {
    setAppliedLink(linkKey);
    if (search.get("kairos") === "1") setKairos(true);
    const tf = search.get("tf");
    if (tf && TIMEFRAMES.includes(tf as Timeframe)) setTimeframe(tf as Timeframe);
    if (wanted && all.status === "ready") {
      const market = search.get("market");
      const hit = all.data.instruments.find((i) => i.symbol === wanted.toUpperCase() && (!market || i.market === market));
      if (hit) setInst(hit);
    }
  }
  const toggleKairos = () => {
    setKairos((k) => !k);
    if (search.has("kairos")) {
      const next = new URLSearchParams(search);
      next.delete("kairos");
      setSearch(next, { replace: true });
    }
  };
  const catalog = useApi<{ indicators: IndicatorInfo[] }>("/indicators");
  const overlayKinds = catalog.status === "ready" ? catalog.data.indicators.filter((i) => i.overlay && (timeframe !== "1d" || !i.intraday_only)) : [];
  const byKey = Object.fromEntries(overlayKinds.map((i) => [i.key, i]));
  const add = (info: IndicatorInfo) =>
    setLines((ls) => [...ls, { id: Date.now(), key: info.key, params: Object.fromEntries(info.params.map((p) => [p.name, p.default])) }]);
  return (
    <>
      <PageHeader title="Charts" subtitle="Look at any stock's price history." />
      <Card>
        <CardHeader className="flex-wrap">
          <div className="flex items-center gap-3">
            <CardTitle>{inst ? `${inst.symbol} · ${TIMEFRAME_LABEL[timeframe]}` : "Pick a stock"}</CardTitle>
            {inst && <Pill>{inst.market === "IN" ? "NSE · ₹" : "US · $"}</Pill>}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <InstrumentSelect value={inst?.id ?? null} onChange={setInst} />
            <Segmented label="Timeframe" value={timeframe} onChange={setTimeframe} options={TIMEFRAMES.map((t) => ({ value: t, label: TIMEFRAME_LABEL[t] }))} />
            {kairosApi && (
              <Button
                size="sm"
                variant={kairos ? "soft" : "secondary"}
                aria-pressed={kairos}
                onClick={toggleKairos}
                disabled={!inst}
                title="Let Kairos draw support, resistance, patterns and a forecast on this chart"
                className={cn(kairos && "ring-1 ring-accent/40")}
              >
                <KairosMark className="size-4" />
                Kairos {kairos ? "on" : "off"}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardBody className="flex flex-col gap-3">
          {inst && (
            <div className="flex flex-wrap items-center gap-2">
              {lines.map((l) => {
                const info = byKey[l.key];
                const first = info?.params[0];
                return (
                  <Pill key={l.id} className="h-9 gap-2 pr-1.5">
                    <span>{info?.label ?? l.key}</span>
                    {first && (
                      <NumberInput
                        aria-label={`${info?.label} ${first.label}`}
                        value={l.params[first.name] ?? first.default}
                        min={first.min}
                        max={first.max}
                        onChange={(v) => v !== null && v >= first.min && v <= first.max && setLines((ls) => ls.map((x) => (x.id === l.id ? { ...x, params: { ...x.params, [first.name]: v } } : x)))}
                        className="h-7 w-16 px-2 text-small"
                      />
                    )}
                    <button type="button" aria-label={`Remove ${lineLabel(l, info)}`} onClick={() => setLines((ls) => ls.filter((x) => x.id !== l.id))} className="rounded-full p-1 text-fg-muted hover:bg-surface-2 hover:text-fg">
                      <X className="size-3.5" aria-hidden="true" />
                    </button>
                  </Pill>
                );
              })}
              {overlayKinds.length > 0 && lines.length < 4 && (
                <Menu
                  align="start"
                  trigger={
                    <Button size="sm" variant="ghost">
                      <Plus aria-hidden="true" />
                      Add indicator
                    </Button>
                  }
                  items={overlayKinds.map((i) => ({ label: i.label, onSelect: () => add(i) }))}
                />
              )}
            </div>
          )}
          {inst ? (
            <PriceView
              key={`${inst.id}-${timeframe}`}
              inst={inst}
              timeframe={timeframe}
              lines={lines.filter((l) => byKey[l.key])}
              kairos={kairos}
              layers={layers}
              onLayer={onLayer}
            />
          ) : (
            <EmptyState icon={LineChart} title="Choose a stock to see its chart" body="Type a symbol or company name above: any stock on NSE or the US exchanges." className="min-h-[480px]" />
          )}
        </CardBody>
      </Card>
    </>
  );
}
