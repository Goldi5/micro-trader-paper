"""
WATCHLIST in spec_watch.py auf Top-20 reduzieren (Root-Cause: spec_watch.py
schreibt 152 Ticker nach spec_watch.json -> spec_trader.py baut 152 Spec-Depots
= ~15200 EUR gebunden). Backup liegt bereits vor (spec_watch.py.bak-*).
"""
import re, os

MT = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(MT, "spec_watch.py")

TOP20 = ["BBAI","FNGU","QS","SOUN","NRGU","BB","IONQ","MRNA","PLTR","TNA",
         "CRSP","SCO","RKLB","JDST","FAZ","BOIL","BITX","TQQQ","RGTI","QQQ"]

src = open(SP, encoding="utf-8").read()

# WATCHLIST-Block extrahieren: von 'WATCHLIST = {' bis zum schliessenden '}' auf eigenstaendiger Zeile
start = src.index("WATCHLIST = {")
# finde das Ende (erste Zeile die nur '}' ist nach start)
rest = src[start:]
end = rest.index("\n}\n") + len("\n}\n")
block = rest[:end]

# Alle Ticker-Eintraege im Block extrahieren
entries = {}
for m in re.finditer(r'^\s*"([A-Z0-9]+)":\s*\{[^}]*\},?', block, re.M):
    ticker = m.group(1)
    if ticker in TOP20:
        entries[ticker] = m.group(0).strip()

missing = [t for t in TOP20 if t not in entries]
print("Gefunden:", len(entries), "/ 20")
if missing:
    print("FEHLT in WATCHLIST:", missing)

# Neues WATCHLIST-Dict bauen
new_block = "WATCHLIST = {\n"
for t in TOP20:
    if t in entries:
        new_block += "    " + entries[t] + "\n"
new_block = new_block.rstrip("\n") + "\n}\n"

new_src = src[:start] + new_block + src[start+end:]
open(SP, "w", encoding="utf-8").write(new_src)
print("WATCHLIST auf", len(TOP20), "Ticker reduziert -> spec_watch.py gespeichert")
