import { Plus, Trash2 } from "lucide-react";
import { Button } from "../../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { Input, NumberInput, Select } from "../../components/ui/input";
import type { Definition, Issue, ParameterDef } from "../../lib/strategy";
import { cn } from "../../lib/utils";

function slug(label: string, taken: string[]): string {
  const base = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^(\d)/, "p_$1").slice(0, 24) || "value";
  let name = /^[a-z]/.test(base) ? base : `p_${base}`;
  let n = 2;
  while (taken.includes(name)) name = `${base}_${n++}`;
  return name;
}

/** Named settings that rules can refer to, and that sweeps can vary. */
export function ParametersPanel<D extends Definition>({ d, onChange, issues }: { d: D; onChange: (d: D) => void; issues: Issue[] }) {
  const set = (parameters: ParameterDef[]) => onChange({ ...d, parameters } as D);
  const update = (i: number, patch: Partial<ParameterDef>) => set(d.parameters.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Parameters</CardTitle>
          <p className="m-0 text-tiny text-fg-subtle">Name a number once, use it in any rule, and test many values with a sweep.</p>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            const label = `Setting ${d.parameters.length + 1}`;
            set([...d.parameters, { name: slug(label, d.parameters.map((p) => p.name)), label, type: "int", default: 14, min: 2, max: 50 }]);
          }}
          disabled={d.parameters.length >= 12}
        >
          <Plus aria-hidden="true" />
          Add
        </Button>
      </CardHeader>
      <CardBody className="flex flex-col gap-2">
        {d.parameters.length === 0 && <p className="m-0 text-small text-fg-subtle">No parameters yet.</p>}
        {d.parameters.map((p, i) => {
          const bad = issues.some((x) => x.path[0] === "parameters" && x.path[1] === i && x.severity === "error");
          return (
            <div key={i} className={cn("grid grid-cols-[1fr_76px_72px_72px_72px_auto] items-center gap-1.5 rounded-tile border p-2", bad ? "border-warning/60" : "border-hairline")}>
              <Input aria-label="Parameter name" value={p.label} maxLength={60} onChange={(e) => update(i, { label: e.target.value || p.label })} className="h-9" />
              <Select aria-label="Whole number or decimal" value={p.type} onChange={(e) => update(i, { type: e.target.value as "int" | "float" })} className="h-9 px-2 text-small">
                <option value="int">Whole</option>
                <option value="float">Decimal</option>
              </Select>
              <NumberInput aria-label="Default" title="Default" value={p.default} onChange={(v) => update(i, { default: v ?? 0 })} className="h-9 px-2" />
              <NumberInput aria-label="Smallest" title="Smallest" value={p.min} onChange={(v) => update(i, { min: v ?? 0 })} className="h-9 px-2" />
              <NumberInput aria-label="Largest" title="Largest" value={p.max} onChange={(v) => update(i, { max: v ?? 0 })} className="h-9 px-2" />
              <Button size="icon-sm" variant="ghost" aria-label={`Remove ${p.label}`} onClick={() => set(d.parameters.filter((_, j) => j !== i))}>
                <Trash2 aria-hidden="true" />
              </Button>
            </div>
          );
        })}
        {d.parameters.length > 0 && <p className="m-0 text-tiny text-fg-subtle">Columns: name · kind · default · smallest · largest.</p>}
      </CardBody>
    </Card>
  );
}
