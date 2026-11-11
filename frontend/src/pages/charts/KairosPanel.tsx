import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, ChevronDown, ExternalLink, Info } from "lucide-react";
import { useState, type ReactNode } from "react";
import { KairosMark } from "../../components/kairos/KairosMark";
import { Pill } from "../../components/ui/pill";
import { Button } from "../../components/ui/button";
import { formatAgo } from "../../lib/format";
import { useKairos } from "../../lib/kairosChat";
import { LAYER_LABEL, type Bias, type ChartReading, type ForecastInfo, type KairosLayer, type NewsResponse, type SignalStats, type Timeframes } from "../../lib/kairos";
import { useApi } from "../../lib/useApi";
import { cn } from "../../lib/utils";

function money(v: number, market: "IN" | "US"): string {
  const sym = market === "IN" ? "₹" : "$";
  return `${v < 0 ? "−" : ""}${sym}${Math.abs(v).toLocaleString(market === "IN" ? "en-IN" : "en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

const BIAS_TONE: Record<Bias, "profit" | "loss" | "neutral"> = { bullish: "profit", bearish: "loss", neutral: "neutral" };
const BIAS_WORD: Record<Bias, string> = { bullish: "Bullish", bearish: "Bearish", neutral: "Neutral" };
const STATUS_TONE: Record<string, "profit" | "loss" | "info" | "warning" | "neutral"> = {
  confirmed: "info",
  target: "profit",
  forming: "warning",
  failed: "loss",
};
const STATUS_WORD: Record<string, string> = { confirmed: "Confirmed", target: "Target reached", forming: "Forming", failed: "Failed" };

/** −100 … +100 as a bar with a marker; red to the left, green to the right. */
function ScoreBar({ score }: { score: number }) {
  const pos = (score + 100) / 2;
  return (
    <div className="flex flex-col gap-1" aria-label={`Kairos score ${score.toFixed(0)} out of 100`} role="img">
      <div className="relative h-2 rounded-full bg-gradient-to-r from-loss/70 via-surface-2 to-profit/70">
        <motion.span
          className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-fg shadow-e1"
          initial={{ left: "50%" }}
          animate={{ left: `${pos}%` }}
          transition={{ type: "spring", stiffness: 140, damping: 20 }}
        />
      </div>
      <div className="flex justify-between text-tiny text-fg-subtle">
        <span>Bearish</span>
        <span>Neutral</span>
        <span>Bullish</span>
      </div>
    </div>
  );
}

function Stats({ st }: { st: SignalStats | null }) {
  if (!st || st.n < 5) return null;
  return (
    <p className="m-0 text-tiny text-fg-subtle">
      In this market's history it worked {Math.round(st.hit_rate * 100)}% of {st.n} times
      {st.base_rate !== undefined ? ` (a random day: ${Math.round(st.base_rate * 100)}%)` : ""}.
    </p>
  );
}

function Section({ title, count, children, open: initial = true }: { title: string; count?: number; children: ReactNode; open?: boolean }) {
  const [open, setOpen] = useState(initial);
  return (
    <section className="border-t border-hairline pt-3">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between text-left">
        <h3 className="m-0 text-small font-semibold text-fg">
          {title}
          {count !== undefined && <span className="ml-1.5 font-normal text-fg-subtle">{count}</span>}
        </h3>
        <ChevronDown className={cn("size-4 text-fg-subtle transition-transform", open && "rotate-180")} aria-hidden="true" />
      </button>
      {open && <div className="mt-2 flex flex-col gap-2.5">{children}</div>}
    </section>
  );
}

const VERDICT_TONE: Record<string, "profit" | "loss" | "warning" | "neutral"> = {
  aligned_up: "profit",
  aligned_down: "loss",
  pullback_in_uptrend: "warning",
  bounce_in_downtrend: "warning",
};

/** The same stock on several timeframes, biggest first, and whether they agree (D-97). */
function TimeframesBlock({ mt }: { mt: Timeframes }) {
  return (
    <Section title="Timeframes">
      <div className="flex items-center gap-2">
        <Pill tone={VERDICT_TONE[mt.verdict] ?? "neutral"} className="h-6 text-tiny">
          {mt.headline}
        </Pill>
      </div>
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Trend on each timeframe">
        {mt.timeframes.map((t) => (
          <li key={t.timeframe} className="flex items-center gap-2 text-small">
            <span className="w-20 shrink-0 text-fg-muted capitalize">{t.label}</span>
            <span className="relative h-1.5 flex-1 rounded-full bg-surface-2" aria-hidden="true">
              <span
                className={cn("absolute top-0 h-1.5 rounded-full", t.trend >= 0 ? "left-1/2 bg-profit" : "right-1/2 bg-loss")}
                style={{ width: `${Math.min(50, Math.abs(t.trend) / 2)}%` }}
              />
            </span>
            <span className={cn("w-28 shrink-0 text-right text-tiny", t.direction > 0 ? "text-profit" : t.direction < 0 ? "text-loss" : "text-fg-subtle")}>
              {t.regime}
            </span>
          </li>
        ))}
      </ul>
      <p className="m-0 text-small leading-5 text-fg-muted">{mt.text}</p>
    </Section>
  );
}

const TONE_DOT: Record<string, string> = { positive: "bg-profit", negative: "bg-loss", neutral: "bg-neutral-dot" };
const MOOD_WORD: Record<string, string> = { positive: "Mostly good news", negative: "Mostly bad news", neutral: "Mixed news", quiet: "No recent news" };

/** The stock's latest headlines; asks again while a refresh is running. */
function News({ instrumentId }: { instrumentId: number }) {
  const [poll, setPoll] = useState<number | undefined>(undefined);
  const n = useApi<NewsResponse>(`/news?instrument_id=${instrumentId}&limit=8`, poll);
  const refreshing = n.status === "ready" && n.data.refreshing;
  if (refreshing !== (poll !== undefined)) setPoll(refreshing ? 4000 : undefined);
  if (n.status !== "ready" || !n.data.enabled) return null;
  const { items, mood } = n.data;
  return (
    <Section title="News" count={items.length}>
      {mood && (
        <p className="m-0 text-small text-fg-muted">
          {MOOD_WORD[mood.tone]}
          {mood.count > 0 && ` · tone ${mood.score > 0 ? "+" : ""}${mood.score.toFixed(2)} from ${mood.count} headline${mood.count === 1 ? "" : "s"}`}
          {refreshing && " · checking for new headlines…"}
        </p>
      )}
      {items.map((i) => (
        <a key={i.id} href={i.link} target="_blank" rel="noopener noreferrer" className="group flex gap-2 rounded-control p-1 -m-1 hover:bg-surface-2">
          <span aria-hidden="true" className={cn("mt-1.5 size-2 shrink-0 rounded-full", TONE_DOT[i.tone])} />
          <span className="min-w-0 flex-1">
            <span className="block text-small leading-5 text-fg group-hover:underline">{i.title}</span>
            <span className="text-tiny text-fg-subtle">
              {i.publisher || "News"} · {formatAgo(i.published_at)} · {i.tone}
            </span>
          </span>
          <ExternalLink className="mt-1 size-3.5 shrink-0 text-fg-subtle opacity-0 group-hover:opacity-100" aria-hidden="true" />
        </a>
      ))}
      {items.length === 0 && !refreshing && <p className="m-0 text-small text-fg-muted">No headlines about this stock in the last 3 days.</p>}
    </Section>
  );
}

function day(ms: number): string {
  return new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** The predicted candles as a small drawing (dashed, so they never pass for real ones). */
function MiniCandles({ candles, label }: { candles: ForecastInfo["candles"] & object; label: string }) {
  const W = 16;
  const H = 64;
  const lo = Math.min(...candles.map((c) => c.low));
  const hi = Math.max(...candles.map((c) => c.high));
  const y = (v: number) => 4 + ((hi - v) / (hi - lo || 1)) * (H - 8);
  return (
    <svg viewBox={`0 0 ${candles.length * W} ${H}`} className="h-16 w-full max-w-[300px]" role="img" aria-label={label}>
      {candles.map((c, i) => {
        const x = i * W + W / 2;
        const tone = c.direction > 0 ? "stroke-profit fill-profit/25" : c.direction < 0 ? "stroke-loss fill-loss/25" : "stroke-fg-subtle fill-surface-2";
        const top = y(Math.max(c.open, c.close));
        const h = Math.max(1.5, y(Math.min(c.open, c.close)) - top);
        return (
          <g key={c.ts} className={tone}>
            <line x1={x} x2={x} y1={y(c.high)} y2={y(c.low)} strokeWidth="1" />
            <rect x={x - 4} y={top} width="8" height={h} rx="1" strokeWidth="1" strokeDasharray="2 1.5" />
          </g>
        );
      })}
    </svg>
  );
}

/** Kairos's predicted candles and how its last prediction compared with reality (§17). */
function Predictions({ fc, market, layers, onLayer }: { fc: ForecastInfo; market: "IN" | "US"; layers: Record<KairosLayer, boolean>; onLayer: (l: KairosLayer, on: boolean) => void }) {
  const cs = fc.candles ?? [];
  const ups = cs.filter((c) => c.direction > 0).length;
  const downs = cs.filter((c) => c.direction < 0).length;
  const prev = fc.previous;
  const cal = fc.calibration;
  return (
    <Section title="Predicted candles">
      {cs.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <MiniCandles candles={cs} label={`${ups} rising, ${downs} falling, ${cs.length - ups - downs} flat predicted candles`} />
          <p className="m-0 text-small text-fg-muted">
            The most likely next {cs.length} candles: {ups} rising, {downs} falling, {cs.length - ups - downs} flat, ending near {money(cs.at(-1)?.close ?? 0, market)}. A likely shape, never a promise: the shaded range is the honest part.
          </p>
          {fc.analyst && (
            <p className="m-0 text-tiny text-fg-subtle">
              Kairos's chart reading (score {fc.analyst.score > 0 ? "+" : ""}
              {fc.analyst.score.toFixed(0)}) is one of the models{fc.news?.tilt ? `, leaned by this stock's news (${fc.news.stock})` : ""}
              {fc.news?.widen_pct ? `; ranges widened ${fc.news.widen_pct}% for market news risk` : ""}.
            </p>
          )}
        </div>
      )}
      {prev && prev.formed > 0 && (
        <div className="flex flex-col gap-1 rounded-control bg-info-soft/50 p-2.5">
          <p className="m-0 text-tiny font-semibold tracking-wide text-info-soft-fg uppercase">
            {prev.kind === "live" ? `Kairos's prediction from ${day(prev.made_at)}` : `Prediction re-created for ${day(prev.made_at)}`}
          </p>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded-control bg-surface px-1.5 py-1">
              <p className="m-0 text-tiny text-fg-subtle">In range</p>
              <p className="m-0 text-small font-semibold tabular-nums">
                {prev.inside80 ?? 0}/{prev.formed}
              </p>
            </div>
            <div className="rounded-control bg-surface px-1.5 py-1">
              <p className="m-0 text-tiny text-fg-subtle">Direction</p>
              <p className="m-0 text-small font-semibold tabular-nums">{prev.direction_scored ? `${prev.direction_hits}/${prev.direction_scored}` : "—"}</p>
            </div>
            <div className="rounded-control bg-surface px-1.5 py-1">
              <p className="m-0 text-tiny text-fg-subtle">Off by</p>
              <p className="m-0 text-small font-semibold tabular-nums">{prev.end_error_pct == null ? "—" : `${prev.end_error_pct > 0 ? "+" : ""}${prev.end_error_pct.toFixed(1)}%`}</p>
            </div>
          </div>
          <p className="m-0 text-small text-fg-muted">{prev.text}</p>
          {prev.kind === "re-created" && <p className="m-0 text-tiny text-fg-subtle">Kairos hadn't shown a prediction for this stock yet, so it re-made the one it would have made then, using only what was known that day.</p>}
          <label className="flex items-center gap-2 text-tiny text-fg-muted">
            <input type="checkbox" checked={layers.lastPrediction} onChange={(e) => onLayer("lastPrediction", e.target.checked)} />
            Outline it over the real candles
          </label>
        </div>
      )}
      {cal?.text && <p className="m-0 text-tiny text-fg-subtle">What its misses taught it: {cal.text}</p>}
    </Section>
  );
}

export function KairosPanel({
  reading,
  layers,
  onLayer,
}: {
  reading: ChartReading;
  layers: Record<KairosLayer, boolean>;
  onLayer: (layer: KairosLayer, on: boolean) => void;
}) {
  const r = reading.report;
  const fc = reading.forecast;
  const m = r.market;
  const kairos = useKairos();
  return (
    <aside aria-label="Kairos's reading of this chart" className="flex h-[540px] flex-col overflow-hidden rounded-card border border-hairline bg-surface">
      <div className="flex items-center gap-2 border-b border-hairline px-4 py-3">
        <KairosMark />
        <div className="min-w-0 flex-1">
          <p className="m-0 text-small font-semibold">Kairos reads {r.symbol}</p>
          <p className="m-0 truncate text-tiny text-fg-subtle">{r.headline}</p>
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-3">
        <div className="flex items-end justify-between gap-2">
          <div>
            <span className={cn("block text-[22px] leading-7 font-semibold", r.bias === "bullish" ? "text-profit" : r.bias === "bearish" ? "text-loss" : "text-fg")}>
              {BIAS_WORD[r.bias]}
            </span>
            <span className="text-tiny text-fg-subtle">{r.confidence[0]?.toUpperCase() + r.confidence.slice(1)} confidence</span>
          </div>
          <Pill tone={BIAS_TONE[r.bias]} className="h-7 tabular-nums">
            Score {r.score > 0 ? "+" : ""}
            {r.score.toFixed(0)}
          </Pill>
        </div>
        <ScoreBar score={r.score} />
        {reading.training_job && (
          <p className="m-0 text-tiny text-fg-subtle" role="status">
            Kairos is studying this market's history to measure how often each signal worked. Those numbers appear next time you open the chart.
          </p>
        )}

        {fc && (
          <div className="rounded-control bg-accent-soft/60 p-3">
            <p className="m-0 text-tiny font-semibold tracking-wide text-accent-soft-fg uppercase">Likely range · next {fc.horizon} candles</p>
            <p className="m-0 mt-1 text-[15px] font-semibold text-fg">
              {money(fc.path.at(-1)?.p10 ?? 0, m)} – {money(fc.path.at(-1)?.p90 ?? 0, m)}
            </p>
            <p className="m-0 text-small text-fg-muted">
              Middle {money(fc.path.at(-1)?.median ?? 0, m)} · chance higher {Math.round(fc.up_probability * 100)}%
            </p>
            <p className="m-0 mt-2 flex gap-1.5 text-tiny text-fg-muted">
              {fc.edge ? <CheckCircle2 className="mt-px size-3.5 shrink-0 text-profit" aria-hidden="true" /> : <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />}
              <span>{fc.verdict}</span>
            </p>
            {fc.live && fc.live.n > 0 && (
              <p className="m-0 mt-1 text-tiny text-fg-muted">
                Live so far: direction right {fc.live.direction_hits} of {fc.live.n}; {fc.live.inside80} of {fc.live.n} ended inside the range.
              </p>
            )}
          </div>
        )}

        {fc && (fc.candles?.length || fc.previous) ? <Predictions fc={fc} market={m} layers={layers} onLayer={onLayer} /> : null}

        {reading.timeframes && <TimeframesBlock mt={reading.timeframes} />}

        <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
          {r.summary.map((line) => (
            <li key={line} className="text-small leading-5 text-fg-muted">
              {line}
            </li>
          ))}
        </ul>

        {r.idea && (
          <Section title="Trade idea">
            <div className="flex flex-col gap-1.5">
              {r.idea.quality === "poor" ? (
                <p className="m-0 flex gap-1.5 text-small text-fg-muted">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden="true" />
                  {r.idea.text}
                </p>
              ) : (
                <>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    {(
                      [
                        ["Entry", r.idea.entry, "text-fg"],
                        ["Stop", r.idea.stop, "text-loss"],
                        ["Target", r.idea.target, "text-profit"],
                      ] as const
                    ).map(([label, v, cls]) => (
                      <div key={label} className="rounded-control bg-surface-2 px-2 py-1.5">
                        <p className="m-0 text-tiny text-fg-subtle">{label}</p>
                        <p className={cn("m-0 text-small font-semibold tabular-nums", cls)}>{money(v, m)}</p>
                      </div>
                    ))}
                  </div>
                  <p className="m-0 text-small text-fg-muted">{r.idea.text}</p>
                  <label className="flex items-center gap-2 text-tiny text-fg-muted">
                    <input type="checkbox" checked={layers.idea} onChange={(e) => onLayer("idea", e.target.checked)} />
                    Show on the chart
                  </label>
                </>
              )}
            </div>
          </Section>
        )}

        {r.patterns.length > 0 && (
          <Section title="Chart patterns" count={r.patterns.length}>
            {r.patterns.map((p) => (
              <div key={`${p.key}-${p.start_ts}`} className="flex flex-col gap-1">
                <div className="flex items-center justify-between gap-2">
                  <span className={cn("text-small font-semibold", p.bias === "bullish" ? "text-profit" : p.bias === "bearish" ? "text-loss" : "text-fg")}>{p.name}</span>
                  <Pill tone={STATUS_TONE[p.status]} className="h-6 px-2 text-tiny">
                    {STATUS_WORD[p.status]} · {Math.round(p.confidence * 100)}%
                  </Pill>
                </div>
                <p className="m-0 text-small leading-5 text-fg-muted">{p.explanation}</p>
                <Stats st={p.stats} />
              </div>
            ))}
          </Section>
        )}

        <News instrumentId={reading.instrument.id} />

        {r.zones.length > 0 && (
          <Section title="Support & resistance" count={r.zones.length}>
            {r.zones.map((z) => (
              <div key={`${z.role}-${z.center}`} className="flex items-center justify-between gap-2 text-small">
                <span className={cn(z.role === "support" ? "text-profit" : z.role === "resistance" ? "text-loss" : "text-accent-soft-fg")}>
                  {z.role === "testing" ? "Testing" : z.role === "support" ? "Support" : "Resistance"}
                </span>
                <span className="tabular-nums text-fg">
                  {money(z.low, m)} – {money(z.high, m)}
                </span>
                <span className="text-tiny text-fg-subtle">
                  {z.touches}× · {z.strength}
                </span>
              </div>
            ))}
          </Section>
        )}

        {(r.candles.length > 0 || r.divergences.length > 0) && (
          <Section title="Candles & divergences" count={r.candles.length + r.divergences.length} open={false}>
            {r.divergences.map((d) => (
              <div key={`${d.kind}-${d.known_ts}`}>
                <p className={cn("m-0 text-small font-semibold", d.bullish ? "text-profit" : "text-loss")}>{d.label}</p>
                <p className="m-0 text-small text-fg-muted">
                  Price and RSI disagree (RSI {d.rsi_from.toFixed(0)} → {d.rsi_to.toFixed(0)}){d.strong ? ", and MACD agrees" : ""}.
                </p>
                <Stats st={d.stats} />
              </div>
            ))}
            {[...r.candles].reverse().slice(0, 6).map((c) => (
              <div key={`${c.key}-${c.ts}`}>
                <p className={cn("m-0 text-small font-semibold", c.bias === "bullish" ? "text-profit" : c.bias === "bearish" ? "text-loss" : "text-fg")}>
                  {c.name} <span className="font-normal text-fg-subtle">· {new Date(c.ts).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</span>
                </p>
                <p className="m-0 text-small text-fg-muted">{c.meaning}</p>
                <Stats st={c.stats} />
              </div>
            ))}
          </Section>
        )}

        <Section title="On the chart" open={false}>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
            {(Object.keys(LAYER_LABEL) as KairosLayer[]).map((k) => (
              <label key={k} className="flex items-center gap-2 text-small text-fg-muted">
                <input type="checkbox" checked={layers[k]} onChange={(e) => onLayer(k, e.target.checked)} />
                {LAYER_LABEL[k]}
              </label>
            ))}
          </div>
        </Section>
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-hairline px-4 py-2">
        <p className="m-0 text-tiny text-fg-subtle">{reading.disclaimer}</p>
        {kairos && (
          <Button size="sm" variant="soft" className="shrink-0" onClick={() => kairos.ask(`What do you see on the ${r.symbol} ${r.timeframe} chart? What would you do?`)}>
            Ask Kairos
          </Button>
        )}
      </div>
    </aside>
  );
}
