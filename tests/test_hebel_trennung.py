"""Regressionstest: breite ETFs duerfen NICHT als Hebel gelten.

ANLASS (27.09.2026):
  Bei der Tier-Trennung wurde Tier 4 von "ETF/Hebel" auf
  "ETF breit" umgebucht und Tier 6 neu als "Hebel/Inverse"
  eingefuehrt. HEBEL_TIERS stand danach noch auf {3, 4} - es
  referenzierte die alte Bedeutung.

  Folge (gemessen bei cash 10000, Risk 95):

      ist_hebel_etf("SPY", 4) == True   -> Limit 3000,00
      ist_hebel_etf("GLD", 4) == True   -> Limit 3000,00
      ist_hebel_etf("XLU", 4) == True   -> Limit 3000,00

  SPY, GLD, XLU, IWM, XLK, QQQ, SLV, XLP, VNQ, VEA - die
  breitesten und risikoaermsten ETFs im Universum wurden wie ein
  3x-Produkt behandelt.

  ZWEITER BEFUND DESSELBEN ABSCHNITTS: batch_trader.py:576
  klemmte den Kaufbetrag mit max_betrag OHNE tier und OHNE
  hebel, waehrend der Controller-Aufruf weiter unten MIT beiden
  arbeitet. min() nahm dadurch den zu grossen Wert:

      Risk 95: Klemmung 3400, Limit 3000  -> 400 zu viel
      Risk 85: Klemmung 3200, Limit 3000  -> 200 zu viel
      Risk 80: Klemmung 3100, Limit 3000  -> 100 zu viel

  Der Controller blockte anschliessend korrekt - aber ein
  zulaessiger Kauf scheiterte an der Klemmung selbst.

  ZUSAMMENHANG: Beides gehoert zur selben Ursache. Die Trennung
  war nicht vollstaendig durchgezogen. Dieser Test haelt beide
  Seiten fest.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import io
import os
import re
import sys

sys.path.insert(0, _MT_BASE)
os.chdir(_MT_BASE)

bestanden = 0
fehlgeschlagen = 0


def pruefe(bedingung, name):
    global bestanden, fehlgeschlagen
    if bedingung:
        bestanden += 1
        print(f"  OK    {name}")
    else:
        fehlgeschlagen += 1
        print(f"  FEHL  {name}")


print("=" * 72)
print(" Hebel-Trennung: breite ETFs sind kein Hebel")
print("=" * 72)
print()

import risk_controller as rc
import risk_profile
import strategie

# ── 1. HEBEL_TIERS enthaelt Tier 6, nicht Tier 4 ─────────────
print("  HEBEL_TIERS:")
pruefe(6 in strategie.HEBEL_TIERS,
       f"Tier 6 (Hebel/Inverse) ist als Hebel markiert "
       f"({sorted(strategie.HEBEL_TIERS)})")
pruefe(4 not in strategie.HEBEL_TIERS,
       "Tier 4 (ETF breit) ist NICHT als Hebel markiert")
pruefe(rc.HEBEL_TIERS == strategie.HEBEL_TIERS,
       f"Controller und strategie sind sich einig "
       f"({sorted(rc.HEBEL_TIERS)})")

# ── 2. Breite ETFs gelten nicht als Hebel ───────────────────
BREIT = ["SPY", "VTI", "VOO", "IWM", "GLD", "SLV", "XLU",
         "XLP", "VNQ", "VEA", "XLK", "XLY", "XLF", "XLV"]
print()
print("  Breite ETFs - ist_hebel_etf():")
falsch = [t for t in BREIT
          if strategie.ist_hebel_etf(t, risk_profile.TICKER_TO_TIER.get(t))]
pruefe(not falsch,
       f"alle {len(BREIT)} breiten ETFs gelten nicht als Hebel"
       + (f" - ausser: {falsch}" if falsch else ""))

# ── 3. Echte Hebel gelten als Hebel ─────────────────────────
HEBEL = ["TQQQ", "SQQQ", "SOXL", "SOXS", "SPXS", "SPXU", "SDOW",
         "UPRO", "TZA", "FNGU", "FNGD", "TECL", "UVXY", "VIXY"]
print()
print("  Hebelprodukte - ist_hebel_etf():")
fehlend = [t for t in HEBEL
           if not strategie.ist_hebel_etf(t, risk_profile.TICKER_TO_TIER.get(t))]
pruefe(not fehlend,
       f"alle {len(HEBEL)} Hebelprodukte gelten als Hebel"
       + (f" - ausser: {fehlend}" if fehlend else ""))

# ── 4. Die Wirkung aufs Limit ───────────────────────────────
print()
print("  Limit bei cash 10000, Risk 95 (breit muss groesser sein):")
cash, risk = 10000.0, 95
sp_y = rc.max_betrag(cash, risk, tier=4,
                     hebel=strategie.ist_hebel_etf("SPY", 4))
t_q = rc.max_betrag(cash, risk, tier=6,
                    hebel=strategie.ist_hebel_etf("TQQQ", 6))
print(f"    SPY (Tier 4)  {sp_y:8.2f}")
print(f"    TQQQ (Tier 6) {t_q:8.2f}")
pruefe(sp_y > t_q,
       f"breite ETF erhaelt mehr als Hebel ({sp_y:.0f} > {t_q:.0f})")

# 01.10.2026: Die Festzahl 3400 ist durch die Eigenschaft ersetzt.
#
# 3400 war exakt 34% von 10000, also die alte Positionsgroesse
# 0.15 + 0.20*0.95. Nach der Umstellung auf 5-7 Positionen gilt
#     size = min(0.34, (1 - cash_floor) / max_positions)
# und bei Risk 95 ist der Anteil kleiner. 34% waere nur mit 2 bis 3
# Positionen oder negativem Cash-Boden moeglich - beides ist
# ausgeschlossen.
#
# "Voller Anteil" heisst inhaltlich: die breite ETF wird NICHT
# geklemmt. Geprueft wird das direkt, statt einen alten Zahlenwert
# festzuschreiben, der bei jeder kuenftigen Anpassung der Leiter
# rot wuerde, ohne dass die Eigenschaft falsch waere.
# Der Vergleich geht GEGEN die Quelle, nicht gegen einen zweiten Aufruf
# derselben Funktion: max_betrag(cash, risk, tier=4, hebel=False) waere
# genau die Zahl, die auch sp_y erzeugt - ein Vergleich damit kann eine
# verstaeckte Klemme nicht erkennen (Gegenprobe: 50%-Klemme fiel durch).
#
# Erwartet wird der analytische Wert: cash * position_size, gedeckelt nur
# durch cash selbst und den Cash-Boden. Alles darunter ist eine Klemme.
_size95 = rc.params(risk)["position_size"]
_erwartet = min(cash, cash * _size95,
                cash - cash * rc.params(risk)["cash_floor"])
pruefe(abs(sp_y - _erwartet) < 0.01,
       f"breite ETF erhaelt den vollen regulaeren Anteil "
       f"({sp_y:.2f}, analytisch erwartet {_erwartet:.2f})")
pruefe(sp_y > 0.0,
       "breite ETF erhaelt einen echten Betrag, nicht 0")
print(f"    Anteil: {sp_y/cash*100:.2f}% von cash (position_size "
      f"{rc.params(risk)['position_size']:.4f}, "
      f"max_positions {rc.params(risk)['max_positions']})")

# ── 5. Die Klemmung ruft max_betrag mit tier und hebel ──────
print()
print("  batch_trader.py - Betragsklemmung:")
bt = io.open((_MT_BASE + "/batch_trader.py"), encoding="utf-8").read()
code = "\n".join(z for z in bt.splitlines()
                 if not z.strip().startswith("#"))
m = re.search(r"_pos_frac\s*=\s*min\(\s*_pos_frac,\s*"
              r"rc_max_betrag\(([^)]*)\)", code, re.S)
pruefe(m is not None, "die Klemmung ruft max_betrag")
if m:
    argumente = m.group(1)
    hat_tier = "tier=" in argumente
    hat_hebel = "hebel=" in argumente
    pruefe(hat_tier, "die Klemmung gibt tier= an den Controller")
    pruefe(hat_hebel, "die Klemmung gibt hebel= an den Controller")
    if not (hat_tier and hat_hebel):
        print(f"        Argumente: {argumente.strip()[:90]}")

# ── 6. Kein Aufruf von max_betrag ohne tier mehr im Kaufpfad ─
print()
einfach = re.findall(
    r"rc_max_betrag\(\s*depot_obj\.bargeld\s*,\s*_risk_bt\s*\)", code)
pruefe(not einfach,
       f"kein Aufruf von max_betrag(cash, risk) mehr ohne tier "
       f"({len(einfach)})")

print()
print("=" * 72)
print(f" {bestanden} bestanden, {fehlgeschlagen} fehlgeschlagen")
print("=" * 72)

sys.exit(1 if fehlgeschlagen else 0)
