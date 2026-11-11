/** Settings → Kairos: the agent's switches, the desk's limits, and its studies. */
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { JobProgress } from "../../components/JobProgress";
import { KairosMark } from "../../components/kairos/KairosMark";
import { LearnerCard } from "../../components/kairos/LearnerCard";
import { MetisCard } from "../../components/metis/MetisCard";
import { ErrorState, LoadingRows } from "../../components/states";
import { Button } from "../../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { NumberInput } from "../../components/ui/input";
import { Segmented } from "../../components/ui/segmented";
import { postJson, putJson, toEnvelope, type MarketCode, type SettingsResponse } from "../../lib/api";
import type { Learned } from "../../lib/desk";
import { formatDate, MARKET_TZ } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { useJob, useJobId } from "../../lib/useJob";

const SWITCHES: [string, string][] = [
  ["autopilot", "Work on their own"],
  ["kairos.enabled", "Show Kairos"],
  ["kairos.think", "Think before answering"],
  ["kairos.follow", "Follow Kairos around the app"],
  ["news.enabled", "Business and world news"],
  ["research.enabled", "Research on the web"],
  ["kairos.keep_learning", "Keep learning while Agora is open"],
  ["kairos.auto_improve", "Let Kairos improve my strategies"],
  ["revisions.auto_undo", "Undo what stops holding up"],
  ["kairos.bigger_chart", "Trade with the bigger chart's trend"],
  ["kairos.smaller_chart", "A closer look at the smaller chart"],
  ["kairos.auto_exits", "Kairos chooses its own exits"],
  ["kairos.judge", "Kairos's trade judge"],
];
const NUMBERS: { key: string; label: string; unit: string; step: number; min: number; max: number }[] = [
  { key: "kairos.risk_pct", label: "Risk per trade", unit: "%", step: 0.1, min: 0.1, max: 5 },
  { key: "kairos.max_positions", label: "Most open trades", unit: "", step: 1, min: 1, max: 20 },
  { key: "kairos.trials", label: "Most Metis strategies on trial", unit: "", step: 1, min: 0, max: 6 },
  { key: "kairos.daily_loss_pct", label: "Daily loss pause", unit: "%", step: 0.5, min: 0.5, max: 20 },
  { key: "kairos.entry_score", label: "Entry score", unit: "/100", step: 5, min: 20, max: 80 },
  { key: "kairos.trail_atr", label: "Trailing stop", unit: "× ATR", step: 0.5, min: 0, max: 8 },
  { key: "kairos.partial_r", label: "Sell half at", unit: "× risk", step: 0.5, min: 0, max: 5 },
];

function Row({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-hairline py-3 first:border-t-0">
      <div className="min-w-0">
        <p className="m-0 font-semibold">{title}</p>
        {description && <p className="m-0 text-small text-fg-muted">{description}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Study({ market }: { market: MarketCode }) {
  const stats = useApi<Learned>(`/kairos/stats?market=${market}`);
  const [jobId, setJobId] = useJobId("kairos_train");
  const { job } = useJob(jobId, (j) => {
    setJobId(null);
    if (j.status === "done") toast.success(`Kairos re-studied ${market === "IN" ? "Indian" : "US"} stocks.`);
    stats.reload();
  });
  const t = stats.status === "ready" ? stats.data.trained : null;
  async function start() {
    try {
      const r = await postJson<{ job_id: string }>("/kairos/train", { market, timeframe: "1d" });
      setJobId(r.job_id);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }
  return (
    <div className="flex flex-col gap-2 border-t border-hairline py-3 first:border-t-0">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="m-0 font-semibold">{market === "IN" ? "Indian stocks" : "US stocks"} (daily)</p>
          <p className="m-0 text-small text-fg-muted">
            {t ? `Studied ${t.candles.toLocaleString()} candles on ${formatDate(t.at, MARKET_TZ[market])}.` : "Not studied yet: it happens the first time Kairos reads one of these charts."}
          </p>
        </div>
        <Button size="sm" variant="ghost" onClick={() => void start()} disabled={jobId !== null}>
          <RefreshCw aria-hidden="true" />
          Study again
        </Button>
      </div>
      {job && <JobProgress job={job} />}
    </div>
  );
}

export function KairosSettings() {
  const settings = useApi<SettingsResponse>("/settings");
  async function save(key: string, value: unknown) {
    try {
      await putJson("/settings", { [key]: value });
      settings.reload();
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }
  if (settings.status === "loading") return <LoadingRows rows={6} />;
  if (settings.status === "error") return <ErrorState error={settings.error} onRetry={settings.reload} />;
  const v = settings.data.values;
  const meta = settings.data.meta;
  return (
    <div className="grid grid-cols-2 items-start gap-5">
      <div className="flex flex-col gap-5">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KairosMark />
              Kairos
            </CardTitle>
          </CardHeader>
          <CardBody>
            {SWITCHES.map(([key, title]) => (
              <Row key={key} title={title} description={meta[key]?.description}>
                <Segmented
                  label={title}
                  value={v[key] === false ? "off" : "on"}
                  onChange={(x) => void save(key, x === "on")}
                  options={[
                    { value: "on", label: "On" },
                    { value: "off", label: "Off" },
                  ]}
                />
              </Row>
            ))}
            <p className="m-0 pt-2 text-tiny text-fg-subtle">Kairos is a research tool, not financial advice. It only ever uses paper money.</p>
          </CardBody>
        </Card>
        <MetisCard settings={settings.data} save={(k, x) => void save(k, x)} />
        <LearnerCard />
      </div>
      <div className="flex flex-col gap-5">
        <Card>
          <CardHeader>
            <CardTitle>Kairos desk</CardTitle>
          </CardHeader>
          <CardBody>
            {NUMBERS.map((n) => (
              <Row key={n.key} title={n.label} description={meta[n.key]?.description}>
                <div className="flex items-center gap-1.5">
                  <NumberInput
                    aria-label={n.label}
                    value={typeof v[n.key] === "number" ? (v[n.key] as number) : null}
                    min={n.min}
                    max={n.max}
                    step={n.step}
                    onChange={(x) => x !== null && x >= n.min && x <= n.max && void save(n.key, x)}
                    className="h-9 w-[88px]"
                  />
                  {n.unit && <span className="text-small text-fg-muted">{n.unit}</span>}
                </div>
              </Row>
            ))}
            <Row title="News guard" description={meta["kairos.news_guard"]?.description}>
              <Segmented
                label="News guard"
                value={(v["kairos.news_guard"] as string) ?? "protective"}
                onChange={(x) => void save("kairos.news_guard", x)}
                options={[
                  { value: "protective", label: "Protective" },
                  { value: "cautious", label: "Cautious" },
                  { value: "off", label: "Off" },
                ]}
              />
            </Row>
            <Row title="Short-term desks" description={meta["autopilot.intraday_desk"]?.description}>
              <Segmented
                label="Short-term desks"
                value={(v["autopilot.intraday_desk"] as string) ?? "all"}
                onChange={(x) => void save("autopilot.intraday_desk", x)}
                options={[
                  { value: "all", label: "All" },
                  { value: "1h", label: "Hourly" },
                  { value: "15m", label: "15 min" },
                  { value: "off", label: "Off" },
                ]}
              />
            </Row>
            <Row title="Trade check" description={meta["kairos.trade_check"]?.description}>
              <Segmented
                label="Trade check"
                value={(v["kairos.trade_check"] as string) ?? "balanced"}
                onChange={(x) => void save("kairos.trade_check", x)}
                options={[
                  { value: "balanced", label: "Balanced" },
                  { value: "strict", label: "Strict" },
                  { value: "learn", label: "Learn" },
                  { value: "off", label: "Off" },
                ]}
              />
            </Row>
            <p className="m-0 pt-2 text-tiny text-fg-subtle">New desks use these limits; a running desk keeps the limits it started with. The news guard applies at once.</p>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>What Kairos has studied</CardTitle>
          </CardHeader>
          <CardBody>
            <Study market="IN" />
            <Study market="US" />
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
