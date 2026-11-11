# Risk, drawdowns and survival

## The arithmetic of drawdowns
tags: drawdown recovery arithmetic loss gain needed
A 10% loss needs an 11% gain to recover; 25% needs 33%; 50% needs 100%. Deep drawdowns also last long and make people abandon strategies at the bottom. Judge strategies by return per unit of drawdown (Calmar, MAR), not by return alone.

## Value at risk and expected shortfall
tags: value at risk var expected shortfall cvar tail loss
Value at risk is the loss exceeded on only, say, 5% of days; expected shortfall (CVaR) is the average loss on those worst days, which captures how bad the tail is. Historical estimates from calm periods understate both; use the worst periods in the data as stress tests.

## Risk of ruin
tags: risk of ruin bankruptcy betting too much
Betting too large a fraction on each trade guarantees eventual ruin even with an edge, because a losing streak arrives sooner or later. With a 55% win rate and equal payoffs, ten losses in a row happen about once in every few hundred trades. Size so the worst plausible streak (the 95th percentile of shuffled trades) is survivable.
**In Agora:** `trade_order` reports the 95th-percentile losing streak and drawdown.

## Fat tails
tags: fat tails kurtosis black swan extreme moves normal distribution
Daily stock returns have far more extreme days than a normal distribution allows (kurtosis well above 3). Models that assume normality understate crash risk; the probabilistic Sharpe ratio corrects for skew and kurtosis, which is one reason Agora uses it.

## Gaps and stops
tags: gap risk stop loss overnight slippage gap down
A stop-loss is not a guaranteed price: if a stock opens below the stop after bad news, the fill is at the open, possibly far below. Overnight and weekend positions carry gap risk; results days and policy announcements carry the most.
**In Agora:** stops fill at the worse of the stop and the open.

## Concentration
tags: concentration position limits sector exposure overlap
Limit any single stock's share of the portfolio and watch for several strategies piling into the same stock at once; in a crisis they become one bet.
**In Agora:** the portfolio caps each sleeve and reports stocks shared by several sleeves.

## The kill switch
tags: kill switch strategy failure live drawdown retire decommission
Professional desks retire a strategy when its live loss exceeds a multiple (often about 1.5–2×) of its worst backtest drawdown, or when its live results fall statistically below the backtest. Hoping it comes back is how small losses become large ones.
**In Agora:** the paper portfolio winds a sleeve down when its live loss passes twice its backtest's worst drop.

## Liquidity risk
tags: liquidity risk volume spread thin trading impact
Thin stocks have wider spreads and bigger price impact, and liquidity disappears exactly when everyone wants out. Prefer liquid stocks (the Nifty 50 and large US names are), and keep orders small relative to volume.
