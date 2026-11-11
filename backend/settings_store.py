"""App settings: defaults, one-line explanations, validation, and storage.

Every setting has a sensible default and a plain-English explanation (CLAUDE.md §5).
Only the values the user changed are stored in the ``settings`` table, so improving a
default in a later version reaches users who never touched it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import Clock
from backend.db.engine import Database
from backend.db.models import SettingRow
from backend.errors import AgoraError

Validator = Callable[[Any], str | None]  # returns a plain-English problem, or None


@dataclass(frozen=True)
class SettingSpec:
    default: Any
    description: str
    validate: Validator


def _one_of(*options: str) -> Validator:
    return lambda v: None if v in options else f"must be one of: {', '.join(options)}"


def _bool(v: Any) -> str | None:
    return None if isinstance(v, bool) else "must be on or off"


def _text(v: Any) -> str | None:
    return None if isinstance(v, str) and v.strip() else "can't be empty"


def _short_text(v: Any) -> str | None:
    """Optional free text (may be empty), e.g. what Metis should look into."""
    return None if isinstance(v, str) and len(v) <= 500 else "must be at most 500 characters"


def _money(v: Any) -> str | None:
    ok = isinstance(v, int | float) and not isinstance(v, bool) and 0 < v <= 1e12
    return None if ok else "must be a positive amount"


def _square_off(v: Any) -> str | None:
    if not isinstance(v, str) or not re.fullmatch(r"\d{2}:\d{2}", v):
        return "must be a time like 15:20"
    hh, mm = int(v[:2]), int(v[3:])
    minutes = hh * 60 + mm
    if mm > 59 or not (9 * 60 + 15 < minutes < 15 * 60 + 30):
        return "must be during market hours and before 15:30"
    return None


def _markets(v: Any) -> str | None:
    ok = isinstance(v, list) and v and all(m in ("IN", "US") for m in v) and len(set(v)) == len(v)
    return None if ok else "must list IN, US or both"


def _ctx_size(v: Any) -> str | None:
    from backend.ai.reading import AUTO, SIZES

    ok = isinstance(v, int) and not isinstance(v, bool) and (v == AUTO or v in SIZES)
    return None if ok else "must be Automatic (0) or one of " + ", ".join(map(str, SIZES))


def _ctx_fit(v: Any) -> str | None:
    from backend.ai.reading import SIZES

    ok = isinstance(v, int) and not isinstance(v, bool) and v in SIZES
    return None if ok else "must be one of " + ", ".join(map(str, SIZES))


def _number(lo: float, hi: float, *, whole: bool = False) -> Validator:
    def check(v: Any) -> str | None:
        ok = isinstance(v, int | float) and not isinstance(v, bool) and lo <= v <= hi
        if ok and whole and v != int(v):
            ok = False
        kind = "a whole number" if whole else "a number"
        return None if ok else f"must be {kind} from {lo:g} to {hi:g}"

    return check


def _pct(v: Any) -> str | None:
    ok = isinstance(v, int | float) and not isinstance(v, bool) and 0 < v <= 100
    return None if ok else "must be a percentage between 0 and 100"


SETTINGS: dict[str, SettingSpec] = {
    "theme": SettingSpec(
        "light", "Light or dark colors for the whole app.", _one_of("light", "dark", "system")
    ),
    "markets": SettingSpec(
        ["IN", "US"], "Which markets you use: India (Nifty 50), the US, or both.", _markets
    ),
    "ai.enabled": SettingSpec(
        True, "Turn the optional AI helper on or off. Agora works fully without it.", _bool
    ),
    "ai.model": SettingSpec("qwen3.5:4b", "Which AI model the helper uses on your laptop.", _text),
    "ai.num_ctx": SettingSpec(
        0,
        "How much text the AI helper reads at once. Automatic picks the most your graphics "
        "card holds (up to 32,768); bigger lets Metis read all its evidence.",
        _ctx_size,
    ),
    "ai.ctx_fit": SettingSpec(
        32768,
        "The biggest reading size that fit your graphics card (Agora finds it on Automatic).",
        _ctx_fit,
    ),
    "ai.base_url": SettingSpec(
        "http://localhost:11434", "Where Agora finds Ollama on your laptop.", _text
    ),
    "ai.fix_gpu": SettingSpec(
        True,
        "If Ollama started without the graphics card (so answers are slow), Agora restarts "
        "Ollama for you once nothing is using the AI.",
        _bool,
    ),
    "default_capital.IN": SettingSpec(
        1_000_000, "Starting money for new India backtests and paper accounts (₹).", _money
    ),
    "default_capital.US": SettingSpec(
        100_000, "Starting money for new US backtests and paper accounts ($).", _money
    ),
    "intraday_square_off_time": SettingSpec(
        "15:20", "When open India intraday trades are closed automatically (IST).", _square_off
    ),
    "volume_cap_pct": SettingSpec(
        5, "Largest order allowed, as a % of a candle's volume, so fills stay realistic.", _pct
    ),
    "intraday.accumulate": SettingSpec(
        True,
        "While Agora is open, save each day's intraday candles so short-timeframe history "
        "keeps growing beyond what Yahoo keeps.",
        _bool,
    ),
    "kairos.enabled": SettingSpec(
        True,
        "Show Kairos, the trading agent: the chat panel, the chart switch and the desk.",
        _bool,
    ),
    "kairos.think": SettingSpec(
        True,
        "Let Kairos think before it answers. Answers are better but take a few seconds longer.",
        _bool,
    ),
    "kairos.follow": SettingSpec(
        True,
        "Let Kairos move the app to the screen it's talking about (a chart, a backtest, a "
        "paper session).",
        _bool,
    ),
    "kairos.risk_pct": SettingSpec(
        1.0,
        "How much of the Kairos desk's paper money one trade may lose if its stop is hit (%).",
        _number(0.1, 5),
    ),
    "kairos.max_positions": SettingSpec(
        # ten trades of a tenth each, so a full desk still spreads over ten stocks (D-136)
        10,
        "The most trades the Kairos desk keeps open at once; each gets an equal share of the "
        "money.",
        _number(1, 20, whole=True),
    ),
    "kairos.trials": SettingSpec(
        # a ceiling, not a quota: Kairos tries only the ones it thinks work (D-139)
        3,
        "At most how many of Metis's strategies Kairos tries at once in each market, each with "
        "its own small paper money; it tries only the ones it thinks work (0 = none).",
        _number(0, 6, whole=True),
    ),
    "kairos.daily_loss_pct": SettingSpec(
        3.0,
        "The Kairos desk stops opening trades for the day after losing this much (%).",
        _number(0.5, 20),
    ),
    "kairos.entry_score": SettingSpec(
        40,
        "How convinced Kairos must be (score out of 100) before its desk opens a trade.",
        _number(20, 80, whole=True),
    ),
    "kairos.auto_exits": SettingSpec(
        True,
        "Kairos chooses its own stop-loss, target, trailing stop and partial profit from what has "
        "worked in its record; off, it uses the numbers below.",
        _bool,
    ),
    "kairos.judge": SettingSpec(
        True,
        "Kairos's trade judge may pass on an entry that, in its tested record, tends to lose. It "
        "switches itself on only after it proved itself on past trades it never learned from.",
        _bool,
    ),
    "kairos.trail_atr": SettingSpec(
        3.0,
        "Kairos's desk trails a stop this many ATRs (the stock's typical daily move) behind the "
        "best price since each trade opened, so winners keep most of their gain. 0 turns it off.",
        _number(0, 8),
    ),
    "kairos.partial_r": SettingSpec(
        1.0,
        "Kairos's desk sells half of each trade once it has made as much as it risked (1 = one "
        "times the risk), then moves the stop to the entry price so the rest can't lose. "
        "0 turns it off.",
        _number(0, 5),
    ),
    "kairos.bigger_chart": SettingSpec(
        True,
        "Let Kairos's desk trade only with the trend of the bigger chart (the weekly chart for "
        "a daily desk, the daily chart for an hourly one): fewer trades, fewer false alarms.",
        _bool,
    ),
    "kairos.smaller_chart": SettingSpec(
        True,
        "Before a desk buys, Kairos looks at the smaller chart (hourly for the daily desk, "
        "5-minute for the hourly and 15-minute desks) and passes if it has turned against "
        "the trade.",
        _bool,
    ),
    "news.enabled": SettingSpec(
        True,
        "Let Kairos read public business and world news (Economic Times, Mint, BBC, Al "
        "Jazeera, the Guardian, NYT, WSJ, Google News, GDELT, the Fed and the RBI) while "
        "Agora is open. No account needed.",
        _bool,
    ),
    "research.enabled": SettingSpec(
        True,
        "Let Kairos and Metis search the web (DuckDuckGo and Wikipedia) and read public pages "
        "to research questions and strategies. Only the search words leave your laptop.",
        _bool,
    ),
    "kairos.news_guard": SettingSpec(
        "protective",
        "How Kairos's desk reacts to market-moving news (news is caution, never a stop). "
        "Protective: readier to buy where the news helps a stock's sector; half-size trades "
        "where it hurts or market risk is high; cut losing trades once prices confirm; leave a "
        "stock on red-flag company news. Cautious: the same sizes, but never closes a trade. "
        "Off: ignore the news.",
        _one_of("protective", "cautious", "off"),
    ),
    "kairos.trade_check": SettingSpec(
        "balanced",
        "How picky Kairos's desk is about each trade. Balanced: skip trades that look clearly "
        "worse than usual. Strict: only good-chance trades (higher win rate, fewer trades). "
        "Learn: never skip, just learn. Off: don't check.",
        _one_of("balanced", "strict", "learn", "off"),
    ),
    "kairos.keep_learning": SettingSpec(
        True,
        "While Agora is open, let Kairos keep studying on its own: review finished backtests "
        "and paper trades, check its price predictions against what happened, and learn "
        "from both. Stops when Agora closes.",
        _bool,
    ),
    "kairos.auto_improve": SettingSpec(
        True,
        "Let Kairos save improved versions of your visual strategies when a filter it found "
        "held up on trades it hadn't seen. Your earlier versions are always kept.",
        _bool,
    ),
    "autopilot": SettingSpec(
        True,
        "When Agora opens, Kairos and Metis start working on their own: Kairos keeps prices up "
        "to date, picks its own stocks and runs its paper-trading desks; Metis researches. "
        "Paper money only, and nothing runs while Agora is closed.",
        _bool,
    ),
    "autopilot.intraday_desk": SettingSpec(
        "all",
        "Besides its daily desk, Kairos runs paper desks on shorter timeframes in each market "
        "(they trade only during market hours). All: hourly and 15-minute desks. Off: daily "
        "desks only.",
        _one_of("off", "all", "1h", "15m"),
    ),
    "metis.enabled": SettingSpec(
        True,
        "Let Metis, Kairos's AI researcher, keep researching on its own while Agora is open: "
        "it thinks up ideas to make your strategies better, tests each one on years it never "
        "saw, and keeps only what holds up. Needs the AI helper; uses your graphics card.",
        _bool,
    ),
    "metis.every_minutes": SettingSpec(
        1,
        "Minutes Metis rests between rounds of research while Agora is open. 1 means it works "
        "all the time (each round uses the graphics card for a few minutes).",
        _number(1, 240, whole=True),
    ),
    "metis.own_ideas": SettingSpec(
        True,
        "Let Metis ask the AI helper for its own ideas. Off: Metis keeps researching with code "
        "only (the playbook, the scanner, its checks), for example while Claude writes its "
        "ideas in a laptop session; the graphics card stays free and cool.",
        _bool,
    ),
    "metis.apply": SettingSpec(
        True,
        "Let Metis save the ideas that held up: as a new version of your strategy (earlier "
        'versions are kept) or as a new strategy named "Metis · …".',
        _bool,
    ),
    "metis.focus": SettingSpec(
        "",
        'Optional: what Metis should look into, in your own words (for example "my breakout '
        'strategy loses too often"). Leave it empty and Metis chooses.',
        _short_text,
    ),
    "metis.new_per_day": SettingSpec(
        5,
        "How many genuinely new strategies Metis may add on its own each day. Improvements to "
        "your strategies are always saved as new versions, never as copies.",
        _number(0, 20, whole=True),
    ),
    "revisions.auto_undo": SettingSpec(
        True,
        "When a version Kairos or Metis saved does clearly worse than the version before it on "
        "the candles formed since, put the earlier version back on its own (saved as a new "
        "version, so nothing is lost).",
        _bool,
    ),
    "portfolio.manage": SettingSpec(
        True,
        "While a portfolio is paper trading, let Kairos and Metis review it each month: retire "
        "sleeves that stopped working and add new opportunities that pass the tests.",
        _bool,
    ),
    "onboarding_done": SettingSpec(
        False, "Whether the first-launch tour has been completed.", _bool
    ),
}


def describe() -> dict[str, dict[str, Any]]:
    return {k: {"default": s.default, "description": s.description} for k, s in SETTINGS.items()}


def read_all(session: Session) -> dict[str, Any]:
    values = {k: s.default for k, s in SETTINGS.items()}
    for row in session.scalars(select(SettingRow)):
        if row.key in SETTINGS:
            values[row.key] = json.loads(row.value)
    return values


def read_setting(db: Database, key: str) -> Any:
    with db.session() as s:
        return read_all(s)[key]


def update(session: Session, changes: Mapping[str, Any], clock: Clock) -> dict[str, Any]:
    """Validate every change first, then store them all (all-or-nothing)."""
    problems = []
    for key, value in changes.items():
        spec = SETTINGS.get(key)
        if spec is None:
            problems.append(f"'{key}' is not a setting Agora knows about")
            continue
        issue = spec.validate(value)
        if issue:
            problems.append(f"{key} {issue}")
    if problems:
        raise AgoraError(
            "INVALID_SETTING",
            "One or more settings couldn't be saved.",
            "Fix the highlighted values and save again.",
            detail="; ".join(problems),
            status=422,
        )
    now = clock.now_ms()
    for key, value in changes.items():
        row = session.get(SettingRow, key)
        if row is None:
            session.add(SettingRow(key=key, value=json.dumps(value), updated_at=now))
        else:
            row.value = json.dumps(value)
            row.updated_at = now
    session.flush()
    return read_all(session)
