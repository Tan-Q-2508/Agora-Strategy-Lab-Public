"""The ready-made watchlists (D-94): indices, sectors, sizes, factor lists, themes and ETFs.

Every list is defined by a rule over the stock profiles (``taxonomy.py``), so refreshing the
seed files refreshes the lists. Kinds of rule:

- ``index``: members of an index (official constituent files: NSE, S&P, Nasdaq, Dow);
- ``sector`` / ``size`` / ``tag``: by profile, optionally narrowed to an index (e.g. the
  large-cap energy stocks);
- ``symbols``: a fixed list (ETFs, themes such as the Magnificent 7);
- ``factor``: worked out from saved prices (momentum, low volatility, 52-week highs…), the way
  quant firms build factor portfolios; rebuilt each day while Agora is open (``factors.py``).

The factor lists from NSE (Nifty200 Momentum 30, Nifty100 Low Volatility 30, Nifty200
Quality 30, Nifty Alpha 50, Nifty Dividend Opportunities 50) are the exchange's own smart-beta
indices, rebuilt by NSE twice a year from fundamentals Agora doesn't have (quality, value).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.watchlists.taxonomy import SECTORS


@dataclass(frozen=True)
class Ready:
    key: str
    market: str
    name: str
    category: str  # index, sector, size, factor, theme, etf
    description: str
    rule: dict[str, object] = field(default_factory=dict)


# US exchange-traded funds Agora knows by name (symbol, name).
US_ETFS: tuple[tuple[str, str], ...] = (
    ("SPY", "SPDR S&P 500 ETF Trust"),
    ("QQQ", "Invesco QQQ Trust"),
    ("DIA", "SPDR Dow Jones Industrial Average ETF"),
    ("IWM", "iShares Russell 2000 ETF"),
    ("RSP", "Invesco S&P 500 Equal Weight ETF"),
    ("MDY", "SPDR S&P MidCap 400 ETF"),
    ("XLK", "Technology Select Sector SPDR"),
    ("XLF", "Financial Select Sector SPDR"),
    ("XLE", "Energy Select Sector SPDR"),
    ("XLV", "Health Care Select Sector SPDR"),
    ("XLY", "Consumer Discretionary Select Sector SPDR"),
    ("XLP", "Consumer Staples Select Sector SPDR"),
    ("XLI", "Industrial Select Sector SPDR"),
    ("XLB", "Materials Select Sector SPDR"),
    ("XLU", "Utilities Select Sector SPDR"),
    ("XLRE", "Real Estate Select Sector SPDR"),
    ("XLC", "Communication Services Select Sector SPDR"),
    ("MTUM", "iShares MSCI USA Momentum Factor ETF"),
    ("QUAL", "iShares MSCI USA Quality Factor ETF"),
    ("VLUE", "iShares MSCI USA Value Factor ETF"),
    ("USMV", "iShares MSCI USA Min Vol Factor ETF"),
    ("SIZE", "iShares MSCI USA Size Factor ETF"),
    ("SPLV", "Invesco S&P 500 Low Volatility ETF"),
    ("SCHD", "Schwab US Dividend Equity ETF"),
    ("VYM", "Vanguard High Dividend Yield ETF"),
    ("IWF", "iShares Russell 1000 Growth ETF"),
    ("IWD", "iShares Russell 1000 Value ETF"),
    ("GLD", "SPDR Gold Shares"),
    ("SLV", "iShares Silver Trust"),
    ("USO", "United States Oil Fund"),
    ("BNO", "United States Brent Oil Fund"),
    ("UNG", "United States Natural Gas Fund"),
    ("TLT", "iShares 20+ Year Treasury Bond ETF"),
    ("IEF", "iShares 7-10 Year Treasury Bond ETF"),
    ("HYG", "iShares iBoxx High Yield Corporate Bond ETF"),
    ("UUP", "Invesco DB US Dollar Index Bullish Fund"),
    ("EEM", "iShares MSCI Emerging Markets ETF"),
    ("EFA", "iShares MSCI EAFE ETF"),
    ("VGK", "Vanguard FTSE Europe ETF"),
    ("FXI", "iShares China Large-Cap ETF"),
    ("EWJ", "iShares MSCI Japan ETF"),
    ("EWT", "iShares MSCI Taiwan ETF"),
    ("INDA", "iShares MSCI India ETF"),
    ("ITA", "iShares U.S. Aerospace & Defense ETF"),
    ("JETS", "U.S. Global Jets ETF"),
    ("SMH", "VanEck Semiconductor ETF"),
    ("KRE", "SPDR S&P Regional Banking ETF"),
    ("XHB", "SPDR S&P Homebuilders ETF"),
    ("XOP", "SPDR S&P Oil & Gas Exploration & Production ETF"),
    ("GDX", "VanEck Gold Miners ETF"),
    ("COPX", "Global X Copper Miners ETF"),
    ("URA", "Global X Uranium ETF"),
    ("ICLN", "iShares Global Clean Energy ETF"),
    ("IBIT", "iShares Bitcoin Trust ETF"),
)
# Indian ETFs on NSE (symbol, name).
IN_ETFS: tuple[tuple[str, str], ...] = (
    ("NIFTYBEES", "Nippon India ETF Nifty 50 BeES"),
    ("JUNIORBEES", "Nippon India ETF Nifty Next 50 Junior BeES"),
    ("BANKBEES", "Nippon India ETF Nifty Bank BeES"),
    ("PSUBNKBEES", "Nippon India ETF Nifty PSU Bank BeES"),
    ("ITBEES", "Nippon India ETF Nifty IT"),
    ("GOLDBEES", "Nippon India ETF Gold BeES"),
    ("SILVERBEES", "Nippon India Silver ETF"),
    ("CPSEETF", "CPSE ETF"),
    ("MON100", "Motilal Oswal Nasdaq 100 ETF"),
)
# Market gauges the move investigator reads (D-96): (market, symbol, yahoo symbol, name).
GAUGES: tuple[tuple[str, str, str, str], ...] = (
    ("IN", "NIFTYBANK", "^NSEBANK", "Nifty Bank index"),
    ("IN", "NIFTYIT", "^CNXIT", "Nifty IT index"),
    ("IN", "NIFTYAUTO", "^CNXAUTO", "Nifty Auto index"),
    ("IN", "NIFTYPHARMA", "^CNXPHARMA", "Nifty Pharma index"),
    ("IN", "NIFTYFMCG", "^CNXFMCG", "Nifty FMCG index"),
    ("IN", "NIFTYMETAL", "^CNXMETAL", "Nifty Metal index"),
    ("IN", "NIFTYREALTY", "^CNXREALTY", "Nifty Realty index"),
    ("IN", "NIFTYENERGY", "^CNXENERGY", "Nifty Energy index"),
    ("IN", "NIFTYPSUBANK", "^CNXPSUBANK", "Nifty PSU Bank index"),
    ("IN", "NIFTYFIN", "NIFTY_FIN_SERVICE.NS", "Nifty Financial Services index"),
    ("IN", "NIFTYINFRA", "^CNXINFRA", "Nifty Infrastructure index"),
    ("IN", "NIFTYNEXT50", "^NSMIDCP", "Nifty Next 50 index"),
    ("IN", "NIFTY500", "^CRSLDX", "Nifty 500 index"),
    ("IN", "INDIAVIX", "^INDIAVIX", "India VIX (expected volatility)"),
    ("IN", "USDINR", "INR=X", "US dollar in rupees"),
    ("US", "VIX", "^VIX", "CBOE Volatility Index (the fear gauge)"),
)

# Every index on the Indices page (the user, 2026-11-05, D-174): (market, symbol, yahoo symbol,
# name, group). Groups: "broad" (the market as a whole and by size), "sector", "gauge"
# (volatility, currency, rates). Symbols checked on Yahoo on 2026-11-05; the gauges above are a
# subset, kept for the move investigator (D-96).
INDICES: tuple[tuple[str, str, str, str, str], ...] = (
    ("IN", "NIFTY50", "^NSEI", "Nifty 50", "broad"),
    ("IN", "SENSEX", "^BSESN", "BSE Sensex", "broad"),
    ("IN", "NIFTYNEXT50", "^NSMIDCP", "Nifty Next 50", "broad"),
    ("IN", "NIFTY100", "^CNX100", "Nifty 100", "broad"),
    ("IN", "NIFTY200", "^CNX200", "Nifty 200", "broad"),
    ("IN", "NIFTY500", "^CRSLDX", "Nifty 500", "broad"),
    ("IN", "BSE500", "BSE-500.BO", "BSE 500", "broad"),
    ("IN", "NIFTYMIDCAP100", "NIFTY_MIDCAP_100.NS", "Nifty Midcap 100", "broad"),
    ("IN", "NIFTYMIDCAP150", "NIFTYMIDCAP150.NS", "Nifty Midcap 150", "broad"),
    ("IN", "NIFTYSMALLCAP100", "^CNXSC", "Nifty Smallcap 100", "broad"),
    ("IN", "NIFTYSMALLCAP250", "NIFTYSMLCAP250.NS", "Nifty Smallcap 250", "broad"),
    ("IN", "NIFTYBANK", "^NSEBANK", "Nifty Bank", "sector"),
    ("IN", "NIFTYPVTBANK", "NIFTY_PVT_BANK.NS", "Nifty Private Bank", "sector"),
    ("IN", "NIFTYPSUBANK", "^CNXPSUBANK", "Nifty PSU Bank", "sector"),
    ("IN", "NIFTYFIN", "NIFTY_FIN_SERVICE.NS", "Nifty Financial Services", "sector"),
    ("IN", "NIFTYIT", "^CNXIT", "Nifty IT", "sector"),
    ("IN", "NIFTYAUTO", "^CNXAUTO", "Nifty Auto", "sector"),
    ("IN", "NIFTYPHARMA", "^CNXPHARMA", "Nifty Pharma", "sector"),
    ("IN", "NIFTYHEALTHCARE", "NIFTY_HEALTHCARE.NS", "Nifty Healthcare", "sector"),
    ("IN", "NIFTYFMCG", "^CNXFMCG", "Nifty FMCG", "sector"),
    ("IN", "NIFTYCONSUMPTION", "^CNXCONSUM", "Nifty India Consumption", "sector"),
    ("IN", "NIFTYCONSRDURBL", "NIFTY_CONSR_DURBL.NS", "Nifty Consumer Durables", "sector"),
    ("IN", "NIFTYMETAL", "^CNXMETAL", "Nifty Metal", "sector"),
    ("IN", "NIFTYENERGY", "^CNXENERGY", "Nifty Energy", "sector"),
    ("IN", "NIFTYOILGAS", "NIFTY_OIL_AND_GAS.NS", "Nifty Oil & Gas", "sector"),
    ("IN", "NIFTYCOMMODITIES", "^CNXCMDT", "Nifty Commodities", "sector"),
    ("IN", "NIFTYREALTY", "^CNXREALTY", "Nifty Realty", "sector"),
    ("IN", "NIFTYINFRA", "^CNXINFRA", "Nifty Infrastructure", "sector"),
    ("IN", "NIFTYMEDIA", "^CNXMEDIA", "Nifty Media", "sector"),
    ("IN", "NIFTYPSE", "^CNXPSE", "Nifty PSE", "sector"),
    ("IN", "NIFTYMNC", "^CNXMNC", "Nifty MNC", "sector"),
    ("IN", "NIFTYSERVICES", "^CNXSERVICE", "Nifty Services Sector", "sector"),
    ("IN", "INDIAVIX", "^INDIAVIX", "India VIX (expected volatility)", "gauge"),
    ("IN", "USDINR", "INR=X", "US dollar in rupees", "gauge"),
    ("US", "SPX", "^GSPC", "S&P 500", "broad"),
    ("US", "DJI", "^DJI", "Dow Jones Industrial Average", "broad"),
    ("US", "IXIC", "^IXIC", "Nasdaq Composite", "broad"),
    ("US", "NDX", "^NDX", "Nasdaq 100", "broad"),
    ("US", "RUT", "^RUT", "Russell 2000 (small caps)", "broad"),
    ("US", "SP400", "^MID", "S&P MidCap 400", "broad"),
    ("US", "SP600", "^SP600", "S&P SmallCap 600", "broad"),
    ("US", "NYA", "^NYA", "NYSE Composite", "broad"),
    ("US", "W5000", "^W5000", "Wilshire 5000 (the whole market)", "broad"),
    ("US", "SP500IT", "^SP500-45", "S&P 500 Information Technology", "sector"),
    ("US", "SP500FIN", "^SP500-40", "S&P 500 Financials", "sector"),
    ("US", "XLE", "XLE", "Energy (Energy Select Sector fund)", "sector"),
    ("US", "SP500HC", "^SP500-35", "S&P 500 Health Care", "sector"),
    ("US", "SP500IND", "^SP500-20", "S&P 500 Industrials", "sector"),
    ("US", "SP500DISC", "^SP500-25", "S&P 500 Consumer Discretionary", "sector"),
    ("US", "SP500STAP", "^SP500-30", "S&P 500 Consumer Staples", "sector"),
    ("US", "SP500UTIL", "^SP500-55", "S&P 500 Utilities", "sector"),
    ("US", "SP500MAT", "^SP500-15", "S&P 500 Materials", "sector"),
    ("US", "SP500RE", "^SP500-60", "S&P 500 Real Estate", "sector"),
    ("US", "SP500COMM", "^SP500-50", "S&P 500 Communication Services", "sector"),
    ("US", "SOX", "^SOX", "PHLX Semiconductor", "sector"),
    ("US", "DJT", "^DJT", "Dow Jones Transportation", "sector"),
    ("US", "DJU", "^DJU", "Dow Jones Utilities", "sector"),
    ("US", "VIX", "^VIX", "CBOE Volatility Index (the fear gauge)", "gauge"),
    ("US", "TNX", "^TNX", "US 10-year Treasury yield (%)", "gauge"),
    ("US", "DXY", "DX-Y.NYB", "US Dollar Index", "gauge"),
)

MAG7 = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA")


def _sector_lists() -> list[Ready]:
    out: list[Ready] = []
    for market, where in (("IN", "Nifty 500"), ("US", "S&P 500")):
        within = "nifty500" if market == "IN" else "sp500"
        for sec in SECTORS:
            key = f"{market.lower()}_sector_{sec.lower().replace(' ', '_')}"
            out.append(
                Ready(
                    key,
                    market,
                    f"{sec} ({where})",
                    "sector",
                    f"Every {where} stock in the {sec} sector (GICS sectors, the same 11 in "
                    "both markets).",
                    {"sector": sec, "within": within},
                )
            )
    return out


def _size_lists() -> list[Ready]:
    rows = [
        ("IN", "large", "Large caps (Nifty 100)", "India's 100 biggest companies (SEBI: top 100)."),
        (
            "IN",
            "mid",
            "Mid caps (Nifty Midcap 150)",
            "Companies 101–250 by size (SEBI's mid caps).",
        ),
        ("IN", "small", "Small caps (Nifty Smallcap 250)", "Companies 251–500 by size."),
        ("IN", "micro", "Micro caps (Nifty Microcap 250)", "Companies 501–750 by size."),
        ("US", "large", "Large caps (S&P 500)", "America's 500 leading large companies."),
        ("US", "mid", "Mid caps (S&P MidCap 400)", "Mid-sized US companies."),
        ("US", "small", "Small caps (S&P SmallCap 600)", "Small US companies with profits."),
    ]
    return [
        Ready(f"{m.lower()}_size_{s}", m, name, "size", desc, {"size": s})
        for m, s, name, desc in rows
    ]


def _index(key: str, market: str, name: str, desc: str, list_key: str, cat: str = "index") -> Ready:
    return Ready(key, market, name, cat, desc, {"list": list_key})


INDEX_LISTS: tuple[Ready, ...] = (
    _index("in_nifty50", "IN", "Nifty 50", "India's 50 biggest, most traded companies.", "nifty50"),
    _index(
        "in_niftynext50", "IN", "Nifty Next 50", "The next 50 after the Nifty 50.", "niftynext50"
    ),
    _index("in_nifty100", "IN", "Nifty 100", "Nifty 50 + Nifty Next 50.", "nifty100"),
    _index("in_nifty200", "IN", "Nifty 200", "India's 200 biggest companies.", "nifty200"),
    _index("in_nifty500", "IN", "Nifty 500", "About 92% of what's listed on NSE.", "nifty500"),
    _index("in_bank", "IN", "Nifty Bank", "The most traded Indian banks.", "bank"),
    _index("in_privatebank", "IN", "Nifty Private Bank", "Private-sector banks.", "privatebank"),
    _index("in_psubank", "IN", "Nifty PSU Bank", "Government-owned banks.", "psubank"),
    _index("in_finance", "IN", "Nifty Financial Services", "Banks, lenders, insurers.", "finance"),
    _index("in_it", "IN", "Nifty IT", "IT services exporters (earn in dollars).", "it"),
    _index("in_auto", "IN", "Nifty Auto", "Cars, bikes, trucks and parts.", "auto"),
    _index("in_pharma", "IN", "Nifty Pharma", "Drug makers, many of them exporters.", "pharma"),
    _index("in_healthcare", "IN", "Nifty Healthcare", "Drug makers and hospitals.", "healthcare"),
    _index("in_fmcg", "IN", "Nifty FMCG", "Everyday goods: steady demand.", "fmcg"),
    _index("in_metal", "IN", "Nifty Metal", "Steel, aluminium, zinc, mining.", "metal"),
    _index("in_realty", "IN", "Nifty Realty", "Property developers (rate-sensitive).", "realty"),
    _index("in_energy", "IN", "Nifty Energy", "Oil, gas, power and coal.", "energy"),
    _index(
        "in_oilgas", "IN", "Nifty Oil & Gas", "Producers, refiners, gas distributors.", "oilgas"
    ),
    _index("in_media", "IN", "Nifty Media", "Media and entertainment.", "media"),
    _index(
        "in_durables",
        "IN",
        "Nifty Consumer Durables",
        "Appliances, jewellery, paints.",
        "consumerdurables",
    ),
    _index("in_chemicals", "IN", "Nifty Chemicals", "Chemical makers.", "chemicals"),
    _index("in_defence", "IN", "Nifty India Defence", "Defence makers and shipyards.", "defence"),
    _index("in_infra", "IN", "Nifty Infrastructure", "Infrastructure builders and users.", "infra"),
    _index("in_commodities", "IN", "Nifty Commodities", "Commodity producers.", "commodities"),
    _index(
        "in_consumption", "IN", "Nifty India Consumption", "Consumer demand plays.", "consumption"
    ),
    _index("in_mnc", "IN", "Nifty MNC", "Indian arms of multinationals.", "mnc"),
    _index("in_pse", "IN", "Nifty PSE", "Government-owned companies.", "pse"),
    _index("in_cpse", "IN", "Nifty CPSE", "Central public sector companies.", "cpse"),
    _index("in_digital", "IN", "Nifty India Digital", "Digital economy companies.", "digital"),
    _index(
        "in_manufacturing",
        "IN",
        "Nifty India Manufacturing",
        "Makers of goods in India.",
        "manufacturing",
    ),
    _index("in_tourism", "IN", "Nifty India Tourism", "Hotels, travel and airlines.", "tourism"),
    _index("us_sp500", "US", "S&P 500", "America's 500 leading companies.", "sp500"),
    _index("us_ndx", "US", "Nasdaq-100", "The 100 biggest non-financial Nasdaq companies.", "ndx"),
    _index("us_dow", "US", "Dow Jones 30", "30 blue-chip US companies.", "dow"),
    _index("us_sp400", "US", "S&P MidCap 400", "Mid-sized US companies.", "sp400"),
    _index("us_sp600", "US", "S&P SmallCap 600", "Small US companies with profits.", "sp600"),
)

FACTOR_LISTS: tuple[Ready, ...] = (
    # The exchange's own smart-beta indices (NSE rebuilds them twice a year).
    _index(
        "in_momentum30",
        "IN",
        "Momentum 30 (NSE)",
        "Nifty200 Momentum 30: the 30 strongest risers of the Nifty 200 over 6 and 12 months, "
        "adjusted for volatility.",
        "momentum30",
        "factor",
    ),
    _index(
        "in_lowvol30",
        "IN",
        "Low volatility 30 (NSE)",
        "Nifty100 Low Volatility 30: the 30 calmest large caps.",
        "lowvol30",
        "factor",
    ),
    _index(
        "in_quality30",
        "IN",
        "Quality 30 (NSE)",
        "Nifty200 Quality 30: high return on equity, low debt, steady profits.",
        "quality30",
        "factor",
    ),
    _index(
        "in_alpha50",
        "IN",
        "Alpha 50 (NSE)",
        "Nifty Alpha 50: the 50 stocks that beat the market most over the last year.",
        "alpha50",
        "factor",
    ),
    _index(
        "in_divopp50",
        "IN",
        "Dividend opportunities 50 (NSE)",
        "Nifty Dividend Opportunities 50: high dividend yields.",
        "divopp50",
        "factor",
    ),
    # Worked out from saved prices, rebuilt daily (factors.py).
    *[
        Ready(
            f"{m.lower()}_{f}",
            m,
            name,
            "factor",
            desc,
            {"factor": f, "within": "nifty200" if m == "IN" else "sp500", "top": 30},
        )
        for m in ("IN", "US")
        for f, name, desc in (
            (
                "momentum",
                "Momentum leaders (12-1)",
                "Biggest rise over the last 12 months leaving out the latest month: the "
                "classic momentum factor (Jegadeesh & Titman; AQR, MSCI).",
            ),
            (
                "low_volatility",
                "Calmest stocks (low volatility)",
                "Smallest daily swings over the last year: the low-volatility anomaly.",
            ),
            (
                "near_high",
                "Near 52-week highs",
                "Closest to their 52-week high (George & Hwang): leaders often keep leading.",
            ),
            (
                "trend",
                "Strong uptrends",
                "Price above the 50-day average above the 200-day average, both rising "
                "(trend-following, like CTAs).",
            ),
            (
                "reversal",
                "Oversold in uptrends (short-term reversal)",
                "Fell most over the last week while still above the 200-day average: the "
                "short-term reversal effect quant desks trade.",
            ),
            (
                "relative_strength",
                "Relative strength vs the market",
                "Beat their index most over the last 3 months.",
            ),
        )
    ],
)

THEME_LISTS: tuple[Ready, ...] = (
    Ready(
        "us_mag7",
        "US",
        "Magnificent 7",
        "theme",
        "Apple, Microsoft, Nvidia, Amazon, Alphabet, Meta and Tesla.",
        {"symbols": list(MAG7)},
    ),
    Ready(
        "us_semis",
        "US",
        "Semiconductors",
        "theme",
        "Chip makers and chip-equipment makers.",
        {"tag": "semiconductors"},
    ),
    Ready(
        "us_ai",
        "US",
        "AI computing",
        "theme",
        "Chips, networking, servers, data centres and the power behind them.",
        {"tag": "ai_compute", "within": "sp500,ndx"},
    ),
    Ready(
        "us_defence", "US", "Defence", "theme", "Aerospace and defence makers.", {"tag": "defence"}
    ),
    Ready(
        "us_oil",
        "US",
        "Oil and gas producers",
        "theme",
        "Earn more when crude rises.",
        {"tag": "oil_producer"},
    ),
    Ready(
        "us_airlines",
        "US",
        "Airlines and travel",
        "theme",
        "Hurt by dear fuel, wars and pandemics.",
        {"tag": "airline,travel", "within": "sp500,sp400"},
    ),
    Ready("us_banks", "US", "Banks", "theme", "Big and regional banks.", {"tag": "bank"}),
    Ready(
        "us_regional_banks",
        "US",
        "Regional banks",
        "theme",
        "Most sensitive to deposit flight and rates (2023).",
        {"tag": "regional_bank"},
    ),
    Ready(
        "us_rate_sensitive",
        "US",
        "Rate-sensitive",
        "theme",
        "Homebuilders, REITs, regional banks: gain when rates fall.",
        {"tag": "rate_sensitive", "within": "sp500"},
    ),
    Ready(
        "us_defensives",
        "US",
        "Defensives",
        "theme",
        "Staples, utilities, health care: steady demand in any economy.",
        {"tag": "defensive", "within": "sp500"},
    ),
    Ready(
        "us_china",
        "US",
        "China-exposed",
        "theme",
        "Big sales or supply chains in China: tariffs and export controls hit them.",
        {"tag": "china_exposed"},
    ),
    Ready(
        "us_gold_metals",
        "US",
        "Gold and metals",
        "theme",
        "Gold miners and metal producers.",
        {"tag": "gold,metals"},
    ),
    Ready(
        "us_sector_etfs",
        "US",
        "Sector ETFs (SPDR)",
        "etf",
        "One fund per sector: the quickest way to see where money is moving.",
        {"symbols": ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]},
    ),
    Ready(
        "us_factor_etfs",
        "US",
        "Factor ETFs",
        "etf",
        "Momentum, quality, value, low volatility, size and dividends, as big quant funds "
        "package them.",
        {
            "symbols": [
                "MTUM",
                "QUAL",
                "VLUE",
                "USMV",
                "SIZE",
                "SPLV",
                "SCHD",
                "VYM",
                "IWF",
                "IWD",
                "RSP",
            ]
        },
    ),
    Ready(
        "us_macro_etfs",
        "US",
        "World and macro ETFs",
        "etf",
        "Gold, oil, gas, bonds, the dollar, Europe, China, Japan, Taiwan, India and emerging "
        "markets: where world events show first.",
        {
            "symbols": [
                "GLD",
                "SLV",
                "USO",
                "BNO",
                "UNG",
                "TLT",
                "IEF",
                "HYG",
                "UUP",
                "EEM",
                "EFA",
                "VGK",
                "FXI",
                "EWJ",
                "EWT",
                "INDA",
                "IBIT",
            ]
        },
    ),
    Ready(
        "us_theme_etfs",
        "US",
        "Theme ETFs",
        "etf",
        "Defence, airlines, chips, regional banks, homebuilders, oil explorers, gold miners, "
        "copper, uranium, clean energy.",
        {"symbols": ["ITA", "JETS", "SMH", "KRE", "XHB", "XOP", "GDX", "COPX", "URA", "ICLN"]},
    ),
    Ready(
        "us_index_etfs",
        "US",
        "Index ETFs",
        "etf",
        "The big US index funds.",
        {"symbols": ["SPY", "QQQ", "DIA", "IWM", "RSP", "MDY"]},
    ),
    Ready(
        "in_oil_hurt",
        "IN",
        "Hurt by dear oil",
        "theme",
        "India imports most of its oil: fuel retailers, airlines, paints, tyres.",
        {"tag": "omc,airline,paints,tyres"},
    ),
    Ready(
        "in_oil_gain",
        "IN",
        "Gain from dear oil",
        "theme",
        "Oil and gas producers.",
        {"tag": "oil_producer"},
    ),
    Ready(
        "in_exporters",
        "IN",
        "Exporters (weak rupee helps)",
        "theme",
        "IT services, pharma and other exporters earn in dollars.",
        {"tag": "exporter", "within": "nifty200"},
    ),
    Ready(
        "in_rate_sensitive",
        "IN",
        "Rate-sensitive",
        "theme",
        "Banks, lenders, property and autos: gain when the RBI cuts.",
        {"tag": "rate_sensitive", "within": "nifty100"},
    ),
    Ready(
        "in_defensives",
        "IN",
        "Defensives",
        "theme",
        "FMCG, pharma, utilities and telecom: steady demand.",
        {"tag": "defensive", "within": "nifty200"},
    ),
    Ready(
        "in_rural",
        "IN",
        "Rural India",
        "theme",
        "Tractors, two-wheelers, fertilisers, FMCG: the monsoon matters.",
        {"tag": "rural", "within": "nifty500"},
    ),
    Ready("in_gold", "IN", "Gold-linked", "theme", "Jewellers and gold lenders.", {"tag": "gold"}),
    Ready(
        "in_capex",
        "IN",
        "Capex and infrastructure",
        "theme",
        "Capital goods, construction, cement: the investment cycle.",
        {"tag": "capex", "within": "nifty200"},
    ),
    Ready(
        "in_capital_markets",
        "IN",
        "Capital markets",
        "theme",
        "Exchanges, brokers, depositories and fund houses: they live on market activity.",
        {"tag": "capital_markets"},
    ),
    Ready(
        "in_renewables",
        "IN",
        "Renewable energy",
        "theme",
        "Wind, solar and green power.",
        {"tag": "renewables"},
    ),
    Ready(
        "in_etfs",
        "IN",
        "Indian ETFs",
        "etf",
        "Index, bank, IT, gold and silver ETFs.",
        {"symbols": [s for s, _ in IN_ETFS]},
    ),
)


def all_ready() -> list[Ready]:
    return [*INDEX_LISTS, *_sector_lists(), *_size_lists(), *FACTOR_LISTS, *THEME_LISTS]
