import { FlaskConical, Play } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { toast } from "sonner";
import { JobProgress } from "../components/JobProgress";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Field, Input, NumberInput, Select } from "../components/ui/input";
import { Segmented } from "../components/ui/segmented";
import { TRADE_CHECK_HINT, TRADE_CHECK_OPTIONS, type TradeCheckMode } from "../lib/tradeCheck";
import {
  postJson,
  toEnvelope,
  type CostProfiles,
  type SavedVersion,
  type SettingsResponse,
  type StrategySummary,
  type Timeframe,
} from "../lib/api";
import { formatCount, MARKET_CURRENCY, TIMEFRAME_LABEL } from "../lib/format";
import type { Definition, ParameterDef } from "../lib/strategy";
import { useApi } from "../lib/useApi";
import { useJob } from "../lib/useJob";

type Mode = "single" | "oos" | "sweep" | "walk_forward";
const DAY = 86_400_000;
const PRESETS = [
  { key: "1y", label: "1 year", days: 365 },
  { key: "3y", label: "3 years", days: 3 * 365 },
  { key: "5y", label: "5 years", days: 5 * 365 },
  { key: "10y", label: "10 years", days: 10 * 365 },
  { key: "custom", label: "Custom", days: 0 },
];
const INTRADAY_PRESETS = [
  { key: "30d", label: "30 days", days: 30 },
  { key: "59d", label: "All available", days: 59 },
  { key: "custom", label: "Custom", days: 0 },
];

function isoDay(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}
function dayMs(iso: string): number {
  return Date.parse(`${iso}T00:00:00Z`);
}

interface SweepRow {
  name: string;
  from: number;
  to: number;
  step: number;
}

function values(r: SweepRow): number[] {
  if (r.step <= 0 || r.to < r.from) return [];
  const out: number[] = [];
  for (let v = r.from; v <= r.to + 1e-9 && out.length <= 60; v += r.step) out.push(Number(v.toFixed(6)));
  return out;
}

function SweepEditor({ params, rows, onChange, max }: { params: ParameterDef[]; rows: SweepRow[]; onChange: (r: SweepRow[]) => void; max: number }) {
  const cells = rows.reduce((n, r) => n * Math.max(1, values(r).length), 1);
  return (
    <div className="flex flex-col gap-3">
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[1fr_90px_90px_90px] items-end gap-2">
          <Field label={i === 0 ? "Parameter" : "Second parameter"}>
            <Select
              value={r.name}
              onChange={(e) => {
                const p = params.find((x) => x.name === e.target.value);
                onChange(rows.map((x, j) => (j === i && p ? { name: p.name, from: p.min, to: p.max, step: Math.max(1, Math.round((p.max - p.min) / 5)) } : x)));
              }}
            >
              {params.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="From">
            <NumberInput value={r.from} onChange={(v) => onChange(rows.map((x, j) => (j === i ? { ...x, from: v ?? 0 } : x)))} />
          </Field>
          <Field label="To">
            <NumberInput value={r.to} onChange={(v) => onChange(rows.map((x, j) => (j === i ? { ...x, to: v ?? 0 } : x)))} />
          </Field>
          <Field label="Step">
            <NumberInput value={r.step} onChange={(v) => onChange(rows.map((x, j) => (j === i ? { ...x, step: v ?? 1 } : x)))} />
          </Field>
        </div>
      ))}
      <div className="flex items-center justify-between">
        <span className={cells > max ? "text-small text-warning" : "text-small text-fg-muted"}>
          {cells} combination{cells === 1 ? "" : "s"} {cells > max ? `(the limit is ${max}; use a bigger step)` : "will be tested"}
        </span>
        {rows.length === 1 && params.length > 1 && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              const p = params.find((x) => x.name !== rows[0]?.name);
              if (p) onChange([...rows, { name: p.name, from: p.min, to: p.max, step: Math.max(1, Math.round((p.max - p.min) / 5)) }]);
            }}
          >
            Add a second parameter
          </Button>
        )}
        {rows.length === 2 && (
          <Button size="sm" variant="ghost" onClick={() => onChange(rows.slice(0, 1))}>
            Use one parameter
          </Button>
        )}
      </div>
    </div>
  );
}

function SetupForm({ strategy, version, onStarted }: { strategy: StrategySummary; version: SavedVersion<Definition>; onStarted: (runId: number, jobId: string) => void }) {
  const d = version.definition;
  const settings = useApi<SettingsResponse>("/settings");
  const profiles = useApi<CostProfiles>(`/costs/profiles?market=${d.market}`);
  const intraday = d.timeframe !== "1d";
  const [timeframe, setTimeframe] = useState<Timeframe>(d.timeframe);
  const [preset, setPreset] = useState(intraday ? "59d" : "5y");
  const [now] = useState(() => Date.now());
  const [custom, setCustom] = useState({ start: isoDay(now - 5 * 365 * DAY), end: isoDay(now) });
  const [capital, setCapital] = useState<number | null>(null);
  const [profileId, setProfileId] = useState<number | null>(null);
  const [slippage, setSlippage] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>("single");
  const [check, setCheck] = useState<TradeCheckMode>("off");
  const [oos, setOos] = useState(70);
  const first = d.parameters[0];
  const [sweep, setSweep] = useState<SweepRow[]>(first ? [{ name: first.name, from: first.min, to: first.max, step: Math.max(1, Math.round((first.max - first.min) / 5)) }] : []);
  const [wf, setWf] = useState({ train: 730, test: 180 });
  const [busy, setBusy] = useState(false);
  const currency = MARKET_CURRENCY[d.market];

  const defaults = useMemo(() => {
    const cap = settings.status === "ready" ? Number(settings.data.values[`default_capital.${d.market}`]) : null;
    const bp = profiles.status === "ready" ? profiles.data.brokerage.find((p) => p.is_default) : undefined;
    const sp = profiles.status === "ready" ? profiles.data.slippage.find((p) => p.is_default) : undefined;
    return { capital: cap, profile: bp?.id ?? null, slippage: sp?.bps ?? null };
  }, [settings, profiles, d.market]);

  const presets = intraday || timeframe !== "1d" ? INTRADAY_PRESETS : PRESETS;
  const days = presets.find((p) => p.key === preset)?.days ?? 0;
  const start = preset === "custom" ? dayMs(custom.start) : now - days * DAY;
  const end = preset === "custom" ? dayMs(custom.end) + DAY : now;

  async function run() {
    setBusy(true);
    const body: Record<string, unknown> = {
      strategy_version_id: version.id,
      timeframe,
      start,
      end,
      capital: capital ?? defaults.capital,
      brokerage_profile_id: profileId ?? defaults.profile,
      slippage_bps: slippage ?? defaults.slippage,
      mode,
      trade_check: check,
    };
    if (mode === "oos") body.oos_fraction = oos / 100;
    if (mode === "sweep") body.sweep = { params: sweep.map((r) => ({ name: r.name, values: values(r) })) };
    if (mode === "walk_forward") body.walk_forward = { train_days: wf.train, test_days: wf.test, params: sweep.map((r) => ({ name: r.name, values: values(r) })) };
    try {
      const r = await postJson<{ run_id: number; job_id: string }>("/backtests", body);
      onStarted(r.run_id, r.job_id);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    } finally {
      setBusy(false);
    }
  }

  const stocks = d.universe.kind === "all" ? (d.market === "IN" ? "All Nifty 50 stocks" : "All your US stocks") : d.universe.symbols.join(", ");
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_380px] items-start gap-5">
      <Card>
        <CardHeader>
          <CardTitle>What to test</CardTitle>
        </CardHeader>
        <CardBody className="flex flex-col gap-5">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Stocks" hint="Change them in the strategy's settings.">
              <p className="m-0 flex h-10 items-center truncate rounded-control bg-surface-2 px-3 text-[14px]">{stocks}</p>
            </Field>
            <Field label="Timeframe">
              <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value as Timeframe)}>
                {(["1d", "1h", "15m", "5m", "1m"] as Timeframe[]).map((t) => (
                  <option key={t} value={t}>
                    {TIMEFRAME_LABEL[t]}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="Period" hint={timeframe !== "1d" ? "Intraday history is short: Yahoo keeps about 60 days (Agora keeps saving more while it's open)." : "A longer period gives more trades to judge by."}>
            <Segmented label="Period" value={preset} onChange={setPreset} options={presets.map((p) => ({ value: p.key, label: p.label }))} />
            {preset === "custom" && (
              <div className="mt-2 flex items-center gap-2">
                <Input type="date" aria-label="Start date" value={custom.start} onChange={(e) => setCustom({ ...custom, start: e.target.value })} />
                <span className="text-small text-fg-muted">to</span>
                <Input type="date" aria-label="End date" value={custom.end} onChange={(e) => setCustom({ ...custom, end: e.target.value })} />
              </div>
            )}
          </Field>
          <Field label="Type of test">
            <Segmented
              label="Type of test"
              value={mode}
              onChange={setMode}
              options={[
                { value: "single", label: "Standard" },
                { value: "oos", label: "In / out of sample" },
                ...(d.parameters.length ? [{ value: "sweep" as Mode, label: "Parameter sweep" }, { value: "walk_forward" as Mode, label: "Walk-forward" }] : []),
              ]}
            />
          </Field>
          {mode === "single" && <p className="m-0 text-small text-fg-muted">One backtest over the whole period.</p>}
          <Field label="Kairos's trade check" hint={TRADE_CHECK_HINT[check]}>
            <Segmented label="Kairos's trade check" value={check} onChange={setCheck} options={TRADE_CHECK_OPTIONS} />
          </Field>
          {mode === "oos" && (
            <Field label={`Tune on the first ${oos}%, check on the last ${100 - oos}%`} hint="Results are shown for both parts side by side; the second part is a fairer test.">
              <input type="range" min={50} max={90} step={5} value={oos} onChange={(e) => setOos(Number(e.target.value))} aria-label="In-sample share" className="accent-[var(--accent-strong)]" />
            </Field>
          )}
          {(mode === "sweep" || mode === "walk_forward") && (
            <SweepEditor params={d.parameters} rows={sweep} onChange={setSweep} max={100} />
          )}
          {mode === "walk_forward" && (
            <div className="grid grid-cols-2 gap-4">
              <Field label="Days to tune on" hint="Each window picks the best setting on this many days…">
                <NumberInput value={wf.train} min={30} step={1} onChange={(v) => setWf({ ...wf, train: Math.round(v ?? 365) })} />
              </Field>
              <Field label="Days to test on" hint="…then uses it on the next days.">
                <NumberInput value={wf.test} min={5} step={1} onChange={(v) => setWf({ ...wf, test: Math.round(v ?? 90) })} />
              </Field>
            </div>
          )}
        </CardBody>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Money and costs</CardTitle>
        </CardHeader>
        <CardBody className="flex flex-col gap-4">
          <Field label={`Starting money (${currency === "INR" ? "₹" : "$"})`} hint="Pretend money; nothing real is used.">
            <NumberInput value={capital ?? defaults.capital} min={1} onChange={setCapital} />
          </Field>
          <Field label="Brokerage" hint="Taxes and exchange fees are always included.">
            <Select value={profileId ?? defaults.profile ?? ""} onChange={(e) => setProfileId(Number(e.target.value))}>
              {profiles.status === "ready" &&
                profiles.data.brokerage.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
            </Select>
          </Field>
          <Field label="Slippage (basis points)" hint="1 bp = 0.01%. Buys fill a little higher and sells a little lower.">
            <NumberInput value={slippage ?? defaults.slippage} min={0} max={500} onChange={setSlippage} />
          </Field>
          <Button variant="primary" size="md" disabled={busy || defaults.capital === null} onClick={run}>
            <Play aria-hidden="true" />
            Run backtest
          </Button>
          <p className="m-0 text-tiny text-fg-subtle">
            {strategy.name} · version {version.version}. Signals use closed candles; orders fill at the next candle's open.
            {d.universe.kind === "all" && d.market === "IN" ? ` About ${formatCount(50)} stocks will be checked.` : ""}
          </p>
        </CardBody>
      </Card>
    </div>
  );
}

export default function BacktestSetup() {
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const list = useApi<{ strategies: StrategySummary[] }>("/strategies");
  const sid = Number(search.get("strategy")) || null;
  const detail = useApi<{ version: SavedVersion<Definition> | null }>(sid ? `/strategies/${sid}` : null);
  const [running, setRunning] = useState<{ runId: number; jobId: string } | null>(null);
  const { job, cancel } = useJob(running?.jobId ?? null, (j) => {
    if (j.status === "done" && running) navigate(`/backtests/${running.runId}`);
  });

  const strategies = list.status === "ready" ? list.data.strategies : [];
  const strategy = strategies.find((s) => s.id === sid);

  return (
    <>
      <PageHeader title="New backtest" subtitle="Test a strategy on past prices with realistic charges." />
      <Card className="p-5">
        <Field label="Strategy">
          <Select value={sid ?? ""} onChange={(e) => setSearch({ strategy: e.target.value })} aria-label="Strategy" className="max-w-[480px]">
            <option value="" disabled>
              Choose a strategy…
            </option>
            {strategies.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.market === "IN" ? "India" : "US"}, v{s.version})
              </option>
            ))}
          </Select>
        </Field>
      </Card>
      {list.status === "ready" && strategies.length === 0 && (
        <Card className="py-4">
          <EmptyState
            icon={FlaskConical}
            title="Create a strategy first"
            body="Backtests run a strategy on past prices. Start from a template; it takes a click."
            action={
              <Button variant="primary" asChild>
                <Link to="/strategies">Choose a template</Link>
              </Button>
            }
          />
        </Card>
      )}
      {running && job && (
        <Card className="p-5">
          <JobProgress job={job} onCancel={cancel} />
          {job.status === "cancelled" && (
            <p className="m-0 mt-2 text-small text-fg-muted">
              Cancelled. <button className="text-accent-strong underline" onClick={() => setRunning(null)}>Change the settings</button>
            </p>
          )}
        </Card>
      )}
      {!running && sid && detail.status === "loading" && <LoadingRows rows={4} />}
      {!running && detail.status === "error" && <ErrorState error={detail.error} onRetry={detail.reload} />}
      {!running && strategy && detail.status === "ready" && detail.data.version && (
        <SetupForm key={detail.data.version.id} strategy={strategy} version={detail.data.version} onStarted={(runId, jobId) => setRunning({ runId, jobId })} />
      )}
    </>
  );
}
