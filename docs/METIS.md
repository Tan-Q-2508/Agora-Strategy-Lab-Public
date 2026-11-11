# METIS: Kairos's AI researcher

> *Metis* (μῆτις) is the ancient Greek word for **wise counsel and cunning intelligence**: the
> kind of thinking that comes up with a plan nobody handed you. In the myths Metis was the
> Titan of good advice, and the mother of Athena, the goddess of wisdom. Kairos knows *when* to
> act; Metis thinks up *what to try*.

Metis is an optional part of Kairos (Phase 12). When the user switches it on, it keeps
researching on its own while Agora is open: it reads how the user's strategies have been doing,
**thinks up ideas** to make them better (or new strategies to try), **tests every idea** on
years it never saw, and **keeps only what holds up**, saving it as a new strategy version and
teaching Kairos what it found. Nobody has to tell it what to do. The user can give it a focus
("my breakout strategy loses too often"), but doesn't have to.

Requested by the user on 2026-10-22: "I wanted Kairos to be an AI agent that starts to learn on
its own… go with option A [the AI researcher]… if I toggle it on it must keep researching on its
own without me instructing it… everything should be automatic." Decisions D-76 to D-78.

---

## 1. The one idea: the AI proposes, the code tests

Kairos's learning so far (KAIROS §8, §16–18) is measurement: statistics that update from
results. That learns *how much* to trust known signals, but it never invents anything new.
Metis adds the missing part, the **creative step**, without giving up honesty:

| Step | Who does it | Why |
|---|---|---|
| Gather the evidence | Code (`brief.py`) | Exact numbers, and only from the *study* years (§3) |
| Think up ideas | **The AI model** (`think.py`), with thinking on | Creativity: spotting a pattern in the evidence and proposing a fix |
| Turn each idea into rules | Code (`trial.py`), and the AI-draft loop for new strategies (D-52) | Only valid Agora rules can be tested |
| Test each idea | Code: the shared backtest engine (D-04) | Numbers come from code, never from the model (D-57) |
| Judge it | Code: fixed rules on the *exam* years (§4) | The AI can't talk an idea into being kept |
| Keep it / apply it | Code (`apply.py`) | A new version (old ones kept) or a new strategy |
| Remember | The notebook + Kairos's lessons | The next round's evidence includes every past verdict |

So Metis *learns*: each round's brief includes its own notebook (what it tried, what held up,
what failed and by how much), so it stops repeating failed ideas and builds on the ones that
worked. What it learns ends up as rules in ordinary strategies that the user can read, backtest
and undo.

**Metis never trades.** It never places, sizes or cancels an order, and never starts or stops a
paper session (D-56). Kairos's desk and the trade check are unaffected.

## 2. What Metis can try

Each round Metis proposes up to three ideas, each one of:

| Kind | What it changes | Works on |
|---|---|---|
| `filter` | Adds one or two entry conditions ("only buy when ADX (14) is at least 20"), for long and/or short entries | Visual strategies |
| `tweak` | Changes settings: a strategy's own parameters (within their limits) and, for visual strategies, the stop loss %, take profit %, trailing stop % or time limit in candles | Visual and code strategies (code is never rewritten, only its parameter defaults) |
| `new_strategy` | A new strategy idea in plain English for a few stocks; the AI-draft loop turns it into rules (D-52) | Any market the user has |
| `simplify` (Phase 14) | Removes one entry condition: simpler rules that do as well are better (Occam; AlphaAgent's complexity limit) | Visual strategies |
| `universe` (Phase 14) | Adds or drops up to three stocks from the strategy's own list, when the stocks' character fits the strategy better | Visual and code strategies |

A filter condition compares an indicator with a number ("ADX (14) at least 20") or, since Phase 14,
an indicator with the price ("close above SMA (200)": `{"indicator": "sma", "params": {"period":
200}, "op": "below", "price": "close"}` reads "SMA (200) below the close"), the classic trend
filter. A strategy may have at most six entry conditions per side; beyond that a filter is
"couldn't test: too many rules already; try simplifying".

The Kairos brain (`kind: "kairos"`) is never changed by Metis: it learns by itself (D-61).

## 3. What Metis sees (the brief, `backend/metis/brief.py`)

For each strategy it studies (up to four a round: the one named in the focus first, then the
most recently backtested), code runs the latest version over its usual stocks and period (its
latest backtest's, or Agora's default) and splits the period in time:

- **Study years**: the first 70% of the period. Metis sees trades, win rate, money after
  costs, costs, average win and loss, exits, and Kairos's review of *these trades only*
  (the market conditions where they failed, `review.py`).
- **Exam years**: the last 30%. **Metis sees nothing from them.** They are kept for the test.

The brief also holds the strategy's rules in plain words, its parameters with their limits, the
indicators it may use (the catalog keys with their settings), the user's focus, and Metis's
notebook (the last 15 ideas with their verdicts and **study-year** numbers; never their exam-year
numbers, which, read round after round, would slowly teach Metis the exam). It deliberately does **not** include Kairos's lessons
or signal statistics, because those were measured on all the years, exam years included.

## 4. The test and the verdict (`backend/metis/trial.py`)

Every idea is backtested over the same stocks and period as its baseline, with the same costs,
slippage and starting money, in the shared engine. Trades are split by entry time at the same
70% point. The verdict is fixed in code:

**Ideas that change a strategy (`filter`, `tweak`)** hold up only if, after costs:
1. in the exam years it made more money than the current version, by at least 0.1% of the
   starting money;
2. in the study years it made at least as much (an idea that doesn't even help where it was
   thought up is luck);
3. in the exam years it kept at least 5 trades and 30% of the current version's trades.

**New strategies** hold up only if they made money after costs in both the study and the exam
years, with at least 5 trades in each, and won at least 1.1× what they lost in the exam years.

**Simplify** ideas hold up when, after costs, the exam years made at least as much as the current
version and the study years at least 95% as much (fewer rules at equal results win).
**Universe** ideas are judged like other changes, on the same period with the new stock list.

**The luck check (Phase 14, D-82)** applies to every change and new strategy on top of the rules
above: the deflated Sharpe ratio must be at least 0.5 (§12).

Anything else is "didn't hold up", with the numbers, and that is recorded too: a failed idea
is a lesson. Ideas that can't be turned into valid rules are "couldn't test" with the plain
reason (an unknown indicator, a setting outside its limits). An idea already tested on the same
strategy version is skipped as a repeat.

Testing many ideas finds some by luck (multiple testing). The two-part rule, the minimum gain,
and the exam years staying unseen keep that down; the notebook shows every idea tried, not only
the winners, so the user sees the full record. (Kept ideas are re-checked on new candles since Phase 16: §16.)

## 5. Keeping what held up (`backend/metis/apply.py`)

With **Metis saves what holds up** on (setting `metis.apply`, default on):
- `filter` / `tweak` / `simplify` / `universe`: saved as the strategy's next **revision** with
  author Metis, the plain-English changes and the evidence (`docs/REVISIONS.md`, D-79). Every
  earlier revision is kept; **Restore** brings any back.
- `new_strategy`: first the sameness check (D-79). If it is really a version of a strategy you
  have, it is judged again against that strategy's current revision on that strategy's own stocks
  and becomes its next revision only if it did better. (Trying a strategy on other stocks is the
  opportunity scanner's job, `docs/PORTFOLIO.md` §3.) Only a genuinely different strategy is saved
  as a new strategy "Metis · …", at most `metis.new_per_day` a day (default 5 since D-118; was 2) when Metis saves on
  its own; the **Save it** button isn't limited.
- Either way, a full backtest of the kept version is started so the user can open it, and
  Kairos gets a lesson written by code from the test's numbers ("Metis found that … on unseen
  years: ₹12,300 more after costs, win rate 58% vs 51%"). Kairos's prompts already include its
  most relevant lessons, so Kairos now knows what Metis found.

With it off, ideas that held up wait in the notebook with a **Save it** button.

## 6. When Metis works (`backend/metis/researcher.py`)

- Only while Agora is open (D-06): a background thread that lives and dies with the app.
- Only when switched on (`metis.enabled`, **off by default** because it uses the graphics card)
  or when the user clicks **Research now**.
- A round starts `metis.every_minutes` after the last one started (default 1, so Metis works
  all the time, D-103). The first one starts a minute after Agora opens, or within 30 seconds of the switch being turned on (the thread checks
  twice a minute).
- Without the AI helper (Phase 14, D-81) it doesn't stop: it runs **playbook rounds**, testing
  the expert's first experiments (§11) and running the opportunity scanner, and says that its own
  ideas need the AI helper.
- It **waits** while a backtest,
  research, training or improvement job is running, and for a minute after the user last
  talked to Kairos (so the graphics card answers the user first).
- Practice-data sessions (tests, the cloud) don't start the thread unless asked
  (`AGORA_METIS=1`), like the always-on learner.
- A round never takes the app down: any failure is logged and the round is marked failed with a
  plain reason.

## 7. Thinking

The model is asked to think first (Ollama `think: true`), then answer with JSON: a few sentences
on what it noticed, and the ideas. If the answer isn't valid JSON, Metis asks once more with
the JSON schema enforced (Ollama structured output). Metis's thinking and reasoning are saved
with the round and shown, labelled as the AI's own words (numbers in them are not checked); its
verdicts are code's.

## 8. Screens

- **Metis** screen (`/metis`, sidebar under Kairos desk): the switch, what Metis is doing now
  ("Thinking…", "Testing idea 2 of 3…", "Next round in 14 min"), **Research now**, the focus box,
  totals (ideas tested, held up, saved), and the **notebook**: each idea with its kind, Metis's
  reasoning, the verdict and the study/exam numbers side by side, links to the strategy, the new
  version and its backtest. Each round shows **How Metis thought**.
- **Settings → Kairos**: a Metis card with the switch, pace, "saves what holds up" and the focus.
- **Kairos chat**: the tool `metis` answers "what has Metis found?", switches it on or off,
  sets a focus and starts a round ("Metis, look into my RSI strategy").
- Without the AI helper the screen explains that Metis needs it, with a button to Settings → AI
  helper.

## 9. Built as

`backend/metis/`: `brief.py` (evidence), `think.py` (prompt, thinking, JSON parsing),
`trial.py` (ideas → rules, backtests, verdicts), `apply.py` (versions, strategies, lessons),
`notebook.py` (storage), `researcher.py` (the thread and a round). Tables `metis_rounds` and
`metis_ideas` (migration 0007). API under `/api/metis` (API_CONTRACT). Settings `metis.enabled`,
`metis.every_minutes`, `metis.apply`, `metis.focus`. Kairos tool `metis`.

## 10. Tests (offline, fake AI)

- The brief never contains a number from the exam years (checked against a run cut at the split).
- Scripted ideas: a filter, a tweak, a new strategy, a broken idea and a repeat each get the
  right verdict, by hand-checked rules, and only held-up ideas are saved.
- JSON that fails to parse triggers the structured retry; nonsense is "couldn't test".
- The loop waits when the AI isn't ready, when a job is running, and when it's off.
- The notebook feeds the next brief; kept ideas become Kairos lessons.
- API, the Kairos tool and the router; the Metis screen in Vitest; a Playwright test that switches
  Metis on, clicks Research now and sees the notebook fill in on practice data. With nothing
  scripted, the fake AI answers Metis with a practice reply (a filter on the first strategy it was
  shown and a new strategy), so the whole flow runs without Ollama.

---

## 11. Metis the senior quant (Phase 14, D-81)

Requested by the user on 2026-10-22: Metis must already have vast knowledge and skills of trading
and trading research, like a researcher with a PhD from a top university and 10–15 years of quant
finance at top firms, clear on all the concepts and able to use them, so it doesn't start from
scratch.

**What that can honestly mean.** A 4-billion-parameter model on a 6 GB graphics card can't hold a
PhD in its head, and fine-tuning doesn't fit the laptop (D-61). So Metis's expertise is built the
way Kairos's is (D-57): the knowledge and the methods live in Agora, tested, and the model is given
the right part at the right time. Four layers:

| Layer | What it is | Where |
|---|---|---|
| **The library** | The quant curriculum a senior researcher knows: the research method, backtest statistics and multiple testing, the documented anomalies and factors (momentum, reversal, low volatility, trend following, seasonality…) with their papers and how they decayed after publication, volatility and regimes, mean reversion and pairs, portfolio construction (Markowitz and its errors, shrinkage, risk parity, HRP, Kelly, volatility targeting), risk and drawdowns, costs and turnover, India and US market structure, machine learning pitfalls, and what the 2025–26 AI research agents learned. Each section ends with **how to test it in Agora**. | `backend/metis/library/*.md`, retrieved by relevance (BM25, like Kairos's playbook) |
| **The toolkit** | The methods as golden-tested code: Sharpe and its standard error, probabilistic and deflated Sharpe ratio, minimum track record, block bootstrap, Monte Carlo of trade order, autocorrelation, variance ratio, Hurst exponent, mean-reversion half-life, volatility estimators, Ledoit–Wolf shrinkage, inverse volatility, equal risk contribution, hierarchical risk parity, Kelly | `backend/quant/` |
| **The expert's first look** | The checklist a senior quant runs on any strategy, turned into code: break-even win rate against the actual one, costs against gross profit, trade count and statistical confidence, where losers cluster (Kairos's review), exits mix, dependence on a few big wins, and whether the stocks trend or mean-revert (variance ratio, Hurst) compared with what the strategy needs. Each finding comes with the **first experiments** an expert would run, written as ready-to-test ideas | `backend/metis/diagnose.py` |
| **The discipline** | The luck check on every verdict (§12), the exam years never shown, the complexity limit, and simplification as a first-class move | `trial.py` |

Each round, the brief now opens with **"A senior quant's first look"** (findings and first
experiments for each strategy, from code) and **"From your library"** (the three to five sections
that match the findings), so the model reasons like an expert from the first round. Its persona
gained the research method: state a hypothesis with an economic reason, prefer simple rules, test
one change at a time, distrust results that depend on a few trades, mind costs and turnover, and
expect most ideas to fail.

## 12. The luck check: deflated Sharpe ratio (D-82)

Trying many ideas on the same exam years finds some by luck. The fix a senior quant uses is the
**deflated Sharpe ratio** (Bailey and López de Prado, 2014): how likely is it that the result's
true Sharpe ratio beats the best of N lucky tries?

- For a change: the daily difference between the idea's and the current version's returns in the
  exam years. For a new strategy: its own daily returns in the exam years.
- N = the ideas already tested on that strategy (or, for new strategies, in that market), plus
  this one. Under "no idea works", the best of N tries has an expected Sharpe ratio of
  √(1/T) × ((1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e))), with T the number of exam days and γ ≈ 0.5772.
- The probabilistic Sharpe ratio against that bar, allowing for skew and fat tails, must be at
  least 0.5 ("more likely real than luck"); the probability is shown on every verdict.

The bar rises slowly as Metis tries more ideas on the same exam years, which is exactly the
multiple-testing problem METIS §4 warned about. Moving the exam years forward as history grows
("a fresh exam") stays in `LATER.md`.

## 13. The research agenda: four directions (D-83)

The user asked whether Metis only improves strategies or also searches for new ones: it does both,
on a plan. Each round picks one direction:

| Direction | What Metis does | Needs the AI helper |
|---|---|---|
| **Improve what's in use** | Strategies in running paper sessions, the Kairos desk's market aside, and portfolio sleeves, first | For its own ideas (playbook ideas without) |
| **Improve the others** | Your other strategies and Kairos's, the most recently tested first | Same |
| **Discover** | New strategies: first the textbook strategies (Agora's 28 templates) you don't have yet, then the AI's own ideas, which are told which strategy families you already have so they propose something different | Templates no; own ideas yes |
| **Opportunities** | Runs the opportunity scanner: your working strategies on new stocks (`docs/PORTFOLIO.md` §3) | No |

The direction is chosen like RD-Agent(Q)'s scheduler: **Thompson sampling** on each direction's
record (ideas kept ÷ ideas tested, starting from one success and one failure), with three fixed
rules on top: a focus that names a strategy means "improve" on it; strategies in use get a round at
least every third round; opportunities at least every fourth. The random draw is seeded by the
round number, so a round can be replayed in tests.

## 14. Rounds without the AI helper (D-81, amends D-77)

When the AI helper isn't ready, Metis no longer just waits: it runs **playbook rounds** that test
the first experiments from the expert's first look, the templates you don't have, and the scanner.
Repeats are skipped, so once the playbook is exhausted a round says "nothing new to test from the
playbook; switch on the AI helper for Metis's own ideas". With the AI helper, the model sees the
playbook's experiments as hints and proposes its own; if its answer can't be used, the playbook's
experiments are tested instead, so no round is wasted.

## 15. Built as (Phase 14 additions)

`backend/quant/` (`stats.py`, `resample.py`, `series.py`, `portfolio.py`, `sizing.py`),
`backend/metis/library/*.md` and `library.py`, `backend/metis/diagnose.py`,
`backend/metis/agenda.py`; `think.py` (persona, `simplify`, `universe`, price conditions),
`trial.py` (luck check, simplify, universe, complexity limit, sameness check for new strategies),
`apply.py` (revisions, opportunities, the daily limit). Migration 0008 adds `direction` to
`metis_rounds` and the new idea kinds. Setting `metis.new_per_day`. The Metis screen shows the
round's direction, the luck check on each verdict, and the library sections it read.

## 16. Phase 16: the overfitting check and forward checks (D-89, D-90)

- **The overfitting check.** Every tested idea now keeps its daily returns over the whole test
  period (and its baseline's). Once a strategy has at least 8 tries (ideas plus the versions they
  were tested against), the probability of backtest overfitting (CSCV: cut the history into 16
  pieces, and for every way of choosing half, see whether the best try on that half is in the top
  half of the other) must be below 50% for a change to be kept: otherwise Metis is finding luck on
  those years, and the change waits for new candles. New strategies are checked the same way over
  the new strategies tried in their market. The verdict lists it beside the luck check, and the
  notebook shows the sentence.
- **Forward checks.** What Metis (and Kairos) saved on its own is re-tested on the candles formed
  after it was saved, against the version before it, at most once a day while Agora is open; a
  version that clearly stopped holding up is put back (`revisions.auto_undo`, default on) and Kairos
  gets a lesson. The Metis screen's card **Do saved improvements still hold up?** lists them. This
  replaces the "re-checking kept ideas on new data" item that was parked in `LATER.md`.
- Ranking strategies (D-91) are left to the opportunity scanner and the portfolio: Metis's ideas
  (filters, tweaks) don't apply to them.


## 17. Several timeframes, sectors and the world (Phase 18, D-94, D-97, D-99)

- **On by default** (`metis.enabled`): with the autopilot, Metis starts researching when Agora opens;
  it thinks with the AI helper as soon as Ollama is ready and runs playbook rounds until then.
- **Bigger-chart filters**: an idea's filter condition may carry `"chart": "1w"` (or `1mo`, `1d`,
  `1h`…) to be read on a bigger chart of the same stock; the expert's first look proposes "Only buy
  while the weekly trend is up" for a daily strategy that loses more often than it wins and never
  looks at the bigger chart. Judged like any filter (unseen years, luck check).
- **Its watchlists**: after each round, `metis/lists.py` saves "Metis · Booming: <sector>" (a
  sector's leaders when it booms) and "Metis · World: <event>" (the stocks the world map expects to
  beat the market), with the reason and a note per stock; the opportunity direction scans the stocks
  these lists bring in.
- **Library**: `library/world.md` (industry momentum, bigger-timeframe filters, event studies,
  geopolitical risk and returns, why oil moves matters). The brief does not include today's sector
  or world readings, so the unseen-years test stays clean.

## 18. The trade autopsy: learning from bad trades (D-109)

Requested by the user on 2026-10-24: improve the strategies by first analysing what went wrong:
another indicator, a pattern, news, the bigger charts, other strategies on the same stock; broad and
self-learning. Built as `backend/metis/autopsy.py`, part of every strategy's brief (study years only):

- **Every trade opened up.** On the signal candle: ~19 readings on the strategy's own chart (ADX,
  choppiness, Aroon, distance from the 50/200 averages, RSI, MACD histogram, rate of change, MFI,
  Chaikin money flow, relative volume, volume oscillator, ATR %, Bollinger bandwidth and %B, z-score,
  stochastic, Williams %R, balance of power) and 6 on each of the next two bigger charts (weekly and
  monthly for a daily strategy).
- **Second opinions.** Up to three of the user's other strategies on the same market and timeframe
  (a different style first) run on the same stocks over the study years. Each trade: good for another
  strategy too, lost for everyone that took it (the market or news, not the rules), or taken alone.
- **The market's mood.** Win rate by the benchmark's trend at entry (evidence for the AI; rules read
  one stock only).
- **What separated losers from winners.** For each reading, a "skip these" threshold chosen on the
  first 60% of the study trades, kept only if it holds on the last 40%. The best three become filter
  ideas, plus the best two together; "only when the other strategy agrees" becomes that strategy's
  state conditions. They go first among the playbook's experiments and into the AI's brief, and are
  tested like any idea (exam years, luck check, overfitting check).
- **Self-learning.** Each condition carries its reading (`probe`). Metis counts how often each
  reading's filters held up over its notebook and ranks the next candidates by it; a reading already
  tried on a strategy version isn't retried. The brief says which readings have worked so far.
- **Screen.** Each round on the Metis screen has **Trade autopsy: why trades went wrong**.

## 19. Every timeframe (D-118)

Requested by the user on 2026-10-24 ("strategies for day, 1 hour, 15 min, 5 min and 1 min too").
`backend/metis/timeframes.py` finds, per market, the timeframes with enough saved history (at least 4
stocks with 250 daily / 120 hourly / 20 fifteen- and five-minute / 10 one-minute trading days) and
how many strategies the user has on each. Discovery tries the textbook templates on those timeframes,
the emptiest first (`templates.timeframes_for`), and minute strategies are tested on the stocks that
have minute history. The AI may give a new strategy a `timeframe`; the brief lists the timeframes.
Metis may add up to 5 genuinely new strategies a day. Everything else (the exam years, the luck and
overfitting checks, the trade autopsy with its bigger charts) works the same on every timeframe; with
60 days of 5-minute history the "years" are weeks.

## 20. Trailing stops (D-119)

A tweak may set `"trailing_stop_atr"` (0.5–8 × ATR behind the best price since entry), besides the
percent trailing stop. The expert's first look proposes one for every visual strategy without it:
2.5 and 3.5 ATR when at least 30% of the study-year losers had been ahead by an ATR (Kairos's review
counts them), otherwise 3 ATR (and 4 for trend strategies). The persona explains trailing stops and
asks Metis to consider one for every strategy; the playbook has "Winners turn into losers". New
strategies drafted from Metis's ideas include a 3 × ATR trailing stop unless the idea says otherwise.

## 21. Partial exits and the index bar (D-125, D-126)

A tweak may set `"partial_half_r"` (sell half at that many R, 0.3–5) or `"partial_thirds_r"` (a
third at R and a third at 2R, 0.3–3); the stop moves to the entry after the first. Both need a
stop-loss, so an idea for a strategy without one adds `"stop_loss_pct"` in the same change. The
first look proposes both (finding `partials`) when at least 30% of the study-year losers had been
ahead first or the win rate is under 50%, and a stop-loss beside the time limit when losses run. The
persona asks Metis to find **why** a strategy is weak first (entry indicator, market trend, news,
bigger chart, costs, exits) and fix that cause. A **new** strategy must also beat buying and holding
the Nifty 50 / SPY over the exam years (a fixed check beside the others; passes with a note when no
index prices are saved). The library has `active.md`: partial exits in research, diagnosing weak
strategies, the index bar, high-win-rate families, institutional flows, volume footprints and
realistic returns.

## 22. Losing trades one by one, no loops, and the web (D-128, D-129)

From three study trades the brief lists the worst losers one by one with their textbook causes
and "What the losers had in common"; the first look's `casebook` finding turns shared causes into
filters (200- or 50-candle trend, weekly trend for the market, ADX, relative volume, z-score) or a
wider stop. Universe ideas top up to 4 stocks from the market's main list when the model names
unknown stocks. The strategies in use rest after 6 empty improve-live rounds in a row until one of
them changes. Each brief has one web question ("From the web"): about the first strategy studied,
or a strategy family in turn when discovering; the persona treats web text as hypotheses to test.

## 23. Reading everything, ideas that can work, and the research sprint's playbook (D-141 to D-144)

Requested on 2026-11-03: "use your intelligence to put Kairos and Metis way way way ahead".
- **Reading size (D-141).** A brief is 6,500–10,000 tokens and the model's thinking counts in
  the same window; at 4,096 or 8,192 Ollama dropped the start (the instructions and the first
  strategies). The reading size is now Automatic, up to 32,768 (it steps down if the graphics
  card can't hold it), and the brief leaves out its least needed parts to fit, never its start.
- **Ideas that can't work are caught first (D-142, `precheck.py`).** A filter that is never or
  always true on the study years, or a new strategy whose entry can never be met, is "could not
  be tested" with the indicator's real range, without a backtest. Crosses are rare by nature and
  count as never true only when they didn't happen once. The structured answer may only name
  real indicators.
- **The playbook first (D-144).** Discovery rounds start from the research sprint's playbook
  (`backend/seed_data/playbook.json`, docs/DECISIONS.md D-143): entries the user doesn't have,
  those whose record suits today's market regime first (the index's regime on daily candles),
  then the textbook templates. Each is judged exactly like any new strategy (exam years, luck,
  overfitting and index checks) on the user's own stocks, so a sprint's result is re-earned, not
  copied.
- **The library** has `india_evidence.md`: what survived costs in Indian stocks since 2015
  (trend rules held up a multiple-testing check, plain RSI and indicator stacking didn't,
  liquidity decides, momentum and low volatility as portfolios, costs and taxes).

### 23a. Sprint 2026-11: what the first sprint on the user's data found (2026-11-03)
Run by Claude on the laptop (RUNBOOK §7a): 30 most traded stocks a market for daily, 15 for
hourly, 10 for 5- and 15-minute; research years before the vault split 70/30; the vault was the
last 365 days (Nifty 50 −8.4%, Sharpe −0.58; SPY +11.4%, Sharpe 0.92).
- **Round 1 (32 families, 302 tests).** US daily: many families passed every rule before the
  vault. India daily: nearly every family failed one rule only, matching simply holding its own
  stocks (exam Sharpe 1.49; India's large stocks rose strongly), except those that stay invested
  for months. Dip buying in India lost in calm sideways markets. Every 5- and 15-minute family,
  and every India hourly one, lost to costs.
- **Round 2 (5 families, 40 tests)**, written from round 1: hold longer and trade less
  (`trend_hold_long`, `breakout_hold_trend`), dips only in stacked trends, in high volatility or
  near the 52-week high. In India the two hold-for-months families passed every rule before the
  vault; the dip variants still didn't beat holding.
- **Finalists (fixed rules, nobody chose):** 22, 6 India, 15 US daily, 1 US hourly.
- **The vault (opened once):** all 6 India finalists lost money in a falling Indian year, so
  none was promoted; the US hourly breakout lost; 15 US daily finalists made money and are the
  playbook. Against SPY's vault Sharpe ratio of 0.92 (return for the risk taken; money terms
  aren't comparable because each test compounds from its first year): six-month momentum ranking
  1.70 (13 trades), Supertrend 1.56, Ichimoku 1.36, Connors RSI dips 1.29, RSI(2) dips 1.07,
  ROC momentum 0.97, Donchian 0.95, accumulation breakout 0.94; the other seven were below it.
- **Metis's turn (D-149):** while playbook entries wait to be re-tested on the user's stocks,
  discovery gets at least every third round.
- **For the next sprint:** India needs a defensive idea for falling years (a market filter on
  the Nifty's own trend, or cash when the index is below its 200-day average); intraday India
  isn't worth more families until costs change; a new sprint name opens a fresh vault later.

## The strategy combiner (D-227, Phase 27)

`backend/metis/combine.py`. `judge` puts two or more strategies through the same fixed tests as any
change; `repair` takes a strategy, finds its bad trades on the study years, tries only strategies that
already passed a real test as blockers, and judges at most three combinations. Every combination
counts as a try. From Python: `combine.repair(ctx, version_id)`; in the app: Strategies → New →
Combine strategies.
