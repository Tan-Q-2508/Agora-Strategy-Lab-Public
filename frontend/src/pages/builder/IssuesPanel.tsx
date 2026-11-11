import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import type { Issue } from "../../lib/strategy";
import { cn } from "../../lib/utils";

export function IssuesPanel({ issues, checking }: { issues: Issue[]; checking: boolean }) {
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");
  return (
    <Card>
      <CardHeader>
        <CardTitle>Checks</CardTitle>
        {checking && <span className="text-tiny text-fg-subtle">Checking…</span>}
      </CardHeader>
      <CardBody className="flex flex-col gap-2" aria-live="polite">
        {issues.length === 0 && (
          <p className="m-0 flex items-center gap-2 text-small text-profit">
            <CheckCircle2 className="size-4" aria-hidden="true" />
            Everything looks right. Ready to save and backtest.
          </p>
        )}
        {[...errors, ...warnings].map((i, k) => (
          <div key={k} className={cn("flex gap-2.5 rounded-tile p-2.5 text-small", i.severity === "error" ? "bg-warning-soft text-warning-soft-fg" : "bg-surface-2 text-fg-muted")}>
            {i.severity === "error" ? <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> : <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />}
            <div>
              <p className="m-0 font-semibold">{i.where}</p>
              <p className="m-0">
                {i.message} {i.hint}
              </p>
            </div>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}
