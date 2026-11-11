/** A ranking strategy's rules in the builder (D-91): what it ranks by, over how long, and how
 * many of the top stocks it holds each month. */
import { ListOrdered } from "lucide-react";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { Field, NumberInput } from "../../components/ui/input";
import { Segmented } from "../../components/ui/segmented";
import { describeRanking, type Issue, type RankingDefinition, type RankingSettings } from "../../lib/strategy";

export function RankingRulesPanel({ d, onChange, issues }: { d: RankingDefinition; onChange: (d: RankingDefinition) => void; issues: Issue[] }) {
  const r = d.ranking;
  const set = (patch: Partial<RankingSettings>) => {
    const next = { ...r, ...patch };
    // its trade size and open-trade limit follow from what it holds (the backend does the same)
    onChange({
      ...d,
      ranking: next,
      sizing: { kind: "percent_equity", value: Math.round((95 / next.hold) * 100) / 100 },
      limits: { ...d.limits, max_open_positions: Math.min(100, 2 * next.hold) },
    });
  };
  const issue = (key: string) => issues.find((i) => i.path[0] === "ranking" && i.path[1] === key);
  const momentum = r.rank_by === "momentum";
  const whole = (n: number | null, lo: number, hi: number) => Math.min(hi, Math.max(lo, Math.round(n ?? lo)));
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <ListOrdered className="size-4 text-accent" aria-hidden="true" />
            Ranking
          </CardTitle>
          <p className="m-0 text-tiny text-fg-subtle">Compares the stocks with each other every month and holds the best-ranked few, instead of reading one chart at a time.</p>
        </div>
      </CardHeader>
      <CardBody className="flex flex-col gap-4">
        <Field label="Rank by" hint={momentum ? "Momentum: the stocks that rose most. Winners tend to keep winning for a few months." : "Low volatility: the calmest stocks. They have earned about as much as wild ones with smaller drops."}>
          <Segmented
            label="Rank by"
            value={r.rank_by}
            onChange={(v) => set(v === "momentum" ? { rank_by: v, skip_months: 1, lookback_months: 12 } : { rank_by: v, skip_months: 0, lookback_months: 6 })}
            options={[
              { value: "momentum", label: "Momentum" },
              { value: "low_volatility", label: "Low volatility" },
            ]}
          />
        </Field>
        <div className="grid grid-cols-3 gap-4">
          <Field label="Months ranked on" hint={issue("lookback_months")?.message ?? "How much history each ranking looks at."} htmlFor="rank-lookback">
            <NumberInput id="rank-lookback" value={r.lookback_months} min={1} max={24} step={1} onChange={(n) => set({ lookback_months: whole(n, 1, 24) })} />
          </Field>
          {momentum && (
            <Field label="Latest months left out" hint={issue("skip_months")?.message ?? "The last month tends to reverse, so classic momentum skips it."} htmlFor="rank-skip">
              <NumberInput id="rank-skip" value={r.skip_months} min={0} max={3} step={1} onChange={(n) => set({ skip_months: whole(n, 0, 3) })} />
            </Field>
          )}
          <Field label="Stocks held" hint={issue("hold")?.message ?? "Fewer is more concentrated; more is steadier."} htmlFor="rank-hold">
            <NumberInput id="rank-hold" value={r.hold} min={1} max={30} step={1} onChange={(n) => set({ hold: whole(n, 1, 30) })} />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-small">
          <input type="checkbox" checked={r.trend_filter} onChange={(e) => set({ trend_filter: e.target.checked })} />
          {momentum ? "Only stocks that actually rose over the period" : "Only stocks above their 200-day average"}
        </label>
        <p className="m-0 rounded-tile bg-surface-2 p-3 text-[14px]">{describeRanking(r)}</p>
      </CardBody>
    </Card>
  );
}
