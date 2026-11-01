#!/usr/bin/env python3
"""
Spekulation-Watch – sammelt täglich Daten zu:
  - Crypto-ETFs (IBIT, ETHA, BITO)
  - Inverse ETFs (SQQQ, SPXS)
  - Volatility (UVXY, VIXY)
  - Leveraged Commodity (JNUG, BOIL, NRGU)
  
Rein passiv – kein Handel, nur Daten + Auswertung.
"""
import sys, os, json, time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import yfinance as yf
import pandas as pd
import numpy as np

# ─── Beobachtete Instrumente ─────────────────────────────────
WATCHLIST = {
    "BBAI":  {"name": "BigBear.ai Holdings",       "kat": "ai",        "hebel": 1},
    "FNGU":  {"name": "MicroSectors FANG+ 3x",    "kat": "lev-bull",  "hebel": 3},
    "QS":    {"name": "QuantumScape Corp.",         "kat": "ev",        "hebel": 1},
    "SOUN":  {"name": "SoundHound AI",             "kat": "ai",        "hebel": 1},
    "NRGU":  {"name": "MicroSectors FANG+ 3x",    "kat": "commodity",  "hebel": 3},
    "BB":    {"name": "BlackBerry Ltd.",           "kat": "meme",      "hebel": 1},
    "MRNA":  {"name": "Moderna Inc.",              "kat": "biotech",   "hebel": 1},
    "PLTR":  {"name": "Palantir Technologies",     "kat": "ai",        "hebel": 1},
    "TNA":   {"name": "Direxion SmallCap Bull 3x","kat": "lev-bull",  "hebel": 3},
    "CRSP":  {"name": "CRISPR Therapeutics",       "kat": "biotech",   "hebel": 1},
}

CACHE_FILE = os.path.join(BASE, ".spec_cache.json")
LOG_FILE = os.path.join(BASE, "spec_log.json")

def fetch_and_analyze():
    """Holt Daten für alle Watchlist-Instrumente, berechnet Metriken."""
    ticker_list = list(WATCHLIST.keys())
    
    daten = yf.download(ticker_list, period="6mo", interval="1d", 
                        progress=False, auto_adjust=True)
    
    ist_multi = isinstance(daten.columns, pd.MultiIndex)
    
    ergebnis = {}
    now = datetime.now()
    
    for ticker in ticker_list:
        meta = WATCHLIST[ticker]
        try:
            if ist_multi:
                # yfinance MultiIndex: (Attribut, Ticker) — z.B. ('Close', 'IBIT')
                close = daten['Close'][ticker].dropna() if 'Close' in daten and ticker in daten['Close'] else None
                vol = daten['Volume'][ticker].dropna() if 'Volume' in daten and ticker in daten['Volume'] else None
            else:
                close = daten['Close'].dropna() if 'Close' in daten else None
                vol = daten['Volume'].dropna() if 'Volume' in daten else None
        except:
            # Fallback: Ticker einzeln
            try:
                t = yf.Ticker(ticker)
                h = t.history(period="6mo")
                close = h['Close'].dropna() if 'Close' in h else None
                vol = h['Volume'].dropna() if 'Volume' in h else None
            except:
                continue
        
        if close is None or len(close) < 20:
            continue
        
        aktuell = float(close.iloc[-1])
        vortag = float(close.iloc[-2]) if len(close) > 1 else aktuell
        tagesrendite = ((aktuell / vortag) - 1) * 100
        
        # SMA
        sma20 = float(close.tail(20).mean())
        sma50 = float(close.tail(50).mean()) if len(close) >= 50 else sma20
        
        # Volatilität (annualisiert)
        daily_returns = close.pct_change().dropna()
        volatilitaet = float(daily_returns.tail(20).std() * np.sqrt(252) * 100)
        
        # Max Drawdown
        cummax = close.cummax()
        drawdown = ((close - cummax) / cummax * 100)
        max_dd = float(drawdown.min()) if len(drawdown) > 0 else 0
        
        # Sharpe Ratio (vereinfacht, risikoloser Zins = 0)
        sharpe = float(daily_returns.tail(60).mean() / daily_returns.tail(60).std() * np.sqrt(252)) if len(daily_returns) >= 60 else 0
        
        # Kursänderung 5 Tage
        if len(close) >= 6:
            woche = ((float(close.iloc[-1]) / float(close.iloc[-6])) - 1) * 100
        else:
            woche = 0
        
        # 30 Tage
        if len(close) >= 31:
            monat = ((float(close.iloc[-1]) / float(close.iloc[-31])) - 1) * 100
        else:
            monat = 0
        
        # Trend-Richtung
        uptrend = 1 if aktuell > sma20 > sma50 else (0 if aktuell < sma20 < sma50 else 0.5)
        
        ergebnis[ticker] = {
            "name": meta["name"],
            "kategorie": meta["kat"],
            "hebel": meta["hebel"],
            "aktuell": round(aktuell, 2),
            "tagesrendite": round(tagesrendite, 2),
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2),
            "uptrend": uptrend,
            "volatilitaet": round(volatilitaet, 1),
            "max_drawdown": round(max_dd, 1),
            "sharpe": round(sharpe, 2),
            "woche": round(woche, 2),
            "monat": round(monat, 2),
            "letztes_update": now.isoformat(),
        }
    
    return ergebnis

def log_verlauf(ticker_data):
    """Hängt täglichen Snapshot an Log-Datei an."""
    log = {"zeit": datetime.now().isoformat(), "daten": ticker_data, "instrumente": list(WATCHLIST.keys())}
    
    # Alte Logs laden
    history = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                history = json.load(f)
        except:
            history = []
    
    # Nur 90 Tage behalten
    history.append(log)
    if len(history) > 90:
        history = history[-90:]
    
    with open(LOG_FILE, "w") as f:
        json.dump(history, f, indent=1)

def analyse():
    """Erstellt Zusammenfassung der gesammelten Daten."""
    if not os.path.exists(LOG_FILE):
        return {"fehler": "Noch keine Daten gesammelt"}
    
    with open(LOG_FILE) as f:
        logs = json.load(f)
    
    if len(logs) < 2:
        return {"fehler": "Weniger als 2 Datenpunkte"}
    
    # Beste/schlechteste Instrumente im Beobachtungszeitraum
    letzter = logs[-1]["daten"]
    erster = logs[0]["daten"]
    
    vergleich = {}
    for ticker, info in letzter.items():
        if ticker in erster:
            erst_preis = erster[ticker].get("aktuell", 0)
            if erst_preis > 0:
                rendite = (info["aktuell"] / erst_preis - 1) * 100
            else:
                rendite = 0
            vergleich[ticker] = {
                "name": info["name"],
                "kategorie": info["kategorie"],
                "rendite": round(rendite, 2),
                "volatilitaet": info["volatilitaet"],
                "sharpe": info["sharpe"],
            }
    
    # Sortieren
    best = sorted(vergleich.items(), key=lambda x: -x[1]["rendite"])
    worst = sorted(vergleich.items(), key=lambda x: x[1]["rendite"])
    
    return {
        "zeitraum": f"{logs[0]['zeit'][:10]} → {logs[-1]['zeit'][:10]}",
        "tage": len(logs),
        "best": [{"ticker": t, **v} for t, v in best[:3]],
        "worst": [{"ticker": t, **v} for t, v in worst[:3]],
        "vergleich": vergleich,
    }

if __name__ == "__main__":
    quiet = "--quiet" in sys.argv
    
    if not quiet:
        print("📡 Spekulation-Watch – sammle Daten...", flush=True)
    
    try:
        daten = fetch_and_analyze()
        log_verlauf(daten)
        
        if not quiet:
            print(f"   ✅ {len(daten)} Instrumente aktualisiert", flush=True)
            
            # Kurzübersicht
            for ticker, info in sorted(daten.items(), key=lambda x: x[1]["kategorie"]):
                pfeil = "🟢" if info["tagesrendite"] > 1 else ("🔴" if info["tagesrendite"] < -1 else "⚪")
                print(f"   {pfeil} {ticker:>5} [{info['kategorie']:>10}]  ${info['aktuell']:<8}  {info['tagesrendite']:>+5.1f}%  Vola {info['volatilitaet']:.0f}%", flush=True)
        
        # Analyse
        if len(daten) > 0 and os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f:
                logs = json.load(f)
            if len(logs) >= 2:
                a = analyse()
                if "fehler" not in a:
                    if not quiet:
                        print(f"\n📊 Analyse ({a['zeitraum']})", flush=True)
                        for e in a["best"]:
                            print(f"   🏆 {e['ticker']} ({e['name']})  {e['rendite']:+.1f}%  Sharpe {e['sharpe']}", flush=True)
                        for e in a["worst"]:
                            print(f"   🗑️ {e['ticker']} ({e['name']})  {e['rendite']:+.1f}%  Sharpe {e['sharpe']}", flush=True)
        
        # Save latest for dashboard
        spfad = os.path.join(BASE, "spec_watch.json")
        with open(spfad, "w") as f:
            json.dump(daten, f, indent=2)
            
    except Exception as e:
        print(f"❌ Fehler: {e}", flush=True)
