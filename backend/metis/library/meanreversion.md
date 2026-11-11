# Random walks, mean reversion and pairs

## Testing for a random walk
tags: random walk variance ratio lo mackinlay test autocorrelation
Lo and MacKinlay (1988): if prices follow a random walk, the variance of q-day returns is q times the variance of one-day returns. Their variance ratio is about 1 for a random walk, above 1 when moves persist (trend) and below 1 when they reverse (mean reversion), with a z-statistic to judge it.
**In Agora:** `variance_ratio` in `backend/quant/series.py`; the brief reports it for the strategy's stocks.

## The Hurst exponent
tags: hurst exponent trending mean reverting long memory
The spread of k-day price changes grows like k^H: H ≈ 0.5 for a random walk, above 0.5 for trending series, below 0.5 for mean-reverting ones. Estimates are noisy; use it with the variance ratio, never alone.
**In Agora:** `hurst`; `character` combines both into "trending", "mean-reverting" or "close to random".

## Half-life of mean reversion
tags: half-life ornstein uhlenbeck ou process mean reversion speed
Fit Δy = a + b·y (an Ornstein–Uhlenbeck process in discrete time); the half-life is −ln 2 ÷ ln(1 + b) candles. It sets a sensible time exit and look-back for a reversion strategy: a spread with a 10-day half-life shouldn't be held for 60 days or measured with a 200-day average.
**In Agora:** `half_life`; match a reversion strategy's time limit to it.

## Stationarity
tags: stationarity adf unit root test dickey fuller
Prices are not stationary; returns roughly are. Mean reversion strategies need a stationary quantity (a spread, an oscillator, a z-score). The augmented Dickey–Fuller test checks for a unit root; failing to reject it means the series may wander away and never come back.

## Cointegration
tags: cointegration engle granger johansen spread pairs
Two non-stationary prices are cointegrated when some combination of them is stationary (Engle and Granger, 1987; Johansen for many series). That combination, the spread, is what a pairs trade bets will revert. Correlated returns are not enough: correlation describes daily co-movement, cointegration describes a long-run tie.

## Pairs trading
tags: pairs trading statistical arbitrage gatev goetzmann rouwenhorst distance
Gatev, Goetzmann and Rouwenhorst (2006) matched US stocks with the closest normalised price paths and traded divergences, earning attractive excess returns from 1962 into the 2000s, with profits declining in later years. Same-sector pairs (two banks, two IT firms) have the most economic reason to co-move.
**In Agora:** pairs need two-stock strategies, which Agora doesn't have yet (LATER).

## Kalman filter hedge ratios
tags: kalman filter dynamic hedge ratio state space
A pair's hedge ratio drifts over time. A Kalman filter re-estimates it each day from the latest prices, adapting faster than a rolling regression without its window-edge jumps.

## When statistical arbitrage breaks
tags: quant crisis august 2007 crowding deleveraging stat arb risk
In August 2007 many quant equity funds lost heavily within days as crowded positions were unwound at once (Khandani and Lo). Spreads can widen far beyond history before reverting; size reversion trades so a 2–3× historical move doesn't end the strategy.
