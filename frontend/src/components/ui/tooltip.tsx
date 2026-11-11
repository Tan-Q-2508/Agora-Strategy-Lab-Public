import { Tooltip as T } from "radix-ui";
import type { ReactNode } from "react";

export function TooltipProvider({ children }: { children: ReactNode }) {
  return <T.Provider delayDuration={300}>{children}</T.Provider>;
}

export function Tooltip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          sideOffset={6}
          className="z-50 max-w-72 rounded-control bg-fg px-3 py-2 text-small text-canvas shadow-e3"
        >
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}
