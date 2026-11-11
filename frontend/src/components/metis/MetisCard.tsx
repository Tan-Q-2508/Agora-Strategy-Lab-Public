import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router";
import type { SettingsResponse } from "../../lib/api";
import { Card, CardBody, CardHeader, CardTitle } from "../ui/card";
import { NumberInput } from "../ui/input";
import { Segmented } from "../ui/segmented";
import { MetisMark } from "./MetisMark";

/** Settings → Kairos: Metis's switches (docs/METIS.md §8). */
export function MetisCard({ settings, save }: { settings: SettingsResponse; save: (key: string, value: unknown) => void }) {
  const v = settings.values;
  const meta = settings.meta;
  const row = "flex items-center justify-between gap-4 border-t border-hairline py-3 first:border-t-0";
  const onOff = (key: string, label: string) => (
    <Segmented
      label={label}
      value={v[key] === false ? "off" : "on"}
      onChange={(x) => save(key, x === "on")}
      options={[
        { value: "on", label: "On" },
        { value: "off", label: "Off" },
      ]}
    />
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MetisMark />
          Metis, the AI researcher
        </CardTitle>
        <Link to="/metis" className="inline-flex items-center gap-1 text-small">
          Open Metis <ArrowUpRight className="size-3.5" aria-hidden="true" />
        </Link>
      </CardHeader>
      <CardBody>
        <div className={row}>
          <div className="min-w-0">
            <p className="m-0 font-semibold">Research on its own</p>
            <p className="m-0 text-small text-fg-muted">{meta["metis.enabled"]?.description}</p>
          </div>
          <div className="shrink-0">{onOff("metis.enabled", "Research on its own")}</div>
        </div>
        <div className={row}>
          <div className="min-w-0">
            <p className="m-0 font-semibold">Every</p>
            <p className="m-0 text-small text-fg-muted">{meta["metis.every_minutes"]?.description}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <NumberInput
              aria-label="Minutes between rounds"
              value={typeof v["metis.every_minutes"] === "number" ? (v["metis.every_minutes"] as number) : null}
              min={1}
              max={240}
              step={1}
              onChange={(x) => x !== null && x >= 1 && x <= 240 && Number.isInteger(x) && save("metis.every_minutes", x)}
              className="h-9 w-[88px]"
            />
            <span className="text-small text-fg-muted">min</span>
          </div>
        </div>
        <div className={row}>
          <div className="min-w-0">
            <p className="m-0 font-semibold">Save what holds up</p>
            <p className="m-0 text-small text-fg-muted">{meta["metis.apply"]?.description}</p>
          </div>
          <div className="shrink-0">{onOff("metis.apply", "Save what holds up")}</div>
        </div>
        <div className={row}>
          <div className="min-w-0">
            <p className="m-0 font-semibold">Its own ideas</p>
            <p className="m-0 text-small text-fg-muted">{meta["metis.own_ideas"]?.description}</p>
          </div>
          <div className="shrink-0">{onOff("metis.own_ideas", "Its own ideas")}</div>
        </div>
      </CardBody>
    </Card>
  );
}
