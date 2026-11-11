"""Which stocks a headline is about.

A stock matches when its ticker (3+ letters, written in capitals) or one of its names
(written as the company writes it, or in capitals) appears as a whole word. Names come
from the company name with the legal suffix removed ("Reliance Industries Ltd." →
"Reliance Industries"), its first word when that word is distinctive, and a few names
headlines actually use ("Airtel", "L&T", "Google", "Reliance").

**Distinctive (D-179).** Headlines are written in Title Case, so a company's first word
matched every headline that used it: "United" linked every story about the United States
or the United Nations to 20 companies named United…, "American", "Global", "Federal" and
"South" did the same, "Share India Securities" was linked to 355 headlines about shares,
and Nasdaq Inc., Dow Inc. and News Corp to every story about the indexes and the news.
A first word now counts alone only when no other listed company starts with it
(``shared``, from the whole list) and it isn't an everyday word (``GENERIC``); a one-word
name that is an everyday word ("Dow", "Nasdaq", "News") counts only through its ticker or
a fuller name in ``EXTRA``. And a headline from an Indian or US feed links only that
market's stocks (``Matcher.find(text, market)``): "Reliance" in an Indian story is
Reliance Industries, not the US steel maker Reliance, Inc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SUFFIXES = re.compile(
    r"(,?\s+(ltd\.?|limited|inc\.?|corporation|corp\.?|company|co\.|& co\.?|plc|trust|"
    r"\(class [a-z]\)))+\s*$",
    re.IGNORECASE,
)
SHARED_FIRST_WORDS = {
    "tata",
    "bajaj",
    "adani",
    "hdfc",
    "state",
    "bharat",
    "bharti",
    "hindustan",
    "power",
    "oil",
    "jio",
    "max",
    "sun",
    "tech",
    "mahindra",
    "shriram",
    "indian",
    "india",
    "national",
    "spdr",
    "invesco",
    "meta",
    "asian",
    "apollo",
    "eicher",
    "coal",
    "titan",
    "trent",
    "grasim",
    "cipla",
}
EXTRA: dict[str, tuple[str, ...]] = {
    "SBIN": ("SBI", "State Bank of India"),
    "LT": ("L&T", "Larsen & Toubro", "Larsen"),
    "M&M": ("M&M", "Mahindra & Mahindra"),
    "BHARTIARTL": ("Airtel", "Bharti Airtel"),
    "INDIGO": ("IndiGo", "InterGlobe"),
    "HINDUNILVR": ("HUL", "Hindustan Unilever"),
    "ETERNAL": ("Eternal", "Zomato"),
    "TMPV": ("Tata Motors",),
    "ULTRACEMCO": ("UltraTech",),
    "DRREDDY": ("Dr Reddy's", "Dr. Reddy's", "Dr Reddy"),
    "SUNPHARMA": ("Sun Pharma",),
    "KOTAKBANK": ("Kotak",),
    "HCLTECH": ("HCLTech", "HCL Tech"),
    "JIOFIN": ("Jio Financial",),
    "TITAN": ("Titan",),
    "TRENT": ("Trent",),
    "CIPLA": ("Cipla",),
    "COALINDIA": ("Coal India",),
    "EICHERMOT": ("Eicher", "Royal Enfield"),
    "GOOGL": ("Alphabet", "Google"),
    "META": ("Meta Platforms", "Facebook", "Meta"),
    "AMZN": ("Amazon",),
    "NVDA": ("Nvidia",),
    "JPM": ("JPMorgan", "JP Morgan"),
    "SPY": ("S&P 500",),
    "QQQ": ("Nasdaq 100", "Nasdaq-100"),
    "RELIANCE": ("Reliance", "RIL"),  # "Reliance" in Indian headlines (D-179)
    "NDAQ": ("Nasdaq Inc", "Nasdaq, Inc."),
    "DOW": ("Dow Inc", "Dow Chemical"),
    "RS": ("Reliance Steel", "Reliance, Inc."),
    "FOX": ("Fox Corp", "Fox Corporation"),
    "FOXA": ("Fox Corp", "Fox Corporation"),
    "NWS": ("News Corp",),
    "NWSA": ("News Corp",),
}
SYMBOL_IS_A_WORD = {"BSE", "ALL", "DOW", "MCX"}  # tickers that are also everyday words in headlines
# fmt: off
GENERIC = {
    "united", "american", "america", "global", "south", "north", "east", "west", "eastern",
    "western", "northern", "southern", "central", "federal", "general", "first", "capital",
    "consumer", "energy", "news", "share", "shares", "health", "financial", "finance",
    "international", "royal", "pacific", "atlantic", "standard", "universal", "public",
    "community", "home", "great", "prime", "premier", "advanced", "applied", "digital", "smart",
    "dow", "nasdaq", "market", "markets", "stock", "stocks", "money", "bank", "banks", "data",
    "life", "world", "golden", "silver", "green", "white", "black", "star", "power", "metro",
    "urban", "select", "total", "alpha", "summit", "pioneer", "liberty", "freedom", "eagle",
    "phoenix", "vision", "future", "china", "japan", "asia", "europe", "british", "canadian",
    "electronics", "industries", "holdings", "group", "technology", "technologies", "systems",
    "services", "solutions", "partners", "resources", "brands", "foods", "motors", "airlines",
    "airways", "medical", "pharma", "pharmaceuticals", "insurance", "realty", "steel",
    "cement", "chemicals", "infra", "infrastructure", "ventures", "enterprises", "trust",
    "income", "growth", "value", "dividend", "strategic", "secure", "security", "national",
    "regional", "liquid", "index", "fund", "funds", "sector", "new", "best", "next", "one",
    "state", "states", "union", "republic",
    # people and institutions in the news, not companies
    "trump", "biden", "musk", "house", "senate", "congress", "president", "people", "social",
    "investors", "investor", "birla", "city", "county", "court", "police", "army", "business",
    "goyal", "sitharaman", "powell", "modi", "gandhi", "ambani",
    # places: a company named after a place matched every story about it
    "canada", "mexico", "texas", "california", "florida", "washington", "london", "paris",
    "berlin", "tokyo", "hong", "singapore", "dubai", "africa", "australia", "brazil", "korea",
    "germany", "france", "italy", "spain", "russia", "ukraine", "israel", "iran", "turkey",
    "jersey", "york", "boston", "chicago", "denver", "atlanta", "dallas", "houston", "miami",
    "carolina", "virginia", "georgia", "ohio", "michigan", "kansas", "arizona", "nevada",
    "oregon", "utah", "colorado", "tennessee", "kentucky", "alabama", "hawaii", "alaska",
    "montana", "idaho", "maine", "vermont", "dakota", "iowa", "missouri", "oklahoma",
    "arkansas", "louisiana", "mississippi", "indiana", "illinois", "wisconsin", "minnesota",
    "nebraska", "delaware", "maryland", "connecticut", "massachusetts", "pennsylvania",
    "midwest", "gulf", "mumbai", "delhi", "bharat", "hindustan", "gujarat", "punjab",
    "kerala", "bengal", "chennai", "kolkata", "hyderabad", "bangalore", "bengaluru",
}
# fmt: on


@dataclass(frozen=True)
class Target:
    instrument_id: int
    symbol: str
    names: tuple[str, ...]
    market: str | None = None


def short_name(name: str) -> str:
    return SUFFIXES.sub("", name.replace(".com", "")).strip(" ,")


TRAILING = {"holdings", "group", "corporation", "incorporated", "enterprises"}


def _core(short: str) -> str:
    """The name without a trailing "Holdings" or "Group", when two or more words remain."""
    words = short.split()
    while len(words) > 2 and words[-1].lower() in TRAILING:
        words.pop()
    return " ".join(words) if len(words) >= 2 else short


def first_word(name: str) -> str:
    short = short_name(name)
    return short.split()[0].lower() if short else ""


def shared_first_words(names: list[str]) -> frozenset[str]:
    """First words that two or more listed companies start with ("united", "reliance"):
    alone they don't say which company a headline means."""
    seen: dict[str, int] = {}
    for n in names:
        w = first_word(n)
        if w:
            seen[w] = seen.get(w, 0) + 1
    return frozenset(w for w, k in seen.items() if k >= 2)


def target(
    instrument_id: int,
    symbol: str,
    name: str,
    shared: frozenset[str] = frozenset(),
    market: str | None = None,
) -> Target:
    names: list[str] = []
    short = short_name(name)
    if short.upper() in SYMBOL_IS_A_WORD:
        short = name.rstrip(".")  # "BSE" alone means the exchange; "BSE Ltd" is the company
    one_word = bool(short) and " " not in short
    core = _core(short)
    if core != short:
        names.append(core)  # "United Airlines Holdings" is "United Airlines" in headlines
    if short and not (one_word and (short.lower() in GENERIC or short.lower() in shared)):
        # a one-word everyday or shared name ("Dow", "News", "Reliance") only via EXTRA
        names.append(short)
    if short:
        first = short.split()[0]
        low = first.lower()
        if (
            len(first) >= 5
            and low not in SHARED_FIRST_WORDS
            and low not in GENERIC
            and low not in shared
            and first != short
        ):
            names.append(first)
    names += EXTRA.get(symbol, ())
    return Target(instrument_id, symbol, tuple(dict.fromkeys(names)), market)


class Matcher:
    """Finds the stocks mentioned in a text; built once per list of stocks.

    A name counts only as written (Titan, not "a titan of industry") or in capitals, with no
    letter, digit or "&" right before or after it. Agora knows every listed stock (about 8,500,
    D-102), so instead of one pattern per stock the names are indexed by their first word: each
    word of the text looks up only the names that start with it."""

    def __init__(self, targets: list[Target]) -> None:
        self._by_head: dict[str, list[tuple[str, int]]] = {}
        self._odd: list[tuple[int, re.Pattern[str]]] = []  # names not starting with a word
        self._market = {t.instrument_id: t.market for t in targets}
        for t in targets:
            terms = {v for n in t.names for v in (n, n.upper())}
            sym = t.symbol
            if len(sym) >= 3 and sym.replace("&", "").isalpha() and sym not in SYMBOL_IS_A_WORD:
                terms.add(sym)
            for term in terms:
                head = _HEAD.match(term)
                if head is None:
                    rule = re.compile(r"(?<![\w&])" + re.escape(term) + r"(?![\w&])")
                    self._odd.append((t.instrument_id, rule))
                else:
                    self._by_head.setdefault(head.group(0), []).append((term, t.instrument_id))

    def find(self, text: str, market: str | None = None) -> set[int]:
        """The stocks ``text`` names; with ``market``, only that market's stocks (a stock
        whose market isn't known is kept)."""
        found: set[int] = set()
        for m in _WORD.finditer(text):
            pos = m.start()
            for term, iid in self._by_head.get(m.group(0), ()):
                end = pos + len(term)
                if text.startswith(term, pos) and not (end < len(text) and _JOINS.match(text[end])):
                    found.add(iid)
        found.update(iid for iid, rule in self._odd if rule.search(text))
        if market is not None:
            found = {i for i in found if self._market.get(i) in (None, market)}
        return found


def version() -> str:
    """A fingerprint of the matching rules: when it changes, saved headlines are linked to
    their stocks again (``NewsService._relink``)."""
    import hashlib

    parts = (sorted(GENERIC), sorted(SHARED_FIRST_WORDS), sorted(EXTRA.items()))
    rule = (sorted(SYMBOL_IS_A_WORD), sorted(TRAILING), "first>=5,unshared,market-filter,core")
    return hashlib.sha1(repr((parts, rule)).encode("utf-8")).hexdigest()[:12]


_HEAD = re.compile(r"[\w&]+")
_WORD = re.compile(r"(?<![\w&])[\w&]+")
_JOINS = re.compile(r"[\w&]")
