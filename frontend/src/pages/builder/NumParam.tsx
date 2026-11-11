import { NumberInput, Select } from "../../components/ui/input";
import type { Num, ParameterDef } from "../../lib/strategy";
import { cn } from "../../lib/utils";

/**
 * A number, or a named parameter ("$name") so sweeps can vary it. Shows a number box, and
 * a parameter picker when the strategy has parameters.
 */
export function NumParam({
  value,
  onChange,
  params,
  label,
  min,
  max,
  className,
  invalid,
}: {
  value: Num;
  onChange: (v: Num) => void;
  params: ParameterDef[];
  label: string;
  min?: number;
  max?: number;
  className?: string;
  invalid?: boolean;
}) {
  const isRef = typeof value === "string" && value.startsWith("$");
  return (
    <div className={cn("flex gap-1.5", className)}>
      {isRef ? (
        <Select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className="min-w-0 flex-1" aria-invalid={invalid}>
          {params.map((p) => (
            <option key={p.name} value={`$${p.name}`}>
              {p.label} ({p.default})
            </option>
          ))}
          {!params.some((p) => `$${p.name}` === value) && <option value={value}>{String(value).slice(1)} (missing)</option>}
        </Select>
      ) : (
        <NumberInput
          aria-label={label}
          aria-invalid={invalid}
          value={typeof value === "number" ? value : Number(value)}
          min={min}
          max={max}
          onChange={(v) => onChange(v ?? 0)}
          className="w-24 min-w-0 flex-1"
        />
      )}
      {params.length > 0 && (
        <Select
          aria-label={`${label}: number or parameter`}
          value={isRef ? "param" : "number"}
          onChange={(e) => {
            const first = params[0];
            if (e.target.value === "param" && first) onChange(`$${first.name}`);
            else if (e.target.value === "number") onChange(isRef ? (params.find((p) => `$${p.name}` === value)?.default ?? 0) : value);
          }}
          className="w-[110px] shrink-0 px-2 text-small"
        >
          <option value="number">Number</option>
          <option value="param">Parameter</option>
        </Select>
      )}
    </div>
  );
}
