import { Archive, ArchiveRestore, Blocks, Code, Copy, FlaskConical, LayoutGrid, MoreHorizontal, Pencil, Plus, Sparkles } from "lucide-react";
import { ScrollBox } from "../components/ui/scroll-box";
import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { toast } from "sonner";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Change } from "../components/ui/change";
import { Dialog } from "../components/ui/dialog";
import { Field, Input } from "../components/ui/input";
import { Menu } from "../components/ui/menu";
import { Pill } from "../components/ui/pill";
import { Segmented } from "../components/ui/segmented";
import { Sparkline } from "../components/ui/sparkline";
import {
  patchJson,
  postJson,
  toEnvelope,
  type MarketCode,
  type SettingsResponse,
  type StrategySummary,
  type TemplateInfo,
} from "../lib/api";
import { formatAgo, formatPercent, TIMEFRAME_LABEL } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ownerOf, type Owner } from "../lib/owner";
import { Tabs } from "../components/ui/tabs";

const AUTHOR = { user: "You", ai_draft: "AI helper", kairos: "Kairos", metis: "Metis" } as const;

const OWNERS: { value: Owner; label: string }[] = [
  { value: "you", label: "Yours" },
  { value: "metis", label: "Metis" },
  { value: "kairos", label: "Kairos" },
];

function useDefaultMarket(): MarketCode {
  const s = useApi<SettingsResponse>("/settings");
  const markets = s.status === "ready" ? (s.data.values.markets as MarketCode[] | undefined) : undefined;
  return markets?.[0] ?? "IN";
}

function StrategyCard({ s, onChanged }: { s: StrategySummary; onChanged: () => void }) {
  const navigate = useNavigate();
  const last = s.last_backtest;

  async function act(fn: () => Promise<unknown>, done: string) {
    try {
      await fn();
      toast.success(done);
      onChanged();
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }

  return (
    <motion.div layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
      <Card className="h-full gap-3 p-5 transition-shadow hover:shadow-e2">
        <div className="flex items-start justify-between gap-3">
          <Link to={`/strategies/${s.id}`} className="min-w-0 text-fg no-underline">
            <p className="m-0 truncate text-[16px] font-semibold">{s.name}</p>
            <p className="m-0 line-clamp-2 min-h-[36px] text-small text-fg-muted">{s.description || "No description yet."}</p>
          </Link>
          <Menu
            trigger={
              <Button size="icon-sm" variant="ghost" aria-label={`More actions for ${s.name}`}>
                <MoreHorizontal aria-hidden="true" />
              </Button>
            }
            items={[
              { label: "Open", icon: <Pencil />, onSelect: () => navigate(`/strategies/${s.id}`) },
              { label: "Backtest", icon: <FlaskConical />, onSelect: () => navigate(`/backtests/new?strategy=${s.id}`) },
              { label: "Duplicate", icon: <Copy />, onSelect: () => act(() => postJson(`/strategies/${s.id}/duplicate`), "Strategy duplicated.") },
              s.archived
                ? { label: "Restore", icon: <ArchiveRestore />, onSelect: () => act(() => patchJson(`/strategies/${s.id}`, { archived: false }), "Strategy restored.") }
                : { label: "Archive", icon: <Archive />, danger: true, onSelect: () => act(() => patchJson(`/strategies/${s.id}`, { archived: true }), "Strategy archived. Its backtests are kept.") },
            ]}
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Pill className="h-6 px-2 text-tiny">{s.market === "IN" ? "India" : "US"}</Pill>
          <Pill className="h-6 px-2 text-tiny">{s.kind === "code" ? "Code" : s.kind === "kairos" ? "Kairos" : s.kind === "ranking" ? "Ranking" : s.kind === "combined" ? "Combined" : "Blocks"}</Pill>
          {s.timeframe && <Pill className="h-6 px-2 text-tiny">{TIMEFRAME_LABEL[s.timeframe]}</Pill>}
          <Pill className="h-6 px-2 text-tiny" title={s.version_at ? `Current revision since ${formatAgo(s.version_at)}` : undefined}>
            v{s.version}
            {s.version_author && s.version_author !== "user" ? ` · ${AUTHOR[s.version_author]}` : ""}
          </Pill>
        </div>
        {last ? (
          <Link to={`/backtests/${last.run_id}`} className="flex items-end justify-between gap-3 rounded-tile bg-surface-2/60 p-3 text-fg no-underline">
            <div className="flex flex-col">
              <span className="text-tiny text-fg-subtle">Last backtest · {formatAgo(last.created_at)}</span>
              {last.total_return !== null && <Change value={last.total_return} text={formatPercent(last.total_return)} className="text-[16px]" />}
            </div>
            <Sparkline points={last.points} className="w-28" label={`Equity curve of the last backtest of ${s.name}`} />
          </Link>
        ) : (
          <Button size="sm" variant="soft" asChild>
            <Link to={`/backtests/new?strategy=${s.id}`}>
              <FlaskConical aria-hidden="true" />
              Run its first backtest
            </Link>
          </Button>
        )}
      </Card>
    </motion.div>
  );
}

function TemplateDialog({ t, onClose }: { t: TemplateInfo | null; onClose: () => void }) {
  const navigate = useNavigate();
  const defaultMarket = useDefaultMarket();
  const [market, setMarket] = useState<MarketCode | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const chosen = market ?? defaultMarket;

  async function create() {
    if (!t) return;
    setBusy(true);
    try {
      const res = await postJson<{ strategy: { id: number } }>("/strategies", {
        name: name.trim() || t.name,
        market: chosen,
        template_key: t.key,
      });
      toast.success("Strategy created from the template.");
      navigate(`/strategies/${res.strategy.id}`);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={t !== null}
      onOpenChange={(o) => !o && onClose()}
      title={t ? `Use “${t.name}”` : ""}
      description={t?.summary}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={busy} onClick={create}>
            Create strategy
          </Button>
        </>
      }
    >
      {t && (
        <div className="flex flex-col gap-5">
          <p className="m-0 text-small text-fg-muted">{t.description}</p>
          <p className="m-0 rounded-tile bg-surface-2 p-3 text-small">
            <b>The idea:</b> {t.idea}
          </p>
          <Field label="Market" hint="You can change the stocks after creating it.">
            <Segmented
              label="Market"
              value={chosen}
              onChange={setMarket}
              options={[
                { value: "IN", label: "India (Nifty 50)" },
                { value: "US", label: "US" },
              ]}
            />
          </Field>
          <Field label="Name" htmlFor="tpl-name">
            <Input id="tpl-name" value={name} placeholder={t.name} onChange={(e) => setName(e.target.value)} maxLength={120} />
          </Field>
        </div>
      )}
    </Dialog>
  );
}

export default function Strategies() {
  const navigate = useNavigate();
  const [archived, setArchived] = useState(false);
  const list = useApi<{ strategies: StrategySummary[] }>(`/strategies?archived=${archived}`);
  const tpls = useApi<{ templates: TemplateInfo[] }>("/templates");
  const [tpl, setTpl] = useState<TemplateInfo | null>(null);
  const [owner, setOwner] = useState<Owner>("you");
  const empty = list.status === "ready" && list.data.strategies.length === 0;
  const { hash } = useLocation();
  useEffect(() => {
    if (hash === "#templates" && tpls.status === "ready") document.getElementById("templates")?.scrollIntoView({ behavior: "smooth" });
  }, [hash, tpls.status]);

  return (
    <>
      <PageHeader
        title="Strategies"
        subtitle="Your sets of rules for when to buy and sell."
        actions={
          <>
            <Segmented
              label="Show"
              value={archived ? "archived" : "active"}
              onChange={(v) => setArchived(v === "archived")}
              options={[
                { value: "active", label: "Active" },
                { value: "archived", label: "Archived" },
              ]}
            />
            <Menu
              trigger={
                <Button variant="primary">
                  <Plus aria-hidden="true" />
                  New strategy
                </Button>
              }
              items={[
                { label: "Build with blocks", icon: <Blocks />, onSelect: () => navigate("/strategies/new?kind=visual") },
                { label: "Write code (advanced)", icon: <Code />, onSelect: () => navigate("/strategies/new?kind=code") },
                { label: "Combine strategies", icon: <Blocks />, onSelect: () => navigate("/strategies/combine") },
                { label: "Describe it to the AI helper", icon: <Sparkles />, onSelect: () => navigate("/strategies/new?kind=ai") },
              ]}
            />
          </>
        }
      />
      {list.status === "loading" && <LoadingRows rows={3} />}
      {list.status === "error" && <ErrorState error={list.error} onRetry={list.reload} />}
      {list.status === "ready" && !empty && (
        <Card className="overflow-hidden p-0">
          <Tabs
            label="Whose strategies"
            value={owner}
            onValueChange={(v) => setOwner(v as Owner)}
            tabs={OWNERS.map((o) => {
              const mine = list.data.strategies.filter((s) => ownerOf(s.name, s.kind) === o.value);
              return {
                value: o.value,
                label: (
                  <>
                    {o.label} <span className="text-small font-normal text-fg-subtle">{mine.length}</span>
                  </>
                ),
                content: mine.length ? (
                  <ScrollBox size="page" label={o.label} className="grid grid-cols-3 gap-5 p-5">
                    {mine.map((s) => (
                      <StrategyCard key={s.id} s={s} onChanged={list.reload} />
                    ))}
                  </ScrollBox>
                ) : (
                  <p className="m-0 py-10 text-center text-small text-fg-muted">Nothing here.</p>
                ),
              };
            })}
          />
        </Card>
      )}
      {empty && (
        <Card className="justify-center py-4">
          <EmptyState
            icon={LayoutGrid}
            title={archived ? "Nothing archived" : "No strategies yet"}
            body={archived ? "Archived strategies show up here. Their backtests are always kept." : "Start from one of the ready-made templates below, or build your own with blocks."}
          />
        </Card>
      )}
      {!archived && (
        <section id="templates" className="flex scroll-mt-6 flex-col gap-4" aria-labelledby="templates-title">
          <div className="flex items-end justify-between">
            <div>
              <h2 id="templates-title" className="m-0 text-heading font-semibold">
                Start from a template
              </h2>
              <p className="m-0 text-small text-fg-muted">Classic ideas, ready to backtest. You can change every rule afterwards.</p>
            </div>
          </div>
          {tpls.status === "ready" ? (
            <div className="grid grid-cols-4 gap-4">
              {tpls.data.templates.map((t) => (
                <Card key={t.key} className="gap-2 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="m-0 font-semibold">{t.name}</p>
                    <Pill tone={t.kind === "ranking" ? "accent" : "neutral"} className="h-6 px-2 text-tiny">
                      {t.kind === "ranking" ? "Monthly ranking" : TIMEFRAME_LABEL[t.timeframe]}
                    </Pill>
                  </div>
                  <p className="m-0 flex-1 text-small text-fg-muted">{t.summary}</p>
                  <Button size="sm" variant="soft" onClick={() => setTpl(t)}>
                    Use this
                  </Button>
                </Card>
              ))}
            </div>
          ) : (
            <LoadingRows rows={2} />
          )}
        </section>
      )}
      <TemplateDialog t={tpl} onClose={() => setTpl(null)} />
    </>
  );
}
