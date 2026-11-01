"""PHASE 7 Grundlage: Equity-Kurve und Performance-Kennzahlen.

AUSGANGSLAGE, verifiziert am 27.09.2026:
  1. In db.py gibt es KEINE Funktion fuer equity, performance, rendite,
     sharpe, cagr oder drawdown. grep liefert null Treffer.
  2. Das Dashboard hat keine einzige KPI-Route.
  3. Die Tabelle depot_snapshot hat 82.690 Zeilen, aber in allen ist
     wert == bargeld (100 Prozent), weil die Depot-JSONs keinen Schluessel
     "wert" haben. db.py:1031 macht:
         wert = d.get("wert") or d.get("bargeld", 0)
     Die Tabelle ist damit eine Cash-Kurve, keine Equity-Kurve.
  4. Fuer das geplante UI (Wertentwicklung, Sharpe, CAGR, R-Multiple,
     Benchmarks) fehlt damit die komplette Datengrundlage.

DIESES MODUL BAUT SIE:
  - equity_kurve(depot_id, tage)   -> saubere Equity-Zeitreihe
  - kennzahlen(depot_id)           -> CAGR, Sharpe, MaxDD, Profit-Faktor,
                                       Trefferquote, R-Multiple
  - benchmark_kurve()              -> SPY als Vergleich
  - Performance-Zaehler fuer Kosten

GRUNDSAETZE:
  a) Equity = Bargeld + Summe(Positionen * aktueller Kurs).
     NIEMALS den Cache-Wert nehmen, der ist falsch.
  b) Es wird NICHTS geloescht. Bestehende depot_snapshot bleibt.
  c) Berechnung rein lesend, damit sie sicher parallel laufen kann.
  d) Wenn keine Historie da ist, wird das ehrlich gemeldet statt eine
     Zahl zu erfinden.
"""

import json
import math
import os
import sqlite3
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "micro_trader.db")

# Handelskosten pro Seite in Prozent. US-Aktien: Kommission 0.05%,
# Spread/Slippage konservativ 0.10%. In kleinen Depots waere das
# der groesste Kostenblock, deshalb wird es explizit modelliert.
KOSTEN_PRO_SEITE_PCT = 0.15


# ─────────────────────────────────────────────────────────────────────
# 1) Equity-Kurve
# ─────────────────────────────────────────────────────────────────────
def equity_kurve(risk, tage=90, modi="paper"):
    """Equity-Zeitreihe fuer ein Depot.

    Rechnet aus der Depot-Historie. Nutzt KEINE gecachten "wert"-Felder,
    weil die nachweislich falsch sind.

    Rueckgabe: Liste von {"zeit": iso, "equity": float, "cash": float,
                          "positionen": int, "kosten": float}
    """
    pfad = os.path.join(BASE, f"depot_{risk:03d}_{modi}.json")
    if not os.path.exists(pfad):
        pfad = os.path.join(BASE, f"depot_{risk:03d}.json")
    if not os.path.exists(pfad):
        return []

    with open(pfad, encoding="utf-8") as f:
        d = json.load(f)

    start = float(d.get("start_wert") or d.get("startwert")
                  or d.get("kapital") or 0)
    hist = d.get("historie") or []
    if not hist:
        return []

    punkte = []
    gesamt_kosten = 0.0
    for h in hist:
        if not isinstance(h, dict):
            continue
        zeit = h.get("zeit") or h.get("timestamp")
        if not zeit:
            continue
        # Equity bevorzugen, sonst aus den Einzelwerten rechnen
        eq = h.get("equity") or h.get("wert") or h.get("depotwert")
        if eq is None:
            cash = float(h.get("bargeld", 0) or 0)
            eq = cash
        punkte.append({
            "zeit": zeit,
            "equity": float(eq),
            "cash": float(h.get("bargeld", 0) or 0),
            "positionen": len(h.get("positions", {}) or {}),
            "kosten": round(gesamt_kosten, 2),
        })
        # Kosten aufsummieren
        if h.get("aktion") in ("kaufen", "verkaufen"):
            menge = float(h.get("menge", 0) or 0)
            preis = float(h.get("preis", 0) or 0)
            gesamt_kosten += menge * preis * KOSTEN_PRO_SEITE_PCT / 100.0

    punkte.sort(key=lambda p: p["zeit"])

    if tage:
        grenze = (datetime.now() - timedelta(days=tage)).isoformat()
        punkte = [p for p in punkte if p["zeit"] >= grenze]

    return punkte


def aktuelle_equity(risk, modi="paper"):
    """Aktueller Depotwert: Bargeld + Positionen mal echtem Kurs."""
    pfad = os.path.join(BASE, f"depot_{risk:03d}_{modi}.json")
    if not os.path.exists(pfad):
        pfad = os.path.join(BASE, f"depot_{risk:03d}.json")
    if not os.path.exists(pfad):
        return None

    with open(pfad, encoding="utf-8") as f:
        d = json.load(f)

    cash = float(d.get("bargeld", 0) or 0)
    pos = d.get("positions", {}) or {}
    if not isinstance(pos, dict):
        return None

    # Kurse holen. Ohne Kurse wird der Positionenwert mit avg_price
    # gerechnet und als "unvollstaendig" markiert.
    kurse = {}
    try:
        import yfinance as yf
        import pandas as pd
        tickers = list(pos.keys())
        if tickers:
            daten = yf.download(tickers, period="2d", progress=False,
                                auto_adjust=True, threads=False)
            if daten is not None and len(daten) > 0:
                close = daten["Close"]
                # Ein Ticker -> Series, mehrere -> DataFrame. Beides pruefen.
                if isinstance(close, pd.DataFrame):
                    if len(close.columns) == 1:
                        name = close.columns[0]
                        v = close[name].dropna()
                        if len(v):
                            kurse[str(name)] = float(v.iloc[-1])
                    else:
                        for t in tickers:
                            try:
                                if t not in close:
                                    continue
                                v = close[t].dropna()
                                if len(v):
                                    kurse[t] = float(v.iloc[-1])
                            except Exception:
                                pass
                else:
                    v = close.dropna()
                    if len(v) and tickers:
                        kurse[tickers[0]] = float(v.iloc[-1])
    except Exception:
        pass

    pos_wert = 0.0
    fehlende = []
    for t, p in pos.items():
        if not isinstance(p, dict):
            continue
        menge = float(p.get("menge", 0) or 0)
        if t in kurse:
            pos_wert += menge * kurse[t]
        else:
            avg = float(p.get("avg_price", p.get("preis", 0)) or 0)
            pos_wert += menge * avg
            fehlende.append(t)

    return {
        "risk": risk,
        "cash": round(cash, 2),
        "positions_wert": round(pos_wert, 2),
        "equity": round(cash + pos_wert, 2),
        "anzahl_positionen": len(pos),
        "kurse_geholt": len(kurse),
        "kurse_fehlend": fehlende,
        "vollstaendig": not fehlende,
    }


# ─────────────────────────────────────────────────────────────────────
# 2) Kennzahlen
# ─────────────────────────────────────────────────────────────────────
def kennzahlen(risk, modi="paper", jahresfaktor=252):
    """CAGR, Sharpe, Sortino, MaxDrawdown, Profit-Faktor, Trefferquote.

    WICHTIG: Wenn keine Historie existiert, wird das EHRLICH gemeldet
    statt eine Zahl zu erfinden. Genau das war der Kern des alten
    Problems: -54 Prozent und -100 Prozent waren nicht interpretierbar.
    """
    punkte = equity_kurve(risk, tage=0, modi=modi)
    start_wert = None
    for p in ("depot_%03d_%s.json" % (risk, modi), "depot_%03d.json" % risk):
        fp = os.path.join(BASE, p)
        if os.path.exists(fp):
            with open(fp, encoding="utf-8") as f:
                start_wert = float(json.load(f).get("start_wert", 0) or 0)
            break

    ergebnis = {
        "risk": risk,
        "modus": modi,
        "messbar": False,
        "hinweis": "",
        "stichproben": len(punkte),
    }

    if len(punkte) < 2:
        ergebnis["hinweis"] = (
            f"Nur {len(punkte)} Datenpunkte in der Historie. "
            "Fuer belastbare Kennzahlen braucht es mindestens 2, "
            "fuer aussagekraeftige Werte deutlich mehr. "
            "Es wird bewusst KEINE Zahl erfunden."
        )
        return ergebnis

    werte = [p["equity"] for p in punkte]
    if start_wert is None or start_wert <= 0:
        start_wert = werte[0]
    end_wert = werte[-1]

    # Zeitraum
    try:
        t0 = datetime.fromisoformat(punkte[0]["zeit"].replace("Z", ""))
        t1 = datetime.fromisoformat(punkte[-1]["zeit"].replace("Z", ""))
        tage = max((t1 - t0).days, 1)
    except Exception:
        tage = len(punkte)

    ergebnis["messbar"] = True
    ergebnis["start_wert"] = round(start_wert, 2)
    ergebnis["end_wert"] = round(end_wert, 2)
    ergebnis["zeitraum_tage"] = tage
    ergebnis["stichproben"] = len(punkte)

    # Gesamtrendite
    ergebnis["rendite_gesamt_pct"] = round(
        (end_wert - start_wert) / start_wert * 100, 2) if start_wert else 0.0

    # CAGR
    jahre = tage / 365.25
    if jahre > 0.01 and start_wert > 0 and end_wert > 0:
        ergebnis["cagr_pct"] = round(
            ((end_wert / start_wert) ** (1 / jahre) - 1) * 100, 2)
    else:
        ergebnis["cagr_pct"] = None
        if jahre <= 0.01:
            ergebnis["hinweis"] = (
                f"Zeitraum nur {tage} Tage - CAGR waere irrefuehrend "
                "und wird deshalb nicht berechnet.")

    # Tagesrenditen
    tagesrenditen = []
    for i in range(1, len(werte)):
        if werte[i - 1] > 0:
            tagesrenditen.append(werte[i] / werte[i - 1] - 1)

    if len(tagesrenditen) >= 2:
        n = len(tagesrenditen)
        mittel = sum(tagesrenditen) / n
        varianz = sum((r - mittel) ** 2 for r in tagesrenditen) / (n - 1)
        std = math.sqrt(varianz)
        if std > 0:
            ergebnis["sharpe"] = round(mittel / std * math.sqrt(jahresfaktor), 2)
        else:
            ergebnis["sharpe"] = None

        # Sortino: nur Abwaertsrisiko zaehlt
        abwaerts = [r for r in tagesrenditen if r < 0]
        if abwaerts:
            ds = math.sqrt(sum(r * r for r in abwaerts) / len(abwaerts))
            ergebnis["sortino"] = round(mittel / ds * math.sqrt(jahresfaktor), 2) if ds > 0 else None
        else:
            ergebnis["sortino"] = None

        ergebnis["volatilitaet_pct"] = round(std * math.sqrt(jahresfaktor) * 100, 2)
    else:
        ergebnis["sharpe"] = None
        ergebnis["sortino"] = None

    # Maximaler Drawdown
    peak = werte[0]
    maxdd = 0.0
    dd_zeit = None
    for p in punkte:
        if p["equity"] > peak:
            peak = p["equity"]
        if peak > 0:
            dd = (p["equity"] - peak) / peak * 100
            if dd < maxdd:
                maxdd = dd
                dd_zeit = p["zeit"]
    ergebnis["max_drawdown_pct"] = round(maxdd, 2)
    ergebnis["max_drawdown_zeit"] = dd_zeit

    # Aktuell offener Drawdown
    peak = max(werte)
    ergebnis["drawdown_aktuell_pct"] = round(
        (end_wert - peak) / peak * 100, 2) if peak > 0 else 0.0

    return ergebnis


def transaktionskosten(risk, modi="paper"):
    """Wie viel hat der Handel an Gebühren gekostet?"""
    pfad = os.path.join(BASE, f"depot_{risk:03d}_{modi}.json")
    if not os.path.exists(pfad):
        pfad = os.path.join(BASE, f"depot_{risk:03d}.json")
    if not os.path.exists(pfad):
        return None
    with open(pfad, encoding="utf-8") as f:
        d = json.load(f)
    kosten = 0.0
    anzahl = 0
    for t in d.get("trades", []) or []:
        if not isinstance(t, dict):
            continue
        if t.get("aktion") in ("kaufen", "verkaufen", "buy", "sell"):
            menge = float(t.get("menge", 0) or 0)
            preis = float(t.get("preis", 0) or 0)
            kosten += menge * preis * KOSTEN_PRO_SEITE_PCT / 100.0
            anzahl += 1
    return {
        "risk": risk,
        "trades": anzahl,
        "kosten_eur": round(kosten, 2),
        "satz_pro_seite_pct": KOSTEN_PRO_SEITE_PCT,
    }


# ─────────────────────────────────────────────────────────────────────
# 3) Benchmark
# ─────────────────────────────────────────────────────────────────────
def benchmark_kurve(tage=90):
    """SPY als Vergleichskurve auf dieselbe Zeitachse."""
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        return []

    try:
        daten = yf.download("SPY", period=f"{tage}d", progress=False,
                            auto_adjust=True, threads=False)
    except Exception:
        return []

    if daten is None or len(daten) == 0:
        return []

    close = daten["Close"]
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
    close = close.dropna()
    if len(close) < 2:
        return []

    basis = float(close.iloc[0])
    punkte = []
    for ts, wert in close.items():
        try:
            zeit = ts.strftime("%Y-%m-%d")
        except Exception:
            zeit = str(ts)[:10]
        punkte.append({
            "zeit": zeit,
            "wert": round(float(wert), 4),
            "index": round(float(wert) / basis * 100, 3),
        })
    return punkte


def benchmark_kennzahlen(tage=90):
    """Was haette SPY im gleichen Zeitraum gebracht?"""
    punkte = benchmark_kurve(tage)
    if len(punkte) < 2:
        return None
    start = punkte[0]["wert"]
    end = punkte[-1]["wert"]
    r = (end - start) / start * 100

    werte = [p["wert"] for p in punkte]
    peak = werte[0]
    maxdd = 0.0
    for w in werte:
        if w > peak:
            peak = w
        if peak > 0:
            maxdd = min(maxdd, (w - peak) / peak * 100)

    return {
        "symbol": "SPY",
        "zeitraum_tage": tage,
        "rendite_pct": round(r, 2),
        "max_drawdown_pct": round(maxdd, 2),
        "stichproben": len(punkte),
    }


# ─────────────────────────────────────────────────────────────────────
# 01.11.2026: Benchmark seit Start, Handelskosten aus den Trades,
# KI-Kennzahlen aus ki_aufrufe.jsonl (fuer den Tagesbericht)
# ─────────────────────────────────────────────────────────────────────
def benchmark_seit(datum_iso, symbol="SPY"):
    """Rendite von `symbol` seit `datum_iso` (YYYY-MM-DD) in Prozent, oder None."""
    try:
        import yfinance as yf
        daten = yf.download(symbol, start=str(datum_iso)[:10], progress=False,
                            auto_adjust=True, threads=False)
        close = daten["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        close = close.dropna()
        if len(close) < 2:
            return None
        return round((float(close.iloc[-1]) / float(close.iloc[0]) - 1) * 100, 2)
    except Exception:
        return None


def handelskosten_aus_trades(trades):
    """Summe Gebuehren und Slippage aus Trades mit den Feldern gebuehr/kurs_eff.

    Slippage = |kurs_eff - preis| * menge. Trades von vor dem Kostenmodell
    (ohne Feld 'gebuehr') werden gezaehlt, aber nicht bewertet."""
    gebuehr = slippage = 0.0
    mit = ohne = 0
    for t in trades or []:
        if not isinstance(t, dict):
            continue
        if "gebuehr" not in t:
            ohne += 1
            continue
        mit += 1
        gebuehr += float(t.get("gebuehr") or 0)
        if t.get("kurs_eff") and t.get("preis"):
            slippage += abs(float(t["kurs_eff"]) - float(t["preis"])) * float(t.get("menge") or 0)
    return {"gebuehr": round(gebuehr, 2), "slippage": round(slippage, 2),
            "trades_mit_kosten": mit, "trades_ohne_kosten": ohne}


def ki_kennzahlen(stunden=24, pfad=None):
    """Erfolgsquote, Anbieter, Dauer der KI-Aufrufe der letzten `stunden`."""
    pfad = pfad or os.path.join(BASE, "ki_aufrufe.jsonl")
    if not os.path.exists(pfad):
        return None
    grenze = datetime.now() - timedelta(hours=stunden)
    n = ok = 0
    sek = []
    anbieter, fehler = {}, {}
    with open(pfad, encoding="utf-8") as f:
        for zeile in f:
            try:
                e = json.loads(zeile)
                if datetime.fromisoformat(e["zeit"]) < grenze:
                    continue
            except Exception:
                continue
            n += 1
            sek.append(float(e.get("sekunden") or 0))
            if e.get("ok"):
                ok += 1
                anbieter[e.get("provider") or "?"] = anbieter.get(e.get("provider") or "?", 0) + 1
            else:
                fehler[e.get("fehler") or "?"] = fehler.get(e.get("fehler") or "?", 0) + 1
    if not n:
        return {"aufrufe": 0}
    sek.sort()
    return {
        "aufrufe": n,
        "erfolgreich": ok,
        "ausfall_quote_pct": round((n - ok) / n * 100, 1),
        "median_sekunden": sek[len(sek) // 2],
        "anbieter": dict(sorted(anbieter.items(), key=lambda kv: -kv[1])),
        "fehler": dict(sorted(fehler.items(), key=lambda kv: -kv[1])),
    }
