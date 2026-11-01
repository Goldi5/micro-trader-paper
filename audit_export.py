"""
Micro-Trader — Audit-Export (Phase 20, §17)
Exportiert alle Trade-Entscheidungen + Depot-Stände als CSV/JSON für
Steuer/Transparenz/Audit-Trail.

Nutzt ki_log.json + depot_*.json + etf_*.json + spec_depots/*.json.
Ausgabe: audit/micro_trader_audit_YYYY-MM-DD.csv (und .json)
"""
import os
import json
import csv
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.join(BASE, "audit")
os.makedirs(AUDIT, exist_ok=True)


def lade_alle_depots():
    depots = []
    import glob
    for pattern in ["depot_*.json", "etf_*.json", "spec_depots/*.json"]:
        for f in sorted(glob.glob(os.path.join(BASE, pattern))):
            if "summary" in f:
                continue
            try:
                depots.append(json.load(open(f, encoding="utf-8")))
            except Exception:
                pass
    return depots


def export_csv(pfad):
    """Export aller KI-Entscheidungen als CSV (Steuer-relevant)."""
    ki_log = []
    kp = os.path.join(BASE, "ki_log.json")
    if os.path.exists(kp):
        ki_log = json.load(open(kp, encoding="utf-8"))

    trades = [e for e in ki_log if e.get("typ") == "decision" and e.get("aktion") in ("kaufen", "verkaufen")]

    with open(pfad, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Datum", "Ticker", "Aktion", "Menge", "Kurs", "Konfidenz",
                    "Grund", "RSI", "Trend", "Depot-Typ", "Risk", "Regime", "Decision-ID"])
        for t in trades:
            w.writerow([
                t.get("zeit", "")[:19], t.get("ticker", ""), t.get("aktion", ""),
                t.get("menge", ""), t.get("kurs", ""), t.get("konfidenz", ""),
                (t.get("grund", "") or "")[:100], t.get("rsi", ""), t.get("trend", ""),
                t.get("depot_typ", ""), t.get("risk", ""), t.get("regime", ""),
                t.get("decision_id", "")
            ])
    return len(trades)


def export_json(pfad):
    """Vollständiger Audit-Trail als JSON (alle Entscheidungen + Depot-Stände)."""
    ki_log = []
    kp = os.path.join(BASE, "ki_log.json")
    if os.path.exists(kp):
        ki_log = json.load(open(kp, encoding="utf-8"))

    depots = lade_alle_depots()
    snapshot = {
        "export_zeit": datetime.now().isoformat(),
        "version": json.load(open(os.path.join(BASE, "version.json"), encoding="utf-8")).get("version", "?"),
        "ki_log_eintraege": len(ki_log),
        "depots": len(depots),
        "depot_stand": [
            {
                "ticker": d.get("ticker", "?"),
                "typ": d.get("typ", d.get("kategorie", "unbekannt")),
                "shares": d.get("shares", 0),
                "bargeld": d.get("bargeld", 0),
                "start": d.get("start", d.get("start_wert", 0)),
            }
            for d in depots
        ],
        "ki_log": ki_log,
    }
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    return len(ki_log)


if __name__ == "__main__":
    heute = datetime.now().strftime("%Y-%m-%d")
    csv_pfad = os.path.join(AUDIT, f"micro_trader_audit_{heute}.csv")
    json_pfad = os.path.join(AUDIT, f"micro_trader_audit_{heute}.json")

    n_trades = export_csv(csv_pfad)
    n_log = export_json(json_pfad)

    print(f"Audit-Export erstellt:")
    print(f"  CSV:  {csv_pfad} ({n_trades} Trades)")
    print(f"  JSON: {json_pfad} ({n_log} KI-Log-Einträge)")
