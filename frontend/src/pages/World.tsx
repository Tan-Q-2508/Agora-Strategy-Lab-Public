/**
 * The world desk (SPEC §18, D-95, D-96): world events in the news and how they ripple into each
 * market's sectors and stocks; sudden moves and their most likely cause; and what past events
 * actually did, measured on saved prices, so the map keeps learning.
 */
import { motion } from "framer-motion";
import { ArrowRight, ExternalLink, Globe2, GraduationCap, Search, TrendingDown, TrendingUp, Zap } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { JobProgress } from "../components/JobProgress";
import { KairosMark } from "../components/kairos/KairosMark";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Change } from "../components/ui/change";
import { Pill } from "../components/ui/pill";
import { Segmented } from "../components/ui/segmented";
import { postJson, toEnvelope, type MarketCode } from "../lib/api";
import { formatAgo } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useJob, useJobId } from "../lib/useJob";
import { cn } from "../lib/utils";
import type { Lesson, Move, WorldDriver, WorldResponse, WorldStock, WorldView } from "../lib/world";
import { ScrollBox } from "../components/ui/scroll-box";

const MARKETS: { value: MarketCode; label: string }[] = [
  { value: "IN", label: "India" },
  { value: "US", label: "US" },
];
const CONF_TONE = { high: "profit", medium: "info", low: "neutral" } as const;

function Effect({ value }: { value: number }) {
  const width = Math.min(100, Math.abs(value) * 50);
  return (
    <span className="relative h-1.5 w-24 shrink-0 rounded-full bg-surface-2" aria-hidden="true">
      <span className={cn("absolute top-0 h-1.5 rounded-full", value >= 0 ? "left-1/2 bg-profit" : "right-1/2 bg-loss")} style={{ width: `${width / 2}%` }} />
    </span>
  );
}

function Driver({ d }: { d: WorldDriver }) {
  return (
    <motion.li initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-3 rounded-card border border-hairline bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="m-0 text-[16px] font-semibold">{d.title}</p>
          <p className="m-0 text-tiny text-fg-subtle">
            {d.headlines.length} headlines · strength {d.strength.toFixed(0)}
            {d.calming && " · calming news"}
          </p>
        </div>
        <Pill tone={d.calming ? "profit" : "warning"} className="h-6 px-2 text-tiny">
          {d.calming ? "Easing" : "In the news"}
        </Pill>
      </div>
      <ol className="m-0 flex flex-col gap-1.5 pl-5 text-small text-fg-muted">
        {d.chain.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      {d.effects.length > 0 && (
        <ScrollBox size="xs">
          <ul className="m-0 flex list-none flex-col gap-1 p-0" aria-label="Expected effects">
            {d.effects.slice(0, 8).map((e) => (
              <li key={e.target} className="flex items-center gap-3 text-small">
                <Effect value={e.value} />
                <span className="min-w-0 flex-1 truncate">{e.label}</span>
                <span className="shrink-0 text-tiny text-fg-subtle">
                  {e.measured ? `measured on ${e.measured.n}: ${e.measured.mean_pct > 0 ? "+" : ""}${e.measured.mean_pct.toFixed(1)}%` : "from the map"}
                </span>
              </li>
            ))}
          </ul>
        </ScrollBox>
      )}
      {d.headlines.length > 0 && (
        <ScrollBox size="xs">
          <ul className="m-0 flex list-none flex-col gap-1 border-t border-hairline p-0 pt-2">
            {d.headlines.slice(0, 3).map((h) => (
              <li key={h.title} className="text-tiny">
                <a href={h.link} target="_blank" rel="noopener noreferrer" className="text-fg-muted no-underline hover:underline">
                  {h.title} <span className="text-fg-subtle">· {h.publisher} · {formatAgo(h.published_at)}</span>
                </a>
              </li>
            ))}
          </ul>
        </ScrollBox>
      )}
    </motion.li>
  );
}

function StockList({ title, rows, market, up }: { title: string; rows: WorldStock[]; market: MarketCode; up: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {up ? <TrendingUp className="size-4 text-profit" aria-hidden="true" /> : <TrendingDown className="size-4 text-loss" aria-hidden="true" />}
          {title}
        </CardTitle>
      </CardHeader>
      <CardBody>
        {rows.length === 0 ? (
          <p className="m-0 text-small text-fg-muted">Nothing stands out from the whole market.</p>
        ) : (
          <ScrollBox size="lg">
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {rows.map((r) => (
                <li key={r.instrument_id} className="flex items-start justify-between gap-3 text-small">
                  <div className="min-w-0">
                    <Link to={`/charts?symbol=${encodeURIComponent(r.symbol)}&market=${market}&kairos=1`} className="font-semibold text-fg no-underline hover:underline">
                      {r.symbol}
                    </Link>
                    <span className="block truncate text-tiny text-fg-subtle">{r.why.join("; ")}</span>
                  </div>
                  <Change value={r.vs_market} text={`${r.vs_market > 0 ? "+" : ""}${r.vs_market.toFixed(1)}`} className="text-tiny" />
                </li>
              ))}
            </ul>
          </ScrollBox>
        )}
      </CardBody>
    </Card>
  );
}

function MoveCard({ m }: { m: Move }) {
  const top = m.causes[0];
  return (
    <li className="flex flex-col gap-2 rounded-card border border-hairline bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-small font-semibold">
          <Zap className="size-4 text-warning" aria-hidden="true" />
          {m.target === "market" ? (m.market === "IN" ? "Nifty 50" : "S&P 500") : m.target} <Change value={m.move_pct} text={`${m.move_pct > 0 ? "+" : ""}${m.move_pct.toFixed(1)}%`} />
        </span>
        <span className="flex items-center gap-2 text-tiny text-fg-subtle">
          {formatAgo(m.end_ts)}
          <Pill tone={CONF_TONE[m.confidence] ?? "neutral"} className="h-6 px-2 text-tiny">
            {m.confidence} confidence
          </Pill>
        </span>
      </div>
      <p className="m-0 text-small leading-5">{m.text}</p>
      {top?.headline && (
        <a href={top.headline.link} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-tiny text-fg-muted no-underline hover:underline">
          <ExternalLink className="size-3" aria-hidden="true" /> {top.headline.title} · {top.headline.publisher}
        </a>
      )}
      {m.causes.length > 1 && (
        <p className="m-0 text-tiny text-fg-subtle">Also considered: {m.causes.slice(1, 4).map((c) => c.title).join("; ")}</p>
      )}
    </li>
  );
}

function Lessons() {
  const res = useApi<{ lessons: Lesson[] }>("/world/lessons");
  const [jobId, setJobId] = useJobId("world_learn");
  const { job } = useJob(jobId, (j) => {
    setJobId(null);
    if (j.status === "done") toast.success("Kairos re-measured what world events did.");
    res.reload();
  });
  async function learn() {
    try {
      const r = await postJson<{ job_id: string }>("/world/learn", {});
      setJobId(r.job_id);
    } catch (err) {
      toast.error(toEnvelope(err).message);
    }
  }
  const rows = res.status === "ready" ? res.data.lessons.filter((l) => l.n >= 2).slice(0, 14) : [];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GraduationCap className="size-4 text-accent-strong" aria-hidden="true" />
          What past events actually did
        </CardTitle>
        <Button size="sm" variant="ghost" onClick={() => void learn()} disabled={jobId !== null}>
          Learn now
        </Button>
      </CardHeader>
      <CardBody className="flex flex-col gap-3">
        {job && <JobProgress job={job} />}
        <p className="m-0 text-small text-fg-muted">
          Measured on saved prices: the average move over the next 5 trading days, for the market itself and for sectors and groups beyond the market. Every new event is measured too, so this keeps learning.
        </p>
        {res.status === "loading" && <LoadingRows rows={3} />}
        {res.status === "ready" && rows.length === 0 && (
          <p className="m-0 text-small text-fg-subtle">Nothing measured yet: Kairos measures past events once their prices are saved.</p>
        )}
        {rows.length > 0 && (
          <ScrollBox size="lg">
            <table className="w-full border-collapse text-small">
              <thead>
                <tr className="border-b border-hairline text-left text-tiny text-fg-subtle">
                  <th className="py-1.5 font-semibold">Kind of event</th>
                  <th className="py-1.5 font-semibold">Market</th>
                  <th className="py-1.5 font-semibold">What</th>
                  <th className="py-1.5 text-right font-semibold">Events</th>
                  <th className="py-1.5 text-right font-semibold">5 days</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((l) => (
                  <tr key={`${l.scenario}-${l.market}-${l.target}`} className="border-b border-hairline last:border-0">
                    <td className="py-1.5">{l.title}</td>
                    <td className="py-1.5 text-fg-muted">{l.market === "IN" ? "India" : "US"}</td>
                    <td className="py-1.5 text-fg-muted">{l.target === "market" ? "whole market" : l.target.replace("tag:", "").replaceAll("_", " ")}</td>
                    <td className="py-1.5 text-right tabular-nums">{l.n}</td>
                    <td className="py-1.5 text-right">
                      <Change value={l.mean_pct} text={`${l.mean_pct > 0 ? "+" : ""}${l.mean_pct.toFixed(1)}%`} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollBox>
        )}
      </CardBody>
    </Card>
  );
}

function MarketView({ v }: { v: WorldView }) {
  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 flex items-start gap-2 text-[15px]">
        <KairosMark className="mt-1 size-4 shrink-0" />
        <span>{v.sentence}</span>
      </p>
      {v.drivers.length === 0 ? (
        <Card>
          <EmptyState icon={Globe2} title="The world is quiet for this market" body="No world event in the news is strong enough to move it. Kairos keeps reading the news while Agora is open." />
        </Card>
      ) : (
        <ScrollBox size="xl">
          <ul className="m-0 grid list-none grid-cols-1 gap-3 p-0 xl:grid-cols-2">
            {v.drivers.map((d) => (
              <Driver key={d.scenario} d={d} />
            ))}
          </ul>
        </ScrollBox>
      )}
      {v.drivers.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <StockList title="Likely to do better than the market" rows={v.helped} market={v.market} up />
          <StockList title="Likely to do worse than the market" rows={v.hurt} market={v.market} up={false} />
        </div>
      )}
    </div>
  );
}

export default function World() {
  const [market, setMarket] = useState<MarketCode>("IN");
  const res = useApi<WorldResponse>("/world", 120_000);
  const [busy, setBusy] = useState(false);
  async function investigate() {
    setBusy(true);
    try {
      const r = await postJson<{ moves: Move[] }>(`/world/investigate?market=${market}`, {});
      toast.success(r.moves.length ? `Investigated ${r.moves.length} unusual move${r.moves.length > 1 ? "s" : ""}.` : "Nothing unusual on the latest candle.");
      res.reload();
    } catch (err) {
      toast.error(toEnvelope(err).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeader
        title="World"
        subtitle="What's happening in the world, how it travels into each market's sectors and stocks, and why markets moved."
        actions={
          <div className="flex items-center gap-3">
            <Segmented label="Market" value={market} options={MARKETS} onChange={setMarket} />
            <Button onClick={() => void investigate()} disabled={busy}>
              <Search aria-hidden="true" /> Why did it move?
            </Button>
          </div>
        }
      />
      {res.status === "loading" && <LoadingRows rows={6} />}
      {res.status === "error" && <ErrorState error={res.error} onRetry={res.reload} />}
      {res.status === "ready" && (
        <>
          <MarketView v={res.data[market]} />
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="size-4 text-warning" aria-hidden="true" />
                Sudden moves and their cause
              </CardTitle>
              <Link to="/news" className="flex items-center gap-1 text-small text-fg-muted no-underline hover:underline">
                All news <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
            </CardHeader>
            <CardBody>
              {res.data.moves.filter((m) => m.market === market).length === 0 ? (
                <p className="m-0 text-small text-fg-muted">
                  No unusual moves yet. When the market or a sector moves far more than usual, Kairos reads the news around it (and searches the web's news index), checks oil, gold, the dollar and the other market, and writes the most likely cause here.
                </p>
              ) : (
                <ScrollBox size="lg">
                  <ul className="m-0 flex list-none flex-col gap-3 p-0">
                    {res.data.moves
                      .filter((m) => m.market === market)
                      .map((m) => (
                        <MoveCard key={m.id} m={m} />
                      ))}
                  </ul>
                </ScrollBox>
              )}
            </CardBody>
          </Card>
          <Lessons />
        </>
      )}
    </>
  );
}
