# Indian equities since 2015: what survived costs

Summarised from research the user gathered on 2026-11-03 (a Gemini deep-research report on
post-2015 Indian evidence). Treat every number as a hypothesis to test on Agora's data: several
sources are working papers, practitioner blogs or single studies, and published anomalies decay
after publication.

## Trend-following rules on liquid NSE stocks survived multiple testing
tags: india nse trend following donchian moving average crossover macd evidence multiple testing 2015 2025
On 78 NSE stocks with continuous F&O eligibility and large daily turnover, 2015 to April 2025, long-only equal-weighted, 0.05% round-trip costs, with a stationary block bootstrap and the Romano–Wolf stepdown correction across 13 rules (Pillai 2026): all seven trend rules survived. Best were the 20-day Donchian breakout (Sharpe about 1.26, alpha about 6.9 points a year over the Nifty) and the 10/50 SMA crossover (Sharpe about 1.26), then the slowed MACD 26/52/18 (better than 12/26/9 because it trades half as often), the 55-day Donchian, 20/100 and 50/200 crossovers. The reason offered: institutions split large orders over weeks and retail investors chase trends, so trends outlast the costs.
**In Agora:** lab families `donchian_breakout`, `sma_cross`, `macd_slow` replicate these on the user's own stocks; for a weak trend strategy, try a slower setting before adding filters.

## Plain mean reversion and indicator stacking failed after costs
tags: india rsi mean reversion bollinger confluence stacking turnover failed evidence
In the same test, RSI 30/70 and 25/75, and Bollinger-band rules, failed the multiple-testing correction (RSI 30/70 had negative alpha and a 34% drawdown). Only extreme RSI 20/80 survived, because it trades rare capitulation events (turnover 0.19 a year). A rule stacking several indicators had the highest turnover (12 times a year) and earned about 1% a year: more conditions meant more trades and more costs, not better trades.
**In Agora:** prefer one strong condition to several weak ones (the simplify idea); a reversion strategy should trade rarely and usually inside an uptrend (lab families `rsi_extremes`, `trend_dip_*`); check costs against gross profit in the first look.

## Liquidity decides whether an Indian strategy survives
tags: india liquidity universe f&o top 200 slippage impact cost small cap mid cap
Indian liquidity is top-heavy. Round-trip impact costs are about 0.05% in liquid F&O names but 0.30–0.50% a trade in mid- and small-caps. Momentum in illiquid stocks reverses quickly while momentum in the most liquid stocks persists for about 12 months (Chui, Ranganathan, Rohit and Veeraraghavan 2023). The recommendation: anything that trades monthly or more often should stay in the top 75–200 F&O stocks; smaller stocks only for slow, low-turnover factor portfolios.
**In Agora:** the lab ranks stocks by value traded; a universe idea for a short-term strategy should add liquid stocks, not small ones.

## Momentum and low volatility as portfolios
tags: india momentum low volatility factor portfolio rebalance quality momentum ranking evidence
Cross-sectional momentum is the strongest documented Indian premium (winner-minus-loser about 17% a year gross in the IIMA data, Agarwalla, Jacob and Varma 2017). A top-30 12-month momentum portfolio rebalanced every six months made about 14% a year after costs and taxes from 2006 to 2025 but fell 70% at worst (Desai and Joshipura 2025). Dropping the most speculatively traded names (high turnover relative to size) raised returns and cut the worst fall to about 42%. Low volatility rebalanced yearly beat the Nifty by about 2 points a year with a fifth less volatility and a shallower worst fall, but lagged in speculative bull markets (2017–18, 2020–25). Commercial factor indices lost most of their edge after launch (Lalwani 2023).
**In Agora:** ranking strategies (momentum, low volatility) belong in a portfolio sleeve with a trend filter; expect long losing stretches and judge them over full cycles.

## Costs and taxes in India
tags: india costs stt taxes stcg ltcg delivery intraday turnover
Delivery trades pay STT of 0.1% on both buy and sell; intraday 0.025% on the sell only. Modelled explicit costs were 0.11–0.20% a leg for delivery. Since 2024, gains held under a year are taxed at 20% and over a year at 12.5% above ₹1.25 lakh, so for frequent trading the tax can cost more than the trading charges. Agora's results include charges and slippage but not income tax.
**In Agora:** for India daily strategies, fewer and longer trades usually win after costs; say when a strategy's profit depends on very frequent trading.

## Things that need data Agora doesn't have
tags: india pairs trading futures post earnings drift pead fundamentals quality value
Pairs trading made money in India mainly through stock futures (cash shorts can't be held overnight) and with rolling, false-discovery-controlled pair selection; static pairs on cash stocks earned about 1.5% a year. Post-earnings drift (Nifty 500, a 6.4-point spread per quarter between the biggest positive and negative surprises) and value or quality factors need earnings and balance-sheet data. None of these can be tested in Agora today.
