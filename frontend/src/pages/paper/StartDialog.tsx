import { Play } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { Button } from "../../components/ui/button";
import { Dialog } from "../../components/ui/dialog";
import { Field, Input, NumberInput, Select } from "../../components/ui/input";
import {
  postJson,
  toEnvelope,
  type PaperAccount,
  type SettingsResponse,
  type StrategySummary,
} from "../../lib/api";
import { formatMoney, MARKET_CURRENCY, TIMEFRAME_LABEL } from "../../lib/format";
import { TRADE_CHECK_HINT, TRADE_CHECK_OPTIONS, type TradeCheckMode } from "../../lib/tradeCheck";
import { useApi } from "../../lib/useApi";

const NEW = "new";

/** Pick a strategy and a paper account, then start paper trading. */
export function StartDialog({
  open,
  onOpenChange,
  replay,
  initialStrategy,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  replay: boolean;
  initialStrategy?: number;
}) {
  const navigate = useNavigate();
  const strategies = useApi<{ strategies: StrategySummary[] }>(open ? "/strategies" : null);
  const accounts = useApi<{ accounts: PaperAccount[] }>(open ? "/paper/accounts" : null);
  const settings = useApi<SettingsResponse>(open ? "/settings" : null);
  const [picked, setPicked] = useState<number | null>(initialStrategy ?? null);
  const [accountChoice, setAccountChoice] = useState<string>(NEW);
  const [capital, setCapital] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [check, setCheck] = useState<TradeCheckMode>("off");

  const list = useMemo(
    () => (strategies.status === "ready" ? strategies.data.strategies.filter((s) => !s.archived && s.version_id !== null && (s.kind !== "kairos" || s.id === initialStrategy)) : []),
    // Kairos's desks run themselves (D-208): they aren't offered for a session of your own
    [strategies, initialStrategy],
  );
  const strategyId = picked ?? list[0]?.id ?? null;
  const strategy = list.find((s) => s.id === strategyId);
  const market = strategy?.market ?? "IN";
  const fitting = accounts.status === "ready" ? accounts.data.accounts.filter((a) => a.market === market) : [];
  const account = fitting.find((a) => String(a.id) === accountChoice);
  const defaultCapital = settings.status === "ready" ? Number(settings.data.values[`default_capital.${market}`] ?? 0) : 0;
  const cur = MARKET_CURRENCY[market];

  async function start() {
    if (!strategy || strategy.version_id === null) return;
    setBusy(true);
    try {
      const body = account
        ? { strategy_version_id: strategy.version_id, account_id: account.id, trade_check: check }
        : { strategy_version_id: strategy.version_id, account: { market, name, starting_capital: capital ?? defaultCapital }, trade_check: check };
      const r = await postJson<{ session_id: number }>("/paper/sessions", body);
      toast.success(replay ? "Practice replay started." : "Paper trading started.");
      onOpenChange(false);
      navigate(`/paper/${r.session_id}`);
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
      title="Start paper trading"
      description={
        replay
          ? "Practice data is on, so this replays the last months of practice prices quickly instead of waiting for live prices."
          : "Runs your strategy on live prices with fake money while Agora is open. Nothing runs when Agora is closed."
      }
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void start()} disabled={busy || !strategy}>
            <Play aria-hidden="true" />
            Start paper trading
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        {strategies.status === "ready" && list.length === 0 ? (
          <p className="m-0 text-body text-fg-muted">Save a strategy first. Then you can paper trade it here.</p>
        ) : (
          <Field label="Strategy" htmlFor="paper-strategy" hint={strategy ? `${strategy.market === "IN" ? "India" : "US"} · ${strategy.timeframe ? TIMEFRAME_LABEL[strategy.timeframe] : ""} · version ${strategy.version}` : undefined}>
            <Select id="paper-strategy" value={strategyId ?? ""} onChange={(e) => setPicked(Number(e.target.value))}>
              {list.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="Kairos's trade check" htmlFor="paper-check" hint={TRADE_CHECK_HINT[check]}>
          <Select id="paper-check" value={check} onChange={(e) => setCheck(e.target.value as TradeCheckMode)}>
            {TRADE_CHECK_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Paper account" htmlFor="paper-account" hint="The pretend money this session uses. Each account keeps its own cash and trades.">
          <Select id="paper-account" value={account ? accountChoice : NEW} onChange={(e) => setAccountChoice(e.target.value)}>
            <option value={NEW}>New paper account</option>
            {fitting.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} · {formatMoney(a.starting_capital, cur, 0)}
              </option>
            ))}
          </Select>
        </Field>
        {!account && (
          <div className="grid grid-cols-2 gap-4">
            <Field label="Account name" htmlFor="paper-name" hint="Optional.">
              <Input id="paper-name" value={name} maxLength={80} placeholder="Paper account" onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Starting money" htmlFor="paper-capital" hint={`Fake ${cur === "INR" ? "rupees" : "dollars"}.`}>
              <NumberInput id="paper-capital" value={capital ?? (defaultCapital || null)} min={1} onChange={setCapital} />
            </Field>
          </div>
        )}
      </div>
    </Dialog>
  );
}
