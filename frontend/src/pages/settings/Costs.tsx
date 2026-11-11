import { ErrorState, LoadingRows } from "../../components/states";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { Pill } from "../../components/ui/pill";
import type { CostProfiles, MarketCode } from "../../lib/api";
import { useApi } from "../../lib/useApi";

const PRODUCT = { intraday: "Intraday", delivery: "Delivery", cash: "Each order" } as const;

function ruleText(rule: unknown, market: MarketCode): string {
  const r = (rule ?? {}) as { flat?: number; percent?: number; cap?: number };
  const cur = market === "IN" ? "₹" : "$";
  if (r.percent !== undefined) return `${r.percent}% of the order${r.cap !== undefined ? `, at most ${cur}${r.cap}` : ""}`;
  if (!r.flat) return "Free";
  return `${cur}${r.flat} per order`;
}

const TAXES: Record<MarketCode, string> = {
  IN: "STT, exchange charges, SEBI fee, stamp duty, GST and the depository charge are added automatically, at the rates in force on each trade's date.",
  US: "The SEC fee and FINRA's trading activity fee on sales are added automatically, at the rates in force on each trade's date.",
};

/** Settings → Costs: the brokerage and slippage profiles backtests and paper accounts use. */
export function CostsPanel() {
  const data = useApi<CostProfiles>("/costs/profiles");
  if (data.status === "loading") return <LoadingRows rows={4} />;
  if (data.status === "error") return <ErrorState error={data.error} onRetry={data.reload} />;
  return (
    <div className="grid grid-cols-2 items-start gap-5">
      {(["IN", "US"] as const).map((m) => (
        <Card key={m}>
          <CardHeader>
            <CardTitle>{m === "IN" ? "India" : "United States"}</CardTitle>
          </CardHeader>
          <CardBody className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <p className="m-0 text-small font-semibold text-fg-muted">Brokerage</p>
              {data.data.brokerage
                .filter((b) => b.market === m)
                .map((b) => (
                  <div key={b.id} className="flex flex-col gap-1 rounded-tile border border-hairline px-4 py-3">
                    <span className="flex items-center gap-2 font-semibold">
                      {b.name}
                      {b.is_default && <Pill tone="accent" className="h-6 px-2 text-tiny">Default</Pill>}
                    </span>
                    {Object.entries(b.rules).map(([product, rule]) => (
                      <span key={product} className="text-small text-fg-muted">
                        {PRODUCT[product as keyof typeof PRODUCT] ?? product}: {ruleText(rule, m)}
                      </span>
                    ))}
                  </div>
                ))}
            </div>
            <div className="flex flex-col gap-1">
              <p className="m-0 text-small font-semibold text-fg-muted">Slippage</p>
              {data.data.slippage
                .filter((x) => x.market === m)
                .map((x) => (
                  <span key={x.id} className="text-[14px]">
                    {x.name}: each fill is {x.bps / 100}% worse than the candle's price
                  </span>
                ))}
            </div>
            <p className="m-0 text-small text-fg-muted">{TAXES[m]}</p>
            <p className="m-0 text-tiny text-fg-subtle">Pick a different brokerage when you set up a backtest or a paper account.</p>
          </CardBody>
        </Card>
      ))}
    </div>
  );
}
