"""Past world events that moved markets, for training the world map (D-95).

Only facts that are easy to check are written here: the date the news broke (or, for news
that broke after the close or on a weekend, the date it was public before the next session),
which kind of event it was (a scenario of ``scenarios.py``), and whether it escalated (+1) or
calmed (−1) things. **How markets reacted is not written down: ``learn.py`` measures it from
saved prices** (the Nifty since 2007, the S&P 500 and the sector funds since 1998–1999 on
Yahoo), so the lessons are numbers from data, not claims. Events before a market's data starts
are skipped for that market. Dates checked 2026-10-23.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    day: str  # YYYY-MM-DD: the news was public before that day's close
    scenario: str
    title: str
    sign: int = 1  # +1 escalation, −1 calming (a ceasefire, a deal, a pause)


EVENTS: tuple[Event, ...] = (
    Event("1990-08-02", "mideast_war", "Iraq invades Kuwait"),
    Event("1991-01-17", "mideast_war", "Operation Desert Storm's air war begins", -1),
    Event("1997-07-02", "rupee_slide", "Thailand floats the baht: the Asian financial crisis"),
    Event("1998-05-11", "us_tariffs_india", "India's nuclear tests; US sanctions follow"),
    Event("1998-08-17", "banking_scare", "Russia defaults on its debt"),
    Event("1998-09-23", "banking_scare", "Long-Term Capital Management is rescued"),
    Event("1999-05-26", "india_pakistan", "Kargil: India launches air strikes"),
    Event("1999-07-26", "india_pakistan", "Kargil war ends", -1),
    Event("2001-09-17", "terror_major", "US markets reopen after the 9/11 attacks"),
    Event("2001-12-13", "india_pakistan", "Attack on India's Parliament"),
    Event("2003-03-20", "mideast_war", "The Iraq war begins"),
    Event("2005-07-07", "terror_major", "London bombings"),
    Event("2008-07-11", "opec_cut", "Brent oil peaks near $147"),
    Event("2008-09-15", "banking_scare", "Lehman Brothers files for bankruptcy"),
    Event("2008-11-27", "india_pakistan", "Mumbai attacks (26/11)"),
    Event("2008-12-16", "fed_dovish", "The Fed cuts rates to near zero"),
    Event("2010-05-10", "banking_scare", "Euro debt crisis: the EU rescue fund", -1),
    Event("2011-02-22", "mideast_war", "Libya's uprising: oil jumps"),
    Event("2011-03-11", "disaster", "Japan's earthquake, tsunami and Fukushima"),
    Event("2011-08-08", "us_politics", "First trading day after S&P downgrades the US"),
    Event("2012-07-26", "banking_scare", "Draghi: 'whatever it takes'", -1),
    Event("2013-05-22", "fed_hawkish", "Bernanke hints at tapering: the taper tantrum"),
    Event("2013-08-28", "rupee_slide", "The rupee hits a record low near 68.8"),
    Event("2013-09-18", "fed_dovish", "The Fed surprises by not tapering"),
    Event("2014-03-03", "russia_ukraine", "Russia moves into Crimea"),
    Event("2014-05-16", "india_politics", "India's election result: a clear majority", -1),
    Event("2014-06-10", "mideast_war", "ISIS takes Mosul"),
    Event("2014-11-28", "oil_crash", "OPEC decides not to cut output"),
    Event("2015-08-11", "china_slump", "China devalues the yuan"),
    Event("2015-08-24", "china_slump", "Global sell-off on China fears"),
    Event("2015-12-16", "fed_hawkish", "The Fed's first hike since 2006"),
    Event("2016-01-20", "oil_crash", "Oil falls below $28"),
    Event("2016-09-29", "india_pakistan", "India's surgical strikes across the LoC"),
    Event("2016-11-09", "india_politics", "India demonetises ₹500 and ₹1,000 notes"),
    Event("2016-11-30", "opec_cut", "OPEC agrees its first output cut since 2008"),
    Event("2017-08-10", "nuclear_threat", "US–North Korea 'fire and fury'"),
    Event("2018-02-05", "us_inflation_hot", "Volatility spike on wage inflation fears"),
    Event("2018-03-22", "us_china_trade", "US announces tariffs on Chinese goods"),
    Event("2018-10-10", "fed_hawkish", "Sell-off on rising yields and Fed hawkishness"),
    Event("2019-01-04", "fed_dovish", "Powell signals patience", -1),
    Event("2019-02-15", "india_pakistan", "First session after the Pulwama attack"),
    Event("2019-02-26", "india_pakistan", "India's air strikes on Balakot"),
    Event("2019-05-06", "us_china_trade", "Trump raises tariffs on China"),
    Event("2019-05-13", "us_china_trade", "China retaliates with tariffs"),
    Event("2019-05-23", "india_politics", "India's election result: a bigger majority", -1),
    Event("2019-08-05", "us_china_trade", "The yuan breaks 7 per dollar"),
    Event("2019-09-16", "shipping_chokepoint", "Drone attack on Saudi Abqaiq oil plant"),
    Event("2019-09-20", "india_politics", "India cuts corporate tax", -1),
    Event("2020-01-06", "mideast_war", "First session after the US kills Iran's Soleimani"),
    Event("2020-02-24", "pandemic", "COVID-19 spreads in Italy and Korea"),
    Event("2020-03-09", "oil_crash", "Saudi–Russia oil price war"),
    Event("2020-03-16", "pandemic", "Emergency Fed cut; global lockdowns"),
    Event("2020-03-24", "pandemic", "Massive stimulus: markets bottom", -1),
    Event("2020-06-16", "india_china", "Galwan valley clash"),
    Event("2020-11-09", "pandemic", "Pfizer's vaccine works", -1),
    Event("2021-11-26", "pandemic", "Omicron variant found"),
    Event("2022-01-26", "fed_hawkish", "Fed signals hikes soon"),
    Event("2022-02-24", "russia_ukraine", "Russia invades Ukraine"),
    Event("2022-03-08", "opec_cut", "US bans Russian oil; Brent near $128"),
    Event("2022-06-13", "us_inflation_hot", "US inflation at a 40-year high"),
    Event("2022-08-02", "taiwan_strait", "Pelosi visits Taiwan"),
    Event("2022-10-07", "us_china_trade", "US curbs chip exports to China"),
    Event("2022-11-10", "us_inflation_hot", "US inflation cools", -1),
    Event("2023-03-10", "banking_scare", "Silicon Valley Bank fails"),
    Event("2023-03-20", "banking_scare", "UBS takes over Credit Suisse"),
    Event("2023-10-09", "mideast_war", "First session after Hamas attacks Israel"),
    Event("2023-12-18", "shipping_chokepoint", "Shipping lines pause Red Sea routes"),
    Event("2024-01-12", "shipping_chokepoint", "US and UK strike the Houthis"),
    Event("2024-04-15", "mideast_war", "First session after Iran's drone attack on Israel"),
    Event("2024-06-04", "india_politics", "India's election result short of expectations"),
    Event("2024-08-05", "yen_carry", "Yen carry-trade unwind: the Nikkei falls 12%"),
    Event("2024-09-18", "fed_dovish", "The Fed cuts by half a point"),
    Event("2024-10-01", "mideast_war", "Iran fires missiles at Israel"),
    Event("2024-11-06", "us_politics", "US election result", -1),
    Event("2025-01-27", "ai_shock", "DeepSeek's cheap AI model"),
    Event("2025-02-07", "rbi_cut", "RBI cuts rates for the first time in five years"),
    Event("2025-04-03", "us_tariffs_world", "'Liberation Day' tariffs"),
    Event("2025-04-09", "us_tariffs_world", "90-day tariff pause", -1),
    Event("2025-04-23", "india_pakistan", "First session after the Pahalgam attack"),
    Event("2025-05-07", "india_pakistan", "Operation Sindoor strikes"),
    Event("2025-05-12", "india_pakistan", "India–Pakistan ceasefire holds", -1),
    Event("2025-05-12", "us_china_trade", "US–China truce in Geneva", -1),
    Event("2025-06-06", "rbi_cut", "RBI cuts by half a point"),
    Event("2025-06-13", "mideast_war", "Israel strikes Iran"),
    Event("2025-06-23", "mideast_war", "First session after US strikes on Iran's nuclear sites"),
    Event("2025-06-24", "mideast_war", "Israel–Iran ceasefire", -1),
    Event("2025-08-07", "us_tariffs_india", "US adds a 25% tariff on India over Russian oil"),
)
