import { Code, FlaskConical, History, Radio, Save, Sparkles } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Pill } from "../components/ui/pill";
import { Skeleton } from "../components/ui/skeleton";
import {
  patchJson,
  postJson,
  toEnvelope,
  type MarketCode,
  type SavedVersion,
  type SettingsResponse,
} from "../lib/api";
import { blankCode, blankVisual, type Definition, type Issue } from "../lib/strategy";
import { useApi } from "../lib/useApi";
import { cn } from "../lib/utils";
import { AIDraftStart, type AIDraft } from "./builder/AIDraftStart";
import { IssuesPanel } from "./builder/IssuesPanel";
import { KairosRulesPanel } from "./builder/KairosRulesPanel";
import { LookaheadPanel } from "./builder/LookaheadPanel";
import { ParametersPanel } from "./builder/ParametersPanel";
import { PreviewPanel } from "./builder/PreviewPanel";
import { RankingRulesPanel } from "./builder/RankingRulesPanel";
import { RulesPanel } from "./builder/RulesPanel";
import { SettingsPanel } from "./builder/SettingsPanel";
import { VersionHistory } from "./builder/VersionHistory";

// Monaco is large; only the code editor loads it.
const CodePanel = lazy(() => import("./builder/CodePanel").then((m) => ({ default: m.CodePanel })));

interface Loaded {
  id: number | null;
  name: string;
  description: string;
  definition: Definition;
  version: number | null;
}

interface StrategyResponse {
  strategy: { id: number; name: string; description: string };
  version: SavedVersion<Definition> | null;
}

function useValidation(definition: Definition | null) {
  const [state, setState] = useState<{ key: string; issues: Issue[] } | null>(null);
  const key = useMemo(() => (definition ? JSON.stringify(definition) : ""), [definition]);
  useEffect(() => {
    if (!definition) return;
    let alive = true;
    const t = setTimeout(() => {
      postJson<{ issues: Issue[] }>("/strategies/validate", { definition })
        .then((r) => alive && setState({ key, issues: r.issues }))
        .catch(() => undefined);
    }, 350);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [key, definition]);
  return { issues: state?.issues ?? [], checking: state?.key !== key };
}

function Loading() {
  return <LoadingRows rows={5} />;
}

/** Route: load an existing strategy, or start a blank one, then hand over to the editor. */
export default function StrategyBuilder() {
  const { id } = useParams();
  const [search] = useSearchParams();
  const settings = useApi<SettingsResponse>(id ? null : "/settings");
  const existing = useApi<StrategyResponse>(id ? `/strategies/${id}` : null);
  if (id) {
    if (existing.status === "error") return <ErrorState error={existing.error} onRetry={existing.reload} />;
    if (existing.status !== "ready" || !existing.data.version) return <Loading />;
    const r = existing.data;
    const v = r.version as SavedVersion<Definition>;
    return (
      <Editor
        key={`${r.strategy.id}-${v.version}`}
        initial={{ id: r.strategy.id, name: r.strategy.name, description: r.strategy.description, definition: v.definition, version: v.version }}
      />
    );
  }
  if (settings.status !== "ready") return <Loading />;
  const markets = (settings.data.values.markets as MarketCode[] | undefined) ?? ["IN"];
  const market = markets[0] ?? "IN";
  if (search.get("kind") === "ai") return <NewFromIdea markets={markets} />;
  const kind = search.get("kind") === "code" ? "code" : "visual";
  return (
    <Editor
      key={`new-${kind}`}
      initial={{
        id: null,
        name: kind === "code" ? "My code strategy" : "My strategy",
        description: "",
        definition: kind === "code" ? blankCode(market) : blankVisual(market),
        version: null,
      }}
    />
  );
}

function NewFromIdea({ markets }: { markets: MarketCode[] }) {
  const [draft, setDraft] = useState<AIDraft | null>(null);
  if (!draft) return <AIDraftStart markets={markets} onDraft={setDraft} />;
  return <Editor key="new-ai" initial={{ id: null, name: "My AI-drafted strategy", description: "", definition: draft.definition, version: null }} ai={draft} />;
}

function snapshot(l: Loaded): string {
  return JSON.stringify([l.name, l.description, l.definition]);
}

function Editor({ initial, ai }: { initial: Loaded; ai?: AIDraft }) {
  const navigate = useNavigate();
  const [draft, setDraft] = useState<Loaded>(initial);
  const [saved, setSaved] = useState(initial.id === null ? "" : snapshot(initial));
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState(false);

  const { issues, checking } = useValidation(draft.definition);
  const errors = issues.filter((i) => i.severity === "error");
  const dirty = snapshot(draft) !== saved;
  const valid = !checking && errors.length === 0;

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // Ctrl/Cmd+S saves, Ctrl/Cmd+Enter backtests (also while typing in the code editor).
  const keys = useRef({ save: () => {}, backtest: () => {} });
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key.toLowerCase() === "s") {
        e.preventDefault();
        keys.current.save();
      } else if (e.key === "Enter") {
        e.preventDefault();
        keys.current.backtest();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function save(): Promise<number | null> {
    if (errors.length) {
      toast.warning("Fix the highlighted problems first.", { description: errors[0] ? `${errors[0].where}: ${errors[0].message}` : undefined });
      return null;
    }
    setBusy(true);
    try {
      if (draft.id === null) {
        const r = await postJson<{ strategy: { id: number }; version: SavedVersion<Definition> }>("/strategies", {
          name: draft.name,
          description: draft.description,
          definition: draft.definition,
          ...(ai ? { created_by: "ai_draft" } : {}),
        });
        setSaved(snapshot(draft));
        toast.success("Strategy saved.");
        navigate(`/strategies/${r.strategy.id}`, { replace: true });
        return r.strategy.id;
      }
      const sid = draft.id;
      const before = saved ? (JSON.parse(saved) as unknown[]) : null;
      if (!before || before[0] !== draft.name || before[1] !== draft.description) {
        await patchJson(`/strategies/${sid}`, { name: draft.name, description: draft.description });
      }
      const r = await postJson<{ version: SavedVersion<Definition> }>(`/strategies/${sid}/versions`, { definition: draft.definition });
      const next = { ...draft, version: r.version.version };
      setDraft(next);
      setSaved(snapshot(next));
      toast.success(`Saved as version ${r.version.version}.`);
      return sid;
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function backtest() {
    const sid = dirty || draft.id === null ? await save() : draft.id;
    if (sid !== null) navigate(`/backtests/new?strategy=${sid}`);
  }

  async function paperTrade() {
    const sid = dirty || draft.id === null ? await save() : draft.id;
    if (sid !== null) navigate(`/paper?start=${sid}`);
  }

  async function openAsCode() {
    if (draft.id === null) return;
    if (dirty && (await save()) === null) return;
    try {
      const r = await postJson<{ strategy: { id: number } }>(`/strategies/${draft.id}/to-code`);
      toast.success("A code copy was created. The block version is unchanged.");
      navigate(`/strategies/${r.strategy.id}`);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }

  useEffect(() => {
    keys.current = {
      save: () => {
        if (!busy && (dirty || draft.id === null)) void save();
      },
      backtest: () => {
        if (!busy && valid) void backtest();
      },
    };
  });

  const d = draft.definition;
  const setDefinition = (definition: Definition) => setDraft({ ...draft, definition });

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <label htmlFor="strategy-name" className="sr-only">
            Strategy name
          </label>
          <input
            id="strategy-name"
            value={draft.name}
            maxLength={120}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            className="-ml-2 w-full max-w-[640px] rounded-control border border-transparent bg-transparent px-2 text-title font-bold tracking-tight hover:border-border focus:border-border"
          />
          <div className="flex items-center gap-2 text-small text-fg-muted">
            <Pill className="h-6 px-2 text-tiny">{d.kind === "code" ? "Code" : d.kind === "kairos" ? "Kairos" : d.kind === "ranking" ? "Ranking" : "Blocks"}</Pill>
            {draft.version !== null && <Pill className="h-6 px-2 text-tiny">Version {draft.version}</Pill>}
            <span className={cn(dirty ? "text-warning" : "text-fg-subtle")}>{dirty ? "Unsaved changes" : draft.id ? "All changes saved" : "Not saved yet"}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2.5">
          {draft.id !== null && (
            <Button variant="ghost" onClick={() => setHistory(true)}>
              <History aria-hidden="true" />
              Revisions
            </Button>
          )}
          {d.kind === "visual" && draft.id !== null && (
            <Button variant="ghost" onClick={openAsCode}>
              <Code aria-hidden="true" />
              Open as code
            </Button>
          )}
          {draft.id !== null && (
            <Button variant="ghost" onClick={() => void paperTrade()} disabled={busy || !valid}>
              <Radio aria-hidden="true" />
              Paper trade
            </Button>
          )}
          <Button onClick={() => void save()} disabled={busy || (!dirty && draft.id !== null)}>
            <Save aria-hidden="true" />
            Save
          </Button>
          <Button variant="primary" onClick={() => void backtest()} disabled={busy || !valid}>
            <FlaskConical aria-hidden="true" />
            Backtest this
          </Button>
        </div>
      </div>
      {ai && draft.id === null && (
        <div className="flex items-start gap-3 rounded-card border border-accent/30 bg-accent-soft/40 p-5">
          <Sparkles className="mt-0.5 size-5 shrink-0 text-accent-strong" aria-hidden="true" />
          <div className="flex flex-col gap-1.5">
            <p className="m-0 font-semibold">Drafted by the AI helper. Check every rule, then save.</p>
            {ai.explanation && <p className="m-0 text-[14px]">{ai.explanation}</p>}
            {ai.unsupported.length > 0 && <p className="m-0 text-small text-fg-muted">Agora can't do these parts of your idea, so they were left out: {ai.unsupported.join("; ")}.</p>}
            <p className="m-0 text-tiny text-fg-subtle">AI-generated. Nothing is saved until you click Save.</p>
          </div>
        </div>
      )}
      <div className="grid grid-cols-[minmax(0,1fr)_440px] items-start gap-5">
        <div className="flex min-w-0 flex-col gap-5">
          {d.kind === "visual" ? (
            <RulesPanel d={d} onChange={setDefinition} issues={issues} />
          ) : d.kind === "kairos" ? (
            <KairosRulesPanel d={d} onChange={setDefinition} issues={issues} />
          ) : d.kind === "ranking" ? (
            <RankingRulesPanel d={d} onChange={setDefinition} issues={issues} />
          ) : (d as { kind: string }).kind === "combined" ? (
            <p className="m-0 rounded-card bg-surface p-5 text-small text-fg-muted">This strategy is several strategies acting as one. To change how they combine, make a new one in Combine strategies.</p>
          ) : (
            <Suspense fallback={<Skeleton className="h-[660px] w-full rounded-card" />}>
              <CodePanel code={d.code} onChange={(code) => setDefinition({ ...d, code })} issues={issues} />
            </Suspense>
          )}
        </div>
        <div className="flex flex-col gap-5">
          <PreviewPanel d={d} valid={valid} />
          <IssuesPanel issues={issues} checking={checking} />
          {draft.id !== null && (
            <LookaheadPanel
              strategyId={draft.id}
              version={draft.version}
              ensureSaved={async () => {
                if (!dirty) return true;
                return (await save()) !== null;
              }}
            />
          )}
          <SettingsPanel d={d} onChange={setDefinition} issues={issues} />
          {d.kind !== "ranking" && <ParametersPanel d={d} onChange={setDefinition} issues={issues} />}
        </div>
      </div>
      {draft.id !== null && (
        <VersionHistory
          strategyId={draft.id}
          current={draft.version}
          open={history}
          onOpenChange={setHistory}
          onLoad={(v) => {
            setDraft({ ...draft, definition: v.definition });
            toast.info(`Version ${v.version} opened. Save to make it the newest version.`);
          }}
        />
      )}
    </>
  );
}
