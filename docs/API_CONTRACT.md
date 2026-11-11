# API_CONTRACT: backend ↔ frontend (v3.0)

Base: `http://localhost:8765/api` · JSON · No auth (localhost only; bind to 127.0.0.1).

## Conventions
- Times in responses: UTC epoch ms plus, where shown to users, a pre-formatted local
  string field (`*_display`).
- Long jobs return `202` with a job id; progress arrives via WebSocket and `GET` polling.
- Pagination: `?limit=&cursor=`; responses include `next_cursor`.
- **Error envelope** (every non-2xx):
  ```json
  {"error": {"code": "DATA_SOURCE_RATE_LIMITED",
             "message": "Yahoo Finance is limiting requests right now. Agora will retry in 15 minutes and is using saved data meanwhile.",
             "action": "No action needed.",
             "detail": "YFRateLimitError: Too Many Requests ..."}}
  ```
  `message` and `action` are plain English (see `GLOSSARY.md`); `detail` is technical and
  shown only in a collapsible section.

## System
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | App version, DB ok, data source states, Ollama state |
| GET/PUT | `/settings` | Read/update settings |
| GET | `/markets/status` | Open/closed, next open/close, countdown, per market |
| GET | `/diagnostics` | Versions, paths, recent app events |
| POST | `/diagnostics/live-test` | Run live data checks (Yahoo, NSE, Stooq, Ollama) → `202 {job_id}`; the job result is `{results: [{name, label, outcome, detail}], summary}` |
| POST | `/diagnostics/support-bundle` | Create a zip of logs + settings; returns a path |
| POST | `/diagnostics/open-folder` | `{which: logs|support|data}` → shows the folder in Explorer/Finder |
| GET | `/indicators/{key}/values` | `?instrument_id=&timeframe=&start=&params={json}` → `{key, label, params, outputs: {name: [{ts, value}]}}` (Charts overlays) |

### Shapes (implemented)
- `GET /health` → `{app: "agora", status: "ok"|"degraded", version, db_ok, data_sources:
  [{source, state, until}], ai: {state, models?}, server_time}`. `ai.state` is
  `not_checked` until the Ollama provider exists (Phase 7), else an `AIStatus.state`.
  The launcher identifies a running Agora by `app == "agora"`.
- `GET /settings` → `{values: {key: value}, meta: {key: {default, description}}}`.
- `PUT /settings` body `{key: value, ...}` (partial) → same shape as GET. All-or-nothing:
  any invalid key or value returns `422 INVALID_SETTING` with the problems in `detail`.
- `GET /markets/status` → `{markets: [{market: "IN"|"US", name, is_open, next_change (UTC ms),
  next_change_display ("Closes 15:30 IST", "Opens Mon 09:30 ET"), seconds_to_change,
  approximate}], server_time}`. Uses the real exchange calendars (holidays, early closes) plus
  `holiday_overrides`; `approximate` is false.
- Unknown `/api/...` paths return `404 NOT_FOUND`; malformed input `422 INVALID_INPUT`;
  unexpected failures `500 INTERNAL_ERROR`, all in the error envelope. Every non-API path
  serves the built frontend (`index.html` fallback for client-side routes).

## Instruments and data
| Method | Path | Purpose |
|---|---|---|
| GET | `/instruments?market=&q=` | Search instruments |
| POST | `/instruments` | Add a US ticker (validates via data source) |
| GET | `/universes` / `/universes/{id}/members?as_of=` | Universe membership |
| POST | `/universes/{id}/import-history` | Import historical membership CSV |
| GET | `/data/coverage?market=&timeframe=` | Coverage grid: first/last bar, gaps, source |
| POST | `/data/refresh` | Body `{symbols?, market?, timeframes, range?}` → job id |
| GET | `/candles?instrument_id=&timeframe=&start=&end=&adjusted=true` | Bars for charts |
| GET | `/data/sources` | Source states and recent fetch log |
| DELETE | `/instruments/{id}` | Remove one of your US tickers (saved prices are kept; SPY can't be removed) |
| GET | `/jobs?kind=a,b&active=true&key=` · `/jobs/{id}` | Long-job progress `{job_id, kind, title, key, created_at, status, pct, eta_s, message, result, error}`; newest first; `active` keeps queued/running jobs (D-107) |
| POST | `/jobs/{id}/cancel` | Ask a job to stop |

### Shapes (implemented, Phase 2)
- `GET /instruments` → `{instruments: [{id, market, symbol, yahoo_symbol, name, type}]}`.
- `POST /instruments` `{symbol}` (US only) → `201 {instrument, job_id}` after checking a source
  has prices for it (`404 TICKER_NOT_FOUND` otherwise); the job downloads its daily history.
- `GET /data/coverage?market=&timeframe=` → `{timeframe, rows: [{instrument_id, symbol, name,
  market, type, first, last, bars, gaps, stale, source, status: ok|gaps|stale|empty, days?}],
  totals, last_update, data_mode: real|fake}` (`days` = stored trading days, intraday only).
- `POST /data/refresh` `{symbols?|instrument_ids?, market?, timeframes, start?, end?, scope?}`
  (`scope`: `lists` = the starter list, default; `saved` = every stock with saved prices, D-107) →
  `202 {job_id}`; job result `{symbols, fetched, failed: [{symbol, timeframe, problem}],
  fallback_used}`.
- `GET /candles?instrument_id=&timeframe=&start=&end=&adjusted=true&fetch=false&limit=5000` →
  `{instrument, timeframe, adjusted, bars: [{ts, open, high, low, close, volume, source}], note}`.
  `fetch=true` first fills gaps from the sources; `note` explains when that failed.
  `full=true` (without `start`): all the history there is: daily from 2000, intraday from
  Yahoo's window or the oldest saved candle, whichever is older (D-92). Charts use it with
  `limit=50000`; the newest bars are kept when there are more.
- `POST /universes/{id}/import-history` `{csv}` with columns `symbol,start_date,end_date` →
  `{rows, instruments_added, problems}`.

## Strategies
| Method | Path | Purpose |
|---|---|---|
| GET | `/strategies` | List (with last backtest sparkline data) |
| POST | `/strategies` | Create (blank, from template, or from AI draft) |
| GET/PATCH/DELETE | `/strategies/{id}` | Read / rename / archive |
| GET | `/strategies/{id}/versions` | Revisions, newest first; each has `author_label`, `parent_version_id`, `changes` (plain-English lines), `evidence`, `source` (Phase 13) |
| POST | `/strategies/{id}/versions` | Save a new version (definition or code); records what changed |
| GET | `/strategies/{id}/diff?to=&from=` | What changed between two versions (`from` defaults to `to`'s parent) → `{from, to, changes}` |
| POST | `/strategies/{id}/versions/{version_id}/restore` | Save an old version again as the newest → `{strategy, version}`; 404 `VERSION_NOT_FOUND` |
| GET | `/strategies/{id}/family` | Other strategies with the same logic → `{same_logic: [{strategy_id, name, similarity, why}]}` |
| POST | `/strategies/validate` | Validate a definition or code → plain-English issues |
| POST | `/strategies/preview` | Signals for one symbol over a short range (preview chart) |
| POST | `/strategies/{id}/to-code` | Convert visual → code (new strategy) |
| POST | `/strategies/{id}/duplicate` | Copy a strategy (latest version) |
| GET | `/templates` | Starter templates |
| GET | `/indicators` | Indicator catalog with parameters and descriptions |
| GET | `/templates/{key}?market=` | One template with its full definition for that market |

### Shapes (implemented, Phase 3)
- `GET /indicators` → `{indicators: [{key, label, description, params: [{name, label, default,
  min, max, type}], outputs: [{key, label}], overlay, uses_source, default_source,
  intraday_only}], price_fields}`.
- `GET /templates` → `{templates: [{key, name, summary, description, idea, timeframe}]}`.
- `POST /strategies/validate` `{definition}` → `{ok, issues: [{path, where, message, hint,
  severity: error|warning}], definition}` (definition normalised with defaults when parseable).

### Shapes (implemented, Phase 4)
- `POST /strategies` `{name, description?, market?, template_key?, definition?, created_by?}` →
  `201 {strategy, version}`; from a template when `template_key` + `market` are given, else the
  definition must validate (`422 INVALID_STRATEGY` with the first problem as the action).
- `GET /strategies?archived=` → `{strategies: [{id, name, description, kind, market, created_at,
  updated_at, archived, template_key, version, version_id, timeframe, last_backtest: {run_id,
  total_return, max_drawdown, trades, created_at, points[≤40]} | null}]}`.
- `POST /strategies/{id}/versions` `{definition, note?, created_by?}` → `201 {strategy, version}`;
  unchanged rules return the existing latest version. `POST /strategies/{id}/duplicate`.
- `POST /strategies/preview` `{definition, instrument_id, days}` → `{ok, issues, bars, signals:
  [{ts, action: buy|short|sell|cover, reason, price}], timeframe}` (adjusted prices).
- `POST /backtests` `{strategy_version_id, symbols?, timeframe?, start?, end?, capital?,
  brokerage_profile_id?, slippage_bps?, mode, overrides?, oos_fraction?, sweep?: {params: [{name,
  values}], metric}, walk_forward?: {train_days, test_days, params, metric}, name?}` →
  `202 {run_id, job_id}`; follow with `GET /jobs/{job_id}` or `GET /backtests/{id}`.
- `GET /backtests/{id}` → brief fields + `{params, metrics, warnings: [{level, code, title, text}],
  summary, error, error_detail, repro, job}`. `metrics` holds the headline and full metrics,
  `monthly_returns`, `per_symbol`, `charges_by_type`, `benchmark`, `benchmark_curve`, and for the
  robustness modes `periods` / `sweep` / `walk_forward`.
- `GET /backtests/{id}/equity` → `{points: [{ts, equity, cash, exposure, drawdown}], benchmark:
  [{ts, value}], capital}`. `GET /backtests/{id}/trades?sort=&order=&symbol=&limit=&cursor=` →
  `{trades, total, next_cursor}`. `GET /backtests/{id}/orders?status=rejected`.
- `POST /backtests/compare` `{run_ids ≤ 4}` → `{series: [{run_id, label, points: [{ts, value
  (start = 100)}]}], metrics: [...]}`.
- `GET /costs/profiles?market=` → `{brokerage: [{id, market, name, rules, is_default}], slippage:
  [{id, market, name, bps, is_default}]}` (Phase 5; feeds the backtest setup screen).

## Backtests
| Method | Path | Purpose |
|---|---|---|
| POST | `/backtests` | Start a run (single, oos, sweep, walk_forward) → `202 {run_id}` |
| GET | `/backtests?strategy_id=` | List runs |
| GET | `/backtests/{id}` | Status, params, metrics, warnings, summary |
| POST | `/backtests/{id}/cancel` | Cancel |
| GET | `/backtests/{id}/equity` | Equity + drawdown + benchmark series |
| GET | `/backtests/{id}/trades` | Trades (paginated, sortable) |
| GET | `/backtests/{id}/trades.csv` | CSV export |
| GET | `/backtests/{id}/children` | Sweep/walk-forward child runs |
| POST | `/backtests/compare` | Body `{run_ids: [...]}` → aligned series + metrics table |
| PATCH | `/backtests/{id}` | Star/unstar, rename |
| GET | `/backtests/{id}/orders` | Order log (default: rejected orders with reasons) |

## Paper trading
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/paper/accounts` | List / create accounts |
| GET | `/paper/sessions` | List sessions with live summary |
| POST | `/paper/sessions` | Start: `{account_id, strategy_version_id, trade_check?: off\|learn\|balanced\|strict}` |
| POST | `/paper/sessions/{id}/stop` / `/pause` / `/resume` | Control |
| GET | `/paper/sessions/{id}` | Detail: positions, equity, orders, fills, events |
| GET | `/paper/sessions/{id}/vs-backtest` | Live vs backtest comparison |

### Shapes (implemented, Phase 6)
- `POST /paper/accounts` `{market, name?, starting_capital?, brokerage_profile_id?, slippage_bps?}`
  → `201 {account}`; defaults come from Settings and the market's default profiles.
- `POST /paper/sessions` `{strategy_version_id, account_id? | account?: {...}}` → `201 {session_id,
  session}`; without an account, a new one is created for the strategy's market.
- `GET /paper/sessions` → `{sessions: [summary], mode: live|replay}`; a summary has `{id, name,
  strategy_id, strategy_version_id, version, market, timeframe, product, symbols, universe, account,
  state, mode, started_at, stopped_at, last_bar_ts, equity, total_return (% from first_capital, the first run's money, D-146), first_capital, moved, day_pnl,
  open_positions, trades, freshness: {level, text, delay_s}, problem, now, gaps}`. Sessions
  hidden by Clear stopped are left out (D-206).
- `POST /paper/sessions/clear-stopped` → `{hidden: n}`: hides every stopped session from the list;
  nothing is deleted and a hidden session still opens by its id (D-206).
- `GET /paper/sessions/{id}` → `{session}`: summary + `positions`, `equity_curve` (a Kairos desk's
  includes the earlier runs it carried its money on from, D-207), `stats` (the whole record over
  every closed trade of those runs, `backend/paper/stats.py`, D-209), `runs`, `fills` (latest
  200), `rejected`, `closed_trades`, `events` (latest 200), `instruments`.
- `POST /paper/sessions/{id}/stop|pause|resume` → `{session}`; `409 SESSION_STOPPED` once stopped.
- `GET /paper/sessions/{id}/vs-backtest` → `{ready: false, message}` until 5 trading days, then
  `{ready, days, live, backtest, matched_trades, only_backtest, only_live, series, reasons}`.
- `GET /paper/sessions/{id}/candles?instrument_id=&limit=` → adjusted candles up to the session's
  own "now" (a replay never shows the future) with fills as `markers`.
- `/ws` sends `{type: "hello"}` on connect; `paper.tick` data is `{session_id, state, equity,
  cash, day_pnl, positions, freshness_s, freshness, problem, now}`.

## AI helper
| Method | Path | Purpose |
|---|---|---|
| GET | `/ai/status` | Installed? running? models present? GPU info if available |
| POST | `/ai/pull` | Download the selected model → job id with progress |
| POST | `/ai/explain` | `{kind: backtest|trade|metric|paper_day, id?, question?}` → streamed text |
| POST | `/ai/draft-strategy` | `{idea, market}` → validated Strategy Definition + explanation |
| GET | `/ai/conversations/{id}` | History |

Streaming endpoints use Server-Sent Events (`text/event-stream`).

### Shapes (implemented, Phase 7)
- `GET /ai/status?fresh=` → `{enabled, state: ready|model_missing|not_running|not_installed|disabled|error,
  version, model, num_ctx, auto_ctx, models: [{name, size_gb}], recommended: [{name, label, note}], warning, runs_on}`.
  `num_ctx` is the reading size in use; `auto_ctx` is true on Automatic (`ai.num_ctx` 0, D-141). `runs_on` (D-100) is null until Ollama has
  the chosen model loaded, else `{where: gpu|partly|cpu, gpu_percent, text, fix?}` from `/api/ps`.
- `POST /ai/pull` `{model?}` → `202 {job_id}`; progress via `/jobs/{id}` and `job.progress`.
- `POST /ai/explain` `{kind, id?, question?}` → SSE events `{type: "start", conversation_id}`,
  `{type: "text", text}`…, then `{type: "done", unverified: [numbers], note}` or
  `{type: "error", message, action}`. Not ready → `409 AI_UNAVAILABLE` (plain English) before
  streaming. `kind=trade` takes a backtest trade id; `metric` needs `question` (and optionally a
  backtest `id` for the user's own values).
- `POST /ai/draft-strategy` `{idea, market}` → `{ok, definition, explanation, unsupported, issues,
  attempts, conversation_id, note}`; nothing is saved (the builder saves with
  `created_by: "ai_draft"`).
- `GET /ai/conversations/{id}` → `{id, kind, context_id, model, created_at, messages}`.

## Kairos (Phase 9, docs/KAIROS.md §11)
| Method | Path | Purpose |
|---|---|---|
| GET | `/analysis/chart?instrument_id&timeframe&start?&forecast?` | Kairos's reading of a chart (report, drawings, forecast) |
| GET | `/analysis/forecast?instrument_id&timeframe&horizon?` | Forecast range + track records |
| GET | `/news?market?&instrument_id?&hours?&limit?` | Latest headlines with tone, matched to stocks (a market's news includes world news of severity 3+) |
| GET | `/news/live?region&group?&topic?&q?&min_severity?&hours?&limit?` | The News screen: every feed kept fresh, filtered headlines, three risk gauges (Phase 10) |
| GET | `/news/risk?market=IN\|US\|WORLD` | The news risk gauge (Phase 10, D-68) |
| POST | `/news/refresh` | `{market?, instrument_id?, world?}`: fetch the feeds now |
| GET | `/kairos/status` | Mode (`ai` · `practice` · `basic`), AI state, suggested prompts, footer |
| POST | `/kairos/chat` | `{message, thread_id?, page}` → SSE steps and words |
| GET/DELETE | `/kairos/threads[/{id}]` | Past conversations |
| POST | `/kairos/train` | `{market, timeframe?}` → job: study the history again |
| GET | `/kairos/stats?market&timeframe?` | What Kairos learned (best and worst signals) |
| GET | `/kairos/lessons?market?` | Lessons from its own paper trades |
| POST | `/kairos/desk` | `{market, symbols, timeframe?, capital?}` → job (result `{session_id}`) |
| GET | `/kairos/desk` | The desks (paper sessions running a `kairos` strategy) |
| GET | `/kairos/desk/{session_id}` | Paper session detail + `journal`, `learned`, `lessons` |
| POST | `/kairos/desk/{session_id}/stop` | Stop a desk |
| GET | `/kairos/review/{backtest\|paper}/{id}` | Kairos's latest review of those trades (`{review: … \| null}`, Phase 11) |
| POST | `/kairos/review/{backtest\|paper}/{id}` | Review now → job |
| GET | `/kairos/trade-check/{strategy_id}` | What the trade check has learned about a strategy |
| POST | `/kairos/improve/{strategy_id}` | Improve with Kairos → job (result: `{changed, headline, lines, compare, to_version?}`) |
| GET | `/kairos/improvements?strategy_id?` | Past improvement attempts |
| GET | `/kairos/learner` | The always-on learner: `{on, thread, running, last_round_at, next_round_at, activity, history, strategies}` |
| POST | `/kairos/learner/round` | Study now → job |

### Shapes (implemented, Phase 9)
- `GET /analysis/chart` → `{instrument, timeframe, report, forecast, disclaimer, computed_ms,
  training_job}`. `report`: `{symbol, name, market, timeframe, as_of, close, change_pct, atr,
  score (−100…100), bias, confidence, components, trend, momentum, volume, zones, lines, channel,
  patterns, candles, divergences, fibonacci, future, idea, invalidation, headline, summary}`;
  each pattern/candle/divergence carries `stats: {n, hit_rate, avg_return_pct, base_rate,
  horizon, paper_n, weight} | null`. `training_job` is set when this reading started Kairos's
  first study of the market. Too little history → `409 NOT_ENOUGH_PRICES`.
- `forecast` / `GET /analysis/forecast` → `{horizon, origin, path: [{ts, p10, p25, median, p75,
  p90}], up_probability, median_change_pct, range80_pct, weights, model_medians_pct, track:
  {tests, direction_hits, direction_rate, skill_pct, band80, band50} | null, text, verdict, edge,
  peers, live: {n, direction_hits, inside80, pending} | null}`.
- `GET /news` → `{enabled, refreshing, sources, items: [item]}` plus, for a stock, `mood: {score,
  count, tone}` and `alert: {state: critical|negative|positive|quiet, score, count, headline,
  flag?}`, and for a market `risk` (the gauge). Item = `{id, title, summary, link, publisher,
  source, published_at, sentiment, tone, symbols, topics, topic_labels, group, severity (0–5),
  impact (−1…+1), scope: IN|US|WORLD, sectors: {name: ±1}}`.
- `GET /news/live` → `{enabled, refreshing, sources, items, risk: {IN, US, WORLD}, guard:
  protective|cautious|off, groups, topics: [{key, label, group}], as_of}`. `region`: ALL, IN, US
  or WORLD; `group`: Geopolitics, Economy, Markets or Companies.
- Gauge (`/news/risk`, `risk.*`) → `{market, level (0–100), name: calm|watchful|elevated|severe,
  text, score, drivers: [{title, link, publisher, published_at, topic, topic_label, severity,
  impact, sources, weight}], headlines, as_of}`.
- `POST /kairos/chat` SSE events: `thread`, `thinking`, `step` (`{id, tool, status:
  running|done|error, label, detail?, pct?, card?, ui?: {navigate}}`), `text` (`{delta}`),
  `text_reset`, `notice`, `done` (`{message_id, thread_id, mode, unchecked, footer}`), `error`.
  Cards: `chart`, `forecast`, `scan`, `news`, `news_risk`, `backtest`, `strategy`, `paper`,
  `desk`, `list`, `overview`, `link`.
- `GET /kairos/stats` → `{market, timeframe, trained: {at, candles, samples, base_rate, horizon}
  | null, best: [signal], worst: [signal], paper_trades, signals, exits: {plan, chosen, why} |
  null (D-140), judge: {on, text} (D-145)}`; signal = `{key, label,
  family, direction, n, hit_rate, base_rate, paper_n, paper_wins, edge, weight, text}`.
- `GET /kairos/desk/{id}` adds `journal: [{id, kind: thesis|review|note|day, symbol,
  instrument_id, trade_id, entry_ts, score, text, won, return_pct, at}]`, `learned` (as stats)
  and `lessons: [{id, text, market, at}]`; a session that isn't a desk → `404 NOT_A_DESK`.
- Strategy definitions gain `kind: "kairos"`: `{kairos: {entry_score, exit_score, stop_atr,
  target_r, trail_atr, max_bars, allow_short}, weights: {signal: 0…2}, trained_at}` plus the
  usual settings (D-60). Paper session summaries include the strategy `kind`.

### Shapes (implemented, Phase 11; docs/KAIROS.md §16–19)
- `POST /backtests` accepts `trade_check: off|learn|balanced|strict` (default off); a run with
  the check reports `metrics.trade_check = {mode, checked, skipped, skipped_followed,
  skipped_would_have_won, skipped_would_have_lost, top_reasons: [{words, count}], learned_from,
  proven, skill, judged, usual_win_rate}`; skipped signals are rejected orders whose reason starts
  "Kairos's trade check skipped this signal". Paper session summaries include `trade_check`.
- Review: `{trades, period, headline, lines, advice, money: {gross, charges, net, cost_share,
  avg_gross, avg_charges, avg_net, trades_per_month, verdict, level: ok|warn|bad}, wins: {trades,
  wins, losses, win_rate, avg_win, avg_loss, payoff, breakeven_win_rate, expectancy, best3_share,
  net_without_best3, longest_losing_streak, lines}, exits: {by_reason: [{reason, label, count,
  win_rate, avg_net}], lines}, conditions: [{key, label, unit, edges, thirds, spread}],
  failure_reasons: [{key, third, count, losers, win_rate, text, gap}], filters: {note, rules:
  [{key, label, keep, value, text, condition, train, test: {before, after}, held_up}]}, losers:
  [{symbol, side, entry_ts, exit_ts, net, return_pct, exit_reason, why}], created_at, kind,
  ref_id, strategy_id}`.
- Forecasts (`/analysis/forecast` and `forecast` in `/analysis/chart`) add `candles: [{ts, open,
  high, low, close, p10, p90, direction: −1|0|1}]`, `previous: {kind: live|re-created, made_at,
  origin, formed, horizon, complete, candles: [{ts, actual, predicted?, direction_right?,
  inside80?, p10?, p90?}], predicted, direction_hits, direction_scored, inside80,
  predicted_change_pct, actual_change_pct, end_error_pct, text} | null`, `calibration: {width,
  bias, tests, live, coverage, text, checked}`, `analyst: {beta, score, news_tilt} | null`,
  `news: {stock, risk, tilt, widen_pct} | null`; `weights` may include `analyst`.
- Kairos chat cards add `options` (`{title, market, spot, days, vol, legs: [{label, premium}],
  net, max_profit, max_loss, breakevens, pop, grid, at_expiry, today, lot}`; `null` = unlimited).
  New tools: `review_trades`, `improve_strategy`, `learning_status`, `option_strategy`.

## Metis, Kairos's AI researcher (Phase 12, docs/METIS.md)
Switching Metis on, its pace, whether it saves what holds up, and its focus are settings
(`metis.enabled`, `metis.every_minutes`, `metis.apply`, `metis.focus`) via `PUT /settings`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/metis` | `{on, state: off\|waiting_ai\|waiting\|scheduled\|working, doing, waiting, ai_ready, thread, last_round_at, next_round_at, every_minutes, apply, focus, totals: {rounds, ideas, tested, held_up, saved}, rounds: [Round], ideas: [Idea]}` (latest 10 rounds, 30 ideas) |
| GET | `/metis/ideas?status?&limit?` | `{ideas: [Idea]}` |
| GET | `/metis/ideas/{id}` | `{idea}` with its full rules (including the tested definition) |
| GET | `/metis/rounds/{id}` | `{round, ideas}`; the round includes `brief`, what Metis was shown; every round has `autopsy: [{strategy, lines}]` (D-109) |
| POST | `/metis/round` | Research now → `{job_id}` (job kind `metis_round`, result `{status, round_id, note, ideas, kept, direction}`); without the AI helper it runs a playbook round (Phase 14); 409 `BUSY` |
| GET | `/metis/library` | What Metis knows → `{total, areas: [{key, title, sections: [title]}]}` |
| POST | `/metis/ideas/{id}/save` | Save an idea that held up → `{idea}`; 409 `NOT_KEPT`, `CHANGED` (the strategy has a newer version) or `GONE` |

- Round: `{id, started_at, finished_at, status: running|done|failed|skipped, trigger: auto|user,
  focus, model, noticed, note, ideas, kept, thinking}`.
- Idea: `{id, round_id, created_at, kind: filter|tweak|new_strategy, title, why, market,
  strategy_id, strategy_version_id, rules, status: held_up|saved|rejected|untestable, verdict,
  result: {start, end, split, symbols, capital, baseline: {study, exam} | null, candidate:
  {study, exam}, checks: [{ok, text}], study_line}, saved_strategy_id, saved_version_id, run_id}`;
  a part is `{trades, wins, win_rate, net, gross, charges, avg_win, avg_loss, profit_factor,
  exits}`.
- Kairos tool `metis` (`{action: status|on|off|now, focus?}`).
- Phase 14 additions: `/metis` also returns `state: playbook`, `ai_note` and `direction`; rounds have
  `direction: improve_live|improve|discover|opportunities`; ideas have `kind` simplify|universe too,
  `origin: ai|playbook`, and `result.luck: {dsr, psr, tries, days, sharpe}` and, for a "new"
  strategy that was really one the user has, `result.family: {strategy_id, name, version_id, why}`.
  `POST /metis/ideas/{id}/save` returns `saved_as: new_strategy|revision|unchanged`; 409
  `DAILY_LIMIT` only when Metis saves on its own.

## Portfolios and opportunities (Phase 15, docs/PORTFOLIO.md)
| Method | Path | Purpose |
|---|---|---|
| GET | `/portfolios` | `{portfolios: [Summary]}` |
| POST | `/portfolios` | `{market, budget?, risk: careful\|balanced\|bold, name?, method?: mix\|momentum\|low_volatility}` → `{portfolio, job_id}` (planning starts at once, job kind `portfolio_plan`; a ranking method plans one whole-index sleeve, D-91) |
| GET/PATCH/DELETE | `/portfolios/{id}` | Detail · change `{name?, budget?, risk?, manage?}` · archive |
| POST | `/portfolios/{id}/plan` | Plan again → `{job_id}` (result: the Plan) |
| POST | `/portfolios/{id}/backtest` | Backtest the whole portfolio → `{job_id}` (job kind `portfolio_backtest`, result: Backtest) |
| POST | `/portfolios/{id}/paper/start` · `/paper/stop` | Paper trade it (a session per sleeve) · stop every sleeve → `{portfolio}` |
| GET | `/portfolios/{id}/rebalance` | Preview: `{total, cash, reserve_target, moves: [{sleeve_id, session_id, move, target, equity}], lines}`; 409 `NOT_PAPER` |
| POST | `/portfolios/{id}/rebalance` | Rebalance now (free cash only) → `{moved, cash}` |
| GET | `/opportunities?market?&status?` | `{opportunities: [Opportunity]}` (open and in a portfolio by default) |
| POST | `/opportunities/scan` | `{markets?}` → `{job_id}` (job kind `opportunity_scan`) |
| POST | `/opportunities/{id}/dismiss` | `{opportunity}` |
| POST | `/opportunities/{id}/backtest` | Backtest the revision on its stocks and settings → `{run_id}` |

- Summary: `{id, name, market, budget, risk, method, status: draft|paper|stopped|archived, manage, created_at,
  updated_at, sleeves_planned, backtest_return, paper_started_at, live?: {equity, cash, invested, pnl,
  return}}`; Detail adds `plan`, `backtest`, `sleeves` (live), `moves` (the diary), `cash`,
  `opportunities`.
- Plan: `{market, budget, risk, sleeves: [{key, name, strategy_id, version_id, symbols, overrides,
  size_pct, opportunity_id, weight, capital, score, sharpe, luck, volatility, worst_drop_pct,
  reasons}], left_out: [{name, reason}], cash, invested, method, estimate: {volatility, return, sharpe,
  diversification}, overlaps, notes, made_at}`.
- Backtest: `{start, end, budget, final, metrics (SPEC §6.3), curve: [[ts, equity]], benchmark,
  sleeves: [{name, capital, final, moved, made, trades}], rebalances, moved, reserve_end, parts:
  {split, study, exam}, honesty, made_at}`.
- Opportunity: `{id, market, strategy_id, version_id, name, symbols, overrides, source:
  scanner|metis|kairos_research|user, status: open|in_portfolio|dismissed|stale, score, study, exam,
  luck, evidence, found_at, checked_at}`.
- Backtests (`POST /backtests`) and paper sessions (`POST /paper/sessions`) accept `size_pct` (and
  sessions `symbols`, `overrides`, `portfolio_id`) so a revision runs on chosen stocks and settings
  without a new version (D-80). Paper session summaries gain `moved` (money a portfolio moved in or
  out; not counted as profit) and `portfolio_id`.
- Kairos tool `portfolio` (`{action: status|build|plan|backtest|start|stop|rebalance|opportunities|scan,
  market?, budget?, risk?, method?, portfolio?}`); the router understands "build me a portfolio with 1 lakh",
  "how is my portfolio doing?", "find new opportunities", "rebalance my portfolio", and (Phase 16)
  "build me a momentum portfolio" / "a low volatility portfolio".
- A sleeve or opportunity with `symbols: []` is a ranking strategy on its own universe (the whole
  index, re-ranked monthly, D-91).

## Checks (Phase 16, docs/LANDSCAPE.md §4)
| Method | Path | Purpose |
|---|---|---|
| POST | `/strategies/{id}/lookahead` | The look-ahead check (D-88) on a saved version: `{version_id?, symbols?, start?, end?}` → `{job_id}` (job kind `lookahead`, result: a Check) |
| GET | `/strategies/{id}/checks?kind=lookahead\|forward&limit=` | `{checks: [Check]}`, newest first |
| GET | `/checks/forward` | `{items: [{subject: revision\|sleeve, name, strategy_id, version_id, sleeve_id, portfolio_id, since, days_since, check: Check\|null}], auto_undo}` (D-90) |
| POST | `/checks/forward/run` | Check now: every subject with enough new candles → `{job_id}` (job kind `forward_check`, result `{checked, checks}`) |
| POST | `/checks/{id}/undo` | Act on a forward check that stopped holding up → `{check}` (400 `NOTHING_TO_UNDO`, 404 `CHECK_NOT_FOUND`) |
| GET | `/backtests/{id}/tearsheet` | The tear sheet (D-89): saved with every run since Phase 16, worked out from the saved rows for older runs |

- Check: `{id, kind: lookahead|forward, created_at, strategy_id, strategy_name?, version_id, version,
  baseline_version_id, sleeve_id, portfolio_id, verdict, title, result, action}`; verdicts: `clean`,
  `lookahead`, `history`, `no_data` (look-ahead) and `waiting`, `holding`, `slipping`, `failed`
  (forward).
- Look-ahead result: `{verdict, title, text, notes, symbols, signals, version, timeframe, start, end,
  lookahead: {slices, signals_checked, indicators_checked, findings: [{symbol, ts, kind:
  signal|indicator, text, …}], leaky_indicators}, history: {extra_candles, signals_compared,
  findings: [{symbol, ts, usual, more_history, text}], unsettled: [{indicator, max_change_pct}]}}`.
- Forward result: `{verdict, title, text, subject, name, since, sessions, trades, numbers: [{label,
  value}], raw, can_undo, undo_label}`.
- Tear sheet (`metrics.tear_sheet` of a backtest): `{days, sharpe: {value, band: {p5, p50, p95}, psr,
  dsr, trials, min_track_record_days, have_days}, outcomes: {return_p5, return_p50, return_p95,
  drop_p50, drop_p95}, trade_order: {trades, history, p50, p95, worst, losing_streak_p95}, rolling:
  {window, points: [[day, sharpe]], share_positive}, underwater: {periods: [{peak, trough, recovered,
  depth, days_falling, days_recovering}], time_underwater}, risk: {var_95, cvar_95, tail_ratio,
  best_day, worst_day, best_month, worst_month, positive_months, skew, kurtosis}, years: [{year,
  return}], summary: [plain sentences]}`.
- A sweep's `metrics.sweep.pbo`: `{pbo, tries, days, blocks, combinations, median_logit, oos_loss,
  degradation, metric, text}` (D-89); a warning `overfit` joins the honesty panel at PBO ≥ 50%. Metis
  ideas' `result.overfit` has the same shape over the strategy's tries.
- Templates: `GET /templates` lists the visual starters (`kind: "visual"`) and the ranking ones
  (`kind: "ranking"`: `momentum_top`, `momentum_fast`, `low_volatility`); `POST /strategies` with a
  ranking `template_key` creates a ranking strategy.

## Watchlists, sectors, the world and the autopilot (Phase 18, docs/WORLD.md)
| Method | Path | Purpose |
|---|---|---|
| GET | `/watchlists?market&category&kind` | `{watchlists: [Summary]}` (ready-made lists load on first use) |
| POST | `/watchlists` | `{market, name, symbols[], description?}` → `{watchlist: Detail}` (201; 409 `NAME_TAKEN`, 422 `UNKNOWN_SYMBOLS`) |
| GET | `/watchlists/{id}` | `{watchlist: Detail}` |
| PATCH | `/watchlists/{id}` | Yours only: `{name?, description?, add?[], remove?[]}` (409 `READ_ONLY` for others) |
| DELETE | `/watchlists/{id}` | Yours, Kairos's or Metis's (409 for ready-made) |
| POST | `/watchlists/{id}/copy` | `{name?}` → an editable copy (201) |
| POST | `/watchlists/refresh-factors?market` | Rebuild the price-factor lists now → `{refreshed: {"IN:momentum": n}}` |
| GET | `/instruments/{id}/profile` | `{profile: {sector, industry, size, lists, tags}, lists: [{id, name, kind, category}]}` |
| GET | `/sectors?market` | `{market, as_of, sectors: [Sector], industries: [Sector], booms, slumps, stocks, sentence, lines}` (D-98) |
| GET | `/indices?market=IN|US&refresh` | Every index by group (`broad`, `sector`, `gauge`): `{market, groups: [{key, indices: [{symbol, name, group, value, as_of, change_pct, change_1m_pct, ytd_pct, change_1y_pct, spark}]}]}` (D-174) |
| GET | `/world?refresh` | `{IN: View, US: View, events: [Event], moves: [Move]}` (D-95) |
| GET | `/world/events?limit` · `/world/moves?market` · `/world/lessons?scenario` · `/world/map` | The events; investigated moves; measured reactions `{scenario, title, market, target, n, mean_pct, map, agrees}`; the 33 scenarios with chain, effects and assets |
| POST | `/world/investigate?market` | Investigate unusual moves on the latest candle now → `{moves: [Move]}` (each once) |
| POST | `/world/learn` | Re-measure past and live events → `{job_id}` (job kind `world_learn`) |
| GET | `/world/stock/{id}` | `{stock: {symbol, tilt, why[], drivers[], sector, tags}}` |
| GET | `/autopilot` | `{on, running, doing, last_round, desks: [{id, market, state, name, auto}], prices: {IN: {have, want}}, metis: {on, ai_ready, why}, last}` (D-99). `have`: stocks of the market with saved daily prices; `want`: every stock the autopilot keeps, the whole exchange (D-102) |
| POST | `/autopilot/run` | One round now → `{job_id}` (job kind `autopilot`) |

- Summary: `{id, name, market, kind, category, key, description, reason, count, editable, live,
  created_at, updated_at}`; Detail adds `rule`, `items: [{instrument_id, symbol, name, type, sector,
  industry, size, tags, note, last, change_pct}]`, `with_prices`.
- Sector: `{name, members, returns: {1w, 1m, 3m, 6m}, rs_ratio, rs_momentum, quadrant, breadth:
  {members, above50, above200, new_highs}, month_z, volume_ratio, state boom|strong|neutral|weak|slump,
  score, leaders, laggards, sentence}`.
- View: `{market, tilt, sectors, tags, drivers: [{scenario, title, calming, strength, weight, chain,
  effects: [{target, label, value, map, measured: {n, mean_pct, hit_rate}|null}], headlines,
  event_id}], helped: [Stock], hurt: [Stock], sentence}`; Stock `{instrument_id, symbol, name, tilt,
  vs_market, why}`.
- Move: `{id, market, target, timeframe, start_ts, end_ts, move_pct, z, verdict, text, created_at,
  causes: [{key, kind world|news|company|contagion, title, score, headline, sources, chain, clues,
  against}], confidence, headlines_read}`.
- `/analysis/chart` gained `timeframes: {chart, timeframes: [{timeframe, label, candles, trend,
  regime, momentum, rsi, above_sma50, above_sma200, direction}], score, verdict, headline, text,
  long_ok, short_ok} | null` (D-97). Strategy operands accept `chart` (D-97).

## WebSocket: `/ws`
Single connection; messages are JSON `{type, data}`.

| type | When |
|---|---|
| `job.progress` | Any long job (refresh, backtest, model pull): `{job_id, pct, eta_s, message}` |
| `job.done` / `job.failed` | Job finished (failed includes the error envelope) |
| `paper.tick` | New bar processed: `{session_id, equity, day_pnl, positions[], freshness_s}` |
| `paper.fill` | Fill: `{session_id, symbol, side, qty, price, reason}` |
| `paper.event` | Pause/resume/outage/info with `message_plain` |
| `market.status` | Market opened/closed |
| `source.status` | Data source state changed |

The frontend reconnects automatically with back-off and re-fetches state on reconnect.

## Added in Phase 27

- `GET /api/alarms`: what should have happened and didn't (D-222).
- `GET /api/actions?q=&kind=&status=&who=&hours=&limit=`: the action log, with a summary by kind (D-220).
- `GET /api/paper/trades/{id}/story`: why a trade happened and what worked (27.11).
- `POST /api/metis/combine` `{version_ids, mode, min_votes}` and `POST /api/metis/combine/repair/{version_id}`: background jobs (D-227).
- `GET /api/data/coverage`: now the whole set in `totals`, and in `rows` only stocks with a problem (D-226).
