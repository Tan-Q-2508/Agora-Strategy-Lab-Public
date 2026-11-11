import { useEffect, useState } from "react";
import type { MarketStatus } from "../../lib/api";
import { formatCountdown } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { Dot, Pill } from "../ui/pill";
import { Skeleton } from "../ui/skeleton";
import { Tooltip } from "../ui/tooltip";

/** Seconds left, counting down locally between refreshes from the server. */
function useCountdown(seconds: number, receivedAt: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return Math.max(0, seconds - Math.floor((now - receivedAt) / 1000));
}

function MarketPill({ m, receivedAt }: { m: MarketStatus; receivedAt: number }) {
  const left = useCountdown(m.seconds_to_change, receivedAt);
  const verb = m.is_open ? "closes" : "opens";
  const tip = `${m.next_change_display}. Exchange holidays and early closes are included.`;
  return (
    <Tooltip content={tip} side="bottom">
      <Pill tone={m.is_open ? "profit" : "neutral"} tabIndex={0}>
        <Dot tone={m.is_open ? "profit" : "neutral"} live={m.is_open} />
        <b className="font-semibold">{m.name}</b>
        {m.is_open ? "Open" : "Closed"} · {verb} in {formatCountdown(left)}
      </Pill>
    </Tooltip>
  );
}

export function MarketPills() {
  const state = useApi<{ markets: MarketStatus[] }>("/markets/status", 60_000);
  if (state.status === "loading") {
    return (
      <div className="flex gap-2">
        <Skeleton className="h-8 w-56 rounded-full" />
        <Skeleton className="h-8 w-52 rounded-full" />
      </div>
    );
  }
  if (state.status === "error") {
    return <Pill tone="warning">Market hours unavailable</Pill>;
  }
  return (
    <div className="flex gap-2">
      {state.data.markets.map((m) => (
        <MarketPill key={m.market} m={m} receivedAt={state.receivedAt} />
      ))}
    </div>
  );
}
