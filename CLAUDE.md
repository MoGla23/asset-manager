# Asset Manager

## Projektziel
Ein persönlicher Asset Manager / Portfolio-Tracker als Sommerprojekt zum Programmieren-Lernen.
Ziel: Depot-Positionen (Ticker, Stückzahl, Kaufkurs) erfassen und anzeigen.

## Technik
- **Sprache:** Python (3.9.6, System-Python)
- **Datenspeicher:** SQLite (lokale Datei `data/portfolio.db`)
- **Oberfläche:** Streamlit

## Projektstruktur
```
asset-manager/
├── CLAUDE.md          Diese Datei
├── app.py             Streamlit-App (Hauptseite)
├── database.py        Datenbank-Funktionen (SQLite)
├── prices.py          Kurs- und Wechselkurs-Abruf über yfinance
├── news.py            Wirtschaftsnachrichten über RSS-Feeds (feedparser)
├── ticker_search.py   Ticker-Live-Suche über Yahoo Finance + feste Rückfallliste
├── data/              Enthält die SQLite-Datenbankdatei
├── requirements.txt   Python-Pakete
└── venv/              Virtuelle Umgebung (nicht in Git)
```

## Aktueller Stand
- [x] Python-Installation geprüft
- [x] Projektstruktur & virtuelle Umgebung eingerichtet
- [x] Minimale Streamlit-App: Tabelle der Positionen + Formular zum Hinzufügen
- [x] Aktuelle Kurse per yfinance, inkl. Aktueller Wert & Gewinn/Verlust (€ und %)
- [x] Währungsumrechnung: Handelswährung je Ticker + Umrechnung in Euro über aktuellen Wechselkurs
- [x] Positionen bearbeiten (Stückzahl/Kaufkurs) und löschen (mit Sicherheitsabfrage)
- [x] Tortendiagramm zur Depot-Aufteilung (Plotly, nach aktuellem Wert in Euro)
- [x] Finanznachrichten (RSS: Tagesschau, Handelsblatt, Yahoo Finance)
- [x] Zwei Ansichten über st.tabs: "Mein Depot" und "News"
- [x] Ticker-Autovervollständigung beim Hinzufügen (streamlit-searchbox + Yahoo-Finance-Suche)
- [x] Breites Seiten-Layout (layout="wide") + kompakte Spaltenbreiten für die Positions-Tabelle
- [x] Spalten der Positions-Tabelle einzeln ein-/ausblendbar (Checkboxen in einem Expander)
- [ ] Weitere Features (z.B. Kennzahlen, historische Wechselkurse zum Kaufzeitpunkt)

## Starten der App
```
source venv/bin/activate
streamlit run app.py
```
