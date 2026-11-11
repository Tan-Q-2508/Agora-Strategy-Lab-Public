# The research method of a senior quant

## The research loop
tags: research method hypothesis test falsify loop process scientific
Professional quant research runs a loop: observe something in the evidence, state a hypothesis with a reason, design the smallest test that could prove it wrong, run it on data the idea was not shaped on, and record the result whether it worked or not. The record matters as much as the winners: it tells you which kinds of ideas pay off and stops you retrying failures. Arnott, Harvey and Markowitz's "A Backtesting Protocol in the Era of Machine Learning" (2019) is the standard checklist.
**In Agora:** this is exactly Metis's round: the brief (evidence from the study years), the ideas (hypotheses), the trial (code, on the exam years), the notebook (the record).

## An economic reason first
tags: economic rationale hypothesis why story behavioural risk premium
Before testing, a senior quant asks why the edge should exist and who is on the other side: a risk premium (being paid to bear a risk others avoid), a behavioural bias (under-reaction, over-reaction, herding, the disposition effect), or a structural friction (index rebalancing, forced selling, costs that keep others out). Ideas without a reason are far more likely to be data-mined luck, and they decay fastest.
**In Agora:** write the reason in the idea's "why". "Losers cluster in falling markets, and dip-buying works when the trend is up because sellers are exhausted" is a reason; "ADX 23 looked best" is not.

## One change at a time
tags: one change controlled experiment attribution ablation
Change one thing per experiment, so a better or worse result can be traced to it. Bundling a new filter, a new stop and new settings into one test makes it impossible to tell which part helped, and invites keeping a harmful change that rode along with a helpful one.
**In Agora:** each Metis idea is one filter, one set of setting changes, one simplification, or one change of stocks.

## Simple beats clever
tags: simplicity occam complexity overfitting parameters rules degrees of freedom
Every extra rule or setting is another chance to fit noise. Strategies with few rules and round settings tend to hold up out of sample; ones with many finely tuned conditions usually don't. A useful habit: after adding a filter, later try removing each old rule; if results hold without it, keep the simpler version. AI alpha-mining agents such as AlphaAgent (2025) add an explicit complexity penalty for the same reason.
**In Agora:** Metis may hold at most six entry conditions per side, and the "simplify" idea removes one; it is kept when the exam years do at least as well.

## Most ideas fail
tags: base rate failure rate expectations false discovery
In real research most ideas don't survive honest testing; a hit rate of one in five to one in ten is normal. Harvey, Liu and Zhu (2016) argued that, given how many factors have been tried, a new one should clear a t-statistic of about 3 rather than 2. Expect failures, record them, and be suspicious of a streak of successes.
**In Agora:** the notebook keeps every failed idea; the luck check raises the bar as tries add up.

## Study years and exam years
tags: holdout out of sample in sample train test split exam study
The cleanest guard against overfitting is a holdout: shape ideas on one period (the study years) and judge them once on another (the exam years) that played no part in shaping them. Looking at exam results and then trying again slowly leaks the exam into the ideas, which is why the number of tries must be counted.
**In Agora:** Metis sees only the first 70% of each period; code judges on the last 30%, and its notebook shows verdicts, never exam numbers.

## Reading a result like a referee
tags: referee checklist robustness skeptic review results
Before believing a backtest, ask: how many trades (fewer than about 30 says little)? Do a few big winners make all the profit? Does it work in each half of the period and on most of the stocks? Do costs and next-candle fills leave anything? Is the drawdown survivable? Is there a reason? How many variants were tried before this one?
**In Agora:** the honesty panel, Kairos's review and Metis's luck check answer most of these for every result.

## When to stop tuning
tags: tuning optimisation parameter sweep plateau isolated peak
Good settings sit on a plateau: neighbouring values do nearly as well. An isolated peak (one setting great, its neighbours poor) is almost always noise. Stop tuning when improvements become small relative to the noise, and prefer the middle of a plateau to its highest point.
**In Agora:** the parameter sweep warns about isolated peaks; Kairos's research picks a steadier neighbour.
