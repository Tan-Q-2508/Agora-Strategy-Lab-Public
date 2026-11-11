# KAIROS: Agora's trading agent

> *Kairos* (καιρός) is the ancient Greek word for **the decisive moment**: the right time to
> act. In the Agora, Athens' marketplace, it was the merchant's sense of when to buy and
> when to sell. It's the one thing every trader is trying to find, so it's the agent's name.

Kairos is an optional agent inside Agora. The user talks to it in plain English and it
operates the whole app: it analyses charts, draws support/resistance and patterns, reads
the news, forecasts a likely price range, builds and backtests strategies, starts paper
trading, runs its own paper-trading desk and learns from the trades it makes.

This document is the reference for Phase 9, Phase 10 (the world's toolkit, world news and
the news guard, §14–15) and Phase 11 (the trade check and reviews, predicted candles that learn,
the always-on learner, futures and options: §16–19). Decisions D-56 to D-75 lock its key choices.
Phase 12 adds **Metis**, Kairos's AI researcher, in its own doc: `docs/METIS.md` (D-76 to D-78).
Phases 13–15 add revision control (`docs/REVISIONS.md`: Kairos reuses or revises strategies, never
copies them; its research winners become opportunities when you already have the strategy), Metis's
quant library (Kairos's `lookup_knowledge` reads it too), and portfolios (`docs/PORTFOLIO.md`: the
Kairos tool `portfolio`).

---

## 1. The one idea that makes it work

The laptop's 6 GB graphics card runs a ~4-billion-parameter model (D-10). Such a model is
good at **understanding a request and choosing tools**, and poor at arithmetic, long
reasoning chains and remembering numbers. So Kairos is split in two:

| Part | What it is | What it does |
|---|---|---|
| **The analyst** (`backend/analysis/`) | Deterministic, golden-tested code | Swings, support/resistance, trendlines, 41 chart patterns (incl. harmonics), 93 candlestick patterns, 19 setups, volume, divergences, Fibonacci, trend regime, forecasts, scores |
| **The trader's brain** (`backend/kairos/brain.py`) | Deterministic strategy (`kind: "kairos"`) running in the shared engine (D-04) | Decides entries/exits from the analyst's signals, weighted by what has actually worked |
| **The voice** (`backend/kairos/agent.py`) | The local LLM with tool calling | Understands the user, plans, calls tools, explains results in plain English |

Every number Kairos shows comes from code, never from the model. That makes Kairos far
more capable than the model alone, and keeps it honest (D-57).

Kairos's "seasoned trader" knowledge has three sources:
1. **The analyst's rules**: textbook definitions of patterns, indicators and market
   structure, written as code with tests.
2. **A knowledge pack** (`backend/kairos/knowledge/*.md`): a curated trading playbook
   (indicators, patterns, risk management, position sizing, market structure, behavioural
   traps, India/US market specifics). Relevant sections are retrieved into the prompt.
3. **Measured experience**: its "training" (§8) measures how every signal actually
   performed on 10+ years of the user's own market data, and its paper trades keep
   updating those numbers.

## 2. Honesty rules (non-negotiable)

- **Paper only.** Kairos can only ever trade simulated paper accounts. There is no
  broker code (D-02).
- **Code decides, the model explains.** Orders come from the brain's code in the shared
  engine. The LLM can *start or stop* a paper session the user asked for, but it never
  picks an individual order, size or price (D-56).
- **Forecasts are ranges with a track record.** Every forecast shows a likely range
  (50% and 80% bands) and how often Kairos's forecasts for that stock were right in
  testing ("direction right 54 of 100 times; coin flip = 50"). Never a single
  certain-looking number (D-58).
- **Patterns carry their own statistics.** Each pattern shows how often it worked on this
  market's history ("Bull flags on Nifty 50 stocks, 10 years: rose 10 days later 58% of
  412 times").
- **Numbers are checked.** Kairos's replies pass the same number check as the AI helper
  (D-52).
- Every Kairos text carries the footer "Kairos is a research tool, not financial advice.
  Paper money only."

## 3. The analyst (`backend/analysis/`)

All functions take numpy OHLCV arrays (split-adjusted, D-07) and are **causal**: anything
reported as known at candle *i* uses candles `0..i` only. The chart snapshot and the brain
use the same code.

| Module | Output |
|---|---|
| `swings.py` | Zig-zag swing highs/lows at two degrees (minor ≈ 1.5×ATR, major ≈ 3×ATR reversal), each with the candle where it became *confirmed* |
| `levels.py` | Support/resistance zones: clustered swing prices (tolerance 0.6×ATR), touches, strength 0–100, role flips, nearest zones above/below |
| `trendlines.py` | Best rising/falling support and resistance lines through swings (≥ 2 touches, no closes through the line), channels |
| `chart_patterns_world.py` | Phase 10 (D-67): harmonics (Gartley, bat, alternate bat, butterfly, crab, deep crab, cypher, shark) with Fibonacci ratio tables, AB=CD, three drives, rounding top; `chart_patterns.py` adds rising/falling channels |
| `candles_world.py` | Phase 10: the rest of TA-Lib's 61 candlestick functions plus common extras (93 in all) |
| `setups.py` | Phase 10: breakaway gaps, islands, NR7 and inside-bar breakouts, springs/upthrusts, key reversals, pocket pivots, new 52-week highs/lows, golden/death crosses, squeeze breakouts (signal family `setup`) |
| `chart_patterns.py` | Double/triple top & bottom, head & shoulders (+ inverse), ascending/descending/symmetrical triangle, rising/falling wedge, rectangle, bull/bear flag, bull/bear pennant, cup & handle, broadening. Each has key points, trigger (breakout) level, invalidation level, measured-move target, status (forming / confirmed / failed / target reached) and confidence |
| `candles.py` | 24 candlestick patterns (doji family, hammer/hanging man, inverted hammer/shooting star, engulfing, harami, piercing/dark cloud, morning/evening star, three soldiers/crows, marubozu, spinning top, tweezers, inside/outside bar) with trend context |
| `volume.py` | Relative volume, spikes, breakout volume confirmation, OBV/price divergence, accumulation/distribution days, Chaikin money flow |
| `divergence.py` | Regular and hidden RSI and MACD divergences against swings |
| `trend.py` | Regime (strong up … strong down) from MA stack, ADX, swing structure (higher highs/lows) and regression slope; volatility regime |
| `fibonacci.py` | Retracements and extensions of the last major leg |
| `forecast.py` | §5 |
| `report.py` | The full chart report: bias score −100…+100, confidence, verdict in plain English, key levels, an educational trade idea (entry/stop/target, reward:risk), what would change the view, and every drawing for the chart |
| `signals.py` | Causal per-candle signal arrays for the brain and for training (§8) |

Defaults are documented in each module's docstring and pinned by golden tests on
hand-built price series (D-11).

## 4. Indicators added (Phase 9.1; Phase 10 adds 58 more, §15)

DEMA, TEMA, HMA, VWMA, KAMA, Ichimoku (tenkan, kijun, senkou A/B, chikou), Parabolic SAR,
MFI, Williams %R, Aroon (up/down/oscillator), Chaikin Money Flow, Stochastic RSI, and
classic pivot points (P, R1–R3, S1–S3 from the previous session). They follow D-34's rules:
vectorized + streaming versions, golden tests, catalog entries usable in the block builder.

## 5. Forecasts (`backend/analysis/forecast.py`)

The forecast is a blend of three models, each producing a distribution of paths H candles
ahead (default H = 10 daily candles; 12 intraday):

1. **Volatility model**: random walk with an EWMA volatility (λ = 0.94) and a small,
   shrunk drift.
2. **Analogues**: the 50 past moments (this stock, and peers in the same market) whose last
   20 candles looked most like today's (z-scored returns), and what happened next, scaled
   to today's volatility. Windows overlapping the present are excluded.
3. **Trend persistence**: the regression slope of the last 50 closes, damped over the
   horizon.

The median path and 10/25/75/90% bands are mixed by weights the walk-forward test (below)
earns for each model, starting at analogues 0.5, volatility 0.4, trend 0.1.

**Track record** (shown with every forecast): a walk-forward test over the last ~250
forecast points (every 5 candles, each using only data available then) reports direction
hit rate, error versus a no-change forecast (skill), and how often the 80% band contained
the outcome. Kairos also saves its live forecasts and scores them when the horizon passes.

Chronos-style forecasting models are parked (`LATER.md`): they need PyTorch (~2 GB) and
published tests show no clear edge over simple baselines on stock prices.

## 6. News (`backend/news/`)

- `NewsSource` interface with RSS implementations (no keys, D-02): Yahoo Finance per-ticker
  headlines (`feeds.finance.yahoo.com/rss/2.0/headline?s=`), Google News search per
  company, Economic Times Markets, Livemint Markets, Business Standard Markets, MarketWatch
  top stories, plus a fake for tests. All checked reachable on 2026-10-21 (D-59).
- Stored in `news_items` (deduplicated by link/title hash). Kept 30 days.
- Each item is linked to instruments by symbol and company-name match, and scored with a
  finance word list (positive/negative/uncertain) to give a sentiment from −1 to +1.
  When Ollama is ready, Kairos can re-read the top headlines for a better judgement.
- Fetched on demand and every 10 minutes **while Agora is open and a Kairos feature is in
  use** (D-06). Throttled per host; failures fall back silently with a "news unavailable"
  note.
- News is used live only. History has no news archive, so backtests of the brain treat
  news as neutral (shown in the honesty panel).

## 7. The voice: the chat agent (`backend/kairos/agent.py`)

### 7.1 Loop
1. Build the prompt: persona + rules + the user's current screen/symbol + relevant
   knowledge-pack sections + recent lessons from memory (§8.3) + the conversation so far
   (trimmed to the context budget).
2. Call Ollama `/api/chat` with `tools` (streaming). Thinking mode is on for planning
   (setting `kairos.think`).
3. If the model calls tools: validate arguments (pydantic), run them, stream a step card
   to the UI, send back a compact result (≤ 1,500 characters), repeat. At most 10 tool
   rounds per request.
4. The final answer streams to the UI, passes the number check, and is saved.

Small-model safeguards: tools are few and high-level (one call does a whole job);
symbol names are resolved fuzzily ("reliance", "apple", "TCS.NS"); invalid arguments go
back with a plain hint; a tool call written as JSON text is recovered; and a rule-based
**fallback router** understands common commands ("analyse INFY", "backtest X on Y", "stop
all paper trading") if the model fails or Ollama is absent.

### 7.2 Tools (everything the user can do in Agora)

| Tool | Does |
|---|---|
| `analyze_chart` | Full report for a symbol/timeframe; opens the chart with Kairos drawings |
| `forecast` | Forecast range + track record |
| `scan_market` | Ranks stocks (a market, a list, or the whole universe) by setup score, pattern or trend |
| `get_news` | Latest headlines and sentiment for a stock, a market, the world (`about: "world"`) or a topic (war, tariffs, rates, oil…) |
| `news_risk` | The news risk gauge for India, the US or the world, what drives it, and what the desk's news guard does (Phase 10) |
| `market_overview` | Index trend, breadth, biggest movers, top news |
| `lookup_knowledge` | Explains any indicator, pattern, metric or concept from the knowledge pack |
| `list_strategies` / `list_templates` | What exists |
| `create_strategy` | From a template (with symbols/parameters) or from a plain-English idea (D-52 draft loop); saves it |
| `run_backtest` | Backtests a strategy on chosen stocks/dates; waits; returns the headline numbers; opens results |
| `optimize_strategy` | Parameter sweep or walk-forward |
| `research_strategy` | "Find the best strategy for these stocks" (§7.3) |
| `compare_backtests` | Opens the compare screen for runs |
| `start_paper_trading` / `stop_paper_trading` / `paper_status` | Manage paper sessions |
| `start_desk` / `stop_desk` / `desk_status` | Kairos's own paper-trading desk (§9) |
| `get_lessons` | What Kairos has learned so far |
| `refresh_data` | Download missing prices |
| `open_screen` | Move the app to a screen (chart, results, session, …) |

Tool results can carry a **UI directive** (`{"navigate": "/charts?..."}`); the app follows
it when "Follow Kairos around the app" is on (default on).

### 7.3 Strategy research ("build the best strategy for these stocks")
A job that, per request:
1. Analyses each stock's character: trendiness (ADX, efficiency ratio), mean reversion
   (variance ratio, RSI reversal stats), volatility.
2. Picks candidate strategies that suit that character (all templates + the Kairos brain).
3. Sweeps each candidate's main parameters on the first 70% of the period (in-sample).
4. Tests the best few on the last 30% (out-of-sample); drops anything that collapses
   out-of-sample or is an isolated peak (D-41).
5. Runs walk-forward on the finalists, ranks them by out-of-sample Sharpe with a penalty
   for few trades, and saves the winner as a strategy.
6. Reports what it tried, what won and why, and what could still go wrong.

## 8. Training and learning (`backend/kairos/learning.py`)

### 8.1 Training ("study the history")
For every signal family (each chart pattern breakout, each candlestick pattern, support
bounce, resistance breakout, divergences, trend regimes, volume spikes …) Kairos finds
every occurrence in the stored history of the market's universe (causal, no look-ahead)
and measures what happened over the next H candles: count, hit rate, average return, and
the base rate for comparison. Results go in `kairos_signal_stats` (source `history`). It
runs automatically the first time Kairos is used on a market/timeframe and again when
data grows by 5%+ (a job with a progress bar, a few seconds to a minute).

### 8.2 Learning from paper trades
Every Kairos desk trade records the signals active at entry and the analyst's snapshot.
When the trade closes, its outcome (R-multiple) updates the stats for those signals
(source `paper`, counted 3× as much as history because it's live experience). The brain's
weights are recomputed each new trading day, so Kairos leans on what keeps working and
backs away from what doesn't. The change is visible on the "What Kairos learned" card.

Weights: for each signal, a Beta posterior on "the move went the signal's way", started at
the market base rate with 20 pseudo-trades of weight, updated by history and paper
results; the weight is the posterior mean edge over the base rate, shrunk toward zero when
evidence is thin.

### 8.3 Lessons (memory)
After each closed desk trade and at the end of each desk day, Kairos writes a short
lesson ("Breakouts on low volume failed 4 of 5 times this week"). It's a rule-based
summary plus, if Ollama is ready, the model's reflection. Lessons are stored in
`kairos_memory` with tags (symbol, signal, market) and the most relevant few go into the
prompt (§7.1). The model's reflection goes in the diary only, never into lessons (D-64).

## 9. The Kairos desk (autonomous paper trading)

"Keep an eye on these stocks and trade when you think it'll make money" starts a **desk**:
a normal paper session (D-06: manual start/stop, nothing runs when Agora is closed) whose
strategy is the Kairos brain over the user's watchlist, with its own paper account.

The brain (`kind: "kairos"` strategy definition):
- Score each candle −100…+100 from learned-weight signals (trend, patterns, levels,
  momentum, volume, divergences, candles; news live only).
- Enter long when score ≥ the entry threshold (default 40) and the trend isn't strongly
  against; short when ≤ −threshold where shorting is allowed (US, India intraday).
- Stop at the pattern's invalidation level or 2×ATR (whichever is tighter but at least
  1×ATR away); target at the measured move or 2.5R; optional ATR trailing stop.
- Size by risk: 1% of equity per trade (setting), at most 5 open positions, pause new
  entries after a 3% daily loss.
- Exit early when the score flips strongly against the position or after the time limit.
- Live only, the **news guard** (§14, D-69, D-211) may halve an entry, nudge the score up
  where the news helps a sector or down where it hurts, close a losing long once prices confirm,
  or block and close a long on red-flag company news.

Because the brain is an ordinary strategy definition, the user can **backtest Kairos
itself** like any strategy ("how would Kairos have traded the last 5 years?").

Each desk trade gets a **thesis** (signals, levels, score, plan) and, after closing, a
**review**. Both are visible in the desk screen's journal. Any paper session running a
`kairos` strategy counts as a desk (D-64); the desk screen is `/paper/desk` (start, list, what
Kairos learned) and `/paper/desk/{id}` (the session with its diary).

Built as (Phase 9.10): `backend/analysis/signals.py` (causal signals, D-63),
`backend/kairos/brain.py` (score, entries, stops/targets, exits), `backend/kairos/desk.py`
(launch, diary, the paper runner's hook), `backend/kairos/learning.py` (training, stats,
weights), `backend/kairos/memory.py` (lessons), `backend/kairos/forecasts.py` (live forecast
scoring), `backend/kairos/research.py` (§7.3, D-65).

## 10. Screens

- **Kairos panel** (every screen): a right-hand drawer opened from the top bar or Ctrl/Cmd+J.
  Conversation list, streaming replies, step cards ("Backtesting MA crossover on 5 stocks…
  done: +31%, Sharpe 1.2"), result cards with buttons, suggested prompts, a stop button.
- **Charts → Kairos toggle**: when on, the chart draws S/R zones, trendlines, pattern
  outlines with labels, candlestick markers, Fibonacci levels (optional) and the forecast
  cone into the future; a side panel shows the verdict, score gauge, findings (each with
  its historical hit rate), key levels, trade idea, forecast track record and news. It
  re-analyses when the symbol or timeframe changes.
- **Kairos desk** screen (under Paper trading): watchlist, positions, journal (theses and
  reviews), "What Kairos learned", start/stop.
- **Settings → Kairos**: on/off, think before answering, follow around the app, risk per
  trade, desk limits, news on/off, retrain now.

## 11. API (added to API_CONTRACT)

- `GET /api/analysis/chart?market&symbol&timeframe[&bars]` → report + drawings + forecast
- `GET /api/analysis/forecast?...` → forecast + track record
- `GET /api/news?market[&instrument_id][&hours]`, `POST /api/news/refresh`
- `GET /api/news/live?region&group&topic&q&min_severity` (the News screen), `GET /api/news/risk?market`
- `POST /api/kairos/chat` (SSE) → events `step`, `text`, `card`, `ui`, `done`, `error`
- `GET /api/kairos/threads`, `GET /api/kairos/threads/{id}`, `DELETE …`
- `POST /api/kairos/train` (job), `GET /api/kairos/stats`, `GET /api/kairos/lessons`
- `POST /api/kairos/desk` (job), `GET /api/kairos/desk`, `GET /api/kairos/desk/{id}`,
  `POST /api/kairos/desk/{id}/stop` (shapes in `API_CONTRACT.md`)
- Phase 11: `GET|POST /api/kairos/review/{backtest|paper}/{id}`, `GET /api/kairos/trade-check/{strategy_id}`,
  `POST /api/kairos/improve/{strategy_id}` (job), `GET /api/kairos/improvements`,
  `GET /api/kairos/learner`, `POST /api/kairos/learner/round` (job)

## 12. Data model (migration 0003)

`news_items`, `news_links` (item ↔ instrument), `kairos_threads`, `kairos_messages`,
`kairos_signal_stats`, `kairos_journal`, `kairos_memory`, `kairos_forecasts`. Migration 0005
(Phase 10) adds `topics`, `severity`, `impact` and `scope` to `news_items`. Migration 0006
(Phase 11) adds `kairos_trade_samples`, `kairos_reviews` and, on `kairos_forecasts`, `p25`,
`p75`, `detail` (predicted candles, each model's range) and `review` (the candle-by-candle check).

## 13. Testing

- Golden tests: swings, levels, every chart pattern and candlestick on hand-built series;
  new indicators against hand calculations.
- Causality tests: signals and snapshots recomputed on truncated histories never change
  the past.
- Forecast: deterministic on fixtures; the track-record calculator on a hand-built series.
- Agent: `FakeAIProvider` scripted tool calls (valid, invalid-then-fixed, JSON-in-text,
  too many rounds); every tool against the practice data; the fallback router.
- Brain: compiles, backtests on fixtures, identical in replay and backtest (D-49).
- Learning: posterior updates by hand.
- Playwright: open chart → toggle Kairos → drawings and panel appear; ask Kairos (fake) to
  backtest → results open.


## 14. World news, the news risk gauge and the news guard (Phase 10, D-68, D-69)

**Sources.** Besides the market and company feeds (§6), world feeds: BBC World and Business, Al
Jazeera, Guardian World and Business, NYT World and Business, WSJ World, Google News World,
OilPrice, the Federal Reserve's and the RBI's press releases, BBC India, Mint and ET economy,
CNBC-TV18 markets, and GDELT's free DOC 2.0 API (three keyless searches: world geopolitics,
world economy, India; one request every 6 s). Read only while Agora is open and the News screen
or Kairos is in use (RSS every 4 minutes, GDELT every 15), six RSS feeds at a time.

**Reading a headline** (`backend/news/topics.py`): topics (war & conflict, terrorism,
sanctions, trade & tariffs, politics & elections, central banks, inflation, growth & jobs, oil
& energy, banking stress, government debt, currencies, health, disasters, cyber, market stress,
regulation, budget & tax, company news), severity 0–5 (raised by escalation words, 5 for
invasions, pandemics, bank collapses and circuit breakers), impact −1…+1 (risk-off/on: the
topic's usual direction blended with word tone; calming news such as a ceasefire flips it),
scope (IN, US, WORLD) and the sectors it usually helps or hurts.

**The gauge** (`backend/news/risk.py`): 0–100 per market and for the world, from the last 36
hours: stories weighted by severity, risk-off reading, recency (half-life 6 h), relevance
(own market 1, world 0.8, other market 0.4), corroboration (+0.5 per extra publisher, up to
3×) and whether a geopolitical story touches markets at all; the heaviest story counts fully,
each next 0.6× as much; calming stories subtract. Calm < 25 ≤ watchful < 50 ≤ elevated < 75 ≤
severe. A stock's own news gives an alert: critical (a red-flag headline), negative, positive
or quiet.

**The news guard** (`backend/kairos/news_guard.py`): see D-69 and D-211. News is caution,
never a stop (the user, 2026-11-06). Each story's topic says which sectors it usually helps or
hurts; each stock's profile says which sectors it is in (`backend/news/exposure.py`). Protective
(default): where the news helps a stock's sector the score gets +10 and market risk doesn't halve
the trade; where it hurts, half size and a long 1%+ down is cut; at elevated or severe market risk
new trades are half size, losing longs are cut once the watchlist falls 0.5% on the candle and,
at 75+, any long once it falls 1%; calming news adds 5; red-flag company news closes that
stock's long and is the only "no new trade"; negative company news halves the trade; a positive
catalyst adds 10. Queued buys are cancelled at the open only when severe news meets a market
down 1%+ that day, except in sectors the news helps. Cautious changes sizes and scores but never
closes a trade; off ignores the news. Live desks only; never backtests or replays. Each action is a
"News guard: …" note in the desk diary.

**Screens.** **News** (sidebar): three gauges with what the desk does now, live headlines with
severity bars, topic, scope, risk-on/off and sectors, filters (region, topic group, market-moving
only, search), the guard card with the stories driving the risk, and the sources. **Home** has a
news-risk card. **Settings → Kairos** has the News guard switch.

## 15. The world's toolkit (Phase 10, D-67)

- **Indicators (93):** the Phase 3 and 9 sets plus SMMA, ZLEMA, ALMA, T3, McGinley, linear
  regression (value, slope, R²), VIDYA, TRIMA, envelope, Alligator, Heikin-Ashi, momentum, CMO,
  TRIX, PPO, DPO, KST, Coppock, Ultimate, Awesome/Accelerator, TSI, RVI, Fisher, Schaff, Connors
  RSI, Elder ray, BOP, Qstick, SMI, WaveTrend, Elder impulse, Vortex, ADXR, Choppiness,
  fractals, standard deviation, NATR, historical volatility, Ulcer, Mass index, Chandelier exit,
  squeeze, z-score, Bollinger %B/bandwidth, disparity, RVOL, PVO, A/D line, Chaikin oscillator,
  Force index, EOM, Klinger, NVI, PVI, PVT, Fibonacci/Camarilla/Woodie pivots. Grouped in the
  builder (moving averages, momentum, trend, volatility & bands, volume, levels).
- **Candlesticks (93):** all 61 TA-Lib functions (kicking-by-length folded into kicking) plus
  windows, above/below the stomach, two black gapping, matching high, tweezers, inside/outside.
- **Chart patterns (41)** and **setups (19):** §3.
- **Templates (28):** the eight starters plus Turtle, golden cross, Connors RSI(2), Elder's
  triple screen, TTM squeeze, Ichimoku, Parabolic SAR, Keltner, ADX/DI, Williams %R, CCI, MFI,
  Heikin-Ashi, VWAP reclaim (intraday), Aroon, Coppock, Vortex, 4-9-18 EMAs, Fisher, Schaff.
- **Knowledge pack (205 sections, D-70):** every one of the above, the schools of analysis
  (Dow, Elliott, Wyckoff, VSA, SMC, market profile, Japanese charting, Gann, DeMark,
  intermarket, breadth, sentiment, seasonality), the famous strategies (CANSLIM, Minervini,
  Weinstein, Darvas, Livermore, momentum and factor investing, pairs trading, event trading,
  Kelly sizing), the macro and geopolitics playbook with real historical reactions, damage
  control, and circuit breakers and calendars for India and the US.


## 16. The trade check and trade reviews (Phase 11, D-71, D-72)

**The trade check** (`backend/kairos/quality.py`) sits in the shared engine between a strategy's
entry signal and the order, so it behaves the same in backtests and paper trading. It reads ten
readings on the signal candle (trend strength, choppiness, RSI, volatility, relative volume,
stretch from the 20-candle average, distance from the 50- and 200-candle averages, place in the
recent range, Kairos's score; directional ones turned round for shorts), estimates the chance
the trade makes money **after costs** from the strategy's own past results, and either takes it
or rejects the order with a plain reason ("…its chance looked 31% against 48% for this
strategy's usual trade, because the market is choppy (CHOP 63; trades like that won 29% of
21)"). Modes: off · learn · balanced · strict. It learns from every closed trade and follows
skipped signals to learn from them too, and it **skips nothing until its judgements have proven
right** (30 judged results, Brier skill > 0.02, measured prequentially). Backtests and paper
sessions choose a mode; Kairos desks use Settings → Kairos → Trade check (balanced).

**Reviews** (`review.py`, `coach.py`): for any backtest or paper session, Kairos explains where
the money went: costs versus gross profit (and per trade), win rate versus the break-even win
rate, dependence on the best three trades, exits, the conditions in which trades failed although
the rules were met, the worst losers with their reasons, and filters chosen on the first 60% of
trades and checked on the last 40%. Shown as **Kairos's review** on Backtest results and paper
sessions, and via the `review_trades` tool ("why did my trades fail?").

**Improve with Kairos** (`improve.py`): adds the filters that held up as ordinary entry
conditions and saves a new version only when the unseen part of the period got better after
costs (D-72). Visual strategies only; old versions are kept. Tool: `improve_strategy`.

## 17. Predicted candles and learning from misses (Phase 11, D-73)

The forecast blends four models: volatility, analogues, trend and the **analyst** (Kairos's own
score turned into a drift by a causal ridge fit; live forecasts lean it by the stock's news and
widen ranges when market news risk is high). Its **predicted candles** follow the typical path
(the sampled path closest to the middle), with the stock's usual wick sizes; the chart draws
them tinted and dashed inside the cone. Every shown forecast is kept with its candles; when the
candles form, Kairos checks each one (direction, inside the 8-in-10 range, how far off the end
was) and the **last prediction is outlined over the real candles** with its score in the panel
("Kairos's prediction from 12 Oct: in range 7/7, direction 4/6, off by +1.2%"). Its misses
widen, narrow or shift later forecasts (calibration), and each model's live losses re-weight the
blend. Before any saved prediction has formed, the panel shows a **re-created** prediction made
with only what was known then.

## 18. Kairos keeps learning while Agora is open (Phase 11, D-73)

`backend/kairos/autolearn.py`: a background thread that wakes every two minutes (D-103) while
Agora is open (never when it's closed) and, when `kairos.keep_learning` is on and no backtest or
research is running, reviews new backtests and paper trades, improves visual strategies whose
reviews found filters that held up (`kairos.auto_improve`), runs **forward checks** (Phase 16,
D-90: versions Kairos and Metis saved, and portfolio sleeves, re-tested on the candles formed since;
undone when they stopped holding up), forecasts a few watchlist stocks and checks older predictions,
and re-studies signal history when data grew. It writes short lessons
(memory) and one `learner` review per round. Settings → Kairos shows **Kairos keeps learning**
with a **Learn now** button; the tool `learning_status` answers "what have you studied?". It never
places an order: everything it learns lands in deterministic rules (D-56). Its creative
counterpart, where the AI model itself proposes ideas and code tests them, is Metis
(`docs/METIS.md`).

## 19. Futures and options (Phase 11, D-74)

Agora doesn't trade F&O, but Kairos knows it: three playbook files (`fno_basics.md`,
`fno_strategies.md`, `fno_markets.md`; 62 sections, facts checked 2026-10-22) and an options
calculator (`backend/analysis/options.py`: Black-Scholes-Merton, binomial American pricing,
implied volatility, 32 strategies with payoff, maximum profit and loss, break-evens, chance of
profit and Greeks). The tool `option_strategy` ("iron condor on Nifty for 7 days") prices the legs
from the underlying's own volatility (estimates, labelled so), uses NSE index lot sizes (Nifty 65)
or 100 for US options, and shows a payoff chart card.


## 20. Several timeframes, sectors, the world desk and the autopilot (Phase 18, D-93 to D-99)

Full detail in `docs/WORLD.md`. For Kairos:
- **Chart reading**: a **Timeframes** section (monthly, weekly and daily for a daily chart; daily,
  hourly and the chart for intraday), each with its trend and momentum, and one verdict ("a bounce
  inside a weekly downtrend"); `analyze_chart` says it too.
- **The brain** has `bigger_chart`: the desk doesn't buy while the bigger chart's trend score is
  −25 or lower (or unknown), nor short while it is +25 or higher (setting `kairos.bigger_chart`).
- **Tools**: `world_events` (what world events mean for a market, a sector or one stock, with the
  chain and what past events did), `why_move` (the move investigator), `sectors` (rotation, booms),
  `watchlists` (list, show, create, add, remove). Watchlist names work wherever stocks do.
  Router phrases: "why did the market fall today?", "what's happening in the world?", "which
  sectors are booming?", "show my watchlists".
- **Knowledge**: `knowledge/geopolitics_world.md` (27 sections: how events travel, chokepoints, who
  exports what, India's and America's weak spots, oil shocks, the Middle East, Russia–Ukraine,
  Taiwan, US–China, India's neighbours, sanctions, central banks, currency crises, elections,
  pandemics, sector maps for both markets, safe havens, "priced in", second-order effects, a
  sudden-fall checklist, moves without news, rotation, sector booms, multiple timeframes).
- **The autopilot** (D-99): Kairos picks its own 20 stocks ("Kairos · Picks India/US") and starts its
  desks when Agora opens; nothing to add.

## 21. The short-term desk (D-118)

Besides its daily desk in each market, the autopilot runs a desk on a shorter timeframe
(`autopilot.intraday_desk`: 15-minute by default; hourly, 5-minute or off in Settings → Kairos), on
Kairos's picks that have that timeframe's history. It studies that timeframe's history before its
first trade, trades only during market hours, and is called "Kairos desk · India · 15-minute".

## 22. Trailing stops (D-119)

Kairos's desks trail every trade `kairos.trail_atr` × ATR behind the best price since entry (default
3; Settings → Kairos → Trailing stop; 0 turns it off). "Improve with Kairos" tries a trailing stop
(2, 3 or 4 ATR, chosen on the first 60% of the trades, kept only if it made more on the last 40%)
when no entry filter helps. Strategies Kairos creates from an idea include one unless the user says
otherwise. The knowledge pack's risk file has "Trailing stops (dynamic stops)".

## 23. Partial exits, active trading and institutions (D-125, D-126)

Kairos's desks sell half of each trade at 1R (`kairos.partial_r`, default 1; Settings → Kairos →
"Sell half at"; 0 turns it off) and then move the stop to the entry price; the rest rides the
trailing stop or the target. A Kairos-brain strategy has "Partial exit (× the risk)" in its rules.
"Improve with Kairos" tries half-at-1R and thirds (1R, 2R) when neither a filter nor a trailing stop
helped, kept only if it made more on the unseen 40% of trades. Three new knowledge files:
`active_trading.md` (partial exits, R multiples, expectancy versus win rate, beating the Nifty,
realistic returns, pullbacks, RSI(2), opening-range breakouts, VWAP, tight-range breakouts, gaps,
what doesn't work), `institutions.md` (FPIs and DIIs, flows, the rupee and US yields, accumulation
footprints, delivery percentage, index rebalancing, bulk and block deals, pledges, open interest and
expiry, quarter-end, stop hunts, US 13F and options expiry, trading alongside institutions) and
`volatility_retail.md` (India VIX regimes, volatility sizing, gaps, event days, circuit limits,
drawdown rules for a full-time trader, bear and sideways markets, volatility clustering).

## 24. The casebook and web research (D-128, D-129)

Kairos's trade review explains each of the worst losing trades even when there are too few trades
for statistics: `kairos/casebook.py` checks it against textbook causes (against the 200- or
50-candle trend, the index moving the other way, a choppy market, thin volume, a chased price, a
stop inside the noise, a gain given back) and lists the causes the losers share more than the
winners, with the fix to test. The `web_research` tool searches DuckDuckGo and Wikipedia, reads up
to three pages and returns the relevant paragraphs with sources (Settings → Kairos → "Research on
the web"). Desks restart with new Settings → Kairos values once they hold no trades.

## 24. Fair shares, every timeframe, every chart, every stock (D-131 to D-133)

Requested by the user on 2026-10-27.
- **Fair shares (D-131).** A desk trade takes at most an equal share of the money (100 ÷ the
  open-trade limit: 10% with the default 10, D-136), so one tight stop can't put the whole account
  in one stock, and a full desk still holds ten different stocks.
- **Desks (D-132, D-177).** Besides the daily desk, the autopilot runs hourly and 15-minute desks
  in each market (Settings → Kairos → Short-term desks: All, one of them, or Off). Each follows the
  250 most traded stocks. Before an entry a live desk takes a closer look at the smaller chart
  (daily → hourly, hourly and 15-minute → 5-minute) and passes if it turned against the trade
  (`kairos/closer.py`; Settings → Kairos → "smaller chart").
- **Every bigger chart (D-132).** Each desk reads all its bigger charts together (a 1-minute desk:
  5-minute, 15-minute and hourly; a daily desk: weekly and monthly) and doesn't trade against them.
- **Every stock (D-133).** The picks rank every stock Agora has fresh prices for that trades enough
  each day; each desk follows the top of that ranking, as many stocks as its candles allow (daily
  30, hourly 20, 15-minute 20, 5-minute 15, 1-minute 10), picked again daily for short desks.

## 25. Every indicator, classic strategy and quant signal (D-138)

Requested by the user on 2026-10-28.
- **Signals.** `backend/analysis/indicator_signals.py` adds 49 signals (both directions): 19
  oscillators, 13 trend indicators, 6 volume indicators, 7 classic strategy entries (2 of them
  intraday only: VWAP, opening range) and 4 quant signals. No look-ahead (tested with the same
  cut-history test as every other signal).
- **Chorus.** `brain.decide` hears them as a bounded vote per part of the score
  (`CHORUS_CAP` 0.6, `CHORUS_MIN` 3); only a classic strategy's entry counts as a fresh trigger.
- **Learning.** Measured and weighted like every signal (§8). The history study is redone when the
  signal list changes (`SIGNALS_VERSION`), on every desk timeframe, and covers Kairos's picks.
- **Faster lessons.** A live desk refreshes its weights on the next candle after any lesson
  (`learning.version`), not the next day.
- **Metis's strategies on trial (D-139).** `kairos/trials.py`: Kairos's own bar (exam 1.2× over
  20+ trades, no loss since saved), at most `kairos.trials` per market (default 3, a ceiling), each
  on its own ₹2 lakh / $20,000 paper account; judged after 20 trades or 30 days (works: 5+
  trades, profit after costs, 1.1×), stopped at a 10% loss, retried after 60 days or a new version.
- **Its own exits (D-140).** `kairos/exits.py`: 54 exit plans (stop × target × trailing × partial)
  played out on the brain's historical entries (study 70% / exam 30%) and on every closed desk
  trade (×3); a plan replaces the settings' only when it is at least as good in the exam years;
  live desks take it with the weights; `kairos.auto_exits` (default on).


## 26. The trade judge and the research sprint (D-143, D-145)

Requested on 2026-11-03 ("I need results in Kairos desk too, don't just focus on Metis").
- **The trade judge** (`kairos/judge.py`): every entry the brain would have made in history
  (the same entries the exit study plays out, D-140) is a lesson: ~25 readings at the signal
  candle (score and its parts, how many signals agreed, a fresh trigger, the trade check's ten
  readings, the stock's trend and volatility regime) and the result in R after costs. Small
  gradient-boosted trees (numpy) learn which *combinations* lose. Time-ordered: study 70%
  (learn on 80% of it, pick how picky to be on the rest), a gap as long as a trade, exam 30%.
- **It switches itself on** only if, on the exam, the entries it keeps earned at least 0.05R
  more each than all entries, by two standard errors, with AUC ≥ 0.53 and 30+ kept trades. On
  synthetic noise it switched on 0 of 30 times; on a real combination edge 10 of 10.
- **Live desks only** ask it before each entry (`brain.judge_says_no`); backtests don't, so a
  backtest of Kairos stays reproducible. Re-learned with every signal study. "What Kairos
  learned" says whether it is on and what it looks at. Setting `kairos.judge` (on).
- **Research sprints** (`backend/lab`, D-143) leave a playbook that Metis re-tests; what Metis
  saves reaches the desks through Kairos's trials (D-139).

### 26a. A warning, never a bench (D-147, D-215)
The trade judge also checks whether the desk's entries on a chart made money at all on unseen
past trades, after costs. If they clearly lost (≥ 0.05R a trade and two standard errors), the
desk's card says so. It changes nothing else: desks always trade at full size, because the user
wants Kairos free to trade, make mistakes and learn from them. (From 2026-11-03 such a desk opened
no trades; on 2026-11-06 it briefly traded at a quarter size, D-214, then this rule replaced both.)

### 26b. Forecasts on the desks (D-175)
Every trading day after the close the autopilot forecasts each daily-desk stock and checks every
due forecast. Once a market's checked forecasts show skill (60+, direction right clearly more
often than a coin), its live daily desk leans on today's forecast for each stock by up to ±10
score points. Until then the desk ignores forecasts.

## The whole story of a trade (Phase 27, 27.11)

`backend/kairos/story.py` tells each closed trade: the plan, what was known at entry, the best and
worst point, what closed it, what happened next, and one of six plain lessons (it worked, gave a gain
back, never worked, a gap past the stop, exited early, an ordinary loss). It is worked out from what
is saved, so it covers every old trade. New closing reviews include it, the paper trades table opens
it, `/api/paper/trades/{id}/story` serves it, and the counts feed Kairos's lessons each study round.

Why Kairos misses moves is measured, not assumed: `backend/diagnosis/opportunities.py` and D-224.
