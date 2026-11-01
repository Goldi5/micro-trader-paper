"""
Micro-Trader — Handelszeiten & Feiertage (Phase 12, §12)
Verhindert falsche Ausführungen an Feiertagen (US/DE/JP).

Prüft pro Markt: ist heute ein Feiertag? (Statische Liste + Wochenenden)
Genutzt von boersen.ist_offen() und Scheduler, um Trades an Feiertagen zu überspringen.

§12 Zweck: keine falschen Ausführungen · keine irreführenden Reports · keine falschen Regime.
"""
import os
import json
from datetime import datetime, date

BASE = os.path.dirname(os.path.abspath(__file__))


# ─── Statische Feiertagslisten 2026 (vereinfacht, keine beweglichen Ostern-basierten exakt) ───
# Vollständige Listen: https://www.boerse-frankfurt.de / https://www.jpx.co.jp / NYSE
FEIERTAGE_2026 = {
    "US": [
        "2026-01-01",  # New Year's Day
        "2026-01-19",  # MLK Day
        "2026-02-16",  # Presidents' Day
        "2026-04-03",  # Good Friday
        "2026-05-25",  # Memorial Day
        "2026-06-19",  # Juneteenth
        "2026-07-03",  # Independence Day (observed)
        "2026-09-07",  # Labor Day
        "2026-11-26",  # Thanksgiving
        "2026-12-25",  # Christmas
    ],
    "DE": [
        "2026-01-01",  # Neujahr
        "2026-04-03",  # Karfreitag
        "2026-04-06",  # Ostermontag
        "2026-05-01",  # Tag der Arbeit
        "2026-05-14",  # Christi Himmelfahrt
        "2026-05-25",  # Pfingstmontag
        "2026-10-03",  # Tag der Deutschen Einheit
        "2026-12-25",  # 1. Weihnachtstag
        "2026-12-26",  # 2. Weihnachtstag
    ],
    "JP": [
        "2026-01-01",  # New Year's Day
        "2026-01-12",  # Coming of Age Day
        "2026-02-11",  # National Foundation Day
        "2026-02-23",  # Emperor's Birthday
        "2026-04-29",  # Showa Day
        "2026-05-03",  # Constitution Memorial Day
        "2026-05-04",  # Greenery Day
        "2026-05-05",  # Children's Day
        "2026-07-20",  # Marine Day
        "2026-08-11",  # Mountain Day
        "2026-09-21",  # Respect for the Aged Day
        "2026-10-12",  # Sports Day
        "2026-11-03",  # Culture Day
        "2026-11-23",  # Labor Thanksgiving Day
    ],
}


def is_wochenende(datum=None):
    """Samstag (5) oder Sonntag (6)?"""
    if datum is None:
        datum = date.today()
    return datum.weekday() >= 5  # 5=Samstag, 6=Sonntag


def feiertag(markt, datum=None):
    """Ist heute (oder datum) ein Feiertag in markt? → bool + Name."""
    if markt not in FEIERTAGE_2026:
        return False, None
    if datum is None:
        datum = date.today()
    ds = datum.strftime("%Y-%m-%d")
    if ds in FEIERTAGE_2026[markt]:
        return True, ds
    return False, None


def markt_geschlossen(markt, datum=None):
    """Kombinierter Check: Wochenende ODER Feiertag."""
    if is_wochenende(datum):
        return True, "Wochenende"
    f, name = feiertag(markt, datum)
    if f:
        return True, f"Feiertag ({name})"
    return False, None


def feiertage_liste(markt):
    """Alle Feiertage eines Marktes (für UI/Debug)."""
    return FEIERTAGE_2026.get(markt, [])


if __name__ == "__main__":
    heute = date.today()
    print(f"Heute: {heute} ({'Sa/So' if is_wochenende(heute) else 'Wochentag'})")
    for m in ["US", "DE", "JP"]:
        zu, grund = markt_geschlossen(m, heute)
        print(f"  {m}: {'GESCHLOSSEN' if zu else 'OFFEN'} ({grund or '-'})")
