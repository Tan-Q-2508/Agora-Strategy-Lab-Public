# LATER: parked ideas (do not build from this file)

Moving anything here into scope requires a new `DECISIONS.md` entry and `PROGRESS.md` tasks.

## Options and futures (from spec v2.2)
Kairos already explains F&O and works out strategy numbers with its options calculator (D-74);
what stays parked is F&O *data*, backtesting and paper trading:
- Option-chain download (NSE, OCC) for real premiums and implied volatility; India VIX.
- India index options: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50. Weekly
  expiries only for NIFTY (since 2024-11-20), weekly expiry day Tuesday (since
  2025-09-01). Lot sizes change by series; store them effective-dated.
- Backtest premiums via Black-Scholes behind a pluggable `PremiumSource` (expired
  contracts aren't available from typical broker APIs); real data hookable later.
- US: SPX/XSP (European, cash-settled) preferred; American-style (SPY, QQQ, single
  stocks) priced with Cox-Ross-Rubinstein binomial.
- Keep `instrument_type` and charge schedules extensible for these.

## Broker data feeds
- Fyers API v3 (historical + WebSocket) or another Indian broker for better intraday
  history and real-time data. Note from v2.2: Fyers refresh tokens expire after 15 days
  and need PIN + interactive login; live-feed use for paper trading conflicted with
  Fyers ToS §11. Re-check terms before adding.
- Alpaca (US) free plan: IEX-only real-time, 15-minute delayed SIP.
- Any broker addition = a new `DataSource` implementation; still no order execution
  unless explicitly decided.

## TradingView cross-check
- Import Strategy Tester "List of trades" CSV and compare trade by trade.
- Live: TradingView webhooks (paid plan, 2FA) to a local endpoint through a tunnel.
- Generate Pine Script from a Strategy Definition.

## Other ideas
- Historical Nifty 50 membership auto-import.
- Volatility-aware slippage; partial fills; borrow fees for US shorts.
- Nifty Next 50 / Nifty 500 universes.
- Exportable PDF backtest report.

## Kairos extras
- Time-series foundation models (Chronos-Bolt, TimesFM) as a fourth forecast model: needs
  PyTorch (~2 GB install) and published tests show no clear edge over simple baselines on
  stock prices. Revisit if a small ONNX build appears.
- Fine-tuning the local model on trading text (doesn't fit a 6 GB card; D-61).
- Larger models (Qwen 3.5 9B+) for users with 8 GB+ graphics cards: selectable today, not
  the default.
- Fundamentals (earnings, ratios) and an economic calendar (central-bank dates, CPI, results).
- Backtesting the news guard on history: GDELT keeps an archive back to 2015, so past headlines
  could be classified the same way. Big download; keep news neutral in backtests until then.
- Acting between candles on a daily desk when news turns severe (today a daily desk acts at the
  next open; an intraday desk within one candle).
- The AI model re-reading the top headlines for nuance (it may explain, never decide: D-56).
- VIX / India VIX download as a fear gauge next to the news gauge.
- Indicators and patterns left out of Phase 10: TD Sequential, volume profile, anchored VWAP,
  relative strength versus the index, diamonds, Wolfe waves, Elliott wave counts, Gann tools,
  pairs trading.

## Metis (Phase 12)
- A fresh exam: as history grows, move the study/exam split forward so ideas are judged on years
  no earlier round has seen (today every round of a strategy shares the same exam years; only
  verdicts, never exam numbers, are fed back to limit how much Metis can learn about them).
- Ideas for the Kairos brain's signal weights and for code strategies' code.

- Comparing strategies by the trades they take (behavioural sameness) as well as by their rules
  (D-79 uses rules only: faster and easier to explain).
- Fundamentals-based ranking (Portfolio123, Danelfin) and social sentiment: no free, reliable,
  local data source yet (LANDSCAPE §3).
- **A real single `Agora.exe`** (RUNBOOK §8 option 3, 2026-10-25): its own window via pywebview or Tauri. Parked: every update would need a rebuild while Agora changes daily; the tray and the app window (D-124) give the same feel.
