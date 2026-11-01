"""
Micro-Trader — Reparatur: leere Spec/ETF-Depots mit Startkapital initialisieren.
Plan B: Depots, die bargeld=0, shares=0 und keine trades haben, bekommen
Startkapital (100$), damit der Trader sie befüllen kann.
Regel Nr.1: vorher Backup (bereits in .backup/ vorhanden).
"""
import os, json, glob, shutil, time

BASE = os.path.dirname(os.path.abspath(__file__))
START_KAPITAL = 100.0

def repariere_spec():
    pfad = os.path.join(BASE, "spec_depots")
    n = 0
    for f in glob.glob(os.path.join(pfad, "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        b = d.get("bargeld", 0) or 0
        s = d.get("shares", 0) or 0
        tr = d.get("trades", [])
        # Leer + nie gehandelt -> reset auf Startkapital
        if b == 0 and s == 0 and len(tr) == 0:
            d["bargeld"] = START_KAPITAL
            if "start" not in d or not d.get("start"):
                d["start"] = START_KAPITAL
            if "start_wert" not in d:
                d["start_wert"] = START_KAPITAL
            json.dump(d, open(f, "w", encoding="utf-8"), indent=2)
            n += 1
    return n

def repariere_etf():
    n = 0
    for f in glob.glob(os.path.join(BASE, "etf_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        pos = d.get("positions", {})
        b = d.get("bargeld", 0) or 0
        pk = d.get("peak_wert", 0) or 0
        wert = b + sum(p.get("shares", 0) * p.get("avg_price", 0) for p in pos.values())
        dd = (pk - wert) / max(pk, 1) * 100 if pk else 0
        # Leer + nie gehandelt -> Startkapital
        if not pos and b == 0:
            d["bargeld"] = START_KAPITAL
            d["start_wert"] = START_KAPITAL
            d["peak_wert"] = START_KAPITAL
            n += 1
        # FALSCH gesperrt: DD<30% aber gesperrt -> entsperren
        if d.get("gesperrt") and dd < 30:
            d["gesperrt"] = False
            n += 1
        json.dump(d, open(f, "w", encoding="utf-8"), indent=2)
    return n

if __name__ == "__main__":
    s = repariere_spec()
    e = repariere_etf()
    print(f"Spec-Depots repariert: {s}")
    print(f"ETF-Depots repariert: {e}")
