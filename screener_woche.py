#!/usr/bin/env python3
"""Woechentliche Aktualisierung des Screener-Universums.

ANLASS (2026-09-29):
  Der Nutzer wollte "einmal die Woche diese Liste ueberpruefen, damit
  man aktuell bleibt". Ohne das bleibt die Kandidatenauswahl ein
  Schnappschuss vom 29.09.2026 - Titel werden delisted, Beta-Waender
  verschieben Titel zwischen Risikoklassen.

  Dieser Lauf macht drei Dinge:
    1. screener.py ausfuehren (Kandidaten neu abfragen)
    2. Mit dem Vorlauf vergleichen und die Unterschiede protokollieren
    3. Nichts loeschen, wenn etwas schiefgeht

GRUNDSAETZE:
  a) Ein Fehler darf nie zur leeren Liste fuehren. Im Fehlerfall
     bleibt die alte Datei stehen und wird nur als veraltet markiert.
  b) Jede Aenderung wird protokolliert, mit Zeitpunkt und Grund.
     Sonst ist nach drei Wochen nicht mehr erkennbar, warum sich die
     Zusammensetzung geaendert hat.
  c) Der Lauf schreibt NIE in Depot-Dateien. Er liefert nur Kandidaten.
  d) Beta-Cache: nur neu laden, was fehlt. Beta aendert sich selten,
     ein Volllauf kostet 6,6 Minuten statt 40 Sekunden.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
SCREENER = os.path.join(BASE, "screener.py")
KANDIDATEN = os.path.join(BASE, "screener_kandidaten.json")
# 29.09.2026: Die Depotkandidaten kommen aus dieser Datei,
# nicht aus KANDIDATEN. Sie war bis heute nur Handarbeit - der
# Wochentimer hat sie nie erneuert, und die Depots handelten
# gegen eine Liste, die niemand mehr pflegte.
ETFBETA        = os.path.join(BASE, "screener_etf_beta.json")
ETFBETA_SKRIPT = os.path.join(BASE, "etf_beta.py")
AKTBETA        = os.path.join(BASE, "screener_aktien_beta.json")
AKTBETA_SKRIPT = os.path.join(BASE, "aktien_beta.py")
VERLAUF = os.path.join(BASE, "screener_verlauf.json")
PROTOKOLL = os.path.join(BASE, "logs", "screener_verlauf.log")
PYTHON = os.path.join(BASE, "venv", "bin", "python")
STUFEN = ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90"]


def log(msg, auch_in_datei=True):
    print(msg, flush=True)
    if auch_in_datei:
        os.makedirs(os.path.dirname(PROTOKOLL), exist_ok=True)
        with open(PROTOKOLL, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), msg))


def lade_verlauf():
    if not os.path.exists(VERLAUF):
        return []
    try:
        with open(VERLAUF, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def kandidaten_index(d):
    """ticker -> Liste der Stufen, in denen er auftaucht."""
    idx = {}
    for s in STUFEN:
        for k in d.get("aktien", {}).get(s, []):
            idx.setdefault(k["ticker"], []).append("A" + s)
        for k in d.get("etf", {}).get(s, []):
            idx.setdefault(k["ticker"], []).append(("E" + s))
    return idx


def vergleiche(alt, neu):
    """Was ist hinzugekommen, was weg, was hat die Stufe gewechselt?"""
    a_idx = kandidaten_index(alt)
    n_idx = kandidaten_index(neu)

    neu_hin = sorted(set(n_idx) - set(a_idx))
    weg = sorted(set(a_idx) - set(n_idx))

    gewechselt = []
    for t in sorted(set(a_idx) & set(n_idx)):
        if sorted(a_idx[t]) != sorted(n_idx[t]):
            gewechselt.append((t, a_idx[t], n_idx[t]))

    return neu_hin, weg, gewechselt


def main():
    log("=" * 70)
    log("  Woechentliche Screener-Aktualisierung")
    log("=" * 70)

    alt_daten = None
    if os.path.exists(KANDIDATEN):
        try:
            with open(KANDIDATEN, encoding="utf-8") as f:
                alt_daten = json.load(f)
            log("  Vorlauf vorhanden: %d Kandidaten"
                % sum(len(v) for v in alt_daten.get("aktien", {}).values()))
        except Exception as e:
            log("  ⚠ Vorlauf unlesbar: %s" % str(e)[:60])
    else:
        log("  Kein Vorlauf - erster Lauf")

    alt_mtime = (os.path.getmtime(KANDIDATEN)
                 if os.path.exists(KANDIDATEN) else 0)

    # --- Screener laufen lassen ---------------------------------------
    log("  Starte screener.py ...")
    t0 = time.time()
    try:
        r = subprocess.run([PYTHON, SCREENER], cwd=BASE, timeout=900,
                           capture_output=True, text=True)
        dauer = time.time() - t0
        if r.returncode != 0:
            log("  ⚠ screener.py endete mit RC=%d" % r.returncode)
            log("    stdout: %s" % (r.stdout or "")[-300:])
            log("    stderr: %s" % (r.stderr or "")[-300:])
            log("  Alte Kandidatendatei bleibt unveraendert stehen.")
            return 1
        log("  screener.py fertig in %.0fs" % dauer)
    except subprocess.TimeoutExpired:
        log("  ✗ screener.py nach 900s abgebrochen - alte Datei bleibt")
        return 2
    except Exception as e:
        log("  ✗ screener.py konnte nicht starten: %s" % str(e)[:80])
        log("  Alte Kandidatendatei bleibt unveraendert stehen.")
        return 3

    if not os.path.exists(KANDIDATEN):
        log("  ✗ Keine Ergebnisdatei nach dem Lauf - abbruch")
        return 4

    neu_mtime = os.path.getmtime(KANDIDATEN)
    if neu_mtime <= alt_mtime:
        log("  ⚠ Ergebnisdatei ist nicht neuer - der Lauf hat nichts geschrieben")
        return 5

    # --- Aktien-Beta-Ableitung ------------------------------------------
    # Der Aktienpfad handelte bis eben gegen eine Liste, die niemand
    # erneuerte: der Wochentimer rief nur screener.py und etf_beta.py
    # auf. Die Aktienliste ist seit dem 29.09. die einzige Quelle fuer
    # engine.bewerte(), also blieb sie eingefroren.
    akt_alt_mtime = (os.path.getmtime(AKTBETA)
                     if os.path.exists(AKTBETA) else 0)
    log("")
    log("  Aktien-Beta-Ableitung (%s):" % os.path.basename(AKTBETA))
    ta = time.time()
    try:
        subprocess.run([PYTHON, AKTBETA_SKRIPT], cwd=BASE, timeout=1200,
                       capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        log("  x aktien_beta.py nach 1200s abgebrochen - alte Datei bleibt")
        return 10
    except Exception as e:
        log("  x aktien_beta.py konnte nicht starten: %s" % str(e)[:80])
        return 11

    if not os.path.exists(AKTBETA):
        log("  x Keine Aktien-Beta-Datei nach dem Lauf - alte Datei bleibt")
        return 12

    if os.path.getmtime(AKTBETA) <= akt_alt_mtime:
        log("  ! Aktien-Beta-Datei ist nicht neuer - Lauf schrieb nichts")
        return 13

    with open(AKTBETA, encoding="utf-8") as f:
        akt_daten = json.load(f)
    akt_stufen = akt_daten.get("stufen") or {}
    log("  + %d Aktien-Kandidaten in %d Stufen (%.0fs)"
        % (sum(len(v) for v in akt_stufen.values()), len(akt_stufen),
           time.time() - ta))
    leere = [s_ for s_, v in akt_stufen.items() if not v]
    if leere:
        log("  ! Leere Aktien-Stufen: %s" % ", ".join(sorted(leere)))

    # --- ETF-Beta-Ableitung ---------------------------------------------
    # Gleiche Absicherung wie der Aktienlauf oben: bei Fehler bleibt
    # die alte Datei stehen, es wird nichts halb geschrieben.
    etf_alt_mtime = (os.path.getmtime(ETFBETA)
                     if os.path.exists(ETFBETA) else 0)
    log("")
    log("  ETF-Beta-Ableitung (%s):" % os.path.basename(ETFBETA))
    t0 = time.time()
    try:
        subprocess.run([PYTHON, ETFBETA_SKRIPT], cwd=BASE, timeout=1200,
                       capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        log("  x etf_beta.py nach 1200s abgebrochen - alte Datei bleibt")
        return 6
    except Exception as e:
        log("  x etf_beta.py konnte nicht starten: %s" % str(e)[:80])
        return 7

    if not os.path.exists(ETFBETA):
        log("  x Keine ETF-Beta-Datei nach dem Lauf - abbruch")
        return 8

    if os.path.getmtime(ETFBETA) <= etf_alt_mtime:
        log("  ! ETF-Beta-Datei ist nicht neuer - Lauf schrieb nichts")
        return 9

    with open(ETFBETA, encoding="utf-8") as f:
        etf_daten = json.load(f)
    etf_stufen = etf_daten.get("stufen") or {}
    log("  + %d ETF-Kandidaten in %d Stufen (%.0fs)"
        % (sum(len(v) for v in etf_stufen.values()), len(etf_stufen),
           time.time() - t0))

    # --- Vergleich -----------------------------------------------------
    with open(KANDIDATEN, encoding="utf-8") as f:
        neu_daten = json.load(f)

    n_a = sum(len(v) for v in neu_daten.get("aktien", {}).values())
    n_e = sum(len(v) for v in neu_daten.get("etf", {}).values())

    eintrag = {
        "zeitpunkt": datetime.now(timezone.utc).isoformat(),
        "aktien": n_a,
        "etf": n_e,
        "dauer_s": round(dauer),
    }

    if alt_daten is not None:
        hin, weg, gewechselt = vergleiche(alt_daten, neu_daten)
        eintrag["neu_hinzugekommen"] = len(hin)
        eintrag["weg_gefallen"] = len(weg)
        eintrag["stufe_gewechselt"] = len(gewechselt)
        log("")
        log("  AENDERUNGEN gegenueber dem Vorlauf:")
        log("    hinzugekommen : %3d  %s" % (len(hin), ", ".join(hin[:8])))
        log("    weggefallen   : %3d  %s" % (len(weg), ", ".join(weg[:8])))
        log("    Stufe wechselt: %3d  %s"
            % (len(gewechselt),
               ", ".join("%s %s->%s" % (t, "".join(a), "".join(n))
                         for t, a, n in gewechselt[:4])))
        eintrag["beispiele"] = {
            "neu": hin[:20], "weg": weg[:20],
            "wechsel": ["%s %s->%s" % (t, "".join(a), "".join(n))
                        for t, a, n in gewechselt[:20]],
        }
    else:
        log("")
        log("  Erster Lauf - keine Vergleichswerte")

    verlauf = lade_verlauf()
    verlauf.append(eintrag)
    # Historie begrenzen: 52 Wochen
    verlauf = verlauf[-52:]
    with open(VERLAUF, "w", encoding="utf-8") as f:
        json.dump(verlauf, f, indent=1, ensure_ascii=False)

    log("")
    log("  Aktueller Stand: %d Aktien-Kandidaten, %d ETF-Kandidaten"
        % (n_a, n_e))
    log("  Verlauf: %d Eintraege in %s" % (len(verlauf), VERLAUF))
    log("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
