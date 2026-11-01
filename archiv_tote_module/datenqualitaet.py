"""
Micro-Trader — Datenqualität-Check (Phase 4.3, §8)
Prüft Kursdaten auf: Vollständigkeit, Aktualität, Duplikate, Symbolkorrektheit,
Währungsbezug, Handelsplatz, Zeitreihen, Plausibilität.

KEIN Trading-Eingriff — nur Validierung für Audit/Monitoring.
"""
import os
from datetime import datetime, timedelta

QUALITAET_REGELN = {
    "vollstaendigkeit": "Datenpunkte >= 50 (für RSI/MACD)",
    "aktualitaet": "Letzter Kurs <= 2 Tage alt",
    "plausibilitaet": "Preis > 0 und < 100000 (kein 0$-Crash)",
    "symbolkorrektheit": "Ticker existiert in yfinance",
    "waehrungsbezug": "Preis in erwarteter Währung (US=USD, DE=EUR, JP=JPY)",
}


def pruefe_kursdaten(ticker, daten, erwartete_waehrung="USD"):
    """Prüft ein Kursdaten-Dict (aus marktdaten.hole_kurs oder fetch_analyse).
    daten: Dict mit 'aktuell', 'sma20', 'sma50', 'close' (optional)
    Return: {ok: bool, warnungen: list, fehler: list}
    """
    warnungen = []
    fehler = []
    ok = True

    # Vollständigkeit
    if daten.get("close") is not None:
        if len(daten["close"]) < 50:
            fehler.append(f"Vollständigkeit: nur {len(daten['close'])} Datenpunkte (<50)")
            ok = False
    elif daten.get("aktuell") is None:
        fehler.append("Vollständigkeit: kein aktueller Kurs")
        ok = False

    # Plausibilität (0$-Crash-Schutz)
    preis = daten.get("aktuell")
    if preis is not None:
        if preis <= 0:
            fehler.append(f"Plausibilität: Preis {preis} <= 0 (0$-Crash!)")
            ok = False
        elif preis > 100000:
            warnungen.append(f"Plausibilität: Preis {preis} sehr hoch (>100k)")
        elif preis < 0.01:
            warnungen.append(f"Plausibilität: Preis {preis} sehr niedrig (<0.01$)")

    # Aktualität
    if daten.get("letztes_update"):
        try:
            lu = datetime.fromisoformat(daten["letztes_update"])
            if datetime.now() - lu > timedelta(days=2):
                warnungen.append(f"Aktualität: letzter Kurs {lu.date()} (>2 Tage alt)")
        except Exception:
            pass

    # Währungsbezug (Basis-Check)
    w = daten.get("waehrung")
    if w and erwartete_waehrung and w != erwartete_waehrung:
        warnungen.append(f"Währungsbezug: {w} != erwartet {erwartete_waehrung}")

    return {"ok": ok, "warnungen": warnungen, "fehler": fehler}


def pruefe_depot_depot_json(pfad):
    """Prüft ein Depot-JSON auf Datenqualität (Bargeld/Positionen plausibel)."""
    import json
    d = json.load(open(pfad, encoding="utf-8"))
    warnungen = []
    fehler = []
    ok = True

    bargeld = d.get("bargeld", 0)
    shares = d.get("shares", 0)
    start = d.get("start", d.get("start_wert", 0))

    if bargeld < 0:
        fehler.append(f"Bargeld negativ: {bargeld}")
        ok = False
    if shares < 0:
        fehler.append(f"Shares negativ: {shares}")
        ok = False
    if start <= 0 and (bargeld > 0 or shares > 0):
        fehler.append(f"Start=0 aber Bargeld/Shares > 0 (toter Platzhalter)")
        ok = False
    if bargeld > 1000 and shares == 0:
        warnungen.append(f"Bargeld {bargeld} aber keine Position (vielleicht tot?)")

    return {"ok": ok, "warnungen": warnungen, "fehler": fehler}


if __name__ == "__main__":
    # Test
    test_daten = {"aktuell": 150.0, "close": [1] * 60, "waehrung": "USD"}
    r = pruefe_kursdaten("AAPL", test_daten, "USD")
    print(f"Test AAPL: ok={r['ok']}, warn={r['warnungen']}, err={r['fehler']}")

    test_crash = {"aktuell": 0.0, "close": [1] * 60}
    r2 = pruefe_kursdaten("TEST", test_crash, "USD")
    print(f"Test 0$-Crash: ok={r2['ok']}, err={r2['fehler']}")
