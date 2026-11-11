# Futures and options in India and the US

## India F&O: what trades
tags: india fno nse bse nifty options bank nifty finnifty midcap select sensex bankex stock options index options
NSE lists index futures and options on Nifty 50, Nifty Bank, Nifty Financial Services, Nifty Midcap Select and Nifty Next 50, plus futures and options on about 200 stocks; BSE lists Sensex and Bankex derivatives. Since 20 Nov 2024 each exchange may offer weekly options on only one benchmark index: Nifty 50 on NSE, Sensex on BSE; the others trade monthly. Index options are European and cash settled; stock F&O is physically settled. Trading hours are 9:15–15:30 IST, with a pre-open session for current-month futures added in December 2025.

## SEBI's F&O rules since 2024
tags: sebi rules fno rules 2024 2025 contract size weekly expiry upfront premium elm calendar spread position limits futeq mwpl
SEBI's 1 Oct 2024 circular added six measures: (1) minimum contract value of ₹15 lakh at launch (lot sizes set for about ₹15–20 lakh), from 20 Nov 2024; (2) one weekly expiry per exchange's benchmark index, from 20 Nov 2024; (3) an extra 2% extreme-loss margin on short index options on expiry day, from 20 Nov 2024; (4) option premium collected upfront from buyers, from 1 Feb 2025; (5) no calendar-spread margin benefit on the expiry day, from 1 Feb 2025; (6) intraday monitoring of position limits, from 1 Apr 2025. A 29 May 2025 circular moved open interest to a delta-adjusted ("future-equivalent") measure, tightened the market-wide position limit (the lower of 15% of free float or 65× average daily delivery value) and set index option limits (₹1,500 crore net, ₹10,000 crore gross end of day), phased in from July to December 2025.

## India lot sizes and expiry days
tags: lot size nifty lot size bank nifty lot size expiry day tuesday thursday nse expiry bse expiry 2026
NSE revises lot sizes every six months to keep contract values in SEBI's range. From the January 2026 contracts (circular of 3 Oct 2025): Nifty 50 65, Nifty Bank 30, Nifty Financial Services 60, Nifty Midcap Select 120, Nifty Next 50 25 (it was 75, 35, 65, 140 and 25 before). Since 1 Sep 2025 all NSE equity derivatives expire on Tuesdays (Nifty 50 weekly every Tuesday; monthlies on the last Tuesday of the month) and BSE's on Thursdays (Sensex weekly); a holiday moves expiry to the previous trading day. Lot sizes change: check NSE's latest circular before trading.

## India F&O costs: STT and charges
tags: stt securities transaction tax fno charges options stt futures stt budget 2026 exchange charges stamp duty gst brokerage
Costs per trade on Indian F&O: brokerage (often ₹20 an order), exchange transaction charges, SEBI fees, stamp duty on buys (0.002% futures, 0.003% options premium), 18% GST on brokerage and fees, and **STT**. STT on the sell side was raised on 1 Oct 2024 (futures 0.02% of value, options 0.1% of premium) and again by the Union Budget 2026-27, effective 1 Apr 2026: **futures 0.05%**, **options 0.15% of premium**, and **0.15% on the intrinsic value of exercised options**. For an active option trader, costs plus the bid-ask spread are a large hurdle: SEBI's FY26 study counted about ₹24,859 crore of transaction costs paid by individuals.

## India F&O taxes
tags: fno tax india business income non speculative audit set off loss itr 3
In India, F&O profits are treated as non-speculative business income, taxed at your slab rate (not as capital gains). Losses can be set off against other non-salary income and carried forward for eight years if the return is filed on time; a tax audit may apply above turnover limits (F&O turnover is computed as the sum of absolute profits and losses, not the contract value). Keep records of every trade. This is general information, not tax advice.

## SEBI studies: how individual F&O traders fare
tags: sebi study fno losses retail traders 91% 88% loss makers statistics
SEBI's studies of individual equity-derivatives traders: FY22, 89% lost money; FY22–FY24 together, 93% lost (average about ₹2 lakh each); FY25, 91% lost, about ₹1.06–1.12 lakh crore in total; FY26 (published Aug 2026), 87.7% lost, about ₹91,685 crore in total, an average loss of about ₹1.17 lakh, with options over 90% of the losses. Before transaction costs 82% were losing, so costs alone pushed another ~6% into losses. Young traders fared worse. The few consistent winners are mostly proprietary desks and algorithmic firms with low costs and fast execution.

## US options: contracts, expiries and exercise
tags: us options spx spy qqq 0dte weekly options american european contract 100 shares section 1256 occ
A US equity option controls 100 shares. Stock and ETF options (AAPL, SPY, QQQ) are American-style and physically settled into shares; index options such as SPX and XSP are European and cash settled, with expiries every trading day (0DTE). Monthly options expire on the third Friday; weeklies expire on other Fridays and, for the busiest products, more days. Broad-based index options (SPX) get Section 1256 tax treatment in the US (60% long-term, 40% short-term). Short American options can be assigned any day, especially ITM calls before an ex-dividend date.

## US options: approvals, costs and the day-trading rule
tags: us options approval level commission orf occ fee pattern day trader pdt 25000 margin finra 4210
Brokers approve option trading in levels (covered calls first, spreads later, naked selling last). Commissions are often zero, with per-contract fees (about $0.50–0.65 at many brokers) and small regulatory fees (ORF, OCC clearing). The old pattern-day-trader rule ($25,000 minimum for frequent day trading in margin accounts) was removed by FINRA amendments to Rule 4210 approved by the SEC in April 2026, effective 4 June 2026, replaced by intraday margin standards; brokers have until October 2027 to adopt them, so rules differ between brokers for a while.

## US futures: index futures and micros
tags: us futures e-mini es mes micro e-mini nq cme futures margin
The CME's E-mini S&P 500 (ES) is $50 × the index; the Micro E-mini (MES) is $5 × the index, small enough for individual accounts; NQ/MNQ track the Nasdaq 100. Futures trade nearly 24 hours on weekdays, settle daily and expire quarterly (March, June, September, December), so positions are rolled about a week before expiry. Margins are set by the exchange and broker; intraday margins can be much lower, which makes leverage easy to overuse.

## What Kairos can do with F&O in Agora
tags: kairos fno options calculator option strategy payoff greeks agora fno support
Agora doesn't download option chains or trade futures and options (parked in LATER.md), so Kairos won't backtest or paper trade them. It can: explain any F&O concept or strategy from this playbook; work out a strategy's legs, estimated premiums, maximum profit and loss, break-evens, chance of profit and Greeks for any stock or index with its options calculator (using the stock's own recent volatility, so premiums are estimates, not quotes); and warn about costs, expiry and settlement rules. Ask: "iron condor on Nifty for 7 days" or "what's a covered call on TCS worth?".
