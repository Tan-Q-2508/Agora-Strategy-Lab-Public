/**
 * News (docs/KAIROS.md §14): business and world news that moves markets, read live while
 * this screen is open. Three risk gauges (India, US, world), headlines read for topic and
 * severity, filters, and what Kairos's desk does about it (the news guard, D-69).
 */
import { AnimatePresence, motion } from "framer-motion";
import { ExternalLink, Newspaper, RefreshCw, Search, ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { KairosMark } from "../components/kairos/KairosMark";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Dot, Pill } from "../components/ui/pill";
import { Segmented } from "../components/ui/segmented";
import { Skeleton } from "../components/ui/skeleton";
import { postJson, toEnvelope } from "../lib/api";
import { formatAgo } from "../lib/format";
import type { GuardMode, LiveNews, NewsItem, NewsRisk } from "../lib/kairos";
import { guardWords, RISK_TONE, RISK_WORD } from "../lib/newsRisk";
import { RiskMeter } from "../components/news/RiskMeter";
import { useApi } from "../lib/useApi";
import { cn } from "../lib/utils";
import { ScrollBox } from "../components/ui/scroll-box";

type Region = "ALL" | "IN" | "US" | "WORLD";

const PLACE: Record<"IN" | "US" | "WORLD", string> = { IN: "India", US: "US", WORLD: "World" };

function Gauge({ risk, mode }: { risk: NewsRisk; mode: GuardMode }) {
  const lead = risk.drivers[0];
  return (
    <Card className="gap-3 p-5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-small text-fg-muted">News risk · {PLACE[risk.market]}</span>
        <Pill tone={RISK_TONE[risk.name]} className="h-7 px-2.5 text-tiny font-semibold">
          {RISK_WORD[risk.name]}
        </Pill>
      </div>
      <p className="m-0 flex items-baseline gap-1.5">
        <span className="text-title font-bold tabular-nums tracking-tight">{Math.round(risk.level)}</span>
        <span className="text-small text-fg-muted">/ 100</span>
      </p>
      <RiskMeter level={risk.level} name={risk.name} />
      <p className="m-0 min-h-10 text-small leading-5 text-fg-muted">
        {lead ? (
          <>
            Biggest story: <span className="text-fg">{lead.title}</span>
            {lead.sources > 1 && <span className="text-fg-subtle"> · {lead.sources} sources</span>}
          </>
        ) : (
          "No market-moving stories in the last day and a half."
        )}
      </p>
      <p className="m-0 flex items-start gap-1.5 border-t border-hairline pt-3 text-small">
        <KairosMark className="mt-0.5 size-4 shrink-0" />
        <span>{risk.market === "WORLD" ? "World news counts toward both markets' gauges." : guardWords(risk.level, mode)}</span>
      </p>
    </Card>
  );
}

function Severity({ n }: { n: number }) {
  return (
    <span className="flex items-center gap-0.5" aria-label={`Severity ${n} of 5`} title={`Severity ${n} of 5`}>
      {[1, 2, 3, 4, 5].map((k) => (
        <span key={k} aria-hidden="true" className={cn("h-3 w-1 rounded-full", k <= n ? (n >= 4 ? "bg-loss" : n >= 3 ? "bg-warning" : "bg-fg-subtle") : "bg-surface-2")} />
      ))}
    </span>
  );
}

function Impact({ value }: { value: number }) {
  if (Math.abs(value) < 0.15) return <span className="text-tiny text-fg-subtle">neutral</span>;
  const off = value < 0;
  return (
    <span className={cn("text-tiny font-semibold tabular-nums", off ? "text-loss" : "text-profit")}>
      {off ? "▼ risk-off" : "▲ risk-on"}
    </span>
  );
}

function Headline({ item }: { item: NewsItem }) {
  const sev = item.severity ?? 0;
  const sectors = Object.entries(item.sectors ?? {}).slice(0, 4);
  return (
    <motion.li
      layout="position"
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
      className="border-b border-hairline last:border-0"
    >
      <a href={item.link} target="_blank" rel="noopener noreferrer" className="group flex gap-3 px-1 py-3 no-underline">
        <div className="pt-1">
          <Severity n={sev} />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="text-[14px] font-medium leading-5 text-fg group-hover:underline">{item.title}</span>
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-tiny text-fg-subtle">
            {item.topic_labels?.[0] && <span className="rounded-full bg-surface-2 px-2 py-0.5 text-fg-muted">{item.topic_labels[0]}</span>}
            {item.scope && <span>{PLACE[item.scope]}</span>}
            <span>·</span>
            <span>{item.publisher || "News"}</span>
            <span>·</span>
            <span>{formatAgo(item.published_at)}</span>
            {sev >= 2 && <Impact value={item.impact ?? 0} />}
            {item.symbols.slice(0, 4).map((s) => (
              <span key={s} className="rounded-full border border-border px-1.5 font-semibold text-fg-muted">
                {s}
              </span>
            ))}
          </span>
          {sev >= 3 && sectors.length > 0 && (
            <span className="text-tiny text-fg-subtle">
              Usually {sectors.map(([name, eff], k) => (
                <span key={name}>
                  {k > 0 && ", "}
                  <span className={eff > 0 ? "text-profit" : "text-loss"}>{eff > 0 ? "▲" : "▼"} {name.toLowerCase()}</span>
                </span>
              ))}
            </span>
          )}
        </div>
        <ExternalLink className="mt-1 size-3.5 shrink-0 text-fg-subtle opacity-0 group-hover:opacity-100" aria-hidden="true" />
      </a>
    </motion.li>
  );
}

function GuardCard({ data }: { data: LiveNews }) {
  const mode = data.guard;
  const words = { protective: "Protective", cautious: "Cautious", off: "Off" }[mode];
  const drivers = [...data.risk.IN.drivers, ...data.risk.US.drivers, ...data.risk.WORLD.drivers]
    .filter((d, k, all) => all.findIndex((x) => x.title === d.title) === k)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 5);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {mode === "off" ? <ShieldAlert className="size-4 text-warning" aria-hidden="true" /> : <ShieldCheck className="size-4 text-profit" aria-hidden="true" />}
          Kairos's news guard
        </CardTitle>
        <Button size="sm" variant="ghost" asChild>
          <Link to="/settings?tab=kairos">{words}</Link>
        </Button>
      </CardHeader>
      <CardBody className="flex flex-col gap-3">
        <p className="m-0 text-small text-fg-muted">
          Kairos's paper desk reads this news before every trade. It never trades on a headline alone: the rules below only stop, shrink or close trades, and every action is written in the desk's diary.
        </p>
        <ScrollBox size="md">
          <ul className="m-0 flex list-none flex-col gap-2 p-0 text-small">
            {(["IN", "US"] as const).map((m) => (
              <li key={m} className="flex items-start gap-2">
                <Dot tone={data.risk[m].name === "severe" ? "loss" : data.risk[m].name === "elevated" ? "warning" : "profit"} />
                <span>
                  <span className="font-semibold">{PLACE[m]}:</span> {guardWords(data.risk[m].level, mode)}
                </span>
              </li>
            ))}
          </ul>
        </ScrollBox>
        <p className="m-0 text-tiny text-fg-subtle">Bad company news (fraud, raids, defaults, profit warnings) closes that stock's trade; good news nudges Kairos to buy.</p>
        {drivers.length > 0 && (
          <div className="flex flex-col gap-2 border-t border-hairline pt-3">
            <p className="m-0 text-small font-semibold">What is driving the risk</p>
            {drivers.map((d) => (
              <a key={d.title} href={d.link ?? undefined} target="_blank" rel="noopener noreferrer" className="flex gap-2 text-small no-underline">
                <Severity n={d.severity} />
                <span className="min-w-0 flex-1 text-fg hover:underline">
                  {d.title}
                  <span className="text-tiny text-fg-subtle"> · {d.topic_label}{d.sources > 1 ? ` · ${d.sources} sources` : ""}</span>
                </span>
              </a>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function query(region: Region, group: string, serious: boolean, q: string): string {
  const p = new URLSearchParams({ region, limit: "150" });
  if (group !== "All") p.set("group", group);
  if (serious) p.set("min_severity", "3");
  if (q.trim()) p.set("q", q.trim());
  return `/news/live?${p.toString()}`;
}

export default function News() {
  const [region, setRegion] = useState<Region>("ALL");
  const [group, setGroup] = useState("All");
  const [serious, setSerious] = useState(false);
  const [q, setQ] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const live = useApi<LiveNews>(query(region, group, serious, q), 30_000);
  const busy = live.status === "ready" && live.data.refreshing;
  const fast = useApi<LiveNews>(busy ? query(region, group, serious, q) : null, 5_000);
  const data = fast.status === "ready" && busy ? fast.data : live.status === "ready" ? live.data : null;

  async function refreshNow() {
    setRefreshing(true);
    try {
      const r = await postJson<{ feeds: number; new: number; errors: string[] }>("/news/refresh", { world: true });
      toast.success(r.new ? `${r.new} new headline${r.new === 1 ? "" : "s"}.` : "No new headlines yet.");
      live.reload();
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <>
      <PageHeader
        title="News"
        subtitle="Business and world news that moves markets, read live while Agora is open, with how risky it is right now."
        actions={
          <>
            <Pill tone="neutral" className="h-9">
              <Dot tone={busy ? "warning" : "profit"} live />
              {busy ? "Reading the feeds…" : data ? `Live · updated ${formatAgo(data.as_of)}` : "Connecting…"}
            </Pill>
            <Button onClick={() => void refreshNow()} disabled={refreshing}>
              <RefreshCw aria-hidden="true" className={cn(refreshing && "animate-spin")} />
              Refresh now
            </Button>
          </>
        }
      />
      {live.status === "error" && <ErrorState error={live.error} onRetry={live.reload} />}
      {live.status === "loading" && (
        <div className="grid grid-cols-3 gap-5">
          {[0, 1, 2].map((k) => (
            <Skeleton key={k} className="h-[220px] rounded-card" />
          ))}
        </div>
      )}
      {data && !data.enabled && (
        <EmptyState
          icon={Newspaper}
          title="Reading news is turned off"
          body="Turn on “Business news” in Settings → Kairos to read headlines here and let Kairos's desk protect itself from bad news."
          action={
            <Button variant="soft" asChild>
              <Link to="/settings?tab=kairos">Open settings</Link>
            </Button>
          }
        />
      )}
      {data && data.enabled && (
        <>
          <div className="grid grid-cols-3 gap-5">
            <Gauge risk={data.risk.IN} mode={data.guard} />
            <Gauge risk={data.risk.US} mode={data.guard} />
            <Gauge risk={data.risk.WORLD} mode={data.guard} />
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_400px] items-start gap-5">
            <Card className="min-w-0">
              <CardHeader className="flex-wrap gap-3">
                <Segmented
                  label="Region"
                  value={region}
                  onChange={setRegion}
                  options={[
                    { value: "ALL", label: "All" },
                    { value: "IN", label: "India" },
                    { value: "US", label: "US" },
                    { value: "WORLD", label: "World" },
                  ]}
                />
                <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Topic">
                  {["All", ...data.groups].map((g) => (
                    <button
                      key={g}
                      type="button"
                      onClick={() => setGroup(g)}
                      aria-pressed={group === g}
                      className={cn(
                        "h-8 rounded-full border px-3 text-small transition-colors duration-150",
                        group === g ? "border-transparent bg-accent-soft font-semibold text-accent-soft-fg" : "border-border text-fg-muted hover:text-fg",
                      )}
                    >
                      {g}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => setSerious(!serious)}
                    aria-pressed={serious}
                    className={cn(
                      "h-8 rounded-full border px-3 text-small transition-colors duration-150",
                      serious ? "border-transparent bg-warning-soft font-semibold text-warning-soft-fg" : "border-border text-fg-muted hover:text-fg",
                    )}
                  >
                    Market-moving only
                  </button>
                </div>
                <label className="relative ml-auto">
                  <span className="sr-only">Search headlines</span>
                  <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
                  <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search headlines" className="h-9 w-[220px] pl-9" />
                </label>
              </CardHeader>
              <CardBody className="max-h-[620px] overflow-y-auto">
                {data.items.length === 0 ? (
                  <EmptyState
                    icon={Newspaper}
                    title={busy ? "Reading the news feeds…" : "No headlines match"}
                    body={busy ? "The first read of every feed takes a few seconds." : "Try another topic or region, or clear the search."}
                    className="py-10"
                  />
                ) : (
                  <ul className="m-0 list-none p-0">
                    <AnimatePresence initial={false}>
                      {data.items.map((i) => (
                        <Headline key={i.id} item={i} />
                      ))}
                    </AnimatePresence>
                  </ul>
                )}
              </CardBody>
            </Card>
            <div className="flex flex-col gap-5">
              <GuardCard data={data} />
              <Card>
                <CardHeader>
                  <CardTitle>Sources</CardTitle>
                  <span className="text-small text-fg-muted">{data.sources.length}</span>
                </CardHeader>
                <CardBody>
                  <p className="m-0 text-small leading-6 text-fg-muted">{data.sources.join(" · ")}</p>
                  <p className="m-0 pt-2 text-tiny text-fg-subtle">Public feeds and GDELT, read while this screen or Kairos is in use. No account, no key. Headlines link to the original article.</p>
                </CardBody>
              </Card>
            </div>
          </div>
          {live.status === "ready" && <p className="m-0 text-tiny text-fg-subtle">Severity bars show how much such news has moved whole markets (5 = an invasion, a pandemic, a bank collapse). Kairos is a research tool, not financial advice.</p>}
        </>
      )}
      {live.status === "ready" && live.data.enabled && live.data.items.length === 0 && live.data.sources.length === 0 && <LoadingRows rows={3} />}
    </>
  );
}
