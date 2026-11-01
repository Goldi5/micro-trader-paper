#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Micro-Trader Eigenständiger Scheduler (ersetzt Hermes-Cron-Jobs).

Startet die Pipeline NUR wenn relevante Börsen offen sind:
  - US-Börse offen        → Pipeline mode=full (Engine + KI-Trader)
  - US zu, Xetra offen    → Pipeline mode=engine (nur Daten sammeln, kein LLM)
  - Alles zu              → nichts (kein unnötiger Start, keine API-Calls)

NACH jedem Lauf: Logik- + Daten-Integritätsprüfung (pruefe_pipeline_ergebnis):
  - KI wirklich aktiv? (ki_log vollständig, nicht nur "halten"-Fallback)
  - ki_cooldown.json blockiert? (Warnung)
  - Alle Spec-Depots haben Kurse? (keine 0-Werte)
  - Neue Trades ausgeführt?

Nutzen:
  python micro_trader_scheduler.py          # Einmal-Check (für manuelle Tests)
  python micro_trader_scheduler.py --loop   # Dauer-Loop (eigener Hintergrund-Prozess)

Konfiguration: INTERVAL_MIN (default 15). Start via VBS im Autostart.
Log: cron_pipeline.log (gemeinsam mit Pipeline).
"""
import subprocess, os, sys, time, json
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

INTERVAL_MIN = int(os.environ.get("MT_SCHEDULER_INTERVAL", 15))
KI_INTERVAL_MIN = int(os.environ.get("MT_KI_INTERVAL", 30))

# ── Pipeline-Start (kopiert aus micro-trader-cron.pyw: windowless, detached) ──
def start_pipeline(mode, extra_args=None):
    # Auf Linux: Pipeline liegt im selben Verzeichnis wie dieser Scheduler.
    # Auf Windows: Pfad aus LOCALAPPDATA (Goldi-Installation).
    if os.name == "nt":
        pipeline = os.path.join(
            os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
            "hermes", "scripts", "micro-trader-pipeline.py")
    else:
        pipeline = os.path.join(BASE, "micro-trader-pipeline.py")

    if os.name == "nt":
        uv_base = os.path.join(
            os.environ.get("APPDATA", r"C:\Users\goldi\AppData\Roaming"),
            "uv", "python", "cpython-3.11-windows-x86_64-none", "pythonw.exe")
        if os.path.exists(uv_base):
            PY = uv_base
        else:
            PY = r"C:\Program Files\Python312\pythonw.exe"
            if not os.path.exists(PY):
                PY = sys.executable
    else:
        PY = sys.executable
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    flags = 0
    if os.name == "nt":
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP
                 | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)
    else:
        flags = 0
    cmd = [PY, pipeline, "--mode", mode]
    if extra_args:
        cmd.extend(extra_args)
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, cwd=BASE, env=env,
            close_fds=True,
            start_new_session=(os.name != "nt"),
            creationflags=flags,
        )
        return True
    except Exception as e:
        log(f"Scheduler: Pipeline-Start ({mode}) FEHLER: {e}")
        return False


def log(msg):
    try:
        with open(os.path.join(BASE, "cron_pipeline.log"), "a",
                  encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _lade_json(pfad, default=None):
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def pruefe_pipeline_ergebnis():
    """Logik- + Daten-Integritätsprüfung nach einem full-Lauf.
    Gibt Warnungen ins Log, damit Störungen (Cooldown-Blockade, 0-Kurse,
    KI-Fallback nur 'halten') sofort sichtbar werden."""
    probleme = []

    # 1. KI-Cooldown blockiert?
    cd = _lade_json(os.path.join(BASE, "ki_cooldown.json"), {})
    if cd:
        kalte = [f"{n}({e.get('grund')})" for n, e in cd.items()
                 if e.get("bis", 0) > time.time()]
        if kalte:
            probleme.append(f"KI-Cooldown aktiv: {', '.join(kalte)}")

    # 2. ki_log: echte Entscheidungen oder nur 'halten'-Fallback?
    ki_log = _lade_json(os.path.join(BASE, "ki_log.json"), [])
    if isinstance(ki_log, list) and ki_log:
        from collections import Counter
        aktionen = Counter(x.get("aktion") for x in ki_log)
        non_hold = sum(v for k, v in aktionen.items()
                       if k not in ("halten", None))
        # Wenn ALLES 'halten' UND keine KI-Cooldown-Datei -> KI liefert nur Fallback
        if aktionen.get("halten", 0) > 0 and non_hold == 0 and not cd:
            probleme.append("KI liefert NUR 'halten' (kein Cooldown) -> Provider evtl. tot?")

    # 3. Spec-Depots: alle mit Kursen? (keine 0-Werte)
    import glob
    zero_kurs = 0
    total = 0
    for fn in glob.glob(os.path.join(BASE, "spec_depots", "*.json")):
        try:
            d = _lade_json(fn, {})
            total += 1
            # kurs-Info steckt in historie[-1] oder ist 0 bei frischem Depot
            hist = d.get("historie", [])
            if hist and isinstance(hist[-1], dict):
                wert = hist[-1].get("wert", 0)
                if not wert or wert <= 0:
                    zero_kurs += 1
        except Exception:
            pass
    if total and zero_kurs > total * 0.3:
        probleme.append(f"{zero_kurs}/{total} Spec-Depots ohne Kurswert")

    # 4. Letzte Pipeline-Läufe im Log prüfen (Timeout?)
    try:
        with open(os.path.join(BASE, "cron_pipeline.log"), encoding="utf-8") as f:
            lines = f.readlines()[-40:]
        timeouts = sum(1 for l in lines if "TIMEOUT" in l)
        if timeouts > 0:
            probleme.append(f"{timeouts} Timeout(s) im letzten Lauf")
    except Exception:
        pass

    if probleme:
        log("Scheduler INTEGRITÄT: ⚠️ " + " | ".join(probleme))
    else:
        log("Scheduler INTEGRITÄT: ✅ alle Prüfungen OK (KI aktiv, Daten da, keine Timeouts)")


# Merkt sich die Kalenderwoche des letzten Wochenberichts. Ohne diese
# Sperre lief der Bericht sonntags in JEDEM Loop-Durchlauf (alle
# INTERVAL_MIN Minuten, also bis zu 96x) und uebernahm jedes Mal
# pending_rules -> learned_rules erneut (52 "[Uebernahme]"-Zeilen am
# 01.11.2026). Laufzeitdatei, git-ignoriert.
WOCHENBERICHT_STAND = os.path.join(BASE, ".wochenbericht_stand.json")


def _wochenbericht_faellig(jetzt=None):
    """True, wenn heute Sonntag ist und diese Woche noch kein Bericht lief."""
    jetzt = jetzt or datetime.now()
    if jetzt.weekday() != 6:  # 6 = Sonntag
        return False
    kw = jetzt.strftime("%G-W%V")
    try:
        with open(WOCHENBERICHT_STAND, encoding="utf-8") as f:
            return json.load(f).get("kw") != kw
    except Exception:
        return True


def _wochenbericht_merken(jetzt=None):
    jetzt = jetzt or datetime.now()
    try:
        with open(WOCHENBERICHT_STAND, "w", encoding="utf-8") as f:
            json.dump({"kw": jetzt.strftime("%G-W%V"),
                       "zeit": jetzt.isoformat(timespec="seconds")}, f)
    except Exception as e:
        log(f"Scheduler: Wochenbericht-Stand nicht speicherbar: {e}")


def run_once():
    # ── Phase 1: Wöchentlicher KI-Reflexionsbericht (Sonntag, 1x pro Woche) ──
    if _wochenbericht_faellig():
        # Vor dem Lauf merken: auch ein fehlgeschlagener Bericht wird
        # nicht alle 15 Minuten wiederholt.
        _wochenbericht_merken()
        try:
            from ki_reflexion import reflexion_wochenbericht
            n, pfad = reflexion_wochenbericht()
            if pfad:
                log(f"Scheduler: Wochenbericht: {n} Regel-Kandidaten -> {pfad}")
            else:
                log("Scheduler: Wochenbericht ohne Ergebnis")
        except Exception as e:
            log(f"Scheduler: Wochenbericht fehlgeschlagen: {e}")

    # ── PAUSE-FLAG (v2.16.2): User kann Handel manuell pausieren ──
    pause_file = os.path.join(BASE, "pause_flag.json")
    if os.path.exists(pause_file):
        try:
            with open(pause_file) as f:
                pd = json.load(f)
            if pd.get("paused"):
                grund = pd.get("grund", "manuell")
                log(f"Scheduler: PAUSIERT ({grund}) -> kein Start")
                return
        except Exception:
            pass

    try:
        import boersen
        us_offen = boersen.ist_offen("US")
        xetra_offen = boersen.ist_offen("XETRA")
        status = boersen.status_text()
    except Exception as e:
        log(f"Scheduler: Börsen-Modul-Fehler ({e}) -> Engine-Lauf als Fallback")
        start_pipeline("engine")
        return

    # 04.10.2026 (Nutzerfreigabe): NYSE-Freigabe.
    #
    # Vorher startete die Pipeline bei xetra_offen, obwohl alle 274
    # Kandidaten (132 ETF + 142 Aktien) und alle 26 gehaltenen
    # Positionen US-Titel sind - boerse_fuer_ticker() faellt per
    # Default auf "US". Das Fenster Xetra-offen/NYSE-zu ist
    # 09:00-15:30 Berliner Zeit, also sieben Stunden pro Tag, in
    # denen US-Depots zu geschlossenen Kursen gehandelt wurden.
    #
    # Die Regel ist jetzt eine Tabelle Depotart -> Boerse, und die
    # Pruefung ist positiv: eine Depotart OHNE Eintrag startet
    # nicht. Wer spaeter einen Xetra-Kandidaten aufnimmt, muss die
    # Zeile selbst ergaenzen - sie faellt nicht automatisch mit.
    DEPOT_BOERSE = {"aktien": "US", "etf": "US", "speculation": "US"}

    if us_offen:
        # ── KI-WELLE (gestreckte Calls, alle 30min rotierend) ──
        # KI soll laufend bewerten/lernen, aber NICHT alle 49 Calls auf einmal
        # (zen Free-Tier drosselt nach ~20 Calls -> 429). Daher: Welle alle
        # 30min, jede Welle nur ~13 Ticker -> zen hält durch.
        from datetime import datetime as _dt
        now_min = _dt.now().hour * 60 + _dt.now().minute
        if now_min % KI_INTERVAL_MIN < INTERVAL_MIN:
            welle = (now_min // KI_INTERVAL_MIN) % 4
            log(f"Scheduler: US offen -> KI-Welle {welle} ({status})")
            start_pipeline("ki_welle", extra_args=[f"--welle", str(welle)])
            time.sleep(180)
            pruefe_pipeline_ergebnis()
            # ── PHASE 5: News-KI in Trading-Kontext (P0-Blocker) ──
            # news_evaluator bewertet neue Headlines via ki_provider.call_ki
            # und schreibt sie als typ='news' in ki_log (von ki_decisions gelesen).
            try:
                from news_evaluator import main as news_eval_main
                news_eval_main()
                log("Scheduler: News-Evaluierung gelaufen")
            except Exception as e:
                log(f"Scheduler: News-Evaluierung fehlgeschlagen: {e}")
        else:
            log(f"Scheduler: US offen -> Engine (Daten, KI-Welle in >{KI_INTERVAL_MIN}min, {status})")
            start_pipeline("engine")
    elif xetra_offen:
        # Xetra offen, NYSE zu. Die Depots handeln ausschliesslich
        # US-Titel, also gibt es hier nichts zu starten. Der Lauf
        # waere gegen geschlossene Kurse gelaufen - das Dashboard
        # zeigt die Xetra-Session weiter an, sie gibt aber keine
        # Handelsfreigabe.
        _fehlend = sorted({v for v in DEPOT_BOERSE.values()}
                          - {"US"})
        log(f"Scheduler: US zu, Xetra offen -> KEIN Start "
            f"({status}); Depots brauchen "
            f"{', '.join(sorted(set(DEPOT_BOERSE.values())))}"
            + (f", fehlend: {', '.join(_fehlend)}" if _fehlend else ""))
    else:
        log(f"Scheduler: Alle Börsen zu ({status}) -> kein Start")

    # ── PHASE 1 P1: markt_daten persistieren (Blocker Shadow->Paper) ──
    # Nur wenn US offen (Kurse verfügbar). Schreibt Kurs/RSI/SMA pro Ticker
    # in SQLite markt_daten (siehe markt_daten_fuellen.py).
    if us_offen:
        try:
            from markt_daten_fuellen import fuelle_markt_daten
            n = fuelle_markt_daten()
            if n:
                log(f"Scheduler: markt_daten persistiert ({n} Ticker)")
        except Exception as e:
            log(f"Scheduler: markt_daten_fuellen fehlgeschlagen: {e}")


def main():
    log(f"Scheduler gestartet (Interval {INTERVAL_MIN} min)")
    if "--loop" in sys.argv:
        while True:
            try:
                run_once()
            except Exception as e:
                log(f"Scheduler Exception: {e}")
            time.sleep(INTERVAL_MIN * 60)
    else:
        run_once()


if __name__ == "__main__":
    main()
