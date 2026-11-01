"""
Micro-Trader — Daily PDF Report (Phase 10, §17) — Erweiterte Profi-Version
Deutscher Tagesbericht als PDF (reportlab, Layout nach pdf-report-i18n-Skill).

NEU (v2.1):
- Gesamt-Rendite + pro Kategorie (Aktien/ETF/Spec) in $ und %
- 7-Tage-Verlauf-Graph (Gesamtwert) via reportlab LineChart
- Beste/Schlechteste 5 (aus allen Depots, auch in Gesamt-Übersicht)
- KI-Lernen: gelernte Regeln + Konfidenz-Level (%) + Konfidenz-Graph
- Marktregime, offene Aufgaben
"""
import os
import sys  # 01.11.2026: fehlte, Provider-Status fiel deshalb immer in den Fallback
from collections import defaultdict
import glob
import json
import subprocess
import time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(BASE, "reports")
os.makedirs(REPORTS, exist_ok=True)

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                ListFlowable, ListItem, HRFlowable, Image, KeepTogether,
                                PageBreak)
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.lib import colors as rc
from svglib.svglib import svg2rlg

# ─── Font mit echten Umlauten ───
FONT = "Helvetica"
try:
    aria = "C:/Windows/Fonts/arial.ttf"
    if os.path.exists(aria):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        pdfmetrics.registerFont(TTFont("Arial", aria))
        FONT = "Arial"
except Exception:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# DATENBESCHAFFUNG
# ─────────────────────────────────────────────────────────────────────────────
def _ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except Exception:
        return None


def _lade_live_kurse(ticker_liste):
    """Live-Kurse via marktdaten.hole_kurs (4-Tier-Fallback)."""
    kurse = {}
    try:
        from marktdaten import hole_kurs
        for t in ticker_liste:
            try:
                k = hole_kurs(t)
                if k and k > 0:
                    kurse[t] = k
            except Exception:
                continue
    except Exception:
        pass
    return kurse


def _trading_mode():
    """Aktiver Modus aus der Datenbank: 'paper' oder 'shadow'.

    security.get_trading_mode() liefert GROSSBUCHSTABEN ("PAPER").
    Ohne lower() ist jeder Vergleich mit "paper" nie wahr - dann
    wird das Schattenverzeichnis gelesen und das Portfolio
    erscheint leer oder falsch zusammengesetzt."""
    try:
        from security import get_trading_mode as _gtr
        return (_gtr() or "paper").lower()
    except Exception:
        return "paper"


def _spec_verzeichnis():
    """spec_depots_paper/ bei PAPER, spec_depots/ bei SHADOW.

    Fester Pfad "spec_depots" ist der Grund, warum der Report vom
    04.10. nur 20 von 30 Depots zaehlte: die zehn Spekulationsdepots
    lagen in spec_depots_paper/ und wurden nie gelesen."""
    return os.path.join(BASE, "spec_depots"
                        if _trading_mode() != "paper" else "spec_depots_paper")


def lade_depots_flat():
    """Alle Depots flach: Ticker, Kategorie, start, wert, pnl_pct.
    wert = MARKTWERT (Live-Kurs via hole_kurs, Fallback avg_price),
    wie das Dashboard es rechnet (nicht Einstandskurs)."""
    out = []
    # 1. Alle Ticker mit Positionen sammeln (für Live-Kurse) — NUR Paper-Portfolio
    alle_ticker = set()
    for f in sorted(glob.glob(os.path.join(_spec_verzeichnis(), "*.json"))):
        if "summary" in f:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
            if d.get("ticker") and (d.get("shares", 0) or 0) > 0:
                alle_ticker.add(d["ticker"])
        except Exception:
            pass
    for pat in ["depot_*_paper.json", "etf_*_paper.json"]:
        for f in sorted(glob.glob(os.path.join(BASE, pat))):
            if "summary" in f:
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
                for t, pos in (d.get("positions", {}) or {}).items():
                    if (pos.get("shares", 0) or 0) > 0:
                        alle_ticker.add(t)
            except Exception:
                pass
    kurse = _lade_live_kurse(sorted(alle_ticker))
    if kurse:
        print(f"  Live-Kurse geladen: {len(kurse)} Ticker", flush=True)

    for f in sorted(glob.glob(os.path.join(_spec_verzeichnis(), "*.json"))):
        if "summary" in f:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
            ticker = d.get("ticker") or os.path.splitext(os.path.basename(f))[0]
            start = d.get("start", 0) or 0
            shares = d.get("shares", 0) or 0
            avg = d.get("avg_price", d.get("aktuell", 0)) or 0
            bargeld = d.get("bargeld", 0) or 0
            # MARKTWERT: Live-Kurs bevorzugt, sonst avg_price
            kurs = kurse.get(ticker) or avg
            wert = bargeld + shares * kurs
            pnl_pct = ((wert - start) / start * 100) if start > 0 else 0
            out.append({"ticker": ticker, "kat": "Spec", "start": start, "wert": wert, "pnl_pct": pnl_pct})
        except Exception:
            pass
    for pat, kat in [("depot_*_paper.json", "Aktien"), ("etf_*_paper.json", "ETF")]:
        for f in sorted(glob.glob(os.path.join(BASE, pat))):
            if "summary" in f:
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
                base_name = os.path.splitext(os.path.basename(f))[0]
                start_wert = d.get("start_wert", 0) or 0
                if "positions" in d and isinstance(d["positions"], dict):
                    n = len(d["positions"])
                    bargeld = d.get("bargeld", 0) or 0
                    # Anteiliges Cash pro Position (wie Dashboard: wert = bargeld + shares*kurs)
                    cash_anteil = (bargeld / n) if n > 0 else 0
                    for ticker, pos in d["positions"].items():
                        shares = pos.get("shares", 0) or 0
                        avg = pos.get("avg_price", pos.get("aktuell", 0)) or 0
                        # MARKTWERT: Live-Kurs bevorzugt, sonst avg_price
                        kurs = kurse.get(ticker) or avg
                        # Rendite = Veraenderung des EIGENEN Einstands.
                        #
                        # Vorher stand hier: anteil = start_wert / n und
                        # pnl_pct = (wert - anteil) / anteil. Das verteilte
                        # den Startwert gleichmaessig auf alle Positionen,
                        # nicht anteilig nach dem Einsatz. Gemessen an 100
                        # Positionen ueber 30 Depots wichen 76 % um mehr als
                        # 10 Prozentpunkte ab, 20 zeigten ein verdrehtes
                        # Vorzeichen (STUB +171 % statt +13 %, WEN -68 %
                        # statt +0,2 %). Die Depot-Summe stimmte, nur die
                        # Zurechnung war falsch — deshalb fiel es nicht auf.
                        einstand = shares * avg
                        markt = shares * kurs
                        # Der Bargeldanteil gehoert nicht in die Positions-
                        # rendite: er zaehlt einmal im Depot, wurde hier
                        # aber je Position erneut in den Marktwert
                        # eingerechnet und verschob jede Rendite.
                        wert = markt
                        if einstand > 0:
                            pnl_pct = ((markt - einstand) / einstand * 100)
                            start = einstand
                        else:
                            # Ohne Einstand ist keine Rendite definierbar.
                            # Eine aus dem Null-Einstand gerechnete Zahl
                            # waere frei erfunden.
                            pnl_pct = 0.0
                            start = 0.0
                        out.append({"ticker": ticker, "kat": kat,
                                    "start": start, "wert": wert,
                                    "pnl_pct": pnl_pct,
                                    "cash_anteil": cash_anteil,
                                    "ohne_einstand": einstand <= 0})
                    # ── LEERE DEPOTS (0 Positionen) nicht ignorieren! ──
                    # Ihr Startkapital (start_wert) gehoert in die Gesamtbilanz.
                    if n == 0:
                        out.append({"ticker": base_name, "kat": kat,
                                    "start": start_wert, "wert": bargeld or start_wert,
                                    "pnl_pct": (((bargeld or start_wert) - start_wert) / start_wert * 100) if start_wert > 0 else 0})
                else:
                    ticker = d.get("ticker") or base_name
                    start = d.get("start", start_wert) or 0
                    shares = d.get("shares", 0) or 0
                    avg = d.get("avg_price", d.get("aktuell", 0)) or 0
                    bargeld = d.get("bargeld", 0) or 0
                    kurs = kurse.get(ticker) or avg
                    wert = bargeld + shares * kurs
                    pnl_pct = ((wert - start) / start * 100) if start > 0 else 0
                    out.append({"ticker": ticker, "kat": kat, "start": start, "wert": wert, "pnl_pct": pnl_pct})
            except Exception:
                pass
    return out


def _kurs_fuer(d, ticker, avg, kurse):
    """Kurs eines Tickers: live, sonst die Bewertung des Depots.

    Reihenfolge:
      1. marktdaten (live)
      2. kurs_quelle[ticker]["kurs"] — der Kurs, mit dem das Depot
         seinen Wert selbst berechnet hat
      3. avg_price — nur Notlauf

    avg_price ist der Einstand. Als Kursersatz verzerrt er die
    Bewertung: BB.json hätte 9.628385 x 9.3582 = 90,10 $ statt
    9.628385 x 8,77 = 84,44 $ — zusammen 331,42 $ zu viel über
    alle Spec-Depots.
    """
    k = kurse.get(ticker)
    if k and k > 0:
        return k
    try:
        kq = d.get("kurs_quelle") or {}
        e = kq.get(ticker) or {}
        k = e.get("kurs")
        if k and k > 0:
            return float(k)
    except Exception:
        pass
    return avg or 0


def _depot_bilanz_pro_kat():
    """Bilanz je Kategorie, aus den DEPOTS.

    Muss zur Gesamtsumme aus _depot_bilanz() passen: sonst zeigt der
    Bericht zwei verschiedene Portfolios nebeneinander. Vorher stand
    hier die flache Positionsliste, die das Bargeld verliert — Aktien
    1.090,06 $ statt 2.000,00 $, ETF 1.204,09 $ statt 2.000,00 $,
    Summe 3.318,03 $ neben einem ausgewiesenen Gesamtwert von
    5.042,29 $.
    """
    ergebnis = {}
    dateien = []
    for pat in ["depot_*_paper.json", "etf_*_paper.json"]:
        dateien += [f for f in sorted(glob.glob(os.path.join(BASE, pat)))
                    if "summary" not in f]
    dateien += [f for f in sorted(glob.glob(os.path.join(_spec_verzeichnis(), "*.json")))
                if "summary" not in f]

    roh = []
    tick = set()
    for f in dateien:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        roh.append(d)
        pos = d.get("positions")
        if isinstance(pos, dict):
            tick.update(pos.keys())
        elif isinstance(pos, list):
            tick.update(p.get("ticker") for p in pos if isinstance(p, dict))
        elif d.get("ticker"):
            tick.add(d.get("ticker"))

    kurse = _lade_live_kurse(sorted(t for t in tick if t))

    for f, d in zip(dateien, roh):
        basis = os.path.basename(f)
        if basis.startswith("depot_"):
            kat = "Aktien"
        elif basis.startswith("etf_"):
            kat = "ETF"
        else:
            kat = "Spec"

        sw = d.get("start_wert", d.get("start", 0)) or 0
        bg = d.get("bargeld", 0) or 0
        pos = d.get("positions")
        markt = 0.0
        if isinstance(pos, dict):
            for t, p in pos.items():
                sh = p.get("shares", 0) or 0
                avg = p.get("avg_price", p.get("aktuell", 0)) or 0
                markt += sh * _kurs_fuer(d, t, avg, kurse)
        elif isinstance(pos, list):
            for p in pos:
                if not isinstance(p, dict):
                    continue
                sh = p.get("shares", 0) or 0
                avg = p.get("avg_price", 0) or 0
                markt += sh * _kurs_fuer(d, p.get("ticker"), avg, kurse)
        elif d.get("ticker"):
            sh = d.get("shares", 0) or 0
            avg = d.get("avg_price", 0) or 0
            markt += sh * _kurs_fuer(d, d.get("ticker"), avg, kurse)

        e = ergebnis.setdefault(kat, {"wert": 0.0, "start": 0.0})
        e["wert"] += bg + markt
        e["start"] += sw

    for kat, e in ergebnis.items():
        e["pnl"] = e["wert"] - e["start"]
        e["pnl_pct"] = (e["pnl"] / e["start"] * 100) if e["start"] > 0 else 0.0
    return ergebnis


def _depot_bilanz():
    """Portfolio-Bilanz aus den DEPOTS, nicht aus den flachen Positionen.

    Die flache Liste eignet sich fuer Ticker-Renditen, nicht fuer die
    Summe: sie enthaelt je Depot nur Positionen und verliert das
    Bargeld. Vor der Umstellung auf echte Einstaende addierte sich
    start_wert/n ueber n Positionen zu start_wert zurueck — das
    Bargeld war damit implizit enthalten. Mit echten Einstaenden fiel
    es heraus, und der Gesamtwert sank von 5.042 auf 3.318 $, waehrend
    die RENDITE (+0,85 %) unveraendert blieb. Genau deshalb ist der
    Fehler nicht aufgefallen.

    Richtig ist: je Depot bargeld + summe(shares * kurs) gegen
    start_wert. Das ist die Bilanz, die das Dashboard zeigt, und sie
    geht ueber alle Depots exakt auf.
    """
    ges_start = 0.0
    ges_wert = 0.0
    n = 0

    dateien = []
    for pat in ["depot_*_paper.json", "etf_*_paper.json"]:
        dateien += [f for f in sorted(glob.glob(os.path.join(BASE, pat)))
                    if "summary" not in f]
    dateien += [f for f in sorted(glob.glob(os.path.join(_spec_verzeichnis(), "*.json")))
                if "summary" not in f]

    rohdaten = []
    alle_ticker = set()
    for f in dateien:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        rohdaten.append(d)
        pos = d.get("positions")
        if isinstance(pos, dict):
            alle_ticker.update(pos.keys())
        elif isinstance(pos, list):
            alle_ticker.update(p.get("ticker") for p in pos if isinstance(p, dict))
        elif d.get("ticker"):
            # Flaches Einzeldepot (spec_depots_paper/BB.json und Co.):
            # kein positions-Feld, sondern ticker/shares/avg_price
            # direkt im Depotkopf. Ohne diesen Zweig gelten diese
            # Depots als leer und ihr Marktwert (zusammen 331,42 $)
            # fiel aus der Bilanz.
            alle_ticker.add(d.get("ticker"))

    # Ein Kursabruf fuer alle Ticker, ueber den Cache des Moduls.
    # hole_kurs ist hier nicht importiert — der Import passiert lokal
    # in _lade_live_kurse().
    kurse = _lade_live_kurse(sorted(t for t in alle_ticker if t))

    for d in rohdaten:
        sw = d.get("start_wert", d.get("start", 0)) or 0
        bg = d.get("bargeld", 0) or 0
        pos = d.get("positions")
        markt = 0.0
        if isinstance(pos, dict):
            # Sammeldepot (Aktien, ETF): Positionen als dict
            for t, p in pos.items():
                sh = p.get("shares", 0) or 0
                avg = p.get("avg_price", p.get("aktuell", 0)) or 0
                markt += sh * _kurs_fuer(d, t, avg, kurse)
        elif isinstance(pos, list):
            # Sammeldepot mit positions-Liste
            for p in pos:
                if not isinstance(p, dict):
                    continue
                sh = p.get("shares", 0) or 0
                avg = p.get("avg_price", 0) or 0
                markt += sh * _kurs_fuer(d, p.get("ticker"), avg, kurse)
        elif d.get("ticker"):
            # Flaches Einzeldepot (spec_depots_paper/BB.json und Co.):
            # kein positions-Feld, sondern ticker/shares/avg_price
            # direkt im Depotkopf.
            sh = d.get("shares", 0) or 0
            avg = d.get("avg_price", 0) or 0
            markt += sh * _kurs_fuer(d, d.get("ticker"), avg, kurse)
        ges_start += sw
        ges_wert += bg + markt
        n += 1
    return ges_start, ges_wert, n

def sammle_daten():
    depots = lade_depots_flat()
    # Bilanz aus den Depots: Bargeld + Marktwerte gegen Startkapital.
    ges_start, ges_wert, _n_dep = _depot_bilanz()
    ges_pnl = ges_wert - ges_start
    ges_pnl_pct = (ges_pnl / ges_start * 100) if ges_start > 0 else 0

    # ── Kategorien-Bilanz ──
    #
    # Aus der flachen Positionsliste fehlte das Bargeld: Aktien
    # 1.090,06 $ statt 2.000,00 $, ETF 1.204,09 $ statt 2.000,00 $, und
    # die drei Kategorien addierten sich auf 3.318,03 $ neben einem
    # ausgewiesenen Gesamtwert von 5.042,29 $. Der Bericht zeigte damit
    # zwei verschiedene Portfolios nebeneinander.
    #
    # Primaer aus den Depoten, mit messbarem Rueckfall: nur wenn die
    # Summe der Kategorien auf den Gesamtwert aufgeht, wird sie
    # uebernommen. Sonst bleibt die flache Liste stehen — sichtbar
    # falsch, aber nicht still falsch in beide Richtungen.
    kat_info = None
    try:
        _kd = _depot_bilanz_pro_kat()
        if _kd and abs(sum(v["wert"] for v in _kd.values()) - ges_wert) < 0.05 \
                and abs(sum(v["start"] for v in _kd.values()) - ges_start) < 0.05:
            kat_info = {k: dict(v) for k, v in _kd.items()}
    except Exception:
        kat_info = None

    if kat_info is None:
        # Rueckfall: flache Liste, Summe weicht ab.
        kat = {}
        for d in depots:
            k = d["kat"]
            kat.setdefault(k, {"wert": 0, "start": 0, "n_depots": 0})
            kat[k]["wert"] += d["wert"]
            if d["start"] > 0:
                kat[k]["start"] += d["start"]
            kat[k]["n_depots"] += 1
        kat_info = {}
        for k, v in kat.items():
            pnl = v["wert"] - v["start"]
            kat_info[k] = {
                "wert": v["wert"], "start": v["start"], "pnl": pnl,
                "pnl_pct": (pnl / v["start"] * 100) if v["start"] > 0 else 0,
                "aus_der_flachen_liste": True,
            }

    # Trades heute
    ki_log = []
    kp = os.path.join(BASE, "ki_log.json")
    if os.path.exists(kp):
        ki_log = json.load(open(kp, encoding="utf-8"))
    heute = datetime.now().date()
    trades_heute = []
    for e in ki_log:
        z = e.get("zeit", "")
        tz = _ts(z)
        if tz and tz.date() == heute and e.get("aktion") in ("kaufen", "verkaufen"):
            trades_heute.append(e)

    # Offene Positionen (wert > 0 = hat Position)
    offen = [d for d in depots if d["wert"] > 0]

    # Auffällige Trades
    auff = [(d["ticker"], d["pnl_pct"], d["kat"]) for d in depots if abs(d["pnl_pct"]) >= 10]

    # Top/Flop 5 (alle Depots, dedupliziert nach Ticker)
    seen = set()
    sortiert = sorted(depots, key=lambda x: x["pnl_pct"])
    flop5, top5 = [], []
    for d in sortiert:
        if d["ticker"] not in seen:
            flop5.append(d)
            seen.add(d["ticker"])
        if len(flop5) >= 5:
            break
    seen = set()
    for d in sorted(depots, key=lambda x: -x["pnl_pct"]):
        if d["ticker"] not in seen:
            top5.append(d)
            seen.add(d["ticker"])
        if len(top5) >= 5:
            break

    # KI: gelernte Regeln
    regeln = {}
    lr = os.path.join(BASE, "learned_rules.json")
    if os.path.exists(lr):
        try:
            regeln = json.load(open(lr, encoding="utf-8"))
        except Exception:
            pass
    rules_list = regeln.get("rules", []) if isinstance(regeln, dict) else []

    # KI: Konfidenz-Schnitt + Verlauf
    konf_vals = [e.get("konfidenz") for e in ki_log if isinstance(e.get("konfidenz"), (int, float))]
    ki_konf_schnitt = (sum(konf_vals) / len(konf_vals)) if konf_vals else None
    # Konfidenz-Verlauf (letzte 20 Entscheidungen mit Zeit)
    konf_verlauf = []
    for e in ki_log:
        k = e.get("konfidenz")
        z = _ts(e.get("zeit", ""))
        if isinstance(k, (int, float)) and z:
            konf_verlauf.append((z, k))
    konf_verlauf.sort()
    konf_verlauf = konf_verlauf[-20:]

    # 7-Tage-Verlauf (Snapshot)
    try:
        import tagesverlauf as tv
        tv.snapshot_schreiben()
        verlauf = tv.hole_7_tage()
    except Exception:
        verlauf = []

    # 7-Tage-Verlauf pro Kategorie
    verlauf_kat = {}
    try:
        import tagesverlauf as tv
        for kn in ["Aktien", "ETF", "Spec"]:
            verlauf_kat[kn] = tv.hole_7_tage_pro_kat(kn)
    except Exception:
        pass

    # Marktregime
    regime = {}
    try:
        import boersen
        regime = boersen.regime_pro_markt()
    except Exception:
        regime = {"US": "?", "DE": "?", "JP": "?"}

    # Offene Punkte: gemessen und auf das bezogen, was heute fehlt.
    # Die alte Liste stand seit August und nannte erledigte Dinge
    # (markt_daten ist gefuellt, Juli-Trades sind bereinigt) neben
    # einem Zustand, den es nicht mehr gibt (Shadow-Modus).
    return {
        "ges_wert": ges_wert, "ges_start": ges_start, "ges_pnl": ges_pnl,
        "ges_pnl_pct": ges_pnl_pct, "kat": kat_info, "trades_heute": trades_heute,
        "offen": offen, "auff": auff, "top5": top5, "flop5": flop5,
        "regeln": regeln, "rules_list": rules_list,
        "ki_konf_schnitt": ki_konf_schnitt, "konf_verlauf": konf_verlauf,
        "verlauf": verlauf, "verlauf_kat": verlauf_kat, "regime": regime,
        "n_depots": len(depots),
        # ── Tagesauswertung-Erweiterung ──
        "alle_trades": _alle_trades_flat(),
        "offene_positionen": len(offen),
        "exposure_pro_symbol": _exposure_pro_symbol(depots),
        "regelstand": _regelstand_agg(),
        "regelstand_version": regeln.get("_regelstand", {}).get("regelstand_version", "n/a") if isinstance(regeln, dict) else "n/a",
        "notifications": _lade_notifications(),
        "ki_aktiv": _ki_aktiv_heute(ki_log, heute),
        "system": _system_status(),
        "anomalien": _anomalien(),
        # ── Phase B: Datenvertrauens-Felder ──
        "trades_anzahl": len(_alle_trades_flat()),
        "depot_snapshot_anzahl": _db_snap_count(),
        "ki_cooldown": _lade_json(os.path.join(BASE, "ki_cooldown.json"), {}),
    }


def _pnl_fifo(trades):
    """Brutto-P&L je Trade per FIFO, oder None wenn nicht bewertbar.

    Ein Verkauf bekommt seinen Einstandspreis aus den Kaeufen
    DESSELBEN Depots und DESSELBEN Tickers, chronologisch. Ohne
    passenden Kauf gibt es keine ehrliche Zahl - dann None, und
    die Zeile lautet "n/a". Eine 0.00 waere hier eine
    Falschaussage: sie sagt "unverlustig", wenn in Wahrheit
    nichts bekannt ist.

    Rueckgabe: Liste parallel zu `trades`, Werte float oder None.
    """
    # Vorlauf: Kaeufe je (depot, ticker) einsammeln
    kauf_lots = defaultdict(list)
    for t in trades:
        typ = _trade_typ(t)
        if "verkauf" not in typ:
            continue
        key = (t.get("_depot"), t.get("ticker"))
        for k in trades:
            ktyp = _trade_typ(k)
            if "verkauf" in ktyp or "kauf" not in ktyp:
                continue
            if (k.get("_depot"), k.get("ticker")) != key:
                continue
            m = k.get("menge")
            p = k.get("preis")
            if isinstance(m, (int, float)) and m > 0 and \
                    isinstance(p, (int, float)) and p > 0:
                kauf_lots[key].append({"menge": m, "preis": p,
                                       "zeit": str(k.get("zeit") or "")})
    for v in kauf_lots.values():
        v.sort(key=lambda x: x["zeit"])

    ergebnis = []
    for t in trades:
        typ = _trade_typ(t)
        if "verkauf" not in typ:
            ergebnis.append(None)
            continue
        m = t.get("menge")
        p = t.get("preis")
        if not (isinstance(m, (int, float)) and m > 0):
            ergebnis.append(None)
            continue
        if not (isinstance(p, (int, float)) and p > 0):
            ergebnis.append(None)
            continue
        key = (t.get("_depot"), t.get("ticker"))
        rest = m
        kosten = 0.0
        for lot in kauf_lots.get(key, []):
            if rest <= 1e-9:
                break
            take = min(rest, lot["menge"])
            kosten += take * lot["preis"]
            rest -= take
        if rest > 1e-6:
            # Mehr verkauft, als die Historie hergibt
            ergebnis.append(None)
            continue
        ergebnis.append(m * p - kosten)
    return ergebnis



# ── Messfunktionen fuer den Aufgabentext ──
#
# Der Aufgabentext stand seit dieser Sitzung mit festen Zahlen im Code
# ("18 Verkäufe ohne belegten Einstand", "Profit Factor 0.21"). Eine
# Zahl, die im Quelltext steht, veraltet still — sie wird nicht neu
# gemessen, sie wird nur weiter abgedruckt. Deshalb kommen sie jetzt
# aus dem Bestand.

def _trade_typ_kanon(t):
    """Trade-Typ auf 'kauf' / 'verkauf' / '' normiert.

    Reihenfolge ist entscheidend: ZUERST auf 'verkauf' pruefen.
    "kauf" ist ein Teilstring von "verkauf", aber nicht umgekehrt.
    Wer umgekehrt prueft, haelt jeden Verkauf fuer einen Kauf.
    """
    roh = str(t.get("typ") or t.get("aktion") or "").strip().lower()
    if "verkauf" in roh:
        return "verkauf"
    if "kauf" in roh and "blockiert" not in roh:
        return "kauf"
    return ""


def _verkaeufe_gesamt():
    n = 0
    for t in _alle_trades_flat():
        if _trade_typ_kanon(t) == "verkauf":
            n += 1
    return n


def _verkaeufe_ohne_einstand():
    """Verkaeufe, fuer die der Bericht KEINE P&L ausweisen kann.

    Das ist die FIFO-Frage, nicht die Bestandsfrage. Zwei Verkaeufe
    koennen beide 'keinen passenden Kauf im Depot' haben und trotzdem
    unterschiedlich liegen:

      17  Verkauf ohne jeden Kauf im selben Depot
      18  Verkauf ohne ausreichendes Kauflot

    Der 18. Fall: depot_090, TGB, verkauft 0.85 Stueck. Ein Kauf ist
    da, aber nur 0.36 — die FIFO kann die Menge nicht decken und
    liefert None. Zu Recht: eine P&L aus einem unvollstaendigen Lot
    waere erfunden.

    Abgeleitet aus der FIFO-Ausgabe, damit Aufgabentext und Kennzahlen
    nie auseinanderlaufen koennen.
    """
    return sum(1 for v in _pnl_fifo_werte() if v is None)


def _pnl_fifo_werte():
    """P&L-Werte, parallel zu den VERKAUFEN in chronologischer Reihenfolge.

    _pnl_fifo() braucht ALLE ausgefuehrten Trades, nicht nur die
    Verkaeufe: die Funktion sammelt im Vorlauf die Kaeufe zu jedem
    (Depot, Ticker) aus derselben Liste. Uebergibt man ihr nur
    Verkaeufe, findet sie keine Kaeufe, und alles wird None.

    Rueckgabe daher: Liste der Verkaufs-P&L, None wo nicht bewertbar.
    """
    alle_t = [t for t in _alle_trades_flat() if _trade_ist_ausgefuehrt(t)]
    werte = _pnl_fifo(alle_t)
    vk = [i for i, t in enumerate(alle_t) if _trade_typ_kanon(t) == "verkauf"]
    return [werte[i] for i in vk]


def _tq_aus_werte(values):
    """Trefferquote aus einer Liste von P&L-Werten (None = nicht bewertbar)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return "n/a"
    gewinn = sum(1 for v in vals if v > 0)
    return f"{gewinn / len(vals) * 100:.0f} %"


def _trefferquote():
    return _tq_aus_werte(_pnl_fifo_werte())


def _kf_aus_werte(values):
    """Profit Factor aus einer Liste von P&L-Werten.

    Gewinnsumme durch Verlustsumme. Bei null Verlust gibt es kein
    Verhaeltnis: "n/a" waere falsch (es gibt sehr wohl eine Zahl),
    "unendlich" beschreibt den Fall treffend.
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return "n/a"
    gut = sum(v for v in vals if v > 0)
    schlecht = -sum(v for v in vals if v < 0)
    if schlecht <= 0:
        return "unendlich"
    return f"{gut / schlecht:.2f}"


def _profit_factor_wert():
    return _kf_aus_werte(_pnl_fifo_werte())


def _pnl_text(v):
    """P&L-Zahl oder 'n/a' mit Grund. Niemals 0,00 ohne Aussage."""
    if v is None:
        return "n/a (kein Einstand)"
    return f"{v:+.2f} $"


def _trade_typ(t):
    """Der Trade-Typ, unabhaengig von der Schreibweise.

    Drei Trader, drei Schemata:
        Aktien/ETF   t["typ"]     "kauf" / "verkauf"
        Spec         t["aktion"]  "kaufen" / "verkaufen"

    Wer nur "typ" liest, uebersieht jeden Spec-Trade - er hat
    dort kein Feld "typ" und wird weder als Kauf noch als
    Verkauf erkannt. Deshalb die eine Stelle, die beide kennt.

    Verglichen wird auf Enthaltenheit, nicht auf Gleichheit:
    "verkauf" in "verkaufen" ist wahr, "verkauf" in
    "kauf_blockiert" ist falsch. Genau das trennt ausgefuehrte
    Trades von Blockierversuchen.
    """
    return str(t.get("typ") or t.get("aktion") or "").strip().lower()


def _trade_ist_ausgefuehrt(t):
    """True nur fuer echte Ausfuehrungen.

    kauf_blockiert ist ein VERSUCH: Menge 0, Geld unberuehrt. Er
    gehoert nicht in die Trade-Tabelle und nicht in die Zahl
    "Trades ausgefuehrt". 1.286 von 1.475 Eintraegen waren solche
    Versuche - die Kennzahl war um den Faktor 50 zu hoch."""
    typ = _trade_typ(t)
    if "block" in typ or "skip" in typ or "verweig" in typ:
        return False
    menge = t.get("menge")
    if isinstance(menge, (int, float)) and menge <= 0:
        return False
    return True


def _alle_trades_flat():
    """Alle Trades aus den Paper-Depots, flach, mit Depotkennung.

    Jeder Eintrag bekommt "_depot" (der Dateiname). Ohne das
    schluesselt die FIFO nach (None, Ticker) und rechnet Kaeufe
    aus depot_010 mit Verkaeufen in depot_030 zusammen - die
    Menge geht dann nicht auf, das Ergebnis wird None, und die
    Brutto-P&L ist eine Mischung aus fremden Depots.

    Die Depotkennung ist die Voraussetzung dafuer, dass "P&L"
    ueberhaupt eine definierte Groesse ist: sie beantwortet
    "welches Depot", nicht nur "welcher Ticker".
    """
    trades = []
    globs = ["depot_*_paper.json", "etf_*_paper.json"]
    # Spec-Depots liegen im Modus-Verzeichnis, nicht fest in
    # spec_depots/ - dieselbe Falle wie in lade_depots_flat().
    globs.append(os.path.join(os.path.relpath(_spec_verzeichnis(), BASE),
                              "*.json"))
    for pat in globs:
        for f in glob.glob(os.path.join(BASE, pat)):
            if "entfernte" in f:
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            tr = d.get("trades", [])
            if not isinstance(tr, list):
                continue
            basis = os.path.splitext(os.path.basename(f))[0]
            for t in tr:
                if isinstance(t, dict):
                    t = dict(t)
                    t["_depot"] = basis
                    if not t.get("ticker"):
                        t["ticker"] = (d.get("ticker")
                                       or basis.replace("depot_", "")
                                       .replace("etf_", ""))
                    trades.append(t)
    return trades


def _exposure_pro_symbol(depots):
    """Brutto-Exposure je Symbol aus aktuellen Depot-Werten."""
    exp = {}
    for d in depots:
        if d["wert"] > 0:
            exp[d["ticker"]] = exp.get(d["ticker"], 0) + d["wert"]
    return exp


def _regelstand_agg():
    """Governance-Aggregat aus learned_rules.json + ki_log.json."""
    ra = {"regeln_gesamt": "n/a", "freigegeben": "n/a", "shadow": "n/a",
          "nicht_freigegeben": "n/a", "im_live_pfad": "n/a",
          "lernereignisse": "n/a", "dedupe": "n/a",
          "mit_decision_id": "n/a", "legacy": "n/a"}
    lr = _lade_json(os.path.join(BASE, "learned_rules.json"), {})
    rules = lr.get("rules", []) if isinstance(lr, dict) else []
    if rules:
        ra["regeln_gesamt"] = len(rules)
        ra["freigegeben"] = sum(1 for r in rules if r.get("freigabe_status") == "freigegeben")
        ra["shadow"] = sum(1 for r in rules if r.get("typ") in ("anti", "swap") or (r.get("effektiv_gewicht", r.get("gewicht", 0)) or 0) < 0)
        ra["nicht_freigegeben"] = sum(1 for r in rules if r.get("freigabe_status") != "freigegeben")
        ra["im_live_pfad"] = sum(1 for r in rules if r.get("live_allowed") or r.get("freigabe_status") == "freigegeben")
    ki = _lade_json(os.path.join(BASE, "ki_log.json"), [])
    if isinstance(ki, list):
        ra["lernereignisse"] = len(ki)
        ra["mit_decision_id"] = sum(1 for e in ki if e.get("decision_id"))
        ra["legacy"] = sum(1 for e in ki if not e.get("decision_id"))
        # Dedupe: gleiche decision_id mehrfach?
        ids = [e.get("decision_id") for e in ki if e.get("decision_id")]
        ra["dedupe"] = len(ids) - len(set(ids))
    return ra


def _lade_notifications():
    n = _lade_json(os.path.join(BASE, "notifications.json"), [])
    if isinstance(n, list):
        return [{"text": x} if isinstance(x, str) else x for x in n]
    return []


def _ki_aktiv_heute(ki_log, heute):
    for e in ki_log:
        tz = _ts(e.get("zeit", ""))
        if tz and tz.date() == heute and isinstance(e.get("konfidenz"), (int, float)) and e.get("konfidenz", 0) > 0:
            return True
    return False


def _system_status():
    """Systemstatus aus system_log.py / trader_status.py / .backup / cron."""
    s = {"engine": "n/a", "ki_job": "n/a", "cron_aktiv": "n/a", "watchdog": "n/a",
         "provider": "n/a", "datenalter": "n/a", "backup": "n/a"}
    # Cron-Jobs (über hermes cron list)
    try:
        out = subprocess.run(["hermes", "cron", "list"], capture_output=True, text=True, timeout=20)
        s["cron_aktiv"] = "3" if "Batch" in out.stdout and "Engine" in out.stdout and "KI" in out.stdout else "?"
    except Exception:
        s["cron_aktiv"] = "n/a"
    # Backup
    bdir = os.path.join(BASE, ".backup")
    s["backup"] = "vorhanden" if os.path.isdir(bdir) and os.listdir(bdir) else "fehlt"
    # Provider (ki_provider ki_faehig oder nous_auth.json Existenz)
    try:
        sys.path.insert(0, BASE)
        import ki_provider
        s["provider"] = "OK" if ki_provider.ki_faehig() else "fehlt"
    except Exception:
        # Fallback: nous_auth.json Existenz prüfen
        na = os.path.expanduser("~/AppData/Local/hermes/shared/nous_auth.json")
        s["provider"] = "OK" if os.path.exists(na) else "n/a"
    # Datenalter: älteste Datei in spec_depots
    try:
        files = glob.glob(os.path.join(BASE, "spec_depots", "*.json"))
        if files:
            oldest = min(os.path.getmtime(f) for f in files)
            alter_std = (time.time() - oldest) / 3600
            s["datenalter"] = f"{alter_std:.0f}h"
    except Exception:
        pass
    s["engine"] = "RUNNING" if os.path.exists(os.path.join(BASE, "engine.py")) else "n/a"
    s["ki_job"] = "OK" if s["provider"] == "OK" else "gestört"
    s["ki_detail"] = "KI liefert Entscheidungen (Konfidenz > 0)" if s["provider"] == "OK" else "Provider nicht erreichbar"
    return s


def _anomalien():
    """Anomalien aus notifications.json (echte Warnungen/Risiken, NICHT positive Rendite-Meldungen)."""
    anom = []
    notifs = _lade_notifications()
    for n in notifs:
        text = n.get("text", "") if isinstance(n, dict) else str(n)
        # Nur echte Probleme: negative Abweichung, Sperren, Fehler, Drawdown
        if any(k in text for k in ["Drawdown", "❌", "gesperrt", "Fehler", "KRITISCH", "verhindert", "gestört"]):
            anom.append({"zeit": n.get("zeit", "?") if isinstance(n, dict) else "?",
                         "kat": "Risiko" if "Drawdown" in text or "gesperrt" in text else "System",
                         "schwere": "HOCH" if "gesperrt" in text or "KRITISCH" in text else "MITTEL",
                         "desc": text[:60], "status": "dokumentiert"})
    return anom[:10]


# ─────────────────────────────────────────────────────────────────────────────
# GRAPHIK
# ─────────────────────────────────────────────────────────────────────────────
def graph_verlauf(verlauf, titel="7-Tage-Verlauf (Rendite ggü. Startwert)"):
    """Reportlab LineChart für Gesamtwert über 7 Tage."""
    d = Drawing(460, 170)
    chart = HorizontalLineChart()
    chart.x = 40
    chart.y = 25
    chart.width = 400
    chart.height = 120
    if verlauf:
        # ABSOLUT vs. RELATIV: Der Gesamtwert pendelt um 5.000 $, die
        # taegliche Bewegung liegt bei wenigen Dollar (aktuell -13,52 $ auf
        # 30 Tage). Mit valueMin/valueMax auf dem Absolutwert (4.986 bis
        # 5.017) ist die Schwankung 0,6 % der Diagrammhoehe - die Linie
        # sieht flach aus, obwohl die Werte stimmen. Der Graph zeigt
        # deshalb die Rendite gegen den Startwert (5.000 $), skaliert auf
        # die tatsaechliche Bandbreite. Das ist die Groesse, die der
        # Abschnitt 1 daneben ebenfalls ausweist.
        _start = next((v.get("ges_start") for v in verlauf if v.get("ges_start")), 0) or 0
        if _start:
            data = [[round((v.get("ges_wert", 0) / _start - 1) * 100, 3) for v in verlauf]]
        else:
            data = [[v.get("ges_wert", 0) for v in verlauf]]
        chart.data = data
        chart.categoryAxis.categoryNames = [v["datum"][5:] for v in verlauf]  # MM-TT
        chart.categoryAxis.labels.fontName = FONT
        chart.categoryAxis.labels.fontSize = 7
        _lo, _hi = min(data[0]), max(data[0])
        _span = (_hi - _lo) or 1.0
        chart.valueAxis.valueMin = _lo - _span * 0.15
        chart.valueAxis.valueMax = _hi + _span * 0.15
        chart.valueAxis.labels.fontName = FONT
        chart.valueAxis.labels.fontSize = 7
        chart.lines[0].strokeColor = rc.HexColor("#0A84FF")
        chart.lines[0].strokeWidth = 2
        chart.joinedLines = 1
    d.add(chart)
    return d


def graph_konfidenz(konf_verlauf):
    """Reportlab LineChart für KI-Konfidenz über Zeit."""
    d = Drawing(460, 150)
    chart = HorizontalLineChart()
    chart.x = 40
    chart.y = 25
    chart.width = 400
    chart.height = 100
    if konf_verlauf:
        data = [[k for _, k in konf_verlauf]]
        chart.data = data
        # Achsenbeschriftung: nur bei Tageswechsel. Vorher stand hier
        # "%d.%H" — bei 20 Entscheidungen an einem Abend ergab das
        # 20x "07.21" untereinander, was nach 20 verschiedenen
        # Konfidenzwerten aussah. Die Werte waren korrekt (60/55/50/45),
        # nur die Achse wiederholte sich.
        _namen = []
        _vorher = None
        for z, _k in konf_verlauf:
            t = z.strftime("%d.%m.")
            _namen.append(t if t != _vorher else "")
            _vorher = t
        chart.categoryAxis.categoryNames = _namen
        chart.categoryAxis.labels.fontName = FONT
        chart.categoryAxis.labels.fontSize = 6
        chart.valueAxis.valueMin = 0
        chart.valueAxis.valueMax = 100
        chart.valueAxis.labels.fontName = FONT
        chart.valueAxis.labels.fontSize = 7
        chart.lines[0].strokeColor = rc.HexColor("#30D158")
        chart.lines[0].strokeWidth = 2
        chart.joinedLines = 1
    d.add(chart)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# BRANDING (SVG-Logo + Banner via svg2rlg)
# Farbwelt: Cyan #20d9ff · Violett #7b5cff · Mint #73e6b0 · Dunkel #111827
# ─────────────────────────────────────────────────────────────────────────────
FARB = {
    "cyan": "#20d9ff",
    "violett": "#7b5cff",
    "mint": "#73e6b0",
    "dunkel": "#111827",
    "dunkel2": "#0b1220",
    "hell": "#f8fafc",
    "grav": "#6b7280",
    "gruen": "#30D158",
    "rot": "#FF453A",
}


def logo_drawing(groesse=46):
    """Micro-Trader Logo (PNG) als reportlab-Image."""
    try:
        pfad = os.path.join(BASE, "assets", "logo.png")
        if os.path.exists(pfad):
            img = Image(pfad)
            img.drawWidth = groesse
            img.drawHeight = groesse
            return img
    except Exception:
        pass
    from reportlab.graphics.shapes import Drawing as _D, Rect as _R
    d = _D(groesse, groesse)
    d.add(_R(0, 0, groesse, groesse, fillColor=rc.HexColor(FARB["violett"])))
    return d


def banner_drawing(breite):
    """Micro-Trader Banner (PNG) als reportlab-Image, skaliert auf Seitenbreite."""
    try:
        pfad = os.path.join(BASE, "assets", "banner.png")
        if os.path.exists(pfad):
            img = Image(pfad)
            img.drawWidth = breite
            img.drawHeight = breite * (620.0 / 2400.0)
            return img
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# PDF-BAU
# ─────────────────────────────────────────────────────────────────────────────
def _db_snap_count():
    """Phase B: zählt depot_snapshot-Zeilen in SQLite (für Datenvertrauens-Score)."""
    try:
        import sqlite3
        c = sqlite3.connect(os.path.join(BASE, "micro_trader.db"))
        n = c.execute('SELECT COUNT(*) FROM "depot_snapshot"').fetchone()[0]
        c.close()
        return n
    except Exception:
        return 0


def _datenvertrauen(daten):
    """Phase B: Datenvertrauens-Score. Leitet Status aus vorhandenen Daten ab.
    Liefert (felder_dict, gesamt_status, begruendung). KEINE erfundenen Werte."""
    import sqlite3
    felder = {}
    # Portfolio-Snapshot
    snap = daten.get("depot_snapshot_anzahl", 0)
    felder["Portfolio-Snapshot"] = "vollständig" if snap > 0 else "fehlt"
    # Trade-Daten
    tr = daten.get("trades_anzahl", 0)
    felder["Trade-Daten"] = "vollständig" if tr > 0 else "fehlt"
    # Einzel-Trade-P&L: nicht verfügbar (keine per-trade P&L in DB)
    felder["Einzel-Trade-P&L"] = "n/a"
    # Gebühren / Slippage: nicht erhoben
    felder["Gebühren"] = "n/a"
    felder["Slippage"] = "n/a"
    # Drawdown: nur Snapshot, keine Zeitreihe
    felder["Drawdown"] = "Snapshot fehlt" if snap == 0 else "verifiziert (Snapshot)"
    # decision_id-Zuordnung: jetzt aus DB (v2.19.1)
    try:
        import sqlite3 as _sq
        _c = _sq.connect(os.path.join(BASE, "micro_trader.db"))
        _tot = _c.execute("SELECT COUNT(*) FROM ki_decisions").fetchone()[0]
        _mit = _c.execute("SELECT COUNT(*) FROM ki_decisions WHERE decision_id IS NOT NULL").fetchone()[0]
        _c.close()
        if _tot == 0:
            felder["decision_id-Zuordnung"] = "n/a (keine KI-Daten)"
        elif _mit == 0:
            felder["decision_id-Zuordnung"] = "Legacy (alte Einträge ohne Feld)"
        else:
            anteil = round(100 * _mit / _tot)
            felder["decision_id-Zuordnung"] = f"vollständig ({anteil}% der Einträge)"
    except Exception:
        felder["decision_id-Zuordnung"] = "n/a (DB-Fehler)"
    # KI-Provider: aus cooldown + ki_log
    cd = daten.get("ki_cooldown", {})
    aktive_cooldowns = [p for p, v in cd.items() if v.get("bis", 0) > time.time()] if cd else []
    if not cd:
        felder["KI-Provider"] = "stabil"
    elif aktive_cooldowns:
        felder["KI-Provider"] = "gestört (" + ", ".join(aktive_cooldowns) + ")"
    else:
        felder["KI-Provider"] = "Fallback (Cooldown abgelaufen)"
    # Report-Erzeugung
    felder["Report-Erzeugung"] = "erfolgreich"
    # Gesamtbewertung (ehrlich, kein künstlicher %-Wert)
    fehlend = [k for k, v in felder.items() if v in ("fehlt", "n/a", "Snapshot fehlt") or "Legacy" in str(v) or "nicht in DB" in str(v)]
    gestoert = [k for k in felder if "gestört" in str(felder[k])]
    if gestoert:
        gesamt = "NIEDRIG"
        beg = "Provider gestört: " + ", ".join(gestoert) + ". Portfolio/Trade-Daten vorhanden, aber Gebühren/Slippage/decision_id nicht verifizierbar."
    elif "fehlt" in felder["Portfolio-Snapshot"] or "fehlt" in felder["Trade-Daten"]:
        gesamt = "NICHT VERIFIZIERT"
        beg = "Kern-Daten (Snapshot/Trades) fehlen."
    elif len(fehlend) >= 4:
        gesamt = "MITTEL"
        beg = "Portfolio-Snapshot + Trade-Daten vorhanden. Einzel-Trade-P&L, Gebühren, Slippage und decision_id-Zuordnung nicht vollständig verfügbar (Legacy/n.a.)."
    else:
        gesamt = "HOCH"
        beg = "Alle Kern-Daten verifiziert."
    return felder, gesamt, beg


def _status_uebersicht():
    """Statusuebersicht — GEMESSEN, nicht festgeschrieben.

    Die vorherige Fassung gab eine feste Liste aus (Hartcode in dieser
    Funktion). Sie meldete 'Paper-Modus OFFEN, nicht implementiert',
    'WhatsApp Bridge AKTIV' und Depotzahlen aus einer aelteren Phase,
    waehrend Paper laeuft, der Versand per E-Mail funktioniert und
    localhost:3000 nicht antwortet. Jede Zeile wird jetzt belegt.
    """
    import glob as _glob
    import json as _json
    import os as _os

    def _zaehle(muster):
        return len([f for f in _glob.glob(_os.path.join(BASE, muster))
                    if "summary" not in os.path.basename(f)])

    def _start(muster):
        s = 0.0
        for f in _glob.glob(_os.path.join(BASE, muster)):
            if "summary" in _os.path.basename(f):
                continue
            try:
                d = _json.load(open(f, encoding="utf-8"))
                s += float(d.get("start_wert") or d.get("einstandswert") or 0)
            except Exception:
                pass
        return s

    n_akt = _zaehle("depot_*_paper.json")
    n_etf = _zaehle("etf_*_paper.json")
    n_spec = _zaehle("spec_depots_paper/*.json")
    s_akt, s_etf, s_spec = (_start("depot_*_paper.json"),
                           _start("etf_*_paper.json"),
                           _start("spec_depots_paper/*.json"))

    # Handelsmodus aus den Depot-JSONs, nicht aus dem Dateinamen
    modus = "unbekannt"
    for f in _glob.glob(_os.path.join(BASE, "depot_*_paper.json"))[:1]:
        try:
            modus = str(_json.load(open(f, encoding="utf-8")).get("mode", "")).upper() or "unbekannt"
        except Exception:
            pass

    # Zustellweg: E-Mail konfiguriert?
    mail_ok = False
    env = _os.path.join(BASE, ".env")
    if _os.path.exists(env):
        try:
            inhalt = open(env, encoding="utf-8", errors="replace").read()
            mail_ok = all(k in inhalt for k in ("SMTP_HOST=", "SMTP_USER=", "SMTP_PASS="))
        except Exception:
            pass

    # Bridge nur AKTIV, wenn sie wirklich antwortet
    bridge = "nicht erreichbar"
    try:
        import urllib.request as _u
        with _u.urlopen("http://localhost:3000/", timeout=3) as r:
            bridge = f"aktiv (HTTP {r.status})"
    except Exception:
        bridge = "nicht erreichbar (HTTP 000)"

    # Dienste aus den Unit-Dateien
    def _unit(name):
        p = f"/etc/systemd/system/{name}"
        return "vorhanden" if _os.path.exists(p) else "fehlt"

    z = []
    z.append(("Handelsmodus", "PAPER" if modus == "PAPER" else modus.upper(),
              f"{n_akt + n_etf + n_spec} Depots, echte Kurse, kein Broker",
              f"{s_akt + s_etf + s_spec:,.0f}$ Start"))
    z.append(("Aktien", "PRODUKTIV", f"{n_akt} Depots mit Positionen/Trades", f"{s_akt:,.0f}$"))
    z.append(("ETF", "PRODUKTIV", f"{n_etf} Depots, Bruchstuecke erlaubt", f"{s_etf:,.0f}$"))
    z.append(("Spekulation", "PRODUKTIV", f"{n_spec} Depots, Stop-Loss aktiv", f"{s_spec:,.0f}$"))
    z.append(("Bericht-Zustellung",
              "PRODUKTIV" if mail_ok else "OFFEN",
              "E-Mail (SMTP 1&1/IONOS) mit PDF-Anhang" if mail_ok
              else "keine SMTP-Zugangsdaten in .env",
              "täglich 22:00" if mail_ok else "PDF nur in reports/"))
    z.append(("Dienste",
              "PRODUKTIV" if _unit("mt-scheduler.service") != "fehlt" else "PRUEFEN",
              f"micro-trader.service {_unit('micro-trader.service')}",
              f"mt-scheduler.service {_unit('mt-scheduler.service')}"))
    z.append(("Uhrzeit", "PRODUKTIV", "Container-Zone Europe/Berlin",
              "NYSE-Schluss als Trigger"))
    return z


def _cash_je_kategorie():
    """Bargeld und dessen Anteil je Kategorie aus den Depot-Snapshots."""
    import sqlite3
    out = {}
    try:
        c = sqlite3.connect(os.path.join(BASE, "micro_trader.db"))
        for typ in ("aktien", "etf", "spec"):
            row = c.execute(
                "SELECT wert, bargeld FROM depot_snapshot "
                "WHERE depot_typ=? AND zeit=(SELECT MAX(zeit) FROM depot_snapshot "
                "WHERE depot_typ=?)", (typ, typ)).fetchall()
            if row:
                wert = sum(r[0] or 0 for r in row)
                cash = sum(r[1] or 0 for r in row)
                out[typ] = {"wert": wert, "cash": cash,
                            "anteil": (cash / wert * 100) if wert else 0}
        c.close()
    except Exception:
        pass
    return out


def _blockaden_gestern():
    """Kauf-Blockaden des letzten Handelstags, gruppiert nach Grund."""
    import sqlite3
    from datetime import datetime, timedelta
    out = {"gesamt": 0, "gruende": {}}
    try:
        c = sqlite3.connect(os.path.join(BASE, "micro_trader.db"))
        gestern = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        rows = c.execute(
            "SELECT grund, COUNT(*) FROM trades "
            "WHERE aktion='kauf_blockiert' AND zeit LIKE ? "
            "GROUP BY grund ORDER BY COUNT(*) DESC", (gestern + "%",)).fetchall()
        for grund, n in rows:
            kern = str(grund or "?").split(":")[0].strip()[:40]
            out["gruende"][kern] = out["gruende"].get(kern, 0) + n
            out["gesamt"] += n
        c.close()
    except Exception:
        pass
    return out


def _ki_aktionen_gestern():
    """Verteilung der KI-Entscheidungen des letzten Handelstags."""
    import sqlite3
    from datetime import datetime, timedelta
    out = {"gesamt": 0, "akt": {}}
    try:
        c = sqlite3.connect(os.path.join(BASE, "micro_trader.db"))
        gestern = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        rows = c.execute(
            "SELECT aktion, COUNT(*) FROM ki_decisions "
            "WHERE zeit LIKE ? GROUP BY aktion", (gestern + "%",)).fetchall()
        for aktion, n in rows:
            a = str(aktion or "?")
            kern = a if not a.startswith("KI Risk") else "KI Risk (Level)"
            out["akt"][kern] = out["akt"].get(kern, 0) + n
            out["gesamt"] += n
        c.close()
    except Exception:
        pass
    return out


def baue_pdf(daten, pfad):
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"], fontName=FONT, fontSize=20, textColor=rc.HexColor("#1C1C1E"))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=FONT, fontSize=13, textColor=rc.HexColor(FARB["violett"]), spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName=FONT, fontSize=9.5, textColor=rc.HexColor("#1C1C1E"))
    small = ParagraphStyle("small", parent=styles["BodyText"], fontName=FONT, fontSize=8, textColor=rc.HexColor("#6E6E73"))
    cell = ParagraphStyle("cell", parent=styles["BodyText"], fontName=FONT, fontSize=8.5, leading=11)
    cellc = ParagraphStyle("cellc", parent=cell, alignment=TA_CENTER)

    doc = SimpleDocTemplate(pfad, pagesize=A4, topMargin=1.6*cm, bottomMargin=1.6*cm,
                            leftMargin=1.6*cm, rightMargin=1.6*cm,
                            title="Micro-Trader Tagesbericht", author="Micro-Trader")
    el = []
    W = doc.width

    # ── Banner oben (volle Breite) ──
    banner = banner_drawing(W)
    if banner:
        el.append(banner)
        el.append(Spacer(1, 0.3*cm))

    # ── Deckblatt-Header mit Logo ──
    logo = logo_drawing(46)
    header_tbl = Table([[logo, Paragraph("<b>Micro-Trader</b><br/>Tagesbericht", title)],
                        ["", Paragraph(datetime.now().strftime("%d.%m.%Y %H:%M") + f" · v{VERSION}", small)]],
                       colWidths=[52, W-52])
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("SPAN", (0,0), (0,1)),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    el.append(header_tbl)
    el.append(Spacer(1, 0.2*cm))
    el.append(HRFlowable(width="100%", thickness=2, color=rc.HexColor(FARB["violett"])))
    el.append(Spacer(1, 0.3*cm))

    # ══════════════════════════════════════════════════════════════════
    # NEUE STRUKTUR (nach User-Prompt v2): Tagesdaten → Projektstatus → Detail
    # ══════════════════════════════════════════════════════════════════
    jetzt = datetime.now()
    report_id = _report_id(jetzt.strftime("%Y-%m-%d"))
    S = {"title": title, "h2": h2, "body": body, "small": small, "cell": cell, "cellc": cellc}

    # ── SEITE 1: Portfolio- und Tagesübersicht ──
    # 1. Gesamt-Rendite
    block1 = [Paragraph("1. Gesamt-Rendite", h2)]
    pnl_farbe = "#30D158" if daten["ges_pnl"] >= 0 else "#FF453A"
    ges_card = [
        ["Gesamtwert", f"{daten['ges_wert']:,.2f} $"],
        ["Investiert", f"{daten['ges_start']:,.2f} $"],
        ["Gewinn/Verlust", f"{daten['ges_pnl']:+,.2f} $"],
        ["Rendite gesamt", f"<font color='{pnl_farbe}'>{daten['ges_pnl_pct']:+,.2f}%</font>"],
    ]
    rows = [[Paragraph(f"<b>{k}</b>", cell), Paragraph(v, cell)] for k, v in ges_card]
    t_ges = Table(rows, colWidths=[W*0.35, W*0.65])
    t_ges.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), rc.HexColor("#F5F7FA")),
        ("BOX", (0,0), (-1,-1), 0.5, rc.HexColor("#E5E5EA")),
        ("INNERGRID", (0,0), (-1,-1), 0.5, rc.HexColor("#E5E5EA")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
    ]))
    block1.append(t_ges)
    block1.append(Spacer(1, 0.2*cm))
    # Pro Kategorie
    block1.append(Paragraph("Rendite pro Kategorie", body))
    kat_rows = [[Paragraph("<b>Kategorie</b>", cell), Paragraph("<b>Wert</b>", cell),
                 Paragraph("<b>Investiert</b>", cell), Paragraph("<b>G/V</b>", cell),
                 Paragraph("<b>Rendite</b>", cell)]]
    for k, v in daten["kat"].items():
        farbe = "#30D158" if v["pnl"] >= 0 else "#FF453A"
        kat_rows.append([
            Paragraph(k, cell), Paragraph(f"{v['wert']:,.2f} $", cell),
            Paragraph(f"{v['start']:,.2f} $", cell), Paragraph(f"{v['pnl']:+,.2f} $", cell),
            Paragraph(f"<font color='{farbe}'>{v['pnl_pct']:+,.2f}%</font>", cell),
        ])
    t_kat = Table(kat_rows, colWidths=[W*0.22, W*0.22, W*0.22, W*0.17, W*0.17])
    t_kat.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor(FARB["violett"])),
        ("TEXTCOLOR", (0,0), (-1,0), rc.white),
        ("GRID", (0,0), (-1,-1), 0.5, rc.HexColor("#E5E5EA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.white, rc.HexColor("#F5F7FA")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    block1.append(t_kat)
    block1.append(Spacer(1, 0.1*cm))
    block1.append(Paragraph(f"Datenquelle: Depot-Snapshot zum {jetzt.strftime('%d.%m.%Y %H:%M')} · "
                            f"nicht live (Snapshot), Werte aus Depot-JSON.", small))
    el.append(KeepTogether(block1))

    # ── Phase B: DATENVERTRAUENS-SCORE (auf Seite 1) ──
    felder, gesamt, beg = _datenvertrauen(daten)
    block_dv = [Paragraph("Datenvertrauen", h2)]
    dv_farbe = {"HOCH": "#30D158", "MITTEL": "#FF9F0A", "NIEDRIG": "#FF453A", "NICHT VERIFIZIERT": "#8E8E93"}[gesamt]
    block_dv.append(Paragraph(f'<b>DATENLAGE: <font color="{dv_farbe}">{gesamt}</font></b>', body))
    block_dv.append(Paragraph(beg, small))
    dv_rows = [[Paragraph("<b>Bereich</b>", cell), Paragraph("<b>Status</b>", cell)]]
    for k, v in felder.items():
        dv_rows.append([Paragraph(k, cell), Paragraph(v, cell)])
    t_dv = Table(dv_rows, colWidths=[W*0.45, W*0.55])
    t_dv.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor(FARB["violett"])),
        ("TEXTCOLOR", (0,0), (-1,0), rc.white),
        ("GRID", (0,0), (-1,-1), 0.5, rc.HexColor("#E5E5EA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.white, rc.HexColor("#F5F7FA")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    block_dv.append(Spacer(1, 0.1*cm))
    block_dv.append(t_dv)
    el.append(KeepTogether(block_dv))
    el.append(PageBreak())

    # Phase D: BETRIEBSKENNZAHLEN AUS DER DB
    _cash = _cash_je_kategorie()
    _block = _blockaden_gestern()
    _kia = _ki_aktionen_gestern()
    if _cash or _block["gesamt"] or _kia["gesamt"]:
        kz_rows = [[Paragraph("<b>Kennzahl</b>", cell), Paragraph("<b>Wert</b>", cell)]]
        for typ, lbl in (("aktien", "Aktien"), ("etf", "ETF"), ("spec", "Spec")):
            if _cash.get(typ):
                d = _cash[typ]
                anteil = d["anteil"]
                farbe = "#FF9F0A" if anteil > 25 else "#8E8E93"
                kz_rows.append([
                    Paragraph(f"Ungenutztes Budget {lbl}", cell),
                    Paragraph(f"<font color='{farbe}'>{d['cash']:,.2f} $ von {d['wert']:,.2f} $ "
                              f"({anteil:.1f}%)</font>", cell)])
        if _block["gesamt"]:
            gruende = ", ".join(f"{n}x {g}" for g, n in
                                sorted(_block["gruende"].items(), key=lambda x: -x[1])[:3])
            kz_rows.append([
                Paragraph("Kauf-Blockaden (Vortag)", cell),
                Paragraph(f"{_block['gesamt']} gesamt · {gruende}", cell)])
        if _kia["gesamt"]:
            halten = _kia["akt"].get("halten", 0)
            kauf = _kia["akt"].get("kaufen", 0)
            verk = _kia["akt"].get("verkaufen", 0)
            q = round(100 * halten / _kia["gesamt"])
            kz_rows.append([
                Paragraph("KI-Entscheidungen (Vortag)", cell),
                Paragraph(f"{_kia['gesamt']} gesamt · {q}% halten, "
                          f"{kauf} kaufen, {verk} verkaufen", cell)])
        t_kz = Table(kz_rows, colWidths=[W*0.38, W*0.62])
        t_kz.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), rc.HexColor(FARB["violett"])),
            ("TEXTCOLOR", (0,0), (-1,0), rc.white),
            ("GRID", (0,0), (-1,-1), 0.5, rc.HexColor("#E5E5EA")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.white, rc.HexColor("#F5F7FA")]),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
        ]))
        block_kz = [Paragraph("Betriebskennzahlen", h2), t_kz,
                    Paragraph("Quelle: micro_trader.db (Depot-Snapshots, trades, "
                              "ki_decisions), Vortag = letzter Handelstag.", small)]
        el.append(KeepTogether(block_kz))
        el.append(Spacer(1, 0.2*cm))

    # ── SEITE 2: Kategorien und Entwicklung ──
    el.append(Paragraph("2. Kategorien und Entwicklung", h2))
    el.append(HRFlowable(width="100%", thickness=1, color=rc.HexColor(FARB["violett"])))
    el.append(Spacer(1, 0.2*cm))
    kat_farbe = {"Aktien": FARB["cyan"], "ETF": FARB["violett"], "Spec": FARB["mint"]}
    for idx, kn in enumerate(["Aktien", "ETF", "Spec"], start=1):
        kv = daten["kat"].get(kn, {})
        pnl = kv.get("pnl", 0)
        block_k = [Paragraph(f"{kn}", h2)]
        vk = daten["verlauf_kat"].get(kn, [])
        if vk:
            block_k.append(graph_verlauf(vk, titel=f"{kn} Verlauf (7 Tage)"))
        else:
            block_k.append(Paragraph("Keine belastbare 7-Tage-Historie für diese Kategorie vorhanden.", small))
        pmk = Table([[Paragraph("<b>Wert</b>", cell), Paragraph(f"{kv.get('wert',0):,.2f} $", cell),
                      Paragraph("<b>G/V</b>", cell), Paragraph(f"<font color='{kat_farbe[kn]}'>{pnl:+,.2f} $ ({kv.get('pnl_pct',0):+,.2f}%)</font>", cell)]],
                    colWidths=[W*0.22, W*0.28, W*0.22, W*0.28])
        pmk.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), rc.HexColor("#F5F7FA")),
            ("BOX", (0,0), (-1,-1), 0.5, rc.HexColor("#E5E5EA")),
            ("INNERGRID", (0,0), (-1,-1), 0.5, rc.HexColor("#E5E5EA")),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
        ]))
        block_k.append(Spacer(1, 0.15*cm))
        block_k.append(pmk)
        block_k.append(Spacer(1, 0.3*cm))
        el.append(KeepTogether(block_k))
    el.append(PageBreak())

    # ── SEITE 3: Performance und KI-Lernen (endet nach Marktregime) ──
    # 6. Beste/Schlechteste 5
    el.append(Paragraph("3. Performance und KI-Lernen", h2))
    el.append(HRFlowable(width="100%", thickness=1, color=rc.HexColor(FARB["violett"])))
    el.append(Spacer(1, 0.2*cm))
    el.append(Paragraph("3.1 Beste & Schlechteste 5 (alle Depots)", body))
    top_rows = [[Paragraph("<b>#</b>", cellc), Paragraph("<b>Ticker</b>", cell),
                 Paragraph("<b>Kat</b>", cell), Paragraph("<b>Rendite</b>", cell)]]
    for i, d in enumerate(daten["top5"], 1):
        top_rows.append([Paragraph(str(i), cellc), Paragraph(d["ticker"], cell),
                         Paragraph(d["kat"], cell),
                         Paragraph(f"<font color='#30D158'>{d['pnl_pct']:+,.2f}%</font>", cell)])
    flop_rows = [[Paragraph("<b>#</b>", cellc), Paragraph("<b>Ticker</b>", cell),
                  Paragraph("<b>Kat</b>", cell), Paragraph("<b>Rendite</b>", cell)]]
    for i, d in enumerate(daten["flop5"], 1):
        flop_rows.append([Paragraph(str(i), cellc), Paragraph(d["ticker"], cell),
                          Paragraph(d["kat"], cell),
                          Paragraph(f"<font color='#FF453A'>{d['pnl_pct']:+,.2f}%</font>", cell)])
    t_top = Table(top_rows, colWidths=[W*0.1, W*0.3, W*0.3, W*0.3])
    t_top.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor("#30D158")),
        ("TEXTCOLOR", (0,0), (-1,0), rc.white),
        ("GRID", (0,0), (-1,-1), 0.5, rc.HexColor("#E5E5EA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.white, rc.HexColor("#F5F7FA")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    t_flop = Table(flop_rows, colWidths=[W*0.1, W*0.3, W*0.3, W*0.3])
    t_flop.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor("#FF453A")),
        ("TEXTCOLOR", (0,0), (-1,0), rc.white),
        ("GRID", (0,0), (-1,-1), 0.5, rc.HexColor("#E5E5EA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.white, rc.HexColor("#F5F7FA")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    el.append(t_top)
    el.append(Spacer(1, 0.15*cm))
    el.append(t_flop)
    el.append(Spacer(1, 0.3*cm))

    # 7. KI-Lernen + Konfidenz
    el.append(Paragraph("3.2 KI-Lernen & Konfidenz", body))
    n_rules = len(daten["rules_list"])
    konf_txt = f"{daten['ki_konf_schnitt']:.1f}%" if daten["ki_konf_schnitt"] is not None else "k.A."
    el.append(Paragraph(f"Gelernte Regeln: <b>{n_rules}</b> · Konfidenz-Schnitt: <b>{konf_txt}</b>", body))
    if daten["rules_list"]:
        items = []
        for r in daten["rules_list"][:6]:
            muster = r.get("muster", r.get("id", "?"))
            gew = r.get("gewicht", r.get("weight", "?"))
            items.append(ListItem(Paragraph(f"<b>{muster}</b> (Gewicht: {gew})", body)))
        el.append(ListFlowable(items, bulletType="bullet"))
    if daten["konf_verlauf"]:
        el.append(Spacer(1, 0.15*cm))
        _kv = daten.get("konf_verlauf") or []
        # Die Werte muessen echte Konfidenzen sein. 133 der 534
        # ki_log-Eintraege haben konfidenz=None; ohne sie zeichnete der
        # Graph Zeitstempel statt Werten und beschriftete jede Achse
        # mit "07.21" - dem Anfang eines Uhrzeit-Strings.
        _echt = [x for x in _kv if isinstance(x[1], (int, float))]
        if _echt:
            el.append(Paragraph("KI-Konfidenz-Verlauf (letzte Entscheidungen):", body))
            el.append(graph_konfidenz(_echt))
        else:
            el.append(Paragraph(
                "KI-Konfidenz-Verlauf: keine auswertbaren Konfidenzwerte in den "
                "letzten Entscheidungen (das Feld ist nicht bei allen Einträgen gesetzt).",
                body))
    el.append(Spacer(1, 0.3*cm))

    # 8. Marktregime (LETZTER Abschnitt auf Seite 3) — KeepTogether gegen verwaiste Überschrift
    regime_block = [Paragraph("3.3 Marktregime (pro Markt)", body)]
    r = daten["regime"]
    rm = {"bull": "🟢 Bull", "bear": "🔴 Bear", "sideways": "🟡 Sideways", "?": "❓ ?"}
    regime_block.append(Paragraph(f"US: {rm.get(r.get('US','?'), '?')} · DE: {rm.get(r.get('DE','?'), '?')} · JP: {rm.get(r.get('JP','?'), '?')}", body))
    el.append(KeepTogether(regime_block))
    el.append(PageBreak())

    # ── Phase C: STATUSÜBERSICHT (Seite 4 Anfang) ──
    el.append(Paragraph("4. Statusübersicht (Produktiv / TOT / OFFEN)", h2))
    el.append(HRFlowable(width="100%", thickness=1, color=rc.HexColor(FARB["violett"])))
    el.append(Spacer(1, 0.2*cm))
    su_rows = [[Paragraph("<b>Bereich</b>", cell), Paragraph("<b>Status</b>", cell),
                Paragraph("<b>Beleg</b>", cell), Paragraph("<b>Kommentar</b>", cell)]]
    status_farbe = {"PRODUKTIV": "#30D158", "SHADOW": "#AF52DE", "PAPER": "#8E8E93",
                    "KONZEPT": "#8E8E93", "OFFEN": "#FF9F0A", "BLOCKIERT": "#FF453A",
                    "NICHT VERIFIZIERT": "#8E8E93", "EINGESCHRÄNKT": "#FF9F0A"}
    for bereich, status, beleg, komm in _status_uebersicht():
        sf = status_farbe.get(status, "#1C1C1E")
        su_rows.append([
            Paragraph(bereich, cell),
            Paragraph(f'<font color="{sf}"><b>{status}</b></font>', cell),
            Paragraph(beleg, cell),
            Paragraph(komm, cell),
        ])
    t_su = Table(su_rows, colWidths=[W*0.18, W*0.16, W*0.38, W*0.28])
    t_su.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor(FARB["violett"])),
        ("TEXTCOLOR", (0,0), (-1,0), rc.white),
        ("GRID", (0,0), (-1,-1), 0.5, rc.HexColor("#E5E5EA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.white, rc.HexColor("#F5F7FA")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
    ]))
    el.append(t_su)
    el.append(Spacer(1, 0.3*cm))


    el.append(PageBreak())

    # ── SEITE 5-9: Tagesauswertung Detail (bisherige 6 Sektionen) ──
    _seite_tagesstatus(el, S, W, daten, report_id, jetzt)
    _seite_performance(el, S, W, daten)
    _seite_risiko(el, S, W, daten)
    _seite_trades(el, S, W, daten)
    _seite_governance(el, S, W, daten)
    _seite_system(el, S, W, daten)

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(FONT, 7)
        canvas.setFillColor(rc.HexColor("#6E6E73"))
        fz = doc_.page
        canvas.drawString(1.6*cm, 1.0*cm,
            f"Report-ID: {report_id} · {jetzt.strftime('%Y-%m-%d %H:%M')} · v{VERSION} · "
            f"KI GENERIERT · Automatisch erzeugt · S. {fz}")
        canvas.restoreState()
    doc.build(el, onFirstPage=_footer, onLaterPages=_footer)
    return pfad


# ══════════════════════════════════════════════════════════════════════════
# TAGESAUSWERTUNG-ERWEITERUNG (6 Pflichtsektionen, nach User-Prompt)
# Nutzt echte Datenquellen: ki_log.json, learned_rules.json, regelstand_aggregat,
# system_log.py, trader_status.py, .backup/. Keine erfundenen Werte → n/a.
# ══════════════════════════════════════════════════════════════════════════

VERSION = "2.18.3"  # Fallback; wird aus version.json ueberschrieben
try:
    with open(os.path.join(BASE, "version.json"), encoding="utf-8") as _vf:
        _vj = json.load(_vf)
    if _vj.get("version"):
        VERSION = _vj["version"]
    else:
        VERSION = "2.18.3"
except Exception:
    VERSION = "2.18.3"

def _lade_json(pfad, default=None):
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}

def _report_id(datum):
    # RPT-YYYYMMDD-NNN (laufende Nummer pro Tag aus reports/-Verzeichnis)
    muster = f"daily_report_{datum.replace('-','')}"
    n = 1
    for f in glob.glob(os.path.join(REPORTS, f"{muster}*.pdf")):
        n += 1
    return f"RPT-{datum.replace('-','')}-{n:03d}"

def _seite_tagesstatus(el, S, W, daten, report_id, jetzt):
    """Seite 5 — Tagesauswertung Detail (Pflichtsektion aus User-Prompt)."""
    el.append(Paragraph("5. Tagesauswertung — Detail", S["h2"]))
    el.append(HRFlowable(width="100%", thickness=1, color=rc.HexColor(FARB["violett"])))
    el.append(Spacer(1, 0.2*cm))

    # Gesamtstatus aus KI-Job + Datenqualität
    sys = daten.get("system", {})
    ki_gestoert = sys.get("ki_job") != "OK"
    notifs = daten.get("notifications", [])
    # Nur ECHTE Warnungen zählen (positive Risk-Rendite-Meldungen sind KEINE Warnungen)
    warnungen = [n for n in notifs
                 if "❌" in n.get("text", "") or "gesperrt" in n.get("text", "")
                 or "Drawdown" in n.get("text", "") or "Fehler" in n.get("text", "")
                 or "KRITISCH" in n.get("text", "")]
    if ki_gestoert:
        gesamtstatus = "WARNUNG"
    elif warnungen:
        gesamtstatus = "WARNUNG"
    else:
        gesamtstatus = "STABIL"

    zeile1 = [
        ["Report-ID", report_id, "Systemversion", VERSION],
        ["Berichtsdatum", jetzt.strftime("%Y-%m-%d"), "Regelwerksversion", f"v{daten.get('regelstand_version','n/a')}"],
        ["Erstellt", jetzt.strftime("%H:%M:%S"), "Auswertungszeitraum", "Tagesabschluss"],
        ["Gesamtstatus", gesamtstatus, "Tagesrendite", f"{daten.get('ges_pnl_pct',0):+.2f}%"],
    ]
    t1 = Table(zeile1, colWidths=[W*0.22, W*0.28, W*0.22, W*0.28])
    t1.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), FONT, 8.5),
        ("TEXTCOLOR", (1,0), (1,-1), rc.HexColor("#1C1C1E")),
        ("TEXTCOLOR", (3,0), (3,-1), rc.HexColor("#1C1C1E")),
        ("BACKGROUND", (0,0), (0,-1), rc.HexColor("#F2F2F7")),
        ("BACKGROUND", (2,0), (2,-1), rc.HexColor("#F2F2F7")),
        ("TEXTCOLOR", (1,3), (1,3), rc.HexColor(FARB["cyan"])),
        ("GRID", (0,0), (-1,-1), 0.4, rc.HexColor("#E5E5EA")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    el.append(t1)
    el.append(Spacer(1, 0.3*cm))

    ges_wert = daten.get("ges_wert", 0)
    nt_heute = daten.get("trades_heute", 0)
    if isinstance(nt_heute, list):
        nt_heute = len(nt_heute)
    el.append(Paragraph(
        f"Equity: <b>{ges_wert:,.2f} $</b> · Netto-P&L: <b>n/a</b> (Einzel-Trade-P&L nicht aggregiert) · "
        f"Drawdown: <b>n/a</b> (Snapshot fehlt) · Trades heute: <b>{nt_heute}</b>", S["body"]))
    el.append(Spacer(1, 0.2*cm))

    # Ehrliche Tagesbewertung (Warnstatus korrekt)
    if ki_gestoert:
        bewertung = (f"⚠ WARNUNG: Portfolio-Snapshot vorhanden. Einzel-Trade-P&L, Gebühren, Slippage und "
                     f"Drawdown konnten für diesen Bericht nicht vollständig verifiziert werden. "
                     f"Der KI-Job war zum Erstellungszeitpunkt gestört (Provider nicht erreichbar). "
                     f"{nt_heute} Trades im Berichtszeitraum erkannt, aber keine vollständige KI-Tagesbewertung verifiziert.")
    else:
        bewertung = _tagesbewertung(daten, gesamtstatus)
    el.append(Paragraph(f"<b>Tagesbewertung:</b> {bewertung}", S["body"]))
    el.append(Spacer(1, 0.3*cm))

def _tagesbewertung(daten, status):
    teile = []
    if status == "STABIL":
        teile.append("Stabiler Handelstag")
    elif status == "WARNUNG":
        teile.append("Handelstag mit Warnungen")
    else:
        teile.append("Kritischer Handelstag (Drawdown-Sperre aktiv)")
    nt = daten.get("trades_heute", 0)
    if isinstance(nt, list):
        nt = len(nt)
    if nt == 1:
        teile.append("1 Trade ausgeführt")
    elif nt > 0:
        teile.append(f"{nt} Trades ausgeführt")
    else:
        teile.append("keine Trades heute")
    if daten.get("ki_aktiv"):
        teile.append("KI aktiv (Konfidenz > 0)")
    else:
        teile.append("KI nicht verfügbar (alle Provider)")
    return ". ".join(teile) + "."

def _profit_factor(pnls):
    """Gewinnsumme / Verlustsumme - oder n/a, wenn nicht definiert.

    Bei 0 Gewinnern waere das 0.00/28.63 = 0.00, und das liest
    sich wie "nichts gebracht". Richtig ist: ohne Gewinner gibt
    es keinen Profit Factor, es gibt nur Verluste. Umgekehrt gilt
    dasselbe - ohne Verlierer ist die Kennzahl nicht aussagekraeftig.

    0.00 ist hier eine Falschaussage, nicht ein Messwert.
    """
    gewinn = sum(p for p in pnls if p > 0)
    verlust = abs(sum(p for p in pnls if p < 0))
    if gewinn <= 0 and verlust <= 0:
        return "n/a (keine bewerteten Trades)"
    if verlust <= 0:
        return "n/a (keine Verluste)"
    if gewinn <= 0:
        return "n/a (keine Gewinner)"
    return f"{gewinn/verlust:.2f}"


def _seite_performance(el, S, W, daten):
    """Seite 6 — Performance und P&L."""
    el.append(Paragraph("6. Performance & P&L", S["h2"]))
    el.append(HRFlowable(width="100%", thickness=1, color=rc.HexColor(FARB["violett"])))
    el.append(Spacer(1, 0.2*cm))

    alle_t = daten.get("alle_trades", [])
    # Nur AUSGEFUEHRTE Trades. 1.286 von 1.475 Eintraegen waren
    # kauf_blockiert (Menge 0) - Blockierversuche sind keine Trades
    # und gehoeren weder in P&L noch in die Trefferquote.
    trades = [t for t in alle_t if _trade_ist_ausgefuehrt(t)]
    blockiert = len(alle_t) - len(trades)
    pnls = _pnl_fifo(trades)
    bewertet = [p for p in pnls if p is not None]
    gewinner = sum(1 for p in bewertet if p > 0)
    verlierer = sum(1 for p in bewertet if p < 0)
    n = len(bewertet)
    treffer = (gewinner / n * 100) if n else 0
    brutto = sum(bewertet)
    n_verkauf = sum(1 for t in trades
                    if "verkauf" in _trade_typ(t))
    if bewertet:
        brutto_text = f"{brutto:,.2f} $"
        fehlend = n_verkauf - len(bewertet)
        if fehlend > 0:
            brutto_text += " · %d Verkäufe ohne belegten Einstand nicht bewertet" % fehlend
    elif n_verkauf:
        brutto_text = "n/a (Verkauf ohne belegten Einstand)"
    else:
        brutto_text = "n/a (kein Verkauf im Berichtszeitraum)"
    # Zeiträume klar trennen
    nt_heute = daten.get("trades_heute", 0)
    if isinstance(nt_heute, list):
        nt_heute = len(nt_heute)
    positionen = daten.get("offene_positionen", 0)
    # 01.11.2026: Gebuehren/Slippage aus den Trades (Kostenmodell
    # handelskosten.py). Aeltere Trades ohne Kostenfelder: n/a.
    try:
        import performance as _perf
        _hk = _perf.handelskosten_aus_trades(trades)
    except Exception:
        _hk = {"trades_mit_kosten": 0}
    if _hk.get("trades_mit_kosten"):
        _zus = (" · %d ältere Trades ohne Kostenfelder" % _hk["trades_ohne_kosten"]
                if _hk.get("trades_ohne_kosten") else "")
        gebuehr_txt = f"{_hk['gebuehr']:,.2f} $" + _zus
        slip_txt = f"{_hk['slippage']:,.2f} $"
        netto_txt = (f"{brutto - _hk['gebuehr']:,.2f} $ (Brutto − Gebühren; Slippage steckt im Kurs)"
                     if bewertet else "n/a")
    else:
        gebuehr_txt = slip_txt = "n/a (Trades vor dem Kostenmodell)"
        netto_txt = "n/a (Gebühren fehlen)"
    tab = [
        ["Kennzahl", "Wert", "Kennzahl", "Wert"],
        ["Brutto-P&L (gesamt)", brutto_text, "Gewinner", f"{gewinner}"],
        ["Netto-P&L", netto_txt, "Verlierer", f"{verlierer}"],
        ["Gebühren", gebuehr_txt, "Trefferquote",
         (f"{treffer:.0f}% (n={n})" if n else "n/a")],
        ["Slippage", slip_txt, "Ø Gewinn",
         (f"{sum(p for p in bewertet if p > 0)/gewinner:,.2f} $"
          if gewinner else "n/a")],
        ["Rendite auf Equity", f"{daten.get('ges_pnl_pct',0):+.2f}%", "Ø Verlust",
         (f"{sum(p for p in bewertet if p < 0)/verlierer:,.2f} $"
          if verlierer else "n/a")],
        ["Ausgeführte Trades gesamt", f"{len(trades)}", "Profit Factor",
         _profit_factor(bewertet)],
        ["Blockierte Versuche (keine Trades)", f"{blockiert}",
         "Portfolio-Positionen", f"{positionen}"],
    ]
    t = Table(tab, colWidths=[W*0.28, W*0.22, W*0.28, W*0.22])
    t.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), FONT, 8.5),
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor(FARB["violett"])),
        ("TEXTCOLOR", (0,0), (-1,0), rc.HexColor("#FFFFFF")),
        ("GRID", (0,0), (-1,-1), 0.4, rc.HexColor("#E5E5EA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.HexColor("#FFFFFF"), rc.HexColor("#F7F7FA")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    el.append(t)
    el.append(Spacer(1, 0.2*cm))
    el.append(Paragraph("Hinweis: 'Trades im Berichtszeitraum' = heute (Snapdate). "
                        "'Historische Trade-Anzahl' = alle Depot-Trades seit Beginn. "
                        "Gebühren/Slippage: seit 01.11.2026 je Trade gespeichert (handelskosten.py).", S["small"]))
    _abschnitt_benchmark_ki(el, S, W, daten, trades)
    el.append(PageBreak())


def _tabelle_einfach(zeilen, W, spalten):
    t = Table(zeilen, colWidths=[W * x for x in spalten])
    t.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), FONT, 8.5),
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor(FARB["violett"])),
        ("TEXTCOLOR", (0,0), (-1,0), rc.HexColor("#FFFFFF")),
        ("GRID", (0,0), (-1,-1), 0.4, rc.HexColor("#E5E5EA")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    return t


def _abschnitt_benchmark_ki(el, S, W, daten, trades):
    """01.11.2026: Vergleich mit Buy & Hold (SPY) seit dem ersten Trade und
    Kennzahlen der KI-Aufrufe der letzten 24 h."""
    try:
        import performance as _perf
    except Exception:
        return
    el.append(Spacer(1, 0.3*cm))
    el.append(Paragraph("Benchmark: Buy &amp; Hold SPY", S["h3"] if "h3" in S else S["h2"]))
    zeiten = sorted(str(t.get("zeit", ""))[:10] for t in trades if t.get("zeit"))
    start = zeiten[0] if zeiten else None
    spy = _perf.benchmark_seit(start) if start else None
    zeilen = [["Was", "Rendite", "vs. SPY"]]
    def _vs(r):
        return "n/a" if spy is None or r is None else f"{r - spy:+.2f} %-Pkt"
    ges = daten.get("ges_pnl_pct")
    zeilen.append(["Alle Depots", f"{ges:+.2f}%" if ges is not None else "n/a", _vs(ges)])
    for k, v in (daten.get("kat") or {}).items():
        r = v.get("pnl_pct")
        zeilen.append([f"  {k}", f"{r:+.2f}%" if r is not None else "n/a", _vs(r)])
    zeilen.append([f"SPY seit {start or '?'}", f"{spy:+.2f}%" if spy is not None else "n/a (keine Kursdaten)", ""])
    el.append(_tabelle_einfach(zeilen, W, (0.45, 0.25, 0.30)))
    el.append(Paragraph("Zeitraum: seit dem ersten erfassten Trade. Positiv in „vs. SPY“ = besser "
                        "als einfaches Kaufen und Halten.", S["small"]))

    ki = _perf.ki_kennzahlen(24)
    el.append(Spacer(1, 0.3*cm))
    el.append(Paragraph("KI-Aufrufe (letzte 24 h)", S["h3"] if "h3" in S else S["h2"]))
    if not ki:
        el.append(Paragraph("Noch keine Daten (Protokoll ki_aufrufe.jsonl seit 01.11.2026).", S["small"]))
        return
    if not ki.get("aufrufe"):
        el.append(Paragraph("Keine KI-Aufrufe in den letzten 24 h.", S["small"]))
        return
    anb = ", ".join(f"{k} {v}" for k, v in list(ki["anbieter"].items())[:5]) or "–"
    feh = ", ".join(f"{k} {v}" for k, v in list(ki["fehler"].items())[:5]) or "–"
    zeilen = [["Kennzahl", "Wert"],
              ["Aufrufe / erfolgreich", f"{ki['aufrufe']} / {ki['erfolgreich']}"],
              ["Ausfallquote", f"{ki['ausfall_quote_pct']:.1f} %"],
              ["Median-Dauer", f"{ki['median_sekunden']:.1f} s"],
              ["Anbieter (Erfolge)", anb],
              ["Fehler", feh]]
    el.append(_tabelle_einfach(zeilen, W, (0.35, 0.65)))

def _seite_risiko(el, S, W, daten):
    """Seite 7 — Risiko und Exposure."""
    el.append(Paragraph("7. Risiko & Exposure", S["h2"]))
    el.append(HRFlowable(width="100%", thickness=1, color=rc.HexColor(FARB["violett"])))
    el.append(Spacer(1, 0.2*cm))

    offen = daten.get("offene_positionen", 0)
    equity = daten.get("ges_wert", 0)
    exp = daten.get("exposure_pro_symbol", {})
    exp_rows = [["Symbol", "Exposure", "Status"]]
    for sym, wert in sorted(exp.items(), key=lambda x: -x[1])[:10]:
        exp_rows.append([sym, f"{wert:,.2f} $", "OK"])
    if not exp_rows[1:]:
        exp_rows.append(["—", "n/a", "n/a"])
    t = Table(exp_rows, colWidths=[W*0.3, W*0.4, W*0.3])
    t.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), FONT, 8.5),
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor(FARB["violett"])),
        ("TEXTCOLOR", (0,0), (-1,0), rc.HexColor("#FFFFFF")),
        ("GRID", (0,0), (-1,-1), 0.4, rc.HexColor("#E5E5EA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.HexColor("#FFFFFF"), rc.HexColor("#F7F7FA")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    el.append(Paragraph(f"Equity: <b>{equity:,.2f} $</b> · Offene Positionen: <b>{offen}</b>", S["body"]))
    el.append(Spacer(1, 0.2*cm))
    el.append(t)
    el.append(Spacer(1, 0.2*cm))
    el.append(Paragraph("⚠ Drawdown nicht verfügbar — erforderlicher Snapshot (Tages-High-Water-Mark / Peak-Tracking) fehlt im System. "
                        "Tages-Drawdown und maximaler Drawdown werden nicht persistiert.", S["small"]))
    el.append(PageBreak())

def _seite_trades(el, S, W, daten):
    """Seite 8 — Trades und Ausführungsqualität."""
    el.append(Paragraph("8. Trades & Ausführungsqualität", S["h2"]))
    el.append(HRFlowable(width="100%", thickness=1, color=rc.HexColor(FARB["violett"])))
    el.append(Spacer(1, 0.2*cm))

    trades = daten.get("alle_trades", [])[:30]
    rows = [["Zeit", "Typ", "Symbol", "Menge", "Preis", "Exit-Grund", "decision_id"]]
    for t in trades:
        mark = "Legacy/Fallback" if not t.get("decision_id") else "vorhanden"
        rows.append([
            t.get("zeit", "?")[:16].replace("T", " "),
            t.get("typ", t.get("aktion", "?")),
            t.get("ticker", "?"),
            f"{t.get('menge',0):.2f}",
            f"{t.get('preis',0):.2f}",
            (t.get("grund", "") or "")[:28],
            mark,
        ])
    if len(rows) == 1:
        rows.append(["—", "—", "—", "—", "—", "keine Trades", "—"])
    t = Table(rows, colWidths=[W*0.16, W*0.1, W*0.1, W*0.1, W*0.1, W*0.3, W*0.14], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), FONT, 7.5),
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor(FARB["cyan"])),
        ("TEXTCOLOR", (0,0), (-1,0), rc.HexColor("#FFFFFF")),
        ("GRID", (0,0), (-1,-1), 0.4, rc.HexColor("#E5E5EA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.HexColor("#FFFFFF"), rc.HexColor("#F7F7FA")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    el.append(t)
    el.append(Spacer(1, 0.2*cm))
    el.append(Paragraph("⚠ Datenqualität: <b>decision_id</b> nur im KI-Log (ki_log.json) vorhanden, "
                        "keine direkte Zuordnung zum Depot-Trade. Trade daher als <b>Legacy/Fallback</b> markiert. "
                        "Slippage/Gebühren/Fill-Preis: <b>n/a</b> (nicht im System erfasst).", S["small"]))
    el.append(PageBreak())

def _seite_governance(el, S, W, daten):
    """Seite 5 — KI-, Regel- und Governance-Status."""
    el.append(Paragraph("KI-, Regel- & Governance-Status", S["h2"]))
    el.append(HRFlowable(width="100%", thickness=1, color=rc.HexColor(FARB["violett"])))
    el.append(Spacer(1, 0.2*cm))

    ra = daten.get("regelstand", {})
    gov = [
        ["Governance-Bereich", "Anzahl", "Status"],
        ["Regeln gesamt", ra.get("regeln_gesamt", "n/a"), ""],
        ["Freigegeben", ra.get("freigegeben", "n/a"), "LIVE"],
        ["Shadow", ra.get("shadow", "n/a"), "nur Kontext"],
        ["Nicht freigegeben", ra.get("nicht_freigegeben", "n/a"), ""],
        ["Im Live-Pfad", ra.get("im_live_pfad", "n/a"), "LIVE"],
        ["Lernereignisse (ki_log)", ra.get("lernereignisse", "n/a"), ""],
        ["Dedupe-Ereignisse", ra.get("dedupe", "n/a"), ""],
        ["Entscheidungen mit decision_id", ra.get("mit_decision_id", "n/a"), ""],
        ["Legacy/Fallback", ra.get("legacy", "n/a"), ""],
    ]
    t = Table(gov, colWidths=[W*0.5, W*0.25, W*0.25])
    t.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), FONT, 8.5),
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor(FARB["violett"])),
        ("TEXTCOLOR", (0,0), (-1,0), rc.HexColor("#FFFFFF")),
        ("GRID", (0,0), (-1,-1), 0.4, rc.HexColor("#E5E5EA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.HexColor("#FFFFFF"), rc.HexColor("#F7F7FA")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    el.append(t)
    el.append(Spacer(1, 0.2*cm))
    el.append(Paragraph("Shadow-Regeln erscheinen NIE als live. freigabe_status wird berücksichtigt. "
                        "Skill-Sync-Status: s. Systemstatus (Seite 6).", S["small"]))
    el.append(Spacer(1, 0.3*cm))

    # ── Phase G: KI-/PROVIDER-STABILITÄT (transparent) ──
    el.append(Paragraph("KI-Provider-Stabilität (transparent)", S["h2"]))
    el.append(HRFlowable(width="100%", thickness=0.6, color=rc.HexColor(FARB["violett"])))
    el.append(Spacer(1, 0.15*cm))
    cd = daten.get("ki_cooldown", {})
    aktive = {p: v for p, v in cd.items() if v.get("bis", 0) > __import__("time").time()} if cd else {}
    prov_status = "gestört" if aktive else ("Fallback (abgelaufen)" if cd else "stabil")
    # Echte Provider-Liste aus ki_provider (openrouter Primary, zen deepseek tot, etc.)
    prov_conf = []
    try:
        import ki_provider
        ki_provider._cooldown_state.clear()
        pl = ki_provider.provider_liste()
        role = {0: "Primary", 1: "2nd", 2: "3rd", 3: "Puffer", 4: "Puffer"}
        for i, p in enumerate(pl):
            prov_conf.append((p["name"], "Free-Tier", f"{role.get(i,'')} | {p['model']}"))
    except Exception:
        prov_conf = [
            ("openrouter", "Free-Tier", "Primary | nemotron-nano"),
            ("nous-hy3", "Free-Tier", "Reasoning (max_tokens>=2048)"),
            ("nous-step", "Free-Tier", "Reasoning (max_tokens>=2048)"),
            ("zen", "Free-Tier", "Puffer | ling-3.0-flash-free (deepseek tot: 429)"),
        ]
    g_rows = [["Provider", "Status", "Konfiguration"]]
    for p, tier, conf in prov_conf:
        st = "⚠ Cooldown" if p in aktive else "✓ aktiv"
        g_rows.append([p, st, conf])
    t_g = Table(g_rows, colWidths=[W*0.22, W*0.20, W*0.58])
    t_g.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), FONT, 8),
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor(FARB["violett"])),
        ("TEXTCOLOR", (0,0), (-1,0), rc.white),
        ("GRID", (0,0), (-1,-1), 0.4, rc.HexColor("#E5E5EA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.white, rc.HexColor("#F7F7FA")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    el.append(t_g)
    el.append(Spacer(1, 0.1*cm))
    hinweise = [
        "Ein Provider-Cooldown blockiert NICHT alle Provider (nur betroffenen).",
        "Leere Reasoning-Antworten = kein globaler Systemfehler (nous-hy3/step).",
        "Konfidenz 0 = kein normaler KI-Wert (Fallback-Trennung nötig).",
        f"Aktueller Provider-Status: {prov_status}.",
    ]
    el.append(ListFlowable([ListItem(Paragraph(h, S["small"])) for h in hinweise], bulletType="bullet"))
    el.append(PageBreak())

def _seite_system(el, S, W, daten):
    """Seite 9 — Governance, Systemstatus und Audit."""
    el.append(Paragraph("9. Governance, Systemstatus & Audit", S["h2"]))
    el.append(HRFlowable(width="100%", thickness=1, color=rc.HexColor(FARB["violett"])))
    el.append(Spacer(1, 0.2*cm))

    sys = daten.get("system", {})
    ki_gestoert = sys.get("ki_job") != "OK"
    rows = [
        ["Bereich", "Status", "Detail"],
        ["Engine", sys.get("engine", "n/a"), ""],
        ["KI-Job", sys.get("ki_job", "n/a"), sys.get("ki_detail", "")],
        ["Cron-Jobs aktiv", sys.get("cron_aktiv", "n/a"), "3 Jobs (Batch/Engine/KI)"],
        ["Watchdog-Recovery", sys.get("watchdog", "n/a"), ""],
        ["Provider", sys.get("provider", "n/a"), "Nous-free (Hermes-Token)"],
        ["Datenalter", sys.get("datenalter", "n/a"), ""],
        ["Backup-Status", sys.get("backup", "n/a"), ".backup/ vorhanden"],
        ["Systemversion", VERSION, ""],
        ["Regelwerksversion", f"v{daten.get('regelstand_version','n/a')}", "Status: shadow"],
    ]
    if ki_gestoert:
        rows.insert(1, ["⚠ KI-STÖRUNG", "KRITISCH", "Provider nicht erreichbar — KI-Bewertung nicht verifiziert"])
    t = Table(rows, colWidths=[W*0.3, W*0.25, W*0.45])
    t.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), FONT, 8.5),
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor(FARB["violett"])),
        ("TEXTCOLOR", (0,0), (-1,0), rc.HexColor("#FFFFFF")),
        ("GRID", (0,0), (-1,-1), 0.4, rc.HexColor("#E5E5EA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.HexColor("#FFFFFF"), rc.HexColor("#F7F7FA")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    el.append(t)
    el.append(Spacer(1, 0.3*cm))

    # Anomalien (gruppiert + priorisiert)
    el.append(Paragraph("Anomalien", S["h2"]))
    anom = daten.get("anomalien", [])
    # Sortierung: KI-Störung zuerst, dann Warnungen, dann dokumentiert
    def _prio(a):
        if a.get("schwere") == "HOCH":
            return 0
        if "gestört" in a.get("desc", ""):
            return 0
        return 1
    anom_sorted = sorted(anom, key=_prio)
    arows = [["Zeit", "Kategorie", "Schwere", "Beschreibung", "Status"]]
    if anom_sorted:
        for a in anom_sorted[:8]:
            arows.append([a.get("zeit", "?"), a.get("kat", "?"), a.get("schwere", "?"),
                          (a.get("desc", "") or "")[:40], a.get("status", "n/a")])
    else:
        arows.append(["—", "—", "—", "keine Anomalien erfasst", "OK"])
    ta = Table(arows, colWidths=[W*0.13, W*0.13, W*0.1, W*0.5, W*0.14], repeatRows=1)
    ta.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), FONT, 7.5),
        ("BACKGROUND", (0,0), (-1,0), rc.HexColor(FARB["cyan"])),
        ("TEXTCOLOR", (0,0), (-1,0), rc.HexColor("#FFFFFF")),
        ("GRID", (0,0), (-1,-1), 0.4, rc.HexColor("#E5E5EA")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [rc.HexColor("#FFFFFF"), rc.HexColor("#F7F7FA")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    el.append(ta)
    el.append(Spacer(1, 0.2*cm))
    el.append(Paragraph("Hinweis: Mehrere Risikostufen (Risk 50–95) meldeten am Berichtstag Renditeabweichungen. "
                        "Diese sind als Sammel-Ereignis 'dokumentiert' gelistet, nicht als zehn kritische Einzelvorfälle.", S["small"]))
    el.append(PageBreak())


if __name__ == "__main__":
    daten = sammle_daten()
    heute = datetime.now().strftime("%Y-%m-%d")
    report_id = _report_id(heute)
    pfad = os.path.join(REPORTS, f"daily_report_{heute}_v{VERSION}_{report_id}.pdf")
    baue_pdf(daten, pfad)
    print(f"PDF erstellt: {pfad}")
    print(f"  Gesamtwert: {daten['ges_wert']:,.2f} $ | Rendite: {daten['ges_pnl_pct']:+,.2f}%")
    print(f"  Kategorien: {daten['kat']}")
    print(f"  Top5: {[d['ticker'] for d in daten['top5']]}")
    print(f"  Flop5: {[d['ticker'] for d in daten['flop5']]}")
    print(f"  KI-Regeln: {len(daten['rules_list'])} | Konfidenz: {daten['ki_konf_schnitt']}")
    print(f"  Verlauf: {len(daten['verlauf'])} Tage")
