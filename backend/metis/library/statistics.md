# Backtest statistics and multiple testing

## The Sharpe ratio and its error
tags: sharpe ratio standard error estimate annualised volatility mean
The Sharpe ratio is average return divided by its standard deviation, annualised by √252 for daily returns. It is an estimate with a large error: with n returns its standard error is roughly √((1 + ½·SR²) ÷ n) per period, so three years of daily data can't tell a Sharpe of 0.5 from 1.0 with confidence. Lo (2002) showed that autocorrelated returns make the usual √252 annualisation misleading. Fat tails and negative skew make it worse.
**In Agora:** `backend/quant/stats.py` computes it and its spread; a bootstrap range is in `resample.py`.

## The probabilistic Sharpe ratio
tags: probabilistic sharpe ratio psr confidence skew kurtosis
Bailey and López de Prado (2012) turned the Sharpe ratio into a probability: given the number of returns and their skew and kurtosis, how likely is it that the true Sharpe exceeds a bar? PSR = Φ((SR − SR*)·√(n−1) ÷ √(1 − skew·SR + (kurtosis−1)/4·SR²)), with per-period Sharpe ratios. Negative skew and fat tails lower it, as they should.
**In Agora:** shown as the "chance it's real" on portfolio candidates and in the luck check.

## The deflated Sharpe ratio
tags: deflated sharpe ratio dsr multiple testing trials selection bias luck
If you try N ideas and keep the best, its Sharpe ratio is inflated by selection. Under "nothing works", the best of N tries is expected to show a Sharpe of about √V·((1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(Ne))), with γ ≈ 0.5772 and V the variance of the tries' Sharpe ratios (about 1/n per period under the null). The deflated Sharpe ratio (Bailey and López de Prado, 2014) is the PSR against that bar. With five years of daily data, a few dozen tries are enough to find an annual Sharpe of about 1 by luck.
**In Agora:** the luck check (D-82) requires a deflated Sharpe of at least 0.5, counting every idea tried on the strategy.

## Minimum track record length
tags: minimum track record length how long enough data
How many returns are needed before an observed Sharpe ratio is convincing? MinTRL = 1 + (1 − skew·SR + (kurtosis−1)/4·SR²)·(z ÷ (SR − SR*))², with z = 1.645 for 95%. A daily Sharpe of 1 a year needs several years of data; a strategy with a few months of good paper trading has proven very little.
**In Agora:** `min_track_record` in `backend/quant/stats.py`.

## The t-statistic hurdle
tags: t statistic hurdle factor zoo harvey liu zhu significance
Harvey, Liu and Zhu (2016) counted hundreds of published factors and argued that, after allowing for all that searching, a new factor should have a t-statistic above about 3.0 rather than the usual 2.0. Hou, Xue and Zhang (2020) re-tested several hundred anomalies with careful methods and most (around two thirds) failed even the usual bar. Treat a single significant result with suspicion.

## Probability of backtest overfitting
tags: pbo cscv overfitting combinatorial cross validation probability
Bailey, Borwein, López de Prado and Zhu (2017) estimate the probability that the best configuration in-sample is below the median out of sample, by splitting the history into blocks and trying every way of choosing half of them for selection (combinatorially symmetric cross-validation). A high PBO means the selection process itself is picking luck.
**In Agora:** planned for sweeps and Metis's tries (Phase 16.3).

## Bootstrap and Monte Carlo
tags: bootstrap monte carlo resampling confidence interval drawdown distribution
Resampling shows how different a result could have been. A block bootstrap of daily returns (keeping runs of days together) gives a range for the Sharpe ratio. Shuffling the order of trades keeps the profit but changes the drawdown: the 95th percentile of shuffled drawdowns is a fairer "worst drop to expect" than the one path history took.
**In Agora:** `bootstrap_sharpe` and `trade_order` in `backend/quant/resample.py`.

## How many trades are enough
tags: number of trades sample size statistical power win rate confidence
A win rate from 20 trades has a standard error of about 11 percentage points; from 100 trades about 5. Below about 30 trades almost nothing can be concluded, and filters that remove most trades make results look better while making them less trustworthy. Count trades in the exam years too, not just overall.
**In Agora:** Metis keeps a change only if it keeps at least 5 exam trades and 30% of the current version's; the honesty panel warns below 30 trades.

## Survivorship and look-ahead bias
tags: survivorship bias look-ahead bias data snooping point in time
Testing on today's index members ignores the companies that dropped out (often after falling), which flatters results. Look-ahead bias uses information not yet known at the time: a closing price to trade at the same close, or a value restated later. Both make backtests look better than any real trading could.
**In Agora:** signals use closed candles and fill at the next open; backtests warn when today's Nifty 50 list is used.

## Stability across periods and stocks
tags: robustness stability sub-period regime stocks consistency
A real edge usually shows up, weaker or stronger, in most sub-periods and on most of the instruments it trades. An edge that comes from one year or two stocks is fragile. Split the record by year, by half of the period, and by stock before believing an average.
**In Agora:** the backtest results table splits by stock; Kairos's review flags dependence on the best three trades.
