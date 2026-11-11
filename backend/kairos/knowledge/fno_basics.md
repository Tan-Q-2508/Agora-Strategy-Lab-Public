# Futures and options: the basics

## Derivatives in one page: futures and options
tags: derivatives fno f&o futures options what are derivatives leverage lot contract
A derivative is a contract whose value comes from something else (a stock or an index). **Futures** oblige both sides to buy or sell at a fixed price on a future date; gains and losses are settled every day. **Options** give the buyer a *right* (not an obligation) to buy (call) or sell (put) at a fixed price (the strike) until expiry, for a price paid up front (the premium); the seller takes the obligation and keeps the premium. Both trade in fixed lots and need only a fraction of the contract value as margin, which is leverage: small moves make large gains and losses. In India SEBI's own studies found about 9 in 10 individual F&O traders lost money (91% in FY25, 87.7% in FY26). Agora doesn't trade futures or options; Kairos explains them and works out strategy numbers with its options calculator.

## Futures contracts: lots, margin and mark-to-market
tags: futures contract lot size margin span exposure mark to market mtm settlement expiry leverage
A future is an agreement to buy (long) or sell (short) a fixed quantity (one lot) at today's futures price on expiry. You don't pay the full value: the exchange blocks an initial margin (in India SPAN plus exposure margin, often 12–20% of the value for index futures, more for stocks). Every evening the position is marked to market: the day's gain is credited and the loss debited in cash. If losses eat into the margin you must add money or the broker closes the position. A 1% move in the underlying is roughly a 5–8% move on the margin, both ways. Indian stock futures are physically settled (you take or give delivery of shares if held into expiry); index futures are cash settled.

## Futures pricing: cost of carry, basis and rollover
tags: futures price cost of carry basis premium discount contango backwardation rollover roll fair value
Fair futures price ≈ spot × (1 + interest rate × time) − expected dividends. The gap between futures and spot is the **basis**: normally a small premium that shrinks to zero at expiry (contango); a discount (backwardation) appears when dividends are due or when traders are very bearish or short-sellers can't borrow stock. **Rollover** is closing this month's contract and opening next month's before expiry; the roll cost is the price gap between the two. Rising rollover percentages with rising prices suggest traders are carrying bullish positions forward; heavy rollovers of short positions suggest the opposite.

## Open interest: what the numbers say
tags: open interest oi long buildup short buildup short covering long unwinding price oi change
Open interest (OI) is the number of contracts still open. Read it with price: **price up + OI up = long build-up** (new buyers, bullish); **price down + OI up = short build-up** (new sellers, bearish); **price up + OI down = short covering** (shorts buying back, a rally that may fade); **price down + OI down = long unwinding** (longs exiting). One day's change is noisy; look at several days and at big strikes. Since SEBI's 2025 rules, position limits use delta-adjusted ("future-equivalent") OI, which counts an option by how much it really moves with the price.

## Call and put options: buyer, seller, strike and premium
tags: options call put buyer seller writer premium strike expiry right obligation option basics
A **call** gains when the price rises above the strike; a **put** gains when it falls below. The **buyer** pays the premium, can lose at most that premium, and needs the move to be big and quick enough. The **seller (writer)** receives the premium, wins if the move doesn't happen, but can lose far more than the premium (unlimited for a naked call). Options are **in the money** (ITM) when exercising would pay (call: price above strike), **at the money** (ATM) near the strike, and **out of the money** (OTM) otherwise. Premium = intrinsic value (what it's worth if exercised now) + time value (what's paid for the chance of more), and time value melts to zero by expiry.

## Option pricing: Black-Scholes and the binomial model
tags: black scholes black-scholes bsm black-76 binomial cox ross rubinstein option pricing model fair value
An option's fair price depends on the price, the strike, time to expiry, interest rates, dividends and, above all, **volatility**. Black-Scholes values European options (exercised only at expiry: NSE index options, SPX); Black-76 does the same from the futures price, which is how Indian index options are usually quoted. American options (US single stocks) can be exercised early, so they're valued with a binomial tree (Cox-Ross-Rubinstein). Every input but volatility is known, so the market price of an option tells you the volatility traders expect: its implied volatility. Kairos's calculator uses these models and labels its premiums as estimates; the option chain gives the real ones.

## Implied versus historical volatility, IV rank and the VIX
tags: implied volatility iv historical volatility realized hv iv rank iv percentile india vix vix fear gauge volatility risk premium
**Historical (realised) volatility** measures how much the price actually moved; **implied volatility (IV)** is what option prices assume it will move. IV is usually a little above what follows (the volatility risk premium, which is why option sellers win more often), but it jumps before events and in panics. **IV rank** places today's IV within its past-year range (0 = lowest, 100 = highest); high IV favours selling premium, low IV favours buying it. **India VIX** (from Nifty options) and the **VIX** (from S&P 500 options) are the market's fear gauges: a VIX of 20 means the market expects about ±20% a year, roughly ±1.25% a day.

## Option Greeks: delta
tags: greeks delta hedge ratio probability itm option delta directional exposure
**Delta** is how much the option's price moves for a 1-point move in the underlying: calls 0 to +1, puts 0 to −1. An ATM option has about ±0.5, deep ITM near ±1, far OTM near 0. Delta is also a rough market-implied chance of finishing in the money (a 0.30-delta call ≈ 30%). Position delta (sum of all legs × lots) says how much the position behaves like owning the stock: +50 delta ≈ long 50 shares. Delta-neutral traders hedge it to zero to bet only on volatility or time.

## Option Greeks: gamma
tags: greeks gamma convexity gamma risk expiry gamma acceleration
**Gamma** is how fast delta changes as the price moves. It's highest for ATM options close to expiry. Long options have positive gamma (moves in your favour accelerate your gains); short options have negative gamma (moves against you accelerate losses), which is why selling options on expiry day is dangerous: a sudden move can turn a small credit into a big loss within minutes. SEBI added an extra 2% margin on short index options on expiry day (from 20 Nov 2024) for this reason.

## Option Greeks: theta and time decay
tags: greeks theta time decay decay weekend expiry days to expiry premium decay
**Theta** is how much an option loses each day as time passes, all else equal. Time value decays slowly at first and fast in the last weeks, and fastest for ATM options. Buyers pay theta every day the move doesn't come; sellers collect it. Most of a weekly option's value can disappear in its last two days. Theta is the seller's friend only while gamma doesn't bite: sellers earn small amounts most days and occasionally lose a lot.

## Option Greeks: vega and IV crush
tags: greeks vega iv crush volatility crush event earnings results budget
**Vega** is the change in an option's price for a one-point change in implied volatility. Long options gain when IV rises, short options when it falls. Before results, budgets and elections IV rises; once the news is out it collapses (**IV crush**), so an option buyer can be right about direction and still lose because the premium deflates. Longer-dated options have more vega.

## Option Greeks: rho, dividends and put-call parity
tags: rho interest rate dividend put call parity synthetic conversion reversal arbitrage
**Rho** is sensitivity to interest rates (small for short-dated options). Dividends lower call prices and raise put prices because the stock drops by the dividend. **Put-call parity** ties European calls and puts with the same strike and expiry: call − put = spot − strike × discount − dividends. It means a long call plus a short put behaves like the stock (a synthetic long), and arbitrageurs keep prices in line through conversions and reversals; when parity looks broken, check dividends, rates and bid-ask spreads before believing it.

## Volatility smile and skew
tags: volatility smile skew smirk otm puts expensive term structure
Implied volatility differs by strike: in equity indices, OTM puts trade at higher IV than OTM calls (the **skew**), because investors pay up for crash protection and markets fall faster than they rise. IV also differs by expiry (the **term structure**): normally longer expiries have higher IV, but before an event or in a panic the near expiry is highest (inverted). Skew makes put spreads and risk reversals priced differently from what a single-volatility model says.

## Reading an option chain
tags: option chain strikes bid ask ltp oi change iv chain analysis atm strike
An option chain lists, for one expiry, every strike with call data on one side and put data on the other: last price, bid and ask, volume, open interest, change in OI and implied volatility. Look first at the ATM strike and its straddle price (the market's expected move), then where OI is heaviest: big call OI above the price is where sellers expect a ceiling, big put OI below where they expect a floor. Wide bid-ask spreads on far strikes or stock options mean you lose money just getting in and out; stick to liquid strikes.

## Put-call ratio (PCR)
tags: put call ratio pcr sentiment contrarian oi pcr volume pcr
PCR = put open interest ÷ call open interest (or volumes). Above about 1.2–1.3, many puts have been written or bought: often read as support (writers expect no fall) or extreme fear; below about 0.7, heavy call activity: complacency or resistance. It's a sentiment gauge, mostly useful at extremes and as a contrarian signal, never a trigger by itself.

## Max pain
tags: max pain maximum pain option writers expiry pinning
Max pain is the strike at which option buyers as a group would lose the most at expiry (and writers gain the most). Some traders expect prices to drift toward it into expiry ("pinning"), especially for heavily traded indices. The evidence is weak and the level moves daily; treat it as one input near expiry, not a target.

## Open interest support and resistance
tags: oi support resistance highest call oi highest put oi option writers levels
The strike with the most call OI above the price is often treated as resistance and the strike with the most put OI below as support, because sellers defend them. When price breaks through a heavy strike, writers rush to cover and the move can accelerate (a short squeeze in calls, or a put-writer unwind on the way down). Changes in OI during the day matter more than yesterday's totals.

## Expiry day: pinning, gamma and zero-day options
tags: expiry day 0dte zero day options weekly expiry gamma blast hero zero pinning
On expiry day option time value collapses to zero by the close. Cheap far OTM options ("hero or zero") look tempting but nearly always expire worthless; short ATM options earn fast decay but carry violent gamma risk. India allows one weekly expiry per exchange's benchmark index (NSE: Nifty 50 on Tuesdays; BSE: Sensex on Thursdays, since 1 Sep 2025); SPX has options expiring every trading day. Most expiry-day option buyers lose; if trading it at all, size tiny and decide the maximum loss before entering.

## Exercise, assignment and settlement
tags: exercise assignment settlement european american physical settlement cash settled itm stt on exercise
European options (NSE index options, SPX) are exercised only at expiry; American options (US stocks, SPY, QQQ) any day, so a short option can be assigned early, typically just before an ex-dividend date for ITM calls. NSE index options are cash settled. Indian stock F&O is physically settled: an ITM stock option held into expiry becomes a delivery of shares, needing full money or shares, and STT on exercised options is charged on the intrinsic value. Close or roll stock options before expiry unless you want the shares.

## Margins for futures and option sellers
tags: margin span exposure peak margin upfront premium option selling margin hedge benefit leverage
Buying options needs only the premium (collected upfront in India since 1 Feb 2025). Selling options or holding futures needs SPAN plus exposure margin; hedged positions (spreads, iron condors) need much less because the worst case is capped. Since 1 Feb 2025 the calendar-spread margin benefit is removed on the expiry day of the near leg in India. Margin is not the risk: a naked short option can lose many times its margin in one gap.

## The expected move from option prices
tags: expected move straddle price one standard deviation range implied move
The ATM straddle price (call + put) is roughly the market's expected move by expiry: about 0.8 × one standard deviation. One standard deviation ≈ price × IV × √(days / 365). For Nifty at 25,000 with IV 13%, the 7-day one-standard-deviation move is about 25,000 × 0.13 × √(7/365) ≈ 450 points, so about two weeks in three it stays within ±450. Strategies that sell inside this range collect more but are breached more often.

## Probability of profit and why options lose money
tags: probability of profit pop win rate options losses theta bid ask risk of ruin why traders lose
A high probability of profit doesn't mean a good trade: selling far OTM options wins often but the rare loss can wipe out months of gains; buying OTM options wins rarely and usually loses the whole premium. What matters is the expected value after costs. Retail traders lose mostly through buying short-dated OTM options, overtrading (costs and bid-ask spreads on every round trip), oversized positions, and selling naked options without a stop. SEBI's FY26 study: 87.7% of individuals lost money; options were over 90% of the losses; before costs 82% lost, so costs alone turned 5% more into losers.

## Position sizing and risk rules for options
tags: options risk management position size max loss defined risk stop loss options rules
Size by the maximum loss, not the margin: risk 1–2% of capital per trade. Prefer defined-risk structures (spreads, condors, butterflies) to naked short options. Decide exits before entering: many premium sellers close at 50% of the maximum profit and cut at 2× the credit received, and avoid holding short options through events or into the last days of expiry. Diversify expiries and underlyings; don't sell more options because the last ten expired worthless.

## Hedging a portfolio with futures and options
tags: hedge hedging beta hedge portfolio insurance index futures put protection
To protect a stock portfolio, short index futures worth portfolio value × beta (a beta-1.2 ₹10 lakh portfolio needs about ₹12 lakh of short Nifty futures), or buy index puts (a protective put on the whole portfolio). Futures hedges remove upside too; puts cost premium but keep the upside. Collars (buy a put, sell a call) make protection cheap by giving up gains above the call. A hedge only works as well as the portfolio tracks the index.
