"""Which of the news topics' sectors a stock belongs to (D-211).

Each news topic names the sectors it usually helps (+1) or hurts (−1) (``topics.Topic.sectors``:
"Oil marketing", "Airlines", "Defence"…). A stock's profile (D-93) has a GICS sector, an industry
and exposure tags (``oil_user``, ``exporter``…). This maps one onto the other, so the news guard
can be cautious on a stock the news hurts and look for an opportunity on one it helps.
"""

from __future__ import annotations

from collections.abc import Iterable

# topic sector → (profile tags, GICS sectors, words in the industry name, lower case)
MATCH: dict[str, tuple[frozenset[str], frozenset[str], tuple[str, ...]]] = {
    "Airlines": (frozenset(), frozenset(), ("airline", "air transport", "aviation")),
    "Autos": (frozenset({"autos"}), frozenset(), ("auto", "motor vehicle", "two wheeler")),
    "Banks": (frozenset({"bank", "regional_bank"}), frozenset(), ("bank",)),
    "Cement": (frozenset({"cement"}), frozenset(), ("cement",)),
    "Chemicals": (frozenset({"chemicals"}), frozenset(), ("chemical",)),
    "Defence": (frozenset({"defence"}), frozenset(), ("defense", "defence", "aerospace")),
    "Energy": (
        frozenset({"oil_producer", "gas", "refiner", "oil_services"}),
        frozenset({"Energy"}),
        ("oil & gas", "petroleum"),
    ),
    "Exporters": (frozenset({"exporter", "it_services"}), frozenset(), ()),
    "Financials": (frozenset({"bank", "nbfc", "insurance"}), frozenset({"Financials"}), ()),
    "Gold": (frozenset(), frozenset(), ("precious metal", "gold", "jewel")),
    "IT services": (frozenset({"it_services", "software"}), frozenset(), ("it services", "edp")),
    "Importers": (frozenset({"oil_user"}), frozenset(), ()),
    "Insurance": (frozenset({"insurance"}), frozenset(), ("insur",)),
    "Metals": (frozenset({"metals", "steel"}), frozenset(), ("metal", "steel", "mining")),
    "Oil marketing": (frozenset({"refiner"}), frozenset(), ("refiner", "oil marketing")),
    "Oil producers": (frozenset({"oil_producer"}), frozenset(), ("oil & gas production",)),
    "Paints": (frozenset(), frozenset(), ("paint",)),
    "Pharma": (frozenset({"pharma"}), frozenset(), ("pharma",)),
    "Real estate": (frozenset({"realty"}), frozenset({"Real Estate"}), ("real estate",)),
    "Travel": (frozenset({"travel"}), frozenset(), ("hotel", "airline", "travel", "tourism")),
}


def names_for(sector: str, industry: str, tags: Iterable[str]) -> frozenset[str]:
    """The topic sectors a stock with this profile belongs to."""
    tagset = {t for t in tags if t}
    ind = industry.lower()
    out = {
        name
        for name, (want_tags, sectors, words) in MATCH.items()
        if tagset & want_tags or sector in sectors or any(w in ind for w in words)
    }
    return frozenset(out)
