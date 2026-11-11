# Active trading for a retail trader: partial exits, R multiples and setups that work

## Partial exits (scaling out, booking partial profit)
tags: partial exit scale out scaling out partial profit booking book profit half position thirds breakeven
Scaling out means selling part of a position at a first target and keeping the rest for a bigger move. The two common plans: sell **half at 1R** (once the trade has made as much as it risked) and move the stop to the entry price; or sell **a third at 1R, a third at 2R**, and let the last third ride a trailing stop or the exit rule. After the first partial the rest of the trade can no longer lose (bar a gap through the stop), which is why traders like it: it pays for the trade early and removes the fear that makes people exit winners too soon. **In Agora:** any visual strategy has "Partial exits" in its exits (up to three steps, in R, percent or ATR; "move the stop to the entry after the first"); Kairos's desks sell half at 1R by default (Settings → Kairos); "Improve with Kairos" and Metis try half-at-1R and thirds when a strategy's trades were ahead and gave it back. A position that scales out is still counted as **one trade** in the results.

## What partial exits really do to results
tags: partial exit win rate trade-off expectancy big winners scale out honest
Partial exits raise the **win rate** (trades that reached 1R and came back to the entry now end in profit instead of a loss) and make the equity curve smoother. They also trim the **biggest winners**, because half the position left at 1R. Whether total profit goes up depends on the strategy: they help mean-reversion and short swings whose moves fade, and often hurt pure trend-following, where a few huge winners pay for everything. So never assume; test it on unseen years, which is exactly what Metis and "Improve with Kairos" do before keeping one.

## R multiples: measure every trade in risk
tags: r multiple risk unit 1r 2r reward to risk stop distance measure trades
R is the distance from the entry to the stop-loss. A trade bought at ₹100 with a stop at ₹95 risks ₹5 a share: 1R = ₹5, so ₹105 is +1R and ₹110 is +2R. Professionals talk in R because it makes every trade comparable whatever the stock's price: "my system averages +0.3R a trade" means something; "I made ₹2,000" doesn't. Partial-exit targets and Kairos's target (2.5R by default) are written in R.

## High win rate is not the goal: expectancy is
tags: high win rate expectancy accuracy profitable strategy retail myth
A strategy that wins 90% of the time can still lose money if its few losses are huge (selling far out-of-the-money options is the classic case). The number that pays the bills is **expectancy**: win rate × average win − loss rate × average loss, after costs. Good high-win-rate designs keep the losses small too: short holding periods, a hard stop-loss, partial exits and a stop at breakeven after the first target. Ask for both: a win rate above about 55–60% **and** a profit factor above 1.3 after costs.

## Beating the Nifty: the minimum bar
tags: beat nifty benchmark index buy and hold alpha underperform point of strategy
If a strategy makes less than simply buying the Nifty 50 (or SPY in the US) and holding it, there is no reason to run it: the index costs almost nothing and needs no work. Every Agora backtest compares the strategy with the index over the same years, and Metis now keeps a new strategy only if it beat the index in the exam years it never saw. A strategy that trades one stock with 10% of the money will rarely beat the index on its own; combine strategies in a portfolio (the Portfolio screen) to put the whole amount to work.

## Realistic returns for a full-time retail trader
tags: realistic returns monthly income livelihood 20% a month expectations full time trader
Be honest about the numbers. ₹20,000 a month on ₹1,00,000 is 20% a month, about 790% a year compounded; no fund, prop desk or famous trader sustains that. The best hedge funds average roughly 20–30% a **year** in good decades; a skilled retail swing trader making 2–4% a month after costs, with losing months, is doing very well. SEBI's studies found about 7 in 10 individual intraday cash traders (FY23) and about 9 in 10 individual F&O traders (FY22–FY24) lost money. To earn ₹20,000 a month at a realistic 2–3% a month needs roughly ₹7–10 lakh of capital. Tell the user this plainly when they ask how much a strategy can earn, then work on the edge, the costs and the risk, which are what decide it.

## Pullback in a trend (buy the dip in an up-trend)
tags: pullback trend continuation buy the dip swing setup ema 20 rsi
The most reliable swing setup: the stock is in an up-trend (close above SMA 50 and SMA 200, or the weekly trend up) and pulls back for 2–5 days toward the 20-day EMA or to RSI(14) near 40–50 without breaking the last swing low. Buy when it turns back up (a close above the previous candle's high); stop below the pullback low; sell half at 1R, trail the rest. It works because institutions that missed the move buy the pullback. Avoid it when the market (Nifty) is below its 200-day average.

## RSI(2) dips in up-trends (Connors)
tags: rsi 2 connors mean reversion short term high win rate dip buying
Larry Connors' studies of the S&P 500: when a stock or index above its 200-day average closes with RSI(2) under 5–10, it tends to bounce within a few days. Win rates of 65–75% are typical in tests, with small average gains, so costs matter: use it on liquid stocks and indexes. Exit when the close is above the 5-day average, or after about 5 days; a stop-loss is optional in his tests but sensible for a retail account. It fails in bear markets, which is what the 200-day filter is for.

## Opening range breakout (intraday)
tags: opening range breakout orb intraday first 15 minutes nifty momentum day trading
Mark the high and low of the first 15 or 30 minutes. A break above the range on rising volume, with the stock and the Nifty above VWAP, is a long; a break below, a short (allowed intraday in India). Stop on the other side of the range or at VWAP; sell half at 1R; close everything by the square-off (Agora's intraday product does this). It works best on gap days and news days and badly on quiet, range-bound days, so filter for a wide first candle or high relative volume.

## VWAP pullbacks (intraday)
tags: vwap pullback intraday institutions average price day trading reclaim
VWAP is the day's volume-weighted average price, the benchmark institutions' execution desks are judged against. In a strong day, price that pulls back to VWAP and holds it often resumes the move because big buyers try to buy at or below VWAP. Long: above VWAP all morning, dips to it, closes back above; stop a little under VWAP; first target the morning high. Lose VWAP decisively and the day has likely turned.

## Breakouts from tight ranges (NR7, inside bars, flags)
tags: breakout nr7 narrow range inside bar volatility contraction flag minervini vcp
Volatility comes in waves: quiet, narrow candles (the narrowest range of 7 days, inside bars, tight flags after a strong move) are often followed by big moves. Buy a break above the tight range in an up-trend, stop below the range (a small R, so the reward-to-risk is high). Mark Minervini's "volatility contraction pattern" is the same idea on daily charts. False breakouts are common: ask for volume at least 1.5× average on the breakout and partial profit at 1–1.5R.

## 20-day breakouts (Turtle style) and why they need patience
tags: donchian breakout 20 day turtle trend following low win rate
Buying a new 20- or 55-day high and trailing a stop is the classic trend system. Win rates are low (30–40%), with a few large winners carrying the results, so partial exits tend to hurt it; trailing stops help it. Run it across many stocks and sectors, because any one stock trends only some of the time.

## Gap-and-go and gap fills
tags: gap up gap down gap fill gap and go opening gap intraday swing news
A gap on news with heavy volume that holds its first 15–30 minutes tends to continue (gap-and-go); a gap without news on light volume often fills back toward the previous close. Check the reason in Agora's news first, and never trade a gap on results day without a stop.

## What usually doesn't work for retail
tags: what doesn't work retail mistakes tips overtrading averaging down revenge
Averaging down on losers without a plan; trading on tips and social media; buying far out-of-the-money options every week; trading the first minutes of results or budget day without a stop; and too many small intraday trades where charges and slippage take the edge. Single indicators (an RSI cross, a MACD cross) on their own are close to coin flips; edges come from a trend or regime filter, a clear trigger, a defined stop and sensible exits together.
