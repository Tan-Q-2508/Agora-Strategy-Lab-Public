"""The news guard: Kairos's damage control on its paper desk (Phase 10.6, D-69).

The Kairos brain trades on prices. Live, the desk also hands it this guard, which reads
the news risk gauge for the desk's market and each stock's own headlines (both from
``backend/news``, D-68) and says what the brain may do on the candle that just closed. It
never places an order itself: it can only stop the brain opening a trade, shrink a new
trade, nudge the score, or ask the brain to close a position, and the brain's code does
the rest in the shared engine (D-56).

What it says, by setting ``kairos.news_guard`` (D-211: the user, 2026-11-06, "news risk doesn't
mean Kairos stops trading… be cautious on the negative side and opportune on the positive"):

News, and what the guard says in protective mode (cautious mode changes sizes and scores but
never closes a trade):

- it **helps** this stock's sector (oil falls: paints, airlines): score +10, readier to buy, and
  market risk doesn't halve the trade;
- it **hurts** this stock's sector: new trades at half size; a long 1%+ down is cut;
- market risk *elevated* or *severe* (50+): new trades at half size; a losing long is cut once
  the watchlist falls 0.5%+ on the candle, and at 75+ any long once it falls 1%+ ¹;
- calming news, market risk under 25: score +5;
- a stock's own news *critical* ²: close a long in it, no new long;
- a stock's own news *negative*: half size, score −10, a long 1%+ down is cut;
- a stock's own news *positive*: score +10 for a long ("go in" on a catalyst).

¹ the gauge is read from headline words; the market's own prices must agree before market news
  closes a trade (D-179). Other markets' news while this market isn't falling changes nothing
  (D-198). Severity alone never stops trading: shorts are never blocked by news, and the only
  "no new trade" is a company's own red flag.
² a red-flag headline: fraud, a raid, a default, a profit warning, the CEO quitting…

Which sectors a story helps or hurts comes from its topic (``news.topics``); which sectors a
stock is in, from its profile (``news.exposure``). Going back in is automatic: stories age with
a 6-hour half-life.

The guard only judges a candle that closed after the desk went live and within two
candle-lengths of now: never warm-up history, never a practice replay, never a backtest
(news has no archive here, so backtests stay reproducible and treat news as neutral).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.core.types import Market
from backend.logging_setup import get_logger
from backend.settings_store import read_setting

log = get_logger("kairos.news_guard")

WATCHFUL, ELEVATED, SEVERE, PANIC = 25.0, 50.0, 75.0, 90.0
CONFIRM_MOVE_PCT = -1.0  # the watchlist's average move that confirms a severe reading
CONFIRM_ELEVATED_PCT = -0.5  # … and an elevated one (D-179)
# Entries on other markets' news (D-198): when less than this share of the gauge is this market's
# own news and this market isn't falling today (its day move above HOME_CALM_PCT), a desk still
# opens trades, at half size, instead of none.
HOME_SHARE = 0.5
HOME_CALM_PCT = -0.5
NUDGE = 10.0
# D-211: news that helps or hurts a stock's sector, weighed like the gauge's stories (a fresh
# severity-3 story moving a sector reads about 0.6); the gauge's calming news (same scale)
SECTOR_EDGE = 0.3
CALMING_EDGE = 0.5
CUT_LOSS_PCT = -1.0  # a long this far down is cut when the news hurts it


@dataclass(frozen=True)
class Advice:
    level: float = 0.0
    name: str = "calm"
    block_long: bool = False
    block_short: bool = False
    exit_long: bool = False
    size_factor: float = 1.0
    nudge: float = 0.0
    reason: str = ""

    @property
    def active(self) -> bool:
        return self.block_long or self.block_short or self.exit_long or self.size_factor < 1


NEUTRAL = Advice()


def sector_effect(gauge: dict[str, Any], exposure: frozenset[str]) -> tuple[float, list[str]]:
    """The net push of the stories on now on this stock's sectors (+ helps, − hurts), and the
    sectors it comes from, strongest first."""
    tilt = gauge.get("sector_tilt") or {}
    hits = sorted(
        ((name, float(tilt[name])) for name in exposure if name in tilt),
        key=lambda x: -abs(x[1]),
    )
    return sum(v for _, v in hits), [n for n, _ in hits]


def _story_for(gauge: dict[str, Any], sectors: list[str], sign: int) -> str:
    """The headline behind a sector's push: the gauge's heaviest story for it (D-213: notes
    named the first top story touching the sector, so US banks were "hurt" by a Paraguayan bank
    collapse that wasn't what moved them, and others said "()")."""
    told = gauge.get("sector_story") or {}
    for s in sectors:
        if told.get(s):
            return str(told[s])
    for d in gauge.get("drivers") or []:
        effects = d.get("sectors") or {}
        if any(int(effects.get(s, 0)) * sign > 0 for s in sectors):
            return str(d.get("title") or "")
    return ""


def advise(
    mode: str,
    gauge: dict[str, Any],
    alert: dict[str, Any],
    *,
    long_pnl_pct: float | None,
    move_pct: Callable[[], float | None],
    home_move: Callable[[], float | None] | None = None,
    exposure: frozenset[str] = frozenset(),
) -> Advice:
    """The rule table above. ``long_pnl_pct`` is the open long's unrealised profit (None when
    not long); ``move_pct`` gives the watchlist's last-candle move, ``home_move`` its move
    today; ``exposure`` the news sectors this stock belongs to (``news.exposure``)."""
    if mode == "off":
        return NEUTRAL
    level = float(gauge.get("level") or 0.0)
    name = str(gauge.get("name") or "calm")
    lead = (gauge.get("drivers") or [{}])[0].get("title") or ""
    protective = mode == "protective"
    block_long = exit_long = False
    size, nudge = 1.0, 0.0
    why: list[str] = []

    # 1. this stock's own part of the market: helped or hurt by the stories on now
    push, sectors = sector_effect(gauge, exposure)
    helped = push >= SECTOR_EDGE
    hurt = push <= -SECTOR_EDGE
    if helped:
        nudge += NUDGE
        story = _story_for(gauge, sectors, +1)
        about = f" ({story})" if story else ""
        why.append(f"the news helps {', '.join(sectors[:2])}: looking for a long{about}")
    elif hurt:
        size = 0.5
        story = _story_for(gauge, sectors, -1)
        about = f" ({story})" if story else ""
        why.append(f"the news hurts {', '.join(sectors[:2])}: new trades at half size{about}")
        if protective and long_pnl_pct is not None and long_pnl_pct <= CUT_LOSS_PCT:
            exit_long = True
            why.append(f"this trade is {long_pnl_pct:+.1f}%: cut the loss")

    # 2. the market as a whole. Risk never stops trading on its own (D-211): it halves new
    # trades and cuts losing longs once the market's own prices agree.
    calm_home = False
    today: float | None = None
    if (
        level >= ELEVATED
        and home_move is not None
        and float(gauge.get("home_share", 1.0)) < HOME_SHARE
    ):
        today = home_move()  # other markets' news: does it show here? (D-198)
        calm_home = today is not None and today > HOME_CALM_PCT
    if level >= ELEVATED and not helped and not calm_home:
        if size > 0.5:
            size = 0.5
            here = f"; this market's stocks are {today:+.1f}% today" if today is not None else ""
            why.append(f"news risk {name} ({level:.0f}/100){here}: new trades at half size: {lead}")
        if protective and long_pnl_pct is not None and not exit_long:
            moved = move_pct()
            if moved is not None and level >= SEVERE and moved <= CONFIRM_MOVE_PCT:
                exit_long = True
                why.append(f"the market fell with it ({moved:+.1f}% on the candle): sell")
            elif moved is not None and long_pnl_pct < 0 and moved <= CONFIRM_ELEVATED_PCT:
                exit_long = True
                why.append(f"this trade is losing and the watchlist moved {moved:+.1f}%: cut early")
    elif level < WATCHFUL and float(gauge.get("calming") or 0.0) >= CALMING_EDGE:
        nudge += NUDGE / 2  # good news for the whole market: a little readier to buy
        story = next(
            (str(d.get("title")) for d in gauge.get("drivers") or [] if d.get("weight", 0) < 0),
            "",
        )
        why.append(f"calming news for the market ({story})")

    # 3. the company's own news
    state = alert.get("state")
    headline = alert.get("headline") or ""
    if state == "critical":
        block_long = True
        why.append(f"red-flag company news ({alert.get('flag', 'bad news')}): {headline}")
        if protective and long_pnl_pct is not None:
            exit_long = True
    elif state == "negative":
        size = min(size, 0.5)
        nudge -= NUDGE
        why.append(f"the company's news is negative: {headline}")
        if protective and long_pnl_pct is not None and long_pnl_pct <= CUT_LOSS_PCT:
            exit_long = True
    elif state == "positive":
        nudge += NUDGE
        why.append(f"a positive catalyst: {headline}")
    return Advice(
        level=level,
        name=name,
        block_long=block_long,
        block_short=False,
        exit_long=exit_long,
        size_factor=size,
        nudge=nudge,
        reason="; ".join(why)[:300],
    )


class NewsGuard:
    """One per live desk session: reads the news for the brain and writes what it did to
    the desk diary (one note per stock, action and day)."""

    def __init__(
        self,
        ctx: Any,
        session_id: int,
        market: Market,
        instruments: dict[str, int],
        *,
        live_from: int,
        bar_ms: int,
        move_pct: Callable[[], float | None],
        home_move: Callable[[], float | None] | None = None,
    ) -> None:
        self.ctx = ctx
        self.home_move = home_move
        self.session_id = session_id
        self.market = market
        self.instruments = instruments
        self.live_from = live_from
        self.bar_ms = bar_ms
        self.move_pct = move_pct
        self._noted: set[tuple[str, str, str]] = set()
        self._lock = threading.Lock()
        self.last: dict[str, Advice] = {}
        self._exposure: dict[int, frozenset[str]] | None = None

    def exposure(self, iid: int | None) -> frozenset[str]:
        """The news sectors a stock belongs to, from its profile (read once per desk)."""
        if iid is None:
            return frozenset()
        if self._exposure is None:
            from sqlalchemy import select

            from backend.db.models import InstrumentProfile
            from backend.news.exposure import names_for

            ids = list(self.instruments.values())
            with self.ctx.db.session() as s:
                rows = s.scalars(
                    select(InstrumentProfile).where(InstrumentProfile.instrument_id.in_(ids))
                ).all()
                self._exposure = {
                    r.instrument_id: names_for(r.sector, r.industry, (r.tags or "").split(";"))
                    for r in rows
                }
        return self._exposure.get(iid, frozenset())

    def mode(self) -> str:
        return str(read_setting(self.ctx.db, "kairos.news_guard"))

    def advise(self, symbol: str, candle_ts: int, long_pnl_pct: float | None) -> Advice:
        now = self.ctx.clock.now_ms()
        if candle_ts < self.live_from - 2 * self.bar_ms or now - candle_ts > 3 * self.bar_ms:
            return NEUTRAL  # warm-up history or a stale candle: news can't know about it
        svc = self.ctx.news
        if not svc.enabled():
            return NEUTRAL
        try:
            mode = self.mode()
            if mode == "off":
                return NEUTRAL
            iid = self.instruments.get(symbol)
            svc.ensure_fresh([*svc.feeds(self.market), *svc.world_feeds(self.market)])
            gauge = svc.risk(self.market)
            alert = svc.alert(iid) if iid is not None else {"state": "quiet"}
            out = advise(
                mode,
                gauge,
                alert,
                long_pnl_pct=long_pnl_pct,
                move_pct=self.move_pct,
                home_move=self.home_move,
                exposure=self.exposure(iid),
            )
        except Exception:  # the news must never stop the desk from trading its signals
            log.exception("News guard failed; trading on prices only")
            return NEUTRAL
        self.last[symbol] = out
        return out

    def acted(self, symbol: str, action: str, advice: Advice, day: str) -> None:
        """Record that the brain followed the guard (closed a trade / skipped an entry)."""
        key = (symbol, action, day)
        with self._lock:
            if key in self._noted:
                return
            self._noted.add(key)
        words = {
            # a desk's sell fills at the next candle's open (D-201: "closed" read as done)
            "exit": f"News guard: selling {symbol} at the next candle's open",
            "skip": f"News guard: did not open a trade in {symbol}",
            # the desk may still refuse it (no room): say what the guard did (D-205)
            "half": f"News guard: halved the size of a trade in {symbol}",
        }[action]
        text = f"{words} because {advice.reason}."
        try:
            from backend.kairos.desk import write_note

            write_note(
                self.ctx,
                self.session_id,
                self.instruments.get(symbol),
                text,
                {"guard": action, "level": advice.level, "name": advice.name},
            )
        except Exception:
            log.exception("Couldn't write the news guard's note")
