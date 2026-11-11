"""Options arithmetic for Kairos (KAIROS §19, D-74): prices, Greeks, implied volatility and
the payoff of any multi-leg strategy.

Agora doesn't trade futures or options (LATER.md); this module lets Kairos *explain* them
with real numbers instead of the language model's guesses (D-57): "a Nifty iron condor
100 points wide collects about X, loses at most Y, breaks even at A and B, and with today's
volatility finishes in profit about 62% of the time".

- **Black-Scholes-Merton** for European options (index options on NSE and SPX are
  European), with a continuous dividend yield ``q``. Index options in India are priced off
  the futures; using ``q`` = the dividend yield gives the same answer as Black-76.
- **Cox-Ross-Rubinstein** binomial tree for American options (US single-stock options),
  which may be exercised early.
- **Implied volatility** by bisection (always converges; Newton steps can overshoot on
  deep in- or out-of-the-money options).
- **Strategies**: legs of calls, puts, the stock or a future, each long or short. The
  payoff at expiry, the value today, maximum profit and loss (``None`` = unlimited), break-
  even prices, net debit or credit, position Greeks, and the chance of finishing in profit
  under a lognormal price with the given volatility.

All prices are per share (or per index point); multiply by the lot size for money. Premiums
Kairos shows from historical volatility are *estimates*: real option prices come from the
option chain, where implied volatility is usually different.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

Kind = Literal["call", "put", "stock", "future"]
YEAR_DAYS = 365.0


def _n(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass(frozen=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    theta: float  # per calendar day
    vega: float  # per 1 volatility point (0.01)
    rho: float  # per 1 interest-rate point (0.01)


def bsm(
    kind: Literal["call", "put"],
    spot: float,
    strike: float,
    years: float,
    rate: float,
    vol: float,
    div: float = 0.0,
) -> Greeks:
    """Black-Scholes-Merton price and Greeks of one European option."""
    if years <= 0 or vol <= 0:
        intrinsic = max(0.0, spot - strike) if kind == "call" else max(0.0, strike - spot)
        delta = (
            (1.0 if spot > strike else 0.0) if kind == "call" else (-1.0 if spot < strike else 0.0)
        )
        return Greeks(intrinsic, delta, 0.0, 0.0, 0.0, 0.0)
    sq = vol * math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - div + 0.5 * vol * vol) * years) / sq
    d2 = d1 - sq
    disc_r, disc_q = math.exp(-rate * years), math.exp(-div * years)
    gamma = disc_q * _pdf(d1) / (spot * sq)
    vega = spot * disc_q * _pdf(d1) * math.sqrt(years) / 100.0
    common = -spot * disc_q * _pdf(d1) * vol / (2.0 * math.sqrt(years))
    if kind == "call":
        price = spot * disc_q * _n(d1) - strike * disc_r * _n(d2)
        delta = disc_q * _n(d1)
        theta = common - rate * strike * disc_r * _n(d2) + div * spot * disc_q * _n(d1)
        rho = strike * years * disc_r * _n(d2) / 100.0
    else:
        price = strike * disc_r * _n(-d2) - spot * disc_q * _n(-d1)
        delta = -disc_q * _n(-d1)
        theta = common + rate * strike * disc_r * _n(-d2) - div * spot * disc_q * _n(-d1)
        rho = -strike * years * disc_r * _n(-d2) / 100.0
    return Greeks(price, delta, gamma, theta / YEAR_DAYS, vega, rho)


def american(
    kind: Literal["call", "put"],
    spot: float,
    strike: float,
    years: float,
    rate: float,
    vol: float,
    div: float = 0.0,
    steps: int = 400,
) -> float:
    """Cox-Ross-Rubinstein price of an American option (early exercise allowed)."""
    if years <= 0 or vol <= 0:
        return max(0.0, spot - strike) if kind == "call" else max(0.0, strike - spot)
    dt = years / steps
    u = math.exp(vol * math.sqrt(dt))
    d = 1.0 / u
    p = (math.exp((rate - div) * dt) - d) / (u - d)
    disc = math.exp(-rate * dt)
    j = np.arange(steps + 1)
    prices = spot * u ** (steps - j) * d**j
    sign = 1.0 if kind == "call" else -1.0
    values = np.maximum(sign * (prices - strike), 0.0)
    for n in range(steps, 0, -1):
        prices = prices[:n] * d
        values = disc * (p * values[:n] + (1 - p) * values[1 : n + 1])
        values = np.maximum(values, sign * (prices - strike))
    return float(values[0])


def implied_vol(
    price: float,
    kind: Literal["call", "put"],
    spot: float,
    strike: float,
    years: float,
    rate: float,
    div: float = 0.0,
) -> float | None:
    """The volatility at which Black-Scholes gives ``price`` (None if no volatility can)."""
    lo, hi = 1e-4, 5.0
    f_lo = bsm(kind, spot, strike, years, rate, lo, div).price - price
    f_hi = bsm(kind, spot, strike, years, rate, hi, div).price - price
    if f_lo > 0 or f_hi < 0:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        f = bsm(kind, spot, strike, years, rate, mid, div).price - price
        if abs(f) < 1e-8:
            return mid
        if f > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def expected_move(spot: float, vol: float, days: float) -> float:
    """One standard deviation of the price over ``days`` (≈ 68% of outcomes inside)."""
    return spot * vol * math.sqrt(max(days, 0.0) / YEAR_DAYS)


# ---------------------------------------------------------------- strategies


@dataclass
class Leg:
    kind: Kind
    side: int  # +1 bought, −1 sold
    strike: float = 0.0  # options only
    qty: float = 1.0  # in lots
    days: float | None = None  # days to this leg's expiry (None = the strategy's)
    premium: float | None = None  # per share; None = priced by the model

    def label(self) -> str:
        verb = "Buy" if self.side > 0 else "Sell"
        qty = "" if self.qty == 1 else f"{self.qty:g}× "
        if self.kind in ("stock", "future"):
            return f"{verb} {qty}{'the stock' if self.kind == 'stock' else 'the future'}"
        when = "" if self.days is None else f" ({self.days:g}-day)"
        return f"{verb} {qty}{self.strike:g} {self.kind}{when}"


@dataclass(frozen=True)
class StrategyInfo:
    key: str
    name: str
    view: str  # the market view it suits
    build: Callable[[float, float], list[Leg]]  # (spot rounded to a strike, strike gap)
    words: tuple[str, ...] = ()
    notes: str = ""


def _c(side: int, k: float, qty: float = 1.0, days: float | None = None) -> Leg:
    return Leg("call", side, k, qty, days)


def _p(side: int, k: float, qty: float = 1.0, days: float | None = None) -> Leg:
    return Leg("put", side, k, qty, days)


STRATEGIES: dict[str, StrategyInfo] = {
    s.key: s
    for s in (
        StrategyInfo(
            "long_call",
            "Long call",
            "Bullish, expecting a big move up",
            lambda a, g: [_c(1, a)],
            ("buy call",),
        ),
        StrategyInfo(
            "long_put",
            "Long put",
            "Bearish, expecting a big move down",
            lambda a, g: [_p(1, a)],
            ("buy put",),
        ),
        StrategyInfo(
            "short_call",
            "Short (naked) call",
            "Neutral to bearish; unlimited risk",
            lambda a, g: [_c(-1, a + g)],
            ("naked call", "sell call"),
        ),
        StrategyInfo(
            "short_put",
            "Short put",
            "Neutral to bullish; willing to buy lower",
            lambda a, g: [_p(-1, a - g)],
            ("sell put", "naked put"),
        ),
        StrategyInfo(
            "covered_call",
            "Covered call",
            "Mildly bullish; earn income on shares held",
            lambda a, g: [Leg("stock", 1), _c(-1, a + 2 * g)],
            ("buy write", "buy-write"),
        ),
        StrategyInfo(
            "cash_secured_put",
            "Cash-secured put",
            "Bullish; get paid to wait for a lower buy price",
            lambda a, g: [_p(-1, a - 2 * g)],
            ("csp", "secured put"),
        ),
        StrategyInfo(
            "protective_put",
            "Protective put",
            "Own the stock, insure against a fall",
            lambda a, g: [Leg("stock", 1), _p(1, a - 2 * g)],
            ("married put", "insurance"),
        ),
        StrategyInfo(
            "collar",
            "Collar",
            "Own the stock, cheap insurance by giving up some upside",
            lambda a, g: [Leg("stock", 1), _p(1, a - 2 * g), _c(-1, a + 2 * g)],
            ("zero cost collar",),
        ),
        StrategyInfo(
            "bull_call_spread",
            "Bull call spread",
            "Moderately bullish, limited cost",
            lambda a, g: [_c(1, a), _c(-1, a + 2 * g)],
            ("call debit spread",),
        ),
        StrategyInfo(
            "bear_put_spread",
            "Bear put spread",
            "Moderately bearish, limited cost",
            lambda a, g: [_p(1, a), _p(-1, a - 2 * g)],
            ("put debit spread",),
        ),
        StrategyInfo(
            "bull_put_spread",
            "Bull put spread",
            "Neutral to bullish; collect premium",
            lambda a, g: [_p(-1, a - g), _p(1, a - 3 * g)],
            ("put credit spread",),
        ),
        StrategyInfo(
            "bear_call_spread",
            "Bear call spread",
            "Neutral to bearish; collect premium",
            lambda a, g: [_c(-1, a + g), _c(1, a + 3 * g)],
            ("call credit spread",),
        ),
        StrategyInfo(
            "long_straddle",
            "Long straddle",
            "A big move either way (events, results)",
            lambda a, g: [_c(1, a), _p(1, a)],
            ("buy straddle",),
        ),
        StrategyInfo(
            "short_straddle",
            "Short straddle",
            "Price stays put; unlimited risk",
            lambda a, g: [_c(-1, a), _p(-1, a)],
            ("sell straddle",),
        ),
        StrategyInfo(
            "long_strangle",
            "Long strangle",
            "A very big move either way, cheaper than a straddle",
            lambda a, g: [_c(1, a + 2 * g), _p(1, a - 2 * g)],
            ("buy strangle",),
        ),
        StrategyInfo(
            "short_strangle",
            "Short strangle",
            "Price stays in a range; unlimited risk",
            lambda a, g: [_c(-1, a + 2 * g), _p(-1, a - 2 * g)],
            ("sell strangle",),
        ),
        StrategyInfo(
            "iron_condor",
            "Iron condor",
            "Price stays in a range; risk capped",
            lambda a, g: [_p(1, a - 4 * g), _p(-1, a - 2 * g), _c(-1, a + 2 * g), _c(1, a + 4 * g)],
            ("condor",),
        ),
        StrategyInfo(
            "iron_butterfly",
            "Iron butterfly",
            "Price pinned near one level; risk capped",
            lambda a, g: [_p(1, a - 3 * g), _p(-1, a), _c(-1, a), _c(1, a + 3 * g)],
            ("iron fly",),
        ),
        StrategyInfo(
            "long_call_butterfly",
            "Long call butterfly",
            "Price ends near a target; cheap, capped",
            lambda a, g: [_c(1, a - 2 * g), _c(-1, a, 2), _c(1, a + 2 * g)],
            ("butterfly", "fly"),
        ),
        StrategyInfo(
            "broken_wing_butterfly",
            "Broken-wing butterfly",
            "Target a level with no risk on one side",
            lambda a, g: [_c(1, a), _c(-1, a + 2 * g, 2), _c(1, a + 5 * g)],
            ("bwb", "broken wing"),
        ),
        StrategyInfo(
            "call_ratio_spread",
            "Call ratio spread",
            "Mildly bullish to a target; risk above",
            lambda a, g: [_c(1, a), _c(-1, a + 2 * g, 2)],
            ("front ratio", "ratio spread"),
        ),
        StrategyInfo(
            "put_ratio_spread",
            "Put ratio spread",
            "Mildly bearish to a target; risk below",
            lambda a, g: [_p(1, a), _p(-1, a - 2 * g, 2)],
            (),
        ),
        StrategyInfo(
            "call_backspread",
            "Call ratio backspread",
            "Strongly bullish; small loss if it stalls",
            lambda a, g: [_c(-1, a), _c(1, a + 2 * g, 2)],
            ("backspread",),
        ),
        StrategyInfo(
            "put_backspread",
            "Put ratio backspread",
            "Strongly bearish; small loss if it stalls",
            lambda a, g: [_p(-1, a), _p(1, a - 2 * g, 2)],
            (),
        ),
        StrategyInfo(
            "jade_lizard",
            "Jade lizard",
            "Neutral to bullish; no upside risk when the credit exceeds the call spread's width",
            lambda a, g: [_p(-1, a - g), _c(-1, a + 2 * g), _c(1, a + 3 * g)],
            ("lizard",),
        ),
        StrategyInfo(
            "strap", "Strap", "A big move, more likely up", lambda a, g: [_c(1, a, 2), _p(1, a)], ()
        ),
        StrategyInfo(
            "strip",
            "Strip",
            "A big move, more likely down",
            lambda a, g: [_c(1, a), _p(1, a, 2)],
            (),
        ),
        StrategyInfo(
            "synthetic_long",
            "Synthetic long",
            "Bullish: behaves like owning the stock",
            lambda a, g: [_c(1, a), _p(-1, a)],
            ("synthetic future",),
        ),
        StrategyInfo(
            "synthetic_short",
            "Synthetic short",
            "Bearish: behaves like shorting the stock",
            lambda a, g: [_c(-1, a), _p(1, a)],
            (),
        ),
        StrategyInfo(
            "calendar_spread",
            "Calendar (time) spread",
            "Price stays near the strike; profits from faster decay of the near option",
            lambda a, g: [_c(-1, a), _c(1, a, 1, 60)],
            ("time spread", "horizontal spread"),
        ),
        StrategyInfo(
            "diagonal_spread",
            "Diagonal spread (poor man's covered call)",
            "Mildly bullish income with less money tied up",
            lambda a, g: [_c(1, a - 4 * g, 1, 120), _c(-1, a + 2 * g)],
            ("poor man's covered call", "poor mans covered call", "pmcc", "diagonal"),
        ),
        StrategyInfo(
            "long_futures",
            "Long futures",
            "Bullish with leverage; losses as large as gains",
            lambda a, g: [Leg("future", 1)],
            ("buy futures",),
        ),
        StrategyInfo(
            "short_futures",
            "Short futures",
            "Bearish, or hedging a portfolio",
            lambda a, g: [Leg("future", -1)],
            ("sell futures", "hedge"),
        ),
    )
}


def find_strategy(text: str) -> StrategyInfo | None:
    low = text.lower().replace("-", " ")
    best: tuple[int, StrategyInfo] | None = None
    for s in STRATEGIES.values():
        names = (s.name.lower().replace("-", " "), s.key.replace("_", " "), *s.words)
        for n in names:
            if n and n in low and (best is None or len(n) > best[0]):
                best = (len(n), s)
    return best[1] if best else None


def strike_gap(spot: float) -> float:
    """A typical strike spacing for this price (Nifty 50, Bank Nifty 100, stocks 1–50)."""
    for limit, gap in (
        (50, 1.0),
        (200, 2.5),
        (500, 5.0),
        (1500, 10.0),
        (5000, 20.0),
        (20000, 50.0),
        (40000, 100.0),
    ):
        if spot < limit:
            return gap
    return 100.0


@dataclass
class Analysis:
    legs: list[Leg]
    net_premium: float  # paid (> 0, a debit) or received (< 0, a credit), per share
    max_profit: float | None  # None = unlimited
    max_loss: float | None  # positive number; None = unlimited
    breakevens: list[float]
    pop: float  # chance of finishing above zero at the first expiry
    greeks: dict[str, float]
    grid: list[float]
    at_expiry: list[float]
    today: list[float]
    expected_move: float
    extras: dict[str, Any] = field(default_factory=dict)


def _leg_value(leg: Leg, s: float, days_left: float, rate: float, vol: float, div: float) -> float:
    if leg.kind == "call" or leg.kind == "put":
        return bsm(leg.kind, s, leg.strike, max(days_left, 0.0) / YEAR_DAYS, rate, vol, div).price
    return s


def analyze(
    legs: Sequence[Leg],
    spot: float,
    days: float,
    vol: float,
    rate: float = 0.065,
    div: float = 0.0,
) -> Analysis:
    """Everything about a strategy. ``days`` is the nearest expiry; legs with their own
    ``days`` (calendars, diagonals) are valued at that moment with time left."""
    legs = [Leg(**{**leg.__dict__}) for leg in legs]
    for leg in legs:
        if leg.premium is None:
            d = leg.days if leg.days is not None else days
            leg.premium = _leg_value(leg, spot, d, rate, vol, div)
    # A future costs nothing to open (it needs margin instead), so it adds no premium.
    net = sum(leg.side * leg.qty * (leg.premium or 0.0) for leg in legs if leg.kind != "future")
    lo, hi = spot * 0.4, spot * 1.6
    grid = np.linspace(lo, hi, 601)

    def value_at(s: float, elapsed: float) -> float:
        total = 0.0
        for leg in legs:
            d = leg.days if leg.days is not None else days
            v = _leg_value(leg, s, d - elapsed, rate, vol, div)
            total += leg.side * leg.qty * (v - (leg.premium or 0.0))
        return total

    at_exp = np.array([value_at(float(s), days) for s in grid])
    today = np.array([value_at(float(s), 0.0) for s in grid])
    # Unlimited if the payoff keeps rising/falling at the edges of a wide grid.
    slope_hi = at_exp[-1] - at_exp[-2]
    slope_lo = at_exp[1] - at_exp[0]
    unlimited_up = slope_hi > 1e-6 * spot
    unlimited_down_profit = slope_lo < -1e-6 * spot and at_exp[0] > 0  # rises toward 0 price
    loss_up = slope_hi < -1e-6 * spot
    max_profit = None if unlimited_up else float(np.max(at_exp))
    if unlimited_down_profit and not unlimited_up:
        max_profit = float(max(np.max(at_exp), value_at(1e-9, days)))
    max_loss = None if loss_up else float(max(0.0, -min(np.min(at_exp), value_at(1e-9, days))))
    bes: list[float] = []
    for k in range(len(grid) - 1):
        a, b = at_exp[k], at_exp[k + 1]
        if a == 0:
            bes.append(float(grid[k]))
        elif a * b < 0:
            bes.append(float(grid[k] - a * (grid[k + 1] - grid[k]) / (b - a)))
    # Chance of finishing in profit: lognormal price at expiry with this volatility.
    t = days / YEAR_DAYS
    if t > 0 and vol > 0:
        mu = math.log(spot) + (rate - div - 0.5 * vol * vol) * t
        sd = vol * math.sqrt(t)
        z = (np.log(grid) - mu) / sd
        dens = np.exp(-0.5 * z * z) / (grid * sd * math.sqrt(2 * math.pi))
        w = dens * np.gradient(grid)
        tail = 1.0 - _n((math.log(hi) - mu) / sd) + _n((math.log(lo) - mu) / sd)
        pop = float(np.sum(w[at_exp > 0]) / max(np.sum(w), 1e-12))
        pop = min(max(pop * (1.0 - tail) + tail * (1.0 if at_exp[-1] > 0 else 0.0), 0.0), 1.0)
    else:
        pop = float(value_at(spot, days) > 0)
    g = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in legs:
        if leg.kind != "call" and leg.kind != "put":
            g["delta"] += leg.side * leg.qty
            continue
        d = leg.days if leg.days is not None else days
        gr = bsm(leg.kind, spot, leg.strike, d / YEAR_DAYS, rate, vol, div)
        for name in g:
            g[name] += leg.side * leg.qty * getattr(gr, name)
    return Analysis(
        legs=legs,
        net_premium=net,
        max_profit=max_profit,
        max_loss=max_loss,
        breakevens=[round(b, 2) for b in bes],
        pop=round(pop, 3),
        greeks={k: round(v, 4) for k, v in g.items()},
        grid=[round(float(x), 2) for x in grid[::10]],
        at_expiry=[round(float(x), 3) for x in at_exp[::10]],
        today=[round(float(x), 3) for x in today[::10]],
        expected_move=round(expected_move(spot, vol, days), 2),
    )


def describe(
    a: Analysis, info: StrategyInfo | None, lot: float, money: Callable[[float], str]
) -> list[str]:
    """Plain-English lines (money = per share × the lot size)."""
    lines = []
    if info is not None:
        lines.append(f"{info.name}: {info.view}.")
    lines.append(
        "Legs: "
        + "; ".join(
            f"{leg.label()} at about {leg.premium:.2f}"
            if leg.kind in ("call", "put")
            else leg.label()
            for leg in a.legs
        )
        + "."
    )
    if any(leg.kind == "future" for leg in a.legs):
        lines.append(
            "Futures cost no premium but need margin (a share of the contract value) "
            "and are settled in cash every day."
        )
    if a.net_premium > 0:
        lines.append(f"Costs about {money(a.net_premium * lot)} to open (a debit).")
    elif a.net_premium < 0:
        lines.append(f"Collects about {money(-a.net_premium * lot)} to open (a credit).")
    mp = "unlimited" if a.max_profit is None else money(a.max_profit * lot)
    ml = "unlimited" if a.max_loss is None else money(a.max_loss * lot)
    lines.append(f"Most it can make at expiry: {mp}. Most it can lose: {ml}.")
    if a.breakevens:
        lines.append("Breaks even at " + " and ".join(f"{b:,.2f}" for b in a.breakevens) + ".")
    lines.append(
        f"Chance of finishing in profit (from this volatility): {a.pop * 100:.0f}%. A one-standard-"
        f"deviation move by expiry is about ±{a.expected_move:,.2f}."
    )
    g = a.greeks
    lines.append(
        f"Greeks now (per share): delta {g['delta']:+.2f}, gamma {g['gamma']:+.4f}, theta "
        f"{g['theta']:+.3f} a day, vega {g['vega']:+.3f} per volatility point."
    )
    return lines
