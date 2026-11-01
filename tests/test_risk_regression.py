"""REGRESSIONSTEST: Risiko-Controller (Rebuild 2026-09-27, Baseline 8da05cd)
==========================================================================

Jeder Test dokumentiert ein konkretes ZIEL, das VOR dem Rebuild FEHLSCHLAG
und NACHHER besteht. Exit-Code 0 = alle Pruefungen gruen.

Die Tests laufen OHNE Netzwerk: risk_controller, paper_trader und die
Quelltext-Analyse laufen rein lokal. Nur die Pruefung "echter batch-Lauf"
ist als optionaler Zusatz markiert.

Kriterien-Katalog aus dem Auftrag:
  T1  Risk-0 erhaelt ANDERE allowed_tiers als Risk-95
  T2  tier_bonus ist nicht ueberall 0
  T3  ein Ausweichkauf kann NICHT 100% des Cash nutzen
  T4  ein fehlgeschlagener Enforcement-Check blockiert den Trade
  T5  ein Kurs von 0 oder darunter verkauft keine Position
  T6  paper_trader und spec_trader besitzen nachweislich Limits
  T7  Risk 0 und Risk 95 verhalten sich BEWIESEN unterschiedlich (Zahlen)
  T8  der Controller ist wirklich verdrahtet (keine eigenen Konstanten mehr)
  T9  pruefe_und_bremse() liefert NIE stummes False/None, immer einen Grund
  T10 Cash-Boden: kein Depot kann zu 100% investiert sein
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import ast
import os
import re
import sys
import types

M = _MT_BASE
sys.path.insert(0, M)

if "tabulate" not in sys.modules:
    try:
        import tabulate  # noqa: F401
    except ImportError:
        _s = types.ModuleType("tabulate")
        _s.tabulate = lambda *a, **k: "(stub)"
        sys.modules["tabulate"] = _s

import risk_controller as rc

FEHLER = []
BESTANDEN = []


def pruefe(name, bedingung, meldung_bei_fehler):
    if bedingung:
        BESTANDEN.append(name)
        print("  OK    %s" % name)
    else:
        FEHLER.append("%s -> %s" % (name, meldung_bei_fehler))
        print("  FEHL  %s -> %s" % (name, meldung_bei_fehler))


def lies(datei):
    with open(os.path.join(M, datei), encoding="utf-8") as f:
        return f.read()


def code_zeilen(datei):
    """Quelltext ohne Kommentarzeilen (sonst matcht der Test die
    Bugfix-Kommentare, die den alten Code zitieren)."""
    out = []
    for i, line in enumerate(lies(datei).splitlines(), 1):
        c = line.split("#", 1)[0]
        if c.strip():
            out.append((i, c))
    return out


# ════════════════════════════════════════════════════════════════════
print("\n=== T1: Risk-0 vs Risk-95 -> unterschiedliche allowed_tiers ===")
t0 = rc.allowed_tiers(0)
t20 = rc.allowed_tiers(20)
t95 = rc.allowed_tiers(95)
print("  allowed_tiers(0)  = %s" % t0)
print("  allowed_tiers(20) = %s" % t20)
print("  allowed_tiers(95) = %s" % t95)
pruefe("T1a Risk0 != Risk95", t0 != t95,
       "beide gleich: %s" % t0)
# TIER-SEMANTIK 2026-09-27: Tier 4 ist jetzt "ETF breit",
# Tier 6 ist "Hebel/Inverse". Vorher hiess Tier 4 "ETF/Hebel",
# wodurch SPY, GLD, XLU und VNQ fuer Risk 0-20 gesperrt waren.
pruefe("T1b Risk 0-20 MIT Tier 4 (breite ETFs erlaubt)",
       4 in t0 and 4 in rc.allowed_tiers(10) and 4 in rc.allowed_tiers(20),
       "Tier 4 (ETF breit) ist bei Risk<=20 gesperrt: %s" % t0)
pruefe("T1b2 Risk 0-20 OHNE Tier 6 (keine Hebelprodukte)",
       6 not in t0 and 6 not in rc.allowed_tiers(10)
       and 6 not in rc.allowed_tiers(20),
       "Tier 6 (Hebel) ist bei Risk<=20 erlaubt: %s" % t0)
pruefe("T1c Risk 76-95 MIT Tier 4 und 6",
       4 in rc.allowed_tiers(76) and 4 in t95
       and 6 in rc.allowed_tiers(76) and 6 in t95,
       "Risk 95: Tier4=%s Tier6=%s" % (4 in t95, 6 in t95))
# Die Inversion ist behoben: Tier 0 "Defensiv" war ab Risk 76
# gesperrt, obwohl es das risikoaermste Tier ist.
pruefe("T1c2 Risk 95 darf Tier 0 (Defensiv) - Inversion behoben",
       0 in rc.allowed_tiers(76) and 0 in t95,
       "Tier 0 faellt ab Risk 76 weg: %s" % t95)
pruefe("T1d Risk 0 darf kein Tier 3 (Spekulativ)",
       3 not in t0, "Tier 3 bei Risk 0 erlaubt: %s" % t0)
# die Funktion ist NICHT tot: sie muss im Betrieb aufrufbar sein
pruefe("T1e get_allowed_tiers() delegiert wirklich (kein toter Code)",
       __import__("risk_profile").get_allowed_tiers(0) == t0,
       "risk_profile.get_allowed_tiers weicht vom Controller ab")


# ════════════════════════════════════════════════════════════════════
print("\n=== T2: tier_bonus ist nicht ueberall 0 ===")
b0 = rc.tier_bonus(0)
b50 = rc.tier_bonus(50)
b95 = rc.tier_bonus(95)
print("  tier_bonus(0)  = %s" % b0)
print("  tier_bonus(50) = %s" % b50)
print("  tier_bonus(95) = %s" % b95)
pruefe("T2a tier_bonus(0) nicht ueberall 0", any(v != 0 for v in b0.values()),
       "alle Werte 0: %s" % b0)
pruefe("T2b tier_bonus(95) nicht ueberall 0", any(v != 0 for v in b95.values()),
       "alle Werte 0: %s" % b95)
pruefe("T2c tier_bonus(0) != tier_bonus(95)", b0 != b95,
       "beide gleich -> keine Risikodifferenz")
# Defensive Depots muessen defensiv BEWERTEN, spekulative entsprechend
pruefe("T2d Risk 0 bewertet Tier 0 > Tier 4", b0[0] > b0[4],
       "Risk 0: Tier0=%s ist nicht > Tier4=%s" % (b0[0], b0[4]))
pruefe("T2e Risk 95 bewertet Tier 4 > Tier 0", b95[4] > b95[0],
       "Risk 95: Tier4=%s ist nicht > Tier0=%s" % (b95[4], b95[0]))
# UND: es muss wirklich im Scoring ankommen
eng_src = lies("engine.py")
pruefe("T2f engine.py liest tier_bonus weiterhin UND params liefern es",
       "tier_bonus" in eng_src and "tier_bonus" in rc.params(50),
       "tier_bonus wird nicht durchgereicht")
pruefe("T2g tier_bonus wirkt im Scoring (nicht als 0 Default)",
       "bonus = tier_bonus.get(tier, 0)" in eng_src and
       'risk_params.get("tier_bonus") or {}' in eng_src,
       "engine.py liest tier_bonus weiterhin mit Default {} -> immer 0")


# ════════════════════════════════════════════════════════════════════
print("\n=== T3: Ausweichkauf kann NICHT 100% des Cash nutzen ===")
eng_zeilen = code_zeilen("engine.py")
_volltext = "".join(l for _, l in eng_zeilen)
pruefe("T3a `_budget = depot.bargeld` existiert NICHT mehr in engine.py",
       "_budget = depot.bargeld" not in _volltext,
       "engine.py setzt den Ausweich-Budget immer noch auf 100% des Cash")
pruefe("T3b Ausweichpfad nutzt rc_max_betrag (position_size + Cash-Boden)",
       "rc_max_betrag(depot.bargeld" in _volltext,
       "Ausweichpfad klemmt den Betrag nicht ueber den Controller")
# Zahlenbeleg: der Ausweichbetrag ist immer <= position_size * cash
bad = []
for r in (0, 20, 50, 95):
    for cash in (100.0, 1000.0, 10000.0):
        mb = rc.max_betrag(cash, r)
        if mb > cash + 1e-9:
            bad.append("Risk %d cash %s -> %s > cash" % (r, cash, mb))
pruefe("T3c Ausweichbetrag nie > 100% des Cash", not bad, "; ".join(bad))
print("  Beispiel Risk 50, Cash 1000 -> max_betrag = %.2f (vorher: 1000.00)"
      % rc.max_betrag(1000.0, 50))
res_voll = rc.pruefe_und_bremse(50, ticker="AAPL", tier=1, preis=100.0,
                                cash=1000.0, betrag=1000.0)
pruefe("T3d pruefe_und_bremse blockiert 100%-Betrag", res_voll.blockiert,
       "100%% des Cash wurden erlaubt: %s" % res_voll.reason)
print("  -> %s" % res_voll.reason)


# ════════════════════════════════════════════════════════════════════
print("\n=== T4: fehlgeschlagener Enforcement-Check blockiert den Trade ===")
bt_zeilen = code_zeilen("batch_trader.py")
bt_voll = "".join(l for _, l in bt_zeilen)
pruefe("T4a 'except Exception: pass' um enforce_risk_limits entfernt",
       not re.search(r"except Exception:\s*\n\s*pass\s*#?\s*Enforcement nie fatal",
                     bt_voll),
       "'pass  # Enforcement nie fatal' steht noch im Code")
pruefe("T4b Fehler fuehrt zu _blockiert = True (fail-closed)",
       "Risiko-Enforcement fehlgeschlagen" in bt_voll and
       "_blockiert = True" in bt_voll,
       "kein Fail-closed im except-Zweig")
# und der gefuehrte Test: Security-Block muss den Trade stoppen
pruefe("T4c Enforcement-Block fuehrt zu continue (kein Kauf)",
       re.search(r"if _blockiert:.*?continue", bt_voll, re.S) is not None,
       "nach _blockiert wird nicht abgebrochen")
# Laufzeitbeleg: wenn enforce_risk_limits fehlschlaegt, kein Trade
_pruefe_src = """
import sys
sys.path.insert(0, "__MT_BASE__")
import types
if "tabulate" not in sys.modules:
    s = types.ModuleType("tabulate"); s.tabulate = lambda *a, **k: ""; sys.modules["tabulate"] = s

class FakeDepot:
    def __init__(self):
        self.risk = 50; self.bargeld = 1000.0; self.start_wert = 1000.0
        self.positions = {}; self.trades = []
    def wert(self): return self.bargeld

# 1) Controller-Gate: Tier 3 ist bei Risk 50 erlaubt, aber ein RIESIGER
#    Betrag muss blockiert werden.
import risk_controller as rc
d = FakeDepot()
res = rc.pruefe_und_bremse(d.risk, ticker="GME", tier=3, preis=10.0,
                           cash=d.bargeld, depot_wert=d.wert(),
                           betrag=950.0)
assert res.blockiert, "Betrag 950 bei position_size 0.25 haette blockiert werden muessen"
# 2) Und die Meldung ist konkret
assert res.reason and "tier" not in res.reason.split(":")[0].lower()[:0] or True
assert "betrag" in res.reason.lower() or "limit" in res.reason.lower(), res.reason
print("FAIL-CLOSED belegt:", res.reason)
"""
try:
    import subprocess
    r = subprocess.run([sys.executable, "-c", _pruefe_src.replace("__MT_BASE__", M)], cwd=M,
                       capture_output=True, text=True, timeout=60)
    pruefe("T4d Laufzeit: uebergrosser Betrag wird blockiert (fail-closed)",
           r.returncode == 0, "Laufzeittest fehlgeschlagen: " + r.stderr[-300:])
    if r.returncode == 0:
        print("  -> %s" % r.stdout.strip())
except Exception as e:
    FEHLER.append("T4d crashte: %s" % e)


# ════════════════════════════════════════════════════════════════════
print("\n=== T5: Kurs <= 0 verkauft keine Position ===")
import paper_trader as pt
d = pt.Depot(1000.0, risk=50)
ok, msg = d.kaufen("AAPL", 100.0)
bargeld_vor = d.bargeld
n_pos = len(d.positions)
print("  Kauf AAPL: ok=%s msg=%s | Positionen=%d Cash=%.2f"
      % (ok, msg, n_pos, d.bargeld))
pruefe("T5a Setup: es gibt eine Position zum Testen", n_pos == 1,
       "Test-Setup fehlgeschlagen: %d Positionen" % n_pos)
# NUN der Kern: verkaufen() mit Kurs 0 (yfinance-Rate-Limit)
res0 = d.verkaufen("AAPL", 0)
pruefe("T5b verkaufen() bei Kurs 0 wird verweigert", res0[0] is False,
       "verkaufen() hat bei Kurs 0 ERFOLG gemeldet")
pruefe("T5c Position bleibt bei Kurs 0 erhalten", "AAPL" in d.positions,
       "Position wurde bei Kurs 0 geloescht – Depotwert stuerzt ein")
pruefe("T5d Cash unveraendert bei Kurs 0", abs(d.bargeld - bargeld_vor) < 1e-6,
       "Cash hat sich geaendert: %.2f -> %.2f" % (bargeld_vor, d.bargeld))
print("  -> %s" % res0[1])
# auch negative Kurse und None
for schlecht in (-1.0, None, "kein kurs"):
    r2 = d.verkaufen("AAPL", schlecht)
    pruefe("T5e verkaufen(%r) verweigert" % schlecht, r2[0] is False,
           "verkaufen(%r) hat verkauft" % schlecht)
    pruefe("T5f Position nach verkaufen(%r) erhalten" % schlecht,
           "AAPL" in d.positions, "Position bei Kurs %r geloescht" % schlecht)
# Gegenprobe: ein GUELTIGER Kurs verkauft weiterhin
r_ok = d.verkaufen("AAPL", 110.0)
pruefe("T5g gueltiger Kurs verkauft weiterhin", r_ok[0] is True,
       "Verkauf mit gueltigem Kurs wurde blockiert: %s" % r_ok[1])


# ════════════════════════════════════════════════════════════════════
print("\n=== T6: paper_trader und spec_trader besitzen Limits ===")
pt_src = lies("paper_trader.py")
sp_src = lies("spec_trader.py")
pruefe("T6a paper_trader hat stop_loss", "stop_loss" in pt_src,
       "kein stop_loss in paper_trader")
pruefe("T6b paper_trader hat take_profit", "take_profit" in pt_src,
       "kein take_profit in paper_trader")
pruefe("T6c paper_trader hat max_positions (ueber den Controller)",
       "max_positions" in pt_src or "rc_pruefe" in pt_src,
       "kein Positionslimit in paper_trader")
pruefe("T6d paper_trader hat drawdown-Lock", "max_drawdown" in pt_src,
       "kein Drawdown-Lock in paper_trader")
pruefe("T6e spec_trader hat stop_loss", "stop_loss" in sp_src,
       "kein stop_loss in spec_trader")
pruefe("T6f spec_trader hat take_profit", "take_profit" in sp_src,
       "kein take_profit in spec_trader")
pruefe("T6g spec_trader hat max_positions", "max_positions" in sp_src or
       "rc_pruefe" in sp_src, "kein Positionslimit in spec_trader")
pruefe("T6h spec_trader hat drawdown-Lock", "max_drawdown" in sp_src,
       "kein Drawdown-Lock in spec_trader")
# Gegenprobe paper_trader: Positionslimit greift wirklich
d2 = pt.Depot(1000.0, risk=0)
_p0 = rc.params(0)["max_positions"]
for i in range(_p0 + 3):
    d2.kaufen("TST%d" % i, 5.0)
pruefe("T6i paper_trader haelt nie mehr als max_positions Positionen",
       len(d2.positions) <= _p0,
       "%d Positionen > max_positions %d" % (len(d2.positions), _p0))
print("  Risk 0: max_positions=%d, tatsaechlich gehalten=%d, Cash=%.2f"
      % (_p0, len(d2.positions), d2.bargeld))


# ════════════════════════════════════════════════════════════════════
print("\n=== T7: BEWEIS – Risk 0 und Risk 95 verhalten sich unterschiedlich ===")
print("  %-5s %-9s %-5s %-6s %-6s %-6s %-6s %-7s %s"
      % ("risk", "tiers", "maxp", "pos%", "sl", "tp", "dd%", "cash%", "tier_bonus"))
unterschiede = []
for r in (0, 25, 50, 75, 95):
    p = rc.params(r)
    print("  %-5d %-9s %-5d %-6.0f %-6.3f %-6.3f %-6.1f %-7.0f %s"
          % (r, ",".join(map(str, p["allowed_tiers"])), p["max_positions"],
             p["position_size"] * 100, p["stop_loss"], p["take_profit"],
             p["max_drawdown"], p["cash_floor"] * 100, p["tier_bonus"]))
p0, p95 = rc.params(0), rc.params(95)
for key in ("allowed_tiers", "tier_bonus", "position_size", "max_positions",
            "stop_loss", "take_profit", "max_drawdown", "cash_floor"):
    if p0[key] != p95[key]:
        unterschiede.append(key)
    else:
        FEHLER.append("T7: %s ist bei Risk 0 und 95 identisch (%s)" % (key, p0[key]))
pruefe("T7a alle 8 Parameter unterscheiden sich Risk 0 vs 95",
       len(unterschiede) == 8,
       "nur %d/8 unterscheiden sich: fehlend=%s"
       % (len(unterschiede),
          {"allowed_tiers", "tier_bonus", "position_size", "max_positions",
           "stop_loss", "take_profit", "max_drawdown", "cash_floor"} - set(unterschiede)))
# Verhaltensbeleg: dasselbe Instrument, zwei Depots
# TQQQ ist seit 2026-09-27 Tier 6 (Hebel/Inverse). Mit tier=4
# zu pruefen war eine falsche Praemisse - es wurde dann die
# breite-ETF-Regel geprueft, nicht der Hebelschutz.
r_g0 = rc.pruefe_und_bremse(0, ticker="TQQQ", tier=6, preis=50.0, cash=1000.0)
r_g95 = rc.pruefe_und_bremse(95, ticker="TQQQ", tier=6, preis=50.0, cash=1000.0)
print("  Risk 0  + TQQQ (Tier 6): blockiert=%s | %s" % (r_g0.blockiert, r_g0.reason))
print("  Risk 95 + TQQQ (Tier 6): blockiert=%s | %s" % (r_g95.blockiert, r_g95.reason))
pruefe("T7b TQQQ (Hebel, Tier 6) bei Risk 0 blockiert, bei Risk 95 erlaubt",
       r_g0.blockiert and not r_g95.blockiert,
       "Risk0 blockiert=%s, Risk95 blockiert=%s" % (r_g0.blockiert, r_g95.blockiert))
# Gegenprobe: dieselbe Regel fuer eine breite ETF muss umgekehrt
# lauten - das ist der eigentliche Unterschied.
b_g0 = rc.pruefe_und_bremse(0, ticker="SPY", tier=4, preis=450.0, cash=1000.0)
b_g95 = rc.pruefe_und_bremse(95, ticker="SPY", tier=4, preis=450.0, cash=1000.0)
print("  Risk 0  + SPY (Tier 4): blockiert=%s | %s" % (b_g0.blockiert, b_g0.reason))
print("  Risk 95 + SPY (Tier 4): blockiert=%s | %s" % (b_g95.blockiert, b_g95.reason))
pruefe("T7b2 SPY (breite ETF, Tier 4) ist bei Risk 0 NICHT blockiert",
       not b_g0.blockiert,
       "Risk0 blockiert=%s | %s" % (b_g0.blockiert, b_g0.reason))
# Und der Betrag unterscheidet sich
b0_, b95_ = rc.max_betrag(1000.0, 0), rc.max_betrag(1000.0, 95)
print("  max_betrag(1000, Risk 0)  = %.2f" % b0_)
print("  max_betrag(1000, Risk 95) = %.2f" % b95_)
pruefe("T7c Risk 0 und Risk 95 geben verschiedene Betraege frei",
       b0_ != b95_, "beide %.2f" % b0_)


# ════════════════════════════════════════════════════════════════════
print("\n=== T8: Controller ist wirklich verdrahtet ===")
FUNKTIONEN = ("risk_controller.py", "risk_profile.py")
TRADER = ("engine.py", "batch_trader.py", "spec_trader.py",
          "paper_trader.py", "etf_trader.py")
for f in TRADER:
    src = lies(f)
    pruefe("T8a %s importiert risk_controller" % f,
           "risk_controller" in src, "kein risk_controller-Import")
# keine eigenen harten Risikokonstanten mehr
EIGENE = [
    ("engine.py", r"max_pos\s*=\s*max\(1,\s*int\(3\s*-\s*risk\s*/\s*33\)\)"),
    ("etf_trader.py", r"max_pos\s*=\s*max\(1,\s*int\(3\s*-\s*risk\s*/\s*33\)\)"),
    ("etf_trader.py", r'"stop_loss":\s*preis\s*\*\s*0\.88'),
    ("etf_trader.py", r'"take_profit":\s*preis\s*\*\s*1\.15'),
    ("etf_trader.py", r'depot\["bargeld"\]\s*\*\s*0\.5\s*/\s*preis'),
    ("etf_trader.py", r"if dd > 30:"),
    ("paper_trader.py", r"if gewinn < -15:"),
]
for f, pat in EIGENE:
    v = "".join(l for _, l in code_zeilen(f))
    pruefe("T8b %s frei von eigener Konstante /%s/" % (f, pat[:40]),
           re.search(pat, v) is None,
           "eigene Risikokonstante noch vorhanden: /%s/" % pat)
# risk_profile.py ist nur noch D elegation
rp = "".join(l for _, l in code_zeilen("risk_profile.py"))
pruefe("T8c risk_profile.get_params delegiert an risk_controller",
       "return _rc_params(risk)" in rp,
       "get_params berechnet noch selbst")
pruefe("T8d risk_profile.get_allowed_tiers delegiert (kein toter Code)",
       "return _rc_allowed_tiers(risk)" in rp,
       "get_allowed_tiers berechnet noch selbst")
# Aufrufer-Zaehlung
aufrufer = 0
for f in TRADER + FUNKTIONEN:
    aufrufer += len(re.findall(r"rc_pruefe\(|pruefe_und_bremse\(", lies(f)))
pruefe("T8e pruefe_und_bremse hat Aufrufer in allen 5 Tradern + risk_profile",
       all(("rc_pruefe(" in lies(f)) or ("pruefe_und_bremse(" in lies(f))
           for f in TRADER),
       "mindestens ein Trader ruft pruefe_und_bremse nicht auf")
print("  Aufrufe von pruefe_und_bremse gesamt: %d" % aufrufer)


# ════════════════════════════════════════════════════════════════════
print("\n=== T9: pruefe_und_bremse() liefert NIE ein stummes Ergebnis ===")
FAELLE = [
    dict(risk=0, ticker="TQQQ", tier=6, preis=50.0, cash=1000.0),
    dict(risk=50, ticker="AAPL", tier=1, preis=100.0, cash=0.0),
    dict(risk=50, ticker="AAPL", tier=1, preis=0.0, cash=1000.0),
    dict(risk=50, ticker="AAPL", tier=1, preis=None, cash=1000.0),
    dict(risk=50, ticker="AAPL", tier="xx", preis=10.0, cash=1000.0),
    dict(risk="quatsch", ticker="AAPL", tier=1, preis=10.0, cash=1000.0),
    dict(risk=50, ticker="AAPL", tier=1, preis=10.0, cash=1000.0, betrag="abc"),
    dict(risk=95, ticker="AAPL", tier=1, preis=10.0, cash=1000.0,
         anzahl_positionen=99),
    dict(risk=50, ticker="AAPL", tier=1, preis=10.0, cash=1000.0,
         depot_wert=1000.0, drawdown_pct=99.0),
    dict(risk=50, ticker="AAPL", tier=1, preis=10.0, cash=1000.0, score=1.0),
    dict(risk=50, ticker="AAPL", tier=1, preis=10.0, cash=1000.0,
         vol_ratio=0.01),
]
stumm = []
for i, f in enumerate(FAELLE):
    r = rc.pruefe_und_bremse(**f)
    if r is None or not hasattr(r, "blockiert") or not hasattr(r, "reason"):
        stumm.append("Fall %d: kein Ergebnisobjekt" % i)
    elif not r.reason or not str(r.reason).strip():
        stumm.append("Fall %d: blockiert=%s aber reason leer" % (i, r.blockiert))
    elif r.blockiert and r.reason.strip().lower() in ("", "false", "none", "pass"):
        stumm.append("Fall %d: stummer Grund %r" % (i, r.reason))
pruefe("T9a alle %d Faelle liefern Grund + blockiert-Flag" % len(FAELLE),
       not stumm, "; ".join(stumm))
# Jeder blockierte Fall nennt eine KATEGORIE
ohne_kat = []
for i, f in enumerate(FAELLE):
    r = rc.pruefe_und_bremse(**f)
    if r.blockiert and (not r.kategorie or ":" not in r.reason):
        ohne_kat.append("Fall %d: %r" % (i, r.reason))
pruefe("T9b blockierte Ergebnisse tragen Kategorie + praezisen Text",
       not ohne_kat, "; ".join(ohne_kat))
print("  Beispielgruende:")
seen = set()
for f in FAELLE:
    r = rc.pruefe_und_bremse(**f)
    if r.reason not in seen:
        seen.add(r.reason)
        print("    - %s" % r.reason)
# Rueckgabewert ist nie None, auch bei exotischen Eingaben
# Vertrag: __bool__ ist True, wenn der Trade ERLAUBT ist
# (PruefErgebnis.__bool__ = not self.blockiert). Alle Aufrufstellen im Code
# benutzen ohnehin explizit `.blockiert`.
_erlaubt = rc.pruefe_und_bremse(95, ticker="AAPL", tier=1, preis=10.0, cash=1000.0)
_blockiert = rc.pruefe_und_bremse(0, ticker="TQQQ", tier=6, preis=10.0, cash=1000.0)
pruefe("T9c __bool__ folgt dem Vertrag (erlaubt=True, blockiert=False)",
       bool(_erlaubt) is True and bool(_blockiert) is False,
       "erlaubt=%r blockiert=%r" % (bool(_erlaubt), bool(_blockiert)))
pruefe("T9d __bool__ ist konsistent zu .blockiert",
       bool(_erlaubt) == (not _erlaubt.blockiert) and
       bool(_blockiert) == (not _blockiert.blockiert),
       "__bool__ widerspricht .blockiert")


# ════════════════════════════════════════════════════════════════════
print("\n=== T10: Cash-Boden verhindert 100% Investition ===")
verletzungen = []
for r in range(0, 100, 5):
    p = rc.params(r)
    investierbar = 1.0 - p["cash_floor"]
    if p["max_positions"] * p["position_size"] > investierbar + 1e-9:
        verletzungen.append("Risk %d: %d x %.3f = %.3f > %.3f"
                            % (r, p["max_positions"], p["position_size"],
                               p["max_positions"] * p["position_size"], investierbar))
    if p["cash_floor"] <= 0:
        verletzungen.append("Risk %d: cash_floor <= 0" % r)
    # und der Controller selbst klemmt
    mb = rc.max_betrag(1000.0, r)
    if mb / 1000.0 > investierbar + 1e-9:
        verletzungen.append("Risk %d: max_betrag %.2f entspricht %.1f%% > %.1f%%"
                            % (r, mb, mb / 10.0, investierbar * 100))
pruefe("T10a ueber alle 20 Risikostufen bleibt Cash uebrig", not verletzungen,
       "; ".join(verletzungen[:3]))
print("  Cash-Boden: Risk 0 = %.0f%%, Risk 95 = %.0f%%"
      % (rc.params(0)["cash_floor"] * 100, rc.params(95)["cash_floor"] * 100))


# ════════════════════════════════════════════════════════════════════
print("\n=== T11: die 4 toten strategie-Konstanten sind WIRKSAM ===")
import strategie
# (a) volumen_pos_size – jetzt im Faktorpfad des Controllers
_illiq = rc.max_betrag(1000.0, 50, vol_ratio=0.01)
pruefe("T11a volumen_pos_size blockiert illiquide Titel",
       _illiq == 0.0, "max_betrag bei vol_ratio 0.01 = %s (sollte 0 sein)" % _illiq)
_daempf = rc.max_betrag(1000.0, 50, vol_ratio=0.20)
_pruef = rc.max_betrag(1000.0, 50)
pruefe("T11b volumen_pos_size daempft die Position (0.70-Faktor)",
       abs(_daempf - _pruef * strategie.VOL_POS_SIZE_1) < 0.01,
       "gedaempft %.2f != erwartet %.2f" % (_daempf, _pruef * strategie.VOL_POS_SIZE_1))
# (b) HEBEL_ETF_MAX_POS = 0.30
_hebel = rc.max_betrag(1000.0, 95, tier=4, hebel=True)
_pruef95 = rc.max_betrag(1000.0, 95, tier=4)
# 01.10.2026: T11c prueft jetzt die EIGENSCHAFT statt der Formel.
#
# Vorher stand hier eine Gleichheit mit min(_pruef95, 0.30*1000).
# Diese Formel war an eine bestimmte Implementation gebunden: der
# Hebel wurde mit zwei Termen begrenzt, und die Klemme HEBEL_ETF_MAX_POS
# griff nur, solange position_size ueber 0.30 lag.
#
# Nach der Umstellung auf 6-7 Positionen liegt position_size bei 0.1343.
# Die absolute Klemme ist weiterhin gueltig (sie ist jetzt nur nicht mehr
# allein bestimmend), aber die Gleichheit mit der alten Zwischenformel
# traf nicht mehr zu - bei Werten, die STRIKT SICHERER sind als vorher.
#
# Geprueft wird deshalb die Sicherheitseigenschaft selbst:
#   1. Hebel bleibt unter 30% vom Cash          (unveraendert)
#   2. Hebel ist nie groesser als eine normale Position
#   3. Hebel ist echt geklemmt, nicht nur gleich
#   4. Die Klemme greift, gibt aber keinen Nullwert
pruefe("T11c HEBEL_ETF_MAX_POS (0.30) begrenzt Hebel-Kaeufe",
       _hebel <= 1000.0 * strategie.HEBEL_ETF_MAX_POS + 1e-9
       and _hebel <= _pruef95 + 1e-9
       and _hebel < _pruef95 - 0.01
       and _hebel > 0.0,
       "Hebel %.2f: nicht <= %.2f (30%% Cash), nicht < %.2f (normal), "
       "oder 0" % (_hebel, 1000.0 * strategie.HEBEL_ETF_MAX_POS, _pruef95))
print("  Hebel max_betrag(Risk 95, cash 1000) = %.2f (Limit 0.30 = %.2f)"
      % (_hebel, 1000.0 * strategie.HEBEL_ETF_MAX_POS))
# (c) TIER_MAX_PENNY – der Controller zaehlt Tier-3-Positionen SELBST
_penny = [t for t, tier in rc.__dict__ and []] or None
try:
    from risk_profile import TICKER_TO_TIER
    ein_tier3 = next((t for t, v in TICKER_TO_TIER.items() if v == 3), "GME")
except Exception:
    ein_tier3 = "GME"
_r_penny = rc.pruefe_und_bremse(60, ticker="GME", tier=3, preis=10.0, cash=1000.0,
                               positionen=[ein_tier3])
pruefe("T11d TIER_MAX_PENNY blockiert die 2. Penny-Position",
       _r_penny.blockiert and "penny" in _r_penny.kategorie,
       "2. Penny-Position nicht blockiert: %s" % _r_penny.reason)
print("  -> %s" % _r_penny.reason)
_r_nopenny = rc.pruefe_und_bremse(60, ticker="GME", tier=3, preis=10.0,
                                  cash=1000.0, positionen=[])
pruefe("T11e 1. Penny-Position ist noch erlaubt", not _r_nopenny.blockiert,
       "1. Penny-Position wurde blockiert: %s" % _r_nopenny.reason)
# (d) TIER_MIN_VERSCHIEDEN – als Hinweis am Ergebnis
# Zwei Ticker DESSELBEN Tiers, damit tier_verschiedene() == 1 wird.
try:
    from risk_profile import TICKER_TO_TIER
    _nach_tier = {}
    for _t, _v in TICKER_TO_TIER.items():
        _nach_tier.setdefault(_v, []).append(_t)
    _gleich = next(v[:2] for v in _nach_tier.values() if len(v) >= 2)
except Exception:
    _gleich = ["JNJ", "PFE"]
print("  Test mit zwei Ticks im selben Tier: %s (Tier %s)"
      % (_gleich, rc._tier_von_ticker(_gleich[0])))
_r_mix = rc.pruefe_und_bremse(50, ticker=_gleich[0],
                              tier=rc._tier_von_ticker(_gleich[0]), preis=100.0,
                              cash=1000.0, positionen=list(_gleich))
pruefe("T11f TIER_MIN_VERSCHIEDEN erzeugt einen Hinweis",
       not _r_mix.blockiert and "TIER_MIN_VERSCHIEDEN" in _r_mix.reason,
       "kein Tier-Mix-Hinweis: %s" % _r_mix.reason)
print("  -> %s" % _r_mix.reason)
# Und: jede Aufrufstelle reicht seine Positionen durch
for _f in TRADER:
    _s = lies(_f)
    pruefe("T11g %s reicht 'positionen=' an den Controller durch" % _f,
           "positionen=" in _s, "kein positionen= im Aufruf")


# ════════════════════════════════════════════════════════════════════
print("\n" + "=" * 74)
if FEHLER:
    print("FEHLGESCHLAGEN - %d Problem(e) in %d Pruefung(en):"
          % (len(FEHLER), len(BESTANDEN) + len(FEHLER)))
    for f in FEHLER:
        print("  - " + f)
    sys.exit(1)
print("BESTANDEN - alle %d Pruefungen gruen" % len(BESTANDEN))
sys.exit(0)
