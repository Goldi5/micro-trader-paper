#!/usr/bin/env python3
"""Nachvollziehbarkeit: Das Log lesbar machen.

Ohne dieses Werkzeug ist events.jsonl eine Datenhalde. Damit stellst
du die Fragen, die bei einem Handelssystem wirklich zaehlen:

    ./mtlog_query.py laeufe                     alle Läufe, newest first
    ./mtlog_query.py lauf <run-id>              ein Lauf, chronologisch
    ./mtlog_query.py heute                      alles von heute
    ./mtlog_query.py entscheidungen             alle Entscheidungen
    ./mtlog_query.py trades                     alle Ausführungen
    ./mtlog_query.py fehler                     nur Fehler
    ./mtlog_query.py was_hat_der_trader_gemacht  Tagesbericht
    ./mtlog_query.py suche AAPL                 Volltextsuche
    ./mtlog_query.py schritt ki_call            alle KI-Aufrufe
    ./mtlog_query.py diagnose                   Gesundheitspruefung
    ./mtlog_query.py wer_hat_gekauft            Ticker-Haeufigkeit

Alle Ausgaben gehen nach stdout, Farben nur wenn es ein Terminal ist.
"""

import io
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "logs", "events.jsonl")

FARBE = sys.stdout.isatty()
C = {
    "rot": "\033[31m", "gruen": "\033[32m", "gelb": "\033[33m",
    "blau": "\033[34m", "grau": "\033[90m", "dick": "\033[1m",
    "aus": "\033[0m",
}


def f(farbe, text):
    return f"{C[farbe]}{text}{C['aus']}" if FARBE else str(text)


def lade(zeitgrenze=None):
    """Liest alle Ereignisse, optional ab einem Zeitpunkt."""
    if not os.path.exists(LOG):
        print(f"Keine Logdatei: {LOG}")
        return []
    gut, kaputt = [], 0
    with io.open(LOG, encoding="utf-8", errors="replace") as f:
        for zeile in f:
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                e = json.loads(zeile)
            except json.JSONDecodeError:
                kaputt += 1
                continue
            if zeitgrenze:
                ts = e.get("ts", "")[:19]
                if ts and ts < zeitgrenze:
                    continue
            gut.append(e)
    if kaputt:
        print(f"Warnung: {kaputt} unlesbare Zeilen uebersprungen", file=sys.stderr)
    return gut


def kurz(e, breite=110):
    """Eine Zeile je Ereignis, fuer die schnelle Uebersicht."""
    ts = e.get("ts", "")[11:23]
    lvl = e.get("level", "?")
    run = (e.get("run") or "")[:8]
    schritt = e.get("schritt") or ""
    msg = e.get("msg", "")
    felder = []
    for k, v in e.items():
        if k in ("ts", "level", "modul", "pid", "msg", "run", "schritt",
                 "traceback"):
            continue
        felder.append(f"{k}={v}")
    zusatz = " ".join(felder[:6])
    zeile = f"{f('grau', ts)} [{f('blau', run):<9}] {msg}"
    if schritt:
        zeile = f"{f('grau', ts)} [{f('blau', run):<9}] {f('gelb', f'({schritt})')} {msg}"
    if zusatz:
        zeile += f"  {f('grau', zusatz[:breite])}"
    if lvl in ("ERROR", "CRITICAL"):
        zeile = f"{f('rot', zeile)}"
    elif lvl == "WARNING":
        zeile = f"{f('gelb', zeile)}"
    return zeile


# ─────────────────────────────────────────────────────────────────────
def cmd_laeufe(daten, args=None):
    laeufe = defaultdict(list)
    for e in daten:
        if e.get("run"):
            laeufe[e["run"]].append(e)
    if not laeufe:
        print("Keine Läufe im Log.")
        return
    print(f"{'RUN-ID':<14} {'START':<21} {'ENDE':<21} {'ZEILEN':>7}  ART")
    print("-" * 92)
    for rid, evs in sorted(laeufe.items(),
                           key=lambda kv: kv[1][0].get("ts", ""),
                           reverse=True)[:40]:
        start = evs[0].get("ts", "")[:19].replace("T", " ")
        ende = ""
        art = ""
        for e in evs:
            if e.get("schritt") == "ende":
                ende = e.get("ts", "")[:19].replace("T", " ")
                art = e.get("event", "")
            elif e.get("schritt") == "abbruch":
                ende = e.get("ts", "")[:19].replace("T", " ") + "!"
                art = e.get("event", "") + " ABGEBROCHEN"
        if not art:
            art = evs[0].get("event", "?")
        fehler = sum(1 for e in evs if e.get("level") == "ERROR")
        marke = f"  {f('rot', str(fehler) + ' FEHLER')}" if fehler else ""
        print(f"{rid:<14} {start:<21} {ende or '(läuft)':<21} "
              f"{len(evs):>7}  {art}{marke}")


def cmd_lauf(daten, args):
    if not args:
        print("Aufruf: mtlog_query.py lauf <run-id>")
        return
    rid = args[0]
    evs = [e for e in daten if e.get("run", "").startswith(rid)]
    if not evs:
        print(f"Kein Lauf mit ID {rid}")
        return
    print(f"=== Lauf {rid}: {len(evs)} Ereignisse ===\n")
    for e in evs:
        print(kurz(e))
        if e.get("traceback"):
            for z in e["traceback"].strip().splitlines():
                print(f"    {f('rot', z)}")


def cmd_entscheidungen(daten, args):
    evs = [e for e in daten if e.get("typ") == "entscheidung"]
    if not evs:
        print("Keine Entscheidungen protokolliert.")
        return
    if args:
        evs = [e for e in evs if args[0].upper() in
               (e.get("ticker", "") + e.get("aktion", "")).upper()]
    print(f"=== {len(evs)} Entscheidungen ===\n")
    print(f"{'ZEIT':<12} {'AKTION':<10} {'TICKER':<8} {'KONF':>5}  GRUND")
    print("-" * 100)
    for e in evs[-60:]:
        konf = e.get("konfidenz", "")
        aktion = e.get("aktion", "?")
        farbe = {"kaufen": "gruen", "verkaufen": "rot"}.get(aktion, "gelb")
        grund = str(e.get("grund", e.get("begruendung", "")))[:62]
        print(f"{e.get('ts','')[11:19]:<12} {f(farbe, aktion):<19} "
              f"{e.get('ticker','-'):<8} {str(konf):>5}  {grund}")


def cmd_trades(daten, args):
    evs = [e for e in daten if e.get("typ") == "trade"]
    if not evs:
        print("Keine Ausführungen protokolliert.")
        return
    print(f"=== {len(evs)} Ausführungen ===\n")
    print(f"{'ZEIT':<12} {'AKTION':<10} {'TICKER':<8} {'MENGE':>8} {'PREIS':>10} {'WERT':>12}")
    print("-" * 72)
    summe = 0.0
    for e in evs[-60:]:
        wert = float(e.get("wert", 0) or 0)
        summe += wert
        aktion = e.get("aktion", "?")
        farbe = {"kaufen": "gruen", "verkaufen": "rot"}.get(aktion, "gelb")
        print(f"{e.get('ts','')[11:19]:<12} {f(farbe, aktion):<19} "
              f"{e.get('ticker','-'):<8} {str(e.get('menge','')):>8} "
              f"{str(e.get('preis','')):>10} {wert:>12.2f}")
    print(f"\n  Summe gehandeltes Volumen: {summe:.2f}")


def cmd_fehler(daten, args):
    evs = [e for e in daten if e.get("level") in ("ERROR", "CRITICAL")]
    if not evs:
        print(f"{f('gruen', 'Keine Fehler im Log.')}")
        return
    # Haeufigste Ursachen zusammenfassen
    print(f"=== {len(evs)} Fehler, haeufigste zuerst ===\n")
    gruppen = defaultdict(list)
    for e in evs:
        nachricht = str(e.get("msg", ""))[:70]
        gruppen[nachricht].append(e)
    for nachricht, liste in sorted(gruppen.items(),
                                   key=lambda kv: -len(kv[1])):
        letzte = max(liste, key=lambda e: e.get("ts", ""))
        print(f"  {len(liste):>4}x  {nachricht}")
        print(f"        letzte: {letzte.get('ts','')[:19].replace('T',' ')}"
              f"  [{letzte.get('run','')[:8]}]")
        if liste[0].get("traceback"):
            z = liste[0]["traceback"].strip().splitlines()[-1]
            print(f"        {f('rot', z[:100])}")
        print()


def cmd_suche(daten, args):
    if not args:
        print("Aufruf: mtlog_query.py suche <begriff>")
        return
    begriff = args[0].lower()
    treffer = [e for e in daten
               if begriff in json.dumps(e, ensure_ascii=False).lower()]
    print(f"=== {len(treffer)} Treffer für '{args[0]}' ===\n")
    for e in treffer[-50:]:
        print(kurz(e))


def cmd_schritt(daten, args):
    if not args:
        print("Aufruf: mtlog_query.py schritt <name>")
        return
    evs = [e for e in daten if e.get("schritt") == args[0]]
    print(f"=== {len(evs)} Ereignisse im Schritt '{args[0]}' ===\n")
    for e in evs[-50:]:
        print(kurz(e))


def cmd_wer_hat_gekauft(daten, args):
    kauf = Counter()
    verkauf = Counter()
    for e in daten:
        if e.get("typ") != "trade":
            continue
        t = e.get("ticker", "?")
        if e.get("aktion") == "kaufen":
            kauf[t] += 1
        elif e.get("aktion") == "verkaufen":
            verkauf[t] += 1
    if not kauf and not verkauf:
        print("Keine Trades protokolliert.")
        return
    print(f"{'TICKER':<10} {'KÄUFE':>7} {'VERKÄUFE':>9}")
    print("-" * 28)
    for t, n in kauf.most_common(30):
        print(f"{t:<10} {n:>7} {verkauf.get(t, 0):>9}")


def cmd_was_hat_gemacht(daten, args):
    """Der Tagesbericht: die Frage, die man wirklich stellt."""
    heute = datetime.now().strftime("%Y-%m-%d")
    evs = [e for e in daten if e.get("ts", "").startswith(heute)]
    if not evs:
        # Auf den letzten Tag mit Aktivitaet zurueckfallen
        tage = sorted({e.get("ts", "")[:10] for e in daten if e.get("ts")})
        if not tage:
            print("Das Log ist leer.")
            return
        letzte = tage[-1]
        evs = [e for e in daten if e.get("ts", "").startswith(letzte)]
        print(f"Heute noch nichts. Zeige stattdessen den {letzte}:\n")

    laeufe = {e["run"] for e in evs if e.get("run")}
    fehler = [e for e in evs if e.get("level") in ("ERROR", "CRITICAL")]
    warnungen = [e for e in evs if e.get("level") == "WARNING"]
    entsch = [e for e in evs if e.get("typ") == "entscheidung"]
    trades = [e for e in evs if e.get("typ") == "trade"]
    metriken = [e for e in evs if e.get("typ") == "metrik"]

    print(f"{'=' * 70}")
    print(f" WAS HAT DER TRADER GEMACHT?  ({evs[0].get('ts','')[:10]})")
    print(f"{'=' * 70}\n")
    print(f"  Läufe          {len(laeufe)}")
    print(f"  Ereignisse     {len(evs)}")
    print(f"  Entscheidungen {len(entsch)}")
    print(f"  Ausführungen   {len(trades)}")
    print(f"  Warnungen      {len(warnungen)}")
    print(f"  Fehler         {len(fehler)}")

    if entsch:
        aktionen = Counter(e.get("aktion", "?") for e in entsch)
        print("\n  Entscheidungen nach Aktion:")
        for a, n in aktionen.most_common():
            print(f"    {a:<12} {n}")

    if trades:
        volumen = sum(float(e.get("wert", 0) or 0) for e in trades)
        print(f"\n  Gehandeltes Volumen: {volumen:.2f}")

    if metriken:
        print("\n  Kennzahlen:")
        for e in metriken[-10:]:
            print(f"    {e.get('metrik','?'):<24} {e.get('wert')}")

    if laeufe:
        print(f"\n  {'LETZTE LÄUFE':<40}")
        nach_runs = defaultdict(list)
        for e in evs:
            if e.get("run"):
                nach_runs[e["run"]].append(e)
        for rid, ls in sorted(nach_runs.items(),
                              key=lambda kv: kv[1][0].get("ts", ""),
                              reverse=True)[:8]:
            ende = next((e for e in ls if e.get("schritt") == "ende"), None)
            abbruch = any(e.get("schritt") == "abbruch" for e in ls)
            art = (ende or ls[0]).get("event", "?")
            dauer = (ende or {}).get("dauer_s", "?")
            zustand = (f"{f('rot', 'ABGEBROCHEN')}" if abbruch
                       else f"{f('gruen', 'OK')} in {dauer}s")
            print(f"    {rid[:8]}  {art:<22} {zustand}")

    if fehler:
        print(f"\n  {f('rot', 'FEHLER IM DETAIL:')}")
        for e in fehler[-5:]:
            print(f"    {e.get('ts','')[11:19]}  {e.get('msg','')[:70]}")

    print()


def cmd_diagnose(daten, args):
    print("=== LOG-GESUNDHEIT ===\n")
    for datei in ("events.jsonl", "trader.log", "fehler.log"):
        p = os.path.join(BASE, "logs", datei)
        if os.path.exists(p):
            kb = os.path.getsize(p) / 1024
            print(f"  {datei:<20} {kb:>10.1f} KB")
        else:
            print(f"  {datei:<20} {'fehlt':>10}")

    # Generationen
    gen = sorted(f for f in os.listdir(os.path.join(BASE, "logs"))
                 if f.startswith("events.jsonl."))
    if gen:
        gesamt = sum(os.path.getsize(os.path.join(BASE, "logs", f))
                     for f in os.listdir(os.path.join(BASE, "logs")))
        print(f"\n  {len(gen)} Rotationsgenerationen, "
              f"gesamt {gesamt / 1024 / 1024:.1f} MB im logs/-Verzeichnis")

    if not daten:
        print("\n  Log ist leer.")
        return

    level = Counter(e.get("level") for e in daten)
    print(f"\n  Verteilung:")
    for lv, n in level.most_common():
        print(f"    {lv:<10} {n}")

    typen = Counter(e.get("typ") for e in daten if e.get("typ"))
    if typen:
        print(f"\n  Typen:")
        for t, n in typen.most_common():
            print(f"    {t:<14} {n}")

    tage = Counter(e.get("ts", "")[:10] for e in daten if e.get("ts"))
    if len(tage) > 1:
        print(f"\n  Tage: {len(tage)}, von {min(tage)} bis {max(tage)}")
        letzte = max(tage)
        print(f"  Letzte Aktivität: {letzte} ({tage[letzte]} Ereignisse)")


def cmd_heute(daten, args):
    heute = datetime.now().strftime("%Y-%m-%d")
    evs = [e for e in daten if e.get("ts", "").startswith(heute)]
    print(f"=== {len(evs)} Ereignisse am {heute} ===\n")
    for e in evs[-200:]:
        print(kurz(e))


BEFEHLE = {
    "laeufe": cmd_laeufe,
    "lauf": cmd_lauf,
    "entscheidungen": cmd_entscheidungen,
    "trades": cmd_trades,
    "fehler": cmd_fehler,
    "suche": cmd_suche,
    "schritt": cmd_schritt,
    "wer_hat_gekauft": cmd_wer_hat_gekauft,
    "was_hat_der_trader_gemacht": cmd_was_hat_gemacht,
    "was_hat_gemacht": cmd_was_hat_gemacht,
    "diagnose": cmd_diagnose,
    "heute": cmd_heute,
}

HILFE = """
Nachvollziehbarkeit fuer den Micro-Trader.

  laeufe                      Alle Läufe mit Start, Ende, Dauer, Fehlerzahl
  lauf <id>                   Ein Lauf chronologisch, mit Tracebacks
  heute                       Alle Ereignisse von heute
  entscheidungen [ticker]     Alle Entscheidungen mit Grund
  trades                      Alle Ausführungen mit Volumen
  wer_hat_gekauft             Ticker-Häufigkeit
  fehler                      Fehler, nach Häufigkeit gruppiert
  suche <text>                Volltextsuche im ganzen Log
  schritt <name>              Alle Ereignisse eines Schritts (ki_call, ...)
  was_hat_der_trader_gemacht  Tagesbericht
  diagnose                    Gesundheit des Logs

Beispiele:
  %(prog)s was_hat_der_trader_gemacht
  %(prog)s fehler
  %(prog)s lauf a1b2c3d4
  %(prog)s schritt ki_call
"""


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "hilfe"):
        print(HILFE % {"prog": os.path.basename(sys.argv[0])})
        return 0
    befehl = sys.argv[1]
    if befehl not in BEFEHLE:
        print(f"Unbekannter Befehl: {befehl}")
        print(HILFE % {"prog": os.path.basename(sys.argv[0])})
        return 1
    daten = lade()
    BEFEHLE[befehl](daten, sys.argv[2:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
