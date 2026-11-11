"""What kind of company a stock is: sector, industry, size and exposure tags (D-93).

- **Sector**: the 11 GICS sectors for both markets, so "Energy" means the same in India and
  the US. US stocks carry S&P's own GICS sector; NSE's industry names are mapped onto them.
- **Industry**: the finer label as published (NSE's industry, or the GICS sub-industry).
- **Size**: by index membership, the way index providers and fund categories define it:
  India large = Nifty 100, mid = Nifty Midcap 150, small = Nifty Smallcap 250, micro =
  Nifty Microcap 250 (SEBI's large/mid/small cap lines are the top 100, the next 150, the
  rest); US large = S&P 500, mid = S&P MidCap 400, small = S&P SmallCap 600.
- **Exposure tags**: what a stock is sensitive to, for the world map (``backend/world``) and
  the theme watchlists: an oil producer, an oil user hurt by dear crude, an exporter that gains
  from a weak rupee, defence, airlines, banks, rate-sensitive, China-exposed and so on. Tags
  come from the industry and sub-industry, plus short hand-checked lists of companies where
  the industry is too coarse (NSE has no "paints" or "tyres" industry).
"""

from __future__ import annotations

SECTORS: tuple[str, ...] = (
    "Information Technology",
    "Financials",
    "Energy",
    "Health Care",
    "Consumer Discretionary",
    "Consumer Staples",
    "Industrials",
    "Materials",
    "Utilities",
    "Real Estate",
    "Communication Services",
)

NSE_SECTOR: dict[str, str] = {
    "Financial Services": "Financials",
    "Information Technology": "Information Technology",
    "Oil Gas & Consumable Fuels": "Energy",
    "Automobile and Auto Components": "Consumer Discretionary",
    "Consumer Durables": "Consumer Discretionary",
    "Consumer Services": "Consumer Discretionary",
    "Textiles": "Consumer Discretionary",
    "Media Entertainment & Publication": "Communication Services",
    "Telecommunication": "Communication Services",
    "Fast Moving Consumer Goods": "Consumer Staples",
    "Healthcare": "Health Care",
    "Capital Goods": "Industrials",
    "Construction": "Industrials",
    "Services": "Industrials",
    "Diversified": "Industrials",
    "Chemicals": "Materials",
    "Metals & Mining": "Materials",
    "Construction Materials": "Materials",
    "Forest Materials": "Materials",
    "Power": "Utilities",
    "Realty": "Real Estate",
}

# Exposure tags and what each means, in plain words (shown on watchlists and the world map).
TAGS: dict[str, str] = {
    "oil_producer": "Oil and gas producers: earn more when crude rises",
    "oil_services": "Oilfield services: follow drilling budgets",
    "refiner": "Refiners: live on the gap between crude and fuel prices",
    "omc": "Fuel retailers (India's oil marketing companies): hurt by dear crude",
    "gas": "Gas transmission and city gas: hurt by dear LNG",
    "oil_user": "Big users of crude-based inputs (paints, tyres, airlines, chemicals)",
    "airline": "Airlines: fuel is their biggest cost",
    "paints": "Paint makers: crude derivatives are a big input",
    "tyres": "Tyre makers: rubber and crude derivatives are big inputs",
    "defence": "Defence makers: gain when security spending rises",
    "it_services": "IT services: earn in dollars",
    "exporter": "Exporters: gain from a weaker home currency, hurt by tariffs",
    "pharma": "Drug makers",
    "bank": "Banks",
    "psu_bank": "Government-owned banks",
    "regional_bank": "US regional banks: most sensitive to deposit flight",
    "nbfc": "Lenders and finance companies other than banks",
    "insurance": "Insurers",
    "capital_markets": "Brokers, exchanges and asset managers: live on market activity",
    "metals": "Metals and mining: follow China and the world economy",
    "steel": "Steel makers",
    "aluminium": "Aluminium makers",
    "copper": "Copper",
    "gold": "Gold miners and jewellers: gold is a safe haven",
    "coal": "Coal and uranium",
    "cement": "Cement and building materials",
    "realty": "Property developers and REITs",
    "rate_sensitive": "Rate-sensitive: gain when interest rates fall",
    "autos": "Car, bike and truck makers and their parts suppliers",
    "fmcg": "Everyday goods: food, soap, drinks",
    "defensive": "Defensives: steady demand in any economy",
    "rural": "Rural demand: monsoon and farm income",
    "travel": "Hotels, travel and leisure",
    "logistics": "Shipping, ports, freight and logistics",
    "fertiliser": "Fertilisers and farm inputs: need gas and imported raw materials",
    "agri": "Farm products and machinery",
    "chemicals": "Chemicals",
    "telecom": "Telecom operators",
    "utility": "Power and water utilities",
    "renewables": "Renewable power",
    "capex": "Capital goods and construction: gain from investment and infrastructure spending",
    "semiconductors": "Chip makers and chip equipment: Taiwan, export controls, the AI cycle",
    "ai_compute": "AI computing: chips, servers, data centres and their power",
    "software": "Software and IT",
    "internet": "Internet platforms and online retail",
    "hardware": "Computer hardware and devices",
    "media": "Media and entertainment",
    "healthcare_services": "Hospitals, insurers and healthcare services",
    "staples_retail": "Supermarkets and discount stores",
    "china_exposed": "US companies with big sales or supply chains in China",
    "india_exposed": "US companies with big operations in India",
    "crypto": "Crypto-linked stocks",
    "textiles": "Textiles and apparel",
    "consumer": "Shops, restaurants and consumer services",
}

US_SUB_TAGS: dict[str, tuple[str, ...]] = {
    "Integrated Oil & Gas": ("oil_producer",),
    "Oil & Gas Exploration & Production": ("oil_producer",),
    "Oil & Gas Drilling": ("oil_producer", "oil_services"),
    "Oil & Gas Equipment & Services": ("oil_services",),
    "Oil & Gas Refining & Marketing": ("refiner",),
    "Oil & Gas Storage & Transportation": ("gas",),
    "Coal & Consumable Fuels": ("coal",),
    "Passenger Airlines": ("airline", "oil_user", "travel"),
    "Aerospace & Defense": ("defence",),
    "Semiconductors": ("semiconductors", "ai_compute"),
    "Semiconductor Materials & Equipment": ("semiconductors",),
    "Gold": ("gold",),
    "Precious Metals & Minerals": ("gold",),
    "Silver": ("gold",),
    "Steel": ("metals", "steel"),
    "Copper": ("metals", "copper"),
    "Aluminum": ("metals", "aluminium"),
    "Diversified Metals & Mining": ("metals",),
    "Fertilizers & Agricultural Chemicals": ("fertiliser", "agri"),
    "Agricultural Products & Services": ("agri",),
    "Agricultural & Farm Machinery": ("agri", "capex"),
    "Hotels, Resorts & Cruise Lines": ("travel",),
    "Casinos & Gaming": ("travel",),
    "Leisure Facilities": ("travel",),
    "Air Freight & Logistics": ("logistics",),
    "Marine Transportation": ("logistics",),
    "Cargo Ground Transportation": ("logistics",),
    "Rail Transportation": ("logistics",),
    "Diversified Banks": ("bank",),
    "Regional Banks": ("bank", "regional_bank", "rate_sensitive"),
    "Consumer Finance": ("nbfc",),
    "Transaction & Payment Processing Services": ("nbfc",),
    "Life & Health Insurance": ("insurance",),
    "Property & Casualty Insurance": ("insurance",),
    "Multi-line Insurance": ("insurance",),
    "Reinsurance": ("insurance",),
    "Insurance Brokers": ("insurance",),
    "Investment Banking & Brokerage": ("capital_markets",),
    "Asset Management & Custody Banks": ("capital_markets",),
    "Financial Exchanges & Data": ("capital_markets",),
    "Homebuilding": ("rate_sensitive", "realty"),
    "Home Improvement Retail": ("rate_sensitive",),
    "Building Products": ("rate_sensitive", "capex"),
    "Electric Utilities": ("utility", "defensive"),
    "Multi-Utilities": ("utility", "defensive"),
    "Gas Utilities": ("utility", "defensive"),
    "Water Utilities": ("utility", "defensive"),
    "Independent Power Producers & Energy Traders": ("utility", "ai_compute"),
    "Renewable Electricity": ("utility", "renewables"),
    "Automobile Manufacturers": ("autos",),
    "Automotive Parts & Equipment": ("autos",),
    "Automotive Retail": ("autos", "consumer"),
    "Motorcycle Manufacturers": ("autos",),
    "Tires & Rubber": ("autos", "tyres", "oil_user"),
    "Packaged Foods & Meats": ("fmcg", "defensive"),
    "Household Products": ("fmcg", "defensive"),
    "Soft Drinks & Non-alcoholic Beverages": ("fmcg", "defensive"),
    "Personal Care Products": ("fmcg", "defensive"),
    "Brewers": ("fmcg", "defensive"),
    "Distillers & Vintners": ("fmcg", "defensive"),
    "Tobacco": ("fmcg", "defensive"),
    "Food Retail": ("staples_retail", "defensive"),
    "Consumer Staples Merchandise Retail": ("staples_retail", "defensive"),
    "Food Distributors": ("fmcg", "defensive"),
    "Drug Retail": ("staples_retail", "defensive"),
    "Pharmaceuticals": ("pharma", "defensive"),
    "Biotechnology": ("pharma",),
    "Health Care Facilities": ("healthcare_services", "defensive"),
    "Managed Health Care": ("healthcare_services", "defensive"),
    "Health Care Services": ("healthcare_services",),
    "Application Software": ("software",),
    "Systems Software": ("software",),
    "IT Consulting & Other Services": ("software", "it_services"),
    "Internet Services & Infrastructure": ("software", "ai_compute"),
    "Interactive Media & Services": ("internet",),
    "Broadline Retail": ("internet", "consumer"),
    "Technology Hardware, Storage & Peripherals": ("hardware",),
    "Electronic Components": ("hardware",),
    "Communications Equipment": ("hardware", "ai_compute"),
    "Construction & Engineering": ("capex",),
    "Construction Machinery & Heavy Transportation Equipment": ("capex",),
    "Heavy Electrical Equipment": ("capex", "ai_compute"),
    "Electrical Components & Equipment": ("capex",),
    "Industrial Machinery & Supplies & Components": ("capex",),
    "Construction Materials": ("cement",),
    "Commodity Chemicals": ("chemicals", "oil_user"),
    "Specialty Chemicals": ("chemicals",),
    "Diversified Chemicals": ("chemicals",),
    "Integrated Telecommunication Services": ("telecom", "defensive"),
    "Wireless Telecommunication Services": ("telecom", "defensive"),
    "Movies & Entertainment": ("media",),
    "Broadcasting": ("media",),
    "Cable & Satellite": ("media",),
    "Publishing": ("media",),
    "Apparel, Accessories & Luxury Goods": ("textiles", "consumer"),
    "Footwear": ("textiles", "consumer"),
    "Restaurants": ("consumer",),
    "Apparel Retail": ("consumer",),
    "Other Specialty Retail": ("consumer",),
    "Homefurnishing Retail": ("consumer",),
    "Data Center REITs": ("realty", "ai_compute"),
}

# US companies with large sales or supply chains in China (company filings; checked 2026-10-23).
US_CHINA = frozenset(
    [
        "AAPL",
        "TSLA",
        "NVDA",
        "QCOM",
        "AMD",
        "MU",
        "AVGO",
        "KLAC",
        "LRCX",
        "AMAT",
        "TXN",
        "INTC",
        "NXPI",
        "MCHP",
        "ON",
        "SWKS",
        "QRVO",
        "NKE",
        "SBUX",
        "LVS",
        "WYNN",
        "YUM",
        "EL",
        "CAT",
        "BA",
        "GM",
        "DE",
        "TER",
        "ADI",
        "MPWR",
    ]
)
US_INDIA = frozenset(["ACN", "CTSH", "EPAM"])
US_CRYPTO = frozenset(["COIN", "MSTR", "HOOD"])

# India: the industry is coarse, so hand-checked company lists sharpen it (NSE symbols).
IN_TAGS: dict[str, tuple[str, ...]] = {
    "ONGC": ("oil_producer",),
    "OIL": ("oil_producer",),
    "BPCL": ("omc", "refiner"),
    "HINDPETRO": ("omc", "refiner"),
    "IOC": ("omc", "refiner"),
    "RELIANCE": ("refiner", "telecom", "consumer"),
    "MRPL": ("refiner",),
    "CHENNPETRO": ("refiner",),
    "GAIL": ("gas",),
    "PETRONET": ("gas",),
    "IGL": ("gas",),
    "MGL": ("gas",),
    "GUJGASLTD": ("gas",),
    "GSPL": ("gas",),
    "ATGL": ("gas",),
    "COALINDIA": ("coal",),
    "INDIGO": ("airline", "oil_user", "travel"),
    "SPICEJET": ("airline", "oil_user", "travel"),
    "ASIANPAINT": ("paints", "oil_user"),
    "BERGEPAINT": ("paints", "oil_user"),
    "KANSAINER": ("paints", "oil_user"),
    "INDIGOPNTS": ("paints", "oil_user"),
    "AKZOINDIA": ("paints", "oil_user"),
    "MRF": ("tyres", "oil_user"),
    "APOLLOTYRE": ("tyres", "oil_user"),
    "CEATLTD": ("tyres", "oil_user"),
    "JKTYRE": ("tyres", "oil_user"),
    "BALKRISIND": ("tyres", "oil_user", "exporter"),
    "TVSSRICHAK": ("tyres", "oil_user"),
    "TATASTEEL": ("steel",),
    "JSWSTEEL": ("steel",),
    "SAIL": ("steel",),
    "JINDALSTEL": ("steel",),
    "JSL": ("steel",),
    "HINDALCO": ("aluminium",),
    "NATIONALUM": ("aluminium",),
    "VEDL": ("aluminium",),
    "HINDZINC": ("metals",),
    "HINDCOPPER": ("copper",),
    "TITAN": ("gold", "consumer"),
    "KALYANKJIL": ("gold", "consumer"),
    "SENCO": ("gold", "consumer"),
    "RAJESHEXPO": ("gold",),
    "MUTHOOTFIN": ("gold", "nbfc"),
    "MANAPPURAM": ("gold", "nbfc"),
    "CHAMBLFERT": ("fertiliser", "rural"),
    "COROMANDEL": ("fertiliser", "rural"),
    "RCF": ("fertiliser", "rural"),
    "FACT": ("fertiliser", "rural"),
    "GSFC": ("fertiliser", "rural"),
    "GNFC": ("fertiliser", "rural"),
    "DEEPAKFERT": ("fertiliser", "rural"),
    "PARADEEP": ("fertiliser", "rural"),
    "NFL": ("fertiliser", "rural"),
    "UPL": ("agri", "rural", "exporter"),
    "PIIND": ("agri", "rural", "exporter"),
    "BAYERCROP": ("agri", "rural"),
    "DHANUKA": ("agri", "rural"),
    "BALRAMCHIN": ("agri", "rural"),
    "TRIVENI": ("agri", "rural"),
    "EIDPARRY": ("agri", "rural"),
    "M&M": ("autos", "rural"),
    "ESCORTS": ("autos", "rural", "agri"),
    "HEROMOTOCO": ("autos", "rural"),
    "SCI": ("logistics",),
    "GESHIP": ("logistics",),
    "ADANIPORTS": ("logistics",),
    "JSWINFRA": ("logistics",),
    "CONCOR": ("logistics",),
    "DELHIVERY": ("logistics",),
    "BLUEDART": ("logistics",),
    "TCIEXP": ("logistics",),
    "INDHOTEL": ("travel",),
    "EIHOTEL": ("travel",),
    "LEMONTREE": ("travel",),
    "CHALET": ("travel",),
    "IRCTC": ("travel",),
    "THOMASCOOK": ("travel",),
    "TATAMOTORS": ("autos", "exporter"),
    "TMPV": ("autos", "exporter"),
    "MOTHERSON": ("autos", "exporter"),
    "SONACOMS": ("autos", "exporter"),
    "BHARATFORG": ("autos", "defence", "exporter"),
    "SUZLON": ("renewables", "capex"),
    "INOXWIND": ("renewables", "capex"),
    "ADANIGREEN": ("renewables",),
    "NTPCGREEN": ("renewables",),
    "WAAREEENER": ("renewables",),
    "PREMIERENE": ("renewables",),
    "DIXON": ("hardware",),
    "KAYNES": ("hardware",),
    "BSE": ("capital_markets",),
    "MCX": ("capital_markets",),
    "CDSL": ("capital_markets",),
    "ANGELONE": ("capital_markets",),
    "CAMS": ("capital_markets",),
    "HDFCAMC": ("capital_markets",),
    "NUVAMA": ("capital_markets",),
    "MOTILALOFS": ("capital_markets",),
    "ETERNAL": ("internet", "consumer"),
    "SWIGGY": ("internet", "consumer"),
    "NYKAA": ("internet", "consumer"),
    "PAYTM": ("internet", "nbfc"),
    "POLICYBZR": ("internet", "insurance"),
    "NAUKRI": ("internet",),
    "INFOEDGE": ("internet",),
}

NSE_INDUSTRY_TAGS: dict[str, tuple[str, ...]] = {
    "Information Technology": ("it_services", "exporter", "software"),
    "Automobile and Auto Components": ("autos",),
    "Construction Materials": ("cement", "capex"),
    "Realty": ("realty", "rate_sensitive"),
    "Power": ("utility",),
    "Capital Goods": ("capex",),
    "Construction": ("capex",),
    "Chemicals": ("chemicals",),
    "Fast Moving Consumer Goods": ("fmcg", "defensive", "rural"),
    "Consumer Durables": ("consumer",),
    "Consumer Services": ("consumer",),
    "Telecommunication": ("telecom",),
    "Textiles": ("textiles", "exporter"),
    "Media Entertainment & Publication": ("media",),
    "Metals & Mining": ("metals",),
    "Healthcare": ("defensive",),
}

# A short line per index membership key: shown on the ready-made watchlists.
IN_LIST_TAGS: dict[str, tuple[str, ...]] = {
    "bank": ("bank",),
    "privatebank": ("bank",),
    "psubank": ("bank", "psu_bank"),
    "pharma": ("pharma", "exporter"),
    "defence": ("defence",),
    "tourism": ("travel",),
    "chemicals": ("chemicals",),
    "realty": ("realty", "rate_sensitive"),
}

IN_SIZE = (
    ("nifty100", "large"),
    ("midcap150", "mid"),
    ("smallcap250", "small"),
    ("microcap250", "micro"),
)
US_SIZE = (("sp500", "large"), ("sp400", "mid"), ("sp600", "small"))


def size_of(lists: set[str], market: str) -> str:
    for key, size in IN_SIZE if market == "IN" else US_SIZE:
        if key in lists:
            return size
    if market == "US" and "ndx" in lists:
        return "large"  # Nasdaq-100 members outside the S&P 500 are all large companies
    return ""


def india_profile(symbol: str, name: str, industry: str, lists: set[str]) -> dict[str, str]:
    tags: set[str] = set(NSE_INDUSTRY_TAGS.get(industry, ()))
    for key, extra in IN_LIST_TAGS.items():
        if key in lists:
            tags.update(extra)
    tags.update(IN_TAGS.get(symbol, ()))
    low = name.lower()
    if industry == "Financial Services" and not tags & {"bank", "capital_markets"}:
        tags.add("insurance" if "insurance" in low or " life" in low else "nbfc")
    if industry == "Healthcare" and "pharma" not in tags:
        hospital = any(w in low for w in ("hospital", "health", "diagnostic", "lab", "medi"))
        tags.add("healthcare_services" if hospital else "pharma")
        if not hospital:
            tags.add("exporter")
    if tags & {"bank", "nbfc", "realty", "autos"}:
        tags.add("rate_sensitive")
    if industry == "Oil Gas & Consumable Fuels" and not tags & {
        "oil_producer",
        "omc",
        "refiner",
        "gas",
        "coal",
    }:
        tags.add("gas")
    return {
        "sector": NSE_SECTOR.get(industry, ""),
        "industry": industry,
        "size": size_of(lists, "IN"),
        "tags": ";".join(sorted(tags)),
    }


def us_profile(symbol: str, sector: str, industry: str, lists: set[str]) -> dict[str, str]:
    tags: set[str] = set(US_SUB_TAGS.get(industry, ()))
    if sector == "Real Estate":
        tags.update(("realty", "rate_sensitive"))
    if sector == "Utilities":
        tags.update(("utility", "defensive"))
    if symbol in US_CHINA:
        tags.add("china_exposed")
    if symbol in US_INDIA:
        tags.add("india_exposed")
    if symbol in US_CRYPTO:
        tags.add("crypto")
    if not tags:
        low = industry.lower()
        if "semiconductor" in low:
            tags.update(("semiconductors", "ai_compute"))
        elif "software" in low:
            tags.add("software")
        elif "aerospace" in low or "defense" in low:
            tags.add("defence")
        elif "internet" in low:
            tags.add("internet")
    return {
        "sector": sector,
        "industry": industry,
        "size": size_of(lists, "US"),
        "tags": ";".join(sorted(tags)),
    }
