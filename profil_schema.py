"""
Micro-Trader — Profil-Schema (Phase 2, §29.A)
JSON-Schema für Profil-Objekt: märkte[], depotarten[], risk_model,
news_sources[], data_sources[], base_currency, handelszeiten, regelstand_ref, modus.

Validiert Profile und liefert Basis für Multi-Markt (US/DE/JP).
KEIN Trading-Eingriff — nur Datenstruktur.
"""
import json
import os
from datetime import datetime

PROFILE_DIR = os.path.dirname(os.path.abspath(__file__))

# Valide Werte (aus Zielarchitektur §4, §5, §7, §29.A)
GueltigeMaerkte = ["US", "DE", "JP"]
GueltigeDepotarten = ["aktien", "etf", "spekulation", "live", "shadow", "paper"]
GueltigeModi = ["shadow", "paper", "live"]
GueltigeWaehrungen = ["USD", "EUR", "JPY"]

SCHEMA = {
    "name": {"typ": str, "required": True},
    "märkte": {"typ": list, "items": str, "allowed": GueltigeMaerkte, "required": True},
    "depotarten": {"typ": list, "items": str, "allowed": GueltigeDepotarten, "required": True},
    "risk_model": {"typ": str, "required": False, "default": "standard"},
    "news_sources": {"typ": list, "items": str, "required": False, "default": []},
    "data_sources": {"typ": list, "items": str, "required": False, "default": ["yfinance"]},
    "base_currency": {"typ": str, "allowed": GueltigeWaehrungen, "required": True},
    "handelszeiten": {"typ": dict, "required": False, "default": {}},
    "regelstand_ref": {"typ": str, "required": False, "default": "v2.16.12"},
    "modus": {"typ": str, "allowed": GueltigeModi, "required": True},
}


def validiere_profil(profil):
    """Validiert ein Profil-Dict gegen SCHEMA.
    Return: (ok: bool, fehler: list, warns: list)"""
    fehler = []
    warns = []
    if not isinstance(profil, dict):
        return False, ["Profil muss ein Dict sein"], warns

    for feld, spec in SCHEMA.items():
        if feld not in profil:
            if spec.get("required"):
                fehler.append(f"Fehlendes Pflichtfeld: {feld}")
            else:
                profil[feld] = spec.get("default")
            continue
        wert = profil[feld]
        # Typ-Check
        if spec["typ"] is list and not isinstance(wert, list):
            fehler.append(f"{feld}: muss eine Liste sein")
            continue
        if spec["typ"] is dict and not isinstance(wert, dict):
            fehler.append(f"{feld}: muss ein Dict sein")
            continue
        if spec["typ"] is str and not isinstance(wert, str):
            fehler.append(f"{feld}: muss ein String sein")
            continue
        # Allowed-Check
        if "allowed" in spec:
            if spec["typ"] is list:
                for item in wert:
                    if item not in spec["allowed"]:
                        fehler.append(f"{feld}: '{item}' nicht erlaubt (erlaubt: {spec['allowed']})")
            else:
                if wert not in spec["allowed"]:
                    fehler.append(f"{feld}: '{wert}' nicht erlaubt (erlaubt: {spec['allowed']})")
    return (len(fehler) == 0), fehler, warns


def lade_profil(name):
    """Lädt Profil aus profile_<name>.json."""
    pf = os.path.join(PROFILE_DIR, f"profile_{name}.json")
    if not os.path.exists(pf):
        return None, [f"Profil-Datei nicht gefunden: {pf}"]
    try:
        d = json.load(open(pf, encoding="utf-8"))
        ok, f, w = validiere_profil(d)
        return d, (f if not ok else []), w
    except Exception as e:
        return None, [f"Parse-Fehler: {e}"], []


def speichere_profil(name, profil):
    """Speichert Profil als profile_<name>.json (validiert)."""
    ok, f, w = validiere_profil(profil)
    if not ok:
        return False, f
    pf = os.path.join(PROFILE_DIR, f"profile_{name}.json")
    profil["_validated_at"] = datetime.now().isoformat()
    json.dump(profil, open(pf, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    return True, w


if __name__ == "__main__":
    # Test: US_Test_Shadow (Basis, vorhandene Logik)
    us = {
        "name": "US_Test_Shadow",
        "märkte": ["US"],
        "depotarten": ["aktien", "etf", "spekulation"],
        "base_currency": "USD",
        "modus": "shadow",
        "news_sources": ["yfinance_news"],
        "data_sources": ["yfinance", "finnhub", "twelvedata", "alphavantage"],
    }
    ok, f, w = validiere_profil(us)
    print(f"US_Test_Shadow valid: {ok} | fehler: {f} | warns: {w}")
