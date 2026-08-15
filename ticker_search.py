"""Ticker-Suche für die Autovervollständigung beim Hinzufügen einer Position.

Nutzt die Live-Suche von Yahoo Finance (über yfinance). Ist diese gerade
nicht erreichbar oder liefert keine Treffer, wird auf eine kleine feste
Liste gängiger deutscher und US-Werte plus bekannter ETFs zurückgegriffen.
"""

import yfinance as yf

RELEVANTE_TYPEN = {"EQUITY", "ETF", "MUTUALFUND"}

FALLBACK_TICKERS = [
    {"symbol": "AAPL", "name": "Apple Inc."},
    {"symbol": "MSFT", "name": "Microsoft Corporation"},
    {"symbol": "GOOGL", "name": "Alphabet Inc. (Google)"},
    {"symbol": "AMZN", "name": "Amazon.com Inc."},
    {"symbol": "TSLA", "name": "Tesla Inc."},
    {"symbol": "META", "name": "Meta Platforms Inc."},
    {"symbol": "NVDA", "name": "NVIDIA Corporation"},
    {"symbol": "SAP.DE", "name": "SAP SE"},
    {"symbol": "SIE.DE", "name": "Siemens AG"},
    {"symbol": "VOW3.DE", "name": "Volkswagen AG (Vorzugsaktie)"},
    {"symbol": "ALV.DE", "name": "Allianz SE"},
    {"symbol": "BAS.DE", "name": "BASF SE"},
    {"symbol": "DBK.DE", "name": "Deutsche Bank AG"},
    {"symbol": "BMW.DE", "name": "Bayerische Motoren Werke AG"},
    {"symbol": "ADS.DE", "name": "adidas AG"},
    {"symbol": "BAYN.DE", "name": "Bayer AG"},
    {"symbol": "DTE.DE", "name": "Deutsche Telekom AG"},
    {"symbol": "MBG.DE", "name": "Mercedes-Benz Group AG"},
    {"symbol": "IFX.DE", "name": "Infineon Technologies AG"},
    {"symbol": "EUNL.DE", "name": "iShares Core MSCI World UCITS ETF"},
    {"symbol": "VWCE.DE", "name": "Vanguard FTSE All-World UCITS ETF"},
    {"symbol": "VUSA.DE", "name": "Vanguard S&P 500 UCITS ETF"},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust"},
    {"symbol": "QQQ", "name": "Invesco QQQ Trust (Nasdaq-100)"},
]


def _fallback_suche(query, max_results):
    query_klein = query.lower()
    treffer = [
        (f"{eintrag['name']} ({eintrag['symbol']})", eintrag["symbol"])
        for eintrag in FALLBACK_TICKERS
        if query_klein in eintrag["name"].lower() or query_klein in eintrag["symbol"].lower()
    ]
    return treffer[:max_results]


def search_tickers(query, max_results=8):
    """Sucht passende Ticker über Yahoo Finance.

    Gibt eine Liste von (Anzeigetext, Ticker) zurück, z.B.
    [("SAP SE (SAP.DE)", "SAP.DE"), ...]. Bei jedem Fehler oder wenn die
    Live-Suche keine passenden Aktien/ETFs/Fonds findet, wird stattdessen
    die feste Liste durchsucht.
    """
    query = query.strip()
    if not query:
        return []

    try:
        treffer_roh = yf.Search(query, max_results=max_results).quotes
        ergebnisse = []
        for eintrag in treffer_roh:
            if eintrag.get("quoteType") not in RELEVANTE_TYPEN:
                continue
            symbol = eintrag.get("symbol")
            name = eintrag.get("shortname") or eintrag.get("longname") or symbol
            if symbol:
                ergebnisse.append((f"{name} ({symbol})", symbol))
        if ergebnisse:
            return ergebnisse
    except Exception:
        pass

    return _fallback_suche(query, max_results)
