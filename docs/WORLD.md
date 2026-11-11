# WORLD: watchlists, sectors, several timeframes, the world desk and the autopilot (Phase 18)

Requested by the user on 2026-10-23 (`CHANGELOG.md`). Decisions D-93 to D-99. Summary in SPEC §18.

The six requests, and where each lives:

| He asked | What Agora does | Code | Decision |
|---|---|---|---|
| Kairos and Metis should read several timeframes of the same stock ("better quality trades, fewer false alarms") | Bigger charts in any rule, the Kairos desk trades only with the bigger chart's trend, the chart reading reads monthly/weekly/daily together, Metis can propose bigger-chart filters | `backend/analysis/mtf.py`, `strategy/runtime.py` (`ctx.chart`), `kairos/brain.py`, `metis/diagnose.py` | D-97 |
| Be very proficient in geopolitics: an event anywhere reaches US and Indian markets, directly or not | The world map: 33 kinds of world event, each with how to recognise it, its chain of effects and its effects on each market's sectors and exposure groups; a 27-section geopolitics playbook | `backend/world/scenarios.py`, `kairos/knowledge/geopolitics_world.md`, `metis/library/world.md` | D-95 |
| Train on the history of geopolitics; correlate; read the internet; self-learning; when the market or a sector dips suddenly, investigate which event caused it | 87 past events measured on saved prices; every live event measured 1, 5 and 20 days later; the map's effects pulled toward what was measured; the move investigator (news + GDELT search + oil/gold/dollar/rupee/VIX/yields + the other market) | `world/history.py`, `world/engine.py`, `world/investigate.py`, `world/service.py` | D-95, D-96 |
| Know sectors and their movements ("one sector receives a bloom and all its stocks boom") | Sector and industry lines, rotation (leading/weakening/lagging/improving), breadth, booms and slumps | `backend/sectors/` | D-98 |
| Start on their own as soon as Agora opens (and Ollama is connected); no stocks or strategies to add | The autopilot: prices, factor lists, Kairos's own picks and desks, Metis researching (on by default) | `backend/autopilot.py`, `kairos/picks.py` | D-99 |
| Ready-made watchlists (sector, size, index, and the ones big quant firms use), besides his own; Kairos and Metis make lists when worth it | 110 ready-made lists, your own lists, Kairos's and Metis's lists with their reasons | `backend/watchlists/`, `metis/lists.py` | D-93, D-94 |

## 1. Stocks and their profiles (D-93)

Agora now knows every stock on NSE's main board (2,617) and the US exchanges (5,892; D-102). About
2,300 of them are in an index: India's Nifty 500 and Microcap 250 and the stocks of 33 NSE sector,
theme and strategy indices; the US S&P 500, 400 and 600, the Nasdaq-100 and the Dow 30. Plus 63 ETFs
and 16 market gauges. The others carry the list key `listed`: they can be charted, backtested,
watched and paper traded, but the sector readings and picks use index stocks. `scripts/fetch_lists.py` rebuilds the two seed files from the
official lists (Claude runs it every few months; `as_of` is in each file). Every stock has a
**sector** (the 11 GICS sectors, the same in both markets), an **industry**, a **size** (large, mid,
small, micro by index) and **exposure tags** (what it is sensitive to: oil producer, fuel retailer,
oil user, airline, exporter, defence, bank, rate-sensitive, China-exposed, semiconductors, …).
Prices are downloaded only for what is used (the autopilot fills in the broad index in batches).

## 2. Watchlists (D-94)

- **Ready-made** (kept up to date, read-only; "Copy to my lists" makes an editable copy):
  - *Indices*: Nifty 50, Next 50, 100, 200, 500, Bank, Private Bank, PSU Bank, Financial Services,
    IT, Auto, Pharma, Healthcare, FMCG, Metal, Realty, Energy, Oil & Gas, Media, Consumer Durables,
    Chemicals, India Defence, Infrastructure, Commodities, Consumption, MNC, PSE, CPSE, India
    Digital, India Manufacturing, India Tourism; S&P 500, Nasdaq-100, Dow 30, S&P 400, S&P 600.
  - *Sectors*: the 11 sectors of the Nifty 500 and of the S&P 500.
  - *Sizes*: large, mid, small (and India's micro) caps.
  - *Factor lists, as quant firms build them*: NSE's own smart-beta indices (Momentum 30, Low
    Volatility 30, Quality 30, Alpha 50, Dividend Opportunities 50) and, rebuilt daily from saved
    prices for both markets: momentum (12-1), low volatility, near 52-week highs, strong uptrends,
    oversold in uptrends (short-term reversal), relative strength.
  - *Themes*: Magnificent 7, semiconductors, AI computing, defence, oil producers, airlines and
    travel, banks, regional banks, rate-sensitive, defensives, China-exposed, gold and metals; India:
    hurt by dear oil, gain from dear oil, exporters, rate-sensitive, defensives, rural India,
    gold-linked, capex, capital markets, renewables.
  - *ETFs*: SPDR sector funds, factor ETFs, world and macro ETFs, theme ETFs, index ETFs, Indian ETFs.
- **Yours**: make, rename, add and remove stocks, delete.
- **Kairos's and Metis's**: "Kairos · Picks India/US" (its desk's stocks), "Metis · Booming:
  <sector>", "Metis · World: <event>"; each with the reason and a note per stock. At most three new
  lists a day each, twelve kept.

Kairos understands list names anywhere it takes stocks ("backtest the RSI strategy on the Nifty IT
list"). The opportunity scanner also tries the stocks the agents' and factor lists brought in.

## 3. Sectors (D-98)

For each sector and industry with priced stocks: an equal-weight line, its returns, its rotation
against the market (leading → weakening → lagging → improving), its breadth (share above the 50- and
200-day averages, new highs), and its state: **booming** (an unusually strong month for this sector,
most stocks taking part, beating the market, busier than usual), leading, steady, lagging or
slumping. Shown at the top of **Watchlists** ("Where money is moving"); Kairos's `sectors` tool;
used by Kairos's picks, Metis's lists and the investigator.

## 4. Several timeframes (D-97)

- **Strategies**: any price or indicator in a rule can be read **on a bigger chart** (Read on: the
  weekly or monthly chart for a daily strategy; the daily or weekly for hourly; …), on its last
  finished candle. Code: `ctx.chart("1w").close`, `ctx.chart("1w").ind.sma("close", 40)`.
- **Kairos's desk** trades only with the bigger chart's trend (weekly for a daily desk), setting
  "Trade with the bigger chart's trend" (on).
- **Charts → Kairos**: a **Timeframes** section: each timeframe's trend, and whether they agree
  ("Every timeframe agrees: up", "A dip inside a weekly uptrend", "A bounce inside a weekly
  downtrend: buy signals here are the classic false alarm").
- **Metis** proposes bigger-chart filters and tests them like any idea (unseen years, luck check).

## 5. The world desk (D-95, D-96)

- **Noticing events**: every saved headline (RSS feeds, central banks, GDELT) is matched against the
  33 kinds of event; one event per kind while it stays in the news (three days), with its strength,
  whether it is escalating or calming, and its headlines.
- **Effects**: per market, on the whole market, each sector and each exposure group; which stocks
  are likely to do better or worse than the market and why.
- **Learning**: past events measured on saved prices (1, 5, 20 trading days); every live event
  measured once its days have passed; the effects shown blend the map with what was measured
  (n/(n+3)); "What past events actually did" lists the measured reactions.
- **Why did it move?**: unusual moves of the market or a sector on the latest daily candle are
  investigated: the news around it (and a GDELT search on the laptop), the confirming assets, the
  other market; the most likely cause, other candidates and a confidence; "no clear news" says so.
- Screen **World**; Kairos tools `world_events`, `why_move`; phrases "what's happening in the
  world?", "what does the Iran war mean for my stocks?", "why did IT fall today?".

## 6. The autopilot (D-99)

When Agora opens (setting **Work on their own**, on): prices are topped up (the market's index,
gauges, confirming assets, sector ETFs, and the broad index 60 stocks a round), factor lists are
rebuilt, Kairos ranks every stock of the market (D-133) and starts a daily desk and hourly and
15-minute desks per market on its 250 most traded stocks (D-177) (unless you run your own desk), and Metis researches (with Ollama when it's ready, from its playbook until then). Every 15
minutes it checks again; a short desk may move to new picks every day, the daily desk every week
(only when it holds no trades).
Paper money only; nothing runs while Agora is closed. Home shows a **Kairos and Metis** card.

## 7. Honesty and limits

- The world map's effects are a prior plus measurements; with few past events of a kind, the
  measurement is noisy (shown with how many events it rests on).
- News arrives through public feeds and GDELT only; no paid intelligence, no accounts (D-02).
- The investigator reads daily candles; intraday moves are not investigated yet.
- Profiles and lists are a snapshot of the official lists on `as_of`; refresh every few months.
- Quality and value factors need company fundamentals; the US uses factor ETFs for them, India
  NSE's own Quality 30 list.
