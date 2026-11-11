import { Tabs as T } from "radix-ui";
import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

export function Tabs({
  value,
  onValueChange,
  tabs,
  className,
  label,
}: {
  value: string;
  onValueChange: (v: string) => void;
  tabs: { value: string; label: ReactNode; content: ReactNode }[];
  className?: string;
  label: string;
}) {
  return (
    <T.Root value={value} onValueChange={onValueChange} className={cn("flex min-h-0 flex-col", className)}>
      <T.List aria-label={label} className="flex gap-1 border-b border-hairline px-5">
        {tabs.map((t) => (
          <T.Trigger
            key={t.value}
            value={t.value}
            className="relative -mb-px h-11 border-b-2 border-transparent px-3 text-[14px] text-fg-muted transition-colors hover:text-fg data-[state=active]:border-accent data-[state=active]:font-semibold data-[state=active]:text-fg"
          >
            {t.label}
          </T.Trigger>
        ))}
      </T.List>
      {tabs.map((t) => (
        <T.Content key={t.value} value={t.value} className="min-h-0 flex-1 outline-none">
          {t.content}
        </T.Content>
      ))}
    </T.Root>
  );
}
