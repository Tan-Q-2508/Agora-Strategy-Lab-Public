import { Sparkles } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { useAIStatus } from "../../components/ai/useAIStatus";
import { LoadingRows } from "../../components/states";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Field, Select } from "../../components/ui/input";
import { postJson, toEnvelope, type ErrorEnvelope, type MarketCode } from "../../lib/api";
import type { Issue, VisualDefinition } from "../../lib/strategy";

export interface AIDraft {
  definition: VisualDefinition;
  explanation: string;
  unsupported: string[];
  issues: Issue[];
  ok: boolean;
}

const EXAMPLES = [
  "Buy when the price closes above its 50-day average and RSI is below 60; sell when it closes below the 20-day average.",
  "Buy stocks making a new 52-week high, with an 8% stop-loss, and sell after 20 days.",
  "Buy when RSI drops below 30 and sell when it goes back above 55.",
];

/** Step one of "Describe it to the AI helper": the idea in plain English → a draft. */
export function AIDraftStart({ markets, onDraft }: { markets: MarketCode[]; onDraft: (d: AIDraft) => void }) {
  const status = useAIStatus();
  const [idea, setIdea] = useState("");
  const [market, setMarket] = useState<MarketCode>(markets[0] ?? "IN");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ErrorEnvelope | null>(null);
  const [failed, setFailed] = useState<AIDraft | null>(null);

  async function go() {
    setBusy(true);
    setError(null);
    setFailed(null);
    try {
      const r = await postJson<AIDraft>("/ai/draft-strategy", { idea, market });
      if (r.ok) onDraft(r);
      else setFailed(r);
    } catch (err) {
      setError(toEnvelope(err));
    } finally {
      setBusy(false);
    }
  }

  const notReady = status.status === "ready" && status.data.state !== "ready";
  return (
    <Card className="mx-auto w-full max-w-[720px] gap-5 p-7">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent-strong">
          <Sparkles className="size-5" aria-hidden="true" />
        </span>
        <div className="flex flex-col gap-1">
          <h1 className="m-0 text-heading font-semibold">Describe your idea</h1>
          <p className="m-0 text-small text-fg-muted">
            Write it the way you'd explain it to a friend. The AI helper turns it into rules you can check and change before anything is saved.
          </p>
        </div>
      </div>
      {status.status === "loading" && <LoadingRows rows={2} />}
      {notReady && (
        <div className="flex items-center justify-between gap-3 rounded-tile bg-warning-soft px-4 py-3 text-small text-warning-soft-fg">
          <span>The AI helper isn't ready yet. It's optional; you can build the rules with blocks instead.</span>
          <span className="flex shrink-0 gap-2">
            <Button size="sm" variant="ghost" asChild>
              <Link to="/settings?tab=ai">Set it up</Link>
            </Button>
            <Button size="sm" asChild>
              <Link to="/strategies/new">Use blocks</Link>
            </Button>
          </span>
        </div>
      )}
      <Field label="Your idea" htmlFor="ai-idea" hint="One or two sentences: when to buy, when to sell, and any stop-loss.">
        <textarea
          id="ai-idea"
          value={idea}
          maxLength={2000}
          rows={4}
          onChange={(e) => setIdea(e.target.value)}
          className="rounded-control border border-border bg-surface px-3 py-2.5 text-[14px] text-fg placeholder:text-fg-subtle"
          placeholder="Buy when…"
        />
      </Field>
      <div className="flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <button key={ex} type="button" onClick={() => setIdea(ex)} className="rounded-full border border-border bg-surface px-3 py-1 text-left text-tiny text-fg-muted hover:border-fg-subtle/50 hover:text-fg">
            {ex.length > 64 ? `${ex.slice(0, 62)}…` : ex}
          </button>
        ))}
      </div>
      <div className="flex items-end justify-between gap-4">
        {markets.length > 1 ? (
          <Field label="Market" htmlFor="ai-market" className="w-[200px]">
            <Select id="ai-market" value={market} onChange={(e) => setMarket(e.target.value as MarketCode)}>
              {markets.map((m) => (
                <option key={m} value={m}>
                  {m === "IN" ? "India" : "US"}
                </option>
              ))}
            </Select>
          </Field>
        ) : (
          <span />
        )}
        <Button variant="primary" onClick={() => void go()} disabled={busy || notReady || idea.trim().length < 8}>
          <Sparkles aria-hidden="true" />
          {busy ? "Drafting… (up to a minute)" : "Draft the rules"}
        </Button>
      </div>
      {error && (
        <p role="alert" className="m-0 rounded-tile bg-warning-soft px-4 py-3 text-small text-warning-soft-fg">
          {error.message} {error.action}
        </p>
      )}
      {failed && (
        <div role="alert" className="flex flex-col gap-2 rounded-tile bg-warning-soft px-4 py-3 text-small text-warning-soft-fg">
          <p className="m-0">
            The AI helper couldn't turn that into valid rules{failed.issues[0] ? `: ${failed.issues[0].where}: ${failed.issues[0].message}` : "."} Try saying it more simply, or open the draft and fix it yourself.
          </p>
          <Button size="sm" className="w-fit" onClick={() => onDraft(failed)}>
            Open the draft anyway
          </Button>
        </div>
      )}
      <p className="m-0 text-tiny text-fg-subtle">AI-generated drafts can be wrong. You'll review every rule before saving.</p>
    </Card>
  );
}
