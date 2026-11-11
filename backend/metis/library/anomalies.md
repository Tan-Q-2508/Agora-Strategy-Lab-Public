# Documented anomalies and factors

## Cross-sectional momentum
tags: momentum cross-sectional winners losers jegadeesh titman relative strength
Jegadeesh and Titman (1993) found that US stocks with the best returns over the past 3–12 months kept outperforming the worst over the next 3–12 months, by about 1% a month before costs. It has been found in most stock markets since, including India. Usually measured over 12 months skipping the latest month (which tends to reverse). It suffers rare, violent crashes when beaten-down markets rebound (Daniel and Moskowitz, 2016).
**In Agora:** a cross-sectional ranking of the Nifty 50 is planned (Phase 16.5); per-stock, "close above its 12-month average" or ROC filters capture part of it.

## Time-series momentum and trend following
tags: time series momentum trend following moskowitz ooi pedersen century
Moskowitz, Ooi and Pedersen (2012) showed that an asset's own past 12-month return predicts its next month's return across dozens of futures markets; the effect fades after about a year. Hurst, Ooi and Pedersen (2017) found trend following profitable in every decade they studied back to 1880, with its best results in crises. Trend rules lose in choppy, range-bound markets through repeated small whipsaws.
**In Agora:** moving-average crossovers, Donchian/Turtle breakouts, Supertrend and ADX trend templates; a 200-day average filter is the simplest version.

## Nearness to the 52-week high
tags: 52-week high momentum anchoring george hwang
George and Hwang (2004) found that stocks trading close to their 52-week high outperform those far from it, and that this explains much of momentum. The usual explanation is anchoring: traders are reluctant to bid a stock above its high, so good news is absorbed slowly.
**In Agora:** the 52-week-high momentum template and the "new 52-week high" setup.

## Short-term reversal
tags: short-term reversal mean reversion one week one month liquidity
Stocks that fell most over the past week or month tend to bounce, and the biggest gainers to give back (Jegadeesh, 1990; Lehmann, 1990). Much of it is a reward for providing liquidity to hurried sellers, so it is strongest in less liquid stocks and is eaten quickly by costs.
**In Agora:** RSI(2), Bollinger and Williams %R reversion templates; mind the break-even win rate after costs.

## Long-term reversal
tags: long-term reversal overreaction de bondt thaler losers
De Bondt and Thaler (1985) found that the worst performers over three to five years outperformed the best over the following three to five years, which they attributed to overreaction. It is slow and largely overlaps with value.

## Low volatility and betting against beta
tags: low volatility anomaly betting against beta frazzini pedersen ang
Low-risk stocks have earned about as much as, or more than, high-risk ones, against theory: Ang, Hodrick, Xing and Zhang (2006) for idiosyncratic volatility, Baker, Bradley and Wurgler (2011) for benchmarking limits, Frazzini and Pedersen (2014) for low-beta stocks (leverage constraints push investors into risky ones). It shows up in most markets.
**In Agora:** the portfolio's risk weighting gives steadier sleeves more money; a low-volatility ranking is Phase 16.5.

## Value and size
tags: value size fama french book to market small cap factor
Fama and French (1992, 1993) found cheap stocks (high book-to-market) and small stocks earned more than expensive and large ones; their five-factor model (2015) added profitability and investment. Value has had long dry spells (the 2010s) and needs accounting data.
**In Agora:** no fundamentals data yet (LATER); price-only proxies like long-term reversal overlap with it.

## Quality and profitability
tags: quality profitability novy-marx gross profitability junk
Novy-Marx (2013) showed gross profitability predicts returns about as well as value, and works well combined with it. Asness, Frazzini and Pedersen ("Quality minus Junk") found safe, profitable, growing, well-run firms earn higher risk-adjusted returns. Needs fundamentals.

## Post-earnings announcement drift
tags: earnings drift pead announcement surprise under-reaction
After a positive earnings surprise prices keep drifting up for weeks, and after a negative one down (Ball and Brown, 1968; Bernard and Thomas, 1989): investors under-react to news. Needs an earnings calendar; gaps on results days are a price-only trace of it.
**In Agora:** the breakaway-gap setup catches some results-day moves.

## Calendar effects
tags: seasonality turn of the month halloween january calendar
The turn of the month (the last trading day and the first few of the next) has historically carried a large share of stock returns (Ariel, 1987; Lakonishok and Smidt, 1988). "Sell in May" (Bouman and Jacobsen, 2002) found weaker May–October returns in many markets. Calendar effects are small, easy to data-mine, and have weakened since publication.

## Overnight versus intraday returns
tags: overnight returns intraday returns night day tug of war
In US stocks most of the long-run return has come overnight (close to next open) rather than during the session (Cliff, Cooper and Gulen, 2008). Lou, Polk and Skouras (2019) found momentum profits accrue overnight while many other anomalies earn intraday. It matters for intraday strategies, which never hold overnight.

## Momentum crashes
tags: momentum crash rebound panic daniel moskowitz tail risk
Momentum strategies have suffered sudden, severe losses when markets rebound sharply after a crash (1932, 2009): the losers they are short, or underweight, jump the most. Daniel and Moskowitz (2016) showed scaling momentum down when volatility is high avoids much of it.
**In Agora:** volatility filters and the portfolio's volatility targeting are the defence.

## Anomalies decay after publication
tags: decay publication alpha decay mclean pontiff crowding
McLean and Pontiff (2016) studied 97 published anomalies: returns were about 26% lower out of sample and about 58% lower after publication, as traders arbitraged them. Expect a documented edge to be smaller than in its paper, and smaller still after costs.

## Evidence from India
tags: india nifty nse momentum low volatility evidence emerging market
Studies of Indian stocks have found momentum and low-volatility effects similar to other markets, with higher costs and more frequent sharp reversals around policy and global shocks. Delivery trades pay securities transaction tax on both sides, so short-term reversal edges must be large to survive. Survivorship in the Nifty 50 list is a real concern for older backtests.
