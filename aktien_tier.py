"""Tier aus den Yahoo-Feldern ableiten.

WARUM: Die Aktien-Datenbasis (screener_aktien_beta.json) stammt
aus echten Yahoo-Abfragen. Die Ticker stehen zu 74 Prozent nicht
in TICKER_TO_TIER, das ist die handgepflegte 686er-Liste des
alten Systems. Ohne eigene Ableitung bekommen alle diese Titel
den Default-Tier 2, und engine.bewerte() verwirft sie bei den
meisten Risikostufen, weil allowed_tiers dort nicht 2 enthaelt.

    Risk 10: 19 Kandidaten, davon 12 "neu" -> alle Default 2
    erlaubt bei Risk 10: [0, 1, 4] -> 0 Titel bestehen

DESHALB: Das Tier wird aus den Feldern berechnet, die Yahoo
liefert und die screener_aktien_beta.json bereits enthaelt:
beta, sektor, branche, ma_cap, volumen, preis.

Die Skala ist dieselbe wie im alten System, soweit sie sich aus
den Daten ableiten laesst: 0 = defensiv, 4 = sehr spekulativ.
Massgeblich ist die Beta, das ist der Risikotrag, den Yahoo
tatsaechlich liefert. Sektor und Marktkapitalisierung
modifizieren.
"""
import io
import os
import json


# ── Beta-Baender ────────────────────────────────────────────────
# Die Grenzen entsprechen den Beta-Baendern, mit denen
# aktien_beta.py die Risikostufen 0..90 bildet. Tier 0 beginnt
# dort, wo die Stufe 0 beginnt.
TIER_BETA = (
    (0.60, 0),
    (0.90, 1),
    (1.20, 2),
    (1.60, 3),
    (99.0, 4),   # alles darueber
)

# Branchen, die unabhaengig von der Beta hochriskant sind
SPEKULATIVE_BRANCHEN = {
    "Biotechnology", "Biotech", "Biotechnology / In Vitro Diagnostics",
    "Capital Markets", "Shell Companies", "Oil & Gas Integrated",
    "Internet Content & Information", "Entertainment",
    "Specialty Retail", "Resorts & Casinos", "Solar",
    "Semiconductor Equipment & Materials", "Steel/Iron Ore",
}

# Branchen, die bei gleicher Beta ein Tier niedriger liegen
DEFENSIVE_BRANCHEN = {
    "Beverages - Non-Alcoholic", "Grocery Stores", "Discount Stores",
    "Tobacco", "Integrated Freight & Logistics", "Utilities - Regulated Electric",
    "Utilities - Regulated Gas", "Banks - Diversified", "Capital Markets - Diversified",
}

# Branchen, die bei gleicher Beta ein Tier hoeher liegen
ZYKLISCHE_BRANCHEN = {
    "Oil & Gas Drilling", "Copper", "Gold", "Silver",
    "Building Materials", "Real Estate Services", "Credit Services",
    "Air Freight/Delivery Services", "Trucking", "Marine Shipping",
}


def tier_fuer(kand):
    """Tier 0..4 aus einem Kandidaten der Yahoo-Datenbasis.

    kand: dict aus screener_aktien_beta.json mit mindestens
    beta, branche, preis, ma_cap, volumen.
    """
    try:
        beta = float(kand.get("beta") or 0)
    except (TypeError, ValueError):
        beta = 0.0

    tier = 4
    for grenze, t in TIER_BETA:
        if beta < grenze:
            tier = t
            break
    else:
        tier = 4

    branche = (kand.get("branche") or "").strip()
    if branche in DEFENSIVE_BRANCHEN and tier > 0:
        tier -= 1
    elif branche in SPEKULATIVE_BRANCHEN and tier < 4:
        tier += 1
    elif branche in ZYKLISCHE_BRANCHEN and tier < 4:
        tier += 1

    # Sehr kleine Marktkapitalisierung ist zusaetzlich riskant
    try:
        cap = float(kand.get("ma_cap") or 0)
    except (TypeError, ValueError):
        cap = 0.0
    if 0 < cap < 500_000_000 and tier < 4:
        tier += 1

    # Sehr illiquide Titel likewise
    try:
        vol = float(kand.get("volumen") or 0)
    except (TypeError, ValueError):
        vol = 0.0
    if 0 < vol < 200_000 and tier < 4:
        tier += 1

    return int(max(0, min(4, tier)))


def baue_tier_tabelle(datei="/opt/micro-trader/screener_aktien_beta.json"):
    """Ticker -> Tier aus der Aktien-Datenbasis. Gibt (dict, zahlen) zurueck."""
    d = json.load(io.open(datei, encoding="utf-8"))
    tabelle = {}
    zahlen = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for stufe, kandidaten in d.get("stufen", {}).items():
        for k in kandidaten or []:
            t = (k.get("ticker") or "").strip().upper()
            if not t or t in tabelle:
                continue
            tier = tier_fuer(k)
            tabelle[t] = tier
            zahlen[tier] += 1
    return tabelle, zahlen


if __name__ == "__main__":
    tabelle, zahlen = baue_tier_tabelle()
    print("  Ticker mit Tier: %d" % len(tabelle))
    print("  Verteilung: %s" % zahlen)

    # Gegenprobe: die alte Liste bleibt erhalten und wird gemischt
    import sys
    sys.path.insert(0, "/opt/micro-trader")
    from risk_profile import TICKER_TO_TIER
    alt = len(TICKER_TO_TIER)
    print("  alte Tabelle: %d" % alt)
    doppelt = [t for t in tabelle if t in TICKER_TO_TIER
               and TICKER_TO_TIER[t] != tabelle[t]]
    print("  Ticker in beiden mit anderem Tier: %d" % len(doppelt))