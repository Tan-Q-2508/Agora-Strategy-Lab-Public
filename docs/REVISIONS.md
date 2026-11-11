# REVISIONS: one strategy, many revisions (revision control)

Requested by the user on 2026-10-22: "whenever Kairos or Metis improve an existing strategy the
strategy must be up-revved… revision control… I don't want them to create 1000 strategies a day
which turn out to be new versions of each other; instead they must be revision controlled unless
they are different strategies." Decisions D-79 and D-80. Phase 13.

---

## 1. The rules

1. **A strategy is its logic.** Two strategies are the *same strategy* when they trade the same
   market and the same core rules: the same indicators compared in the same direction, whatever
   the numbers (RSI(14) below 30 and RSI(10) below 25 are the same rule), give or take up to two
   extra filter conditions; or the same starter template; or, for code, the same code apart from
   its numbers. The Kairos brain is one strategy per market.
2. **Improving makes a new revision, never a copy.** When Kairos or Metis improve a strategy, the
   change is saved as its next revision (v1 → v2 → v3). Each revision records:
   - **who** made it: you, Kairos, Metis or the AI helper;
   - **what changed**, in plain words, worked out by code ("Added: ADX (14) at least 20 on
     buys"; "Stop loss: 3% → 2.5%"; "Stocks: added TCS");
   - **why** (the note) and the **evidence** (the test numbers that justified it);
   - which revision it came from.
3. **Nothing is ever overwritten.** Every revision is kept. **Restore** makes a new revision that
   copies an old one, so history only grows. A backtest, a paper session or a portfolio sleeve
   keeps the exact revision it started with.
4. **The same strategy on other stocks is an opportunity, not a new strategy (D-80).** Running
   RSI reversion on TCS instead of RELIANCE doesn't change the strategy. Such a pairing (a
   revision, its stocks, and settings when they were tuned for those stocks) is recorded in the
   **opportunities** list (`docs/PORTFOLIO.md` §3); it can be backtested, paper traded and put in
   the portfolio without adding a strategy.
5. **A different logic is a new strategy**, and the agents create few of them: Metis may add at
   most `metis.new_per_day` new strategies a day (default 2). Ideas beyond that wait in its
   notebook with a **Save it** button.

## 2. Who does what

| Situation | Before (Phases 9–12) | Now |
|---|---|---|
| Metis improves a strategy (filter, settings, simplify, stocks) | New version | New revision with author Metis, plain-English changes and evidence |
| Metis proposes a "new" strategy that is really an existing one | New "Metis · …" strategy | Re-judged against that strategy's current revision on that strategy's own stocks and period; saved as its next revision only if it did better ("Not a new strategy: it is a version of …") |
| Metis proposes a genuinely new strategy | New strategy | New strategy (within the daily limit) |
| Kairos's research ("find the best strategy for these stocks") picks a strategy you already have | New "… · tuned for …" strategy every time | An opportunity: your strategy on those stocks with the tuned settings, backtested; no new strategy |
| Kairos is asked to create a strategy you already have | New strategy | Uses yours ("you already have this one: #12"); different settings become its next revision |
| Kairos paper trades a strategy on other stocks | New version with those stocks | Same revision, the stocks are the session's own |
| Improve with Kairos | New version | New revision with author Kairos, changes and evidence |
| You save in the builder | New version | New revision with author You and the changes listed |

## 3. How code decides "same strategy" (`backend/strategy/lineage.py`)

Each visual rule becomes a token: side, left operand (indicator name and output, or price field),
direction (up: above / at least / crosses above; down: below / at most / crosses below) and the
kind of right operand (number, price, or the indicator's name). Numbers and indicator settings are
ignored. A number on the left is turned round ("30 above RSI" = "RSI below 30").

- **Similarity** = 0.75 × overlap of entry tokens + 0.25 × overlap of exit tokens (Jaccard),
  for the same market and kind; 0 otherwise.
- **Same strategy** when similarity ≥ 0.75, when one's entry tokens contain the other's with at
  most two extra (a filtered variant), or when both came from the same template.
- Code strategies: same when the code is identical once comments, spacing and numbers are
  removed. Kairos brains: same market = same strategy.

The structural check is deliberately simple and explainable; it was preferred to comparing the
trades two strategies take (slower, and harder to explain).

## 4. Revision metadata (migration 0008)

`strategy_versions` gains `parent_version_id`, `changes` (JSON list of plain-English lines),
`evidence` (JSON) and `source` (e.g. `metis-idea:12`, `kairos-improve:5`, `restore:3`), and
`created_by` accepts `metis`. The diff is computed by `backend/strategy/diff.py` when a revision is
saved (and on demand between any two revisions).

## 4a. Forward checks and undo (Phase 16, D-90)

A revision Kairos or Metis saved on its own is re-tested against the revision before it on the
candles formed after it was saved (`backend/checks/forward.py`). When it clearly stopped holding up,
the earlier revision's rules are saved again as the newest revision (source `forward-undo:<check>`,
note "Undid version N…"), on its own with **Undo what stops holding up** (`revisions.auto_undo`,
default on) or with the **Put version N back** button. Nothing is deleted, so **Restore** can bring
the undone version back. Only a revision that is still the newest is undone; if anyone saved a newer
one since, the check says so and changes nothing.

## 5. Screens

- **Strategy → Revisions** (was "Version history"): a timeline, newest first, each with its
  number, author badge, date, the changes in plain words, the evidence, **Compare with the one
  before**, **Open** and **Restore**.
- Strategy cards show the current revision and who made it ("v7 · Metis, 2 h ago").
- Metis's notebook links each saved idea to the revision it became.

## 6. API

- `GET /api/strategies/{id}/versions` → each version also has `parent_version_id`, `changes`,
  `evidence`, `source`, `author_label`.
- `GET /api/strategies/{id}/diff?from={version_id}&to={version_id}` → `{changes: [...]}`.
- `POST /api/strategies/{id}/versions/{version_id}/restore` → a new revision copying that one.
- `GET /api/strategies/{id}/family` → strategies that are the same logic (normally none, since
  agents no longer create copies; older copies from before Phase 13 show here).
