"""Abruf von Finanz- und Wirtschaftsnachrichten über kostenlose RSS-Feeds."""

import socket
from datetime import datetime, timezone

import feedparser

# Verhindert, dass die App ewig hängt, wenn ein Feed nicht antwortet.
socket.setdefaulttimeout(10)

NEWS_FEEDS = {
    "Tagesschau Wirtschaft": "https://www.tagesschau.de/wirtschaft/index~rss2.xml",
    "Handelsblatt": "https://www.handelsblatt.com/contentexport/feed/schlagzeilen",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
}


def get_headlines(max_items=8):
    """Holt die neuesten Schlagzeilen aus allen Feeds, sortiert nach Datum.

    Gibt ein Tupel (schlagzeilen, fehlgeschlagene_quellen) zurück. Ist ein
    einzelner Feed gerade nicht erreichbar, wird er übersprungen statt die
    ganze Funktion abstürzen zu lassen.
    """
    schlagzeilen = []
    fehlgeschlagen = []

    for quelle, url in NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            if not feed.entries:
                fehlgeschlagen.append(quelle)
                continue
            for entry in feed.entries:
                zeitstempel = entry.get("published_parsed") or entry.get("updated_parsed")
                if zeitstempel:
                    datum = datetime(*zeitstempel[:6], tzinfo=timezone.utc).astimezone()
                else:
                    datum = None
                schlagzeilen.append(
                    {
                        "titel": entry.get("title", "(ohne Titel)"),
                        "quelle": quelle,
                        "link": entry.get("link", ""),
                        "datum": datum,
                    }
                )
        except Exception:
            fehlgeschlagen.append(quelle)

    schlagzeilen.sort(key=lambda s: s["datum"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return schlagzeilen[:max_items], fehlgeschlagen
