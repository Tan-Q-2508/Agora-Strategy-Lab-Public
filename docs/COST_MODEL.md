# COST_MODEL: charges, slippage and fills

All rates live in `charge_schedules` / `brokerage_profiles` / `slippage_profiles`
(see `DATA_MODEL.md`) and are resolved **by the simulated trade date** (D-09).

> **Verify before seeding.** The values below are starting points from public broker
> calculators and exchange circulars as commonly published up to 2025–26. At build time,
> check each against an official source (NSE, SEBI, state stamp act notifications, SEC,
> FINRA), set `source_url` and `verified_at`, and add earlier effective-dated rows where
> rates changed within the backtest range you support (at least 10 years back, best effort).

## 1. India (NSE equity)

Turnover = price × quantity per leg.

| Charge | Intraday | Delivery | Basis |
|---|---|---|---|
| Brokerage | From profile (default "Discount": min(₹20, 0.03%) per order) | From profile (default ₹0) | Per executed order |
| STT | 0.025% on **sell** | 0.1% on **buy and sell** | Turnover |
| Exchange transaction charge (NSE) | 0.00307% (from 1 Mar 2026; history in D-38) | same | Turnover, both sides |
| SEBI turnover fee | ₹10 per crore | ₹10 per crore | Turnover, both sides |
| Stamp duty | 0.003% on **buy** | 0.015% on **buy** | Turnover |
| GST | 18% on (brokerage + exchange charge + SEBI fee) | same | Not on STT or stamp duty |
| DP charge | n/a | ₹13.00 + GST per scrip per day on **sell** (₹3.50 CDSL + ₹9.50 broker) | Per scrip per sell day |

Rounding (implemented in `backend/costs/model.py`, the only place it lives): compute in
`Decimal`; each charge rounds half-up to the paisa; STT rounds to the nearest rupee; GST is
18% of the already-rounded brokerage + exchange charge + SEBI fee + DP charge. US: the SEC fee
rounds **up** to the next cent; FINRA TAF rounds half-up to the cent (cap applied first).

Brokerage profiles to seed: "Discount broker (₹20 cap)", "Zero brokerage", "Full-service
(0.3% delivery / 0.03% intraday)". User can edit or add.

## 2. US

| Charge | Basis |
|---|---|
| Commission | From profile (default $0) |
| SEC Section 31 fee | Sells only, rate per $1M of proceeds, changes periodically; **verify current and historical rates** |
| FINRA Trading Activity Fee | Sells only, per share with a per-trade cap; **verify** |
| Borrow fees (shorts) | Not modeled in v3.0; shown as a caveat |

## 3. Slippage

- Applied as basis points against the trader: buys fill higher, sells lower.
- Defaults: India 5 bps for Nifty 50 stocks, US 2 bps for large caps/ETFs. User-editable.
- Optional "volatility-aware" mode (later): slippage = max(base_bps, k × ATR%/bar).

## 4. Fill model (reference for engine + tests)

Let bar `t` close produce a signal.

1. **Market order** → fills at `open[t+1] ± slippage`. If `t+1` is in a new session for
   India intraday, it is rejected (no overnight intraday positions).
2. **Limit buy at L** → fills at `min(open, L)` on the first later bar where `low ≤ L`.
   Limit sell mirrors this.
3. **Stop sell at S** (long stop-loss) → triggers on the first later bar where
   `low ≤ S`; fills at `min(open, S) − slippage` (gaps through stops fill at the open).
   Stop buy mirrors this.
4. **Stop and target both inside one bar** → assume **stop first** (conservative).
5. **Trailing stop** updates using closed bars only, then behaves as rule 3.
6. **Volume cap:** an entry buys at most `volume_cap_pct` × bar volume (default 5%), whole
   shares; a bigger order is filled at that size (D-135), and rejected with reason "Order too
   large for this candle's volume" only when not one share fits.
7. **Circuit-locked bar** (high == low and volume > 0, at a price band): no fills.
8. **Intraday square-off:** at the square-off time (default 15:20 IST) open intraday
   positions close at that bar's open.
9. **End of backtest:** open positions are marked to the last close and reported as
   `end_of_test`; they count in equity, not in closed-trade stats.
10. **Quantity:** whole shares only (round down). Reject if qty < 1.
11. **Partial exits** (D-125): each step is a limit order for part of the starting quantity
    (rounded down, at least one share always left), filled like rule 2 (no slippage; at the open
    when the bar opens past it), nearest step first, only when the stop wasn't hit in that bar
    (rule 4). With "move the stop to the entry", the stop becomes the entry price after the first
    step, from the next bar. Each partial pays its own charges. The position is still **one
    trade**: its quantity is the starting quantity, its exit price the average of all sales, its
    P&L and charges the sum, so win rates aren't inflated by counting partial sales as wins.

## 5. Where costs appear

- Each fill records its charges broken down by type.
- Backtest results show total charges, charges as % of gross profit, and a breakdown
  donut chart. This often decides whether a strategy is viable, so make it prominent.
- Paper trading charges every fill with the same model (one engine, D-04). Checked on the
  laptop on 2026-11-06 against the real records (the user asked "are you not considering
  brokerage and taxes?"): all 492 Indian paper fills carried charges, at the rates above
  (intraday buy about 0.023%, intraday sell about 0.046%, delivery buy about 0.119%, delivery
  sell about 0.123% with the DP charge); US buys carry $0 on the $0-commission profile and US
  sells carry the SEC fee and FINRA TAF.
- **Not modeled: income tax on profits** (India's capital-gains tax, US capital-gains tax). It
  depends on the person's tax slab, holding period across the year and set-offs of losses, so
  results are before income tax. STT, stamp duty, GST and the exchange and SEC fees, which are
  taxes charged on each trade, are included.

## 6. Golden tests (required)

Write hand-calculated cases in `tests/golden/test_costs.py`, each with the arithmetic in
comments, at minimum:
- India intraday round trip: buy 100 @ ₹1,000, sell 100 @ ₹1,010, discount profile.
- India delivery round trip: buy 50 @ ₹2,500, sell 50 @ ₹2,600 on a later day (incl. DP).
- India rate change: the same trade on dates either side of a seeded rate change.
- US round trip: buy 100 @ $200, sell 100 @ $205, $0 commission.
- Slippage direction for buys, sells, and shorts.
- Gap through a stop; stop-and-target in one bar; volume-cap rejection.
