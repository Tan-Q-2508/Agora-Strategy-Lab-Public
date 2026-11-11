/** The Kairos brain's settings in the builder: how sure it must be, where its stops and
 * targets go, and the signal weights it learned (read-only; "Study again" refreshes them). */
import { KairosMark } from "../../components/kairos/KairosMark";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { Field, NumberInput } from "../../components/ui/input";
import { Segmented } from "../../components/ui/segmented";
import type { Issue, KairosDefinition, KairosSettings, Num } from "../../lib/strategy";
import { formatDate } from "../../lib/format";

const FIELDS: { key: keyof KairosSettings; label: string; hint: string; step: number }[] = [
  { key: "entry_score", label: "Entry score", hint: "How convinced Kairos must be (out of 100) before it opens a trade.", step: 5 },
  { key: "exit_score", label: "Exit score", hint: "It leaves early when the score turns this far against the trade.", step: 5 },
  { key: "stop_atr", label: "Widest stop (ATRs)", hint: "The stop goes at the pattern's own invalidation price, or this many ATRs away if that is wider.", step: 0.5 },
  { key: "target_r", label: "Target (× the risk)", hint: "Used when a pattern has no measured move worth at least 1.5× the risk.", step: 0.5 },
  { key: "trail_atr", label: "Trailing stop (ATRs)", hint: "Optional. Follows the price to lock in gains. Leave empty for none.", step: 0.5 },
  { key: "partial_r", label: "Partial exit (× the risk)", hint: "Optional. Sells half the trade once it has made this many times its risk, then moves the stop to the entry. Leave empty for none.", step: 0.5 },
  { key: "max_bars", label: "Time limit (candles)", hint: "Leave a trade after this many candles. Leave empty for none.", step: 5 },
];

function isRef(v: Num | null): v is string {
  return typeof v === "string";
}

export function KairosRulesPanel({ d, onChange, issues }: { d: KairosDefinition; onChange: (d: KairosDefinition) => void; issues: Issue[] }) {
  const k = d.kairos;
  const set = (patch: Partial<KairosSettings>) => onChange({ ...d, kairos: { ...k, ...patch } });
  const weights = Object.entries(d.weights).sort((a, b) => b[1] - a[1]);
  const leaned = weights.filter(([, w]) => w > 1.05).slice(0, 6);
  const ignored = weights.filter(([, w]) => w < 0.5).slice(-6);
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <KairosMark />
            Kairos brain
          </CardTitle>
          <p className="m-0 text-tiny text-fg-subtle">
            Kairos scores every candle from chart patterns, levels, momentum, volume and candles, each weighted by how it has worked, and trades when the score is strong.
          </p>
        </div>
      </CardHeader>
      <CardBody className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-4">
          {FIELDS.map((f) => {
            const v = (k[f.key] ?? null) as Num | null;
            const issue = issues.find((i) => i.path[0] === "kairos" && i.path[1] === f.key);
            return (
              <Field key={f.key} label={f.label} hint={issue ? issue.message : isRef(v) ? `Uses the parameter “${v.slice(1)}” (change it under Parameters).` : f.hint} htmlFor={`kairos-${f.key}`}>
                <NumberInput
                  id={`kairos-${f.key}`}
                  value={isRef(v) ? (d.parameters.find((p) => p.name === v.slice(1))?.default ?? null) : (v as number | null)}
                  disabled={isRef(v)}
                  step={f.step}
                  onChange={(n) => set({ [f.key]: n } as Partial<KairosSettings>)}
                />
              </Field>
            );
          })}
        </div>
        <Field label="Short-selling" hint="Only where it's allowed: US stocks, and India intraday." className="w-[280px]">
          <Segmented
            label="Short-selling"
            value={k.allow_short ? "yes" : "no"}
            onChange={(v) => set({ allow_short: v === "yes" })}
            options={[
              { value: "yes", label: "Allowed" },
              { value: "no", label: "Buy only" },
            ]}
          />
        </Field>
        <div className="flex flex-col gap-1.5 rounded-tile border border-hairline p-3">
          <p className="m-0 text-small font-semibold">What it learned ({weights.length} signals)</p>
          <p className="m-0 text-tiny text-fg-subtle">
            {d.trained_at ? `Weights measured on ${formatDate(d.trained_at)}.` : "No weights yet: every signal counts the same until Kairos studies the history."} ×1 is average, ×2 is the most it leans on a signal, ×0 means it ignores it.
          </p>
          {leaned.length > 0 && <p className="m-0 text-small text-fg-muted">Leans on: {leaned.map(([key, w]) => `${label(key)} ×${w.toFixed(1)}`).join(" · ")}</p>}
          {ignored.length > 0 && <p className="m-0 text-small text-fg-muted">Ignores: {ignored.map(([key]) => label(key)).join(" · ")}</p>}
        </div>
      </CardBody>
    </Card>
  );
}

function label(key: string): string {
  const parts = key.split(":");
  const words = (parts[1] ?? key).replace(/_/g, " ");
  if (parts[0] === "pattern") return `${words} ${parts[2] === "down" ? "breakdown" : parts[2] === "up" ? "breakout" : parts[2] ?? ""}`.trim();
  return words;
}
