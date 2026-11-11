/**
 * The Kairos desk (docs/KAIROS.md §9): Kairos paper trades a watchlist on its own, with its
 * own paper account, and keeps a diary. Started and stopped here (or by asking Kairos).
 */
import { ScrollBox } from "../components/ui/scroll-box";
import { ArrowLeft, Play, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";
import { InstrumentSelect } from "../components/InstrumentSelect";
import { JobProgress } from "../components/JobProgress";
import { KairosMark } from "../components/kairos/KairosMark";
import { ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Change } from "../components/ui/change";
import { Field, NumberInput } from "../components/ui/input";
import { Pill } from "../components/ui/pill";
import { Segmented } from "../components/ui/segmented";
import { postJson, toEnvelope, type MarketCode, type PaperSessionSummary, type SettingsResponse } from "../lib/api";
import type { Learned, Lesson } from "../lib/desk";
import { formatDate, MARKET_CURRENCY, MARKET_TZ } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useJob, useJobId } from "../lib/useJob";
import { STATE_WORDS } from "./paper/common";
import { LearnedCard } from "./paper/DeskPanels";

const STARTERS: Record<MarketCode, string[]> = {
  IN: ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"],
  US: ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"],
};

function DeskRow({ d }: { d: PaperSessionSummary }) {
  const st = STATE_WORDS[d.state];
  return (
    <Link to={`/paper/desk/${d.id}`} className="flex items-center justify-between gap-4 rounded-control border border-hairline bg-surface px-4 py-3 no-underline hover:shadow-e1">
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-[14px] font-semibold text-fg">
          {d.name} · {d.symbols.length} stocks
        </span>
        <span className="text-small text-fg-muted">
          {d.market === "IN" ? "India" : "US"} · started {formatDate(d.started_at, MARKET_TZ[d.market])} · {d.trades} closed trade{d.trades === 1 ? "" : "s"}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="text-[15px] tabular-nums">
          <Change value={d.total_return} text={`${d.total_return >= 0 ? "+" : "−"}${Math.abs(d.total_return).toFixed(2)}%`} />
        </span>
        {d.mode === "replay" && <Pill tone="info" className="h-7 px-2.5 text-tiny">Practice replay</Pill>}
        <Pill tone={st.tone} className="h-7 px-2.5 text-tiny">{st.label}</Pill>
      </div>
    </Link>
  );
}

export default function KairosDesk() {
  const navigate = useNavigate();
  const [market, setMarket] = useState<MarketCode>("IN");
  const [symbols, setSymbols] = useState<string[]>(STARTERS.IN);
  const [capital, setCapital] = useState<number | null>(null);
  const [jobId, setJobId] = useJobId("kairos_desk");
  const desks = useApi<{ desks: PaperSessionSummary[] }>("/kairos/desk", 15_000);
  const settings = useApi<SettingsResponse>("/settings");
  const learned = useApi<Learned>(`/kairos/stats?market=${market}`);
  const lessons = useApi<{ lessons: Lesson[] }>(`/kairos/lessons?market=${market}`);
  const { job } = useJob<{ session_id: number }>(jobId, (j) => {
    setJobId(null);
    if (j.status === "done" && j.result) {
      toast.success("The Kairos desk is running.");
      navigate(`/paper/desk/${j.result.session_id}`);
    }
  });
  const cur = MARKET_CURRENCY[market];
  const defaultCapital = settings.status === "ready" ? Number(settings.data.values[`default_capital.${market}`] ?? 0) : 0;
  const risk = settings.status === "ready" ? Number(settings.data.values["kairos.risk_pct"] ?? 1) : 1;
  const maxPos = settings.status === "ready" ? Number(settings.data.values["kairos.max_positions"] ?? 10) : 10;

  function pickMarket(m: MarketCode) {
    setMarket(m);
    setSymbols(STARTERS[m]);
  }

  async function start() {
    try {
      const r = await postJson<{ job_id: string }>("/kairos/desk", { market, symbols, capital: capital ?? undefined });
      setJobId(r.job_id);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }

  const list = desks.status === "ready" ? desks.data.desks : [];
  return (
    <>
      <div className="flex flex-col gap-2">
        <Link to="/paper" className="flex w-fit items-center gap-1.5 text-small text-fg-muted no-underline hover:text-fg">
          <ArrowLeft className="size-4" aria-hidden="true" />
          Paper trading
        </Link>
        <h1 className="m-0 flex items-center gap-2.5 text-title font-bold tracking-tight">
          <KairosMark className="size-7" />
          Kairos desk
        </h1>
        <p className="m-0 max-w-[760px] text-body text-fg-muted">
          Kairos watches the stocks you pick and paper trades them on its own, with fake money, by its own rules: chart patterns, levels, momentum, volume and candles, weighted by what has worked. Every trade gets a written reason, and every result teaches it. It runs only while Agora is open.
        </p>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_420px] items-start gap-5">
        <div className="flex min-w-0 flex-col gap-5">
          <Card>
            <CardHeader>
              <CardTitle>Start a desk</CardTitle>
            </CardHeader>
            <CardBody className="flex flex-col gap-5">
              <Field label="Market" className="w-[240px]">
                <Segmented
                  label="Market"
                  value={market}
                  onChange={pickMarket}
                  options={[
                    { value: "IN", label: "India" },
                    { value: "US", label: "US" },
                  ]}
                />
              </Field>
              <Field label="Stocks to watch" hint="Up to 250. Kairos only trades these.">
                <div className="flex flex-wrap items-center gap-1.5">
                  {symbols.map((sym) => (
                    <span key={sym} className="inline-flex h-8 items-center gap-1 rounded-full border border-border bg-surface-2 pr-1 pl-3 text-small font-semibold">
                      {sym}
                      <button type="button" aria-label={`Remove ${sym}`} onClick={() => setSymbols(symbols.filter((s) => s !== sym))} className="rounded-full p-1 text-fg-muted hover:bg-surface hover:text-fg">
                        <X className="size-3" aria-hidden="true" />
                      </button>
                    </span>
                  ))}
                  <InstrumentSelect
                    key={`${market}:${symbols.join(",")}`}
                    label="Add a stock"
                    market={market}
                    value={null}
                    onChange={(inst) => inst.type !== "index" && !symbols.includes(inst.symbol) && symbols.length < 30 && setSymbols([...symbols, inst.symbol])}
                    className="[&_select]:h-8 [&_select]:w-[190px]"
                  />
                </div>
              </Field>
              <Field label="Paper money" htmlFor="desk-capital" hint={`Fake ${cur === "INR" ? "rupees" : "dollars"} for the desk's own account.`}>
                <NumberInput id="desk-capital" value={capital ?? (defaultCapital || null)} min={1} onChange={setCapital} className="w-[220px]" />
              </Field>
              <p className="m-0 text-small text-fg-muted">
                Each trade risks {risk}% of the desk's money (the loss if its stop is hit), with at most {maxPos} trades open at once. Change these in Settings → Kairos.
              </p>
              {job ? (
                <JobProgress job={job} />
              ) : (
                <div>
                  <Button variant="primary" onClick={() => void start()} disabled={!symbols.length}>
                    <Play aria-hidden="true" />
                    Start the Kairos desk
                  </Button>
                </div>
              )}
            </CardBody>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Desks</CardTitle>
            </CardHeader>
            <CardBody className="flex flex-col gap-2.5">
              {desks.status === "error" && <ErrorState error={desks.error} onRetry={desks.reload} />}
              {desks.status === "loading" && <LoadingRows rows={2} />}
              {desks.status === "ready" && list.length === 0 && <p className="m-0 text-small text-fg-muted">No desk yet. Start one above, or ask Kairos: “keep an eye on TCS and Infosys and trade them for me”.</p>}
              <ScrollBox size="lg" className="flex flex-col gap-2.5">
                {list.map((d) => (
                  <DeskRow key={d.id} d={d} />
                ))}
              </ScrollBox>
            </CardBody>
          </Card>
        </div>
        {learned.status === "ready" ? (
          <LearnedCard learned={learned.data} lessons={lessons.status === "ready" ? lessons.data.lessons : []} onRetrained={learned.reload} />
        ) : (
          <LoadingRows rows={4} />
        )}
      </div>
      <p className="m-0 text-tiny text-fg-subtle">Kairos is a research tool, not financial advice. Paper money only.</p>
    </>
  );
}
