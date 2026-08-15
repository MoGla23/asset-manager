"""Abruf aktueller Aktienkurse über yfinance.

Diese Funktion ist bewusst von Streamlit getrennt, damit sie einfach
zu testen ist und Fehler (z.B. falscher Ticker, kein Internet) nicht
die ganze App zum Absturz bringen.
"""

import pandas as pd
import yfinance as yf


def get_current_price(ticker):
    """Gibt den letzten verfügbaren Schlusskurs zurück, oder None bei Fehler."""
    try:
        history = yf.Ticker(ticker).history(period="1d")
        if history.empty:
            return None
        return float(history["Close"].iloc[-1])
    except Exception:
        return None


def get_ticker_currency(ticker):
    """Gibt die Handelswährung eines Tickers zurück (z.B. 'USD'), oder None bei Fehler."""
    try:
        currency = yf.Ticker(ticker).fast_info.get("currency")
        return currency
    except Exception:
        return None


def get_exchange_rate_to_eur(currency):
    """Gibt den Wechselkurs von 1 Einheit `currency` in Euro zurück, oder None bei Fehler.

    Nutzt die Devisenkurs-Ticker von Yahoo Finance, z.B. 'USDEUR=X'.
    """
    if currency is None:
        return None
    if currency == "EUR":
        return 1.0
    try:
        pair = f"{currency}EUR=X"
        history = yf.Ticker(pair).history(period="1d")
        if history.empty:
            return None
        return float(history["Close"].iloc[-1])
    except Exception:
        return None


def _normalisiere_datumsindex(reihe):
    """Entfernt die Zeitzone aus dem Datumsindex und schneidet auf den Kalendertag zu.

    Nötig, weil yfinance je nach Börse unterschiedliche Zeitzonen liefert -
    ohne diesen Schritt lassen sich Kurse verschiedener Ticker/Devisenpaare
    nicht anhand des Datums vergleichen.
    """
    index = reihe.index
    if index.tz is not None:
        index = index.tz_localize(None)
    reihe.index = index.normalize()
    return reihe


def get_price_history(ticker, period="1y"):
    """Gibt die historischen Schlusskurse eines Tickers als pandas Series zurück.

    Index ist das Datum, Werte sind die Schlusskurse in der Handelswährung
    des Tickers. Gibt None zurück, wenn keine Historie abrufbar ist.
    """
    try:
        history = yf.Ticker(ticker).history(period=period)
        if history.empty:
            return None
        return _normalisiere_datumsindex(history["Close"])
    except Exception:
        return None


def get_exchange_rate_history(currency, period="1y"):
    """Gibt den historischen Wechselkurs von 1 Einheit `currency` in Euro zurück.

    Wie get_exchange_rate_to_eur, aber als Zeitreihe (pandas Series).
    Gibt None zurück, wenn keine Historie abrufbar ist.
    """
    if currency is None:
        return None
    try:
        pair = f"{currency}EUR=X"
        history = yf.Ticker(pair).history(period=period)
        if history.empty:
            return None
        return _normalisiere_datumsindex(history["Close"])
    except Exception:
        return None


def wert_am_oder_vor_datum(reihe, datum):
    """Gibt den letzten bekannten Wert einer Zeitreihe an oder vor `datum` zurück.

    Nützlich, um z.B. den Wechselkurs an einem bestimmten Transaktionsdatum zu
    ermitteln, auch wenn genau an diesem Tag kein Kurs vorliegt (Wochenende,
    Feiertag). Gibt None zurück, wenn keine passenden Daten vorhanden sind.
    """
    if reihe is None or reihe.empty or datum is None:
        return None
    ziel = pd.Timestamp(datum).normalize()
    passende = reihe[reihe.index <= ziel]
    if passende.empty:
        return None
    return float(passende.iloc[-1])
