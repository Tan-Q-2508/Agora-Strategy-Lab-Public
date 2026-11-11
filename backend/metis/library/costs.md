# Costs, fills and turnover

## The break-even win rate
tags: break even win rate cost expectancy payoff
Break-even win rate = average loss ÷ (average win + average loss), measured after costs. If a strategy's win rate is at or below it, no amount of tuning the entry will help much: the payoff (exits) or the costs (fewer, larger trades) must change.
**In Agora:** the expert's first look compares the two for every strategy.

## Costs against gross profit
tags: costs share of profit turnover charges stt brokerage
When charges take more than about a third of gross profit, the strategy is mostly working for its broker and the tax office; a little more slippage would erase it. The fix is usually fewer, better trades: a stronger signal threshold, a trend or volatility filter, or longer holding.
**In Agora:** Kairos's review shows charges as a share of gross profit; Metis's first look flags it above 30%.

## Indian charges
tags: india charges stt stamp duty exchange fee gst sebi delivery intraday
Indian trades pay securities transaction tax (on both sides for delivery, on the sell side for intraday at a lower rate), exchange transaction charges, SEBI fees, stamp duty on buys, GST on brokerage and fees, and a depository charge on delivery sells. For delivery trades STT dominates, so short holding periods are expensive.
**In Agora:** every charge is effective-dated and computed in `Decimal` (`docs/COST_MODEL.md`); never assume a rate, read the table.

## US charges
tags: us charges sec fee finra taf commission
Most US brokers charge no commission; the SEC fee and FINRA's trading activity fee apply to sells and are tiny. For US strategies the spread and slippage matter more than fees.

## Slippage and market impact
tags: slippage market impact square root law spread execution
Fills are worse than the quoted price by the half-spread plus impact. Impact grows roughly with the square root of the order's share of daily volume (the "square-root law" seen across markets). For small orders in liquid stocks a few basis points is realistic; for thin stocks far more.
**In Agora:** slippage in basis points per market; orders over 5% of a candle's volume are refused.

## Next-open fills
tags: next open fill close signal timing execution assumption
Signals computed on a candle's close can only be traded after it, so Agora fills at the next candle's open. Strategies that look good only when filled at the signal's own close are fooling themselves; the overnight gap often takes most of the edge of short-term reversal.

## Cutting turnover
tags: turnover reduction bands holding period smoothing hysteresis
Ways to trade less without losing the signal: require the signal to pass a threshold by a margin (hysteresis), exit on a weaker condition than the entry, add a minimum holding period, smooth the indicator, or rebalance less often. Each cuts costs; test that it doesn't cut the edge.
