import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Check, Download, Play } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { JobProgress } from "../components/JobProgress";
import { Logo } from "../components/shell/Logo";
import { ErrorState } from "../components/states";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { postJson, putJson, toEnvelope, type ErrorEnvelope, type MarketCode, type RefreshResult, type TemplateInfo } from "../lib/api";
import { useApi } from "../lib/useApi";
import { useJob } from "../lib/useJob";
import { cn } from "../lib/utils";

const STEPS = ["Pick your markets", "Download prices", "Run your first backtest"];

const MARKETS: { code: MarketCode; title: string; body: string }[] = [
  { code: "IN", title: "India", body: "The 50 Nifty 50 stocks, traded on NSE in rupees." },
  { code: "US", title: "United States", body: "SPY, QQQ and 8 big US stocks. You can add more later." },
];

function StepDots({ step }: { step: number }) {
  return (
    <ol className="m-0 flex list-none gap-2 p-0" aria-label="Setup steps">
      {STEPS.map((title, i) => (
        <li key={title} className="flex items-center gap-2 text-small">
          <span
            className={cn(
              "flex size-6 items-center justify-center rounded-full text-tiny font-bold",
              i < step ? "bg-profit text-on-accent" : i === step ? "bg-accent-strong text-on-accent" : "bg-surface-2 text-fg-muted",
            )}
          >
            {i < step ? <Check className="size-3.5" aria-hidden="true" /> : i + 1}
          </span>
          <span className={cn(i === step ? "font-semibold" : "text-fg-muted")}>{title}</span>
          {i < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-border" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}

const STARTERS = ["ma_crossover", "rsi_mean_reversion", "donchian_breakout"];

/** Step 3: pick a starter strategy and run a real backtest on the prices just downloaded. */
function FirstBacktest({ market, waiting, onFinish }: { market: MarketCode; waiting: boolean; onFinish: (to: string) => void }) {
  const templates = useApi<{ templates: TemplateInfo[] }>("/templates");
  const [picked, setPicked] = useState(STARTERS[0]!);
  const [run, setRun] = useState<{ runId: number; jobId: string } | null>(null);
  const [error, setError] = useState<ErrorEnvelope | null>(null);
  const [busy, setBusy] = useState(false);
  const { job } = useJob(run?.jobId ?? null);
  const list = templates.status === "ready" ? templates.data.templates.filter((t) => STARTERS.includes(t.key)) : [];
  const done = job?.status === "done";

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const name = list.find((t) => t.key === picked)?.name ?? "My first strategy";
      const created = await postJson<{ version: { id: number } }>("/strategies", { name, market, template_key: picked });
      const r = await postJson<{ run_id: number; job_id: string }>("/backtests", { strategy_version_id: created.version.id, mode: "single" });
      setRun({ runId: r.run_id, jobId: r.job_id });
    } catch (err) {
      setError(toEnvelope(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="flex flex-col gap-2">
        <h1 className="m-0 text-title font-bold tracking-tight">Run your first backtest</h1>
        <p className="m-0 text-body text-fg-muted">
          Pick a ready-made strategy. Agora tests it on the last ten years of {market === "IN" ? "Nifty 50" : "US"} prices you just downloaded, then explains what happened in plain English.
        </p>
      </div>
      {!run && (
        <div role="radiogroup" aria-label="Starter strategy" className="flex flex-col gap-2.5">
          {list.map((t) => (
            <button
              key={t.key}
              type="button"
              role="radio"
              aria-checked={picked === t.key}
              onClick={() => setPicked(t.key)}
              className={cn(
                "flex flex-col gap-0.5 rounded-tile border px-4 py-3 text-left transition-colors",
                picked === t.key ? "border-accent bg-accent-soft/50" : "border-border hover:border-fg-subtle/50",
              )}
            >
              <span className="font-semibold">{t.name}</span>
              <span className="text-small text-fg-muted">{t.summary}</span>
            </button>
          ))}
        </div>
      )}
      {waiting && !run && <p className="m-0 text-small text-fg-muted">Prices are still downloading. The backtest can start as soon as they're saved.</p>}
      {run && job && <JobProgress job={job} />}
      {error && <ErrorState error={error} />}
      <div className="flex justify-between gap-3">
        <Button variant="ghost" onClick={() => onFinish("/")}>
          {run ? "Go to Home" : "Skip for now"}
        </Button>
        {done && run ? (
          <Button variant="primary" onClick={() => onFinish(`/backtests/${run.runId}`)}>
            See the results
            <ArrowRight aria-hidden="true" />
          </Button>
        ) : (
          <Button variant="primary" disabled={busy || waiting || !!run || list.length === 0} onClick={() => void start()}>
            <Play aria-hidden="true" />
            Run backtest
          </Button>
        )}
      </div>
    </>
  );
}

/** First-launch setup (SPEC §9.10): pick markets → download prices → first backtest. */
export default function Onboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [markets, setMarkets] = useState<MarketCode[]>(["IN", "US"]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<ErrorEnvelope | null>(null);
  const { job, cancel } = useJob<RefreshResult>(jobId);
  const downloading = job?.status === "running" || job?.status === "queued";

  function toggle(code: MarketCode) {
    setMarkets((m) => (m.includes(code) ? m.filter((x) => x !== code) : [...m, code]));
  }

  async function startDownload() {
    setError(null);
    try {
      await putJson("/settings", { markets });
      const jobs = await Promise.all(
        markets.length === 2
          ? [postJson<{ job_id: string }>("/data/refresh", { timeframes: ["1d"] })]
          : [postJson<{ job_id: string }>("/data/refresh", { market: markets[0], timeframes: ["1d"] })],
      );
      setJobId(jobs[0].job_id);
      setStep(1);
    } catch (err) {
      setError(toEnvelope(err));
    }
  }

  async function finish(to: string) {
    try {
      await putJson("/settings", { onboarding_done: true });
    } catch {
      // Not worth blocking the user over; the tour will simply show again next time.
    }
    navigate(to);
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-8 text-fg">
      <Card className="w-[min(680px,100%)] gap-7 p-10 shadow-e2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Logo size={36} />
            <span className="text-heading font-bold">Agora</span>
          </div>
          <StepDots step={step} />
        </div>
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={step}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            className="flex flex-col gap-6"
          >
            {step === 0 && (
              <>
                <div className="flex flex-col gap-2">
                  <h1 className="m-0 text-title font-bold tracking-tight">Welcome to your strategy lab</h1>
                  <p className="m-0 text-body text-fg-muted">
                    Build trading rules, test them on years of past prices, then paper trade them live. Fake money only, always.
                  </p>
                </div>
                <fieldset className="m-0 flex flex-col gap-3 border-0 p-0">
                  <legend className="mb-3 text-[14px] font-semibold">Which markets do you want?</legend>
                  {MARKETS.map((m) => {
                    const on = markets.includes(m.code);
                    return (
                      <label
                        key={m.code}
                        className={cn(
                          "flex cursor-pointer items-start gap-4 rounded-tile border p-4 transition-colors",
                          on ? "border-accent/50 bg-accent-soft" : "border-border hover:bg-surface-2",
                        )}
                      >
                        <input type="checkbox" checked={on} onChange={() => toggle(m.code)} className="mt-1 size-4 accent-[var(--accent-strong)]" />
                        <span className="flex flex-col">
                          <span className="font-semibold">{m.title}</span>
                          <span className="text-small text-fg-muted">{m.body}</span>
                        </span>
                      </label>
                    );
                  })}
                </fieldset>
                {error && <ErrorState error={error} />}
                <div className="flex justify-between gap-3">
                  <Button variant="ghost" onClick={() => finish("/")}>
                    Skip for now
                  </Button>
                  <Button variant="primary" disabled={markets.length === 0} onClick={startDownload}>
                    <Download aria-hidden="true" />
                    Download prices
                  </Button>
                </div>
              </>
            )}
            {step === 1 && (
              <>
                <div className="flex flex-col gap-2">
                  <h1 className="m-0 text-title font-bold tracking-tight">Downloading prices</h1>
                  <p className="m-0 text-body text-fg-muted">
                    About ten years of daily prices for every stock, saved on your laptop. This takes a few minutes the first
                    time; later updates only fetch what's new.
                  </p>
                </div>
                {job && <JobProgress job={job} onCancel={cancel} />}
                {job?.status === "done" && job.result && job.result.failed.length > 0 && (
                  <p className="m-0 text-small text-warning">
                    {job.result.failed.length} stock{job.result.failed.length === 1 ? "" : "s"} didn't download. You can retry from the
                    Data screen.
                  </p>
                )}
                <div className="flex justify-between gap-3">
                  <Button variant="ghost" onClick={() => setStep(2)}>
                    {downloading ? "Continue while it downloads" : "Continue"}
                  </Button>
                  <Button variant="primary" disabled={downloading} onClick={() => setStep(2)}>
                    Next
                    <ArrowRight aria-hidden="true" />
                  </Button>
                </div>
              </>
            )}
            {step === 2 && <FirstBacktest market={markets[0] ?? "IN"} waiting={downloading} onFinish={(to) => void finish(to)} />}
          </motion.div>
        </AnimatePresence>
      </Card>
    </div>
  );
}
