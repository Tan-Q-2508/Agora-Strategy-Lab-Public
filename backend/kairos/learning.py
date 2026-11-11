"""Kairos's training and learning (KAIROS §8, D-61).

**Training** ("study the history"): for every signal in ``backend/analysis/signals.py``,
find each time it fired in the stored history of the market's stocks and measure what
happened ``horizon`` candles later: how often the price moved the signal's way, and by how
much on average. The same count over *every* candle is the base rate ("any day"), so a
signal is only interesting when it beats it. Results are rows in ``kairos_signal_stats``
(source ``history``).

**Learning**: each closed Kairos desk trade updates the rows of the signals that were in
play when it opened (source ``paper``), counted 3× because it's live experience.

**Weights**: for each signal, a Beta posterior on "the move went the signal's way", started
at the base rate with 20 pseudo-trades of weight (so thin evidence barely moves it), then
updated by history and paper results. The weight multiplies the signal's say in the brain's
score: ×1 at the base rate, ×2 at 5 points better, ×0 at 5 points worse. A signal can be
switched off by its record but never flipped, because a flipped signal is usually noise.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import threading
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy import delete, select

from backend.analysis import signals as sig
from backend.analysis.service import HORIZON
from backend.core.types import Market, Timeframe
from backend.data.store import InstrumentRef
from backend.db.models import KairosSignalStat
from backend.indicators.series import BarSeries, from_bars
from backend.kairos import exits, judge
from backend.logging_setup import get_logger
from backend.settings_store import read_all

log = get_logger("kairos.learning")
STUDY_PICKS = 60  # the picks a study reads besides its study list (D-177)

PRIOR = 20.0  # pseudo-trades at the base rate
PAPER_WEIGHT = 3.0  # one paper trade counts as much as three historical signals
FULL_EDGE = 0.05  # an edge this big doubles a signal's weight (and −5 points switches it off)
MIN_CANDLES = 250  # a stock needs this much history to be studied
RETRAIN_GROWTH = 0.05  # retrain when the data has grown this much
BASE_UP = "base:up"
BASE_DOWN = "base:down"
# Which list of signals the history was studied with: a study made before new signals were
# added (D-138) is redone so they get a record too.
SIGNALS_KEY = "base:signals"
SIGNALS_VERSION = 4  # 3: the exit plans are studied too (D-140); 4: the trade judge (D-145)
REGIMES = {"regime:uptrend": 1, "regime:downtrend": -1}

FAMILY_WORDS = {
    "pattern": "chart pattern",
    "candle": "candlestick",
    "divergence": "divergence",
    "level": "support/resistance",
    "line": "trendline",
    "momentum": "momentum",
    "volume": "volume",
    "trend": "trend",
    "regime": "trend",
    "setup": "setup",
    "strategy": "strategy",
    "quant": "quant",
}


# ---------------------------------------------------------------- the maths (hand-tested)


def posterior(base: float, wins: float, n: float, prior: float = PRIOR) -> float:
    """Posterior mean of a Beta(prior·base, prior·(1−base)) after ``wins`` of ``n``."""
    return (prior * base + wins) / (prior + n)


def multiplier(edge: float) -> float:
    """A signal's weight from its edge over the base rate: 1 + edge/5 points, in 0 … 2."""
    return float(min(2.0, max(0.0, 1.0 + edge / FULL_EDGE)))


@dataclass
class Tally:
    n: float = 0.0
    wins: float = 0.0
    sum_ret: float = 0.0
    sum_ret2: float = 0.0

    def add(self, ret: float, weight: float = 1.0) -> None:
        self.n += weight
        self.wins += weight * (1.0 if ret > 0 else 0.0)
        self.sum_ret += weight * ret
        self.sum_ret2 += weight * ret * ret


def tally_series(ss: sig.SignalSet, horizon: int) -> dict[str, Tally]:
    """Outcomes of every signal in one stock's history, plus its base rates.

    Returns are measured close-to-close from the signal's candle to ``horizon`` candles
    later, signed so a move the signal's way is positive. Trend regimes are sampled every
    ``horizon`` candles (consecutive candles of one trend aren't independent evidence)."""
    out: dict[str, Tally] = defaultdict(Tally)
    c = ss.close
    n = ss.n
    if n <= horizon + 1:
        return dict(out)
    fwd = np.full(n, np.nan)
    fwd[: n - horizon] = c[horizon:] / c[: n - horizon] - 1.0
    for e in ss.events:
        r = fwd[e.index]
        if np.isfinite(r):
            out[e.key].add(e.direction * float(r))
    start = min(200, n // 4)  # skip the warm-up of the 200-candle average
    for i in range(start, n - horizon, horizon):
        r = float(fwd[i])
        if not math.isfinite(r):
            continue
        out[BASE_UP].add(r)
        out[BASE_DOWN].add(-r)
        t = ss.trend[i]
        if t >= 25:
            out["regime:uptrend"].add(r)
        elif t <= -25:
            out["regime:downtrend"].add(-r)
    return dict(out)


def direction_of(key: str) -> int:
    """+1 for bullish signals, −1 for bearish ones (from the key alone)."""
    if key in REGIMES:
        return REGIMES[key]
    if key == BASE_DOWN:
        return -1
    if key.startswith("candle:"):
        from backend.analysis.candles import INFO

        info = INFO.get(key.split(":", 1)[1])
        return -1 if info is not None and info.bias == "bearish" else 1
    if key.startswith("divergence:"):
        return 1 if key.endswith("bullish") else -1
    if key in sig.DIRECTION:
        return sig.DIRECTION[key]
    return -1 if key.endswith(":down") else 1


def label_of(key: str) -> str:
    """Plain words for a signal key, for the "What Kairos learned" card."""
    if key in sig.LABELS:
        return sig.LABELS[key]
    family, _, rest = key.partition(":")
    if family == "pattern":
        from backend.analysis.chart_patterns import NAMES

        name, _, way = rest.rpartition(":")
        word = NAMES.get(name, (name.replace("_", " ").capitalize(), ""))[0]
        return f"{word} {'breakout' if way == 'up' else 'breakdown'}"
    if family == "candle":
        from backend.analysis.candles import INFO

        info = INFO.get(rest)
        return info.name if info else rest.replace("_", " ").capitalize()
    if family == "divergence":
        from backend.analysis.divergence import LABELS

        return LABELS.get(rest, rest.replace("_", " "))
    if key == "regime:uptrend":
        return "Being in an uptrend"
    if key == "regime:downtrend":
        return "Being in a downtrend"
    return key


# ---------------------------------------------------------------- the service


@dataclass(frozen=True)
class SignalRecord:
    key: str
    direction: int
    history: Tally
    paper: Tally
    base: float  # chance of a move this way on any candle
    horizon: int

    @property
    def hit_rate(self) -> float:
        return self.history.wins / self.history.n if self.history.n else float("nan")

    @property
    def posterior(self) -> float:
        n = self.history.n + PAPER_WEIGHT * self.paper.n
        wins = self.history.wins + PAPER_WEIGHT * self.paper.wins
        return posterior(self.base, wins, n)

    @property
    def edge(self) -> float:
        return self.posterior - self.base

    @property
    def weight(self) -> float:
        return multiplier(self.edge)


# Kairos's study processes running at once (D-164): enough to finish ten timeframes in well
# under an hour, few enough that a laptop's processor stays cool.
MAX_STUDIES = 2
STUDY_SLOTS = threading.BoundedSemaphore(MAX_STUDIES)


def _python() -> str:
    """The interpreter for a child study: the console one beside a windowless ``pythonw``
    (whose output can't be read); the child is started without a window."""
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        console = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(console):
            return console
    return exe


class LearningService:
    """Training jobs, the stats behind every "worked 58% of 412 times", and the weights."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.auto = True  # start training on first use (tests switch this off)
        self._lock = threading.Lock()
        self._running: dict[tuple[str, str], str] = {}  # (market, tf) → job id
        self._cache: dict[tuple[str, str], dict[str, SignalRecord]] = {}
        # Goes up whenever what Kairos learned changes (a closed desk trade, a new study), so
        # live desks take the new weights at once instead of the next day (D-138).
        self.version = 0
        self._judges: dict[tuple[str, str], judge.Model | None] = {}
        # Studies run in a child process in the app (D-148); tests study in-process.
        self.separate = False
        self.study_command: list[str] = [_python(), "-m", "backend.kairos.study"]

    # ------------------------------------------------------------ reading

    def records(self, market: Market, tf: Timeframe) -> dict[str, SignalRecord]:
        key = (market.value, tf.value)
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            return hit
        with self.ctx.db.session() as s:
            rows = list(
                s.scalars(
                    select(KairosSignalStat).where(
                        KairosSignalStat.market_code == market.value,
                        KairosSignalStat.timeframe == tf.value,
                    )
                )
            )
        hist: dict[str, Tally] = {}
        paper: dict[str, Tally] = {}
        horizon = HORIZON[tf.value]
        for r in rows:
            t = Tally(float(r.n), r.wins, r.sum_ret, r.sum_ret2)
            (hist if r.source == "history" else paper)[r.signal] = t
            if r.source == "history":
                horizon = r.horizon
        up = hist.get(BASE_UP)
        base_up = up.wins / up.n if up and up.n else 0.5
        down = hist.get(BASE_DOWN)
        base_down = down.wins / down.n if down and down.n else 0.5
        out: dict[str, SignalRecord] = {}
        for k in set(hist) | set(paper):
            if k.startswith(("base:", "exit:")):
                continue
            d = direction_of(k)
            out[k] = SignalRecord(
                k,
                d,
                hist.get(k, Tally()),
                paper.get(k, Tally()),
                base_up if d > 0 else base_down,
                horizon,
            )
        with self._lock:
            self._cache[key] = out
        return out

    def trained(self, market: Market, tf: Timeframe) -> dict[str, Any] | None:
        """When the history was last studied, on how much data (None if never)."""
        with self.ctx.db.session() as s:
            row = s.scalars(
                select(KairosSignalStat).where(
                    KairosSignalStat.market_code == market.value,
                    KairosSignalStat.timeframe == tf.value,
                    KairosSignalStat.signal == BASE_UP,
                    KairosSignalStat.source == "history",
                )
            ).first()
            if row is None:
                return None
            return {
                "at": row.updated_at,
                "candles": row.base_n,
                "samples": row.n,
                "base_rate": round(row.wins / row.n, 4) if row.n else None,
                "horizon": row.horizon,
            }

    def lookup(self, market: Market, tf: Timeframe) -> Callable[[str], Mapping[str, Any] | None]:
        """For the chart report: ``"pattern:bull_flag:up"`` → its record in plain numbers."""
        recs = self.records(market, tf)

        def find(key: str) -> Mapping[str, Any] | None:
            r = recs.get(key)
            if r is None or r.history.n < 1:
                return None
            return {
                "n": int(r.history.n),
                "hit_rate": round(r.hit_rate, 4),
                "avg_return_pct": round(100.0 * r.history.sum_ret / r.history.n, 2),
                "base_rate": round(r.base, 4),
                "horizon": r.horizon,
                "paper_n": int(r.paper.n),
                "weight": round(r.weight, 2),
            }

        return find

    def weights(self, market: Market, tf: Timeframe) -> dict[str, float]:
        """Signal → weight (0 … 2) for the brain; signals never seen weigh 1."""
        return {k: round(r.weight, 3) for k, r in sorted(self.records(market, tf).items())}

    # ------------------------------------------------------------ training

    def needs_training(self, market: Market, tf: Timeframe) -> bool:
        info = self.trained(market, tf)
        if info is None or self._signals_version(market, tf) < SIGNALS_VERSION:
            return True
        grown: bool = self._candles(market, tf) > (1.0 + RETRAIN_GROWTH) * max(1, info["candles"])
        return grown

    def _signals_version(self, market: Market, tf: Timeframe) -> int:
        with self.ctx.db.session() as s:
            n = s.scalar(
                select(KairosSignalStat.n).where(
                    KairosSignalStat.market_code == market.value,
                    KairosSignalStat.timeframe == tf.value,
                    KairosSignalStat.signal == SIGNALS_KEY,
                    KairosSignalStat.source == "history",
                )
            )
        return int(n or 1)

    def ensure_trained(self, market: Market, tf: Timeframe) -> str | None:
        """Start a training job if there is none yet or the data grew 5%+. Returns the job
        id (an already running one if any), or None when the stats are current."""
        key = (market.value, tf.value)
        with self._lock:
            jid = self._running.get(key)
        if jid is not None:
            job = self.ctx.jobs.get(jid)
            if job is not None and job.status in ("queued", "running"):
                return jid
        if not self.needs_training(market, tf):
            return None
        return self.start_training(market, tf)

    def start_training(self, market: Market, tf: Timeframe) -> str:
        what = "Indian" if market is Market.IN else "US"
        job = self.ctx.jobs.submit(
            "kairos_train",
            f"Kairos is studying {what} {tf.value} history",
            lambda jc: (
                self.train_separately(market, tf, jc.progress, jc.check)
                if self.separate
                else self.train(market, tf, jc.progress, jc.check)
            ),
            key=f"{market}:{tf.value}",
            single=True,
        )
        with self._lock:
            self._running[(market.value, tf.value)] = job.id
        return str(job.id)

    def train_separately(
        self,
        market: Market,
        tf: Timeframe,
        progress: Callable[[float, str], None] | None = None,
        check: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """The same study in a child process (``backend.kairos.study``), so studies of
        several timeframes use several cores instead of sharing one (D-148). The child writes
        the numbers and the judge; this process then forgets what it had cached."""
        from backend.kairos import study

        # At most MAX_STUDIES at once, below normal priority (D-164): ten studies on every core
        # ran the user's laptop CPU to 95 °C, which switched its Wi-Fi card off.
        if not STUDY_SLOTS.acquire(blocking=False):
            if progress is not None:
                progress(0.0, "Waiting for a free study slot…")
            while not STUDY_SLOTS.acquire(timeout=1.0):
                if check is not None:
                    check()
        try:
            return self._run_study(market, tf, study, progress, check)
        finally:
            STUDY_SLOTS.release()

    def _run_study(
        self,
        market: Market,
        tf: Timeframe,
        study: Any,
        progress: Callable[[float, str], None] | None,
        check: Callable[[], None] | None,
    ) -> dict[str, Any]:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0
        )
        proc = subprocess.Popen(
            [*self.study_command, market.value, tf.value],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
            # Windows pipes default to the old code page; stock names and "…" need UTF-8
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        result: dict[str, Any] = {}
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if check is not None:
                    check()
                if line.startswith(study.PROGRESS + " ") and progress is not None:
                    _tag, pct, text = [*line.rstrip().split(" ", 2), ""][:3]
                    progress(float(pct), text)
                elif line.startswith(study.RESULT + " "):
                    result = json.loads(line[len(study.RESULT) + 1 :])
            err = proc.stderr.read() if proc.stderr is not None else ""
            code = proc.wait()
        except BaseException:
            proc.kill()
            raise
        if code != 0:
            raise RuntimeError(f"The study stopped (code {code}): {err.strip()[-800:]}")
        self._forget(market, tf)
        with self._lock:
            self._judges.pop((market.value, tf.value), None)
        return result

    def _instruments(self, market: Market) -> list[InstrumentRef]:
        """The market's study list plus the stocks Kairos's desks trade (its picks), so the
        record is measured on the stocks it actually trades too."""
        from backend.kairos import picks, resolve

        out = {i.id: i for i in resolve.universe(self.ctx, market)}
        try:
            found = self.ctx.watchlists.find(f"Kairos · {picks.NAME[market.value]}", market.value)
            if found is not None:
                # the strongest of the picks only (D-177): all 250 would make each study
                # several times slower on a laptop that overheats
                for i in self.ctx.watchlists.instruments(found["id"])[:STUDY_PICKS]:
                    out.setdefault(i.id, i)
        except Exception:  # no picks yet (or no watchlists in a test): the study list alone
            log.debug("No Kairos picks to study", exc_info=True)
        return list(out.values())

    def _candles(self, market: Market, tf: Timeframe) -> int:
        from sqlalchemy import func

        from backend.db.models import Candle

        ids = [i.id for i in self._instruments(market)]
        if not ids:
            return 0
        with self.ctx.db.session() as s:
            return int(
                s.scalar(
                    select(func.count())
                    .select_from(Candle)
                    .where(Candle.instrument_id.in_(ids), Candle.timeframe == tf.value)
                )
                or 0
            )

    def series(self, inst: InstrumentRef, tf: Timeframe) -> BarSeries | None:
        now = self.ctx.clock.now_ms()
        bars = self.ctx.cache.bars(inst, tf, 0, now + 1, adjusted_prices=True)
        if len(bars) < MIN_CANDLES:
            return None
        return from_bars(bars, tf, inst.market)

    def train(
        self,
        market: Market,
        tf: Timeframe,
        progress: Callable[[float, str], None] | None = None,
        check: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        horizon = HORIZON[tf.value]
        totals: dict[str, Tally] = defaultdict(Tally)
        insts = self._instruments(market)
        study = self._exit_study(market, tf)
        candles = 0
        studied = 0
        lessons: list[judge.Lesson] = []
        for k, inst in enumerate(insts):
            if check is not None:
                check()
            if progress is not None:
                progress(100.0 * k / max(1, len(insts)), f"Studying {inst.symbol}…")
            s = self.series(inst, tf)
            if s is None:
                continue
            ss = sig.compute(s)
            for key, t in tally_series(ss, horizon).items():
                agg = totals[key]
                agg.n += t.n
                agg.wins += t.wins
                agg.sum_ret += t.sum_ret
                agg.sum_ret2 += t.sum_ret2
            # the exit plans on the brain's entries in this history (D-140)
            entries: list[tuple[int, int, Any, float]] = []
            for key, (n, total, total2) in exits.tally(
                s, ss, market.value, collect=entries, **study
            ).items():
                agg = totals[key]
                agg.n += n
                agg.sum_ret += total
                agg.sum_ret2 += total2
            # every entry is a lesson for the trade judge (D-145)
            if entries:
                reader = judge.Reader(s)
                lessons += [
                    judge.Lesson(int(s.ts[i]), reader.at(i, side, d), r)
                    for i, side, d, r in entries
                ]
            candles += len(s)
            studied += 1
        now = self.ctx.clock.now_ms()
        base_up = totals.get(BASE_UP, Tally())
        base_down = totals.get(BASE_DOWN, Tally())
        with self.ctx.db.session() as s:
            s.execute(
                delete(KairosSignalStat).where(
                    KairosSignalStat.market_code == market.value,
                    KairosSignalStat.timeframe == tf.value,
                    KairosSignalStat.source == "history",
                )
            )
            for key, t in sorted(totals.items()):
                base = base_down if direction_of(key) < 0 else base_up
                s.add(
                    KairosSignalStat(
                        market_code=market.value,
                        timeframe=tf.value,
                        signal=key,
                        source="history",
                        horizon=horizon,
                        n=int(t.n),
                        wins=t.wins,
                        sum_ret=t.sum_ret,
                        sum_ret2=t.sum_ret2,
                        base_n=candles if key == BASE_UP else int(base.n),
                        base_wins=base.wins,
                        updated_at=now,
                    )
                )
            s.add(
                KairosSignalStat(
                    market_code=market.value,
                    timeframe=tf.value,
                    signal=SIGNALS_KEY,
                    source="history",
                    horizon=horizon,
                    n=SIGNALS_VERSION,
                    wins=0.0,
                    sum_ret=0.0,
                    sum_ret2=0.0,
                    base_n=0,
                    base_wins=0.0,
                    updated_at=now,
                )
            )
            s.commit()
        self._forget(market, tf)
        self._learn_judge(market, tf, lessons, int(study["max_bars"]))
        signals = len([k for k in totals if not k.startswith(("base:", "exit:"))])
        log.info(
            "Kairos trained on %s %s: %d stocks, %d candles",
            market.value,
            tf.value,
            studied,
            candles,
        )
        if progress is not None:
            progress(100.0, f"Studied {studied} stocks: {signals} kinds of signal measured.")
        return {"stocks": studied, "candles": candles, "signals": signals, "horizon": horizon}

    # ------------------------------------------------------------ learning from paper trades

    def record_trade(
        self,
        market: Market,
        tf: Timeframe,
        signals: list[tuple[str, int]],
        side: int,
        return_pct: float,
    ) -> None:
        """One closed desk trade: every signal in play at entry learns from it. A signal
        that agreed with the trade wins when the trade made money; one that disagreed
        (a bearish candle under a long entry) wins when it lost."""
        if not signals:
            return
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            for key, d in dict(signals).items():
                ret = d * side * return_pct / 100.0
                row = s.scalars(
                    select(KairosSignalStat).where(
                        KairosSignalStat.market_code == market.value,
                        KairosSignalStat.timeframe == tf.value,
                        KairosSignalStat.signal == key,
                        KairosSignalStat.source == "paper",
                    )
                ).first()
                if row is None:
                    row = KairosSignalStat(
                        market_code=market.value,
                        timeframe=tf.value,
                        signal=key,
                        source="paper",
                        horizon=0,
                        n=0,
                        wins=0.0,
                        sum_ret=0.0,
                        sum_ret2=0.0,
                        base_n=0,
                        base_wins=0.0,
                        updated_at=now,
                    )
                    s.add(row)
                row.n += 1
                row.wins += 1.0 if ret > 0 else 0.0
                row.sum_ret += ret
                row.sum_ret2 += ret * ret
                row.updated_at = now
            s.commit()
        self._forget(market, tf)

    # ------------------------------------------------------------ exits (D-140)

    def default_exits(self) -> exits.ExitPlan:
        """The exit plan of the settings (and the brain's default stop and target)."""
        from backend.kairos import brain

        with self.ctx.db.session() as s:
            st = read_all(s)
        stop, target = (float(p.default) for p in brain.PARAMETERS[1:3])
        return exits.ExitPlan(
            stop,
            target,
            float(st["kairos.trail_atr"]) or None,
            float(st["kairos.partial_r"]) or None,
        )

    def _exit_study(self, market: Market, tf: Timeframe) -> dict[str, Any]:
        with self.ctx.db.session() as s:
            st = read_all(s)
        intraday = tf is not Timeframe.D1
        return {
            "weights": self.weights(market, tf),
            "entry": float(st["kairos.entry_score"]),
            "shorts": market is Market.US or intraday,
            "max_bars": 60 if intraday else 30,
            "default": self.default_exits(),
        }

    def exit_plan(self, market: Market, tf: Timeframe) -> dict[str, Any]:
        """The exit plan Kairos uses now, with why (``exits.choose``)."""
        with self.ctx.db.session() as s:
            rows = list(
                s.scalars(
                    select(KairosSignalStat).where(
                        KairosSignalStat.market_code == market.value,
                        KairosSignalStat.timeframe == tf.value,
                        KairosSignalStat.signal.like("exit:%"),
                    )
                )
            )
        hist = {r.signal: (float(r.n), r.sum_ret) for r in rows if r.source == "history"}
        paper = {
            r.signal.removeprefix("exit:paper:"): (float(r.n), r.sum_ret)
            for r in rows
            if r.source == "paper"
        }
        return exits.choose(hist, paper, self.default_exits())

    def record_exits(self, market: Market, tf: Timeframe, results: Mapping[str, float]) -> None:
        """One closed desk trade under every exit plan (plan key → R), counted 3× in choosing."""
        if not results:
            return
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            for key, r in results.items():
                signal = f"exit:paper:{key}"
                row = s.scalars(
                    select(KairosSignalStat).where(
                        KairosSignalStat.market_code == market.value,
                        KairosSignalStat.timeframe == tf.value,
                        KairosSignalStat.signal == signal,
                        KairosSignalStat.source == "paper",
                    )
                ).first()
                if row is None:
                    row = KairosSignalStat(
                        market_code=market.value,
                        timeframe=tf.value,
                        signal=signal,
                        source="paper",
                        horizon=0,
                        n=0,
                        wins=0.0,
                        sum_ret=0.0,
                        sum_ret2=0.0,
                        base_n=0,
                        base_wins=0.0,
                        updated_at=now,
                    )
                    s.add(row)
                row.n += 1
                row.wins += 1.0 if r > 0 else 0.0
                row.sum_ret += r
                row.sum_ret2 += r * r
                row.updated_at = now
            s.commit()
        self._forget(market, tf)

    def _forget(self, market: Market, tf: Timeframe) -> None:
        with self._lock:
            self._cache.pop((market.value, tf.value), None)
            self.version += 1
        analysis = self.ctx.services.get("analysis")
        clear = getattr(analysis, "clear_cache", None)
        if callable(clear):
            clear()

    def lessons_for_prompt(self, question: str) -> str:
        from backend.kairos import memory

        return memory.for_prompt(self.ctx, question)

    # ------------------------------------------------------------ "What Kairos learned"

    def learned(self, market: Market, tf: Timeframe, top: int = 5) -> dict[str, Any]:
        recs = [r for r in self.records(market, tf).values() if r.history.n + r.paper.n >= 10]
        info = self.trained(market, tf)
        where = "Indian" if market is Market.IN else "US"
        h = info["horizon"] if info else HORIZON[tf.value]
        unit = "days" if tf is Timeframe.D1 else "candles"

        def line(r: SignalRecord) -> dict[str, Any]:
            way = "rose" if r.direction > 0 else "fell"
            text = (
                f"{label_of(r.key)} on {where} stocks: {way} {h} {unit} later "
                f"{round(100 * r.hit_rate)}% of {int(r.history.n)} times "
                f"(any {('day' if unit == 'days' else 'candle')}: {round(100 * r.base)}%)."
                if r.history.n
                else f"{label_of(r.key)}: {int(r.paper.n)} paper trades so far."
            )
            if r.paper.n:
                won, n = int(r.paper.wins), int(r.paper.n)
                text += f" In Kairos's own paper trades: {won} of {n} went its way."
            return {
                "key": r.key,
                "label": label_of(r.key),
                "family": FAMILY_WORDS.get(r.key.split(":", 1)[0], "signal"),
                "direction": r.direction,
                "n": int(r.history.n),
                "hit_rate": round(r.hit_rate, 4) if r.history.n else None,
                "base_rate": round(r.base, 4),
                "paper_n": int(r.paper.n),
                "paper_wins": int(r.paper.wins),
                "edge": round(r.edge, 4),
                "weight": round(r.weight, 2),
                "text": text,
            }

        ranked = sorted(recs, key=lambda r: -r.edge)
        best = [line(r) for r in ranked[:top] if r.edge > 0]
        worst = [line(r) for r in reversed(ranked[-top:]) if r.edge < 0]
        paper = [r for r in recs if r.paper.n]
        return {
            "market": market.value,
            "timeframe": tf.value,
            "trained": info,
            "best": best,
            "worst": worst,
            "paper_trades": int(max((r.paper.n for r in paper), default=0)),
            "signals": len(recs),
            "exits": self._exits_card(market, tf),
            "judge": self._judge_card(market, tf),
        }

    # ------------------------------------------------------------ the trade judge (D-145)

    def _learn_judge(
        self, market: Market, tf: Timeframe, lessons: list[judge.Lesson], max_bars: int
    ) -> None:
        bar_ms = 86_400_000 * 1.5 if tf is Timeframe.D1 else tf.minutes * 60_000
        try:
            model = judge.learn(lessons, embargo_ms=int(max_bars * bar_ms))
        except Exception:  # the judge is a bonus: never fail the study for it
            log.exception("The trade judge couldn't learn on %s %s", market.value, tf.value)
            return
        judge.save(self.ctx.paths.data_dir, market.value, tf.value, model)
        self._judges.pop((market.value, tf.value), None)
        log.info("Trade judge %s %s: %s", market.value, tf.value, judge.words(model))

    def trade_judge(self, market: Market, tf: Timeframe) -> judge.Model | None:
        """The trade judge for this market and timeframe, or None (cached)."""
        key = (market.value, tf.value)
        if key not in self._judges:
            self._judges[key] = judge.load(self.ctx.paths.data_dir, *key)
        return self._judges[key]

    def _judge_card(self, market: Market, tf: Timeframe) -> dict[str, Any]:
        m = self.trade_judge(market, tf)
        return {
            "on": bool(m and m.active),
            "stand_aside": bool(m and m.stand_aside),
            "text": judge.words(m),
        }

    def _exits_card(self, market: Market, tf: Timeframe) -> dict[str, Any] | None:
        try:
            ch = self.exit_plan(market, tf)
        except Exception:
            log.debug("No exit plan to show", exc_info=True)
            return None
        if not ch:
            return None
        return {"plan": ch["plan"].words(), "chosen": ch["chosen"], "why": ch["why"]}
