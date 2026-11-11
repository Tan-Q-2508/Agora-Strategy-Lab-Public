import type { ReactNode } from "react";

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded-[5px] border border-border px-1.5 font-sans text-tiny text-fg-muted">{children}</kbd>;
}
