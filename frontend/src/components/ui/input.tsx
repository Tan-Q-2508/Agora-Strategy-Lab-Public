import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const control =
  "h-10 rounded-control border border-border bg-surface px-3 text-[14px] text-fg placeholder:text-fg-subtle " +
  "transition-colors hover:border-fg-subtle/50 disabled:opacity-50 aria-[invalid=true]:border-warning";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(control, className)} {...props} />;
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(control, "pr-8", className)} {...props}>
      {children}
    </select>
  );
}

/** A labelled form field with an optional one-line explanation (CLAUDE.md §5). */
export function Field({
  label,
  hint,
  children,
  className,
  htmlFor,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
  htmlFor?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-small font-medium text-fg">
        {label}
      </label>
      {children}
      {hint && <p className="m-0 text-tiny text-fg-subtle">{hint}</p>}
    </div>
  );
}

/** A number box that keeps what the user typed until it parses (so "0." isn't eaten). */
export function NumberInput({
  value,
  onChange,
  min,
  max,
  step,
  className,
  ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & {
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <Input
      type="number"
      inputMode="decimal"
      value={value ?? ""}
      min={min}
      max={max}
      step={step ?? "any"}
      onChange={(e) => {
        const raw = e.target.value;
        if (raw === "") return onChange(null);
        const n = Number(raw);
        if (Number.isFinite(n)) onChange(n);
      }}
      className={cn("tabular-nums", className)}
      {...rest}
    />
  );
}
