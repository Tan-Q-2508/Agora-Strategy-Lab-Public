/**
 * Portfolio (docs/PORTFOLIO.md): one budget in one market, split by Agora's allocator (tested
 * code, never the AI) into sleeves, each a strategy on its own stocks, plus cash kept back. Plan
 * it, backtest it as a whole, paper trade it, and watch the opportunities Kairos and Metis find.
 */
import { motion } from "framer-motion";
import { ArrowUpRight, FlaskConical, PieChart, Play, Plus, RefreshCw, Search, Square } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { ForwardChecks } from "../components/checks/ForwardChecks";
import { JobProgress } from "../components/JobProgress";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Change } from "../components/ui/change";
import { Dialog } from "../components/ui/dialog";
import { Field, Input, NumberInput } from "../components/ui/input";
import { Pill } from "../components/ui/pill";
import { Segmented } from "../components/ui/segmented";
import { getJson, patchJson, postJson, toEnvelope, type MarketCode } from "../lib/api";
import { formatAgo, formatDateTime, formatMoney, formatPercent, formatSignedMoney, MARKET_CURRENCY } from "../lib/format";
import { spring } from "../lib/motion";
import { hasBacktest, hasPlan, METHOD_LABEL, RISK_LABEL, SOURCE_WORDS, STATUS_WORDS, type Method, type Opportunity, type PortfolioDetail, type PortfolioSummary, type Risk } from "../lib/portfolio";
import { useApi } from "../lib/useApi";
import { useJob, useJobId } from "../lib/useJob";
import { AllocationDonut, PortfolioEquity } from "./portfolio/charts";
import { ScrollBox } from "../components/ui/scroll-box";

const DEFAULT_BUDGET: Record<MarketCode, number> = { IN: 100_000, US: 10_000 };

/** A share or a level, without a sign (weights, volatility). */
const share = (x: number) => `${Math.round(x * 100)}%`;

/** A sleeve's stocks; none listed means a ranking that picks from the whole index monthly. */
function stocksText(symbols: string[]): string {
  if (!symbols.length) return "the whole index (re-ranked monthly)";
  return symbols.slice(0, 5).join(", ") + (symbols.length > 5 ? ` and ${symbols.length - 5} more` : "");
}

function NewPortfolio({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const navigate = useNavigate();
  const [market, setMarket] = useState<MarketCode>("IN");
  const [budget, setBudget] = useState<number | null>(DEFAULT_BUDGET.IN);
  const [risk, setRisk] = useState<Risk>("balanced");
  const [method, setMethod] = useState<Method>("mix");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  async function create() {
    setBusy(true);
    try {
      const r = await postJson<{ portfolio: PortfolioSummary; job_id: string }>("/portfolios", { market, budget, risk, name, method });
      onOpenChange(false);
      navigate(`/portfolio/${r.portfolio.id}?job=${r.job_id}`);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="New portfolio" description="Give Kairos and Metis a budget. Agora's allocator splits it across strategies and stocks that held up on years they weren't chosen on. Paper money only.">
      <div className="flex flex-col gap-4">
        <Field label="Market">
          <Segmented
            label="Market"
            value={market}
            onChange={(m) => (setMarket(m), setBudget(DEFAULT_BUDGET[m]))}
            options={[
              { value: "IN", label: "India (₹)" },
              { value: "US", label: "US ($)" },
            ]}
          />
        </Field>
        <Field label="Budget" htmlFor="pf-budget" hint="Any amount. A small budget gets fewer, larger sleeves so every trade can buy at least one share.">
          <NumberInput id="pf-budget" value={budget} onChange={setBudget} min={1} />
        </Field>
        <Field label="How to spread it" hint={METHOD_LABEL[method].hint}>
          <Segmented label="How to spread it" value={method} onChange={setMethod} options={(["mix", "momentum", "low_volatility"] as const).map((m) => ({ value: m, label: METHOD_LABEL[m].label }))} />
        </Field>
        <Field label="Risk" hint={RISK_LABEL[risk].hint}>
          <Segmented
            label="Risk"
            value={risk}
            onChange={setRisk}
            options={(["careful", "balanced", "bold"] as const).map((r) => ({ value: r, label: RISK_LABEL[r].label }))}
          />
        </Field>
        <Field label="Name (optional)" htmlFor="pf-name">
          <Input id="pf-name" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} placeholder={market === "IN" ? "India portfolio" : "US portfolio"} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" disabled={busy || !budget || budget <= 0} onClick={() => void create()}>
            <PieChart aria-hidden="true" />
            Plan it
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function PortfolioCard({ p }: { p: PortfolioSummary }) {
  const cur = MARKET_CURRENCY[p.market];
  const st = STATUS_WORDS[p.status];
  return (
    <motion.div layout transition={spring}>
      <Link to={`/portfolio/${p.id}`} className="block rounded-card no-underline focus-visible:outline-2 focus-visible:outline-accent">
        <Card className="gap-3 p-5 transition-shadow hover:shadow-e2">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 flex-col gap-1">
              <p className="m-0 truncate text-heading font-semibold text-fg">{p.name}</p>
              <p className="m-0 text-small text-fg-muted">
                {formatMoney(p.budget, cur, 0)} · {RISK_LABEL[p.risk].label} · {p.method && p.method !== "mix" ? METHOD_LABEL[p.method].label : `${p.sleeves_planned} sleeve${p.sleeves_planned === 1 ? "" : "s"}`}
              </p>
            </div>
            <Pill tone={st.tone} className="h-7 px-2.5 text-tiny">
              {st.label}
            </Pill>
          </div>
          {p.live ? (
            <p className="m-0 text-small text-fg">
              Worth {formatMoney(p.live.equity, cur, 0)} <Change value={p.live.return} text={formatPercent(p.live.return)} />
            </p>
          ) : p.backtest_return !== null ? (
            <p className="m-0 text-small text-fg-muted">
              Backtest: <Change value={p.backtest_return} text={formatPercent(p.backtest_return)} />
            </p>
          ) : null}
        </Card>
      </Link>
    </motion.div>
  );
}

function OpportunityRow({ o, onChange }: { o: Opportunity; onChange: () => void }) {
  const navigate = useNavigate();
  async function act(path: string, done: string, then?: (r: { run_id?: number }) => void) {
    try {
      const r = await postJson<{ run_id?: number }>(path);
      toast.success(done);
      then?.(r);
      onChange();
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }
  return (
    <li className="flex flex-col gap-1.5 border-t border-hairline py-3 first:border-t-0" aria-label={`${o.name} on ${stocksText(o.symbols)}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="m-0 font-semibold">
          <Link to={`/strategies/${o.strategy_id}`}>{o.name}</Link>
          <span className="font-normal text-fg-muted"> on {stocksText(o.symbols)}</span>
        </p>
        <div className="flex gap-1.5">
          {o.status === "in_portfolio" && <Pill tone="profit" className="h-6 px-2 text-tiny">In a portfolio</Pill>}
          <Pill className="h-6 px-2 text-tiny">{SOURCE_WORDS[o.source]}</Pill>
        </div>
      </div>
      <p className="m-0 text-small text-fg-muted">{o.evidence}</p>
      <div className="flex gap-2">
        <Button size="sm" variant="soft" onClick={() => void act(`/opportunities/${o.id}/backtest`, "Backtest started.", (r) => r.run_id && navigate(`/backtests/${r.run_id}`))}>
          <FlaskConical aria-hidden="true" />
          Backtest
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void act(`/opportunities/${o.id}/dismiss`, "Dismissed. It won't be offered again.")}>
          Dismiss
        </Button>
      </div>
    </li>
  );
}

function Opportunities({ items, onChange }: { items: Opportunity[]; onChange: () => void }) {
  const [jobId, setJobId] = useJobId("opportunity_scan");
  const { job } = useJob<{ note?: string }>(jobId, (j) => {
    setJobId(null);
    if (j.status === "done" && j.result?.note) toast.success(j.result.note);
    onChange();
  });
  async function scan() {
    try {
      setJobId((await postJson<{ job_id: string }>("/opportunities/scan")).job_id);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Opportunities</CardTitle>
        <Button size="sm" variant="secondary" disabled={jobId !== null} onClick={() => void scan()}>
          <Search aria-hidden="true" />
          Find new opportunities
        </Button>
      </CardHeader>
      <CardBody className="flex flex-col gap-2">
        <p className="m-0 text-small text-fg-muted">
          Your strategies on stocks where they held up: stocks chosen on the first 70% of the years, then judged on the last 30% they weren't chosen on, with a luck check. Metis runs this search on its own too. No new strategies are made: it's the same strategy on other stocks.
        </p>
        {job && <JobProgress job={job} />}
        {items.length === 0 ? (
          <p className="m-0 text-small text-fg-subtle">None open yet. Click Find new opportunities, or let Metis look while Agora is open.</p>
        ) : (
          <ScrollBox size="lg">
            <ul className="m-0 list-none p-0">
              {items.map((o) => (
                <OpportunityRow key={o.id} o={o} onChange={onChange} />
              ))}
            </ul>
          </ScrollBox>
        )}
      </CardBody>
    </Card>
  );
}

function Detail({ id }: { id: string }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const d = useApi<{ portfolio: PortfolioDetail }>(`/portfolios/${id}`, 10_000);
  const [jobId, setJobId] = useJobId("portfolio_plan,portfolio_backtest", `portfolio:${id}`, params.get("job"));
  const [preview, setPreview] = useState<{ lines: string[] } | null>(null);
  const { job } = useJob<{ note?: string }>(jobId, () => {
    setJobId(null);
    d.reload();
  });
  if (d.status === "loading") return <LoadingRows rows={6} />;
  if (d.status === "error") return <ErrorState error={d.error} onRetry={d.reload} />;
  const p = d.data.portfolio;
  const cur = MARKET_CURRENCY[p.market];
  const st = STATUS_WORDS[p.status];

  async function run(path: string, ok?: string) {
    try {
      const r = await postJson<{ job_id?: string }>(path);
      if (r.job_id) setJobId(r.job_id);
      else if (ok) toast.success(ok);
      d.reload();
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }
  async function showPreview() {
    try {
      setPreview(await getJson<{ lines: string[] }>(`/portfolios/${p.id}/rebalance`));
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }
  async function manage(on: boolean) {
    try {
      await patchJson(`/portfolios/${p.id}`, { manage: on });
      d.reload();
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }

  return (
    <>
      <PageHeader
        title={p.name}
        subtitle={`${p.market === "IN" ? "India" : "US"} · budget ${formatMoney(p.budget, cur, 0)} · ${RISK_LABEL[p.risk].label} risk${p.method && p.method !== "mix" ? ` · ${METHOD_LABEL[p.method].label} ranking` : ""} · paper money only`}
        actions={
          <>
            <Pill tone={st.tone} className="h-9 px-3">
              {st.label}
            </Pill>
            {p.status !== "paper" && (
              <>
                <Button variant="secondary" disabled={jobId !== null} onClick={() => void run(`/portfolios/${p.id}/plan`)}>
                  <RefreshCw aria-hidden="true" />
                  Plan again
                </Button>
                <Button variant="secondary" disabled={jobId !== null || !hasPlan(p) || p.plan.sleeves.length === 0} onClick={() => void run(`/portfolios/${p.id}/backtest`)}>
                  <FlaskConical aria-hidden="true" />
                  Backtest it
                </Button>
                <Button variant="primary" disabled={jobId !== null || !hasPlan(p) || p.plan.sleeves.length === 0} onClick={() => void run(`/portfolios/${p.id}/paper/start`, "Paper trading started.")}>
                  <Play aria-hidden="true" />
                  Paper trade it
                </Button>
              </>
            )}
            {p.status === "paper" && (
              <>
                <Button variant="secondary" onClick={() => void showPreview()}>
                  Preview rebalance
                </Button>
                <Button variant="danger" onClick={() => void run(`/portfolios/${p.id}/paper/stop`, "Paper trading stopped.")}>
                  <Square aria-hidden="true" />
                  Stop
                </Button>
              </>
            )}
          </>
        }
      />
      {job && <JobProgress job={job} />}
      {preview && (
        <Card>
          <CardHeader>
            <CardTitle>If it rebalanced now</CardTitle>
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" onClick={() => setPreview(null)}>
                Close
              </Button>
              <Button size="sm" variant="primary" onClick={() => (setPreview(null), void run(`/portfolios/${p.id}/rebalance`, "Rebalanced: only free cash moved."))}>
                Rebalance now
              </Button>
            </div>
          </CardHeader>
          <CardBody>
            <ScrollBox size="sm">
              <ul className="m-0 pl-5 text-small">
                {preview.lines.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </ScrollBox>
          </CardBody>
        </Card>
      )}
      <div className="grid grid-cols-[minmax(0,1fr)_380px] items-start gap-5">
        <div className="flex min-w-0 flex-col gap-5">
          {p.live && (
            <Card>
              <CardHeader>
                <CardTitle>Paper trading now</CardTitle>
                <Segmented label="Manage on its own" value={p.manage ? "on" : "off"} onChange={(v) => void manage(v === "on")} options={[{ value: "on", label: "Manages itself" }, { value: "off", label: "Hands off" }]} />
              </CardHeader>
              <CardBody className="flex flex-col gap-3">
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <p className="m-0 text-tiny text-fg-subtle">Worth now</p>
                    <p className="m-0 text-[22px] font-bold tabular-nums">{formatMoney(p.live.equity, cur, 0)}</p>
                  </div>
                  <div>
                    <p className="m-0 text-tiny text-fg-subtle">Profit or loss</p>
                    <p className="m-0 text-[22px] tabular-nums">
                      <Change value={p.live.pnl} text={formatSignedMoney(p.live.pnl, cur, 0)} />
                    </p>
                  </div>
                  <div>
                    <p className="m-0 text-tiny text-fg-subtle">Cash kept back</p>
                    <p className="m-0 text-[22px] tabular-nums">{formatMoney(p.live.cash, cur, 0)}</p>
                  </div>
                </div>
                <ScrollBox size="md">
                  <ul className="m-0 list-none p-0">
                    {p.sleeves.map((s) => (
                      <li key={s.id} className="flex items-center justify-between gap-3 border-t border-hairline py-2 text-small first:border-t-0">
                        <span>
                          {stocksText(s.symbols)}
                          {s.status !== "active" && <span className="text-fg-subtle"> · {s.status === "winding_down" ? "winding down" : "retired"}</span>}
                        </span>
                        <span className="flex items-center gap-3 tabular-nums">
                          {s.equity !== null && formatMoney(s.equity, cur, 0)}
                          {s.session_id && (
                            <Link to={`/paper/${s.session_id}`} className="inline-flex items-center gap-1">
                              Session <ArrowUpRight className="size-3.5" aria-hidden="true" />
                            </Link>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </ScrollBox>
                <p className="m-0 text-tiny text-fg-subtle">
                  {p.manage
                    ? "While Agora is open it rebalances monthly (moving only free cash), winds down a sleeve whose loss passes twice its backtest's worst drop, and adds new opportunities that pass the tests."
                    : "Hands off: it still rebalances monthly, but won't retire or add sleeves on its own."}
                </p>
              </CardBody>
            </Card>
          )}
          <Card>
            <CardHeader>
              <CardTitle>The plan</CardTitle>
              {hasPlan(p) && p.plan.made_at && <span className="text-tiny text-fg-subtle">made {formatAgo(p.plan.made_at)}</span>}
            </CardHeader>
            <CardBody className="flex flex-col gap-4">
              {!hasPlan(p) ? (
                <p className="m-0 text-small text-fg-muted">Planning… the allocator is testing each candidate as a sleeve.</p>
              ) : p.plan.sleeves.length === 0 ? (
                <EmptyState
                  icon={PieChart}
                  title="Nothing passed the tests yet"
                  body={p.plan.notes[0] ?? "No strategy held up on unseen years in this market. Find new opportunities or build strategies, then plan again."}
                  action={
                    <Button asChild size="sm" variant="secondary">
                      <Link to="/strategies">Your strategies</Link>
                    </Button>
                  }
                />
              ) : (
                <>
                  <div className="grid grid-cols-[220px_minmax(0,1fr)] items-center gap-5">
                    <AllocationDonut plan={p.plan} />
                    <div className="grid grid-cols-2 gap-3 text-small">
                      <div className="rounded-control bg-surface-2 p-3">
                        <p className="m-0 text-tiny text-fg-subtle">Invested</p>
                        <p className="m-0 text-heading font-semibold tabular-nums">{formatMoney(p.plan.invested, cur, 0)}</p>
                      </div>
                      <div className="rounded-control bg-surface-2 p-3">
                        <p className="m-0 text-tiny text-fg-subtle">Kept in cash</p>
                        <p className="m-0 text-heading font-semibold tabular-nums">{formatMoney(p.plan.cash, cur, 0)}</p>
                      </div>
                      {p.plan.estimate.volatility !== undefined && (
                        <div className="rounded-control bg-surface-2 p-3">
                          <p className="m-0 text-tiny text-fg-subtle">Expected swings (a year)</p>
                          <p className="m-0 text-heading font-semibold tabular-nums">{share(p.plan.estimate.volatility)}</p>
                        </div>
                      )}
                      {p.plan.estimate.diversification !== undefined && (
                        <div className="rounded-control bg-surface-2 p-3">
                          <p className="m-0 text-tiny text-fg-subtle">Diversification</p>
                          <p className="m-0 text-heading font-semibold tabular-nums">{p.plan.estimate.diversification.toFixed(2)}×</p>
                        </div>
                      )}
                    </div>
                  </div>
                  <ScrollBox size="md">
                    <ul className="m-0 flex list-none flex-col gap-2 p-0">
                      {p.plan.sleeves.map((s) => (
                        <li key={s.key} className="rounded-control border border-hairline p-3" aria-label={`Sleeve ${s.name}`}>
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="m-0 font-semibold">
                              <Link to={`/strategies/${s.strategy_id}`}>{s.name}</Link>
                              <span className="font-normal text-fg-muted"> on {stocksText(s.symbols)}</span>
                            </p>
                            <p className="m-0 tabular-nums">
                              {formatMoney(s.capital, cur, 0)} <span className="text-fg-subtle">· {share(s.weight)}</span>
                            </p>
                          </div>
                          <ul className="m-0 mt-1 pl-5 text-small text-fg-muted">
                            {s.reasons.map((r) => (
                              <li key={r}>{r}</li>
                            ))}
                          </ul>
                        </li>
                      ))}
                    </ul>
                  </ScrollBox>
                  {p.plan.overlaps.length > 0 && <p className="m-0 text-small text-warning">{p.plan.overlaps.join(" ")}</p>}
                  <p className="m-0 text-tiny text-fg-subtle">{p.plan.notes.join(" ")} Every number here comes from Agora's tests; the AI never sets a weight.</p>
                </>
              )}
              {hasPlan(p) && p.plan.left_out.length > 0 && (
                <details className="text-small">
                  <summary className="cursor-pointer text-fg-muted">Left out ({p.plan.left_out.length}) and why</summary>
                  <ScrollBox size="sm">
                    <ul className="mt-2 mb-0 pl-5 text-fg-muted">
                      {p.plan.left_out.map((x) => (
                        <li key={x.name + x.reason}>
                          <span className="text-fg">{x.name}</span>: {x.reason}
                        </li>
                      ))}
                    </ul>
                  </ScrollBox>
                </details>
              )}
            </CardBody>
          </Card>
          {hasBacktest(p) && (
            <Card>
              <CardHeader>
                <CardTitle>Backtest of the whole portfolio</CardTitle>
                {p.backtest.made_at && <span className="text-tiny text-fg-subtle">{formatAgo(p.backtest.made_at)}</span>}
              </CardHeader>
              <CardBody className="flex flex-col gap-3">
                <p className="m-0 text-body">
                  {formatMoney(p.backtest.budget, cur, 0)} became <strong>{formatMoney(p.backtest.final, cur, 0)}</strong>
                  {p.backtest.metrics.total_return !== null && p.backtest.metrics.total_return !== undefined && (
                    <>
                      {" "}
                      (<Change value={p.backtest.metrics.total_return} text={formatPercent(p.backtest.metrics.total_return)} />)
                    </>
                  )}
                  {p.backtest.metrics.max_drawdown !== null && p.backtest.metrics.max_drawdown !== undefined && <>, worst drop {share(Math.abs(p.backtest.metrics.max_drawdown))}</>}, {p.backtest.rebalances} rebalances.
                </p>
                <PortfolioEquity bt={p.backtest} market={p.market} />
                <ScrollBox size="lg">
                  <table className="w-full border-collapse text-small">
                    <thead>
                      <tr className="text-left text-tiny text-fg-subtle">
                        <th className="py-1 pr-3 font-medium">Sleeve</th>
                        <th className="py-1 pr-3 font-medium">Started with</th>
                        <th className="py-1 pr-3 font-medium">Made</th>
                        <th className="py-1 font-medium">Trades</th>
                      </tr>
                    </thead>
                    <tbody>
                      {p.backtest.sleeves.map((s) => (
                        <tr key={s.name} className="border-t border-hairline">
                          <td className="py-1.5 pr-3">{s.name}</td>
                          <td className="py-1.5 pr-3 tabular-nums">{formatMoney(s.capital, cur, 0)}</td>
                          <td className="py-1.5 pr-3 tabular-nums">
                            <Change value={s.made} text={formatSignedMoney(s.made, cur, 0)} />
                          </td>
                          <td className="py-1.5 tabular-nums">{s.trades}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ScrollBox>
                <p className="m-0 rounded-control bg-warning-soft p-3 text-small text-warning-soft-fg">{p.backtest.honesty}</p>
              </CardBody>
            </Card>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          <Opportunities items={p.opportunities} onChange={d.reload} />
          <ForwardChecks
            subject="sleeve"
            portfolioId={p.id}
            title="Do the sleeves still hold up?"
            intro="Each sleeve is re-tested on the candles formed since it was added and compared with what its exam years led to expect. One that clearly stopped working is wound down (or taken out of a draft plan)."
          />
          <Card>
            <CardHeader>
              <CardTitle>Diary</CardTitle>
            </CardHeader>
            <CardBody>
              {p.moves.length === 0 ? (
                <p className="m-0 text-small text-fg-muted">Every plan, rebalance and change is written here.</p>
              ) : (
                <ScrollBox size="lg">
                  <ul className="m-0 list-none p-0">
                    {p.moves.map((m) => (
                      <li key={m.id} className="border-t border-hairline py-2 text-small first:border-t-0">
                        <span className="text-tiny text-fg-subtle">{formatDateTime(m.ts)}</span>
                        <br />
                        {m.text}
                      </li>
                    ))}
                  </ul>
                </ScrollBox>
              )}
            </CardBody>
          </Card>
          <Button variant="ghost" onClick={() => navigate("/portfolio")}>
            All portfolios
          </Button>
        </div>
      </div>
    </>
  );
}

export default function Portfolio() {
  const { id } = useParams();
  const list = useApi<{ portfolios: PortfolioSummary[] }>(id ? null : "/portfolios", 15_000);
  const opps = useApi<{ opportunities: Opportunity[] }>(id ? null : "/opportunities");
  const [open, setOpen] = useState(false);
  if (id) return <Detail id={id} />;
  return (
    <>
      <PageHeader
        title="Portfolio"
        subtitle="Give Kairos and Metis one budget; Agora's allocator splits it across strategies and stocks that held up, keeps some cash back, and rebalances. Paper money only."
        actions={
          <Button variant="primary" onClick={() => setOpen(true)}>
            <Plus aria-hidden="true" />
            New portfolio
          </Button>
        }
      />
      {list.status === "loading" && <LoadingRows rows={3} />}
      {list.status === "error" && <ErrorState error={list.error} onRetry={list.reload} />}
      {list.status === "ready" && (
        <div className="grid grid-cols-[minmax(0,1fr)_380px] items-start gap-5">
          {list.data.portfolios.length === 0 ? (
            <EmptyState
              icon={PieChart}
              title="No portfolio yet"
              body="Start with a budget, for example ₹1,00,000 or $10,000. Agora finds what works on unseen years and allocates the money across it, never all of it on one stock."
              action={
                <Button variant="primary" onClick={() => setOpen(true)}>
                  <Plus aria-hidden="true" />
                  New portfolio
                </Button>
              }
            />
          ) : (
            <div className="grid grid-cols-2 gap-4">
              {list.data.portfolios.map((p) => (
                <PortfolioCard key={p.id} p={p} />
              ))}
            </div>
          )}
          <Opportunities items={opps.status === "ready" ? opps.data.opportunities : []} onChange={opps.reload} />
        </div>
      )}
      <NewPortfolio open={open} onOpenChange={setOpen} />
      <p className="m-0 text-tiny text-fg-subtle">Portfolios are a research tool, not financial advice. The allocation is Agora's tested code; orders come only from your strategies in paper accounts.</p>
    </>
  );
}
