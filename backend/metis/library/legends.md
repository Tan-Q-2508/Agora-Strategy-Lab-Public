# The great traders' rules as ideas Metis can test

Each section turns one famous trader's or investor's method into rules that Agora can test on
daily prices, with what Agora's own results (agora_evidence) say to expect. A legend's name is not
evidence: every idea still has to pass the exam years, the index bar and the luck check.
First test (5 Nov, round 2504): all six entry rules below failed as new strategies on the
fixed 30-stock lists; see agora_evidence, "The great traders' entry rules, tested as written,
failed here". Prefer their exits and stay-invested habits.

## Tudor Jones and Schwartz: only own what is above its trend line
tags: paul tudor jones 200 day moving average marty schwartz 10 day ema trend filter regime stand aside legends
Rule forms: hold a stock only while it closes above its 200-day average (Tudor Jones), or enter
only above a rising 10-day exponential average (Schwartz). On the index's own chart the same rule
is a regime switch: no new longs while the Nifty 50 or S&P 500 is below its 200-day average.
Agora's evidence: in India's falling sealed year every long-only rule lost; a market-level
200-day switch is the obvious answer to test. On a single stock it cut big winners of trend
strategies (filters section), so apply it to the index, not the stock, first.
**In Agora:** a regime condition on the index's chart, or `regime_map`, for strategies that
already work in rising years.

## O'Neil, Minervini, Kullamägi: strongest stocks breaking out of tight ranges
tags: relative strength momentum leaders breakout tight range volatility contraction 52 week high minervini oneil kullamagi legends
Rule forms: universe = the top 20–30 stocks by 3- and 6-month return, within 15% of their
52-week high, above a rising 50- and 200-day average; entry = a close above a 10–20 day range
whose width (high minus low, as a share of price) is the narrowest in 3–6 months, on volume at
least 1.5 × its 50-day average; stop = the range's low or 7–8% below entry; exit = a close below
the 20-day average, or a partial exit after 3–5 days and a 10- or 20-day trail for the rest.
Agora's evidence: the 52-week-high breakout held until the trend ends passed in India; momentum
ranking passed the US sealed year. Expect a win rate near 35–45% and profit from a few trades.
**In Agora:** keep exits wide; don't add more filters once a few winners pay for everything.

## Turtles and Seykota: plain breakouts, volatility sizing, add to winners
tags: turtles donchian breakout seykota trend following atr sizing pyramiding add to winners legends
Rule forms: buy a close above the 55-day high, stop 2 × ATR(20) below, exit on a 20-day low;
size each trade so 2 ATR equals 1% of equity. Pyramiding (adding a unit every 0.5 ATR in your
favour) is the Turtles' big-win engine but Agora's engine opens one position per stock, so test
the plain form. Agora's evidence: Donchian passed the US sealed year; in India these rules match
but rarely beat holding the stocks, because they sit in cash between trends.

## Raschke: the first pullback in a strong trend, and failed breakouts
tags: linda raschke holy grail adx pullback 20 day average turtle soup failed breakout legends
Holy Grail: when ADX(14) is above 30 and rising, buy the first touch of the 20-day exponential
average, then above that day's high; stop below the pullback low; exit at the recent swing high
or on a trail. Turtle Soup: when a stock makes a new 20-day low that is at least 4 days after the
previous 20-day low, buy when it closes back above the old low; stop under the new low; exit
within 2–5 days. Both are short swings: check costs. Agora's evidence: dips in rising, jumpy
markets paid; dips in calm sideways markets lost.

## Templeton and Buffett: buy strength after a market-wide washout
tags: templeton maximum pessimism buffett greedy when others fearful washout india vix crash buying quality legends
Rule form: when the index has fallen at least 10–15% from its 52-week high and India VIX (or
VIX) is in its top fifth of the past year, buy the stocks of the low-volatility or quality list
that are holding up best (nearest their own 52-week high); hold for months with a wide trailing
stop (3–4 ATR) or until the index regains its 200-day average. Few trades, so the luck check
needs many years: use the longest history available and both markets.

## Lynch and Jhunjhunwala: hold the big winners
tags: peter lynch ten bagger jhunjhunwala titan hold winners trailing stop long holding let winners run legends
The test is on exits, not entries: take a strategy that already works and compare a fixed target
or a short time limit against a 3–4 ATR trailing stop or a close below the 50-day average.
Agora's evidence: India's passing daily rules were the ones invested for months, and every filter
that cut the big winners cut profit. Expect a lower win rate and a higher average win.

## Druckenmiller and Marks: get small when the backdrop turns
tags: druckenmiller marks cycle liquidity risk off cut size drawdown regime news risk legends
Rule forms at the portfolio level: halve new position sizes, or take no new entries, while the
index is below its 50-day average and falling, or while Kairos's news risk gauge is high; resume
at full size when the index regains it. This is a change to a working strategy's risk, judged on
drawdown as much as return.

## Simons and Thorp: many weak edges, honestly counted
tags: simons renaissance thorp kelly many small edges luck check deflated sharpe out of sample legends
The lesson for Metis's own process: an idea that is barely better than a coin can be valuable
only if it survives costs, out-of-sample years and the luck check for every variant tried, and
only sized well below its apparent edge. Rewordings of the same rule count as tries. A
legend-inspired idea gets no exemption from this.
