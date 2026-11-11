import { ScrollBox } from "../components/ui/scroll-box";
/**
 * Watchlists (SPEC §18, D-94, D-98): ready-made lists (indices, sectors, sizes, factor lists,
 * themes, ETFs), your own lists, and the lists Kairos and Metis made with their reasons; plus
 * where money is moving between sectors right now.
 */
import { motion } from "framer-motion";
import { Copy, ListPlus, ListChecks, Plus, Sparkles, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { KairosMark } from "../components/kairos/KairosMark";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Change } from "../components/ui/change";
import { Dialog } from "../components/ui/dialog";
import { Field, Input } from "../components/ui/input";
import { Pill } from "../components/ui/pill";
import { Segmented } from "../components/ui/segmented";
import { deleteJson, patchJson, postJson, toEnvelope, type MarketCode } from "../lib/api";
import { formatAgo } from "../lib/format";
import { useApi } from "../lib/useApi";
import { cn } from "../lib/utils";
import {
  CATEGORY_ORDER,
  CATEGORY_WORD,
  STATE_TONE,
  STATE_WORD,
  type SectorOverview,
  type SectorReading,
  type WatchlistDetail,
  type WatchlistSummary,
} from "../lib/world";

const MARKETS: { value: MarketCode; label: string }[] = [
  { value: "IN", label: "India" },
  { value: "US", label: "US" },
];

function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function SectorTile({ r }: { r: SectorReading }) {
  const m1 = r.returns["1m"];
  return (
    <li className="flex flex-col gap-1.5 rounded-control border border-hairline bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-small font-semibold">{r.name}</span>
        <Pill tone={STATE_TONE[r.state]} className="h-6 px-2 text-tiny">
          {STATE_WORD[r.state]}
        </Pill>
      </div>
      <div className="flex items-baseline justify-between gap-2">
        {m1 !== null ? <Change value={m1} text={pct(m1)} className="text-[15px]" /> : <span className="text-fg-subtle">—</span>}
        <span className="text-tiny text-fg-subtle">this month</span>
      </div>
      <div className="h-1.5 rounded-full bg-surface-2" aria-label={`${r.breadth.above50}% of its stocks above their 50-day average`} role="img">
        <div className={cn("h-1.5 rounded-full", r.breadth.above50 >= 50 ? "bg-profit" : "bg-loss")} style={{ width: `${r.breadth.above50}%` }} />
      </div>
      <span className="text-tiny text-fg-subtle">
        {Math.round(r.breadth.above50)}% above 50-day avg · {r.quadrant !== "unknown" ? r.quadrant : "new"}
      </span>
    </li>
  );
}

function Sectors({ market }: { market: MarketCode }) {
  const res = useApi<SectorOverview>(`/sectors?market=${market}`, 300_000);
  if (res.status === "loading") return <LoadingRows rows={2} />;
  if (res.status === "error") return <ErrorState error={res.error} onRetry={res.reload} />;
  const o = res.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-4 text-accent-strong" aria-hidden="true" />
          Where money is moving
        </CardTitle>
        <span className="text-tiny text-fg-subtle">{o.stocks} stocks with prices</span>
      </CardHeader>
      <CardBody className="flex flex-col gap-3">
        <p className="m-0 text-small text-fg-muted">{o.sentence}</p>
        {o.sectors.length > 0 && (
          <ScrollBox size="lg">
            <ul className="m-0 grid list-none grid-cols-2 gap-2 p-0 md:grid-cols-3 xl:grid-cols-4">
              {o.sectors.map((r) => (
                <SectorTile key={r.name} r={r} />
              ))}
            </ul>
          </ScrollBox>
        )}
        {o.industries.some((r) => r.state === "boom" || r.state === "strong") && (
          <p className="m-0 text-small text-fg-muted">
            Strong industries:{" "}
            {o.industries
              .filter((r) => r.state === "boom" || r.state === "strong")
              .slice(0, 5)
              .map((r) => `${r.name} (${pct(r.returns["1m"])})`)
              .join(", ")}
          </p>
        )}
      </CardBody>
    </Card>
  );
}

function NewList({ market, open, onOpenChange }: { market: MarketCode; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [name, setName] = useState("");
  const [symbols, setSymbols] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  async function save() {
    setBusy(true);
    try {
      const r = await postJson<{ watchlist: WatchlistDetail }>("/watchlists", {
        market,
        name,
        symbols: symbols.split(/[\s,;]+/).filter(Boolean),
      });
      toast.success(`Saved “${r.watchlist.name}”.`);
      onOpenChange(false);
      setName("");
      setSymbols("");
      void nav(`/watchlists/${r.watchlist.id}`);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="New watchlist"
      description={`A list of ${market === "IN" ? "Indian" : "US"} stocks you want to keep an eye on.`}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" disabled={busy || !name.trim()} onClick={() => void save()}>
            Save list
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label="Name">
          <Input aria-label="List name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. My banks" />
        </Field>
        <Field label="Stocks" hint="Tickers separated by commas, e.g. HDFCBANK, ICICIBANK, SBIN">
          <Input aria-label="Stocks" value={symbols} onChange={(e) => setSymbols(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}

function Groups({ lists, selected, market }: { lists: WatchlistSummary[]; selected: number | null; market: MarketCode }) {
  const [q, setQ] = useState("");
  const groups = useMemo(() => {
    const words = q.trim().toLowerCase();
    const shown = lists.filter((w) => w.market === market && (!words || w.name.toLowerCase().includes(words)));
    return CATEGORY_ORDER.map((c) => [c, shown.filter((w) => w.category === c)] as const).filter(([, ws]) => ws.length > 0);
  }, [lists, market, q]);
  return (
    <nav aria-label="Watchlists" className="flex flex-col gap-4">
      <Input aria-label="Find a list" placeholder="Find a list" value={q} onChange={(e) => setQ(e.target.value)} />
      <ScrollBox size="page" className="flex flex-col gap-4">
        {groups.map(([cat, ws]) => (
          <div key={cat} className="flex flex-col gap-1">
            <p className="m-0 px-2 text-tiny font-semibold tracking-wide text-fg-subtle uppercase">{CATEGORY_WORD[cat]}</p>
            <ul className="m-0 flex list-none flex-col p-0">
              {ws.map((w) => (
                <li key={w.id}>
                  <Link
                    to={`/watchlists/${w.id}`}
                    className={cn(
                      "flex items-center justify-between gap-2 rounded-control px-2 py-1.5 text-small no-underline hover:bg-surface-2",
                      selected === w.id ? "bg-accent-soft font-semibold text-accent-soft-fg" : "text-fg",
                    )}
                  >
                    <span className="flex min-w-0 items-center gap-1.5 truncate">
                      {(w.kind === "kairos" || w.kind === "metis") && <KairosMark className="size-3.5 shrink-0" />}
                      <span className="truncate">{w.name}</span>
                    </span>
                    <span className="shrink-0 text-tiny text-fg-subtle tabular-nums">{w.count}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </ScrollBox>
    </nav>
  );
}

function Detail({ id, onChanged }: { id: number; onChanged: () => void }) {
  const res = useApi<{ watchlist: WatchlistDetail }>(`/watchlists/${id}`);
  const [adding, setAdding] = useState("");
  const nav = useNavigate();
  if (res.status === "loading") return <LoadingRows rows={6} />;
  if (res.status === "error") return <ErrorState error={res.error} onRetry={res.reload} />;
  const w = res.data.watchlist;
  const money = w.market === "IN" ? "₹" : "$";

  async function act(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      toast.success(ok);
      res.reload();
      onChanged();
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }
  async function copy() {
    try {
      const r = await postJson<{ watchlist: WatchlistDetail }>(`/watchlists/${id}/copy`, {});
      toast.success(`Copied to “${r.watchlist.name}”.`);
      onChanged();
      void nav(`/watchlists/${r.watchlist.id}`);
    } catch (err) {
      toast.error(toEnvelope(err).message);
    }
  }
  return (
    <motion.div key={id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className="flex flex-col gap-4">
      <Card>
        <CardBody className="flex flex-col gap-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="m-0 text-heading font-semibold">{w.name}</h2>
              <p className="m-0 text-small text-fg-muted">{w.description}</p>
            </div>
            <div className="flex gap-2">
              {!w.editable && (
                <Button size="sm" onClick={() => void copy()}>
                  <Copy aria-hidden="true" /> Copy to my lists
                </Button>
              )}
              {w.kind !== "ready" && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    void act(async () => {
                      await deleteJson(`/watchlists/${id}`);
                      void nav("/watchlists");
                    }, "List deleted.")
                  }
                >
                  <Trash2 aria-hidden="true" /> Delete
                </Button>
              )}
            </div>
          </div>
          {w.reason && (w.kind === "kairos" || w.kind === "metis") && (
            <p className="m-0 flex gap-2 rounded-control bg-accent-soft/60 p-3 text-small">
              <KairosMark className="mt-0.5 size-4 shrink-0" />
              <span>
                <span className="font-semibold">{w.kind === "kairos" ? "Kairos" : "Metis"} made this list: </span>
                {w.reason}
              </span>
            </p>
          )}
          <p className="m-0 text-tiny text-fg-subtle">
            {w.count} stocks · {w.with_prices} with saved prices{w.live ? " · rebuilt daily from prices" : ""} · updated {formatAgo(w.updated_at)}
          </p>
          {w.editable && (
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                const add = adding.split(/[\s,;]+/).filter(Boolean);
                if (add.length) void act(() => patchJson(`/watchlists/${id}`, { add }), "Added.").then(() => setAdding(""));
              }}
            >
              <Input aria-label="Add stocks" placeholder="Add stocks, e.g. TCS, INFY" value={adding} onChange={(e) => setAdding(e.target.value)} className="flex-1" />
              <Button size="sm" type="submit">
                <Plus aria-hidden="true" /> Add
              </Button>
            </form>
          )}
        </CardBody>
      </Card>
      {w.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={ListChecks}
            title={w.live ? "Waiting for prices" : "No stocks yet"}
            body={w.live ? "This list is worked out from saved daily prices. Kairos downloads them on its own while Agora is open." : "Add stocks above."}
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <ScrollBox size="xl">
            <table className="w-full border-collapse text-small">
              <thead>
                <tr className="border-b border-hairline text-left text-tiny text-fg-subtle">
                  <th className="px-4 py-2 font-semibold">Stock</th>
                  <th className="px-2 py-2 font-semibold">Sector</th>
                  <th className="px-2 py-2 text-right font-semibold">Last</th>
                  <th className="px-2 py-2 text-right font-semibold">Day</th>
                  <th className="px-4 py-2 font-semibold">{w.kind === "ready" && !w.live ? "Size" : "Why"}</th>
                  {w.editable && <th className="w-10" />}
                </tr>
              </thead>
              <tbody>
                {w.items.map((i) => (
                  <tr key={i.instrument_id} className="border-b border-hairline last:border-0 hover:bg-surface-2/60">
                    <td className="px-4 py-2">
                      <Link to={`/charts?symbol=${encodeURIComponent(i.symbol)}&market=${w.market}`} className="font-semibold text-fg no-underline hover:underline">
                        {i.symbol}
                      </Link>
                      <span className="block max-w-56 truncate text-tiny text-fg-subtle">{i.name}</span>
                    </td>
                    <td className="px-2 py-2 text-fg-muted">{i.sector || i.industry || i.type}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{i.last !== null ? `${money}${i.last.toLocaleString(w.market === "IN" ? "en-IN" : "en-US", { maximumFractionDigits: 2 })}` : "—"}</td>
                    <td className="px-2 py-2 text-right">{i.change_pct !== null ? <Change value={i.change_pct} text={pct(i.change_pct)} /> : <span className="text-fg-subtle">—</span>}</td>
                    <td className="px-4 py-2 text-tiny text-fg-muted">{i.note || (i.size ? `${i.size} cap` : "")}</td>
                    {w.editable && (
                      <td className="pr-2">
                        <Button size="icon-sm" variant="ghost" aria-label={`Remove ${i.symbol}`} onClick={() => void act(() => patchJson(`/watchlists/${id}`, { remove: [i.symbol] }), `Removed ${i.symbol}.`)}>
                          <X aria-hidden="true" />
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollBox>
        </Card>
      )}
    </motion.div>
  );
}

export default function Watchlists() {
  const params = useParams();
  const selected = params.id ? Number(params.id) : null;
  const lists = useApi<{ watchlists: WatchlistSummary[] }>("/watchlists");
  const [marketPick, setMarket] = useState<MarketCode>("IN");
  const [creating, setCreating] = useState(false);
  const current = lists.status === "ready" && selected !== null ? lists.data.watchlists.find((w) => w.id === selected) : undefined;
  const market = current?.market ?? marketPick;
  return (
    <>
      <PageHeader
        title="Watchlists"
        subtitle="Ready-made lists by index, sector, size, factor and theme; your own lists; and the ones Kairos and Metis made."
        actions={
          <div className="flex items-center gap-3">
            <Segmented label="Market" value={market} options={MARKETS} onChange={(m) => setMarket(m)} />
            <Button variant="primary" onClick={() => setCreating(true)}>
              <ListPlus aria-hidden="true" /> New list
            </Button>
          </div>
        }
      />
      <Sectors market={market} />
      {lists.status === "loading" && <LoadingRows rows={6} />}
      {lists.status === "error" && <ErrorState error={lists.error} onRetry={lists.reload} />}
      {lists.status === "ready" && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px_1fr]">
          <Card className="h-fit p-3">
            <Groups lists={lists.data.watchlists} selected={selected} market={market} />
          </Card>
          {selected !== null ? (
            <Detail id={selected} onChanged={lists.reload} />
          ) : (
            <Card>
              <EmptyState icon={ListChecks} title="Pick a list" body="Open any list on the left to see its stocks, or make your own with “New list”." />
            </Card>
          )}
        </div>
      )}
      <NewList market={market} open={creating} onOpenChange={setCreating} />
    </>
  );
}
