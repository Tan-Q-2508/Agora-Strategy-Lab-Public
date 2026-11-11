import { X } from "lucide-react";
import { InstrumentSelect } from "../../components/InstrumentSelect";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { Field, NumberInput, Select } from "../../components/ui/input";
import { Segmented } from "../../components/ui/segmented";
import type { MarketCode, Timeframe } from "../../lib/api";
import { TIMEFRAME_LABEL } from "../../lib/format";
import {
  defaultProduct,
  PRODUCT_WORDS,
  SIZING_WORDS,
  type Definition,
  type Issue,
  type SizingKind,
} from "../../lib/strategy";
import { cn } from "../../lib/utils";
import { NumParam } from "./NumParam";

const TIMEFRAMES: Timeframe[] = ["1d", "1h", "15m", "5m", "1m"];

function issueFor(issues: Issue[], key: string): Issue | undefined {
  return issues.find((i) => i.path[0] === key && i.severity === "error");
}

/** Market, stocks, timeframe, trade type, sizing and limits (shared by blocks and code). */
export function SettingsPanel<D extends Definition>({ d, onChange, issues }: { d: D; onChange: (d: D) => void; issues: Issue[] }) {
  const set = (patch: Partial<Definition>) => onChange({ ...d, ...patch } as D);
  const uni = issueFor(issues, "universe");
  const sizingIssue = issueFor(issues, "sizing");

  const ranking = d.kind === "ranking";

  function setMarket(m: MarketCode) {
    if (m === d.market) return;
    set({
      market: m,
      universe: ranking ? { kind: "all", symbols: [] } : { kind: "symbols", symbols: m === "IN" ? ["RELIANCE"] : ["SPY"] },
      product: defaultProduct(m, d.timeframe),
    });
  }

  function setTimeframe(tf: Timeframe) {
    const product = d.market === "US" ? "cash" : tf === "1d" ? (d.product === "intraday" ? "intraday" : "delivery") : "intraday";
    const patch: Partial<Definition> = { timeframe: tf, product };
    if (d.kind === "visual" && tf === "1d" && d.exit.exit_time) {
      onChange({ ...d, ...patch, exit: { ...d.exit, exit_time: null } } as D);
      return;
    }
    set(patch);
  }

  const sizing = SIZING_WORDS[d.sizing.kind];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Settings</CardTitle>
      </CardHeader>
      <CardBody className="flex flex-col gap-4">
        <Field label="Market">
          <Segmented
            label="Market"
            value={d.market}
            onChange={setMarket}
            options={[
              { value: "IN", label: "India" },
              { value: "US", label: "US" },
            ]}
          />
        </Field>
        <Field label="Stocks" hint={uni ? <span className="text-warning">{uni.message} {uni.hint}</span> : "Which stocks the rules run on."}>
          <Segmented
            label="Stocks"
            value={d.universe.kind}
            onChange={(k) => set({ universe: { kind: k, symbols: k === "all" ? [] : d.universe.symbols.length ? d.universe.symbols : [d.market === "IN" ? "RELIANCE" : "SPY"] } })}
            options={[
              { value: "symbols", label: "Chosen stocks" },
              { value: "all", label: d.market === "IN" ? "All Nifty 50" : "All my US stocks" },
            ]}
          />
          {d.universe.kind === "symbols" && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {d.universe.symbols.map((sym) => (
                <span key={sym} className="inline-flex h-8 items-center gap-1 rounded-full border border-border bg-surface-2 pr-1 pl-3 text-small font-semibold">
                  {sym}
                  <button
                    type="button"
                    aria-label={`Remove ${sym}`}
                    onClick={() => set({ universe: { kind: "symbols", symbols: d.universe.symbols.filter((s) => s !== sym) } })}
                    className="rounded-full p-1 text-fg-muted hover:bg-surface hover:text-fg"
                  >
                    <X className="size-3" aria-hidden="true" />
                  </button>
                </span>
              ))}
              <InstrumentSelect
                key={d.universe.symbols.join(",")}
                label="Add a stock"
                market={d.market}
                value={null}
                onChange={(inst) =>
                  !d.universe.symbols.includes(inst.symbol) && inst.type !== "index" && set({ universe: { kind: "symbols", symbols: [...d.universe.symbols, inst.symbol] } })
                }
                className="[&_select]:h-8 [&_select]:w-[190px]"
              />
            </div>
          )}
        </Field>
        {ranking ? (
          <p className="m-0 text-small text-fg-muted">
            Daily candles, re-ranked on the first trading day of each month. Each stock held gets an equal share: 95% of the money ÷ the stocks held. {d.market === "IN" ? "Delivery trades (held overnight)." : "Cash trades."}
          </p>
        ) : (
        <>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Timeframe" hint="The length of each candle.">
            <Select value={d.timeframe} onChange={(e) => setTimeframe(e.target.value as Timeframe)}>
              {TIMEFRAMES.map((t) => (
                <option key={t} value={t}>
                  {TIMEFRAME_LABEL[t]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Trade type" hint={d.market === "IN" ? "Intraday trades close the same day." : "US trades can be held overnight."}>
            <Select value={d.product} disabled={d.market === "US"} onChange={(e) => set({ product: e.target.value as Definition["product"] })}>
              {(d.market === "US" ? (["cash"] as const) : (["delivery", "intraday"] as const)).map((p) => (
                <option key={p} value={p}>
                  {PRODUCT_WORDS[p]}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Trade size" hint={sizingIssue ? <span className="text-warning">{sizingIssue.message} {sizingIssue.hint}</span> : sizing.hint}>
          <div className="flex gap-2">
            <Select
              aria-label="Sizing method"
              value={d.sizing.kind}
              onChange={(e) => {
                const kind = e.target.value as SizingKind;
                const v = { percent_equity: 10, fixed_amount: d.market === "IN" ? 100000 : 10000, fixed_qty: 10, risk_percent: 1 }[kind];
                set({ sizing: { kind, value: v } });
              }}
              className="flex-1"
            >
              {(Object.keys(SIZING_WORDS) as SizingKind[]).map((k) => (
                <option key={k} value={k}>
                  {SIZING_WORDS[k].label}
                </option>
              ))}
            </Select>
            <NumParam label="Size" value={d.sizing.value} params={d.parameters} onChange={(v) => set({ sizing: { ...d.sizing, value: v } })} className="w-[170px]" invalid={!!sizingIssue} />
          </div>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Most trades open at once">
            <NumberInput value={d.limits.max_open_positions} min={1} max={100} step={1} onChange={(v) => set({ limits: { ...d.limits, max_open_positions: Math.max(1, Math.round(v ?? 1)) } })} />
          </Field>
          <Field label="Stop for the day after losing (%)" hint="Leave empty for no daily limit.">
            <NumberInput
              value={d.limits.max_daily_loss_pct}
              min={0.1}
              max={100}
              onChange={(v) => set({ limits: { ...d.limits, max_daily_loss_pct: v && v > 0 ? v : null } })}
              className={cn(issueFor(issues, "limits") && "border-warning")}
            />
          </Field>
        </div>
        </>
        )}
      </CardBody>
    </Card>
  );
}
