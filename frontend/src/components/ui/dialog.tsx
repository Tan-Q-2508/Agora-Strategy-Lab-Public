import { X } from "lucide-react";
import { Dialog as D } from "radix-ui";
import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  className,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[2px] data-[state=open]:animate-[fade-in_150ms_ease-out]" />
        <D.Content
          aria-describedby={description ? undefined : undefined}
          className={cn(
            "fixed top-1/2 left-1/2 z-50 flex max-h-[86vh] w-[min(560px,92vw)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-card border border-border bg-surface shadow-e3",
            className,
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-hairline px-6 pt-5 pb-4">
            <div className="flex flex-col gap-1">
              <D.Title className="m-0 text-heading font-semibold">{title}</D.Title>
              {description ? (
                <D.Description className="m-0 text-small text-fg-muted">{description}</D.Description>
              ) : (
                <D.Description className="sr-only">{title}</D.Description>
              )}
            </div>
            <D.Close className="rounded-control p-1.5 text-fg-muted hover:bg-surface-2 hover:text-fg" aria-label="Close">
              <X className="size-4" aria-hidden="true" />
            </D.Close>
          </div>
          <div className="relative min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
          {footer && <div className="flex justify-end gap-2.5 border-t border-hairline px-6 py-4">{footer}</div>}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
