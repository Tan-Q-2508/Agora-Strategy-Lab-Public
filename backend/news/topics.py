"""What a headline is about and how much it matters to markets (Phase 10.5, D-68).

A small, transparent rule set, the same idea as ``sentiment.py``: every rule is a list of
words and phrases a market desk would scan for. A headline gets

- **topics**: geopolitics (war & conflict, terrorism, sanctions, politics), trade
  (tariffs), central banks, inflation, growth & jobs, energy, banking stress, government
  debt, currencies, health emergencies, natural disasters, cyber attacks, market stress,
  regulation, budget & tax, company news;
- **severity** 0–5: how much such news has historically moved whole markets (0 = not
  market news, 1 = company news, 3 = a war or sanctions headline, 5 = an invasion, a
  pandemic lockdown, a bank collapse or a market-wide circuit breaker), raised one step
  by words like "escalates", "biggest since", "emergency";
- **impact** −1 (risk-off: sell first, ask later) … +1 (risk-on): from the topic's usual
  direction (a rate hike is risk-off, a ceasefire risk-on) blended with the headline's
  sentiment;
- **scope**: ``IN``, ``US`` or ``WORLD``, from the places it names;
- **sectors** it usually helps (+1) or hurts (−1), for the News screen.

No model is involved, so the same headline always reads the same way, offline. The rules
are tested on real-style headlines in ``tests/news/test_world_news.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.news import sentiment


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    group: str  # what the News screen filters by
    severity: int
    direction: float  # the usual market reaction: −1 risk-off … +1 risk-on
    words: tuple[str, ...]
    sectors: dict[str, int] = field(default_factory=dict)


GEO, MACRO, MARKETS, COMPANY = "Geopolitics", "Economy", "Markets", "Companies"

# fmt: off
TOPICS: tuple[Topic, ...] = (
    Topic(
        "conflict", "War & conflict",
        GEO,
        3,
        -0.8,
        (
            "war", "wars", "invasion", "invade", "invades", "invaded", "airstrike",
            "airstrikes", "air strike", "air strikes", "missile", "missiles", "drone strike",
            "drone attack", "troops", "military", "shelling", "bombing", "bombardment",
            "artillery", "clashes", "border tension", "border tensions", "escalation",
            "retaliates", "retaliation", "retaliatory strike", "mobilises", "mobilizes",
            "nuclear threat", "hostilities", "offensive", "warplanes", "naval blockade",
            "strait of hormuz", "red sea attack", "houthi", "ceasefire", "truce",
            "warship", "warships", "military drills", "war games", "blockade",
            "naval drills", "live-fire drills",
            "peace talks", "peace deal", "armistice",
        ),
        {"Energy": 1, "Defence": 1, "Gold": 1, "Airlines": -1, "Travel": -1},
    ),
    Topic(
        "terror", "Terrorism",
        GEO,
        3,
        -0.7,
        (
            "terror attack", "terrorist", "terrorists", "bomb blast", "suicide bomber",
            "hostage", "hostages", "gunmen", "massacre",
        ),
        {"Travel": -1, "Airlines": -1},
    ),
    Topic(
        "sanctions", "Sanctions",
        GEO,
        3,
        -0.6,
        (
            "sanction", "sanctions", "sanctioned", "embargo", "export ban", "blacklist",
            "blacklisted", "asset freeze", "price cap",
        ),
        {"Energy": 1, "Metals": 1},
    ),
    Topic(
        "trade", "Trade & tariffs",
        GEO,
        3,
        -0.6,
        (
            "tariff", "tariffs", "trade war", "import duty", "import duties", "customs duty",
            "retaliatory duties", "export curbs", "export controls", "trade deal",
            "trade pact", "trade agreement", "trade truce", "wto",
        ),
        {"Exporters": -1, "IT services": -1, "Autos": -1, "Metals": -1},
    ),
    Topic(
        "politics", "Politics & elections",
        GEO,
        2,
        -0.3,
        (
            "election", "elections", "poll results", "exit poll", "exit polls", "coup",
            "impeachment", "impeach", "no-confidence", "government collapses", "snap election",
            "martial law", "state of emergency", "unrest", "riots", "protests",
            "parliament dissolved", "resigns as prime minister", "hung parliament",
            "coalition",
        ),
    ),
    Topic(
        "central_bank", "Central banks & rates",
        MACRO,
        2,
        -0.2,
        (
            "fed", "fomc", "federal reserve", "rbi", "reserve bank", "ecb", "bank of japan",
            "boj", "bank of england", "monetary policy", "repo rate", "rate hike",
            "rate hikes", "rate cut", "rate cuts", "interest rate", "interest rates",
            "hawkish", "dovish", "powell", "lagarde", "malhotra", "quantitative tightening",
            "quantitative easing", "policy rate", "mpc", "emergency rate",
            "central bank", "keeps rates", "holds rates", "rates unchanged", "rates steady",
            "raises rates", "lowers rates", "cuts rates",
        ),
        {"Banks": 1, "Real estate": -1},
    ),
    Topic(
        "inflation", "Inflation",
        MACRO,
        2,
        -0.3,
        (
            "inflation", "cpi", "wpi", "consumer prices", "consumer price index",
            "price index", "pce", "core prices", "stagflation", "hyperinflation",
        ),
    ),
    Topic(
        "growth", "Growth & jobs",
        MACRO,
        2,
        -0.2,
        (
            "gdp", "recession", "slowdown", "contraction", "contracts", "pmi", "jobs report",
            "payrolls", "unemployment", "jobless", "jobless claims", "industrial output",
            "iip", "retail sales", "consumer confidence", "economic growth", "economy shrinks",
            "soft landing", "hard landing",
        ),
    ),
    Topic(
        "energy", "Oil & energy",
        MACRO,
        2,
        -0.3,
        (
            "crude", "oil price", "oil prices", "brent", "wti", "opec", "opec+", "natural gas",
            "lng", "fuel prices", "petrol", "diesel", "oil supply", "oil output", "barrel",
        ),
        {"Oil producers": 1, "Oil marketing": -1, "Airlines": -1, "Paints": -1, "Chemicals": -1},
    ),
    Topic(
        "banking", "Banking stress",
        MARKETS,
        4,
        -0.9,
        (
            "bank run", "bank collapse", "bank collapses", "bank failure", "bank fails",
            "bailout", "liquidity crisis", "credit crunch", "contagion", "systemic risk",
            "deposit flight", "insolvent", "lehman", "shadow banking",
        ),
        {"Banks": -1, "Financials": -1},
    ),
    Topic(
        "debt", "Government debt & bonds",
        MACRO,
        3,
        -0.6,
        (
            "sovereign debt", "debt ceiling", "government shutdown", "sovereign rating",
            "credit rating downgrade", "rating downgrade", "bond yields", "treasury yields",
            "yields surge", "yields jump", "bond rout", "bond market", "default on its debt",
            "fiscal crisis", "yield curve",
        ),
        {"Banks": -1, "Real estate": -1},
    ),
    Topic(
        "currency", "Currencies",
        MACRO,
        2,
        -0.3,
        (
            "rupee", "dollar index", "currency crisis", "devaluation", "devalues",
            "forex reserves", "yen", "yuan", "exchange rate", "record low against the dollar",
        ),
        {"IT services": 1, "Importers": -1},
    ),
    Topic(
        "health", "Health emergency",
        GEO,
        3,
        -0.8,
        (
            "pandemic", "outbreak", "epidemic", "lockdown", "lockdowns", "virus", "covid",
            "bird flu", "public health emergency", "quarantine",
        ),
        {"Pharma": 1, "Travel": -1, "Airlines": -1},
    ),
    Topic(
        "disaster", "Natural disaster",
        GEO,
        2,
        -0.5,
        (
            "earthquake", "tsunami", "cyclone", "hurricane", "typhoon", "floods", "flooding",
            "wildfire", "wildfires", "drought", "deficient monsoon", "weak monsoon",
            "heatwave", "volcano",
        ),
        {"Insurance": -1, "Cement": 1},
    ),
    Topic(
        "cyber", "Cyber attack",
        GEO,
        2,
        -0.5,
        (
            "cyberattack", "cyber attack", "cyber-attack", "ransomware", "hackers", "hacked",
            "data breach", "global outage", "it outage",
        ),
    ),
    Topic(
        "market_stress", "Market stress",
        MARKETS,
        3,
        -0.8,
        (
            "market crash", "stock market crash", "stocks crash", "sensex crashes",
            "nifty crashes", "sell-off", "selloff", "market rout", "stocks rout", "bond rout",
            "bloodbath on dalal street", "circuit breaker", "circuit breakers", "trading halted",
            "trading halts",
            "market-wide halt",
            "panic selling", "black monday",
            "bear market", "market correction", "vix", "india vix", "fear gauge",
            "worst day since", "investors lose", "wipes out investor wealth", "biggest fall",
            "markets tumble", "markets plunge", "stocks tumble", "stocks plunge", "stocks slump",
            "markets slump", "dow plunges", "wall street plunges",
        ),
    ),
    Topic(
        "regulation", "Regulation & probes",
        COMPANY,
        2,
        -0.5,
        (
            "sebi", "sec", "antitrust", "probe", "investigation", "regulator", "raid", "raids",
            "enforcement directorate", "cbi", "fraud", "lawsuit", "penalty", "fined",
            "short seller", "hindenburg", "accounting irregularities", "insider trading",
        ),
    ),
    Topic(
        "fiscal", "Budget & tax",
        MACRO,
        2,
        0.1,
        (
            "budget", "union budget", "fiscal deficit", "stimulus", "tax cut", "tax cuts",
            "tax hike", "gst", "capital gains tax", "subsidy", "spending bill", "windfall tax",
        ),
    ),
    Topic(
        "corporate", "Company news",
        COMPANY,
        1,
        0.0,
        (
            "earnings", "quarterly results", "q1", "q2", "q3", "q4", "profit", "revenue",
            "guidance", "merger", "acquisition", "acquires", "takeover", "ipo", "buyback",
            "dividend", "layoffs", "downgrade", "upgrade", "ceo", "order win", "stake sale",
            "block deal", "promoter", "pledge", "listing",
        ),
    ),
)
BY_KEY = {t.key: t for t in TOPICS}
GROUPS = (GEO, MACRO, MARKETS, COMPANY)

# Words that make a headline one step more serious, or turn it risk-on.
ESCALATE = (
    "escalate", "escalates", "escalated", "escalating", "escalation", "biggest since",
    "worst since", "highest since", "record low",
    # not "historic": in headlines it is elections, records and upsets far more than escalation
    # (D-199: "Trump blames Democrats for selloff after historic midterm win" rated 4)
    "emergency", "all-out", "full-scale", "declares war", "imminent", "spirals",
    "spiral", "crisis", "collapse", "collapses", "meltdown", "nuclear", "invasion", "invades",
    "martial law", "lockdown", "circuit breaker", "trading halted",
)
CALM = (
    "ceasefire", "truce", "peace talks", "peace deal", "deal reached", "agreement reached",
    "de-escalation", "de-escalate", "eases", "easing", "cools", "pause", "pauses", "pact",
    "trade deal", "rate cut", "rate cuts", "cuts rates", "cuts interest rates",
    "cut interest rates", "lowers rates", "lowers interest rates", "dovish", "stimulus",
    "rebound", "rebounds", "ease", "ease escalation", "mediation", "lower risk",
    "recovers", "rally", "rallies", "relief", "lifted", "lifts sanctions", "averted",
    "soft landing", "steady", "unchanged",
)
# Phrases where a war or crisis word means something else (D-179): taken out before reading.
NOT_WAR = (
    "home invasion", "home invasions", "demographic invasion", "invasion hype",
    "invasion of privacy", "invasive species", "invasive", "trade war on talent",
    "price war", "price wars", "talent war", "bidding war", "war chest", "war room",
    "culture war", "culture wars", "war of words", "star wars", "console war",
    "nuclear microreactor", "nuclear microreactors", "nuclear energy", "nuclear power",
    "historic upset", "historic win", "historic victory", "historic high",
    "historic highs", "record high", "record highs", "emergency room", "pandemic-era",
    "privilege escalation", "escalation of privileges", "escalation path", "customer escalation",
)
# Combinations that are always top-severity, whatever the other words say.
TOP = (
    ("invasion",),
    ("invades",),
    ("declares war",),
    ("nuclear", "strike"),
    ("pandemic",),
    ("lockdown",),
    ("lockdowns",),
    ("bank", "collapse"),
    ("circuit breaker",),
    ("circuit breakers",),  # whole words since D-179: the plural needs its own entry (D-199)
    ("trading halted",),
    ("trading halts",),
    ("martial law",),
    ("coup",),
    ("coups",),
    ("emergency rate",),
)

REGIONS: dict[str, tuple[str, ...]] = {
    "IN": (
        "india", "indian", "rbi", "sebi", "nifty", "sensex", "rupee", "new delhi", "delhi",
        "mumbai", "modi", "dalal street", "nse", "bse", "kashmir", "pakistan", "lok sabha",
        "gst", "union budget", "fii", "fpi", "dii", "bengaluru", "chennai", "kolkata",
        "hyderabad", "gujarat", "maharashtra", "karnataka", "tamil nadu", "kerala", "punjab",
    ),
    "US": (
        "u.s.", "united states", "america", "american", "fed", "federal reserve", "fomc",
        "wall street", "nasdaq", "s&p", "s&p 500", "dow", "washington", "white house",
        "treasury", "congress", "senate", "trump", "powell", "nyse", "biden", "pentagon",
        "silicon valley", "new york", "california", "texas", "chicago",
    ),
}
WORLD_WORDS = (
    "global", "world", "china", "chinese", "russia", "russian", "ukraine", "israel", "iran",
    "gaza", "middle east", "opec", "europe", "ecb", "japan", "taiwan", "saudi", "brent",
    "red sea", "hormuz", "nato", "g7", "g20", "imf", "world bank", "north korea", "oil",
    # other markets (D-188: "South Korea stocks plunge 8%" from a US feed read as US news)
    "korea", "south korea", "korean", "kospi", "nikkei", "japanese", "hang seng", "asia", "asian",
    "european", "stoxx", "ftse", "dax", "taiwanese", "australian", "asx",
)
# Smaller, distant economies (D-173): a crisis there is real news but not systemic for Indian or US
# stocks, so a story naming only these is world news of at most severity 3. "Paraguay's president
# resigns after bank collapse" came in through a US feed, was read as US news at severity 5 and
# pushed the US gauge to 66–74 with "Elevated: … opens no new trades". India's neighbours aren't
# here: their news can move Indian stocks.
FAR_WORDS = (
    "paraguay", "paraguayan", "uruguay", "bolivia", "peru", "peruvian", "ecuador", "venezuela",
    "venezuelan", "colombia", "colombian", "chile", "chilean", "argentina", "argentine", "brazil",
    "brazilian", "mexico", "mexican", "guatemala", "honduras", "nicaragua", "el salvador",
    "costa rica", "panama", "cuba", "haiti", "dominican", "jamaica", "guyana", "suriname",
    "nigeria", "nigerian", "kenya", "kenyan", "ghana", "ethiopia", "south africa", "egypt",
    "egyptian", "morocco", "moroccan", "western sahara", "sahrawi", "polisario", "algeria",
    "tunisia", "senegal", "angola", "zambia", "zimbabwe",
    "mozambique", "uganda", "tanzania", "sudan", "congo", "mali", "niger", "cameroon",
    "philippines", "vietnam", "thailand", "malaysia", "indonesia", "cambodia", "laos",
    "myanmar", "mongolia", "kazakhstan", "uzbekistan", "kyrgyzstan", "georgia", "armenia",
    "azerbaijan", "moldova", "serbia", "bosnia", "albania", "fiji", "papua new guinea",
    # regions too: "Latin American president resigns after bank collapse" (the Paraguay story
    # again, 5 Nov) named no country, and "american" read it as US news at severity 5, pushing
    # the US gauge to 79, "Severe", where the desks close their trades
    "latin america", "latin american", "south america", "south american", "central america",
    "central american", "caribbean", "africa", "african", "sub-saharan", "southeast asia",
    "southeast asian", "central asia", "central asian", "balkan", "balkans", "pacific islands",
)
# fmt: on


# A geopolitical story moves markets when it touches them: these words say it does.
MARKET_LINK = (
    "market",
    "markets",
    "stock",
    "stocks",
    "shares",
    "investors",
    "oil",
    "crude",
    "brent",
    "gas",
    "prices",
    "price",
    "inflation",
    "economy",
    "economic",
    "trade",
    "tariff",
    "tariffs",
    "sanctions",
    "exports",
    "imports",
    "supply",
    "shipping",
    "rupee",
    "dollar",
    "currency",
    "yields",
    "bonds",
    "gold",
    "sensex",
    "nifty",
    "wall street",
    "futures",
    "bank",
    "banks",
    "rates",
    "growth",
    "gdp",
    "energy",
    "fuel",
    "food",
    "commodity",
    "commodities",
    "rally",
    "selloff",
    "sell-off",
    "strait of hormuz",
    "red sea",
    "suez",
    "chips",
    "semiconductors",
)


def _pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    parts = sorted({re.escape(w) for w in words}, key=len, reverse=True)
    return re.compile(r"(?<![\w&])(" + "|".join(parts) + r")(?![\w&])")


_TOPIC_RX = {t.key: _pattern(t.words) for t in TOPICS}
_ESC_RX = _pattern(ESCALATE)
_TOP_RX = tuple(tuple(_pattern((w,)) for w in combo) for combo in TOP)
_NOT_RX = _pattern(NOT_WAR)
_CALM_RX = _pattern(CALM)
# which way an oil headline says the price went (D-211)
_OIL_DOWN_RX = _pattern(
    (
        "falls",
        "fall",
        "fell",
        "slides",
        "slid",
        "drops",
        "dropped",
        "declines",
        "decline",
        "crash",
        "crashes",
        "slumps",
        "slump",
        "tumbles",
        "plunges",
        "plunge",
        "retreats",
        "lower",
        "two-month low",
        "month low",
        "year low",
        "weekly loss",
        "price cut",
        "cheaper",
    )
)
_OIL_UP_RX = _pattern(
    (
        "surges",
        "surge",
        "jumps",
        "jump",
        "spikes",
        "spike",
        "soars",
        "climbs",
        "rises",
        "rose",
        "higher",
        "gains",
        "rallies",
        "month high",
        "year high",
        "price hike",
    )
)
_OIL_WORD_RX = re.compile(r"\b(oil|crude|brent|wti|fuel|petrol|diesel)\b", re.I)
_HOLD_RX = re.compile(
    r"\b(holds?|held|keeps?|kept|leaves?|left|pauses?)\b[^.]{0,40}\brates?\b"
    r"|\brates?\b[^.]{0,30}\b(unchanged|steady|on hold)\b",
    re.I,
)


def _oil_fell(head: str) -> bool:
    """Did the OIL price fall? The direction word nearest the oil word decides: "Rupee hits
    six-month high on oil price decline" read as oil up, from the rupee's high."""
    oil = [m.start() for m in _OIL_WORD_RX.finditer(head)]
    if not oil:
        return bool(_OIL_DOWN_RX.search(head)) and not _OIL_UP_RX.search(head)

    def nearest(rx: re.Pattern[str]) -> float:
        return min(
            (abs(m.start() - o) for m in rx.finditer(head) for o in oil), default=float("inf")
        )

    down, up = nearest(_OIL_DOWN_RX), nearest(_OIL_UP_RX)
    return down < up


_REGION_RX = {k: _pattern(v) for k, v in REGIONS.items()}
_WORLD_RX = _pattern(WORLD_WORDS)
_FAR_RX = _pattern(FAR_WORDS)
_LINK_RX = _pattern(MARKET_LINK)
# "US" in capitals only (the word "us" is everywhere)
_US_CAPS = re.compile(r"(?<![\w.])US(?![\w])")


@dataclass(frozen=True)
class Reading:
    topics: tuple[str, ...]
    severity: int
    impact: float
    scope: str  # "IN", "US" or "WORLD"
    sectors: dict[str, int]
    calming: bool

    @property
    def group(self) -> str | None:
        return BY_KEY[self.topics[0]].group if self.topics else None


INDEX_WORDS = (
    "s&p 500",
    "s&p",
    "s & p",
    "nasdaq",
    "nasdaq 100",
    "dow",
    "dow jones",
    "nifty",
    "sensex",
    "nifty 50",
    "bank nifty",
    "wall street",
    "russell 2000",
    "nikkei",
    "kospi",
    "hang seng",
    "stoxx",
    "ftse",
    "dax",
)
FALL_WORDS = (
    "down",
    "falls",
    "fell",
    "drops",
    "dropped",
    "slides",
    "slid",
    "slumps",
    "slumped",
    "plunges",
    "plunged",
    "plummets",
    "plummeted",
    "tumbles",
    "tumbled",
    "crashes",
    "crashed",
    "sinks",
    "sank",
    "sheds",
    "loses",
    "lost",
    "tanks",
    "tanked",
    "sell-off",
    "selloff",
    "worst",
    "rout",
    "bleeds",
    "cracks",
)
DROP_SEVERE = (2.0, 4.0)
_SECTOR_RX = re.compile(
    r"\s*(realty|bank|it|pharma|auto|metal|fmcg|energy|media|psu|financial|fin|oil|healthcare|"
    r"infra|midcap|smallcap|next 50|consumer|chemicals|defence|private bank|psu bank)\b"
)
# conflict words that also mean other things; alone they don't make a story a war (D-187)
WEAK_CONFLICT = frozenset(
    {"escalation", "offensive", "retaliation", "clashes", "military", "blockade", "retaliates"}
)  # an index falling this many percent: severity 4, then 5
_INDEX_RX = re.compile(r"(?<![\w&])(" + "|".join(re.escape(w) for w in INDEX_WORDS) + r")(?![\w&])")
_FALL_RX = re.compile(r"(?<![\w&])(" + "|".join(re.escape(w) for w in FALL_WORDS) + r")(?![\w&])")
_PCT_RX = re.compile(r"(\d+(?:\s?\.\s?\d+)?)\s?%")


# places and markets that tie headlines to one event (``risk.stories``, D-189)
ANCHOR_RX = (_INDEX_RX, *(_pattern(v) for v in REGIONS.values()), _pattern(WORLD_WORDS))


def index_drop(head: str) -> float:
    """How far an index fell, in percent, when the headline names an index, a fall and a
    percentage ("Nifty down 3.2%"); 0 otherwise."""
    best = 0.0
    for m in _INDEX_RX.finditer(head):
        # the fall and its size right after the index's name: "Nifty down 3.2%", not
        # "Zomato shares down 8% after results, Nifty flat"
        # within its own clause: "Nifty below 24,500; Power Grid drops 3%" is a stock's fall
        after = re.split(r";|\||, | - | – ", head[m.end() : m.end() + 40])[0]
        if _SECTOR_RX.match(after):
            continue  # "Nifty Realty down 2%": one sector's index, not the market (D-194)
        if not _FALL_RX.search(after):
            continue
        pct = _PCT_RX.search(after)
        if pct is not None:
            v = float(pct.group(1).replace(" ", ""))
            if v < 40:
                best = max(best, v)
    return best


def _plain(low: str) -> str:
    """Remove phrases where a war or crisis word means something else (D-179)."""
    # a trade war is a trade story: "war" alone made it armed conflict (D-229)
    return _NOT_RX.sub(" ", low.replace("trade war", "tariff dispute"))


def classify(title: str, summary: str = "", market: str | None = None) -> Reading:
    """Read one headline (``market`` is the feed's market, used when no place is named).

    What a story is *about* comes from the headline first: a topic named only in the summary
    (often background, "since Russia's invasion of Ukraine", "during the pandemic") counts one
    severity lower, and the words that raise severity (``ESCALATE``, ``TOP``) count only in the
    headline (D-179: an ice-hockey story and a governor's race read as an invasion and a
    pandemic from their summaries)."""
    text = f"{title}. {summary}"
    low = _plain(text.lower())
    head = _plain(title.lower())
    found: list[tuple[int, int, str]] = []
    for t in TOPICS:
        hits = _TOPIC_RX[t.key].findall(low)
        # "root escalation exploits", "military and NASA power problems": a word that is also
        # everyday English, with no war word or warring place beside it, isn't a war (D-187)
        weak = bool(hits) and {h.lower() for h in hits} <= WEAK_CONFLICT
        if t.key == "conflict" and weak and not _WORLD_RX.search(low):
            continue
        if hits:
            # title words count double: the headline is what the desk reacts to
            in_title = len(_TOPIC_RX[t.key].findall(head))
            found.append((in_title, len(hits) + in_title, t.key))
    # the headline's topics first, then the most severe; company news only if nothing bigger
    found.sort(key=lambda x: (x[0] == 0, -BY_KEY[x[2]].severity, -x[1]))
    title_topics = {k for n, _, k in found if n}
    keys = tuple(k for _, _, k in found)
    if len(keys) > 1 and "corporate" in keys:
        keys = (*(k for k in keys if k != "corporate"), "corporate")
    # an index's own fall, by its size (D-183: "S&P 500 down 4.4% in worst day since April
    # 2025" and "Nasdaq 100 plunges 6.36%" read as severity 3, the gauge stayed calm)
    drop = index_drop(head)
    if drop >= DROP_SEVERE[0] and "market_stress" not in keys:
        keys = ("market_stress", *keys)
    tone = sentiment.headline_score(title, summary)
    calming = bool(_CALM_RX.search(low))
    if not keys:
        return Reading((), 0, round(0.5 * tone, 3), _scope(text, low, market), {}, calming)
    main = BY_KEY[keys[0]]
    sev = main.severity
    if main.key not in title_topics:
        sev -= 1  # only the summary names it: background more often than news
    # "de-escalation" is calming news, not an escalation (D-188)
    escalates = bool(_ESC_RX.search(head.replace("de-escalat", "deescalat")))
    if escalates:
        sev += 1
    # whole words only: "coup" was found in "coupon" and "couple" (D-179)
    if any(all(rx.search(head) for rx in combo) for combo in _TOP_RX):
        sev = 5
    if calming and not escalates:
        sev = max(1, sev - 1)
    if drop >= DROP_SEVERE[1]:
        sev, calming = 5, False
    elif drop >= DROP_SEVERE[0]:
        sev, calming = max(sev, 4), False
    if _far_only(text, low):
        sev = min(sev, FAR_SEVERITY)  # a local crisis far away isn't systemic here (D-173)
    sev = int(min(5, max(0, sev)))
    worded_calm = calming
    oil_down = "energy" in keys[:2] and _oil_fell(head)
    # a central bank standing still is neither a hike nor a cut (the audit, 27.3: "RBI holds repo
    # rate" read as a hike, with banks up and property down)
    held = main.key == "central_bank" and bool(_HOLD_RX.search(head))
    if main.key == "energy" and oil_down:
        calming = True  # cheaper oil eases costs and inflation (D-211)
    # direction: the topic's usual reaction, flipped for calming news, blended with tone
    base = 0.0 if held else abs(main.direction) if calming else main.direction
    # Word tone is tuned on company headlines ("surges" is good news for a stock, but
    # "oil surges" is bad news for markets), so world and economy news lean on the topic.
    lean = 0.8 if main.group != COMPANY else 0.3
    impact = lean * base + (1 - lean) * tone if base else tone
    sectors: dict[str, int] = {}
    # oil news reads as oil going up (producers gain, users lose); a falling oil price is the
    # other way round (D-211: "Oil Slides Below $100" and "oil prices crash" read as oil up)
    for k in keys[:2]:
        if held and k == "central_bank":
            continue
        flip = (k == "energy" and oil_down) or (worded_calm and k != "energy")
        for name, eff in BY_KEY[k].sectors.items():
            sectors.setdefault(name, -eff if flip else eff)
    return Reading(
        keys[:3],
        sev,
        round(max(-1.0, min(1.0, impact)), 3),
        _scope(text, low, market),
        sectors,
        calming,
    )


FAR_SEVERITY = 3
_US_MARKET_WORDS = frozenset(
    {
        "u.s.",
        "united states",
        "fed",
        "federal reserve",
        "fomc",
        "wall street",
        "nasdaq",
        "s&p",
        "s&p 500",
        "dow",
        "nyse",
        "powell",
    }
)


def _far_only(text: str, low: str) -> bool:
    """The story names only smaller, distant economies: not India, the US or the world list."""
    if not _FAR_RX.search(low):
        return False
    # only US markets or the US economy make a far country's story US news: every country has a
    # congress and a treasury, and "a Trump ally" is still a story about Paraguay (D-173)
    named = {m.lower() for m in _REGION_RX["US"].findall(low)} & _US_MARKET_WORDS
    us = bool(named) or bool(_US_CAPS.search(text))
    return not (us or _REGION_RX["IN"].search(low) or _WORLD_RX.search(low))


def _scope(text: str, low: str, market: str | None) -> str:
    if _far_only(text, low):
        return "WORLD"  # not the feed's market just because a US feed carried it (D-173)
    india = bool(_REGION_RX["IN"].search(low))
    us = bool(_REGION_RX["US"].search(low)) or bool(_US_CAPS.search(text))
    world = bool(_WORLD_RX.search(low))
    if world or (india and us):
        return "WORLD"
    if india:
        return "IN"
    if us:
        return "US"
    return market or "WORLD"


def market_linked(text: str) -> bool:
    """Does the text talk about markets, prices or the economy at all?"""
    return bool(_LINK_RX.search(text.lower()))


def label(key: str) -> str:
    return BY_KEY[key].label if key in BY_KEY else key


# Bump when the reading's logic changes (not only its word lists), so saved headlines are read
# again: D-183's index falls weren't applied to the stories already saved until this existed.
RULES = "2026-11-07 a"  # D-229: oil direction, rates held, trade wars


def _version() -> str:
    """A fingerprint of every word list and rule above: when it changes, saved headlines are
    read again (``NewsService._backfill``), so a fix reaches the stories already in the gauge."""
    import hashlib

    parts = (TOPICS, ESCALATE, CALM, TOP, REGIONS, WORLD_WORDS, FAR_WORDS, MARKET_LINK, NOT_WAR)
    extra = (FAR_SEVERITY, sorted(_US_MARKET_WORDS), INDEX_WORDS, FALL_WORDS, DROP_SEVERE, RULES)
    return hashlib.sha1(repr((parts, extra)).encode("utf-8")).hexdigest()[:12]


VERSION = _version()


def far_only(text: str) -> bool:
    """Public: the story names only smaller, distant economies (D-173, D-213)."""
    return _far_only(text, _plain(text.lower()))
