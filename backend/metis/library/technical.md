# Technical strategies, researched

## What the research says about technical rules
tags: technical analysis evidence brock lakonishok lebaron data snooping
Brock, Lakonishok and LeBaron (1992) found simple moving-average and range-breakout rules had predictive power on the Dow from 1897 to 1986. Sullivan, Timmermann and White (1999) re-tested thousands of rules with a bootstrap that allows for data snooping: the best rules' edge largely vanished in later years. Park and Irwin's survey (2007) found most studies positive but many with snooping, selection or cost problems. Lo, Mamaysky and Wang (2000) found some chart patterns carry modest information. Conclusion: simple, robust rules with a reason, judged after costs on unseen data.

## The trend filter
tags: trend filter 200-day moving average regime faber timing
The best-known filter in quant trading: only buy when the price is above a long average (often 200 days or 10 months; Faber, 2007, showed it cut drawdowns across asset classes). For dip-buying strategies it keeps you from catching falling knives; for breakouts it keeps you on the side of the main trend.
**In Agora:** a price condition, "close above SMA (200)": `{"indicator": "sma", "params": {"period": 200}, "op": "below", "price": "close"}`.

## Mean reversion inside a trend
tags: mean reversion pullback connors rsi2 dip buying trend
Connors and Alvarez popularised buying short, sharp pullbacks (RSI(2) under 10, or closes below the lower Bollinger band) only in stocks above their 200-day average, and selling on the first strong close. Holding periods are days, win rates high, average wins small: costs and slippage decide whether it works.
**In Agora:** the Connors RSI(2) template; try a trend filter on reversion strategies whose losers cluster in down-trends.

## Breakouts and false breakouts
tags: breakout donchian turtle false breakout channel range
Channel breakouts (Donchian; the Turtles' 20/55-day rules) catch the start of trends but most breakouts fail; the edge comes from a few large winners, so win rates of 35–45% are normal and the exits (wide trailing stops) matter most. Volume confirmation and a volatility squeeze before the break improve the odds in many studies.
**In Agora:** Donchian, Turtle, Keltner and squeeze templates; relative volume as a filter.

## Trend strength filters
tags: adx trend strength choppiness filter ranging trending
ADX above about 20–25 says a trend is strong enough for trend rules; below 20 favours range trading. The choppiness index works the other way round. Use them to switch off a strategy in the wrong kind of market, not as entries.
**In Agora:** `adx` at least 20 for trend strategies; `chop` at least 50 or ADX at most 20 for reversion strategies.

## Volatility filters
tags: volatility filter atr percent natr high volatility low volatility
Mean-reversion entries in very high volatility are often the start of a crash, and breakouts in very low volatility often go nowhere. ATR as a percent of price (NATR) or the Bollinger bandwidth measure it. When Kairos's review shows losers cluster at one end of volatility, a filter on that side is the natural test.
**In Agora:** `natr` (ATR % of price) at most / at least a value from the review's thirds.

## Volume confirmation
tags: volume confirmation relative volume rvol breakout participation
Moves on heavy volume (relative volume above about 1.5) are more likely to continue; breakouts on thin volume fail more often. On the Nifty 50, results days and index events distort volume, so use relative volume against the stock's own average.
**In Agora:** relative volume and MFI/CMF indicators; Kairos's review reports volume conditions of losing trades.

## Exits matter more than entries
tags: exits stop loss trailing stop time exit target profit
Many studies find random entries with good exits beat good entries with poor exits. A time exit caps how long a stale idea ties up money; an ATR trailing stop lets winners run while adapting to volatility; a fixed target suits mean reversion (the reversion has a natural end) more than trend following.
**In Agora:** Metis's tweaks may change stop loss %, take profit %, trailing stop % or ATRs ("trailing_stop_atr") and the time limit.

## When stop-losses help
tags: stop loss research kaminski lo momentum random walk
Kaminski and Lo (2014) showed that if prices follow a random walk, stop-losses reduce expected return (they sell at a loss and miss rebounds); when returns trend (positive autocorrelation) stops can add value, and in mean-reverting markets they tend to hurt. So the right stop depends on the stock's character, not on habit.
**In Agora:** check the variance ratio and Hurst exponent of the stocks before widening or tightening stops.

## Win rate versus payoff
tags: win rate payoff ratio average win average loss break even expectancy
A strategy's break-even win rate is average loss ÷ (average win + average loss). A 40% win rate is fine if winners are twice the losers (break-even 33%); a 65% win rate loses if losers are twice the winners (break-even 67%). Improving payoff (letting winners run, cutting losers) is often easier than raising the win rate.
**In Agora:** the expert's first look compares the actual and break-even win rates in the study years.

## Holding period and costs
tags: holding period turnover costs frequency short-term
Shorter holding periods mean more trades, more costs and more sensitivity to fills. A strategy whose average trade earns less than about three times its round-trip cost is fragile: a little extra slippage erases it. Lengthening the time exit or requiring stronger signals often helps more than any new indicator.
**In Agora:** charges are in every trade's net result; the review shows costs as a share of gross profit.

## Multi-timeframe confirmation
tags: multiple timeframe higher timeframe confirmation triple screen elder
Elder's triple screen trades in the direction of the longer timeframe's trend and times entries on the shorter one. On daily candles the same idea is a long average (weekly trend) plus a short oscillator (daily timing).
**In Agora:** the triple screen template; trend filters on long averages emulate the higher timeframe.

## Regime filters
tags: regime filter market regime trend volatility matrix switching
Many strategies only work in one regime: trend in strong trends, reversion in calm ranges. A two-by-two of trend (up/down) and volatility (high/low) is a simple regime map; strategies can be switched off in their bad cells. Fit the boundaries on the study years and test on the exam years, or the filter only memorises history.
