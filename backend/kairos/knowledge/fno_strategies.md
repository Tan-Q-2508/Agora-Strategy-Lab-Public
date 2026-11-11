# Option and futures strategies

## Choosing an option strategy: view and volatility
tags: option strategy choose which strategy matrix bullish bearish neutral volatile high iv low iv
Pick by two questions: where do you think the price goes (up, down, sideways, big move either way) and is implied volatility high or low? **Bullish**: long call or bull call spread (low IV), bull put spread or cash-secured put (high IV). **Bearish**: long put or bear put spread (low IV), bear call spread (high IV). **Sideways**: iron condor, iron butterfly, short strangle (high IV), calendar spread (low IV). **Big move either way**: long straddle or strangle (low IV, before an event the market underprices). Defined-risk versions are safer for everyone, and Kairos's calculator gives each one's cost, maximum profit and loss, break-evens and chance of profit.

## Long call
tags: long call buy call bullish option leverage long_call
Buy a call: profits if the price rises above strike + premium by expiry; the most you lose is the premium; the upside is unlimited. Best with a strong, quick bullish view and low implied volatility. Theta works against you every day, and an IV drop after an event can hurt even if you're right. ATM calls balance cost and responsiveness; far OTM calls are cheap lottery tickets that mostly expire worthless.

## Long put
tags: long put buy put bearish protection long_put
Buy a put: profits if the price falls below strike − premium; loss limited to the premium; profit grows as the price falls toward zero. Used for bearish bets and as insurance. Puts on indices are usually pricier than calls (skew), so bearish bets via puts cost more than the same bullish bet via calls.

## Short (naked) call and short put
tags: short call naked call short put naked put option selling writer short_call short_put
Selling a call alone earns the premium if the price stays below the strike, but losses are unlimited if it rallies. Selling a put alone earns the premium if the price stays above the strike, and loses as the price falls (down to zero): it's like agreeing to buy the stock lower. Both win often and lose big; margins are high and SEBI's studies show naked selling is not the safe income it looks like. Convert them to spreads by buying a further OTM option to cap the risk.

## Covered call
tags: covered call buy write income stock call writing covered_call bxm
Own the shares and sell an OTM call against them: the premium is income, but gains above the strike are given away. It lowers volatility rather than raising returns: Cboe's BXM buy-write index had returns close to the S&P 500 with about a third less volatility over 1986–2011 in commissioned studies, trailing in strong bull markets and beating it in flat or falling ones. In India stock options are physically settled, so an ITM short call at expiry means delivering the shares.

## Cash-secured put and the wheel
tags: cash secured put csp wheel strategy put writing income cash_secured_put
Sell an OTM put while holding enough cash to buy the shares at the strike. If the price stays above, keep the premium; if it falls below, you buy the stock at strike − premium, a discount to where it was. The **wheel** repeats: sell puts until assigned, then sell covered calls until called away. It works on stocks you'd be happy to own; in a crash you own a falling stock, so position size matters more than premium.

## Protective put and collar
tags: protective put married put collar zero cost collar insurance hedge protective_put collar
A **protective put** is stock plus a put: losses below the strike are capped, the upside stays, and the cost is the premium (like insurance). A **collar** adds a sold OTM call to pay for the put: cheap or free protection, but gains above the call strike are given up. Useful before an event when you don't want to sell the shares.

## Bull call spread
tags: bull call spread call debit spread vertical spread bullish bull_call_spread
Buy a call and sell a higher-strike call, same expiry. Cheaper than a long call, with less theta and vega exposure; profit is capped at the strike gap minus the debit; loss is capped at the debit; break-even is the lower strike + the debit. Best for a moderate rise to around the upper strike. Example on Nifty: buy 25,000 call, sell 25,200 call.

## Bear put spread
tags: bear put spread put debit spread vertical bearish bear_put_spread
Buy a put and sell a lower-strike put. A cheaper bearish bet than a long put: maximum profit is the strike gap minus the debit, maximum loss the debit, break-even the upper strike − the debit. Suits a moderate decline toward the lower strike.

## Bull put spread (put credit spread)
tags: bull put spread put credit spread credit spread neutral bullish bull_put_spread
Sell a put and buy a lower-strike put for protection: you collect a credit and keep it if the price stays above the short strike. Maximum loss = strike gap − credit; break-even = short strike − credit. Wins often in flat or rising markets and has defined risk; one sharp fall takes several wins' worth of profit. A common rule is to take profits at half the credit.

## Bear call spread (call credit spread)
tags: bear call spread call credit spread credit spread bearish neutral bear_call_spread
Sell a call and buy a higher-strike call: keep the credit if the price stays below the short strike. Maximum loss = strike gap − credit; break-even = short strike + credit. Useful above resistance or after a sharp rally when IV is high.

## Long straddle
tags: long straddle buy straddle volatility event results big move long_straddle
Buy a call and a put at the same (ATM) strike: profits from a large move either way; loses both premiums if the price sits still. Break-evens are strike ± total premium. Before results or a budget the straddle is expensive (IV is high) and IV crush afterwards often makes it lose even when the stock moves; it pays when the move beats what the market priced.

## Short straddle
tags: short straddle sell straddle range bound theta unlimited risk short_straddle
Sell the ATM call and put: collect both premiums, profit if the price ends near the strike; break-evens strike ± credit; losses unlimited either way. High theta and high gamma: the classic expiry-day trade that occasionally blows up accounts. If used, hedge it into an iron butterfly.

## Long strangle and short strangle
tags: strangle long strangle short strangle otm call put range long_strangle short_strangle
A **long strangle** buys an OTM call and an OTM put: cheaper than a straddle but needs a bigger move. A **short strangle** sells them: profits while the price stays between the strikes (wider than a straddle's range, so it wins more often) but risk is unlimited both ways. Sellers often choose strikes near 15–20 delta and close at half the credit. Converting it to an iron condor caps the risk.

## Iron condor
tags: iron condor condor range bound credit defined risk neutral iron_condor
Sell an OTM put spread and an OTM call spread on the same expiry: a credit that's kept if the price stays between the short strikes. Maximum loss = the wider spread's width − the credit; break-evens are the short put − credit and the short call + credit. A favourite for range-bound indices with high IV. Manage it: close at around half the credit, or roll the threatened side early; don't let a breached side run to expiry.

## Iron butterfly
tags: iron butterfly iron fly atm short straddle hedged iron_butterfly
Sell an ATM call and put, buy an OTM call and put as wings: a short straddle with capped risk. Bigger credit than an iron condor, narrower profit zone; maximum profit if the price ends exactly at the middle strike. Break-evens are the middle strike ± the credit.

## Long call butterfly and broken-wing butterfly
tags: butterfly long butterfly call butterfly broken wing butterfly bwb target price long_call_butterfly broken_wing_butterfly
A **butterfly** buys one lower call, sells two middle calls and buys one higher call: a cheap, defined-risk bet that the price ends near the middle strike. A **broken-wing butterfly** moves one wing further out so the trade costs nothing or earns a credit, removing risk on one side and adding some on the other. Good for a price target near an expiry, with small cost.

## Ratio spreads and backspreads
tags: ratio spread front ratio backspread call ratio put ratio call_ratio_spread put_ratio_spread call_backspread put_backspread
A **ratio spread** buys one option and sells two further OTM: often a small credit, profits most if the price ends at the short strike, but risk is unlimited beyond it. A **backspread** is the reverse (sell one, buy two further out): small loss if the price stalls between the strikes, unlimited profit on a big move in the chosen direction. Ratio spreads suit a mild move; backspreads suit a breakout.

## Jade lizard
tags: jade lizard twisted sister premium selling no upside risk jade_lizard
Sell an OTM put and an OTM call spread. When the total credit is larger than the call spread's width, there's no risk to the upside at all; the risk is a fall below the short put. A neutral-to-bullish premium-selling structure for high-IV stocks. (A twisted sister mirrors it: short call plus put spread.)

## Strap and strip
tags: strap strip straddle bias two calls two puts
A **strap** is two calls and one put at the same strike (a big move, more likely up); a **strip** is one call and two puts (a big move, more likely down). Like straddles they need a big move to pay and suffer from time decay and IV crush.

## Synthetic positions, conversions and box spreads
tags: synthetic long synthetic short conversion reversal box spread arbitrage synthetic future synthetic_long synthetic_short
Long call + short put at the same strike = a **synthetic long** (moves like the stock or a future); short call + long put = a **synthetic short**. Combining a synthetic with the opposite stock or future position locks in a fixed result: a conversion or reversal, used by arbitrageurs when put-call parity drifts. A **box spread** (bull call spread + bear put spread on the same strikes) is worth the strike gap at expiry, so its price is just an interest rate; retail "free money" boxes usually vanish after costs and assignment risk.

## Calendar (time) spread
tags: calendar spread time spread horizontal spread near far expiry theta vega calendar_spread
Sell a near-expiry option and buy the same strike in a later expiry. The near one decays faster, so the spread gains if the price stays near the strike; it also gains if IV rises (the long, later option has more vega). It loses on a big move away from the strike. Since 1 Feb 2025, Indian exchanges don't give calendar-spread margin relief on the near leg's expiry day.

## Diagonal spread and the poor man's covered call
tags: diagonal spread poor mans covered call pmcc leaps diagonal_spread
Buy a longer-dated, deeper ITM call (high delta) and sell short-dated OTM calls against it repeatedly: it behaves like a covered call with much less money tied up. Risk is the debit paid; sharp rallies above the short strike cap gains, and a sharp fall hurts the long call.

## Futures strategies: directional, spread and arbitrage
tags: long futures short futures calendar spread futures cash and carry arbitrage basis trade long_futures short_futures
**Long or short futures** are leveraged bets on direction with no premium but daily cash settlement; always use a stop because losses aren't capped. A **futures calendar spread** buys one month and sells another, betting on the basis between them (lower margin). **Cash-and-carry arbitrage** buys the stock and sells the future when the future is rich, locking in the basis as a near risk-free return (what arbitrage mutual funds do). Beta-weighted index futures hedge a stock portfolio.

## Delta-neutral trading, adjustments and gamma scalping
tags: delta neutral adjustment rolling roll gamma scalping hedging adjust options
Delta-neutral positions aim to profit from time decay or volatility rather than direction. When the price moves, delta drifts and traders adjust: roll the untested side closer, roll the tested side out in time, or hedge with futures. **Gamma scalping** owns options (long gamma) and repeatedly trades the underlying against them, earning when realised volatility beats implied. Every adjustment costs fees and slippage; adjusting a losing trade forever is a way to avoid admitting a loss.

## Trading options around events: results and IV crush
tags: event earnings results iv crush budget election rbi fed options before event
Before results, RBI or Fed decisions, budgets and elections, IV rises because a big move is possible. After the news it collapses. Buying straddles before an event pays only if the actual move beats the expected move (the straddle price); selling defined-risk structures into the event (iron condors, iron butterflies) harvests the crush but needs strikes outside the expected move. Check the move history: some stocks routinely move more than priced, most move less.

## Managing option trades: profit targets, stops and rolling
tags: manage options trade profit target 50% stop loss 21 dte rolling close early exit rules
Write the exit rules before entering. Premium sellers commonly take profit at about 50% of the maximum, cut losses at about 2× the credit, and close or roll well before the final days (where gamma risk is largest). Option buyers set a premium stop (for example −50%) and a time stop. Rolling (closing and reopening further out in time or strike) should give a better position, not just postpone a loss. Never hold short stock options in India into expiry by accident: physical settlement follows.

## Common F&O mistakes
tags: fno mistakes options mistakes overtrading leverage naked selling hero zero averaging
The mistakes behind the statistics: buying cheap far OTM weekly options; trading too often (each round trip pays brokerage, STT, exchange fees, GST and the bid-ask spread); using the whole margin; selling naked options because they "always expire worthless"; averaging down on losing option buys; holding through events without knowing the expected move; ignoring liquidity; and revenge trading after a loss. Kairos's rule: decide the maximum loss first, prefer defined-risk spreads, and check costs against the expected profit before every trade.
