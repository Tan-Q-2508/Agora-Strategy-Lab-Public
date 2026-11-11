import { DropdownMenu as M } from "radix-ui";
import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

export interface MenuItem {
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
}

export function Menu({ trigger, items, align = "end" }: { trigger: ReactNode; items: MenuItem[]; align?: "start" | "end" }) {
  return (
    <M.Root>
      <M.Trigger asChild>{trigger}</M.Trigger>
      <M.Portal>
        <M.Content align={align} sideOffset={4} className="z-50 min-w-48 rounded-card border border-border bg-surface p-1.5 shadow-e3">
          {items.map((it) => (
            <M.Item
              key={it.label}
              disabled={it.disabled}
              onSelect={it.onSelect}
              className={cn(
                "flex h-9 cursor-pointer items-center gap-2.5 rounded-control px-2.5 text-[14px] outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-surface-2 [&_svg]:size-4",
                it.danger ? "text-loss" : "text-fg",
              )}
            >
              {it.icon}
              {it.label}
            </M.Item>
          ))}
        </M.Content>
      </M.Portal>
    </M.Root>
  );
}
