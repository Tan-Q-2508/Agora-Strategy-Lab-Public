"""Strategies as one, by hand-worked cases (D-227). The members are small scripts."""

from __future__ import annotations

from typing import Any

from backend.core.types import Market
from backend.strategy.combined import Combiner
from backend.strategy.runtime import IndicatorProvider, SizeSpec, StrategyContext


class Script:
    """A member that enters and exits on the candles it is told."""

    warmup = 0
    params: dict[str, float] = {}  # noqa: RUF012
    default_size = SizeSpec("percent_equity", 10)

    def __init__(self, buys: list[int], sells: list[int] | None = None) -> None:
        self.buys, self.sells = buys, sells or []

    def on_bar(self, ctx: StrategyContext) -> None:
        i = ctx._index
        if ctx.position is None and i in self.buys:
            ctx.buy(reason="buy")
        elif ctx.position is not None and i in self.sells:
            ctx.sell_all("sell")


class FakeProvider(IndicatorProvider):
    def __init__(self) -> None:  # a member here reads no candles
        pass


def run(mode: str, members: list[Script], n: int, *, votes: int = 2, window: int = 3) -> list[int]:
    """Bars the combination wants in on; each entry is "taken", then closed right away."""
    c = Combiner([(f"m{i}", m) for i, m in enumerate(members)], mode, votes, window)
    ctx = StrategyContext("X", Market.IN, "1d", {}, FakeProvider())
    wanted = []
    for i in range(n):
        ctx._advance(i, None, 1000.0)
        c.on_bar(ctx)
        if ctx._intents:
            wanted.append(i)
    return wanted


def test_all_needs_every_member_on_inside_the_window() -> None:
    assert run("all", [Script([2]), Script([4])], 8) == [4]  # 2 stays good for 3 candles
    assert run("all", [Script([2]), Script([7])], 9) == []  # too far apart


def test_any_takes_each_signal() -> None:
    assert run("any", [Script([2]), Script([6])], 8) == [2, 6]


def test_vote_needs_enough_members() -> None:
    three = [Script([2]), Script([3]), Script([9])]
    assert run("vote", three, 8, votes=2) == [3]
    assert run("vote", three, 8, votes=3) == []


def test_veto_blocks_the_first_member_after_another_said_get_out() -> None:
    blocker = Script([1], [3])  # went in on 1, said get out on 3
    assert run("veto", [Script([4]), blocker], 8) == []  # 4 is inside the blocker's window
    assert run("veto", [Script([8]), blocker], 10) == [8]  # long past it


def test_a_restart_decides_as_a_backtest_does() -> None:
    # the first member fired before the restart: rebuilt from recent candles, it still counts
    members = [Script([2]), Script([4])]
    c = Combiner([("a", members[0]), ("b", members[1])], "all", 2, 3)
    ctx = StrategyContext("X", Market.IN, "1d", {}, FakeProvider())
    ctx._advance(4, None, 1000.0)  # first call of this run, on candle 4
    c.on_bar(ctx)
    assert ctx._intents, "candle 2's signal was rebuilt"


def test_the_member_that_fired_owns_the_exit() -> None:
    from backend.strategy.runtime import Exit, PositionView

    m = Script([2], [5])
    c = Combiner([("a", m), ("b", Script([1], []))], "any", 2, 9)
    ctx = StrategyContext("X", Market.IN, "1d", {}, FakeProvider())
    pos: Any = None
    exits = []
    for i in range(7):
        ctx._advance(i, pos, 1000.0)
        c.on_bar(ctx)
        if pos is None and ctx._intents:
            pos = PositionView("long", 1, 1, 0, 0, 0)
        exits += [i for x in ctx._intents if isinstance(x, Exit)]
    assert exits == []  # b fired first, owns the trade, and has no exit rule


def test_the_owner_of_a_trade_closes_it() -> None:
    from backend.strategy.runtime import Exit, PositionView

    c = Combiner([("a", Script([2], [5])), ("b", Script([9]))], "any", 2, 9)
    ctx = StrategyContext("X", Market.IN, "1d", {}, FakeProvider())
    pos: Any = None
    exits = []
    for i in range(7):
        ctx._advance(i, pos, 1000.0)
        c.on_bar(ctx)
        if pos is None and ctx._intents:
            pos = PositionView("long", 1, 1, 0, 0, 0)
        exits += [i for x in ctx._intents if isinstance(x, Exit)]
    assert exits == [5]
