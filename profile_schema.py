"""
profile_schema.py — Phase 2: Identität & Struktur (Profil-Modell)
Gemäß Micro-Trader-Zielarchitektur §29.A.

Ein Profil kapselt alle markt-/depot-/risiko-bezogenen Konfigurationen:
  - märkte:        welche Börsenregionen aktiv (US, DE, JP)
  - depotarten:    welche Depot-Kategorien (aktien, etf, spec)
  - risk_model:    Risiko-Stufen-Parameter (RISK_STUFEN)
  - news_sources:  aktive News-Feeds
  - data_sources:  Kursdaten-Quellen (yfinance etc.)
  - base_currency: Basiswährung des Depots
  - handelszeiten: Börsenkalender-Referenz
  - regelstand_ref: welcher freigegebene Regelstand gilt
  - modus:         shadow | paper | live

Das Profil ist aktuell eine KONFIGURATIONS-HÜLLE (Metadaten) — es greift
noch NICHT steuernd in Trading-Logik ein (das folgt in Phase 3+).
Es macht den Zustand aber sichtbar, versionierbar und mehrfach anlegbar.
"""

import json
import os
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PROFIL_DATEI = os.path.join(BASE, "profile.json")


# ── JSON-Schema (Validierung bei load/save) ──────────────────────────────
PROFIL_SCHEMA = {
    "märkte": list,            # ["US"] / ["US","DE"] / ["US","DE","JP"]
    "depotarten": list,         # ["aktien","etf","spec"]
    "risk_model": str,          # "RISK_STUFEN" (Referenz auf batch_trader.RISK_STUFEN)
    "news_sources": list,       # ["finanzen.net", "yfinance_news", ...]
    "data_sources": list,       # ["yfinance"]
    "base_currency": str,       # "USD" / "EUR" / "JPY"
    "handelszeiten": str,       # "boersen.py" (Referenz)
    "regelstand_ref": str,      # "latest" / "v2.x"
    "modus": str,               # "shadow" | "paper" | "live"
}


def _default_profil():
    """US_Test_Shadow — Basis-Profil (vorhandene Logik, Singleton)."""
    return {
        "name": "US_Test_Shadow",
        "beschreibung": "US-Markt, Paper-Trading, Shadow-Lernmodus (kein Live-Eingriff)",
        "märkte": ["US"],
        "depotarten": ["aktien", "etf", "spec"],
        "risk_model": "RISK_STUFEN",
        "news_sources": ["yfinance_news"],
        "data_sources": ["yfinance"],
        "base_currency": "USD",
        "handelszeiten": "boersen.py",
        "regelstand_ref": "latest",
        "modus": "shadow",
        "erstellt": "2026-08-05",
        "version": "2.16.3",
    }


class Profil:
    """Einfache Profil-Klasse (Dict-Wrapper mit Validierung)."""

    def __init__(self, daten: dict):
        self.daten = daten

    def __getitem__(self, key):
        return self.daten[key]

    def get(self, key, default=None):
        return self.daten.get(key, default)

    @property
    def name(self):
        return self.daten.get("name", "unbenannt")

    @property
    def modus(self):
        return self.daten.get("modus", "shadow")

    def märkte(self):
        return self.daten.get("märkte", [])

    def depotarten(self):
        return self.daten.get("depotarten", [])

    @property
    def base_currency(self):
        return self.daten.get("base_currency", "USD")

    def to_dict(self):
        return dict(self.daten)

    def validate(self):
        """Prüft Pflichtfelder gegen Schema (wirft bei Fehler)."""
        for feld, typ in PROFIL_SCHEMA.items():
            if feld not in self.daten:
                raise ValueError(f"Profil fehlt Feld: {feld}")
            if not isinstance(self.daten[feld], typ):
                raise ValueError(f"Profil-Feld {feld} hat falschen Typ (erwartet {typ.__name__})")
        if self.daten["modus"] not in ("shadow", "paper", "live"):
            raise ValueError(f"Profil.modu s ungültig: {self.daten['modus']}")
        return True


def lade_profil(pfad: str = PROFIL_DATEI) -> Profil:
    """Lädt Profil aus profile.json. Wenn fehlend/kaputt -> Default + speichern."""
    if os.path.exists(pfad):
        try:
            with open(pfad, encoding="utf-8") as f:
                d = json.load(f)
            p = Profil(d)
            p.validate()
            return p
        except Exception:
            pass
    # Default erzeugen + persistieren
    p = Profil(_default_profil())
    speichere_profil(p, pfad)
    return p


def speichere_profil(profil: Profil, pfad: str = PROFIL_DATEI) -> bool:
    """Schreibt Profil atomar (temp + rename)."""
    try:
        profil.validate()
        tmp = pfad + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(profil.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp, pfad)
        return True
    except Exception as e:
        print(f"Profil-Speichern fehlgeschlagen: {e}")
        return False


# Modus-Icon für Dashboard
MODUS_ICON = {"shadow": "👁️", "paper": "📄", "live": "🔴"}




# ── Mehrfach-Profile (Phase 2 Erweiterung) ──────────────────────────────
ACTIVE_DATEI = os.path.join(BASE, "active_profile.json")


def liste_profile():
    """Alle verfügbaren Profile (profile_*.json im BASE)."""
    profile = []
    import glob
    for fn in sorted(glob.glob(os.path.join(BASE, "profile_*.json"))):
        try:
            with open(fn, encoding="utf-8") as f:
                d = json.load(f)
            name = d.get("name", os.path.basename(fn))
            profile.append({"datei": os.path.basename(fn), "name": name,
                            "modus": d.get("modus", "?"), "märkte": d.get("märkte", [])})
        except Exception:
            pass
    return profile


def aktives_profil_name():
    """Liest den Namen des aktiven Profils (aus active_profile.json)."""
    if os.path.exists(ACTIVE_DATEI):
        try:
            with open(ACTIVE_DATEI, encoding="utf-8") as f:
                return json.load(f).get("aktiv", "US_Test_Shadow")
        except Exception:
            pass
    return "US_Test_Shadow"


def setze_aktives_profil(name):
    """Setzt das aktive Profil (schreibt active_profile.json)."""
    # Profil-Datei finden
    ziel = os.path.join(BASE, f"profile_{name}.json")
    if not os.path.exists(ziel):
        # Fallback: name ohne prefix
        ziel = os.path.join(BASE, f"{name}.json")
    if not os.path.exists(ziel):
        return False
    try:
        with open(ACTIVE_DATEI, "w", encoding="utf-8") as f:
            json.dump({"aktiv": name, "zeit": time.strftime("%Y-%m-%d %H:%M")}, f)
        return True
    except Exception:
        return False


def lade_aktives_profil():
    """Lädt das aktive Profil (oder Default wenn keins aktiv)."""
    name = aktives_profil_name()
    ziel = os.path.join(BASE, f"profile_{name}.json")
    if os.path.exists(ziel):
        try:
            with open(ziel, encoding="utf-8") as f:
                return Profil(json.load(f))
        except Exception:
            pass
    return lade_profil()  # Default


if __name__ == "__main__":
    p = lade_profil()
    print(f"Profil geladen: {p.name} | Modus: {p.modus} | Märkte: {p.märkte}")
    p.validate()
    print("Validierung: OK")
