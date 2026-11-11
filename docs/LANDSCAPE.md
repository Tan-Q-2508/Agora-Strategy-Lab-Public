# LANDSCAPE: the tools like Agora, and what Agora takes from each

Requested by the user on 2026-10-22: "find out similar tools currently available, both AI and
coded, and make Agora, Metis and Kairos the best version of all those tools." Researched the same
day (web search, the tools' own documentation and papers). Decision D-87.

The aim is not to copy any tool: it's to take each one's best idea that fits Agora's rules
(local, paper money only, no broker, plain English, one engine, AI never trades) and to say
plainly what Agora deliberately doesn't do.

---

## 1. The map

| Group | Tools | What they are best at |
|---|---|---|
| **AI research agents** | Microsoft **RD-Agent(Q)** (NeurIPS 2025), **AlphaAgent** (KDD 2025) and its 2026 successors (QuantaAlpha, AlphaMemo, XAlpha), QuantConnect **Mia** | An AI that proposes, codes, backtests and learns from feedback, unattended |
| **AI trading teams** | **TradingAgents** (multi-agent LLM framework), **ai-hedge-fund** (open source), **FinRobot** (AI4Finance) | Several AI roles (analysts, bull/bear researchers, risk manager, portfolio manager) that debate before a decision |
| **AI signal products** | **Trade Ideas** (Holly), **TrendSpider**, **Tickeron**, **Danelfin** | Daily AI-picked setups, automatic chart patterns, a 1–10 AI score per stock |
| **No-code strategy builders** | **Composer** (symphonies, "Trade with AI"), **Zerodha Streak**, **AlgoTest**, **Tradetron** | Plain-language or drag-and-drop strategies, one-click backtests, scheduled and drift-based rebalancing |
| **Quant platforms and engines** | **QuantConnect / LEAN**, Backtrader, Zipline, vectorbt, NautilusTrader, **Freqtrade** (+ FreqAI) | Serious backtesting: universe → alpha → portfolio construction → risk → execution; optimisation; bias checks |
| **Research and ranking** | **Portfolio123**, **Quantpedia** | Factor ranking systems; an encyclopaedia of 900+ documented strategy ideas with papers and out-of-sample backtests |
| **Portfolio and risk libraries** | **Riskfolio-Lib**, **skfolio**, PyPortfolioOpt, Alphalens / pyfolio / QuantStats, mlfinlab | Risk parity, hierarchical risk parity (HRP/HERC), shrinkage, tear sheets, López de Prado's methods |
| **Charting** | **TradingView** (Pine Script, strategy tester) | Charts, a huge indicator library, strategy tester |

## 2. What Agora takes from each (and where it lives)

| From | Their best idea | In Agora | Status |
|---|---|---|---|
| RD-Agent(Q) | A research → development → feedback loop, with a **bandit scheduler** choosing which direction to push next | Metis's loop (Phase 12) plus its **agenda**: four directions picked by Thompson sampling on what has paid off (D-83) | Built (Phase 14) |
| AlphaAgent | **Originality and complexity limits** against crowded, overfit factors (regularised exploration) | The **sameness check** (a near-copy becomes a revision, never a new strategy, D-79) and the **complexity limit** (no more than 6 entry rules a side; Metis can also *simplify*) | Built (Phases 13–14) |
| AlphaMemo / XAlpha | A structured **memory of the search** (what was tried, by family, with outcomes) | Metis's notebook, now grouped by direction and idea kind, with the success rate of each kind fed back into the agenda | Built (Phase 14) |
| QuantConnect Mia | An agent that **works for hours unattended** | Metis already runs on its own while Agora is open; now also without the AI helper, from its playbook (D-81) | Built (Phase 14) |
| TradingAgents / ai-hedge-fund | A **risk manager and a portfolio manager** that must approve before money moves | The portfolio's **allocator and risk rules are code** that must approve every sleeve (evidence screen, luck check, caps); the AI only proposes (D-84). A 4B model "debating" adds little; the checks are deterministic instead | Built (Phase 15) |
| FinRobot | Layered agents with financial chain-of-thought | Kairos (voice) + analyst (code) + Metis (research) already split this way (D-57, D-76) | Done |
| Trade Ideas (Holly) | Re-tests its strategies **every night** and only trades those that pass statistical thresholds | The opportunity scanner and the portfolio's review re-check every sleeve; sleeves that stop passing are wound down (D-86) | Built (Phase 15) |
| TrendSpider / Tickeron | Automatic trendlines and patterns with **odds from history** | Kairos's analyst: 41 chart patterns, 93 candles, each with its own history statistics (KAIROS §3, §8) | Done |
| Danelfin / Portfolio123 | A **ranking** of stocks by evidence | The opportunity list is ranked by unseen-year evidence and the luck check (PORTFOLIO §3); **ranking strategies** rank the index monthly by momentum or low volatility, alone or as a portfolio method (D-91). Fundamentals need data Agora doesn't have (parked) | Built (Phases 15–16); fundamentals parked |
| Composer | AI → strategy → backtest in one step; **scheduled and drift rebalancing**; a **dry run** that previews a rebalance | Kairos builds and backtests from plain English (Phase 9); the portfolio rebalances monthly or on drift, and shows a **preview** before anything moves | Built (Phase 15) |
| Streak / AlgoTest / Tradetron | No-code blocks; India-first costs; multi-leg options | Block builder (Phase 5), India charges in `Decimal` (D-38), options calculator (D-74). Live broker deployment is never built (D-02) | Done |
| QuantConnect LEAN | **Universe selection → alpha → portfolio construction → risk → execution** as separate parts | The portfolio follows the same split: opportunity scanner (universe + alpha) → allocator (portfolio construction) → caps and cash reserve (risk) → the shared engine (execution) | Built (Phase 15) |
| Freqtrade | **Look-ahead and recursive-formula checks** for strategies; hyperopt | The one-click **look-ahead check** (growing slices with later candles hidden, plus a more-history run) for any strategy, D-88. Parameter sweeps exist (Phase 4.6) and report the probability of overfitting (D-89) | Built (Phase 16) |
| vectorbt | Thousands of parameter combinations in seconds | The scanner runs one strategy over the whole universe in a single pass with independent positions (PORTFOLIO §3) | Built (Phase 15) |
| Quantpedia | A **library of documented strategies** with papers and out-of-sample results | Metis's quant library (D-81): the research behind each family of strategy, with "how to test it in Agora"; and Metis's discovery starts from the textbook strategies the user doesn't have yet | Built (Phase 14) |
| Riskfolio-Lib / skfolio / PyPortfolioOpt | Risk parity, **HRP**, shrinkage covariance | `backend/quant/portfolio.py`: Ledoit–Wolf shrinkage, inverse volatility, equal risk contribution, HRP, risk contributions, all golden-tested in-house (no new dependency) | Built (Phase 14) |
| pyfolio / QuantStats / Alphalens | Tear sheets: Sharpe confidence, drawdown distribution, factor decay | Probabilistic and deflated Sharpe, minimum track record, bootstrap and Monte Carlo drawdowns in `backend/quant/`; a **tear sheet** on every backtest (Sharpe band, other histories, trade order, rolling Sharpe, underwater periods, VaR/CVaR, years; D-89) | Built (Phases 14–16) |
| mlfinlab (López de Prado) | Deflated Sharpe ratio, CSCV, purged cross-validation, meta-labelling | The **luck check** (deflated Sharpe over the number of tries, D-82); the **probability of backtest overfitting** by CSCV on sweeps and Metis's tries (D-89); Kairos's trade check is a form of meta-labelling (D-71) | Built (Phases 14–16) |
| Trade Ideas (Holly), nightly | Re-tests every night and drops what stopped working | **Forward checks** of what Kairos and Metis saved and of portfolio sleeves on candles formed after saving, with undo (D-90) | Built (Phase 16) |
| TradingView | Pine Script, strategy tester | Cross-checking against TradingView stays in `LATER.md` | Parked |

## 3. What Agora deliberately doesn't do

- **Broker connections and real orders** (Composer, Streak, Tradetron, QuantConnect live): never
  (D-02). Agora is a lab; paper money only.
- **Cloud AI and accounts** (TradingAgents and ai-hedge-fund usually call cloud models): never;
  the AI is local (Ollama), and Agora works without it.
- **AI that decides trades** (several AI products): never (D-56). The AI proposes; code tests and
  decides; the shared engine trades.
- **Social sentiment and fundamentals data**: no free, reliable, local source yet (parked).

## 4. Phase 16: the best of the rest (built 2026-10-23, D-88 to D-91)

| Task | From | Why it's worth it |
|---|---|---|
| 16.1 A one-click look-ahead check for code strategies (run on growing slices and compare) | Freqtrade | Catches the most common mistake in hand-written strategies |
| 16.2 A tear sheet for any backtest: Sharpe confidence band, Monte Carlo drawdowns, rolling Sharpe, underwater periods | pyfolio / QuantStats | Shows how much of a result could be luck, in pictures |
| 16.3 Probability of backtest overfitting (CSCV) on sweeps and Metis's tries | mlfinlab | One number for "how likely is the best setting just the luckiest" |
| 16.4 A forward check of saved Metis revisions and portfolio sleeves on candles formed after they were saved (undo when they stop holding up) | Holly's nightly re-test | Already in `LATER.md` for Metis; becomes a task |
| 16.5 Cross-sectional strategies (rank all Nifty 50 stocks each month by momentum or low volatility, hold the top few) as a portfolio method | Portfolio123, Quantpedia | The best-documented stock anomalies are cross-sectional |

## Sources

- Microsoft RD-Agent(Q): arXiv 2505.15155, NeurIPS 2025 — https://arxiv.org/html/2505.15155v2
- AlphaAgent (KDD 2025) and 2026 successors: https://www.researchgate.net/publication/394259787 ·
  https://arxiv.org/pdf/2602.07085 · https://arxiv.org/pdf/2606.20625 ·
  https://arxiv.org/html/2607.08332v2 · survey https://arxiv.org/pdf/2608.31041
- TradingAgents: arXiv 2412.20138 — https://arxiv.org/html/2412.20138v4
- FinRobot: arXiv 2405.14767 — https://arxiv.org/html/2405.14767v1
- QuantConnect Algorithm Framework — https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview
- QuantConnect Mia — https://www.quantconnect.com/announcements/19846/your-ai-quant-developer/
- Composer AI and rebalancing — https://help.composer.trade/article/108-create-with-ai
- AI trading platforms 2026 overview — https://www.finder.com/stock-trading/ai-trading-bot ·
  https://chartinglens.com/blog/best-ai-trading-platforms-2026
- India builders (Streak, AlgoTest, Tradetron) — https://algotest.in/blog/algotest-vs-streak/
- Freqtrade (lookahead-analysis, recursive-analysis, hyperopt) — https://gitcode.com/GitHub_Trending/fr/freqtrade/blob/develop/README.md
- Quantpedia — https://quantpedia.com/how-it-works/faq/
- Portfolio123 and Danelfin — https://www.liberatedstocktrader.com/portfolio123-lab-test-review/ ·
  https://diyai.io/ai-tools/finance/reviews/danelfin-review/
- Riskfolio-Lib and skfolio (HRP) — https://riskfolio-lib.readthedocs.io/ ·
  https://skfolio.org/_modules/skfolio/optimization/cluster/hierarchical/_hrp.html
