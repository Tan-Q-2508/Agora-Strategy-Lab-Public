import { Reorder, useDragControls } from "framer-motion";
import { AlertTriangle, Clock, GripVertical, MoreHorizontal, Plus, Timer, Trash2 } from "lucide-react";
import { useContext } from "react";
import { Button } from "../../components/ui/button";
import { Input, Select } from "../../components/ui/input";
import { Menu } from "../../components/ui/menu";
import { spring } from "../../lib/motion";
import {
  defaultCompare,
  OP_WORDS,
  pathWithin,
  type AllOf,
  type AnyOf,
  type CompareOp,
  type Condition,
  type Issue,
} from "../../lib/strategy";
import { cn } from "../../lib/utils";
import { carry, EnvContext, keyOf, type Path } from "./env";
import { NumParam } from "./NumParam";
import { OperandPicker } from "./OperandPicker";

function issuesAt(issues: Issue[], path: Path, exact = false): Issue[] {
  return issues.filter((i) => (exact ? i.path.length === path.length && pathWithin(i.path, path) : pathWithin(i.path, path)));
}

function Hint({ issues }: { issues: Issue[] }) {
  const first = issues.find((i) => i.severity === "error") ?? issues[0];
  if (!first) return null;
  return (
    <p className={cn("m-0 mt-1.5 flex items-center gap-1.5 text-tiny", first.severity === "error" ? "text-warning" : "text-fg-subtle")}>
      <AlertTriangle className="size-3.5 shrink-0" aria-hidden="true" />
      {first.message} {first.hint}
    </p>
  );
}

const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

function TimeInput({ value, onChange, label }: { value: string | null | undefined; onChange: (v: string | null) => void; label: string }) {
  return (
    <Input
      type="time"
      aria-label={label}
      value={value ?? ""}
      onChange={(e) => onChange(TIME_RE.test(e.target.value) ? e.target.value : null)}
      className="w-[120px]"
    />
  );
}

function Leaf({ c, onChange, path }: { c: Condition; onChange: (c: Condition) => void; path: Path }) {
  const env = useContext(EnvContext);
  const bad = (sub: string) => issuesAt(env.issues, [...path, sub]).some((i) => i.severity === "error");
  const update = (next: Condition) => onChange(carry(c, next));
  switch (c.type) {
    case "compare":
      return (
        <div className="flex flex-wrap items-center gap-2">
          <OperandPicker label="Left side" value={c.left} onChange={(left) => update({ ...c, left })} params={env.params} timeframe={env.timeframe} invalid={bad("left")} />
          <Select aria-label="Comparison" value={c.op} onChange={(e) => update({ ...c, op: e.target.value as CompareOp })} className="h-9 w-auto">
            {(Object.keys(OP_WORDS) as CompareOp[]).map((op) => (
              <option key={op} value={op}>
                {OP_WORDS[op]}
              </option>
            ))}
          </Select>
          <OperandPicker label="Right side" value={c.right} onChange={(right) => update({ ...c, right })} params={env.params} timeframe={env.timeframe} invalid={bad("right")} />
        </div>
      );
    case "between":
      return (
        <div className="flex flex-wrap items-center gap-2">
          <OperandPicker label="Value" value={c.value} onChange={(value) => update({ ...c, value })} params={env.params} timeframe={env.timeframe} invalid={bad("value")} />
          <span className="text-small text-fg-muted">is between</span>
          <OperandPicker label="Lower limit" value={c.lower} onChange={(lower) => update({ ...c, lower })} params={env.params} timeframe={env.timeframe} invalid={bad("lower")} />
          <span className="text-small text-fg-muted">and</span>
          <OperandPicker label="Upper limit" value={c.upper} onChange={(upper) => update({ ...c, upper })} params={env.params} timeframe={env.timeframe} invalid={bad("upper")} />
        </div>
      );
    case "time":
      return (
        <div className="flex flex-wrap items-center gap-2 text-[14px]">
          <Clock className="size-4 text-fg-muted" aria-hidden="true" />
          <span className="text-fg-muted">Candle opens after</span>
          <TimeInput label="After" value={c.after} onChange={(after) => update({ ...c, after })} />
          <span className="text-fg-muted">and before</span>
          <TimeInput label="Before" value={c.before} onChange={(before) => update({ ...c, before })} />
        </div>
      );
    case "position":
      return (
        <div className="flex flex-wrap items-center gap-2 text-[14px]">
          <Timer className="size-4 text-fg-muted" aria-hidden="true" />
          <Select aria-label="Trade check" value={c.check} onChange={(e) => update({ ...c, check: e.target.value as typeof c.check })} className="h-9 w-auto">
            <option value="bars_held_at_least">In the trade for at least (candles)</option>
            <option value="profit_pct_at_least">Profit is at least (%)</option>
            <option value="loss_pct_at_least">Loss is at least (%)</option>
          </Select>
          <NumParam label="Amount" value={c.value} params={env.params} onChange={(value) => update({ ...c, value })} className="w-[220px]" />
        </div>
      );
    default:
      return null;
  }
}

function Item({
  c,
  path,
  depth,
  onChange,
  onRemove,
}: {
  c: Condition;
  path: Path;
  depth: number;
  onChange: (c: Condition) => void;
  onRemove: () => void;
}) {
  const env = useContext(EnvContext);
  const controls = useDragControls();
  const negated = c.type === "not";
  const inner = negated ? c.condition : c;
  const innerPath = negated ? [...path, "condition"] : path;
  const own = issuesAt(env.issues, path).filter((i) => !(inner.type === "all" || inner.type === "any") || i.path.length <= innerPath.length);
  const hasError = own.some((i) => i.severity === "error");
  const isGroup = inner.type === "all" || inner.type === "any";

  function setInner(next: Condition) {
    onChange(negated ? carry(c, { type: "not", condition: next }) : carry(c, next));
  }

  return (
    <Reorder.Item
      value={c}
      dragListener={false}
      dragControls={controls}
      transition={spring}
      className={cn(
        "relative list-none rounded-tile border bg-surface p-3 transition-shadow",
        hasError ? "border-warning/60 shadow-[0_0_0_3px] shadow-warning/15" : "border-hairline",
      )}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          aria-label="Drag to reorder"
          onPointerDown={(e) => controls.start(e)}
          className="mt-1.5 cursor-grab touch-none rounded p-0.5 text-fg-subtle hover:text-fg active:cursor-grabbing"
        >
          <GripVertical className="size-4" aria-hidden="true" />
        </button>
        <div className="min-w-0 flex-1">
          {negated && <span className="mb-1.5 inline-block rounded-full bg-surface-2 px-2 py-0.5 text-tiny font-semibold text-fg-muted">NOT</span>}
          {isGroup ? (
            <Group group={inner as AllOf | AnyOf} path={innerPath} depth={depth + 1} onChange={setInner} />
          ) : (
            <Leaf c={inner} path={innerPath} onChange={setInner} />
          )}
          {!isGroup && <Hint issues={own} />}
        </div>
        <Menu
          trigger={
            <Button size="icon-sm" variant="ghost" aria-label="Condition options">
              <MoreHorizontal aria-hidden="true" />
            </Button>
          }
          items={[
            { label: negated ? "Remove NOT" : "Turn into NOT", onSelect: () => onChange(negated ? carry(c, c.condition) : carry(c, { type: "not", condition: c })) },
            ...(!isGroup && depth < 3 ? [{ label: "Wrap in a group", onSelect: () => onChange(carry(c, { type: "all", conditions: [c] } as AllOf)) }] : []),
          ]}
        />
        <Button size="icon-sm" variant="ghost" aria-label="Remove condition" onClick={onRemove}>
          <Trash2 aria-hidden="true" />
        </Button>
      </div>
    </Reorder.Item>
  );
}

function newCondition(kind: "compare" | "time" | "position" | "between" | "group"): Condition {
  if (kind === "time") return { type: "time", after: "09:30", before: "15:00" };
  if (kind === "position") return { type: "position", check: "bars_held_at_least", value: 10 };
  if (kind === "between")
    return { type: "between", value: { kind: "indicator", name: "rsi", params: { period: 14 } }, lower: { kind: "number", value: 40 }, upper: { kind: "number", value: 60 } };
  if (kind === "group") return { type: "any", conditions: [defaultCompare()] };
  return defaultCompare();
}

export function Group({
  group,
  path,
  depth,
  onChange,
  childPath,
}: {
  group: AllOf | AnyOf;
  path: Path;
  depth: number;
  onChange: (g: Condition) => void;
  childPath?: (i: number) => Path;
}) {
  const env = useContext(EnvContext);
  const pathOf = childPath ?? ((i: number) => [...path, "conditions", i]);
  const own = issuesAt(env.issues, path, true);

  function set(conditions: Condition[]) {
    onChange(carry(group, { ...group, conditions }));
  }

  function add(kind: Parameters<typeof newCondition>[0]) {
    set([...group.conditions, newCondition(kind)]);
  }

  return (
    <div className="flex flex-col gap-2">
      {group.conditions.length > 1 && (
        <div className="flex items-center gap-2 text-small text-fg-muted">
          <Select
            aria-label="How conditions combine"
            value={group.type}
            onChange={(e) => onChange(carry(group, { ...group, type: e.target.value as "all" | "any" }))}
            className="h-8 w-auto text-small font-semibold"
          >
            <option value="all">ALL of these are true</option>
            <option value="any">ANY of these is true</option>
          </Select>
        </div>
      )}
      <Reorder.Group axis="y" values={group.conditions} onReorder={set} className="m-0 flex flex-col gap-2 p-0">
        {group.conditions.map((c, i) => (
          <Item
            key={keyOf(c)}
            c={c}
            path={pathOf(i)}
            depth={depth}
            onChange={(next) => set(group.conditions.map((x, j) => (j === i ? next : x)))}
            onRemove={() => set(group.conditions.filter((_, j) => j !== i))}
          />
        ))}
      </Reorder.Group>
      <Hint issues={own} />
      <div className="flex gap-2">
        <Button size="sm" variant="ghost" onClick={() => add("compare")}>
          <Plus aria-hidden="true" />
          Condition
        </Button>
        <Menu
          align="start"
          trigger={
            <Button size="sm" variant="ghost">
              More…
            </Button>
          }
          items={[
            { label: "Between two values", onSelect: () => add("between") },
            ...(env.timeframe !== "1d" ? [{ label: "Time of day", onSelect: () => add("time") }] : []),
            ...(env.exitRule ? [{ label: "Trade check (candles held, profit, loss)", onSelect: () => add("position") }] : []),
            ...(depth < 3 ? [{ label: "A group (AND / OR)", onSelect: () => add("group") }] : []),
          ]}
        />
      </div>
    </div>
  );
}

/**
 * One rule (e.g. "Buy when …"). Its condition may be a single block or a group; it is
 * always shown as a group, and a group of one is saved as just that block.
 */
export function RuleEditor({ value, onChange, path }: { value: Condition | null; onChange: (c: Condition | null) => void; path: Path }) {
  const isGroup = value !== null && (value.type === "all" || value.type === "any");
  const group: AllOf | AnyOf = isGroup ? (value as AllOf | AnyOf) : { type: "all", conditions: value ? [value] : [] };

  function save(next: Condition) {
    if (next.type === "all" || next.type === "any") {
      if (next.conditions.length === 0) return onChange(null);
      if (next.conditions.length === 1) return onChange(next.conditions[0] ?? null);
    }
    onChange(next);
  }

  return (
    <Group
      group={group}
      path={path}
      depth={0}
      onChange={save}
      childPath={isGroup ? undefined : () => path}
    />
  );
}
