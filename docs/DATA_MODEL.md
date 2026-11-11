# DATA_MODEL: SQLite schema (v3.0)

File: `data/agora.db` · Engine: SQLite (WAL mode) · ORM: SQLAlchemy 2.x · Migrations: Alembic.

Conventions:
- Primary keys: `id INTEGER PRIMARY KEY` unless noted.
- Timestamps: `*_at` / `ts` = UTC epoch **milliseconds** (INTEGER).
- Money: REAL in the table; `Decimal` in cost/P&L code.
- JSON columns: TEXT containing JSON, validated by Pydantic models.
- Enums: TEXT with CHECK constraints.

## Reference data

**markets**: `code` TEXT PK (`IN`, `US`), `name`, `currency` (`INR`/`USD`),
`timezone`, `calendar_name` (`NSE`/`NYSE`).

**instruments**: `id`, `market_code` FK, `symbol` (Agora symbol, e.g. `RELIANCE`, `AAPL`),
`yahoo_symbol` (`RELIANCE.NS`), `name`, `instrument_type` (`equity`, `etf`, `index`;
`option`/`future` reserved for later), `isin` NULL, `is_active`, `added_at`.
Unique (`market_code`, `symbol`).

**instrument_aliases**: `instrument_id` FK, `alias_symbol`, `valid_from`, `valid_to` NULL.

**universes**: `id`, `market_code`, `name` (`NIFTY50`, `US_WATCHLIST`), `description`.

**universe_members**: `universe_id` FK, `instrument_id` FK, `valid_from` (date as ms),
`valid_to` NULL, `source`. Index (`universe_id`, `valid_from`).

**holiday_overrides**: `market_code`, `date` (YYYY-MM-DD), `kind` (`closed`, `open`,
`early_close`), `close_time` NULL, `note`.

## Market data

**candles**: `instrument_id`, `timeframe` (`1m`,`5m`,`15m`,`1h`,`1d`), `ts` (bar open,
UTC ms), `open`, `high`, `low`, `close`, `volume`, `split_factor` (cumulative factor to
convert to today's split-adjusted terms), `source` (`yahoo`,`nse`,`stooq`,`derived`,
`fake`), `fetched_at`. **PK** (`instrument_id`, `timeframe`, `ts`). WITHOUT ROWID.

**corporate_actions**: `id`, `instrument_id`, `ex_date` (ms), `kind` (`split`,
`dividend`), `ratio` NULL (e.g. 2.0 for 2:1), `amount` NULL (cash per share),
`source`. Unique (`instrument_id`, `ex_date`, `kind`).

**data_fetch_log**: `id`, `source`, `instrument_id` NULL, `timeframe` NULL,
`range_start`, `range_end`, `status` (`ok`,`empty`,`rate_limited`,`error`,`fallback`),
`rows`, `message`, `started_at`, `duration_ms`.

**source_status**: `source` PK, `state` (`ok`,`cooling_down`,`down`), `until` NULL,
`last_error` NULL, `updated_at`.

## Costs

**brokerage_profiles**: `id`, `market_code`, `name` (e.g. "Discount broker (₹20 cap)",
"Zero brokerage", "US $0 commission"), `rules` JSON (per product: flat, percent, cap,
min), `is_default`.

**charge_schedules**: `id`, `market_code`, `charge` (`stt`, `exchange_txn`, `sebi_fee`,
`stamp_duty`, `gst`, `dp_charge`, `sec_fee`, `finra_taf`), `product` (`intraday`,
`delivery`, `cash`, `any`), `side` (`buy`,`sell`,`both`), `rate_type` (`percent`,
`per_crore`, `flat_per_order`, `flat_per_scrip_day`, `per_share`, `per_million`),
`rate`, `cap` NULL, `effective_from`, `effective_to` NULL, `source_url`, `verified_at`.
See `COST_MODEL.md`.

**slippage_profiles**: `id`, `market_code`, `name`, `bps`, `is_default`.

## Strategies

**strategies**: `id`, `name`, `description`, `kind` (`visual`, `code`), `market_code`,
`created_at`, `updated_at`, `archived_at` NULL, `template_key` NULL.

**strategy_versions**: `id`, `strategy_id` FK, `version` (int, increments), `definition`
JSON (Strategy Definition, or `{code, parameters}` for code strategies), `schema_version`,
`content_hash` (sha256 of canonical JSON), `created_at`, `note`, `created_by` (`user`,
`ai_draft`). Unique (`strategy_id`, `version`).

## Backtests

**backtest_runs**: `id`, `strategy_version_id` FK, `status` (`queued`,`running`,
`done`,`failed`,`cancelled`), `params` JSON (symbols, timeframe, date range, capital,
brokerage_profile_id, slippage_bps, sizing overrides, mode: `single`,`oos`,`sweep`,
`walk_forward`), `repro` JSON (data ranges + sources used, charge schedule ids, engine
version, yfinance version), `metrics` JSON, `summary_text`, `warnings` JSON (honesty
panel), `progress` REAL, `error_plain` NULL, `error_detail` NULL, `created_at`,
`started_at`, `finished_at`, `parent_run_id` NULL (sweep/walk-forward children),
`name` NULL, `starred` INTEGER DEFAULT 0.

**backtest_trades**: `id`, `run_id` FK, `instrument_id`, `side` (`long`,`short`),
`qty`, `entry_ts`, `entry_price`, `exit_ts`, `exit_price`, `gross_pnl`, `charges`,
`net_pnl`, `return_pct`, `bars_held`, `entry_reason`, `exit_reason`
(`signal`,`stop`,`target`,`trailing`,`time`,`square_off`,`end_of_test`).

**backtest_equity**: `run_id`, `ts`, `equity`, `cash`, `exposure`, `drawdown`.
PK (`run_id`, `ts`). Daily points for daily strategies; per-bar for intraday, downsampled
to ≤ 5,000 points for charts.

**backtest_orders** (debug detail, pruned for old runs): `run_id`, `ts`, `instrument_id`,
`type`, `side`, `qty`, `status`, `reason`.

## Paper trading

**paper_accounts**: `id`, `name`, `market_code`, `starting_capital`, `brokerage_profile_id`,
`slippage_bps`, `created_at`, `archived_at` NULL.

**paper_sessions**: `id`, `account_id` FK, `strategy_version_id` FK, `state`
(`running`,`paused_data`,`paused_user`,`stopped`), `started_at`, `stopped_at` NULL,
`last_bar_ts` NULL, `notes` JSON (gaps, pauses).

**paper_orders**: `id`, `session_id`, `instrument_id`, `created_ts`, `type` (`market`,
`limit`,`stop`,`stop_limit`), `side`, `qty`, `limit_price` NULL, `stop_price` NULL,
`status` (`open`,`filled`,`cancelled`,`rejected`), `reason`.

**paper_fills**: `id`, `order_id` FK, `ts`, `price`, `qty`, `charges`, `slippage`.

**paper_positions**: `session_id`, `instrument_id`, `qty` (negative = short),
`avg_price`, `opened_ts`, `realized_pnl`. PK (`session_id`, `instrument_id`).

**paper_trades** (added in migration 0002, D-46): closed paper trades, same columns as
`backtest_trades` with `session_id` instead of `run_id`.

**paper_equity**: `session_id`, `ts`, `equity`, `cash`, `unrealized_pnl`. PK (`session_id`, `ts`).

**paper_events**: `id`, `session_id`, `ts`, `level` (`info`,`warn`,`error`), `kind`,
`message_plain`, `detail` JSON.

## AI

**ai_conversations**: `id`, `context_kind` (`backtest`,`trade`,`strategy_draft`,
`paper_day`,`general`), `context_id` NULL, `model`, `created_at`.

**ai_messages**: `id`, `conversation_id` FK, `role` (`user`,`assistant`,`system`),
`content`, `created_at`, `tokens` NULL, `latency_ms` NULL.

## Kairos (Phase 9, migration 0003; docs/KAIROS.md §12)

| Table | Holds |
|---|---|
| `news_items` | Headlines from public feeds and GDELT: `uid` (de-duplication), source, market (NULL for world feeds), title, summary, link, publisher, `published_at`, `fetched_at`, sentiment (−1 … +1); since migration 0005 (D-68) `topics` (comma list, main topic first), `severity` (0–5), `impact` (−1 risk-off … +1 risk-on) and `scope` (IN / US / WORLD), NULL on older rows until first read. World headlines are kept 7 days, others 30 |
| `news_links` | Which instruments each headline mentions (`news_id`, `instrument_id`) |
| `kairos_threads` | Conversations with Kairos (title, model, created/updated) |
| `kairos_messages` | Turns: `role` user / assistant / step (a tool Kairos ran), content, `payload` JSON (tool, arguments, cards, navigation) |
| `kairos_signal_stats` | Per market, timeframe, signal, source (`history` / `paper`) and horizon: count, wins, return sums and the base rate (D-61) |
| `kairos_journal` | The desk's diary: thesis / review / note / day entries per paper session and trade |
| `kairos_memory` | Lessons, preferences and facts with tags; the most relevant go into Kairos's prompt |
| `kairos_forecasts` | Forecasts shown (origin, p10/p50/p90, chance up) and how they turned out once the horizon passed |

Migration 0004 widens two checks for the Kairos brain (D-60, D-66): `strategies.kind` allows
`kairos`, and `strategy_versions.created_by` allows `kairos` (strategies Kairos saves itself:
desk versions, research winners). A Kairos definition keeps its signal weights inside the
version's JSON, so a backtest of it is reproducible.

## Kairos learning (Phase 11, migration 0006; docs/KAIROS.md §16–18)
| Table | What it holds |
|---|---|
| `kairos_trade_samples` | Every trade (and followed skipped signal, `origin = shadow`) with the market's readings on its signal candle (`features` JSON), its result after costs (`ret_pct`, `win`) and weight; one row per strategy, source (backtest / paper), symbol, signal candle, side and origin. `known_ts` (when the result was known) and `created_at` keep seeds causal (D-71) |
| `kairos_reviews` | Kairos's reviews: `kind` backtest · paper · improvement · learner, `ref_id`, `strategy_id`, `trades_seen`, `headline`, `payload` JSON |

`kairos_forecasts` gains `p25`, `p75`, `detail` (JSON: the predicted candles, the range at each
step, each model's horizon quantiles, the raw middle and half-range) and `review` (JSON: the
candle-by-candle comparison, the miss in half-range units, each model's loss), D-73.

## Metis (Phase 12, migration 0007; docs/METIS.md)
| Table | What it holds |
|---|---|
| `metis_rounds` | One round of research: `started_at`, `finished_at`, `status` running · done · failed · skipped, `trigger` auto · user, `focus`, `model`, `noticed` (the model's summary), `thinking` (the model's thinking, last 8,000 characters), `note` (code's plain-English outcome), `ideas`, `kept`, `brief` (exactly what Metis was shown) |
| `metis_ideas` | The notebook: `round_id`, `kind` filter · tweak · new_strategy · simplify · universe (0008), `title`, `why` (the model's reasoning), `market_code`, `strategy_id`, `strategy_version_id`, `spec` (JSON: the idea as rules plus the tested definition), `fingerprint` (repeats are skipped), `status` held_up · rejected · untestable · saved, `verdict` (code's), `result` (JSON: study and exam numbers for the current version and the idea, the checks), `saved_strategy_id`, `saved_version_id`, `run_id`, `origin` ai · playbook (0008: who thought of it, METIS §14) |

## Revisions (Phase 13, migration 0008; docs/REVISIONS.md)

`strategy_versions` gained: `parent_version_id` (the revision it came from), `changes` (JSON:
plain-English lines worked out by `strategy/diff.py`), `evidence` (JSON: the test behind it),
`source` (e.g. `metis-idea:12`, `kairos-improve:5`, `restore:3`); `created_by` accepts `metis`.
`metis_rounds` gained `direction` (improve_live · improve · discover · opportunities, D-83).

## Opportunities and portfolios (Phase 15, migration 0009; docs/PORTFOLIO.md)

| Table | Purpose and key columns |
|---|---|
| `opportunities` | A strategy revision on stocks that held up on unseen years: `market_code`, `strategy_id`, `version_id`, `symbols` (JSON), `overrides` (JSON: tuned settings), `source` scanner · metis · kairos_research · user, `status` open · in_portfolio · dismissed · stale, `score` (exam Sharpe × luck-check probability), `study`, `exam`, `luck` (JSON), `evidence` (plain words), `fingerprint` (version + stocks + settings), `found_at`, `checked_at` |
| `portfolios` | `name`, `market_code`, `budget`, `risk` careful · balanced · bold, `status` draft · paper · stopped · archived, `manage` (manage on its own), `plan` (JSON: the allocator's plan with reasons), `backtest` (JSON: the latest portfolio backtest), `cash` (the reserve while paper trading), `paper_started_at`, `last_rebalance_at`, `last_review_at` |
| `portfolio_sleeves` | `portfolio_id`, `strategy_id`, `version_id`, `opportunity_id`, `symbols`, `overrides`, `size_pct` (% of the sleeve's money per trade), `weight`, `capital`, `status` planned · active · winding_down · retired, `session_id` (its paper session), `worst_drop_pct` (backtest's, for the kill switch), `reasons` (JSON), `added_at`, `retired_at` |
| `portfolio_moves` | The diary: `portfolio_id`, `ts`, `kind` plan · rebalance · add · retire · transfer · start · stop · note, `text` (plain words), `detail` (JSON) |

## Checks, rankings and portfolio methods (Phase 16, migration 0010; docs/LANDSCAPE.md §4)

| Table | Purpose and key columns |
|---|---|
| `strategy_checks` | One check of a strategy revision: `kind` lookahead · forward, `created_at`, `strategy_id`, `version_id`, `baseline_version_id` (the version a revision is compared with), `sleeve_id` and `portfolio_id` (a sleeve's forward check), `verdict` clean · lookahead · history · no_data · waiting · holding · slipping · failed, `title`, `result` (JSON, API_CONTRACT → Checks), `action` (what was done about it, e.g. "Version 4's rules were put back on its own as version 6.") |

`strategies.kind` accepts `ranking` (D-91: a definition with `ranking: {rank_by: momentum ·
low_volatility, lookback_months, skip_months, hold, trend_filter}`, daily candles, sizing and limits
derived from `hold`). `portfolios` gained `method` mix · momentum · low_volatility (default mix).
Only the latest `waiting` forward check of a subject is kept. Metis ideas' `result` JSON keeps
`daily` and `base_daily` (each try's daily returns, for the overfitting check; not sent to screens)
and `overfit`; a backtest's `metrics` JSON keeps `tear_sheet` and, for sweeps, `sweep.pbo`.

## Watchlists, sectors and the world (Phase 18, migration 0011; docs/WORLD.md)

| Table | Purpose and key columns |
|---|---|
| `instrument_profiles` | One per profiled stock (D-93): `instrument_id` PK, `sector` (GICS), `industry`, `size` large · mid · small · micro · '', `lists` (";"-joined index keys: nifty50, nifty500, bank, momentum30, sp500, ndx, dow, …), `tags` (";"-joined exposure tags), `as_of` |
| `watchlists` | `id`, `market_code`, `name` (unique per market), `kind` custom · ready · kairos · metis, `category` custom · index · sector · size · factor · theme · etf · ai, `key` (ready-made), `description`, `reason` (why Kairos or Metis made it), `rule` JSON (how a ready-made list is built: list, sector, size, tag, within, symbols, or factor + top), `created_at`, `updated_at`, `archived_at` |
| `watchlist_items` | `watchlist_id`, `instrument_id` (unique pair), `note`, `rank`, `added_at` |
| `world_events` | A world event in the news (D-95): `scenario`, `title`, `first_seen`, `last_seen`, `strength`, `status` active · fading · measured, `headlines` JSON, `reactions` JSON (`sign`, `sign_now`, `measured: {market: {target: {h: %}}}`) |
| `world_effects` | What a kind of event did (D-95): `scenario`, `market_code`, `target` (market, a sector or `tag:x`), `horizon` 1 · 5 · 20, `source` history · live (unique together), `n`, `mean` (%, escalating direction; the market's return, others in excess of it), `m2`, `hits`, `updated_at` |
| `move_investigations` | A sudden move and its likely cause (D-96): `market_code`, `target`, `timeframe`, `start_ts`, `end_ts`, `move_pct`, `zscore`, `created_at`, `verdict` news · world · contagion · unclear, `text`, `detail` JSON (`causes`, `confidence`, `headlines_read`) |

Private rows in `settings`: `_seed.watchlists` (the seed fingerprint) and `_autopilot.state` (what
the autopilot fetched today and the desks it started); `read_all` ignores them.

## The lab (Phase 25, migration 0013; D-143)

| Table | Purpose and key columns |
|---|---|
| `lab_tests` | One research-sprint test: `sprint`, `family`, `variant` JSON (settings), `market_code`, `timeframe`, `def_hash`, `definition` JSON, `symbols` JSON, `start_ms`, `split_ms`, `vault_ms`, `end_ms`, `study` / `exam` JSON (trades, net, win rate, profit factor, Sharpe, drawdown, stocks up; the exam also keeps daily `returns`), `regimes` JSON (per regime: trades, win rate, average return), `vault` JSON once opened, `vault_opened_at`, `status` tested · finalist · promoted · failed_vault · dropped, `note`, `created_at` |

Migration 0012 resets a stored `ai.num_ctx` under 16,384 to 0 (Automatic, D-141). The trade
judge (D-145) is a file, `data/kairos/judge_<market>_<tf>.json`, not a table.

## App

**settings**: `key` TEXT PK, `value` JSON, `updated_at`. Keys include `theme`,
`ai.enabled`, `ai.model`, `ai.base_url`, `default_capital.IN`, `default_capital.US`,
`intraday_square_off_time`, `volume_cap_pct`, `onboarding_done`, and for Kairos
`kairos.enabled`, `kairos.think`, `kairos.follow`, `news.enabled`, `kairos.news_guard`
(protective · cautious · off, D-69), `kairos.risk_pct`,
`kairos.max_positions`, `kairos.daily_loss_pct`, `kairos.entry_score`, and (Phase 11)
`kairos.trade_check` (balanced · strict · learn · off), `kairos.keep_learning`,
`kairos.auto_improve`, and (Phase 16) `revisions.auto_undo` (D-90), and (Phase 18) `autopilot`
(D-99, on) and `kairos.bigger_chart` (D-97, on); `metis.enabled` is on by default since Phase 18.

**app_events**: `id`, `ts`, `level`, `area`, `message_plain`, `detail` JSON (mirrors
important log lines for the in-app Diagnostics view).

## Retention
- Candles: forever.
- Backtest runs: forever; `backtest_orders` pruned after 90 days unless the run is starred.
- `data_fetch_log`, `app_events`: 90 days.

## Files beside the database (Phase 27)

- `data/actions.db`: the action log, separate on purpose (D-220). Table `actions`.
- `data/heartbeat.json`, `data/logs/outages.jsonl`: the heartbeat and every stop nobody saw (D-218).
- `data/backups/split-repair-undo.csv`: every candle changed by D-228.
- A strategy definition can be `kind: "combined"` (D-227); it is plain JSON in `strategy_versions`, no migration.
