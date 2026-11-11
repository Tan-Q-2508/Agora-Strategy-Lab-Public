/**
 * Revisions (docs/REVISIONS.md): every save of a strategy, newest first, with who made it (you,
 * Kairos, Metis or the AI helper), what changed in plain words, and the evidence behind it.
 * Nothing is ever overwritten: Restore saves an old revision again as the newest.
 */
import { History, RotateCcw, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { LoadingRows } from "../../components/states";
import { Button } from "../../components/ui/button";
import { Dialog } from "../../components/ui/dialog";
import { Pill } from "../../components/ui/pill";
import { postJson, toEnvelope, type SavedVersion } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import type { Definition } from "../../lib/strategy";
import { useApi } from "../../lib/useApi";

const AUTHOR_TONE: Record<string, "accent" | "profit" | "neutral" | "warning"> = {
  user: "neutral",
  ai_draft: "warning",
  kairos: "accent",
  metis: "profit",
};

export function VersionHistory({
  strategyId,
  current,
  open,
  onOpenChange,
  onLoad,
}: {
  strategyId: number;
  current: number | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onLoad: (v: SavedVersion<Definition>) => void;
}) {
  const list = useApi<{ versions: SavedVersion<Definition>[] }>(open ? `/strategies/${strategyId}/versions` : null);
  const versions = open && list.status === "ready" ? list.data.versions : null;
  const latest = versions?.[0]?.version ?? null;
  const [busy, setBusy] = useState<number | null>(null);

  async function restore(v: SavedVersion<Definition>) {
    setBusy(v.id);
    try {
      const r = await postJson<{ version: SavedVersion<Definition> }>(`/strategies/${strategyId}/versions/${v.id}/restore`);
      toast.success(`Version ${v.version} is back, saved as version ${r.version.version}. Nothing was deleted.`);
      onLoad(r.version);
      list.reload();
      onOpenChange(false);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Revisions"
      description="Every change is a new revision, whoever made it: you, Kairos or Metis. Nothing is overwritten, and backtests always point at the exact revision they ran."
    >
      {!versions ? (
        <LoadingRows rows={3} />
      ) : (
        <ol className="m-0 flex max-h-[60vh] list-none flex-col gap-2 overflow-y-auto p-0">
          {versions.map((v) => (
            <li key={v.id} className="flex flex-col gap-2 rounded-tile border border-hairline p-3" aria-label={`Version ${v.version}`}>
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <History className="size-4 shrink-0 text-fg-muted" aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="m-0 flex flex-wrap items-center gap-2 font-semibold">
                      Version {v.version}
                      <Pill tone={AUTHOR_TONE[v.created_by] ?? "neutral"} className="h-5 px-2 text-tiny font-medium">
                        {v.created_by === "ai_draft" && <Sparkles className="size-3" aria-hidden="true" />}
                        {v.author_label ?? v.created_by}
                      </Pill>
                      {v.version === latest && <span className="text-tiny font-normal text-fg-subtle">current</span>}
                      {v.version === current && <span className="text-tiny font-normal text-fg-subtle">(open now)</span>}
                    </p>
                    <p className="m-0 text-small text-fg-muted">
                      {formatDateTime(v.created_at)}
                      {v.note ? ` · ${v.note}` : ""}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button size="sm" variant="ghost" disabled={v.version === current} onClick={() => (onLoad(v), onOpenChange(false))}>
                    Open
                  </Button>
                  {v.version !== latest && (
                    <Button size="sm" variant="soft" disabled={busy !== null} onClick={() => void restore(v)}>
                      <RotateCcw aria-hidden="true" />
                      Restore
                    </Button>
                  )}
                </div>
              </div>
              {v.changes && v.changes.length > 0 && v.changes[0] !== "First version." && (
                <ul className="m-0 flex list-disc flex-col gap-0.5 pl-9 text-small">
                  {v.changes.slice(0, 8).map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                  {v.changes.length > 8 && <li className="text-fg-subtle">and {v.changes.length - 8} more changes</li>}
                </ul>
              )}
              {v.evidence?.verdict && <p className="m-0 pl-7 text-tiny text-fg-muted">Evidence: {v.evidence.verdict}</p>}
            </li>
          ))}
        </ol>
      )}
    </Dialog>
  );
}
