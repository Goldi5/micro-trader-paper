"""
markt_daten_fuellen.py — P1: markt_daten Tabelle fuellen (Blocker Shadow->Paper)

Holt Kurs/RSI/SMA pro Ticker (aus spec_watchlist + Aktien/ETF-Depots) via
marktdaten.hole_kurs (4-Tier-Fallback, identisch mit Dashboard) und schreibt
in SQLite markt_daten (zeit, ticker, kurs, rsi, sma20, sma50).

Aufruf: python markt_daten_fuellen.py
"""
import os, json, glob, sqlite3
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "micro_trader.db")

def ticker_liste():
    t = set()
    # Spec-Watchlist
    try:
        wl = json.load(open(os.path.join(BASE, "spec_watchlist.json")))
        t.update(wl.get("ticker", []))
    except Exception:
        pass
    # Spec-Depots
    for f in glob.glob(os.path.join(BASE, "spec_depots", "*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
            if d.get("ticker"):
                t.add(d["ticker"])
        except Exception:
            pass
    # Aktien/ETF Paper-Positionen
    for pat in ["depot_*_paper.json", "etf_*_paper.json"]:
        for f in glob.glob(os.path.join(BASE, pat)):
            try:
                d = json.load(open(f, encoding="utf-8"))
                for tk in (d.get("positions", {}) or {}).keys():
                    t.add(tk)
            except Exception:
                pass
    return [x for x in t if x]

def rsi_berechnen(hist):
    """Einfache RSI aus Kurshistorie (close)."""
    try:
        import pandas as pd
        s = pd.Series([h.get("close", h.get("kurs", 0)) for h in hist if h.get("close") or h.get("kurs")])
        if len(s) < 15:
            return None
        delta = s.diff()
        up = delta.clip(lower=0).rolling(14).mean()
        down = (-delta.clip(upper=0)).rolling(14).mean()
        rs = up / down
        return float(100 - (100 / (1 + rs.iloc[-1])))
    except Exception:
        return None

def sma(hist, n):
    try:
        vals = [h.get("close", h.get("kurs", 0)) for h in hist if h.get("close") or h.get("kurs")]
        if len(vals) < n:
            return None
        return float(sum(vals[-n:]) / n)
    except Exception:
        return None

def fuelle_markt_daten():
    from marktdaten import hole_kurs
    tickers = ticker_liste()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS markt_daten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        zeit TEXT, ticker TEXT, kurs REAL, rsi REAL,
        sma20 REAL, sma50 REAL)""")
    ok = 0
    for t in tickers:
        try:
            kurs = hole_kurs(t)
            if not kurs or kurs <= 0:
                continue
            hist = []
            for f in glob.glob(os.path.join(BASE, "spec_depots", f"{t}.json")):
                d = json.load(open(f, encoding="utf-8"))
                hist = d.get("historie", [])
            rsi = rsi_berechnen(hist)
            s20 = sma(hist, 20)
            s50 = sma(hist, 50)
            c.execute("INSERT INTO markt_daten (zeit, ticker, kurs, rsi, sma20, sma50) VALUES (?,?,?,?,?,?)",
                      (now, t, kurs, rsi, s20, s50))
            ok += 1
        except Exception as e:
            print(f"  FEHLER {t}: {e}")
    conn.commit()
    conn.close()
    print(f"markt_daten gefuellt: {ok}/{len(tickers)} Ticker geschrieben.")
    return ok

def main():
    fuelle_markt_daten()

if __name__ == "__main__":
    main()
