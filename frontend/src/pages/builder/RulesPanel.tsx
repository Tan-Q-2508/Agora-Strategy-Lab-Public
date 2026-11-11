import { ArrowDownRight, ArrowUpRight, LogOut, Plus, Shield } from "lucide-react";
import type { ReactNode } from "react";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { Input, Select } from "../../components/ui/input";
import { defaultCompare, type Condition, type Issue, type ScaleOutSpec, type StopSpec, type VisualDefinition } from "../../lib/strategy";
import { cn } from "../../lib/utils";
import { RuleEditor } from "./ConditionEditor";
import { EnvContext, type Path } from "./env";
import { NumParam } from "./NumParam";

function Section({
  icon,
  title,
  subtitle,
  tone,
  children,
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
  tone: "profit" | "loss" | "neutral";
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center gap-2.5">
        <span
          className={cn(
            "flex size-7 items-center justify-center rounded-full [&_svg]:size-4",
            tone === "profit" && "bg-profit-soft text-profit-soft-fg",
            tone === "loss" && "bg-loss-soft text-loss-soft-fg",
            tone === "neutral" && "bg-surface-2 text-fg-muted",
          )}
        >
          {icon}
        </span>
        <div>
          <h3 className="m-0 text-[15px] font-semibold">{title}</h3>
          <p className="m-0 text-tiny text-fg-subtle">{subtitle}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

function Rule({
  value,
  onChange,
  path,
  emptyLabel,
}: {
  value: Condition | null;
  onChange: (c: Condition | null) => void;
  path: Path;
  emptyLabel: string;
}) {
  if (value === null) {
    return (
      <button
        type="button"
        onClick={() => onChange(defaultCompare())}
        className="flex h-14 items-center justify-center gap-2 rounded-tile border border-dashed border-border text-small text-fg-muted transition-colors hover:border-accent hover:bg-accent-soft hover:text-accent-soft-fg"
      >
        <Plus className="size-4" aria-hidden="true" />
        {emptyLabel}
      </button>
    );
  }
  return <RuleEditor value={value} onChange={onChange} path={path} />;
}

function StopRow({
  label,
  hint,
  value,
  onChange,
  invalid,
}: {
  label: string;
  hint: string;
  value: StopSpec | null;
  onChange: (v: StopSpec | null) => void;
  invalid: boolean;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2 rounded-tile border p-3", invalid ? "border-warning/60" : "border-hairline")}>
      <label className="flex w-40 items-center gap-2 text-[14px] font-medium">
        <input type="checkbox" checked={value !== null} onChange={(e) => onChange(e.target.checked ? { kind: "percent", value: 5 } : null)} className="size-4 accent-[var(--accent-strong)]" />
        {label}
      </label>
      {value ? (
        <>
          <Select aria-label={`${label} type`} value={value.kind} onChange={(e) => onChange({ ...value, kind: e.target.value as "percent" | "atr", value: e.target.value === "atr" ? 2 : 5 })} className="h-9 w-auto">
            <option value="percent">% from the entry price</option>
            <option value="atr">× ATR (typical daily range)</option>
          </Select>
          <EnvContext.Consumer>
            {(env) => <NumParam label={`${label} amount`} value={value.value} params={env.params} onChange={(v) => onChange({ ...value, value: v })} className="w-[200px]" invalid={invalid} />}
          </EnvContext.Consumer>
        </>
      ) : (
        <span className="text-small text-fg-subtle">{hint}</span>
      )}
    </div>
  );
}

const HALF_AT_1R: ScaleOutSpec = { steps: [{ kind: "r", value: 1, sell_pct: 50 }], breakeven: true };
const PARTIAL_PLANS: { key: string; label: string; plan: ScaleOutSpec }[] = [
  { key: "half", label: "Sell half at 1R", plan: HALF_AT_1R },
  {
    key: "thirds",
    label: "Sell a third at 1R and a third at 2R",
    plan: { steps: [{ kind: "r", value: 1, sell_pct: 33 }, { kind: "r", value: 2, sell_pct: 33 }], breakeven: true },
  },
  { key: "half15", label: "Sell half at 1.5R", plan: { steps: [{ kind: "r", value: 1.5, sell_pct: 50 }], breakeven: true } },
];

function planKey(v: ScaleOutSpec): string {
  const same = (p: ScaleOutSpec) => JSON.stringify(p.steps) === JSON.stringify(v.steps);
  return PARTIAL_PLANS.find((p) => same(p.plan))?.key ?? "custom";
}

function stepText(v: ScaleOutSpec): string {
  const unit = { r: "R", percent: "% profit", atr: " ATR" } as const;
  return v.steps.map((s) => `${s.sell_pct}% at ${s.value}${unit[s.kind]}`).join(", then ");
}

/** Partial exits (D-125): a few ready plans in R (1R = as far as the stop-loss is). */
function PartialRow({ value, onChange, invalid, hasStop }: { value: ScaleOutSpec | null; onChange: (v: ScaleOutSpec | null) => void; invalid: boolean; hasStop: boolean }) {
  const key = value ? planKey(value) : "half";
  return (
    <div className={cn("flex flex-wrap items-center gap-2 rounded-tile border p-3", invalid ? "border-warning/60" : "border-hairline")}>
      <label className="flex w-40 items-center gap-2 text-[14px] font-medium">
        <input type="checkbox" checked={value !== null} onChange={(e) => onChange(e.target.checked ? HALF_AT_1R : null)} className="size-4 accent-[var(--accent-strong)]" />
        Partial exits
      </label>
      {value ? (
        <>
          <Select aria-label="Partial exit plan" value={key} onChange={(e) => { const p = PARTIAL_PLANS.find((x) => x.key === e.target.value); if (p) onChange({ ...p.plan, breakeven: value.breakeven }); }} className="h-9 w-auto">
            {PARTIAL_PLANS.map((p) => (
              <option key={p.key} value={p.key}>{p.label}</option>
            ))}
            {key === "custom" && <option value="custom">{stepText(value)}</option>}
          </Select>
          <label className="flex items-center gap-2 text-small text-fg-muted">
            <input type="checkbox" checked={value.breakeven} onChange={(e) => onChange({ ...value, breakeven: e.target.checked })} className="size-4 accent-[var(--accent-strong)]" />
            then move the stop to the entry
          </label>
          {!hasStop && <span className="text-small text-warning">Needs a stop-loss: R is the distance to it.</span>}
        </>
      ) : (
        <span className="text-small text-fg-subtle">Book part of the profit early; the rest rides the trend.</span>
      )}
    </div>
  );
}

export function RulesPanel({
  d,
  onChange,
  issues,
}: {
  d: VisualDefinition;
  onChange: (d: VisualDefinition) => void;
  issues: Issue[];
}) {
  const env = { issues, params: d.parameters, timeframe: d.timeframe, exitRule: false };
  const exitEnv = { ...env, exitRule: true };
  const canShort = d.product !== "delivery";
  const bad = (path: Path) => issues.some((i) => i.severity === "error" && path.every((p, k) => i.path[k] === p));
  const setEntry = (side: "long" | "short", c: Condition | null) => onChange({ ...d, entry: { ...d.entry, [side]: c } });
  const setExit = (patch: Partial<VisualDefinition["exit"]>) => onChange({ ...d, exit: { ...d.exit, ...patch } });

  return (
    <Card className="min-h-0">
      <CardHeader>
        <CardTitle>Rules</CardTitle>
        <span className="text-small text-fg-muted">Checked on every closed candle; orders fill at the next candle's open.</span>
      </CardHeader>
      <CardBody className="flex flex-col gap-6">
        <EnvContext.Provider value={env}>
          <Section icon={<ArrowUpRight />} title="Buy when" subtitle="Opens a trade that profits if the price rises." tone="profit">
            <Rule value={d.entry.long} onChange={(c) => setEntry("long", c)} path={["entry", "long"]} emptyLabel="Add a buy rule" />
          </Section>
          {canShort && (
            <Section icon={<ArrowDownRight />} title="Short-sell when" subtitle="Optional. Profits if the price falls." tone="loss">
              <Rule value={d.entry.short} onChange={(c) => setEntry("short", c)} path={["entry", "short"]} emptyLabel="Add a short-sell rule" />
            </Section>
          )}
        </EnvContext.Provider>
        <EnvContext.Provider value={exitEnv}>
          {d.entry.long && (
            <Section icon={<LogOut />} title="Sell when" subtitle="Closes a buy trade." tone="neutral">
              <Rule value={d.exit.long} onChange={(c) => setExit({ long: c })} path={["exit", "long"]} emptyLabel="Add a sell rule" />
            </Section>
          )}
          {canShort && d.entry.short && (
            <Section icon={<LogOut />} title="Buy back when" subtitle="Closes a short trade." tone="neutral">
              <Rule value={d.exit.short} onChange={(c) => setExit({ short: c })} path={["exit", "short"]} emptyLabel="Add a buy-back rule" />
            </Section>
          )}
          <Section icon={<Shield />} title="Protect each trade" subtitle="Checked during every candle, not just at the close." tone="neutral">
            <div className="flex flex-col gap-2">
              <StopRow label="Stop-loss" hint="Exit if the trade loses this much." value={d.exit.stop_loss} onChange={(v) => setExit({ stop_loss: v })} invalid={bad(["exit", "stop_loss"])} />
              <StopRow label="Take-profit" hint="Exit when the trade gains this much." value={d.exit.take_profit} onChange={(v) => setExit({ take_profit: v })} invalid={bad(["exit", "take_profit"])} />
              <StopRow label="Trailing stop" hint="A stop that follows the price up." value={d.exit.trailing_stop} onChange={(v) => setExit({ trailing_stop: v })} invalid={bad(["exit", "trailing_stop"])} />
              <PartialRow value={d.exit.scale_out ?? null} onChange={(v) => setExit({ scale_out: v })} invalid={bad(["exit", "scale_out"])} hasStop={d.exit.stop_loss !== null} />
              <div className={cn("flex flex-wrap items-center gap-2 rounded-tile border p-3", bad(["exit", "max_bars"]) ? "border-warning/60" : "border-hairline")}>
                <label className="flex w-40 items-center gap-2 text-[14px] font-medium">
                  <input type="checkbox" checked={d.exit.max_bars !== null} onChange={(e) => setExit({ max_bars: e.target.checked ? 20 : null })} className="size-4 accent-[var(--accent-strong)]" />
                  Time limit
                </label>
                {d.exit.max_bars !== null ? (
                  <>
                    <NumParam label="Most candles to hold" value={d.exit.max_bars} params={d.parameters} onChange={(v) => setExit({ max_bars: v })} className="w-[200px]" />
                    <span className="text-small text-fg-muted">candles at most</span>
                  </>
                ) : (
                  <span className="text-small text-fg-subtle">Exit after a number of candles.</span>
                )}
              </div>
              {d.timeframe !== "1d" && (
                <div className={cn("flex flex-wrap items-center gap-2 rounded-tile border p-3", bad(["exit", "exit_time"]) ? "border-warning/60" : "border-hairline")}>
                  <label className="flex w-40 items-center gap-2 text-[14px] font-medium">
                    <input type="checkbox" checked={d.exit.exit_time !== null} onChange={(e) => setExit({ exit_time: e.target.checked ? (d.market === "IN" ? "15:10" : "15:45") : null })} className="size-4 accent-[var(--accent-strong)]" />
                    Exit by
                  </label>
                  {d.exit.exit_time !== null ? (
                    <Input type="time" aria-label="Exit time" value={d.exit.exit_time} onChange={(e) => e.target.value && setExit({ exit_time: e.target.value })} className="w-[120px]" />
                  ) : (
                    <span className="text-small text-fg-subtle">Close trades at a set time of day.</span>
                  )}
                </div>
              )}
            </div>
          </Section>
        </EnvContext.Provider>
      </CardBody>
    </Card>
  );
}
