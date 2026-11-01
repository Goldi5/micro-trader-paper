"""Gegenprobe: Sind die sieben Depots wirklich diversifiziert?

Liest die Empfehlung und prueft fuer jedes Depot die paarweisen
Korrelationen. Ein Depot mit Paaren ueber 0,75 ist faktisch ein
ETF, nur teurer und mit mehr Ordergebuehr.
"""

import json

P = "/opt/micro-trader/empfehlung_depotreihe.json"

with open(P, encoding="utf-8") as f:
    d = json.load(f)

korr = {}
for k in d["korrelationen"]:
    korr[(k["a"], k["b"])] = k["korr"]
    korr[(k["b"], k["a"])] = k["korr"]


def c(a, b):
    return korr.get((a, b))


print(f"  {d['bestanden']} Titel bestanden von {d['geprueft']} geprueft")
print(f"  {len(d['korrelationen'])} Paare gespeichert")
print()

probleme = 0
for dp in d["depots"]:
    t = dp["ticker"]
    paare, hoch, fehlen = [], [], []
    for i in range(len(t)):
        for j in range(i + 1, len(t)):
            v = c(t[i], t[j])
            if v is None:
                fehlen.append(f"{t[i]}/{t[j]}")
            else:
                paare.append(v)
                if v > 0.75:
                    hoch.append(f"{t[i]}/{t[j]}={v:+.2f}")

    avg = sum(paare) / len(paare) if paare else None
    marke = ""
    if hoch:
        marke = "  <-- ENGE PAARE"
        probleme += 1
    if avg is None:
        print(f"  Risk {dp['risk']:2d}: {len(t)} Titel, KEINE Paardaten")
        probleme += 1
        continue

    print(f"  Risk {dp['risk']:2d}: {len(t)} Titel  "
          f"OK-Korr {avg:+.2f}  max {max(paare):+.2f}  "
          f"min {min(paare):+.2f}{marke}")
    if hoch:
        print(f"           {', '.join(hoch)}")
    if fehlen:
        print(f"           ohne Paardaten: {', '.join(fehlen)}")

print()
print(f"  Depots mit engen Paaren: {probleme}")
if probleme == 0:
    print("  Alle Depots sind ausreichend diversifiziert.")
