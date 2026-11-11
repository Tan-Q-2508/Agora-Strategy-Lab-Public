# Machine learning and AI in quant research

## Why machine learning overfits in finance
tags: machine learning overfitting signal to noise finance ml
Market returns are mostly noise: the predictable part is tiny and keeps changing. Flexible models (trees, neural networks) find patterns in noise easily, and a few hundred trades can't tell them apart from real ones. Use few features with a reason, strong regularisation, and honest out-of-sample tests; distrust anything with a Sharpe ratio far above what professionals earn.

## Purged cross-validation
tags: purged k-fold cross validation embargo leakage lopez de prado
Ordinary k-fold cross-validation leaks information when labels overlap in time (a 10-day trade label overlaps the next nine days). López de Prado (2018) purges training observations whose labels overlap the test fold and adds an embargo after it. Walk-forward testing avoids the problem by always testing on later data.

## Triple-barrier labelling
tags: triple barrier labelling profit take stop loss time label
Label each trade by which of three barriers it hits first: a profit target, a stop-loss, or a time limit (López de Prado, 2018). It matches how trades really end, unlike fixed-horizon returns, and makes labels comparable across volatility regimes when barriers are set in volatility units.

## Meta-labelling
tags: meta labelling secondary model filter bet sizing
A primary model (any strategy) proposes trades; a second model learns which of its signals tend to win and skips or shrinks the rest. It raises precision without changing the strategy's logic, and its probabilities can size bets.
**In Agora:** Kairos's trade check is a meta-labelling filter in the shared engine (D-71), proving itself on 30+ results before it acts.

## Feature importance
tags: feature importance mdi mda sfi permutation
Ask which inputs matter before trusting a model: mean decrease impurity (fast, biased towards noisy features), mean decrease accuracy (permutation, out of sample) and single-feature importance (one at a time). Features that only matter in-sample are overfitting.

## Fractional differentiation
tags: fractional differentiation stationarity memory features
Returns are stationary but forget the price level; prices remember but aren't stationary. Differencing by a fraction (for example 0.4) keeps much of the memory while making a series stationary enough for models (López de Prado, 2018).

## Walk-forward testing
tags: walk forward rolling optimisation out of sample stitched
Optimise on a window, test on the next, roll forward, and stitch the test pieces together: the stitched curve is what the research process would really have produced. It is slower than one split but closer to live trading.
**In Agora:** the walk-forward backtest mode and Kairos's research use it.

## What AI research agents have learned
tags: ai research agent llm rd-agent alphaagent alpha mining lessons
Recent AI quant agents loop hypothesis → code → backtest → feedback. Microsoft's RD-Agent(Q) (2025) adds a multi-armed bandit to choose which direction to work on next. AlphaAgent (2025) penalises ideas too similar to known ones and overly complex ones, and checks that each idea matches its stated hypothesis, to slow alpha decay. Later agents add structured memory of what was tried. The common lesson: the model's creativity helps only inside strict, automated, out-of-sample testing.
**In Agora:** Metis's agenda (bandit), sameness check (originality), complexity limit and notebook (memory).
