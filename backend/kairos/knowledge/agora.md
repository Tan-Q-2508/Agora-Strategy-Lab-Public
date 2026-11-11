# Agora and Kairos

## What Agora is
tags: agora app lab paper trading backtest local
Agora is a local strategy lab: build a strategy with blocks or Python, backtest it on Nifty 50 or US stocks with realistic costs, and paper trade it live with simulated money. Nothing connects to a broker; no real orders are ever placed. Prices come from Yahoo Finance (with NSE and Stooq as backups) and are saved on the laptop. News comes from public feeds and GDELT, with no account or key.

## What Kairos can do
tags: kairos capabilities tools help what can you do
Kairos reads charts with the world's toolkit: 93 indicators (everything common to TradingView, TA-Lib and StockCharts that works on one stock's prices and volume), 93 candlestick patterns (all 61 in TA-Lib plus common extras), 41 chart patterns (classics, flags, harmonics such as the Gartley, bat, butterfly, crab, cypher and shark, AB=CD, three drives, channels), 19 named setups (breakaway gaps, islands, NR7, springs, pocket pivots, crosses, squeezes), trendlines, support and resistance, divergences and Fibonacci. It forecasts a likely price range with its track record, reads business and world news (geopolitics, central banks, oil, trade, crises) and scores how risky the news is for markets, scans many stocks, explains any concept, builds and backtests strategies, optimises and validates them, starts and stops paper trading, and runs its own paper-trading desk that learns from its results and protects itself when the news turns dangerous. It works only with paper money.

## Starter strategies in Agora
tags: templates starter strategies ma crossover rsi bollinger donchian supertrend opening range macd 52 week turtle connors triple screen squeeze ichimoku ma_crossover rsi_mean_reversion bollinger_reversion donchian_breakout opening_range_breakout macd_momentum high_52w_momentum
Agora's 28 templates: moving-average crossover, golden cross, triple moving average (4-9-18), RSI mean reversion, Connors RSI(2), Bollinger reversion, Donchian breakout, Turtle trading, Supertrend, Parabolic SAR, Keltner breakout, ADX trend, Aroon trend, Vortex crossover, Ichimoku cloud, Heikin-Ashi trend, MACD momentum, Schaff trend cycle, Coppock turn, 52-week-high momentum, Elder's triple screen, TTM squeeze breakout, Williams %R pullback, CCI swing, money-flow bounce, Fisher reversal, and two intraday ones (opening-range breakout, VWAP reclaim). Each can be created for India or the US and then edited or optimised.

## Kairos's honesty rules
tags: honesty disclaimer advice prediction limits
Kairos's numbers come from Agora's tested code, never from guesswork. Forecasts are ranges with a measured track record. Kairos says when the evidence is weak, when a backtest has too few trades, and when a strategy simply matches buy-and-hold. It is a research tool, not financial advice, and it trades paper money only.

## Win rate versus profit after costs
tags: win rate profit after costs payoff ratio expectancy break even win rate costs overtrading high win rate
A high win rate isn't the goal; profit after costs is. A strategy that wins 70% of the time but whose losses are three times its wins loses money; one that wins 35% with wins three times its losses makes money. The break-even win rate is 1 ÷ (1 + average win ÷ average loss). Costs are paid on every trade, so many small wins can turn a good backtest into a loss. Kairos can raise a strategy's win rate by skipping its worst trades, but only keeps a filter when profit after costs holds up too.

## Kairos's trade check
tags: trade check quality filter meta labelling skip bad trades kairos brain learn which trades to skip balanced strict
Kairos's trade check sits between a strategy's signal and the order. It reads the market's condition on the signal candle (trend strength, choppiness, RSI, volatility, volume, stretch, distance from the 50- and 200-candle averages, place in the recent range and Kairos's own score), estimates the chance this trade makes money after costs from the strategy's own past results, and skips trades that look clearly worse than usual (balanced) or keeps only good-chance trades (strict, for a higher win rate with fewer trades). It must first prove its judgements were right on at least 30 results before it skips anything, it follows skipped signals to learn from them too, and it runs identically in backtests and paper trading.

## Why trades fail: Kairos's review
tags: review post mortem why trades failed losing trades costs ate profit what went wrong analysis
After every backtest and paper session Kairos reviews the trades: how much costs ate, the win rate against the size of wins and losses, whether a few big trades carried the result, how exits behaved (stops hit too fast, winners given back), and the market conditions in which trades failed although all the strategy's rules were met ("14 of 18 trades taken when the market was choppy lost"). It then tests filters on the first 60% of the trades and checks them on the last 40%, which they never saw.

## Improve with Kairos
tags: improve strategy better strategy fewer bad trades new version filter kairos improvement auto improve
Improve with Kairos backtests the strategy, finds filters that held up on unseen trades, adds them as ordinary entry conditions, backtests again and saves a new version only if, on the part of the period the filters never saw, it made at least as much after costs, won at least 2 points more often and kept at least 30% of the trades. Old versions are always kept. With "Let Kairos improve my strategies" on, it does this on its own while Agora is open, at most once a week per strategy.

## Kairos's predicted candles
tags: predicted candles forecast candles projection future candles prediction vs actual kairos prediction
Kairos draws the most likely next candles in the forecast cone: each closes on the middle of its forecast range and opens where the last one closed, with wicks the size this stock's candles usually have. They blend four models (volatility, past look-alike moments, trend and Kairos's own chart reading, leaned by the stock's news). It keeps every prediction and draws the latest one over the candles that actually formed, scoring each candle's direction and whether it stayed in range; its misses widen, narrow or shift future forecasts. They are a likely shape, never a promise.

## Kairos keeps learning while Agora is open
tags: always on learning perpetual learning self learning autonomous study background kairos learns on its own
While Agora is open (and "Keep learning" is on), Kairos studies every ten minutes or so: it reviews finished backtests and paper sessions, saves what made trades win or lose, tests improvements, makes and later checks price predictions for watchlist stocks, and re-studies signal history when new data arrives. It pauses while you run a backtest or research and stops completely when Agora closes. It never places an order on its own: everything it learns goes into deterministic rules.
