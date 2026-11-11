import { ChevronDown, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "../../components/ui/button";
import { Field, Input, NumberInput, Select } from "../../components/ui/input";
import { Popover } from "../../components/ui/popover";
import { Segmented } from "../../components/ui/segmented";
import {
  BIGGER,
  CHART_WORDS,
  FIELD_WORDS,
  operandText,
  type BiggerTf,
  type IndicatorInfo,
  type IndicatorOperand,
  type Operand,
  type ParameterDef,
  type PriceField,
} from "../../lib/strategy";
import type { Timeframe } from "../../lib/api";
import { cn } from "../../lib/utils";
import { NumParam } from "./NumParam";
import { useCatalog } from "./useCatalog";

const FIELDS = Object.keys(FIELD_WORDS) as PriceField[];

type ExtrasValue = { offset?: number; times?: number | string; chart?: BiggerTf | null };

function Extras({
  value,
  onChange,
  params,
  timeframe,
}: {
  value: ExtrasValue;
  onChange: (v: { offset: number; times: number | string; chart: BiggerTf | null }) => void;
  params: ParameterDef[];
  timeframe: Timeframe;
}) {
  const now = { offset: value.offset ?? 0, times: value.times ?? 1, chart: value.chart ?? null };
  const bigger = BIGGER[timeframe] ?? [];
  return (
    <div className="flex flex-col gap-3">
      {bigger.length > 0 && (
        <Field label="Read on" hint="A bigger chart of the same stock, on its last finished candle: fewer false signals.">
          <Select aria-label="Read on" value={now.chart ?? ""} onChange={(e) => onChange({ ...now, chart: (e.target.value || null) as BiggerTf | null })}>
            <option value="">This chart</option>
            {bigger.map((t) => (
              <option key={t} value={t}>
                The {CHART_WORDS[t]} chart
              </option>
            ))}
          </Select>
        </Field>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Candles ago" hint="0 = the latest closed candle.">
          <NumberInput aria-label="Candles ago" value={now.offset} min={0} max={500} step={1} onChange={(v) => onChange({ ...now, offset: Math.max(0, Math.round(v ?? 0)) })} />
        </Field>
        <Field label="Multiply by" hint="1.02 = 2% above.">
          <NumParam label="Multiply by" value={now.times} params={params} onChange={(t) => onChange({ ...now, times: t })} />
        </Field>
      </div>
    </div>
  );
}

function IndicatorForm({
  value,
  onChange,
  info,
  params,
  timeframe,
}: {
  value: IndicatorOperand;
  onChange: (v: IndicatorOperand) => void;
  info: IndicatorInfo;
  params: ParameterDef[];
  timeframe: Timeframe;
}) {
  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-small text-fg-muted">{info.description}</p>
      {info.params.length > 0 && (
        <div className="grid grid-cols-2 gap-3">
          {info.params.map((p) => (
            <Field key={p.name} label={p.label}>
              <NumParam
                label={p.label}
                value={value.params[p.name] ?? p.default}
                params={params}
                min={p.min}
                max={p.max}
                onChange={(v) => onChange({ ...value, params: { ...value.params, [p.name]: v } })}
              />
            </Field>
          ))}
        </div>
      )}
      {info.outputs.length > 1 && (
        <Field label="Which line">
          <Select value={value.output ?? info.outputs[0]?.key} onChange={(e) => onChange({ ...value, output: e.target.value })}>
            {info.outputs.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {info.uses_source && (
        <Field label="Computed on">
          <Select value={value.source ?? info.default_source} onChange={(e) => onChange({ ...value, source: e.target.value as PriceField })}>
            {FIELDS.map((f) => (
              <option key={f} value={f}>
                {FIELD_WORDS[f]}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Extras value={value} params={params} timeframe={timeframe} onChange={(x) => onChange({ ...value, ...x })} />
    </div>
  );
}

/** Pick what one side of a rule is: a price, an indicator line, or a number. */
export function OperandPicker({
  value,
  onChange,
  params,
  timeframe,
  invalid,
  label,
}: {
  value: Operand;
  onChange: (v: Operand) => void;
  params: ParameterDef[];
  timeframe: Timeframe;
  invalid?: boolean;
  label: string;
}) {
  const catalog = useCatalog();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("All");
  const groups = useMemo(() => {
    const seen = new Set<string>();
    for (const i of catalog ? Object.values(catalog) : []) if (i.group) seen.add(i.group);
    return ["All", ...seen];
  }, [catalog]);
  const list = useMemo(() => {
    const all = catalog ? Object.values(catalog) : [];
    const q = query.trim().toLowerCase();
    return all.filter(
      (i) =>
        (!q || i.label.toLowerCase().includes(q) || i.key.includes(q) || i.description.toLowerCase().includes(q)) &&
        (q || group === "All" || i.group === group),
    );
  }, [catalog, query, group]);

  function choose(info: IndicatorInfo) {
    onChange({
      kind: "indicator",
      name: info.key,
      params: Object.fromEntries(info.params.map((p) => [p.name, p.default])),
      output: info.outputs.length > 1 ? info.outputs[0]?.key : undefined,
    });
  }

  const text = operandText(value, catalog ?? undefined, params);
  const info = value.kind === "indicator" ? catalog?.[value.name] : undefined;

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      className="w-[400px]"
      trigger={
        <button
          type="button"
          aria-label={`${label}: ${text}`}
          className={cn(
            "inline-flex h-9 max-w-[280px] items-center gap-1.5 rounded-control border px-3 text-[14px] font-semibold transition-colors",
            value.kind === "number" ? "border-border bg-surface text-fg" : "border-accent/30 bg-accent-soft text-accent-soft-fg",
            invalid && "border-warning ring-2 ring-warning/30",
          )}
        >
          <span className="truncate">{text || "Choose…"}</span>
          <ChevronDown className="size-3.5 shrink-0 opacity-60" aria-hidden="true" />
        </button>
      }
    >
      <div className="flex flex-col gap-4">
        <Segmented
          label="Kind"
          value={value.kind}
          onChange={(k) => {
            if (k === value.kind) return;
            if (k === "number") onChange({ kind: "number", value: 30 });
            else if (k === "price") onChange({ kind: "price", field: "close" });
            else if (catalog?.rsi) choose(catalog.rsi);
          }}
          options={[
            { value: "indicator", label: "Indicator" },
            { value: "price", label: "Price" },
            { value: "number", label: "Number" },
          ]}
        />
        {value.kind === "number" && (
          <Field label="Value">
            <NumParam label="Value" value={value.value} params={params} onChange={(v) => onChange({ kind: "number", value: v })} />
          </Field>
        )}
        {value.kind === "price" && (
          <div className="flex flex-col gap-3">
            <Field label="Price">
              <Select value={value.field} onChange={(e) => onChange({ ...value, field: e.target.value as PriceField })}>
                {FIELDS.map((f) => (
                  <option key={f} value={f}>
                    {FIELD_WORDS[f]}
                  </option>
                ))}
              </Select>
            </Field>
            <Extras value={value} params={params} timeframe={timeframe} onChange={(x) => onChange({ ...value, ...x })} />
          </div>
        )}
        {value.kind === "indicator" && (
          <div className="flex flex-col gap-3">
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
              <Input aria-label="Search indicators" placeholder="Search indicators" value={query} onChange={(e) => setQuery(e.target.value)} className="w-full pl-9" />
            </div>
            {groups.length > 2 && !query.trim() && (
              <div className="flex flex-wrap gap-1" role="group" aria-label="Indicator group">
                {groups.map((g) => (
                  <button
                    key={g}
                    type="button"
                    aria-pressed={group === g}
                    onClick={() => setGroup(g)}
                    className={cn(
                      "h-6 rounded-full px-2 text-tiny transition-colors",
                      group === g ? "bg-surface-2 font-semibold text-fg" : "text-fg-muted hover:text-fg",
                    )}
                  >
                    {g}
                  </button>
                ))}
              </div>
            )}
            <div className="flex max-h-36 flex-wrap gap-1.5 overflow-y-auto">
              {list.map((i) => {
                const disabled = i.intraday_only && timeframe === "1d";
                return (
                  <button
                    key={i.key}
                    type="button"
                    disabled={disabled}
                    title={disabled ? "Only works on intraday candles" : i.description}
                    onClick={() => choose(i)}
                    className={cn(
                      "h-7 rounded-full border px-2.5 text-tiny transition-colors disabled:opacity-40",
                      i.key === value.name ? "border-accent bg-accent-soft font-semibold text-accent-soft-fg" : "border-border hover:bg-surface-2",
                    )}
                  >
                    {i.label.replace(/ \(.*\)$/, "")}
                  </button>
                );
              })}
            </div>
            {info && <IndicatorForm value={value} onChange={onChange} info={info} params={params} timeframe={timeframe} />}
          </div>
        )}
        <div className="flex justify-end">
          <Button size="sm" variant="primary" onClick={() => setOpen(false)}>
            Done
          </Button>
        </div>
      </div>
    </Popover>
  );
}
