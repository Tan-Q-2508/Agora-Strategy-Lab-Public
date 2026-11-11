# Agora: Product Specification v3.0

**Status:** v3.0 (October 2026). Replaces v2.2, which covered F&O and broker APIs
(parked in `docs/LATER.md`).

## 1. What Agora is

A local, single-user lab where a non-technical person can:

1. **Build** a trading strategy visually (blocks) or in Python (code editor).
2. **Backtest** it on historical data for Nifty 50 stocks or US stocks/ETFs, with
   realistic Indian and US trading costs.
3. **Paper trade** it live during market hours with a simulated account.
4. **Understand** results through clear charts, plain-English summaries, and an
   optional local AI helper.

### Not in scope (v3.0)
- Futures, options, currencies, commodities, crypto
- Any broker connection or real order placement
- Cloud hosting, multi-user, mobile apps
- Fundamental data (news arrives with Kairos only, §13)

## 2. Users and principles

One user: the owner. No coding background. Wants **maximum automation, minimum
reading**. Every design choice bends toward: double-click start, sensible defaults,
plain-English messages, no maintenance.

## 3. Markets and instruments

| Market | Universe | Currency | Session (local) | Timezone |
|---|---|---|---|---|
| India (NSE) | Nifty 50 constituents + the Nifty 50 index (benchmark only) | INR | 09:15–15:30 | Asia/Kolkata |
| US | User watchlist of stocks/ETFs (default: SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM) + SPY as benchmark | USD | 09:30–16:00 | America/New_York |

- Yahoo symbols: India uses the `.NS` suffix (`RELIANCE.NS`); Nifty index `^NSEI`.
- The user can add any US ticker. India's default universe is the Nifty 50; since Phase 18
  (D-93) Agora also knows the Nifty 500 and Microcap 250 and the S&P 500, 400 and 600, Nasdaq-100
  and Dow 30 stocks, with sector, industry, size and exposure tags, for watchlists, sectors and the
  world desk; their prices are downloaded when used.
- **Nifty 50 membership changes over time.** Store memberships with effective dates
  (`universe_members`). Seed with the current list. Backtests show a badge
  "Uses today's Nifty 50 list (survivorship bias)" unless historical membership has
  been imported (see `docs/DATA_SOURCES.md` §6).
- Pre-market, post-market, and extended US hours are ignored in v3.0.

## 4. Data

Full detail in `docs/DATA_SOURCES.md`. Summary:

- **Primary:** Yahoo Finance via `yfinance`: daily history (many years) and
  intraday (short windows).
- **Backups for daily bars:** NSE bhavcopy (India), Stooq (US).
- **Everything is cached in SQLite.** Agora fetches only missing bars.
- **Intraday history accumulates:** while Agora is open, it saves intraday candles
  for the universe each day so intraday history grows beyond Yahoo's window.
- **Timeframes:** 1d (primary), 1h, 15m, 5m, 1m. Backtests on intraday timeframes
  warn when history is short ("Only 58 days of 5-minute data available").
- **Adjustments:** splits and dividends from Yahoo. Signals use split-adjusted prices;
  P&L uses actual traded prices on the simulated date (see D-07).
- **Data health page:** coverage per symbol/timeframe, last update, gaps, source,
  and a "Refresh now" button.

## 5. Strategies

### 5.1 One strategy format
Every strategy, however it's built, compiles to the same **Strategy Definition**
(JSON, versioned, stored in `strategy_versions`). It contains:

- `universe`: market + symbols (or "all Nifty 50")
- `timeframe`
- `entry` rules (long only in v3.0 for India delivery; long and short for India
  intraday and US; see §7.4)
- `exit` rules: signal exits, stop-loss (% or ATR), take-profit, trailing stop,
  time exit (e.g. "exit intraday positions at 15:15 IST")
- `position_sizing`: fixed quantity, fixed amount, % of equity, or risk-based (% risk
  per trade using stop distance)
- `limits`: max open positions, max per symbol, max daily loss (pauses new entries)
- `product`: India `intraday` or `delivery`; US `cash`
- `parameters`: named, typed values with ranges, used by optimization

### 5.2 Visual builder (default)
- Drag-and-drop blocks in plain English, Streak-style:
  "When **RSI(14)** crosses below **30** AND **Close** is above **SMA(200)** → **Buy**".
- Block types: indicators, price fields, numbers, comparisons (above, below, crosses
  above, crosses below, between), logic (AND, OR, NOT), time conditions, and
  position state (e.g. "in position for more than 5 bars").
- Live validation: incomplete blocks glow amber with a one-line fix hint.
- A live **preview chart** shows where the rules would have fired on the selected
  symbol over the last ~6 months.
- **Templates:** at least 8 starter strategies (MA crossover, RSI mean reversion,
  Bollinger reversion, Donchian breakout, Supertrend trend-follow, opening range
  breakout (intraday), MACD momentum, 52-week-high momentum).

### 5.3 Code editor (advanced)
- Monaco editor with Python syntax, autocomplete for the Agora strategy API, and
  inline error markers.
- Code runs in a **RestrictedPython** sandbox: no imports except an allow-list
  (`math`, `statistics`, Agora's indicator API), no file/network/OS access, CPU-time
  and memory limits per bar, deterministic.
- API shape (the strategy implements `on_bar(ctx)`; `ctx` exposes closed bars only):
  ```python
  def on_bar(ctx):
      rsi = ctx.ind.rsi(ctx.close, 14)
      if not ctx.position and rsi[-1] < 30:
          ctx.buy(size=ctx.size.percent_equity(10))
      elif ctx.position and rsi[-1] > 70:
          ctx.sell_all()
  ```
- A visual strategy can be "opened as code" (one-way conversion; the original
  visual version is kept).

### 5.4 Indicators (built in-house, golden-tested)
SMA, EMA, WMA, RSI, MACD, Bollinger Bands, ATR, ADX, Stochastic, CCI, VWAP (intraday,
session-anchored), Supertrend, Donchian Channel, Keltner Channel, OBV, ROC, Highest/
Lowest over N, 52-week high/low, previous day high/low/close, opening range high/low.
Added with Kairos (Phase 9.1): DEMA, TEMA, HMA, VWMA, KAMA, Ichimoku, Parabolic SAR, MFI,
Williams %R, Aroon, Chaikin Money Flow, Stochastic RSI, pivot points.

Implemented in `backend/indicators/` with vectorized and incremental (streaming)
versions that are tested to produce identical values.

### 5.5 Ranking strategies (Phase 16, D-91)
A fourth kind besides blocks, code and the Kairos brain: each month a **ranking strategy** ranks
every stock of its universe (normally the whole index) by **momentum** (the rise over the last 1–24
months, leaving out the latest 0–3) or **low volatility** (the calmest daily moves), optionally only
risers / stocks above their 200-day average, and holds the top 1–30 in equal shares (95% of the money
÷ the number held) until the next month. It runs in the same engine as every strategy; its scores use
closed candles only. Three starters: *Momentum: the 10 strongest risers*, *Momentum: six months, top
5*, *Low volatility: the 10 calmest stocks*.

### 5.6 The look-ahead check (Phase 16, D-88)
One click in the strategy editor (**Look-ahead check → Run the check**): the rules run on the whole
period and on growing slices with the later candles hidden, and again with more older history; any
signal or indicator value that changes is listed in plain words ("RELIANCE, 5 Mar 2024: with later
candles visible the rules bought; with them hidden they did nothing"). Code can't read a later candle
in the first place (`shift()` only looks back), so the check mostly proves it, and finds rules that
depend on how much history is loaded.

## 6. Backtesting

### 6.1 Running a backtest
- Pick strategy (+ version), market, symbols, timeframe, date range, starting capital
  (defaults ₹10,00,000 / $100,000), cost profile, slippage.
- Runs in a background worker thread with a progress bar and an ETA; the UI stays
  responsive. Cancel button.
- Every run is saved with its exact inputs (strategy version hash, data snapshot
  range, cost schedule versions) so it can be reproduced.

### 6.2 Engine rules
- Event-driven, bar by bar, shared with paper trading (D-04).
- **Signals are computed on bar close; market orders fill at the next bar's open**
  plus slippage. Stop and limit orders fill intrabar when the bar's range crosses
  the price, using the conservative assumption when both stop and target are inside
  one bar (stop first). See `docs/COST_MODEL.md` §4.
- Volume cap: an order cannot exceed 5% of the bar's volume (configurable). Excess is
  rejected with a logged reason. No partial fills in v3.0.
- India intraday positions are force-closed at **15:20 IST** (configurable, must be
  before 15:30). US positions can be held overnight.
- Circuit limits: if a bar is locked at its price band, no fills that bar (best effort,
  detected by high == low == close on volume).
- Corporate actions: positions held across a split are adjusted in quantity; dividends
  are credited on ex-date for delivery/cash holdings.

### 6.3 Results
- **Headline cards:** Total return, CAGR, Max drawdown, Sharpe, Win rate, Trades,
  plus "vs benchmark" (Nifty 50 / SPY buy-and-hold over the same period).
- **Charts:** equity curve vs benchmark, drawdown underwater chart, monthly returns
  heatmap, trade P&L distribution, price chart with entry/exit markers per symbol.
- **Tables:** trades list (sortable, filterable, CSV export), per-symbol breakdown.
- **Full metrics:** total/annualized return, volatility, Sharpe, Sortino, Calmar, max
  drawdown + duration, win rate, profit factor, expectancy, avg win/loss, largest
  win/loss, avg holding time, exposure %, turnover, total charges paid, charges as % of
  gross profit.
- **Honesty panel** (always visible): data source and gaps, survivorship warning, short
  intraday history warning, number of trades (warn if < 30: "Too few trades to trust").
- **Tear sheet: "How much could be luck"** (Phase 16, D-89): the Sharpe ratio with its 90% range,
  the chance it is really above zero, the luck check over a sweep's settings, the days of results
  needed to be 95% sure, other histories it could have had (yearly return and worst drop ranges),
  the same trades in other orders, the six-month Sharpe line, each year's return, the five deepest
  falls (from, lowest, recovered, days), and the risk numbers (a bad day, the worst 5% of days, best
  and worst day and month, winning months, tail ratio, skew, kurtosis), with plain sentences.
- **Plain-English summary**, generated by rules (no AI needed), e.g. "This strategy made
  42% over 5 years, less than simply holding the Nifty 50 (61%). Its worst drop was 18%."
  If Ollama is available, an "Explain more" button asks the AI helper.

### 6.4 Robustness tools
- **In-sample / out-of-sample split:** optional; shows both periods side by side.
- **Parameter sweep:** grid over 1–2 parameters, results as a heatmap; warns about
  overfitting when the best cell is an isolated peak, and (Phase 16, D-89) gives the
  **probability of backtest overfitting** ("chance the best setting is just the luckiest", CSCV),
  warning at 50% or more.
- **Walk-forward:** rolling optimize-then-test windows; shows stitched out-of-sample
  equity.
- **Compare runs:** overlay up to 4 equity curves with a metrics table.

## 7. Live paper trading

### 7.1 Sessions
- The user picks a strategy version and clicks **Start paper trading**. Agora runs it
  against live data until the user clicks **Stop** or closes Agora. Nothing runs when
  Agora is closed (D-06).
- Multiple strategies can paper trade at once, each with its own **paper account**
  (starting capital, cost profile).
- Outside market hours the session shows "Market closed. Next open: Mon 09:15 IST" and
  waits; it does not auto-close the session.

### 7.2 Live data
- Polls Yahoo for the latest bars of the strategy's timeframe (minimum 1-minute
  candles; polling every 60 s for 1m strategies, aligned to bar close + a few seconds).
- **Data freshness badge** always visible: shows the age of the last received bar
  (green < 2 min, amber < 10 min, red otherwise) and "Delayed data" text if Yahoo's
  timestamps lag.
- If Yahoo fails, the session pauses new entries, keeps existing stops monitored on
  the last known data, and shows a plain-English banner. It retries with back-off.

### 7.3 Execution simulation
- Same fill model and cost model as backtests.
- Every order, fill, rejection and pause is logged with a plain-English reason.
- Missed time: if Agora was closed or the laptop slept, the session resumes on restart
  **without** back-filling trades it would have taken while closed (shown as a gap).

### 7.4 Short selling
- India: shorting allowed only for `intraday` product. Delivery is long-only.
- US: shorting allowed, no borrow fees modeled in v3.0 (shown as a caveat).

### 7.5 Live screen
- Real-time equity, today's P&L, open positions with live unrealized P&L, recent
  fills feed, strategy signals log, price chart with markers, freshness badge.
- Pushes via WebSocket; the UI updates without refresh.
- A **"Backtest vs live"** panel compares live paper results to a backtest of the same
  strategy over the same dates once enough days have passed.
- **Money over time** switches between **Hours** (the last 5 trading days), **Days** and
  **Months**, so the trend reads while the market is closed. A Kairos desk's chart joins the
  earlier runs it carried its money on from (D-207).

- A **Performance** card shows the strategy's whole record over every closed trade (a desk's
  earlier runs included): win rate, net profit, profit factor, biggest win and loss, the best and
  worst 10% of trades, streaks, charges, and how trades ended (D-209).

### 7.6 The Paper page
- Sessions are grouped: **Kairos Desk (India)**, **Kairos Desk (USA)**, **Metis (India)**,
  **Metis (USA)**, **Your strategies (India/USA)**, then **Stopped**, folded. Each group runs
  daily, then hourly, then 15-minute. **Clear stopped** takes stopped sessions off the page;
  their trades stay in the database for Kairos's learning (D-206).

## 8. AI helper (optional, Ollama)

Full detail in `docs/AI_ASSISTANT.md`. Summary:
- Default model `qwen3.5:4b`; alternative `gemma4:e4b`; user-selectable.
- Features: explain a backtest, explain a trade, draft a strategy from a plain-English
  idea (returns a Strategy Definition that must pass validation and is shown to the
  user before saving), summarize a paper trading day, and answer "what does this metric
  mean?" questions.
- The helper never places orders and works offline. Kairos (§13) extends it into an agent
  that can start paper sessions and reads public news headlines.
- If Ollama isn't installed or running, the AI features show a friendly setup card;
  everything else works.

## 9. Screens

1. **Home**: market status (India/US open or closed + countdown), active paper sessions
   with live P&L, recent backtests, data health summary, quick actions.
2. **Strategies**: library (cards with mini equity sparkline of last backtest),
   templates, create/duplicate/archive.
3. **Strategy builder**: visual blocks or code, parameters panel, preview chart,
   version history, "Backtest this" button.
4. **Backtest setup → Backtest results** (as in §6).
5. **Compare**: overlay runs.
6. **Paper trading**: list of sessions + live session screen (as in §7.5).
7. **Charts**: free-form chart of any symbol with indicators (Lightweight Charts), on
   1d, 1h, 15m, 5m and 1m candles. Each chart loads all the history there is (daily since
   2000; intraday: whatever Yahoo still serves plus every older candle Agora saved) and
   opens zoomed to the recent stretch (2 years, 4 months, 30, 10, 3 days); scroll to see
   older candles (D-92).
8. **Data**: data health, coverage, refresh, universe management.
8a. **Watchlists** (Phase 18): ready-made lists (indices, sectors, sizes, factor lists, themes,
    ETFs), your own lists and Kairos's and Metis's lists, with "Where money is moving" (sectors).
8b. **World** (Phase 18): world events and their effects on each market's sectors and stocks,
    sudden moves and their most likely cause, and what past events actually did.
9. **Settings**: general (currency formats, theme), cost profiles, AI helper,
   diagnostics (run live data tests, open log folder, export a support bundle).
10. **Onboarding**: first-launch 3-step tour (pick markets → download data → run a
    template backtest).

Global: command palette (Ctrl/Cmd+K), toasts, keyboard shortcuts, empty states with a
clear next action, skeleton loaders, light/dark themes.

## 10. Costs

Full detail in `docs/COST_MODEL.md`. India uses an effective-dated charges table
(brokerage profile, STT, exchange transaction charge, SEBI fee, stamp duty, GST, DP
charge). US uses commission (default $0) plus regulatory sell-side fees, also
effective-dated. Slippage is configurable in basis points per market.

## 11. Non-functional requirements

| Area | Requirement |
|---|---|
| Startup | Double-click to browser in < 10 s after first-run setup |
| First run | Fully automatic setup; progress shown; < 10 min on normal broadband |
| Backtest speed | 1 symbol × 10 years daily < 2 s; Nifty 50 × 10 years daily < 30 s; 1 symbol × 60 days of 5m < 5 s (on the user's laptop) |
| UI | 60 fps animations; no layout shift; fixed-size panels; works from 1366×768 up |
| Reliability | Crash-safe SQLite (WAL); a crash never corrupts saved runs |
| Privacy | No outbound traffic except Yahoo/NSE/Stooq/Ollama(localhost) and the news feeds in D-59 |
| Logs | Rotating logs in `data/logs/`; a support bundle excludes nothing secret because there are no secrets |
| Accessibility | WCAG AA contrast, full keyboard navigation, reduced-motion support |

## 12. Acceptance checklist (v3.0 is done when)

- [ ] Fresh laptop: double-click → Agora opens, onboarding runs, Nifty 50 daily data
      downloads, a template backtest completes and shows results.
- [ ] A visual strategy and a code strategy produce **identical** results for the same
      logic.
- [ ] Backtest of the golden test strategies matches hand-calculated expectations.
- [ ] Paper trading session runs a full NSE day and a full US day without errors;
      trades match a backtest of the same day within the documented tolerance.
- [ ] Yahoo outage simulation: app stays usable, shows banners, recovers.
- [ ] AI helper works with Ollama present and degrades gracefully without it.
- [ ] Every user-facing error has plain-English text and a next step.
- [ ] UI passes the design checklist in `docs/DESIGN_BRIEF.md` §9.

## 13. Kairos, the trading agent (Phase 9)

Full detail in `docs/KAIROS.md`. Summary:
- A chat agent (Ctrl/Cmd+J, every screen) that operates all of Agora from plain English:
  analyse charts, scan stocks, read news, forecast, create/backtest/optimise strategies,
  research the best strategy for a set of stocks, start/stop paper trading.
- **Charts → Kairos toggle:** draws support/resistance zones, trendlines, chart patterns,
  candlestick patterns and a forecast range on the chart, with a verdict panel.
- **Kairos desk:** Kairos paper-trades a watchlist on its own (paper money only), with a
  thesis and review per trade, and learns from the results.
- Analysis, forecasts and trade decisions are tested code; the local model plans and
  explains (D-57). Forecasts are always ranges with a track record (D-58).

Acceptance (added to §12):
- [ ] Charts: toggling Kairos draws levels, patterns and a forecast range on real data.
- [ ] Kairos answers "analyse RELIANCE", backtests a strategy on chosen stocks and starts
      paper trading from one plain-English request.
- [ ] A Kairos desk trades a watchlist for a full day; each trade has a thesis and review.
- [ ] "Find the best strategy for these stocks" reports what held up out of sample.
(These are section 10 of `docs/ACCEPTANCE.md`.)

**Phase 10 additions** (requested by the user 2026-10-22; `docs/KAIROS.md` §14–15, D-67 to
D-70): the world's toolkit (93 indicators, 93 candlesticks, 41 chart patterns including
harmonics, 19 setups, 28 templates) and a playbook that covers all of it; world business and
geopolitical news from public feeds and GDELT's free API, read for topic and severity into a
news risk gauge; a live **News** screen; and Kairos's **news guard**, fixed rules that stop,
shrink or close its desk's trades when the news turns dangerous (paper money only; the AI
never places orders). Acceptance: section 11 of `docs/ACCEPTANCE.md`.

**Phase 11 additions** (requested by the user 2026-10-22; `docs/KAIROS.md` §16–19, D-71 to
D-75): Kairos's **trade check**, a learned filter in the shared engine that skips signals which
tend to lose after costs (only after proving its judgement); **reviews** of backtests and paper
sessions (costs, win rate versus break-even, why trades failed although the rules were met) and
**Improve with Kairos**, which saves a better version only when it held up on unseen trades;
**predicted candles** on the chart that are kept, compared with the candles that formed, and
learned from; an **always-on learner** while Agora is open; **futures and options** knowledge and
an options calculator (no F&O trading); and a new **logo**. Acceptance: section 12 of
`docs/ACCEPTANCE.md`.

## 14. Metis, Kairos's AI researcher (Phase 12)

Requested by the user on 2026-10-22 (`CHANGELOG.md`). Full detail in `docs/METIS.md`; decisions
D-76 to D-78. Summary:
- **Metis** (Greek for wise counsel) is the AI part of Kairos that comes up with ideas. Switched
  on (Settings → Kairos, or the Metis screen), it keeps researching on its own while Agora is
  open, round after round (a minute of rest between rounds by default, D-103), with no instructions needed. An optional focus
  steers it.
- Each round the local AI model reads how the user's strategies did in their **study years**
  (the first 70% of the period), thinks, and proposes up to three ideas: a filter, a settings
  change, or a new strategy.
- Code tests every idea in the shared engine on the **exam years** (the last 30%, which Metis
  never saw) and keeps it only if it did better after costs by fixed rules. Kept ideas become a
  new strategy version (old ones kept) or a new strategy, get a full backtest, and become a
  Kairos lesson. Every idea, kept or not, is in Metis's notebook, which feeds the next round.
- Metis never trades, never starts paper sessions and never changes the Kairos brain (D-56).
  It needs the AI helper (Ollama); without it the screen explains how to set it up.
- Screens: the **Metis** screen (switch, live status, Research now, focus, the notebook with
  each idea's reasoning, verdict and numbers, and how Metis thought), a Metis card in Settings →
  Kairos, and the Kairos tool `metis` ("what has Metis found?").

Acceptance: section 13 of `docs/ACCEPTANCE.md`.

**Phase 14 additions** (requested by the user 2026-10-22; `docs/METIS.md` §11–15, D-81 to D-83):
Metis starts as a **senior quant**, not from scratch: a quant **library** (the research method,
backtest statistics, documented anomalies and factors, volatility and regimes, mean reversion,
portfolio construction, risk, costs, market structure, machine learning pitfalls), a golden-tested
**toolkit** (`backend/quant/`), and **the expert's first look**, a checklist in code that turns
each strategy's study-year evidence into findings and first experiments. Every verdict also passes
a **luck check** (deflated Sharpe ratio over the number of tries). Metis follows a **research
agenda** with four directions (improve what's in use, improve the others, discover new
strategies, find new stocks for working strategies), can **simplify** rules or change a strategy's
**stocks**, and keeps working from its playbook when the AI helper isn't available.
Acceptance: section 14 of `docs/ACCEPTANCE.md`.

## 15. Revision control for strategies (Phase 13)

Requested by the user on 2026-10-22 (`CHANGELOG.md`). Full detail in `docs/REVISIONS.md`;
decisions D-79 and D-80. Summary:
- A strategy is its logic. When Kairos or Metis improve a strategy, the change is saved as its
  next **revision** (v1 → v2 → v3) with who made it, what changed in plain words, why, and the
  evidence; never as a new strategy. Every revision is kept; **Restore** brings any back as a new
  revision.
- Before saving anything "new", Kairos and Metis check whether it is the same logic as a strategy
  the user already has (same indicators compared the same way, numbers ignored, a filter or two
  either way; or the same template). If so, it becomes a revision of that strategy, only if it did
  better on that strategy's own stocks.
- The same strategy on other stocks (or with settings tuned for them) is an **opportunity**, not a
  strategy (§16). Only genuinely different logic is a new strategy, and Metis adds at most two a day.
- Screens: **Revisions** on each strategy (timeline with author badges, changes, evidence,
  compare, restore); strategy cards show the current revision and its author.
- **Forward checks** (Phase 16, D-90): a revision Kairos or Metis saved on its own is re-tested
  against the one before it on the candles formed after it was saved; when it clearly stopped
  holding up, the earlier rules come back as a new revision (setting **Undo what stops holding up**,
  on by default; otherwise a button).

## 16. Opportunities and the portfolio (Phase 15)

Requested by the user on 2026-10-22 (`CHANGELOG.md`). Full detail in `docs/PORTFOLIO.md`;
decisions D-84 to D-86. Summary:
- **Opportunities**: Kairos and Metis keep finding strategy-and-stocks pairings that work: the
  opportunity scanner tries the user's strategies on every stock of the market (stocks chosen on
  the study years, judged on the unseen exam years, with the luck check); Kairos's research and
  Metis's ideas add more. Ranked by evidence.
- **Portfolio**: the user gives a budget for a market (for example ₹1,00,000 or $1,000) and a risk
  level. The allocator (tested code, never the AI) screens the candidates, picks a few that don't
  move together, weighs them by risk (hierarchical risk parity on shrunk covariances) tilted
  towards stronger evidence, caps each, keeps a cash reserve, and fits the plan to the budget (no
  sleeve that can't buy a share). Every choice has a plain-English reason.
- **Backtest a portfolio**: all sleeves run together in the shared engine on one budget, rebalanced
  monthly by moving free cash, against the benchmark, with each sleeve's contribution.
- **Paper trade a portfolio**: one paper session per sleeve; while Agora is open the portfolio
  manager rebalances, retires sleeves that stopped working and adds new opportunities, writing
  every move in the portfolio's diary. Paper money only; orders only from the strategies.
- Screen: **Portfolio** (allocation with reasons, backtest, paper trading, diary, rebalance
  preview, opportunities). Kairos tool `portfolio`.
- **How to spread it** (Phase 16, D-91): *Best strategies* (the allocator, default), or a monthly
  *Momentum* or *Low volatility* ranking of the whole index as one sleeve. **Forward checks** (D-90)
  re-test each sleeve on the candles formed since it was added and wind down one that clearly
  stopped holding up.
Acceptance: section 15 of `docs/ACCEPTANCE.md`.

## 17. The landscape (Phase 16)

Requested by the user on 2026-10-22: find the similar tools available today, AI and coded, and make
Agora, Metis and Kairos the best version of them. `docs/LANDSCAPE.md` (D-87) maps 22 tools (AI
research agents such as Microsoft's RD-Agent(Q) and AlphaAgent, AI trading teams such as
TradingAgents, AI signal products, no-code builders such as Composer and Streak, quant platforms
such as QuantConnect and Freqtrade, research and ranking tools, portfolio libraries, TradingView),
what Agora takes from each, and what it deliberately doesn't do. Phases 13–15 build the adopted
features; Phase 16 (built 2026-10-23, D-88 to D-91) the rest: the look-ahead check (§5.6), tear
sheets and the probability of backtest overfitting (§6.3, §6.4; also on Metis's tries), forward
checks of what Kairos and Metis saved and of portfolio sleeves on new candles with undo, and ranking
strategies (§5.5) with ranking portfolios (momentum or low volatility, `docs/PORTFOLIO.md` §9).
Acceptance: section 16 of `docs/ACCEPTANCE.md`.


## 18. Watchlists, sectors, several timeframes, the world desk and the autopilot (Phase 18)

Requested by the user on 2026-10-23 (`CHANGELOG.md`). Full detail in `docs/WORLD.md`; decisions
D-93 to D-99. Summary:
- **Several timeframes** (D-97): any rule can read a bigger chart of the same stock on its last
  finished candle ("the weekly close is above its 40-week average"; code `ctx.chart("1w")`); the
  Kairos desk only trades with the bigger chart's trend (setting, on); the chart reading reads the
  monthly, weekly and daily (or the intraday equivalents) together with one verdict; Metis can
  propose bigger-chart filters.
- **The world desk** (D-95, D-96): 33 kinds of world event (wars, chokepoints, tariffs, sanctions,
  oil, central banks, elections, pandemics…) recognised in the news, each with its chain of effects
  on India's and America's markets, sectors and exposure groups; 87 past events since 1990 measured
  on saved prices and every live event measured after 1, 5 and 20 trading days, so the map learns;
  unusual moves of the market or a sector investigated (news, a GDELT search, oil, gold, the dollar,
  the rupee, VIX, yields, the other market) with the most likely cause and a confidence; a
  geopolitics playbook in the knowledge pack. Screen **World**; Kairos tools `world_events`,
  `why_move`.
- **Sectors** (D-98): equal-weight sector and industry lines, rotation, breadth, booms and slumps
  ("Where money is moving" on Watchlists; Kairos tool `sectors`).
- **Watchlists** (D-93, D-94): every stock on NSE (2,617) and the US exchanges (5,892), D-102; about
  2,300 of them in an index, with full profiles; 110 ready-made lists (indices, sectors,
  sizes, factor lists including NSE's smart-beta indices and price factors rebuilt daily, themes,
  ETFs); your own lists; Kairos's and Metis's lists with their reasons (Kairos tool `watchlists`).
- **The autopilot** (D-99, amends D-06): with **Work on their own** on (default), when Agora opens
  Kairos keeps prices up to date, picks its own stocks and runs paper desks, and Metis (now on by
  default) researches; nothing to add or trigger. Paper money only; nothing runs while Agora is
  closed. Home card **Kairos and Metis**.

Acceptance: section 18 of `docs/ACCEPTANCE.md`.

## 19. Learning from bad trades, background tasks and the long watch (Phase 19)

Requested by the user on 2026-10-24 (`CHANGELOG.md`). Decisions D-107 to D-111.
- **The trade autopsy** (D-109, `docs/METIS.md` §18): Metis opens up every study-year trade of the
  strategies it studies (about 19 readings on the strategy's chart, 6 on each of two bigger charts,
  second opinions from up to three other strategies on the same stocks, the market's mood), finds
  the readings that separated losers from winners and held on later trades, tests them as filters on
  unseen years, and ranks the next candidates by which readings have held up before.
- **Background tasks stay visible** (D-107): a screen shows its running task again when reopened,
  and the top bar shows everything that runs. **Refresh now** updates every stock with saved prices.
- **Ollama stays on** while Agora is open (D-108); **Start Agora reuses the open tab** (D-111).
- **Every timeframe** (D-118): Metis discovers and tests strategies on daily, hourly, 15-, 5- and
  1-minute candles wherever there is saved history, the timeframes with the fewest strategies first;
  Kairos runs a short-term desk (15-minute by default) beside its daily one.
- **Trailing stops** (D-119): Kairos's desks trail every trade (3 × ATR by default); Kairos's
  improvement and Metis's first look try one on strategies without it; drafted strategies get one.
- **No terminal window** (D-124): Agora runs from a tray icon (Open, Restart, Open the log folder,
  Stop) and opens in its own window without tabs or an address bar; a Desktop shortcut starts it.
- **The long watch**: Claude Code sessions on the laptop watch the backend log in 2-hour rounds,
  exercise every screen, fix what breaks, restart Agora, and repeat (PROGRESS Phase 19).

## 20. Active trading: partial exits, the index bar and a trader's knowledge (Phase 20)

Requested by the user on 2026-10-25 (`CHANGELOG.md`). Decisions D-125, D-126.
- **Partial exits** (D-125, COST_MODEL §4 rule 11): any strategy can sell part of a trade at profit
  targets (half at 1R, or a third at 1R and a third at 2R, or its own steps in R, percent or ATR)
  and move the stop to the entry price after the first, letting the rest run. The builder has a
  "Partial exits" row; code strategies use `ctx.scale_out`. A trade that scales out counts once.
  Kairos's desks sell half at 1R by default.
- **Diagnose, then fix** (D-125): when a strategy is weak, Metis looks for why (the autopsy and the
  first look: indicator, market trend, news, bigger chart, costs, exits) and tests the matching fix,
  now including a stop-loss and partial exits; "Improve with Kairos" tries partial exits too.
- **Beat the index** (D-126): Metis keeps a new strategy only if it beat buying and holding the
  Nifty 50 (or SPY) in the exam years.
- **A trader's knowledge** (D-126): active-trading setups and exits, institutional investors and
  how they move markets, and trading through volatility, with honest numbers on what a retail
  trader can earn.
- **Not changed:** Agora still places no real orders and connects to no broker (CLAUDE.md §4).
  Making it a real trading app later would be a separate, deliberate decision.

## 21. Review fixes and research on the internet (Phase 21)

Requested by the user on 2026-10-25 (`CHANGELOG.md`). Decisions D-128, D-129.
- **Every losing trade explained** (D-128): from three trades, each loser is checked against the
  textbook causes (against the trend, the market falling, choppy, thin volume, chased, stopped by
  noise, gave the gain back); what the losers share and the winners don't becomes a fix to test.
- **Metis doesn't loop** on a strategy with nothing new, and tests "more stocks" ideas on known
  stocks (D-128).
- **Desks follow Settings → Kairos**: a desk restarts with new settings once it holds no trades.
- **World news search recovers** after GDELT refuses, instead of failing every few minutes.
- **Research on the internet** (D-129): Kairos's `web_research` tool and one web question per
  Metis round, with sources; switch it off in Settings → Kairos.

## 22. Paper sessions poll every candle (Phase 22)

Requested by the user on 2026-10-26 (`CHANGELOG.md`): after a full trading day in India and the US
no paper trade had been made. Decision D-130.
- **Live paper sessions check for new prices after every candle**, all day, for as long as Agora is
  open; a session that was asleep (laptop asleep, Agora busy) checks as soon as it wakes.
- A trading day missed while sessions weren't checking is not traded afterwards (no back-fill).

## 23. Fair shares, every timeframe, every chart, every stock (Phase 23)

Requested by the user on 2026-10-27 (`CHANGELOG.md`). Decisions D-131 to D-137.
- **Fair shares of the money (D-131).** One trade never takes the whole account: a strategy can cap
  a trade at a share of the money, and Kairos's desks hold up to ten trades with at most a tenth of
  the money each (D-136; Settings → Kairos → Most open trades), so other stocks can still be bought
  and sold.
- **A desk on every timeframe (D-132).** Besides its daily desk, Kairos runs a paper desk on the
  hourly, 15-minute, 5-minute and 1-minute charts in each market (Settings → Kairos → Short-term
  desks: all of them, one of them, or off).
- **Every bigger chart together (D-132).** Each desk reads all its bigger charts at once (a 5-minute
  desk: 15-minute, hourly and daily; a daily desk: weekly and monthly) and doesn't trade against
  them. Metis's trade autopsy reads every bigger chart too.
- **Every stock (D-133).** Kairos scans every stock Agora has prices for (about 2,300 Indian and
  5,700 US stocks), not only the Nifty 200 and S&P 500, and each desk trades the best of the whole
  market. Since D-177 every desk follows the market's **250 most traded stocks** (money traded a
  day, the median of the last 20 days), strongest first; the list is picked again every day.
- **Long and short term (D-177).** Kairos trades long term on a daily desk, which consults the
  hourly chart before it buys, and short term on hourly and 15-minute desks, which consult the
  5-minute chart. The 5- and 1-minute desks were retired (they lost to costs on every test).
- **Orders the candle can't take (D-135).** An order bigger than a candle can absorb (5% of its
  volume) buys what it can instead of being thrown away, so short desks don't leave money idle.
- **Updates reach an open window (D-137).** A window left open across an update reloads itself
  when it asks for a page the new version replaced, instead of staying blank.
- **Restarts.** Agora may be restarted whenever new code needs to load, without asking the user
  (his standing instruction).

## 24. Kairos trades on everything it knows, and learns at once (Phase 24)

Requested by the user on 2026-10-28 (`CHANGELOG.md`). Decisions D-138, D-139, D-140.
- **Everything on the chart.** Kairos's desks read chart patterns, support and resistance,
  trendlines, candlesticks, divergences, volume, the trend, named setups, the bigger charts and
  the news, and now also every indicator's own signal (Stochastic, CCI, ADX, Supertrend,
  Ichimoku, OBV and more), the entries of classic strategies (Turtle, Connors RSI-2, Bollinger
  reversion, pullbacks, VWAP, opening range) and quant signals (z-score, 12-1 momentum,
  regression fit, volatility breakout).
- **A chorus, not a crowd.** The indicators vote together: their agreement moves Kairos's score
  a limited amount, so more indicators add evidence without making it trade on everything.
- **Metis's strategies, when Kairos believes in them (D-139).** Kairos tries a strategy Metis
  saved only when it passes Kairos's own, stricter check (strong unseen exam years, and no loss
  since it was saved); nothing obliges it to. At most three per market at once (Settings →
  Kairos), each on its own small paper money; kept when it works live, ended when it doesn't,
  stopped at once after losing 10%.
- **Its own exits (D-140).** Kairos knows stop-losses, targets, trailing stops and partial
  profits, and chooses how to use them: it plays every entry from history and every closed paper
  trade under 54 exit plans and trades with the one that has earned the most per trade, when it
  also held up on years it didn't choose from (Settings → Kairos → "Kairos chooses its own
  exits"; off, it uses the numbers there).
- **It learns what works.** Each signal's record is measured on the market's history and updated
  by every paper trade; signals that work count up to twice as much, ones that don't are switched
  off. A desk uses a new lesson on the next candle after a trade closes.

## 25. Claude's research sprints (Phase 25)

Asked for by the user on 2026-11-03 (`CHANGELOG.md`), approved the same day: "I want you to
spend all this week's credits in just training Kairos and Metis hard", Kairos's desk as much as
Metis. Decisions D-141 to D-145. Claude Code, in a local session on the laptop, does strategy
research inside Agora with the user's real data and leaves the results behind as code and a
tested playbook; Agora never needs Claude to run.
- **The AI reads everything (D-141).** Reading size Automatic, up to 32,768 tokens, stepping
  down when the graphics card is full; Metis's evidence fits instead of losing its start.
- **Ideas that can work (D-142).** Metis's ideas that are never or always true are caught
  before a backtest and the real range goes back to Metis.
- **The lab (D-143).** 32 strategy families with a reason each, a headless runner on the shared
  engine over the most traded stocks, a ledger of every test, a sealed vault of the latest year
  opened once, finalists chosen by fixed rules, the regime map, and the playbook.
- **Metis starts from the playbook (D-144)**, the entries that suit today's market first, and
  re-tests each on the user's stocks.
- **Kairos's trade judge (D-145)** learns which combinations of readings lose and, once it has
  proved itself on unseen past trades, lets live desks pass on those entries.
- **A desk stands aside where its entries lose (D-147)**, after costs on unseen past trades,
  until a study shows them earning.
- **A restarted desk's return counts from its first run (D-146)**, the user's report
  (2026-11-03) that paper trading's total return was wrong.
- **Claude in place of the local model (the user, 2026-11-03):** in laptop sessions Claude does
  the research Metis's model would (families, reasons, judging results) at full speed; results
  stay in Agora as families and the playbook, since Agora can't call Claude without a paid API.
- **First sprint, 2026-11 (laptop, 2026-11-03):** 342 tests in two rounds; 22 finalists by the
  fixed rules; the vault promoted 15 (all US daily) and failed all 6 India finalists and the US
  hourly one. Results in `docs/METIS.md` §23a.
- Not built: fine-tuning the local model (D-61); capital-gains tax in results.

## 26. The weekend audit, the combiner and the road to live trading (Phase 27)

Requested 2026-11-06; the full request is `docs/WEEKEND_BRIEF.md`. In short:
- **Strategy combiner:** the user, Metis and Kairos can combine two or more strategies (all agree,
  any, veto, vote, blend) so that one cancels another's bad trades, judged by the same honest tests.
- **Universe:** NSE stocks for India; NYSE and Nasdaq stocks for the US.
- **Data tab:** the whole data set, showing only warnings and errors.
- **Screens:** tabs instead of stacked groups on Paper; the same grouping on Strategies and
  Backtests; built for a pro trader, simple to look at.
- **Kairos:** never benched, always full size (D-215); a better way of choosing stocks so it misses
  fewer opportunities; a full log of every trade that feeds its learning.
- **Quality:** a repeatable end-to-end diagnosis that catches silent failures, and one action
  log for everything Agora does: how it started, what it did, what came out, whether it was right.
- **Live trading:** the user wants it within a month. §4 of CLAUDE.md forbids it until he decides;
  Phase 27 ends with a readiness review, not with order code.

## 28. The weekend audit additions (Phase 27, user request 2026-11-06)

Every action gets a log (Logs page). Home shows alarms only when something needs a look. Paper,
Strategies and Backtests group by tabs. Strategies can be combined (all agree, any one, veto, vote) and
tested under the usual tests. Every closed trade has its whole story. The Data tab covers the whole
set and lists only stocks with problems. The universe is NSE, NYSE and Nasdaq stocks. A desk's list
moves without pausing it. Stops act on candles missed while Agora was closed. `docs/DIAGNOSIS.md`
describes the repeatable diagnosis; `docs/LIVE_READINESS.md` what real money would need.
