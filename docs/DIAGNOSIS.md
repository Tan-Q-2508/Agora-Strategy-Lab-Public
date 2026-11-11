# DIAGNOSIS: how to tell Agora is right, not just running

Run `python scripts/diagnose.py` (add `--journeys` for the failure journeys). It only reads, so it
is safe while desks trade, and it saves a dated report in `data/logs/`. Run it after any change to
the engine, the data or the desks, and before any decision about real money.

## On the live data

| Part | Question | Where |
|---|---|---|
| The books | Every fill inside its candle; gross − charges = net; no trade recorded twice; starting money + trades = cash on every session; no unexplained jump in the money chart; intraday trades closed the same day; one live session a desk | `backend/diagnosis/reconcile.py` |
| The data | No impossible candle; half-saved candles; every desk stock has recent candles; wild moves listed to look at | `backend/diagnosis/market_data.py` |
| Opportunities | Each big up-day of the last 28 days: on a list? wanted? what stopped it? | `backend/diagnosis/opportunities.py` |
| Silence | Stops nobody saw, desks with no prices, work started and never finished, work that should have happened and didn't, a full disk (also on Home) | `backend/diagnosis/alarms.py` |
| Charges | Every fill recomputed with the cost model at its own date | `backend/diagnosis/charges.py` |
| What happened | Every kind of work in the last day: how often, failures, cut off, how long | `data/actions.db` (D-220) |

Charges against `docs/COST_MODEL.md` are proved by the hand-worked tests in `tests/golden/test_costs.py`.
Backtest against paper on the same dates (D-04): `tests/kairos/test_desk.py::test_desk_replay_matches_a_backtest_of_the_brain`.

## Journeys, each with its test

| Journey | Test |
|---|---|
| First start, data download | `tests/data/test_data_api.py`, `frontend/src/App.test.tsx` (onboarding) |
| Strategy, backtest | `tests/strategy/`, `tests/golden/test_engine.py` |
| Paper session, trade, review, learning | `tests/paper/test_runner.py`, `tests/kairos/test_desk.py` |
| Restart, close and reopen | `tests/paper/test_runner.py` (resume, stops on missed candles, D-219) |
| Moving a desk's list with trades open | `test_a_desk_moves_to_a_new_list_with_its_trades_and_money` |
| Sleep and wake, a stop nobody saw, a freeze | `tests/unit/test_uptime.py`, `tests/unit/test_desktop.py` |
| No internet, a source down | `test_outage_pauses_entries_then_late_candles_dont_open_trades`, `tests/data/test_cache.py` |
| Locked database at start | `test_a_busy_database_at_the_start_waits_and_never_stops_a_session` |
| Damaged database | `tests/journeys/test_failures.py` |
| Disk full | `tests/journeys/test_failures.py` |
| Crash mid-work | `test_work_in_flight_when_the_app_is_killed_shows_as_cut_off` |
| Market holiday, half day | `tests/unit/test_markets_status.py`, `tests/data/test_cache.py` |
| Clock change | `tests/unit/test_clock_dates.py` |
| Corrupt or missing log | `tests/journeys/test_failures.py`, `tests/unit/test_log_rotation.py` |

## No look-ahead, by strategy type

Rule strategies: `test_every_daily_template_passes`. Code: `test_fixed_window_code_passes` and
`test_shift_cannot_look_forward`. Monthly rankings: `test_a_ranking_passes`. Kairos's brain:
`test_the_brain_has_no_look_ahead`. Combined: `test_a_combined_strategy_has_no_look_ahead`. Each
truncates the future and proves decisions don't change. A leak is proved to be caught by
`test_a_leaky_indicator_is_caught`.

## Not covered

A real Windows sleep, a real power cut and a real full disk are simulated, not performed. Yahoo's own
closing candle can't be checked against a second source intraday (D-221).
