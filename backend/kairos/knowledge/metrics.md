# Backtest metrics

## Return measures: total return, CAGR
tags: total return cagr annual return compound growth
Total return is the whole gain over the test. CAGR is the steady yearly rate that would have produced it, the fair way to compare tests of different lengths. Always compare with the benchmark's CAGR over the same dates.

## Risk measures: drawdown, volatility
tags: max drawdown drawdown duration volatility underwater risk
Maximum drawdown is the worst fall from a peak to a later low; it is the pain you would have lived through. Drawdown duration is how long it took to recover. Volatility is the annualised standard deviation of daily returns. Most people abandon strategies in drawdowns deeper than they imagined, so size so that the worst drawdown is bearable.

## Risk-adjusted: Sharpe, Sortino, Calmar
tags: sharpe ratio sortino calmar risk adjusted return
Sharpe ratio = annual return ÷ annual volatility (Agora uses a 0% risk-free rate): above 1 is good, above 2 is excellent and should raise overfitting suspicions in a backtest. Sortino counts only downside volatility. Calmar = CAGR ÷ maximum drawdown.

## Trade statistics: win rate, profit factor, expectancy
tags: win rate profit factor expectancy average win loss trades exposure
Win rate is the share of profitable trades; profit factor is gross profit ÷ gross loss; expectancy is the average result per trade. Exposure is the share of time money was invested. Fewer than 30 trades is too few to trust any of these.
