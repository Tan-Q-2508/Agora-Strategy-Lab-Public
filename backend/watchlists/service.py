"""Watchlists: yours, ready-made, and the ones Kairos and Metis make (SPEC §18, D-94).

- **Yours** (``custom``): make, rename, add and remove stocks, delete. Any ready-made list can
  be copied into one of yours.
- **Ready-made** (``ready``): indices, sectors, sizes, factor lists, themes and ETFs
  (``catalog.py``), kept up to date from the seed files; the price-based factor lists are
  rebuilt from saved daily candles at most once a day (``refresh_factors``).
- **Made by Kairos or Metis** (``kairos`` / ``metis``): an agent saves a list with the reason it
  made it and a note per stock ("leading sector, strongest setup"). Making a list with a name
  that already exists updates it instead of adding another. Each agent may make at most
  ``AGENT_NEW_PER_DAY`` new lists a day and keeps at most ``AGENT_MAX_LISTS``; the oldest is
  put away when there are more. They never touch your lists.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from typing import Any

import numpy as np
from sqlalchemy import func, select

from backend.core.types import Market, Timeframe
from backend.data import store
from backend.data.store import InstrumentRef
from backend.db.models import (
    Instrument,
    InstrumentProfile,
    Watchlist,
    WatchlistItem,
)
from backend.errors import AgoraError
from backend.logging_setup import get_logger
from backend.watchlists import factors, seed

log = get_logger("watchlists")
DAY_MS = 86_400_000
AGENT_NEW_PER_DAY = 3
AGENT_MAX_LISTS = 12
MAX_ITEMS = 500
BENCH = {"IN": "NIFTY50", "US": "SPY"}


def _err(code: str, message: str, action: str, status: int = 422) -> AgoraError:
    return AgoraError(code, message, action, status=status)


class WatchlistService:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._lock = threading.Lock()
        self._ready = False
        self._factors_at: dict[str, int] = {}

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """App start: load the ready-made lists (only does work after an update). Practice-data
        sessions (tests) load them on first use instead."""
        if self.ctx.data_mode != "real":
            return
        try:
            self.ensure()
        except Exception:  # lists are a bonus at start; the screens retry
            log.exception("Loading the ready-made watchlists failed")

    def ensure(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            with self.ctx.db.session() as s:
                if seed.needs_sync(s):
                    counts = seed.sync(s, self.ctx.clock.now_ms())
                    log.info("Watchlists loaded: %s", counts)
            self._ready = True

    # ------------------------------------------------------------ reading

    def lists(
        self, market: str | None = None, category: str | None = None, kind: str | None = None
    ) -> list[dict[str, Any]]:
        self.ensure()
        with self.ctx.db.session() as s:
            stmt = select(Watchlist).where(Watchlist.archived_at.is_(None))
            if market:
                stmt = stmt.where(Watchlist.market_code == market)
            if category:
                stmt = stmt.where(Watchlist.category == category)
            if kind:
                stmt = stmt.where(Watchlist.kind == kind)
            rows = s.scalars(stmt.order_by(Watchlist.id)).all()
            counts = dict(
                s.execute(
                    select(WatchlistItem.watchlist_id, func.count()).group_by(
                        WatchlistItem.watchlist_id
                    )
                ).all()
            )
            return [self._summary(w, int(counts.get(w.id, 0))) for w in rows]

    @staticmethod
    def _summary(w: Watchlist, count: int) -> dict[str, Any]:
        return {
            "id": w.id,
            "name": w.name,
            "market": w.market_code,
            "kind": w.kind,
            "category": w.category,
            "key": w.key,
            "description": w.description,
            "reason": w.reason,
            "count": count,
            "editable": w.kind == "custom",
            "live": "factor" in json.loads(w.rule or "{}"),
            "created_at": w.created_at,
            "updated_at": w.updated_at,
        }

    def _row(self, s: Any, wid: int) -> Watchlist:
        w: Watchlist | None = s.get(Watchlist, wid)
        if w is None or w.archived_at is not None:
            raise _err("NOT_FOUND", "That watchlist doesn't exist.", "Pick another list.", 404)
        return w

    def detail(self, wid: int) -> dict[str, Any]:
        self.ensure()
        with self.ctx.db.session() as s:
            w = self._row(s, wid)
            rows = s.execute(
                select(WatchlistItem, Instrument, InstrumentProfile)
                .join(Instrument, Instrument.id == WatchlistItem.instrument_id)
                .outerjoin(InstrumentProfile, InstrumentProfile.instrument_id == Instrument.id)
                .where(WatchlistItem.watchlist_id == wid)
                .order_by(WatchlistItem.rank, Instrument.symbol)
            ).all()
            out = self._summary(w, len(rows))
            out["rule"] = json.loads(w.rule or "{}")
            items = []
            for item, inst, prof in rows:
                items.append(
                    {
                        "instrument_id": inst.id,
                        "symbol": inst.symbol,
                        "name": inst.name,
                        "type": inst.instrument_type,
                        "sector": prof.sector if prof else "",
                        "industry": prof.industry if prof else "",
                        "size": prof.size if prof else "",
                        "tags": [t for t in (prof.tags if prof else "").split(";") if t],
                        "note": item.note,
                    }
                )
        quotes = self.quotes([i["instrument_id"] for i in items])
        for i in items:
            i.update(quotes.get(i["instrument_id"], {"last": None, "change_pct": None}))
        out["items"] = items
        out["with_prices"] = sum(1 for i in items if i["last"] is not None)
        return out

    def quotes(self, ids: list[int]) -> dict[int, dict[str, float | None]]:
        """Latest saved daily close and its change, for stocks that have prices."""
        if not ids:
            return {}
        from backend.db.models import Candle

        out: dict[int, dict[str, float | None]] = {}
        with self.ctx.db.session() as s:
            last = dict(
                s.execute(
                    select(Candle.instrument_id, func.max(Candle.ts))
                    .where(Candle.instrument_id.in_(ids), Candle.timeframe == "1d")
                    .group_by(Candle.instrument_id)
                ).all()
            )
            for iid, ts in last.items():
                pair = s.execute(
                    select(Candle.close)
                    .where(Candle.instrument_id == iid, Candle.timeframe == "1d", Candle.ts <= ts)
                    .order_by(Candle.ts.desc())
                    .limit(2)
                ).all()
                close = float(pair[0][0])
                prev = float(pair[1][0]) if len(pair) > 1 else None
                out[iid] = {
                    "last": close,
                    "change_pct": round((close / prev - 1) * 100, 2) if prev else None,
                }
        return out

    def instruments(self, wid: int) -> list[InstrumentRef]:
        self.ensure()
        with self.ctx.db.session() as s:
            self._row(s, wid)
            rows = s.scalars(
                select(Instrument)
                .join(WatchlistItem, WatchlistItem.instrument_id == Instrument.id)
                .where(WatchlistItem.watchlist_id == wid)
                .order_by(WatchlistItem.rank, Instrument.symbol)
            ).all()
            return [store.ref(r) for r in rows]

    def find(self, text: str, market: str | None = None) -> dict[str, Any] | None:
        """A list by its name or key, forgiving about case and small words ("nifty it",
        "the semiconductors list", "US large caps")."""
        want = _words(text)
        if not want:
            return None
        best: tuple[float, dict[str, Any]] | None = None
        for w in self.lists(market):
            have = _words(f"{w['name']} {w['key'] or ''} {w['category']}")
            if not have:
                continue
            hit = len(want & have) / len(want)
            if w["name"].lower() == text.strip().lower():
                hit = 2.0
            if hit > 0.6 and (
                best is None or hit > best[0] or (hit == best[0] and w["count"] < best[1]["count"])
            ):
                best = (hit, w)
        return best[1] if best else None

    def profile(self, iid: int) -> dict[str, Any] | None:
        with self.ctx.db.session() as s:
            p = s.get(InstrumentProfile, iid)
            if p is None:
                return None
            return {
                "sector": p.sector,
                "industry": p.industry,
                "size": p.size,
                "lists": [x for x in p.lists.split(";") if x],
                "tags": [x for x in p.tags.split(";") if x],
            }

    def lists_with(self, iid: int) -> list[dict[str, Any]]:
        """The lists a stock is in (for the chart panel)."""
        with self.ctx.db.session() as s:
            rows = s.scalars(
                select(Watchlist)
                .join(WatchlistItem, WatchlistItem.watchlist_id == Watchlist.id)
                .where(WatchlistItem.instrument_id == iid, Watchlist.archived_at.is_(None))
                .order_by(Watchlist.id)
            ).all()
            return [
                {"id": w.id, "name": w.name, "kind": w.kind, "category": w.category} for w in rows
            ]

    # ------------------------------------------------------------ yours

    def _ids_for(self, s: Any, market: str, symbols: Iterable[str]) -> list[int]:
        out: list[int] = []
        unknown: list[str] = []
        for raw in symbols:
            sym = raw.strip().upper().removesuffix(".NS")
            if not sym:
                continue
            inst = store.find_instrument(s, Market(market), sym)
            if inst is None:
                unknown.append(sym)
            else:
                out.append(inst.id)
        if unknown:
            raise _err(
                "UNKNOWN_SYMBOLS",
                f"Agora doesn't know {', '.join(unknown[:5])}"
                + (f" and {len(unknown) - 5} more" if len(unknown) > 5 else "")
                + ".",
                "Check the spelling, or add US tickers on the Data screen first.",
            )
        return out

    def create(
        self,
        market: str,
        name: str,
        symbols: list[str],
        description: str = "",
        *,
        kind: str = "custom",
        reason: str = "",
        notes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.ensure()
        name = name.strip()[:80]
        if not name:
            raise _err("NO_NAME", "A watchlist needs a name.", "Type a name and save again.")
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            ids = self._ids_for(s, market, symbols)[:MAX_ITEMS]
            clash = s.scalar(
                select(Watchlist).where(Watchlist.market_code == market, Watchlist.name == name)
            )
            if clash is not None and clash.archived_at is None:
                raise _err(
                    "NAME_TAKEN",
                    f"There's already a list called “{name}”.",
                    "Pick another name.",
                    409,
                )
            if clash is not None:  # an archived list with that name: reuse the row
                clash.archived_at = None
                w = clash
                w.kind, w.category = kind, "custom" if kind == "custom" else "ai"
                w.description, w.reason, w.updated_at = description, reason, now
            else:
                w = Watchlist(
                    market_code=market,
                    name=name,
                    kind=kind,
                    category="custom" if kind == "custom" else "ai",
                    description=description,
                    reason=reason,
                    created_at=now,
                    updated_at=now,
                )
                s.add(w)
                s.flush()
            by_id = {}
            if notes:
                for sym, note in notes.items():
                    inst = store.find_instrument(s, Market(market), sym.upper())
                    if inst is not None:
                        by_id[inst.id] = note[:300]
            seed.set_items(s, w.id, ids, now, by_id)
            wid = w.id
        return self.detail(wid)

    def _editable(self, s: Any, wid: int) -> Watchlist:
        w = self._row(s, wid)
        if w.kind != "custom":
            raise _err(
                "READ_ONLY",
                "This list is kept up to date by Agora, so it can't be edited.",
                "Use “Copy to my lists” and edit the copy.",
                409,
            )
        return w

    def update(
        self,
        wid: int,
        *,
        name: str | None = None,
        description: str | None = None,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> dict[str, Any]:
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            w = self._editable(s, wid)
            if name is not None and name.strip() and name.strip() != w.name:
                if s.scalar(
                    select(Watchlist.id).where(
                        Watchlist.market_code == w.market_code,
                        Watchlist.name == name.strip(),
                        Watchlist.id != wid,
                    )
                ):
                    raise _err("NAME_TAKEN", "Another list has that name.", "Pick another.", 409)
                w.name = name.strip()[:80]
            if description is not None:
                w.description = description[:500]
            current = [
                i.instrument_id
                for i in s.scalars(
                    select(WatchlistItem)
                    .where(WatchlistItem.watchlist_id == wid)
                    .order_by(WatchlistItem.rank)
                )
            ]
            ids = list(current)
            if add:
                ids += [i for i in self._ids_for(s, w.market_code, add) if i not in ids]
            if remove:
                drop = set(self._ids_for(s, w.market_code, remove))
                ids = [i for i in ids if i not in drop]
            if ids != current:
                seed.set_items(s, wid, ids[:MAX_ITEMS], now)
            w.updated_at = now
        return self.detail(wid)

    def delete(self, wid: int) -> None:
        with self.ctx.db.session() as s:
            w = self._row(s, wid)
            if w.kind == "ready":
                raise _err(
                    "READ_ONLY",
                    "Ready-made lists can't be deleted.",
                    "Hide it by not using it; it costs nothing.",
                    409,
                )
            w.archived_at = self.ctx.clock.now_ms()

    def copy(self, wid: int, name: str | None = None) -> dict[str, Any]:
        src = self.detail(wid)
        base = name or f"My {src['name']}"
        taken = {w["name"] for w in self.lists(src["market"])}
        final, n = base, 2
        while final in taken:
            final, n = f"{base} ({n})", n + 1
        return self.create(
            src["market"],
            final,
            [i["symbol"] for i in src["items"]],
            src["description"],
        )

    # ------------------------------------------------------------ made by Kairos or Metis

    def save_for_agent(
        self,
        agent: str,
        market: str,
        name: str,
        symbols: list[str],
        reason: str,
        notes: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """Kairos or Metis saves a list: updates its own list of that name, or makes a new
        one within the daily limit. Returns None when the limit stops it."""
        assert agent in ("kairos", "metis")
        self.ensure()
        label = "Kairos" if agent == "kairos" else "Metis"
        full = name if name.startswith(f"{label} · ") else f"{label} · {name}"
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            mine = s.scalar(
                select(Watchlist).where(
                    Watchlist.market_code == market,
                    Watchlist.name == full,
                    Watchlist.kind == agent,
                )
            )
            if mine is not None and mine.archived_at is None:
                ids = self._ids_for(s, market, symbols)[:MAX_ITEMS]
                by_id: dict[int, str] = {}
                for sym, note in (notes or {}).items():
                    inst = store.find_instrument(s, Market(market), sym.upper())
                    if inst is not None:
                        by_id[inst.id] = note[:300]
                seed.set_items(s, mine.id, ids, now, by_id)
                mine.reason, mine.updated_at = reason[:1000], now
                wid = mine.id
                made_today = None
            else:
                made_today = s.scalar(
                    select(func.count()).where(
                        Watchlist.kind == agent, Watchlist.created_at >= now - DAY_MS
                    )
                )
        if made_today is None:
            return self.detail(wid)
        if made_today >= AGENT_NEW_PER_DAY:
            log.info("%s's watchlist limit for today reached; skipped %s", label, full)
            return None
        out = self.create(
            market, full, symbols, reason[:300], kind=agent, reason=reason, notes=notes
        )
        self._trim(agent)
        return out

    def _trim(self, agent: str) -> None:
        with self.ctx.db.session() as s:
            rows = s.scalars(
                select(Watchlist)
                .where(Watchlist.kind == agent, Watchlist.archived_at.is_(None))
                .order_by(Watchlist.updated_at.desc())
            ).all()
            for w in rows[AGENT_MAX_LISTS:]:
                w.archived_at = self.ctx.clock.now_ms()

    def discovery(self, market: str, limit: int = 100) -> list[InstrumentRef]:
        """Stocks worth scanning beyond the index (D-94): Kairos's and Metis's lists and the
        price-factor lists, only those with saved daily prices, after the market's own index."""
        from backend.data import service as data_service

        self.ensure()
        with self.ctx.db.session() as s:
            base = [i for i in data_service.default_symbols(s, Market(market)) if not i.is_index]
            extra = s.scalars(
                select(Instrument)
                .join(WatchlistItem, WatchlistItem.instrument_id == Instrument.id)
                .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
                .where(
                    Watchlist.market_code == market,
                    Watchlist.archived_at.is_(None),
                    (Watchlist.kind.in_(("kairos", "metis"))) | (Watchlist.category == "factor"),
                    Instrument.instrument_type == "equity",
                )
                .order_by(Watchlist.updated_at.desc(), WatchlistItem.rank)
            ).all()
            from backend.db.models import Candle

            priced = set(
                s.scalars(
                    select(Candle.instrument_id)
                    .where(
                        Candle.timeframe == "1d",
                        Candle.instrument_id.in_([e.id for e in extra] or [-1]),
                    )
                    .distinct()
                )
            )
            out = list(base)
            seen = {i.id for i in out}
            for e in extra:
                if e.id in priced and e.id not in seen:
                    seen.add(e.id)
                    out.append(store.ref(e))
        return out[:limit]

    # ------------------------------------------------------------ factor lists

    def closes(self, ids: list[int], days: int = 420) -> dict[int, np.ndarray]:
        """Adjusted daily closes of the last ``days`` days for stocks that have them."""
        now = self.ctx.clock.now_ms()
        out: dict[int, np.ndarray] = {}
        with self.ctx.db.session() as s:
            refs = [store.get_instrument(s, i) for i in ids]
        for ref in refs:
            if ref is None:
                continue
            bars = self.ctx.cache.bars(
                ref, Timeframe.D1, now - days * DAY_MS, now + 1, adjusted_prices=True
            )
            if bars:
                out[ref.id] = np.array([b.close for b in bars], dtype=np.float64)
        return out

    def refresh_factors(self, market: str | None = None, *, force: bool = False) -> dict[str, int]:
        """Rebuild the price-based factor lists (at most once a day unless ``force``)."""
        self.ensure()
        now = self.ctx.clock.now_ms()
        done: dict[str, int] = {}
        with self.ctx.db.session() as s:
            rows = [
                (w.id, w.market_code, json.loads(w.rule))
                for w in s.scalars(
                    select(Watchlist).where(
                        Watchlist.kind == "ready", Watchlist.category == "factor"
                    )
                )
                if "factor" in json.loads(w.rule) and (market is None or w.market_code == market)
            ]
        cache: dict[tuple[str, str], dict[int, np.ndarray]] = {}
        for wid, mkt, rule in rows:
            key = f"{mkt}:{rule['factor']}"
            if not force and now - self._factors_at.get(key, 0) < DAY_MS:
                continue
            within = str(rule.get("within", ""))
            if (mkt, within) not in cache:
                with self.ctx.db.session() as s:
                    ids = seed.members(s, mkt, {"list": within})
                cache[(mkt, within)] = self.closes(ids)
            bench_ref = None
            with self.ctx.db.session() as s:
                bench_ref = store.find_instrument(s, Market(mkt), BENCH[mkt])
            bench = None
            if bench_ref is not None:
                bench = self.closes([bench_ref.id]).get(bench_ref.id)
            picks = factors.rank(
                str(rule["factor"]), cache[(mkt, within)], bench=bench, top=int(rule.get("top", 30))
            )
            with self.ctx.db.session() as s:
                seed.set_items(
                    s,
                    wid,
                    [p.instrument_id for p in picks],
                    now,
                    {p.instrument_id: p.note for p in picks},
                )
                w = s.get(Watchlist, wid)
                assert w is not None
                w.updated_at = now
            self._factors_at[key] = now
            done[key] = len(picks)
        return done


def _words(text: str) -> set[str]:
    import re

    drop = {"the", "list", "watchlist", "stocks", "my", "of", "a", "an", "nifty", "s&p", "index"}
    words = {w for w in re.findall(r"[a-z0-9&]+", text.lower()) if w not in drop}
    return words or {w for w in re.findall(r"[a-z0-9&]+", text.lower())}
