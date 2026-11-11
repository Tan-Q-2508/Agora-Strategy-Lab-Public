# DECISIONS: Agora v3.0

Locked decisions. To change one, add a new entry that supersedes it (never edit history).
Format: ID · decision · why · consequences.

---

**D-01 · Stocks only; F&O parked.**
Why: options pricing, expiries and lot sizes made v2.2 large and fragile; stocks deliver a
working lab faster. Consequence: options material lives in `LATER.md`; the data model keeps
an `instrument_type` column so options can return.

**D-02 · No broker, no API keys.**
Why: the user has no Indian broker API; broker-free removes token refresh, ToS risk (Fyers
§11 live-feed conflict from v2.2), and all secrets. Consequence: data comes from Yahoo +
public sources; there is zero order-execution code. `DataSource` stays pluggable so a broker
feed can be added later (see `LATER.md`).

**D-03 · Yahoo Finance (`yfinance`) is the primary data source; NSE bhavcopy and Stooq back
up daily bars.**
Why: no clearly better free, broker-free source covers both NSE and US. Consequences: Yahoo is
unofficial and rate-limits without published thresholds, so caching, throttling, back-off and
fallback are mandatory; data is for personal, non-commercial use only; the UI badges delayed or
stale data.

**D-04 · One engine for backtest and paper trading.**
Why: the most common source of "it worked in backtest but not live" is two different code paths.
Consequence: `backend/engine/` is driven by a `Clock` and a `BarFeed`. Backtest = historical
feed + simulated clock; paper = live feed + wall clock; replay = fixture feed + fast clock.

**D-05 · Local-only app, built in Claude Code cloud sessions.**
Why: free, private, uses the user's GPU for Ollama; GitHub alone cannot host a backend.
Consequence: all external dependencies have fakes; tests run offline; real connections are
exercised only on the laptop (Diagnostics + `@pytest.mark.live`).

**D-06 · No background processes; manual start/stop of paper trading.**
Why: user preference (carried over from v2.2), and simpler to trust. Consequence: sessions
resume on restart but never back-fill missed trades; the gap is shown. *Amended by D-99
(2026-10-23, the user's request): the autopilot may also start Kairos's paper desks when Agora
opens; nothing still runs while Agora is closed.*

**D-07 · Prices: signals on split-adjusted data; fills/P&L on the actual price of the
simulated date.**
Why: unadjusted series break indicators across splits; adjusted series misstate historical
cash amounts. Consequence: the engine keeps both series and an adjustment factor per bar;
dividends are credited as cash on ex-date for held positions; Yahoo's dividend-adjusted
"Adj Close" is not used for fills.

**D-08 · Fill model: decide on bar close, fill market orders at next bar open + slippage;
stops/limits fill intrabar; stop-before-target when both are hit in one bar.**
Why: conservative and look-ahead free. Consequence: `COST_MODEL.md` §4 is the reference.

**D-09 · All statutory charges are effective-dated rows, never constants.**
Why: Indian charge rates change often (carried over from v2.2). Consequence: the cost model
resolves rates by trade date from `charge_schedules`; seeded values must be verified against
official sources at build time and each row stores its source URL.

**D-10 · AI helper = Ollama, default `qwen3.5:4b`, alternative `gemma4:e4b`.**
Why: free and local; the user's RTX 3060 laptop has 6 GB VRAM, and 4B-class models fit with
room for context while 7–9B models are slow or don't fit. Consequence: AI is optional, never in
the trading loop, and uses structured JSON output with validation for strategy drafts.

**D-11 · Golden tests are mandatory for indicators, fills, costs, and metrics.**
Why: the user can't spot numeric bugs. Consequence: each has hand-calculated expected values
in `tests/golden/` with the calculation written out in comments.

**D-12 · Frontend build output is committed.**
Why: the user must never need Node. Consequence: any frontend change includes rebuilding
`frontend/dist/` in the same commit; a check fails if `dist` is stale.

**D-13 · Python environment managed by `uv`; launcher bootstraps everything.**
Why: uv installs the right Python automatically and is fast; the user can't manage Python.
Consequence: launchers install uv if missing, then `uv sync`, migrate, and start.

**D-14 · India universe = Nifty 50 with effective-dated membership.**
Why: survivorship bias. Consequence: until historical membership is imported, backtests show a
survivorship badge.

**D-15 · India intraday positions square off at 15:20 IST by default.**
Why: mirrors broker auto-square-off behavior and keeps simulations realistic.

**D-16 · Theme: light by default (warm off-white, orange accent, matte colors), with a polished
dark mode; fixed-size panels with no overflow.**
Why: user preference from v2.2, now with a "very modern, premium" bar. Final palette is approved
in Phase 1.2.

**D-17 · Single process on port 8765.**
Why: one window, one thing to start and stop. Consequence: the backtest worker uses threads or
a process pool inside the app; the launcher checks the port and shows a plain message if busy.

**D-18 · TradingView cross-checking is parked.**
Why: it needs manual exports or a paid webhook plan, and the user wants no manual steps.
Consequence: listed in `LATER.md`.

**D-19 · The launchers are thin; startup logic lives in `backend/launch.py`.**
Why: batch and shell scripts are hard to test and differ per OS. Consequence: `Start Agora.bat`
/ `.command` only install uv and run `uv sync --frozen --no-dev`, then
`uv run python -m backend.launch`, which checks the port, backs up + migrates + seeds the
database, starts uvicorn in-process, and opens the browser once `/api/health` answers. There is
no module-level `app`; uvicorn uses the `backend.main:create_app` factory so importing the code
never opens the real database.

**D-20 · A daily bar's `ts` is its session open time (UTC ms).**
Why: "ts = bar open" then means the same thing for every timeframe, and a bar's end is simply
min(ts + duration, session close), which is what the no-look-ahead rule needs. Consequence: data
sources normalise Yahoo's midnight-dated daily rows to the session open on ingest (Phase 2.1).

**D-21 · Settings store only values the user changed; defaults live in code.**
Why: a better default in a later version then reaches everyone who never touched it.
Consequence: `backend/settings_store.py` holds each setting's default, one-line explanation and
validator; `PUT /api/settings` is all-or-nothing.

**D-22 · Synthetic fixtures are generated in-house, committed as gzip CSV, and checked for drift.**
Why: tests must run offline and deterministically (D-05). Consequence:
`backend/fakes/synthetic.py` (pure Python, fixed seed) writes `tests/fixtures/market/`; a test
fails if the committed files differ from a fresh run. 21 symbols (10 Nifty + the index, 10 US),
10 years daily (2016–2025), and the last 60 sessions of 1h/5m (1m: last 5) for RELIANCE, INFY,
AAPL and SPY. Their calendar is a simplified fixture calendar, not the real exchange calendar.

**D-23 · Seeded charge rates as of 2026-10-21.**
Verified against published sources: NSE transaction charge 0.00297% from 2024-10-01; SEC Section
31 fee $0.00/M until 2026-04-03 and $20.60/M from 2026-04-04 (SEC fee rate advisory 2026-2);
FINRA TAF $0.000195/share capped at $9.79 from 2026-01-01. Not yet verified (best-known values,
`verified_at` NULL): STT, SEBI fee, stamp duty, GST history, DP charge, the pre-Oct-2024 NSE rate,
pre-2026 FINRA and pre-2025 SEC rows. US rows before 2024 are missing. Phase 4.3 must verify these
and backfill history to at least 2016.

**D-24 · Frontend toolchain versions.**
Vite 8, TypeScript 6, ESLint 10, Vitest 5 (latest at build time). Tailwind v4, shadcn/ui and
Framer Motion are added in Phase 1.3, when the design tokens exist.

**D-25 · Design direction A "Warm Studio" is approved (supersedes the open question in D-16).**
Why: chosen by the user on 2026-10-21 from three directions. Consequence: the tokens in
`DESIGN_BRIEF.md` §10 are final; components use only the token utilities; dark mode uses the
same tokens under `[data-theme="dark"]`. Primary buttons use `accent-strong` (#C4501A) so white
text passes AA; the bright accent (#E8692C) is for charts, focus rings and highlights.

**D-26 · Interim market hours until Phase 2.3.**
Why: the top-bar open/closed pills are needed now, but exchange calendars arrive in Phase 2.3.
Consequence: `backend/markets/basic_session.py` uses weekdays + regular session times +
`holiday_overrides`, and marks results `approximate`; the UI tooltip says holidays come later.
Phase 2.3 replaces its internals with `pandas_market_calendars`; the API shape stays.

**D-27 · Frontend building blocks.**
React Router (client-side routes, served by the SPA fallback), shadcn/ui-style components
written by hand on Radix primitives (`radix-ui`) + `class-variance-authority` (no shadcn CLI, so
nothing is fetched at build time), `cmdk` for the command palette, `sonner` for toasts,
`framer-motion` with `MotionConfig reducedMotion="user"`. Fonts via `@fontsource` (local, no
Google Fonts request: SPEC §11 privacy). Charts and Settings load lazily so the first screen is
fast. Theme choice lives in the `theme` setting (server is the source of truth) and is mirrored
in localStorage only to avoid a flash on first paint.

**D-28 · Yahoo behaviour verified 2026-10-21 (yfinance 1.7.0, pinned).**
Checked against live responses: with `auto_adjust=False`, Open/High/Low/Close **and Volume are
still split-adjusted**, and dividends are split-adjusted too. Daily rows are stamped at local
midnight; intraday rows at the bar open in exchange time; the first NSE 5-minute bar of a session
can report volume 0. Consequence: `YahooSource` converts every bar back to raw prices with the
split list (raw = adjusted ÷ factor, volume × factor) and stores dividends as cash actually paid
per share on the ex-date. History windows used: 1m 29 days (7 per request), 5m/15m 59 days, 1h
729 days, 1d unlimited. NSE's UDiFF bhavcopy (from 8 Jul 2024) columns were verified from a real
file; the legacy layout is used before that. Stooq was unreachable from the cloud, so its parser is
tested on hand-made samples and checked for real by the live tests on the laptop. Stooq's prices
are split- and dividend-adjusted, so its bars are only used to fill gaps (marked `stooq`).

**D-29 · Default history: 11 years of daily bars; intraday = Yahoo's window.**
Why: ten years of backtests plus a year for indicators like SMA(200) to warm up. Consequence:
onboarding and "Refresh now" ask for 11 years back; the cache manager only fetches what's missing
and asks for a session a source genuinely lacks (before listing, real exchange gaps) only once.
Daily bars fetched within 6 hours of the close are re-checked once (Yahoo revises the last bar).

**D-30 · Split factors are known before bars are stored.**
Why: a bar stored with the wrong factor silently breaks indicators across a split. Consequence:
the cache manager fetches each stock's splits/dividends once per app run before its first price
download; adding a split later only rewrites `split_factor`, never raw prices.

**D-31 · Long jobs run on an in-app thread pool and live in memory; the UI polls them.**
Why: one process (D-17), and the results they produce (candles, runs) are already saved as they
go. Consequence: `backend/jobs.py` with `GET /api/jobs/{id}` (polled every 0.5 s by the UI) and
`job.*` events on the event bus for the WebSocket (Phase 6.3). Jobs are lost when Agora closes,
which is fine because nothing runs when Agora is closed (D-06).

**D-32 · Practice-data mode (`AGORA_FAKE_DATA=1`).**
Why: cloud sessions can't rely on Yahoo, but screens must be checked against realistic data.
Consequence: the app can start with the synthetic fixtures and their calendar instead of the real
sources; the Data screen shows a clear "practice prices" banner. The launcher never sets it.

**D-33 · Intraday accumulator runs inside the app, a little after each market's close.**
Why: SPEC §4 wants intraday history to grow; D-06 forbids background processes. Consequence: a
thread started with the app saves 1m/5m/15m/1h candles for the universe once per closed session
(and catches up on start), through the same throttled cache manager. Setting
`intraday.accumulate` turns it off.

**D-34 · Indicator conventions (pinned by golden tests).**
EMA seeds with the SMA of its first n values; Wilder smoothing (RSI, ATR, ADX) seeds with a
simple average; the first true range is high − low; Bollinger uses population standard
deviation; Supertrend's first direction is "up" if the first close is above hl2; Donchian and
Highest/Lowest include the current candle (use an offset of 1 for "previous N candles");
52-week high/low are time-based (365 days) and empty until a full year exists; opening range is
known from the candle that completes it. Divisions by zero give a neutral value (RSI 50,
Stochastic 50, CCI 0). Streaming versions match the vectorized ones to 1e-9 (floating-point
summation order is the only difference), checked on fixtures and random data.

**D-35 · One strategy API for visual and code strategies.**
Why: SPEC §12 requires identical results for the same logic built either way. Consequence: a
visual definition compiles into an `on_bar(ctx)` that calls the same `ctx` helpers code uses
(`ctx.crosses_above`, `ctx.ind.rsi`, `ctx.buy` …); "Open as code" generates that same logic as
readable Python, and a test checks visual == generated code, signal for signal, for every
template. Rule semantics: entries are only evaluated when flat (long before short); in a trade
the signal exit is checked first, then the time limit, then the exit time; one position per
symbol; values that don't exist yet are NaN and any comparison with NaN is false. Numbers in a
definition may be `"$name"` references to named parameters (used by sweeps).

**D-36 · Code-strategy sandbox.**
RestrictedPython plus: a short builtins allow-list (no `open/eval/exec/getattr/type/globals`),
imports limited to `math` and `statistics` (passed as plain namespaces of their public functions),
no classes or `global`, no names starting with `_`, `str.format` blocked. Limits per candle:
200,000 executed lines and 0.5 s of CPU; `range` ≤ 1,000,000 steps; `*`, `**`, `<<` (and their
in-place forms) refuse to build sequences over 1,000,000 items or integers over 10,000 bits.
Everything a strategy can reach is a plain Python value or a small class with underscore-named
internals; numpy objects never leak (numpy scalars can write files). `print` goes to the run's
strategy log. Errors carry the line number and a plain hint.

**D-37 · Indicator values are read through a per-symbol provider.**
Backtests compute each indicator once over the whole history (value i depends only on candles
0..i, so a `SeriesView` ending at the current candle can't look ahead). Live paper trading uses
the same provider, recomputed when a candle arrives, so live and backtest values are identical by
construction; the streaming classes remain available (and tested) for incremental use.

**D-38 · Charge rates verified and back-filled to 2016 (supersedes the "not yet verified" list in D-23).**
Verified 2026-10-21 against primary or broker-published sources (each row stores its URL):
NSE transaction charge 0.00325% (2016–2020, NSE/FA/46730 "existing" top slab) → 0.00345% from
1 Jan 2021 (NSE/FA/46730) → 0.00325% from 1 Apr 2023 → 0.00322% from 1 Apr 2024 → 0.00297% from
1 Oct 2024 → **0.00307% from 1 Mar 2026** (NSE/FA/73061; Zerodha charges page); STT 0.1% delivery
both sides / 0.025% intraday sell (unchanged since 2013); stamp duty 0.015%/0.003% on buys from
1 Jul 2020; GST 18%. SEC Section 31: $21.80 (2016) → $23.10 (4 Jul 2017) → $13.00 (22 May 2018) →
$20.70 (16 Apr 2019) → $22.10 (18 Feb 2020) → $5.10 (25 Feb 2021) → $22.90 (14 May 2022) → $8.00
(27 Feb 2023) → $27.80 (22 May 2024) → $0.00 (14 May 2025) → $20.60 (4 Apr 2026). FINRA TAF
$0.000166/share (cap $8.30) 2024–25, $0.000195 (cap $9.79) from 2026, **paused at $0 for
1 Oct–31 Dec 2026** (SR-FINRA-2026-021, effective on filing), back to $0.000195 from 2027
(SR-FINRA-2026-020). Still best-known only (`verified_at` NULL): SEBI fee history (₹10/crore
today), stamp duty before Jul 2020 (varied by state; today's rates used), service tax before
GST, FINRA TAF 2016–2023, and the DP charge (₹13.00 + GST today: ₹3.50 CDSL + ₹9.50 broker; was
₹13.50 in the original seed). The seed now reconciles `charge_schedules` with this table on every
start, because charge rates are reference data, not user data. Backtests that touch an unverified
row say so in the honesty panel.

**D-39 · Engine conventions beyond COST_MODEL §4.**
Stops/targets are checked on the entry candle too (the position exists from that open). The volume
cap applies to entries only; exits always fill (a rejected exit would leave a trade stuck). No
leverage: longs need the cash; a short's notional plus open exposure must fit in equity. Short
proceeds count as cash and the short is valued at −qty × price. India intraday on daily candles
means "open at the next open, close at that day's close"; on intraday candles the square-off
closes at the open of the first candle at/after 15:20, or at the close of the last candle of the
day if none opens by then. Splits are applied when a stock's split factor changes between candles
(quantity × ratio, prices ÷ ratio). Dividends are credited to cash on the ex-date for delivery and
cash holdings (shorts pay them) and included in that trade's gross P&L. With imported Nifty 50
history, entries are only allowed while the stock was a member. Rounding of each charge follows
contract notes (D-38, `backend/costs/model.py`); GST is charged on the rounded components.

**D-40 · Metric definitions** are in `backend/metrics/performance.py`'s docstring and pinned by
`tests/golden/test_metrics.py`: daily-resampled returns, √252 annualisation, 0% risk-free rate,
sample standard deviation for Sharpe, RMS of negative returns for Sortino, calendar-time CAGR,
drawdown over every equity point, trade statistics on closed trades only.

**D-41 · Robustness tools.**
In/out-of-sample is one continuous run whose results are sliced at the split date (so the
out-of-sample period starts with real open positions, not from flat). A sweep runs every grid cell
(≤ 100) as a child run and re-runs the best cell in full; an "isolated peak" warning appears when
the best cell beats its grid neighbours' average by more than one standard deviation of all cells
and by more than half its own value. Walk-forward picks the best cell on each training window by
the chosen metric (default Sharpe) and runs it on the following test window; test windows are
chained into one equity curve.

**D-42 · What a saved run keeps.**
Top-level runs keep trades, all orders (≤ 20,000; rejections are shown to the user), equity
downsampled to ≤ 5,000 points with drawdown, metrics (including per-symbol and benchmark curve),
honesty warnings, the rule-based summary and a reproducibility record (strategy content hash,
data ranges and sources, charge schedule row ids, engine and yfinance versions, the last 200 log
lines). Sweep/walk-forward children keep metrics and a ≤ 400-point equity curve only. Runs left
"running" when Agora closed are marked failed on the next start (D-06).

**D-43 · Monaco is bundled, not fetched.**
The code editor loads Monaco from `node_modules` through a Vite alias (`monaco-esm`) and a
generated `frontend/src/lib/monacoBundle.ts` that imports only the core editor and the Python
language, so it works offline (no CDN). It is the largest chunk (~4 MB, read from the user's own
disk) and loads only when the code editor opens. Theme colours are normalised to 6-digit
hex because Monaco rejects shorthand like `#fff`.

**D-44 · Heavy screens load on demand.**
The strategy builder, code editor, backtest results, compare and charts screens are lazy-loaded
chunks, keeping the first load small (~580 KB). A page-level error boundary inside the shell shows
a plain-English "This screen ran into a problem" card with Details instead of a blank window.

**D-45 · End-to-end smoke test runs on practice data.**
`frontend/e2e/smoke.spec.ts` (Playwright, Chromium) starts a throwaway backend on port 8798 with
`AGORA_FAKE_DATA=1` and a temporary data folder (`scripts/e2e_server.sh`), then creates a strategy
from a template, backtests it and opens the results. It runs in `scripts/check.sh`; the Windows
`check.ps1` skips it because the helper server script is bash-only.

**D-46 · Paper trades get their own table (`paper_trades`, migration 0002).**
Why: the backtest-vs-live panel and the daily summary need closed trades with entry/exit and
net P&L, which `paper_orders`/`paper_fills` alone can't give without re-pairing fills.
Consequence: same columns as `backtest_trades`, keyed by `session_id`. Data model v3.0 + 1 table.

**D-47 · Practice data means practice replays.**
Why: with `AGORA_FAKE_DATA=1` there are no live prices, but the paper-trading screens still need
to be built, tested and shown. Consequence: in practice mode every paper session runs on its own
fake clock through the last months of the fixtures (daily: 180 days, intraday: 40 days, 1m: 5
days), a few candles per second, and stops itself at the end of the practice prices. The same
runner code drives real sessions on the wall clock; replays are also how tests run sessions.

**D-48 · Live polling rules (DATA_SOURCES §5 made concrete).**
The runner polls 5 s after each candle close. A candle is final once a later candle exists or one
minute has passed since it closed (not one full polling cycle: for 1h candles that would be an
hour late). While the newest closed candle is missing the runner retries every minute (for up to
6 hours, then waits for the next close). Failed polls back off 5/10/20/40/60 s; after two in a
row the session shows "waiting for prices" and pauses new trades. Freshness shown to the user is
"how late the expected candle is": green < 2 min, amber < 10 min, red otherwise; "Market closed"
outside sessions; "Delayed data" when the source's newest candle is two candles behind.
Responses are shared between sessions for 15 s so several sessions don't multiply requests.

**D-49 · What pauses and restarts do.**
A pause (by the user, or late prices) blocks new trades only; exits, stops and square-off keep
running, because leaving a position unmanaged is worse than missing an entry. On restart the
runner restores cash and positions (with their stops) from a snapshot in `paper_sessions.notes`,
reloads indicator history from the session's original history start (so indicators continue
exactly), turns candles from while Agora was closed into history only, records the gap, and
cancels orders that were waiting for a candle that has since passed (D-06). With no gaps, pauses
or late prices, a paper session and a backtest of the same days produce identical trades
(pinned by `tests/paper/test_replay.py`).

**D-50 · One WebSocket per tab, state re-fetched on reconnect.**
The page opens `/ws` when a live screen is shown, reconnects with back-off (1 s → 30 s), and
re-fetches full state after reconnecting; screens fall back to polling while disconnected.
Messages are hints to refresh, never the only copy of any state.

**D-51 · AI model tags checked (2026-10-21).**
`qwen3.5:4b` and `gemma4:e4b` both exist in the Ollama library. `gemma4:e4b` is larger than
the brief assumed (about 6.6 GB or more, with image input), so on a 6 GB card it may spill out of
graphics memory; Settings shows a warning for any model file above 4.5 GB and recommends Qwen.
Download sizes are taken from Ollama's own progress, never hard-coded.

**D-52 · How the AI helper is wired.**
`backend/ai/`: `OllamaProvider` (httpx; `think: false` for short answers; 120 s per reply; a
2 s probe for status, cached 5 s), versioned prompts in `prompts/*.md`, grounded context
builders (`context.py`, readable dates so they can be checked too), the number check
(`numbers.py`: a number in the reply must appear in the data as-is, ×100 or ÷100 within
rounding; counts ≤ 12 and years are ignored; the rest are shown as "couldn't check", not
removed), and the draft loop (`draft.py`: the definition schema's `$defs` are lifted to the top of
the reply schema; Agora fills defaults for anything left out; validator problems go back to the
model at most twice). Explanations stream as Server-Sent Events over POST. Conversations are
stored in `ai_conversations`/`ai_messages` with the prompt name and version. `AGORA_FAKE_AI=1`
swaps in canned replies (the Playwright smoke test uses it); otherwise practice mode still talks
to a real Ollama if there is one.

**D-53 · No "Update data library" button (deviation from RUNBOOK §5).**
Why: `uv add yfinance@latest` would change `pyproject.toml`/`uv.lock` in the user's copy, and the
next GitHub Desktop pull would conflict; `uv pip install -U` would be undone by the launcher's
`uv sync`. Consequence: Diagnostics runs the live data checks and, if Yahoo fails, tells the user
to pull the latest Agora version; library updates ship as normal commits.

**D-54 · Keyboard shortcuts and palette.**
Ctrl/Cmd+K palette (screens, actions, own strategies, recent backtests, running sessions);
"?" shows shortcuts; "G" then a letter jumps to a screen (H, S, B, C, P, T for charts, D, comma
for settings); "N" starts a new strategy; Ctrl/Cmd+S saves and Ctrl/Cmd+Enter backtests in the
builder. Single-letter keys are ignored while typing or when a dialog is open.

**D-55 · Paper sessions keep a bounded history in memory.**
Each stock keeps its newest 3,000 candles (or 4× the strategy's warm-up if longer) in memory, so
a minute-candle session left open for weeks stays as fast as on day one. Older candles stay in
the database. 3,000 candles is far beyond what any indicator needs to settle, so signals are
unaffected in practice; parity with backtests is pinned only for sessions within that size.


**D-56 · Kairos, the trading agent, joins Agora (Phase 9; supersedes D-10's "never in the trading
loop" and SPEC §1's "no news" for Kairos only).**
Why: the user asked on 2026-10-21 for an agent that operates the whole app, analyses charts, reads
news, forecasts, builds strategies and paper trades on its own while learning from its trades.
Consequence: `docs/KAIROS.md` is the reference. Paper money only: there is still no broker code
(D-02). The LLM may start and stop paper sessions the user asked for, but individual orders always
come from deterministic strategy code in the shared engine (D-04), so CLAUDE.md §4's "Ollama output
never places, sizes, or cancels an order" still holds. Kairos acts through the same services the
screens use; there is no hidden path.

**D-57 · Code computes, the model talks.**
Why: the 4B model that fits a 6 GB card picks tools well but can't do arithmetic or long reasoning.
Consequence: chart analysis, patterns, forecasts, scoring and trade decisions are golden-tested
code in `backend/analysis/` and `backend/kairos/`; the model sees compact results and explains them;
replies pass the D-52 number check. Tools are few and high-level so one call does a whole job.

**D-58 · Forecasts are ranges with a measured track record.**
Why: no method reliably predicts stock prices; a single number would mislead a non-technical user.
Consequence: every forecast shows 50%/80% bands and a walk-forward track record (direction hit
rate vs 50%, error vs a no-change forecast, 80% band coverage). Live forecasts are stored and
scored later.

**D-59 · News from free RSS feeds, only while Agora is open (amends SPEC §11 privacy).**
Hosts: feeds.finance.yahoo.com, news.google.com, economictimes.indiatimes.com, livemint.com,
business-standard.com, feeds.content.dowjones.io (MarketWatch). All returned valid RSS on
2026-10-21 (Moneycontrol and CNBC refused automated requests; GDELT rate-limits). No keys, no
accounts. Fetched on demand and every 10 minutes while a Kairos feature is in use; nothing runs when
Agora is closed (D-06). The user can turn news off in Settings.

**D-60 · The Kairos brain is a strategy kind (`"kairos"`), not a special trading path.**
Why: one engine (D-04) and the ability to backtest Kairos like any strategy. Consequence: a
Kairos definition holds its settings and a snapshot of its signal weights; it compiles to a
`Program` whose `on_bar` reads causal signal arrays from `backend/analysis/signals.py`. Backtests
use the snapshot (reproducible); desk sessions refresh weights at the start of each trading day.
News is neutral in backtests (no history) and is flagged in the honesty panel.

**D-61 · Training = measured signal statistics; learning = Bayesian updates from paper trades.**
Why: real fine-tuning doesn't fit a 6 GB laptop and wouldn't teach market edges anyway; measuring
what worked on the user's own data does. Consequence: `kairos_signal_stats` holds per market,
timeframe and signal the history and paper outcomes; weights are Beta-posterior edges over the base
rate (prior: 20 pseudo-trades at the base rate; paper trades count 3×). Lessons (`kairos_memory`)
are rule-based summaries plus the model's reflection when available, and the most relevant few go
into each prompt.

**D-62 · Kairos needs Ollama for conversation, not for analysis.**
Why: the chart toggle, forecasts, scans, news, training and the desk are code and must work for
everyone. Consequence: without Ollama the Kairos panel still accepts common commands through a
rule-based router and replies with templates, and says how to install the AI helper for full
conversation. Tool calling uses Ollama's `tools` field (`/api/chat`, streaming, `role: "tool"`
results with `tool_name`), checked against Ollama's API docs on 2026-10-21.

**D-63 · The brain's signals are computed causally once per series and cached.**
Why: the brain must see exactly what a trader saw on each candle (no look-ahead), and backtests,
research and the desk run it many times. Consequence: `backend/analysis/signals.py` records each
finding on the candle it became known (patterns from confirmed swings, followed to their
breakout; trendline breaks; level breaks/bounces; divergences; candles; momentum, volume and
trend events) plus per-candle trend/momentum/volume readings; computing on a shorter history
gives identical results for the shared candles (tested). Signal sets are cached per series
(64 most recent), so a parameter sweep computes them once. A Kairos backtest equals its
practice replay exactly while the weights are held still (tested).

**D-64 · Kairos paper sessions learn; the reflection stays in the diary.**
Why: learning must come from Kairos's own trades without letting the model's words steer later
decisions. Consequence: every paper session running a `kairos` strategy is a desk: after each save
the runner hands it new positions (a thesis is written) and closed trades (a review is written,
the signals in play at entry update `kairos_signal_stats` source `paper`, ×3, and lessons are
rewritten from the last 20 reviews when a signal's record is clearly good, ≥ 75%, or bad,
≤ 25%, over ≥ 3 trades). Desk weights refresh at the first candle of each day. With the AI
model ready, Kairos adds a one-sentence reflection to the diary; it may only use numbers from
the thesis and review (D-52) and is never stored as a lesson.

**D-65 · Strategy research is out-of-sample first, and Kairos competes without its weights.**
Why: a search over many strategies and settings finds luck unless it is judged on unseen data.
Consequence: tune on the first 70% of the period with a small grid, picking the setting whose
neighbourhood does best (D-41); drop anything with fewer than 5 trades, a non-positive in-sample
Sharpe, a loss on the last 30%, or less than 30% of its in-sample Sharpe there; walk-forward the
best 3 (anchored, 3 folds); rank by out-of-sample Sharpe × min(1, trades/20) plus half the
walk-forward Sharpe. The Kairos brain is tested with equal weights because its learned weights
were measured on the same years; the saved winner gets them back. When nothing survives, Kairos
says so and saves nothing.

**D-66 · Migrations run with foreign keys off.**
Why: SQLite can only change a CHECK constraint by rebuilding the table (0004 widens `strategies.kind`
and `strategy_versions.created_by` for Kairos), and it refuses to drop a table other rows point
at while foreign keys are on. Consequence: `backend/migrations/env.py` turns foreign keys off for
the migration only, runs `PRAGMA foreign_key_check` afterwards (a broken reference fails the
upgrade, and the automatic pre-migration backup stays), then turns them back on. Tested by
upgrading a 0003 database that has saved strategies.

**D-67 · Phase 10: the world's toolkit, held to the same rules as the first one.**
Why: the user asked Kairos and Agora to know "all" indicators, patterns and strategies used
worldwide. "All" is defined as everything in TradingView's built-ins, TA-Lib and StockCharts'
ChartSchool that works on one stock's own prices and volume (no second symbol, order book or
options), every one of TA-Lib's 61 candlestick functions plus common extras, the classic and
harmonic chart patterns with published Fibonacci rules (Gartley, bat, alternate bat, butterfly,
crab, deep crab, cypher, shark, AB=CD, three drives; ratios from capital.com and LuxAlgo, read
2026-10-22, which agree wherever they overlap), the named event setups scanners use, and the
classic strategies that the visual builder can express. Consequence: 58 more indicators (93),
68 more candlesticks (93), 23 more chart patterns (41), a new signal family `setup` (19 setups,
fed to the report, the brain's pattern bucket and training) and 20 more templates (28). Each
indicator has a vectorized and a streaming version and golden tests (chains such as KST, Connors
RSI, Schaff and the squeeze are checked against a brute-force recomputation from the
definition); each candle, pattern and setup has a hand-built golden case; templates compile,
signal identically as visual and code, and trade on practice data in both markets. Where shapes
overlap (a rising wedge with three pushes is also a three-drives top), the textbook name wins
(lower rank for the newer reading). A breakout candle that already covers a pattern's whole
measured move is reported as "target reached", not as a fresh signal. Left out on purpose and
parked in `LATER.md`: diamonds, Wolfe waves, Elliott counts, Gann, TD Sequential, volume
profile, pairs trading.

**D-68 · World news: public feeds plus GDELT, read by rules into a news risk gauge.**
Why: the user wants Kairos aware of business and geopolitical news through an API it can call,
with a page that streams it. GDELT's DOC 2.0 API is free, keyless and global (it asks for at
most one request every 5 seconds; it answered 75 articles per search from the cloud on
2026-10-22, with occasional 429s on the shared address). Consequence: world feeds (BBC World
and Business, Al Jazeera, Guardian World and Business, NYT World and Business, WSJ World, Google
News World, OilPrice, the Fed's and the RBI's press releases, BBC India, Mint and ET economy,
CNBC-TV18 markets; all returned RSS on 2026-10-22; CNBC's US feeds refused) and three GDELT
searches (geopolitics, world economy, India), read six RSS feeds at a time and GDELT 6 s apart,
only while Agora is open and the News screen or Kairos is in use (D-06). Every headline is
classified by a transparent word-rule table (`backend/news/topics.py`): topics, severity 0–5,
impact −1…+1 (the topic's usual direction leans 80% for world/economy news, 30% for company news,
because word tone is tuned on company headlines: "oil surges" is bad for markets), scope and the
sectors it usually moves. Migration 0005 stores topics, severity, impact and scope (older rows
are classified on first read); world headlines are kept 7 days. The gauge (`risk.py`) sums
stories (grouped by topic and shared words) weighted by severity, risk-off reading, recency
(6-hour half-life), market relevance and corroboration (+0.5 per extra publisher, up to 3×),
halving geopolitical stories that never mention markets or the economy (except severity 5), with
each next-heaviest story counting 0.6× the one before and calming stories subtracting.
Calibrated on a real day's 700 world headlines during an ongoing Middle East war: the first,
plain sum read 99 ("severe"), which would have sold everything on any war day; the final design
read about 30 (watchful) with the right top stories, while an invasion confirmed by five sources
still reads 85+.

**D-69 · The news guard: damage control by fixed rules, live only.**
Why: the user wants Kairos to know when to go in and pull out on news, and D-56 forbids the
model from placing orders. Consequence: live Kairos desks (never backtests or practice replays)
hand the brain a `NewsGuard` (`backend/kairos/news_guard.py`) that, for each fresh candle, reads
the gauge and the stock's own headlines and may only block an entry, halve its size, nudge the
score ±10, or ask the brain to close a long. Protective (default): watchful → half size;
elevated → no new longs, losing longs cut; severe → no new trades, longs closed when the
watchlist confirms (−1% on the candle) or the gauge reads 90+; red-flag company news closes that
stock's long. Cautious only blocks entries. Off ignores the news. Shorts keep their stops.
Going back in is the brain's own signals once the gauge cools. Every action is a desk-diary note
("News guard: …"), once per stock, action and day. Daily desks act at the next open (the engine
fills on the candle after the decision); intraday desks react within one candle. The setting is
`kairos.news_guard`.

**D-70 · The knowledge pack must cover everything Agora computes.**
Why: Kairos must be able to explain any indicator, pattern, setup, strategy or news topic it
shows. Consequence: `tests/kairos/test_knowledge.py` fails when any catalog indicator, candle,
chart pattern, setup, template or news topic has no tagged section, when a section has no tags
or is too long for the prompt budget, or when common questions ("what is a Gartley", "what
happens to markets when a war starts", "when should Kairos pull out") don't retrieve the right
section. The pack grew from 47 to 205 sections, including a macro and geopolitics playbook with
verified historical reactions (LPL Research's shock study, 1990, 9/11, 2008, 2020, 2022, the
4 June 2024 election day, Operation Sindoor, the April 2025 tariffs) and India/US circuit-breaker
rules (NSE/BSE and SEBI pages).

**D-71 · Kairos's trade check: a learned filter in the shared engine that must earn the right
to skip.**
Why: the user asked Kairos to "improve the quality of trades, not just depend on a fixed
strategy", to "use a real brain to decide if the strategy is right at the moment" and to raise
win rates, while D-56 forbids the AI model from placing, sizing or cancelling orders.
Consequence: `backend/kairos/quality.py` is deterministic code plugged into the engine
(`Engine.check`), so backtests and paper trading judge identically (D-04). For each entry signal
it reads ten catalog readings on the signal candle (ADX, choppiness, RSI, ATR %, relative volume,
20-candle z-score, distance from the 50- and 200-candle averages, stochastic %K, Kairos's score),
turned round for shorts, and estimates the chance of a win after costs with a shrunk,
third-by-third naive-Bayes model (prior 10 pseudo-trades per third, damping chosen by
leave-one-out). Modes: off, learn (never skips), balanced (skip clearly-worse-than-usual or
negative expected value), strict (good-chance trades only, never fewer than the best ~30%).
Skipped signals are followed anyway (shadow trades over the typical holding time, minus typical
costs, half weight) so wrong rules are unlearned. It skips nothing until it has **proven
itself**: at least 30 judged results with a Brier skill above 0.02 against "every trade is the
usual trade", measured prequentially (each block judged by a model fitted only on what was known
before it). Rationale: on practice data (random prices) an unproven strict check cut 205 trades
to 81 and lowered profit; with the proof rule it stays hands-off there, and engages on real
structure (tested). Seeds are samples known before the run's first candle and saved before it
started (`kairos_trade_samples`, migration 0006), so a run never learns from its own future.
Defaults: backtests and user paper sessions off (opt in per run); Kairos desks use the
`kairos.trade_check` setting (balanced).

**D-72 · Reviews of trades and "Improve with Kairos": judged on trades the rule never saw.**
Why: the user saw backtests whose profits vanish after costs, strategies that live on a few big
winners, and trades that failed although every rule was met; he wants Kairos to find out why and
keep improving the strategy. Consequence: `review.py` reads closed trades with the candles around
them: costs versus gross profit, win rate versus the break-even win rate implied by the
win/loss sizes, dependence on the best three trades, exits (stopped within two candles, losers
that were ahead by an ATR), market conditions where losses concentrate (a third is named only
when its shrunk rate is 8+ points under the overall rate and z ≤ −1.3), and single-reading
filters chosen on the first 60% of trades and judged on the last 40%. `improve.py` adds up to
two filters that held up as ordinary entry conditions (turned round for shorts), backtests, and
saves a new version only if, after the 60% point, it made at least as much after costs, won 2+
points more often and kept 30%+ of the trades. Earlier versions are always kept. Code strategies
and the Kairos brain are never rewritten; the trade check serves them instead.

**D-73 · Predicted candles that learn from their misses, and a learner that runs while Agora is
open.**
Why: the user asked Kairos to draw the likely next candles from analysis, news, trend lines and
patterns, to compare them with the candles that formed, and to keep learning on its own.
Consequence: `forecast.py` gains a fourth model, the **analyst** (a ridge fit, causal via prefix
sums, of the next H candles' move in volatility units on Kairos's score; live forecasts lean it
by the stock's own news, ±10 score points, and widen every model by up to 50% when the market's
news risk is high), and **calibration from misses**: width = the 80th percentile of past misses
in 80%-half-range units, bias = their mean, both shrunk (n/(n+20), n/(n+30)) and clipped; the
walk-forward applies it using earlier misses only, and scored live forecasts count 3×. Predicted
candles follow the **typical path** (the sampled path closest to the middle path), because the
middle path itself is nearly flat and would draw a row of dojis; wick sizes come from the
stock's own last 60 candles. Every shown forecast stores its candles, each model's range and the
raw middle/half-range (`kairos_forecasts.detail`, migration 0006); when its candles form it is
reviewed candle by candle (`review`) and its miss and model losses feed the next forecast. With
no saved prediction yet, the chart shows a **re-created** one (made with only the data known then,
clearly labelled). `autolearn.py` runs a round every ~10 minutes while Agora is open and
`kairos.keep_learning` is on (D-06: never when closed): reviews new backtests and paper trades,
improves strategies (`kairos.auto_improve`, at most one a round and once a week each), forecasts
and checks a few watchlist stocks, and re-studies signal history; it yields to running
backtests and research. Practice-data sessions (tests, the cloud) don't start its thread.

**D-74 · Futures and options: knowledge and an options calculator, no F&O trading.**
Why: the user asked to "train Kairos on all the F&O and F&O strategies" although Agora has no
F&O. Fine-tuning doesn't fit the laptop (D-61), so "training" means the knowledge pack plus
code that computes the numbers (D-57). Consequence: three playbook files (62 sections: Greeks,
pricing, IV, OI, PCR, max pain, expiry, margins, hedging, 30+ strategies, India and US rules
and costs) with facts checked on 2026-10-22 (SEBI's 1 Oct 2024 and 29 May 2025 circulars, NSE's
3 Oct 2025 lot sizes, the 1 Sep 2025 Tuesday/Thursday expiry swap, the Budget 2026 STT rise
effective 1 Apr 2026, SEBI's FY25 and FY26 loss studies, FINRA's 2026 PDT change); and
`backend/analysis/options.py` (Black-Scholes-Merton with dividends, CRR binomial for American
options, bisection implied volatility, 32 named strategies, payoff, unlimited-risk detection,
break-evens, lognormal chance of profit, Greeks), golden-tested on textbook values, behind a
Kairos tool `option_strategy` with a payoff chart card. Premiums are estimates from the stock's
own volatility and say so. F&O data, backtests and paper trading stay in `LATER.md`.

**D-75 · The logo: a Λ roof with one candle under it.**
Why: the user asked for a thoughtful logo instead of a plain "A". Consequence: the mark is a
Greek capital Λ (the roof of the agora's stoa, and the shape of the A) with a single candlestick
standing under it whose body sits where the A's crossbar would be (the market, and the decisive
moment). Ink tile with a parchment Λ and an orange candle in the light theme; a lifted charcoal
tile in the dark; thicker strokes at 24 px and below so the candle still reads as the crossbar.
The Kairos mark is the same candle inside a ring that opens just before one o'clock. Designed on
a Claude Design canvas (`docs/DESIGN_BRIEF.md` §11); four other concepts were rejected (a temple
of candle columns read as a generic bank icon, a triangle with a baseline as a warning sign).

**D-76 · Metis, Kairos's AI researcher: the AI proposes, code tests, and only what holds up on
unseen years is kept (Phase 12; amends D-61, keeps D-56 and D-57).**
Why: the user asked on 2026-10-22 for Kairos to be a real AI agent that learns on its own; until
now its learning was measurement only, and the model never came up with anything. Fine-tuning
still doesn't fit the laptop (D-61), so the AI's part is the creative step: reading the evidence
and proposing ideas. Consequence: `docs/METIS.md` is the reference. Each round, code builds a
brief from the **study years only** (the first 70% of each strategy's period: trades, costs, win
rate, exits, Kairos's review of those trades), plus the notebook of Metis's past verdicts; the
model (thinking on) proposes up to three ideas of three kinds (`filter`, `tweak`,
`new_strategy`); code turns them into valid rules (new strategies through the D-52 draft loop)
and backtests them in the shared engine. A strategy change is kept only if, after costs, it made
more in the **exam years** (the last 30%, never shown to the model) by ≥ 0.1% of the starting
money, at least as much in the study years, and kept ≥ 5 and ≥ 30% of the exam trades; a new
strategy only if it made money in both parts with ≥ 5 trades each and an exam profit factor
≥ 1.1. Kairos's lessons and signal statistics are left out of the brief because they were
measured on all years. Kept ideas become new strategy versions (old ones kept) or new strategies
("Metis · …") when `metis.apply` is on, start a full backtest, and become Kairos lessons written
by code from the test's numbers. Metis never places, sizes or cancels orders, never starts paper
sessions and never changes the Kairos brain or code strategies' code (parameters only).

**D-77 · Metis works on its own while Agora is open, off by default, and gives way to the user.**
Why: the user wants it automatic once switched on, but it shares the 6 GB graphics card with the
Kairos chat. Consequence: `metis.enabled` (default off) starts a thread that runs a round every
`metis.every_minutes` (default 20; first round 2 minutes after opening or after switching on)
only while Agora is open (D-06). It waits while the AI helper isn't ready, while a backtest,
research, training or improvement job runs, and for 60 seconds after the user last talked to
Kairos. **Research now** runs a round on demand even when the switch is off. An optional
`metis.focus` steers it; empty means it chooses. Practice-data sessions start the thread only
with `AGORA_METIS=1`.

**D-78 · Every user request is recorded and documented.**
Why: the user's standing instruction (2026-10-22): "anything I ask you to do must be added to
spec or changelog or added as a new phase and well documented." Consequence: `CHANGELOG.md` lists
every request (date, what was asked, where it is documented, status), back-filled to 2026-10-20;
each request is also written into `SPEC.md`, a `PROGRESS.md` phase or task, and its own doc.
CLAUDE.md §1–2 make reading and updating it part of every session.

**D-79 · Revisions, not copies: a strategy is its logic (Phase 13).**
Why: the user asked on 2026-10-22 that whenever Kairos or Metis improve a strategy it be up-revved
under revision control, never saved as yet another strategy, "unless they are different
strategies". Until now Metis's new-strategy ideas and every Kairos research run created a new
strategy, even when it was the same logic with other numbers. Consequence: `docs/REVISIONS.md`.
`backend/strategy/lineage.py` decides "same strategy" structurally (same market and kind; entry and
exit rules as tokens of indicator, direction and operand kind, numbers ignored; similarity ≥ 0.75,
or a filtered variant with ≤ 2 extra conditions, or the same template; code identical without
numbers; one Kairos brain per market). Kairos and Metis save through one gateway
(`backend/strategy/revisions.py`): identical → reuse; same family → next revision (only after it
beat the current revision on that strategy's own stocks); different → new strategy, Metis at most
`metis.new_per_day` (default 2) a day. Revisions record author (`user`, `ai_draft`, `kairos`,
`metis`), parent, plain-English changes (`backend/strategy/diff.py`), evidence and source
(migration 0008). Restore = a new revision copying an old one; history is never rewritten. The
user's own saves in the builder are unchanged except that they also record changes.

**D-80 · The same strategy on other stocks is an opportunity, not a strategy.**
Why: a strategy is its logic (D-79), so trading it on other stocks, or with settings tuned for
those stocks, must not create strategies or churn its revisions. Consequence: an opportunity is
(revision, stocks, optional parameter overrides) with its evidence, stored in `opportunities`
(migration 0009). Backtests (`BacktestRequest.overrides`), paper sessions (`SessionIn.symbols`,
`overrides`, `size_pct`, kept in the session's notes) and portfolio sleeves can run a revision that
way. Kairos's research winner becomes an opportunity when you already have its strategy; Kairos
paper trading a strategy on other stocks no longer saves a version (amends Phase 9's
`start_paper_trading`).

**D-81 · Metis is a senior quant: a library, a toolkit, the expert's first look, and playbook
rounds without the AI (amends D-77).**
Why: the user asked on 2026-10-22 that Metis already have the knowledge and practical skills of a
PhD quant researcher with 10–15 years' experience, so it doesn't start from scratch. A 4B local
model can't hold that (D-10, D-61), so the expertise lives in Agora, tested, and is handed to the
model when relevant (as D-57 does for Kairos). Consequence: METIS §11–15: the quant library
(`backend/metis/library/*.md`, BM25-retrieved; Kairos can read it too), the toolkit
(`backend/quant/`, golden-tested, no new dependency: stdlib `NormalDist` and numpy), the expert's
first look (`diagnose.py`: findings and ready-to-test first experiments from study-year evidence
only), a persona with the research method, and **playbook rounds** when the AI helper isn't ready
(they test the first experiments, the templates the user doesn't have and the scanner), so Metis
keeps working on laptops without Ollama. With the AI, unusable answers fall back to the playbook.

**D-82 · The luck check: deflated Sharpe ratio on every Metis verdict and portfolio candidate
(amends D-76).**
Why: many ideas tried on the same exam years find some by luck (METIS §4); a senior quant deflates
for the number of trials (Bailey and López de Prado, 2014). Consequence: for a change, the exam-year
daily return differences against the current version; for a new strategy or a portfolio candidate,
its own exam-year daily returns. N = tries on that strategy (or in that market, or candidates in
the plan) including this one; the bar is the expected best Sharpe of N null tries,
√(1/T)·((1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(Ne))); the probabilistic Sharpe ratio against it (with skew and
kurtosis) must be ≥ 0.5. It is a fourth rule beside D-76's three; its probability is shown.

**D-83 · Metis's research agenda: four directions chosen by Thompson sampling; simplify and
universe ideas; a complexity limit.**
Why: the user asked whether Metis only improves strategies or also searches for new ones, hoping
for both; and RD-Agent(Q) and AlphaAgent (LANDSCAPE §2) show that an explicit direction scheduler
and complexity/originality limits make automated research better. Consequence: METIS §13. Each round
picks improve-in-use, improve-others, discover, or opportunities by Thompson sampling on each
direction's kept/tested record (Beta(1+kept, 1+failed), random draw seeded by the round number),
with in-use at least every third round and opportunities at least every fourth; a focus naming a
strategy forces improve. New idea kinds `simplify` (remove one entry condition; kept when exam ≥
current and study ≥ 95%) and `universe` (add/drop ≤ 3 stocks). Filters may compare an indicator with
the price. At most six entry conditions per side. `metis_rounds.direction` (migration 0008).

**D-84 · The portfolio: one budget, sleeves, allocation by tested code.**
Why: the user asked on 2026-10-22 that Kairos and Metis keep finding opportunities and allocate a
budget (e.g. $1,000 or ₹1 lakh) intelligently as one collective portfolio, not the full amount per
stock. Consequence: `docs/PORTFOLIO.md`. A portfolio (one market, a budget, a risk level) is split
into sleeves (revision × stocks × money) and a cash reserve. The allocator screens candidates on
exam-year evidence and the luck check, scores by exam Sharpe × luck-check probability, picks greedily
skipping correlation ≥ 0.7, weighs by HRP (≥ 3) or inverse volatility on a Ledoit–Wolf covariance
of study-year returns, tilts by evidence, caps per sleeve, targets the risk level's volatility,
and drops sleeves the budget can't fund (dearest price × max open trades × 1.05). Inside a sleeve
each trade gets an equal share (sleeve money ÷ max open trades): sizing belongs to portfolio
construction, as in LEAN. Every number and reason comes from code; the AI never sets weights (D-56).

**D-85 · Portfolio backtests: sleeves in lockstep in the shared engine, monthly rebalancing that
moves only free cash.**
Why: "portfolio-level backtests" were parked (`LATER.md`); the portfolio needs them, and D-04 must
hold. Consequence: one `Engine` per sleeve, stepped together over the union of their candle times;
`Engine.transfer(amount)` moves cash in or out (out only up to free cash: cash not needed by
pending entries, never below zero), applied before the first step of a new month and on drift >
25% of target. Portfolio equity = sleeves' equity + reserve. Metrics as SPEC §6.3, plus each
sleeve's contribution and the money moved. Every portfolio backtest carries the selection-bias note.

**D-86 · Paper portfolios: a session per sleeve, managed by code while Agora is open.**
Why: the user wants it automatic, while D-06 (nothing runs when closed) and D-56 (AI never trades)
hold. Consequence: **Paper trade this portfolio** starts one paper session per sleeve (its stocks,
settings and trade size in the session's notes) and keeps the reserve as portfolio cash. The
portfolio manager (a thread while Agora is open, checked every minute) rebalances monthly and on
drift with `PaperRunner.transfer` (recorded in the session's notes, so P&L counts money moved in
and out), and, with **Manage on its own** on (default), reviews monthly: winds down a sleeve whose
live loss exceeds twice its backtest's worst drop or that the plan drops after a month (paused for
new trades; stopped and returned to the reserve once flat) and adds sleeves the plan picks, funded
from the reserve. It only acts on portfolios the user started paper trading. Orders still come only
from the strategies in the shared engine.

**D-87 · The landscape: take each tool's best idea that fits Agora's rules.**
Why: the user asked on 2026-10-22 to find similar AI and coded tools and make Agora the best of
them. Consequence: `docs/LANDSCAPE.md` lists 22 tools in 8 groups, what Agora takes from each and
where (Phases 13–15 build most of it; Phase 16 holds the rest), and what it deliberately doesn't do
(brokers, real money, cloud AI, AI deciding trades). It is re-checked when the user asks again.

**D-88 · The look-ahead check: run the rules, don't read them; and shift() only looks back.**
Why: LANDSCAPE §4 task 16.1 (Freqtrade's lookahead-analysis and recursive-analysis). Agora's runtime
already hides future candles from `SeriesView`, but a check that *runs* the strategy proves it for
any code, brain or future indicator, and finds the subtler problem of rules that depend on how much
history is loaded. Consequence: `backend/strategy/lookahead.py` (pure) and `backend/checks/lookahead.py`
(the job). The rules are traced (each stock alone, from the tested period's first candle, compiled
afresh for every run) on the whole period and on growing slices ending at their signals and at eight
evenly spread candles (at most 40 slices a stock, 150,000 candles and 90 seconds in all); every
signal and every named-price indicator value up to a slice's end must match the full run (relative
tolerance 1e-9). Then once more with at least 250 more older candles: signals in the period must
match; indicators still differing by more than 0.1% are noted. Verdicts: clean · lookahead · history
· no_data, saved in `strategy_checks` (migration 0010) per version; up to 8 stocks. A hole found while
building it is closed: `SeriesView.shift(k)` with a negative `k` read later candles in code
strategies; it now raises a plain error ("shift() only looks back").

**D-89 · Tear sheets and the probability of backtest overfitting.**
Why: LANDSCAPE §4 tasks 16.2 (pyfolio / QuantStats) and 16.3 (mlfinlab): one page and one number for
"how much could be luck". Consequence: `backend/metrics/tearsheet.py` computes, from each run's daily
equity, the Sharpe ratio with a 90% stationary-bootstrap band (400 resamples, mean block 10 days,
vectorised, seeded), PSR, DSR over a sweep's cells, the minimum track record, bootstrap yearly-return
and worst-drop ranges, the trade-order Monte Carlo, the 126-day rolling Sharpe, the five deepest
underwater periods, historical VaR/CVaR at 95% (the ⌈n·5%⌉-th worst day and the mean of the worst
ones), tail ratio, best/worst day and month, winning months, skew, kurtosis and yearly returns, plus
a rule-written summary; saved in `metrics.tear_sheet` with every run (`GET /backtests/{id}/tearsheet`
works it out for older runs). `backend/quant/overfit.py` is CSCV (Bailey, Borwein, López de Prado and
Zhu, 2017): S = 16 blocks (fewer for short histories, at least 4 days a block), all C(S, S/2) halves,
Sharpe ratio per half, ω = the in-sample winner's average rank out of sample ÷ (N + 1), PBO = share
of halves with ω ≤ ½, plus the out-of-sample loss rate and the degradation slope. Sweeps report it
(`metrics.sweep.pbo`, an `overfit` warning at ≥ 50%). Metis keeps each tested idea's daily returns
and, once a strategy has 8 or more tries (ideas plus the versions they were tested against), a change
must also pass "PBO below 50%" (a fifth rule beside D-76's three and the luck check, D-82); new
strategies likewise over the new strategies tried in their market.

**D-90 · Forward checks: re-test what was saved on candles formed after it, and undo what stopped
holding up.**
Why: LANDSCAPE §4 task 16.4 (Trade Ideas' Holly re-tests nightly); `LATER.md` had parked re-checking
Metis's kept ideas on new data. Candles formed after a save were seen by no test, so they are the
fairest exam. Consequence: `backend/checks/forward.py`. Subjects: versions authored by Kairos or
Metis with a parent, saved in the last 400 days, while they are their strategy's newest version (not
the put-back versions themselves); and portfolio sleeves (active in a paper portfolio, planned in a
draft). Each is checked at most once a day by Kairos's always-on learner (two per round) or on
**Check now**, once 20 trading days and 4 trades have formed. A revision is backtested against its
parent from its save to now: holding when it made at least as much; failed after 40+ days when it
made less by more than 0.1% of the money and the daily difference's PSR says ≥ 80% it is worse;
otherwise slipping. A sleeve is backtested from when it was added and compared with its exam years
(z-test on the mean daily return): failed after 40+ days with a loss and ≥ 97.5% likely below the
exam years. Undo: the parent's rules are saved again as a new version (author kept when automatic,
source `forward-undo:<check>`), on its own with setting `revisions.auto_undo` (default on); a sleeve
is wound down (paper, when the portfolio manages itself) or taken out of a draft plan; Kairos gets a
lesson. Orders still come only from strategies in the shared engine (D-56).

**D-91 · Ranking strategies: cross-sectional momentum and low volatility in the shared engine.**
Why: LANDSCAPE §4 task 16.5 (Portfolio123, Quantpedia): the best-documented anomalies compare stocks
with each other, which per-stock rules can't. Consequence: a strategy kind `ranking` (migration 0010)
with `ranking: {rank_by: momentum | low_volatility, lookback_months 1–24, skip_months 0–3, hold 1–30,
trend_filter}` as plain numbers (not swept), daily candles, delivery/cash; sizing (95% ÷ hold of the
money each) and the open-trade limit (2 × hold, so a rebalance day's sells and buys can overlap: sells
fill first at the next open) are derived. `backend/strategy/ranking.py`: on the first trading day of
each month the program ranks every stock the engine holds (`Program.bind`, called by `Engine`) from
split-adjusted closes up to that candle (momentum: close 21·skip days ago ÷ close 21·lookback days
ago − 1, only risers with the filter; low volatility: minus the annualised spread of daily log moves,
only above the 200-day average with the filter), skipping stocks outside the index on the day and
stocks without a candle for 10 days, and holds the top `hold`. Templates `momentum_top` (12-1, 10),
`momentum_fast` (6-1, 5), `low_volatility` (6 months, 10), kept apart from the 28 rule templates.
Sameness: same `rank_by` = the same strategy (other numbers are revisions). Portfolios gained a
`method`: mix (the allocator, default) or momentum / low_volatility: one sleeve running the ranking
on the whole index (`symbols: []`), sized by the risk level's cash reserve and volatility aim, with
the exam-year screen reported rather than enforced (the user chose the method). The opportunity
scanner judges ranking strategies as a whole on the index, so the allocator can mix them in too.
Metis and Kairos's improver leave ranking strategies alone.

**D-92 · Charts load all the history there is, on every timeframe including 1 minute.**
Why: the user asked (2026-10-23) for a 1-minute option on Charts and for history "till whatever
available". Consequence: `GET /candles` gained `full=true`: with no `start` it fetches from
`service.full_start_ms` (daily: 2000-01-01, where the market calendars begin; intraday: Yahoo's
window, as before) and reads from the oldest stored candle if that is older, so intraday candles
saved by the accumulator (SPEC §4) stay on the chart after Yahoo drops them. The Charts page asks
for `full` with `limit=50000` (newest kept), offers 1 minute, and opens zoomed to the old fixed
windows (`VIEW_DAYS`: 730/120/30/10/3 days, at least 30 candles) via `PriceChart.initialFrom`;
indicator lines cover the whole loaded stretch, Kairos still reads only the recent stretch so it
stays quick. Older intraday days are never re-downloaded; days Agora was closed past Yahoo's
window stay missing.

**D-93 · Stock profiles: the GICS sectors in both markets, industry, size by index, exposure tags.**
Why: the user asked (2026-10-23) for sector, size and index watchlists and for Kairos and Metis to
know sectors and how world events reach them; that needs every stock's kind, the same way in both
markets. Consequence: `instrument_profiles` (migration 0011) for every stock in the official lists
fetched by `scripts/fetch_lists.py` (run by Claude, never by the app) into
`backend/seed_data/instruments_{in,us}.csv` with an `as_of` line: India's Nifty 500 and Microcap 250
plus 33 sector/theme/strategy indices (NSE's constituent files, NSE's industry), the US S&P 500, 400
and 600 (Wikipedia's lists, which follow S&P's notices, with GICS sector and sub-industry), the
Nasdaq-100 (Nasdaq's own list; members outside the S&P 1500 get their sector from Yahoo's search)
and the Dow 30. **Sector** = the 11 GICS sectors (NSE industries mapped); **size** = by index: India
large Nifty 100 / mid Midcap 150 / small Smallcap 250 / micro Microcap 250 (SEBI's lines), US large
S&P 500 (and Nasdaq-100) / mid S&P 400 / small S&P 600; **exposure tags** (`taxonomy.TAGS`:
oil producer, fuel retailer, oil user, airline, exporter, defence, bank, rate-sensitive,
China-exposed, semiconductors…; 54 in all) from the GICS sub-industry, NSE's industry and short hand-checked
company lists where the industry is too coarse. About 2,300 stocks are added as instruments when
Agora first opens after the update (`WatchlistService.start`, ~1 s, once per seed fingerprint); 54
US and 9 Indian ETFs and 16 market gauges (Nifty sector indices, India VIX, USD/INR, VIX) too.
News matching keeps using every active stock. REITs/InvITs are left out of India.

**D-94 · Watchlists: yours, ready-made, and the ones Kairos and Metis make, with their reasons.**
Why: the user asked for ready-made lists (sector, size, index, "others which big quant firms have")
besides his own, and for Kairos and Metis to make lists when their analysis says so. Consequence:
`watchlists` and `watchlist_items` (migration 0011). Kinds: `custom` (editable), `ready` (110 lists
from `catalog.py`: 36 indices, 22 sectors, 7 sizes, 17 factor lists, 22 themes, 6 ETF lists),
`kairos`, `metis` (named "Kairos · …"/"Metis · …", a `reason` and a note per stock). Factor lists
are the exchange's own smart-beta indices (Nifty200 Momentum 30, Nifty100 Low Volatility 30,
Nifty200 Quality 30, Nifty Alpha 50, Dividend Opportunities 50) and six price factors per market
worked out from saved daily candles at most once a day (`factors.py`: 12-1 momentum, low volatility,
near the 52-week high, trend template, short-term reversal, 3-month relative strength), the way
quant funds build factor portfolios; quality and value need fundamentals Agora doesn't have, so the
US uses the factor ETFs (MTUM, QUAL, VLUE, USMV…) for those. Agents save through
`save_for_agent`: same name = update in place; at most 3 new lists a day each and 12 kept (oldest put
away); they never touch the user's lists. Kairos can take a list's name wherever it takes stocks
("backtest RSI on the Nifty IT list", at most 30 stocks). The opportunity scanner also scans the
stocks the agents' and factor lists brought in that have prices (≤ 100 a market).

**D-95 · The world desk: a map of world events, trained on past events, learning from live ones.**
Why: the user asked for Kairos and Metis to be proficient in geopolitics: events in one corner of the
world affect US and Indian markets directly or indirectly; train on all the history of geopolitics
that moved markets; correlate; read the internet; be self-learning. Consequence: `backend/world/`.
`scenarios.py`: 33 kinds of event (Middle East war, a shipping chokepoint, Russia–Ukraine,
India–Pakistan, India–China, Taiwan, US–China trade, US tariffs on India, broad US tariffs, OPEC
cuts, oil crashes, Fed and RBI moves, hot US inflation, recession fears, China stimulus or slump, a
banking scare, a rupee slide, a yen carry unwind, pandemics, disasters, the monsoon, US and Indian
politics, a major terror attack, defence spending, nuclear threats, sanctions, cyber attacks, AI
spending shocks), each with
how to recognise it in a headline (news topics, places, words, minimum severity), the chain of
effects in plain steps, effects −2…+2 per market on the market, GICS sectors and exposure tags, and
the confirming assets. `history.py`: 87 dated past events since 1990 with kind and direction (no
claimed reactions). `learn`: every past event is measured on saved prices (1, 5 and 20 trading days
from the close before the news; the market's plain return; sectors and exposure groups as excess
over the market; calming events counted in the escalating direction) into `world_effects`
(`source=history`, Welford means, hits = moved the way the map said), re-done when saved prices grow;
every live event (`world_events`, grouped per scenario within 72 hours, strength = severity × 24-hour
half-life × a half for repeat publishers, ≥ 3 to count) is measured once each horizon has passed
(`source=live`, counted twice when pooled). Effects shown are the map's value pulled toward the
measured mean (1 unit = 1% excess over 5 days) with weight n/(n+3), scaled by 1 − e^(−strength/8).
A stock's tilt = market + its sector + its strongest tag; "helped"/"hurt" are relative to the
market. Reads only saved headlines (RSS feeds and GDELT, D-59/D-68); a new geopolitics file in
the knowledge pack (27 sections) and a Metis library file (event studies, GPR, oil
shocks, industry momentum, timeframe filters) carry the knowledge. A thread wakes every 5 minutes
while Agora is open (real data; `AGORA_WORLD=1` elsewhere). Code reads and measures; the AI only
explains when asked. The desk's orders are unchanged (no world-based trading rule in the brain).

**D-96 · "Why did it move?": the move investigator.**
Why: the user asked that when the whole market or a sector dips suddenly, Kairos investigates which
event caused it, beyond charts and maths. Consequence: `world/investigate.py` + `WorldService`. Every
30 minutes (and on request) the latest daily candle of the benchmark and of each sector's
equal-weight line is checked: unusual = |move| ≥ 2.5 × the last 60 moves' standard deviation and
≥ 1.2% (market) / 2.0% (sector). Each unusual move is investigated once: on the laptop GDELT is first
searched for that time window (`gdelt_window_url`, stories land in `news_items`); every headline
from 30 hours before the move to 6 hours after scores severity/5 × timing (before/during 1, decaying
past 18 h lead; after ≤ 6 h 0.8) × relevance (own market 1, world 0.8, other 0.4; for a sector,
scenario effect on it, member company news or matching sectors, else 0.3) × direction (agrees 1,
neutral 0.6, against 0.25) × 1.15 for a market report published during the move; grouped into causes
(scenario, else topic, else company) with diminishing returns and +25% per extra publisher (≤ 3);
×1.3 when the confirming assets moved the scenario's way (oil, gold, dollar, VIX, US yields via TLT,
the rupee via USD/INR), ×0.8 when they contradict it. Contagion: the other market's latest move with
|z| ≥ 2 the same way. Verdict news/world/contagion/unclear (top score < 0.2: "no news explains it
clearly: flows, expiry, levels"), confidence high/medium/low, saved in `move_investigations` with the
causes; a plain paragraph answers "why did it fall?". Intraday moves are left for later (daily
candles only).

**D-97 · Several timeframes: bigger charts in strategies, the brain and the chart reading.**
Why: the user asked for Kairos and Metis to analyse multiple timeframes of the same stock: "better
quality trades and fewer false alarms" (multiple timeframe / top-down analysis; Elder's triple
screen). Consequence: `backend/analysis/mtf.py`. (1) Any price or indicator in a visual rule can be
read "on" a bigger chart (`chart`: daily → 1w, 1mo; 1h → 1d, 1w; 15m → 1h, 1d; 5m → 15m, 1h, 1d;
1m → 5m, 15m, 1h), built from the strategy's own candles (session-anchored buckets; weeks and months
by local date) and seen as of its **last finished** candle (the period before the current one), so
backtests, paper and replays agree and nothing unfinished leaks; code strategies use
`ctx.chart("1w").close` / `.ind.sma("close", 40)`; codegen, words, lineage tokens (`@1w`), the
validator and warm-up (× candles per period) know it; empty `chart` is left out of the stored JSON so
older strategies keep their hashes. (2) The Kairos brain has `bigger_chart` (desks: daily → weekly,
1h → daily, 15m/5m → hourly): no long while the bigger chart's trend score is ≤ −25 or unknown, no
short while it is ≥ +25 (setting `kairos.bigger_chart`, on). (3) The chart reading adds the trend and
momentum of each timeframe from its own saved candles (daily chart: monthly, weekly, daily; unfinished
weeks/months left out) and one verdict (all up, all down, a dip in an uptrend, a bounce in a
downtrend, sideways, mixed), on the chart panel and in `analyze_chart`. (4) Metis's ideas and first
look can add a bigger-chart filter (e.g. weekly close above its 40-week average).

**D-98 · Sector strength, rotation, breadth and booms.**
Why: the user asked for knowledge of sector movements: "sometimes one sector receives a bloom and
all the stocks in that sector boom". Consequence: `backend/sectors/`. For each GICS sector (and each
industry with 3+ priced stocks) of the stocks with saved daily prices: an equal-weight line, 1w/1m/3m/
6m returns, relative rotation (RS-ratio = 100 × RS ÷ its 63-day average; RS-momentum = 100 ×
RS-ratio ÷ RS-ratio 10 days ago → leading/weakening/lagging/improving), breadth (above the 50- and
200-day averages, 52-week highs), the 1-month z-score against its own 3 years, member volume (10 ÷
60 days). **Boom**: z ≥ 1.5, ≥ 60% above the 50-day average, beating the market, volume ≥ 1.2×;
**slump** the mirror; else strong/weak/neutral. Cached per market until a new benchmark candle.
Used by the Watchlists screen, Kairos's `sectors` tool, Kairos's picks, Metis's lists and the move
investigator.

**D-99 · The autopilot: Kairos and Metis start on their own when Agora opens.**
Why: the user asked (2026-10-23) that as soon as he starts Agora (and connects Ollama) Kairos and
Metis start working without him triggering anything, adding stocks or strategies. This amends D-06
and CLAUDE.md §4 "paper trading starts and stops manually": paper sessions may now also be started by
the autopilot; still paper money only, still nothing runs while Agora is closed, sessions still
resume without back-filling. Consequence: setting `autopilot` (on) and `metis.enabled` now on by
default; `backend/autopilot.py`, a thread 20 s after Agora opens then every 15 minutes (real data;
`AGORA_AUTOPILOT=1` elsewhere): (1) daily prices for the confirming assets, the market's index,
gauges, US sector ETFs and the broad index (Nifty 200 / S&P 500) in batches of 60 new stocks a
round, each symbol at most once a day; (2) factor lists; (3) Kairos's picks (`kairos/picks.py`: the
broad index's stocks with prices ranked by 0.35 relative strength z + 0.25 momentum z + 0.2
near-high z + 0.3 uptrend + 0.4 sector state + 0.3 world tilt vs the market, ≤ 4 per sector, 20
stocks, saved as "Kairos · Picks India/US") and, per market with no Kairos desk running, a desk on
them (the user's own desk is left alone); once a week, when the autopilot's desk has no open trades
and ≥ 40% of the picks changed, it moves to the new picks with its equity; (4) pokes Metis (which
researches with the AI helper once Ollama is ready and from its playbook until then) and keeps the
news fresh. After each Metis round, `metis/lists.py` saves "Metis · Booming: <sector>" and "Metis ·
World: <event>" lists. Status: `GET /api/autopilot`, the Home card "Kairos and Metis".

**D-100 · Settings says where the AI model runs (2026-10-24).**
On the laptop the user's first explanation loaded Qwen into ordinary memory (+3.5 GB RAM, GPU 0 idle),
which he could only see in Task Manager. `OllamaProvider.status()` now also reads `/api/ps` (optional:
an Ollama without it reports nothing loaded) into `AIStatus.loaded`; `/api/ai/status` returns
`runs_on` for the chosen model: graphics card (≥ 95% of it in graphics memory), partly, or processor,
with plain fix steps. Nothing is shown until Ollama has loaded the model (it loads on the first
question and unloads after about 5 idle minutes). Agora never forces the processor: it sends only
`num_ctx` and `temperature`.

**D-101 · Agora keeps the AI model on the graphics card (2026-10-24).**
Cause found on the laptop: Ollama (0.40.10) started at Windows sign-in before the NVIDIA card had
woken (the laptop also has AMD integrated graphics). Its GPU search then found only the processor
(`server.log`: `inference compute … library=cpu`, `total_vram="0 B"`) and Ollama kept running every
answer on the processor until it was restarted. A fresh start found the card (`library=CUDA`,
compute 8.6, 6 GB) and Qwen 3.5 (4B) loaded 100% into graphics memory (`/api/ps`: `size_vram` =
`size`), answering at about 70 tokens a second. Not the power mode, not a driver problem, not the AMD
chip. Consequence: `backend/ai/gpu.py` (Windows, real data only), 15 s after Agora opens and then
every 5 minutes: when `nvidia-smi -L` lists a card and the running Ollama's latest start in the log
found only the processor (or a loaded model sits 0% on the card), and neither Metis nor Kairos is
using the AI, it quits Ollama (`taskkill` of `ollama app.exe` and `ollama.exe`), starts `ollama
app.exe` again, waits for its GPU search, and loads the model once (the first load after a start
compiles graphics-card code and can take a minute or two). At most twice per Agora run. Setting
`ai.fix_gpu` (on). Requests now send `keep_alive: 30m` so the model stays on the card between
Kairos's and Metis's rounds, and the chat timeout is 300 s (the first answer after a start is slow).

**D-102 · The whole market, not 61 stocks (2026-10-24).**
The user asked why only 61 stocks: the Welcome download fetches the Nifty 50 and the 11 default US
stocks so the first start stays short, and the autopilot then added the Nifty 200 / S&P 500 at 60
stocks every 15 minutes; Agora knew ≈2,300 index stocks. Now `scripts/fetch_lists.py` also adds every
NSE main-board equity (NSE `EQUITY_L.csv`, series EQ/BE/BZ: 2,617 stocks in all) and every US common
stock on the Nasdaq, NYSE and NYSE American (Nasdaq's screener, with its sector mapped to GICS
names; warrants, units, rights and preference shares left out: 5,892 in all). Stocks in no index
carry only the list key `listed` (`seed.LISTED_ONLY`); they have a profile (US: sector and
industry) but no size, so the size lists stay the official indices, and the sector readings, the
world desk's stocks helped/hurt and Kairos's picks keep using index stocks (equal-weight sector lines
of thousands of tiny companies would be noise). Every stock can be charted, backtested, added to
watchlists and traded on paper. The autopilot downloads daily history for all of them: after the
broad index, every other index stock, then the rest of the market, 250 new stocks a round, four at a
time (the shared Yahoo throttle still spaces requests about a second apart), with the next round 20
seconds after the last while stocks are waiting (every 5 minutes once all are in). The first full
fill takes several hours of Agora being open; nothing is fetched twice. Queries that asked "which
stocks have candles" now use one primary-key lookup per stock instead of scanning every candle.

**D-103 · Kairos and Metis work all the time while Agora is open (2026-10-24).**
The user asked that their frequency go up: "they must be constantly working". Metis's
`metis.every_minutes` (minutes of rest between rounds) now defaults to 1 (allowed 1–240; was 20,
5–240) and its first round starts a minute after Agora opens; Kairos's learning round runs every 2
minutes (was 10, first after 60 s); the autopilot every 5 minutes (was 15). They still yield: Metis
waits while you talk to Kairos or a backtest runs, Kairos's learner skips a round while a study job
runs. Still nothing runs while Agora is closed (D-06).

**D-104 · "Describe it to the AI helper" leaves the rule details to Agora's checker (2026-10-24).**
On the laptop (Ollama 0.40.10, Qwen 3.5 4B) every draft came back as two "time of day" rules with the
RSI condition stuffed into a time field, whatever the idea. Cause: Ollama's grammar for the full
Strategy Definition JSON schema (nested `$defs` references, `anyOf` rule types) forces the model into
the first rule type; with plain JSON the same model writes the right rules. Consequence: the draft's
reply schema now only fixes the outer shape (`explanation`, `unsupported`, `definition` as an
object); the prompt (version 2) shows groups (`all`/`any`), price operands and the stop/target shape;
`draft._fill` tidies small-model slips before validation (stops written next to the rules move into
`exit`, `5` or `{"type": "percent", "value": -5}` → `{"kind": "percent", "value": 5}`, rules
labelled `kind` instead of `type`, empty extras dropped). The validator and up to two retries are
unchanged, and the user still reviews the draft before saving. Measured: valid drafts in 15–30 s.
A 4B model sometimes drops one condition of a long idea; the review step is where that is caught.
Metis's own reply schema is flat and was not affected.

**D-105 · Stooq is unavailable as the US backup (2026-10-24).**
Stooq now answers automatic downloads with a JavaScript browser check (or "page not found" without
a browser's user agent). Agora does not try to get around bot checks, so `stooq.py` recognises any
web page in place of a CSV and raises a plain "Stooq no longer allows automatic downloads…" error;
the live check in Settings → Diagnostics reports it as skipped with that sentence. Yahoo Finance
remains the US source; NSE's files remain India's backup. If Stooq reopens downloads, nothing needs
to change.

**D-106 · Agora stays responsive while everything works at once (2026-10-24).**
With Kairos, Metis and the autopilot working all the time and four downloads at once (D-102, D-103),
the laptop showed "database is locked" errors and screens taking 10–25 s. Causes and fixes: (1) the
news saver held a database write open while matching every headline against every stock name: it
now prepares everything first and writes in one short step, and the name matcher looks names up by
their first word instead of running one pattern per stock (headlines × 8,500 stocks); (2) saving
downloaded prices is queued inside the cache (one writer at a time) instead of racing; (3) SQLite's
busy timeout is 30 s (was 5) and the connection pool 20 + 30 (was 5 + 10); (4) Agora reaches Ollama
at `127.0.0.1` instead of `localhost`, which on Windows lost about 2 s per connection trying IPv6
first (every AI status check took 6–7 s; now 0.3 s); (5) the autopilot caches its stock counts. Free
text is matched against the ~6,000 stocks in no index only by an exact capital ticker unless the
user uses that stock (`seed.rarely_named`): their names ("Seven Hills", "Force Motors") matched
everyday headline words. Kairos's chat matching also skips everyday words written in lower case
("is it safe", "any news", "rsi"), lets a ticker win over another company's first word ("reliance"
is RELIANCE, not Reliance Steel) and a whole name win over another's first word ("apple" is Apple
Inc, not Apple Hospitality).

**D-107 · Background tasks are never lost from view; "Refresh now" covers every saved stock (2026-10-24).**
The user: when something is running and he switches screens and comes back, the progress is gone,
and "Refresh now" only checked 51 stocks. Jobs always kept running on the backend (they live as long
as Agora is open); the screens forgot them, because each screen kept the job it started only in its
own memory. Now every job has a `key` (what it is about, "strategy:12") and a start time, `GET
/jobs?kind=a,b&active=true&key=` lists the unfinished ones newest first, and every screen that starts
a job (`useJobId` in `lib/useJob.ts`) asks for its kind when it opens and shows that job's progress
again. The top bar shows **Working… / N tasks running** whenever anything runs, on every screen, with
each task's progress. "Refresh now" on the Data screen sends `scope: "saved"`: every stock of the
market that has saved prices on that timeframe plus the starter list (onboarding still downloads the
starter list only), four stocks at a time when there are more than 20 (`refresh(workers=…)`). The
rest of the market keeps downloading on its own (D-102).

**D-108 · Agora keeps Ollama running while it is open (2026-10-24).**
The user: "make sure Ollama is on every time Agora is working". The graphics-card guard (D-101) now
also checks every minute: AI helper on, Ollama on this computer, installed but not answering → it
starts Ollama the way its own shortcut does (Windows: `ollama app.exe`, or `ollama serve` if only the
command is installed; macOS: `open -a Ollama`), waits until it answers, and loads the model. At most
one start every 5 minutes, so a broken install isn't hammered. Ollama is not stopped when Agora
closes (the user may use it elsewhere; it frees the graphics memory once the model unloads after 30
idle minutes). The graphics-card check itself still runs every 5 minutes, Windows only.

**D-109 · The trade autopsy: Metis learns from its strategies' bad trades (2026-10-24).**
The user: Metis and Kairos must improve strategies by first analysing what went wrong: another
indicator, a pattern, news, the bigger charts, other strategies on the same stock; broad and
self-learning, not only his examples. Built as `backend/metis/autopsy.py` (METIS §18): for each
strategy Metis studies, the study-year trades are opened up with ~19 readings on the strategy's own
chart (trend, momentum, volume and money flow, volatility, stretch, range position, candle shape) and
6 on each of the next two bigger charts (on their last finished candle, exactly as a `chart` rule
reads them); up to three of the user's other strategies on the same stocks and timeframe give second
opinions (each trade labelled: good for another strategy too, lost for everyone, taken alone); the
benchmark's trend at entry is reported. A "skip these trades" threshold per reading is chosen on the
first 60% of the study trades and must hold on the last 40% (money, win rate +2 points, a third of
the trades kept), like Kairos's review (D-72). The best three (and the best two together, so a
strategy keeps adding what it learns) become filter ideas, tested like any idea on the unseen exam
years with the luck and overfitting checks. Rules read only one stock, so the market's mood and news
are evidence for the AI and the user, not filters; "only when the other strategy agrees" is written
as that strategy's state conditions (crosses are moments and are skipped). Self-learning: every
autopsy condition carries its reading (`probe`); Metis counts over its notebook how often each
reading's filters held up and ranks the next candidates by that record (Beta(1,1) average), and never
retries a reading on the same strategy version. Thresholds are rounded to 2–3 significant figures so
new candles don't create "new" ideas. The autopsy is cached per version and period (Metis works every
minute). Kairos learns what held up through Metis's lessons (METIS §5); the Metis screen shows each
round's autopsy. Exam years stay unseen: everything here uses study-year trades only.

**D-110 · Dates before 1970 on Windows (2026-10-24).**
`datetime.fromtimestamp` raises `OSError [Errno 22]` on Windows for times before 1970, and Yahoo's
dividend history for old US stocks goes back to the 1960s, so backtests and the opportunity scanner
failed on those stocks (seen on the laptop). Every conversion now goes through
`core.clock.ms_to_dt`, which adds the milliseconds to 1970-01-01 instead.

**D-111 · "Start Agora" reuses the tab that is already open (2026-10-24).**
The user: every click on Start Agora opened another Chrome tab; the open one should start working
again. Every Agora tab now keeps its live channel (`/ws`) open on every screen and retries every 1–3 s
(was up to 30 s) while Agora is down. The server's hello carries `boot_id` (when it started); a tab
that reconnects to a *different* `boot_id` reloads itself, so it runs the new version. `GET /api/tabs`
says how many tabs are connected: after Agora is healthy the launcher waits up to 12 s for one to
reconnect and opens a new tab only if none does (and, when Agora is already running, only if no tab
is open). Chrome slows timers in tabs left in the background for a long time, so such a tab may miss
the 12 s; then a new tab opens as before.

**D-112 · Fewer wasted Metis ideas (2026-10-24, the long watch).**
On the laptop 49 of 109 of Metis's ideas were "couldn't test". The two biggest causes: the 4B model
proposed a new strategy but left its description empty (20), and named a strategy number it wasn't
shown (10). Now a new strategy without a description uses the model's other keys (`description`,
`rules`…) or its title and reasons, and when only one strategy was in the brief, an idea with a
wrong or missing number is about that one.

**D-113 · Screens stay quick while Agora works hard (2026-10-24, the long watch).**
Stress bursts on the laptop (backtests, a sweep, walk-forward, the scanner, Metis, world learning
and downloads at once) made screens take 10–80 s. Causes and fixes: (1) the Data screen counted the
candles of *every* saved stock (millions now that the whole market downloads, D-102) to show the
~51 in its list: `coverage_stats` now takes the stocks wanted; (2) the download log looked up all
~8,500 stocks to name 50 rows: only those rows' stocks now; (3) the World screen added up every
learned effect row in Python for each market and loaded every stock profile: the sum runs in the
database and both are cached (60 s; profiles 10 min; cleared when the map learns); (4) Metis, Kairos's
learner and the world desk each crunched numbers in their own thread at the same time: they now take
turns (`core/heavy.py`, one at a time; what the user starts never waits for it); (5) Python hands its
lock between threads every 1 ms instead of 5, so a screen's request isn't stuck behind a backtest.
Running backtests in separate processes would remove the rest of the contention; parked until the
watch shows it is still needed.

**D-114 · One odd stock no longer pauses a price source for everyone (2026-10-24, the long watch).**
Round 1 found that when Yahoo had no prices for a stock in the asked period (before it listed, or
after it stopped trading: yfinance's `YFPricesMissingError`, "Data doesn't exist for startDate…"),
Agora counted it as Yahoo failing, retried four times (~30 s) and then paused Yahoo for **every**
stock for 15 minutes, stalling the whole-market download and refreshes. Now: "no data for these
dates" is an empty answer (asked once, no retry, no pause); any other failure pauses a source only
when it is rate limiting or after 3 different stocks fail in a row; a source that refuses automatic
downloads (`Blocked`, Stooq's browser check, D-105) is left alone for 24 hours without retries. Pauses in a row
without a success double (15 min, 30, 60… up to a day), so a source that stopped answering isn't
asked all day (round 3: Stooq timing out).
DATA_SOURCES §2 amended.

**D-115 · Three lanes for background tasks; a chat never waits behind them (2026-10-24, the long watch).**
Round 2's stress test found a Kairos chat stuck for over 5 minutes at "Backtesting… Waiting to
start": its backtest queued behind sweeps, the scanner and an hour-long "refresh every saved stock"
download, all sharing three job slots. `JobManager` now has three lanes: number crunching (3), jobs
that mostly wait on the network (`data_refresh`, `ai_pull`, `live_test`: 3 of their own), and one
for what Kairos starts while the user is chatting (`priority=True`: its backtests, walk-forward,
improvement tests and strategy research).

**D-116 · A second click joins the running task; intraday days counted in the database (2026-10-24, the long watch).**
Round 2's profile under load: most of the processor went to "Learn from world events" started again
while the previous one still ran (each re-reads every stock's history), and the Data screen's
5-minute view loaded every candle's time to count days. Jobs can now be `single`: starting the same
kind (and key) while one is queued or running returns the running one. Used for world learning,
forward checks, the opportunity scanner, portfolio planning and backtests, Kairos's studying (per
market and timeframe), autopilot rounds, and whole-market refreshes (per market, timeframes and
scope). Intraday "days saved" is `count(distinct ts / 1 day)` in SQL: NSE and US sessions each sit
inside one UTC day.

**D-117 · Status cards never wait for a recount (2026-10-24, the long watch).**
Round 3: the autopilot's status took up to 15 s when its "stocks Agora keeps" count expired (it walks
every stock's profile), and the Sectors view took 23 s on its first load after a restart. The count is
now refreshed in the background while the old one is shown, and the autopilot computes both markets'
sector readings each round so they are cached before anyone opens the screen.

**D-118 · Metis and Kairos work on every timeframe (2026-10-24).**
The user: "Are all the backtests and strategies happening only on Day level? I want strategies for
day, 1 hour, 15 min, and 5 min and 1 min ones too." They were: all 7 strategies and all 126
backtests were daily, because Metis's discovery and the autopilot only started daily ones (the
builder and backtests always supported every timeframe). Now:
- **Templates on any chart.** `template_definition(…, timeframe)` runs a textbook template on
  hourly or minute candles; `timeframes_for` lists where it makes sense (all five for most; daily
  only for the 52-week high, Coppock, the triple screen and the golden cross; the intraday templates
  on 5/15/1-minute). In India, 15-, 5- and 1-minute versions are intraday trades (squared off the
  same day, shorts allowed); hourly versions hold overnight like daily ones.
- **Discovery by timeframe** (`metis/timeframes.py`): a timeframe is usable in a market when at
  least 4 stocks have enough saved history (daily 250 trading days, hourly 120, 15/5-minute 20,
  1-minute 10). Discovery tries templates on the usable timeframes with the fewest strategies first,
  the markets taking turns; a template on another timeframe is a different idea (its fingerprint
  carries the timeframe). Minute strategies are tested on the stocks with that history.
- **The AI's own ideas** may name a timeframe (the schema has `timeframe`; "hourly", "5 min" are
  understood); the brief lists, per market and timeframe, the user's strategies and the stocks with
  history.
- **Metis may add 5 new strategies a day** (was 2), one per timeframe.
- **Kairos's short-term desk**: besides the daily desk, the autopilot runs a desk per market on
  `autopilot.intraday_desk` (default 15-minute; hourly, 5-minute or off in Settings → Kairos) on its
  picks that have that history, named "Kairos desk · India · 15-minute". It trades only in market
  hours.

**D-119 · Kairos and Metis use trailing stops (2026-10-24).**
The user: "introduce trailing stop loss and make both Kairos and Metis familiar with trailing stop
loss… trailing or dynamic stop loss… instruct them to use it in strategies." The engine already had
trailing stops (percent, or a multiple of ATR at the entry signal, behind the best price since entry,
checked inside each candle) and the builder showed them; Kairos and Metis rarely used them. Now:
- **Kairos's desks trail every trade** at `kairos.trail_atr` × ATR (default 3; 0 = off; Settings →
  Kairos → Trailing stop), through the brain's existing `trail_atr`.
- **"Improve with Kairos"**: when no entry filter holds up (or the filter didn't do better), it tries
  a trailing stop of 2, 3 and 4 ATR, picks the width on the first 60% of the trades and keeps it only
  if it made more after costs, with enough trades, on the last 40%.
- **Metis**: tweaks may set `trailing_stop_atr` (0.5–8); the expert's first look proposes a trailing
  stop for every visual strategy without one (2.5 and 3.5 ATR when at least 30% of losers had been
  ahead by an ATR; 3, or 3 and 4 for trend strategies, otherwise), tested like any idea on the exam
  years; its prompt explains trailing stops and asks it to consider one for every strategy. Kairos's
  review now returns the gave-back counts it already measured.
- **Strategies drafted from an idea** (the AI helper, Kairos's create_strategy, Metis's own new
  strategies) get a 3 × ATR trailing stop unless the idea gives its own or says not to (draft prompt
  version 3); Kairos's chat rules say the same.
- **Knowledge**: "Trailing stops (dynamic stops)" in Kairos's risk knowledge, "Winners turn into
  losers" in Metis's playbook.
- **Engine fix**: an ATR trailing stop now uses the ATR measured at the entry signal, as the engine's
  own note said, instead of recomputing ATR on every candle; the per-candle value made a Kairos desk
  trail at slightly different prices in paper trading than in a backtest of the same version (the
  one-engine test, D-04, caught it once desks started trailing).

**D-120 · Metis gives way when the user chats with Kairos (2026-10-24, the long watch).**
Rounds 4 and 5 timed Kairos's answers at 50–186 s even for simple questions while Agora was busy.
The AI model on the laptop answers one request at a time, and Metis's thinking takes minutes; Metis
already waited a minute after a chat before *starting* a round, but a chat that began while Metis was
thinking queued behind it. Now Metis checks between streamed pieces of its thinking: when the user is
chatting with Kairos it closes the stream (which stops the model at once) and ends the round as
"Paused so Kairos could answer you first"; it starts again a minute after the chat.

**D-121 · One save of headlines at a time (2026-10-24, the long watch, round 6).**
Right after a restart, Kairos's `get_news` tool and the background news refresh saved the same
headline at once and the second failed ("UNIQUE constraint failed: news_items.uid"), so Kairos's
answer lost its news. The news service now saves headlines one batch at a time (each batch checks
what is already saved first), like prices (D-106) and dividends (D-104).

**D-122 · Kairos compares strategies from their saved results (2026-10-25, the long watch, round 6).**
"Which of my strategies is doing best?" took Kairos up to 5 minutes because its `list_strategies`
tool gave only names, so the model ran fresh backtests to compare. The tool now lists each strategy's
latest backtest (return, win rate, trades, worst drop), best first, and says to use it before running
new backtests.

**D-123 · More of the small model's rule slips are tidied (2026-10-25, the long watch, round 7).**
Since the timeframe change Metis's own new strategies were "couldn't test" 35 times because the 4B
model wrote rules almost right: a bare `30` or `"close"` instead of an operand, `">"` or
`"operator"` instead of `"op": "above"`, `"and"`/`"crossover"` as a type, or a comparison with no
type at all. The draft tidier (D-104) now turns all of these into Agora's shape before validation;
anything still wrong goes back to the model with the problems as before. Round 8 added two more: an indicator
line given as a number means the main line, and an idea built on VWAP (a within-the-day average)
runs on 15-minute candles instead of failing on daily ones. Untestable AI strategies fell from about
half to about a quarter after the first part.

**D-124 · Agora runs from a tray icon in its own window (2026-10-25).**
The user chose options 1 and 2 of RUNBOOK §8: no terminal window, a tray icon, and Agora in its own
window without tabs or an address bar. Built as `backend/desktop/`: `window.py` opens
`--app=http://localhost:8765` in Chrome (his browser) or Edge (always on Windows), else a normal
tab; `supervisor.py` runs the server as a windowless child process (so Restart loads new code and a
server crash can't take the tray down), restarts it if it stops on its own (3 times an hour at most)
and stops it cleanly through the new local-only `POST /api/system/quit` (`launch.request_stop`), by
force only after 30 s; `tray.py` draws the logo with Pillow, holds port 8766 so only one tray runs,
opens the window unless a window reconnects (D-111), offers Open / Restart / Open the log folder /
Stop, and makes a Desktop shortcut once (the Desktop Windows reports, often in OneDrive; minimised,
with the logo). New dependencies: **pystray** (the tray icon) and **Pillow** (drawing it), both
small and pure-Python on Windows. The .bat still shows a console while uv installs or updates
(seconds; first run minutes), so setup problems stay visible, then hands over and closes; the
shortcut starts it minimised. A real single `.exe` (option 3) stays in `LATER.md`: every update
would need a rebuild. Trying it on the laptop found three things, all fixed: the launchers named a
module that doesn't exist (silent with pythonw; a test now checks every module the launchers name),
PowerShell's inline command can't take arguments (the shortcut paths are quoted into it), and the
quit route found no server because `python -m backend.launch` runs as `__main__` (the server is now
registered on the importable module).

**D-125 · Partial exits (scaling out) in the shared engine (2026-10-25).**
The user asked for strategies that sell half, or a third and then another third, of a position at
profit targets and keep the rest for the next target or the exit rule. Built once, in the engine
both backtests and paper trading use (D-04): `ctx.scale_out([(1, 50), (2, 25)])` for code
strategies, `exit.scale_out` (up to three steps in R, percent or ATR, plus "move the stop to the
entry after the first") for visual ones, `kairos.partial_r` / `partial_pct` for the Kairos brain.
R is the distance to the stop-loss, so R steps need one (the checker says so). Fill rules in
COST_MODEL §4 rule 11. A position that scales out is reported as **one trade** (starting quantity,
average exit price, summed P&L and charges, `partials` = how many partial sales); counting each
partial sale as a winning trade would have made win rates look better than they are. Paper
sessions save the partial-exit state, so a restart keeps it. Kairos's desks sell half at 1R by
default (Settings → Kairos → "Sell half at"; 0 turns it off). Metis's first look proposes
half-at-1R and thirds (with a stop-loss when there's none, sized by timeframe) only when there is a
symptom: losers that were ahead first, or a win rate under 50%; "Improve with Kairos" tries them
when neither a filter nor a trailing stop helped. Both keep the change only if it made more on
trades the choice never saw. Partial exits trade some of the biggest winners for a higher win rate,
so they are tested, never assumed.

**D-126 · A new strategy must beat simply holding the index (2026-10-25).**
The user: "if my strategy is generating less than Nifty then what is the point". Metis keeps a new
strategy only if, over the exam years, its equity grew more than buying and holding the Nifty 50
(India) or SPY (US) over the same days: both on the whole starting money, the strategy after costs,
the index price only (`trial.against_index`). When no index prices are saved the check passes
with a note, so missing data never rejects a strategy on its own. Changes to existing strategies
are still judged against their current version (making a weak strategy better is progress even
before it beats the index). Expect fewer new strategies to be kept: a strategy that puts 10% of the
money into one stock rarely beats the index alone; the portfolio (Phase 15) is where several are
combined to use the whole amount. Kairos and Metis also got knowledge on active trading,
institutional investors and volatility (`knowledge/active_trading.md`, `institutions.md`,
`volatility_retail.md`, `library/active.md`), including honest numbers on what a retail trader can
earn: the user's example (₹20,000 a month on ₹1 lakh, 20% a month) is far beyond what any fund
sustains, and Kairos says so when asked.

**D-127 · Agora's server process ends once it has stopped (2026-10-25).**
Restarting Agora after Phase 20 showed that a clean stop ("Agora stopped cleanly" in the log) could
leave the server process alive for minutes: Metis's rounds, price downloads and news run on
thread-pool workers, and Python waits for those to finish before it exits. The tray saw a live
process, so it didn't start the new server. `python -m backend.launch` now gives background work
10 seconds to finish after the server stops (`EXIT_GRACE_S`), logs any task it ends, and exits.
Nothing is lost: paper sessions and settings are saved when the server stops, a database write cut
short is rolled back, and an unfinished Metis round runs again next time.

**D-128 · What the review of Kairos's and Metis's work found, and the fixes (2026-10-25).**
The user asked whether Kairos and Metis work as he asked, and whether failed strategies are
analysed trade by trade. Checked on the laptop from Agora's own records: the desks had no trades
because they were started on a Saturday (normal); Metis had run 580 rounds and tested 701 ideas
(18 held up, 9 saved). Found and fixed:
1. **Losing trades were only explained with 12+ trades** (statistics) and the trade autopsy needs
   20, so most of Metis's strategies got no explanation (the autopsy ran in 13 of 145 sampled
   rounds). New `kairos/casebook.py`: every losing trade is checked against textbook causes
   (against the 200- or 50-candle trend, the index moving the other way, a choppy market, thin
   volume, a chased price, a stop inside the noise, a gain given back), and causes the losers
   share more than the winners (2+ losers, 25 points more common) become findings with the
   matching fix. Kairos's review uses it below 12 trades; Metis's brief lists the worst losers one
   by one from 3 study trades; the first look turns shared causes into filters to test.
2. **Metis looped on one strategy**: every third round went to the strategy in use (5 trades), and
   its "more stocks" ideas failed when the model named stocks Agora doesn't know. Universe ideas
   now top up to 4 stocks from the market's main list; strategies in use rest after 6 empty rounds
   in a row until one of them changes (`agenda.live_resting`).
3. **Desks keep the rules they started with**, so the Phase 20 settings never reached the running
   desks. `DeskService.rules_outdated` compares a desk with Settings → Kairos; the autopilot
   restarts a desk with the new settings once it holds no trades.
4. **GDELT refused almost every request** (417 failures: answers take 10–20 s, past the 10 s
   time-out, then 429 "too many requests"). GDELT now gets 25 s, and after a refusal or a time-out
   it rests 15 minutes, doubling up to 2 hours, then is tried again.
News per losing trade is not added for backtests: Agora saves headlines only from the day it was
installed, so old trades have none; live desk trades use the news guard and Kairos's lessons.

**D-129 · Kairos and Metis research on the internet (2026-10-25).**
The user: "they must have access to internet if the laptop has access, to research and get
answers". New `backend/research/`: DuckDuckGo's plain HTML search (no account or key) plus
Wikipedia's search, up to 3 pages opened per question (1.5 MB cap, no video or social sites), the
paragraphs that share most words with the question kept (700 characters a page), each with its
source; answers cached 6 hours; searches 2 s apart. Kairos has a `web_research` tool (group "web":
research, look up, what do traders, institutions, FII, does it work…) and is told to name sources
and suggest a backtest. Metis's brief gets one web question a round: about the first strategy it
studies ("<kind> trading strategy why it loses how to improve <market>") or, when discovering, a
strategy family in turn. Web text is information, not instructions: it sits under a heading that
says so, both personas are told to ignore instructions in it, and nothing it says can place a
trade (D-56). Only the search words leave the laptop; Settings → Kairos → "Research on the web"
switches it off (`research.enabled`). Tests use `FakeWeb`; nothing in the suite touches the network.

**D-130 · Live paper sessions count the next poll from the last poll (2026-10-26).**
The user: "One trading day of India and US completed, but I don't see any trades made or simulated
in Agora." The first full trading day with desks running (Mon 26 Oct) showed every live session
(the three Kairos desks and "RSI Mean Reversion") polled once when it started and never again.
`PaperRunner.next_due` found the next candle close strictly after *now*; the live loop sleeps until
that moment and asks again, and by then "now" has reached it, so the answer was the following
candle: the due time slid forward every candle, forever. Tests and practice replays never saw it
because `replay_step` jumps the clock and polls without asking twice. The next poll now counts from
the last poll (the first close whose poll moment comes after it), so a loop that wakes on time
polls, and one that wakes late (laptop asleep) polls at once. New test: a whole day walked the
way the live loop walks it (`test_live_loop_polls_every_candle_of_the_day`). Missed days are not
traded afterwards: when the fixed sessions start, Monday's candles become history, as after any
time Agora was closed (D-04, no back-fill).

**D-131 · One trade may take at most its share of the money (2026-10-27).**
The user: "allocate resources man... all resources are in one stock then other stocks wont
buy/sell." On Tue 27 Oct the 15-minute desk bought 518 BHARTIARTL (₹9.99 lakh of ₹10 lakh): risk
sizing (1% of the money at risk) with a tight stop (0.5% away) asks for twice the account, and the
only cap was "all the cash". KOTAKBANK and ETERNAL signals then failed with "Not enough cash". A
strategy may now set `limits.max_position_pct`, the most of the money one trade takes, applied after
any sizing (shared engine: backtests and paper alike). Kairos's desks set it to an equal share of
their open-trade limit (100 ÷ 5 = 20%), so five trades can be open at once. It is left out of the
stored text while empty, so older strategies keep their hash (D-73). A desk picks the new rule up
when the autopilot restarts it once it holds no trades (D-128).

**D-132 · Kairos desks on every timeframe, reading every bigger chart together (2026-10-27).**
The user: "I also want Kairos desks in 1 minute, 5 min, 1 hour too… Kairos and Metis must analyse
all the charts together too if needed." The autopilot's short-term desk setting
(`autopilot.intraday_desk`) gains **All** (the new default: hourly, 15-, 5- and 1-minute desks in
each market, besides the daily desk) and **1 min**; one timeframe or Off remain. The brain gains
`kairos.bigger_charts`: every bigger chart of its own (`mtf.BIGGER`: a 5-minute desk reads the
15-minute, hourly and daily charts; a daily desk the weekly and monthly). The nearest chart works
as before (unknown or against the trade: no trade); a further one says no only when its trend is
known and clearly against the trade, because a short desk's further charts often have too little
history to say anything. Desks pick it up when the autopilot restarts them (D-128). Metis's trade
autopsy reads every bigger chart, not just the next two. Left out of the stored text while empty,
so older desks keep their hash.

**D-133 · Kairos picks from every stock, each desk as many as its candles allow (2026-10-27).**
The user: "The Kairos desk must have all the stocks available to Agora, not only 50 or 200 stocks,
all the stocks." Kairos's picks rank every stock of the market with a profile (about 2,300 Indian
and 5,700 US stocks with prices on the laptop), not only the Nifty 200 / S&P 500, from saved prices
only: 130+ days of history, the last candle at most 10 days old, and a median traded value over 20
days of at least ₹5 crore / $5 million a day (thinner stocks can't be bought and sold at the price
the chart shows). The ranking is made once and shared by every desk of the market, and made again
after four hours. A desk can't follow thousands of stocks live: it asks Yahoo for each of its stocks
every candle, and Yahoo answers about one request a second for all desks together, so each desk
follows the top of the ranking, as many as its candles allow (`picks.DESK_SIZE`: daily 30, hourly
20, 15-minute 20, 5-minute 15, 1-minute 10; at the top of the hour every short desk polls at once,
about a minute). Short desks follow the market's best again every day (when they hold no trades),
the daily desk every week. A short desk's warm-up downloads recent history its stocks don't have.

**D-134 · A stopping server gives open connections 10 seconds (2026-10-27).**
Restarting Agora on Tue 27 Oct (tray's Restart path, `POST /api/system/quit`) hung: the server
accepted the stop but uvicorn waited forever for an open connection (Agora's window, or a long
request) before running the shutdown, so the tray never started the new code and the old process
had to be ended by hand. `uvicorn.Config(timeout_graceful_shutdown=10)` now ends whatever is still
open after 10 seconds; paper sessions save their state after every candle, so nothing is lost.
D-127 already ends the process 10 seconds after the server itself stops.

**D-135 · An order bigger than the candle buys what the candle can take (2026-10-27).**
The user felt the desks still put all their money in one trade. Checked live on Tue 27 Oct: no
trade on any desk took more than about a fifth of its money (D-131), but the short desks threw many
trades away whole: "Order too large for this candle's volume" turned down 74 orders on the India
1-minute desk, 52 on the US 1-minute and 11 on the US 5-minute, so their money sat idle while a few
stocks traded. A one-minute candle of a mid-sized stock trades a few thousand shares, and a fifth of
₹10 lakh is far more than 5% of that. The shared engine now fills an entry at the size the candle
allows (5% of its volume, whole shares, the stop and partial exits planned on that size) and turns
it down only when not one share fits. One engine, so backtests do the same: a backtest whose orders
used to be turned down now trades smaller. Also: a trade's diary entry written after a partial sale
on its first candle showed the stop already moved to the entry ("risking 0.0%") and the shares left;
it now tells the trade as it was opened.

**D-136 · Kairos's desks hold up to ten trades of a tenth each (2026-10-27).**
After the live check (D-135) showed each desk full at five trades of a fifth, with later signals
turned down ("Already at the limit of 5 open trades", 18 times on the India 15-minute desk in one
morning), the user chose: "Let each Kairos desk hold up to 10 trades at a time, each with a tenth
of the money." `kairos.max_positions` now defaults to 10 (and his setting was set to 10), so each
trade takes at most 10% (D-131's cap is 100 ÷ the limit). Risk sizing is unchanged (1% of the money
at the stop), so the cap binds more often and a stop-out costs less. Desks pick it up when they
hold no trades (D-128). Settings → Kairos → Most open trades still takes 1 to 20.

**D-137 · An open window reloads itself after an update (2026-10-28).**
The user: "No page is loading in Agora." The server and a freshly opened page were fine; his window
had stayed open across the update that rebuilt the screens (D-136), so it still ran the old build,
whose pages are separate files with names that change on every build, and every page it asked for
was gone (404). Two guards: the page list (`index.html`) is served with `Cache-Control: no-cache`,
so a reload always gets the current build; and when a page file fails to load, the screens reload
themselves once (Vite's `vite:preloadError`, at most once a minute so an outage can't loop,
`frontend/src/lib/staleBuild.ts`). A window opened before this change needs one Ctrl+R.

**D-138 · Kairos trades on every indicator, classic strategy and quant signal, and learns at once (2026-10-28).**
The user: "I hope Kairos keeps learning from the trades it's making in paper trading. Kairos must
use all strategies as well as patterns, resistance/support, all indicators and news to make
trades, unless I missed something. Quant too." It already learned from every closed desk trade
(D-61) and read patterns, support/resistance, trendlines, candles, divergences, volume, the trend,
RSI, MACD, named setups, the bigger charts (D-132) and the news (D-69), but of Agora's 93
indicators only a handful, no classic strategy rules and no quant signals, and a desk took new
lessons only the next day. Now:
1. `backend/analysis/indicator_signals.py` flags 49 more signals (98 with both directions), each
   on the candle that completes it and never looking ahead: 19 oscillators (Stochastic, Stochastic
   RSI, CCI, Williams %R, MFI, ROC, CMO, Ultimate, Awesome, Coppock, Schaff, Connors RSI,
   WaveTrend, SMI, TRIX, TSI, KST, Fisher, RVI), 13 trend indicators (Supertrend, Parabolic SAR,
   ADX/DI, Ichimoku cloud and TK cross, Aroon, Vortex, EMA 9/21, the 200 average, KAMA, Hull,
   Heikin-Ashi, Elder impulse), 6 volume indicators (OBV, CMF, Chaikin, force index, ease of
   movement, Klinger), 7 classic strategies (Turtle breakout, Connors RSI-2, Bollinger reversion,
   first pullback to the 20 EMA, MACD zero cross, intraday VWAP reclaim, opening range breakout)
   and 4 quant signals (z-score snap-back, 12-1 momentum, regression fit, volatility breakout).
   Left out because they need future candles: the Ichimoku lagging span, fractals, centred DPO.
2. They vote as a **chorus** in the brain's score: in each part (trend, momentum, volume,
   patterns) their weighted agreement moves it by at most 0.6 of the part's room (×0.5 for the
   trend, momentum and volume readings), and fewer than three fresh voices can't reach that. On
   ten years of daily prices, adding them one by one made half of all candles look like trades
   (from a third); as a chorus, 37%. A single indicator crossing doesn't count as "something
   just happened" (with dozens of them one fires on most candles); a classic strategy's entry
   does. Entries rose about 22% on the test prices, mostly from the strategy entries.
3. Each is measured like every other signal: the history study counts how often it was right,
   and every desk trade updates that (×3), so its learned weight (0 … 2) keeps the ones that work
   and silences the ones that don't. A study made before these signals existed is redone
   (`learning.SIGNALS_VERSION`); the learner re-studies every desk timeframe (daily, hourly, 15,
   5 and 1 minute), one study a round, and the study covers Kairos's picks as well as the
   market's study list.
4. A live desk takes new weights on the next candle after any trade closes (or a study ends),
   through `learning.version`, instead of the next trading day. Backtests keep their snapshot.
Library strategies (the user's and Metis's) still run as their own paper sessions or portfolio
sleeves; they are not voices in the desk's brain.

**D-139 · Kairos tries Metis's strategies it believes in, on their own paper money (2026-10-28).**
The user: "If Kairos thinks strategies made by Metis work then it can test those strategies
too… not sure how you will regulate the usage though", then "There should be no compulsion on
Kairos to use those strategies." `backend/kairos/trials.py`, run by the autopilot each round:
- **Kairos's own bar, no compulsion.** A strategy Metis made and saved (not archived) is tried
  only when Kairos thinks it works: its exam years won at least 1.2× what they lost over 20+
  trades (Metis's own bar is 1.1× over 5), and Kairos's re-test on the candles formed since it was
  saved (seen by no test) didn't lose money once it has 5+ trades. A strategy saved under 30 days
  ago that is too new to re-test (a daily strategy needs weeks of candles) is judged on its exam
  years alone: no evidence against it yet. The view and its reason are kept for a day. First run
  on the laptop (28 Oct): of 7 candidates Kairos tried one (US "MACD momentum on hourly candles"). Of the 9 Metis strategies on the laptop, most fall short of the exam bar today
  (one: 1.18× over 75 trades, $194 on $100,000), so Kairos may well try none: that's the point.
- **A ceiling, not a quota.** At most `kairos.trials` (Settings → Kairos, default 3, 0 = off) on
  trial per market, and none new while 5 already proved themselves live.
- **Separate money.** Each trial has its own paper account (₹2,00,000 / $20,000), never the
  desks' money, on the stocks Metis tested it on.
- **Verdict.** After 20 closed trades or 30 days: it works live with 5+ trades, a profit after
  costs and wins of 1.1× its losses, and keeps running; otherwise it ends once it holds no
  trades and isn't tried again for 60 days unless a newer version is saved. A trial whose money
  falls 10% is stopped at once. A newer version restarts the trial once flat. Each verdict is a
  lesson in Kairos's memory, and its learner reviews the trials' trades like any paper session's.
Orders still only come from the strategies' code in the shared engine (D-56).

**D-140 · Kairos chooses its own exits from its record (2026-10-28).**
The user: "I hope Kairos is learning from all the bad trades and good trades as well and trying
to improve or find ways to avoid losses or get more profit. Concepts like stop-loss, trailing
stop-loss, partial profits, everything must be known to it, but usage of these depends on
Kairos's brain." It already learned from every trade which signals to trust (D-61, D-138), which
trades to skip (the trade check) and why losers lost (the casebook, D-128), and it knew every exit
(a stop at the signal's invalidation or a multiple of the ATR, a measured-move or multiple-of-risk
target, a trailing stop, half sold at a multiple of the risk with the stop then at the entry, a
time limit), but the exit numbers were fixed settings. Now (`backend/kairos/exits.py`):
- **54 exit plans** (stop 1.5 / 2 / 3 ATR × target 2 / 2.5 / 3.5× the risk × no / 2 / 3 ATR
  trailing × no partial sale / half at 1× the risk), plus the settings' own plan.
- **On history**, as part of the signal study: every entry the brain would have made (at most one
  per 10 candles per stock) is played out under each plan with the engine's own fill rules (next
  open; stop before target inside a candle; gaps fill at the open; the trailing stop follows the
  best price of earlier candles; after the partial sale the stop moves to the entry; out at the
  close after the time limit), in R after an approximate round-trip cost (India 0.15%, US 0.03%).
  The first 70% of each stock's history is the study, the rest the exam.
- **On paper**: every closed desk trade is played out under every plan too, counted 3×.
- **The choice**: a plan may replace the settings' plan only when it did at least as well in the
  exam years with 30+ exam trades (so it isn't just lucky in the study); then the best average R
  wins, history weighted by up to 200 trades and paper trades 3× each. Under 100 past trades the
  settings' plan stays.
- **Live desks** take the chosen plan with the weights (each day, and on the next candle after
  any lesson); trades already open keep their exits. Each thesis in the diary names the exits and
  why; "What Kairos learned" shows them. Backtests keep the definition's exits, so the desk-vs-
  backtest check holds them still like the weights (D-04).
- **Settings → Kairos → "Kairos chooses its own exits"** (on by default); off, the desk uses the
  numbers in the settings. The signal study is redone once for this (`SIGNALS_VERSION` 3).


**D-141 · The AI reads up to 32,768 tokens: "Automatic" reading size (2026-11-03).**
The user asked whether the reading size (Ollama's `num_ctx`, which he saw at 4,096) could be
32k or 64k. Measured on the practice data: Metis's brief for two strategies is ~20,000
characters with its instructions (≈ 6,500 tokens), four strategies plus the notebook and web
excerpts reach ≈ 10,000, and the model's thinking counts in the same window. At 4,096 or 8,192
Ollama silently dropped the *start* of the conversation: Metis's instructions and its first
strategies, leaving it the indicator list. Qwen 3.5 (4B) reads 262,144 tokens and only 8 of its
32 layers keep a memory that grows with the text (~32 KB a token), so 32,768 needs ~1 GB beside
the 3.4 GB model, which fits a 6 GB card; 65,536 (~2 GB more) is offered but may not fit.
- `ai.num_ctx` now offers Automatic (0, the default) and 8,192 to 65,536. Automatic starts at
  32,768 (`ai.ctx_fit`) and steps down one size (to 8,192 at the lowest) when Ollama reports the
  model only *partly* on the graphics card after an answer or a Metis round; wholly on the
  processor means the card is off (power mode, `gpu.py`), not a size problem. A chosen size is
  never changed. Migration 0012 resets a stored size under 16,384 to Automatic (the user asked
  for more).
- Metis's brief fits its budget (`reading.prompt_budget`: the size minus 6,144 for thinking and
  1,536 for the answer, minus the instructions): it leaves out, in order, the web excerpts, the
  library, older notebook lines, strategies after the first, then the notebook, and says so in
  the log. A strategy left out is removed from the round, so ideas about it aren't tested blind.
- Kairos's chat, the desk's reflections and drafts use the same size, so Ollama never reloads the
  model between them.

**D-142 · Ideas that can't work are caught before a backtest (2026-11-03).**
Metis kept 0 of ~1,180 ideas in its first full day (PROGRESS 22.4). Many could never work: a
threshold outside an indicator's range (ADX "at least 80"), a condition true on every candle, or
an on/off flag compared with the price. `backend/metis/precheck.py` evaluates each simple
condition of a filter, and each must-hold entry condition of a new strategy, on the **study
years** of up to four of its stocks: under 1% of candles true on every stock is "never true", over
99% "always true". Such an idea is "could not be tested" with the indicator's real range (5th to
95th percentile), so the next brief's notebook teaches the scale. Bigger-chart conditions are left
to the backtest. Metis's structured answers may only name real indicator keys (an enum in the
schema). The check only shortens the way to the same verdict; it never keeps an idea.

**D-143 · The lab: research sprints, the vault, the regime map and the playbook (2026-11-03).**
The user asked how Claude can make Kairos and Metis "way way ahead" without paying for an API.
Claude can't run inside Agora, but in a session on the laptop it can do the research with his
real data and leave the results behind as code and a committed playbook (Phase 25).
- **Families** (`backend/lab/families.py`): 32 hypotheses, each with an economic reason and a
  small grid (≤ 18 variants; grids are kept small because the luck check counts them). Four
  replicate the rules that survived a strict multiple-testing test on liquid NSE stocks,
  2015–2025 (the user's Gemini research): channel breakouts, plain crossovers, a slowed MACD, RSI
  only at extremes.
- **Stocks**: the market's most traded stocks (median daily value traded) with enough history;
  the research says trading rules survive costs in India only in the top 75–200.
- **The vault** (`vault.py`): the last 365 days (daily), 120 (hourly), 12 (5- and 15-minute), 4
  (1-minute) are never used while choosing. Research runs before it, split 70/30.
- **The ledger** (`lab_tests`, migration 0013): every test with its study, exam and regime
  numbers; the exam keeps its daily returns for the luck check.
- **Finalists by fixed rules** (`runner.pick_finalists`), set before any result: 30+ study and
  12+ exam trades, money made after costs and 1.1× profit factor in both, half its stocks
  profitable, the deflated Sharpe ratio over the family's tries ≥ 0.5 in the exam, an exam
  Sharpe ratio at least that of the index *and* of simply holding the strategy's own stocks in
  equal shares, and most one-step neighbours profitable (no isolated peak). The best study Sharpe
  among those wins; exam numbers gate but never rank; a finalist that trades exactly like one
  already chosen (two families can be one rule: a close under the lower Bollinger band is a
  z-score under −width) is dropped. Nobody hand-picks.
- **Rehearsal on the practice data** (random walks that only drift upwards, so no real edge
  exists): all 32 families ran (250 daily tests in ~3 minutes on 10 stocks a market; the intraday
  and hourly ones with the practice data's 2 intraday stocks). Without the hold-its-stocks bar 25
  of ~55 groups became finalists, because any buy-only rule earns in a rising market; with it, 3,
  which the vault is there to catch. The daily chart a short strategy reads is built from its own
  candles, so 5- and 15-minute families use short daily trends (60 days of history).
- **The vault opens once** for the finalists: 5+ trades and money made → promoted; otherwise
  failed_vault. It can't be opened twice.
- **The regime map** (`backend/analysis/regime_map.py`): trend (close vs its 200-candle average
  and the 50-candle average's rise in ATRs) × volatility (ATR% in the top third of its own last
  250 candles), six regimes, no look-ahead. Every trade is tagged with its signal candle's regime.
- **The playbook** (`backend/seed_data/playbook.json`): promoted tests as entries with rules,
  reason, numbers and the regimes they work in and should avoid. Rules and summary numbers only,
  no prices. Metis and Kairos re-test each on the user's data before using it (D-144).
- Not modelled: capital-gains tax (India 20% short-term, 12.5% long-term), which the research
  says can outweigh trading costs for frequent trading; Agora shows results before tax.

**D-144 · Metis starts discovering from the research sprint's playbook (2026-11-03).**
A 4B model is weak at inventing strategies and fine at choosing between proven ones. Discovery
rounds now seed first from `playbook.json` (`agenda.sprint_seeds`): entries for the market the
user doesn't have yet (the sameness check, D-79) on timeframes with saved history, those whose
record suits today's regime of the market's index (daily candles) first, sorted by their average
return per trade in it, then the rest unless they avoid it; textbook templates follow. A seed's
rules are the entry's, on Metis's stocks for that idea; the verdict is Metis's usual one for new
strategies (exam years, luck, overfitting, the index bar), so a sprint's result must be earned
again on the user's own data before it is saved, and Kairos may then try it (D-139).

**D-145 · Kairos's trade judge (2026-11-03).**
The user: "I need results in Kairos desk too." Kairos's weights and the trade check learn one
reading at a time and can't see combinations. The judge (`backend/kairos/judge.py`) is a
meta-labeling model (López de Prado): lessons are the brain's historical entries from the signal
study (one per 10 candles per stock, D-140) with ~25 readings at the signal candle and the result
in R after costs under the settings' exits; gradient-boosted depth-2 trees in numpy (120 trees,
rate 0.1, ≥ 25 lessons a leaf, 16 quantile cuts per reading, missing values handled). Time order:
study 70% (learn on 80%, choose the share kept among 50–90% on the rest), a gap of the longest
trade, exam 30%. It is active only when the exam's kept entries beat all entries by ≥ 0.05R a
trade *and* two standard errors (σ·√(1/n_kept − 1/n)), AUC ≥ 0.53, 30+ kept; synthetic noise
switched it on 0 of 30 times, a real combination edge 10 of 10. Saved per market and timeframe in
`data/kairos/judge_<market>_<tf>.json` (not committed); re-learned with every study. Live desks
only (`brain.judge_says_no`, through the paper runner like the exits); backtests and replays
don't use it (D-04 reproducibility). Setting `kairos.judge` (on). Not done: a separate "signal
families" step (PROGRESS 25.8): the chorus (D-138) already divides a bucket's say among its
voices, so five oscillators saying "oversold" count once; the judge handles the rest.

**D-146 · A restarted desk's total return counts from its first run (2026-11-03).**
The user: "all paper trading I see the total return is wrongly calculated." The autopilot
restarts a desk with the money its last run ended with (D-128, D-133), and each run is a new
paper session with that money as its starting capital, so the return shown counted only since
the last restart (India 15-minute: 10,00,000 → 10,11,725 → 10,01,819 → 10,01,479 showed −0.03%,
not +0.15%). A run now carries `first_capital` in its session notes (the autopilot passes the
first run's money on); `total_return` and the session page count from it, less money a portfolio
moved (D-86, which the session page also ignored). Migration 0014 links the runs restarted before
the fix: same market and timeframe, stopped before the next started, ending with its starting money.

**D-147 · A Kairos desk stands aside where its entries lose (2026-11-03).**
The first re-study with the trade judge (D-145) on the user's data showed, on unseen past
trades after costs: India daily entries earned +0.07R a trade, but 1-hour lost 0.16R, 15-minute
0.25R and 5-minute 0.48R; on 5-minute the judge switched on and its picks still lost 0.39R.
The research sprint agreed: every 5- and 15-minute family and every India hourly family lost to
costs. Being picky can't rescue a chart where nothing pays. So the judge also decides
`stand_aside`: the entries the desk would take (the judge's picks when it is on, else all) lost on
the exam by at least 0.05R a trade *and* two standard errors (a small or noisy loss isn't enough).
A desk standing aside opens no new trades on that chart, keeps managing open ones, and says so on
its card ("Standing aside: … lost −0.48R each after costs"). Each study re-decides, so the desk
trades again once its entries earn. Live desks only, like the judge; `kairos.judge` off turns
both off. Tested: clearly losing lessons stand aside; earning and near-zero ones do not.

**D-148 · Each Kairos study runs in a process of its own (2026-11-03).**
The user: "try to speed up… increase speed vastly". A study walks every stock's history in plain
Python, so studies started as job threads share one core (Python's global lock): re-studying ten
timeframes after D-147 took hours, with three "running" at once on one core. Run by hand as six
child processes on the 16-core laptop, the remaining six finished in 30 s to 8 minutes. Now the
app does the same: a `kairos_train` job starts `python -m backend.kairos.study MARKET TF` (the
console interpreter beside a windowless `pythonw`, no window, UTF-8 output), passes its
`PROGRESS` lines on as the job's progress, reads its `RESULT` line, and forgets its cached numbers
and judge so the child's are read. Cancelling the job kills the child. The child writes to the
same database and judge file as an in-process study; tests and the practice data study in-process
(`learning.separate` is set only by the app). Also used to run studies in parallel from a session.

**D-149 · A waiting playbook gets every third Metis round (2026-11-03).**
After the first sprint's playbook was committed, Metis ran two scanner rounds in a row and no
discovery. Its direction is drawn from each direction's record (Thompson sampling, D-90-style):
discovery's record from inventing strategies with the small model (18 kept of ~2,500) draws
near 0.007, while the scanner, with no record of tested ideas, draws uniformly; so discovery,
the only direction that re-tests playbook entries (D-144), almost never won. Now, while any
playbook entry waits to be tested on the user's stocks (`agenda.playbook_waiting`), discovery
gets at least every third round, after the live strategies' and the scanner's guaranteed turns.
When every entry has been tried, the draw decides as before.

**D-150 · Discovery tests playbook entries before the model's own ideas (2026-11-03).**
The first discovery round after the sprint (round 2101) tested three ideas the small model wrote
itself, two of them impossible (a line "crossing" itself), and none of the 15 playbook entries
it had been shown. D-144 put the entries first in the brief, but with the AI ready the model's
ideas were tested and the playbook was only the fallback. Now each discovery round tests up to
two waiting playbook entries first, exactly as the sprint found them, and the model's ideas fill
the rest of the round's three slots; the verdict is Metis's usual one on the user's stocks.

**D-151 · A playbook entry's luck check counts the playbook, not every idea (2026-11-03).**
In the first round after D-150 (2106), Metis tested two playbook entries (new 52-week high, six-
month momentum ranking) and rejected both on one check only: the luck check counted them against
1,316 tries, every new strategy the small model had ever tested on US stocks. The deflated
Sharpe ratio's N is the number of candidates the winner was *chosen from*. A playbook entry was
chosen from its family's small grid in the sprint, whose own luck check counted that grid, then
passed a vault year never used in choosing; Metis re-tests it as one of the market's playbook
entries. So its N is the market's playbook size, or the playbook entries Metis has re-tested so
far plus one if that is larger (`trial.playbook_tries`). Every other check (study and exam years,
overfitting across Metis's history, the index bar) is unchanged, and the model's own inventions
keep the full count. Changed after seeing two rejections, so stated plainly: the rule follows
from what the luck check measures, not from the results; the sprint's vault rules are untouched.
The three entries rejected on that check alone before the fix (ideas 3541, 3542, 3545: six-month
momentum ranking, new 52-week high, Supertrend) keep their verdicts in the notebook and still
count as tries; their fingerprints were marked `|before-D-151` so each is re-tested once.
"Monthly calmest stocks" (3544) lost money in the exam years and stays rejected.

**D-152 · An order waiting overnight survives a restart (2026-11-04).**
Watching the India session, the India daily desk had never made a trade, nor had any India or
US daily desk before it. A daily desk decides when a candle closes (15:30 India, 16:00 US) and
buys at the next open; the order waits in the engine overnight. The saved state left waiting
orders out ("that candle has long passed", D-06), so whenever Agora was closed overnight, as
the user normally does, every daily order was cancelled before it could fill (28 Oct: "10
orders waiting for the next candle were cancelled"). The same hit any daily paper session and
intraday orders around a quick restart. Now the snapshot keeps the waiting orders (side, size,
stops, targets, trailing stop, partial exits, ATR at the signal), and a resumed session puts an
order back only if the newest saved candle is still the one it was placed on, so no candle
closed while Agora was away: it then fills at the open it was waiting for, exactly as if Agora
had stayed open. If a candle closed meanwhile, it is cancelled as before ("…because a candle
closed while Agora was closed"). Snapshots from before this change hold only a count and are
cancelled. Tested: an overnight restart keeps and fills the order; ten days away cancels it.

**D-153 · Metis's thinking is capped and kept (2026-11-04).**
The user asked to check that the AI and its context limit work. Measured on round 2129's real
brief at 16,384 (the size Automatic settled on, 100% on the RTX 3060): the brief took 8,166
tokens, Qwen 3.5 then thought for 8,218 and stopped at the window's end ("length") with no answer,
after 2 min 18 s. Metis then asked again for JSON, but without the thinking, so ~30,000
characters of reasoning were thrown away each round and the ideas were written from nothing.
Now Metis's thinking and answer get a fixed allowance (`num_predict` = THINK_RESERVE +
ANSWER_RESERVE = 7,680), so it stops where the brief's budget expects; and when the thinking runs
out with no answer, the second ask carries the last 4,000 characters of it ("My thinking so far,
cut short") and asks for the ideas from those notes. Kairos's chat thinks too (`kairos.think`)
with short prompts; it is watched in the 48-hour check (PROGRESS 25.19).

**D-154 · Kairos tells of every desk, not only its newest (2026-11-04).**
Checking Kairos's chat for the reading-size question (it answers in ~15 s, thinking fits), it
said of the India daily desk: "There doesn't appear to be an active India-specific desk", and
called a desk's 20 trades "closed today". Its `desk_status` tool described only `desks[0]`, the
newest of the ten desks the autopilot runs (one per market and candle size, D-133). The tool now
takes an optional market and candle size: with neither it lists every running desk in a line
each (return since it began, today, open trades, trades closed since it started, and its trade
judge's line, so it can say which desks stand aside, D-147); with one desk named it adds its
positions, theses and reviews. The quick router passes the market and candle size a question
names ("the India daily desk" → IN, 1d).

**D-155 · Kairos picks only steadily traded stocks (2026-11-04).**
In the 48-hour watch, the India daily desk's catch-up fetches kept failing for tiny stocks, and a
third of its 30 picks traded under ₹20 crore a day; KABRAEXTRU traded ₹1 crore a day over the
year and was let in by a few busy weeks, since the bar (₹5 crore, $5 million) used only the
last 20 days. The sprint found trading rules survive costs only in the most traded stocks
(D-143). The bar is now ₹20 crore / $20 million a day on the lower of the 20- and 120-day
medians of value traded (`picks.STEADY_DAYS`). Desks take the new picks at their usual refresh
(a daily desk weekly, a short desk daily, once flat, D-133), so nothing is sold to make room.

**D-156 · Findings already tested are only mentioned in Metis's brief (2026-11-04).**
In the 48-hour watch, 4 of 7 Metis rounds ended "didn't come up with a usable idea". Replaying
round 2176's brief on the real model (D-153 working: thinking cut, notes kept, 3 ideas back) showed
why: all three ideas were "Partial Exit Scaling", already tested on those strategies, so all were
skipped as repeats. The senior quant's first look kept giving the same finding ("losing trades
were ahead and gave it all back… partial exits") every round, and the 4B model followed it. Now a
finding whose every suggested idea is in the notebook is left out of the first look and its
seeds, and the brief says in one line "Already tested on this strategy (look for a different
cause): …", so the model looks elsewhere.

**D-157 · Slots the model spends on repeats go to untested suggestions (2026-11-04).**
After D-156 the brief said in so many words that partial exits were already tested on strategy
#11, yet the next two rounds again ended with repeats: the 4B model doesn't reliably follow such
a line, and the casebook's text ("First fix to test: partial exits or a trailing stop") still
points at them. Rather than trust the model, the round now drops its repeats before testing and
fills those slots with the first look's untested suggestions (after the playbook entries,
D-150), and says so in the round's note. Repeats no longer cost a round.

**D-158 · The log keeps working when Windows won't rename it (2026-11-04).**
In the 48-hour watch Agora's log stopped at 05:02 (laptop time) for over three hours: when
`agora.log` reached 2 MB, renaming it to `agora.log.1` failed ("being used by another
process") because the tray process had the same file open, and Python's handler then failed on
every record (1,073 "Logging error" tracebacks in `server.log`, nothing in the app log). Agora
itself kept running. Now the tray writes `tray.log`, so only the server writes `agora.log`; and
the handler (`SharedRotatingFileHandler`) treats a refused rename as "not yet": it keeps
writing to the current file and tries again after another tenth of the size limit, so an
antivirus or a viewer holding the file can't silence the log either.

**D-159 · Metis's brief tells it about today's market (2026-11-04).**
The user asked whether Kairos and Metis look at the news. Kairos's live desks do (the news guard
nudges each entry's score and halves, skips or exits trades: 48 such actions on 4 Nov). Metis's
brief had none of it: no news, world events, sectors or regime, though the user asked
(2026-10-23) for both to weigh geopolitics and sectors. Every brief now opens with "Today's
market": per market, the index's regime (`regime_map`), the news risk gauge, the world events in
play (the world desk's drivers) and the groups of stocks they help and hurt, with the advice that a
trend, sector or regime condition can keep a strategy out when the backdrop is against it. About
600 characters; each part is left out if it can't be read.

**D-160 · Claude's ideas go through Metis's tests (2026-11-04).**
The user: "replace Ollama completely" for 48 hours and "boost discovering, testing, improving of
strategies by 100x or more". The 4B model gave about one usable idea every three minutes, many
broken or repeats. `python -m backend.metis.claude strategies` lists the user's strategies with
their rules and records; `… run FILE` tests a JSON list of ideas (Metis's idea shape) as one
round with model "claude" (trigger "user"): changes go through `trial.try_change`, new
strategies through `trial.try_new`, where a new strategy may now carry finished rules
(`definition`), fingerprinted by a hash of the rules. The luck check counts every idea tried,
Claude's included; what holds up is saved as Metis saves its own. Several files can run at once
on separate cores. Ollama stays for Kairos's chat; Metis's own rounds continue alongside.
Caveat stated plainly: Claude saw the sprint's vault year (D-143) before writing these ideas,
and Metis's exam years include it, so ideas are written as whole grids from economic reasons,
never tuned to that year, and Metis's luck check counts every one.

**D-161 · A condition that compares a value with itself is refused (2026-11-04).**
Listing the user's strategies for D-160 showed "Metis · US Volatility Squeeze Reversal" (#10,
paper traded as a Kairos trial) buying when "%B at least %B": always true, 2,641 trades in 2,641
candles. The rule checker now refuses any comparison whose two sides are identical, for every
strategy (the user's, Metis's, Kairos's), so no such rule can be saved again. Saved versions still
load (sessions read rules without the checker). Strategy #10 and its session are left to the
user (archiving needs his OK).

**D-162 · The luck check counts independent tries, not every try (2026-11-04).**
Running Claude's first 67 new strategies through Metis (D-160), 8 of the US ones failed on the
luck check alone, each against "the best of ~1,400 lucky tries": every new strategy Metis had
tried in that market, most of them the small model's near-copies. The deflated Sharpe ratio
assumes the N tries are independent; with correlated tries its authors deflate by the effective
number of independent trials. Measured on the saved exam-year returns (4 Nov): the US's 1,410
tries hold 159 patterns explaining 90% of their variation (participation ratio 9), India's
1,237 hold 134 (12). A new strategy's N is now that count, `overfit.effective_tries` (the
cautious 90% measure, recomputed hourly or when tries change; every try when too few have saved
returns), plus one. At N ≈ 160 the bar is an exam Sharpe ratio near 1.8 a year instead of 2.2:
still strict. Changes keep their per-strategy count; the overfitting check (PBO, D-89), the
index bar and the exam rules are unchanged. Changed after seeing these rejections, so said
plainly: the rule follows from what the deflated Sharpe ratio assumes, not from the results.

**D-163 · Past Metis ideas judged again after the context fix (2026-11-04).**
The user: "all the previous Metis stuff which the AI didn't take in properly because of
context… need to be corrected." The cut brief (D-141, D-153) damaged the *ideas* (written blind),
not the verdicts (code). Two corrections. (1) `python -m backend.metis.claude rejudge`: new
strategies rejected on the luck check alone (125; every other check had passed) are judged again
on their saved exam-year returns with the count of independent tries (D-162), at today's count;
copies with the same returns count once (the small model rewrote one ADX trend rule 13 times), and
a name that claims a chart the rules don't use is corrected ("India Hourly ADX Trend" → "India ADX
Trend (daily)"). Result on 4 Nov: 19 distinct ideas held up; none was saved as a new strategy,
because Agora's sameness check (D-79) found each a version of strategies the user already has
(#11, #12), which have changed since, and one failed today's rule checks. (2) Saved strategies with
rules that can't mean what they say (#10 "%B at least %B", D-161) are left to the user to retire.

**D-164 · Keep the laptop cool: at most two studies at once, Metis rests 15 minutes (2026-11-05).**
The user: his ASUS TUF A15 (2021) reached 95 °C with G-Helper's fans on high, and its Wi-Fi card
(known to cut out when the laptop is hot) switched off, so Agora's data and the 48-hour watch
stopped. The load was ours: up to 12 of Claude's research processes, 6 Kairos studies in parallel
(D-148), Metis's model working every minute on the graphics card (which shares the laptop's
cooling) and 15 live sessions. Now Kairos runs at most `MAX_STUDIES` = 2 study processes at once
(others wait, "Waiting for a free study slot…"), at below-normal priority; `metis.every_minutes`
is set to 15 (from 1; a setting the user can change back), while Claude supplies most ideas
(D-160); Claude's own research runs at most two processes at a time, at low priority.

**D-165 · No internet isn't a source refusing us (2026-11-05).**
After the laptop overheated and its Wi-Fi card switched off (D-164), every price request failed
with "Could not resolve host", and Agora treated each failure as Yahoo (and NSE) refusing it: the
doubling pauses (D-114) reached 8 hours, so when the Wi-Fi came back Yahoo stayed "cooling down"
until 08:10 UTC, past most of India's next session, and all ten desks paused for want of prices,
though Yahoo answered normally. Now an error that means this computer couldn't reach the
internet (DNS or connection failures, `cache.offline`) sets a one-minute wait with "No internet
connection right now", and doesn't lengthen the source's pause. Real refusals (rate limits,
blocks, repeated bad answers) back off as before.

**D-166 · Metis's own ideas can be switched off; Claude is Metis's AI until Friday (2026-11-05).**
The user: "No, you will be the AI till Friday." Setting `metis.own_ideas` (on by default,
Settings → Metis): off, Metis never asks the local model; its rounds run on code (playbook
seeds, textbook templates, the first look's suggestions, the scanner) and say why. Set off on
5 Nov for the 48-hour watch, while Claude writes Metis's ideas (D-160) in small batches at low
priority (D-164); the graphics card stays free and cool. Kairos's chat keeps the AI helper.

**D-167 · The world desk's tilts saturate softly (2026-11-05).**
In the 48-hour watch both markets' world tilt read exactly −2.0 all day, and whole groups
(airlines, IT services, metals) sat at −2.0 too: with 18–20 active events, the summed effects
passed the hard clip at ±2 (±3 for a stock). A crisis then read the same as a tense week, and
Kairos's picks, which add 0.3 × a stock's tilt relative to its market, couldn't tell badly hurt
from slightly hurt. The market, sector and group tilts now pass through `soft(x) = 2x / (2 + |x|)`
(a stock's total through the same shape at ±3): order is always kept and the cap is never
reached (soft(20) = 1.82); small values shrink a little (0.5 → 0.4), which the ±0.2/±0.3
thresholds tolerate. A rational curve rather than tanh, which rounds back to the cap past ~6.

**D-168 · A Kairos desk holds at most three open trades in one sector (2026-11-05).**
In the watch the US 15-minute desk held ten trades, six of them on the oil price (shorts in EOG,
Chevron, ConocoPhillips, APA, the oil fund BNO, and ECO): one oil move would hit ~60% of the desk
at once. Kairos's picks limit four stocks a sector in the watchlist (D-133), but nothing limited
the trades held. Limits now take `max_per_group` (off by default): the engine refuses an entry
when that many trades (or waiting entries) are already open in the stock's sector, or its
industry when it has no sector ("Already 3 open trades in Energy."); a stock with neither counts
alone. The same engine applies it in backtests and live sessions (D-04), from the stocks'
profiles. Kairos's desks use 3 (`brain.MAX_PER_SECTOR`); a running desk takes it at its next
restart once flat (`rules_outdated`).

**D-169 · A desk with orders waiting isn't flat (2026-11-05).**
Loading D-168 made every desk's rules "out of date", and the autopilot restarts such a desk once
it holds no trades (D-128). The India daily desk held none, but it had ten buys waiting for the
next open (kept across restarts by D-152): restarting it threw them away, and its new run had to
decide again at the next close. "Flat" now also means no order waiting for the next candle
(`Autopilot._waiting`, from the running engine), for both the settings restart and the weekly
or daily change of picks.

**D-170 · A session stopped while it starts stays stopped (2026-11-05).**
After the restart that loaded D-168, two desks ran for the US 1-minute slot (#41 and #51) and two
for India 1-minute (#36 and #48). The autopilot had stopped #41 and #36 while they were still
loading their prices after the restart; the start then finished and set them "running" again
(#41: "stopped by you" at 09:35, "resumed" at 09:36), doubling the load and splitting the slot's
results. The start now leaves a session it finds stopped as it is.

**D-171 · Kairos judges a monthly ranking on its own trade count (2026-11-05).**
Kairos tries a Metis strategy only if its exam years won at least 1.2× what they lost over 20+
trades (D-139). Six-month momentum (#21), the best performer in the sealed last year (Sharpe
1.70) with exam trades winning 12× what they lost, was refused for having 15 trades: a monthly
ranking holds each stock a month, so it makes few trades by design. A ranking's bar is now 12
trades, Metis's own minimum for exam years; the profit-factor bar and the re-test since saving
are unchanged.

**D-172 · A desk given new stocks is studied again (2026-11-05).**
The US 15-minute desk kept opening trades on a judge verdict ("−0.08R, not clear enough to stand
aside") from a study made before the autopilot changed its stocks; re-studied on 5 Nov it stood
aside at −0.24R over 446 unseen past trades, after the desk had lost about 10%. The study covers
the market's study list plus the desk's picks (D-138), so new picks change the verdict. When the
autopilot starts a desk on different stocks than its last run, it now starts a study of that
market and timeframe (at most two at once, D-164); the same stocks don't trigger one.

**D-173 · A crisis in a small, distant economy isn't systemic news here (2026-11-05).**
In the watch the US news gauge reached 66–74 ("Elevated: Kairos's desk opens no new trades and,
in protective mode, closes trades that are losing"), led by "Paraguay President Santiago Peña
resigns after bank collapse": it came through a US feed, so with no recognised place it took the
feed's market (US), and "bank collapse" (banking, 4) plus escalation made it severity 5, as for a
US banking crisis. A story that names only smaller, distant economies (`topics.FAR_WORDS`: most of
Latin America, Africa, smaller Asian and European economies; India's neighbours are not on it) is
now world news (scope weight 0.8 instead of 1.0) at severity at most 3. A story that also names
India, the US or the world list ("spreads to global markets") keeps its full reading. Recent stored
headlines were re-read once with the new rule.
Then the same story from another feed still read as US news at 5: its summary said "the lower
house of congress voted", and "congress" was a US word. With a far country named, the generic
institutions every country has (congress, senate, treasury) no longer make a story American, nor
does an American name ("President Pena, a Trump ally"): with a far country named, only US
markets or the US economy (U.S., United States, the Fed, Wall Street, Nasdaq, S&P, Dow, NYSE,
Powell) keep a story American.
After the fix the US gauge fell from 74 to about 21 though a real chip sell-off was under way
("semiconductor index sinks 11%", market stress, severity 3). Left as designed: a headline
reporting a fall the prices already show is what the desks' charts, stops and judge react to; the
news guard is for news the prices haven't caught up with yet (war, sanctions, bank failures).

**D-174 · An Indices page with every Indian and US index (2026-11-05).**
The user asked for one page with all the indices of both markets, sector indices too. 60 indices
(`catalog.INDICES`, Yahoo symbols checked on 5 Nov): India 11 broad (Nifty 50, Sensex, Next 50,
100, 200, 500, BSE 500, Midcap 100/150, Smallcap 100/250), 21 sector (banks, private and PSU banks,
financial services, IT, auto, pharma, healthcare, FMCG, consumption, consumer durables, metal,
energy, oil & gas, commodities, realty, infrastructure, media, PSE, MNC, services) and gauges
(India VIX, USD/INR); US 9 broad (S&P 500, Dow, Nasdaq Composite and 100, Russell 2000, S&P 400
and 600, NYSE, Wilshire 5000), 14 sector (the 11 S&P 500 sectors, energy through the XLE fund as
Yahoo's index has no prices, semiconductors, transports, utilities) and gauges (VIX, 10-year yield,
dollar index). Each is an instrument whose daily history the autopilot keeps; `GET /api/indices`
gives value, today, 1 month, this year, 1 year and three months of closes; the page groups them
(the market, sectors sorted by today's move, gauges) with an India/US switch. BSE Midcap and
Smallcap had no Yahoo prices and were left out.

**D-175 · Forecasts are made and checked every day, and desks use them once they prove skill (2026-11-05).**
The user asked whether Kairos's candle forecasts were self-learning, trustable and used by the
desks, and whether Agora works as one. They learn from each forecast checked against what
happened (KAIROS §17), but a forecast was only made and checked when someone opened a chart:
414 made, 2 checked, and no desk read them. Now (`kairos/forecast_desk.py`): the autopilot, once a
trading day after the close, forecasts every stock its daily desk trades (which also checks that
stock's due forecasts) and checks every other stock's due forecasts. A market's forecasts show
skill with 60+ checked and direction right more often than a coin by two standard errors; only
then does a live daily desk add `10 × (2 × chance of rising − 1)` score points from today's
forecast for a stock (±10 at full conviction, on a −100…100 score). Live only, like the judge
(D-145), so backtests stay reproducible. On 5 Nov no market had a checked record, so desks don't
use forecasts yet; the first 10-day forecasts come due on 6 Nov.
The round runs for the latest *closed* session, not the market's calendar day: India closes at
2 am on a laptop in California, so a round keyed to India's date missed every day Agora opened
after India's midnight.

**D-176 · The app scrolls only inside its main panel, never the window (2026-11-05).**
The user found every page scrolling past its end into blank space, the sidebar sliding away. The
shell is one screen tall and scrolls in `<main>`, but the screen-reader labels (`sr-only`, which is
`position: absolute`) beside every coloured change had no positioned ancestor, so they were placed
against the window at their spot deep in the content and made the window itself taller. Now
`<main>`, the shell and a dialog's body are `relative`, so such labels stay inside the panel that
scrolls, and `html, body` hide vertical overflow so nothing placed against the window (a chart
tooltip too) can scroll the whole app again.

**D-177 · Desks: 1 day, 1 hour and 15 minutes, on the 250 most traded stocks, with a closer look at
the smaller chart (2026-11-05).**
The user saw that each desk followed only 10–30 stocks and asked: remove the 1-minute desks; trade
long term on daily candles (consulting the hourly chart) and short term on hourly and 15-minute
candles (consulting the 5-minute chart); and trade the top 250 stocks by volume, "if you have a
better suggestion please suggest". Now:
- **Desks** (`autopilot.SHORT_DESKS`): daily, hourly and 15-minute. The 5- and 1-minute desks are
  retired (`Autopilot.retire`, once they have no open trades); every 5- and 1-minute family and
  Kairos's own entries on those charts lost to costs in every test (agora_evidence).
- **Stocks** (`picks.rank`): the 250 most traded stocks of each market by money traded a day
  (price × shares), the median of the last 20 days, ordered by Kairos's strength score so the
  strongest get the desk's slots first. Money rather than share count, and 20 days rather than
  yesterday, are the suggestion: share counts favour cheap stocks, and one day lets a single block
  deal swap a stock in and out (and would move the desks every day). The thin-stock floor stays;
  the per-sector cap on the list is gone (the desk caps open trades per sector, D-168). A desk
  whose list grew by half or more moves to it as soon as it has no open trades.
- **Closer look** (`kairos/closer.py`, live desks only, setting `kairos.smaller_chart`, on by
  default): before an entry the desk reads the smaller chart's candles that closed inside its own
  candle and passes when the last close is below (for a buy) a falling 20-candle EMA. Only for the
  stocks it is about to trade: Yahoo answers about one request a second, so the 5-minute chart of
  250 stocks every 5 minutes wouldn't fit; 250 stocks on the 15-minute desk take about four minutes
  a candle, and India and the US never trade at the same time.
- **Studies** read the study list plus the first 60 picks (`learning.STUDY_PICKS`): all 250 would
  make each study several times slower on a laptop that overheats (D-164). Kairos's brain reads a
  stock's chart in about 0.3 s, so a 250-stock 15-minute desk costs about 80 s of one core a candle.
- **Metis researches the desks' timeframes first** (`metis.timeframes.DESK`): discovery went to the
  timeframes with the fewest strategies, which kept sending it to 5-minute ideas no desk trades and
  that lost to costs on every test; now daily, hourly and 15-minute come first and 5- and 1-minute
  only after them (still allowed, D-118).

**D-178 · Region words count as far away, and saved headlines are read again when the reading
changes (2026-11-05).**
At 14:45 laptop time the US news gauge jumped from 17 to 79 ("Severe": Kairos's desks close their
trades and wait) and India's from 19 to 46 on "Latin American president resigns after bank
collapse": the Paraguay story of D-173 again, this time naming only a region. "Latin American"
wasn't on the far-away list and "american" matched the US words, so it read as US banking stress at
severity 5, from four sources. Region words (Latin America, South and Central America, the
Caribbean, Africa, Southeast and Central Asia, the Balkans, the Pacific islands) now join the
far-away list. And because each such fix used to reach the headlines already saved only by hand,
the news reading now has a fingerprint (`topics.VERSION`, a hash of every word list and rule):
when it changes, Agora reads the last 14 days of saved headlines again on its next start
(`NewsService._backfill`).

**D-179 · The news reader reads the headline, whole words only, and market news needs the market
to agree before it closes a trade (2026-11-05).**
The user: "Kairos and Metis are reading the news wrongly… this can cause huge losses." An audit of
every headline rated 4–5 in the two weeks to 5 Nov (52 headlines) found most of them misread, for
three reasons. (1) The top-severity combinations matched inside words: "coup" in "coupon" and
"couple" put "US sanctions India-based couple…" and three Cummins results stories at 5. (2) The
summary counted as much as the headline: an ice-hockey story that mentions "Russia's invasion of
Ukraine" as background, and a governor's race whose winner ran a state's pandemic response, read as
an invasion and a pandemic; escalating words in summaries ("historic", "nuclear", "crisis") raised
others. (3) Words with other meanings: "home invasion", "demographic invasion", "invasion hype",
"nuclear microreactors", "historic upset". Now (`news/topics.py`): the top-severity combinations and
the escalating words count only in the headline and only as whole words; a topic named only in the
summary counts one level lower and the headline's topics lead; `NOT_WAR` phrases are taken out
before reading; "ease", "mediation" and "lower risk" read as calming. Every misread headline now
rates 1–3 and real crises still rate 5 (tests both ways). The saved headlines are read again
automatically (D-178).
The news guard also stops trusting the gauge alone (`kairos/news_guard.py`): at *elevated* a losing
long is closed only when the desk's watchlist fell 0.5%+ on that candle, and at 90+ a long is closed
unless the watchlist rose or held (before: closed without confirmation). Blocking new trades still
follows the gauge, so a misreading can cost missed trades but no longer sells positions while the
market is calm. A company's own red flag (fraud, a raid, a default…) still needs no confirmation.

**D-180 · Headlines are linked only to the companies they name (2026-11-05).**
The deep audit the user asked for ("history must be checked to know how far this problem
exists") went from the gauge to the news guard's whole history (121 actions since 27 Oct) and
from there to which stocks headlines are linked to. Findings: (1) the guard never closed a trade
on news; (2) the 104 trades it opened at half size on 27–28 Oct and 4 Nov were halved by
misread headlines: re-scored with D-179 the gauge was calm each time (25–38 → 4–20); the 57 that
have closed lost $7,587 and ₹44, so the halving happened to save about as much; (3) 13 entries on
5 Nov were skipped because of the Paraguay story (D-178); (4) a fund's trades were blocked twice
by "red-flag news" that was a Dollar General lawsuit, because the matcher linked headlines to
companies by their first word in Title Case: "United" put every United States or United Nations
story on 20 companies (BNO, UAL, UPS…), "American", "Global", "Federal" and "South" likewise,
"Share India Securities" was on 355 headlines, Nasdaq Inc., Dow Inc. and News Corp on every index
and news story, Trump Media on 312 political stories, and Indian stories about Reliance on the US
company Reliance, Inc. A stock's own news blocks entries, nudges the score ±10 and can close a
trade on a red flag, so wrong links acted on trades. Now (`news/relevance.py`): a first word counts
alone only when no other listed company starts with it and it isn't an everyday word, person or
place (`GENERIC`); a one-word name that is everyday or shared counts only through its ticker or a
fuller name (`EXTRA`); "X Holdings"/"X Group" also matches as "X"; a market's own feed links only
that market's stocks; and when these rules change the last 14 days of saved headlines are linked
again (`NewsService._relink`, a per-company feed's own link kept).

**D-181 · A candle that closed while Agora was closed is traded on the next start (2026-11-05).**
Found by the deep audit: US daily paper sessions had never recorded a single equity point (#30
since 28 Oct, the US daily desk #49). A session acted only on candles that closed while it was
running; every candle that closed while Agora was closed, or before a restart, was loaded as
warm-up history and never traded. A daily desk decides at the close, so it decided only when
Agora happened to be open at that moment: India closes at 2 am on the user's laptop, and on 5 Nov
each restart right after the US close skipped that day's decision. Now a resumed session holds
back the candles after the last one it traded, when they closed within the "late" window (two
candles: 48 hours for a daily desk), and trades them as live candles as soon as it has loaded: an
order waiting from the last candle fills at the next open, the decision on the new candle is made,
the equity curve records it, and the session notes "N candles closed while Agora was closed; they
were traded as if Agora had been open". Look-ahead stays impossible (only closed candles, fills
at the next open). A longer gap is still not back-filled (D-152).

**D-182 · A download skipped because its source is paused isn't "up to date"; stale stocks
aren't ranked; a candle's high and low include its open and close (2026-11-05).**
Found by the deep audit of the desks' price data. (1) On 6 Nov only 144 of ~5,930 US stocks and
135 of ~2,650 Indian stocks had current daily prices; 2,986 US stocks stopped on 27 Oct. Yahoo
paused on 4 Nov after errors (up to a day, D-114), Stooq refuses downloads, and while a source is
paused `cache.ensure` skipped the download without raising, so the autopilot marked every stock
"topped up today". Kairos then ranked its 250 most traded stocks, their strength and the sectors on
prices up to ten days old. Now `EnsureResult.waited` says a source was paused, and the autopilot
counts such a stock as still waiting (it is asked again next round). (2) The ranking leaves out a
stock more than four days behind the market's newest daily candle (`picks.BEHIND_MS`), and keeps its
last ranking while the day's prices are still being topped up. (3) 2,138 saved candles had an open
or close outside their high–low range (Yahoo's daily rows, e.g. ZS on 5 Nov: open 216.62, high
216.43), which a stop or target check reads wrongly; `store.upsert_bars` now widens the high and
low to include the open and close, and the saved ones were repaired.

**D-183 · An index's own fall counts by its size; every check-in checks outputs (2026-11-06).**
The rebuilt check-in (below) found the opposite misreading on its first run: on 5 Nov the S&P 500
fell 4.4% and the Nasdaq 100 6.4%, Wall Street's worst day in 19 months, and the US gauge read
calm (23): "S&P 500 down 4.4% in worst day since April 2025" rated severity 3 like any sell-off
story. Now (`topics.index_drop`) a headline that names an index with a fall and its size right
after it ("Nifty down 3.2%", "Nasdaq 100 plunges 6.36%") is market stress at severity 4 from 2%
and 5 from 4%; a single stock's fall next to a flat index, and small moves, are not.
**Check-ins check outputs (the user, 2026-11-05: "every small thing must be checked").** The watch's
health script only checked that things ran (the newest daily candle anywhere, not how many stocks
were current; the gauge level, not what drove it). It now also prints, every check-in: the gauge's
drivers and every new headline rated 4–5, the most-linked stocks with samples, the share of stocks
with current prices and any impossible candle, each desk's last candle against the latest closed
one and every trade and news-guard action since the last check, the trade arithmetic and balances,
the picks, the judge's verdicts and the forecasts made and checked.

**D-184 · Exchange test symbols aren't stocks; the NSE backup fills only recent gaps (2026-11-06).**
After D-182 the Indian top-up still stood at "22 of 1000" round after round. A thread dump of the
same top-up in a separate process showed why: four NSE test securities in the stock list
(DUMMYHEG, DUMMYINGL1, DUMMYINGL2, DUMMYINXGN) are unknown to Yahoo, so each fell back to NSE's
bhavcopy, one file per day for up to 400 days, which held all four download threads for hours on
every round; with it most Indian stocks' daily prices stopped (1,434 at 2 Nov). Now
`seed.is_test_symbol` keeps them out of the stock list (and `seed.sync` switches off the ones
saved before), and `nse.MAX_DAYS_PER_CALL` is 10: the backup fills a gap of recent days, not years.

**D-185 · Roundups don't drive one stock's alert; the stalest prices are topped up first;
"privilege escalation" isn't war (2026-11-06).**
From the first check-ins that judge outputs. (1) Live blogs and roundups ("Q2 results live: NCC
PAT up 19%; …") name dozens of companies; Airtel and Titan sat on about 40 such updates a day, and
their tone set a stock's own alert, which blocks entries, nudges the score ±10 and can close a
trade on a red flag: on 28 Oct Laurus Labs got a "positive catalyst" from a PVR Inox roundup.
A headline naming more than three stocks (`risk.ROUNDUP_STOCKS`) no longer counts for a stock's
alert. (2) After D-182/D-184 the share of stocks with current prices didn't rise for an hour: the
top-up walks its list in a fixed order and spent the round on stocks already current. It now
tops up the stocks with the oldest saved candle first. (3) "Linux kernel privilege escalation"
read as a severity-4 escalation; such phrases are taken out before reading (`NOT_WAR`).


**D-186 · The price top-up stops after ten minutes a round (2026-11-06).** The check-in found the
autopilot's last round finished 1.4 hours earlier: 1,000 downloads a round held the desks, trials,
forecasts and news behind them. `PRICE_BUDGET_S` (600 s) ends the top-up; the rest carries on in the
next round, 20 seconds later while there is a backlog.

**D-187 · A weak war word alone isn't a war (2026-11-06).** "OpenAI pipeline generates 948 Linux
root escalation exploits" rated severity 4 after D-185 took out "privilege escalation": adding
phrases one at a time doesn't end it. Now the conflict topic needs more than words that are also
everyday English (`WEAK_CONFLICT`: escalation, offensive, retaliation, clashes, military, blockade)
unless a warring place or world word is named too: "Iran war escalation", "offensive in Gaza" and
"clashes on the India-China border" stay conflict news. The check-in's link check now leaves out
roundups, as stock alerts do (D-185).

**D-188 · Other markets' news is world news; "de-escalation" calms (2026-11-06).** In the Asian
AI sell-off "South Korea stocks plunge 8%" came through a US feed and counted as US news at full
weight (world news counts 0.8, D-68): Korea, Japan's Nikkei, Hang Seng, Asia, Europe's indexes and
Australia's ASX are now world words. And "…Iran war de-escalation" read as an escalation (severity
4, its calming ignored) because "escalation" sits inside "de-escalation"; it now reads as calming.

**D-189 · One event from several outlets is one story in the gauge (2026-11-06).** The gauge
groups headlines into stories so coverage volume isn't counted as new risk (D-68), but only by 35%
shared words: "South Korea stocks plunge 8%", "Kospi crashes 8%" and "Asian markets crash… Kospi
plunges 8%" were three stories, so the crash was added three times instead of once with three
sources. Now headlines with the same main topic that name the same place or market and the same
figure ("8%", "1,800 points") are one story, and groups a later headline ties together are merged.

**D-190 · Buys waiting for the open are cancelled when the news turns severe (2026-11-06).** The
India daily desk queued ten buys at the 5 Nov close on calm news; by the next open a global
sell-off (S&P 500 −4.4%, Kospi −8% with a circuit breaker, Nikkei in a bear market) read 84,
"severe", where the news guard opens no new trades. Orders already waiting were not covered by the
guard, which judges only new signals. Now, before a Kairos desk trades a live candle in protective
mode, buys waiting from an earlier candle are cancelled when the market's gauge reads severe (75+),
with a note in the session; exits still go ahead. Also from this check-in: the D-189 grouping lifted
the gauges (US 69 → 94, India 65 → 84), because a crash covered by 21 outlets now counts once with
three-fold corroboration and the separate crises behind it (Kospi, Nikkei) count too, instead of
duplicates filling the list: an honest reading of that day.

**D-191 · Desks really follow their 250 stocks (2026-11-06).** Watching India's first live
candles on 6 Nov: only 30 of the 15-minute desk's 250 stocks got a candle. `desk.launch` kept the
first `MAX_SYMBOLS = 30` of whatever list it was handed, and a strategy's stock list allowed 100,
so since D-177 (the evening before) every desk followed only the 30 strongest of its 250 picks while
the autopilot's log said "250 stocks" and its state recorded the 250 it had handed over. The D-177
tests checked the autopilot's list, not what the desk received. Now `MAX_SYMBOLS` is 250 (Kairos's
picks), a list may hold 500 (a watchlist's limit), and the autopilot compares its picks with the
stocks the desk really follows, so the 30-stock desks move to their full 250 as soon as they hold
nothing. A test now checks a 250-stock Kairos desk definition end to end.

**D-192 · While a market trades, the price top-up steps back (2026-11-06).** In India's session on
6 Nov Yahoo answered daily downloads in 5–13 seconds instead of about one, and the top-up's four
threads competed with the desks' live polls for the same source. While either market is open the
top-up now uses one thread and a two-minute budget a round (`OPEN_BUDGET_S`); the backlog is done
while both markets are closed.

**D-193 · An index's fall is read within its own clause (2026-11-06).** India's opening live blog
"Sensex starts on choppy note, Nifty below 24,500; Power Grid drops 3%" rated 4 as the Nifty
falling 3%: `index_drop` looked 40 characters past the index's name and crossed into the next
clause about one stock. It now stops at the clause's end (";", "|", ", ", " - ").

**D-194 · Live polls overlap their requests; a sector index isn't the market; no stray control
characters (2026-11-06).** In India's session the 15-minute desk on 250 stocks showed "up to date"
two candles behind: its poll asked Yahoo one stock after another, and at 5–13 s an answer a poll
took about 25 minutes. `YahooSource.latest_bars` now keeps up to eight requests in flight (still
started at most one a second), and a stock Yahoo has no prices for is left out instead of failing
the whole poll. "Sensex jumps 400 pts…; Nifty Realty down 2%" rated 4 as the market falling: a
sector index ("Nifty Realty", "Nifty IT") is now skipped by `index_drop`. Writing that pattern
through the shell turned its "\b" into a backspace character; a scan then found the same fault in
Kairos's tool router since D-127 ("web" never matched, so "check the web" didn't offer the web
tools). Both fixed, and a test now fails on any control character in the source.

**D-195 · Yahoo is asked about three times a second, not once (2026-11-06).** After D-194 the
India 15-minute desk still had no candles from today for 218 of its 250 stocks, and Agora's own
log showed Yahoo downloads taking 37–72 seconds. Asked directly at the same moment, Yahoo answered
in 0.1–0.5 s: the wait was Agora's own queue, one request a second shared by two 250-stock desk
polls, the price top-up, the intraday saver and dividend checks. `yahoo.MIN_INTERVAL_S` is now
0.34 s; if Yahoo ever answers "slow down", the source still pauses (D-114).

**D-196 · A view of Agora's threads for diagnosis (2026-11-06).** `GET /api/diagnostics/threads`
lists where each thread is waiting: the watch found a desk's poll stuck with nothing in the log.

**D-197 · A live poll is one request a stock, and a desk with its latest candle waits
(2026-11-06).** The thread view showed the India 15-minute desk's poll queued behind ~2,000
requests: every polled stock cost a second Yahoo request for its dividend and split list (held
only in memory, so each restart emptied it), and after each restart all four desks polled at once,
the two US desks with their market closed. Live polls now use a stock's split list only if it is
already known (the newest candles follow any split, and the feed applies the stored ones), and a
desk that already holds the latest closed candle waits for the next close instead of polling at
start.

**D-198 · Other markets' news doesn't block a market that isn't falling (2026-11-06).** The user:
"Indian market is up yet no trading?" India's gauge read 84 ("severe": no new trades) on the US
chip crash and the Kospi and Nikkei falls, while the Nifty was up 0.3% and the Sensex 0.6%; every
Indian entry was blocked, though the news hadn't reached Indian prices. The gauge now says how much
of its risk is this market's own news (`home_share`); when that is under half and the desk's own
stocks aren't falling today (their average move since the previous close above −0.5%), the guard
lets the desk trade at half size instead of none. This market's own news, or a falling market, still
blocks; exits keep their rules (D-179); company red flags are unchanged. (India's 15-minute and
hourly desks still stand aside on the trade judge's evidence, D-147; that choice is the user's,
25.48.)
The same rule now applies to buys waiting for the open (D-190): they stand when the severe reading
is other markets' news and the desk's stocks aren't falling. First reading on 6 Nov: India's gauge
was 97.5% foreign news, but the India 15-minute desk's 250 stocks were down 1.4% on average (62 of
250 up) while the Nifty 50 rose 0.3%: the momentum names were being sold, so the guard kept blocking.
The guard's note now names that reason when it applies ("news risk severe (other markets' news,
and this market's stocks are −1.4% today): …"), so the desk diary shows why buys were blocked.

**D-199 · "Historic" isn't an escalation; plurals in the top-severity list (2026-11-06).** "Trump
blames Democrats for Wall Street selloff after historic midterm election win" rated 4: "historic"
was an escalating word, but headlines use it for elections, records and upsets. It's gone from the
list. Checking that change found "Stocks suffer historic crash as circuit breakers trip" rating 0:
since D-179 the top-severity phrases match whole words, so "circuit breaker" no longer matched
"circuit breakers". The plurals (circuit breakers, trading halts, lockdowns, coups) are listed too.

**D-200 · A market live blog isn't a stock's own news (2026-11-06).** Titan sat on 20 headlines a
day after D-185 left roundups out: most were ET's "Sensex Today | Stock Market Live Updates: Nifty
surges 230 points…" posts, whose summaries name only a stock or two, so their market tone set
Titan's own alert (which nudges the score ±10 as a catalyst or blocks on bad news). Headlines that
are live blogs ("live", "live updates", "as it happened", "stocks to watch") no longer count for a
stock's alert; they still count for the market gauge.

**D-201 · The forecast round fetches today's candle before checking; the guard says "selling at
the next open" (2026-11-06).** After India's close on 6 Nov the round checked 7 forecasts while 51
were due: 15 minutes after the close only the daily desk's own stocks had today's candle (the
others come with the price top-up later), so 43 waited for the next trading day. The round now
fetches each due stock's recent candles first. And the news guard's note said "closed RATNAVEER"
when it had placed a sell for the next candle's open (a daily desk sells at Monday's open); it now
says "selling … at the next candle's open". Both cuts that day followed D-179: losing trades,
gauge elevated, and the desk's own stocks down 3.7% on the day.

**D-202 · A sector's latest day counts only once most of its stocks have it (2026-11-06).** The
world desk logged "Industrials (India) fell 21.7% … (16.8× a normal day)" and "IT fell 9.1%" five
minutes after India's close on 6 Nov, when only the daily desk's stocks had that day's price: the
sector line is the average of members with both days' prices, so one or two stocks that fell hard
were "the sector". Recomputed on full prices the moves were about 0% and +1.5%. History: the US
moves logged 21 minutes after the 5 Nov close were partly wrong too (Financials logged +5.2%, really
−2.0%; Consumer Staples −3.1% against −1.0%; Real Estate −4.0% against −1.7%; Energy overstated).
Those seven investigations were removed. Now the sector lines leave out the latest day while fewer
than 60% of the stocks that had the day before have its price (`trim_partial_day`).

**D-203 · The price top-up runs again after each market's close (2026-11-06).** Checking D-202 found
India's lines still stopped at 5 Nov after the 6 Nov close: the top-up fetched each stock once per
UTC day, and India's UTC day starts at 05:30 IST, before its 15:30 close, so the day's top-up always
ran before the close and most Indian stocks' daily prices lagged a day (the desks' own stocks were
current through their live polls). It is now keyed to the market's latest closed session. The
check-in's "current" now means having the latest session's candle; "within two days" hid this.

**D-204 · Indian index symbols are Indian (2026-11-06).** Checking the Indices page against Yahoo:
the Nifty 50 matched (25,030.35, +2.01%), but the Sensex showed 77,301 (really 81,028), Bank Nifty
55,914 (59,086) and India VIX 15.19 (17.47), all dated 4 Nov. `yahoo.market_of` guessed a symbol's
market from its suffix and knew only ^NSEI among Indian indices, so ^BSESN, ^NSEBANK, every ^CNX
sector index, ^INDIAVIX, ^CRSLDX, ^NSMIDCP and INR=X were read as US symbols, their daily candles
stamped with US session dates that never matched India's calendar. Since the gauges were added
(late October) India VIX and the Indian sector indices were stale or misdated wherever they were
read, and since D-174 on the Indices page. Their saved daily candles and download log were cleared
and downloaded again with the right dates; a test checks every catalog index's market.

**D-205 · The guard's half-size note says what it did (2026-11-06).** The US 15-minute desk's
first candle on 6 Nov (traded live 2 minutes after the close, all 250 stocks' candles in) wanted
more trades than its 10 open-trade slots; the diary said "News guard: opened XOM at half size"
for trades the desk then refused at its limit. The note now reads "halved the size of a trade in
XOM": the guard's part, not the desk's outcome.

**D-206 · The Paper page groups sessions and can clear stopped ones (2026-11-06).** The user:
"remove all paper strategies which are stopped… very confusing, mostly repeated or older
versions… categorise: Kairos Desk (India), Kairos Desk (USA), Metis (USA), Metis (India),
Stopped". 49 of 61 sessions were stopped, mostly earlier runs of the same desks. The page now
shows one section per group (Kairos by `kind`, Metis by its "Metis" name, the user's own by
market), daily before hourly before 15-minute; Stopped is folded. **Clear stopped** marks stopped
sessions `hidden` in their notes instead of deleting them: Kairos learns from their trades, the
desk's total return counts from its first run (D-146), and a session still opens by its link.
`GET /paper/sessions` leaves hidden ones out; `POST /paper/sessions/clear-stopped` hides them.

**D-207 · Money over time by hours, days or months, with a desk's earlier runs (2026-11-06).**
The user, with a screenshot of a flat line from 11:30 to 14:30: "show it in hours, days,
months… if the stock market is closed how will I know the trend of history". Two causes: the
chart showed only the current run (the autopilot had restarted the India 1-hour desk that
morning, carrying its money on), and it plotted every candle with no longer view. Now a Kairos
desk's chart joins the chain of runs it carried on from (same market and timeframe, the run
stopped latest before it that ended with its starting money, as D-146 counts the return), and
the chart switches between Hours (the last 5 trading days), Days and Months, keeping the money
at the end of each, in the market's time zone. Days is the default once there's a week of
history; a daily desk offers Days and Months only. The y-axis is fitted to the line, so a flat
day no longer sits in a ₹4L–₹16L band.

**D-208 · Kairos's accounts and desks stay out of the user's Start dialog (2026-11-06).** The user,
with a screenshot of the account picker: "what are all these accounts? why repeated and why 89k
and stuff?" All 61 accounts were Kairos's: the autopilot opens a new account for each desk run
and each Metis trial, carrying over the money the last run ended with (D-128), so a 15-minute
desk that had lost 8.6% restarted with $91,365. `GET /paper/accounts` now leaves out accounts
named "Kairos…" or "Metis…" (`include_kairos=true` lists them), and the dialog no longer offers Kairos's desk
strategies, which run themselves. Nothing is deleted: the desks keep their accounts and history.
The user also asked for "heavy optimization in every corner, every small area": recorded as
PROGRESS 25.62, a page-by-page tidy-up sweep.

**D-209 · A paper strategy's whole record, in numbers (2026-11-06).** The user: "for all paper
strategies, whenever I open completed trades it is zero… I want the whole history of strategy
performance: win rate, highest loss, highest wins, top percentile wins… all the statistics". The
cause: each desk restart is a new run, and the page showed only the current run's trades (the
desks had 462 completed trades across their runs; the restarted ones showed 0). The Metis
strategies showing 0 had really closed none yet. Now a session's page counts every closed trade of
the session and, for a desk, of the runs it carried its money on from (D-207), up to 2,000 listed,
and a **Performance** card shows, over all of them (`backend/paper/stats.py`, golden-tested): win
rate, net profit after charges, profit factor, average trade, biggest win and loss (money and %),
average win and loss, the best 10% and worst 10% of trades and the middle trade, charges paid,
longest winning and losing runs, candles held, longs and shorts, and how trades ended (stop-loss,
take-profit, trailing stop, exit rule, square-off, time).

**D-210 · Open trades show their take-profit, trailing stop and partial-profit price (2026-11-06).**
The user, with a screenshot of the open-trades table: "Kairos is not using the concept of stop
loss, trailing stop loss and partial profits… why is that?" It is: since D-140 each desk picks
its exit plan from 54 (stop 1.5/2/3 ATR × target 2/2.5/3.5× the risk × no/2/3 ATR trailing × no
partial sale or half at 1× the risk) by what earned most on history and on paper. On 6 Nov: India
daily and 15-minute, stop 3 ATR and target 3.5×; India hourly adds a 3 ATR trailing stop; US daily
and hourly, stop 2 ATR and target 2×; US 15-minute uses all of them (stop 3 ATR, target 2×,
trailing 2 ATR, half sold at 1× the risk). Of 462 desk trades, 234 ended at the stop-loss, 67 at
the target, 60 at the trailing stop, 66 on the exit rule and 31 at the intraday square-off. The
table showed only the stop. Now each open trade shows its stop-loss (marked when it trails, and
once it has moved up), its take-profit and the price of its partial sale.

**D-211 · News is caution, never a stop; sectors it helps are opportunities (2026-11-06).** The
user: "for news risk, it doesn't mean Kairos stops trading because of news risk; news can be
positive or negative… severity is fine but it should not decide to stop trading… cautious in both
cases, exit or cut losses if negative impact, high opportunity if positive… some news might hurt
one part of the market but help another; Kairos must be opportune on the positive side and
cautious on the negative side." On 6 Nov the India hourly desk skipped every entry at 14:18 on a
US chip sell-off (gauge 74). Changed (`backend/kairos/news_guard.py`):
- **Sectors.** Each story's topic already says which sectors it usually helps or hurts (oil up:
  producers +, oil marketers, paints and airlines −). The gauge now adds these up, weighted like the
  stories (`sector_tilt`), and `backend/news/exposure.py` maps a stock's profile (GICS sector,
  industry, exposure tags) onto them. Helped (net +0.3 or more): score +10 and market risk doesn't
  halve the trade. Hurt (−0.3 or less): half size, and a long 1%+ down is cut.
- **Market risk** (elevated or severe) halves new trades, longs and shorts alike, and blocks none.
  Losing longs are cut once the watchlist falls 0.5% on the candle; at 75+ any long once it falls
  1%. The 90+ exit without price confirmation is gone. Watchful (25–50) changes nothing.
  Other markets' news while this market holds up changes nothing (D-198).
- **Calming news** (the gauge's calming stories, 0.5+, risk under 25) adds 5 to the score.
- **Company news.** A red flag (fraud, default…) still closes the long and is the only "no new
  trade"; negative news halves the trade, takes 10 off the score and cuts a long 1%+ down; a
  positive catalyst adds 10.
- **Queued buys** (D-190) are cancelled at the open only when severe news meets a market down 1%+
  that day, and never in a sector the news helps.
- Cautious mode changes sizes and scores but never closes a trade. Settings text, the News screen,
  the gauge's words, Kairos's `news_risk` tool (which now names the helped and hurt sectors) and
  its prompt say the same.

**D-212 · Every list and table scrolls inside a fixed-height box (2026-11-06).** The user, with a
screenshot of the Kairos diary running down the page: "there is too much scrolling when the
Kairos diary fills up… make it a fixed-size container with scroll… in all the pages of Agora all
containers must be a fixed size (set appropriately for each) and extra length must be scrolled
inside that container", then "do it for the whole app, not just that". A shared `ScrollBox`
(`frontend/src/components/ui/scroll-box.tsx`) gives a box a fixed maximum height, a slim themed
scrollbar, keyboard focus, and table headers that stay in view. Heights: 200 px for short side
lists, 280 for lists inside a card, 380 for medium lists, 480 for tables, 600 for the Kairos
diary and the paper session grids, and the window's height less the page header for a page's
main list (strategies, backtests, the watchlist menu). Applied to 52 places on every page: the
desk diary and what Kairos learned, open and completed trades, fills, activity, Home's lists,
Metis, News, Portfolio, World, Watchlists, Indices, Compare, Data, Diagnostics, backtest results,
Kairos's chat cards and drawer steps, the jobs list. Lists that were already boxed keep their
heights.

**D-213 · A desk that never goes flat still moves to its new list; sector notes quote their story
(2026-11-06).** The watch's last check found two desks on old, short lists: the US hourly desk on
20 stocks since 27 Oct and the India daily desk on 30 since 5 Nov, while their picks were 250. The
autopilot moves a desk only when it is flat (D-169), and these always held a trade. Now, when the
list has grown by half or more and the desk isn't flat, the autopilot pauses it (open trades still
end by their own rules, no new ones open) and restarts it on the full list with the same money
once it is flat. The same check found the news guard's sector notes naming the first top story
that touched the sector (US banks "hurt" by a Paraguayan bank collapse that wasn't what moved
them) or nothing at all ("()"). The gauge now keeps each sector's heaviest story
(`sector_story`), and the note quotes it, or nothing. Quoting the story showed the heaviest war
story behind Airlines and Defence was the Polisario warning about Western Sahara: local stories
from far smaller economies (D-173's list, now with Western Sahara and Morocco's words) no longer
move sectors at all; after the fix the Iran-war stories drive them (Airlines −0.49, Defence +0.49).

**D-214 · A desk whose entries lose trades small instead of standing aside (2026-11-06).** The
user's answer to 25.48: "Trade them small". D-147 stopped a desk opening trades on a chart whose
entries lost on unseen past trades, which left the India hourly and 15-minute desks and the US
hourly desk with nothing to learn from. Such a desk now takes its entries (the judge's picks if
the judge has earned its place, else all) at a quarter of its size (`brain.SMALL_SIZE`, on top of
any news halving), says "Small size…" in each trade's reason and "Trading small" on its card, and
goes back to full size by itself when a study shows its entries earning. Live desks only;
backtests stay as they were. The cost: India's ₹20 brokerage cap saves less on small orders, so
these trades cost a little more per rupee (about 0.03% brokerage against 0.015% on a ₹1.3 lakh
order). The loss on history is expected to continue at small size: this buys live evidence and
learning, not profit.

Testing this found a bug: Kairos sizes a trade from its risk, then caps it at the per-trade limit
(D-131). With a close stop the risk figure asks for more than the cap, so halving the risk changed
nothing. Of the 85 filled trades the guard's notes called half size, 63 were really full size
(checked 6 Nov), and a quarter-size trade came out full size too. `SizeSpec.scale` now takes its
share of the finished size, after every cap, in the shared engine; strategies that don't set it
are unchanged. Past trades are left as they were.

**D-215 · Kairos's desks are never benched and always trade at full size (2026-11-06).** The
user: "let Kairos desk be free of this restriction, it is a self-learning thing… if it made
mistakes I want it to learn and keep logs… keep it at full size and never bench it." This
replaces D-147's stand-aside and D-214's quarter size within hours: a losing verdict from the
trade judge is now only a warning on the desk's card. `SizeSpec.scale` (D-214's fix) stays, because
the news guard's half sizes need it. A judge that has earned its place can still pass on a single
entry; none has today. Paper money only: this rule needs another look before any real money.

**D-216 · The mouse wheel works over scroll boxes (2026-11-06).** The user: "scrolling using mouse
does not work in Agora". My `ScrollBox` (D-212) set `overscroll-behavior: contain`, and in current
Chrome and Edge (152 here) that swallows the wheel even over a box with nothing to scroll, so
wherever the pointer sat over a box the page stood still; the boxes cover most pages. Reproduced in
the browser, confirmed by switching the rule off live (page 0 → 500 px), and removed.

**D-217 · A desk moves to a new list where it stands (2026-11-06, replaces D-213's pause).** The user
saw "Paused" on the India daily and US hourly desks, and a daily desk's trades can last weeks, so
pausing until flat cost weeks of new trades. `PaperRunner.relist` saves the session on the new list
and ends its loop; `PaperService.relist` starts a fresh runner, which resumes through the ordinary
restart path (open trades, stops, waiting orders, cash, same account, same session). A stock with an
open trade or a waiting order stays on the list even if the new list drops it, so every trade still
ends by its own rules (India daily: 250 picks + 4 held = 254). The autopilot uses it whenever the
list grew by half or the weekly refresh changed enough; a study follows, as for any new stocks
(D-172). Session summaries now report the list really followed (`notes.symbols`), not the strategy's
first list: the same mistake as D-191.

**D-218 · Agora can't vanish unnoticed (2026-11-06).** Cause of the 6 Nov stop (12:24 laptop time,
40 minutes): the tray and server died together, with no shutdown line, no "stopped on its own" from
the tray, no Windows sleep or shutdown event. `.venv\Scripts\pythonw.exe` is a launcher that ties its
real Python to itself with a kill-on-close Windows job (measured: flags 0x3000), so ending a launcher
ends its Python instantly and silently; the tray had been started from a tool, so it sat in that
tool's process tree and the tool's clean-up ended the chain. This is the best-supported explanation,
not a recorded observation: nothing logged the moment itself. Three changes: (1)
`scripts/start_detached.ps1` and `restart_agora.ps1` start Agora from a tool through the WMI service,
outside any tool's tree (the user's double-click was never at risk); (2) `backend/uptime.py`, a
heartbeat every 30 s, so the next start writes down any stop nobody saw and any long gap (sleep or a
freeze) in `data/logs/outages.jsonl`: something killed can't report itself, so the next start does.
No separate watchdog process, because CLAUDE §4 says nothing runs while Agora is closed; (3) the tray
now also ends and restarts a server that is alive but silent for two minutes (it only looked at
whether the process existed), and says so once when it gives up. The 43 "stopped on its own" lines
of this week were not crashes: each followed a clean stop asked for by a session's restart, which the
tray can't tell apart. Windows' own job status is no use as a test (every process here is in one).

**D-219 · Stops act on candles missed while Agora was closed; notes say what really happened
(2026-11-06).** The US 15-minute desk's −10.7% traced to one moment: Agora closed 28 Oct to 4 Nov
with overnight trades open; IOVA fell 28% on 29 Oct and 41% by reopening, and the stop acted six days
late for −$8,418. A real stop rests at the broker while the laptop is off, so a resuming session now
replays every missed candle for stocks with an open trade: stops, targets and exit rules act on the
candle they would have, entries stay blocked on those old candles (the existing "arrived late" rule).
This replaces "nothing is simulated while closed" for exits only. New trades are still never
back-filled (D-181's recent window apart), because that would be choosing them with hindsight. The
same trace found a gap note that read "28 Oct 11:15 ET to 20:10 ET" for six days (both dates now) and
"stopped by you" on the autopilot's own restarts; `stop` and `pause` take the reason.

**D-220 · One action log (2026-11-06, the user's request, WEEKEND_BRIEF §8).** `backend/actions.py`,
in its own `data/actions.db`, so it works when the main database is locked or damaged and never adds
writes to the database trading depends on; a queue and one thread write it, so it can't block or stop
the work it logs. Hooks sit at the choke points, not in every caller: jobs (backtests, studies,
downloads), AI calls, Metis's rounds and each idea, Kairos's learning rounds and lessons, autopilot
rounds, desk starts and moves, desk orders and closed trades and events, news reads, data fetches,
forecasts, trials, settings, app starts and stops, outages. An entry says who started it and why,
what came out, whether that was right, how long it took. Work running at a stop is marked `cut_off`
at the next start. 90 days are kept. Read it on the Logs page, at `/api/actions`, or with
`scripts/actions.py`.

**D-221 · Volume Yahoo lost (2026-11-06).** Yahoo re-serves Indian hourly candles with volume 0 for
the first hour (76% of them in three weeks; 37,403 hourly candles), though the same candle had volume
when first served. The engine's volume cap then took 5% of nothing and refused the entry as "too
large", so India hourly backtests and desks lost entries there, and volume indicators read nothing.
Three layers: `upsert_bars` never replaces saved volume with 0; a candle with a price range and no
volume is treated as "volume unknown" and capped by the candle before; `scripts/repair_zero_volume.py`
restored 4,925 candles from the 15-minute data. The 32,478 older candles have no 15-minute data left
to repair from; the engine rule covers them. Yahoo's closing 15-minute candle is also one price 28%
of the time in its own data: not repairable, and accepted as a flaw of the source.

**D-222 · Silence is a failure (2026-11-06).** `backend/diagnosis/alarms.py`, on Home at `/api/alarms`,
empty when all is well: stops nobody saw, desks with no fresh prices, work that started and never
finished, work that should have happened and hasn't, a full disk. `backend/diagnosis/reconcile.py`
and `market_data.py` check the books and the data, read-only, against the live database.

**D-223 · NSE, NYSE and Nasdaq stocks only (2026-11-06, the user's request).** All 2,617 Indian
stocks were already NSE. Of 5,892 US listings, checked against Nasdaq Trader's official lists, 523 are
left out: 263 NYSE American, 225 blank-check shells, 17 preferred or notes, 17 no longer listed, 1 on
Cboe (the stock CBOE itself, a large company, left out because the user named the exchanges: put it
back by removing its line). `backend/seed_data/excluded_us.csv`, made by
`scripts/exclude_universe.py`; 5,369 remain. Nothing is deleted: a left-out stock keeps its saved
prices and stops updating. One with an open paper trade stays followed until the trade ends. ADRs
(Alibaba) and partnership units (Icahn) are common equity and stay; a first draft of the rules wrongly
caught them. Series BE and BZ NSE stocks stay; they can't be traded intraday on the real exchange,
which belongs in the live-readiness review (27.13).

**D-224 · Why Kairos misses opportunities: measured (2026-11-06, task 27.5).** Over 28 days, every
up-day of 5% or more in a stock above the thin-stock floor (2,746 of them): India 415 (248 outside the
250, 150 in the 250 but on no desk's list yet, 12 followed with no signal, 3 traded, 2 refused for a
full desk); US 2,331 (2,035 outside, 169 followed with no signal, 108 not on a list, 15 traded, 4
refused). **The 927 "desk full" refusals account for 6 of the 2,746**, and refused trades did no
better than filled ones held the same time, so rotating out the weakest trade has no evidence behind
it and is not built. The trade check earned its place: the 108 US signals it skipped lost 1.26% on
average. **A causal scanner test over two years found no edge in chasing:** bought the next open
after a breakout, an unusual-volume day or a 5% day, after costs, none beats simply holding every
liquid stock in study and exam, in India or the US. The one exception is the US bounce after a heavy
fall on high volume (5 days: +2.10% study, +0.65% exam; medians +0.51% and +0.21%), for Metis to test
under the luck check. Big days also tend to fade (next 5 days −1.3% India, −1.6% US; 46% up). So the
main reason is that entries don't yet predict, not that restraints block them: trades reach about
+1% to +2% then end negative. What the evidence supports is done: desks now take up their list
at once (D-217) and refresh it every day while the market is closed, instead of weekly. No scanner
was added to chase moves: it would have added losing trades. `backend/diagnosis/opportunities.py`
repeats the measure.

**D-225 · A busy database never stops a session (2026-11-06).** Applying D-223 made the watchlist
update hold the database for about 50 seconds while Agora started. Seven sessions (Metis's trials, no
desk) failed to load and the failure path marked each stopped for good. A real fault waiting to hit
a desk. A session's start now retries for three minutes; if the database is still busy it stays saved
as it was and carries on at the next start. The seven were restored with their money and trades.

**D-226 · The Data tab covers everything and lists only trouble (2026-11-06, the user's request).**
`/api/data/coverage` counts every active stock (daily) or every stock desks follow (shorter charts),
and returns stock by stock only those with a problem. The calendar is read once a market instead of
once a stock. The answer is kept and refreshed behind the scenes, so only the first call after a
start waits (up to about 20 seconds).

**D-227 · The strategy combiner (2026-11-06, the user's request, WEEKEND_BRIEF §5).** A new strategy
kind, `combined`, so one engine runs it in backtest and on paper (D-04): `backend/strategy/combined.py`
runs each member on its own context over the same candles. Modes: all agree, any one, veto, a vote.
A member's signal stays good for five candles, because two strategies rarely fire on the same one;
the member that fired last owns the trade (its stop, target and exit rule run it). States are rebuilt
from recent candles on a stock's first candle, so a restart decides as a backtest does. A shared-money
blend is not a new kind: that is the Portfolio (Phase 15), which already runs in both, and the screen
says so. The guards against luck (`backend/metis/combine.py`): judged by the same
`trial.judge_against` as every change (exam gain after costs, study not worse, trades kept, overfit
check, luck check); every combination is written in the notebook so it counts as a try; `repair`, for
Metis and Kairos, picks blockers on the study years only, admits only strategies that already passed
a real test (two lucky things can't excuse each other), and judges at most three per strategy.
Kairos desks and monthly rankings can't join yet: they work across stocks or from a learned brain.
First real test: #12 + #11, all agree, India daily: rejected (exam ₹4.18 lakh against ₹7.33 lakh for
#12 alone).

**D-228 · Half-adjusted candles around big splits (2026-11-06).** The audit's wild-move check found
false crashes of −98% on the same few dates across many US stocks. Yahoo's history of a stock that
split can mix adjusted and unadjusted rows, and undoing the adjustment over-corrected some: AMTD read
0.77 and 0.0126 on neighbouring days; DHY's whole history was ten times too low; Motilal Oswal
had a false −75% on 1 Jan 2024. `backend/data/repair.py` finds rows wrong by exactly the split's ratio,
using the first candle after the split as the anchor; only 3-for-1 or bigger (a real halving looks
like a 2-for-1), and nothing is changed if no level lands. 79,806 candles in 134 stocks repaired;
`data/backups/split-repair-undo.csv` lists each change. New downloads pass through the same repair.
Backtests and studies before this read those false crashes, so the affected studies are redone.

**D-229 · News words are read next to what they describe (2026-11-07).** The user's lead: "Rupee hits
six-month high on oil price decline" read as oil rising, because a direction word anywhere in the
headline counted. The direction word nearest the oil word decides now. The same check found "RBI
holds repo rate" read as a hike (banks up, property down): a central bank standing still now moves no
sector. "Trade war fears ease" counted as armed conflict; a trade war is a trade story. "IEA Sees
4,800 GW of New Renewables", the user's other lead, already reads as no topic.

**D-230 · A wide idea keeps its stocks (2026-11-07).** `trial.try_new` cut every new strategy to its first
eight stocks except rankings, or six when none were named, so most of Metis's new strategies were tested
on very few stocks and too few trades for the luck check to pass. Claude's batch titled "US 250"
ran on 8 and was relabelled in the notebook. Finished rules with their own list now keep it; the model's
own ideas stay capped, because a wide run is slower and its lists are unreliable.

**D-231 · A wide list must be judged as it stood at the time (2026-11-07).** With D-230 lifting the
stock cap, two India strategies passed every test on today's 250 most traded stocks, with exam gains of
+155% and +164%. That looked too good, and it was: those are the stocks that did well, so the list
carries hindsight. `trial.survivorship_check` runs a list of more than 30 stocks again on the stocks most
traded just before the exam began, chosen only from what was known then, and it must make money, win
at least 1.1× what it loses and beat the index. Momentum (#24) fell to a loss on its trades (0.91×) and
+20.7% against +28.7% for the Nifty: rejected, archived. The 50-day breakout in an uptrend (#23) kept
+56.5% against +28.7%, 1.46×, 153 trades: kept. Stocks since delisted aren't saved, so some
hindsight remains, and the true figure is likely lower.

Added to D-231 the same day: changes to a strategy pass the same check when their list is wide
(`judge_against`). Batch E's update to #22 kept its own 30 stocks, so it was below that line; checked by
hand, it passed (+83.5% against +68.2%, 2.03×). Keeper #25's fair result is about a seventh of what
today's list showed: quote the fair figure, never the first one.

**D-232 · A wide idea isn't a revision of a narrow one (2026-11-07).** D-79 judges a "new" strategy that
matches an existing one against that strategy, on its stocks. So India's RSI(2) "on 250" ran on the two
stocks of #5, and the US rankings on 30. A list over 30 stocks is now judged as itself when the match
holds 30 or fewer. Rerun: India RSI(2) lost on the fair list (0.92×), US calmest 20 trailed the index,
US 12-month momentum top 20 was the strongest near miss of the weekend: +153.7% against +68.2%,
2.19×, 72 exam trades, luck check 30%. Rejected; the bar stays where it is.

**D-233 · A frightened market is never "Calm" (2026-11-07).** The page review found the gauge reading
Calm 14/100 on the weekend after the worst US day in 19 months (QQQ −6.5%, VIX 17 to 28), because
headlines fade with a six-hour half-life, weekends included, and Kairos becomes readier to buy at
calm levels. A fear gauge (VIX, India VIX) at 1.25× its 90-day median holds the gauge at watchful and
says why. It stops there on purpose: fear doesn't halve trades or sell anything, which stays with the
news itself (D-211). The headline half-life is unchanged.

**D-234 · Real money: keep the rule, review later (2026-11-09, the user's decision on 27.13).** CLAUDE §4
stands: no broker, no API keys, no real orders. Paper trading runs on unchanged rules for at least three
months, then the user reviews against the gates in `docs/LIVE_READINESS.md` (about 9 February 2027 at
the earliest). No broker or order code before he decides again.

**D-235 · The US 12-month momentum near miss is watched on paper (2026-11-09, the user's request).** It failed
only the luck check (D-232), so it stays rejected as a keeper: Metis and Kairos don't count it, and the bar
is unchanged. The user asked to watch it anyway. Saved as its own strategy, "US 250: monthly 12-month
momentum, top 20 (paper trial)", on the exact rules and 250-stock list it was judged on, and started on a
$100,000 paper account (session 68), large enough for one-twentieth of it to buy the dearest stocks, with
the trade check off so paper shows the rules as tested. It joins the three-month review (D-234).

