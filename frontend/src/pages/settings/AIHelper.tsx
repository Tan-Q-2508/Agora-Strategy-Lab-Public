import { Bot, Download, ExternalLink, RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { JobProgress } from "../../components/JobProgress";
import { ErrorState, LoadingRows } from "../../components/states";
import { Button } from "../../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { Field, Select } from "../../components/ui/input";
import { Dot, Pill } from "../../components/ui/pill";
import type { AIStatus } from "../../lib/ai";
import { postJson, putJson, toEnvelope } from "../../lib/api";
import { useApi } from "../../lib/useApi";
import { useJob, useJobId } from "../../lib/useJob";

const STATE_TEXT: Record<AIStatus["state"], { title: string; body: string; tone: "profit" | "warning" | "neutral" }> = {
  ready: { title: "Ready", body: "The AI helper can explain results and draft strategies.", tone: "profit" },
  model_missing: { title: "Model not downloaded", body: "Ollama is running. Download the AI model below (a one-time download).", tone: "warning" },
  not_running: { title: "Ollama isn't running", body: "Start Ollama from your Start menu (or Applications on a Mac), then click Check again.", tone: "warning" },
  not_installed: { title: "Not installed", body: "The AI helper is free and optional. It runs on your laptop's graphics card using Ollama.", tone: "neutral" },
  disabled: { title: "Turned off", body: "Everything else in Agora works without it. Turn it on to use the AI features.", tone: "neutral" },
  error: { title: "Couldn't check", body: "Agora couldn't check the AI helper. Click Check again.", tone: "warning" },
};

/** 0 = Automatic: the most the graphics card holds, up to 32,768 (D-141). */
const CTX_OPTIONS = [0, 8192, 16384, 24576, 32768, 49152, 65536];

/** Settings → AI helper: install steps, model download, and the few settings that matter. */
export function AIHelperSettings() {
  const status = useApi<AIStatus>("/ai/status?fresh=true");
  const [jobId, setJobId] = useJobId("ai_pull");
  const { job, cancel } = useJob(jobId, (j) => {
    if (j.status === "done") toast.success("AI model downloaded.");
    status.reload();
  });

  async function save(values: Record<string, unknown>) {
    try {
      await putJson("/settings", values);
      status.reload();
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }

  async function download(model: string) {
    try {
      const r = await postJson<{ job_id: string }>("/ai/pull", { model });
      setJobId(r.job_id);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }

  if (status.status === "loading") return <LoadingRows rows={4} />;
  if (status.status === "error") return <ErrorState error={status.error} onRetry={status.reload} />;
  const s = status.data;
  const text = STATE_TEXT[s.state];
  const installed = new Set(s.models.map((m) => m.name));
  const choices = [...new Set([...s.recommended.map((r) => r.name), ...s.models.map((m) => m.name), s.model])];
  const downloading = job !== null && (job.status === "running" || job.status === "queued");

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_380px] items-start gap-5">
      <Card>
        <CardHeader>
          <CardTitle>AI helper</CardTitle>
          <Button size="sm" variant="ghost" onClick={status.reload}>
            <RefreshCw aria-hidden="true" />
            Check again
          </Button>
        </CardHeader>
        <CardBody className="flex flex-col gap-5">
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent-strong">
              <Bot className="size-5" aria-hidden="true" />
            </span>
            <div className="flex flex-col gap-1">
              <p className="m-0 flex items-center gap-2 text-[16px] font-semibold">
                <Pill tone={text.tone === "neutral" ? "neutral" : text.tone} className="h-7 px-2.5 text-tiny">
                  <Dot tone={text.tone} />
                  {text.title}
                </Pill>
                {s.version && <span className="text-tiny font-normal text-fg-subtle">Ollama {s.version}</span>}
              </p>
              <p className="m-0 text-small text-fg-muted">{text.body}</p>
            </div>
          </div>

          {s.state === "not_installed" && (
            <ol className="m-0 flex flex-col gap-2 pl-5 text-[14px]">
              <li>
                Download Ollama (free) and install it like any other app.{" "}
                <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-semibold">
                  ollama.com/download <ExternalLink className="size-3.5" aria-hidden="true" />
                </a>
              </li>
              <li>Come back here and click Check again. Agora then offers to download the AI model.</li>
            </ol>
          )}

          {(s.state === "model_missing" || s.state === "ready") && (
            <div className="flex flex-col gap-3">
              {s.recommended.map((r) => (
                <div key={r.name} className="flex items-center justify-between gap-4 rounded-tile border border-hairline px-4 py-3">
                  <div className="flex flex-col">
                    <span className="font-semibold">
                      {r.label} {s.model === r.name && <span className="text-tiny font-normal text-accent-strong">· in use</span>}
                    </span>
                    <span className="text-small text-fg-muted">{r.note}</span>
                  </div>
                  {installed.has(r.name) ? (
                    <span className="text-small text-fg-subtle">Downloaded</span>
                  ) : (
                    <Button size="sm" onClick={() => void download(r.name)} disabled={downloading}>
                      <Download aria-hidden="true" />
                      Download
                    </Button>
                  )}
                </div>
              ))}
              {job && <JobProgress job={job} onCancel={downloading ? () => void cancel() : undefined} />}
            </div>
          )}
          {s.state === "ready" && s.runs_on && (
            <div
              className={
                s.runs_on.fix
                  ? "m-0 flex flex-col gap-1 rounded-tile bg-warning-soft px-4 py-3 text-small text-warning-soft-fg"
                  : "m-0 flex flex-col gap-1 rounded-tile border border-hairline px-4 py-3 text-small"
              }
            >
              <p className="m-0">
                <span className="font-semibold">Running on: </span>
                {s.runs_on.text}
              </p>
              {s.runs_on.fix && <p className="m-0">{s.runs_on.fix}</p>}
            </div>
          )}
          {s.warning && <p className="m-0 rounded-tile bg-warning-soft px-4 py-3 text-small text-warning-soft-fg">{s.warning}</p>}
          <p className="m-0 flex items-center gap-1.5 text-tiny text-fg-subtle">
            <Sparkles className="size-3.5" aria-hidden="true" />
            The AI helper only explains and drafts. It never places, sizes or cancels trades, and nothing leaves your laptop.
          </p>
        </CardBody>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Settings</CardTitle>
        </CardHeader>
        <CardBody className="flex flex-col gap-5">
          <Field label="AI helper" htmlFor="ai-enabled" hint="Turn the optional AI helper on or off.">
            <Select id="ai-enabled" value={s.enabled ? "on" : "off"} onChange={(e) => void save({ "ai.enabled": e.target.value === "on" })}>
              <option value="on">On</option>
              <option value="off">Off</option>
            </Select>
          </Field>
          <Field label="AI model" htmlFor="ai-model" hint="Which downloaded model answers. Qwen 3.5 (4B) suits a 6 GB graphics card.">
            <Select id="ai-model" value={s.model} onChange={(e) => void save({ "ai.model": e.target.value })}>
              {choices.map((m) => (
                <option key={m} value={m}>
                  {m}
                  {installed.has(m) ? "" : " (not downloaded)"}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Reading size"
            htmlFor="ai-ctx"
            hint="How much text the AI reads at once. Automatic picks the most your graphics card holds, so Metis reads all its evidence."
          >
            <Select
              id="ai-ctx"
              value={s.auto_ctx ? 0 : s.num_ctx}
              onChange={(e) => void save({ "ai.num_ctx": Number(e.target.value) })}
            >
              {CTX_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n === 0
                    ? `Automatic (now ${s.num_ctx.toLocaleString()}, recommended)`
                    : `${n.toLocaleString()}${n > 32768 ? " (may not fit a 6 GB card)" : ""}`}
                </option>
              ))}
            </Select>
          </Field>
        </CardBody>
      </Card>
    </div>
  );
}
