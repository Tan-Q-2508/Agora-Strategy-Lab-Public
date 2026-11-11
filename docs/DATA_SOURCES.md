# DATA_SOURCES: where Agora's prices come from

## 1. Sources at a glance

| Source | Used for | Markets | Notes |
|---|---|---|---|
| Yahoo Finance (`yfinance`) | Daily + intraday history, live polling, splits, dividends | India (`.NS`), US | Primary. Unofficial; rate-limited with unpublished thresholds |
| NSE bhavcopy | Daily bars backup + verification | India | Official end-of-day files from NSE archives |
| Stooq | Daily bars backup | US | Free CSV downloads; **blocked since Oct 2026** by a browser check (D-105) |
| Fake source | Tests, replay, cloud development | Both | Deterministic synthetic data |

All sources implement one protocol:

```python
class DataSource(Protocol):
    name: str
    def supports(self, market: Market, timeframe: Timeframe) -> bool: ...
    def fetch_bars(self, symbol: str, timeframe: Timeframe,
                   start: datetime, end: datetime) -> list[Bar]: ...
    def fetch_corporate_actions(self, symbol: str) -> list[CorporateAction]: ...
    def latest_bars(self, symbols: list[str], timeframe: Timeframe) -> dict[str, list[Bar]]: ...
```

Canonical `Bar`: `ts` (UTC epoch ms, bar **open** time), `open`, `high`, `low`, `close`,
`volume`, `source`, `is_final` (False for the still-forming bar; strategies never see
non-final bars).

> Amended 2026-10-24 (D-114): a source is paused for 15 minutes only when it rate-limits Agora or
> after 3 different stocks fail in a row; "no prices for these dates" is an empty answer; a source
> that refuses automatic downloads is left alone for 24 hours.

## 2. Yahoo specifics

**Verify at build time** and record the verified values in `DECISIONS.md`. Commonly
observed limits (they change):

| Interval | Approximate history available |
|---|---|
| 1m | ~last 30 days, max ~7 days per request (fetch in chunks) |
| 2m–30m (incl. 5m, 15m) | ~last 60 days |
| 60m / 1h | ~last 730 days |
| 1d | Full history (decades for large caps) |

Rules:
- **Throttle:** max ~1 request per second by default, batch symbols where `yfinance`
  supports it, and never more than one concurrent request burst.
- **Retry:** exponential back-off on rate-limit or empty responses (2 s, 4 s, 8 s, 16 s,
  then mark the source "cooling down" for 15 minutes).
- **Detect silent failures:** empty DataFrames, all-NaN rows, or timestamps far behind
  now are treated as failures, not "no data".
- **Pin the `yfinance` version** in `pyproject.toml`; Diagnostics shows the installed
  version, with a one-click "update data library" action if Yahoo changes break it.
- Timezone: Yahoo returns exchange-local timestamps; convert to UTC on ingest.
- Use `auto_adjust=False`; store raw OHLC plus split factors (see D-07).

## 3. NSE bhavcopy
- Daily equity bhavcopy files from NSE archives (the format changed to the "UDiFF"
  CSV layout in 2024; implement the current format and keep the parser isolated so it
  can be updated).
- Used to (a) fill daily gaps when Yahoo fails, (b) spot-check Yahoo daily closes
  (flag differences > 0.5% in the fetch log).
- NSE endpoints may require browser-like headers and a session cookie; handle politely
  (low request rate, back-off). If blocked, fall back silently and log it.

## 4. Stooq
_Unavailable since October 2026: Stooq answers automatic downloads with a browser check, which
Agora does not get around (D-105). The code stays; it reports the plain reason._
- Daily US bars as CSV. Used only when Yahoo daily fails. Symbols map as `aapl.us`.

## 5. Live polling (paper trading)
- Poll every `max(timeframe, 60 s)`, scheduled **a few seconds after each bar close**
  (e.g. hh:mm:05) in the market's timezone.
- Request only the symbols with active sessions; batch them.
- A bar is accepted as final only once a later bar exists or the bar's end time has
  passed by ≥ 1 minute (D-48; implemented in `backend/paper/feed.py`).
- Freshness = now − (last final bar's end time). Thresholds in SPEC §7.2.
- During outages: pause new entries, keep monitoring stops on last data, retry with
  back-off, show the banner, and log every transition.

## 6. Universe and survivorship
- Seed `universe_members` with the current Nifty 50 list (verify against NSE's published
  constituents at build time; store the source and date).
- Provide an importer for historical Nifty 50 changes (CSV with symbol, start date, end
  date) so the user, or a later session, can remove survivorship bias. Backtests use
  membership as of each simulated date when history exists.
- Symbol changes and mergers (e.g. renamed tickers) are mapped in an `instrument_aliases`
  table.

## 7. Caching
- `candles` is the single store; a unique key is (`instrument_id`, `timeframe`, `ts`).
- Before a backtest, the cache manager computes the gaps for the requested range,
  fetches only those, and records each attempt in `data_fetch_log`.
- Intraday bars are kept forever (they can't be re-downloaded later). Charts show them
  all (`/candles?full=true`, D-92), so saved intraday history keeps growing on the chart.
- Daily bars older than 7 days are considered final; recent daily bars are re-checked
  once (Yahoo sometimes revises the last bar).
- Higher timeframes may be aggregated from lower ones locally (e.g. 15m from 5m) when
  the lower one has better coverage; the result is marked `source = "derived"`.

## 8. Market calendars
- Use `pandas_market_calendars` for NSE and NYSE sessions, holidays, and early closes.
- Overlay a local `holiday_overrides` table (seeded empty) so a wrong library holiday
  can be fixed without a code change.
- Expose: `is_open(market, at)`, `next_open(market, after)`, `session_bounds(market, date)`.

## 9. Fixtures (for cloud development)
- `scripts/make_fixtures.py` generates seeded synthetic OHLCV for ~10 Indian and ~10 US
  symbols across 1d (10 years), 1h, 5m and 1m, including: a split, a dividend, a gap, a
  circuit-locked bar, a holiday, and an early close.
- Fixtures are small, synthetic, and committed. Real market data is never committed.

## 10. News (Kairos, D-59 and D-68)
News isn't price data, but it comes from outside the laptop too, so it is listed here. All of it
is public and keyless; nothing is read while Agora is closed.

| Source | What | Read |
|---|---|---|
| Economic Times, Mint, Business Standard, Google News (business), MarketWatch, Yahoo Finance | Market news for India and the US | every 10 min while news is in use |
| Yahoo per-ticker feeds (US), Google News searches by company name | One company's headlines | when its chart or news is opened |
| BBC World/Business/India, Al Jazeera, Guardian, NYT, WSJ World, Google News World, OilPrice, Fed and RBI press releases, Mint/ET economy, CNBC-TV18 | World, macro and geopolitical news | every 4 min while the News screen or Kairos is in use |
| GDELT DOC 2.0 API (`api.gdeltproject.org`) | Global news searches (geopolitics, world economy, India), JSON | every 15 min, one request every 6 s (GDELT's limit is one per 5 s) |

A feed that fails is left alone for 15 minutes; failures never stop anything else. Tests use a
fake reader with practice headlines (`backend/news/fetch.py`).

## 11. Stock lists and what the autopilot downloads (Phase 18, D-93, D-99)

- **Lists**: `scripts/fetch_lists.py` (run by Claude in a cloud session, never by the app) reads
  NSE's index constituent files (`nsearchives.nseindia.com/content/indices/*.csv`: Nifty 500,
  Microcap 250 and 33 sector, theme and strategy indices), Wikipedia's S&P 500/400/600 lists (GICS
  sector and sub-industry), Nasdaq's Nasdaq-100 list (`api.nasdaq.com`), Yahoo's search for the
  sector of Nasdaq-100 members outside the S&P 1500, and a fixed Dow 30. It writes
  `backend/seed_data/instruments_{in,us}.csv` with an `as_of` line (2026-10-23). The app never
  fetches lists.
- **Gauges** (Yahoo symbols): `^NSEBANK`, `^CNXIT`, `^CNXAUTO`, `^CNXPHARMA`, `^CNXFMCG`,
  `^CNXMETAL`, `^CNXREALTY`, `^CNXENERGY`, `^CNXPSUBANK`, `NIFTY_FIN_SERVICE.NS`, `^CNXINFRA`,
  `^NSMIDCP` (Next 50), `^CRSLDX` (Nifty 500), `^INDIAVIX`, `INR=X`, `^VIX`; confirming assets USO,
  BNO, GLD, UUP, TLT; sector ETFs XLK…XLC. Checked reachable on 2026-10-23.
- **Autopilot downloads**: daily history (from 2000, like the Charts) for the confirming assets, the
  market's index, the gauges, the US sector ETFs and the broad index (Nifty 200 / S&P 500), then
  every other index stock, then every other listed stock (D-102), 250 new stocks a round, four
  downloads at once (the shared throttle still spaces requests), the next round 20 s later while
  stocks are waiting (every 5 minutes once all are in), each symbol at most once a day; only
  missing candles are fetched (§7).
- **Exchange lists** (D-102, `scripts/fetch_lists.py`): NSE `EQUITY_L.csv` (every main-board
  equity) and Nasdaq's screener API (`api.nasdaq.com/api/screener/stocks`, every US-listed stock
  with sector, industry and market value). Checked reachable from the laptop on 2026-10-24.
- **GDELT window search** (D-96): `startdatetime`/`enddatetime` around a sudden move, at most one
  per move, paced like the other GDELT requests (6 s).

## Faults of the sources, found by the November audit

- Yahoo re-serves Indian hourly candles with volume 0 for the first hour (D-221).
- Yahoo mixes adjusted and unadjusted rows around big splits (D-228); `backend/data/repair.py` handles new downloads.
- Yahoo's last Indian 15-minute candle is one price 28% of the time. Not repairable.
- The US universe is NYSE and Nasdaq only: `backend/seed_data/excluded_us.csv` (D-223).
