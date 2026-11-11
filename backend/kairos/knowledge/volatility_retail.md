# Navigating market volatility as a retail trader

## India VIX and the volatility regime
tags: india vix vix volatility index fear regime calm wild market
India VIX measures the volatility the options market expects for the Nifty over the next month. Roughly: under 12 is calm (trends grind, breakouts are slow, option premiums cheap), 12–18 normal, 18–25 nervous (wider swings, more gaps), above 25 fear (2020's crash took it above 80). The US VIX works the same way for the S&P 500. Agora reads the regime from each stock's ATR and the index's trend; let it change how much you trade, not just what.

## Size by volatility, so risk stays the same
tags: volatility sizing atr position size wild market cut size risk constant
When a stock's ATR doubles, the same number of shares carries twice the risk. Sizing by risk (Agora's "risk-based" sizing: a fixed percent of equity between the entry and the stop) shrinks positions automatically in wild markets and grows them in calm ones. On days or weeks when VIX jumps, also cut the number of open trades: correlations rise in sell-offs, so five positions behave like one.

## Gaps and overnight risk
tags: gap risk overnight holding stop loss gap through slippage results news
A stop-loss can't protect against a gap: if a stock closes at ₹100 with a stop at ₹95 and opens at ₹88 on bad news, the stop fills near ₹88. Agora's backtests fill stops at the open on a gap for exactly this reason. Hold smaller positions overnight before known events (results, RBI and Fed decisions, the Union Budget, election results) or close them; intraday trading avoids overnight gaps but pays more in costs.

## Event days
tags: event day budget rbi policy fed fomc election results expiry day volatility
On scheduled events the first move is often wrong and spreads widen. Professional practice: no new positions in the hour before the announcement, let the first 15–30 minutes settle, then trade the direction that holds. Weekly expiry days in India add pinning near big option strikes and sharp moves in the last hour.

## Circuit limits and frozen stocks
tags: circuit limit upper circuit lower circuit price band frozen cannot sell nse
NSE stocks have daily price bands (2%, 5%, 10% or 20%); a stock locked at its lower circuit can't be sold until buyers appear, and the index has market-wide circuit breakers at 10%, 15% and 20%. Avoid small caps on tight bands for short-term trades, and never size a position you couldn't exit if it locked for a day or two. Agora fills nothing on a locked candle.

## Drawdown rules for someone trading for a living
tags: drawdown rules daily loss limit monthly loss limit livelihood full time stop trading
Professionals stop before losses compound: a daily loss limit (Agora's desk pauses after 3%), a monthly limit (for example stop new trades after a 6–8% month and review), and a cut in size by half after a drawdown of about 10% until results recover. A livelihood needs capital that survives the bad months, which every strategy has. Never add money to "win it back".

## Trading in a falling market
tags: bear market falling market downtrend short selling cash defensive sectors
When the Nifty is below its 200-day average and falling, most long setups fail more often. Options: trade less and keep cash (a position too); short intraday (allowed in India) or in the US; switch to defensive sectors (FMCG, pharma, IT when the rupee is weak) that institutions rotate into; and use the market filter (index above its average) on long strategies. Bear-market rallies are sharp and short, so take partial profits quickly.

## Sideways, choppy markets
tags: sideways choppy range bound whipsaw low adx mean reversion
In a range (ADX under about 20, prices crossing their averages often), trend and breakout strategies get whipsawed; mean-reversion setups (RSI(2), Bollinger-band dips, range support) and quick partial exits work better. Agora's regime check and Kairos's brain decide which kind of strategy fits the current market.

## Volatility clustering
tags: volatility clustering garch calm follows calm wild follows wild
Big moves follow big moves and quiet follows quiet; volatility is far more predictable than direction. After a sudden spike, expect a few more wide days before it settles; after weeks of calm, expect an eventual break. Breakout strategies like the end of calm periods; dip-buying works best once a spike starts to fade.
