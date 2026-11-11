# What Agora's own tests on the user's data showed (November 2026)

Measured in laptop sessions by Claude on the user's saved prices (sprint 2026-11, Kairos's trade
judge, and Claude's idea batches through Metis's tests, D-143 to D-163). These are results on
this data, not universal laws: re-test before relying on them, and expect them to drift.

## In a strong rising market, holding the stocks is the bar to beat
tags: buy and hold benchmark index bar exam years cash drag trend india us bull market
In sprint 2026-11 nearly every Indian daily rule failed one check only: its exam Sharpe ratio
(0.9–1.2) was below simply holding the same 30 large stocks (1.49), because India's large
stocks rose strongly in those years and a rule that sits in cash part of the time lags. In the
US the bar was 1.19 and many rules cleared it. The rules that passed in India were the ones that
stay invested for months: plain crossovers, Supertrend, the slowed MACD, the 52-week-high
breakout held until the trend ends.
**In Agora:** for a daily strategy, ask "how much of the time is it invested, and does it beat
holding its own stocks?" before tuning its entry. Fewer, longer trades usually win.

## The last year was different: India fell, the US rose
tags: regime vault india down nifty fell us rose trend following failed regime change
In the year sealed from the sprint (Nov 2025 to Nov 2026) the Nifty 50 fell 8.4% and every
Indian finalist lost money, while the S&P 500 rose 11.4% and 15 US daily finalists made money;
eight of them beat its Sharpe ratio (six-month momentum ranking, Supertrend, Ichimoku, Connors
RSI dips, RSI(2) dips, ROC momentum, Donchian, accumulation breakout). Long-only trend rules
can't make money when the whole market falls.
**In Agora:** an Indian long-only idea needs a reason to stand aside in a falling market: a trend
filter on the index's own chart or a regime condition (`regime_map`), or cash below the 200-day
average. The brief's "Today's market" line says what regime each index is in now.

## Intraday rules lose to costs on this data
tags: intraday 5 minute 15 minute hourly costs stt slippage scalping lose after costs india
Every 5- and 15-minute family in the sprint (opening-range breakout, VWAP reclaim, intraday RSI
dips) and every Indian hourly family lost money after costs. Kairos's own entries agreed: on
unseen past trades after costs, India's 1-hour entries lost 0.15R a trade, 15-minute 0.24R,
5-minute 0.43R, 1-minute 1.23R; US 5-minute 0.14R and 1-minute 0.28R; and once its stocks were
refreshed (5 Nov), US 15-minute lost 0.16–0.24R, after its desk had lost about 10%. Only the US hourly
breakout looked good before the vault, and it lost in the vault year.
**In Agora:** propose intraday ideas only with a clear reason costs won't eat them (a large
average move per trade, few trades a day, liquid stocks); prefer daily candles for new ideas.

## Dips pay in rising regimes and lose in calm sideways ones
tags: mean reversion dip buying rsi2 connors bollinger regime sideways calm uptrend volatile
Buying short dips inside an uptrend (RSI(2), Connors RSI, Bollinger, z-score) made money in both
markets before costs, most in jumpy uptrends (about +1% a trade in India) and nothing or a loss
in calm sideways markets (India −0.18% a trade). In the US, RSI(2) and Connors RSI dips also
passed the sealed year. In India they never beat holding the stocks.
**In Agora:** a dip-buying idea should name its regime: a volatility condition (NATR at least
2–3%), a stacked trend, or the index above its 200-day average.

## Filters cut the big winners of trend strategies
tags: filter trend following big winners fewer trades weekly trend 200 day volume confirmation
Claude tested trend, weekly-chart, volume and stop filters on the user's live strategies (#1, #4,
#9, #12). Every one made less money per trade in the exam years, not just fewer trades: on #1 a
weekly-trend filter cut trades from 29 to 21 but profit from ₹2.13 lakh to ₹33,426. These
strategies earn from a few large winners, and filters removed some of them.
**In Agora:** before filtering a trend strategy, look at where its profit comes from (average
win against average loss). If a few big winners pay for everything, change its exits or its
stocks instead, or leave it.

## Write one idea once: rewordings count against the luck check
tags: luck check deflated sharpe duplicates rewording same rule effective trials
Of about 1,400 new strategies Metis tried on US stocks, their exam returns held only about 160
independent patterns; in India one ADX trend rule was rewritten 13 times with identical returns.
The luck check now counts independent patterns, but each copy still costs a slot in a round.
**In Agora:** vary the mechanism (what makes money and why), not the wording. A strategy that is
a filter on an existing one is a "filter" idea, not a new strategy.

## Liquidity: tiny stocks lose and go missing
tags: liquidity small cap value traded missing data universe stocks desk picks
Stocks trading under about ₹20 crore (or $20 million) a day kept failing to return prices and
cost more to trade than any edge earns; Kairos's picks now require that on both a 20- and a
120-day median (D-155). The sprint ranked stocks by value traded for the same reason.
**In Agora:** a universe idea should add liquid stocks, never thin ones.

## Gaps go through stops
tags: gap stop loss overnight earnings biotech risk position size gap risk
A US 15-minute desk held a biotech stock that fell 38% overnight on news; the stop could only
fill at the next open, and one trade cost the desk about 7.5%. Stops limit losses only when the
price moves continuously.
**In Agora:** size by risk and keep stocks with frequent overnight jumps (small biotech, results
day) small, or avoid holding them overnight on short-term strategies.

## The user's live strategies are near their best: 32 changes, none kept
tags: live strategies exits partial profit target time limit stop tweak no improvement local optimum
Claude tried 32 changes on the user's strategies #1, #4, #9, #11, #12 and #13 (trend, weekly,
volume and 200-day filters; ATR trailing stops; fixed stops; partial exits at 1R; a 15% target;
time limits of 15 to 60 candles). None made more money in the exam years than the current
version; most made much less, because they cut trades that become the big winners. For these
strategies the cheap changes are exhausted.
**In Agora:** don't propose another stop, target, time limit or simple trend filter for these
strategies; the remaining questions are which stocks they trade (a universe idea with liquid
stocks) and whether they suit today's regime at all.

## When more stocks make a strategy worse, its edge is in its stocks, not its rule
tags: universe concentration few stocks adanient bse stock selection luck generalise diversification
The user's India strategies #1, #11 and #12 trade 2 to 6 stocks, all including ADANIENT and two
of them BSE, among the most volatile large stocks of recent years. Adding the most traded large
caps (HDFC Bank, ICICI Bank, Reliance, Infosys, TCS, SBI) made every one of them earn less in
the exam years; the same happened for the US squeeze breakout (#4) with Microsoft, Alphabet and
AMD. A rule that only pays on a few hand-picked volatile stocks is mostly a bet on those stocks:
it can stop working when they calm down.
**In Agora:** judge a strategy on at least 10 liquid stocks; a new strategy that only works on
two or three names should be called what it is, a bet on those names, and kept small.

## Rankings: calm US stocks held up; momentum's neighbours confirm it
tags: ranking momentum low volatility calm stocks monthly cross sectional factor us india 6 months 12 months
Claude's ranking batch on the 30 most traded stocks: US "Monthly calmest stocks (six months)"
held up (exam: 49 trades, 63% won) and was saved as #22, the low-volatility anomaly with a
200-day trend filter. US momentum over 3, 9 and 12 months were judged versions of the six-month
momentum ranking already kept (#21) and didn't beat it, which is what a real effect looks like:
neighbouring windows behave alike. In India, 12-month momentum skipping a month came closest
(luck check 39%, needs 50%), 9-month 29%, 3-month 14%; calm Indian stocks earned too little
(1.06× what they lost).
**In Agora:** for ranking ideas, change what is ranked (a different factor or a combination),
not the window of one already kept. In India, momentum is the factor closest to passing.

## The great traders' entry rules, tested as written, failed here
tags: legends great traders minervini oneil kullamagi raschke holy grail turtle soup tudor jones 200 day templeton washout tested failed
On 5 Nov Claude tested six legends' rules in both markets (12 tests, round 2504): O'Neil and
Minervini's leader breakout near the 52-week high on volume, Kullamägi's momentum burst from a
calm base, Raschke's Holy Grail pullback and Turtle Soup, Tudor Jones's 200-day line held with a
trail, and a Templeton-style washout in a strong stock. All 12 were rejected. The breakouts and
the washout fired 4–30 times in three exam years and lost (US leader breakout: 1% on the luck
check); Turtle Soup traded 150+ times in the study years and lost to costs in both markets; the
200-day rule came closest in the US (won 1.09× what it lost; needs 1.1×) and lost in India. Why:
those methods pick a few leaders out of the whole market, and a new strategy here is tested on
about 30 large, liquid stocks, where real breakouts of leaders are rare and short swings pay
India's costs on every trade.
**In Agora:** don't propose a legend's entry rule as a new strategy on a fixed stock list. Their
lessons that did hold here are about exits and staying invested (see "In a strong rising market,
holding the stocks is the bar to beat"): use them as exits, or as filters on a market-wide ranking
strategy, and test the 200-day line as an exit on strategies that already work.

## The great traders' exits didn't improve the user's working strategies either
tags: legends exits trailing stop 4 atr wider trail stop loss 8 percent oneil partial exit time limit max bars tested failed
On 5 Nov (round 2512) Claude tried nine legend-style exit changes on the user's live strategies
#1, #4, #9, #11 and #12: a 4 ATR trailing stop (Livermore, Lynch, Seykota), O'Neil's 8% stop, a
60-day time limit instead of 20 (let the trend run), Kullamägi's half off at 2R, and a 6% stop on
the US breakout. None held up. Two lessons. A trailing stop on a strategy that exits on its own
signal cut its big winners hard: #1 fell from ₹2.13 lakh to ₹8,631 in the exam years and its win
rate from 38% to 24%, because its moving-average exit already lets trends run and the trail sold
them on ordinary pullbacks. And widening a trail or a time limit that already exists (#11, #12, #9,
#4's trail) changed the result by too little to beat the luck check (1–5%), so the 3 ATR trails and
the 20-day limit the user's strategies have are already about right.
**In Agora:** don't add a trailing stop to a strategy that already exits on a trend signal, and
don't re-tune an exit within a step of where it is; propose an exit change only when the trade
autopsy shows a specific failure (winners given back, losers running).

## A momentum sell-off hits the strongest stocks while the index holds
tags: momentum crash sell-off strongest stocks index holds breadth risk off ai 6 nov relative strength ranking
On 6 Nov, after the S&P 500 fell 4.4% and Asia crashed (Kospi −8%, Nikkei −5.7%) in an AI
sell-off, India's Nifty 50 rose 0.3% and the Sensex 0.6%, but the 250 most traded Indian stocks
ranked strongest by Kairos (relative strength, momentum, near their highs) fell 1.4% on average,
with only 62 of 250 up. This is the classic momentum crash (anomalies: "Momentum crashes"): when
risk is cut, the stocks that rose most are sold first, while the largest index names hold. A
momentum or relative-strength strategy should expect its worst days on global risk-off days even
when its home index looks calm.
**In Agora:** judge a momentum idea's drawdown on the market's worst risk-off days, not only its
average; a market-level condition (index above its 50-day average, or the news gauge calm) is
worth testing as a regime switch for momentum rankings, rather than a stock-level filter (which
cuts the big winners, see "Filters cut the big winners of trend strategies").

## The luck bar rises with every try: dip ideas made money and still failed
tags: luck check deflated sharpe number of tries effective tries dip mean reversion rsi williams bollinger 6 nov
On 6 Nov (round 2576) six dip-in-an-uptrend ideas were tested in both markets: RSI(3) under 15
in a calm uptrend, Williams %R(2) washout, below the lower Bollinger band with ADX under 25, near
the 52-week high and calm, Connors' two-day RSI(2) washout, three lower closes in a stacked trend.
None held up. Several US versions were profitable in the exam years but failed the luck check
(1–12% against 50%) because 174 strategies had already been tried on US daily data: the more
ideas tested, the higher the Sharpe ratio a new one needs before it counts as more than luck.
Two Indian versions were judged as versions of strategy #5, not new ones.
**In Agora:** spend tries where the evidence is strongest (changes to strategies that already
work, or a genuinely new source of edge), not on near-variants of tested families; each rewording
raises the bar for every later idea.

## Chasing a big day doesn't pay, in either market
tags: scanner breakout unusual volume gap momentum chase big move next day fade whole market
Over two years of every liquid stock, bought the next open after a 5% day on three times the volume, a
3% day on double, or a 20-day high on 1.5 times the volume, after costs: none beat simply holding every
liquid stock, in the study years or the exam years, in India or the US. Big up-days fade: the next five
days average −1.3% in India and −1.6% in the US, 46% up. Of 2,746 big up-days in 28 days, a full desk
refused only 6.
**In Agora:** don't propose "buy what's moving" ideas, and don't widen a desk's list to chase moves.
The reason Kairos misses moves is that its entries don't predict them, not its limits.

## The bounce after a heavy fall: real in the whole market, not in 30 large stocks
tags: heavy fall bounce mean reversion panic forced selling high volume us india dip
Across all liquid US stocks, buying the next open after a 5% fall on double volume and holding five
days made +2.10% (study) and +0.65% (exam) a trade after costs, medians +0.51% and +0.21%: the only
causal edge the scanner test found. India: nothing. On 6 to 8 large stocks it gives only 20 to 72
trades in the study years and fails the luck check (5% to 28%), with and without a 200-day filter, a
stop or a longer hold.
On the 250 most traded US stocks it had 1,100 to 2,100 trades: with a 200-day filter and a 10-day hold,
exam +80.8% against +68.2% for holding, won 1.45× what it lost; the luck check still said 14%. That
list is today's survivors, which flatters it.
**In Agora:** this needs a wide universe to be tested fairly, and a list as it stood at the time.
Don't re-word it on a few stocks.

## Trades get ahead, then give it back
tags: exits give back best point stop trailing kairos desk real trades lessons
On 454 real desk trades the average trade reached +1% to +2% at best and ended negative. What
happened after the exit was mixed, so stops aren't simply too tight: in most groups the move after
closing was small or the wrong way. The entries are the weak part.
**In Agora:** judge an exit change by the whole record, not by the trades it would have saved.

## Combining two strategies that overlap gives less, not more
tags: combine combination all agree veto filter confirm india daily
#12 (ADX filter crossover) with #11 (trending stocks) requiring both, India daily: ₹4.18 lakh in the
exam years against ₹7.33 lakh for #12 alone, the same result filters have on trend strategies: it
cut the big winners.
**In Agora:** combine strategies that are different in kind, and judge them by the combiner's tests.

## A blocker that removes good and bad trades alike knows nothing
tags: combine repair blocker veto filter information bad trades good trades india daily
The combiner's repair looked for strategies that would have blocked the bad trades of #52, #51 and
#40 (India daily) in the study years. Each candidate blocked about the same share of good trades as
of bad ones (62% of bad and 61% of good; 64% and 77%), so nothing reached the exam.
**In Agora:** a real filter separates: judge a blocker by the difference between the two shares.

## Today's most traded stocks flatter every past test
tags: survivorship hindsight universe wide list most traded india momentum breakout point in time
On today's 250 most traded Indian stocks a momentum rule made +155% in the exam years. On the stocks most
traded when the exam began it lost on its trades (won 0.91× what it lost) and trailed the Nifty. A
50-day breakout in an uptrend went from +164% to +56.5%, still twice the Nifty's +28.7%. The stocks on
today's list are there because they went up.
**In Agora:** never judge a wide idea on today's list alone; `survivorship_check` does this. Discount
any result on a list chosen today, and expect less than the backtest even on a fair list.

## India's kept breakout: trend following needs breadth
tags: india breakout 50 day uptrend trend following breadth wide list big winners
A close above the 50-day high, above the 200-day average, held until the close falls below the 50-day
average, on 250 stocks: 153 exam trades, 39% won, won 1.46× what it lost, on a fair list. On 8 stocks
such rules were never given a chance, because a few big winners pay for everything and 8 stocks
rarely hold them.
**In Agora:** try trend-following on wide lists, not on a handful of large stocks.

## Ranking stocks against each other held up where single-chart momentum didn't
tags: ranking momentum 12 month india top 20 low volatility calmest fair list us
On a fair list, India's monthly 12-month momentum, top 20, made +98.6% in the exam years against +28.7%
for the Nifty (won 1.26× what it lost). The single-chart six-month momentum rule failed on the same
test. India's calmest 20 failed (0.98×). In the US, holding the calmest 20 of its list did better
than 10: +83.5% against +68.2%, 2.03×.
**In Agora:** rankings compare stocks; try them where a one-chart rule failed.

## Dips need testing wide before they are believed; US momentum nearly passed
tags: rsi2 dip india wide list momentum us 12 month ranking near miss luck check
India's RSI(2) dip in an uptrend on 250 stocks lost on the fair list (0.92×, −16.2%) after looking fine on
today's list. US 12-month momentum, top 20: +153.7% against +68.2% on the fair list, 2.19×, 72 exam
trades, but 30% on the luck check.
**In Agora:** a wide fair-list result is the one to trust. A near miss isn't a keeper; forward paper
results are what would settle US momentum.

## Shorting falling US stocks loses, even with a trend filter
tags: short selling 50 day low below 200 day falling stocks us hedge
On 250 US stocks, shorting a 50-day low below the 200-day average lost in the study and exam years
(0.39×, −49.3%), and on the fair list (0.65×). Falling stocks bounce hard, and the market rose.
**In Agora:** don't expect a simple short rule to hedge the long strategies.

