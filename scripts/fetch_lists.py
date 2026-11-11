"""Rebuild the stock lists behind Agora's ready-made watchlists (Phase 18, D-93).

Run by Claude in a cloud session (never by the user, never by the app):

    uv run python scripts/fetch_lists.py

It downloads the official constituent lists and writes two committed seed files:

- ``backend/seed_data/instruments_in.csv``: every NSE stock in the Nifty 500, the Nifty Microcap
  250 and the sector/theme/strategy indices below, with NSE's industry and the indices it
  belongs to (from ``nsearchives.nseindia.com/content/indices/*.csv``);
- ``backend/seed_data/instruments_us.csv``: every S&P 500, S&P MidCap 400 and S&P SmallCap 600
  stock with its GICS sector and sub-industry (Wikipedia's lists, which follow S&P's notices),
  plus the Nasdaq-100 (Nasdaq's own list) and the Dow 30. Nasdaq-100 members outside the S&P
  1500 get their sector from Yahoo's search.

Every other stock listed on the exchanges is added too, with the list key ``listed`` (the user's
request 2026-10-24: "there are so many stocks in the US and India"): all NSE main-board equities
(NSE's ``EQUITY_L.csv``) and every common stock on the Nasdaq, NYSE and NYSE American (Nasdaq's
screener, which also gives a sector and the market value). Warrants, units, rights and preference
shares are left out. Stocks in an index carry ``listed`` as well.

The files carry the date they were made (``as_of``); refresh them every few months.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "backend" / "seed_data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
NSE = "https://nsearchives.nseindia.com/content/indices/"
NSE_ALL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
US_ALL = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true"
# Nasdaq's sector names → the GICS names the rest of Agora uses
NASDAQ_SECTOR = {
    "Finance": "Financials",
    "Technology": "Information Technology",
    "Telecommunications": "Communication Services",
    "Basic Materials": "Materials",
    "Miscellaneous": "",
}
NOT_COMMON = (" warrant", " unit", " right", "preferred", "preference", " notes due", "% notes")

# membership key → NSE file name (without .csv)
NSE_LISTS: dict[str, str] = {
    "nifty50": "ind_nifty50list",
    "niftynext50": "ind_niftynext50list",
    "nifty100": "ind_nifty100list",
    "nifty200": "ind_nifty200list",
    "nifty500": "ind_nifty500list",
    "midcap150": "ind_niftymidcap150list",
    "smallcap250": "ind_niftysmallcap250list",
    "microcap250": "ind_niftymicrocap250_list",
    "bank": "ind_niftybanklist",
    "privatebank": "ind_nifty_privatebanklist",
    "psubank": "ind_niftypsubanklist",
    "finance": "ind_niftyfinancelist",
    "it": "ind_niftyitlist",
    "auto": "ind_niftyautolist",
    "pharma": "ind_niftypharmalist",
    "healthcare": "ind_niftyhealthcarelist",
    "fmcg": "ind_niftyfmcglist",
    "metal": "ind_niftymetallist",
    "realty": "ind_niftyrealtylist",
    "energy": "ind_niftyenergylist",
    "oilgas": "ind_niftyoilgaslist",
    "media": "ind_niftymedialist",
    "consumerdurables": "ind_niftyconsumerdurableslist",
    "chemicals": "ind_niftyChemicals_list",
    "defence": "ind_niftyindiadefence_list",
    "infra": "ind_niftyinfralist",
    "commodities": "ind_niftycommoditieslist",
    "consumption": "ind_niftyconsumptionlist",
    "mnc": "ind_niftymnclist",
    "pse": "ind_niftypselist",
    "cpse": "ind_niftycpselist",
    "digital": "ind_niftyindiadigital_list",
    "manufacturing": "ind_niftyindiamanufacturing_list",
    "tourism": "ind_niftyindiatourism_list",
    "momentum30": "ind_nifty200Momentum30_list",
    "lowvol30": "ind_Nifty100LowVolatility30list",
    "quality30": "ind_nifty200Quality30_list",
    "alpha50": "ind_nifty_Alpha_Index",
    "alpha30": "ind_nifty200alpha30_list",
    "divopp50": "ind_niftydivopp50list",
}

WIKI = "https://en.wikipedia.org/wiki/"
US_LISTS = {
    "sp500": "List_of_S%26P_500_companies",
    "sp400": "List_of_S%26P_400_companies",
    "sp600": "List_of_S%26P_600_companies",
}
NDX_API = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
# The Dow 30 (S&P Dow Jones Indices; NVDA and SHW joined on 8 Nov 2024). Checked 2026-10-23.
DOW30 = [
    "AAPL",
    "AMGN",
    "AMZN",
    "AXP",
    "BA",
    "CAT",
    "CRM",
    "CSCO",
    "CVX",
    "DIS",
    "GS",
    "HD",
    "HON",
    "IBM",
    "JNJ",
    "JPM",
    "KO",
    "MCD",
    "MMM",
    "MRK",
    "MSFT",
    "NKE",
    "NVDA",
    "PG",
    "SHW",
    "TRV",
    "UNH",
    "V",
    "VZ",
    "WMT",
]
YAHOO_SECTOR = {
    "Technology": "Information Technology",
    "Healthcare": "Health Care",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Financial Services": "Financials",
    "Basic Materials": "Materials",
}


def get(url: str, *, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                data: bytes = r.read()
                return data
        except Exception as exc:  # network: retry with back-off
            if attempt == 3:
                raise
            print(f"  retry {url}: {exc}", file=sys.stderr)
            time.sleep(2**attempt * 2)
    raise RuntimeError("unreachable")


def india() -> list[dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for key, name in NSE_LISTS.items():
        text = get(f"{NSE}{name}.csv").decode("utf-8-sig")
        n = 0
        for r in csv.DictReader(io.StringIO(text)):
            sym = (r.get("Symbol") or "").strip()
            if not sym or (r.get("Series") or "EQ").strip() not in ("EQ", "BE", "BZ"):
                continue
            row = rows.setdefault(
                sym,
                {
                    "symbol": sym,
                    "name": (r.get("Company Name") or "").strip(),
                    "industry": (r.get("Industry") or "").strip(),
                    "isin": (r.get("ISIN Code") or "").strip(),
                    "lists": "",
                },
            )
            row["lists"] = ";".join(sorted({*filter(None, row["lists"].split(";")), key}))
            n += 1
        print(f"IN {key}: {n}")
        time.sleep(0.4)
    return sorted(rows.values(), key=lambda r: r["symbol"])


def _wiki_table(page: str) -> pd.DataFrame:
    html = get(WIKI + page).decode("utf-8")
    t = pd.read_html(io.StringIO(html), flavor="lxml")[0]
    return t


def _yahoo_profile(sym: str) -> tuple[str, str, str]:
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={sym}&quotesCount=1&newsCount=0"
    q = json.loads(get(url))["quotes"]
    hit = next((x for x in q if x.get("symbol") == sym), q[0] if q else {})
    sector = str(hit.get("sector") or "")
    return (
        str(hit.get("longname") or hit.get("shortname") or sym),
        YAHOO_SECTOR.get(sector, sector),
        str(hit.get("industry") or ""),
    )


def us() -> list[dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for key, page in US_LISTS.items():
        t = _wiki_table(page)
        for _, r in t.iterrows():
            sym = str(r["Symbol"]).strip().replace(".", "-")
            row = rows.setdefault(
                sym,
                {
                    "symbol": sym,
                    "name": str(r["Security"]).strip(),
                    "sector": str(r["GICS Sector"]).strip(),
                    "industry": str(r["GICS Sub-Industry"]).strip(),
                    "lists": "",
                },
            )
            row["lists"] = ";".join(sorted({*filter(None, row["lists"].split(";")), key}))
        print(f"US {key}: {len(t)}")
        time.sleep(1.0)
    ndx = json.loads(get(NDX_API, accept="application/json"))["data"]["data"]["rows"]
    for r in ndx:
        sym = str(r["symbol"]).strip().replace(".", "-")
        if sym not in rows:
            name, sector, industry = _yahoo_profile(sym)
            rows[sym] = {"symbol": sym, "name": name, "sector": sector, "industry": industry}
            rows[sym]["lists"] = ""
            time.sleep(0.5)
        row = rows[sym]
        row["lists"] = ";".join(sorted({*filter(None, row["lists"].split(";")), "ndx"}))
    print(f"US ndx: {len(ndx)}")
    for sym in DOW30:
        row = rows[sym]
        row["lists"] = ";".join(sorted({*filter(None, row["lists"].split(";")), "dow"}))
    return sorted(rows.values(), key=lambda r: r["symbol"])


def _add_list(row: dict[str, str], key: str) -> None:
    row["lists"] = ";".join(sorted({*filter(None, row.get("lists", "").split(";")), key}))


def india_listed(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Add every NSE main-board equity (series EQ, BE, BZ) to the index stocks."""
    by_sym = {r["symbol"]: r for r in rows}
    text = get(NSE_ALL).decode("utf-8-sig")
    n = 0
    for raw in csv.DictReader(io.StringIO(text)):
        r = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        sym, series = r.get("SYMBOL", ""), r.get("SERIES", "")
        if not sym or series not in ("EQ", "BE", "BZ"):
            continue
        row = by_sym.setdefault(
            sym,
            {
                "symbol": sym,
                "name": r.get("NAME OF COMPANY", sym),
                "industry": "",
                "isin": r.get("ISIN NUMBER", ""),
                "lists": "",
            },
        )
        _add_list(row, "listed")
        n += 1
    print(f"IN listed: {n} (total {len(by_sym)})")
    return sorted(by_sym.values(), key=lambda r: r["symbol"])


def _common(sym: str, name: str) -> bool:
    low = f" {name.lower()}"
    return bool(sym) and "^" not in sym and not any(w in low for w in NOT_COMMON)


def us_listed(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Add every common stock on the US exchanges, with Nasdaq's sector and industry."""
    by_sym = {r["symbol"]: r for r in rows}
    data = json.loads(get(US_ALL, accept="application/json"))["data"]["rows"]
    n = 0
    for r in data:
        sym = str(r.get("symbol") or "").strip().replace("/", "-").replace(".", "-")
        name = str(r.get("name") or "").strip()
        if not _common(sym, name):
            continue
        sector = str(r.get("sector") or "").strip()
        row = by_sym.setdefault(
            sym,
            {
                "symbol": sym,
                "name": name.replace(" Common Stock", "").replace(" Class A Ordinary Shares", ""),
                "sector": NASDAQ_SECTOR.get(sector, sector),
                "industry": str(r.get("industry") or "").strip(),
                "lists": "",
            },
        )
        _add_list(row, "listed")
        n += 1
    print(f"US listed: {n} (total {len(by_sym)})")
    return sorted(by_sym.values(), key=lambda r: r["symbol"])


def write(path: Path, rows: list[dict[str, str]], cols: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        f.write(f"# as_of={date.today().isoformat()}\n")
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    print(f"wrote {path} ({len(rows)} rows)")


def main() -> None:
    write(
        OUT / "instruments_in.csv",
        india_listed(india()),
        ["symbol", "name", "industry", "isin", "lists"],
    )
    write(
        OUT / "instruments_us.csv",
        us_listed(us()),
        ["symbol", "name", "sector", "industry", "lists"],
    )


if __name__ == "__main__":
    main()
