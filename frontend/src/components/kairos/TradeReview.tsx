import { AlertTriangle, CheckCircle2, ShieldCheck, Sparkles, Wand2 } from "lucide-react";
import { Link } from "react-router";
import { postJson } from "../../lib/api";
import { formatMoney, formatPercent, MARKET_CURRENCY } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { useJob, useJobId } from "../../lib/useJob";
import { cn } from "../../lib/utils";
import { JobProgress } from "../JobProgress";
import { LoadingRows } from "../states";
import { Button } from "../ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../ui/card";
import { Pill } from "../ui/pill";
import { KairosMark } from "./KairosMark";
import { ScrollBox } from "../ui/scroll-box";

interface Part {
  trades: number;
  win_rate: number | null;
  net: number;
  expectancy?: number | null;
}

interface FilterRule {
  key: string;
  text: string;
  held_up: boolean;
  test: { before: Part; after: Part };
}

export interface Review {
  trades: number;
  headline: string;
  lines: string[];
  advice: string[];
  money?: { gross: number; charges: number; net: number; cost_share: number | null; avg_gross: number; avg_charges: number; trades_per_month: number | null; level: "ok" | "warn" | "bad" };
  wins?: { win_rate: number; payoff: number | null; breakeven_win_rate: number | null; expectancy: number; best3_share: number | null; net_without_best3: number; longest_losing_streak: number };
  exits?: { by_reason: { reason: string; label: string; count: number; win_rate: number; avg_net: number }[]; lines: string[] };
  failure_reasons?: { text: string; key: string }[];
  filters?: { note: string; rules: FilterRule[] };
  losers?: { symbol: string; side: string; entry_ts: number; net: number; return_pct: number; exit_reason: string; why: string[] }[];
}

export interface TradeCheckSummary {
  mode: string;
  checked: number;
  skipped: number;
  skipped_followed: number;
  skipped_would_have_won: number;
  skipped_would_have_lost: number;
  proven?: boolean;
  judged?: number;
  skill?: number;
  top_reasons: { words: string; count: number }[];
}

interface Improvement {
  changed: boolean;
  headline: string;
  lines: string[];
  to_version?: number;
  strategy_id: number;
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "profit" | "loss" | "warning" }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-tile bg-surface-2 px-3 py-2.5">
      <span className="text-tiny text-fg-subtle">{label}</span>
      <span className={cn("text-[18px] leading-6 font-semibold tabular-nums", tone === "profit" && "text-profit", tone === "loss" && "text-loss", tone === "warning" && "text-warning")}>{value}</span>
      {sub && <span className="text-tiny text-fg-muted">{sub}</span>}
    </div>
  );
}

const rate = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

/** What the trade check did during this run (KAIROS §16). */
export function TradeCheckNote({ tc }: { tc: TradeCheckSummary }) {
  const followed = tc.skipped_followed;
  return (
    <div className="flex gap-2.5 rounded-control bg-info-soft/50 p-3 text-small">
      <ShieldCheck className="mt-0.5 size-4 shrink-0 text-info" aria-hidden="true" />
      <div className="flex flex-col gap-1">
        <p className="m-0 font-semibold">
          Kairos's trade check ({tc.mode}): skipped {tc.skipped} of {tc.checked} signals
        </p>
        {tc.proven === false && tc.mode !== "learn" && (
          <p className="m-0 text-fg-muted">
            It hasn't yet proven it can tell good trades from bad for this strategy ({tc.judged ?? 0} judged results; it needs 30 and a measurable edge), so it only watched and learned.
          </p>
        )}
        {followed > 0 && (
          <p className="m-0 text-fg-muted">
            Kairos followed the skipped signals anyway: {tc.skipped_would_have_lost} would have lost and {tc.skipped_would_have_won} would have won.
          </p>
        )}
        {tc.top_reasons.length > 0 && <p className="m-0 text-fg-muted">Most skipped because {tc.top_reasons.slice(0, 3).map((r) => `${r.words} (${r.count})`).join(", ")}.</p>}
      </div>
    </div>
  );
}

/** Kairos's review of a backtest's or paper session's trades, with "Improve with Kairos". */
export function TradeReview({ kind, refId, market, strategyId, canImprove }: { kind: "backtest" | "paper"; refId: number; market: "IN" | "US"; strategyId?: number; canImprove?: boolean }) {
  const r = useApi<{ review: Review | null }>(`/kairos/review/${kind}/${refId}`);
  const [jobId, setJobId] = useJobId("kairos_review", `${kind}:${refId}`);
  const [improveId, setImproveId] = useJobId(strategyId ? "kairos_improve" : null, strategyId ? `strategy:${strategyId}` : null);
  const review = useJob(jobId, () => r.reload());
  const improve = useJob<Improvement>(improveId);
  const cur = MARKET_CURRENCY[market];
  const money = (v: number) => formatMoney(v, cur, 0);
  const start = () => postJson<{ job_id: string }>(`/kairos/review/${kind}/${refId}`).then((j) => setJobId(j.job_id));
  const startImprove = () => strategyId && postJson<{ job_id: string }>(`/kairos/improve/${strategyId}`).then((j) => setImproveId(j.job_id));

  const rv = r.status === "ready" ? r.data.review : null;
  const running = review.job && (review.job.status === "running" || review.job.status === "queued");
  return (
    <Card id="kairos-review">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KairosMark />
          Kairos's review: why the trades went the way they did
        </CardTitle>
        {rv && (
          <Button size="sm" variant="ghost" onClick={start} disabled={Boolean(running)}>
            Review again
          </Button>
        )}
      </CardHeader>
      <CardBody className="flex flex-col gap-4">
        {r.status === "loading" && <LoadingRows rows={3} />}
        {running && review.job && <JobProgress job={review.job} />}
        {r.status === "ready" && !rv && !running && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="m-0 max-w-[640px] text-small text-fg-muted">
              Kairos reads every trade and the market around it: how much costs ate, whether a few lucky trades carried the result, and in which conditions the strategy's trades failed although all its rules were met. While Agora is open it also does this on its own.
            </p>
            <Button variant="soft" onClick={start}>
              <Sparkles aria-hidden="true" />
              Review with Kairos
            </Button>
          </div>
        )}
        {rv && rv.trades === 0 && <p className="m-0 text-small text-fg-muted">{rv.headline}</p>}
        {rv && rv.trades > 0 && (
          <>
            <div className="grid grid-cols-4 gap-3">
              {rv.money && (
                <Tile
                  label="Costs took"
                  value={rv.money.cost_share === null ? money(rv.money.charges) : `${Math.round(rv.money.cost_share * 100)}% of profit`}
                  sub={`${money(rv.money.avg_charges)} a trade vs ${money(rv.money.avg_gross)} earned before costs`}
                  tone={rv.money.level === "bad" ? "loss" : rv.money.level === "warn" ? "warning" : undefined}
                />
              )}
              {rv.wins && <Tile label="Win rate" value={rate(rv.wins.win_rate)} sub={rv.wins.breakeven_win_rate !== null ? `needs ${rate(rv.wins.breakeven_win_rate)} to break even` : undefined} tone={rv.wins.breakeven_win_rate !== null && rv.wins.win_rate < rv.wins.breakeven_win_rate ? "loss" : "profit"} />}
              {rv.wins && <Tile label="Average trade after costs" value={money(rv.wins.expectancy)} sub={rv.wins.payoff ? `wins are ${rv.wins.payoff.toFixed(1)}× the losses` : undefined} tone={rv.wins.expectancy >= 0 ? "profit" : "loss"} />}
              {rv.wins && (
                <Tile
                  label="Without the best 3 trades"
                  value={money(rv.wins.net_without_best3)}
                  sub={rv.wins.best3_share !== null ? `they made ${Math.round(rv.wins.best3_share * 100)}% of the profit` : `longest losing streak ${rv.wins.longest_losing_streak}`}
                  tone={rv.wins.net_without_best3 >= 0 ? "profit" : "loss"}
                />
              )}
            </div>
            <ScrollBox size="md">
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {rv.lines.map((l) => (
                  <li key={l} className="flex gap-2 text-small leading-5 text-fg">
                    <span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-accent" />
                    {l}
                  </li>
                ))}
              </ul>
            </ScrollBox>
            <div className="grid grid-cols-2 gap-5">
              {rv.filters && (
                <section className="flex flex-col gap-2">
                  <h3 className="m-0 text-small font-semibold">Filters tested on trades they never saw</h3>
                  <p className="m-0 text-tiny text-fg-subtle">{rv.filters.note}</p>
                  {rv.filters.rules.map((f) => (
                    <div key={f.text} className="flex flex-col gap-1 rounded-control border border-hairline p-2.5">
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-small">{f.text}</span>
                        <Pill tone={f.held_up ? "profit" : "neutral"} className="h-6 shrink-0 px-2 text-tiny">
                          {f.held_up ? "Held up" : "Didn't hold up"}
                        </Pill>
                      </div>
                      <span className="text-tiny tabular-nums text-fg-muted">
                        Unseen trades: win rate {rate(f.test.before.win_rate)} → {rate(f.test.after.win_rate)}, after costs {money(f.test.before.net)} → {money(f.test.after.net)}, {f.test.before.trades} → {f.test.after.trades} trades
                      </span>
                    </div>
                  ))}
                </section>
              )}
              {rv.losers && rv.losers.length > 0 && (
                <section className="flex flex-col gap-2">
                  <h3 className="m-0 text-small font-semibold">The worst losing trades, explained</h3>
                  <ul className="m-0 flex max-h-[260px] list-none flex-col gap-2 overflow-y-auto p-0">
                    {rv.losers.map((t) => (
                      <li key={`${t.symbol}-${t.entry_ts}`} className="flex flex-col gap-0.5 text-small">
                        <span>
                          <b className="font-semibold">{t.symbol}</b> <span className="text-fg-subtle">{new Date(t.entry_ts).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })} · {t.exit_reason}</span>{" "}
                          <span className="tabular-nums text-loss">{money(t.net)} ({formatPercent(t.return_pct / 100, 1)})</span>
                        </span>
                        <span className="text-fg-muted">{t.why.join("; ")}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
            {rv.exits && rv.exits.by_reason.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {rv.exits.by_reason.map((x) => (
                  <Pill key={x.reason} className="h-7 text-tiny">
                    {x.label}: {x.count} trades, {rate(x.win_rate)} won, avg {money(x.avg_net)}
                  </Pill>
                ))}
              </div>
            )}
            {rv.advice.length > 0 && (
              <div className="flex flex-col gap-1.5 rounded-control bg-accent-soft/60 p-3">
                {rv.advice.map((a) => (
                  <p key={a} className="m-0 flex gap-2 text-small text-fg">
                    <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-accent-soft-fg" aria-hidden="true" />
                    {a}
                  </p>
                ))}
              </div>
            )}
            {canImprove && strategyId && rv.filters?.rules.some((f) => f.held_up) && (
              <div className="flex flex-col gap-2 border-t border-hairline pt-3">
                {!improve.job && (
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="m-0 max-w-[640px] text-small text-fg-muted">
                      Kairos can add the filters that held up as ordinary rules, backtest again, and save a new version only if it made at least as much after costs and won more often on the part of the period the filters never saw. Your current version is kept.
                    </p>
                    <Button variant="primary" onClick={startImprove}>
                      <Wand2 aria-hidden="true" />
                      Improve with Kairos
                    </Button>
                  </div>
                )}
                {improve.job && improve.job.status !== "done" && <JobProgress job={improve.job} />}
                {improve.job?.status === "done" && improve.job.result && (
                  <div className="flex flex-col gap-1">
                    <p className="m-0 flex items-center gap-2 text-small font-semibold">
                      {improve.job.result.changed ? <CheckCircle2 className="size-4 text-profit" aria-hidden="true" /> : <ShieldCheck className="size-4 text-fg-muted" aria-hidden="true" />}
                      {improve.job.result.headline}
                    </p>
                    {improve.job.result.lines.map((l) => (
                      <p key={l} className="m-0 text-small text-fg-muted">
                        {l}
                      </p>
                    ))}
                    {improve.job.result.changed && (
                      <Link to={`/backtests/new?strategy=${strategyId}`} className="text-small font-semibold text-accent-soft-fg">
                        Backtest the new version
                      </Link>
                    )}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
