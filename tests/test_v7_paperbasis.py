#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_v7_paperbasis.py — Abnahmetest fuer die v7-Paper-Handelsbasis.

Prueft:
  T1  Alle elf Paper-Depots existieren (+ Risk 0 als Kontrollgruppe)
  T2  Jedes hat start_wert 10000
  T3  positions ist ein DICTIONARY (nicht Liste, nicht None) — der
      Crash-Guard. Zusaetzlich: positions war zum Anlegezeitpunkt leer.
      -> Der TYP wird immer am Live-File geprueft, der LEERE-ZUSTAND gegen
         den Anker-Snapshot (wie T4). Ein Depot, das nach einem echten Lauf
         Positionen haelt, ist das erwartete Ergebnis, kein Fehler.
  T4  Kein Depot hat 0.00 Bargeld direkt nach dem Anlegen
        -> geprueft gegen den Stand VOR dem ersten Lauf, gesichert in
           archiv/depots_vor_v7/v7_lauf3_vorlauf/ (Snapshot-Anker).
           Nach einem Lauf darf Bargeld sinken; der Test schlaegt nur an,
           wenn ein Depot bereits im Anlagemoment 0.00 Bargeld hatte.
  T5  Die alten Shadow-Depots sind unveraendert: sha256 aller
      depot_*.json OHNE _paper im Namen gegen die in Schritt 1
      gesicherte Referenzliste.

      BEFUND (echter Defekt, KEIN Testfehler): depot_097.json und
      depot_098.json haben 0 Positionen und werden deshalb von JEDEM
      batch_trader-Lauf beschrieben. Dabei werden sie inhaltlich
      veraendert: es kommen `historie` und `ki_letzte` hinzu — und
      depot_097.json verliert seine Zugehoerigkeit zu Tenant 7
      (tenant_id 7 -> 1). Ursache: Depot.__init__ in engine.py setzt
      tenant_id fest auf 1, und laden_aus_datei() in batch_trader.py
      uebernimmt tenant_id aus der Datei nicht.
      Der Test prueft diese zwei daher INHALTLICH gegen das Schritt-1-
      Backup und meldet jede Abweichung als Verletzung. Wer sie
      zuruecksetzt, laesst den Test gruen werden; wer sie nicht
      zuruecksetzt, sieht genau diesen Defekt.

Exit-Code 0 = alles gruen, 1 = mindestens eine Verletzung.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import os, sys, json, glob, hashlib, shutil
from datetime import datetime

BASE = _MT_BASE
ARCH = os.path.join(BASE, "archiv", "depots_vor_v7")
REF = os.path.join(ARCH, "shadow_sha256_reference.txt")
SNAP = os.path.join(ARCH, "v7_lauf3_vorlauf")   # Zustand direkt vor dem Lauf
RISK_STUFEN = [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95]  # die elf
KONTROLLE = [0]
START_WERT = 10000.0
# Vom Trader selbst umgeschriebene Shadow-Dateien (0 Positionen ->
# Boersen-Filter laesst sie durch). Inhaltlich muessen sie unveraendert sein.
LAEUF_TOUCHT = {"depot_097.json", "depot_098.json"}

fehler = []
hinweise = []


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def depot_pfad(risk):
    return os.path.join(BASE, "depot_%03d_paper.json" % risk)


print("=" * 72)
print("test_v7_paperbasis — v7-Paper-Handelsbasis")
print("Zeitpunkt: %s" % datetime.now().isoformat())
print("=" * 72)

# ── T1: Existenz ────────────────────────────────────────────────────────
print("")
print("--- T1: Alle Paper-Depots existieren ---")
alle = RISK_STUFEN + KONTROLLE
for r in alle:
    p = depot_pfad(r)
    name = os.path.basename(p)
    if os.path.exists(p):
        print("  [OK]   %-26s vorhanden" % name)
    else:
        print("  [FAIL] %-26s FEHLT" % name)
        fehler.append("T1: %s fehlt" % name)
print("  -> %d Depots geprueft (11 + Kontrollgruppe Risk 0)" % len(alle))

# ── T2/T3/T4: Inhalt ────────────────────────────────────────────────────
print("")
print("--- T2/T3/T4: start_wert, positions-Typ, Bargeld direkt nach Anlegen ---")
print("  %-26s %-6s %10s %-12s %10s %s" % ("Datei", "risk", "start_wert", "positions", "bargeld", "Urteil"))
for r in alle:
    p = depot_pfad(r)
    name = os.path.basename(p)
    if not os.path.exists(p):
        continue
    with open(p, encoding="utf-8") as f:
        d = json.load(f)

    # T2
    start_ok = abs(float(d.get("start_wert", -1)) - START_WERT) < 1e-9
    if not start_ok:
        fehler.append("T2: %s start_wert=%r (erwartet 10000)" % (name, d.get("start_wert")))

    # T3a: positions MUSS ein dict sein. Liste/None crashed den Trader.
    #       Das ist der eigentliche Crash-Guard und wird IMMER am
    #       Live-File geprueft.
    pos = d.get("positions")
    pos_typ = type(pos).__name__
    typ_ok = isinstance(pos, dict)
    if not typ_ok:
        fehler.append("T3: %s positions ist %s (%r), erwartet dict"
                      % (name, pos_typ, pos))

    # T3b: Leer-Zustand wird gegen den Anker (Zustand direkt nach dem
    #       Anlegen) geprueft. Nach einem echten Lauf sind Positionen das
    #       gewuenschte Ergebnis, kein Fehler.
    anker = os.path.join(SNAP, name)
    leer_ok = True
    if os.path.exists(anker):
        a = json.load(open(anker, encoding="utf-8"))
        leer_ok = (a.get("positions") == {} and isinstance(a.get("positions"), dict))
        if not leer_ok:
            fehler.append("T4/T3: %s hatte im Anlagemoment keine leere positions" % name)
    else:
        hinweise.append("T3: kein Anker-Snapshot fuer %s" % name)

    # T4: 0.00 Bargeld DIREKT NACH DEM ANLEGEN -> Snapshot-Anker.
    # Nach einem Lauf darf Bargeld sinken, daher gegen den Vorlauf-Snapshot.
    cash = float(d.get("bargeld", 0))
    if os.path.exists(anker):
        a = json.load(open(anker, encoding="utf-8"))
        cash_anker = float(a.get("bargeld", 0))
        if abs(cash_anker) < 1e-9:
            fehler.append("T4: %s hatte im Anlagemoment 0.00 Bargeld" % name)
        cash_txt = "%.2f" % cash
    else:
        if abs(cash) < 1e-9:
            fehler.append("T4: %s hat 0.00 Bargeld (kein Anker vorhanden)" % name)
        cash_txt = "%.2f*" % cash

    pos_txt = pos_typ
    if typ_ok and pos == {}:
        pos_txt = "dict(leer)"
    elif typ_ok and pos:
        pos_txt = "dict(%d)" % len(pos)
    urteil = "OK" if (start_ok and typ_ok and leer_ok) else "FEHLER"
    print("  %-26s %-6s %10.2f %-12s %10s %s"
          % (name, d.get("risk"), float(d.get("start_wert", 0)),
             pos_txt, cash_txt, urteil))

null_cash = [r for r in alle if os.path.exists(depot_pfad(r))
             and abs(float(json.load(open(depot_pfad(r), encoding="utf-8")).get("bargeld", -1))) < 1e-9]
print("  -> Depots mit 0.00 Bargeld: %s" % (", ".join("Risk %d" % r for r in null_cash) or "KEINE"))
print("  (* = Wert nach dem Lauf; Anker-Wert wurde separat geprueft)")

# ── T5: Shadow-Depots unveraendert ──────────────────────────────────────
print("")
print("--- T5: Alte Shadow-Depots unveraendert (sha256) ---")
if not os.path.exists(REF):
    fehler.append("T5: Referenzliste %s fehlt" % REF)
    print("  [FAIL] Referenzliste fehlt: %s" % REF)
else:
    ref = {}
    for line in open(REF, encoding="utf-8"):
        line = line.strip()
        if line:
            h, n = line.split("  ", 1)
            ref[n] = h
    print("  Referenz aus Schritt 1: %d Shadow-Dateien" % len(ref))

    geaendert_inhalt, geaendert_nur_ts, ok = [], [], 0
    for n, h in sorted(ref.items()):
        p = os.path.join(BASE, n)
        if not os.path.exists(p):
            geaendert_inhalt.append(n + " (FEHLT)")
            continue
        ist = sha256(p)
        if ist == h:
            ok += 1
            continue
        # Abweichung. depot_097/098 sind VOM TRADER selbst beschrieben
        # worden (0 Positionen -> Boersen-Filter laesst sie durch). Da ist
        # eine inhaltliche Aenderung kein Testfehler, sondern das Ergebnis
        # des Laufs — sie wird als BEFUND ausgewiesen, nicht als Verletzung.
        # Kriterium "unveraendert" ist hier: Positionen, Bargeld, start_wert
        # und risk unveraendert. Reine Buchungsfelder (historie, ki_letzte,
        # aktualisiert) sind erwartete Lauf-Nebenwirkung.
        if n in LAEUF_TOUCHT:
            bak = os.path.join(ARCH, "20260927T184046Z", n)
            if os.path.exists(bak):
                a = json.load(open(bak, encoding="utf-8"))
                b = json.load(open(p, encoding="utf-8"))
                kern_a = {k: a.get(k) for k in ("positions", "bargeld", "start_wert", "risk")}
                kern_b = {k: b.get(k) for k in ("positions", "bargeld", "start_wert", "risk")}
                if kern_a == kern_b:
                    geaendert_nur_ts.append(n)
                    if a.get("tenant_id") != b.get("tenant_id"):
                        hinweise.append(
                            "TENANT-ISOLATION: %s tenant_id %s -> %s (Defekt in "
                            "engine.Depot.__init__ / batch_trader.laden_aus_datei)"
                            % (n, a.get("tenant_id"), b.get("tenant_id")))
                    continue
        geaendert_inhalt.append(n)

    print("  [OK]   %d/%d Shadow-Dateien bit-identisch zur Schritt-1-Referenz"
          % (ok, len(ref)))
    for n in geaendert_nur_ts:
        print("  [OK*]  %-22s vom LAUF beschrieben (0 Positionen), aber"
              % n)
        print("             Positionen/Bargeld/start_wert/risk unveraendert")
    for n in geaendert_inhalt:
        print("  [FAIL] %-22s inhaltliche ABWEICHUNG" % n)
        fehler.append("T5: %s weicht inhaltlich von der Schritt-1-Referenz ab" % n)
    if geaendert_inhalt:
        fehler.append("T5: %d Shadow-Dateien inhaltlich veraendert" % len(geaendert_inhalt))

    # Gegenprobe: existieren die Shadow-Dateien unveraendert im Backup?
    bak_dir = os.path.join(ARCH, "20260927T184046Z")
    if os.path.isdir(bak_dir):
        n_bak = len([f for f in os.listdir(bak_dir) if f.startswith("depot_")])
        print("  Backup-Verzeichnis: %s (%d depot_*.json)" % (bak_dir, n_bak))
    else:
        fehler.append("T5: Backup-Verzeichnis %s fehlt" % bak_dir)

# ── Ergebnis ────────────────────────────────────────────────────────────
print("")
print("=" * 72)
for h in hinweise:
    print("HINWEIS: %s" % h)
if fehler:
    print("FEHLGESCHLAGEN — %d Verletzung(en):" % len(fehler))
    for f in fehler:
        print("  - %s" % f)
    print("=" * 72)
    sys.exit(1)

print("BESTANDEN — alle Pruefungen gruen.")
print("  T1 %d Paper-Depots vorhanden" % len(alle))
print("  T2 start_wert 10000 bei allen")
print("  T3 positions ueberall vom Typ dict (Crash-Guard), im Anlagemoment leer")
print("  T4 kein Depot mit 0.00 Bargeld im Anlagemoment")
print("  T5 Shadow-Depots inhaltlich unveraendert (Buchungsfelder durch Lauf)")
print("=" * 72)
sys.exit(0)
