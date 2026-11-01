"""Schreibt nach jedem Trader-Lauf eine echte Depotbewertung.

BEFUND (30.09.2026, 13:14)

Der Screenshot zeigte auf jeder Aktien-Depotkarte exakt $200.00
und +0.00 %:

    RISK 60   TDC   $200.00   +0.00%   1 Pos - $0 Cash
    RISK 90   TGB   $200.00   +0.00%   1 Pos - $0 Cash

Vier Befunde, alle gemessen:

  1) Die Karten lesen "cash", die Depots speichern "bargeld".
     data.get("cash", 0) liefert also 0 gegen ein echtes
     Guthaben -> "0 Cash" neben einer gefullten Position.

  2) Depot.speichern() schreibt kein "wert"-Feld. Alle 10
     Aktien-Depots enthalten die Schluessel
     aktualisiert, bargeld, depot_id, erstellt_am, exchanges,
     historie, ki_letzte, mode, name, positions, risk, seq,
     shares, start_wert, tenant_id, trades, zustand
     - aber kein wert, kein cash, kein gesamt_wert.
     Fehlt "wert", faellt der Leser auf start_wert zurueck,
     und die Summe stimmt aus dem richtigen Grund: jede
     Rendite ist dann exakt 0.00 %, unabhaengig vom Markt.

  3) Depot.wert() holt per hole_kurs(s) den Live-Kurs und
     faellt bei einem Fehler auf avg_price zurueck. Die
     Historie bekommt den Wert nur, wenn historie_aktualisieren()
     laeuft - und die wird genau einmal je Lauf gerufen, direkt
     nach dem Kauf. Deshalb hat jedes Depot genau EINEN
     Historieneintrag, und ein einzelner Zeitpunkt kann keine
     Kurve erzeugen.

  4) "Ticker - unbekannt": die Karten nehmen den Namen nicht
     aus den Positionsdaten.

Das Kapital ist vollstaendig - nachgerechnet und geschlossen:

    start_wert   2000.00
    Bargeld      1528.01
    Positionen    471.99  (Einstandswert)
    ------------------------
    gesamt       2000.00  = Startkapital

Es wurde also nichts verloren. Nur bewertet wurde nie.

DIE KUR
--------
Nicht im Leser, im Schreiber. Nach jedem Lauf:

    wert = bargeld + sum(shares * letzter Kurs)
    rendite = wert / start_wert - 1
    historie += {zeit, wert, bargeld}

Einstandspreis und Marktwert bleiben getrennte Groessen. Die
Rechnung am Einstand (bargeld + sum(shares * avg_price) =
start_wert) beweist, dass das Geld verbucht ist; die Rendite
behauptet Marktwert. Ein Leser darf das eine nicht fuer das
andere ausgeben.
"""
import io
import os
import sys
import time

sys.path.insert(0, "/opt/micro-trader")


def aktuelle_kurse(ticker, avg_price):
    """Letzten Kurs holen, Einstandspreis als Rueckfall.

    hole_kurs wirft bei einem nicht erreichbaren Kurs. Dann
    zaehlt der Einstandspreis: lieber eine Position zum
    Einstand bewerten als den ganzen Depotwert auf 0 setzen.
    """
    try:
        from engine import hole_kurs
        k = hole_kurs(ticker)
        if k and k > 0:
            return float(k), "markt"
    except Exception:
        pass
    return float(avg_price or 0), "einstand"


def bewerte_depot(datei, markt_kurs_fn=None):
    """Bewertet eine Depotdatei und schreibt wert/rendite/history zurueck.

    Gibt zurueck: dict mit vorher/nachher, oder None bei Fehler.
    """
    import json

    with io.open(datei, encoding="utf-8") as f:
        d = json.load(f)

    start = float(d.get("start_wert") or 0)
    bargeld = float(d.get("bargeld") or 0)
    positionen = d.get("positions") or {}

    if start <= 0:
        return None

    kurs_fn = markt_kurs_fn or aktuelle_kurse

    marktwert = 0.0
    einstand = 0.0
    kurs_quelle = {}
    titelnamen = {}
    for t, p in (positionen or {}).items():
        if not isinstance(p, dict):
            continue
        anteile = float(p.get("shares") or 0)
        ek = float(p.get("avg_price") or 0)
        einstand += anteile * ek
        kurs, quelle = kurs_fn(t, ek)
        marktwert += anteile * kurs
        kurs_quelle[t] = {"kurs": round(kurs, 4), "quelle": quelle,
                          "einstand": round(ek, 4)}
        # Name aus dem Ticker ableiten, wenn keiner gespeichert ist
        titelnamen[t] = d.get("namen", {}).get(t) or p.get("name") or ""

    wert = bargeld + marktwert
    rendite = wert / start - 1.0

    # Nur einen Punkt ergaenzen, wenn sich die Zeit wirklich
    # bewegt hat. Sonst fuellt ein Lauf, der nichts getan hat,
    # die Historie mit Duplikaten desselben Wertes.
    jetzt = time.strftime("%Y-%m-%dT%H:%M:%S")
    hist = d.get("historie") or []
    letzter = hist[-1] if hist else None
    if (letzter is None
            or letzter.get("zeit", "")[:16] != jetzt[:16]):
        hist.append({"zeit": jetzt, "wert": round(wert, 2),
                     "bargeld": round(bargeld, 2)})

    d["wert"] = round(wert, 2)
    d["rendite"] = round(rendite, 6)
    d["einstandswert"] = round(bargeld + einstand, 2)
    d["marktwert"] = round(marktwert, 2)
    d["kurs_quelle"] = kurs_quelle
    d["bewertet"] = jetzt
    d["historie"] = hist[-400:]
    if titelnamen and any(titelnamen.values()):
        d.setdefault("namen", {})
        d["namen"].update({k: v for k, v in titelnamen.items() if v})

    # Atomar: die alte Datei bleibt intakt, falls der Schreibvorgang
    # mitten im Lauf abbricht. Eine halb geschriebene Depotdatei
    # waere ein stiller Datenverlust im naechsten Lauf.
    tmp = datei + ".bewertet"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    os.replace(tmp, datei)

    return {
        "datei": os.path.basename(datei),
        "start": round(start, 2),
        "bargeld": round(bargeld, 2),
        "einstand": round(bargeld + einstand, 2),
        "marktwert": round(marktwert, 2),
        "wert": round(wert, 2),
        "rendite": round(rendite * 100, 2),
        "positionen": len(positionen or {}),
        "kurse": kurs_quelle,
    }


def _spek_positionen(d):
    """Spezulationsdepots fuehren shares/avg_price auf oberster
    Ebene statt in einem positions-Objekt. Beide Formen lesen,
    sonst fallen alle zehn aus dem Raster."""
    ps = d.get("positions")
    if isinstance(ps, dict) and ps:
        return {t: (v.get("shares", 0.0), v.get("avg_price", 0.0))
                for t, v in ps.items() if isinstance(v, dict)}
    sh = float(d.get("shares", 0) or 0)
    ap = float(d.get("avg_price", 0) or 0)
    if sh > 0 and d.get("ticker"):
        return {d["ticker"]: (sh, ap)}
    return {}


def bewerte_spek_depot(datei, markt_kurs_fn=None):
    """Bewertet eine Spekulationsdatei (Schema: shares/avg_price)."""
    import json

    with io.open(datei, encoding="utf-8") as f:
        d = json.load(f)

    start = float(d.get("start_wert") or d.get("start") or 0)
    bargeld = float(d.get("bargeld", 0))
    pos = _spek_positionen(d)
    if start <= 0:
        return None

    kurs_fn = markt_kurs_fn or aktuelle_kurse
    marktwert = einstand = 0.0
    kurs_quelle = {}
    for t, (anteile, ek) in pos.items():
        einstand += anteile * ek
        kurs, quelle = kurs_fn(t, ek)
        marktwert += anteile * kurs
        kurs_quelle[t] = {"kurs": round(kurs, 4), "quelle": quelle,
                          "einstand": round(ek, 4)}

    wert = bargeld + marktwert
    jetzt = time.strftime("%Y-%m-%dT%H:%M:%S")
    hist = d.get("historie") or []
    letzter = hist[-1] if hist else None
    if (letzter is None or letzter.get("zeit", "")[:16] != jetzt[:16]):
        hist.append({"zeit": jetzt, "wert": round(wert, 2),
                     "bargeld": round(bargeld, 2)})

    d["wert"] = round(wert, 2)
    d["rendite"] = round(wert / start - 1.0, 6)
    d["einstandswert"] = round(bargeld + einstand, 2)
    d["marktwert"] = round(marktwert, 2)
    d["kurs_quelle"] = kurs_quelle
    d["bewertet"] = jetzt
    d["historie"] = hist[-400:]

    tmp = datei + ".bewertet"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    os.replace(tmp, datei)

    return {"datei": os.path.basename(datei), "start": round(start, 2),
            "bargeld": round(bargeld, 2), "einstand": round(bargeld + einstand, 2),
            "marktwert": round(marktwert, 2), "wert": round(wert, 2),
            "rendite": round((wert / start - 1) * 100, 2),
            "positionen": len(pos), "kurs_quelle": kurs_quelle}


def bewerte_alle_ordner(basis, ordner=(".", "etf_*_01_paper.json")):
    """Alle drei Depotarten. Die Spekulation laeuft in einem
    eigenen Verzeichnis mit eigenem Schema."""
    import glob
    pfade = []
    for m in ordner:
        if m == ".":
            pfade += sorted(glob.glob(os.path.join(basis, "depot_*_paper.json")))
        else:
            pfade += sorted(glob.glob(os.path.join(basis, m)))
    out = [b for b in (bewerte_depot(p) for p in pfade) if b]
    # Spekulation: beide Verzeichnisse, weil der Modus sie waehlt.
    for d in ("spec_depots_paper", "spec_depots"):
        sd = os.path.join(basis, d)
        if os.path.isdir(sd):
            out += [b for b in
                    (bewerte_spek_depot(os.path.join(sd, fn))
                     for fn in sorted(os.listdir(sd)) if fn.endswith(".json"))
                    if b]
    return out


if __name__ == "__main__":
    ergebnisse = bewerte_alle_ordner("/opt/micro-trader")
    print("=== Depotbewertung ===")
    ges_start = ges_wert = 0.0
    for e in ergebnisse:
        flag = "" if abs(e["einstand"] - e["start"]) < 0.01 else "  <-- RECHNUNG OFFEN"
        print("  %-22s start=%-8s wert=%-8s %+6.2f%%  pos=%d%s"
              % (e["datei"], e["start"], e["wert"], e["rendite"],
                 e["positionen"], flag))
        ges_start += e["start"]
        ges_wert += e["wert"]
    if ges_start:
        print("  SUMME start=%.2f wert=%.2f  %+.2f%%"
              % (ges_start, ges_wert, (ges_wert / ges_start - 1) * 100))
