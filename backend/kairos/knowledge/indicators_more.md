# More indicators (the world's list)

## Smoothed and adaptive moving averages: SMMA, ZLEMA, ALMA, T3, McGinley, VIDYA, TRIMA
tags: smma zlema alma t3 mcginley vidya trima rma wilder zero lag arnaud legoux tillson adaptive moving average
SMMA (Wilder's smoothed average, also called RMA) is the slow, steady average inside RSI and ATR; it is what the Alligator uses. ZLEMA (zero-lag EMA, John Ehlers) adds the recent change back in to cancel most of an EMA's lag. ALMA (Arnaud Legoux) weights the window with a bell curve set towards the newest candles, so it is smooth yet quick. T3 (Tim Tillson) blends six EMAs into one very smooth line; its volume factor (0.7 by default) trades smoothness for speed. The McGinley Dynamic (John McGinley) speeds up in falls and slows in rises, hugging the price better than an EMA. VIDYA (Tushar Chande) is an EMA whose speed rises with momentum (the CMO). TRIMA, the triangular average, is an average of an average that weights the middle of the window most. Use: as trend filters and trailing references. Faster averages give earlier signals and more false ones; no average predicts, they only describe.

## Linear regression (LSMA), slope and R²
tags: linreg lsma linear regression slope r2 least squares trend quality regression channel
The least-squares line through the last N closes. Its end point is the LSMA (a fast moving average), its slope says how fast the trend climbs per candle, and R² (0 to 1) says how straight the trend is: above 0.7 is a clean trend, below 0.3 is noise. Traders use slope > 0 with high R² as a trend-quality filter, and the line plus or minus two standard errors as a regression channel.

## Moving-average envelope and disparity
tags: envelope disparity percentage band moving average distance stretch
An envelope is an SMA with bands a fixed percentage (often 2.5–5%) above and below. In ranges, closes outside the envelope tend to come back; in trends, price rides one band. The disparity index is the same idea as a number: the % distance from the average. Extreme disparity (for a large stock, more than about 10% from its 20-day average) usually means a stretched move that pauses.

## Williams Alligator and fractals
tags: alligator fractals bill williams jaw teeth lips chaos trading
Bill Williams' Alligator is three smoothed averages of the mid-price, drawn 8, 5 and 3 candles into the future (jaw, teeth, lips). Tangled lines mean the alligator is asleep (no trend, stay out); lines fanning apart in order mean it is feeding (a trend). Williams fractals mark a candle whose high (or low) is the extreme of five candles; Agora shows the latest confirmed fractal high and low, which act as breakout triggers and stop levels. A fractal is only known two candles after it happens.

## Heikin-Ashi candles
tags: heikin_ashi heikin ashi average bar smoothed candles trend colour
Heikin-Ashi ("average bar") candles use the average of open, high, low and close as the close, and the average of the previous Heikin-Ashi candle as the open. Trends show as long runs of one colour with no lower wicks (uptrend) or no upper wicks (downtrend); small bodies with wicks on both sides warn of a turn. The prices are not real traded prices, so Agora always fills orders at real prices.

## Momentum, ROC and the Chande momentum oscillator (CMO)
tags: momentum roc cmo chande rate of change oscillator
Momentum is today's price minus the price N candles ago; ROC is the same in percent. The Chande momentum oscillator compares the sum of up moves with the sum of down moves over N candles (−100 to +100; beyond ±50 is stretched). Momentum turning before price is an early warning; zero-line crosses mark trend changes. Cross-sectional momentum (buying the stocks that rose most over 6–12 months) is one of the best-documented effects in finance.

## TRIX, PPO and PVO
tags: trix ppo pvo percentage price oscillator percentage volume oscillator triple exponential
TRIX (Jack Hutson) is the 1-candle % change of a triple-smoothed EMA, with a signal line: momentum with most noise removed; crosses of zero and of the signal line are the signals. PPO is MACD in percent (fast EMA minus slow EMA, divided by the slow EMA), so it can compare a ₹100 stock with a ₹5,000 one. PVO is the same formula on volume: above zero means volume is expanding, which should accompany breakouts.

## Detrended price oscillator (DPO)
tags: dpo detrended price oscillator cycles
The DPO removes the trend to reveal cycles: Agora uses the causal form, the price half a window ago minus today's average. Peaks and troughs of the DPO show the typical cycle length, useful for timing entries in a range. It is not a trend tool.

## Know Sure Thing (KST) and the Coppock curve
tags: kst know sure thing pring coppock curve long term momentum
Martin Pring's KST adds four smoothed rates of change (10, 15, 20, 30 periods, weighted 1–4) into one momentum line with a signal line; crossings mark the start of major moves. Edwin Coppock designed his curve in 1962 for monthly index closes: a weighted average of the 14- and 11-month rates of change. A turn up from below zero has historically marked the start of bull markets in indices; on daily stock charts it is just a slow momentum filter.

## Ultimate oscillator
tags: ultimate oscillator larry williams buying pressure divergence
Larry Williams' ultimate oscillator averages buying pressure (close minus the true low) over 7, 14 and 28 candles, weighted 4:2:1, on a 0–100 scale. Williams' own buy rule: a bullish divergence with the oscillator below 30, then a break above the divergence high. Below 30 is oversold, above 70 overbought.

## Awesome and Accelerator oscillators
tags: awesome accelerator ao ac bill williams saucer twin peaks
The Awesome oscillator is the 5-period average of the mid-price minus the 34-period one, shown as a histogram; the Accelerator is the Awesome minus its own 5-period average, showing whether momentum is speeding up. Bill Williams' signals: zero-line crosses, "saucers" (three bars changing colour on one side of zero) and "twin peaks" (a divergence on one side of zero).

## True strength index (TSI) and stochastic momentum index (SMI)
tags: tsi true strength index smi stochastic momentum index blau double smoothed
William Blau's TSI double-smooths price changes and divides by double-smoothed absolute changes (−100 to +100), with a signal line; it is a smoother, less noisy momentum gauge. Blau's SMI is a stochastic centred on zero: where the close sits against the middle of the recent range, double smoothed; below −40 oversold, above +40 overbought.

## Relative vigor index (RVI) and balance of power (BOP), Qstick
tags: rvi relative vigor index bop balance of power qstick open close
These ask whether candles close above their opens. RVI (John Ehlers) divides smoothed (close − open) by smoothed (high − low); it rises in healthy uptrends because closes sit near highs. Balance of power (Igor Livshin) averages (close − open) / (high − low), from −1 (sellers in control) to +1. Qstick (Tushar Chande) is simply the average of close − open. All three are confirmation tools: use them with a trend filter.

## Fisher transform
tags: fisher transform ehlers turning points gaussian
John Ehlers' Fisher transform converts where the mid-price sits in its recent range into a roughly normal distribution, so extremes stand out as sharp peaks. Readings beyond ±2 are rare; a cross of its trigger line (yesterday's value) from such an extreme is an early reversal signal. It reacts fast and whipsaws in trends.

## Schaff trend cycle (STC)
tags: stc schaff trend cycle macd stochastic
Doug Schaff ran MACD through a double stochastic to make a cycle line from 0 to 100 that turns earlier than MACD. Common rules: buy when it crosses up through 25, sell when it crosses down through 75; it spends long stretches pinned at 0 or 100 in strong trends.

## Connors RSI
tags: connors_rsi connors rsi streak percent rank short term mean reversion
Larry Connors' composite: the average of a 3-day RSI of the close, a 2-day RSI of the up/down streak length, and the percentile rank of today's % change among the last 100 days. Readings under 10 (or 5) mark deep short-term oversold conditions; in stocks above their 200-day average such dips have historically bounced within days. It is a short-term tool; costs matter.

## Elder ray and the Elder impulse system
tags: elder_ray elder_impulse bull power bear power alexander elder triple screen
Alexander Elder's bull power is the high minus a 13-period EMA; bear power is the low minus it. In an uptrend (rising EMA), buy when bear power is negative but rising (a pullback losing force). The impulse system colours each candle: green when the EMA and the MACD histogram both rise, red when both fall, blue otherwise. Elder's rule: never buy on red, never short on green.

## WaveTrend
tags: wavetrend lazybear channel index oscillator tradingview
A popular TradingView oscillator (by LazyBear): the typical price's distance from its EMA, normalised like CCI and smoothed (WT1), with a 4-candle average (WT2). Crosses of the two lines below −60 are buy signals, above +60 sell signals. Like all oscillators it works best in ranges or for pullback timing.

## Vortex indicator and ADXR
tags: vortex vi adxr adx rating directional movement trend start
The vortex indicator (Botes and Siepman, 2010) compares upward movement (today's high minus yesterday's low) with downward movement over N candles, divided by the true range. VI+ crossing above VI− signals a new uptrend. ADXR (Welles Wilder) is the average of today's ADX and the ADX a window ago: a steadier trend-strength reading used to rank which markets trend most.

## Choppiness index
tags: chop choppiness index trending ranging regime filter dreiss
E.W. Dreiss's choppiness index compares the sum of true ranges with the overall range over N candles on a 0–100 scale. Above 61.8 the market is chopping sideways (trend systems lose money); below 38.2 it is trending. It says nothing about direction: use it to choose between trend-following and mean-reversion tools.

## Standard deviation, historical volatility and normalised ATR
tags: stdev hv natr standard deviation historical volatility atr percent volatility regime
Standard deviation measures how spread out prices were. Historical volatility is the annualised standard deviation of daily log returns, in %: around 15–25% is calm for a large Indian or US stock, 40%+ is wild. NATR is ATR as a percentage of the price, so you can compare a ₹200 stock with a ₹4,000 one. Volatility clusters: calm follows calm and storms follow storms, which is why position sizes should shrink when volatility rises.

## Ulcer index
tags: ulcer index peter martin drawdown pain risk
Peter Martin's ulcer index is the root-mean-square of percentage drawdowns from the recent high: it measures how deep and long the pain was, not how much the price moved. A stock rising steadily has a low ulcer index even if volatile on up days. Used for risk-adjusted ranking (the "ulcer performance index").

## Mass index
tags: mass_index mass index dorsey reversal bulge range expansion
Donald Dorsey's mass index sums the ratio of a 9-period EMA of the range to the EMA of that EMA over 25 candles. A "reversal bulge" (a rise above 27 followed by a fall below 26.5) warns that the trend may reverse, whichever way it was going.

## Chandelier exit
tags: chandelier exit le beau trailing stop atr
Chuck Le Beau's chandelier exit hangs a trailing stop a multiple of ATR (3× over 22 candles by default) below the highest high since entry (above the lowest low for shorts). It lets trends run while giving back only a volatility-sized chunk at the end. A close through it ends the trend trade.

## Squeeze (Bollinger inside Keltner)
tags: squeeze ttm john carter bollinger keltner volatility compression breakout
John Carter's squeeze: when the Bollinger Bands (20, 2 standard deviations) contract inside the Keltner Channel (20 EMA ± 1.5 ATR), volatility is unusually low and a big move often follows. The momentum line (a linear regression of price against its range middle) leans the way the breakout is likely to go. Agora's "squeeze breakout" setup fires when a squeeze ends with a close outside the bands.

## Z-score and Bollinger %B and bandwidth
tags: zscore bollinger_pct percent b bandwidth standard deviations stretch mean reversion
The z-score says how many standard deviations the price is from its average: beyond ±2 is a statistically unusual stretch, common in mean-reversion strategies. %B places the price between the Bollinger Bands (0 = lower band, 1 = upper band, above 1 = outside). Bandwidth is the band width as % of the middle; its lowest readings in six months mark squeezes (John Bollinger's "the squeeze").

## Relative volume (RVOL)
tags: rvol relative volume unusual volume breakout confirmation
Today's volume divided by the average of the previous 20 candles. 1 is normal, 2 is twice the usual trading, 5+ means news or a big player. Breakouts on RVOL ≥ 1.5 are more reliable; price moves on RVOL under 0.7 are suspect. Intraday traders compare volume with the same time of day on previous days.

## Accumulation/distribution line, Chaikin oscillator, price-volume trend
tags: ad_line chaikin_osc pvt accumulation distribution marc chaikin price volume trend
Marc Chaikin's A/D line adds each candle's volume weighted by where it closed in its range (+1 at the high, −1 at the low). Rising A/D with flat prices hints at quiet accumulation; falling A/D at highs warns of distribution. The Chaikin oscillator is the 3-minus-10 EMA of the A/D line (its momentum). PVT is like OBV but adds volume in proportion to the % price change.

## Force index and ease of movement
tags: force_index eom ease of movement richard arms elder volume
Elder's force index multiplies the price change by volume and smooths it: big moves on big volume are forceful. Richard Arms' ease of movement divides the mid-price change by volume per unit of range: high values mean prices rise easily on light volume (little resistance).

## Klinger volume oscillator
tags: klinger kvo volume oscillator stephen klinger
Stephen Klinger's oscillator compares fast and slow averages of volume signed by the direction of the typical price, with a signal line. It tries to spot long-term money flow while staying sensitive to short-term turns; divergences with price are the main signal. Agora uses TradingView's simplified form.

## Negative and positive volume index (NVI, PVI)
tags: nvi pvi negative volume index positive volume index fosback smart money
Norman Fosback's NVI changes only on days when volume falls (when, the theory says, informed investors act); PVI only on days volume rises (the crowd). Fosback's rule: NVI above its 255-day EMA has historically been a strong bull-market signal for indices.

## Pivot point variants: Fibonacci, Camarilla, Woodie
tags: pivots_fib pivots_camarilla pivots_woodie fibonacci camarilla woodie floor pivots intraday levels
All use the previous session's high, low and close. Fibonacci pivots space support and resistance at 38.2%, 61.8% and 100% of the previous range around the classic pivot. Camarilla pivots (Nick Stott, 1989) sit tightly around the previous close: intraday traders fade moves into R3/S3 and follow breaks of R4/S4. Woodie pivots give the previous close double weight. All pivots are self-fulfilling to a degree because many intraday traders watch them; they matter most in the first hours of a session.
