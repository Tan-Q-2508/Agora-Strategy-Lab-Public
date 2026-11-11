# GLOSSARY: plain words for the UI

Use the **UI word** in anything the user sees. Show the **one-line explanation** as a
tooltip (ⓘ) the first time a term appears on a screen.

| UI word | Avoid | One-line explanation |
|---|---|---|
| Strategy | Algo, system | A set of rules that decides when to buy and sell. |
| Backtest | Simulation run | Testing a strategy on past prices to see how it would have done. |
| Paper trading | Forward test, sim trading | Running a strategy live with fake money. |
| Paper account | Sim account | The pretend money a paper-trading strategy uses. |
| Total return | Cumulative return | How much the money grew or shrank overall. |
| Yearly return (CAGR) | Annualized return | The average growth per year, compounded. |
| Worst drop (Max drawdown) | MDD | The biggest fall from a high point before recovering. |
| Sharpe ratio | Risk-adjusted return | Return per unit of ups and downs. Above 1 is good; above 2 is very good. |
| Sortino ratio | Downside Sharpe | Like Sharpe, but only counts the bad swings. |
| Win rate | Hit ratio | The share of trades that made money. |
| Profit factor | Gross P/L ratio | Total money made on winners ÷ total lost on losers. Above 1.5 is healthy. |
| Average per trade (Expectancy) | Expectancy | What a typical trade made or lost after costs. |
| Charges | Fees, costs | Brokerage, taxes and exchange fees paid on trades. |
| Slippage | Impact cost | The small difference between the expected price and the price you'd really get. |
| Intraday | MIS | Bought and sold the same day. |
| Delivery | CNC | Bought and held for more than a day. |
| Stop-loss | SL | An exit that limits how much a trade can lose. |
| Take-profit | Target | An exit that locks in a gain at a set level. |
| Trailing stop | TSL | A stop-loss that moves up as the price rises. |
| Benchmark | Index | What you'd get by simply holding the Nifty 50 or SPY. |
| Out-of-sample | OOS | A slice of time the strategy wasn't tuned on, used as a fairer test. |
| Overfitting | Curve-fitting | Tuning rules so tightly to the past that they fail in the future. |
| Survivorship bias | (none) | Testing only on companies that are in the index today, which flatters results. |
| Delayed data | Lagged feed | Prices that arrive a little late. |
| Data freshness | Latency | How old the latest price is. |
| Timeframe | Interval, resolution | The length of each candle: 1 minute, 5 minutes, 1 day, etc. |
| Candle | Bar, OHLC | Open, high, low and close prices for one timeframe period. |
| Indicator | Study, TA | A calculation on prices, like a moving average or RSI. |
| AI helper | LLM, model | The free AI on your laptop that explains results and drafts ideas. |
| Kairos | Agent, bot | Agora's trading agent: reads charts, runs the lab for you and paper trades on its own. |
| Kairos desk | Autotrader, bot account | Kairos paper trading a list of stocks on its own, with fake money. |
| Thesis | Rationale | Why Kairos opened a trade: the signals, its stop, its target and its plan. |
| Review | Post-mortem | What happened to a trade against its plan, written when it closes. |
| Score | Signal strength | How bullish (up to +100) or bearish (down to −100) Kairos reads a chart. |
| Support / resistance | S/R | Price areas where falls (support) or rises (resistance) have stopped before. |
| Chart pattern | Formation | A shape in prices, like a flag or a double bottom, that often comes before a move. |
| Likely range | Forecast cone | Where the price will probably be: 8 times in 10 inside the range. |
| Signal weight | Coefficient | How much Kairos leans on a signal, from how often it worked (×1 is average). |
| Walk-forward test | WFO | Tuning on the past, testing on the next slice, and repeating: a strict honesty check. |
| News risk | Event risk score | How dangerous today's news is for a market, from 0 (calm) to 100 (severe). |
| Watchful / elevated / severe | Risk regime | The news-risk levels: 25+, 50+ and 75+ out of 100. |
| News guard | Kill switch, circuit breaker | Kairos's fixed rules for bad news: stop opening trades, cut losers, close longs. |
| Severity | Impact level | How much this kind of news has moved whole markets, from 1 to 5 bars. |
| Risk-off / risk-on | Sentiment shift | News that makes investors sell first (risk-off) or buy (risk-on). |
| Setup | Signal, trigger | A named price event traders scan for, like a gap or a false breakout. |
| Harmonic pattern | XABCD | A zig-zag chart pattern whose legs follow Fibonacci ratios, like the Gartley or the bat. |
| Trade check | Meta-labelling, trade filter | Kairos judging each signal from what it learned, and skipping ones that tend to lose after costs. |
| Predicted candles | Price projection | The likely next candles Kairos draws inside its forecast range; a shape, never a promise. |
| Break-even win rate | Required hit rate | How often a strategy must win just to not lose money, given the size of its wins and losses. |
| Option premium | Option price | What an option costs; the buyer pays it, the seller keeps it. |
| Metis | AI researcher, autoML | Kairos's AI researcher: thinks up ideas to improve strategies and keeps only the ones that hold up on years it never saw. |
| Study years | In-sample, training set | The first 70% of a strategy's period: what Metis is shown when it thinks. |
| Exam years | Out-of-sample, holdout | The last 30% of the period: Metis never sees them; every idea is judged there. |
| Held up | Passed validation | An idea that did better after costs on the exam years, by Agora's fixed rules. |
| Version (revision) | Revision, commit | One saved state of a strategy. Improvements by you, Kairos or Metis add a version; old ones are kept and can be restored. |
| Same strategy | Strategy family, lineage | Two strategies with the same rules apart from their numbers (or a filter or two): Agora keeps them as one strategy with versions. |
| Luck check | Deflated Sharpe ratio | The chance a result is real rather than the luckiest of the many ideas tried. |
| Playbook | Expert heuristics | A senior quant's first experiments, written as code; Metis tests them even without the AI helper. |
| Opportunity | Deployment, candidate | One of your strategies on stocks where it held up on years it wasn't chosen on. |
| Portfolio | Multi-strategy allocation | One budget split across several strategies and stocks, with some cash kept back. |
| Sleeve | Sub-account, allocation bucket | The slice of a portfolio's money one strategy trades on its stocks. |
| Allocator | Portfolio construction | Agora's tested code that decides how much money each sleeve gets, with a reason for each. |
| Rebalance | Reweighting | Moving spare cash between sleeves so each is back near its share; open trades are never cut. |
| Volatility | Risk, standard deviation | How much something swings in a year; 15% means a typical year's swing of about that size. |
| Look-ahead | Look-ahead bias, data leakage | Using a candle that hadn't closed yet. The look-ahead check proves a strategy doesn't. |
| Depends on history | Recursive-formula bias, warm-up dependence | Signals that change with how much older history is loaded, so a backtest and paper trading disagree. |
| Tear sheet | Tear sheet, performance report | A backtest's page of "how much could be luck": the Sharpe range, other histories, the deepest falls. |
| Sharpe range | Bootstrap confidence interval | The span of Sharpe ratios the same kind of days could have given (90% of reshuffles fall inside). |
| Chance it is really above zero | Probabilistic Sharpe ratio (PSR) | How likely the strategy's true Sharpe ratio is above zero, allowing for lopsided and fat-tailed days. |
| Other histories | Bootstrap, Monte Carlo | The daily results reshuffled in blocks, many times, to see the range of outcomes the strategy could have had. |
| Underwater | Drawdown period | Time spent below an earlier high, from the high to the recovery. |
| A bad day / the worst 5% of days | Value at risk (VaR) / expected shortfall (CVaR) | The loss of a bad day, and the average loss of the worst 5% of days. |
| Chance the best is just the luckiest | Probability of backtest overfitting (PBO, CSCV) | Over many tries, how often the best on one half of the history was in the bottom half of the other. |
| Forward check | Out-of-sample monitoring, paper re-test | Re-testing what Kairos or Metis saved on the candles formed after it was saved. |
| Holding up / slipping / stopped holding up | Live validation status | Better than before on the new candles / worse but not clearly / clearly worse: put back or wound down. |
| Ranking strategy | Cross-sectional strategy | A strategy that compares the stocks with each other each month and holds the best-ranked few. |
| Momentum | Cross-sectional momentum (12-1) | The stocks that rose most over the past year (leaving out the latest month). |
| Low volatility | Low-volatility anomaly | The calmest stocks: smaller daily moves. |

Number formatting: India uses lakh/crore grouping (₹12,34,567.89; "₹12.3 L", "₹1.2 Cr");
US uses $1,234,567.89 ("$1.2M"). Percentages show a sign: +4.2%, −1.8%.

## Phase 18 words
| Say | Instead of | Meaning |
|---|---|---|
| bigger chart | higher timeframe, HTF | The same stock on a longer candle (weekly for a daily chart), read on its last finished candle |
| work on their own | autopilot mode | Kairos and Metis start when Agora opens without being asked |
| booming sector | sector breakout, bloom | Most of a sector's stocks rising together, unusually strongly, beating the market |
| leading / lagging | RRG quadrant | Beating / trailing the market lately, and getting stronger / weaker |
| world event | geopolitical scenario | A kind of news (a war, tariffs, an oil cut…) Kairos knows how markets usually take |
| likely to do better than the market | positive tilt | What the world map expects for a stock, beyond the whole market |
| why did it move | attribution | The news, world event or other market most likely behind a sudden move |
| factor list | smart-beta screen | Stocks picked by one trait (momentum, calm, near highs…) the way quant funds pick |

