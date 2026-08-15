"""Asset Manager - minimale Streamlit-Oberfläche.

Zwei Ansichten: "Mein Depot" (Tabelle, Kennzahlen, Diagramm, Transaktionen)
und "News" (Finanz- und Wirtschaftsnachrichten).

Die Transaktionen (Käufe/Verkäufe) sind die einzige Wahrheit über das
Depot. Aktuelle Positionen und der Wertverlauf werden daraus abgeleitet
(siehe berechne_positionen / berechne_depotverlauf unten).
"""

from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from database import (
    add_transaction,
    delete_transaction,
    get_transactions,
    init_db,
    migrate_legacy_positions_to_transactions,
)
from news import get_headlines
from prices import (
    get_current_price,
    get_exchange_rate_history,
    get_exchange_rate_to_eur,
    get_fundamentals,
    get_price_history,
    get_ticker_currency,
    wert_am_oder_vor_datum,
)
from streamlit_searchbox import st_searchbox
from ticker_search import search_tickers

st.set_page_config(page_title="Mein Asset Manager", layout="wide")

init_db()
_neu_migriert = migrate_legacy_positions_to_transactions()

# Feste, gut unterscheidbare Farbreihenfolge fürs Tortendiagramm.
KATEGORIE_FARBEN = [
    "#2a78d6",  # blau
    "#eb6834",  # orange
    "#1baf7a",  # türkis
    "#eda100",  # gelb
    "#e87ba4",  # magenta
    "#008300",  # grün
    "#4a3aa7",  # violett
    "#e34948",  # rot
]

# Auswahl an Vergleichsindizes fürs Benchmark-Diagramm.
BENCHMARK_OPTIONEN = {
    "S&P 500": "^GSPC",
    "MSCI World (URTH)": "URTH",
    "DAX": "^GDAXI",
}

# Referenzindex für die Beta-Berechnung im Analyse-Tab.
BETA_REFERENZ_TICKER = "^GSPC"
BETA_REFERENZ_LABEL = "S&P 500"


@st.dialog("Transaktion wirklich löschen?")
def confirm_delete_transaction(transaction_id, ticker, typ):
    st.write(
        f"Soll die Transaktion **{typ} {ticker}** (ID {transaction_id}) "
        "dauerhaft gelöscht werden?"
    )
    spalte_ja, spalte_nein = st.columns(2)
    if spalte_ja.button("Ja, löschen", type="primary", use_container_width=True):
        delete_transaction(transaction_id)
        st.rerun()
    if spalte_nein.button("Abbrechen", use_container_width=True):
        st.rerun()


@st.cache_data(ttl=60, show_spinner="Aktuelle Kurse werden abgerufen...")
def fetch_prices(tickers):
    """Ruft für mehrere Ticker die aktuellen Kurse ab (in der jeweiligen Handelswährung).

    Das Ergebnis wird 60 Sekunden zwischengespeichert (Cache), damit
    nicht bei jeder Interaktion in der App erneut abgefragt wird.
    """
    return {ticker: get_current_price(ticker) for ticker in tickers}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_currencies(tickers):
    """Ruft für mehrere Ticker die Handelswährung ab.

    Die Handelswährung ändert sich praktisch nie, daher wird hier
    eine Stunde lang gecacht statt nur eine Minute wie bei den Kursen.
    """
    return {ticker: get_ticker_currency(ticker) for ticker in tickers}


@st.cache_data(ttl=3600, show_spinner="Fundamentaldaten werden abgerufen...")
def fetch_fundamentals(tickers):
    """Ruft für mehrere Ticker Fundamentaldaten ab (KGV, Dividendenrendite, Marktkap.).

    Ändert sich selten (Quartalszahlen), daher eine Stunde lang gecacht.
    """
    return {ticker: get_fundamentals(ticker) for ticker in tickers}


@st.cache_data(ttl=60, show_spinner="Wechselkurse werden abgerufen...")
def fetch_exchange_rates(currencies):
    """Ruft für mehrere Währungen den Wechselkurs zu Euro ab."""
    return {currency: get_exchange_rate_to_eur(currency) for currency in currencies}


@st.cache_data(ttl=900, show_spinner=False)
def fetch_news():
    """Holt die Schlagzeilen und cacht sie 15 Minuten lang."""
    return get_headlines(max_items=8)


@st.cache_data(ttl=3600, show_spinner="Historische Kurse werden abgerufen...")
def fetch_price_histories(tickers, period):
    """Ruft für mehrere Ticker die historischen Kurse ab."""
    return {ticker: get_price_history(ticker, period) for ticker in tickers}


@st.cache_data(ttl=3600, show_spinner="Historische Wechselkurse werden abgerufen...")
def fetch_exchange_rate_histories(currencies, period):
    """Ruft für mehrere Währungen den historischen Wechselkurs zu Euro ab."""
    return {currency: get_exchange_rate_history(currency, period) for currency in currencies}


@st.cache_data(ttl=3600, show_spinner="Historische Wechselkurse werden abgerufen...")
def fetch_exchange_rate_histories_lang(currencies):
    """Wie fetch_exchange_rate_histories, aber mit maximal langer Historie.

    Wird für die Umrechnung einzelner Transaktionen zu ihrem jeweiligen
    (ggf. weit zurückliegenden) Datum gebraucht statt für einen kurzen,
    fest gewählten Anzeige-Zeitraum.
    """
    return {currency: get_exchange_rate_history(currency, "max") for currency in currencies}


def _transaktions_sortierschluessel(transaktion):
    """Sortiert Transaktionen chronologisch; Transaktionen ohne Datum zuerst.

    Annahme: eine Transaktion ohne Datum (z.B. migrierte Alt-Position) liegt
    zeitlich vor allen datierten Transaktionen.
    """
    transaktion_id, datum, *_rest = transaktion
    if datum is None:
        return (0, "", transaktion_id)
    return (1, datum, transaktion_id)


def berechne_positionen(transaktionen, currencies, wechselkurshistorien_lang, wechselkurse_aktuell):
    """Leitet aktuelle Positionen aus den Transaktionen ab (Durchschnittskostenmethode).

    Für jeden Ticker wird die Stückzahl fortlaufend aus Käufen (+) und
    Verkäufen (-) verfolgt. Der Einstand (Kaufkurs) ist der gleitende
    Durchschnittskurs: ein Kauf mittelt den Durchschnitt neu, ein Verkauf
    reduziert Stückzahl und Gesamtkosten proportional, ohne den
    Durchschnittskurs der verbleibenden Stücke zu verändern.

    Der Kaufkurs (€) wird parallel dazu in Euro geführt, wobei jeder Kauf
    mit dem historischen Wechselkurs an seinem Transaktionsdatum
    umgerechnet wird (Fallback: heutiger Kurs, siehe `fx_fallback_ticker`).

    Gibt (positionen_df, fx_fallback_ticker) zurück. positionen_df hat die
    Spalten Ticker/Stückzahl/Kaufkurs/Kaufkurs (€) und enthält nur Ticker
    mit aktuell positiver Stückzahl.
    """
    zustand = {}
    fx_fallback_ticker = set()

    for transaktion in sorted(transaktionen, key=_transaktions_sortierschluessel):
        _id, datum, ticker, typ, menge, preis = transaktion
        s = zustand.setdefault(ticker, {"menge": 0.0, "kosten": 0.0, "kosten_eur": 0.0})

        if typ == "Kauf":
            waehrung = currencies.get(ticker)
            wechselkurs = None
            if waehrung == "EUR":
                wechselkurs = 1.0
            elif waehrung is not None and datum is not None:
                wechselkurs = wert_am_oder_vor_datum(
                    wechselkurshistorien_lang.get(waehrung), datum
                )
            if wechselkurs is None:
                # Historischer Kurs nicht verfügbar (oder Datum unbekannt) ->
                # ersatzweise heutigen Kurs nehmen und das kenntlich machen.
                wechselkurs = wechselkurse_aktuell.get(waehrung)
                fx_fallback_ticker.add(ticker)

            s["menge"] += menge
            s["kosten"] += menge * preis
            if wechselkurs is not None:
                s["kosten_eur"] += menge * preis * wechselkurs
            else:
                s["kosten_eur"] = float("nan")
        else:  # Verkauf
            verkaufsmenge = min(menge, s["menge"]) if s["menge"] > 0 else 0.0
            if s["menge"] > 1e-9:
                anteil = verkaufsmenge / s["menge"]
                s["kosten"] -= s["kosten"] * anteil
                s["kosten_eur"] -= s["kosten_eur"] * anteil
            s["menge"] -= verkaufsmenge

    zeilen = []
    for ticker, s in zustand.items():
        if s["menge"] > 1e-9:
            zeilen.append(
                {
                    "Ticker": ticker,
                    "Stückzahl": s["menge"],
                    "Kaufkurs": s["kosten"] / s["menge"],
                    "Kaufkurs (€)": s["kosten_eur"] / s["menge"],
                }
            )

    positionen_df = pd.DataFrame(
        zeilen, columns=["Ticker", "Stückzahl", "Kaufkurs", "Kaufkurs (€)"]
    )
    return positionen_df, sorted(fx_fallback_ticker)


def berechne_bestandsverlauf_je_ticker(transaktionen, datumsindex):
    """Gibt je Ticker eine Series mit der gehaltenen Stückzahl pro Tag zurück.

    `datumsindex` sind die Handelstage, für die wir Kurse haben. Transaktionen
    ohne Datum gelten als "vor dem ersten Tag von datumsindex" passiert.
    """
    transaktionen_je_ticker = {}
    for transaktion in transaktionen:
        ticker = transaktion[2]
        transaktionen_je_ticker.setdefault(ticker, []).append(transaktion)

    ergebnis = {}
    for ticker, rows in transaktionen_je_ticker.items():
        laufende_menge = 0.0
        stuetzpunkte = {}
        for transaktion in sorted(rows, key=_transaktions_sortierschluessel):
            _id, datum, _ticker, typ, menge, _preis = transaktion
            if typ == "Kauf":
                laufende_menge += menge
            else:
                laufende_menge = max(0.0, laufende_menge - menge)
            stuetzpunkt_datum = pd.Timestamp(datum) if datum else datumsindex.min()
            stuetzpunkte[stuetzpunkt_datum] = laufende_menge

        stuetz_reihe = pd.Series(stuetzpunkte).sort_index()
        erweiterter_index = datumsindex.union(stuetz_reihe.index)
        bestand = stuetz_reihe.reindex(erweiterter_index).ffill().fillna(0.0)
        ergebnis[ticker] = bestand.reindex(datumsindex).ffill().fillna(0.0)

    return ergebnis


def berechne_depotverlauf(transaktionen, currencies, period):
    """Berechnet den historischen Depotwert in Euro anhand der echten Bestände.

    Anders als eine reine Kurs-Multiplikation berücksichtigt das hier, wie
    viele Stück eines Tickers an jedem Tag laut Transaktionshistorie
    tatsächlich gehalten wurden (nicht die heutige Stückzahl). Die Kurve
    beginnt daher erst an dem Tag, an dem erstmals eine Position bestand.

    Gibt ein DataFrame (Spalten "Datum", "Depotwert (€)") sowie eine Liste der
    Ticker zurück, für die keine Kurshistorie abrufbar war.
    """
    tickers = tuple(sorted({transaktion[2] for transaktion in transaktionen}))
    kurshistorien = fetch_price_histories(tickers, period)

    benoetigte_waehrungen = tuple(
        sorted({c for t, c in currencies.items() if t in tickers and c is not None and c != "EUR"})
    )
    wechselkurshistorien = fetch_exchange_rate_histories(benoetigte_waehrungen, period)

    kurse_eur_je_ticker = {}
    fehlende_ticker = []
    for ticker in tickers:
        kurse = kurshistorien.get(ticker)
        if kurse is None or kurse.empty:
            fehlende_ticker.append(ticker)
            continue

        waehrung = currencies.get(ticker)
        if waehrung == "EUR":
            wechselkurs = pd.Series(1.0, index=kurse.index)
        else:
            wechselkurs = wechselkurshistorien.get(waehrung)
            if wechselkurs is None or wechselkurs.empty:
                fehlende_ticker.append(ticker)
                continue
            # Wechselkurs auf die Handelstage des Tickers ausrichten (unterschiedliche
            # Börsen/Feiertage) und Lücken mit dem letzten bekannten Kurs auffüllen.
            wechselkurs = wechselkurs.reindex(kurse.index).ffill().bfill()

        kurse_eur_je_ticker[ticker] = kurse * wechselkurs

    if not kurse_eur_je_ticker:
        return None, fehlende_ticker

    # ffill schließt Lücken durch unterschiedliche Handelskalender (z.B. US-
    # und deutsche Feiertage fallen nicht auf dieselben Tage); bfill sorgt
    # zusätzlich dafür, dass ganz am Anfang kein künstlicher Einbruch entsteht.
    kurse_kombiniert = pd.DataFrame(kurse_eur_je_ticker).sort_index().ffill().bfill()
    bestandsverlaeufe = berechne_bestandsverlauf_je_ticker(transaktionen, kurse_kombiniert.index)

    wert_je_ticker = {
        ticker: kurse_kombiniert[ticker] * bestandsverlaeufe[ticker]
        for ticker in kurse_kombiniert.columns
        if ticker in bestandsverlaeufe
    }
    if not wert_je_ticker:
        return None, fehlende_ticker

    depotwert = pd.DataFrame(wert_je_ticker).sum(axis=1, skipna=True)

    # Die Kurve soll erst zeigen, ab wann tatsächlich eine Position bestand -
    # vorher ist der (korrekte) Depotwert schlicht 0 und nicht aussagekräftig.
    gehalten = depotwert[depotwert > 1e-9]
    if gehalten.empty:
        return None, fehlende_ticker
    depotwert = depotwert.loc[gehalten.index.min():]

    verlauf_df = pd.DataFrame(
        {"Datum": depotwert.index, "Depotwert (€)": depotwert.values}
    )
    return verlauf_df, fehlende_ticker


def berechne_index_verlauf(index_ticker, period, ziel_datumsindex):
    """Berechnet den historischen Kursverlauf eines Vergleichsindex in Euro.

    Wird auf `ziel_datumsindex` (die Handelstage des Depots) ausgerichtet,
    damit sich Depot- und Indexkurve im Diagramm über dieselben Daten
    vergleichen lassen. Gibt None zurück, wenn der Index nicht abrufbar ist.
    """
    kurse = fetch_price_histories((index_ticker,), period).get(index_ticker)
    if kurse is None or kurse.empty:
        return None

    waehrung = fetch_currencies((index_ticker,)).get(index_ticker)
    if waehrung == "EUR":
        wechselkurs = pd.Series(1.0, index=kurse.index)
    elif waehrung is None:
        return None
    else:
        wechselkurs = fetch_exchange_rate_histories((waehrung,), period).get(waehrung)
        if wechselkurs is None or wechselkurs.empty:
            return None
        wechselkurs = wechselkurs.reindex(kurse.index).ffill().bfill()

    kurse_eur = kurse * wechselkurs
    return kurse_eur.reindex(ziel_datumsindex).ffill().bfill()


MIN_DATENPUNKTE_RISIKO = 5
HANDELSTAGE_PRO_JAHR = 252
RISIKOFREIER_ZINS = 0.02


def berechne_risikokennzahlen(depotwert_reihe, risikofreier_zins=RISIKOFREIER_ZINS):
    """Berechnet Volatilität, Sharpe Ratio und maximalen Drawdown aus einer Wertreihe.

    `depotwert_reihe` ist eine pandas Series mit dem (indexierten oder
    absoluten) Depotwert pro Tag - für Renditen/Drawdown ist das gleichwertig,
    da beides relative Veränderungen sind. Gibt bei zu wenig Datenpunkten
    None für die jeweilige Kennzahl zurück, statt einen Fehler zu werfen.
    """
    tagesrenditen = depotwert_reihe.pct_change().dropna()

    volatilitaet = None
    sharpe = None
    if len(tagesrenditen) >= MIN_DATENPUNKTE_RISIKO:
        vola_jahr = tagesrenditen.std() * (HANDELSTAGE_PRO_JAHR ** 0.5)
        volatilitaet = vola_jahr * 100
        if vola_jahr > 0:
            rendite_jahr = tagesrenditen.mean() * HANDELSTAGE_PRO_JAHR
            sharpe = (rendite_jahr - risikofreier_zins) / vola_jahr

    max_drawdown = None
    if len(depotwert_reihe) >= 2:
        laufendes_hoch = depotwert_reihe.cummax()
        drawdown = (depotwert_reihe - laufendes_hoch) / laufendes_hoch
        max_drawdown = drawdown.min() * 100

    return {
        "volatilitaet": volatilitaet,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
    }


def berechne_beta(ticker_renditen, index_renditen):
    """Berechnet Beta (Kovarianz mit dem Index / Varianz des Index) aus Tagesrenditen.

    Beta > 1 heißt: schwankt stärker als der Referenzindex, < 1 heißt: schwächer.
    Gibt None zurück, wenn zu wenige gemeinsame Handelstage vorliegen oder der
    Index in diesem Zeitraum keine Schwankung zeigt (Division durch 0).
    """
    if index_renditen is None:
        return None
    gemeinsam = pd.concat(
        [ticker_renditen.rename("ticker"), index_renditen.rename("index")], axis=1, join="inner"
    ).dropna()
    if len(gemeinsam) < MIN_DATENPUNKTE_RISIKO:
        return None
    varianz_index = gemeinsam["index"].var()
    if not varianz_index:
        return None
    return gemeinsam["ticker"].cov(gemeinsam["index"]) / varianz_index


def berechne_ticker_vergleich(tickers, period):
    """Vergleicht mehrere Ticker unabhängig vom Depot (jeweils auf 100 normiert).

    Anders als beim Depot-Wertverlauf wird hier NICHT in Euro umgerechnet:
    für den reinen prozentualen Vergleich ist die Handelswährung unerheblich,
    da jeder Ticker gegen seinen eigenen Startwert normiert wird.

    Gibt (diagramm_df, kennzahlen, fehlgeschlagene_ticker) zurück. diagramm_df
    hat die Spalte "Datum" plus eine Spalte je erfolgreich geladenem Ticker.
    kennzahlen ist eine Liste von Dicts mit allen aus dem Kursverlauf selbst
    berechenbaren Kennzahlen (Gesamtrendite, Volatilität, Max Drawdown, beste/
    schlechteste Tagesrendite, Beta) für die Kennzahlen-Tabelle.
    """
    alle_ticker = tuple(dict.fromkeys(list(tickers) + [BETA_REFERENZ_TICKER]))
    kurshistorien = fetch_price_histories(alle_ticker, period)

    index_kurse = kurshistorien.get(BETA_REFERENZ_TICKER)
    index_renditen = (
        index_kurse.pct_change().dropna()
        if index_kurse is not None and not index_kurse.empty
        else None
    )

    diagramm_df = None
    kennzahlen = []
    fehlgeschlagene_ticker = []

    for ticker in tickers:
        kurse = kurshistorien.get(ticker)
        if kurse is None or kurse.empty:
            fehlgeschlagene_ticker.append(ticker)
            continue

        normiert = kurse / kurse.iloc[0] * 100
        spalte = pd.DataFrame({"Datum": normiert.index, ticker: normiert.values})
        if diagramm_df is None:
            diagramm_df = spalte
        else:
            diagramm_df = diagramm_df.merge(spalte, on="Datum", how="outer")

        risiko = berechne_risikokennzahlen(normiert)
        tagesrenditen = normiert.pct_change().dropna()
        beta = (
            None
            if ticker == BETA_REFERENZ_TICKER
            else berechne_beta(tagesrenditen, index_renditen)
        )

        kennzahlen.append(
            {
                "Ticker": ticker,
                "Gesamtrendite (%)": normiert.iloc[-1] - 100,
                "Volatilität (%)": risiko["volatilitaet"],
                "Max Drawdown (%)": risiko["max_drawdown"],
                "Beste Tagesrendite (%)": (
                    tagesrenditen.max() * 100 if not tagesrenditen.empty else None
                ),
                "Schlechteste Tagesrendite (%)": (
                    tagesrenditen.min() * 100 if not tagesrenditen.empty else None
                ),
                f"Beta (vs. {BETA_REFERENZ_LABEL})": beta,
            }
        )

    if diagramm_df is not None:
        diagramm_df = diagramm_df.sort_values("Datum")

    return diagramm_df, kennzahlen, fehlgeschlagene_ticker


st.title("Mein Asset Manager")

tab_depot, tab_analyse, tab_news = st.tabs(["Mein Depot", "Analyse", "News"])

with tab_depot:
    st.header("Depot-Positionen")

    if _neu_migriert:
        st.info(
            f"{_neu_migriert} bestehende Position(en) wurden automatisch als "
            "Kauf-Transaktionen mit **Datum unbekannt** übernommen, damit nichts "
            "verloren geht. Möchtest du das echte Kaufdatum nachtragen: die "
            "betreffende Transaktion unten im Transaktionsverlauf löschen und "
            "mit dem richtigen Datum neu erfassen."
        )

    transaktionen = get_transactions()

    if not transaktionen:
        st.info("Noch keine Transaktionen vorhanden. Erfasse unten deine erste Transaktion.")
    else:
        alle_tickers = tuple(sorted({t[2] for t in transaktionen}))
        currencies = fetch_currencies(alle_tickers)
        alle_waehrungen = tuple(sorted({c for c in currencies.values() if c is not None}))
        exchange_rates = fetch_exchange_rates(alle_waehrungen)
        wechselkurshistorien_lang = fetch_exchange_rate_histories_lang(
            tuple(w for w in alle_waehrungen if w != "EUR")
        )

        df, fx_fallback_ticker = berechne_positionen(
            transaktionen, currencies, wechselkurshistorien_lang, exchange_rates
        )

    if transaktionen and not df.empty:
        unique_tickers = tuple(sorted(df["Ticker"].unique()))
        current_prices = fetch_prices(unique_tickers)

        df["Währung"] = df["Ticker"].map(currencies)
        df["Wechselkurs zu €"] = df["Währung"].map(exchange_rates)
        df["Aktueller Kurs (Original)"] = df["Ticker"].map(current_prices)
        df["Aktueller Kurs (€)"] = df["Aktueller Kurs (Original)"] * df["Wechselkurs zu €"]
        df["Aktueller Wert (€)"] = df["Stückzahl"] * df["Aktueller Kurs (€)"]
        # Kaufkurs (€) kommt bereits aus berechne_positionen und nutzt den
        # historischen Wechselkurs am jeweiligen Kaufdatum (Durchschnittskosten-
        # methode), nicht den heutigen Kurs.
        df["Kaufwert (€)"] = df["Stückzahl"] * df["Kaufkurs (€)"]
        df["Gewinn/Verlust (€)"] = df["Aktueller Wert (€)"] - df["Kaufwert (€)"]
        df["Gewinn/Verlust (%)"] = (df["Gewinn/Verlust (€)"] / df["Kaufwert (€)"]) * 100

        alle_spalten = list(df.columns)
        with st.expander("Spalten anzeigen/ausblenden"):
            checkbox_spalten = st.columns(4)
            sichtbare_spalten = []
            for index, spaltenname in enumerate(alle_spalten):
                with checkbox_spalten[index % 4]:
                    if st.checkbox(spaltenname, value=True, key=f"spalte_sichtbar_{spaltenname}"):
                        sichtbare_spalten.append(spaltenname)

        if not sichtbare_spalten:
            st.warning("Bitte mindestens eine Spalte auswählen.")
            sichtbare_spalten = alle_spalten

        st.dataframe(
            df[sichtbare_spalten],
            hide_index=True,
            use_container_width=True,
            column_config={
                "ID": st.column_config.NumberColumn(width="small"),
                "Ticker": st.column_config.TextColumn(width="small"),
                "Stückzahl": st.column_config.NumberColumn(width="small", format="%.2f"),
                "Währung": st.column_config.TextColumn(width="small"),
                "Kaufkurs": st.column_config.NumberColumn(width="small", format="%.2f"),
                "Aktueller Kurs (Original)": st.column_config.NumberColumn(
                    width="small", format="%.2f"
                ),
                "Wechselkurs zu €": st.column_config.NumberColumn(width="small", format="%.4f"),
                "Aktueller Kurs (€)": st.column_config.NumberColumn(
                    width="small", format="€ %.2f"
                ),
                "Aktueller Wert (€)": st.column_config.NumberColumn(
                    width="small", format="€ %.2f"
                ),
                "Kaufkurs (€)": st.column_config.NumberColumn(width="small", format="€ %.2f"),
                "Kaufwert (€)": st.column_config.NumberColumn(width="small", format="€ %.2f"),
                "Gewinn/Verlust (€)": st.column_config.NumberColumn(
                    width="small", format="€ %.2f"
                ),
                "Gewinn/Verlust (%)": st.column_config.NumberColumn(
                    width="small", format="%.2f %%"
                ),
            },
        )

        fehlende_kurse = [t for t, price in current_prices.items() if price is None]
        if fehlende_kurse:
            st.warning(
                "Für folgende Ticker konnte gerade kein aktueller Kurs abgerufen "
                f"werden, sie fehlen daher in der Summe: {', '.join(fehlende_kurse)}"
            )

        fehlende_kurse_set = set(fehlende_kurse)
        fehlende_wechselkurse = [
            t
            for t in df["Ticker"].unique()
            if t not in fehlende_kurse_set
            and exchange_rates.get(currencies.get(t)) is None
        ]
        if fehlende_wechselkurse:
            st.warning(
                "Für folgende Ticker konnte gerade kein Wechselkurs abgerufen werden, "
                f"sie fehlen daher in der Summe: {', '.join(fehlende_wechselkurse)}"
            )

        df_gueltig = df.dropna(subset=["Aktueller Wert (€)"])
        gesamtwert = df_gueltig["Aktueller Wert (€)"].sum()
        gesamt_gv = df_gueltig["Gewinn/Verlust (€)"].sum()

        spalte1, spalte2 = st.columns(2)
        spalte1.metric("Gesamtwert des Depots", f"{gesamtwert:,.2f}")
        spalte2.metric("Gesamter Gewinn/Verlust", f"{gesamt_gv:,.2f}")

        st.subheader("Depot-Aufteilung")
        if not df_gueltig.empty:
            pie_df = (
                df_gueltig.groupby("Ticker", as_index=False)["Aktueller Wert (€)"]
                .sum()
                .sort_values("Aktueller Wert (€)", ascending=False)
            )
            # Feste Farbreihenfolge, damit jede Position immer dieselbe Farbe hat.
            # Ab 8 Positionen werden die kleinsten zu "Sonstige" zusammengefasst,
            # damit keine zwei Segmente eine kaum unterscheidbare Farbe bekommen.
            max_segmente = len(KATEGORIE_FARBEN)
            if len(pie_df) > max_segmente:
                haupt = pie_df.iloc[: max_segmente - 1]
                rest_summe = pie_df.iloc[max_segmente - 1 :]["Aktueller Wert (€)"].sum()
                pie_df = pd.concat(
                    [
                        haupt,
                        pd.DataFrame(
                            {"Ticker": ["Sonstige"], "Aktueller Wert (€)": [rest_summe]}
                        ),
                    ],
                    ignore_index=True,
                )

            fig = px.pie(
                pie_df,
                values="Aktueller Wert (€)",
                names="Ticker",
                color_discrete_sequence=KATEGORIE_FARBEN,
            )
            fig.update_traces(textinfo="label+percent", textposition="inside")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Für das Diagramm fehlen noch aktuelle Werte.")

        if fx_fallback_ticker:
            st.warning(
                "Für folgende Ticker konnte der Wechselkurs am jeweiligen "
                "Kaufdatum nicht ermittelt werden (z.B. weil das Datum unbekannt "
                "ist oder kein historischer Kurs verfügbar war); ersatzweise "
                f"wurde der heutige Wechselkurs verwendet: {', '.join(fx_fallback_ticker)}"
            )

        st.caption(
            "Kaufkurs (€) wird mit dem historischen Wechselkurs am jeweiligen "
            "Kaufdatum umgerechnet (Durchschnittskostenmethode bei mehreren "
            "Käufen desselben Tickers) - nicht mehr mit dem heutigen Kurs."
        )
    elif transaktionen:
        st.info(
            "Aktuell keine offenen Positionen - alle gehaltenen Ticker wurden "
            "bereits wieder verkauft. Die Wertentwicklung unten zeigt trotzdem "
            "deine gesamte Transaktionshistorie."
        )

    if transaktionen:
        st.subheader("Wertentwicklung")
        zeitraum_optionen = {"1 Monat": "1mo", "6 Monate": "6mo", "1 Jahr": "1y"}
        spalte_zeitraum, spalte_index = st.columns(2)
        with spalte_zeitraum:
            ausgewaehlter_zeitraum = st.selectbox(
                "Zeitraum", list(zeitraum_optionen.keys()), index=2
            )
        with spalte_index:
            ausgewaehlter_index = st.selectbox(
                "Vergleichsindex", list(BENCHMARK_OPTIONEN.keys())
            )
        zeitraum_code = zeitraum_optionen[ausgewaehlter_zeitraum]

        verlauf_df, fehlende_historie = berechne_depotverlauf(
            transaktionen, currencies, zeitraum_code
        )

        if fehlende_historie:
            st.warning(
                "Für folgende Ticker konnte keine Kurshistorie abgerufen werden, "
                f"sie fehlen daher in der Kurve: {', '.join(fehlende_historie)}"
            )

        if verlauf_df is not None and not verlauf_df.empty:
            # Beide Kurven auf einen gemeinsamen Startwert von 100 normieren,
            # damit man die prozentuale Entwicklung statt absoluter Eurobeträge
            # vergleicht (siehe Erklärung unten).
            ziel_datumsindex = pd.DatetimeIndex(verlauf_df["Datum"])
            depot_indexiert = verlauf_df.set_index("Datum")["Depotwert (€)"]
            depot_indexiert = depot_indexiert / depot_indexiert.iloc[0] * 100

            diagramm_df = pd.DataFrame(
                {"Datum": depot_indexiert.index, "Mein Depot": depot_indexiert.values}
            )

            index_ticker = BENCHMARK_OPTIONEN[ausgewaehlter_index]
            index_kurse_eur = berechne_index_verlauf(
                index_ticker, zeitraum_code, ziel_datumsindex
            )

            index_rendite = None
            if index_kurse_eur is None or index_kurse_eur.isna().all():
                st.warning(
                    f"Für den Vergleichsindex {ausgewaehlter_index} ({index_ticker}) "
                    "konnten gerade keine historischen Kurse abgerufen werden."
                )
            else:
                index_indexiert = index_kurse_eur / index_kurse_eur.iloc[0] * 100
                diagramm_df[ausgewaehlter_index] = index_indexiert.values
                index_rendite = index_indexiert.iloc[-1] - 100

            fig_verlauf = px.line(
                diagramm_df,
                x="Datum",
                y=[spalte for spalte in diagramm_df.columns if spalte != "Datum"],
                # Feste, gut unterscheidbare Farben statt der Standardfarben von
                # Plotly, die sich für Depot und Index zu ähnlich sahen.
                color_discrete_map={"Mein Depot": "#2a78d6", ausgewaehlter_index: "#eb6834"},
            )
            fig_verlauf.update_yaxes(title="Indexiert (Start = 100)")
            fig_verlauf.update_layout(legend_title_text="")
            st.plotly_chart(fig_verlauf, use_container_width=True)

            depot_rendite = depot_indexiert.iloc[-1] - 100
            spalte_rendite_depot, spalte_rendite_index = st.columns(2)
            spalte_rendite_depot.metric(
                f"Rendite Depot ({ausgewaehlter_zeitraum})",
                f"{depot_rendite:+.2f} %",
                delta=(
                    f"{depot_rendite - index_rendite:+.2f} %-Pkt. ggü. {ausgewaehlter_index}"
                    if index_rendite is not None
                    else None
                ),
            )
            spalte_rendite_index.metric(
                f"Rendite {ausgewaehlter_index} ({ausgewaehlter_zeitraum})",
                f"{index_rendite:+.2f} %" if index_rendite is not None else "—",
            )

            st.markdown("**Risikokennzahlen Depot**")
            risiko = berechne_risikokennzahlen(depot_indexiert)
            spalte_vola, spalte_sharpe, spalte_drawdown = st.columns(3)
            spalte_vola.metric(
                "Volatilität (annualisiert)",
                f"{risiko['volatilitaet']:.2f} %"
                if risiko["volatilitaet"] is not None
                else "Zu wenig Daten",
            )
            spalte_sharpe.metric(
                "Sharpe Ratio (vereinfacht)",
                f"{risiko['sharpe']:.2f}" if risiko["sharpe"] is not None else "Zu wenig Daten",
            )
            spalte_drawdown.metric(
                "Maximaler Drawdown",
                f"{risiko['max_drawdown']:.2f} %"
                if risiko["max_drawdown"] is not None
                else "Zu wenig Daten",
            )
            st.caption(
                f"Hinweis: Die Sharpe Ratio nimmt vereinfachend einen festen "
                f"risikofreien Zins von {RISIKOFREIER_ZINS * 100:.0f} % pro Jahr an und "
                "rechnet die tägliche Rendite/Volatilität linear (× 252 bzw. × √252) "
                "auf ein Jahr hoch - eine grobe Näherung, kein exaktes Finanzmodell."
            )
        else:
            st.info(
                "Für die Wertentwicklung fehlen entweder historische Kurse, oder "
                "es gibt im abrufbaren Zeitraum zu wenige Transaktionen für eine "
                "sinnvolle Auswertung."
            )

        st.caption(
            "Die Kurve zeigt deine **tatsächlichen** Bestände im Zeitverlauf: für "
            "jeden Tag wird berechnet, wie viele Stück du laut deiner "
            "Transaktionshistorie an diesem Tag wirklich gehalten hast, "
            "multipliziert mit dem historischen Kurs. Sie beginnt deshalb erst an "
            "dem Tag, an dem erstmals eine Position bestand - nicht am Anfang des "
            "gewählten Zeitraums. Fürs Diagramm wird Plotly Express verwendet, "
            "wie schon beim Tortendiagramm."
        )

    st.header("Neue Transaktion erfassen")

    if "ticker_input" not in st.session_state:
        st.session_state["ticker_input"] = ""

    # Die Live-Suche kann nicht in einem st.form() stehen, weil sie bei
    # jedem Tastendruck einen eigenen Rerun auslöst - das würde sich mit
    # dem Formular beißen. Deshalb liegt sie davor und schreibt den
    # ausgewählten Ticker in den Session State, den das Textfeld im
    # Formular darunter anzeigt (und das man dort auch von Hand anpassen kann).
    ausgewaehlter_ticker = st_searchbox(
        search_tickers,
        placeholder="Ticker suchen (z.B. SAP, Apple, MSCI World)...",
        label="Ticker suchen",
        key="ticker_searchbox",
    )
    if ausgewaehlter_ticker:
        st.session_state["ticker_input"] = ausgewaehlter_ticker

    with st.form("add_transaction_form", clear_on_submit=True):
        ticker = st.text_input(
            "Ticker (aus der Suche oben oder von Hand, z.B. AAPL)",
            key="ticker_input",
        )
        spalte_datum, spalte_typ = st.columns(2)
        with spalte_datum:
            transaktionsdatum = st.date_input("Datum", value=date.today())
        with spalte_typ:
            typ = st.selectbox("Typ", ["Kauf", "Verkauf"])
        quantity = st.number_input("Stückzahl", min_value=0.0, step=1.0)
        price_per_unit = st.number_input(
            "Preis pro Stück (in der Handelswährung des Tickers)",
            min_value=0.0,
            step=0.01,
        )

        submitted = st.form_submit_button("Transaktion erfassen")

        if submitted:
            if not ticker:
                st.error("Bitte einen Ticker eingeben oder aus der Suche auswählen.")
            elif quantity <= 0:
                st.error("Die Stückzahl muss größer als 0 sein.")
            else:
                add_transaction(
                    transaktionsdatum.isoformat(), ticker, typ, quantity, price_per_unit
                )
                st.success(f"{typ} von {quantity:g} {ticker.upper()} wurde erfasst.")
                st.rerun()

    st.header("Transaktionsverlauf")

    if not transaktionen:
        st.info("Noch keine Transaktionen erfasst. Nutze das Formular oben.")
    else:
        transaktionen_df = pd.DataFrame(
            transaktionen,
            columns=["ID", "Datum", "Ticker", "Typ", "Stückzahl", "Preis pro Stück"],
        )
        transaktionen_df["Datum"] = transaktionen_df["Datum"].fillna("Datum unbekannt")
        st.dataframe(
            transaktionen_df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "ID": st.column_config.NumberColumn(width="small"),
                "Datum": st.column_config.TextColumn(width="small"),
                "Ticker": st.column_config.TextColumn(width="small"),
                "Typ": st.column_config.TextColumn(width="small"),
                "Stückzahl": st.column_config.NumberColumn(width="small", format="%.2f"),
                "Preis pro Stück": st.column_config.NumberColumn(
                    width="small", format="%.2f"
                ),
            },
        )

        transaktion_options = {
            (
                f"ID {tid} – {datum or 'Datum unbekannt'} – {typ} {ticker} "
                f"({menge:g} Stk @ {preis:.2f})"
            ): (tid, ticker, typ)
            for tid, datum, ticker, typ, menge, preis in transaktionen
        }
        ausgewaehltes_transaktions_label = st.selectbox(
            "Transaktion zum Löschen auswählen", list(transaktion_options.keys())
        )
        loesch_id, loesch_ticker, loesch_typ = transaktion_options[
            ausgewaehltes_transaktions_label
        ]
        if st.button("Transaktion löschen"):
            confirm_delete_transaction(loesch_id, loesch_ticker, loesch_typ)

with tab_analyse:
    st.header("Analyse")
    st.warning(
        "Diese Analyse zeigt ausschließlich die **Vergangenheit** und ist "
        "keine Prognose oder Kaufempfehlung. Vergangene Wertentwicklung ist "
        "kein verlässlicher Indikator für zukünftige Ergebnisse."
    )
    st.write(
        "Vergleiche 2 bis 5 beliebige Wertpapiere unabhängig von deinem Depot "
        "- z.B. um vor einem Kauf verschiedene Aktien, ETFs oder Anleihen-ETFs "
        "gegenüberzustellen."
    )

    if "analyse_ticker_liste" not in st.session_state:
        st.session_state["analyse_ticker_liste"] = []
    if "analyse_ticker_input" not in st.session_state:
        st.session_state["analyse_ticker_input"] = ""

    st.subheader("Ticker auswählen")

    ausgewaehlter_analyse_ticker = st_searchbox(
        search_tickers,
        placeholder="Ticker suchen (z.B. SAP, Apple, MSCI World)...",
        label="Ticker suchen",
        key="analyse_searchbox",
    )
    if ausgewaehlter_analyse_ticker:
        st.session_state["analyse_ticker_input"] = ausgewaehlter_analyse_ticker

    # clear_on_submit statt manuellem Zurücksetzen: st.session_state eines
    # Widgets darf nach dessen Erzeugung im selben Lauf nicht mehr verändert
    # werden. Innerhalb eines Formulars räumt clear_on_submit das Feld nach
    # dem Absenden automatisch selbst leer.
    with st.form("analyse_add_form", clear_on_submit=True):
        neuer_analyse_ticker = st.text_input(
            "Ticker (aus der Suche oben oder von Hand)",
            key="analyse_ticker_input",
        )
        analyse_hinzufuegen_geklickt = st.form_submit_button("Hinzufügen")

    if analyse_hinzufuegen_geklickt:
        ticker_normalisiert = neuer_analyse_ticker.strip().upper()
        aktuelle_liste = st.session_state["analyse_ticker_liste"]
        if not ticker_normalisiert:
            st.error("Bitte einen Ticker eingeben oder aus der Suche auswählen.")
        elif ticker_normalisiert in aktuelle_liste:
            st.warning(f"{ticker_normalisiert} ist bereits in der Auswahl.")
        elif len(aktuelle_liste) >= 5:
            st.warning(
                "Maximal 5 Ticker möglich. Entferne erst einen, um einen neuen "
                "hinzuzufügen."
            )
        else:
            st.session_state["analyse_ticker_liste"] = aktuelle_liste + [ticker_normalisiert]
            st.rerun()

    aktuelle_analyse_liste = st.session_state["analyse_ticker_liste"]
    if aktuelle_analyse_liste:
        analyse_auswahl = st.multiselect(
            "Ausgewählte Ticker (zum Entfernen abwählen)",
            options=aktuelle_analyse_liste,
            default=aktuelle_analyse_liste,
        )
        if analyse_auswahl != aktuelle_analyse_liste:
            st.session_state["analyse_ticker_liste"] = analyse_auswahl
            st.rerun()

    zeitraum_optionen_analyse = {
        "1 Monat": "1mo",
        "6 Monate": "6mo",
        "1 Jahr": "1y",
        "5 Jahre": "5y",
    }
    ausgewaehlter_zeitraum_analyse = st.selectbox(
        "Zeitraum", list(zeitraum_optionen_analyse.keys()), index=2, key="analyse_zeitraum"
    )

    aktuelle_analyse_liste = st.session_state["analyse_ticker_liste"]
    if len(aktuelle_analyse_liste) < 2:
        st.info("Wähle mindestens 2 Ticker aus, um sie zu vergleichen.")
    else:
        zeitraum_code_analyse = zeitraum_optionen_analyse[ausgewaehlter_zeitraum_analyse]
        diagramm_df, kennzahlen, fehlgeschlagene_ticker = berechne_ticker_vergleich(
            aktuelle_analyse_liste, zeitraum_code_analyse
        )

        if fehlgeschlagene_ticker:
            st.warning(
                "Für folgende Ticker konnte keine Kurshistorie abgerufen werden, "
                f"sie fehlen im Vergleich: {', '.join(fehlgeschlagene_ticker)}"
            )

        waehrungen_analyse = fetch_currencies(tuple(aktuelle_analyse_liste))
        unterschiedliche_waehrungen = {c for c in waehrungen_analyse.values() if c is not None}
        if len(unterschiedliche_waehrungen) > 1:
            st.caption(
                "Hinweis: Die ausgewählten Ticker handeln in unterschiedlichen "
                f"Währungen ({', '.join(sorted(unterschiedliche_waehrungen))}). Für "
                "den Vergleich spielt das keine Rolle, da jeder Ticker auf seinen "
                "eigenen Startwert (100) normiert wird - verglichen wird die "
                "prozentuale Veränderung, nicht der absolute Kurs."
            )

        if diagramm_df is not None and len(diagramm_df.columns) > 1:
            fig_vergleich = px.line(
                diagramm_df,
                x="Datum",
                y=[spalte for spalte in diagramm_df.columns if spalte != "Datum"],
                color_discrete_sequence=KATEGORIE_FARBEN,
            )
            fig_vergleich.update_yaxes(title="Indexiert (Start = 100)")
            fig_vergleich.update_layout(legend_title_text="")
            st.plotly_chart(fig_vergleich, use_container_width=True)

            st.subheader("Kennzahlen")

            # Anzeigename -> Standardmäßig aktiv? Reihenfolge bestimmt die Spaltenreihenfolge.
            kursverlauf_optionen = {
                "Gesamtrendite (%)": True,
                "Volatilität (%)": True,
                "Max Drawdown (%)": True,
                "Beste Tagesrendite (%)": False,
                "Schlechteste Tagesrendite (%)": False,
                f"Beta (vs. {BETA_REFERENZ_LABEL})": False,
            }
            fundamental_optionen = {
                "KGV": False,
                "Dividendenrendite (%)": False,
                "Marktkapitalisierung": False,
            }

            with st.expander("Kennzahlen auswählen"):
                st.caption("Aus dem Kursverlauf (selbst berechnet)")
                spalten_kv = st.columns(3)
                sichtbare_kursverlauf = []
                for i, (name, standard) in enumerate(kursverlauf_optionen.items()):
                    with spalten_kv[i % 3]:
                        if st.checkbox(name, value=standard, key=f"analyse_kz_{name}"):
                            sichtbare_kursverlauf.append(name)

                st.caption("Fundamentaldaten (von yfinance, weniger zuverlässig)")
                spalten_fd = st.columns(3)
                sichtbare_fundamental = []
                for i, (name, standard) in enumerate(fundamental_optionen.items()):
                    with spalten_fd[i % 3]:
                        if st.checkbox(name, value=standard, key=f"analyse_kz_{name}"):
                            sichtbare_fundamental.append(name)

            def formatiere_prozent(wert):
                return "-" if wert is None or pd.isna(wert) else f"{wert:.2f} %"

            def formatiere_zahl(wert, nachkomma=2):
                return "-" if wert is None or pd.isna(wert) else f"{wert:.{nachkomma}f}"

            if sichtbare_kursverlauf:
                prozent_spalten = {
                    "Gesamtrendite (%)",
                    "Volatilität (%)",
                    "Beste Tagesrendite (%)",
                    "Schlechteste Tagesrendite (%)",
                    "Max Drawdown (%)",
                }
                kennzahlen_anzeige = []
                for zeile in kennzahlen:
                    neue_zeile = {"Ticker": zeile["Ticker"]}
                    for spalte in sichtbare_kursverlauf:
                        wert = zeile.get(spalte)
                        neue_zeile[spalte] = (
                            formatiere_prozent(wert)
                            if spalte in prozent_spalten
                            else formatiere_zahl(wert)
                        )
                    kennzahlen_anzeige.append(neue_zeile)

                st.dataframe(
                    pd.DataFrame(kennzahlen_anzeige),
                    hide_index=True,
                    use_container_width=True,
                )
                st.caption(
                    "Gesamtrendite, Volatilität, Max Drawdown, beste/schlechteste "
                    "Tagesrendite und Beta werden ausschließlich aus den "
                    "historischen Kursen des gewählten Zeitraums berechnet (Beta "
                    f"gegenüber dem {BETA_REFERENZ_LABEL}), mit derselben Logik wie "
                    "die Depot-Risikokennzahlen. Bei zu kurzer Historie steht "
                    "\"-\" statt einer unsicheren Zahl."
                )
            else:
                st.info("Wähle oben mindestens eine Kursverlauf-Kennzahl aus.")

            if sichtbare_fundamental:
                fundamentaldaten = fetch_fundamentals(tuple(aktuelle_analyse_liste))
                fundamental_anzeige = []
                for ticker in aktuelle_analyse_liste:
                    if ticker in fehlgeschlagene_ticker:
                        continue
                    daten = fundamentaldaten.get(ticker, {})
                    zeile = {"Ticker": ticker}
                    if "KGV" in sichtbare_fundamental:
                        zeile["KGV"] = formatiere_zahl(daten.get("kgv"))
                    if "Dividendenrendite (%)" in sichtbare_fundamental:
                        zeile["Dividendenrendite (%)"] = formatiere_prozent(
                            daten.get("dividendenrendite")
                        )
                    if "Marktkapitalisierung" in sichtbare_fundamental:
                        marktkap = daten.get("marktkapitalisierung")
                        zeile["Marktkapitalisierung"] = (
                            "-" if marktkap is None else f"{marktkap / 1e9:,.1f} Mrd."
                        )
                    fundamental_anzeige.append(zeile)

                st.markdown("**Fundamentaldaten** _(Quelle: yfinance)_")
                st.dataframe(
                    pd.DataFrame(fundamental_anzeige),
                    hide_index=True,
                    use_container_width=True,
                )
                st.caption(
                    "Fundamentaldaten stammen direkt von Yahoo Finance und sind "
                    "weniger verlässlich als die selbst berechneten Kursverlauf-"
                    "Kennzahlen oben: sie können je nach Datenlage veraltet oder "
                    "ungenau sein und fehlen bei ETFs/Anleihen-ETFs oft komplett "
                    "(dann steht \"-\"). Die Marktkapitalisierung ist in der "
                    "jeweiligen Handelswährung des Tickers angegeben, nicht in Euro."
                )
        else:
            st.info("Für den Vergleich fehlen noch historische Kurse.")

with tab_news:
    st.header("Finanznachrichten")
    schlagzeilen, fehlgeschlagene_quellen = fetch_news()

    if fehlgeschlagene_quellen:
        st.caption(f"Gerade nicht erreichbar: {', '.join(fehlgeschlagene_quellen)}")

    if schlagzeilen:
        for eintrag in schlagzeilen:
            datum_text = (
                eintrag["datum"].strftime("%d.%m. %H:%M Uhr") if eintrag["datum"] else ""
            )
            st.markdown(f"**[{eintrag['titel']}]({eintrag['link']})**")
            st.caption(f"{eintrag['quelle']} · {datum_text}")
    else:
        st.info("Aktuell keine Nachrichten verfügbar.")
