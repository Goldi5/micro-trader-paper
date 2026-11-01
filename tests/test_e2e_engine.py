"""END-TO-END-BEWEIS gegen die ECHTEN Produktionsfunktionen.

Hier wird nicht der Controller isoliert getestet, sondern der echte Pfad
engine.ausfuehren() -> Konzentrations-Bremse -> Ausweichkauf.

Ziel: belegen, dass der Ausweichkauf (Befund 1) nicht mehr 100% des
Depot-Cash einsetzen kann, sondern dieselben Limits durchlaeuft wie ein
regulaerer Kauf. Zusaetzlich: Risk-0 und Risk-95 werden im echten Engine-
Pfad unterschiedlich behandelt.

Lauf ohne Netzwerk: die Kursdaten werden direkt als Aktionsliste
injiziert, nur die Risikologie ist echt.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import sys
import types

M = _MT_BASE
sys.path.insert(0, M)
if "tabulate" not in sys.modules:
    _s = types.ModuleType("tabulate"); _s.tabulate = lambda *a, **k: ""
    sys.modules["tabulate"] = _s

import engine
import risk_controller as rc

FEHLER = []


def pruefe(name, bedingung, msg):
    if bedingung:
        print("  OK    %s" % name)
    else:
        FEHLER.append("%s -> %s" % (name, msg))
        print("  FEHL  %s -> %s" % (name, msg))


# ─────────────────────────────────────────────────────────────────
print("=== E1: Konzentrations-Bremse erzwingen, Ausweichkauf messen ===")
print("  (echte engine.ausfuehren(), nur die Konzentrationszaehlung ersetzt)")

import ki_kontext
_orig_konz = ki_kontext.ticker_konzentration
# NUR der gekaufte Ticker ist gesperrt, der Ausweichkandidat ist frei.
# Sonst wuerde die Bremse auch den Ersatz-Titel sperren und der Ausweichpfad
# wuerde gar nicht durchlaufen.
ki_kontext.ticker_konzentration = lambda t: 99 if t == "GESPERRT" else 0

def kauf_mit_ausweich(risk, cash=1000.0):
    d = engine.Depot(start_wert=cash, risk=risk)
    d.bargeld = cash
    # Aktion: Kaufe den gesperrten Ticker; der Ausweichkandidat ist "ALT"
    aktionen = [{"typ": "kaufen", "ticker": "GESPERRT", "menge": 99.0,
                 "preis": 10.0, "grund": "Test", "tier": 1}]
    alts = [{"ticker": "ALT", "preis": 20.0, "tier": 1}]
    engine.ausführen(d, aktionen, rc.params(risk), alternatives=alts)
    return d

for risk in (0, 50, 95):
    d = kauf_mit_ausweich(risk)
    cash_vor = 1000.0
    eingesetzt = cash_vor - d.bargeld
    quote = eingesetzt / cash_vor
    gekauft = "ALT" in d.positions
    anteil = (d.positions["ALT"]["avg_price"] * d.positions["ALT"]["shares"]
              / cash_vor) if gekauft else 0.0
    print("  Risk %2d: gekauft=%-5s eingesetzt=%7.2f = %5.1f%% des Cash "
          "(max erlaubt %.1f%%)"
          % (risk, gekauft, eingesetzt, quote * 100,
             rc.params(risk)["position_size"] * 100))
    pruefe("E1.%d Risk %d: Ausweichkauf nutzt NIE 100%% des Cash" % (risk, risk),
           anteil < 0.999,
           "Ausweichkauf setzte %.1f%% des Cash ein" % (anteil * 100))
    pruefe("E1.%d Risk %d: Cash-Boden gewahrt" % (risk, risk),
           d.bargeld > 0, "kein Cash mehr uebrig")

# Gegenprobe: der BASELINE-Pfad (100% des Cash) waere das gewesen
print("\n  Zum Vergleich, was der alte Pfad getan haette:")
print("    BASELINE engine.py:546  _budget = depot.bargeld  -> %.2f = 100.00%%"
      % 1000.0)
print("    NEU      max_betrag()                    -> %.2f = %.1f%%"
      % (rc.max_betrag(1000.0, 50), rc.max_betrag(1000.0, 50) / 10.0))

ki_kontext.ticker_konzentration = _orig_konz

# ─────────────────────────────────────────────────────────────────
print("\n=== E2: Risk 0 vs Risk 95 im ECHTEN Engine-Kaufpfad ===")
from risk_profile import TICKER_TO_TIER
# TIER-SEMANTIK 2026-09-27: Tier 4 = "ETF breit", Tier 6 = "Hebel".
# Vorher war beides Tier 4, wodurch breite ETFs fuer Risk 0-20
# gesperrt waren und GLD, SLV, XLU, VNQ als "Hebel" gefuehrt
# wurden. Der alte Test zog den ERSTEN Tier-4-Ticker und nannte
# ihn "Hebel" - das war eine falsche Praemisse, seit die Trennung
# ist es eine breite ETF.
_t_hebel = next((t for t, v in TICKER_TO_TIER.items() if v == 6), "TQQQ")
_t_breit = next((t for t, v in TICKER_TO_TIER.items() if v == 4), "SPY")
_t0 = next((t for t, v in TICKER_TO_TIER.items() if v == 0), "JNJ")
print("  Tier-6 (Hebel): %s, Tier-4 (breit): %s, Tier-0: %s"
      % (_t_hebel, _t_breit, _t0))


def _kaufe(risk, tick, tier):
    """Kauft im echten Enginepfad und gibt (gekauft, grund) zurueck."""
    d = engine.Depot(start_wert=1000.0, risk=risk)
    d.bargeld = 1000.0
    aktionen = [{"typ": "kaufen", "ticker": tick, "menge": 10.0,
                 "preis": 10.0, "grund": "Test", "tier": tier}]
    engine.ausführen(d, aktionen, rc.params(risk))
    gekauft = tick in d.positions
    blockiert = [t for t in d.trades if t.get("typ") == "kauf_blockiert"]
    grund = blockiert[-1]["grund"] if blockiert else ""
    return gekauft, grund


# 1. Risk 0 muss einen Hebel blockieren
g0h, grund0h = _kaufe(0, _t_hebel, 6)
print("  Risk 0  + %s (Tier 6, Hebel) -> gekauft=%-5s %s"
      % (_t_hebel, g0h, grund0h))
pruefe("E2a Risk 0 blockiert den HEBEL-Kauf (Tier 6) im echten Enginepfad",
       not g0h, "Risk 0 hat den Hebel-Kauf durchgelassen")

# 2. Risk 0 muss eine breite ETF erlauben - das ist die
#    eigentliche Aenderung seit dem 27.09.2026
g0b, grund0b = _kaufe(0, _t_breit, 4)
print("  Risk 0  + %s (Tier 4, breit) -> gekauft=%-5s %s"
      % (_t_breit, g0b, grund0b))
pruefe("E2a2 Risk 0 erlaubt die breite ETF (Tier 4) im echten Enginepfad",
       g0b, "Risk 0 hat eine breite ETF blockiert: %s" % grund0b)

# 3. Risk 95 darf beides
g95h, _ = _kaufe(95, _t_hebel, 6)
g95b, grund95b = _kaufe(95, _t_breit, 4)
print("  Risk 95 + %s (Tier 6) -> gekauft=%s" % (_t_hebel, g95h))
print("  Risk 95 + %s (Tier 4) -> gekauft=%s %s"
      % (_t_breit, g95b, grund95b))
pruefe("E2b Risk 95 erlaubt den HEBEL-Kauf (Tier 6)",
       g95h, "Risk 95 hat den erlaubten Hebel-Kauf blockiert")
pruefe("E2b2 Risk 95 erlaubt die breite ETF (Tier 4)",
       g95b, "Risk 95 hat die breite ETF blockiert: %s" % grund95b)

# ─────────────────────────────────────────────────────────────────
print("\n=== E3: Positionslimit im echten signal_aktion-Pfad ===")
for risk in (0, 95):
    d = engine.Depot(start_wert=1000.0, risk=risk)
    d.bargeld = 1000.0
    # Kuenstliche Bewertung: 10 saubere Kandidaten, alle erlaubt
    bewertet = [{"ticker": "AAPL", "score": 90, "preis": 20.0, "tier": 1,
                 "uptrend": 1, "rsi": 55, "macd": 1, "bb_pos": 0.2,
                 "atr": 2.0, "vol_ratio": 1.2} for _ in range(1)]
    bewertet = []
    for i, t in enumerate(["AAPL", "MSFT", "JNJ", "PFE", "KO", "PEP", "WMT",
                           "T", "VZ", "XOM"]):
        bewertet.append({"ticker": t, "score": 90, "preis": 20.0, "tier": 1,
                         "uptrend": 1, "rsi": 55, "macd": 1, "bb_pos": 0.2,
                         "atr": 2.0, "vol_ratio": 1.2})
    aktionen = engine.signal_aktion(d, bewertet, rc.params(risk))
    kaeufe = [a for a in aktionen if a["typ"] == "kaufen"]
    print("  Risk %2d: %d Kauf-Aktionen, max_positions=%d, Summe investiert "
          "= %.2f von 1000.00"
          % (risk, len(kaeufe), rc.params(risk)["max_positions"],
             sum(a["menge"] * a["preis"] for a in kaeufe)))
    pruefe("E3.%d Risk %d: Anzahl Kaeufe <= max_positions" % (risk, risk),
           len(kaeufe) <= rc.params(risk)["max_positions"],
           "%d Kaeufe > max_positions %d"
           % (len(kaeufe), rc.params(risk)["max_positions"]))
    pruefe("E3.%d Risk %d: nie mehr als 100%% des Cash im einen Lauf" % (risk, risk),
           sum(a["menge"] * a["preis"] for a in kaeufe) <= 1000.0 * (1 - rc.params(risk)["cash_floor"]) + 1e-6,
           "mehr investiert als der Cash-Boden erlaubt")

# ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 74)
if FEHLER:
    print("FEHLGESCHLAGEN - %d Problem(e):" % len(FEHLER))
    for f in FEHLER:
        print("  - " + f)
    sys.exit(1)
print("BESTANDEN - alle E2E-Pruefungen gegen die echten Funktionen gruen")
sys.exit(0)
