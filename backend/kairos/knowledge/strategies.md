# Strategy styles and how to test them

## Trend following and momentum
tags: trend following momentum moving average crossover breakout donchian supertrend 52 week high
Buy strength, sell weakness: moving-average crossovers, channel breakouts (Donchian), Supertrend, 52-week-high momentum. Win rates are often only 30–45%, with a few large winners paying for many small losses. It works in trending, high-ADX markets and bleeds in choppy ranges. Momentum across stocks (buying the strongest 6–12-month performers) is one of the most researched market effects, but it can crash sharply when markets reverse.

## Mean reversion
tags: mean reversion rsi oversold bollinger reversion pullback buy the dip
Buy short-term weakness in a long-term uptrend (for example RSI under 30 while price is above its 200-day average), sell into short-term strength. Win rates are high (60–75%) but losses can be large if there's no stop, because "cheap" can get cheaper. It works best in large, liquid stocks and indices, poorly in stocks in steady decline.

## Breakouts and opening-range breakouts
tags: breakout opening range orb intraday volume range expansion
Enter when price leaves a range with volume. Many breakouts fail; the filters that help are a prior tight range, volume at least 1.5× normal, alignment with the larger trend and a breakout early in the session. Intraday opening-range breakouts on Indian stocks must respect the 15:20 square-off.

## Choosing a strategy for a stock
tags: stock character trending mean reverting efficiency ratio hurst variance ratio research
Measure the stock's character first: efficiency ratio and ADX (does it trend?), how often RSI extremes reverted (does it mean-revert?), and its volatility. Trend tools for trenders, reversion tools for range-bound stocks. Kairos's strategy research does this automatically, then validates on data the strategy never saw.

## Backtesting honestly: overfitting
tags: overfitting curve fitting in sample out of sample walk forward parameter sweep robustness data snooping
With enough parameters any strategy fits the past. Defences: keep rules simple and parameters few; judge on out-of-sample data (the last 30% of the period, untouched while choosing parameters); prefer broad plateaus in a parameter sweep over isolated peaks; run walk-forward tests (optimise on a window, test on the next, repeat); demand enough trades (30+, ideally 100+); and expect live results to be worse than the backtest. A strategy that only works with one exact setting is fitted to noise.

## Costs and slippage
tags: costs brokerage stt slippage charges turnover
Costs decide whether a frequent-trading strategy survives. In India, securities transaction tax, exchange charges, stamp duty, GST and DP charges add up, especially for delivery trades; in the US commissions are usually zero but regulatory fees and slippage remain. A strategy whose profits come from many tiny wins is usually destroyed by costs. Agora's backtests include all of these.

## Benchmarks
tags: benchmark buy and hold nifty spy alpha beta
Always compare with simply holding the index (Nifty 50 or SPY) over the same period. Many strategies "make money" but less than buy-and-hold, with more work and more tax. A strategy is interesting if it beats the benchmark after costs, or matches it with much smaller drawdowns.
