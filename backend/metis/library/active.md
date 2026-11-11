# Active trading research: exits, win rates, the index bar and institutional flows

## Partial exits (scaling out) in research
tags: partial exits scale out scaling out profit booking breakeven r multiple research
Scaling out trades some of the right tail for a higher hit rate and a smoother equity curve. Research and practitioner tests agree on the shape: it helps strategies whose moves fade (mean reversion, short swings, intraday), and usually costs pure trend-following money, whose profits come from a few outliers. The stop-to-breakeven rule after the first partial removes the "winner turns into a loser" trade but adds some stopped-out-at-entry trades that would have recovered.
**In Agora:** tweak with "partial_half_r": 1 (half at 1R, stop to entry) or "partial_thirds_r": 1 (a third at 1R and 2R); both need a stop-loss ("stop_loss_pct" in the same change if there is none). The trade is still counted once, so the win rate isn't inflated.

## Why a weak strategy is weak: diagnose before fixing
tags: diagnose weak strategy why low results root cause entry exit regime news costs
Before changing anything, find which part failed. The entry: the trigger indicator is near random on its own (check the win rate against a random-entry baseline). The market: losers cluster when the index or the bigger chart trends against the trade (add the trend or bigger-chart filter). News: losers cluster around results or big events (Kairos's news guard). Costs: charges take over 30% of gross profit (fewer, stronger trades). The exits: trades were ahead and gave it back (a trailing stop or partial exits), losers ran (a stop-loss or time limit), or stops sat inside the noise (a wider, ATR-based stop). Fix the cause the evidence points to, one change at a time, and keep it only if the exam years agree.
**In Agora:** the trade autopsy (D-109) and the first look (D-81) produce these findings with ready experiments.

## Beating the index is the minimum bar
tags: benchmark beat index nifty buy and hold alpha minimum bar
A strategy is only worth running if it beats buying and holding the index over the same period, after costs; otherwise the investor should buy an index fund. Measure it on unseen data, on the whole starting money, and look at drawdown too: a strategy that matches the index with half the drawdown can still be useful inside a portfolio, but alone it fails the bar.
**In Agora:** new strategies must beat the Nifty 50 (or SPY) in the exam years to be kept (D-126); the backtest summary always says whether the strategy did better than holding the index.

## High win rate strategies: what the evidence says
tags: high win rate short term reversal connors rsi 2 mean reversion evidence
The families with genuinely high hit rates are short-horizon reversals in liquid stocks and indexes in up-trends (Connors' RSI(2) and cumulative-RSI rules: 65–75% in his tests), opening-range and VWAP intraday plays on news days, and option selling (high hit rate, fat left tail: not for a small account). Their average win is small, so they are very sensitive to costs and slippage; test them with Agora's full charges.

## Institutional flows as a research variable
tags: institutional flows fii dii fpi flows predictability index rebalancing research
Flow effects with good evidence: index additions and deletions (prices move between announcement and effective date, partly reverse after), mutual-fund flow pressure (stocks bought by funds with big inflows run up, then mean-revert), end-of-quarter window dressing, and the post-earnings drift (prices keep moving in the direction of an earnings surprise for weeks). Daily FPI flows in India follow returns more than they predict them; persistent multi-week flows and the rupee are better regime signals than any single day.
**In Agora:** these work as regime and universe choices (sector rotation, the world desk), not as entry rules on one stock.

## Volume and the footprints of accumulation
tags: volume accumulation distribution obv relative volume delivery footprints research
Price moves on high relative volume carry more information than moves on light volume, and volume-confirmed breakouts fail less often in most tests. Accumulation indicators (OBV, accumulation/distribution, money flow) and India's delivery percentage are proxies for institutional buying. Use them as filters on a trend or breakout entry ("relative volume at least 1.5"), not as the trigger.

## Realistic return targets
tags: realistic returns monthly return expectations sharpe compounding livelihood
A Sharpe ratio of 1 to 2 after costs is excellent for a systematic strategy; at 15% annual volatility that is roughly 15–30% a year. Monthly figures of 10–20% sustained are not seen in audited records; a backtest that shows them is almost always overfitted, has look-ahead, or ignores costs and liquidity. Say so when a result looks like that, and prefer the robust strategy over the spectacular one.
