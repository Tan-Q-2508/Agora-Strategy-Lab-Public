"""Several strategies as one (WEEKEND_BRIEF §5, D-227).

Each member keeps running its own rules on its own little context, sharing the stock's candles
and indicators, so a combined strategy is an ordinary program: the same engine runs it in a
backtest and on paper (D-04). A member that wants in is "on" for ``window`` candles, because two
strategies rarely fire on the very same candle and a crossover confirmed three candles later is
still confirmed. The ways to combine:

- **all**: every member on, the same way round, one of them firing now.
- **any**: any member firing now.
- **veto**: the first member fires, and no other member has just said to get out or the opposite.
- **vote**: at least ``min_votes`` members on, one of them firing now.

The member that fired last owns the trade: its stop, target and exit rule run it. Members' states
are rebuilt from recent candles on a symbol's first candle, so a restarted paper session decides
exactly as a backtest does.

A shared-money blend isn't here: that is several sleeves with their own money, which the portfolio
(Phase 15) already runs in backtest and paper alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.strategy.runtime import Enter, Exit, PositionView, Side, StrategyContext


@dataclass
class Member:
    name: str
    program: Any
    side: Side | None = None  # the side this member is in, on its own reckoning
    since: int = -1  # the candle it went in on
    out_at: int = -(10**9)  # the candle it last said to get out
    out_side: Side | None = None
    ctx: StrategyContext | None = None


@dataclass
class Book:
    members: list[Member]
    owner: Member | None = None
    fired: list[tuple[Member, Enter]] = field(default_factory=list)


class Combiner:
    def __init__(
        self, members: list[tuple[str, Any]], mode: str, min_votes: int, window: int
    ) -> None:
        self.members = members
        self.mode = mode
        self.min_votes = min_votes
        self.window = window
        self.warmup = max(p.warmup for _, p in members)
        self.books: dict[str, Book] = {}

    def _book(self, ctx: StrategyContext) -> Book:
        book = self.books.get(ctx.symbol)
        if book is not None:
            return book
        members = []
        for name, program in self.members:
            shadow = StrategyContext(
                symbol=ctx.symbol,
                market=ctx.market,
                timeframe=ctx.timeframe,
                params=dict(program.params),
                _provider=ctx._provider,
                _default_size=program.default_size,
            )
            members.append(Member(name, program, ctx=shadow))
        book = Book(members)
        self.books[ctx.symbol] = book
        # rebuild the last few candles: a restart must decide as a backtest does
        for i in range(max(0, ctx._index - 2 * self.window), ctx._index):
            self._step(book, i, ctx)
        return book

    def _step(self, book: Book, index: int, ctx: StrategyContext) -> None:
        book.fired = []
        for m in book.members:
            shadow = m.ctx
            assert shadow is not None
            view = None
            if m.side is not None:
                price = 0.0
                view = PositionView(m.side, 1.0, price, 0, index - m.since, 0.0)
            shadow._advance(index, view, ctx._equity)
            m.program.on_bar(shadow)
            for intent in shadow._intents:
                if isinstance(intent, Exit) and m.side is not None:
                    m.out_at, m.out_side = index, m.side
                    m.side = None
                elif isinstance(intent, Enter) and m.side is None:
                    m.side, m.since = intent.side, index
                    book.fired.append((m, intent))
            shadow._logs.clear()
            # a member that nothing took up lets go after its window; one holding a real trade
            # keeps its place, or its own exit rule would never be asked
            expired = m.side is not None and index - m.since >= self.window
            if expired and m is not book.owner:
                m.side = None

    def _on(self, book: Book, side: Side, index: int) -> list[Member]:
        return [m for m in book.members if m.side == side and index - m.since <= self.window]

    def _chosen(self, book: Book, index: int) -> tuple[Member, Enter, str] | None:
        n = len(book.members)
        for m, intent in book.fired:
            with_it = self._on(book, intent.side, index)
            if self.mode == "any":
                return m, intent, m.name
            if self.mode == "all" and len(with_it) == n:
                return m, intent, " + ".join(x.name for x in book.members)
            if self.mode == "vote" and len(with_it) >= self.min_votes:
                return m, intent, f"{len(with_it)} of {n} agree"
            if self.mode == "veto" and m is book.members[0]:
                against = any(
                    x.side not in (None, intent.side)
                    or (index - x.out_at <= self.window and x.out_side == intent.side)
                    for x in book.members[1:]
                )
                if not against:
                    return m, intent, f"{m.name}, no veto"
        return None

    def on_bar(self, ctx: StrategyContext) -> None:
        book = self._book(ctx)
        index = ctx._index
        self._step(book, index, ctx)
        pos = ctx.position
        if pos is None:
            book.owner = None
            chosen = self._chosen(book, index)
            if chosen is not None:
                m, intent, why = chosen
                book.owner = m
                reason = f"{why}: {intent.reason}"[:200]
                ctx._intents.append(
                    Enter(
                        intent.side,
                        intent.size,
                        intent.stop_loss,
                        intent.take_profit,
                        intent.trailing_stop,
                        reason,
                        intent.scale_out,
                    )
                )
            return
        owner = book.owner
        if owner is not None and owner.side is None and owner.out_at == index:
            ctx.sell_all(f"{owner.name} said to get out")
