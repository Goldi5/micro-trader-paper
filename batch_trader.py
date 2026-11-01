#!/usr/bin/env python3
"""
Batch-Trader v3 – 20 Depots mit Tier-basiertem Risiko (0–95).
Scannt einmal, bewertet je Risk-Stufe mit Tier-Bonus und füllt alle Depots.
"""
import math
import sys, os, json, time, glob
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from engine import scan_markt, bewerte, signal_aktion, ausführen, historie_aktualisieren, Depot
try:
    from security import get_broker_adapter
except Exception:
    get_broker_adapter = None
from ki_decisions import entscheide_aktien_depot, hole_kurs_fuer, get_client, MODEL, API_KEY, ZEN_URL, schreibe_ki_log
from ki_provider import call_ki  # Fallback-Kette: openai → zen → nous → openrouter


def _parse_ki_json(raus):
    """Robuster JSON-Parser fuer KI-Antworten (fängt Array/Object-Fehler ab)."""
    if not raus:
        return None
    raus = raus.strip()
    # Fall 1: Antwort beginnt mit [ (korrektes Array)
    if raus.startswith("["):
        start, end = raus.find("["), raus.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(raus[start:end])
            except Exception:
                pass
    # Fall 2: Antwort beginnt mit { (Modell hat Array-Klammern vergessen)
    if raus.startswith("{"):
        # Versuche als einzelnes Objekt
        try:
            obj = json.loads(raus)
            return [obj] if isinstance(obj, dict) else obj
        except Exception:
            pass
        # Oder als Array ohne aeussere Klammern: "{"risk":0,...}, {"risk":1,...}"
        try:
            wrapped = "[" + raus + "]"
            return json.loads(wrapped)
        except Exception:
            pass
    # Fall 3: JSON in Markdown-Codeblock
    if "```" in raus:
        import re
        m = re.search(r"```(?:json)?\s*(.*?)```", raus, re.DOTALL)
        if m:
            return _parse_ki_json(m.group(1))
    # Fall 4: Irgendwo im Text ein Array finden
    start, end = raus.find("["), raus.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raus[start:end])
        except Exception:
            pass
    return None

from risk_profile import fuer_risk_stufe, RISK_STUFEN, TIERS, TICKER_TO_TIER

# VERDRAHTUNG 2026-09-27 (Rebuild Risiko-Controller): batch_trader holt seine
# Risikokonstanten (Positionsgroesse, max. Positionen, SL, TP, Drawdown-Lock,
# Tier-Gate, Cash-Boden) ausnahmslos aus risk_controller.py.
from risk_controller import (
    params as rc_params,
    pruefe_und_bremse as rc_pruefe,
    max_betrag as rc_max_betrag,
    drawdown_pct_von as rc_drawdown_pct,
)
# 01.11.2026: Die Hebel-Erkennung in der Betragsklemmung (Kaufpfad) nutzte
# rc.HEBEL_TIERS und strategie_bt.ist_hebel_etf(), beide Namen waren aber nie
# importiert. Der NameError landete im except-Zweig "_hebel_c = True" - damit
# wurde JEDER Kauf als Hebel-ETF geklemmt (Betrag x HEBEL_ANTEIL_VON_NORMAL).
import risk_controller as rc
try:
    import strategie as strategie_bt
except Exception:  # Klemme faellt dann auf HEBEL_TIERS allein zurueck
    strategie_bt = None
import mtlog  # Zentrales Logsystem (Run-Kontext, Rotation)

def runde(x, n=2):
    """Rundet fuer das Log. None bleibt None, statt 0 zu erfinden."""
    try:
        return round(float(x), n)
    except (TypeError, ValueError):
        return None

# 01.10.2026: Kandidaten, die in diesem Lauf zweimal am Risikolimit
# gescheitert sind, werden fuer den Rest des Laufs gesperrt.
#
# BEFUND: Risk 80 hatte 16 blockierte Kaufversuche, alle auf denselben
# Ticker (CABO), alle mit "positionslimit: Depot hat 2 Positionen".
#
# Schluessel ist die Risikostufe. Pro LAUF, nicht global: beim
# naechsten Timerlauf ist die Sperre weg und der Titel wird neu
# bewertet. Eine dauerhafte Sperre wuerde einen einmal abgelehnten
# Titel nie wieder pruefen lassen - das waere Datenverlust.
_GESPERRT = {}

QUIET = "--quiet" in sys.argv

# Quelle der Aktien-Auswahl. Bis 29.09.2026 stand hier die
# handgepflegte Liste TICKER_TO_TIER aus risk_profile.py mit 686
# Symbolen. Die war der Grund fuer leere Aktien-Depots: sie war
# gepflegt statt gemessen, enthielt Titel, die es nicht mehr gab,
# und hatte keinen Anschluss an den Yahoo-Screener, der fuer die
# ETFs seit Wochen laeuft.
#
# Neu: screener_aktien_beta.json (aktien_beta.py). Wer die Datei
# nicht liest, bekommt eine leere Liste und der Trader tut nichts -
# das ist gewollt. Ein Fehlen der Quelle darf nicht dazu fuehren,
# dass auf eine alte Liste zurueckgefallen wird, denn genau das
# war der stille Pfad in die leeren Depots.
SCREENER_DATEI = os.path.join(BASE, "screener_aktien_beta.json")


def screener_kandidaten():
    """Aktien aus der geprueften Screener-Liste.

    Liefert die Titel je Risikostufe, damit die Einordnung nicht
    noch einmal geschchaetzt werden muss: der Screener hat sie
    aus 2 Jahren Tagesrenditen gegen SPY berechnet.
    """
    if not os.path.exists(SCREENER_DATEI):
        if not QUIET:
            print("FEHLER: %s fehlt. Erst aktien_beta.py laufen lassen - "
                  "es gibt keine handgepflegte Ersatzliste mehr."
                  % SCREENER_DATEI, flush=True)
        return {}
    try:
        with open(SCREENER_DATEI, encoding="utf-8") as fh:
            daten = json.load(fh)
    except Exception as e:
        if not QUIET:
            print("FEHLER: %s unlesbar: %s" % (SCREENER_DATEI, e),
                  flush=True)
        return {}
    roh = daten.get("stufen") or {}
    pro_stufe = {}
    for stufe, eintraege in roh.items():
        if isinstance(eintraege, list):
            pro_stufe[int(stufe)] = eintraege
    return pro_stufe


# 30.09.2026: Traeger fuer die depotuebergreifende Streuung.
# Ein Objekt statt einer Liste, damit die Sortenpruefung
# funktioniert: eine Liste waere am Anfang leer und damit
# falsch.
_streu_gesperrt = type("_StreuSperre", (), {"stufen": None})()


def _streu_kandidaten_liste(liste, seed, n):
    """Kandidatenliste vor der Kappung mischen.

    Absichtlich kein random: derselbe Lauf muss dasselbe Ergebnis
    liefern, sonst waere kein Paper-Ergebnis reproduzierbar. Der
    Seed ist aus Depot-ID und Risikostufe abgeleitet, damit jedes
    Depot eine andere Sicht auf dieselbe Bewertung bekommt.

    Ohne diesen Schritt ziehen alle Depots aus 200 Euro Budget auf
    dieselben zwei Titel: der Listenanfang ist nach Score sortiert
    und die score-besten Small Caps sind ueberall dieselben.
    """
    if not liste or n <= 0 or len(liste) <= n:
        return list(liste)[:max(n, 0)]
    a = list(liste)
    # Deterministischer LCG statt random.seed, damit die Funktion
    # ohne Zustand arbeitet und auch in Threads das Gleiche tut.
    s_ = seed & 0x7FFFFFFF
    for i in range(len(a) - 1, 0, -1):
        s_ = (s_ * 1103515245 + 12345) & 0x7FFFFFFF
        j = s_ % (i + 1)
        a[i], a[j] = a[j], a[i]
    return a[:n]


def alle_ticker():
    """Alle Titel aus der Screener-Liste, ohne Doppelungen."""
    pro_stufe = screener_kandidaten()
    if not pro_stufe:
        return []
    gesehen = set()
    raus = []
    for stufe in sorted(pro_stufe):
        for k in pro_stufe[stufe]:
            t = (k.get("ticker") or "").strip().upper()
            if not t or t in gesehen:
                continue
            gesehen.add(t)
            raus.append(t)
    return raus

def laden_oder_erstellen(risk, mode="shadow"):
    """Lädt Depot oder erstellt neues.
    PHASE 5 (§9): mode='shadow' -> depot_<risk>.json (Bestand, rückwärtskompatibel),
    mode='paper' -> depot_<risk>_paper.json (frisches virtuelles Portfolio,
    Shadow-Positionen werden NIE übernommen)."""
    if mode == "paper":
        pfad = os.path.join(BASE, f"depot_{risk:03d}_paper.json")
    else:
        pfad = os.path.join(BASE, f"depot_{risk:03d}.json")
    if os.path.exists(pfad):
        with open(pfad) as f:
            data = json.load(f)
        d = Depot(start_wert=data.get("start_wert", 100), risk=risk, depot_pfad=pfad)
        d.bargeld = data.get("bargeld", 100)
        d.positions = data.get("positions", {})
        d.historie = data.get("historie", [])
        # trades defensiv: liste oder int -> liste
        _tr = data.get("trades", [])
        d.trades = _tr if isinstance(_tr, list) else []
        d.ki_letzte = data.get("ki_letzte")
        d.mode = data.get("mode", mode)
        return d
    else:
        d = Depot(start_wert=100, risk=risk, depot_pfad=pfad)
        d.mode = mode
        d.speichern()
        return d

def laden_aus_datei(pfad):
    """Laedt ein Depot aus einer existierenden Datei (fuer neu erstellte Depots)."""
    with open(pfad, encoding="utf-8") as f:
        data = json.load(f)
    d = Depot(start_wert=data.get("start_wert", 100), risk=data.get("risk", 20), depot_pfad=pfad)
    d.bargeld = data.get("bargeld", 100)
    d.positions = data.get("positions", {})
    d.historie = data.get("historie", [])
    # trades defensiv: liste oder int -> liste
    _tr = data.get("trades", [])
    d.trades = _tr if isinstance(_tr, list) else []
    d.ki_letzte = data.get("ki_letzte")
    d.mode = data.get("mode", "paper")
    # BUG-FIX: alle Felder uebernehmen, die die Depot-Klasse nicht
    # kennt - etwa "empfehlung" mit erlaubte_ticker, min_score und
    # tier_ignore. Ohne das waeren sie schon beim Laden weg und
    # das Depot haette wieder das ganze 657-Titel-Universum als
    # Kandidatenmenge.
    # Die klassischen Felder werden bewusst ausgenommen, damit
    # self.zusatz nicht den echten Depot-Zustand ueberschreibt.
    _BEKANNT = {
        "start_wert", "risk", "bargeld", "positions", "historie",
        "trades", "ki_letzte", "aktualisiert", "tenant_id", "mode",
        "exchanges",
    }
    d.zusatz = {k: v for k, v in data.items() if k not in _BEKANNT}
    return d


def _ist_depotdatei(pfad):
    """True, wenn die Datei ein Depot ist und keine Ableitung.

    Ein Name allein sagt nichts: etf_summary.json ist eine
    Zusammenfassung und traegt trotzdem positions, bargeld und
    start_wert. Entscheidend sind die Felder.
    """
    try:
        with open(pfad, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return False
    if not isinstance(d, dict):
        return False
    # start_wert und risk sind Pflicht; positions ist der
    # Nachweis, dass hier gehandelt wird.
    return ("start_wert" in d and "risk" in d
            and isinstance(d.get("positions"), dict))


def main():
    # ── PHASE 4 (§8): Trading-Mode-Gate — bei PAUSED/SUSPENDED/REVOKED/LIVE_*
    #    wird KEIN Handel ausgefuehrt. Nur SHADOW und PAPER erlauben Trading
    #    (LIVE_* ohne Broker-Adapter und PAPER_ONLY = grundsaetzlich gesperrt).
    try:
        import security as _sec8
        _mode8 = _sec8.get_trading_mode(1) or "SHADOW"
    except Exception:
        _mode8 = "SHADOW"
    if _mode8 in ("PAUSED", "SUSPENDED", "REVOKED") or _mode8.startswith("LIVE"):
        if not QUIET:
            print(f"⏸ Trading-Modus {_mode8} — Batch-Trader ueberspringt Lauf.",
                  flush=True)
        return
    # PHASE 5 (§9): Modus bestimmt Depot-Satz — SHADOW nutzt depot_*.json,
    # PAPER nutzt depot_*_paper.json (getrennte virtuelle Portfolios).
    _depot_mode = "paper" if _mode8 == "PAPER" else "shadow"
    ticker = alle_ticker()
    if not QUIET:
        print(f"🔍 Scanne {len(ticker)} Aktien...", flush=True)

    scan = scan_markt(ticker)

    aktien_liste = []
    for t, a in scan.items():
        a["ticker"] = t
        aktien_liste.append(a)

    if not QUIET:
        print(f"   ✅ {len(aktien_liste)} Aktien", flush=True)

    ergebnisse = []

    # Sammle alle Depot-Kontexte für parallele KI-Calls
    # FIX v2.56: alle vorhandenen Depot-Dateien scannen (nicht nur RISK_STUFEN),
    # damit neu eroeffnete Depots (depot_erstellen im Dashboard) automatisch gehandelt werden.
    depot_kontexte = []
    # 30.09.2026: Dieser Trader ist der AKTIEN-Trader. Er sah vorher
    # vier Muster und damit auch die ETF-Depots - zwei Trader, eine
    # Dateiliste, zwei Wahrheiten ueber dasselbe Portfolio. Und
    # etf_summary.json, eine Zusammenfassungsdatei, wurde als 11.
    # Depot mitverrechnet (gemessen: 21 Treffer statt 10).
    #
    # Die Trennung gehoert hierher und nicht in die Verarbeitung:
    # eine Depotart je Trader.
    _depot_pfade = []
    _depot_pfade += glob.glob(os.path.join(BASE, "depot_*_paper.json"))
    _depot_pfade += glob.glob(os.path.join(BASE, "depot_*.json"))
    # Und trotzdem kein blosser Dateinamensfilter: eine Datei mit
    # risk UND start_wert UND positions ist ein Depot. Alles andere
    # ist eine Ableitung und wird hier nicht gehandelt.
    _depot_pfade = [p for p in _depot_pfade
                    if _ist_depotdatei(p)]
    # 30.09.2026: Die Spekulationsdepots sind aus der Liste
    # raus. Sie gehoeren spec_trader.py.
    #
    # Vorher standen hier zwei Globs auf spec_depots/ und
    # spec_depots_paper/, damit der Batch-Trader auch die
    # Spekulationsdepots mit den Aktien-Kandidaten handelte.
    # Nachgewiesen: acht von zehn Spec-Depots hatten eine
    # Position aus der Aktienliste (STUB, TDC, UEC, UMAC, UMC,
    # WRBY) - also genau die Titel, die der Aktien-Screener
    # fuer die jeweilige Risikostufe vorschlug.
    #
    # Das erzeugte zwei Fehler zugleich:
    #  1) Doppelte Zustandsfuehrung. spec_trader rechnet mit
    #     "shares" (ein Ticker je Depot), batch_trader schreibt
    #     in "positions". Beides stand in derselben Datei:
    #     BBAI hatte positions={WRBY} und shares=0. Der Wert
    #     lag in der einen Struktur, der Trader las die andere,
    #     die Position wurde nie verkauft.
    #  2) Falsches Universum. Spekulationsdepots sollen Meme-,
    #     Biotech- und AI-Titel handeln, nicht die Titel des
    #     Aktien-Screeners.
    #
    # Die Trennung ist vorgesehen: micro-trader-pipeline.py
    # ruft batch_trader, etf_trader und spec_trader nacheinander
    # auf, je einen fuer seine Depotart.
    _seen = set()
    for _pf in _depot_pfade:
        if _pf in _seen:
            continue
        _seen.add(_pf)
        try:
            with open(_pf, encoding="utf-8") as _fh:
                _dd = json.load(_fh)
            risk = int(_dd.get("risk", 20))
            params = fuer_risk_stufe(risk)
            # Depot-Eigene Empfehlung uebernehmen. Ohne diesen Block
            # arbeitet das Scoring das ganze 657-Titel-Universum ab
            # und ignoriert erlaubte_ticker sowie min_score des
            # Depots. Nachgewiesen im Lauf vom 27.09.2026, 19:53:
            # Risk 25 kaufte LRCX, obwohl in seiner erlaubten Liste
            # nur VYM, VNQ, XLU, VEA, XLP standen.
            _empfehlung = _dd.get("empfehlung") or {}
            _erlaubt = _empfehlung.get("erlaubte_ticker") or []
            if _erlaubt:
                params = dict(params)
                params["erlaubte_ticker"] = list(_erlaubt)
                # min_score aus der Empfehlung nur uebernehmen,
                # wenn einer gesetzt ist. Sonst bliebe der Wert aus
                # fuer_risk_stufe stehen, und genau der ist fuer
                # ETF-Depots unerreichbar (47 gefordert, 17,6
                # erreicht).
                if _empfehlung.get("min_score") is not None:
                    params["min_score"] = _empfehlung["min_score"]
            depot = laden_aus_datei(_pf) if os.path.exists(_pf) else laden_oder_erstellen(risk, mode=_depot_mode)
        except Exception as _e:
            if not QUIET:
                print(f"   ⚠ Depot uebersprungen ({os.path.basename(_pf)}): {_e}", flush=True)
            continue
        budget = depot.start_wert
        # 🛡 v2.16.8: Aktien-Liste NACH Preis filtern BEVOR bewertet wird.
        # bewerte() vergibt hohe Scores an teure Large-Caps -> top[:10] waeren fast
        # nur unbezahlbare -> nach Budget-Filter bliebe nichts. So bewertet bewerte()
        # nur Aktien, die das Depot mit 80% des Bargelds kaufen KANN.
        # v2.20.2: Budget-Filter pos_size-basiert (vorher bargeld*0.8 → zu eng, Risk 70 kaufte nie)
        # Erlaubt Aktien, die das Depot zu ~1.5x der Zielpositionsgroesse kaufen kann.
        kauf_budget = depot.bargeld * params["position_size"] * 1.5
        bezahlbare = [a for a in aktien_liste if 0 < a.get("aktuell", 0) <= kauf_budget]
        # (TEMP-DEBUG-Block entfernt in Phase 4 — schrieb _budget_debug.txt)
        if not bezahlbare:
            # Fallback: nur Ticker mit gueltigem Preis > 0
            mit_preis = [a for a in aktien_liste if a.get("aktuell", 0) > 0]
            bezahlbare = [min(mit_preis, key=lambda a: a["aktuell"])] if mit_preis else []
        # tier_ignore gehoert zum Depot, nicht zu den
        # risk_params. Ohne eigene erlaubte Liste bleibt es False
        # und das Verhalten ist unveraendert.
        _tier_ignore = bool(_empfehlung.get("tier_ignore")) and bool(
            _empfehlung.get("erlaubte_ticker"))
        top = bewerte(bezahlbare, budget, risk_params=params,
                      tier_ignore=_tier_ignore)
        alle_kandidaten = [{
                "ticker": t["ticker"],
                "preis": t.get("preis", 0),  # bewerte() gibt 'preis' zurück, nicht 'aktuell'
                "score": t.get("score", 0),
                "tier": t.get("tier", 2),
                "atr": t.get("atr", 0),
                "vol_ratio": t.get("vol_ratio", 1),
            } for t in top[:10]]  # Top 10 bewerten, dann filtern
        
        # v2.20.2: Budget-Filter (Sicherung) nutzt jetzt pos_size-basiertes kauf_budget (s.o.)
        kandidaten = [k for k in alle_kandidaten if 0 < k["preis"] <= kauf_budget]
        # Fallback (User-Idee): keine bezahlbaren Kandidaten -> günstigsten mit
        # gueltigem Preis aus der Gesamtliste nehmen, damit das Depot IMMER
        # mindestens eine Kauf-Option hat
        if not kandidaten and alle_kandidaten:
            mit_preis = [k for k in alle_kandidaten if k["preis"] > 0]
            kandidaten = [min(mit_preis, key=lambda k: k["preis"])] if mit_preis else []
        # 30.09.2026: Streuung vor der Kappung.
        #
        # Vorher stand hier nur "kandidaten[:5]". Weil bewerte()
        # nach Score sortiert und das Kaufbudget bei 200 Euro
        # klein ist, waren die score-besten Titel in mehreren
        # Depots identisch: sieben Aktien-Depots, zwei Ticker
        # (UDR, WRBY).
        #
        # Die Liste wird deshalb vor der Kappung gemischt. Der
        # Seed kommt aus Depot-ID und Risikostufe, damit derselbe
        # Lauf immer dieselbe Auswahl trifft - ein Paper-Ergebnis
        # muss reproduzierbar sein.
        # 30.09.2026: Zweite Stufe der Streuung.
        #
        # Die Mischung oben wirkt je Depot, aber nicht
        # depotuebergreifend. Weil der Seed aus Risikostufe und
        # Depot-Pfad kommt und die Kandidatenliste bei hohen
        # Stufen fast gleich ist (Risk 80: 115 bewertet, Risk 90:
        # 113, beide aus derselben 143er-Menge), zogen zwei
        # Depots denselben Erstkandidaten: ZETA war in Risk 80
        # und Risk 90 erster Kandidat.
        #
        # Deshalb wird zusätzlich festgehalten, welche Titel in
        # diesem Lauf schon vergeben wurden. Das entspricht dem
        # Muster aus dem KI-Fallback (_bereits) und ist
        # deterministisch: die Reihenfolge der Depots ist fest.
        _k_stufen = getattr(_streu_gesperrt, "stufen", None)
        if _k_stufen is None:
            _k_stufen = set()
            _streu_gesperrt.stufen = _k_stufen

        if len(kandidaten) > 5:
            # Der Seed braucht etwas, das je Depot verschieden
            # ist. Depot.depot_id gibt es nicht (die Klasse kennt
            # nur start_wert, risk, bargeld, positions, historie,
            # trades, ki_letzte, zusatz, depot_pfad). depot_pfad
            # ist eindeutig und steht immer zur Verfuegung.
            _seed = abs(hash("%s:%s" % (risk, depot.depot_pfad))) % 1000003
            kandidaten = _streu_kandidaten_liste(kandidaten, _seed, 5)

        # Bereits in diesem Lauf vergeben? Dann aus der Liste
        # nehmen, aber nur wenn danach noch etwas uebrig bleibt -
        # ein leeres Depot ist schlechter als eine Doppelposition.
        _offen = [k for k in kandidaten
                  if (k["ticker"] or "").upper() not in _k_stufen]
        if _offen:
            kandidaten = _offen
        if kandidaten:
            _k_stufen.add((kandidaten[0]["ticker"] or "").upper())
        kandidaten = kandidaten[:5]  # max 5 Kandidaten pro Depot
        
        # Priorisiere: Nur Depots mit negativer Rendite ODER vielen Trades bekommen KI
        wert = depot.wert()
        rendite_pct = (wert / depot.start_wert - 1) * 100
        anzahl_pos = len(depot.positions)
        anzahl_trades = len(depot.trades)
        
        # KI-Priorität score (höher = dringender)
        prioritaet = 0
        if rendite_pct < -2:
            prioritaet += 3
        elif rendite_pct < -0.5:
            prioritaet += 2
        if anzahl_pos >= 3:
            prioritaet += 2
        if anzahl_trades > 0 and anzahl_trades % 5 == 0:
            prioritaet += 1
        
        # BUG-FIX: eindeutige Depot-ID. Zwei Depots koennen dieselbe
        # Risikostufe haben, und die KI antwortet nur mit "risk".
        # Ohne eigene ID traf die Rueckzuordnung immer das zuerst
        # gelistete Depot - im Lauf vom 27.09.2026, 20:00, bekam so
        # das Alt-Depot die KI-Entscheidung und das Empfehlungsdepot
        # blieb leer (Risk 25 kaufte LRCX statt eines erlaubten ETF).
        _did = "D%02d" % len(depot_kontexte)
        depot_kontexte.append((risk, params, depot, kandidaten,
                               prioritaet, _did))
    
    # ── BÖRSE-AWARE KI-FILTER (v2.15.8) ─────────────────────────────
    # Nur Depots mit mind. einer OFFENEN Position an einer gerade offenen
    # Börse brauchen KI-Bewertung. Das spart KI-Calls, wenn die jeweilige
    # Börse zu ist (z.B. Xetra zu, keine DE-Positionen -> keine Calls).
    # exchanges-Feld (von engine.py) hat Vorrang; Fallback auf Suffix-Mapping.
    try:
        from boersen import boerse_fuer_ticker, ist_offen as _boerse_offen
        _hat_boersen_mod = True
    except Exception:
        _hat_boersen_mod = False
        def boerse_fuer_ticker(t):
            t = (t or "").upper().strip()
            for s, b in ((".DE", "XETRA"), (".F", "XETRA"), (".T", "TSE"),
                         (".HK", "HKEX"), (".L", "LSE")):
                if t.endswith(s):
                    return b
            return "US"
        def _boerse_offen(b):
            return False  # Fallback: bei Modul-Fehler lieber KI-Call machen
    def _depot_hat_offene_boerse(dep):
        pos = getattr(dep, "positions", {}) or {}
        # 🛡 Fix v2.16.8: Depot OHNE Positionen (aber mit Cash) IMMER zur KI lassen —
        # es kann neue Käufe machen. Vorher gab dieser Filter False -> leere Depots
        # wurden nie von der KI bewertet -> kauften nie nach (6 Depots mit 97-120$ Cash).
        if not pos:
            return True
        ex = getattr(dep, "exchanges", {}) or {}
        for t, p in pos.items():
            if (p.get("shares", 0) if isinstance(p, dict) else 0) <= 0:
                continue
            b = ex.get(t) or boerse_fuer_ticker(t)
            if _boerse_offen(b):
                return True
        return False
    depot_kontexte_vor = len(depot_kontexte)
    depot_kontexte = [c for c in depot_kontexte if _depot_hat_offene_boerse(c[2])]
    # 30.09.2026: Nach dem Boersen-Filter kann depot_kontexte leer
    # sein - das ist korrekt (bei geschlossener Boerse wird nicht
    # gehandelt), fuehrte aber zu einer Division durch null in der
    # Zusammenfassung und damit zu einem Abbruch nach 2,5 Sekunden.
    # Gemessen: 14 Fehlereintraege, Trader arbeite seit Stunden nicht.
    boersengesperrt = depot_kontexte_vor - len(depot_kontexte)
    if not QUIET and len(depot_kontexte) != depot_kontexte_vor:
        print(f"   🌍 Börse-Filter: {depot_kontexte_vor - len(depot_kontexte)} Depots ohne offene Börse übersprungen (spart KI-Calls)", flush=True)
    
    # Sortiere nach Priorität (höchste zuerst), nimm Top 4
    depot_kontexte.sort(key=lambda x: x[4], reverse=True)
    
    # KI-Cache: pro Depot max 1 Call pro 60 Minuten (spart API-Quota)
    KI_CACHE_DAUER = 3600  # 1 Stunde
    jetzt_ts = time.time()
    cache = {}
    cp = os.path.join(BASE, "ki_cache_batch.json")
    if os.path.exists(cp):
        try:
            with open(cp) as f:
                cache = json.load(f)
        except:
            cache = {}
    
    # Filtere: nur Depots die noch keinen Cache-Eintrag haben
    ki_kontexte_frisch = []
    for ctx in depot_kontexte:  # ALLE 20 Depots, nicht nur Top 4
        risk = ctx[0]
        letzter_call = cache.get(str(risk), {}).get("ts", 0)
        if jetzt_ts - letzter_call > KI_CACHE_DAUER:
            ki_kontexte_frisch.append(ctx)
    
    if not QUIET:
        risks = [str(c[0]) for c in ki_kontexte_frisch]
        print(f"   🤖 KI für Depots: {len(risks)} von 20 (Priorität + Cache)", flush=True)
    
    # Rate-Limit-sicher: EIN KI-Call für ALLE Depots (20 auf einmal)
    def ki_call_alleeps(args_list):
        import time as _time
        # Warte falls vorheriger Call noch nicht lange her
        last = getattr(ki_call_alleeps, "_last_call", 0)
        elapsed = _time.time() - last
        if elapsed < 35:
            _time.sleep(35 - elapsed)
        ki_call_alleeps._last_call = _time.time()
        
        # ── v2.16.8: Batches à 5 Depots statt 1 Mega-Prompt (20 Depots) ──
        # Der 20-Depot-Prompt mit max_tokens=4096 überforderte die Free-Provider
        # (>200s, Timeout, Cooldown) -> "KI nicht verfügbar" -> keine Käufe.
        # 4 Calls à 5 Depots = kleinere Prompts, schnellere Antworten, stabiler.
        def depot_to_dict(d):
            return {
                "risk": d.risk,
                "bargeld": d.bargeld,
                "positions": getattr(d, "positions", {}),
                "start": d.start_wert,
            }
        
        # BUG-FIX: das Tupel braucht 6 Elemente, weil die
        # for-Schleife 6 entpackt. Vorher waren es hier 5, und
        # _baue_prompt brach mit "not enough values to unpack
        # (expected 6, got 5)" ab - der Lauf handelte gar nicht.
        depot_dicts = [(risk, params, depot_to_dict(depot), kandidaten, prio,
                        _did)
                       for risk, params, depot, kandidaten, prio,
                       _did in args_list]
        
        def _streu_kandidaten(liste, seed, n):
            """Deterministisch mischen, dann die naechsten n nehmen.

            Absichtlich kein random: derselbe Lauf muss dieselbe
            Auswahl treffen, sonst waere kein Paper-Ergebnis
            reproduzierbar. Der Seed kommt aus der Depot-ID.
            """
            if seed % 2:
                liste = list(reversed(liste))
            # Fisher-Yates mit deterministischem Zufall
            a = list(liste)
            for i in range(len(a) - 1, 0, -1):
                seed = (seed * 1103515245 + 12345) % 2147483648
                j = seed % (i + 1)
                a[i], a[j] = a[j], a[i]
            return a[:n]

        def _baue_prompt(chunk):
            depot_infos = []
            for risk, params, dep, kandidaten, _prio, _did in chunk:
                pos_liste = []
                for t, pos in dep.get("positions", {}).items():
                    if pos.get("shares", 0) > 0:
                        preis = hole_kurs_fuer(t)
                        pnl = ((preis / pos["avg_price"]) - 1) * 100 if pos["avg_price"] > 0 else 0
                        pos_liste.append(f"{t}: {pos['shares']:.2f}st @${pos['avg_price']:.2f} (Kurs ${preis:.2f}, P&L {pnl:+.2f}%)")
                
                depot_wert = dep.get("bargeld", 0)
                for t, pos in dep.get("positions", {}).items():
                    if pos.get("shares", 0) > 0:
                        depot_wert += pos["shares"] * hole_kurs_fuer(t)
                
                # Die Kandidatenliste ist je Risikostufe
                # alphabetisch sortiert (WMT, XOM, TSCO, ...). Ohne
                # Mischen sieht die KI in mehreren Depots exakt
                # dieselben fuenf Titel und waehlt daraus denselben
                # aus: 6 Positionen, aber nur 2 verschiedene
                # Aktien. Der Zufalls-Mix mit dem Depot-Seed
                # streut die Auswahl, ohne die Reihenfolge der
                # Kandidatendatei zu veraendern.
                _kliste = list(kandidaten or [])
                if len(_kliste) > 8:
                    _seed = abs(hash(str(_did) + ":" + str(risk))) % 1000003
                    _kliste = _streu_kandidaten(_kliste, _seed, 8)
                kandidaten_str = ", ".join(
                    f"{k['ticker']} ${k['preis']:.1f} ({k['preis']/max(dep.get('bargeld',1),0.01)*100:.0f}% Cash)"
                    for k in _kliste[:8]
                )
                # 🛡 v2.16.8: Leere Depots (Cash, keine Position) explizit markieren —
                # die KI soll dort KAUFEN, nicht halten.
                hinweis = ""
                if not pos_liste and dep.get('bargeld', 0) >= 20:
                    hinweis = " [LEER: bitte KAUFEN aus den Kandidaten waehlen, die ins Budget passen!]"
                depot_infos.append(f"[{_did}] Risk {risk}: Cash "
                                  f"${dep.get('bargeld',0):.1f}, Wert ${depot_wert:.1f}, "
                                  f"Pos: {', '.join(pos_liste) if pos_liste else 'keine'}, "
                                  f"Kandidaten: {kandidaten_str or 'keine'}{hinweis}")
            
            prompt = f"Analysiere {len(chunk)} Aktien-Depots. Entscheide pro Depot: Welche Positionen KAUFEN/VERKAUFEN/HALTEN.\n\n"
            prompt += "\n".join(depot_infos)
            prompt += "\n\nAntworte NUR mit JSON-Array (KEIN Text, KEINE Erklärung):\n"
            prompt += '[{"depot_id": "D00", "risk": 55, "aktionen": [{"ticker": "SYMBOL", "aktion": "kaufen", "menge": "voll", "grund": "Depot leer, passender Kandidat"}]}, {"risk": 93, "aktionen": [{"ticker": "SYMBOL", "aktion": "kaufen", "menge": "voll", "grund": "Depot leer, passender Kandidat"}]}]'
            prompt += "\nWICHTIG: depot_id MUSS exakt die ID in eckigen Klammern am Zeilenanfang sein (BUG-FIX: mehrere Depots teilen sich eine Risk-Zahl). "
            prompt += "risk MUSS exakt die Risk-Zahl des Depots sein. Bei leeren Depots (Cash verfügbar, Pos: keine) -> IMMER KAUFEN aus den Kandidaten (erste Aktion = kaufen). Niemals leere aktionen bei leerem Depot.\n"
            # TEMP-DEBUG (v2.16.8): Prompt fuer Diagnose loggen
            try:
                if any(f"Risk {c[0]}:" in prompt for c in chunk):
                    with open(os.path.join(BASE, "_prompt_debug.txt"), "w", encoding="utf-8") as _pf:
                        _pf.write(prompt)
            except Exception:
                pass
            return prompt
        
        # 🧠 PHASE 14 (2026-09-29): Jev-Gate. Standardmaessig AUS.
        #
        # Jev ist ein ZWEITER Filter ueber der Risiko-Regel, nicht deren
        # Ersatz. Es darf einen Kauf blockieren, nie freigeben, und gibt
        # weder Menge noch Stop-Loss vor - das bleibt beim risk_controller.
        #
        # WARUM ALS FILTER UND NICHT ALS ENTSCHEIDER: im 100-Faelle-Test
        # 100/100 Antworten, aber nur 40% Uebereinstimmung mit der Regel.
        # noul<->Volatilitaet r=0,11. Als alleiniger Entscheider wuerde es
        # 58 von 74 regelkonformen Kaeufen verwerfen. Als Filter darueber
        # fand es 2 Titel mit Konzentration 30-40%, die die Regel passieren.
        #
        # PAPER_ONLY bleibt gesetzt. Einschalten: MT_JEV_GATE=1
        _JEV_AKTIV = os.environ.get('MT_JEV_GATE', '0') == '1'

        BATCH_GROESSE = 5
        results = {}
        chunks = [depot_dicts[i:i+BATCH_GROESSE] for i in range(0, len(depot_dicts), BATCH_GROESSE)]
        if not QUIET and len(chunks) > 1:
            print(f"   📦 KI-Batches: {len(chunks)} x {BATCH_GROESSE} Depots", flush=True)
        
        for chunk in chunks:
            prompt = _baue_prompt(chunk)
            try:
                raus, provider_genutzt = call_ki(
                    [
                        {"role": "system", "content": "Du antwortest NUR mit JSON. Kein Denken, keine Erklärung, nur das JSON-Array."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=2000,
                )
            except Exception as e:
                if not QUIET:
                    print(f"   ⚠ KI-Batch Fehler: {e}", file=sys.stderr, flush=True)
                raus = None
            
            if not raus:
                # KI nicht verfuegbar (Rate-Limit/Cooldown) -> naechster Batch versuchen,
                # am Ende sauber mit dem abbrechen, was wir haben.
                if not QUIET:
                    print(f"   ⚠ KI-Batch ohne Antwort (Provider gedrosselt/Cooldown) — übersprungen", flush=True)
                continue
            
            if not QUIET and provider_genutzt:
                print(f"   KI via {provider_genutzt}", flush=True)
        
        # JSON extrahieren (robust)
            entscheidungen = _parse_ki_json(raus)
            if entscheidungen is None:
                if not QUIET:
                    print(f"   ⚠ KI-JSON ungültig, Fallback für LEERE Depots = KAUFEN", flush=True)
                    print(f"   🔍 KI-RAW: {raus[:500]}", flush=True)  # DEBUG: raw response
                # Fallback: leere Depots (Cash, keine Positionen) kriegen einen
                # Kauf-Auftrag aus ihren Kandidaten — sonst würden sie bei KI-Fehlern
                # für immer leer bleiben. Depots MIT Positionen -> halten.
                entscheidungen = []
                # Konzentrations-Bremse respektieren: freien Kandidaten suchen
                try:
                    from ki_kontext import ticker_konzentration
                    from engine import max_depot_pro_ticker
                    _max_dt = max_depot_pro_ticker()
                    def _frei(t):
                        try:
                            return ticker_konzentration(t) < _max_dt
                        except Exception:
                            return True
                except Exception:
                    def _frei(t):
                        return True
                # Titel, die in diesem Lauf schon vergeben wurden. Ohne
                # diese Liste ziehen alle Depots auf dieselben zwei
                # Ticker.
                _bereits = set()
                for _c in chunk:
                    for _t in (_c[2].get("positions") or {}):
                        _bereits.add(_t.upper())
                for _c in chunk:
                    _risk, _params, _dep, _kands, _prio = _c[:5]
                    if not _dep.get("positions") and _kands:
                        # Kandidaten wählen, der
                        #  1. die Konzentrations-Bremse noch nicht
                        #     auslöst (sonst bleibt das Depot leer) und
                        #  2. nicht schon ein anderer Depot in diesem
                        #     Lauf bekommen hat.
                        # 3. unter den Resten den mit dem hoechsten
                        #    Handelsvolumen.
                        # Punkt 3 ist der eigentliche Fix: vorher
                        # stand hier next() und damit der erste
                        # Kandidat der Liste.
                        #
                        # Die Liste aus screener_aktien_beta.json ist
                        # alphabetisch sortiert, deshalb war "erster
                        # Kandidat" in Risk 30, 40, 50, 60 und 90
                        # immer derselbe Titel. Ein score-Feld gibt es
                        # dort nicht; risk_score ist die Stufe selbst
                        # und damit je Depot konstant und als
                        # Auswahlkriterium nutzlos. Gewertet wird
                        # deshalb das Handelsvolumen: bei 200 Euro
                        # Budget sind grossvolumige Titel sinnvoller
                        # als illiquide, und der Wert steht bereits
                        # in den Kandidatendaten.
                        def _rang(k):
                            return k.get("volumen") or 0
                        _freie = [k for k in _kands
                                  if _frei(k["ticker"])
                                  and (k["ticker"] or "").upper() not in _bereits]
                        if not _freie:
                            # Alle belegt: Konzentration aufgeben,
                            # aber weiterhin streuen. Sonst bleibt
                            # das Depot leer und das ist schlechter
                            # als eine Doppelposition.
                            _freie = [k for k in _kands
                                      if (k["ticker"] or "").upper() not in _bereits]
                        _gewaehlt = (max(_freie, key=_rang)
                                     if _freie else None)
                        if _gewaehlt:
                            _bereits.add((_gewaehlt["ticker"] or "").upper())
                            entscheidungen.append({
                                "risk": _risk,
                                "aktionen": [{"ticker": _gewaehlt["ticker"], "aktion": "kaufen",
                                              "menge": "voll", "grund": "Fallback: KI-JSON fehlgeschlagen, Depot leer -> Kauf aus freien Kandidaten"}]
                            })
            
            # Konvertiere zu depot_action Format
            for ed in entscheidungen:
                risk_val = ed.get("risk")
                if risk_val is not None:
                    # BUG-FIX: Rueckzuordnung ueber depot_id statt ueber risk.
                    # Zwei Depots teilen sich eine Risikostufe; "next(...)" traf
                    # immer das zuerst gelistete. Ohne ID in der Antwort (alte
                    # KI-Antwort, kaputtes JSON) gilt weiterhin das alte
                    # Verhalten, damit der Lauf nicht abbricht.
                    did_val = ed.get("depot_id")
                    depot_dict = None
                    if did_val:
                        depot_dict = next((c for c in args_list
                                            if len(c) > 5 and c[5] == did_val), None)
                        if depot_dict is None and not QUIET:
                            print(f"   ⚠ unbekannte depot_id {did_val} - "
                                  f"Fallback auf risk {risk_val}", flush=True)
                    if depot_dict is None:
                        depot_dict = next((c for c in args_list if c[0] == risk_val), None)
                    if depot_dict:
                        depot_obj = depot_dict[2]  # Depot-Objekt
                        params = depot_dict[1]
                        kandidaten = depot_dict[3]
                        aktionen = []
                        for a in ed.get("aktionen", []):
                            ticker = a.get("ticker", "")
                            akt = a.get("aktion", "halten")
                            grund = a.get("grund", "KI-Entscheidung")
                            if akt == "kaufen":
                                # 01.10.2026: _risk_bt wird VOR der
                                # Kandidatenpruefung gesetzt. Die
                                # Kandidatensperre weiter unten liest
                                # die Variable, die innere Zuweisung
                                # stand aber hinter der Bedingung
                                # 'cand and preis > 0' - bei einem
                                # Kandidaten ohne Preis wurde sie nie
                                # erreicht und der Lauf starb an einem
                                # UnboundLocalError (20x gemessen).
                                _risk_bt = int(getattr(depot_obj, "risk", risk))
                                cand = next((k for k in (kandidaten or []) if k["ticker"] == ticker), None)
                                # 🛡 Konzentrations-Bremse schon hier respektieren: wenn der
                                # KI-Ticker die Depot-Grenze erreicht hat (oder allgemein der
                                # am wenigsten konzentrierte Kandidat gewählt wird), auf einen
                                # Ausweich-Kandidaten mit der niedrigsten Depot-Konzentration
                                # ausweichen, damit Käufe über alle Kandidaten verteilt werden
                                # und leere Depots nicht unnötig leer bleiben.
                                # 01.10.2026: Kandidatensperre (siehe _GESPERRT).
                                # Ein Ticker, der in diesem Lauf zweimal am Risikolimit
                                # gescheitert ist, wird fuer den Rest des Laufs gesperrt und der
                                # naechste Kandidat aus der Liste genommen. Ohne das prueft der
                                # Aktienpfad bis zu 16x denselben Titel und scheitert 16x am
                                # selben Limit - gemessen bei Risk 80 (Ticker CABO).
                                #
                                # Die Sperre gilt pro LAUF, nicht dauerhaft: beim naechsten
                                # Timerlauf ist sie weg und der Titel wird neu bewertet.
                                _sp = _GESPERRT.setdefault(_risk_bt, {})
                                if _sp.get(ticker, 0) >= 2:
                                    _sp_frei = [k for k in (kandidaten or [])
                                                if k.get("preis", 0) > 0
                                                and k["ticker"] not in _sp]
                                    if not _sp_frei:
                                        # Kein Kandidat mehr frei. Das ist ein Ergebnis, kein
                                        # Fehler - das Depot laeuft mit dem, was es hat.
                                        break
                                    _sp_alt = _sp_frei[0]
                                    grund = (grund or "") + (
                                        " [gesperrt: %s war 2x am Risikolimit]" % ticker)
                                    ticker = _sp_alt["ticker"]
                                    cand = _sp_alt
                                
                                try:
                                    from ki_kontext import ticker_konzentration as _tk
                                    from engine import max_depot_pro_ticker as _mdt
                                    _max_dt = _mdt()
                                    # Kandidat mit der geringsten aktuellen Konzentration wählen
                                    # (schließt den bereits gewählten ticker mit ein, falls frei)
                                    _freie = [k for k in (kandidaten or [])
                                              if k.get("preis", 0) > 0 and _tk(k["ticker"]) < _max_dt]
                                    if _freie:
                                        _alt = min(_freie, key=lambda k: _tk(k["ticker"]))
                                        if _alt["ticker"] != ticker:
                                            ticker = _alt["ticker"]
                                            cand = _alt
                                            grund = (grund or "") + " [Bremse: Ausweich-Kandidat]"
                                except Exception:
                                    pass
                                # 🧠 PHASE 14 (2026-09-29): Jev als ZWEITER Filter.
                                # Jev (noul) darf NUR blockieren, nie freigeben, und gibt weder
                                # Menge noch Stop-Loss vor - das bleibt beim risk_controller.
                                # Faellt die KI aus, gilt der alte Pfad weiter.
                                # Aktiv nur mit MT_JEV_GATE=1.
                                #
                                # BEFUND aus dem 100-Faelle-Test (logs/jev_100test_v2.json):
                                #   100/100 Antworten, 0 Parse-Ausfaelle, Median 0,26s,
                                #   0,73 USD/Jahr. ABER nur 40% Uebereinstimmung mit der
                                #   Betriebsregel, 58x 'Regel KAUF / Jev NEIN' gegen 2x umgekehrt.
                                #   noul<->Volatilitaet r=0,11, noul<->Score r=0,24. Jev folgt dem
                                #   RSI, nicht dem Risikoprofil. Als Ersatz der Regel unbrauchbar,
                                #   als Filter darueber nuetzlich: es fand 2 Titel mit Konzentration
                                #   30-40%, die die Regel passieren.
                                if _JEV_AKTIV:
                                    try:
                                        import ki_entscheider as _kie
                                        _risk_g = int(getattr(depot_obj, 'risk', risk))
                                        _kv = {
                                            'ticker': ticker,
                                            'risikostufe': _risk_g,
                                            'score': round(float(cand.get('score', 0.0) or 0.0), 1),
                                            'mindestscore': round(float(
                                                params.get('min_score', 0.0) or 0.0), 1),
                                            # 01.11.2026: vorher getattr(_rcp_bt, ...) -
                                            # _rcp_bt entsteht erst weiter unten, der
                                            # NameError schaltete das Jev-Gate stumm.
                                            'beta': round(float(cand.get('beta', 0.0) or 0.0), 2),
                                            'volatilitaet_prozent': round(float(
                                                cand.get('volatilitaet', cand.get('vol', 0.0)) or 0.0), 1),
                                            'rendite_1j_prozent': round(float(
                                                cand.get('rendite_1j', cand.get('r1j', 0.0)) or 0.0), 1),
                                            'abstand_52w_hoch_prozent': round(float(
                                                cand.get('dd_52w', cand.get('dd', 0.0)) or 0.0), 1),
                                            'konzentration_prozent': 0.0,
                                        }
                                        try:
                                            from ki_kontext import ticker_konzentration as _tk2
                                            _kv['konzentration_prozent'] = round(100.0 * _tk2(ticker), 1)
                                        except Exception:
                                            pass
                                        # Echte Cache-Kennzahlen ergaenzen (RSI, MACD, Volumen, Trend)
                                        try:
                                            with open(os.path.join(BASE, '.scan_cache.json'),
                                                      encoding='utf-8') as _fh:
                                                _e = (json.load(_fh) or {}).get(ticker) or {}
                                            for _k2, _f2 in (('rsi', 'rsi'),
                                                              ('macd_bullish', 'macd_positiv'),
                                                              ('vol_ratio', 'volumen_faktor'),
                                                              ('uptrend', 'aufwaertstrend')):
                                                if _e.get(_k2) is not None:
                                                    _kv[_f2] = _e[_k2]
                                        except Exception:
                                            pass
                                        _jev_g = _kie.entscheide(_kv)
                                        if not _jev_g.get('kaufen'):
                                            _ohne = [a for a in aktionen
                                                     if not (a.get('typ') == 'kaufen'
                                                             and a.get('ticker') == ticker)]
                                            if len(_ohne) != len(aktionen):
                                                if not QUIET:
                                                    print('   🧠 Jev blockiert %s '
                                                          '(Stufe %s, p=%s, %.1fs)' % (
                                                              ticker, _jev_g.get('stufe'),
                                                              _jev_g.get('p'),
                                                              _jev_g.get('sekunden', 0)),
                                                          flush=True)
                                                aktionen = _ohne
                                                if not aktionen:
                                                    break
                                    except Exception as _jev_err:
                                        # Gate ausgefallen -> kaufen NICHT blockieren. Der
                                        # risk_controller prueft ohnehin unabhaengig.
                                        if not QUIET:
                                            print('   \u26a0 Jev-Gate nicht auswertbar: %s'
                                                  % str(_jev_err)[:80], file=sys.stderr, flush=True)

                                if cand and cand.get("preis", 0) > 0:
                                    menge_faktor = 1.0 if a.get("menge") == "voll" else 0.5
                                    # 🛡 BEFUND-3-FIX 2026-09-27: der GEPRUEFTE
                                    # Wert (pos_pct) und der GEHANDELTE Wert
                                    # (_pos_frac) wurden unabhaengig voneinander
                                    # berechnet. Jetzt wird _pos_frac EINMAL
                                    # berechnet und fuer beides verwendet –
                                    # geprueft und gehandelt sind derselbe Wert.
                                    # _risk_bt ist weiter oben
                                    # gesetzt - vor der Kandidaten-
                                    # pruefung. Hier nur noch lesen.
                                    _rcp_bt = rc_params(_risk_bt)
                                    # Tenant-Limit holen (Bestand bleibt wie vorher)
                                    _max_pos = 0.35
                                    try:
                                        import security as _sec12a
                                        _tid12a = _sec12a.resolve_tenant_for_user({"username": "admin"}) or 1
                                        _eff = _sec12a.risk_get(_tid12a, params.get("modus", "moderate"))
                                        _max_pos = float(_eff.get("position_size") or 0.35)
                                    except Exception:
                                        pass
                                    # DER eine gepruefte UND gehandelte Betrag
                                    _pos_frac = min(_rcp_bt["position_size"], _max_pos) * menge_faktor
                                    # BUG-FIX 2026-09-27: dieser Aufruf von
                                    # max_betrag ging OHNE tier und OHNE hebel,
                                    # der Controller-Aufruf weiter unten geht
                                    # MIT beiden. Fuer Hebel-ETFs lieferte die
                                    # Klemmung 34 % statt 30 %, und min() nahm
                                    # den zu grossen Wert:
                                    #     Risk 95: 3400 statt erlaubt 3000
                                    #     Risk 85: 3200 statt erlaubt 3000
                                    #     Risk 80: 3100 statt erlaubt 3000
                                    # Der Controller blockte dann korrekt -
                                    # ein zulaessiger Kauf scheiterte an der
                                    # Klemmung selbst.
                                    #
                                    # Die Hebel-Erkennung wird nicht nachgebaut.
                                    # risk_controller hat HEBEL_TIERS und
                                    # strategie.ist_hebel_etf(ticker, tier);
                                    # hier wird derselbe Aufruf mit denselben
                                    # Parametern gemacht wie der Controller.
                                    _tier_c = cand.get("tier", 2)
                                    _hebel_c = False
                                    try:
                                        _hebel_c = int(_tier_c) in rc.HEBEL_TIERS
                                        if not _hebel_c and strategie_bt is not None:
                                            _hebel_c = bool(strategie_bt.ist_hebel_etf(
                                                ticker, _tier_c))
                                    except Exception:
                                        # Im Zweifel ist es ein Hebel - die
                                        # Klemmung darf nicht zu gross sein.
                                        _hebel_c = True
                                    # Und zusaetzlich hart durch den Controller
                                    _pos_frac = min(
                                        _pos_frac,
                                        rc_max_betrag(depot_obj.bargeld, _risk_bt,
                                                      tier=_tier_c,
                                                      hebel=_hebel_c)
                                        / max(depot_obj.bargeld, 1e-9))
                                    # 🛡 PHASE 12 (v2.35.0): Tenant-Risiko- und Regel-Enforcement
                                    # BEFUND-2-FIX 2026-09-27: das except war "pass"
                                    # ("Enforcement nie fatal"). Schlaegt der Risiko-Check
                                    # FEHL, wird der Trade jetzt BLOCKIERT, nicht durchgelassen.
                                    _blockiert = False
                                    _blockgrund = ""
                                    try:
                                        import security as _sec12
                                        _tid12 = _sec12.resolve_tenant_for_user({"username": "admin"}) or 1
                                        # Positionsgroesse in % des Depotwerts (bargeldbasiert, konservativ)
                                        pos_pct = _pos_frac
                                        r12 = _sec12.enforce_risk_limits(
                                            _tid12, params.get("modus", "moderate"),
                                            pos_pct, depot_obj.start_wert)
                                        if not r12["allowed"]:
                                            _blockiert = True
                                            _blockgrund = f"enforce_risk_limits: {r12['reason']}"
                                        else:
                                            r12b = _sec12.enforce_rules(
                                                _tid12, ticker,
                                                {"kauf_count": depot_obj.positions.get(ticker, {}).get("shares", 0) > 0 and 1 or 0})
                                            if not r12b["allowed"]:
                                                _blockiert = True
                                                _blockgrund = f"enforce_rules: {r12b['reason']}"
                                    except Exception as _e:
                                        # FAIL-CLOSED: der Check ist die einzige
                                        # serverseitige Risikopruefung im Aktienpfad.
                                        _blockiert = True
                                        _blockgrund = (f"Risiko-Enforcement fehlgeschlagen "
                                                       f"({type(_e).__name__}: {_e}) - Trade blockiert")
                                    if _blockiert:
                                        if not QUIET:
                                            print(f"   🛑 RISIKO-BLOCK {ticker}: {_blockgrund}", flush=True)
                                        depot_obj.trades.append({
                                            "typ": "kauf_blockiert", "ticker": ticker,
                                            "menge": 0, "preis": round(cand.get("preis", 0), 2),
                                            "grund": _blockgrund,
                                        })
                                        # 01.10.2026: Sperrzaehler mitfuehren.
                                        _GESPERRT.setdefault(_risk_bt, {})[ticker] = (
                                            _GESPERRT.setdefault(_risk_bt, {}).get(ticker, 0) + 1)
                                        continue
                                    # 🛡 Zentraler Eintritt (risk_controller)
                                    _rc_res = rc_pruefe(
                                        _risk_bt, ticker=ticker, tier=cand.get("tier", 2),
                                        preis=cand["preis"], cash=depot_obj.bargeld,
                                        depot_wert=depot_obj.wert(),
                                        anzahl_positionen=len(depot_obj.positions),
                                        positionen=list(depot_obj.positions),
                                        betrag=depot_obj.bargeld * _pos_frac,
                                        drawdown_pct=rc_drawdown_pct(depot_obj.start_wert, depot_obj.wert()),
                                        quelle="batch_trader.ki_kauf")
                                    if _rc_res.blockiert:
                                        if not QUIET:
                                            print(f"   🛑 RISIKO-BLOCK {ticker}: {_rc_res.reason}", flush=True)
                                        depot_obj.trades.append({
                                            "typ": "kauf_blockiert", "ticker": ticker,
                                            "menge": 0, "preis": round(cand.get("preis", 0), 2),
                                            "grund": _rc_res.reason,
                                        })
                                        # 01.10.2026: Sperrzaehler mitfuehren.
                                        _GESPERRT.setdefault(_risk_bt, {})[ticker] = (
                                            _GESPERRT.setdefault(_risk_bt, {}).get(ticker, 0) + 1)
                                        continue
                                    budget = depot_obj.bargeld * _pos_frac
                                    menge = budget / cand["preis"]
                                    # Eine Menge fuer den ganzen Block (Intent,
                                    # Aktion, Ausfuehrung). Abgerundet, damit
                                    # kosten <= budget gilt.
                                    _menge_exec = math.floor(menge * 10000) / 10000.0
                                    # 🛡 PHASE 13 (v2.36.0): Order-Intent MUSS vor jeder
                                    # Ausfuehrung als Objekt entstehen (Auftrag §11).
                                    try:
                                        import security as _sec13
                                        _intent13 = _sec13.create_order_intent(
                                            tenant_id=_tid12,
                                            ticker=ticker, side="buy",
                                            quantity=_menge_exec,
                                            price=cand["preis"],
                                            mode=params.get("modus", "paper"),
                                            reason=f"KI: {grund[:50]}",
                                            decision_id=ed.get("decision_id"),
                                            rule_version=_sec13.get_rule_version(_tid12)
                                            if hasattr(_sec13, "get_rule_version") else None)
                                        _v13 = _sec13.validate_order_intent(
                                            _intent13, portfolio_value=depot_obj.start_wert)
                                        if not _v13["allowed"]:
                                            if not QUIET:
                                                print(f"   🛡 INTENT-BLOCK {ticker}: {_v13['reason']}", flush=True)
                                            continue
                                    except Exception:
                                        _intent13 = None  # Intent nie fatal (PAPER_ONLY)
                                    aktionen.append({
                                        "typ": "kaufen", "ticker": ticker,
                                        # ABRUNDEN statt RUNDEN (BUG-FIX 2026-09-27,
                                        # vgl. engine.py:583). round() hebt die
                                        # Stueckzahl in der Haelfte aller Faelle
                                        # ueber das Limit: 1.68995995 -> 1.69 ->
                                        # 1.69*1183.46 = 2000.0474 gegen ein
                                        # Budget von 2000.00. Der Controller
                                        # blockierte dann korrekt, aber grundlos.
                                        # floor haelt kosten <= budget.
                                        #
                                        # Einmal fuer den ganze Block: der
                                        # Order-Intent unten und die Aktion
                                        # hier muessen dieselbe Menge tragen.
                                        # Sonst beschreibt der Intent eine
                                        # andere Order als die Ausfuehrung.
                                        "menge": _menge_exec,
                                        "preis": cand["preis"],
                                        "grund": f"🤖 KI: {grund[:50]}",
                                        "tier": cand.get("tier", 2),
                                        "order_intent_id": (_intent13 or {}).get("order_intent_id"),
                                        "risk_check_status": (_intent13 or {}).get("risk_check_status", "pending"),
                                    })
                            elif akt == "verkaufen":
                                pos = getattr(depot_obj, "positions", {}).get(ticker, {})
                                if pos.get("shares", 0) > 0:
                                    menge_faktor = 1.0 if a.get("menge") == "voll" else 0.5
                                    preis = hole_kurs_fuer(ticker)
                                    # 🛡 Fix: Verkauf zum Preis 0/None verhindern (yfinance Rate-Limit
                                    # liefert 0 -> Erlös 0, Position verschwindet ohne Bargeld-Gutschrift)
                                    if not preis or preis <= 0:
                                        if not QUIET:
                                            print(f"   🛡 KEIN VERKAUF {ticker}: Kurs {preis} (Rate-Limit/Fehler) — Position behalten", flush=True)
                                        continue
                                    aktionen.append({
                                        "typ": "verkaufen", "ticker": ticker,
                                        "menge": round(pos["shares"] * menge_faktor, 4),
                                        "preis": preis,
                                        "grund": f"🤖 KI: {grund[:50]}",
                                    })
                        
                        ki_letzte = {
                            "typ": "decision",
                            "zeit": datetime.now().isoformat(),
                            "aktion": ed.get("analyse", ed.get("kommentar", ""))[:60] or f"KI Risk {risk_val}",
                            "konfidenz": ed.get("konfidenz", 50),
                            "analyse": ed.get("analyse", ed.get("kommentar", "")),
                            "ticker": f"Risk {risk_val}",
                        }
                        schreibe_ki_log(ki_letzte)
                        results[risk_val] = (depot_obj, params, {"aktionen": aktionen, "ki_letzte": ki_letzte})
                        # Cache aktualisieren
                        cache[str(risk_val)] = {"ts": time.time(), "aktionen": aktionen, "ki_letzte": ki_letzte}
                        
                        if not QUIET:
                            print(f"   🤖 KI[Risk {risk_val}]: {len(aktionen)} Aktionen (K:{ki_letzte['konfidenz']})", flush=True)
            if not QUIET and len(chunks) > 1:
                print(f"   ✅ Batch {chunks.index(chunk)+1}/{len(chunks)} verarbeitet", flush=True)
        return results
    
    if ki_kontexte_frisch:
        ki_ergebnisse = ki_call_alleeps(ki_kontexte_frisch) or {}
        # Cache speichern
        with open(cp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    else:
        ki_ergebnisse = {}
    
    # Restliche Depots: Cache verwenden oder leer.
    # PHASE: nutze die gesammelten depot_kontexte (inkl. custom Depots wie 55/93/97/100),
    # NICHT nur die hartkodierten RISK_STUFEN — sonst werden neu angelegte Depots
    # vom Ausführungs-Loop (for risk in RISK_STUFEN) nie erreicht.
    for _ctx in depot_kontexte:
        risk = _ctx[0]
        if risk in ki_ergebnisse:
            continue
        depot = _ctx[2]
        params = _ctx[1]
        # Cache-Eintrag?
        cached = cache.get(str(risk), {})
        if cached and jetzt_ts - cached.get("ts", 0) < KI_CACHE_DAUER:
            ki_letzte_cached = cached.get("ki_letzte")
            # 01.11.2026: Gecachte Aktionen werden NICHT erneut ausgefuehrt.
            # Sie wurden bereits in dem Lauf gehandelt, der sie erzeugt hat.
            # Vorher landeten sie hier wieder in der Ausfuehrung - jeder
            # weitere Lauf innerhalb von KI_CACHE_DAUER (z. B. der zweite
            # batch_trader-Aufruf im Pipeline-Modus "full" Sekunden spaeter)
            # kaufte/verkaufte dieselben Positionen ein zweites Mal.
            # Der Cache spart weiter den KI-Call, nicht die Entscheidung.
            aktionen_cached = cached.get("aktionen", [])
            ki_ergebnisse[risk] = (depot, params, {"aktionen": [], "ki_letzte": ki_letzte_cached})
            if not QUIET and ki_letzte_cached:
                print(f"   💾 Cache[Risk {risk}]: {len(aktionen_cached)} Aktionen "
                      f"bereits ausgefuehrt - keine Wiederholung", flush=True)
        else:
            ki_ergebnisse[risk] = (depot, params, {"aktionen": [], "ki_letzte": depot.ki_letzte})

    # Ausführen (sequentiell, da Datei-IO).
    # PHASE: über alle entschiedenen Depots iterieren (inkl. custom), nicht nur RISK_STUFEN.
    # Kandidaten-Map für Ausweich-Käufe bei Konzentrations-Bremse.
    _kandidaten_map = {_c[0]: _c[3] for _c in depot_kontexte}
    for risk in list(ki_ergebnisse.keys()):
        if risk not in ki_ergebnisse:
            continue
        depot, params, ki_ergebnis = ki_ergebnisse[risk]
        aktionen = ki_ergebnis["aktionen"]
        depot.ki_letzte = ki_ergebnis["ki_letzte"]

        # 01.11.2026: Harte Ausstiege VOR den KI-Aktionen. stop_loss und
        # take_profit wurden beim Kauf gespeichert, aber bisher nie geprueft
        # (engine.signal_aktion wird nicht aufgerufen). Dazu Trailing-Stop.
        # Ein ausgeloester Ausstieg hat Vorrang; KI-Aktionen fuer denselben
        # Titel entfallen in diesem Lauf.
        _exit_aktionen = []
        try:
            import exits as _exits
            _trail = _exits.trailing_aktiv()
            for _t, _pos in list(getattr(depot, "positions", {}).items()):
                _k = hole_kurs_fuer(_t)
                _grund = _exits.pruefe_position(_pos, _k, getattr(depot, "risk", risk), _trail)
                if _grund:
                    _exit_aktionen.append({"typ": "verkaufen", "ticker": _t,
                                           "menge": _pos.get("shares", 0), "preis": _k,
                                           "grund": "🛡 " + _grund})
        except Exception as _ex_err:
            if not QUIET:
                print(f"   ⚠ Ausstiegspruefung Risk {risk} fehlgeschlagen: {_ex_err}", flush=True)
        if _exit_aktionen:
            _exit_ticker = {a["ticker"] for a in _exit_aktionen}
            aktionen = _exit_aktionen + [a for a in aktionen if a.get("ticker") not in _exit_ticker]
            if not QUIET:
                for a in _exit_aktionen:
                    print(f"   🛡 Risk {risk}: {a['grund']} {a['ticker']} @ {a['preis']}", flush=True)

        # Ausführen
        buys = [a for a in aktionen if a["typ"] == "kaufen"]
        sells = [a for a in aktionen if a["typ"] == "verkaufen"]

        _alts = _kandidaten_map.get(risk) or []
        for a in aktionen:
            broker = get_broker_adapter(getattr(depot, "tenant_id", 1)) if get_broker_adapter else None
            ausführen(depot, [a], params, broker=broker, alternatives=_alts)
            if a.get("typ") == "kaufen":
                mtlog.trade(aktion="kaufen", ticker=a.get("ticker"),
                          menge=runde(a.get("menge"), 4),
                          preis=runde(a.get("preis"), 4),
                          wert=runde(a.get("menge", 0) * a.get("preis", 0), 2),
                          tier=a.get("tier"), grund=a.get("grund"),
                          risk=getattr(depot, "risk", None))
            elif a.get("typ") == "verkaufen":
                mtlog.trade(aktion="verkaufen", ticker=a.get("ticker"),
                          menge=runde(a.get("menge"), 4),
                          preis=runde(a.get("preis"), 4),
                          wert=runde(a.get("menge", 0) * a.get("preis", 0), 2),
                          grund=a.get("grund"),
                          risk=getattr(depot, "risk", None))
            mtlog.entscheidung(aktion=a.get("typ"), ticker=a.get("ticker"),
                              grund=a.get("grund"), tier=a.get("tier"),
                              menge=runde(a.get("menge"), 4),
                              preis=runde(a.get("preis"), 4),
                              risk=getattr(depot, "risk", None))
            if not QUIET:
                t = a["ticker"]
                if a["typ"] == "kaufen":
                    print(f"   🟢 Kauf {t} {a['menge']:.2f}st @${a['preis']:.2f} (Tier {a.get('tier','?')}) – {a.get('grund','')}", flush=True)
                elif a["typ"] == "verkaufen":
                    print(f"   🔴 Verkauf {t} {a['menge']:.2f}st @${a['preis']:.2f} – {a.get('grund','')}", flush=True)

        # Historie
        historie_aktualisieren(depot)
        depot.speichern()

        wert = depot.wert()
        rendite_pct = (wert / depot.start_wert - 1) * 100
        # start_wert mitfuehren: die Renditebasis ist je Depot
        # verschieden (200 EUR), nicht pauschal 100.
        ergebnisse.append((risk, wert, depot.bargeld, rendite_pct,
                           len(depot.positions), len(depot.trades),
                           depot.start_wert))

    # ─── Ergebnis-Tabelle ────────────────────────────────
    _n_depots = len(ergebnisse)
    ges_wert = sum(e[1] for e in ergebnisse)
    # Die Basis ist die Summe der tatsaechlichen Startwerte der
    # Depots, nicht 100 Euro je Depot. Sonst stimmt die Rendite
    # nicht, sobald ein Depot mit anderem Budget startet.
    ges_start = sum(e[6] for e in ergebnisse) if ergebnisse else 0.0
    if not ges_start:
        ges_start = float(_n_depots * 100)
    print(f"\n{'='*60}", flush=True)
    print(f"📊 {_n_depots} Depots | Trades: {sum(e[5] for e in ergebnisse)} | Gesamtwert: ${ges_wert:.2f}", flush=True)
    print(f"{'='*60}", flush=True)
    print(f" {'Risk':>5} {'Wert':>8} {'Cash':>7} {'Rendite':>8} {'Pos':>3} {'Trades':>6}", flush=True)
    print(f"{'─'*42}", flush=True)
    for risk, wert, cash, rendite, pos, trades, _start in ergebnisse:
        farbe = "🟢" if rendite > 0 else ("🔴" if rendite < -0.1 else "⚪")
        invest_pct = (1 - cash/wert) * 100 if wert > 0 else 0
        print(f" {farbe} {risk:>4} ${wert:>6.2f} ${cash:>5.2f}  {rendite:>+6.2f}%  {pos:>2}  {trades:>4}", flush=True)

    # Zusammenfassung
    investiert = ges_wert
    # Nur mit Basis. Ohne Depots gibt es keine Rendite, und 0/0 ist
    # keine -100-%-Meldung, sondern ein Absturz. Ein leerer Lauf ist
    # ein Ergebnis: die Boerse war zu.
    gesamt_rendite = (ges_wert / ges_start - 1) * 100 if ges_start else 0.0
    if not ges_start:
        print("   [uebersprungen] 0 Depots ausgefuehrt "
              "(Boersensperre %d, sonst keine offenen Positionen) - "
              "kein Handel, keine Bewertung" % boersengesperrt, flush=True)
    print(f"\n💰 Gesamt: ${investiert:.2f} von ${ges_start:.0f} ({gesamt_rendite:+.2f}%)", flush=True)

    # Best/Worst
    # max()/min() auf einer leeren Liste wirft ValueError - auch das
    # waere ein Absturz, eine Zeile nach dem anderen.
    if ergebnisse:
        best = max(ergebnisse, key=lambda x: x[3])
        worst = min(ergebnisse, key=lambda x: x[3])
    else:
        best = worst = (None, 0.0, 0.0, 0.0, 0, 0, 0.0)
    print(f"🏆 Best: Risk {best[0]} ({best[3]:+.2f}%)  |  😱 Worst: Risk {worst[0]} ({worst[3]:+.2f}%)", flush=True)

    # Save summary
    summary = {
        "zeit": datetime.now().isoformat(),
        "depots": _n_depots,
        "gesamtwert": round(ges_wert, 2),
        "gesamt_rendite": round(gesamt_rendite, 2),
        "best_risk": best[0],
        "best_rendite": round(best[3], 2),
        "worst_risk": worst[0],
        "worst_rendite": round(worst[3], 2),
        "trades": sum(e[5] for e in ergebnisse),
        "detail": [{"risk":r, "wert":round(w,2), "rendite":round(rend,2), "pos":p, "trades":t}
                   for r,w,_,rend,p,t,_s in ergebnisse],
    }
    spfad = os.path.join(BASE, "batch_summary.json")
    with open(spfad, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Status speichern
    try:
        from trader_status import update_status
        update_status("batch_trader", {
            "depots": _n_depots,
            "trades": sum(e[5] for e in ergebnisse),
            "rendite": round(gesamt_rendite, 2),
        })
    except Exception:
        pass

    # 30.09.2026: Nach jedem Lauf bewerten. Ohne das hat keine
    # Depotdatei ein "wert"-Feld, der Leser faellt auf
    # start_wert zurueck und jede Rendite ist exakt 0.00 %,
    # egal was der Markt tut. Die Historie bekaemmt erst hier
    # einen zweiten Punkt und kann ueberhaupt eine Kurve
    # zeichnen.
    try:
        from depot_bewertung import bewerte_alle_ordner
        _bew = bewerte_alle_ordner(BASE)
        if _bew:
            _ws = sum(b["start"] for b in _bew)
            _wv = sum(b["wert"] for b in _bew)
            print("   [bewertet] %d Depots, Start %.2f, Wert %.2f (%+.2f%%)"
                  % (len(_bew), _ws, _wv,
                     (_wv / _ws - 1) * 100 if _ws else 0.0), flush=True)
    except Exception as _e:
        # Die Bewertung ist eine Anzeige, kein Handelsschritt.
        # Ein Fehler hier darf den gerade getaetigten Handel
        # nicht zurueckrollen.
        print("   [bewertung fehlgeschlagen] %s" % _e, flush=True)

    # System-Log
    try:
        from system_log import log_eintrag
        level = "ok" if gesamt_rendite >= 0 else "warn"
        log_eintrag("batch", f"Batch-Lauf: {len(RISK_STUFEN)} Depots, "
                    f"{sum(e[5] for e in ergebnisse)} Trades, Rendite {gesamt_rendite:+.2f}%", level)
    except Exception:
        pass


if __name__ == "__main__":
    mtlog.setup()
    mtlog.log.info('Programmstart', modul=__name__)
    with mtlog.run('traderlauf', modul=__name__):
        main()
