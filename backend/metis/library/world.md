# Sectors, the world and several timeframes: what research says

## Industry momentum and sector rotation
tags: industry momentum sector momentum moskowitz grinblatt rotation relative strength sector etf
Moskowitz and Grinblatt (1999) found that much of stock momentum is industry momentum: industries that did best over the last 6–12 months kept outperforming for months, and buying winning stocks inside losing industries worked much less well. Sector-rotation strategies (hold the strongest sectors by 6–12 month return, rebalance monthly) have worked across markets, with momentum's usual crashes when beaten-down sectors rebound. Breadth (the share of a sector's stocks above their averages) helps tell a broad advance from a narrow one.
**In Agora:** the sector readings (`backend/sectors/`: equal-weight sector lines, RS-ratio and RS-momentum, breadth, booms) and the sector watchlists; a strategy's stocks can be limited to a leading sector's list (a universe idea).

## Trend filters on a bigger timeframe
tags: multiple timeframe trend filter faber 10 month moving average weekly filter higher timeframe false signals whipsaw
Faber (2007) showed that holding an asset only while it is above its 10-month average cut drawdowns sharply across asset classes for a similar return. The same idea, applied to signals on a smaller chart, is the multiple-timeframe filter: only take daily buy signals while the weekly chart is in an uptrend. It removes trades against the bigger trend, which are the most likely to fail, at the cost of fewer trades and later entries. Test it like any filter: on the study years, judged on unseen years, with the luck check.
**In Agora:** conditions "on the weekly chart" or "on the monthly chart" in any rule (`chart` on an operand, D-97); the Kairos desk's bigger-chart check; Metis can propose a "bigger chart" filter.

## Event studies: measuring how news moves prices
tags: event study abnormal return mackinlay market model news reaction cumulative abnormal return
An event study (MacKinlay, 1997) measures what an event did by comparing prices after it with what they would have done anyway: the abnormal return is the return minus the market's (or a market model's) over a window (1, 5, 20 days), averaged over many similar events, with its uncertainty. Few events of a kind means a noisy average: treat a handful as a hint, not a law.
**In Agora:** the world desk measures each kind of world event this way on saved prices (the market's plain return; sectors and exposure groups minus the market) and blends the measurement with the map's prior, weight n/(n+3).

## Geopolitical risk and stock returns
tags: geopolitical risk index caldara iacoviello gpr war threats acts returns investment
Caldara and Iacoviello (2022) built a geopolitical risk index from newspaper articles about wars, terrorism and tensions. Higher geopolitical risk forecast lower investment and employment and a higher chance of large stock falls; *threats* weighed on markets more than *acts* (uncertainty hurts more than the event itself). The effect is largest for industries most exposed (defence up, travel and consumer down).
**In Agora:** the news risk gauge (D-68) and the world desk's events (D-95) are the live version; the investigator (D-96) explains specific moves.

## Oil prices and stock markets
tags: oil price shock stock returns importers exporters kilian park supply demand shocks
Kilian and Park (2009) showed that it matters *why* oil moves: oil rising on strong world demand comes with rising stocks; oil rising on a supply disruption (a war, an embargo) hurts stocks, most in oil-importing countries. So a war-driven spike is bad news for India's market and its oil users, while a demand-driven rise may come with a strong market.
**In Agora:** the world map separates supply shocks (wars, chokepoints, OPEC cuts) from demand stories (China stimulus, recession fears).
