"""
Micro-Trader — Tages-Snapshot (Backbone für 7-Tage-Graph)
Speichert täglich: Gesamtwert, investiert, PnL, KI-Konfidenz-Schnitt, pro Kategorie.
Rekonstruiert rückwirkend aus depot_*.json / etf_*.json / spec_depots/*.json "historie".

Genutzt von report_pdf.py für den 7-Tage-Verlauf-Graph.
"""
import os
import json
import glob
from datetime import datetime, date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(BASE, "tagesverlauf.json")


def _ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except Exception:
        return None


def lade_depots_flat():
    """Alle Depots als flache Liste (Ticker, Kategorie, start, wert, pnl_pct)."""
    out = []
    # Einzel-Depots: spec_depots/TICKER.json
    for f in sorted(glob.glob(os.path.join(BASE, "spec_depots_paper", "*.json"))
                    + glob.glob(os.path.join(BASE, "spec_depots", "*.json"))):
        if "summary" in f:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
            ticker = d.get("ticker") or os.path.splitext(os.path.basename(f))[0]
            start = d.get("start", 0) or d.get("einstandswert", 0) or d.get("start_wert", 0) or 0
            shares = d.get("shares", 0) or 0
            avg = d.get("avg_price", d.get("aktuell", 0)) or 0
            bargeld = d.get("bargeld", 0) or 0
            wert = bargeld + shares * avg
            pnl_pct = ((wert - start) / start * 100) if start > 0 else 0
            out.append({"ticker": ticker, "kat": "spec", "start": start, "wert": wert, "pnl_pct": pnl_pct})
        except Exception:
            pass
    # Sammeldepots: depot_*.json (positions), etf_*.json
    for pat, kat in [("depot_*.json", "aktien"), ("etf_*.json", "etf")]:
        for f in sorted(glob.glob(os.path.join(BASE, pat))):
            if "summary" in f:
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
                base_name = os.path.splitext(os.path.basename(f))[0]
                start_wert = d.get("start_wert", 0) or 0
                if "positions" in d and isinstance(d["positions"], dict):
                    # Startwert gehört EINMAL pro Depot, nicht pro Position.
                    # Vorher stand hier `start_wert` in jeder Positionszeile,
                    # wodurch ein 200-$-Depot mit 6 Positionen 1.200 $
                    # Start zählte (Summe 20.000 statt 4.997,97).
                    # Die Positionen werden als Blöcke bewertet:
                    # Bargeld + Summe(shares*avg) = Depotwert.
                    positionen = d["positions"]
                    ges_pos_wert = 0.0
                    anzahl_pos = 0
                    for ticker, pos in positionen.items():
                        shares = (pos or {}).get("shares", 0) or 0
                        if shares <= 0:
                            continue
                        avg = (pos or {}).get("avg_price", (pos or {}).get("aktuell", 0)) or 0
                        ges_pos_wert += shares * avg
                        anzahl_pos += 1
                    bargeld = d.get("bargeld", 0) or d.get("cash", 0) or 0
                    depot_wert = bargeld + ges_pos_wert
                    pnl_pct = ((depot_wert - start_wert) / start_wert * 100) if start_wert > 0 else 0
                    out.append({"ticker": base_name, "kat": kat, "start": start_wert,
                                "wert": depot_wert, "pnl_pct": pnl_pct,
                                "parent": base_name, "positionen": anzahl_pos})
                else:
                    ticker = d.get("ticker") or base_name
                    start = d.get("start", start_wert) or 0
                    shares = d.get("shares", 0) or 0
                    avg = d.get("avg_price", d.get("aktuell", 0)) or 0
                    bargeld = d.get("bargeld", 0) or 0
                    wert = bargeld + shares * avg
                    pnl_pct = ((wert - start) / start * 100) if start > 0 else 0
                    out.append({"ticker": ticker, "kat": kat, "start": start, "wert": wert, "pnl_pct": pnl_pct})
            except Exception:
                pass
    return out


def berechne_heute():
    depots = lade_depots_flat()
    ges_wert = sum(d["wert"] for d in depots)
    ges_start = sum(d["start"] for d in depots if d["start"] > 0)
    # pro Kategorie
    kat = {}
    for d in depots:
        k = d["kat"]
        kat.setdefault(k, {"wert": 0, "start": 0})
        kat[k]["wert"] += d["wert"]
        if d["start"] > 0:
            kat[k]["start"] += d["start"]
    # KI-Konfidenz-Schnitt (ki_log letzte 24h)
    konf = None
    kp = os.path.join(BASE, "ki_log.json")
    if os.path.exists(kp):
        try:
            ki = json.load(open(kp, encoding="utf-8"))
            vals = [e.get("konfidenz") for e in ki if isinstance(e.get("konfidenz"), (int, float))]
            if vals:
                konf = sum(vals) / len(vals)
        except Exception:
            pass
    return {
        "datum": datetime.now().strftime("%Y-%m-%d"),
        "ges_wert": round(ges_wert, 2),
        "ges_start": round(ges_start, 2),
        "pnl": round(ges_wert - ges_start, 2),
        "pnl_pct": round(((ges_wert - ges_start) / ges_start * 100) if ges_start > 0 else 0, 2),
        "kategorien": {k: {"wert": round(v["wert"], 2),
                           "start": round(v["start"], 2),
                           "pnl_pct": round(((v["wert"] - v["start"]) / v["start"] * 100) if v["start"] > 0 else 0, 2)}
                       for k, v in kat.items()},
        "ki_konfidenz": round(konf, 1) if konf else None,
    }


def lade_snapshots():
    if os.path.exists(SNAP):
        try:
            return json.load(open(SNAP, encoding="utf-8"))
        except Exception:
            pass
    return []


def rekonstruiere_historie():
    """Fallback: letzter Wert pro Tag aus depot_*/etf_*/spec historie."""
    tage = {}
    # Modus aufloesen: die aktiven Depots heissen *_paper.json. Ein Glob
    # ohne Suffix traf ins Leere und liess Aktien- und ETF-Depots ganz
    # ausser Betracht (der Fallback meldete 168 $ statt ~5.000 $).
    muster = ["depot_*_paper.json", "etf_*_paper.json",
              "spec_depots_paper/*.json", "spec_depots/*.json"]
    for pat in muster:
        for f in glob.glob(os.path.join(BASE, pat)):
            if "summary" in f:
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            h = d.get("historie")
            if not isinstance(h, list):
                continue
            for e in h:
                z = _ts(e.get("zeit", ""))
                if not z:
                    continue
                tag = z.strftime("%Y-%m-%d")
                w = e.get("wert")
                if w is None:
                    continue
                # Je Depot den LETZTEN Eintrag des Tages nehmen, dann
                # ueber alle Depots des Tages summieren. Ein Mittelwert
                # ueber Depots ist kein Portfoliowert.
                slot = tage.setdefault(tag, {"_werte": {}, "_kat": {}})
                slot["_werte"][f] = w
                # Kategorie aus dem Dateinamen ableiten: das Depot-JSON
                # traegt kein zuverlaessiges Kat-Feld, der Name aber schon.
                bn = os.path.basename(f)
                if bn.startswith("depot_"):
                    kat = "aktien"
                elif bn.startswith("etf_"):
                    kat = "etf"
                else:
                    kat = "spec"
                slot["_kat"].setdefault(kat, {})
                # Je Depot den letzten Wert des Tages behalten
                slot["_kat"][kat][f] = w

    out = {}
    for t, v in tage.items():
        werte = v.get("_werte") or {}
        if not werte:
            continue
        ges = round(sum(werte.values()), 2)
        kats = {}
        for kat, kv in (v.get("_kat") or {}).items():
            kats[kat] = {"wert": round(sum(kv.values()), 2), "depots": len(kv)}
        out[t] = {"ges_wert": ges, "depots": len(werte), "kategorien": kats}
    return out


def snapshot_schreiben(force=False):
    """Heutigen Snapshot speichern (einmal pro Tag)."""
    snaps = lade_snapshots()
    heute = datetime.now().strftime("%Y-%m-%d")
    if snaps and snaps[-1].get("datum") == heute and not force:
        return snaps  # heute schon da
    # entferne alten Eintrag von heute
    snaps = [s for s in snaps if s.get("datum") != heute]
    snaps.append(berechne_heute())
    # auf 30 Tage begrenzen
    snaps = snaps[-30:]
    json.dump(snaps, open(SNAP, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    return snaps


def hole_7_tage_pro_kat(kat_name):
    """Liefert 7-Tage-Reihe für eine Kategorie (Aktien/ETF/Spec) aus Snapshots.

    Eintraege mit 'datenqualitaet' werden ausgeschlossen: ihr Startwert
    war je Depot und Position doppelt gezaehlt und taugt nicht als
    Verlauf. Der Schnitt kommt VOR der Zuschneidung auf 7 — sonst
    zeigen juengste Markierungen genau die veralteten Werte.
    """
    _k = str(kat_name or "").strip().lower()
    snaps = [s for s in lade_snapshots() if not s.get("datenqualitaet")]
    if len(snaps) >= 2:
        reihe = []
        for s in snaps[-7:]:
            kat = s.get("kategorien", {}).get(_k, {})
            reihe.append({
                "datum": s["datum"],
                "ges_wert": kat.get("wert", 0),
                "pnl_pct": kat.get("pnl_pct"),
            })
        return reihe
    # Fallback: Rekonstruktion aus den Depot-Historien. Ohne diesen
    # Zweig bekam der Bericht "keine belastbare Historie", obwohl die
    # Werte in den Depot-Dateien stehen — es gab nur einen gültigen
    # Snapshot, und die Zweier-Bedingung griff nicht.
    rec = rekonstruiere_historie()
    # _k ist oben bereits klein geschrieben (Snapshot- und Fallback-Zweig
    # nutzen dieselbe Angleichung).
    reihe = []
    for t in sorted(rec.keys())[-7:]:
        kat = (rec[t].get("kategorien") or {}).get(_k)
        if not kat:
            continue
        reihe.append({
            "datum": t,
            "ges_wert": kat.get("wert", 0),
            "pnl_pct": None,
        })
    return reihe


def hole_7_tage():
    """Liefert 7-Tage-Reihe für Graph (Snapshot + Rekonstruktion als Fallback).

    Markierte Eintraege (fehlerhafter Startwert) werden ausgeschlossen.
    """
    snaps = [s for s in lade_snapshots() if not s.get("datenqualitaet")]
    if len(snaps) >= 2:
        return snaps[-7:]
    # Fallback: Rekonstruktion
    rec = rekonstruiere_historie()
    reihe = []
    for t in sorted(rec.keys())[-7:]:
        reihe.append({"datum": t, "ges_wert": rec[t]["ges_wert"],
                      "pnl_pct": None, "ki_konfidenz": None})
    return reihe


if __name__ == "__main__":
    s = snapshot_schreiben()
    print(f"Snapshot gespeichert: {len(s)} Tage")
    if s:
        print(f"  Heute: {s[-1]}")
    r = hole_7_tage()
    print(f"7-Tage-Reihe: {len(r)} Punkte")
    for p in r:
        print(f"  {p['datum']}: {p.get('ges_wert', '?')}")
