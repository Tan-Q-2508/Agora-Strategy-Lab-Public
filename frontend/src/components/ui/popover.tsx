import { Popover as P } from "radix-ui";
import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

export function Popover({
  trigger,
  children,
  open,
  onOpenChange,
  align = "start",
  className,
}: {
  trigger: ReactNode;
  children: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  align?: "start" | "center" | "end";
  className?: string;
}) {
  return (
    <P.Root open={open} onOpenChange={onOpenChange}>
      <P.Trigger asChild>{trigger}</P.Trigger>
      <P.Portal>
        <P.Content
          align={align}
          sideOffset={6}
          collisionPadding={12}
          className={cn("z-50 w-80 rounded-card border border-border bg-surface p-4 shadow-e3 outline-none", className)}
        >
          {children}
        </P.Content>
      </P.Portal>
    </P.Root>
  );
}
