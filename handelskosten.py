"""Handelskosten-Simulation fuer das Paper-Trading (01.11.2026).

Bis hierher wurde jeder Kauf und Verkauf zum exakten Kurs ohne Gebuehr
gebucht (Tagesbericht: "Gebuehren: n/a, Slippage: n/a"). Bei Depots mit
200 EUR und Positionen von 10-70 EUR ist das der groesste Unterschied
zwischen Paper und echtem Konto: 1 EUR Ordergebuehr sind dort 1,5-10 %.

Modell je Order:
    gebuehr   = max(gebuehr_min, betrag * gebuehr_prozent / 100) + gebuehr_fix
    slippage  = Kurs wird beim Kauf um s % erhoeht, beim Verkauf gesenkt
                (s je Instrumentklasse: etf / aktie / spekulativ)

Einstellbar in settings.json, Abschnitt "handelskosten" (alle Felder
optional, fehlende nehmen den Standard unten):

    "handelskosten": {
        "aktiv": true,
        "gebuehr_fix": 1.0,          # je Order, in Depotwaehrung
        "gebuehr_prozent": 0.0,      # zusaetzlich in % vom Betrag
        "gebuehr_min": 0.0,          # Mindestgebuehr fuer den %-Anteil
        "slippage_prozent": {"etf": 0.05, "aktie": 0.10, "spekulativ": 0.30},
        "max_gebuehr_anteil_prozent": null   # z. B. 5 -> Kaeufe, bei denen die
                                             # Gebuehr > 5 % des Betrags waere,
                                             # werden nicht ausgefuehrt
    }

"aktiv": false schaltet alles ab (Verhalten wie vor dem 01.11.2026).
"""
import json
import math
import os

BASE = os.path.dirname(os.path.abspath(__file__))

STANDARD = {
    "aktiv": True,
    "gebuehr_fix": 1.0,
    "gebuehr_prozent": 0.0,
    "gebuehr_min": 0.0,
    "slippage_prozent": {"etf": 0.05, "aktie": 0.10, "spekulativ": 0.30},
    "max_gebuehr_anteil_prozent": None,
}

_cache = {"mtime": None, "cfg": None}


def konfiguration():
    """Standardwerte, ueberschrieben durch settings.json -> handelskosten."""
    pfad = os.path.join(BASE, "settings.json")
    try:
        mtime = os.path.getmtime(pfad)
    except OSError:
        mtime = None
    if _cache["cfg"] is not None and _cache["mtime"] == mtime:
        return _cache["cfg"]
    cfg = json.loads(json.dumps(STANDARD))
    try:
        with open(pfad, encoding="utf-8") as f:
            eigene = (json.load(f) or {}).get("handelskosten") or {}
        for k, v in eigene.items():
            if k == "slippage_prozent" and isinstance(v, dict):
                cfg["slippage_prozent"].update(v)
            elif k in cfg:
                cfg[k] = v
    except Exception:
        pass
    _cache.update(mtime=mtime, cfg=cfg)
    return cfg


def klasse(tier=None, art=None):
    """Instrumentklasse fuer die Slippage.

    art: "etf" | "aktie" | "spekulativ" hat Vorrang.
    tier (risk_profile): 4 = breite ETFs, 3/6 = spekulativ/Hebel, sonst Aktie.
    """
    if art in ("etf", "aktie", "spekulativ"):
        return art
    try:
        t = int(tier)
    except (TypeError, ValueError):
        return "aktie"
    if t == 4:
        return "etf"
    if t in (3, 6):
        return "spekulativ"
    return "aktie"


def gebuehr(betrag, cfg=None):
    cfg = cfg or konfiguration()
    if not cfg.get("aktiv") or betrag <= 0:
        return 0.0
    prozent = betrag * float(cfg.get("gebuehr_prozent") or 0) / 100.0
    prozent = max(float(cfg.get("gebuehr_min") or 0), prozent) if prozent > 0 else 0.0
    return round(prozent + float(cfg.get("gebuehr_fix") or 0), 4)


def ausfuehrungskurs(kurs, seite, tier=None, art=None, cfg=None):
    """Kurs inkl. Slippage. seite: "kauf" (teurer) oder "verkauf" (billiger)."""
    cfg = cfg or konfiguration()
    if not cfg.get("aktiv") or not kurs or kurs <= 0:
        return kurs
    s = float((cfg.get("slippage_prozent") or {}).get(klasse(tier, art), 0) or 0) / 100.0
    return kurs * (1 + s) if seite == "kauf" else kurs * (1 - s)


def kauf(menge, kurs, bargeld, tier=None, art=None, nachkommastellen=4):
    """Rechnet einen Kauf mit Kosten durch.

    Gibt ein dict zurueck:
        menge      - ggf. reduziert, damit menge*kurs_eff + gebuehr <= bargeld
        kurs_eff   - Ausfuehrungskurs inkl. Slippage
        gebuehr    - Ordergebuehr
        gesamt     - abzubuchender Betrag
        abgelehnt  - Grund (str) oder None
    """
    cfg = konfiguration()
    k_eff = ausfuehrungskurs(kurs, "kauf", tier, art, cfg)
    if not k_eff or k_eff <= 0 or menge <= 0:
        return {"menge": 0, "kurs_eff": k_eff, "gebuehr": 0.0, "gesamt": 0.0,
                "abgelehnt": "kein Kurs oder keine Menge"}
    g = gebuehr(menge * k_eff, cfg)
    faktor = 10 ** nachkommastellen
    if menge * k_eff + g > bargeld:
        menge = math.floor(max(0.0, (bargeld - g) / k_eff) * faktor) / faktor
        g = gebuehr(menge * k_eff, cfg) if menge > 0 else g
    if menge <= 0:
        return {"menge": 0, "kurs_eff": k_eff, "gebuehr": g, "gesamt": 0.0,
                "abgelehnt": "Bargeld reicht nach Gebuehr %.2f nicht" % g}
    anteil_max = cfg.get("max_gebuehr_anteil_prozent")
    if anteil_max not in (None, "") and g > menge * k_eff * float(anteil_max) / 100.0:
        return {"menge": 0, "kurs_eff": k_eff, "gebuehr": g, "gesamt": 0.0,
                "abgelehnt": "Gebuehr %.2f > %s %% von %.2f"
                             % (g, anteil_max, menge * k_eff)}
    return {"menge": menge, "kurs_eff": k_eff, "gebuehr": g,
            "gesamt": menge * k_eff + g, "abgelehnt": None}


def verkauf(menge, kurs, tier=None, art=None):
    """Erloes eines Verkaufs nach Slippage und Gebuehr (nie negativ)."""
    cfg = konfiguration()
    k_eff = ausfuehrungskurs(kurs, "verkauf", tier, art, cfg)
    brutto = menge * k_eff
    g = min(gebuehr(brutto, cfg), brutto)
    return {"kurs_eff": k_eff, "gebuehr": g, "erloes": brutto - g}
