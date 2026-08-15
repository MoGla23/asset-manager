"""Datenbank-Funktionen für den Asset Manager.

Die Transaktionen (Käufe/Verkäufe) sind die einzige Wahrheit über das
Depot; aktuelle Positionen werden daraus abgeleitet (siehe app.py).
Die alte Tabelle 'positions' bleibt nur als Quelle für die einmalige
Migration in Transaktionen erhalten.

Lokale SQLite-Datenbank unter data/portfolio.db.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "portfolio.db"


def get_connection():
    # Legt den "data"-Ordner an, falls er fehlt (z.B. bei einem frischen
    # Checkout aus Git, wo die Datenbankdatei bewusst nicht enthalten ist).
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    """Legt alle benötigten Tabellen an, falls sie noch nicht existieren."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                quantity REAL NOT NULL,
                buy_price REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                ticker TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('Kauf', 'Verkauf')),
                quantity REAL NOT NULL,
                price_per_unit REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )


def add_transaction(date, ticker, type_, quantity, price_per_unit):
    """Legt eine Transaktion an. `date` ist ein ISO-String (YYYY-MM-DD) oder None."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO transactions (date, ticker, type, quantity, price_per_unit) "
            "VALUES (?, ?, ?, ?, ?)",
            (date, ticker.upper(), type_, quantity, price_per_unit),
        )


def get_transactions():
    """Alle Transaktionen, chronologisch (Transaktionen ohne Datum zuerst)."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, date, ticker, type, quantity, price_per_unit FROM transactions "
            "ORDER BY (date IS NULL) DESC, date, id"
        )
        return cursor.fetchall()


def delete_transaction(transaction_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))


def migrate_legacy_positions_to_transactions():
    """Wandelt einmalig alte 'positions'-Einträge in Kauf-Transaktionen um.

    Läuft nur beim allerersten Mal (markiert über die 'meta'-Tabelle), damit
    spätere Neustarts keine bereits gelöschten Transaktionen wiederherstellen.
    Gibt die Anzahl neu angelegter Transaktionen zurück (0, wenn schon migriert).
    """
    with get_connection() as conn:
        bereits_migriert = conn.execute(
            "SELECT value FROM meta WHERE key = 'positions_migrated'"
        ).fetchone()
        if bereits_migriert:
            return 0

        alte_positionen = conn.execute(
            "SELECT ticker, quantity, buy_price FROM positions"
        ).fetchall()
        for ticker, quantity, buy_price in alte_positionen:
            conn.execute(
                "INSERT INTO transactions (date, ticker, type, quantity, price_per_unit) "
                "VALUES (NULL, ?, 'Kauf', ?, ?)",
                (ticker, quantity, buy_price),
            )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('positions_migrated', '1')"
        )
        return len(alte_positionen)
