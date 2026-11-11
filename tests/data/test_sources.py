"""Parser tests for Yahoo, NSE bhavcopy and Stooq on hand-made samples (no network).

Samples copy the real layouts (checked against live responses on 2026-10-21) but use
made-up numbers: real market data is never committed (CLAUDE.md §4).
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from backend.core.types import Bar, CorporateAction, Timeframe
from backend.data.adjust import adjusted, factor_at, split_events, unadjust, with_factors
from backend.data.errors import EmptyResponse, NotFound, RateLimited, SourceError
from backend.data.nse import NseBhavcopySource, parse_legacy, parse_udiff, url_for
from backend.data.stooq import StooqSource, parse_csv
from backend.data.throttle import Throttle
from backend.data.yahoo import Row, YahooSource, _translate
from backend.fakes.clock import FakeClock
from backend.markets.calendar import ExchangeCalendar

NY = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")
CAL = ExchangeCalendar()


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def no_throttle() -> Throttle:
    return Throttle(0.0, sleep=lambda _s: None)


# ---------------------------------------------------------------- adjustments


def test_split_factor_counts_only_later_splits() -> None:
    splits = [(100, 2.0), (200, 3.0)]
    assert factor_at(50, splits) == pytest.approx(1 / 6)
    assert factor_at(100, splits) == pytest.approx(1 / 3)  # ex-date itself: already split
    assert factor_at(150, splits) == pytest.approx(1 / 3)
    assert factor_at(250, splits) == 1.0


def test_unadjust_and_adjust_round_trip() -> None:
    adj = Bar(0, 125.0, 126.0, 124.0, 125.5, 4000.0, "yahoo")
    raw = unadjust(adj, 0.25)
    assert (raw.open, raw.close, raw.volume, raw.split_factor) == (500.0, 502.0, 1000, 0.25)
    back = adjusted(raw)
    assert back.open == pytest.approx(125.0) and back.volume == pytest.approx(4000.0)


def test_unadjust_rounds_float_noise() -> None:
    raw = unadjust(Bar(0, 127.58000183105469, 128, 127, 127.5, 10, "yahoo"), 1.0)
    assert raw.open == 127.58


def test_split_events_ignore_dividends_and_no_op_splits() -> None:
    acts = [
        CorporateAction(10, "dividend", amount=1.0),
        CorporateAction(20, "split", ratio=1.0),
        CorporateAction(30, "split", ratio=2.0),
    ]
    assert split_events(acts) == [(30, 2.0)]
    bars = with_factors([Bar(5, 1, 1, 1, 1, 1, "x"), Bar(40, 1, 1, 1, 1, 1, "x")], [(30, 2.0)])
    assert [b.split_factor for b in bars] == [0.5, 1.0]


# ---------------------------------------------------------------- Yahoo


class FakeYahoo:
    """Stands in for yfinance: returns split-adjusted rows like the real thing."""

    def __init__(self, rows: list[Row], actions: list[tuple[datetime, float, float]]) -> None:
        self.rows = rows
        self.actions_rows = actions
        self.calls: list[dict[str, Any]] = []

    def history(self, symbol: str, kwargs: dict[str, Any]) -> list[Row]:
        self.calls.append({"symbol": symbol, **kwargs})
        return self.rows

    def actions(self, symbol: str) -> list[tuple[datetime, float, float]]:
        return self.actions_rows


def _yahoo(fake: FakeYahoo, now: datetime) -> YahooSource:
    return YahooSource(
        FakeClock(ms(now)),
        CAL,
        history=fake.history,
        actions=fake.actions,
        throttle=no_throttle(),
    )


def test_yahoo_daily_restamps_to_session_open_and_unadjusts_splits() -> None:
    # Made-up stock with a 4:1 split on 2020-08-31 (a real NYSE session).
    rows = [
        Row(datetime(2020, 8, 28, tzinfo=NY), 126.0, 127.0, 125.0, 126.5, 4_000_000),
        Row(datetime(2020, 8, 31, tzinfo=NY), 127.0, 131.0, 126.0, 129.0, 9_000_000),
    ]
    fake = FakeYahoo(rows, [(datetime(2020, 8, 31, tzinfo=NY), 0.0, 4.0)])
    src = _yahoo(fake, datetime(2026, 1, 5, tzinfo=UTC))
    bars = src.fetch_bars(
        "TEST", Timeframe.D1, datetime(2020, 8, 27, tzinfo=UTC), datetime(2020, 9, 1, tzinfo=UTC)
    )
    assert [b.ts for b in bars] == [
        ms(datetime(2020, 8, 28, 9, 30, tzinfo=NY)),
        ms(datetime(2020, 8, 31, 9, 30, tzinfo=NY)),
    ]
    pre, post = bars
    assert (pre.open, pre.close, pre.volume, pre.split_factor) == (504.0, 506.0, 1_000_000, 0.25)
    assert (post.open, post.split_factor) == (127.0, 1.0)
    assert fake.calls[0]["interval"] == "1d"


def test_yahoo_dividends_are_stored_as_cash_actually_paid() -> None:
    fake = FakeYahoo(
        [],
        [
            (datetime(2019, 8, 9, tzinfo=NY), 0.1925, 0.0),  # adjusted for the later 4:1
            (datetime(2020, 8, 31, tzinfo=NY), 0.0, 4.0),
        ],
    )
    acts = _yahoo(fake, datetime(2026, 1, 5, tzinfo=UTC)).fetch_corporate_actions("TEST")
    div = next(a for a in acts if a.kind == "dividend")
    assert div.amount == pytest.approx(0.77)
    assert div.ex_date == ms(datetime(2019, 8, 9, 9, 30, tzinfo=NY))


def test_yahoo_drops_bad_rows_and_marks_forming_bar() -> None:
    now = datetime(2026, 10, 21, 10, 12, tzinfo=IST)
    rows = [
        Row(datetime(2026, 10, 21, 9, 15, tzinfo=IST), 100, 101, 99, 100.5, 1000),
        Row(datetime(2026, 10, 21, 9, 20, tzinfo=IST), float("nan"), 101, 99, 100.5, 1000),
        Row(datetime(2026, 10, 21, 10, 10, tzinfo=IST), 100, 101, 99, 100.5, 10),
    ]
    src = _yahoo(FakeYahoo(rows, []), now)
    latest = src.latest_bars(["RELIANCE.NS"], Timeframe.M5)["RELIANCE.NS"]
    assert len(latest) == 2
    assert latest[0].is_final and not latest[1].is_final
    # fetch_bars never returns the forming bar
    bars = src.fetch_bars(
        "RELIANCE.NS", Timeframe.M5, now - timedelta(hours=2), now + timedelta(hours=1)
    )
    assert [b.is_final for b in bars] == [True]


def test_yahoo_one_minute_requests_are_chunked_and_windowed() -> None:
    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    fake = FakeYahoo([Row(datetime(2026, 10, 20, 10, 0, tzinfo=NY), 1, 1, 1, 1, 1)], [])
    src = _yahoo(fake, now)
    src.fetch_bars("SPY", Timeframe.M1, now - timedelta(days=90), now)
    assert len(fake.calls) == 5  # 29-day window / 7-day chunks
    assert fake.calls[0]["start"] >= now - timedelta(days=29, minutes=1)


def test_yahoo_empty_answer_is_a_failure_not_no_data() -> None:
    src = _yahoo(FakeYahoo([], []), datetime(2026, 1, 5, tzinfo=UTC))
    with pytest.raises(EmptyResponse):
        src.fetch_bars(
            "SPY", Timeframe.D1, datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC)
        )


def test_yahoo_errors_translate() -> None:
    class YFRateLimitError(Exception):
        pass

    assert isinstance(_translate(YFRateLimitError("Too Many Requests"), "X"), RateLimited)
    assert isinstance(_translate(Exception("X: possibly delisted; no price data"), "X"), NotFound)


# ---------------------------------------------------------------- NSE bhavcopy

UDIFF_HEAD = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,"
    "PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,"
    "TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4"
)


def udiff_row(
    day: str, sym: str, series: str, o: float, h: float, lo: float, c: float, v: int
) -> str:
    return (
        f"{day},{day},CM,NSE,STK,1,INE000000000,{sym},{series},,,,,{sym} LTD,{o},{h},{lo},{c},"
        f"{c},{c},,{c},,,{v},1000.0,10,F1,1,,,,,"
    )


LEGACY_HEAD = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,"


def zipped(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, text)
    return buf.getvalue()


def test_nse_parsers_keep_only_eq_series() -> None:
    text = "\n".join(
        [
            UDIFF_HEAD,
            udiff_row("2024-10-28", "ABC", "EQ", 10, 11, 9, 10.5, 1000),
            udiff_row("2024-10-28", "ABC", "BE", 1, 1, 1, 1, 1),
        ]
    )
    assert parse_udiff(text) == {"ABC": (10.0, 11.0, 9.0, 10.5, 1000.0)}
    legacy = LEGACY_HEAD + "\nABC,EQ,10,11,9,10.5,10.4,10,1000,10500,05-JUL-2024,5,INE0,\n"
    assert parse_legacy(legacy) == {"ABC": (10.0, 11.0, 9.0, 10.5, 1000.0)}


def test_nse_url_switches_format_on_udiff_date() -> None:
    assert url_for(date(2024, 10, 28)).endswith("BhavCopy_NSE_CM_0_0_0_20241028_F_0000.csv.zip")
    assert url_for(date(2024, 7, 5)).endswith(
        "historical/EQUITIES/2024/JUL/cm05JUL2024bhav.csv.zip"
    )


def test_nse_source_builds_raw_daily_bars_and_skips_missing_files() -> None:
    files = {
        url_for(date(2024, 10, 25)): zipped(
            "a.csv", UDIFF_HEAD + "\n" + udiff_row("2024-10-25", "ABC", "EQ", 10, 11, 9, 10.5, 100)
        ),
        url_for(date(2024, 10, 28)): zipped(
            "b.csv", UDIFF_HEAD + "\n" + udiff_row("2024-10-28", "ABC", "EQ", 5, 6, 4, 5.5, 300)
        ),
    }
    src = NseBhavcopySource(
        FakeClock(ms(datetime(2026, 1, 5, tzinfo=UTC))),
        CAL,
        download=files.get,
        throttle=no_throttle(),
    )
    bars = src.fetch_bars(
        "ABC", Timeframe.D1, datetime(2024, 10, 24, tzinfo=UTC), datetime(2024, 10, 30, tzinfo=UTC)
    )
    assert [(b.ts, b.close, b.source) for b in bars] == [
        (ms(datetime(2024, 10, 25, 9, 15, tzinfo=IST)), 10.5, "nse"),
        (ms(datetime(2024, 10, 28, 9, 15, tzinfo=IST)), 5.5, "nse"),
    ]
    with pytest.raises(NotFound):
        src.fetch_bars(
            "XYZ",
            Timeframe.D1,
            datetime(2024, 10, 24, tzinfo=UTC),
            datetime(2024, 10, 30, tzinfo=UTC),
        )
    assert src.symbol_for(src_market(), "NIFTY50", "^NSEI") is None


def src_market() -> Any:
    from backend.core.types import Market

    return Market.IN


# ---------------------------------------------------------------- Stooq


def test_stooq_csv_and_errors() -> None:
    text = "Date,Open,High,Low,Close,Volume\n2025-01-02,10,11,9,10.5,1000\n2025-01-03,10.5,12,10,11,2000\n"
    rows = parse_csv(text)
    assert rows[0] == (date(2025, 1, 2), 10.0, 11.0, 9.0, 10.5, 1000.0)
    with pytest.raises(NotFound):
        parse_csv("No data")
    with pytest.raises(RateLimited):
        parse_csv("Exceeded the daily hits limit")
    with pytest.raises(SourceError, match="browser check"):  # Stooq's bot check (2026)
        parse_csv('<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>…')
    src = StooqSource(
        FakeClock(ms(datetime(2026, 1, 5, tzinfo=UTC))),
        CAL,
        download=lambda sym, d1, d2: text,
        throttle=no_throttle(),
    )
    bars = src.fetch_bars(
        "aapl.us", Timeframe.D1, datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 4, tzinfo=UTC)
    )
    assert bars[0].ts == ms(datetime(2025, 1, 2, 9, 30, tzinfo=NY))
    assert src.returns_adjusted
    from backend.core.types import Market

    assert src.symbol_for(Market.US, "BRK.B", "BRK-B") == "brk-b.us"


def test_a_live_poll_overlaps_slow_answers_and_skips_unknown_stocks() -> None:
    """D-194: one request after another, 250 stocks at 5-13 s an answer took 25 minutes and the
    15-minute desk fell two candles behind; a stock Yahoo doesn't know failed the whole poll."""
    import threading
    import time as _t

    from backend.data.errors import NotFound

    now = datetime(2026, 10, 21, 10, 12, tzinfo=IST)
    rows = [Row(datetime(2026, 10, 21, 9, 15, tzinfo=IST), 100, 101, 99, 100.5, 1000)]
    fake = FakeYahoo(rows, [])
    inflight = {"now": 0, "max": 0}
    lock = threading.Lock()

    def slow(symbol: str, kwargs: dict[str, Any]) -> list[Row]:
        if symbol == "GONE.NS":
            raise NotFound("no such symbol")
        with lock:
            inflight["now"] += 1
            inflight["max"] = max(inflight["max"], inflight["now"])
        _t.sleep(0.05)
        with lock:
            inflight["now"] -= 1
        return fake.history(symbol, kwargs)

    src = YahooSource(
        FakeClock(ms(now)), CAL, history=slow, actions=fake.actions, throttle=no_throttle()
    )
    syms = [f"S{k}.NS" for k in range(12)] + ["GONE.NS"]
    out = src.latest_bars(syms, Timeframe.M15)
    assert inflight["max"] > 1  # answers overlapped
    assert out["GONE.NS"] == [] and all(out[f"S{k}.NS"] for k in range(12))


def test_yahoo_is_asked_about_three_times_a_second() -> None:
    """D-195: one request a second, shared by everything, queued requests for a minute."""
    from backend.data import yahoo

    assert 0.25 <= yahoo.MIN_INTERVAL_S <= 0.5


def test_a_live_poll_doesnt_ask_for_each_stocks_split_list() -> None:
    """D-197: every polled stock cost a second request for its dividends and splits."""
    now = datetime(2026, 10, 21, 10, 12, tzinfo=IST)
    rows = [Row(datetime(2026, 10, 21, 9, 15, tzinfo=IST), 100, 101, 99, 100.5, 1000)]
    fake = FakeYahoo(rows, [])
    asked: list[str] = []

    def actions(symbol: str) -> list[tuple[datetime, float, float]]:
        asked.append(symbol)
        return []

    src = YahooSource(
        FakeClock(ms(now)), CAL, history=fake.history, actions=actions, throttle=no_throttle()
    )
    src.latest_bars(["RELIANCE.NS", "TCS.NS"], Timeframe.M15)
    assert asked == []
    src.fetch_bars("RELIANCE.NS", Timeframe.M15, now - timedelta(hours=2), now)
    assert asked == ["RELIANCE.NS"]  # history downloads still know the splits


def test_indian_index_symbols_are_indian() -> None:
    """D-204: only ^NSEI was known; the Sensex, Bank Nifty, sector indices and India VIX were
    read as US symbols and stamped with US session dates."""
    from backend.core.types import Market
    from backend.data.yahoo import market_of
    from backend.watchlists import catalog

    for sym in ("^NSEI", "^BSESN", "^NSEBANK", "^CNXIT", "^INDIAVIX", "^CRSLDX", "INR=X", "TCS.NS"):
        assert market_of(sym) is Market.IN, sym
    for sym in ("^GSPC", "^VIX", "AAPL", "^SOX"):
        assert market_of(sym) is Market.US, sym
    for row in (*catalog.INDICES, *catalog.GAUGES):
        assert market_of(row[2]).value == row[0], row
