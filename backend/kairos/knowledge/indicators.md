# Indicators

## Moving averages: SMA, EMA, WMA, DEMA, TEMA, HMA, VWMA, KAMA
tags: sma ema wma dema tema hma vwma kama moving average ma trend smoothing lag crossover golden death cross
A moving average smooths price to show direction. The simple average (SMA) weights every candle equally; the exponential (EMA) and weighted (WMA) averages favour recent candles and turn sooner. DEMA, TEMA and the Hull average (HMA) remove most of the lag, at the cost of more false turns. VWMA weights candles by volume, so heavy-volume days count more. KAMA speeds up in clean trends and slows down in chop.
How traders use them: price above a rising 200-day average is a long-term uptrend; the 50-day average crossing above the 200-day is the "golden cross" (below: "death cross"). A fast average crossing a slow one is the classic trend-following signal. In sideways markets crossovers whipsaw, so pair them with a trend-strength filter such as ADX above 20–25.

## RSI (relative strength index)
tags: rsi momentum overbought oversold 70 30 divergence wilder
RSI compares recent gains with recent losses on a 0–100 scale (14 candles by default, Wilder smoothing). Above 70 is "overbought", below 30 "oversold", but in strong trends RSI can stay above 70 or below 30 for weeks, so these are not sell or buy signals on their own. Useful readings: RSI holding 40–50 on pullbacks in an uptrend (bull range) or failing at 50–60 in a downtrend (bear range); divergences, where price makes a new extreme but RSI doesn't; and mean-reversion entries (RSI under 30) only when the longer trend is up.

## MACD
tags: macd signal line histogram momentum crossover 12 26 9
MACD is the 12-period EMA minus the 26-period EMA; its 9-period EMA is the signal line and the gap between them is the histogram. MACD crossing above its signal line suggests momentum turning up; the histogram shrinking warns that momentum is fading before price turns. MACD above zero means the short-term average is above the long-term one (an uptrend). Divergences between MACD and price are a common warning.

## Bollinger Bands and Keltner Channels
tags: bollinger bands keltner channel volatility squeeze standard deviation atr mean reversion breakout
Bollinger Bands are a 20-period SMA with bands two standard deviations above and below; Keltner Channels use an EMA with bands a multiple of ATR. Bands widen when volatility rises and narrow when it falls. A "squeeze" (very narrow bands) often comes before a big move but does not say which way. In ranges, touches of the outer band tend to revert to the middle; in strong trends price can "walk the band" for a long time.

## ATR (average true range)
tags: atr volatility stop loss position sizing true range
ATR measures how far price typically moves per candle, including gaps. It has no direction. Its main uses are stop placement (for example 2–3 × ATR from entry so normal noise doesn't stop you out) and position sizing (risk a fixed amount of money per trade: shares = money at risk ÷ (ATR multiple × ATR)). Kairos expresses its pattern tolerances and stops in ATRs so they work for any price level and timeframe.

## ADX and the directional lines
tags: adx dmi +di -di trend strength directional
ADX measures trend strength from 0 to 100, regardless of direction: under 20 means no real trend (range-trading tools work better), above 25 a trend worth following, above 40 a very strong one. +DI above −DI means buyers dominate; the reverse means sellers do.

## Stochastic, Stochastic RSI, Williams %R
tags: stochastic stoch rsi williams %r oscillator overbought oversold stoch_rsi williams_r
These oscillators show where the close sits within the recent high–low range. Stochastic and Stochastic RSI run 0–100 (above 80 overbought, below 20 oversold); Williams %R runs 0 to −100. They are fast and noisy, best used for timing entries in the direction of the larger trend, for example buying when the stochastic turns up from below 20 while the price is above its 200-day average.

## Volume tools: OBV, MFI, CMF, VWAP, relative volume
tags: volume obv mfi cmf vwap relative volume accumulation distribution money flow
Volume confirms price. On-balance volume adds volume on up candles and subtracts it on down candles; OBV rising while price falls hints at quiet accumulation. MFI is a volume-weighted RSI. Chaikin money flow above +0.1 shows buying pressure, below −0.1 selling pressure. VWAP is the day's volume-weighted average price: intraday traders treat price above VWAP as buyers in control. Relative volume compares today's volume with its recent average; breakouts on 1.5× volume or more are more trustworthy than quiet ones.

## Ichimoku, Parabolic SAR, Supertrend, Aroon
tags: ichimoku cloud tenkan kijun parabolic sar supertrend aroon trend following psar
Ichimoku's cloud (spans A and B) marks support and resistance; price above a rising cloud is bullish. The conversion line crossing the base line is its fast signal. Parabolic SAR and Supertrend trail the price and flip sides when the trend turns, which makes them natural trailing stops. Aroon shows how recently the highest high and lowest low happened: Aroon up near 100 with Aroon down near 0 marks a fresh uptrend.

## Donchian channels, 52-week highs, pivot points, opening range
tags: donchian breakout 52 week high pivot points opening range turtle levels highest lowest high_52w low_52w prev_day previous day opening_range pivots
The Donchian channel is the highest high and lowest low of the last N candles: a close above it is the classic breakout entry (the "turtle" rule). Stocks near their 52-week high tend to keep outperforming (momentum), contrary to intuition. Floor pivots (P, R1–R3, S1–S3) come from the previous session's high, low and close and act as intraday reference levels. The opening-range breakout trades a move beyond the first 15–30 minutes' range.

## CCI (commodity channel index)
tags: cci commodity channel index donald lambert cycles overbought oversold
Donald Lambert's CCI (1980) measures how far the typical price is from its 20-candle average, scaled by the average deviation, so about 70–80% of readings fall between −100 and +100. Above +100 is unusual strength (trend traders buy it; swing traders see it as stretched), below −100 unusual weakness. A climb back above −100 after a dip below it is a common swing-low entry; divergences with price warn of turns.
