import { useId, useMemo, useState } from "react";
import type { Instrument, MarketCode } from "../lib/api";
import { useApi } from "../lib/useApi";
import { cn } from "../lib/utils";

const SHOWN = 60;

/** Best matches first: exact symbol, symbol starts with, name word starts with, anywhere. */
function searchInstruments(items: Instrument[], text: string): Instrument[] {
  const q = text.trim().toUpperCase();
  if (!q) return items.slice(0, SHOWN);
  const scored: [number, Instrument][] = [];
  for (const i of items) {
    const sym = i.symbol.toUpperCase();
    const name = i.name.toUpperCase();
    let rank = -1;
    if (sym === q) rank = 0;
    else if (sym.startsWith(q)) rank = 1;
    else if (name.startsWith(q) || name.includes(` ${q}`)) rank = 2;
    else if (sym.includes(q) || name.includes(q)) rank = 3;
    if (rank >= 0) scored.push([rank, i]);
  }
  scored.sort((a, b) => a[0] - b[0] || a[1].symbol.length - b[1].symbol.length || a[1].symbol.localeCompare(b[1].symbol));
  return scored.slice(0, SHOWN).map(([, i]) => i);
}

/**
 * A type-to-search stock picker. Agora knows every stock on NSE and the US exchanges
 * (about 8,500, D-102), far too many for a plain dropdown: type a symbol or a company name.
 */
export function InstrumentSelect({
  value,
  onChange,
  market,
  label = "Stock",
  className,
}: {
  value: number | null;
  onChange: (inst: Instrument) => void;
  market?: MarketCode;
  label?: string;
  className?: string;
}) {
  const s = useApi<{ instruments: Instrument[] }>(market ? `/instruments?market=${market}` : "/instruments");
  const items = useMemo(() => (s.status === "ready" ? s.data.instruments : []), [s]);
  const chosen = items.find((i) => i.id === value) ?? null;
  const [text, setText] = useState<string | null>(null); // null: not typing, show the choice
  const [active, setActive] = useState(0);
  const listId = useId();
  const open = text !== null;
  const hits = useMemo(() => (text !== null ? searchInstruments(items, text) : []), [items, text]);

  const pick = (inst: Instrument) => {
    setText(null);
    onChange(inst);
  };
  const shown = chosen ? `${chosen.symbol} · ${chosen.name}` : "";

  return (
    <div className={cn("relative text-small text-fg-muted", className)}>
      <input
        role="combobox"
        aria-label={label}
        aria-expanded={open && hits.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        disabled={s.status !== "ready"}
        value={open ? text : shown}
        placeholder={s.status === "ready" ? `Search ${items.length.toLocaleString()} stocks…` : "Loading stocks…"}
        onFocus={(e) => {
          setText("");
          setActive(0);
          e.currentTarget.select();
        }}
        onBlur={() => setTimeout(() => setText(null), 150)}
        onChange={(e) => {
          setText(e.target.value);
          setActive(0);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, hits.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === "Enter" && hits[active]) {
            e.preventDefault();
            pick(hits[active]);
            e.currentTarget.blur();
          } else if (e.key === "Escape") {
            setText(null);
            e.currentTarget.blur();
          }
        }}
        className="h-9 w-[300px] rounded-control border border-border bg-surface px-3 text-[14px] text-fg placeholder:text-fg-subtle"
      />
      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-label={`${label} matches`}
          className="absolute left-0 top-10 z-50 m-0 max-h-[320px] w-[360px] list-none overflow-y-auto rounded-control border border-border bg-surface p-1 shadow-e3"
        >
          {hits.length === 0 ? (
            <li className="px-3 py-2 text-fg-muted">No stock matches “{text}”.</li>
          ) : (
            hits.map((i, n) => (
              <li
                key={i.id}
                role="option"
                aria-selected={n === active}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(i);
                }}
                onMouseEnter={() => setActive(n)}
                className={cn(
                  "flex cursor-pointer items-baseline gap-2 rounded-[6px] px-3 py-1.5 text-[14px] text-fg",
                  n === active && "bg-surface-2",
                )}
              >
                <span className="font-medium">{i.symbol}</span>
                <span className="truncate text-small text-fg-muted">{i.name}</span>
                {!market && <span className="ml-auto text-tiny text-fg-subtle">{i.market === "IN" ? "India" : "US"}</span>}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
