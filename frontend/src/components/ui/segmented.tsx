import { ToggleGroup } from "radix-ui";
import { cn } from "../../lib/utils";

export interface SegmentedOption<V extends string> {
  value: V;
  label: string;
}

/** A small set of mutually exclusive choices (e.g. Light / Dark / System). */
export function Segmented<V extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: V;
  options: SegmentedOption<V>[];
  onChange: (value: V) => void;
  label: string;
}) {
  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      aria-label={label}
      onValueChange={(v) => v && onChange(v as V)}
      className="inline-flex rounded-[9px] bg-surface-2 p-[3px]"
    >
      {options.map((o) => (
        <ToggleGroup.Item
          key={o.value}
          value={o.value}
          className={cn(
            "h-9 rounded-[7px] px-4 text-[14px] text-fg-muted transition-colors duration-150",
            "data-[state=on]:bg-surface data-[state=on]:font-semibold data-[state=on]:text-fg data-[state=on]:shadow-e1",
          )}
        >
          {o.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}
