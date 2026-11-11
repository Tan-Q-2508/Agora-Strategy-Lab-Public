# Volatility and regimes

## Volatility clusters
tags: volatility clustering garch arch engle bollerslev
Calm days follow calm days and wild days follow wild days (Mandelbrot noted it in the 1960s; Engle's ARCH, 1982, and Bollerslev's GARCH, 1986, model it). GARCH(1,1): tomorrow's variance = ω + α·(today's return)² + β·(today's variance), with α + β close to 1 for stocks. Volatility is far more predictable than returns, which is why risk can be managed even when direction can't be forecast.

## EWMA volatility
tags: ewma riskmetrics volatility estimate exponential lambda 0.94
RiskMetrics (1996) set the industry default: variance updated as λ·variance + (1−λ)·return², with λ = 0.94 for daily data (about a month's memory). Simple, responsive and nearly as good as GARCH for sizing.
**In Agora:** `ewma_vol` in `backend/quant/series.py`; Kairos's volatility forecast model uses the same λ.

## Range-based volatility
tags: parkinson garman klass yang zhang high low range estimator
Highs and lows hold more information than closes. Parkinson (1980) uses the high-low range; Garman and Klass (1980) add open and close; Yang and Zhang (2000) also handle overnight gaps. With the same data they estimate volatility several times more efficiently than close-to-close.
**In Agora:** `parkinson_vol`; ATR is the trader's version.

## The leverage effect
tags: leverage effect asymmetric volatility negative skew falling markets
Volatility rises more after falls than after rises of the same size (Black, 1976), so stock returns are negatively skewed and falling markets are wilder. Risk models and stops calibrated in calm up-trends underestimate risk in sell-offs.

## Volatility-managed portfolios
tags: volatility targeting volatility managed moreira muir risk scaling
Moreira and Muir (2017) scaled factor portfolios by the inverse of last month's variance and raised Sharpe ratios for most factors: high volatility isn't followed by proportionally higher returns, so cutting exposure then improves the trade-off. Volatility targeting also smooths drawdowns.
**In Agora:** the portfolio aims at its risk level's volatility and keeps the rest in cash.

## Regime detection
tags: regime detection hidden markov model markov switching hamilton
Markets switch between states (calm bull, volatile bear). Hamilton's (1989) Markov-switching model and hidden Markov models estimate the probability of each state from returns. Simpler practical proxies: price above or below a long average, and volatility above or below its median.
**In Agora:** Kairos's trend regime (`analysis/trend.py`) and volatility readings.

## Correlations rise in crises
tags: correlation crisis contagion diversification breakdown longin solnik
Correlations between stocks, and between strategies, rise sharply in sell-offs (Longin and Solnik, 2001): diversification fails when it is most needed. Portfolio risk measured in calm years understates crisis risk; keep a cash reserve and position caps.

## The volatility risk premium
tags: implied volatility realized volatility premium vix india vix options
Implied volatility (what options price in, VIX, India VIX) is usually above the volatility that follows: option sellers are paid for bearing crash risk (Carr and Wu, 2009). A spike in implied volatility signals fear and wider ranges ahead.
**In Agora:** no option-chain data yet; Kairos's options calculator explains the premium.
