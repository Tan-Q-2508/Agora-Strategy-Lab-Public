"""Turn loose words into exact things: stocks, strategies, templates, timeframes, dates.

A small model writes "reliance", "Apple", "TCS.NS", "the RSI one" or "last 5 years"; the
tools need instrument ids, strategy versions and timestamps. Everything here is forgiving
(case, suffixes, company names, close spellings) and says plainly what it couldn't find.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select

from backend.core.types import Market, Timeframe
from backend.data import service as data_service
from backend.data.store import InstrumentRef, ref
from backend.db.models import Instrument, Strategy
from backend.errors import AgoraError
from backend.news import relevance
from backend.strategy import service as strategy_service
from backend.strategy import templates
from backend.watchlists import seed

DAY_MS = 86_400_000


MAX_FROM_LIST = 30


class NotFound(AgoraError):
    def __init__(self, message: str, action: str) -> None:
        super().__init__("KAIROS_NOT_FOUND", message, action, status=404)


# ---------------------------------------------------------------- markets & timeframes


def market_of(text: str | None) -> Market | None:
    if not text:
        return None
    t = text.strip().lower()
    if t in ("in", "india", "indian", "nse", "nifty", "nifty 50", "bse", "sensex"):
        return Market.IN
    if t in ("us", "usa", "america", "american", "nyse", "nasdaq", "s&p", "s&p 500", "wall street"):
        return Market.US
    return None


_TF = {
    "1d": Timeframe.D1,
    "d": Timeframe.D1,
    "day": Timeframe.D1,
    "daily": Timeframe.D1,
    "1h": Timeframe.H1,
    "h": Timeframe.H1,
    "hour": Timeframe.H1,
    "hourly": Timeframe.H1,
    "60m": Timeframe.H1,
    "15m": Timeframe.M15,
    "15": Timeframe.M15,
    "15 min": Timeframe.M15,
    "15min": Timeframe.M15,
    "15 minutes": Timeframe.M15,
    "5m": Timeframe.M5,
    "5": Timeframe.M5,
    "5 min": Timeframe.M5,
    "5min": Timeframe.M5,
    "5 minutes": Timeframe.M5,
    "1m": Timeframe.M1,
    "1 min": Timeframe.M1,
    "1min": Timeframe.M1,
    "1 minute": Timeframe.M1,
    "minute": Timeframe.M1,
}


def timeframe(text: str | None, default: Timeframe = Timeframe.D1) -> Timeframe:
    if not text:
        return default
    return _TF.get(text.strip().lower(), default)


# ---------------------------------------------------------------- stocks


@dataclass(frozen=True)
class Known:
    inst: InstrumentRef
    names: tuple[str, ...]
    rare: bool = False  # in no index and not used by you: matched by exact ticker only (D-102)


_CACHE: dict[int, tuple[int, list[Known], relevance.Matcher]] = {}


def _known(ctx: Any) -> tuple[list[Known], relevance.Matcher]:
    """Every active stock, and a matcher over the commonly named ones. Cached until the
    number of stocks (or of the ones you use) changes: building it for ~8,500 stocks takes
    a moment."""
    with ctx.db.session() as s:
        rare = seed.rarely_named(s)
        count = int(s.scalar(select(func.count(Instrument.id))) or 0)
        key = count * 100_000 + len(rare)
        hit = _CACHE.get(id(ctx))
        if hit is not None and hit[0] == key:
            return hit[1], hit[2]
        rows = s.scalars(select(Instrument).where(Instrument.is_active == 1)).all()
        shared = relevance.shared_first_words([r.name for r in rows])
        out = []
        for r in rows:
            t = relevance.target(r.id, r.symbol, r.name, shared, r.market_code)
            out.append(Known(ref(r), tuple(n.lower() for n in t.names), r.id in rare))
    common = [k for k in out if not k.rare]
    by_symbol = {k.inst.symbol.lower(): k.inst.id for k in common}
    by_name = {k.names[0]: k.inst.id for k in common if k.names}
    targets = []
    shared = relevance.shared_first_words([k.inst.name for k in out])
    for k in common:
        t = relevance.target(k.inst.id, k.inst.symbol, k.inst.name, shared, k.inst.market.value)
        names = tuple(n for n in t.names if _own(k, n.lower(), by_symbol, by_name))
        targets.append(relevance.Target(t.instrument_id, t.symbol, names))
    matcher = relevance.Matcher(targets)
    _CACHE[id(ctx)] = (key, out, matcher)
    return out, matcher


def _own(k: Known, n: str, by_symbol: dict[str, int], by_name: dict[str, int]) -> bool:
    """Is ``n`` this stock's name to claim? Not when it is another stock's ticker
    ("RELIANCE" is RELIANCE, not Reliance Steel or Reliance Power), and a first word isn't
    when it is another company's whole name ("Apple" is Apple Inc, not Apple Hospitality)."""
    if by_symbol.get(n, k.inst.id) != k.inst.id:
        return False
    return not (k.names and n != k.names[0] and by_name.get(n, k.inst.id) != k.inst.id)


def _all(ctx: Any) -> list[Known]:
    return _known(ctx)[0]


def stock(ctx: Any, text: str, market: Market | None = None) -> InstrumentRef:
    """One stock from a ticker, a Yahoo symbol or a company name."""
    raw = text.strip()
    if not raw:
        raise NotFound(
            "Which stock? I didn't get a name.", "Name a stock, for example RELIANCE or AAPL."
        )
    want = raw.upper().removesuffix(".NS").removesuffix(".BO")
    if want in ("NIFTY", "NIFTY 50", "NIFTY50", "^NSEI"):
        want = "^NSEI"
    known = _all(ctx)
    pool = [k for k in known if market is None or k.inst.market is market] or known
    for k in pool:
        if k.inst.symbol.upper() == want or k.inst.yahoo_symbol.upper() in (want, raw.upper()):
            return k.inst
    low = raw.lower()
    for k in pool:
        if low in k.names or low == k.inst.name.lower():
            return k.inst
    # A close spelling of a ticker or a name ("relaince", "infosis"), among the stocks people
    # usually mean (index stocks and yours), not the ~6,000 small listed ones.
    choices: dict[str, InstrumentRef] = {}
    for k in [k for k in pool if not k.rare] or pool:
        choices[k.inst.symbol.lower()] = k.inst
        for n in k.names:
            choices.setdefault(n, k.inst)
    close = difflib.get_close_matches(low, list(choices), n=1, cutoff=0.8)
    if close:
        return choices[close[0]]
    hint = (
        "Agora knows the Nifty 500 (and the Microcap 250), the S&P 500, 400 and 600, the "
        "Nasdaq-100 and your own US tickers"
    )
    if re.fullmatch(r"[A-Za-z]{1,5}([.-][A-Za-z])?", raw) and market is not Market.IN:
        hint += f"; to add the US ticker {raw.upper()}, use the Data screen"
    raise NotFound(f"I couldn't find a stock called “{raw}”.", hint + ".")


def stocks(
    ctx: Any, items: list[str] | str | None, market: Market | None = None
) -> list[InstrumentRef]:
    """Several stocks ("RELIANCE, TCS and Infosys", or a list); duplicates removed."""
    if not items:
        return []
    parts = items if isinstance(items, list) else re.split(r",|;|\band\b|&(?!T)|\n", items)
    out: list[InstrumentRef] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        try:
            found = [stock(ctx, p, market)]
        except NotFound:
            # "the Nifty IT list", "US semiconductors": a watchlist's stocks (D-94)
            lists = ctx.services.get("watchlists")
            wl = lists.find(p, market.value if market else None) if lists else None
            if wl is None:
                raise
            found = lists.instruments(wl["id"])[:MAX_FROM_LIST]
        for inst in found:
            if all(o.id != inst.id for o in out):
                out.append(inst)
    return out


def universe(ctx: Any, market: Market) -> list[InstrumentRef]:
    with ctx.db.session() as s:
        return [i for i in data_service.default_symbols(s, market) if not i.is_index]


# Everyday words that are also tickers or company names ("is it safe to trade", "any news",
# "the best strategy"): written in lower case they mean the word, not the stock. In capitals
# (SAFE, NWS) the ticker still counts.
EVERYDAY = frozenset(
    [
        "rsi",
        "macd",
        "ema",
        "sma",
        "atr",
        "adx",
        "vwap",
        "about",
        "after",
        "again",
        "all",
        "also",
        "and",
        "any",
        "are",
        "back",
        "bank",
        "banks",
        "best",
        "big",
        "bill",
        "both",
        "buy",
        "call",
        "can",
        "card",
        "care",
        "cash",
        "chart",
        "charts",
        "check",
        "close",
        "core",
        "data",
        "day",
        "days",
        "deal",
        "does",
        "doing",
        "down",
        "each",
        "earn",
        "edge",
        "even",
        "ever",
        "fast",
        "find",
        "fine",
        "first",
        "five",
        "flat",
        "for",
        "free",
        "from",
        "fund",
        "funds",
        "fuel",
        "gain",
        "gas",
        "gold",
        "good",
        "great",
        "grow",
        "growth",
        "has",
        "have",
        "help",
        "here",
        "high",
        "hold",
        "home",
        "hot",
        "how",
        "idea",
        "into",
        "its",
        "just",
        "keep",
        "key",
        "kind",
        "last",
        "less",
        "life",
        "like",
        "line",
        "live",
        "long",
        "look",
        "loss",
        "low",
        "main",
        "make",
        "many",
        "market",
        "markets",
        "mean",
        "metal",
        "more",
        "most",
        "move",
        "much",
        "must",
        "new",
        "news",
        "next",
        "nice",
        "now",
        "oil",
        "one",
        "only",
        "open",
        "over",
        "own",
        "part",
        "pay",
        "peak",
        "plan",
        "play",
        "plus",
        "post",
        "power",
        "price",
        "prices",
        "pure",
        "rate",
        "real",
        "rest",
        "rise",
        "risk",
        "run",
        "safe",
        "same",
        "save",
        "sell",
        "set",
        "share",
        "shares",
        "should",
        "show",
        "sign",
        "size",
        "slow",
        "some",
        "spot",
        "star",
        "start",
        "stock",
        "stocks",
        "stop",
        "strategy",
        "strong",
        "such",
        "sun",
        "sure",
        "take",
        "tech",
        "than",
        "that",
        "the",
        "then",
        "they",
        "this",
        "time",
        "today",
        "top",
        "trade",
        "trend",
        "true",
        "two",
        "up",
        "value",
        "very",
        "view",
        "want",
        "watch",
        "way",
        "well",
        "what",
        "when",
        "which",
        "who",
        "why",
        "will",
        "win",
        "with",
        "work",
        "world",
        "year",
        "yes",
        "yield",
        "you",
        "your",
    ]
)


def find_in_text(ctx: Any, text: str) -> list[InstrumentRef]:
    """Every stock mentioned in free text (tickers and company names), for the router.
    Stocks in no index that you don't use count only as an exact capital ticker ("PLTR")."""
    known, matcher = _known(ctx)
    ids = matcher.find(text)
    ids.update(_lower_matcher(ctx, known).find(text.lower()))
    rare = {k.inst.symbol: k.inst.id for k in known if k.rare}
    for word in re.findall(r"(?<![\w&])[A-Z][A-Z0-9&-]{1,11}(?![\w&])", text):
        if word in rare:
            ids.add(rare[word])
    order = {k.inst.id: k.inst for k in known}
    return [
        order[i]
        for i in sorted(ids, key=lambda i: text.lower().find(order[i].symbol.lower()) % 10_000)
    ]


_LOWER: dict[int, tuple[int, relevance.Matcher]] = {}


def _lower_matcher(ctx: Any, known: list[Known]) -> relevance.Matcher:
    """Lower-case names and tickers ("reliance", "aapl") of the commonly named stocks. A word
    that is one stock's ticker isn't also another company's name ("reliance" is RELIANCE, not
    Reliance Steel), and everyday words never count."""
    hit = _LOWER.get(id(ctx))
    if hit is not None and hit[0] == id(known):
        return hit[1]
    common = [k for k in known if not k.rare]
    by_symbol = {k.inst.symbol.lower(): k.inst.id for k in common}
    # "apple" is Apple Inc (its whole name), not Apple Hospitality (only its first word).
    by_name = {k.names[0]: k.inst.id for k in common if k.names}
    targets = []
    for k in common:
        terms = []
        sym = k.inst.symbol.lower()
        if len(sym) >= 3 and sym not in EVERYDAY:
            terms.append(sym)
        for n in k.names:
            if len(n) < 4 or n in EVERYDAY or not _own(k, n, by_symbol, by_name):
                continue
            terms.append(n)
        if terms:
            targets.append(relevance.Target(k.inst.id, "", tuple(dict.fromkeys(terms))))
    matcher = relevance.Matcher(targets)
    _LOWER[id(ctx)] = (id(known), matcher)
    return matcher


# ---------------------------------------------------------------- strategies & templates

TEMPLATE_WORDS: dict[str, tuple[str, ...]] = {
    "ma_crossover": (
        "moving average",
        "ma crossover",
        "crossover",
        "golden cross",
        "sma",
        "ema cross",
    ),
    "rsi_mean_reversion": ("rsi", "mean reversion", "oversold"),
    "bollinger_reversion": ("bollinger",),
    "donchian_breakout": ("donchian", "channel breakout", "turtle"),
    "supertrend": ("supertrend", "super trend"),
    "opening_range_breakout": ("opening range", "orb"),
    "macd_momentum": ("macd",),
    "high_52w_momentum": ("52-week", "52 week", "52w"),
}


KAIROS_WORDS = re.compile(
    r"\bkairos\b|\byour(self| own (rules|brain|strategy|signals))\b|\byour brain\b|"
    r"\bwould you have\b"
)


def means_kairos(text: str | None) -> bool:
    """True when the user means Kairos's own brain as the strategy ("backtest yourself")."""
    return bool(text) and KAIROS_WORDS.search(str(text).lower()) is not None


def template_key(text: str | None) -> str | None:
    if not text:
        return None
    t = text.strip().lower().replace("-", "_")
    if t in templates.TEMPLATES:
        return t
    for key, tpl in templates.TEMPLATES.items():
        if tpl.name.lower() in text.lower():
            return key
    low = text.lower()
    for key, words in TEMPLATE_WORDS.items():
        if any(w in low for w in words):
            return key
    return None


@dataclass(frozen=True)
class StrategyRef:
    strategy_id: int
    version_id: int
    name: str
    market: Market
    timeframe: str
    symbols: tuple[str, ...]


def strategy(ctx: Any, text: str | int | None, *, latest_id: int | None = None) -> StrategyRef:
    """A saved strategy by id, exact or close name; "latest"/"it" → the one in use."""
    with ctx.db.session() as s:
        rows = s.scalars(
            select(Strategy)
            .where(Strategy.archived_at.is_(None))
            .order_by(Strategy.updated_at.desc())
        ).all()
        if not rows:
            raise NotFound(
                "There are no saved strategies yet.",
                "Create one from a template or describe an idea.",
            )
        pick: Strategy | None = None
        if isinstance(text, int) or (isinstance(text, str) and text.strip().isdigit()):
            pick = next((r for r in rows if r.id == int(text)), None)
        elif not text or str(text).strip().lower() in (
            "latest",
            "it",
            "this",
            "that",
            "last",
            "the strategy",
        ):
            pick = next((r for r in rows if r.id == latest_id), rows[0])
        else:
            want = str(text).strip().lower()
            pick = next((r for r in rows if r.name.lower() == want), None)
            if pick is None:
                pick = next((r for r in rows if want in r.name.lower()), None)
            if pick is None:
                close = difflib.get_close_matches(
                    want, [r.name.lower() for r in rows], n=1, cutoff=0.6
                )
                pick = next((r for r in rows if close and r.name.lower() == close[0]), None)
            if pick is None:
                key = template_key(want)
                pick = next((r for r in rows if key and r.template_key == key), None)
        if pick is None:
            names = ", ".join(r.name for r in rows[:6])
            raise NotFound(
                f"I couldn't find a strategy called “{text}”.", f"Saved strategies: {names}."
            )
        v = strategy_service.latest_version(s, pick.id)
        assert v is not None
        d = v.definition
        return StrategyRef(
            pick.id, v.id, pick.name, Market(d.market), d.timeframe, tuple(d.universe.symbols)
        )


# ---------------------------------------------------------------- periods


def period(
    now_ms: int, years: float | None = None, start: str | None = None, end: str | None = None
) -> tuple[int | None, int | None]:
    """(start, end) in UTC ms from "years back" or ISO dates; None means Agora's default."""

    def day(text: str) -> int:
        d = date.fromisoformat(text.strip()[:10])
        return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)

    try:
        lo = day(start) if start else None
        hi = day(end) if end else None
    except ValueError as exc:
        raise AgoraError(
            "BAD_DATE", "I couldn't read that date.", "Use a date like 2021-01-31.", status=422
        ) from exc
    if lo is None and years:
        lo = (hi or now_ms) - int(float(years) * 365.25 * DAY_MS)
    return lo, hi
