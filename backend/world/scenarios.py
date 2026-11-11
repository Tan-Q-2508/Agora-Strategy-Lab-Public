"""The world map: kinds of world events and how they ripple into markets (D-95).

Each **scenario** is a kind of event a macro desk watches for (a war in the Middle East, a
Taiwan Strait crisis, US tariffs on India, a Fed surprise, a banking scare…), written as:

- **how to recognise it** in a headline: the news topics it belongs to (``news/topics.py``),
  places that must be named (any one), extra words (any one) and a minimum severity;
- **the chain**: how it travels, in plain steps (war → oil supply → crude price → India's import
  bill → rupee and inflation → fuel retailers, airlines, paints…);
- **effects** per market on the whole market, on GICS sectors and on exposure tags
  (``watchlists/taxonomy.py``), each −2 (hurt a lot) … +2 (helped a lot), for the escalating
  version of the event; calming news (a ceasefire, a deal, a pause) reverses them;
- **assets** that usually move first and confirm it: oil, gold, the dollar, the rupee,
  volatility (VIX), bond yields.

The map is the prior: what history and the textbooks say. ``learn.py`` measures what each kind
of event actually did, on past events (``history.py``) and on every live event Agora sees, and
``impact.py`` blends the two, so the map keeps learning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Effects = dict[str, dict[str, int]]  # market → target ("market", a sector, "tag:x") → −2…+2


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    group: str  # war, energy, trade, rates, finance, politics, health, nature, tech
    topics: tuple[str, ...]
    places: tuple[str, ...] = ()
    words: tuple[str, ...] = ()
    min_severity: int = 2
    chain: tuple[str, ...] = ()
    effects: Effects = field(default_factory=dict)
    assets: dict[str, int] = field(default_factory=dict)  # oil, gold, usd, rupee, vix, yields
    two_sided: bool = False  # calming news is common and reverses it (wars, tariffs)


MIDEAST = (
    "israel",
    "israeli",
    "iran",
    "iranian",
    "tehran",
    "gaza",
    "hamas",
    "hezbollah",
    "lebanon",
    "syria",
    "iraq",
    "yemen",
    "houthi",
    "houthis",
    "saudi",
    "gulf",
    "middle east",
    "west bank",
    "idf",
    "irgc",
)
CHOKEPOINTS = (
    "strait of hormuz",
    "hormuz",
    "red sea",
    "bab el-mandeb",
    "bab-el-mandeb",
    "suez",
    "suez canal",
    "tanker",
    "tankers",
    "shipping lane",
    "shipping lanes",
    "strait of malacca",
    "panama canal",
    "black sea",
)
RUSSIA = (
    "russia",
    "russian",
    "ukraine",
    "ukrainian",
    "kremlin",
    "putin",
    "zelensky",
    "zelenskyy",
    "kyiv",
    "kiev",
    "moscow",
    "crimea",
    "donbas",
    "nato",
)
TAIWAN = ("taiwan", "taiwanese", "taipei", "tsmc", "taiwan strait")
CHINA = ("china", "chinese", "beijing", "xi jinping", "prc")
PAKISTAN = (
    "pakistan",
    "pakistani",
    "islamabad",
    "rawalpindi",
    "kashmir",
    "line of control",
    "loc",
    "pahalgam",
    "pulwama",
    "balakot",
    "operation sindoor",
    "lashkar",
    "jaish",
)
INDIA = ("india", "indian", "new delhi", "delhi", "modi", "rupee", "nifty", "sensex")
US = (
    "united states",
    "u.s.",
    "america",
    "american",
    "washington",
    "white house",
    "trump",
    "congress",
)
FED = ("fed", "fomc", "federal reserve", "powell", "fed chair")
RBI = ("rbi", "reserve bank of india", "repo rate", "mpc", "malhotra")

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "mideast_war",
        "War in the Middle East",
        "war",
        ("conflict", "terror", "sanctions", "energy"),
        places=MIDEAST,
        min_severity=3,
        chain=(
            "Fighting near the world's biggest oil producers raises the risk to supply: the "
            "Gulf ships about a third of the world's seaborne crude, a fifth of all oil passes "
            "the Strait of Hormuz.",
            "Crude oil, gold, the dollar and volatility rise; investors sell risky assets first.",
            "India imports about 85% of its oil: a dearer import bill weakens the rupee, lifts "
            "inflation and squeezes fuel retailers, airlines, paint and tyre makers. About 9 "
            "million Indians work in the Gulf, and their remittances matter too.",
            "In the US, oil producers and defence makers gain; airlines and travel lose.",
        ),
        effects={
            "IN": {
                "market": -1,
                "Energy": 0,
                "tag:oil_producer": 1,
                "tag:omc": -2,
                "tag:airline": -2,
                "tag:paints": -1,
                "tag:tyres": -1,
                "tag:defence": 1,
                "tag:gold": 1,
                "tag:it_services": 1,
            },
            "US": {
                "market": -1,
                "Energy": 1,
                "tag:oil_producer": 2,
                "tag:defence": 2,
                "tag:airline": -2,
                "tag:travel": -1,
                "tag:gold": 1,
            },
        },
        assets={"oil": 2, "gold": 1, "usd": 1, "rupee": -1, "vix": 1},
        two_sided=True,
    ),
    Scenario(
        "shipping_chokepoint",
        "A shipping chokepoint is threatened (Hormuz, Red Sea, Suez)",
        "war",
        ("conflict", "energy", "terror"),
        places=CHOKEPOINTS,
        chain=(
            "Ships avoid the danger zone: trips around Africa add 10–14 days, freight and "
            "insurance costs jump, and oil and gas cargoes are delayed.",
            "Oil and LNG prices rise; goods arrive later and cost more (inflation).",
            "Shipping lines earn more per container; importers and airlines pay more.",
        ),
        effects={
            "IN": {
                "market": -1,
                "tag:omc": -2,
                "tag:airline": -1,
                "tag:paints": -1,
                "tag:gas": -1,
                "tag:logistics": 1,
                "tag:oil_producer": 1,
            },
            "US": {"market": -1, "tag:oil_producer": 1, "tag:logistics": 1, "tag:airline": -1},
        },
        assets={"oil": 2, "vix": 1, "rupee": -1},
        two_sided=True,
    ),
    Scenario(
        "russia_ukraine",
        "Russia–Ukraine war or a Russia–NATO standoff",
        "war",
        ("conflict", "sanctions", "energy"),
        places=RUSSIA,
        min_severity=3,
        chain=(
            "Russia is a top exporter of oil, gas, wheat, fertilisers, aluminium, nickel and "
            "palladium; Ukraine of wheat, corn and sunflower oil.",
            "Escalation or new sanctions lift those prices; Europe's energy bill jumps.",
            "Defence spending rises across NATO. Fertiliser and food prices climb.",
            "India buys discounted Russian oil, which helps its refiners, but risks US penalties "
            "for it (the US added a 25% tariff on Indian goods over it in August 2025).",
        ),
        effects={
            "IN": {
                "market": -1,
                "tag:metals": 1,
                "tag:defence": 1,
                "tag:fertiliser": -1,
                "tag:omc": -1,
                "tag:refiner": 1,
            },
            "US": {
                "market": -1,
                "Energy": 1,
                "tag:defence": 2,
                "tag:fertiliser": 1,
                "tag:agri": 1,
                "tag:metals": 1,
                "tag:airline": -1,
            },
        },
        assets={"oil": 1, "gold": 1, "usd": 1, "vix": 1},
        two_sided=True,
    ),
    Scenario(
        "india_pakistan",
        "India–Pakistan tension",
        "war",
        ("conflict", "terror"),
        places=PAKISTAN,
        min_severity=2,
        chain=(
            "A terror attack or strikes across the border raise the fear of a wider war.",
            "Indian markets have usually dipped briefly and recovered (Kargil 1999, Uri 2016, "
            "Balakot 2019, Operation Sindoor 2025); a ceasefire brings a relief rally.",
            "Defence makers rise; airlines, hotels and travel dip.",
        ),
        effects={
            "IN": {"market": -1, "tag:defence": 2, "tag:airline": -1, "tag:travel": -1},
        },
        assets={"rupee": -1, "vix": 1},
        two_sided=True,
    ),
    Scenario(
        "terror_major",
        "Major terror attack in a big economy",
        "war",
        ("terror",),
        places=(
            "new york",
            "london",
            "paris",
            "washington",
            "mumbai",
            "delhi",
            "europe",
            "united states",
            "u.s.",
            "india",
        ),
        min_severity=3,
        chain=(
            "Markets react to what follows (war, security costs, travel fears) more than to the "
            "attack itself: after 9/11 the S&P 500 fell about 12% in the week it reopened and "
            "regained its level within about a month.",
            "Airlines, travel and insurers fall; defence rises.",
        ),
        effects={
            "US": {
                "market": -1,
                "tag:airline": -2,
                "tag:travel": -2,
                "tag:insurance": -1,
                "tag:defence": 1,
            },
            "IN": {"market": -1, "tag:airline": -1, "tag:travel": -1},
        },
        assets={"vix": 2, "gold": 1},
    ),
    Scenario(
        "india_china",
        "India–China border tension or trade curbs",
        "war",
        ("conflict", "trade", "sanctions"),
        places=("ladakh", "galwan", "arunachal", "doklam", "line of actual control", "lac"),
        chain=(
            "Clashes on the Himalayan border (Galwan 2020) bring calls to cut imports from China.",
            "India relies on China for drug ingredients (APIs), electronics parts and solar "
            "panels: curbs raise costs for pharma, electronics and solar makers, but help local "
            "makers over time.",
        ),
        effects={"IN": {"market": -1, "tag:defence": 1, "tag:pharma": -1, "tag:hardware": 1}},
        assets={"rupee": -1},
        two_sided=True,
    ),
    Scenario(
        "taiwan_strait",
        "Taiwan Strait crisis",
        "war",
        ("conflict", "sanctions", "trade"),
        places=TAIWAN,
        chain=(
            "Taiwan's TSMC makes about 90% of the world's most advanced chips.",
            "Military drills or a blockade threaten the chip supply of Apple, Nvidia, AMD and "
            "every carmaker; a war there would be the biggest supply shock in decades.",
            "Chip and hardware stocks fall most; defence rises; investors run to safety.",
        ),
        effects={
            "US": {
                "market": -1,
                "tag:semiconductors": -2,
                "tag:hardware": -2,
                "tag:ai_compute": -1,
                "tag:china_exposed": -1,
                "tag:defence": 1,
            },
            "IN": {"market": -1, "tag:hardware": -1, "tag:autos": -1},
        },
        assets={"vix": 2, "gold": 1, "usd": 1},
        two_sided=True,
    ),
    Scenario(
        "us_china_trade",
        "US–China trade war or chip export controls",
        "trade",
        ("trade", "sanctions", "regulation"),
        places=CHINA,
        words=(
            "tariff",
            "tariffs",
            "export control",
            "export controls",
            "entity list",
            "chip",
            "chips",
            "semiconductor",
            "rare earth",
            "rare earths",
            "trade war",
            "trade deal",
            "trade truce",
            "ban",
        ),
        chain=(
            "Tariffs and export controls hit US companies that sell to or make things in China "
            "(Apple, Tesla, Nvidia, Qualcomm, Nike, Starbucks) and US farmers.",
            "China answers with its own tariffs or curbs on rare earths, which chip and defence "
            "makers need.",
            'India can gain as companies move factories out of China ("China plus one"): '
            "electronics, chemicals and textiles.",
        ),
        effects={
            "US": {"market": -1, "tag:china_exposed": -2, "tag:semiconductors": -1, "tag:agri": -1},
            "IN": {"market": 0, "tag:hardware": 1, "tag:chemicals": 1, "tag:metals": -1},
        },
        assets={"vix": 1, "usd": 1},
        two_sided=True,
    ),
    Scenario(
        "us_tariffs_india",
        "US tariffs on India (or a US–India trade deal)",
        "trade",
        ("trade", "sanctions"),
        places=INDIA,
        words=(
            "tariff",
            "tariffs",
            "trade deal",
            "trade pact",
            "trade agreement",
            "duty",
            "duties",
            "h-1b",
            "h1b",
            "visa fee",
            "secondary tariff",
            "trade talks",
        ),
        chain=(
            "The US is India's biggest export market: textiles, gems and jewellery, seafood, "
            "auto parts, drugs and IT services.",
            "Higher US tariffs (or visa curbs on Indian IT workers) hurt those exporters and "
            "foreign investors pull money; a trade deal does the opposite.",
        ),
        effects={
            "IN": {
                "market": -1,
                "tag:exporter": -1,
                "tag:it_services": -1,
                "tag:textiles": -2,
                "tag:pharma": -1,
                "tag:autos": -1,
            },
            "US": {"tag:india_exposed": -1},
        },
        assets={"rupee": -1},
        two_sided=True,
    ),
    Scenario(
        "us_tariffs_world",
        "Broad US tariffs (a global trade war)",
        "trade",
        ("trade",),
        places=US,
        words=("tariff", "tariffs", "reciprocal", "trade war", "import tax", "levies"),
        min_severity=3,
        chain=(
            "Broad tariffs raise US prices, squeeze companies that import parts or goods, and "
            "invite retaliation; growth fears follow (2 April 2025: the S&P 500 fell about 12% "
            "in four days; a 90-day pause on 9 April brought one of its best days ever).",
            "Exporters everywhere, carmakers and retailers suffer; safe havens rise.",
        ),
        effects={
            "US": {
                "market": -2,
                "tag:china_exposed": -2,
                "tag:autos": -1,
                "tag:consumer": -1,
                "tag:semiconductors": -1,
                "tag:defensive": 1,
            },
            "IN": {"market": -1, "tag:exporter": -1, "tag:metals": -1},
        },
        assets={"vix": 2, "gold": 1},
        two_sided=True,
    ),
    Scenario(
        "opec_cut",
        "Oil supply cut (OPEC+, sanctions on oil exporters)",
        "energy",
        ("energy", "sanctions"),
        words=(
            "opec",
            "opec+",
            "output cut",
            "production cut",
            "supply cut",
            "oil sanctions",
            "price cap",
            "oil embargo",
            "saudi aramco",
        ),
        chain=(
            "Less oil on the market lifts crude prices.",
            "Good for oil producers; bad for oil importers like India (rupee, inflation, fuel "
            "retailers, airlines, paints, tyres) and for airlines everywhere.",
        ),
        effects={
            "IN": {
                "market": -1,
                "tag:oil_producer": 2,
                "tag:omc": -2,
                "tag:airline": -2,
                "tag:paints": -1,
                "tag:tyres": -1,
            },
            "US": {"Energy": 2, "tag:oil_producer": 2, "tag:airline": -2},
        },
        assets={"oil": 2, "rupee": -1},
    ),
    Scenario(
        "oil_crash",
        "Oil price collapse",
        "energy",
        ("energy",),
        words=(
            "oil plunges",
            "oil slumps",
            "oil crashes",
            "crude plunges",
            "crude slumps",
            "crude crashes",
            "oil price war",
            "glut",
            "oversupply",
            "output hike",
            "raise output",
            "boost output",
            "oil tumbles",
            "crude tumbles",
            "brent falls",
            "brent drops",
            "oil falls",
        ),
        chain=(
            "Cheap oil is a gift to importers: India's import bill shrinks, the rupee steadies, "
            "inflation eases.",
            "Fuel retailers, airlines, paint and tyre makers gain; oil producers and US shale "
            "lose (OPEC's November 2014 decision not to cut began a fall of more than half).",
        ),
        effects={
            "IN": {
                "market": 1,
                "tag:omc": 2,
                "tag:airline": 2,
                "tag:paints": 1,
                "tag:tyres": 1,
                "tag:oil_producer": -2,
            },
            "US": {"Energy": -2, "tag:oil_producer": -2, "tag:oil_services": -2, "tag:airline": 1},
        },
        assets={"oil": -2, "rupee": 1},
    ),
    Scenario(
        "fed_hawkish",
        "Fed hike or hawkish surprise",
        "rates",
        ("central_bank", "inflation"),
        places=FED,
        words=(
            "hike",
            "hikes",
            "hawkish",
            "higher for longer",
            "raises rates",
            "rate increase",
            "tightening",
            "no cut",
            "pause cuts",
            "fewer cuts",
        ),
        chain=(
            "Higher US rates make the dollar dearer and future profits worth less today.",
            "Growth stocks, homebuilders and small companies fall most; the dollar and bond "
            "yields rise.",
            "Foreign investors pull money from emerging markets like India; the rupee weakens.",
        ),
        effects={
            "US": {
                "market": -1,
                "tag:rate_sensitive": -2,
                "tag:software": -1,
                "tag:realty": -2,
                "tag:bank": 1,
            },
            "IN": {"market": -1, "tag:rate_sensitive": -1, "tag:it_services": 1},
        },
        assets={"usd": 1, "yields": 1, "gold": -1, "rupee": -1},
    ),
    Scenario(
        "fed_dovish",
        "Fed cut or dovish surprise",
        "rates",
        ("central_bank",),
        places=FED,
        words=(
            "rate cut",
            "rate cuts",
            "cuts rates",
            "dovish",
            "easing",
            "lowers rates",
            "slashes rates",
        ),
        chain=(
            "Cheaper money helps borrowers and lifts the value of future profits.",
            "Homebuilders, REITs, small companies and growth stocks gain; the dollar eases.",
            "Money flows back to emerging markets like India (unless the cut is because a "
            "recession is coming).",
        ),
        effects={
            "US": {"market": 1, "tag:rate_sensitive": 2, "tag:realty": 2, "tag:software": 1},
            "IN": {"market": 1, "tag:rate_sensitive": 1},
        },
        assets={"usd": -1, "yields": -1, "gold": 1, "rupee": 1},
    ),
    Scenario(
        "rbi_cut",
        "RBI rate cut",
        "rates",
        ("central_bank",),
        places=RBI,
        words=(
            "rate cut",
            "cuts repo",
            "cuts rates",
            "repo cut",
            "dovish",
            "lowers repo",
            "crr cut",
            "accommodative",
        ),
        chain=(
            "Cheaper loans help banks' borrowers, home buyers, car buyers and companies with debt.",
            "Banks, lenders, property developers and carmakers gain.",
        ),
        effects={
            "IN": {
                "market": 1,
                "tag:rate_sensitive": 2,
                "tag:realty": 2,
                "tag:nbfc": 1,
                "tag:autos": 1,
            }
        },
        assets={"rupee": -1},
    ),
    Scenario(
        "rbi_hike",
        "RBI rate hike or hawkish turn",
        "rates",
        ("central_bank", "inflation"),
        places=RBI,
        words=(
            "hike",
            "hikes repo",
            "raises repo",
            "hawkish",
            "tightening",
            "withdrawal of accommodation",
        ),
        chain=("Dearer loans weigh on borrowers: lenders, property, autos fall.",),
        effects={"IN": {"market": -1, "tag:rate_sensitive": -2, "tag:realty": -2}},
        assets={"rupee": 1},
    ),
    Scenario(
        "us_inflation_hot",
        "US inflation hotter than expected",
        "rates",
        ("inflation",),
        places=(*US, "cpi", "pce"),
        words=(
            "hotter",
            "higher than expected",
            "accelerat",
            "surges",
            "jumps",
            "rises more",
            "sticky",
            "above forecast",
            "beats forecast",
        ),
        chain=(
            "Hot inflation means the Fed keeps rates high for longer.",
            "Bonds and growth stocks fall; the dollar rises; emerging markets feel it next.",
        ),
        effects={
            "US": {"market": -1, "tag:rate_sensitive": -2, "tag:software": -1},
            "IN": {"market": -1},
        },
        assets={"usd": 1, "yields": 1, "rupee": -1},
    ),
    Scenario(
        "recession_fear",
        "Recession fears (weak jobs, falling output)",
        "rates",
        ("growth", "market_stress"),
        words=(
            "recession",
            "layoffs",
            "job cuts",
            "jobless claims",
            "contraction",
            "shrinks",
            "slowdown",
            "unemployment rises",
            "payrolls miss",
            "gdp contracts",
            "hard landing",
        ),
        chain=(
            "A slowing economy hurts profits of companies that depend on spending and "
            "investment: banks, carmakers, metals, capital goods, travel.",
            "Defensives (staples, utilities, health care) hold up better; bonds and gold rise.",
            "India's IT exporters suffer when their US and European clients cut budgets.",
        ),
        effects={
            "US": {
                "market": -2,
                "tag:defensive": 1,
                "tag:metals": -2,
                "tag:capex": -1,
                "tag:bank": -1,
                "tag:travel": -1,
                "tag:autos": -1,
            },
            "IN": {"market": -1, "tag:it_services": -2, "tag:metals": -2, "tag:defensive": 1},
        },
        assets={"yields": -1, "gold": 1, "oil": -1, "vix": 1},
    ),
    Scenario(
        "china_stimulus",
        "China stimulus",
        "rates",
        ("growth", "central_bank", "fiscal"),
        places=CHINA,
        words=(
            "stimulus",
            "rate cut",
            "cuts rates",
            "easing",
            "support package",
            "property support",
            "pboc",
        ),
        chain=(
            "China uses about half of the world's steel, copper and aluminium: stimulus lifts "
            "metal prices and miners.",
        ),
        effects={
            "IN": {"tag:metals": 2, "tag:steel": 1, "tag:aluminium": 1},
            "US": {"tag:metals": 2, "tag:china_exposed": 1, "tag:copper": 2},
        },
        assets={"oil": 1},
    ),
    Scenario(
        "china_slump",
        "China slowdown or property crisis",
        "rates",
        ("growth", "debt", "banking", "market_stress"),
        places=CHINA,
        words=(
            "slowdown",
            "property crisis",
            "evergrande",
            "country garden",
            "default",
            "deflation",
            "contraction",
            "devalue",
            "devaluation",
            "yuan falls",
            "weak demand",
        ),
        chain=(
            "Less Chinese building and factory output means less demand for metals and energy.",
            "Metal makers and miners fall; companies selling to China suffer; a weaker yuan "
            "exports deflation (August 2015's devaluation shook markets worldwide).",
        ),
        effects={
            "IN": {"market": -1, "tag:metals": -2},
            "US": {"market": -1, "tag:metals": -2, "tag:china_exposed": -2},
        },
        assets={"oil": -1, "vix": 1},
    ),
    Scenario(
        "banking_scare",
        "Banking scare",
        "finance",
        ("banking",),
        min_severity=3,
        chain=(
            "Depositors pull money from weak banks; banks stop lending to each other.",
            "Bank shares fall first and most (Lehman 2008, Silicon Valley Bank 2023), then the "
            "wider market; gold and government bonds rise; central banks step in.",
        ),
        effects={
            "US": {
                "market": -2,
                "tag:bank": -2,
                "tag:regional_bank": -2,
                "tag:gold": 1,
                "tag:defensive": 1,
            },
            "IN": {"market": -1, "tag:bank": -1, "tag:nbfc": -1},
        },
        assets={"vix": 2, "gold": 1, "yields": -1},
    ),
    Scenario(
        "rupee_slide",
        "Rupee slide",
        "finance",
        ("currency",),
        places=("rupee", "inr", "usd/inr", "usdinr"),
        words=(
            "record low",
            "all-time low",
            "falls",
            "slumps",
            "weakens",
            "depreciat",
            "slides",
            "plunges",
            "lifetime low",
        ),
        chain=(
            "A weaker rupee raises the cost of imports (oil, electronics, gold) and usually "
            "comes with foreign investors selling Indian shares.",
            "Exporters that earn in dollars (IT services, pharma) gain; importers and companies "
            "with dollar debt lose.",
        ),
        effects={
            "IN": {
                "market": -1,
                "tag:it_services": 2,
                "tag:exporter": 1,
                "tag:pharma": 1,
                "tag:omc": -1,
            }
        },
        assets={"rupee": -2},
    ),
    Scenario(
        "yen_carry",
        "Yen carry-trade unwind (Bank of Japan surprise)",
        "finance",
        ("central_bank", "currency", "market_stress"),
        places=("japan", "bank of japan", "boj", "yen", "nikkei", "ueda"),
        words=(
            "hike",
            "carry trade",
            "unwind",
            "yen surges",
            "yen jumps",
            "nikkei plunges",
            "crash",
        ),
        chain=(
            "Investors who borrowed cheap yen to buy other assets rush to repay when the yen "
            "jumps, selling whatever they own (5 August 2024: the Nikkei fell 12.4%).",
            "Crowded winners (chip stocks, momentum) fall most; volatility spikes worldwide.",
        ),
        effects={
            "US": {"market": -1, "tag:semiconductors": -2, "tag:software": -1},
            "IN": {"market": -1},
        },
        assets={"vix": 2, "usd": -1},
    ),
    Scenario(
        "pandemic",
        "Pandemic or health emergency",
        "health",
        ("health",),
        min_severity=4,
        chain=(
            "Lockdowns stop travel, shops and factories; earnings collapse for months.",
            "Travel, airlines and hotels fall most; drug makers, online platforms and staples "
            "hold up (February–March 2020: the S&P 500 fell about 34%, the Nifty about 38%).",
        ),
        effects={
            "US": {
                "market": -2,
                "tag:travel": -2,
                "tag:airline": -2,
                "tag:pharma": 1,
                "tag:internet": 1,
                "tag:defensive": 1,
                "tag:oil_producer": -2,
            },
            "IN": {
                "market": -2,
                "tag:travel": -2,
                "tag:airline": -2,
                "tag:pharma": 2,
                "tag:fmcg": 1,
            },
        },
        assets={"vix": 2, "oil": -2, "gold": 1, "yields": -1},
    ),
    Scenario(
        "disaster",
        "Major natural disaster",
        "nature",
        ("disaster",),
        min_severity=3,
        chain=(
            "Disasters move markets when they hit a big economy or a supply chain (Japan 2011: "
            "the Nikkei fell about 16% in two days).",
            "Insurers pay out; builders and cement makers later gain from rebuilding.",
        ),
        effects={
            "US": {"tag:insurance": -2, "market": 0},
            "IN": {"tag:insurance": -1, "tag:cement": 1},
        },
        assets={"vix": 1},
    ),
    Scenario(
        "monsoon",
        "Monsoon news",
        "nature",
        ("disaster", "growth", "inflation"),
        words=(
            "monsoon",
            "rainfall",
            "imd",
            "drought",
            "kharif",
            "sowing",
            "el nino",
            "deficient rain",
            "excess rain",
        ),
        chain=(
            "Most Indian farms depend on the June–September monsoon.",
            "A weak monsoon cuts rural income: tractors, two-wheelers, fertilisers and everyday "
            "goods sell less, and food prices rise. A good one does the opposite.",
        ),
        effects={"IN": {"tag:rural": -2, "tag:fertiliser": -1, "tag:fmcg": -1, "market": 0}},
        assets={},
        two_sided=True,
    ),
    Scenario(
        "us_politics",
        "US political shock (shutdown, debt ceiling, contested election)",
        "politics",
        ("politics", "debt", "fiscal"),
        places=(
            "congress",
            "senate",
            "white house",
            "shutdown",
            "debt ceiling",
            "debt limit",
            "capitol",
            "speaker",
            "election",
        ),
        chain=(
            "Standoffs over spending or the debt limit cause short scares (the August 2011 US "
            "downgrade was followed by a 6.7% fall in a day); gold and bonds rise.",
        ),
        effects={"US": {"market": -1, "tag:defence": -1, "tag:gold": 1}},
        assets={"vix": 1, "gold": 1},
        two_sided=True,
    ),
    Scenario(
        "india_politics",
        "Indian election or political shock",
        "politics",
        ("politics", "fiscal"),
        places=(
            *INDIA,
            "lok sabha",
            "bjp",
            "congress party",
            "exit poll",
            "exit polls",
            "election commission",
        ),
        chain=(
            "Markets dislike uncertainty more than any party: a surprise result (4 June 2024) "
            "sent the Nifty down about 6% in a day; it recovered once a government was clear.",
            "Government-owned companies, banks and capital goods move most on policy continuity.",
        ),
        effects={"IN": {"market": -1, "tag:psu_bank": -2, "tag:capex": -1, "tag:defence": -1}},
        assets={"rupee": -1},
        two_sided=True,
    ),
    Scenario(
        "defence_spending",
        "Higher defence spending",
        "war",
        ("conflict", "fiscal", "politics"),
        words=(
            "defence budget",
            "defense budget",
            "defence spending",
            "defense spending",
            "rearm",
            "rearmament",
            "military spending",
            "arms deal",
            "fighter jets",
            "defence order",
            "defense contract",
        ),
        min_severity=1,
        chain=("Governments ordering more weapons: defence makers' order books grow.",),
        effects={"IN": {"tag:defence": 2}, "US": {"tag:defence": 2}},
    ),
    Scenario(
        "nuclear_threat",
        "Nuclear threat",
        "war",
        ("conflict",),
        words=("nuclear", "nuke", "warhead", "atomic", "enrichment"),
        min_severity=3,
        chain=("Talk of nuclear weapons sends investors to safety: gold, the dollar, bonds.",),
        effects={
            "US": {"market": -1, "tag:defence": 1, "tag:gold": 1},
            "IN": {"market": -1, "tag:defence": 1},
        },
        assets={"vix": 2, "gold": 2, "usd": 1},
        two_sided=True,
    ),
    Scenario(
        "sanctions_wave",
        "New sanctions on a major economy",
        "trade",
        ("sanctions",),
        min_severity=3,
        chain=(
            "Sanctions on a big exporter lift what it sells (oil, gas, metals, grain) and hurt "
            "those who buy from it or sell to it.",
        ),
        effects={
            "US": {"tag:oil_producer": 1, "tag:metals": 1},
            "IN": {"tag:omc": -1, "tag:metals": 1},
        },
        assets={"oil": 1},
        two_sided=True,
    ),
    Scenario(
        "cyber_attack",
        "Major cyber attack or outage",
        "tech",
        ("cyber",),
        min_severity=2,
        chain=(
            "A big attack or outage hits the companies involved and can stop airlines, banks "
            "and payments for hours (the July 2024 global IT outage grounded flights).",
            "Cybersecurity companies often rise after big attacks.",
        ),
        effects={"US": {"tag:software": 0, "tag:airline": -1}, "IN": {"tag:it_services": -1}},
        assets={},
    ),
    Scenario(
        "ai_shock",
        "AI spending shock (boom or doubt)",
        "tech",
        ("corporate", "market_stress", "regulation"),
        words=(
            "ai spending",
            "ai capex",
            "data center",
            "data centre",
            "hyperscaler",
            "deepseek",
            "ai bubble",
            "ai chips",
            "gpu",
            "openai",
            "nvidia",
        ),
        min_severity=1,
        chain=(
            "Chip makers, server makers, data-centre builders and power producers live on AI "
            "spending: a doubt about it (DeepSeek, 27 January 2025: Nvidia fell about 17% in a "
            "day) hits all of them at once; a spending boom lifts them together.",
        ),
        effects={"US": {"tag:ai_compute": -2, "tag:semiconductors": -2, "market": -1}},
        assets={},
        two_sided=True,
    ),
)

BY_KEY = {s.key: s for s in SCENARIOS}
TARGET_LABEL_TAG = "tag:"


def target_label(target: str) -> str:
    """Plain words for an effect target."""
    if target == "market":
        return "the whole market"
    if target.startswith(TARGET_LABEL_TAG):
        from backend.watchlists.taxonomy import TAGS

        return TAGS.get(target[4:], target[4:]).split(":")[0]
    return target
