"""The synthetic fixtures are deterministic and contain every awkward case on purpose."""

from __future__ import annotations

import gzip
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.fakes.synthetic import encode_csv_gz, generate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "market"


@pytest.fixture(scope="module")
def generated() -> dict:  # type: ignore[type-arg]
    return generate()


def _rows(rel: str) -> list[list[float]]:
    with gzip.open(FIXTURES / rel, "rt") as fh:
        next(fh)
        return [[float(x) for x in line.split(",")] for line in fh]


def test_committed_fixtures_match_the_generator(generated: dict) -> None:  # type: ignore[type-arg]
    for rel, rows in generated["files"].items():
        assert (FIXTURES / rel).read_bytes() == encode_csv_gz(rows), (
            f"{rel} is stale: run `uv run python scripts/make_fixtures.py`"
        )
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert manifest == json.loads(json.dumps(generated["manifest"]))


def test_universe_size(generated: dict) -> None:  # type: ignore[type-arg]
    markets = [v["market"] for v in generated["manifest"]["symbols"].values()]
    assert markets.count("IN") >= 10 and markets.count("US") >= 10


@pytest.mark.parametrize(
    "rel", sorted(p.relative_to(FIXTURES).as_posix() for p in FIXTURES.rglob("*.csv.gz"))
)
def test_bars_are_sane(rel: str) -> None:
    rows = _rows(rel)
    assert rows, rel
    last_ts = -1.0
    for ts, o, h, lo, c, v, f in rows:
        assert ts > last_ts, f"{rel}: timestamps must strictly increase"
        assert lo <= min(o, c) and h >= max(o, c), f"{rel}: OHLC inconsistent at {ts}"
        assert v >= 0 and f > 0
        last_ts = ts


def test_ten_years_of_daily_history() -> None:
    rows = _rows("US/SPY_1d.csv.gz")
    assert 2400 < len(rows) < 2600


def test_holidays_have_no_bars(generated: dict) -> None:  # type: ignore[type-arg]
    tz = ZoneInfo("Asia/Kolkata")
    days = {datetime.fromtimestamp(r[0] / 1000, tz).date() for r in _rows("IN/RELIANCE_1d.csv.gz")}
    holidays = [date.fromisoformat(d) for d in generated["manifest"]["holidays"]["IN"]]
    assert holidays and not (days & set(holidays))
    assert date(2025, 1, 27) in days and date(2025, 1, 26) not in days


def test_early_close_cuts_intraday_bars(generated: dict) -> None:  # type: ignore[type-arg]
    tz = ZoneInfo("America/New_York")
    early = generated["manifest"]["early_closes"]["US"]
    assert "2025-11-28" in early and "2025-12-24" in early
    bars = [datetime.fromtimestamp(r[0] / 1000, tz) for r in _rows("US/AAPL_5m.csv.gz")]
    on_day = [b for b in bars if b.date() == date(2025, 11, 28)]
    assert on_day[0].strftime("%H:%M") == "09:30"
    assert on_day[-1].strftime("%H:%M") == "12:55"
    normal = [b for b in bars if b.date() == date(2025, 12, 1)]
    assert normal[-1].strftime("%H:%M") == "15:55"


def test_intraday_aggregates_match_daily() -> None:
    daily = {int(r[0]): r for r in _rows("IN/RELIANCE_1d.csv.gz")}
    hourly = _rows("IN/RELIANCE_1h.csv.gz")
    tz = ZoneInfo("Asia/Kolkata")
    first_day = datetime.fromtimestamp(hourly[0][0] / 1000, tz).date()
    hours = [r for r in hourly if datetime.fromtimestamp(r[0] / 1000, tz).date() == first_day]
    assert len(hours) == 7  # 09:15, 10:15, ... 15:15 (the last one is 15 minutes long)
    d = daily[int(hours[0][0])]
    assert d[1] == hours[0][1]
    assert d[2] == max(h[2] for h in hours)
    assert d[3] == min(h[3] for h in hours)
    assert d[4] == hours[-1][4]
    assert d[5] == sum(h[5] for h in hours)


def test_one_minute_covers_last_five_sessions() -> None:
    tz = ZoneInfo("Asia/Kolkata")
    days = {datetime.fromtimestamp(r[0] / 1000, tz).date() for r in _rows("IN/INFY_1m.csv.gz")}
    assert len(days) == 5
    assert len(_rows("IN/INFY_1m.csv.gz")) == 5 * 375


def _event(generated: dict, kind: str) -> dict:  # type: ignore[type-arg]
    return next(e for e in generated["manifest"]["events"] if e["kind"] == kind)


def test_split_is_in_raw_prices_with_factor(generated: dict) -> None:  # type: ignore[type-arg]
    ev = _event(generated, "split")
    rows = _rows(f"IN/{ev['symbol']}_1d.csv.gz")
    i = next(i for i, r in enumerate(rows) if r[0] == ev["ts"])
    before, after = rows[i - 1], rows[i]
    assert before[6] == pytest.approx(1 / ev["ratio"]) and after[6] == 1.0
    ratio = before[4] / after[1]  # raw price roughly halves overnight on a 2:1 split
    assert 1.6 < ratio < 2.5


def test_dividend_drops_the_open(generated: dict) -> None:  # type: ignore[type-arg]
    ev = _event(generated, "dividend")
    rows = _rows(f"IN/{ev['symbol']}_1d.csv.gz")
    i = next(i for i, r in enumerate(rows) if r[0] == ev["ts"])
    assert rows[i][1] == pytest.approx(rows[i - 1][4] - ev["amount"], abs=0.05)


def test_data_gap_sessions_missing(generated: dict) -> None:  # type: ignore[type-arg]
    ev = _event(generated, "data_gap")
    present = {int(r[0]) for r in _rows(f"IN/{ev['symbol']}_1d.csv.gz")}
    assert not (set(ev["ts"]) & present)
    assert len(ev["ts"]) == 3


def test_price_gap(generated: dict) -> None:  # type: ignore[type-arg]
    ev = _event(generated, "price_gap")
    rows = _rows(f"IN/{ev['symbol']}_1d.csv.gz")
    i = next(i for i, r in enumerate(rows) if r[0] == ev["ts"])
    assert rows[i][1] / rows[i - 1][4] - 1 == pytest.approx(-0.08, abs=0.001)


def test_circuit_locked_bar(generated: dict) -> None:  # type: ignore[type-arg]
    ev = _event(generated, "circuit_locked")
    rows = _rows(f"IN/{ev['symbol']}_1d.csv.gz")
    bar = next(r for r in rows if r[0] == ev["ts"])
    assert bar[1] == bar[2] == bar[3] == bar[4] and bar[5] > 0
