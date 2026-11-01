#!/usr/bin/env python3
"""ETF-Trader – 20 Depots mit Risiko-Rating 0–95, ETF-Universum.

Analog zu batch_trader.py aber für ETFs mit risk_score (0-100).
Jedes Depot startet mit $100 → $2.000 Gesamt.
"""
import math
import sys, os, json, time, random
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from engine import scan_markt, hole_kurs, signal_aktion, ausführen, historie_aktualisieren
import strategie  # v2.20.0: zentrale Strategie-Config
import handelskosten  # 01.11.2026: Gebuehren + Slippage im Paper-Trading
import exits  # 01.11.2026: Stop-Loss / Trailing-Stop / Take-Profit
from etf_profile import ETF_TICKERS, TICKER_TO_ETF, TICKER_TO_RISK, risk_stufe

# VERDRAHTUNG 2026-09-27 (Rebuild Risiko-Controller): etf_trader hatte eigene
# hartkodierte Risikokonstanten (max_pos = 3 - risk/33, SL 0.88, TP 1.15,
# Positionsgroesse 0.5 * Bargeld, Drawdown-Lock 30%). Die sind jetzt ersetzt.
from risk_controller import (
    params as rc_params,
    pruefe_und_bremse as rc_pruefe,
    max_betrag as rc_max_betrag,
    HEBEL_TIERS,
)
import mtlog  # Zentrales Logsystem (Run-Kontext, Rotation)

def runde(x, n=2):
    """Rundet fuer das Log. None bleibt None, statt 0 zu erfinden."""
    try:
        return round(float(x), n)
    except (TypeError, ValueError):
        return None

QUIET = "--quiet" in sys.argv

# 20 ETF-Depots mit Risiko 0-95 (5er Schritte wie Aktien)
# 29.09.2026: Die zehn Stufen, die der Nutzer bestellt hat
# (10 Depots, je 200 EUR, Stufen 0 bis 90 in 10er-Schritten).
# vorher: list(range(0, 100, 5)) -> 20 Depots, auch belegt.
ETF_RISK_STUFEN = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]

def etf_pfad(risk, mode="shadow"):
    # PHASE 5 (§9): getrennte virtuelle Portfolios - PAPER nutzt etf_<risk>_paper.json
    #
    # 29.09.2026: Die zehn Testdepots tragen seq 1 im Namen, weil
    # etf_<risk>_paper.json schon von den aelteren Depots belegt
    # war. depot_erstellen() vergibt die seq selbst, deshalb heisst
    # die Reihenfolge hier: die seq-1-Datei ZUERST probieren und
    # nur dann auf den alten Namen zurueckfallen.
    #
    # Ein Umbenennen waere der sauberere Weg, wuerde aber die in
    # dashboard.py berechnete Depot-Id (etf:<risk>:<seq>) und
    # damit den Bezug zwischen Datei und Oberflaeche zerreissen.
    # Deshalb wird nicht umbenannt, sondern gesucht.
    if mode == "paper":
        kandidaten = [f"etf_{risk:03d}_01_paper.json",
                      f"etf_{risk:03d}_paper.json"]
    else:
        kandidaten = [f"etf_{risk:03d}.json"]
    for name in kandidaten:
        pfad = os.path.join(BASE, name)
        if os.path.exists(pfad):
            return pfad
    return os.path.join(BASE, kandidaten[-1])

def laden_oder_erstellen(risk, mode="shadow"):
    pfad = etf_pfad(risk, mode)
    if os.path.exists(pfad):
        with open(pfad) as f:
            data = json.load(f)
        # 29.09.2026: get(..., False) haelt ein vorhandenes None
        # bei - data.get faellt nur auf den Default zurueck, wenn
        # der Schluessel FEHLT. Die zehn Testdepots aus depot10.py
        # tragen "gesperrt": null, und darauf ist None truthy, also
        # sprang jedes Depot auf GESPERRT. Deshalb bool(...) drueber.
        d = {
            "risk": risk,
            "start_wert": data.get("start_wert") or 100,
            "bargeld": data.get("bargeld") or 100,
            "positions": data.get("positions") or {},
            "historie": data.get("historie") or [],
            "trades": data.get("trades") or [],
            "gesperrt": bool(data.get("gesperrt")),
            "peak_wert": data.get("peak_wert") or data.get("start_wert") or 100,
            "pfad": pfad,
        }
        return d
    else:
        d = {
            "risk": risk,
            "start_wert": 100,
            "bargeld": 100,
            "positions": {},
            "historie": [],
            "trades": [],
            "gesperrt": False,
            "peak_wert": 100,
            "pfad": pfad,
        }
        speichern(d)
        return d

def depot_wert(depot, kurse=None):
    """Gesamtwert eines Depots: Bargeld + Positionen.

    29.09.2026: Der Drawdown-Lock hat vorher das Bargeld gegen den
    bisherigen Höchststand gerechnet. Nach dem ersten Kauf ist das
    Bargeld niedriger, weil Geld in Positionen umgewichelt ist - das
    ist aber kein Verlust. Der Drawdown eines Depots ist der
    Rückgang des Gesamtvermögens, nicht des Bargelds.

    Ohne Kursquelle wird der Einstandspreis verwendet. Das ist
    bewusst konservativ: es zählt nichts als Gewinn, was nicht
    realisiert wurde.
    """
    wert = depot.get("bargeld") or 0.0
    for ticker, pos in (depot.get("positions") or {}).items():
        anteile = pos.get("shares") or 0
        preis = None
        if kurse and ticker in kurse:
            preis = kurse[ticker]
        if not preis or preis <= 0:
            preis = pos.get("avg_price") or 0
        wert += anteile * preis
    return wert


def speichern(d):
    data = {k: v for k, v in d.items() if k != "pfad"}
    data["aktualisiert"] = datetime.now().isoformat()
    data.setdefault("tenant_id", 1)  # PHASE 3 §2.3: Depot tenant-markieren
    data.setdefault("mode", "shadow")  # PHASE 5 §9: Portfolio-Modus
    # 01.11.2026: atomar (tmp + os.replace), damit ein Abbruch keine halbe
    # Depot-Datei hinterlaesst.
    _tmp = d["pfad"] + ".tmp"
    with open(_tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(_tmp, d["pfad"])

def etf_bewerte(etf_liste, depot_risk):
    """Bewertet ETFs für ein Depot mit bestimmtem risk-Level.
    
    Depot risk 0-95 → sucht ETFs mit passendem risk_score.
    Ähnlich wie bewerte() in engine.py aber für ETF risk_score.
    """
    # Depot-Risiko in ETF-Stufe übersetzen
    depot_stufe = int(depot_risk / 20)  # 0-95 → 0-4
    
    erlaubt = []
    for e in etf_liste:
        score = e.get("risk_score", 50)
        stufe = risk_stufe(score)
        
        # Erlaubte Stufen: depot_stufe ±1
        if abs(stufe - depot_stufe) <= 1:
            preis = e.get("preis", 0)
            budget = 100
            # Preis-Bewertung zentral aus strategie.py (v2.20.0) - konsistent mit Aktien
            preis_bonus = strategie.preis_score(preis, budget) if preis > 0 else 0
            # 🛡 Preis-Malus: ETF teurer als Budget ist mit $100 Startkapital NICHT
            # kaufbar (menge=0) -> stark abwerten, damit bezahlbare Alternativen ranken
            if preis > budget:
                preis_bonus += strategie.TOO_EXPENSIVE_MALUS
        
            # Nächste zum idealen Risk-Score gewinnt
            ideal = depot_risk
            abstand = abs(score - ideal)
            naehe = max(0, 100 - abstand * 1.5)  # 100 = perfekt, ~70 bei 20 Punkte Abweichung
            # leichter Bias zu leicht aggressiveren ETFs (Wachstum)
            growth_bonus = min(5, max(0, score - ideal) * 0.15)
        
            ges_score = naehe + growth_bonus + preis_bonus
            erlaubt.append({
                "ticker": e["ticker"],
                "score": ges_score,
                "preis": preis,
                "name": e.get("name", ""),
                "sektor": e.get("sektor", ""),
                "risk_score": score,
            })
    
    # Top 8 nach Score (Fix v2.16.7: vorher nur Top 3 -> wenn die alle zu teuer
    # waren, kaufte das Depot nie; mehr Kandidaten = bezahlbare Alternativen dabei)
    erlaubt.sort(key=lambda x: x["score"], reverse=True)
    return erlaubt[:8]

SCREENER_DATEI = os.path.join(BASE, "screener_etf_beta.json")


def etf_liste_bauen(scan):
    """Baut die ETF-Liste, die der Trader bewertet.

    Primaer aus screener_etf_beta.json (selbst berechnetes Beta,
    135 Kandidaten in 10 Stufen), im Rueckfall auf etf_profile.

    Rueckgabe: (liste, quelle) - die Quelle steht in der Logzeile,
    damit ein Lauf im Paper-Betrieb nicht lautlos mit den alten
    31 Titeln laeuft.
    """
    liste, quelle = [], "screener_etf_beta.json"
    kandidaten = {}
    if os.path.exists(SCREENER_DATEI):
        try:
            with open(SCREENER_DATEI, encoding="utf-8") as f:
                daten = json.load(f)
            for stufe, eintraege in (daten.get("stufen") or {}).items():
                for k in eintraege:
                    t = k.get("ticker")
                    if not t:
                        continue
                    kandidaten.setdefault(t, dict(k, stufe=int(stufe)))
        except Exception as e:
            if not QUIET:
                print(f"⚠️ Screener-Datei unlesbar ({e}), "
                      f"nutze etf_profile.py", flush=True)
            kandidaten = {}

    if kandidaten:
        for t, k in kandidaten.items():
            preis = scan.get(t, {}).get("aktuell", 0)
            if preis == 0:
                preis = hole_kurs(t)
            # risk_score: Beta auf 0-100, wie es etf_profile tut.
            # Das ist der Wert, den etf_bewerte() sieht.
            beta = abs(float(k.get("beta") or 0))
            liste.append({
                "ticker": t,
                "name": k.get("name", ""),
                "preis": max(preis, 0.01),
                "risk_score": int(min(100, max(0, beta * 50))),
                "sektor": "",
                "beta": beta,
                "screener_stufe": k.get("stufe"),
            })
        return liste, quelle

    # Rueckfall auf die alte, gepflegte Liste
    quelle = "etf_profile.py (Rueckfall)"
    for t in ETF_TICKERS:
        info = TICKER_TO_ETF.get(t, {})
        preis = scan.get(t, {}).get("aktuell", 0)
        if preis == 0:
            preis = hole_kurs(t)
        liste.append({
            "ticker": t,
            "name": info.get("name", ""),
            "preis": max(preis, 0.01),
            "risk_score": TICKER_TO_RISK.get(t, 50),
            "sektor": info.get("sektor", ""),
        })
    return liste, quelle


def main():
    # PHASE 5 (§9): Modus bestimmt Portfolio-Satz (shadow/paper)
    try:
        import security as _sec9
        _mode9 = _sec9.get_trading_mode(1) or "SHADOW"
    except Exception:
        _mode9 = "SHADOW"
    if _mode9 in ("PAUSED", "SUSPENDED", "REVOKED") or _mode9.startswith("LIVE"):
        if not QUIET:
            print(f"⏸ Trading-Modus {_mode9} — ETF-Trader ueberspringt Lauf.", flush=True)
        return
    _emode = "paper" if _mode9 == "PAPER" else "shadow"
    # 29.09.2026: Auswahl aus dem Screener, nicht aus
    # etf_profile.py. Begruendung: von 31 dort gepflegten ETFs
    # stehen nur 13 im Screener, und 4 davon (TQQQ, SOXL, SQQQ,
    # SPXS) sind Derivate mit monatlichem Roll, die im alten
    # Betrieb tatsaechlich gekauft wurden - SPXS in 6 Depots,
    # TQQQ in einem. Sie gehoeren nicht in eine Stufe, die
    # "breit gestreut" verspricht.
    #
    # Fehlt die Datei, laeuft der Trader mit etf_profile weiter.
    # Ein fehlender Datenstand soll den Handel anhalten koennen,
    # aber er soll sichtbar sein - deshalb die Meldung.
    etf_liste, quelle = etf_liste_bauen(scan_markt(ETF_TICKERS))
    if not QUIET:
        print(f"\U0001F9E0 ETF-Auswahl: {len(etf_liste)} ETFs aus "
              f"{quelle}", flush=True)
    
    if not QUIET:
        print(f"📦 ETF-Trader: {len(etf_liste)} ETFs", flush=True)
    
    ergebnisse = []
    
    for risk in ETF_RISK_STUFEN:
        depot = laden_oder_erstellen(risk, mode=_emode)
        
        if depot["gesperrt"]:
            if not QUIET:
                print(f"   ⛔ Risk {risk:>3} – GESPERRT", flush=True)
            ergebnisse.append((risk, depot["bargeld"], depot["bargeld"], 0, 0, 0))
            continue
        
        # Top ETFs finden
        top = etf_bewerte(etf_liste, risk)
        
        if not top:
            continue
        
        # Prüfen ob wir Positionen halten die nicht mehr passen
        zu_verkaufen = []
        for ticker, pos in list(depot["positions"].items()):
            info = TICKER_TO_ETF.get(ticker)
            if info:
                stufe = risk_stufe(info["risk_score"])
                depot_stufe = int(risk / 20)
                if abs(stufe - depot_stufe) > 1:
                    zu_verkaufen.append(ticker)
        
        for ticker in zu_verkaufen:
            pos = depot["positions"][ticker]
            preis = hole_kurs(ticker)
            if preis > 0:
                menge = pos["shares"]
                # 01.11.2026: Erloes nach Slippage und Gebuehr
                depot["bargeld"] += handelskosten.verkauf(menge, preis, art="etf")["erloes"]
                depot["trades"].append({
                    "zeit": datetime.now().isoformat(),
                    "ticker": ticker,
                    "typ": "verkaufen",
                    "menge": menge,
                    "preis": round(preis, 4),
                    "grund": f"Risk mismatch (ETF Stufe {risk_stufe(TICKER_TO_RISK.get(ticker,50))} vs Depot {int(risk/20)})",
                })
                del depot["positions"][ticker]
                mtlog.trade(aktion="verkaufen", ticker=ticker,
                          menge=runde(menge, 4), preis=runde(preis, 4),
                          grund="Risk-Mismatch", risk=risk)
                if not QUIET:
                    print(f"   🔴 ETF Verkauf {ticker} {menge:.2f}st @${preis:.2f} (Risk-Mismatch)", flush=True)
        
        # Kaufe Top-ETFs
        # VERDRAHTUNG: Positionslimit kommt aus dem Risk-Controller.
        # Vorher hartkodiert: max_pos = max(1, int(3 - risk / 33))
        _rcp = rc_params(risk)
        max_pos = _rcp["max_positions"]
        aktuelle = len(depot["positions"])

        for e in top:
            if aktuelle >= max_pos:
                break
            if e["ticker"] in depot["positions"]:
                continue

            preis = e["preis"]
            if preis <= 0:
                continue

            # VERDRAHTUNG: Positionsgroesse + Cash-Boden aus dem Controller.
            # Vorher: depot["bargeld"] * 0.5 – feste 50% des Cash, und im
            # Notfall wurde auf 100% des Bargeld hochgerechnet.
            # 01.10.2026: tier= und hebel= waren hier nicht uebergeben.
            # Ohne sie kann der Controller den Hebel-Deckel nicht anwenden
            # und gibt die volle Positionsgroesse zurueck - 140.00 * 0.1300
            # = 18.20 bei Risk 80. Genau dieser Betrag wurde 169x als
            # "Betrag 18.20 > erlaubt 15.47" blockiert, obwohl die Klemme
            # ihn auf 15.47 heruntergezogen haette (18.20 * 0.85).
            # Die Stufe kommt aus derselben Funktion wie im Tier-Gate
            # weiter unten - eine andere Stufe ergaebe einen stillen
            # Zweig, wie der hier behobene.
            _tier_bt_etf = risk_stufe(e.get("risk_score", 50))
            _hebel_bt_etf = _tier_bt_etf in HEBEL_TIERS
            budget = rc_max_betrag(depot["bargeld"], risk,
                                   tier=_tier_bt_etf,
                                   hebel=_hebel_bt_etf,
                                   vol_ratio=e.get("vol_ratio"))
            if budget <= 0:
                continue
            # Zentraler Eintritt: Tier-Gate + Positionslimit + Drawdown-Lock
            _res = rc_pruefe(risk, ticker=e["ticker"], tier=risk_stufe(e.get("risk_score", 50)),
                             preis=preis, cash=depot["bargeld"], depot_wert=depot["bargeld"],
                             anzahl_positionen=aktuelle, betrag=budget,
                             positionen=list(depot["positions"]),
                             vol_ratio=e.get("vol_ratio"),
                             # 29.09.2026: Der Drawdown war der BARGELD-
                      # Wert, nicht der Depotwert. Nach dem ersten
                      # Kauf ist das Bargeld von 200 auf 147, das
                      # sahen 26,2 % aus und sperrte das Depot.
                      # Ein Kauf ist kein Verlust: fuer den
                      # Drawdown zaehlt nur, was ANGEKAUFT wurde
                      # und wie sich der Bestand entwickelt hat.
                      # Richtig ist der Gesamtwert aus Bargeld plus
                      # Positionen zum Einstandspreis.
                      drawdown_pct=(depot["peak_wert"] - depot_wert(depot)) / max(depot["peak_wert"], 1) * 100,
                             quelle="etf_trader.kauf")
            if _res.blockiert:
                if not QUIET:
                    print(f"   🛑 {e['ticker']} abgewiesen: {_res.reason}", flush=True)
                depot["trades"].append({
                    "zeit": datetime.now().isoformat(),
                    "ticker": e["ticker"], "typ": "kauf_blockiert", "menge": 0,
                    "preis": round(preis, 4), "grund": _res.reason,
                })
                continue
            budget = min(budget, _res.max_betrag)

            # 04.10.2026 (Nutzerfreigabe): Bruchstuecke. Die
            # Aktien-Schwester rechnet seit Anfang an so
            # (2,5732 / 0,7053 Stueck) - int() war hier die einzige
            # Stelle im Projekt mit Ganzzahl-Pflicht. Gemessen waren
            # bei Budget 11,20-19,20 EUR nur 3-6 der 132 Kandidaten
            # ganzzahlig kaufbar, die Top-8 (39,68-80,33) nie.
            #
            # floor() statt int(): bei positiven Mengen identisch,
            # aber es rundet auch dann nach unten statt zur naechsten
            # ganzen Zahl zu springen. Die Menge traegt 6 Nachkomma-
            # stellen, wie die Schwester.
            menge = math.floor((budget / preis) * 1000000) / 1000000.0
            if menge <= 0:
                # 02.10.2026: dieser Zweig war still. Ein Lauf, der nicht
                # handeln kann, ist ein Ergebnis - er sagt nur nichts.
                # Die Aktien-Schwester protokolliert hier 'kauf_blockiert'
                # mit Grund, deshalb fehlte diese Klasse in der Auswertung.
                depot["trades"].append({
                    "zeit": datetime.now().isoformat(),
                    "ticker": e["ticker"], "typ": "kauf_blockiert",
                    "menge": 0, "preis": round(preis, 4),
                    "grund": (f"Budget {budget:.2f} < 1 Anteil "
                              f"@${preis:.2f} - auch als Bruchteil "
                              f"nicht darstellbar"),
                })
                continue
            kosten = menge * preis
            # Gegenprobe, keine Korrektur: mit Bruchteilen kann der
            # Kauf nie teurer werden als das Budget. Der Zweig bleibt
            # als Verteidigung, taet aber nur dann etwas, wenn
            # jemand die Mengenberechnung oben wieder veraendert -
            # dann soll er nicht stillschweigend durchlaufen.
            if kosten > depot["bargeld"]:
                menge = math.floor((depot["bargeld"] / preis)
                                   * 1000000) / 1000000.0
                if menge <= 0:
                    depot["trades"].append({
                        "zeit": datetime.now().isoformat(),
                        "ticker": e["ticker"], "typ": "kauf_blockiert",
                        "menge": 0, "preis": round(preis, 4),
                        "grund": (f"Bargeld {depot['bargeld']:.2f} < "
                                  f"1 Anteil @${preis:.2f}"),
                    })
                    continue
                kosten = menge * preis

            # 01.11.2026: Handelskosten (Gebuehr + Slippage). Menge wird ggf.
            # verkleinert, damit Kauf + Gebuehr ins Budget passen.
            _hk = handelskosten.kauf(menge, preis, min(budget, depot["bargeld"]),
                                     art="spekulativ" if _hebel_bt_etf else "etf",
                                     nachkommastellen=6)
            if _hk["abgelehnt"]:
                depot["trades"].append({
                    "zeit": datetime.now().isoformat(),
                    "ticker": e["ticker"], "typ": "kauf_blockiert",
                    "menge": 0, "preis": round(preis, 4),
                    "grund": "Handelskosten: " + _hk["abgelehnt"],
                })
                continue
            menge = _hk["menge"]
            kosten = _hk["gesamt"]

            # 02.10.2026: 'score' ist bei Kandidaten aus dem Screener
            # oft None - die Kaufzeile formatierte es mit '.0f' und
            # waere beim ersten erfolgreichen Kauf mit einem TypeError
            # abgebrochen. Der Pfad war vorher nie erreichbar, weil jede
            # Auswahl am Betragslimit scheiterte.
            _score_txt = e.get("score")
            _score_txt = ("%.0f" % _score_txt
                          if isinstance(_score_txt, (int, float))
                          else "n/a")
            depot["bargeld"] -= kosten
            depot["positions"][e["ticker"]] = {
                "shares": menge,
                "avg_price": kosten / menge,  # inkl. Handelskosten
                # VERDRAHTUNG: SL/TP je Risikostufe (vorher fix 0.88 / 1.15)
                "stop_loss": preis * _rcp["stop_loss"],
                "take_profit": preis * _rcp["take_profit"],
                "kauf_zeit": datetime.now().isoformat(),
            }
            depot["trades"].append({
                "zeit": datetime.now().isoformat(),
                "ticker": e["ticker"],
                "typ": "kaufen",
                "menge": menge,
                "preis": round(preis, 4),
                "grund": f"Score {_score_txt} | RiskScore {e['risk_score']} | {e.get('sektor', 'n/a')}",
            })
            aktuelle += 1
            if not QUIET:
                print(f"   🟢 ETF Kauf {e['ticker']} {menge:.0f}st @${preis:.2f} "
                      f"(RiskScore {e['risk_score']}, Score {_score_txt})", flush=True)
        
        # Stop-Loss / Take-Profit prüfen
        for ticker, pos in list(depot["positions"].items()):
            preis = hole_kurs(ticker)
            if preis <= 0:
                continue
            # 01.11.2026: Trailing-Stop zieht den Stop mit dem Hoch nach
            # (exits.py); dieselbe Pruefung wie bei den Aktien-Depots.
            _g = exits.pruefe_position(pos, preis, risk)
            if _g in ("stop_loss", "trailing_stop"):
                depot["bargeld"] += handelskosten.verkauf(pos["shares"], preis, art="etf")["erloes"]
                depot["trades"].append({
                    "zeit": datetime.now().isoformat(),
                    "ticker": ticker,
                    "typ": "verkaufen",
                    "menge": pos["shares"],
                    "preis": round(preis, 4),
                    "grund": "Trailing-Stop" if _g == "trailing_stop" else "Stop-Loss",
                })
                del depot["positions"][ticker]
                if not QUIET:
                    print(f"   🔴 ETF Stop-Loss {ticker} @${preis:.2f}", flush=True)
            elif _g == "take_profit":
                depot["bargeld"] += handelskosten.verkauf(pos["shares"], preis, art="etf")["erloes"]
                depot["trades"].append({
                    "zeit": datetime.now().isoformat(),
                    "ticker": ticker,
                    "typ": "verkaufen",
                    "menge": pos["shares"],
                    "preis": round(preis, 4),
                    "grund": "Take-Profit",
                })
                del depot["positions"][ticker]
                if not QUIET:
                    print(f"   🟢 ETF Take-Profit {ticker} @${preis:.2f}", flush=True)
        
        # Historie
        wert = depot["bargeld"]
        for t, p in depot["positions"].items():
            # 01.11.2026: Kurs 0 (Rate-Limit) zaehlte die Position mit 0 -
            # der Drawdown direkt darunter konnte das Depot faelschlich
            # sperren. Ohne gueltigen Kurs gilt der Einstandspreis.
            try:
                preis = hole_kurs(t)
            except Exception:
                preis = None
            if not preis or preis <= 0:
                preis = p.get("avg_price", 0) or 0
            wert += p["shares"] * preis
        
        if wert > depot["peak_wert"]:
            depot["peak_wert"] = wert
        
        dd = (depot["peak_wert"] - wert) / max(depot["peak_wert"], 1) * 100
        # VERDRAHTUNG: Drawdown-Lock kommt aus dem Risk-Controller und ist
        # damit pro Risikostufe verschieden. Vorher: fixe 30% fuer alle.
        dd_limit = rc_params(risk)["max_drawdown"]
        if dd >= dd_limit:
            depot["gesperrt"] = True
            if not QUIET:
                print(f"   ⛔ Risk {risk:>3} – Drawdown {dd:.1f}% >= Limit {dd_limit:.1f}% → GESPERRT", flush=True)
        
        depot["historie"].append({
            "zeit": datetime.now().isoformat(),
            "wert": round(wert, 2),
            "bargeld": round(depot["bargeld"], 2),
        })
        
        speichern(depot)
        
        rendite = (wert / depot["start_wert"] - 1) * 100
        ergebnisse.append((risk, wert, depot["bargeld"], rendite, len(depot["positions"]), len(depot["trades"])))
    
    # Zusammenfassung
    ges_wert = sum(e[1] for e in ergebnisse)
    ges_start = len(ETF_RISK_STUFEN) * 100
    ges_rendite = (ges_wert / ges_start - 1) * 100 if ges_start > 0 else 0
    
    if not QUIET:
        print(f"\n{'='*60}", flush=True)
        print(f"📊 ETF: {len(ergebnisse)} Depots | ${ges_wert:.2f} ({ges_rendite:+.2f}%)", flush=True)
        for risk, wert, cash, rendite, pos, trades in ergebnisse:
            farbe = "🟢" if rendite > 0 else ("🔴" if rendite < -0.1 else "⚪")
            print(f"   {farbe} Risk {risk:>3} ${wert:>6.2f} {rendite:>+6.2f}%  {pos} Pos  {trades} Trades", flush=True)
    
    # Save summary
    summary = {
        "zeit": datetime.now().isoformat(),
        "depots": len(ETF_RISK_STUFEN),
        "gesamtwert": round(ges_wert, 2),
        "gesamt_rendite": round(ges_rendite, 2),
        "trades": sum(e[5] for e in ergebnisse),
        "detail": [{"risk": r, "wert": round(w,2), "rendite": round(rend,2), "pos": p, "trades": t}
                   for r,w,_,rend,p,t in ergebnisse],
    }
    with open(os.path.join(BASE, "etf_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    # Status speichern
    try:
        from trader_status import update_status
        update_status("etf_trader", {
            "depots": len(ETF_RISK_STUFEN),
            "trades": sum(e[5] for e in ergebnisse),
            "rendite": round(ges_rendite, 2),
        })
    except Exception:
        pass

    # System-Log
    try:
        from system_log import log_eintrag
        level = "ok" if ges_rendite >= 0 else "warn"
        log_eintrag("etf", f"ETF-Lauf: {len(ETF_RISK_STUFEN)} Depots, "
                    f"{sum(e[5] for e in ergebnisse)} Trades, Rendite {ges_rendite:+.2f}%", level)
    except Exception:
        pass


if __name__ == "__main__":
    mtlog.setup()
    mtlog.log.info('Programmstart', modul=__name__)
    with mtlog.run('traderlauf', modul=__name__):
        main()
