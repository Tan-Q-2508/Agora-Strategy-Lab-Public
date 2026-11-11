/**
 * The Kairos desk's own panels (docs/KAIROS.md §9–10): its diary (a thesis when a trade
 * opens, a review when it closes), what it has learned, and its lessons.
 */
import { BookOpen, CheckCircle2, GraduationCap, Lightbulb, RefreshCw, XCircle } from "lucide-react";
import { toast } from "sonner";
import { JobProgress } from "../../components/JobProgress";
import { KairosMark } from "../../components/kairos/KairosMark";
import { EmptyState } from "../../components/states";
import { Button } from "../../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { Pill } from "../../components/ui/pill";
import { postJson, toEnvelope, type MarketCode } from "../../lib/api";
import type { JournalEntry, Learned, LearnedSignal, Lesson } from "../../lib/desk";
import { formatDate, formatDateTime, MARKET_TZ } from "../../lib/format";
import { useJob, useJobId } from "../../lib/useJob";
import { cn } from "../../lib/utils";
import { ScrollBox } from "../../components/ui/scroll-box";

export function Journal({ entries, market }: { entries: JournalEntry[]; market: MarketCode }) {
  const tz = MARKET_TZ[market];
  if (!entries.length) {
    return (
      <EmptyState
        icon={BookOpen}
        title="Nothing in the diary yet"
        body="When Kairos opens a trade it writes down why, with its stop and target. When the trade closes it writes what happened."
      />
    );
  }
  return (
    <ScrollBox size="xl">
      <ol className="m-0 flex list-none flex-col gap-3 p-0">
        {entries.map((j) => {
          const review = j.kind === "review";
          const Icon = review ? (j.won ? CheckCircle2 : XCircle) : Lightbulb;
          return (
            <li key={j.id} className="flex gap-3 rounded-control border border-hairline bg-surface p-3.5">
              <Icon className={cn("mt-0.5 size-4 shrink-0", review ? (j.won ? "text-profit" : "text-loss") : "text-accent")} aria-hidden="true" />
              <div className="flex min-w-0 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-small font-semibold text-fg">{j.symbol ?? "Desk"}</span>
                  <Pill tone={review ? (j.won ? "profit" : "loss") : j.kind === "thesis" ? "accent" : j.text.startsWith("News guard") ? "warning" : "neutral"} className="h-6 px-2 text-tiny">
                    {review ? (j.won ? "Review · worked" : "Review · didn't work") : j.kind === "thesis" ? "Thesis" : j.kind === "note" ? (j.text.startsWith("News guard") ? "News guard" : "Reflection") : "Day"}
                  </Pill>
                  {j.score !== null && <span className="text-tiny tabular-nums text-fg-subtle">score {j.score >= 0 ? "+" : "−"}{Math.abs(j.score).toFixed(0)}</span>}
                  <span className="text-tiny text-fg-subtle">{formatDateTime(j.at, tz)}</span>
                </div>
                <p className="m-0 text-small leading-relaxed text-fg-muted">{j.text}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </ScrollBox>
  );
}

function SignalLine({ s }: { s: LearnedSignal }) {
  const good = s.edge >= 0;
  return (
    <li className="flex items-start gap-3">
      <span
        className={cn("mt-1 inline-flex h-5 min-w-12 items-center justify-center rounded-full px-1.5 text-tiny font-semibold tabular-nums", good ? "bg-profit-soft text-profit-soft-fg" : "bg-loss-soft text-loss-soft-fg")}
        title="How much Kairos leans on this signal now (×1 = average)"
      >
        ×{s.weight.toFixed(1)}
      </span>
      <p className="m-0 text-small text-fg-muted">{s.text}</p>
    </li>
  );
}

/** "What Kairos learned": the signals that have worked best and worst, and a Retrain button. */
export function LearnedCard({ learned, lessons, onRetrained }: { learned: Learned; lessons: Lesson[]; onRetrained?: () => void }) {
  const [jobId, setJobId] = useJobId("kairos_train");
  const { job } = useJob(jobId, (j) => {
    setJobId(null);
    if (j.status === "done") {
      toast.success("Kairos re-measured every signal.");
      onRetrained?.();
    }
  });
  const t = learned.trained;
  const tz = MARKET_TZ[learned.market];

  async function retrain() {
    try {
      const r = await postJson<{ job_id: string }>("/kairos/train", { market: learned.market, timeframe: learned.timeframe });
      setJobId(r.job_id);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle className="flex items-center gap-2">
          <GraduationCap className="size-4 text-accent" aria-hidden="true" />
          What Kairos learned
        </CardTitle>
        <Button size="sm" variant="ghost" onClick={() => void retrain()} disabled={jobId !== null}>
          <RefreshCw aria-hidden="true" />
          Study again
        </Button>
      </CardHeader>
      <CardBody className="flex flex-col gap-4">
        {job && <JobProgress job={job} />}
        {t ? (
          <p className="m-0 text-small text-fg-muted">
            Studied {t.candles.toLocaleString()} candles of {learned.market === "IN" ? "Indian" : "US"} stocks on {formatDate(t.at, tz)}. On any candle, the price was higher {t.horizon} candles later{" "}
            {Math.round(100 * (t.base_rate ?? 0.5))}% of the time: a signal is only useful when it beats that.
            {learned.paper_trades > 0 && ` ${learned.paper_trades} of its own paper trades have taught it since.`}
          </p>
        ) : (
          <p className="m-0 text-small text-fg-muted">Kairos hasn't studied this market's history yet. It does so the first time you use it here.</p>
        )}
        {learned.best.length > 0 && (
          <div className="flex flex-col gap-2">
            <h3 className="m-0 text-small font-semibold text-fg">Leans on</h3>
            <ScrollBox size="sm">
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {learned.best.map((s) => (
                  <SignalLine key={s.key} s={s} />
                ))}
              </ul>
            </ScrollBox>
          </div>
        )}
        {learned.worst.length > 0 && (
          <div className="flex flex-col gap-2">
            <h3 className="m-0 text-small font-semibold text-fg">Distrusts</h3>
            <ScrollBox size="sm">
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {learned.worst.map((s) => (
                  <SignalLine key={s.key} s={s} />
                ))}
              </ul>
            </ScrollBox>
          </div>
        )}
        {learned.exits && (
          <div className="flex flex-col gap-1">
            <h3 className="m-0 text-small font-semibold text-fg">Exits it trades with</h3>
            <p className="m-0 text-small text-fg">{learned.exits.plan.charAt(0).toUpperCase() + learned.exits.plan.slice(1)}.</p>
            <p className="m-0 text-small text-fg-muted">
              {learned.exits.why.charAt(0).toUpperCase() + learned.exits.why.slice(1)}.
            </p>
          </div>
        )}
        {learned.judge && (
          <div className="flex flex-col gap-1">
            <h3 className="m-0 text-small font-semibold text-fg">Trade judge</h3>
            <p className="m-0 text-small text-fg-muted">{learned.judge.text}</p>
          </div>
        )}
        {lessons.length > 0 && (
          <div className="flex flex-col gap-2">
            <h3 className="m-0 text-small font-semibold text-fg">Lessons from its own trades</h3>
            <ScrollBox size="sm">
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {lessons.map((l) => (
                  <li key={l.id} className="flex items-start gap-2 text-small text-fg-muted">
                    <KairosMark className="mt-0.5 size-4 shrink-0" />
                    {l.text}
                  </li>
                ))}
              </ul>
            </ScrollBox>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
