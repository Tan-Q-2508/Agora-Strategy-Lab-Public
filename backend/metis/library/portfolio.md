# Portfolio construction

## Markowitz and estimation error
tags: markowitz mean variance optimisation estimation error michaud
Mean-variance optimisation (Markowitz, 1952) is the foundation, but fed with estimated means it becomes an "error maximiser" (Michaud, 1989): it piles into whatever had the luckiest past returns. Chopra and Ziemba (1993) found errors in expected returns matter roughly ten times more than errors in variances. Practitioners therefore avoid relying on estimated returns and weight by risk instead.

## One-over-N is hard to beat
tags: equal weight 1/n naive diversification demiguel garlappi uppal
DeMiguel, Garlappi and Uppal (2009) compared 14 optimised portfolio rules with simply splitting money equally: none beat 1/N consistently out of sample, because estimation error ate the gains. Any clever allocation must beat equal weighting after costs to be worth its complexity.

## Shrinking the covariance
tags: covariance shrinkage ledoit wolf estimation noise
Sample covariances from a few years of returns are noisy, especially with many assets. Ledoit and Wolf (2004) blend the sample matrix with a structured target (a scaled identity, or constant correlation) in the proportion that minimises expected error; the weights it produces are steadier and do better out of sample.
**In Agora:** `ledoit_wolf` in `backend/quant/portfolio.py`; the allocator always shrinks.

## Minimum variance
tags: minimum variance portfolio low volatility clarke
The portfolio with the least volatility needs only the covariance matrix, not expected returns, so it avoids the worst estimation error; with the low-volatility anomaly it has historically earned market-like returns with less risk (Clarke, de Silva and Thorley, 2006). Unconstrained it concentrates in a few assets, so caps are needed.

## Risk parity
tags: risk parity equal risk contribution erc maillard roncalli
Equal risk contribution (Maillard, Roncalli and Teïletche, 2010) sizes each holding so each adds the same share of the portfolio's risk; with no correlation it reduces to weights proportional to 1 ÷ volatility. It sits between equal weights and minimum variance and needs no return forecasts.
**In Agora:** `erc` and `inverse_vol`.

## Hierarchical risk parity
tags: hrp hierarchical risk parity clustering lopez de prado
López de Prado (2016) clusters assets by correlation, orders them so similar ones sit together, then splits money top-down between halves in inverse proportion to their variance. It never inverts the covariance matrix, so it is stable with noisy or near-singular data, and it gives similar assets a shared budget instead of letting them crowd out the rest.
**In Agora:** `hrp`; the allocator's default with three or more sleeves.

## Black–Litterman
tags: black litterman views equilibrium bayesian
Black and Litterman (1992) start from the market's implied returns and tilt them towards the investor's views in proportion to the views' confidence, giving sensible, diversified weights instead of Markowitz's extremes. The idea that matters for Agora: tilt a neutral risk-based allocation towards stronger evidence, but only partly.
**In Agora:** the allocator tilts risk weights by evidence × (0.5 + 0.5 × score ÷ best score).

## Kelly and fractional Kelly
tags: kelly criterion fractional kelly half kelly growth sizing thorp
The Kelly fraction (μ ÷ σ² for continuous returns; p − (1−p)/b for a bet) maximises long-run growth, but only with the true edge, which is never known. Half Kelly gets about three quarters of the growth with half the volatility; most professionals use a quarter to a half, or less.
**In Agora:** `kelly` and `kelly_from_trades` in `backend/quant/sizing.py`, used as a ceiling, never as a target.

## Volatility targeting
tags: volatility target risk budget scaling exposure
Choose a target volatility (say 10–15% a year) and scale exposure so the portfolio's estimated volatility matches it, holding the rest in cash. It keeps risk steady across calm and wild markets and, per Moreira and Muir (2017), tends to improve risk-adjusted returns.
**In Agora:** Careful 10%, Balanced 15%, Bold 22% a year.

## Diversify across strategies, not just stocks
tags: diversification strategies correlation sleeves multi strategy
Five strategies that all buy dips in the same stocks are one bet. Diversification comes from return streams that don't move together: trend with reversion, different holding periods, different stocks. Measure the correlation of the strategies' daily returns, not of the stocks.
**In Agora:** the allocator skips a candidate whose returns correlate 0.7 or more with one already picked.

## Rebalancing
tags: rebalancing calendar threshold drift costs schedule
Rebalancing returns weights to target. Calendar rebalancing (monthly, quarterly) is simple; threshold rebalancing (when a weight drifts beyond a band) trades only when needed. Too frequent wastes costs; too rare lets risk drift.
**In Agora:** monthly plus a 25% drift band, moving only free cash.

## Small accounts
tags: small account integer shares minimum capital lot size budget
With a small budget, whole shares and per-order charges dominate: ₹1,00,000 spread over 25 positions is ₹4,000 each, which can't buy one share of the dearest Nifty stocks, and a flat brokerage charge is a large share of a small order. Small budgets need fewer, larger positions and fewer, slower strategies.
**In Agora:** the allocator drops sleeves the budget can't fund (dearest price × most open trades × 1.05) and says so.

## Capacity
tags: capacity liquidity scale market impact volume
Every strategy has a capacity beyond which its own trades move prices. A paper account rarely hits it, but strategies that trade thin stocks or large fractions of a candle's volume would not survive real size.
**In Agora:** orders above 5% of a candle's volume are refused (the volume cap).
