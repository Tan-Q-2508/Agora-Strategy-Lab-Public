"""The plain-English summary and the honesty panel (SPEC §6.3), built by rules, not AI.

The summary reads like a person explaining the result in three or four sentences; the
honesty panel lists everything that could make the result look better than it would be in
real life, so the user can judge how much to trust it.
"""

from __future__ import annotations

from typing import Any

from backend.core.types import Market

FEW_TRADES = 30


def money(value: float, market: Market) -> str:
    sym = "₹" if market is Market.IN else "$"
    v = abs(value)
    if market is Market.IN:
        if v >= 1e7:
            text = f"{sym}{v / 1e7:.2f} crore"
        elif v >= 1e5:
            text = f"{sym}{v / 1e5:.2f} lakh"
        else:
            text = f"{sym}{v:,.0f}"
    elif v >= 1e6:
        text = f"{sym}{v / 1e6:.2f} million"
    else:
        text = f"{sym}{v:,.0f}"
    return ("−" if value < 0 else "") + text


def pct(x: float, digits: int = 0) -> str:
    return f"{abs(x) * 100:.{digits}f}%"


def _years(days: float) -> str:
    years = days / 365.25
    if years >= 1.5:
        return f"{years:.0f} years"
    if years >= 0.9:
        return "1 year"
    months = max(1, round(days / 30.4))
    return f"{months} month{'s' if months != 1 else ''}"


def summary(m: dict[str, Any], market: Market, benchmark_name: str) -> str:
    if m.get("empty"):
        return "The backtest had no prices to run on, so there is nothing to summarise."
    period = _years(m["days"])
    total = m["total_return"]
    parts: list[str] = []
    verb = "made" if total >= 0 else "lost"
    first = f"This strategy {verb} {pct(total)} over {period}"
    if m.get("cagr") is not None and m["days"] >= 365:
        first += f" ({pct(m['cagr'], 1)} a year)"
    bench = m.get("benchmark") or {}
    if bench.get("total_return") is not None:
        b = bench["total_return"]
        if total > b:
            first += f", more than simply holding the {benchmark_name} ({pct(b)})"
        else:
            first += f", less than simply holding the {benchmark_name} ({pct(b)})"
    parts.append(first + ".")
    parts.append(f"Its worst drop was {pct(m['max_drawdown'])}.")
    n = m.get("trades", 0)
    if n == 0:
        parts.append("It never completed a trade, so the rules may be too strict for this period.")
    else:
        wr = m.get("win_rate") or 0.0
        parts.append(f"It made {n} trade{'s' if n != 1 else ''} and won {pct(wr)} of them.")
        share = m.get("charges_pct_of_gross_profit")
        if share is not None and share >= 0.05:
            parts.append(
                f"Charges took {pct(share)} of its gross profit ({money(m['charges_total'], market)})."
            )
        elif m.get("gross_pnl", 0) <= 0 and m.get("charges_total", 0) > 0:
            parts.append(
                f"It paid {money(m['charges_total'], market)} in charges on top of its trading losses."
            )
    if 0 < n < FEW_TRADES:
        parts.append("That's too few trades to trust the result much.")
    return " ".join(parts)


def honesty(
    m: dict[str, Any],
    *,
    market: Market,
    product: str,
    timeframe: str,
    data: dict[str, dict[str, Any]],
    data_mode: str,
    survivorship: bool,
    unverified_rates: bool,
    has_shorts: bool,
) -> list[dict[str, str]]:
    """Plain-English caveats: {level: info|warn, code, title, text}."""
    out: list[dict[str, str]] = []

    def add(level: str, code: str, title: str, text: str) -> None:
        out.append({"level": level, "code": code, "title": title, "text": text})

    sources: set[str] = set()
    for d in data.values():
        sources.update(d.get("sources", {}))
    if data_mode == "fake" or sources == {"fake"}:
        add(
            "warn",
            "practice_data",
            "Practice prices",
            "These are synthetic practice prices, not real market data.",
        )
    else:
        names = {
            "yahoo": "Yahoo Finance",
            "nse": "NSE end-of-day files",
            "stooq": "Stooq",
            "derived": "built from shorter candles",
        }
        used = ", ".join(names.get(x, x) for x in sorted(sources))
        add("info", "data_source", "Where the prices came from", f"Prices from {used}.")
        if "stooq" in sources:
            add(
                "warn",
                "stooq",
                "Some prices are approximate",
                "Some days came from Stooq, whose prices are adjusted for dividends, so they differ slightly from what traded.",
            )
    gaps = {s: d["missing_sessions"] for s, d in data.items() if d.get("missing_sessions")}
    if gaps:
        total = sum(gaps.values())
        add(
            "warn",
            "gaps",
            "Missing days",
            f"{total} trading day{'s' if total != 1 else ''} of prices are missing across {len(gaps)} stock{'s' if len(gaps) != 1 else ''}. No trades could happen on those days.",
        )
    empty = [s for s, d in data.items() if not d.get("bars")]
    if empty:
        add(
            "warn",
            "no_data",
            "Stocks left out",
            f"No prices for {', '.join(empty[:5])}{'…' if len(empty) > 5 else ''} in this period, so they were skipped.",
        )
    if survivorship:
        add(
            "warn",
            "survivorship",
            "Uses today's Nifty 50 list (survivorship bias)",
            "Stocks that left the index in the past aren't included, which flatters results. Import historical membership on the Data screen to fix this.",
        )
    if timeframe != "1d":
        days = max((d.get("trading_days", 0) for d in data.values()), default=0)
        label = {"1h": "hourly", "15m": "15-minute", "5m": "5-minute", "1m": "1-minute"}.get(
            timeframe, timeframe
        )
        if days < 250:
            add(
                "warn",
                "short_history",
                "Short history",
                f"Only {days} days of {label} data available.",
            )
    n = m.get("trades", 0)
    if n < FEW_TRADES:
        add(
            "warn",
            "few_trades",
            "Too few trades to trust",
            f"Only {n} completed trade{'s' if n != 1 else ''}. With fewer than {FEW_TRADES}, luck can easily explain the result.",
        )
    if m.get("open_at_end"):
        k = m["open_at_end"]
        add(
            "info",
            "open_at_end",
            "Trades still open at the end",
            f"{k} trade{'s were' if k != 1 else ' was'} still open on the last day; {'they are' if k != 1 else 'it is'} valued at the last close and not counted in the win rate.",
        )
    if has_shorts and market is Market.US:
        add(
            "info",
            "borrow_fees",
            "Short-selling costs",
            "Borrowing fees for short selling aren't included.",
        )
    if unverified_rates:
        add(
            "info",
            "unverified_rates",
            "Some charges are estimates",
            "A few charge rates for this period couldn't be confirmed from official sources and use best-known values.",
        )
    if product == "intraday" and market is Market.IN:
        add(
            "info",
            "square_off",
            "Intraday square-off",
            "Open intraday trades are closed automatically at the square-off time each day.",
        )
    return out
