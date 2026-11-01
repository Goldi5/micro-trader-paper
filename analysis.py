#!/usr/bin/env python3
"""
Analyse-Modul – Trade-Analyse, Strategie-Bewertung, Risiko-Assessment.

Liefert Daten für den 📊 Analyse-Tab im Dashboard.
Analysiert alle drei Kategorien: Aktien, ETF, Spekulation.
"""
import os, json, sys
from datetime import datetime
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))

def lade_depots(prefix="depot_"):
    """Lädt alle Depot-Dateien mit bestimmtem Prefix."""
    depots = []
    exclude = ["summary"]  # summary-Dateien ausschließen
    for f in sorted(os.listdir(BASE)):
        if f.startswith(prefix) and f.endswith(".json") and not any(e in f for e in exclude):
            try:
                with open(os.path.join(BASE, f)) as fh:
                    depots.append(json.load(fh))
            except:
                pass
    return depots

def lade_spec_depots():
    """Lädt Spec-Depots, filtert aber leere Watchlist-Platzhalter raus.
    Nur Depots mit start>0 ODER shares>0 ODER trades>0 zählen als echtes
    Portfolio (wie dashboard.py data()). 38 leere Platzhalter (start=0) gehören
    in die Watchlist, nicht ins Performance-Portfolio."""
    sdd = os.path.join(BASE, "spec_depots")
    depots = []
    if os.path.isdir(sdd):
        for fn in sorted(os.listdir(sdd)):
            if fn.endswith(".json"):
                with open(os.path.join(sdd, fn)) as f:
                    d = json.load(f)
                if (d.get("start", 0) or 0) > 0 or (d.get("shares", 0) or 0) > 0 or len(d.get("trades", []) or []) > 0:
                    depots.append(d)
    return depots

def analyse_trades(depots, name=""):
    """Analysiert alle Trades aus einer Depot-Liste."""
    alle_trades = []
    for d in depots:
        trades = d.get("trades", [])
        if isinstance(trades, (int, float)):
            trades = []
        for t in trades:
            if isinstance(t, dict):
                t["_depot_risk"] = d.get("risk", "?")
                alle_trades.append(t)
    
    if not alle_trades:
        return {"name": name, "total": 0}
    
    buys = [t for t in alle_trades if t.get("typ","") in ("kaufen","kauf")]
    sells = [t for t in alle_trades if t.get("typ","") in ("verkaufen","verkauf")]
    
    # Win/Loss pro Ticker
    ticker_stats = defaultdict(lambda: {"buys": 0, "sells": 0, "volume": 0, "trades": 0})
    for t in alle_trades:
        ticker = t.get("ticker","?")
        ticker_stats[ticker]["trades"] += 1
        ticker_stats[ticker]["volume"] += t.get("menge", 0) * t.get("preis", 0)
        if t.get("typ","") in ("verkaufen","verkauf"):
            ticker_stats[ticker]["sells"] += 1
        else:
            ticker_stats[ticker]["buys"] += 1
    
    # Strategie (Grund) Analyse
    grund_stats = defaultdict(int)
    for t in alle_trades:
        g = t.get("grund", "unbekannt")[:20]
        grund_stats[g] += 1
    
    # Performance pro Risk-Stufe
    risk_perf = defaultdict(lambda: {"trades": 0, "volume": 0})
    for d in depots:
        r = d.get("risk", 0)
        trades = d.get("trades", [])
        if isinstance(trades, (int, float)):
            trades = []
        for t in trades:
            if isinstance(t, dict):
                risk_perf[r]["trades"] += 1
                risk_perf[r]["volume"] += t.get("menge", 0) * t.get("preis", 0)
    
    # Wert wie dashboard.py data(): Top-Level shares*avg_price (konsistent mit Spec-Tab)
    wert = sum(
        d.get("bargeld", 0) + (d.get("shares", 0) or 0) * (d.get("avg_price", 0) or 0)
        for d in depots
    )
    start = sum(d.get("start", 0) or 0 for d in depots)
    rendite = round((wert / start - 1) * 100, 2) if start > 0 else 0
    
    return {
        "name": name,
        "depots": len(depots),
        "total_trades": len(alle_trades),
        "buys": len(buys),
        "sells": len(sells),
        "wert": round(wert, 2),
        "start": round(start, 2),
        "rendite": rendite,
        "top_ticker": sorted(ticker_stats.items(), key=lambda x: x[1]["trades"], reverse=True)[:10],
        "grund_stats": dict(sorted(grund_stats.items(), key=lambda x: x[1], reverse=True)[:10]),
        "risk_perf": [{"risk": k, "trades": v["trades"], "volume": round(v["volume"], 2)} 
                      for k, v in sorted(risk_perf.items())],
    }

def analyse_risiko(depots, name=""):
    """Risiko-Assessment: Drawdown, Konzentration, VIX-Korrelation."""
    details = []
    ges_wert = 0
    ges_peak = 0
    max_drawdown = 0
    
    for d in depots:
        hist = d.get("historie", [])
        if isinstance(hist, (int, float)):
            hist = []
        if not hist:
            continue
        wert = d.get("bargeld", 0) + (d.get("shares", 0) or 0) * (d.get("avg_price", 0) or 0)
        ges_wert += wert
        
        # Max Drawdown
        peak = hist[0].get("wert", 100) or 100
        for h in hist:
            w = h.get("wert", 0) or 0
            if w > peak: peak = w
            dd = (peak - w) / peak * 100 if peak > 0 else 0
            if dd > max_drawdown: max_drawdown = dd
        if wert > ges_peak: ges_peak = wert
        
        # Konzentration
        pos_count = len(d.get("positions", {}))
        
        details.append({
            "risk": d.get("risk", "?"),
            "wert": round(wert, 2),
            "dd": round(max_drawdown, 1),
            "positionen": pos_count,
        })
    
    ges_dd = round((ges_peak - ges_wert) / max(ges_peak, 1) * 100, 1) if ges_peak > 0 else 0
    
    return {
        "name": name,
        "max_drawdown": round(max_drawdown, 1),
        "ges_drawdown": ges_dd,
        "depot_details": details,
    }

def run_all():
    """Führt alle Analysen aus und gibt ein Dict zurück."""
    aktien_depots = lade_depots("depot_")
    etf_depots = lade_depots("etf_")
    spec_depots = lade_spec_depots()
    
    return {
        "zeit": datetime.now().isoformat(),
        "aktien": analyse_trades(aktien_depots, "Aktien"),
        "etf": analyse_trades(etf_depots, "ETF"),
        "spekulation": analyse_trades(spec_depots, "Spekulation"),
        "risiko_aktien": analyse_risiko(aktien_depots, "Aktien"),
        "risiko_etf": analyse_risiko(etf_depots, "ETF"),
        "risiko_spekulation": analyse_risiko(spec_depots, "Spekulation"),
    }

def main():
    result = run_all()
    # Zusammenfassung
    for k, v in result.items():
        if k == "zeit": continue
        if isinstance(v, dict):
            w = v.get("wert", v.get("total_trades", 0))
            r = v.get("rendite", "")
            t = v.get("total_trades", 0)
            print(f"  {k:15s}  Wert=${w:<8}  Rendite={r}%  Trades={t}" if r != "" else f"  {k:15s}  Trades={t}  Drawdown={v.get('max_drawdown','?')}%")

    # Save cache
    cache_path = os.path.join(BASE, "analysis_cache.json")
    with open(cache_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Analyse gecached in {cache_path}")

if __name__ == "__main__":
    main()
