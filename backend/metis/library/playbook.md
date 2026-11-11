# The expert's playbook: symptoms and first experiments

## Win rate below break-even
tags: playbook win rate below break even losing edge diagnosis
Symptom: the study-year win rate is at or under the break-even win rate. First experiments: a trend filter (close above SMA 200 for buys) so dip-buys only happen in up-trends; a filter on the market condition where losers cluster (from Kairos's review); a wider take profit or a trailing stop to raise the payoff instead of the win rate.

## Costs eat the edge
tags: playbook costs eat edge turnover charges share of gross diagnosis
Symptom: charges are over 30% of gross profit, or the average trade earns under about three times its costs. First experiments: a stronger entry threshold (fewer, better trades), a trend-strength filter (ADX at least 20–25), a longer time limit; never a looser filter.

## Losers cluster in falling markets
tags: playbook losers downtrend falling market trend filter regime
Symptom: Kairos's review says most losing trades came when the trend was down. First experiment: the trend filter, close above SMA (200) or SMA (100), on the side that lost. Second: ADX at least 20 with the trend.

## Losers cluster in wild markets
tags: playbook losers high volatility filter natr atr regime
Symptom: losing trades cluster when volatility (ATR % of price) was in its highest third. First experiment: NATR at most the review's upper edge. For breakout strategies the opposite often holds: losers in the lowest third mean breakouts from dead markets fail.

## Losers cluster on thin volume
tags: playbook losers low volume relative volume filter
Symptom: losing trades cluster when relative volume was low. First experiment: relative volume at least the review's lower edge for breakouts; for reversion strategies, test the opposite (panic volume often marks the low).

## Stops cut too many trades
tags: playbook stop loss too tight stop exits whipsaw noise
Symptom: most exits are stop-losses and many stopped trades later recovered. First experiments: widen the stop by about half, or move to a stop in ATRs; check the stocks' character first (stops hurt in mean-reverting stocks, help in trending ones: Kaminski and Lo).

## Losses run too long
tags: playbook losses run no stop time exit average loss large
Symptom: the average loss is much larger than the average win and there is no stop or time limit. First experiments: a time limit near the strategy's typical winning hold, or a stop near two ATRs.

## Profit from a few trades
tags: playbook concentration few trades fragile best three
Symptom: the best three trades make most of the profit. This is fragile; prefer changes that raise the typical trade (filters, exits) over ones that add more lottery tickets, and expect wide uncertainty.

## Too few trades to judge
tags: playbook too few trades statistical power sample size
Symptom: fewer than about 30 study trades. Don't add filters (they remove trades); test the strategy on more stocks with the same character instead (a "universe" idea), or relax an entry setting within its range.

## The strategy doesn't fit its stocks
tags: playbook stocks character trending mean reverting fit universe
Symptom: a mean-reversion strategy on stocks whose variance ratio and Hurst say "trending", or a trend strategy on mean-reverting stocks. First experiment: drop the stocks that fit worst and add ones that fit (a "universe" idea), judged on the exam years.

## Too many rules
tags: playbook too many rules complexity simplify remove condition
Symptom: five or more entry conditions, or filters added round after round. First experiment: remove each condition in turn ("simplify"); keep the simpler strategy when the exam years do at least as well.

## Good in the study years, poor after
tags: playbook overfit study exam decay regime change
Symptom: a strategy (or an idea) is strong in the study years and weak in the exam years. Suspect overfitting or a regime change; prefer simplifying and robust filters (trend, volatility) to more tuning, and remember the luck check counts every try.

## Discovering new strategies
tags: playbook discover new strategy documented anomaly template textbook
Start from documented edges with a reason: trend following (moving-average and breakout rules), short-term reversal within an up-trend, 52-week-high momentum, volatility-squeeze breakouts. Test the textbook version first, unchanged, before tuning anything; propose something different from the strategies the user already has.

## Winners turn into losers
tags: playbook trailing stop gave back gains ahead then lost chandelier atr exits let winners run
Symptom: many losing trades were ahead by at least one ATR before turning (Kairos's review counts them), or a trend strategy has no exit that locks in gains. First experiments: a trailing stop sized to the stock's own wiggle, "trailing_stop_atr" 2.5 for swings and 3.5 for trends (LeBeau's chandelier exit is 3 × ATR); compare with a take profit at about 2–3 × the initial risk. Judge on money after costs, not the win rate: a trailing stop usually lowers the win rate a little while raising the average win.
