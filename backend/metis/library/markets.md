# Market structure for quants: India and the US

## NSE trading day
tags: nse session pre-open auction india market hours
NSE equities trade 09:15–15:30 IST after a pre-open call auction (09:00–09:08) that sets the opening price. Opening prices therefore come from an auction, and the first minutes are the most volatile. Agora fills next-candle orders at that open.

## Price bands and circuits
tags: circuit limit price band upper circuit lower circuit india
Many Indian stocks have daily price bands (from 2% to 20%); a stock locked at its band can't be traded that candle. Index-wide circuit breakers halt trading on very large index moves. Stocks with derivatives have wider, dynamic bands.
**In Agora:** a candle with high = low = close on volume is treated as locked and nothing fills.

## Delivery, intraday and short selling in India
tags: delivery intraday mis short selling india rules
Delivery (cash) trades are held overnight and settle T+1 (India moved to T+1 in 2023). Intraday positions must close the same day. Retail short selling in cash equities is intraday only.
**In Agora:** India delivery is long-only; intraday positions close at 15:20 IST.

## Nifty 50 membership
tags: nifty 50 index rebalancing membership survivorship
The Nifty 50 is reviewed twice a year and members change; today's list contains the survivors. Backtests on today's list overstate long-run results unless historical membership is imported.

## US trading day
tags: us market hours nyse nasdaq t+1 session
US stocks trade 09:30–16:00 New York time (extended hours are ignored in Agora). Settlement moved to T+1 in May 2024. Short selling is allowed (Agora ignores borrow fees).

## Event risk
tags: events earnings results rbi fomc budget policy calendar
Results seasons, central-bank decisions (RBI, the Federal Reserve), the Union Budget, elections and index rebalances move prices and gap them overnight. Strategies that hold through events carry gap risk their backtest may not show if the period was calm.
**In Agora:** Kairos's news risk gauge and news guard handle this for its desk (D-69).

## Benchmarks and beta
tags: benchmark nifty spy buy and hold comparison alpha beta
Always compare with simply holding the index (the Nifty 50 or SPY) over the same period, and ask how much of a strategy's return is just market exposure (beta). A strategy that made 40% while the index made 60% with similar risk added nothing.
