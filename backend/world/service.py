"""The world desk: what is happening, what it means for each market, sector and stock, what
moved and why, and what Kairos learned from it (SPEC §18, D-95, D-96).

While Agora is open (``start``; real data only, or ``AGORA_WORLD=1``) a thread wakes every few
minutes and:

1. **notices events**: reads the saved headlines of the last three days (the news service keeps
   them fresh from the RSS feeds and GDELT), recognises world-map scenarios and keeps one
   ``world_events`` row per ongoing event, with its strength, direction and headlines;
2. **investigates moves**: when the whole market or a sector made an unusual move on its latest
   candle, it scores the news around it (and, on the laptop, searches GDELT, the open news
   index of the world's news sites, for that window), checks the confirming assets and the
   other market, and saves the most likely cause (``move_investigations``);
3. **learns**: once the days have passed, it measures how each live event's markets, sectors and
   exposure groups really moved (1, 5 and 20 trading days) and folds that into the learned
   effects; once a day it re-measures all past events (``history.py``) on the saved prices.

Everything is code; the AI helper only explains the results when the user asks Kairos. Nothing
here places an order (D-56); nothing runs when Agora is closed (D-06).
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import case, delete, func, select

from backend.core.clock import ms_to_dt
from backend.core.heavy import background_turn
from backend.core.types import MARKET_TZ, Market, Timeframe
from backend.data import store
from backend.db.models import (
    Instrument,
    InstrumentProfile,
    MoveInvestigation,
    WorldEffect,
    WorldEvent,
)
from backend.logging_setup import get_logger
from backend.watchlists import seed
from backend.world import engine
from backend.world import investigate as inv
from backend.world.history import EVENTS
from backend.world.scenarios import BY_KEY, SCENARIOS

CACHE_S = 60.0
PROFILE_CACHE_S = 600.0
log = get_logger("world")
HOUR = 3_600_000
DAY_MS = 86_400_000
TICK_S = 300.0
EVENT_GAP_MS = 72 * HOUR  # headlines this close in time belong to the same event
NEWS_HOURS = 72
MIN_STRENGTH = 3.0
MIN_COVER = 0.6  # share of stocks that must have the latest day's price before it counts (D-202)
BENCH = {"IN": "NIFTY50", "US": "SPY"}
BENCH_LABEL = {"IN": "the Nifty 50", "US": "the S&P 500"}
# Confirming assets (symbol in its market, how a rise reads: +1 the asset itself, −1 inverted)
CLUES: dict[str, tuple[str, str, int]] = {
    "oil": ("US", "USO", 1),
    "gold": ("US", "GLD", 1),
    "usd": ("US", "UUP", 1),
    "vix": ("US", "VIX", 1),
    "yields": ("US", "TLT", -1),  # bond prices fall when yields rise
    "rupee": ("IN", "USDINR", -1),  # dollars per rupee: a rise in USD/INR is a weaker rupee
}


class WorldService:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.last_detect = 0
        self.last_investigate = 0
        self.last_learn = 0
        self.last_train_key = ""
        # short caches for the screens (D-113): both markets' views, Kairos's picks and the
        # autopilot read these many times a minute, and the tables change only when learning
        self._learned: tuple[float, dict[tuple[str, str, str, int], engine.Learned]] | None = None
        self._profiles: dict[str, tuple[float, list[tuple[int, str, str, str, str]]]] = {}

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if self.ctx.data_mode != "real" and not os.environ.get("AGORA_WORLD"):
            return
        self._thread = threading.Thread(target=self._loop, name="world", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(TICK_S):
            try:
                with background_turn("the world desk"):
                    self.tick()
            except Exception:  # never take the app down
                log.exception("World desk round failed")

    def tick(self) -> dict[str, Any]:
        """One round: notice events; investigate moves every 30 minutes; learn once a day."""
        now = self.ctx.clock.now_ms()
        out: dict[str, Any] = {}
        news = self.ctx.services.get("news")
        if news is not None and news.enabled():
            news.ensure_fresh(news.world_feeds())
        out["events"] = len(self.detect())
        if now - self.last_investigate >= 30 * 60_000:
            self.last_investigate = now
            out["moves"] = sum(len(self.investigate(m)) for m in ("IN", "US"))
        if now - self.last_learn >= DAY_MS:
            self.last_learn = now
            out["learned"] = self.learn_live()
            out["trained"] = self.train_history()
        return out

    # ------------------------------------------------------------ 1. notice events

    def _headlines(self, hours: int = NEWS_HOURS, since: int | None = None) -> list[dict[str, Any]]:
        news = self.ctx.services.get("news")
        if news is None:
            return []
        items: list[dict[str, Any]] = news.latest(
            None, hours=hours, limit=3000, world=None, min_severity=1, since=since
        )
        return items

    def detect(self) -> list[engine.ActiveEvent]:
        """Recognise world events in the last three days of headlines and keep them saved."""
        now = self.ctx.clock.now_ms()
        grouped: dict[str, list[tuple[dict[str, Any], engine.Hit]]] = defaultdict(list)
        for h in self._headlines():
            for hit in engine.match(
                h["title"],
                h.get("summary") or "",
                h.get("topics") or [],
                int(h["severity"]),
                bool(h.get("calming")),
            ):
                grouped[hit.scenario].append((h, hit))
        events: list[engine.ActiveEvent] = []
        with self.ctx.db.session() as s:
            for key, pairs in grouped.items():
                strength = 0.0
                signed = 0.0
                publishers: set[str] = set()
                shown: list[dict[str, Any]] = []
                for h, hit in sorted(pairs, key=lambda x: -int(x[0]["published_at"])):
                    age_h = max(0.0, (now - int(h["published_at"])) / HOUR)
                    fade = 0.5 ** (age_h / 24.0)
                    pub = str(h.get("publisher") or h.get("source") or "")
                    extra = 1.0 if pub not in publishers else 0.5
                    publishers.add(pub)
                    w = hit.weight * fade * extra
                    strength += w
                    signed += w * hit.sign
                    if len(shown) < 8:
                        shown.append(
                            {
                                "title": h["title"],
                                "publisher": h.get("publisher") or "",
                                "published_at": h["published_at"],
                                "link": h.get("link") or "",
                                "calming": hit.sign < 0,
                            }
                        )
                if strength < MIN_STRENGTH:
                    continue
                sign = float(np.clip(signed / strength, -1.0, 1.0))
                first = min(int(h["published_at"]) for h, _ in pairs)
                last = max(int(h["published_at"]) for h, _ in pairs)
                row = s.scalar(
                    select(WorldEvent)
                    .where(WorldEvent.scenario == key, WorldEvent.last_seen >= first - EVENT_GAP_MS)
                    .order_by(WorldEvent.id.desc())
                )
                if row is None:
                    row = WorldEvent(
                        scenario=key,
                        title=shown[0]["title"] if shown else BY_KEY[key].title,
                        first_seen=first,
                        last_seen=last,
                        strength=strength,
                        status="active",
                        headlines=json.dumps(shown),
                        reactions=json.dumps({"sign": sign}),
                    )
                    s.add(row)
                    s.flush()
                else:
                    row.last_seen = max(row.last_seen, last)
                    row.strength = strength
                    row.headlines = json.dumps(shown)
                    if row.status == "fading":
                        row.status = "active"
                    r = json.loads(row.reactions or "{}")
                    r.setdefault("sign", sign)
                    r["sign_now"] = sign
                    row.reactions = json.dumps(r)
                events.append(
                    engine.ActiveEvent(key, strength, sign, shown, row.id, row.first_seen)
                )
            # events not heard of for three days are fading
            for row in s.scalars(
                select(WorldEvent).where(
                    WorldEvent.status == "active", WorldEvent.last_seen < now - EVENT_GAP_MS
                )
            ):
                row.status = "fading"
        self.last_detect = now
        return events

    def active(self) -> list[engine.ActiveEvent]:
        """Saved events still in the news (no new reading of headlines)."""
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            rows = s.scalars(
                select(WorldEvent)
                .where(WorldEvent.status == "active", WorldEvent.last_seen >= now - EVENT_GAP_MS)
                .order_by(WorldEvent.strength.desc())
            ).all()
            out = []
            for r in rows:
                fade = 0.5 ** (max(0.0, (now - r.last_seen) / HOUR) / 24.0)
                re_ = json.loads(r.reactions or "{}")
                out.append(
                    engine.ActiveEvent(
                        r.scenario,
                        r.strength * fade,
                        float(re_.get("sign_now", re_.get("sign", 1.0))),
                        json.loads(r.headlines or "[]"),
                        r.id,
                        r.first_seen,
                    )
                )
            return out

    # ------------------------------------------------------------ 2. effects

    def learned(self) -> dict[tuple[str, str, str, int], engine.Learned]:
        """Learned effects: past events and live ones pooled (a live event counts twice: it is
        today's market, measured on its own)."""
        hit = self._learned
        if hit is not None and time.monotonic() - hit[0] < CACHE_S:
            return hit[1]
        e = WorldEffect
        w = case((e.source == "live", 2.0), else_=1.0)
        with self.ctx.db.session() as s:
            rows = s.execute(
                select(
                    e.scenario,
                    e.market_code,
                    e.target,
                    e.horizon,
                    func.sum(w * e.n),
                    func.sum(w * e.n * e.mean),
                    func.sum(w * e.hits),
                ).group_by(e.scenario, e.market_code, e.target, e.horizon)
            ).all()
        out = {
            (sc, m, t, int(h)): engine.Learned(round(n), mm / n if n else 0.0, round(hh or 0))
            for sc, m, t, h, n, mm, hh in rows
            if n and n > 0
        }
        self._learned = (time.monotonic(), out)
        return out

    def forget_learned(self) -> None:
        """After learning: the next view reads the new effects."""
        self._learned = None

    def _profile_rows(self, market: str) -> list[tuple[int, str, str, str, str]]:
        """(id, symbol, name, sector, tags) of the broad index's stocks, cached."""
        hit = self._profiles.get(market)
        if hit is not None and time.monotonic() - hit[0] < PROFILE_CACHE_S:
            return hit[1]
        within = "nifty200" if market == "IN" else "sp500"
        p = InstrumentProfile
        with self.ctx.db.session() as s:
            rows = s.execute(
                select(Instrument.id, Instrument.symbol, Instrument.name, p.sector, p.tags, p.lists)
                .join(p, p.instrument_id == Instrument.id)
                .where(Instrument.market_code == market, p.lists.like(f"%{within}%"))
            ).all()
        out = [
            (iid, sym, name, sector, tags or "")
            for iid, sym, name, sector, tags, lists in rows
            if within in (lists or "").split(";")
        ]
        self._profiles[market] = (time.monotonic(), out)
        return out

    def view(self, market: str, *, refresh: bool = False) -> dict[str, Any]:
        events = self.detect() if refresh or not self.last_detect else self.active()
        v = engine.view(market, events, self.learned())
        helped, hurt = self._stocks(market, v)
        return {
            "market": market,
            "tilt": v.tilt,
            "sectors": v.sectors,
            "tags": v.tags,
            "drivers": v.drivers,
            "helped": helped,
            "hurt": hurt,
            "sentence": _sentence(market, v),
        }

    def _stocks(self, market: str, v: engine.View, n: int = 8) -> tuple[list[Any], list[Any]]:
        if not v.drivers:
            return [], []
        self.ctx.watchlists.ensure()
        rows: list[dict[str, Any]] = []
        for iid, sym, name, sector, tags in self._profile_rows(market):
            tilt, why = v.stock(sector, [t for t in tags.split(";") if t])
            rel = round(tilt - v.tilt, 2)
            if abs(rel) < 0.25:
                continue  # nothing beyond the whole market
            rows.append(
                {
                    "instrument_id": iid,
                    "symbol": sym,
                    "name": name,
                    "tilt": tilt,
                    "vs_market": rel,
                    "why": why,
                }
            )
        # "helped" and "hurt" are against the market: the stocks likely to do better or worse
        rows.sort(key=lambda r: (-r["vs_market"], r["symbol"]))
        helped = [r for r in rows if r["vs_market"] > 0][:n]
        hurt = [r for r in reversed(rows) if r["vs_market"] < 0][:n]
        return helped, hurt

    def stock(self, iid: int) -> dict[str, Any]:
        """What today's world events mean for one stock."""
        with self.ctx.db.session() as s:
            inst = s.get(Instrument, iid)
            prof = s.get(InstrumentProfile, iid)
        if inst is None:
            return {"tilt": 0.0, "why": [], "drivers": []}
        v = engine.view(inst.market_code, self.active(), self.learned())
        tags = [t for t in (prof.tags if prof else "").split(";") if t]
        tilt, why = v.stock(prof.sector if prof else "", tags)
        return {
            "symbol": inst.symbol,
            "tilt": tilt,
            "why": why,
            "drivers": [d["title"] for d in v.drivers],
            "sector": prof.sector if prof else "",
            "tags": tags,
        }

    # ------------------------------------------------------------ prices

    def _closes(self, market: str, symbols: list[str], lo: int, hi: int) -> dict[str, Any]:
        """{symbol: (ts array, close array)} of saved daily candles."""
        out: dict[str, Any] = {}
        with self.ctx.db.session() as s:
            refs = [store.find_instrument(s, Market(market), x) for x in symbols]
        for ref in refs:
            if ref is None:
                continue
            bars = self.ctx.cache.bars(ref, Timeframe.D1, lo, hi, adjusted_prices=True)
            if bars:
                out[ref.symbol] = (
                    np.array([b.ts for b in bars], dtype=np.int64),
                    np.array([b.close for b in bars], dtype=np.float64),
                )
        return out

    def _lines(
        self, market: str, lo: int, hi: int, targets: set[str]
    ) -> tuple[np.ndarray, dict[str, np.ndarray]] | None:
        """Aligned daily lines: the market (benchmark), each sector and each exposure tag
        asked for (equal-weight of members with prices)."""
        from backend.sectors import rotation as rot

        bench = self._closes(market, [BENCH[market]], lo, hi).get(BENCH[market])
        if bench is None or len(bench[0]) < 30:
            return None
        dates, bclose = bench
        pos = {int(t): i for i, t in enumerate(dates)}
        members: dict[str, list[rot.Member]] = defaultdict(list)
        with self.ctx.db.session() as s:
            profs = s.execute(
                select(Instrument.id, Instrument.symbol, InstrumentProfile)
                .join(InstrumentProfile, InstrumentProfile.instrument_id == Instrument.id)
                .where(
                    Instrument.market_code == market,
                    Instrument.instrument_type == "equity",
                    InstrumentProfile.lists != seed.LISTED_ONLY,  # index stocks (D-102)
                )
            ).all()
        priced = self._priced(market)
        for iid, sym, prof in profs:
            if iid not in priced:
                continue
            groups = [prof.sector] if prof.sector in targets else []
            groups += [f"tag:{t}" for t in prof.tags.split(";") if f"tag:{t}" in targets]
            if not groups:
                continue
            ref = store.InstrumentRef(iid, Market(market), sym, sym, sym, "equity")
            bars = self.ctx.cache.bars(ref, Timeframe.D1, lo, hi, adjusted_prices=True)
            close = np.full(len(dates), np.nan)
            for b in bars:
                i = pos.get(b.ts)
                if i is not None:
                    close[i] = b.close
            m = rot.Member(iid, sym, close, np.zeros(len(dates)))
            for g in groups:
                members[g].append(m)
        # the latest day counts only once most stocks have its price (D-202): 5 minutes after
        # India's close on 6 Nov only the daily desk's stocks had it, and "Industrials fell
        # 21.7%" was one or two of them; a day still coming in is left out of every line
        dates, bclose, members = trim_partial_day(dates, bclose, members)
        lines: dict[str, np.ndarray] = {"market": bclose}
        for g, ms in members.items():
            if len(ms) >= 2:
                lines[g] = _line_with_gaps(ms)
        return dates, lines

    def _priced(self, market: str) -> set[int]:
        from backend.db.models import Candle

        with self.ctx.db.session() as s:
            return {
                int(x)
                for x in s.scalars(
                    select(Instrument.id).where(
                        Instrument.market_code == market,
                        select(Candle.instrument_id)
                        .where(Candle.instrument_id == Instrument.id, Candle.timeframe == "1d")
                        .exists(),
                    )
                )
            }

    # ------------------------------------------------------------ 3. learn

    def _targets(self, market: str) -> set[str]:
        from backend.watchlists.taxonomy import SECTORS

        t = set(SECTORS)
        for sc in SCENARIOS:
            t.update(k for k in sc.effects.get(market, {}) if k != "market")
        return t

    def train_history(self, *, force: bool = False) -> dict[str, int]:
        """Measure every past event (``history.py``) on the saved prices: re-done from scratch
        when the saved prices grew (a day's new candles don't change old reactions, but a
        newly downloaded stock adds members)."""
        now = self.ctx.clock.now_ms()
        counts: dict[str, int] = {}
        key_parts = []
        for market in ("IN", "US"):
            key_parts.append(f"{market}:{len(self._priced(market))}")
        key = "|".join(key_parts)
        if not force and key == self.last_train_key:
            return {}
        stats: dict[tuple[str, str, str, int], list[Any]] = {}
        for market in ("IN", "US"):
            got = self._lines(market, 0, now + 1, self._targets(market))
            if got is None:
                continue
            dates, lines = got
            zone = MARKET_TZ[Market(market)]
            days = [_local_date(int(t), zone) for t in dates]
            measured = 0
            for ev in EVENTS:
                sc = BY_KEY.get(ev.scenario)
                if sc is None:
                    continue
                d = date.fromisoformat(ev.day)
                base = (
                    int(np.searchsorted(np.array([x.toordinal() for x in days]), d.toordinal())) - 1
                )
                if base < 0 or base + 1 >= len(dates):
                    continue
                if days[base + 1].toordinal() - d.toordinal() > 7:
                    continue  # no data around that date
                rx = engine.reactions(lines, base)
                if "market" not in rx:
                    continue
                measured += 1
                for target, by_h in rx.items():
                    prior = sc.effects.get(market, {}).get(target)
                    for h, val in by_h.items():
                        x = val * ev.sign
                        k = (ev.scenario, market, target, h)
                        a = stats.setdefault(k, [0, 0.0, 0.0, 0])
                        n, mean, m2 = engine.welford(int(a[0]), a[1], a[2], x)
                        hit = int(prior is not None and prior != 0 and x * prior > 0)
                        stats[k] = [n, mean, m2, a[3] + hit]
            counts[market] = measured
        with self.ctx.db.session() as s:
            s.execute(delete(WorldEffect).where(WorldEffect.source == "history"))
            for (sc_key, market, target, h), (n, mean, m2, hits) in stats.items():
                s.add(
                    WorldEffect(
                        scenario=sc_key,
                        market_code=market,
                        target=target,
                        horizon=h,
                        source="history",
                        n=int(n),
                        mean=float(mean),
                        m2=float(m2),
                        hits=int(hits),
                        updated_at=now,
                    )
                )
        self.last_train_key = key
        self.forget_learned()
        log.info("World map trained on past events: %s", counts)
        return counts

    def learn_live(self) -> int:
        """Measure live events whose days have passed and fold them into the learned effects."""
        now = self.ctx.clock.now_ms()
        done = 0
        with self.ctx.db.session() as s:
            rows = s.scalars(
                select(WorldEvent).where(
                    WorldEvent.status != "measured", WorldEvent.first_seen <= now - DAY_MS
                )
            ).all()
            pending = [
                (r.id, r.scenario, r.first_seen, json.loads(r.reactions or "{}")) for r in rows
            ]
        for eid, sc_key, first, reactions in pending:
            sc = BY_KEY.get(sc_key)
            if sc is None:
                continue
            sign = float(reactions.get("sign", 1.0))
            sign = 1.0 if sign >= 0 else -1.0
            measured: dict[str, dict[str, dict[str, float]]] = reactions.get("measured", {})
            complete = True
            for market in sc.effects:
                got = self._lines(market, first - 120 * DAY_MS, now + 1, self._targets(market))
                if got is None:
                    continue  # no prices for that market: nothing to learn there
                dates, lines = got
                base = engine.base_index(dates, first - 6 * HOUR)
                if base is None:
                    continue
                rx = engine.reactions(lines, base)
                have = measured.setdefault(market, {})
                for target, by_h in rx.items():
                    for h, val in by_h.items():
                        hk = str(h)
                        if hk in have.get(target, {}):
                            continue
                        have.setdefault(target, {})[hk] = val
                        self._add_live(sc_key, market, target, h, val * sign, now)
                        done += 1
                if not all(str(20) in v for v in have.values()) or not have:
                    complete = False
            reactions["measured"] = measured
            with self.ctx.db.session() as s:
                row = s.get(WorldEvent, eid)
                if row is not None:
                    row.reactions = json.dumps(reactions)
                    if complete and now - first > 35 * DAY_MS:
                        row.status = "measured"
        if done:
            self.forget_learned()
        return done

    def _add_live(self, sc_key: str, market: str, target: str, h: int, x: float, now: int) -> None:
        prior = BY_KEY[sc_key].effects.get(market, {}).get(target)
        with self.ctx.db.session() as s:
            row = s.scalar(
                select(WorldEffect).where(
                    WorldEffect.scenario == sc_key,
                    WorldEffect.market_code == market,
                    WorldEffect.target == target,
                    WorldEffect.horizon == h,
                    WorldEffect.source == "live",
                )
            )
            if row is None:
                row = WorldEffect(
                    scenario=sc_key,
                    market_code=market,
                    target=target,
                    horizon=h,
                    source="live",
                    n=0,
                    mean=0.0,
                    m2=0.0,
                    hits=0,
                    updated_at=now,
                )
                s.add(row)
            n, mean, m2 = engine.welford(row.n, row.mean, row.m2, x)
            row.n, row.mean, row.m2 = n, mean, m2
            row.hits += int(prior is not None and prior != 0 and x * prior > 0)
            row.updated_at = now

    def lessons(self, scenario: str | None = None) -> list[dict[str, Any]]:
        """What each kind of event did, measured (5 trading days), strongest first."""
        out = []
        for (sc, market, target, h), ln in self.learned().items():
            if h != 5 or (scenario and sc != scenario):
                continue
            prior = BY_KEY[sc].effects.get(market, {}).get(target) if sc in BY_KEY else None
            out.append(
                {
                    "scenario": sc,
                    "title": BY_KEY[sc].title if sc in BY_KEY else sc,
                    "market": market,
                    "target": target,
                    "n": ln.n,
                    "mean_pct": round(ln.mean, 2),
                    "map": prior,
                    "agrees": None if not prior else (ln.mean * prior > 0),
                }
            )
        out.sort(key=lambda x: -abs(float(x["mean_pct"])) * min(1.0, int(x["n"]) / 5))  # type: ignore[arg-type,call-overload]
        return out

    # ------------------------------------------------------------ 4. investigate moves

    def investigate(self, market: str, *, force: bool = False) -> list[dict[str, Any]]:
        """Look for unusual moves on the latest daily candle (the market and each sector) and
        find their most likely cause. Each move is investigated once."""
        now = self.ctx.clock.now_ms()
        targets = {"market", *self._targets(market)}
        got = self._lines(market, now - 200 * DAY_MS, now + 1, targets)
        if got is None:
            return []
        dates, lines = got
        out: list[dict[str, Any]] = []
        found: list[tuple[str, float, float]] = []
        for target, line in lines.items():
            if target.startswith("tag:"):
                continue
            u = inv.unusual(line, kind="market" if target == "market" else "sector")
            if u is not None:
                found.append((target, u[0], u[1]))
        if not found:
            return []
        end = int(dates[-1])
        start = int(dates[-2])
        session_close = end + (375 if market == "IN" else 390) * 60_000
        for target, pct, z in found:
            with self.ctx.db.session() as s:
                dup = s.scalar(
                    select(MoveInvestigation.id).where(
                        MoveInvestigation.market_code == market,
                        MoveInvestigation.target == target,
                        MoveInvestigation.end_ts == session_close,
                    )
                )
            if dup is not None and not force:
                continue
            label = (
                BENCH_LABEL[market]
                if target == "market"
                else f"{target} ({'India' if market == 'IN' else 'US'})"
            )
            move = inv.Move(market, target, label, "1d", start + 6 * HOUR, session_close, pct, z)
            out.append(self.explain_move(move))
        return out

    def explain_move(self, move: inv.Move) -> dict[str, Any]:
        """Score the causes of one move, save the investigation and teach the world map."""
        now = self.ctx.clock.now_ms()
        self._search_web(move)
        heads = self._headlines(since=move.start_ts - 30 * HOUR, hours=0)
        heads = [h for h in heads if int(h["published_at"]) <= move.end_ts + 6 * HOUR]
        sym, tags = self._sector_members(move)
        causes = inv.rank(
            move,
            heads,
            sector_symbols=sym,
            sector_tags=tags,
            clues=self._clues(move),
            other_market=self._other_market(move),
        )
        zone = MARKET_TZ[Market(move.market)]
        when = "on " + ms_to_dt(move.end_ts, _zone(zone)).strftime("%a %d %b")
        text = inv.explain(move, causes, when)
        verdict = inv.verdict(causes)
        detail = {
            "causes": [c.to_json() for c in causes[:6]],
            "confidence": inv.confidence(causes),
            "headlines_read": len(heads),
        }
        with self.ctx.db.session() as s:
            row = MoveInvestigation(
                market_code=move.market,
                target=move.target,
                timeframe=move.timeframe,
                start_ts=move.start_ts,
                end_ts=move.end_ts,
                move_pct=move.move_pct,
                zscore=move.z,
                created_at=now,
                verdict=verdict,
                text=text,
                detail=json.dumps(detail),
            )
            s.add(row)
            s.flush()
            rid = row.id
        log.info("Move investigated: %s", text)
        return {"id": rid, "verdict": verdict, "text": text, **detail, **_move_json(move)}

    def _sector_members(self, move: inv.Move) -> tuple[frozenset[str], frozenset[str]]:
        if move.target == "market":
            return frozenset(), frozenset()
        syms: set[str] = set()
        tags: dict[str, int] = defaultdict(int)
        with self.ctx.db.session() as s:
            for sym, prof in s.execute(
                select(Instrument.symbol, InstrumentProfile)
                .join(InstrumentProfile, InstrumentProfile.instrument_id == Instrument.id)
                .where(
                    Instrument.market_code == move.market,
                    InstrumentProfile.sector == move.target,
                    InstrumentProfile.lists != seed.LISTED_ONLY,
                )
            ).all():
                syms.add(sym)
                for t in prof.tags.split(";"):
                    if t:
                        tags[t] += 1
        common = {t for t, n in tags.items() if n >= max(2, len(syms) // 5)}
        return frozenset(syms), frozenset(common)

    def _clues(self, move: inv.Move) -> dict[str, tuple[float, float]]:
        out: dict[str, tuple[float, float]] = {}
        lo = move.end_ts - 120 * DAY_MS
        for asset, (market, sym, sign) in CLUES.items():
            got = self._closes(market, [sym], lo, move.end_ts + DAY_MS).get(sym)
            if got is None:
                continue
            z = inv.zscore(got[1])
            if z is not None:
                out[asset] = (z[0] * sign, z[1] * sign)
        return out

    def _other_market(self, move: inv.Move) -> tuple[str, float, float] | None:
        other = "US" if move.market == "IN" else "IN"
        got = self._closes(other, [BENCH[other]], move.start_ts - 120 * DAY_MS, move.end_ts)
        series = got.get(BENCH[other])
        if series is None:
            return None
        ts, c = series
        keep = ts < move.end_ts - 6 * HOUR
        z = inv.zscore(c[keep])
        if z is None:
            return None
        return (BENCH_LABEL[other][0].upper() + BENCH_LABEL[other][1:], z[0], z[1])

    def _search_web(self, move: inv.Move) -> None:
        """On the laptop: ask GDELT (the open index of the world's news sites) for stories in
        the move's window, so the investigation isn't limited to the feeds Agora follows."""
        news = self.ctx.services.get("news")
        if self.ctx.data_mode != "real" or news is None or not news.enabled():
            return
        from backend.news.feeds import Feed, gdelt_window_url

        words = (
            "(stock market OR shares OR sensex OR nifty)"
            if move.market == "IN"
            else ("(stock market OR wall street OR stocks)")
        )
        if move.target != "market":
            words = f'("{move.target}" OR sector) {words}'
        feed = Feed(
            f"gdelt_move_{move.market}",
            "GDELT · search",
            gdelt_window_url(words, move.start_ts - 24 * HOUR, move.end_ts + 3 * HOUR),
            Market(move.market),
            "world",
            format="gdelt",
        )
        try:
            news.refresh([feed], force=True)
        except Exception:
            log.info("GDELT search for the move failed")

    def investigations(self, market: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with self.ctx.db.session() as s:
            q = select(MoveInvestigation).order_by(MoveInvestigation.id.desc()).limit(limit)
            if market:
                q = q.where(MoveInvestigation.market_code == market)
            rows = s.scalars(q).all()
            return [
                {
                    "id": r.id,
                    "market": r.market_code,
                    "target": r.target,
                    "timeframe": r.timeframe,
                    "start_ts": r.start_ts,
                    "end_ts": r.end_ts,
                    "move_pct": r.move_pct,
                    "z": r.zscore,
                    "verdict": r.verdict,
                    "text": r.text,
                    "created_at": r.created_at,
                    **json.loads(r.detail or "{}"),
                }
                for r in rows
            ]

    def events(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.ctx.db.session() as s:
            rows = s.scalars(
                select(WorldEvent).order_by(WorldEvent.last_seen.desc()).limit(limit)
            ).all()
            return [
                {
                    "id": r.id,
                    "scenario": r.scenario,
                    "kind": BY_KEY[r.scenario].title if r.scenario in BY_KEY else r.scenario,
                    "title": r.title,
                    "first_seen": r.first_seen,
                    "last_seen": r.last_seen,
                    "strength": round(r.strength, 1),
                    "status": r.status,
                    "headlines": json.loads(r.headlines or "[]"),
                    "reactions": json.loads(r.reactions or "{}"),
                }
                for r in rows
            ]


def trim_partial_day(
    dates: np.ndarray, bclose: np.ndarray, members: dict[str, list[Any]]
) -> tuple[np.ndarray, np.ndarray, dict[str, list[Any]]]:
    """Leave out the latest day while fewer than ``MIN_COVER`` of the stocks that had the day
    before have its price (D-202)."""
    from backend.sectors import rotation as rot

    everyone = list({id(m): m for ms in members.values() for m in ms}.values())
    before = [m for m in everyone if len(m.close) >= 2 and np.isfinite(m.close[-2])]
    if not before or len(dates) <= 2:
        return dates, bclose, members
    have = sum(1 for m in before if np.isfinite(m.close[-1]))
    if have >= MIN_COVER * len(before):
        return dates, bclose, members
    cut = {
        id(m): rot.Member(m.instrument_id, m.symbol, m.close[:-1], m.volume[:-1]) for m in everyone
    }
    return dates[:-1], bclose[:-1], {g: [cut[id(m)] for m in ms] for g, ms in members.items()}


def _line_with_gaps(members: list[Any]) -> np.ndarray:
    from backend.sectors import rotation as rot

    line = rot.equal_weight(members)
    # Before any member has a price the line is flat at 100: mark it unknown instead.
    have = np.zeros(len(line), dtype=bool)
    for m in members:
        have |= np.isfinite(m.close)
    out = line.copy()
    first = int(np.argmax(have)) if have.any() else len(line)
    out[:first] = np.nan
    return out


def _zone(name: str) -> Any:
    from zoneinfo import ZoneInfo

    return ZoneInfo(name)


def _local_date(ts: int, zone: str) -> date:
    return ms_to_dt(ts, _zone(zone)).date()


def _move_json(m: inv.Move) -> dict[str, Any]:
    return {
        "market": m.market,
        "target": m.target,
        "label": m.label,
        "move_pct": m.move_pct,
        "z": m.z,
        "start_ts": m.start_ts,
        "end_ts": m.end_ts,
    }


def _sentence(market: str, v: engine.View) -> str:
    if not v.drivers:
        return "No world event in the news is big enough to move this market right now."
    top = v.drivers[0]
    what = "calming" if top["calming"] else "in the news"
    lean = (
        "leans against the market"
        if v.tilt <= -0.3
        else "leans in the market's favour"
        if v.tilt >= 0.3
        else "matters for some sectors more than for the market"
    )
    return f"{top['title']} is {what}; it {lean}."
