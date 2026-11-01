"""Hebel-Muster: Gegenprobe ueber den echten Modulimport.

Kein Nachbauen des Musters im Test - der Test ruft die Funktion auf,
die im Betrieb laeuft. Ein Test, der das Muster selbst nachbaut,
prueft die Kopie und nicht das Produkt.

NACHGEMESSENE FEHLER in den ersten beiden Fassungen des Tests:
  1. Auslesen des Musters mit lstrip("|") zerstoerte die
     Wortgrenzen: aus "\\b\\d+" wurde "b\\d+". Danach matchte
     alles. Der Produktcode war in Ordnung, der Test nicht.
  2. Auslesen mit eval() ueber Teilzeilen liess die Schlusszeile
     mit re.I) in den Ausdruck.
Deshalb: importieren und aufrufen.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import sys

sys.path.insert(0, _MT_BASE)
import etf_beta

PROBE = [
    # (Name, muss_erkannt_werden)
    ("Direxion Small Cap Bull 3X ETF", True),
    ("ProShares UltraPro Dow30", True),
    ("ProShares Ultra S&P500", True),
    ("ProShares Ultra QQQ", True),
    ("Leverage Shares 2X Long TSLA", True),
    ("GraniteShares 2x Long MSFT Daily", True),
    ("Direxion Daily MU Bull 2X ETF", True),
    ("AdvisorShares MSOS Daily Leveraged 2X", True),
    ("T-Rex 2X Inverse Tesla Daily Target", True),
    # breite Fonds, die durch MUSSEN
    ("VanEck Semiconductor ETF", False),
    ("Global X Uranium ETF", False),
    ("State Street SPDR S&P 500 ETF Trust", False),
    ("Invesco QQQ Trust, Series 1", False),
    ("Vanguard S&P 500 ETF", False),
    ("Vanguard Russell 2000 ETF", False),
    ("SPDR S&P MidCap 400 ETF", False),
    ("iShares iBoxx $ High Yield Corp Bond", False),
    ("Vanguard Total Bond Market Index", False),
    # Die vier echten Yahoo-Namen aus der fertigen Liste.
    # Zwei davon sind kein Fehler und muessen bleiben:
    # UCO ist Rohoel (Beta 0,04), UGL ist Gold (Beta 0,50),
    # beide defensiv und richtig einsortiert.
    ("ProShares Ultra Bloomberg Crude", False),
    ("ProShares Ultra Gold", False),
    # Diese beiden muessen raus. Der Name ist bei 25
    # Zeichen abgeschnitten - genau daran scheitert das
    # Muster ohne die Korrektur.
    ("AdvisorShares MSOS Daily Levera", True),
    ("AdvisorShares MSOS Daily Leveraged ETF", True),
    # "Direxion Daily Homebuilders & S" endet mit "Bul" aus
    # "Bull" - ein Bull-ETF ist kein Hebel, bleibt also.
    ("Direxion Daily Homebuilders & S", False),
]

print()
print("=" * 76)
print("  Hebel-Muster: Gegenprobe gegen den laufenden Code")
print("=" * 76)
print()

fehl = falsch = 0
for name, soll in PROBE:
    ist = etf_beta.ist_einzeltitel_hebel(name)
    ok = ist == soll
    if not ok:
        if soll:
            fehl += 1
        else:
            falsch += 1
    print("  %-44s erwartet %-5s ist %-5s%s" % (
        name[:44], soll, ist, "" if ok else "   <-- FEHLER"))

print()
print("  Hebelprodukte übersehen: %d" % fehl)
print("  Breite Fonds fälschlich aussortiert: %d" % falsch)
print()

# Und der Derivat-Filter, der unabhängig davon arbeitet
print("  Derivat-Filter:")
# Krypto-Filter, eigenes Pruefverfahren
print()
print("  Krypto-Filter:")
kry_probe = [("BTC", True), ("IBIT", True), ("TETH", True),
             ("TETHW", True), ("ETHW", True), ("SOLZ", True),
             ("XRP", True), ("NASA", True), ("SMH", False),
             ("SOXX", False), ("SPY", False), ("QQQ", False),
             ("SMCY", False)]
k_fehl = 0
for t, soll in kry_probe:
    ist = etf_beta.ist_krypto(t)
    if ist != soll:
        k_fehl += 1
    print("    %-6s erwartet %-5s ist %-5s%s" % (
        t, soll, ist, "" if ist == soll else "   <-- FEHLER"))
print("  Krypto-Filter-Fehler: %d" % k_fehl)

der_probe = [("VXX", True), ("UVXY", True), ("SQQQ", True),
             ("SOXS", True), ("UPRO", True), ("TMF", True),
             ("SPY", False), ("QQQ", False), ("VTI", False),
             ("MSTY", True), ("NVDY", True)]

# 29.09.2026: Options-Einkommensfonds. Die fallen ueber die
# Tickerliste nicht, weil jeder Anbieter eigene Symbole hat -
# der Abgleich laeuft auf dem Namen. "SMCY" stand mit Beta 1,98
# ganz normal in Risk 90 und 52 Wochen bei -65,2 %.
aussch_probe = [("SMCY", "YieldMax SMCI Option Income Str", True),
                ("XYZW", "YieldMax Magnificent Seven Fund", True),
                ("QQQI", "Defiance S&P 500 Enhanced Options", True),
                ("SPY", "SPDR S&P 500 ETF Trust", False),
                ("QQQ", "Invesco QQQ Trust Series 1", False),
                ("VTI", "Vanguard Total Stock Market ETF", False),
                ("BND", "Vanguard Total Bond Market Index Fund", False)]
a_fehl = 0
for _t, _nm, _soll in aussch_probe:
    _ist = etf_beta.ist_derivat(_t, _nm)
    if _ist != _soll:
        a_fehl += 1
    print("    %-6s %-34s erwartet %-5s ist %-5s%s" % (
        _t, _nm[:34], _soll, _ist,
        "" if _ist == _soll else "   <-- FEHLER"))
d_fehl = 0
for t, soll in der_probe:
    ist = etf_beta.ist_derivat(t)
    if ist != soll:
        d_fehl += 1
    print("    %-6s erwartet %-5s ist %-5s%s" % (
        t, soll, ist, "" if ist == soll else "   <-- FEHLER"))

print()
print("  Derivat-Filter-Fehler: %d" % d_fehl)
gesamt = fehl + falsch + d_fehl + k_fehl + a_fehl
print()
print("  ERGEBNIS: %s" % ("alle %d Pruefungen bestanden" % (len(PROBE) + len(der_probe) + len(aussch_probe) + len(kry_probe))
                          if gesamt == 0
                          else "%d Abweichungen" % gesamt))
print("=" * 76)
print()

raise SystemExit(0 if gesamt == 0 else 1)
