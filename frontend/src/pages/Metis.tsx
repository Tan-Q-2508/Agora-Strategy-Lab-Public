/**
 * Metis, Kairos's AI researcher (docs/METIS.md). Switched on, it researches on its own while
 * Agora is open: the AI thinks up ideas, code tests each one on years the AI never saw, and only
 * what holds up is kept. This screen shows what it is doing, its notebook, and how it thought.
 */
import { ArrowUpRight, BookOpen, FlaskConical, Play, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { JobProgress } from "../components/JobProgress";
import { MetisMark } from "../components/metis/MetisMark";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { ForwardChecks } from "../components/checks/ForwardChecks";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Field, Input } from "../components/ui/input";
import { Dot, Pill } from "../components/ui/pill";
import { Segmented } from "../components/ui/segmented";
import { postJson, putJson, toEnvelope } from "../lib/api";
import { formatAgo, formatDate, formatSignedMoney, MARKET_CURRENCY } from "../lib/format";
import { DIRECTION_LABEL, KIND_LABEL, STATUS_LABEL, stateLine, type LibraryArea, type MetisIdea, type MetisPart, type MetisRound, type MetisStatus } from "../lib/metis";
import { useApi } from "../lib/useApi";
import { useJob, useJobId } from "../lib/useJob";
import { ScrollBox } from "../components/ui/scroll-box";

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-control bg-surface-2 px-4 py-3">
      <span className="text-[22px] font-semibold tabular-nums">{value}</span>
      <span className="text-small text-fg-muted">{label}</span>
    </div>
  );
}

function cell(p: MetisPart | undefined, currency: "INR" | "USD") {
  if (!p) return "–";
  const wr = p.win_rate === null ? "–" : `${Math.round(p.win_rate * 100)}%`;
  return `${formatSignedMoney(p.net, currency, 0)} · ${p.trades} trades · won ${wr}`;
}

function Numbers({ idea }: { idea: MetisIdea }) {
  const r = idea.result;
  if (!r.candidate) return null;
  const cur = MARKET_CURRENCY[idea.market ?? "IN"];
  const rows: [string, "study" | "exam"][] = [
    [`Study years${r.split ? ` (to ${formatDate(r.split)})` : ""}: Metis saw these`, "study"],
    ["Exam years: Metis never saw these", "exam"],
  ];
  return (
    <ScrollBox size="lg">
      <table className="w-full border-collapse text-small">
        <thead>
          <tr className="text-left text-tiny text-fg-subtle">
            <th className="py-1 pr-3 font-medium">After costs</th>
            {r.baseline && <th className="py-1 pr-3 font-medium">Current version</th>}
            <th className="py-1 font-medium">{r.baseline ? "With the idea" : "The new strategy"}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, key]) => (
            <tr key={key} className="border-t border-hairline">
              <td className="py-1.5 pr-3 text-fg-muted">{label}</td>
              {r.baseline && <td className="py-1.5 pr-3 tabular-nums">{cell(r.baseline[key], cur)}</td>}
              <td className="py-1.5 tabular-nums">{cell(r.candidate?.[key], cur)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollBox>
  );
}

function IdeaCard({ idea, onSaved }: { idea: MetisIdea; onSaved: () => void }) {
  const st = STATUS_LABEL[idea.status];
  const [saving, setSaving] = useState(false);
  async function save() {
    setSaving(true);
    try {
      await postJson(`/metis/ideas/${idea.id}/save`);
      toast.success("Saved. Your earlier version is kept.");
      onSaved();
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    } finally {
      setSaving(false);
    }
  }
  return (
    <article className="flex flex-col gap-3 rounded-control border border-hairline bg-surface p-4" aria-label={idea.title}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Pill className="h-6 px-2 text-tiny">{KIND_LABEL[idea.kind]}</Pill>
          <h3 className="m-0 truncate text-[15px] font-semibold">{idea.title}</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-tiny text-fg-subtle">{formatAgo(idea.created_at)}</span>
          <Pill tone={st.tone} className="h-7 px-2.5 text-tiny">{st.label}</Pill>
        </div>
      </div>
      {idea.why && (
        <blockquote className="m-0 border-l-2 border-accent pl-3 text-small text-fg-muted">
          <span className="text-tiny font-semibold tracking-wide text-fg-subtle uppercase">
            {idea.origin === "playbook" ? "From the playbook (a senior quant's first experiment, in code)" : "Metis's reasoning (AI's own words)"}
          </span>
          <br />
          {idea.why}
        </blockquote>
      )}
      <p className="m-0 text-small">{idea.verdict}</p>
      {idea.result.luck && (
        <p className="m-0 text-small text-fg-muted">
          Luck check: {Math.round(idea.result.luck.dsr * 100)}% chance it beats the best of {idea.result.luck.tries} lucky {idea.result.luck.tries === 1 ? "try" : "tries"} (deflated Sharpe ratio over {idea.result.luck.days} unseen days).
        </p>
      )}
      {idea.result.overfit?.pbo != null && <p className="m-0 text-small text-fg-muted">{idea.result.overfit.text}</p>}
      <Numbers idea={idea} />
      <div className="flex flex-wrap items-center gap-3 text-small">
        {idea.strategy_id && (
          <Link to={`/strategies/${idea.strategy_id}`} className="inline-flex items-center gap-1">
            {idea.result.family ? `It is a version of “${idea.result.family.name}”` : "The strategy"} <ArrowUpRight className="size-3.5" aria-hidden="true" />
          </Link>
        )}
        {idea.saved_strategy_id && idea.kind === "new_strategy" && (
          <Link to={`/strategies/${idea.saved_strategy_id}`} className="inline-flex items-center gap-1">
            Open the new strategy <ArrowUpRight className="size-3.5" aria-hidden="true" />
          </Link>
        )}
        {idea.run_id && (
          <Link to={`/backtests/${idea.run_id}`} className="inline-flex items-center gap-1">
            See its backtest <ArrowUpRight className="size-3.5" aria-hidden="true" />
          </Link>
        )}
        {idea.status === "held_up" && (
          <Button size="sm" variant="soft" onClick={() => void save()} disabled={saving}>
            Save it
          </Button>
        )}
      </div>
    </article>
  );
}

function RoundItem({ r }: { r: MetisRound }) {
  const tone = r.status === "failed" ? "loss" : r.status === "running" ? "warning" : r.kept ? "profit" : "neutral";
  return (
    <li className="flex flex-col gap-1.5 border-t border-hairline py-3 first:border-t-0">
      <p className="m-0 flex items-center gap-2 text-small">
        <Dot tone={tone} live={r.status === "running"} />
        <span className="font-semibold">{r.status === "running" ? "Researching now" : formatAgo(r.started_at)}</span>
        <span className="text-fg-subtle">· {r.trigger === "user" ? "you asked" : "on its own"}</span>
        {r.model === "playbook" && <span className="text-fg-subtle">· from the playbook</span>}
      </p>
      {r.direction && <p className="m-0 text-tiny font-semibold tracking-wide text-fg-subtle uppercase">{DIRECTION_LABEL[r.direction]}</p>}
      {r.note && <p className="m-0 text-small">{r.note}</p>}
      {r.noticed && <p className="m-0 text-small text-fg-muted">What it noticed: {r.noticed}</p>}
      {r.autopsy && r.autopsy.length > 0 && (
        <details className="text-small">
          <summary className="cursor-pointer text-fg-muted">Trade autopsy: why trades went wrong</summary>
          {r.autopsy.map((a) => (
            <div key={a.strategy} className="mt-2 rounded-control bg-surface-2 p-3">
              <p className="m-0 text-tiny font-semibold">{a.strategy}</p>
              <ScrollBox size="sm">
                <ul className="m-0 mt-1 flex list-disc flex-col gap-1 pl-4 text-tiny leading-5 text-fg-muted">
                  {a.lines.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </ScrollBox>
            </div>
          ))}
          <p className="m-0 pt-1 text-tiny text-fg-subtle">From the study years only. Each pattern becomes a filter idea that must still pass the test on unseen years.</p>
        </details>
      )}
      {r.thinking && (
        <details className="text-small">
          <summary className="cursor-pointer text-fg-muted">How Metis thought</summary>
          <p className="mt-2 mb-0 max-h-[240px] overflow-y-auto rounded-control bg-surface-2 p-3 text-tiny leading-5 whitespace-pre-wrap text-fg-muted">{r.thinking}</p>
          <p className="m-0 pt-1 text-tiny text-fg-subtle">The AI's own thinking. Numbers in it aren't checked; the verdicts come from Agora's tests.</p>
        </details>
      )}
    </li>
  );
}

/** What Metis knows: its quant library, by area (docs/METIS.md §11). */
function Knowledge() {
  const lib = useApi<{ areas: LibraryArea[]; total: number }>("/metis/library");
  if (lib.status !== "ready") return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BookOpen className="size-4 text-accent" aria-hidden="true" />
          What Metis knows
        </CardTitle>
      </CardHeader>
      <CardBody className="flex flex-col gap-2">
        <p className="m-0 text-small text-fg-muted">
          A senior quant's library of {lib.data.total} sections: the research method, the statistics of luck, the documented market anomalies with their papers, portfolio construction, risk and costs, each with how to test it in Agora. Metis reads the sections its evidence calls for before every round.
        </p>
        <ScrollBox size="lg">
          <ul className="m-0 list-none p-0">
            {lib.data.areas.map((a) => (
              <li key={a.key} className="border-t border-hairline py-1.5 first:border-t-0">
                <details className="text-small">
                  <summary className="cursor-pointer">
                    {a.title} <span className="text-fg-subtle">· {a.sections.length}</span>
                  </summary>
                  <p className="m-0 pt-1 text-tiny text-fg-muted">{a.sections.join(" · ")}</p>
                </details>
              </li>
            ))}
          </ul>
        </ScrollBox>
      </CardBody>
    </Card>
  );
}

export default function Metis() {
  const s = useApi<MetisStatus>("/metis", 5_000);
  const [jobId, setJobId] = useJobId("metis_round");
  const [focus, setFocus] = useState<string | null>(null);
  const { job } = useJob<{ note?: string }>(jobId, (j) => {
    setJobId(null);
    if (j.status === "done" && j.result?.note) toast.success(j.result.note);
    s.reload();
  });
  const savedFocus = s.status === "ready" ? s.data.focus : "";

  async function setting(key: string, value: unknown, done?: string) {
    try {
      await putJson("/settings", { [key]: value });
      if (key === "metis.focus") setFocus(null);
      if (done) toast.success(done);
      s.reload();
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }
  async function researchNow() {
    try {
      const r = await postJson<{ job_id: string }>("/metis/round");
      setJobId(r.job_id);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }

  return (
    <>
      <div className="flex flex-col gap-2">
        <h1 className="m-0 flex items-center gap-2.5 text-title font-bold tracking-tight">
          <MetisMark className="size-7" />
          Metis
        </h1>
        <p className="m-0 max-w-[780px] text-body text-fg-muted">
          Kairos's AI researcher. Switched on, it keeps researching on its own while Agora is open: it reads how your strategies did, thinks up ideas to make them better (or new strategies to try), tests every idea on years it never saw, and keeps only what holds up. It never trades.
        </p>
      </div>
      {s.status === "loading" && <LoadingRows rows={6} />}
      {s.status === "error" && <ErrorState error={s.error} onRetry={s.reload} />}
      {s.status === "ready" && (
        <div className="grid grid-cols-[minmax(0,1fr)_400px] items-start gap-5">
          <div className="flex min-w-0 flex-col gap-5">
            <Card>
              <CardHeader>
                <CardTitle>Research on its own</CardTitle>
                <Segmented
                  label="Metis researches on its own"
                  value={s.data.on ? "on" : "off"}
                  onChange={(x) => void setting("metis.enabled", x === "on", x === "on" ? "Metis is on. Its first round starts shortly." : "Metis is off.")}
                  options={[
                    { value: "on", label: "On" },
                    { value: "off", label: "Off" },
                  ]}
                />
              </CardHeader>
              <CardBody className="flex flex-col gap-4">
                <p className="m-0 flex items-center gap-2 text-small text-fg-muted" aria-live="polite">
                  <Dot tone={s.data.state === "working" ? "warning" : s.data.state === "scheduled" ? "profit" : "neutral"} live={s.data.state === "working"} />
                  {stateLine(s.data)}
                </p>
                {s.data.direction && s.data.state === "working" && <p className="m-0 text-small font-semibold">This round: {DIRECTION_LABEL[s.data.direction]}</p>}
                {!s.data.ai_ready && (s.data.ai_note ?? "").includes("switched off in Settings → Metis") && (
                  <p className="m-0 text-small text-fg-muted">Metis's own ideas are switched off: it runs its playbook, and Claude writes its ideas for now. They go through the same tests.</p>
                )}
                {!s.data.ai_ready && !(s.data.ai_note ?? "").includes("switched off in Settings → Metis") && (
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-card bg-warning-soft p-4 text-warning-soft-fg">
                    <p className="m-0 text-small">
                      Without the AI helper (Ollama), Metis works from its playbook: it tests a senior quant's first experiments on your strategies and the textbook strategies you don't have yet. Set up the AI helper for its own ideas.
                    </p>
                    <Button asChild size="sm" variant="secondary">
                      <Link to="/settings?tab=ai">Set up the AI helper</Link>
                    </Button>
                  </div>
                )}
                {job && <JobProgress job={job} />}
                <div className="grid grid-cols-4 gap-3">
                  <Stat label="Ideas tested" value={s.data.totals.tested} />
                  <Stat label="Held up" value={s.data.totals.held_up} />
                  <Stat label="Saved to your strategies" value={s.data.totals.saved} />
                  <Stat label="Rounds of research" value={s.data.totals.rounds} />
                </div>
                <Field label="What should Metis look into? (optional)" htmlFor="metis-focus" hint="In your own words, e.g. “my breakout strategy loses too often”. Leave it empty and Metis chooses.">
                  <div className="flex gap-2">
                    <Input id="metis-focus" className="min-w-0 flex-1" maxLength={500} value={focus ?? savedFocus} onChange={(e) => setFocus(e.target.value)} />
                    <Button variant="secondary" disabled={focus === null || focus === savedFocus} onClick={() => void setting("metis.focus", focus ?? "", "Metis will look into that next round.")}>
                      Save
                    </Button>
                  </div>
                </Field>
                <div className="flex flex-wrap items-center gap-3">
                  <Button variant="primary" onClick={() => void researchNow()} disabled={jobId !== null || s.data.state === "working"}>
                    <Play aria-hidden="true" />
                    Research now
                  </Button>
                  <span className="text-small text-fg-muted">
                    {s.data.apply
                      ? "Ideas that hold up are saved by themselves: an improvement becomes the next version of your strategy (never a copy; earlier versions are kept), and only a genuinely different strategy is saved as “Metis · …”, a few a day at most."
                      : "Ideas that hold up wait here for you to save them."}{" "}
                    Change this in Settings → Kairos.
                  </span>
                </div>
              </CardBody>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>The notebook</CardTitle>
              </CardHeader>
              <CardBody className="flex flex-col gap-3">
                {s.data.ideas.length === 0 ? (
                  <EmptyState
                    icon={Sparkles}
                    title="No ideas yet"
                    body="Metis writes every idea it tests here, the ones that didn't hold up too. Switch it on, or click Research now. It works best once a strategy has been backtested."
                    action={
                      <Button asChild size="sm" variant="secondary">
                        <Link to="/strategies">
                          <FlaskConical aria-hidden="true" />
                          Your strategies
                        </Link>
                      </Button>
                    }
                  />
                ) : (
                  s.data.ideas.map((i) => <IdeaCard key={i.id} idea={i} onSaved={s.reload} />)
                )}
              </CardBody>
            </Card>
          </div>
          <div className="flex min-w-0 flex-col gap-5">
          <ForwardChecks
            subject="revision"
            title="Do saved improvements still hold up?"
            intro="Every version Kairos or Metis saved on its own is re-tested on the candles formed after it was saved, which no test ever saw, against the version before it."
          />
          <Knowledge />
          <Card>
            <CardHeader>
              <CardTitle>Rounds of research</CardTitle>
            </CardHeader>
            <CardBody>
              {s.data.rounds.length === 0 ? (
                <p className="m-0 text-small text-fg-muted">Each round Metis reads the evidence, thinks, and tests up to three ideas. Its rounds and how it thought appear here.</p>
              ) : (
                <ScrollBox size="lg">
                  <ul className="m-0 list-none p-0">
                    {s.data.rounds.map((r) => (
                      <RoundItem key={r.id} r={r} />
                    ))}
                  </ul>
                </ScrollBox>
              )}
            </CardBody>
          </Card>
          </div>
        </div>
      )}
      <p className="m-0 text-tiny text-fg-subtle">Metis is a research tool, not financial advice. It changes strategies only by saving new versions, and never places orders. Paper money only.</p>
    </>
  );
}
