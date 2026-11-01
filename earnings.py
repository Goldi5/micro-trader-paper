"""Earnings-Sperre: keine Neukaeufe kurz vor Quartalszahlen (01.11.2026).

Rund um Quartalszahlen springen Kurse oft um 5-20 % - in beide Richtungen.
Ein Neukauf kurz davor ist eine Wette auf die Zahlen, keine Entscheidung
aus Trend oder Bewertung. Verkaeufe und bestehende Positionen sind nicht
betroffen.

Quelle: yfinance Ticker.calendar ("Earnings Date"). Ergebnisse werden
24 h in .earnings_cache.json gehalten (Laufzeitdatei, git-ignoriert).
Ist kein Termin ermittelbar (ETF, Datenausfall), ist der Kauf ERLAUBT
(fail-open) - die Sperre darf den Handel bei einem Ausfall nicht stilllegen.

settings.json (optional):
    "earnings_sperre": {"aktiv": true, "tage_vorher": 2}
"""
import json
import os
import time
from datetime import date, datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".earnings_cache.json")
CACHE_DAUER = 24 * 3600


def konfiguration():
    cfg = {"aktiv": True, "tage_vorher": 2}
    try:
        with open(os.path.join(BASE, "settings.json"), encoding="utf-8") as f:
            cfg.update((json.load(f) or {}).get("earnings_sperre") or {})
    except Exception:
        pass
    return cfg


def _hole_termin(ticker):
    """Naechster Earnings-Termin als ISO-Datum oder None (Netzabruf)."""
    import yfinance as yf
    cal = yf.Ticker(ticker).calendar
    termine = []
    if isinstance(cal, dict):
        termine = cal.get("Earnings Date") or []
    elif cal is not None and hasattr(cal, "loc"):  # aeltere yfinance: DataFrame
        try:
            termine = list(cal.loc["Earnings Date"])
        except Exception:
            termine = []
    heute = date.today()
    kuenftig = []
    for t in termine:
        try:
            d = t if isinstance(t, date) and not isinstance(t, datetime) else t.date()
        except Exception:
            continue
        if d >= heute:
            kuenftig.append(d)
    return min(kuenftig).isoformat() if kuenftig else None


def _lade_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _speichere_cache(c):
    try:
        tmp = CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(c, f)
        os.replace(tmp, CACHE)
    except Exception:
        pass


def naechster_termin(ticker):
    t = (ticker or "").upper()
    if not t:
        return None
    c = _lade_cache()
    e = c.get(t)
    if e and time.time() - e.get("ts", 0) < CACHE_DAUER:
        return e.get("termin")
    try:
        termin = _hole_termin(t)
    except Exception:
        # Abruf fehlgeschlagen: nicht cachen, damit der naechste Lauf es
        # erneut versucht; Kauf bleibt erlaubt.
        return None
    c[t] = {"ts": time.time(), "termin": termin}
    _speichere_cache(c)
    return termin


def kauf_gesperrt(ticker, heute=None):
    """(True, Grund) wenn die Quartalszahlen in <= tage_vorher Tagen kommen."""
    cfg = konfiguration()
    if not cfg.get("aktiv"):
        return False, None
    termin = naechster_termin(ticker)
    if not termin:
        return False, None
    try:
        d = date.fromisoformat(termin)
    except ValueError:
        return False, None
    heute = heute or date.today()
    tage = (d - heute).days
    if 0 <= tage <= int(cfg.get("tage_vorher", 2)):
        return True, "Quartalszahlen am %s (in %d Tag%s)" % (
            d.strftime("%d.%m."), tage, "" if tage == 1 else "en")
    return False, None
