# Risk management and position sizing

## The first rule: survive
tags: risk management survival drawdown ruin capital preservation
Professional traders focus on losses before profits. A 50% loss needs a 100% gain to recover, so keeping drawdowns small matters more than finding the best entry. Most professional desks risk 0.25–2% of capital on a single idea and cap total exposure. A strategy with a modest edge and small drawdowns compounds; one with a big edge and huge drawdowns usually gets abandoned at the worst time.

## Position sizing by risk
tags: position sizing risk per trade percent risk stop distance atr shares
Decide the stop first, then the size: shares = (equity × risk %) ÷ (entry − stop). With ₹10,00,000, 1% risk (₹10,000) and a stop ₹50 below entry, buy 200 shares. This makes every trade cost about the same when it fails, whatever the stock's price or volatility. Agora's "risk-based" sizing does exactly this, and the Kairos desk uses 1% by default.

## Stops and targets
tags: stop loss target take profit trailing stop reward risk ratio r multiple
Put stops where the idea is wrong (beyond support, the pattern's other side), not at an arbitrary percentage, and at least about one ATR away so normal noise doesn't hit them. Reward-to-risk compares the distance to the target with the distance to the stop; ideas under about 1.5× rarely pay for their losing trades. Trailing stops (ATR-based, Supertrend, Parabolic SAR) let winners run. Results are best measured in R (multiples of the initial risk): a +2R winner made twice what was risked.

## Expectancy and win rate
tags: expectancy win rate profit factor average win average loss edge
Expectancy = win rate × average win − loss rate × average loss. A 35% win rate can be very profitable if winners are three times the losers; a 70% win rate can lose money if the losses are large. Profit factor (gross profit ÷ gross loss) above about 1.3 after costs is a reasonable bar; above 2 is strong and deserves suspicion of overfitting.

## Correlation and concentration
tags: correlation diversification concentration sector exposure portfolio
Five positions in five banks are really one position. Spread risk across sectors, cap the number of open positions and the total amount at risk, and reduce size when markets are wild. Kairos's desk limits open positions (5 by default) and pauses new entries after a 3% losing day.

## Volatility and regime
tags: volatility regime trending ranging mean reversion momentum market environment
Strategies work in some environments and fail in others. Trend-following needs trends (ADX above 20–25, prices beyond their averages); mean reversion needs ranges. When volatility jumps, cut size so the money at risk stays the same. A good trader first asks "what kind of market is this?" and only then "what should I do?".

## When not to trade
tags: no trade waiting patience cash discipline overtrading
Waiting is a position. Skip trades with poor reward-to-risk, trades into major events (earnings, central-bank decisions, budget day), trades that need a reason you can't state in one sentence, and revenge trades after losses. Overtrading, mostly through costs and impulsive entries, is the most common way retail traders lose.

## Trailing stops (dynamic stops)
tags: trailing stop dynamic stop chandelier exit atr trailing protect profit lock in gains let winners run ratchet
A trailing stop follows the price as a trade moves your way and never moves back: for a buy it sits a set distance below the highest price since entry, for a short above the lowest. It turns "how far can this go?" into "sell when the move is over", so winners keep most of their gain while losers are still cut at the start. Distance: a fixed percent ignores how much a stock normally moves; a multiple of ATR (the average true range, the stock's typical daily move) adapts to each stock. Chuck LeBeau's chandelier exit is 3 × ATR(22) below the highest high; 2–2.5 ATR suits short swings, 3–4 ATR lets trends breathe, under about 1.5 ATR gets shaken out by normal noise. Supertrend and Parabolic SAR are trailing stops drawn as indicators. Use one when trades were well ahead and then turned into losses, when a trend strategy has no exit that locks in gains, or when a fixed target cuts big winners short. Mean-reversion trades have a natural end (back to the average), so a target often suits them better; a wide trailing stop still caps the disasters. Kaminski and Lo (2014) found stop rules add value when returns trend (momentum), not when they mean-revert.
**In Agora:** every strategy's exits have "Trailing stop": a percent, or a multiple of ATR (ATR at the entry signal) behind the best price since entry, checked inside each candle like a stop. Kairos's desks trail at 3 × ATR by default (Settings → Kairos → Trailing stop); "Improve with Kairos" tries 2, 3 and 4 ATR when no entry filter helps; Metis proposes one for strategies without it.
