# PORTFOLIO: one budget, many strategies, and the hunt for new opportunities

Requested by the user on 2026-10-22: "I want Metis and Kairos to keep finding new opportunities to
invest: new stocks, new strategies. If I give Kairos and Metis $1,000 or ₹1 lakh (just an
example), it must be able to intelligently allocate resources to different stocks… not investing
$1,000 or ₹1 lakh on each stock but on a collective portfolio." Decisions D-84 to D-86. Phase 15.

Paper money only, like everything in Agora (D-02). The AI never sets a weight or places an order:
the allocation is tested code, and orders come from the strategies in the shared engine (D-56).

---

## 1. The idea in one picture

```
 opportunities (strategy revision × stocks, with unseen-year evidence)
        │  found by the scanner (code), Metis's research and Kairos's research
        ▼
 the allocator (code): screen → pick → weigh → fit to the budget
        │  every decision has a plain-English reason
        ▼
 the portfolio: one budget split into sleeves + a cash reserve
        │  each sleeve = one strategy revision on its stocks with its share of the money
        ▼
 the shared engine (D-04): backtest in lockstep, or paper trade live, rebalanced monthly
```

It follows the split QuantConnect's LEAN uses (universe → alpha → portfolio construction → risk →
execution), with the allocator's ideas from risk parity and López de Prado's hierarchical risk
parity (`docs/LANDSCAPE.md`).

A **sleeve** is a slice of the portfolio's money run by one strategy revision on its own stocks.
Sleeves share one budget: if the portfolio is ₹1,00,000, the sleeves' money plus the reserve add
up to ₹1,00,000. Inside a sleeve, each trade gets an equal share of the sleeve's money (its money ÷
its maximum open trades), so a sleeve's size is its risk budget and the allocator controls risk.

## 2. A portfolio's settings

| Setting | Meaning | Default |
|---|---|---|
| Market | India or US (one currency per portfolio) | the first of your markets |
| Budget | The paper money to allocate | ₹1,00,000 / $10,000 (any amount; small amounts get fewer sleeves) |
| Risk | Careful / Balanced / Bold | Balanced |
| Manage on its own | While paper trading, review the portfolio every month: retire sleeves that stopped working, add new opportunities that pass | On |

| Risk | Cash kept back | Most in one sleeve | Most sleeves | Volatility aimed for (a year) |
|---|---|---|---|---|
| Careful | 20% | 30% | 6 | 10% |
| Balanced | 10% | 40% | 6 | 15% |
| Bold | 5% | 50% | 6 | 22% |

## 3. Opportunities (`backend/portfolio/scan.py`)

An **opportunity** is a strategy revision on a set of stocks (with tuned settings when Kairos's
research tuned them), plus the evidence that it works there. Opportunities never add strategies
(D-80). They come from:

1. **The scanner** (code, no AI). For each of your strategies (up to 12 per market, the most
   recently changed first), one pass over the market's whole universe with independent positions
   (every stock trades as if alone), over Agora's default period split in time: the **study
   years** (first 70%) and the **exam years** (last 30%).
   - Stocks are chosen on the study years only: at least 4 trades, made money after costs, won at
     least 1.2× what it lost; the best five by average profit per trade × √trades.
   - The group is then judged on the **exam years**, which played no part in choosing it: at
     least 8 trades, made money after costs, won at least 1.1× what it lost.
   - Its own stocks are always checked too (the strategy as it is).
   - Kept groups become opportunities with their study and exam numbers, and a **luck check**
     (deflated Sharpe ratio, D-82) over the number of strategies scanned.
2. **Kairos's research** ("find the best strategy for these stocks"): when the winner is a
   strategy you already have, the result is an opportunity, not a copy (D-79).
3. **Metis**: its **opportunities** direction runs the scanner on its own, at least every fourth
   round (METIS §13), so new pairings keep appearing while Agora is open.

The **Opportunities** list on the Portfolio screen ranks them by evidence, with **Backtest**,
**Add to portfolio** and **Dismiss**. An opportunity that fails a later scan is marked stale.

## 4. The allocator (`backend/portfolio/allocate.py`)

Candidates: the current sleeves (when re-planning) and the open opportunities of the market. Each
candidate is run once as a sleeve (its revision, its stocks, equal-share sizing) over the default
period, giving daily returns and its study/exam numbers.

1. **Screen** (every exclusion has its reason): in the exam years it made money after costs, with at
   least 8 trades and at least 1.1× won to lost; and it passed the luck check (deflated Sharpe ≥
   0.5 over the number of candidates).
2. **Score**: its exam-year Sharpe ratio × its luck-check probability (evidence that is both strong
   and unlikely to be luck).
3. **Pick**, best score first, skipping a candidate whose study-year daily returns move with one
   already picked (correlation ≥ 0.7: "too similar to …, which is already in"), up to the most
   sleeves allowed, and no more than the budget can fund.
4. **Weigh** by risk: hierarchical risk parity (three or more sleeves) or inverse volatility (one
   or two), on a Ledoit–Wolf shrunk covariance of study-year daily returns; then tilted towards
   stronger evidence (× (0.5 + 0.5 × score ÷ best score)), capped per sleeve (redistributing the
   excess), and scaled down (more cash) if the estimated portfolio volatility is above the risk
   level's aim (volatility targeting).
5. **Fit to the budget**: each sleeve needs enough money for its trades to buy at least one share
   of its dearest stock (dearest price × maximum open trades × 1.05). A sleeve that can't be
   funded is dropped with the reason ("₹8,000 can't buy one share of MARUTI at ₹12,450 per trade")
   and the weights are worked out again. With a very small budget this naturally leaves one or two
   sleeves.

The plan lists each sleeve with its money, its share, its reasons ("steady: 9% volatility; held up
on unseen years: Sharpe 1.3; 84% chance it isn't luck"), the stocks traded by more than one sleeve,
what was left out and why, and the estimated volatility, return and diversification of the whole.

## 5. Backtesting a portfolio (`backend/portfolio/backtest.py`)

All sleeves run in **lockstep** in the shared engine (D-04), each with its own cash, over the same
period. On the first candle of each month (and when a sleeve drifts more than 25% from its target)
the portfolio **rebalances**: each sleeve's target is its weight × the portfolio's value; sleeves
above target hand their *free* cash to the reserve, sleeves below target receive from it. Open
trades are never cut to rebalance. Results: the portfolio's equity against the benchmark, every
metric of SPEC §6.3, each sleeve's contribution, the money moved, and the study/exam split.

Honesty note shown with every portfolio backtest: sleeves are chosen because they held up in these
years, so the backtest flatters the portfolio; the paper portfolio is the real test.

## 6. Paper trading a portfolio (`backend/portfolio/live.py`, D-86)

**Paper trade this portfolio** starts one paper session per sleeve (its revision, its stocks, its
money) and keeps the reserve as portfolio cash. While Agora is open the portfolio manager (code,
checked once a minute):

- **Rebalances** on the first market day of each month and on drift, moving only free cash, each
  move written in the portfolio's diary ("Moved ₹4,200 from RSI reversion to the reserve").
- With **Manage on its own** on, **reviews** the plan monthly: a sleeve whose live loss is more than
  twice its backtest's worst drop, or that the new plan no longer picks after a month, is
  **wound down** (no new trades; open trades end by their own rules; then its money returns to the
  reserve). New opportunities the plan picks get new sleeves funded from the reserve.
- Never force-sells to rebalance, never trades when Agora is closed (D-06), and only acts on a
  portfolio you started paper trading.

**Preview rebalance** shows exactly what would move before anything does (like Composer's dry run).

**Forward checks** (Phase 16, D-90): each sleeve is also re-tested, at most once a day, on the candles
formed since it was added, against what its exam years led to expect; one that clearly stopped
holding up (after 40+ trading days, a loss, ≥ 97.5% likely below its exam years) is wound down when
the portfolio manages itself, or offered with **Wind this sleeve down** (a draft portfolio's sleeve is
taken out of the plan). The card **Do the sleeves still hold up?** shows each sleeve's latest check.

## 7. Screens

**Portfolio** (sidebar, under Paper trading): your portfolios, **New portfolio** (market, budget,
risk), and for one portfolio: the allocation (donut and table with reasons), what was left out,
the backtest (equity vs benchmark, contribution by sleeve), **Paper trade this portfolio**, live
value and sleeves while paper trading, the diary of moves, **Preview rebalance**, **Re-plan**, and
the **Opportunities** list with **Find new opportunities**.

Kairos: the tool `portfolio` ("build me a portfolio with ₹1 lakh", "how is my portfolio doing?",
"rebalance my portfolio", "find new opportunities").

## 8. Built as

`backend/quant/` (statistics and portfolio maths, golden-tested), `backend/portfolio/`
(`scan.py`, `allocate.py`, `sleeves.py`, `backtest.py`, `live.py`, `service.py`), tables
`opportunities`, `portfolios`, `portfolio_sleeves`, `portfolio_moves` (migration 0009), API
`/api/portfolios` and `/api/opportunities` (API_CONTRACT), the Kairos tool `portfolio`. The engine
gained one method, `transfer`, that moves cash in or out of a sleeve; paper sessions can carry their
own stocks, settings and trade size (D-80, D-86).

## 9. Ranking portfolios (Phase 16, D-91)

Requested as part of making Agora the best of the tools like it (`docs/LANDSCAPE.md` §4, Portfolio123
and Quantpedia): the best-documented stock anomalies are *cross-sectional*, so a portfolio can also be
spread by a monthly ranking instead of by the allocator:

| How to spread it | What happens |
|---|---|
| **Best strategies** (mix, default) | The allocator above: your strategies and stocks that held up on unseen years |
| **Momentum** | Each month, hold the index's 10 strongest risers of the past year (leaving out the latest month), in equal shares |
| **Low volatility** | Each month, hold the index's 10 calmest stocks that are above their 200-day average, in equal shares |

A ranking portfolio has one sleeve: a **ranking strategy** (`backend/strategy/ranking.py`, a strategy
kind of its own) on the whole index (`symbols: []`), with the risk level's cash kept back and scaled
down when its volatility is above the risk level's aim. If you already have a ranking strategy with
the same logic it is reused; otherwise one is made from the starter (author Kairos, never a copy:
D-79). Its unseen-year evidence is shown; if it fails the usual screen the plan says so but follows
your choice. It backtests, paper trades, rebalances and is forward-checked like any portfolio, and it
re-picks its stocks inside the shared engine on the first trading day of each month.

Ranking strategies also work on their own (Strategies → templates: *Momentum: the 10 strongest
risers*, *Momentum: six months, top 5*, *Low volatility: the 10 calmest stocks*), and the opportunity
scanner judges each one as a whole on the index, so the allocator can mix a ranking into a "best
strategies" portfolio too. Kairos: "build me a momentum portfolio with 1 lakh".
