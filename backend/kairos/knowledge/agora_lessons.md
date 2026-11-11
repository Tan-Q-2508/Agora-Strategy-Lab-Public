# What Agora's own tests and desks taught (November 2026)

Measured on the user's data in laptop sessions (sprint 2026-11, the trade judge, the desks).
Results on this data, not laws: they can change, and every desk re-checks them with each study.

## Where Kairos's entries make money after costs, and where they don't
tags: desk stand aside trade judge intraday daily costs lose after costs which timeframe
On past trades the desks hadn't learned from, after costs: India daily entries earned about
+0.07R a trade and US daily +0.015R; India 1-hour lost 0.15R, 15-minute 0.24R, 5-minute 0.43R,
1-minute 1.23R; US 5-minute lost 0.14R and 1-minute 0.28R. A desk whose entries clearly lose
gets a warning on its card and keeps trading at full size (D-215: the user wants Kairos free to
make mistakes and learn). The judge can make a desk pickier, but it can't rescue a chart where
nothing pays: read the trade reviews to find out why, and improve the entries.

## Holding the index is the honest bar
tags: benchmark index buy and hold beat the market nifty s&p bar compare
In the sealed last year the Nifty 50 fell 8.4% and the S&P 500 rose 11.4%. No Indian strategy
from the research sprint made money in that year; eight US ones beat the S&P 500's Sharpe ratio
(return for the risk taken): six-month momentum ranking, Supertrend, Ichimoku, Connors RSI dips,
RSI(2) dips, ROC momentum, Donchian breakout, accumulation breakout. Say plainly when a desk or a
strategy is behind simply holding the index.

## Trend strategies earn from a few big winners
tags: trend following big winners filters exits win rate profit factor
On the user's live trend strategies every added filter (weekly trend, 200-day average, volume)
cut a few large winners and made less money per trade. Win rates of 35–45% are normal for trend
rules; the average win being several times the average loss is the edge.
**When reviewing a trend trade:** don't judge it by its win rate; judge the exits (did a winner
give back most of its gain?).

## Overnight gaps go through stops
tags: gap stop loss biotech overnight news risk
A US 15-minute desk lost about 7.5% when a biotech stock it held fell 38% overnight; the stop
filled at the next open. Stops don't protect against gaps: small, news-driven stocks need
smaller positions, or no overnight holding on short desks.

## Thin stocks cost more and go missing
tags: liquidity thin stocks small cap missing prices value traded picks
Stocks trading under about ₹20 crore (or $20 million) a day often return no prices and cost more
to trade than any edge earns; Kairos's picks require that on 20 and 120 days (D-155).

## A strategy that only works on two or three stocks is a bet on those stocks
tags: few stocks concentration universe stock selection adanient bse trial metis strategy
The user's India strategies #1, #11 and #12 trade 2 to 6 stocks (ADANIENT and BSE among them) and
earned less when liquid large caps were added. When Kairos considers trying such a Metis strategy
on a desk, or reviews its trades, treat its record as evidence about those stocks, not about the
rule, and size it small.

## Two US rankings held up on unseen years
tags: ranking momentum low volatility metis strategy trial desk us monthly calm stocks
Metis keeps two monthly US rankings that passed every check: six-month momentum (#21, the best
performer in the sealed last year) and the six-month calmest stocks above their 200-day average
(#22, 63% of exam trades won). They rebalance monthly, so they suit a slow sleeve or a trial, not a
fast desk. When the user asks what works in the US, these two are the honest answer so far.

## Why a desk isn't trading: the honest reasons
tags: desk not trading why no trades stand aside sector limit waiting orders paused prices market closed
When the user asks why a desk made no trades, check these in order: (1) the market is closed
(the desk card says so); (2) the trade judge passed on the entry; a judge's warning alone
never stops a desk (D-215); (3) it already holds **three trades in that sector** ("Already 3 open
trades in Energy"), so one theme can't fill the desk (D-168); (4) a **daily desk** decides at the
close and buys at the next open, so its orders wait overnight and survive a restart when no
candle closed meanwhile (D-152); (5) prices aren't arriving ("No live prices"): it resumes by
itself once they do, and an internet outage only pauses it a minute at a time (D-165). Say which
it is, from the desk card, rather than guessing.

## How a desk's return is counted
tags: total return desk restart first capital how much made return since started
A desk's total return counts from the money its first run started with, across every restart
by the autopilot (D-146); money a portfolio moved in or out isn't profit. "Today" is today's
change only.

## Reading the news gauge: what counts and what doesn't
tags: news risk gauge elevated calm why paused news guard far away country sell off headline
On 5 Nov the US gauge read 74 ("Elevated": desks open no new trades, losing ones close in
protective mode) because a Paraguayan bank collapse had been read as US news at the top severity.
Now a crisis that names only smaller, distant economies counts as world news of at most "serious"
(D-173); it counts as US news only when US markets or the US economy are named. A headline that
reports a fall the prices already show ("chip stocks sink 11%") stays "serious": the desks see the
fall in their charts, stops and judge; the gauge is for news the prices haven't caught up with yet
(war, sanctions, a bank failure at home), plus an index's own fall by its size (D-183: "S&P 500
down 4.4%" is severity 5, "Nifty down 3.2%" 4). When the user asks why a desk paused on news, name
the driver from the gauge and say whether it is about this market.
How it reads (D-179 to D-189): the headline, not the summary's background ("since Russia's
invasion"); whole words ("coup" isn't in "coupon"); words that also mean other things
("escalation", "military", "home invasion") aren't war on their own; other markets' news (Kospi,
Nikkei) is world news; one event from many outlets is one story with corroboration, not many.

## A global sell-off day: what the desks do
tags: crash sell-off severe news gauge global market panic circuit breaker what does the desk do protect
On 6 Nov the gauges read severe (US 92, India 89): the S&P 500 had fallen 4.4% and the Nasdaq
100 6% in an AI sell-off, Korea's Kospi 8–9% with a circuit breaker, Japan's Nikkei 6% into a bear
market. On such a day Kairos's desks open no new trades; buys queued at the last close on calm
news are cancelled before they fill (D-190); a long is closed only when the market itself falls
on the candle (1%+, or any fall at 90+, D-179), so a misread headline can't sell positions in a
calm market; company red flags still close at once. The gauge fades with a six-hour half-life, so
trading resumes on its own as the news ages. When asked "why didn't the desk buy the dip?", say
that: the evidence on this data is that entries into a crash lose before they win, and the desk
waits for its chart and the news to agree.

## Checking that the numbers are right, not only that Agora runs
tags: data stale prices current wrong numbers audit check health how do you know
In the 5–6 Nov audit "everything running" hid wrong outputs: most stocks' daily prices had stopped
for up to ten days behind a paused source (D-182), four exchange test symbols stalled India's
top-up (D-184), 10,542 headline links pointed at the wrong companies (D-180), and desks skipped
candles that closed while Agora was off (D-181). Before trusting a ranking or a backtest, check the
share of stocks with current prices and the date of the newest candle of the stocks used; before
trusting a news-driven pause, read the headline behind it.

## The first checked forecasts: not yet better than a coin
tags: forecast record skill accuracy candle forecast checked hit rate range calibration trust
On 6 Nov the first batch of Kairos's 10-day forecasts for Indian stocks came due: of 53 checked,
the direction was right 36% of the time (worse than a coin) and the price ended inside the
forecast's 80% range only 21% of the time (it should be about 80%): in the weeks of the US
election and the AI sell-off, moves were far bigger than the forecasts' ranges allowed. That is
exactly what the skill test is for (D-175): desks use forecasts only after 60+ checked ones show
direction right clearly more often than a coin, so these never moved a trade. When asked "can I
trust the forecast?", give the checked record, not the forecast's own confidence.

## What the weekend audit showed (November 2026)
tags: opportunity missed moves chase breakout india survivorship exits give back gains trades ahead
Chasing a stock after a big day doesn't pay in either market: big up-days fade over the next five days.
Full desks cost almost nothing: 6 of 2,746 big days. My trades reach +1% to +2% then end negative, so
entries are the weak part. On a fair list, India's 50-day breakout in an uptrend beat the Nifty; momentum
on today's most traded stocks only looked good because the list has hindsight.

