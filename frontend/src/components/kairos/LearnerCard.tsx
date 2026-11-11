import { Brain, RefreshCw } from "lucide-react";
import { postJson } from "../../lib/api";
import { formatAgo } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { useJob, useJobId } from "../../lib/useJob";
import { JobProgress } from "../JobProgress";
import { LoadingRows } from "../states";
import { Button } from "../ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../ui/card";
import { Dot } from "../ui/pill";

interface LearnerItem {
  at: number;
  kind: string;
  text: string;
}

interface LearnerStatus {
  on: boolean;
  thread: boolean;
  running: boolean;
  last_round_at: number | null;
  next_round_at: number | null;
  activity: LearnerItem[];
  history: { at: number; headline: string; items: LearnerItem[] }[];
  strategies: { strategy_id: number; name: string; trades: number; win_rate: number }[];
}

/** What Kairos studies on its own while Agora is open (KAIROS §18). */
export function LearnerCard() {
  const s = useApi<LearnerStatus>("/kairos/learner", 20_000);
  const [jobId, setJobId] = useJobId("kairos_learn");
  const { job } = useJob(jobId, () => {
    setJobId(null);
    s.reload();
  });
  const learnNow = () => postJson<{ job_id: string }>("/kairos/learner/round").then((r) => setJobId(r.job_id));
  const items = s.status === "ready" ? [...s.data.activity, ...s.data.history.flatMap((h) => h.items)] : [];
  const seen = new Set<string>();
  const unique = items.filter((i) => (seen.has(i.text) ? false : (seen.add(i.text), true))).slice(0, 8);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Brain className="size-4 text-accent" aria-hidden="true" />
          Kairos keeps learning
        </CardTitle>
        <Button size="sm" variant="ghost" onClick={() => void learnNow()} disabled={jobId !== null}>
          <RefreshCw aria-hidden="true" />
          Learn now
        </Button>
      </CardHeader>
      <CardBody className="flex flex-col gap-3">
        {s.status === "loading" && <LoadingRows rows={3} />}
        {s.status === "ready" && (
          <>
            <p className="m-0 flex items-center gap-2 text-small text-fg-muted">
              <Dot tone={s.data.on ? (s.data.running ? "warning" : "profit") : "neutral"} live={s.data.running} />
              {!s.data.on
                ? "Switched off: Kairos only learns when you ask."
                : s.data.running
                  ? "Studying right now…"
                  : s.data.last_round_at
                    ? `Last studied ${formatAgo(s.data.last_round_at)}; it studies every ten minutes or so while Agora is open.`
                    : "It studies every ten minutes or so while Agora is open, starting a minute or two after Agora opens."}
            </p>
            {job && <JobProgress job={job} />}
            {unique.length > 0 ? (
              <ul className="m-0 flex max-h-[220px] list-none flex-col gap-1.5 overflow-y-auto p-0">
                {unique.map((i) => (
                  <li key={`${i.at}-${i.text}`} className="text-small leading-5">
                    <span className="text-fg">{i.text}</span> <span className="text-tiny text-fg-subtle">· {formatAgo(i.at)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="m-0 text-small text-fg-muted">Nothing new yet. Run a backtest or a paper session and Kairos will review its trades, test improvements and check its own price predictions against what happened.</p>
            )}
            {s.data.strategies.length > 0 && (
              <p className="m-0 text-tiny text-fg-subtle">
                Trade experience: {s.data.strategies.slice(0, 4).map((x) => `${x.name} (${x.trades} trades, ${Math.round(x.win_rate * 100)}% won)`).join(" · ")}
              </p>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
