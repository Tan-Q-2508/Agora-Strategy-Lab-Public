import { Tabs } from "radix-ui";
import { useCallback } from "react";
import { useSearchParams } from "react-router";
import { EChart, type OptionBuilder } from "../components/charts/EChart";
import { PageHeader } from "../components/PageHeader";
import { ErrorState, LoadingRows } from "../components/states";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Segmented } from "../components/ui/segmented";
import type { SettingsResponse } from "../lib/api";
import { exampleEquity } from "../lib/demoData";
import { formatCompactMoney } from "../lib/format";
import { useTheme, type ThemeChoice } from "../lib/theme";
import { useApi } from "../lib/useApi";
import { AIHelperSettings } from "./settings/AIHelper";
import { CostsPanel } from "./settings/Costs";
import { DiagnosticsPanel } from "./settings/Diagnostics";
import { KairosSettings } from "./settings/Kairos";

const LABELS: Record<string, string> = {
  "ai.enabled": "AI helper",
  "ai.model": "AI model",
  "ai.base_url": "Ollama address",
  "ai.num_ctx": "AI reading size",
  "default_capital.IN": "Starting money (India)",
  "default_capital.US": "Starting money (US)",
  intraday_square_off_time: "Intraday close time",
  volume_cap_pct: "Largest order (% of volume)",
};

function display(key: string, value: unknown): string {
  if (typeof value === "boolean") return value ? "On" : "Off";
  if (key === "default_capital.IN" && typeof value === "number") return formatCompactMoney(value, "INR");
  if (key === "default_capital.US" && typeof value === "number") return formatCompactMoney(value, "USD");
  if (key === "volume_cap_pct") return `${String(value)}%`;
  if (key === "ai.num_ctx") return value === 0 ? "Automatic" : String(value);
  if (key === "intraday_square_off_time") return `${String(value)} IST`;
  return String(value);
}

function ThemePreview() {
  const build = useCallback<OptionBuilder>((t) => {
    const d = exampleEquity();
    return {
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: d.months, boundaryGap: false },
      yAxis: { type: "value", scale: true, axisLabel: { formatter: (v: number) => formatCompactMoney(v, "INR") } },
      series: [
        {
          name: "Strategy",
          type: "line",
          data: d.strategy,
          showSymbol: false,
          lineStyle: { width: 2.5, color: t.accent },
          areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: t.accent + "38" }, { offset: 1, color: t.accent + "00" }] } },
        },
        { name: "Nifty 50", type: "line", data: d.benchmark, showSymbol: false, lineStyle: { width: 1.5, type: "dashed", color: t.benchmark } },
      ],
    };
  }, []);
  return <EChart build={build} height={220} caption="Example: a strategy vs simply holding the Nifty 50, in the current theme." ariaLabel="Example equity chart" />;
}

function General() {
  const { choice, setChoice } = useTheme();
  const settings = useApi<SettingsResponse>("/settings");
  return (
    <div className="grid grid-cols-2 gap-5">
      <Card>
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
        </CardHeader>
        <CardBody className="flex flex-col gap-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="m-0 font-semibold">Theme</p>
              <p className="m-0 text-small text-fg-muted">Light or dark colors for the whole app.</p>
            </div>
            <Segmented<ThemeChoice>
              label="Theme"
              value={choice}
              onChange={setChoice}
              options={[
                { value: "light", label: "Light" },
                { value: "dark", label: "Dark" },
                { value: "system", label: "Automatic" },
              ]}
            />
          </div>
          <ThemePreview />
        </CardBody>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Defaults</CardTitle>
        </CardHeader>
        <CardBody>
          {settings.status === "loading" && <LoadingRows rows={6} />}
          {settings.status === "error" && <ErrorState error={settings.error} onRetry={settings.reload} />}
          {settings.status === "ready" && (
            <dl className="m-0 flex flex-col">
              {Object.keys(LABELS).map((key) => (
                <div key={key} className="flex items-start justify-between gap-4 border-t border-hairline py-3 first:border-t-0">
                  <div>
                    <dt className="font-semibold">{LABELS[key]}</dt>
                    <dd className="m-0 text-small text-fg-muted">{settings.data.meta[key]?.description}</dd>
                  </div>
                  <dd className="m-0 shrink-0 text-[14px] font-semibold">{display(key, settings.data.values[key])}</dd>
                </div>
              ))}
            </dl>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

const tabClass =
  "h-9 rounded-[7px] px-4 text-[14px] text-fg-muted data-[state=active]:bg-surface data-[state=active]:font-semibold data-[state=active]:text-fg data-[state=active]:shadow-e1";

export default function Settings() {
  const [search, setSearch] = useSearchParams();
  const tab = search.get("tab") ?? "general";
  return (
    <>
      <PageHeader title="Settings" subtitle="Sensible defaults are already set; change them only if you want to." />
      <Tabs.Root value={tab} onValueChange={(v) => setSearch(v === "general" ? {} : { tab: v }, { replace: true })} className="flex flex-col gap-5">
        <Tabs.List aria-label="Settings sections" className="inline-flex w-fit rounded-[9px] bg-surface-2 p-[3px]">
          <Tabs.Trigger value="general" className={tabClass}>General</Tabs.Trigger>
          <Tabs.Trigger value="costs" className={tabClass}>Costs</Tabs.Trigger>
          <Tabs.Trigger value="ai" className={tabClass}>AI helper</Tabs.Trigger>
          <Tabs.Trigger value="kairos" className={tabClass}>Kairos</Tabs.Trigger>
          <Tabs.Trigger value="diagnostics" className={tabClass}>Diagnostics</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="general"><General /></Tabs.Content>
        <Tabs.Content value="costs"><CostsPanel /></Tabs.Content>
        <Tabs.Content value="ai">
          <AIHelperSettings />
        </Tabs.Content>
        <Tabs.Content value="kairos"><KairosSettings /></Tabs.Content>
        <Tabs.Content value="diagnostics"><DiagnosticsPanel /></Tabs.Content>
      </Tabs.Root>
    </>
  );
}
