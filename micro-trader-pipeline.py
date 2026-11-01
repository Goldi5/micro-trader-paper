"""Micro-Trading Pipeline – läuft als abgetrennter Prozess vom Cron-Runner.
Führt die Pipeline aus: News → Spec-Watch → Spec-Trader → KI-Lernen → ETF → Batch.
Loggt nach ~/projects/micro-trader/cron_pipeline.log

Priorität 0 (Zwei-Ebenen-Cron): --mode steuert welche Schritte laufen:
  --mode engine   nur lokale Logik OHNE LLM-Calls (Kurse, Bremsen, Indizes)
  --mode ki       nur LLM-Läufe (Trader + Lernen + Skill-Sync)
  --mode full     alles (Default, für manuellen Aufruf)
"""
import subprocess, os, sys, json, time, logging, argparse
import urllib.request  # 01.11.2026: fehlte, _gateway_send_file nutzte urllib
from datetime import datetime

BASE = os.path.expanduser("~/projects/micro-trader") if os.name == "nt" else "/opt/micro-trader"
sys.path.insert(0, BASE)
LOG = os.path.join(BASE, "cron_pipeline.log")


def _gateway_send_file(chat_id, message, media_path, gateway_url="http://localhost:3000"):
    """Sendet eine Datei via Hermes-Gateway HTTP API.
    WICHTIG: hermes send CLI parst MEDIA: bei WhatsApp NICHT (nur Text).
    Gateway /send mit media-Feld funktioniert (verifiziert 06.08.2026).
    Fallback: Wenn Gateway nicht erreichbar, nur Text via hermes send."""
    payload = {"chatId": chat_id, "message": message, "media": media_path}
    try:
        req = urllib.request.Request(
            f"{gateway_url}/send",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        # Fallback: nur Text (Datei geht dann nicht, aber Info kommt an)
        try:
            subprocess.run(
                ["hermes", "send", "-t", "whatsapp:Christian Glaser (dm)",
                 f"{message} (Datei: {media_path})"],
                capture_output=True, timeout=30)
        except Exception:
            pass
        raise RuntimeError(f"Gateway-Send fehlgeschlagen: {e}")


# Hermes-venv Python nutzen (hat yfinance + openai + pydantic_core + alle Deps)
# FENSTERLOS: der venv/Scripts/pythonw.exe ist nur ein uv-SHIM (poppt Fenster).
# Echtes windowless pythonw liegt im uv-base (gleiche home, lädt alle venv-Module):
if os.name == "nt":
    uv_base = os.path.join(
        os.environ.get("APPDATA", r"C:\Users\goldi\AppData\Roaming"),
        "uv", "python", "cpython-3.11-windows-x86_64-none", "pythonw.exe")
    if os.path.exists(uv_base):
        PY = uv_base
    else:
        venv_pyw = os.path.join(
            os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
            "hermes", "hermes-agent", "venv", "Scripts", "pythonw.exe")
        if os.path.exists(venv_pyw):
            PY = venv_pyw
        else:
            PY = r"C:\Program Files\Python312\pythonw.exe"
            if not os.path.exists(PY):
                PY = r"C:\Program Files\Python312\python.exe"
                if not os.path.exists(PY):
                    PY = sys.executable  # Fallback
else:
    # Linux: Nutze das venv-python des Micro-Traders
    venv_py = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "venv", "bin", "python")
    if os.path.exists(venv_py):
        PY = venv_py
    else:
        PY = sys.executable

logging.basicConfig(
    filename=LOG, level=logging.INFO,
    format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")

def ensure_whatsapp_bridge():
    """Startet den Hermes WhatsApp-Bridge (Node.js, Port 3000) falls nicht läuft.
    Der Gateway managed den Bridge auf Windows nicht selbst -> wir starten ihn.
    """
    import socket
    port = 3000
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return  # Bridge läuft bereits
    except Exception:
        pass
    bridge = os.path.join(
        os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
        "hermes", "hermes-agent", "scripts", "whatsapp-bridge", "bridge.js")
    if os.path.exists(bridge):
        try:
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            subprocess.Popen(["node", bridge], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, startupinfo=startupinfo)
            log.info("WhatsApp-Bridge gestartet (Port 3000)")
        except Exception as e:
            log.warning("WhatsApp-Bridge Start fehlgeschlagen: %s", e)

def run(cmd, timeout=300):
    """Führt Befehl aus, gibt stdout zurück."""
    env = dict(os.environ)
    # PYTHONPATH auf venv site-packages setzen (nicht leeren!)
    if os.name == "nt":
        venv_sp = os.path.join(
            os.environ.get("LOCALAPPDATA", r"C:\Users\goldi\AppData\Local"),
            "hermes", "hermes-agent", "venv", "Lib", "site-packages")
    else:
        venv_sp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "venv", "lib", "python3.11", "site-packages")
        if not os.path.exists(venv_sp):
            # Fallback: site-packages ermitteln
            import site
            ves = site.getsitepackages()
            venv_sp = ves[0] if ves else ""
    if venv_sp and os.path.isdir(venv_sp):
        env["PYTHONPATH"] = venv_sp
    t0 = time.time()
    # Windows: KEIN Konsolenfenster für Subprozesse (SW_HIDE ist zuverlässiger als CREATE_NO_WINDOW bei Pipes)
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    # Befehl in Argumente zerlegen; immer über PY (Python-Interpreter) ausführen
    args = cmd.split()
    if args and args[0].endswith(".py") and "--quiet" not in args:
        args.insert(0, PY)
        args.append("--quiet")
    elif args and args[0].endswith(".py"):
        args.insert(0, PY)
    else:
        args = [PY] + args  # Fallback: trotzdem über Python
    try:
        r = subprocess.run(
            args,
            capture_output=True, text=True, timeout=timeout,
            cwd=BASE, env=env, startupinfo=startupinfo
        )
        out = r.stdout.strip()
        status = "OK" if r.returncode == 0 else f"FEHLER(rc={r.returncode})"
        log.info(f"{cmd:22s} {status}  {time.time()-t0:.0f}s")
        if r.returncode != 0 and r.stderr.strip():
            log.info(f"  stderr: {r.stderr.strip()[-300:]}")
        return out
    except subprocess.TimeoutExpired:
        log.info(f"{cmd:22s} TIMEOUT({timeout}s)  {time.time()-t0:.0f}s")
        return ""

try:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["engine", "ki", "full"], default="full")
    args, _ = parser.parse_known_args()
    mode = args.mode
    log.info(f"=== Pipeline gestartet (mode={mode}) ===\n")

    # SINGLETON-GUARD: verhindert parallele Pipeline-Instanzen
    # (Multi-Instance waere Doppel-Orders/Racing bei DB-Writes)
    import psutil as _ps
    _lock = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pipeline.lock")
    _my_pid = os.getpid()
    if os.path.exists(_lock):
        try:
            with open(_lock) as _f:
                _old = int(_f.read().strip())
            if _ps.pid_exists(_old):
                # andere Instanz lebt noch -> diese hier beenden
                log.warning(f"Pipeline laeuft schon (PID {_old}). Beende doppelte Instanz.")
                sys.exit(0)
            else:
                os.remove(_lock)
        except (ValueError, OSError):
            os.remove(_lock)
    with open(_lock, "w") as _f:
        _f.write(str(_my_pid))
    # Lock cleanup bei Exit
    import atexit
    def _rm_lock():
        try:
            if os.path.exists(_lock) and int(open(_lock).read().strip()) == _my_pid:
                os.remove(_lock)
        except Exception:
            pass
    atexit.register(_rm_lock)

    # WhatsApp-Bridge sicherstellen (für späteren Bericht)
    ensure_whatsapp_bridge()

    # Watchdog-Check (falls Loop-Prozess nicht läuft)
    try:
        import whatsapp_watchdog
        whatsapp_watchdog.check()
    except Exception as e:
        log.warning("WhatsApp-Watchdog Check fehlgeschlagen: %s", e)

    # ─── Börsen-Check: spart API-Calls bei geschlossenen Märkten ───
    try:
        import boersen
        us_offen = boersen.ist_offen("US")
        xetra_offen = boersen.ist_offen("XETRA")
        status = boersen.status_text()
        log.info(status)
        try:
            from system_log import log_eintrag
            log_eintrag("cron", f"Börsen-Check: {status}", "info")
        except Exception:
            pass
    except Exception as e:
        log.warning("Börsen-Modul nicht verfügbar (%s) -> alles läuft normal", e)
        us_offen = True
        xetra_offen = True

    if mode in ("engine", "full"):
        # ── ENGINE-EBENE: nur lokale Logik, KEIN LLM-Call ──
        run("news_monitor.py", timeout=120)
        run("spec_watch.py", timeout=120)
        # P1 (v2.52.0): markt_daten-Persistenz -> Shadow→Paper-Übergang
        run("markt_daten_fuellen.py", timeout=180)
        # Bremsen/Indizes werden in Tradern geprüft; hier nur Daten sammeln
        if mode == "engine":
            log.info("=== Engine-Lauf fertig (kein LLM) ===\n")
            try:
                from system_log import log_eintrag
                log_eintrag("cron", "Engine-Lauf (ohne LLM) durchgelaufen", "ok")
            except Exception:
                pass

    # 01.11.2026: batch_trader lief im Modus "full" zweimal (KI-Ebene und
    # Block unten). Der zweite Lauf Sekunden spaeter fuehrte die frisch
    # gecachten KI-Aktionen erneut aus (siehe batch_trader.py, KI-Cache).
    batch_gelaufen = False
    if mode in ("ki", "full"):
        # ── KI-EBENE: nur wenn Börse offen (US) ──
        if us_offen:
            run("spec_trader.py", timeout=600)
            run("ki_news.py", timeout=300)
            run("ki_learning.py", timeout=120)
            run("ki_reflexion.py", timeout=120)
            run("skill_sync.py", timeout=120)
            # ETF-Trader läuft immer (US & DE)
            run("etf_trader.py", timeout=120)
            run("batch_trader.py", timeout=200)
            batch_gelaufen = True
            log.info("=== KI-Lauf fertig ===\n")
            try:
                from system_log import log_eintrag
                log_eintrag("cron", "KI-Lauf durchgelaufen", "ok")
            except Exception:
                pass
        else:
            log.info("US-Markt geschlossen -> KI-Ebene übersprungen")
    elif mode == "ki_welle":
        # ── KI-WELLE: gestreckte Calls (Rate-Limit-Schonung) ──
        # Nur Spec-Trader mit --welle N (Slice der 49 Ticker), damit zen
        # (Free-Tier) nicht nach ~20 Calls mit 429 drosselt.
        import sys
        welle = int(sys.argv[sys.argv.index("--welle") + 1]) if "--welle" in sys.argv else 0
        if us_offen:
            # 30.09.2026: Bis hier lief NUR der Spec-Trader. Die
            # anderen beiden Depotarten - Aktien (batch_trader) und
            # ETFs (etf_trader) - waren an der Pipeline verdrahtet,
            # aber kein Scheduler-Aufruf erreichte sie: run_once()
            # startet "engine" oder "ki_welle", nie "ki" oder
            # "full". Folge: 20 von 30 Depoten wurden nie von
            # selbst gehandelt, alle Kaeufe kamen aus manuellen
            # Laeufen.
            #
            # Je Welle laeuft jetzt ein Trader, rotierend nach
            # Wellennummer. Das haelt den Verbrauch je Takt
            # niedrig und laesst alle drei Depotarten im Umlauf.
            trader_dreh = ("batch_trader.py", "etf_trader.py",
                           f"spec_trader.py --welle {welle}")
            aktuell = trader_dreh[welle % len(trader_dreh)]
            run(aktuell, timeout=300)
            log.info(f"=== KI-Welle {welle} fertig "
                      f"({aktuell}) ===\n")
            try:
                from system_log import log_eintrag
                log_eintrag("cron", f"KI-Welle {welle} durchgelaufen", "ok")
            except Exception:
                pass
        else:
            log.info("US-Markt geschlossen -> KI-Welle übersprungen")

    if mode == "full" and not batch_gelaufen:
        # Batch-Trader nur wenn EINE Börse offen (US ODER XETRA) -> spart
        # KI-Tokens/API-Calls bei geschlossenem Markt (sonst sinnloser Timeout)
        if us_offen or xetra_offen:
            # Timeout 200s: call_ki braucht bis zu 5x18s Rotation, bricht bei
            # Rate-Limit aber sofort ab (FAIL_FAST) -> meist viel schneller fertig.
            run("batch_trader.py", timeout=200)
        else:
            log.info("Alle Börsen geschlossen -> Batch-Trader übersprungen (spart Tokens)")

    # ─── Daily PDF Report (§17, §29.D): nach 22:00 MEZ, NUR EINMAL/Tag ──
    try:
        from datetime import datetime
        # Bewusste Berliner Zeit, nicht datetime.now(): sonst
        # scheitert der Vergleich mit boersen.schlusszeit() an
        # naiv-vs-aware und der Bericht faellt auf die Stunde zurueck.
        import boersen as _bz
        now = _bz.jetzt_lokal()
        # Marker-Datei verhindert doppelten Versand (Scheduler läuft alle 15min)
        # Der Handelstag, nicht das Berliner Tagesdatum.
        #
        # Vorher stand hier now.strftime('%Y-%m-%d'). Um 00:15 Berliner
        # Zeit ist der 09.10. — der Marker hiess .sent_2026-10-09, und
        # die Sperre beantwortete damit "heute schon versendet?", nicht
        # "diesen Handelstag schon berichtet?". Der Handelstag war da
        # schon abgeschlossen und schon versendet, also kam die zweite
        # Mail. Mit dem New-York-Handelstag als Marker-Datum fallen
        # beide Fragen zusammen: ein Handelstag, ein Versand.
        try:
            from zoneinfo import ZoneInfo
            import boersen as _bz2
            _close_hs = _bz2.schlusszeit("US", now.astimezone(ZoneInfo("America/New_York")))
            _handelstag = _close_hs.strftime("%Y-%m-%d") if _close_hs else now.strftime("%Y-%m-%d")
        except Exception:
            _handelstag = now.strftime("%Y-%m-%d")
        sent_marker = os.path.join(BASE, f".daily_report_sent_{_handelstag}")
        # Zweiter Marker: der Versand hat es einmal versucht und ist
        # gescheitert. Ohne ihn versucht der naechste 15-Minuten-
        # Takt es erneut - achtmal pro Abend, acht Logzeilen,
        # und der Nutzer kann nicht unterscheiden, ob es einmal
        # oder dauernd fehlschlaegt.
        fail_marker = os.path.join(BASE, f".daily_report_sendfail_{now.strftime('%Y-%m-%d')}")
        # ══ Handelstag statt Uhrzeit ══
        # Vorher stand hier `now.hour >= 22`. Auf einem UTC-
        # Container ist 01:30 UTC hour=1, nie >= 22 - der Block
        # war einen Monat lang unerreichbar und der Report
        # entstand trotzdem aus einem anderen Weg. Nach der
        # Umstellung auf Europe/Berlin stimmt die Stunde -
        # aber nur, solange die Container-Zone stimmt.
        #
        # Die Bedingung lautet jetzt: der NYSE-Schluss des
        # heutigen Handelstags liegt in der Vergangenheit. Das
        # ist unabhaengig von der Zone, in der der Scheduler
        # laeuft, weil boersen.py die NYSE-Zone selbst kennt.
        # Der Berichtszeitraum entscheidet, nicht die Uhrzeit.
        #
        # Der Fehler: `now >= schlusszeit("US", now)` prueft gegen den
        # Schluss des heutigen Kalendertags, aber boersen.schlusszeit()
        # rechnet den Zeitpunkt vorher nach New York (boersen.py Z.159).
        # Aus 00:15 Berliner Zeit wurde damit der 08.10. in New York, und
        # dessen Schluss liegt in der Vergangenheit — der Vergleich war
        # immer wahr. Jeder Lauf nach 22:00, auch um Mitternacht, meldete
        # faellig=true und versandte einen zweiten Bericht.
        #
        # Richtig: die NYSE ist erst beendet, wenn in New York der
        # Schluesszeitpunkt des heutigen New-York-Tages erreicht ist.
        # 22:00 Berlin = 16:00 New York → beendet, Versand.
        # 00:15 Berlin = 18:15 New York des Vortags → der heutige
        # New-York-Tag ist der 08.10., Schluss 16:00 noch nicht
        # erreicht → kein Versand.
        try:
            from zoneinfo import ZoneInfo
            import boersen
            _now_ny = now.astimezone(ZoneInfo("America/New_York"))
            _close = boersen.schlusszeit("US", _now_ny)
            if _close is None:
                _faellig = False
                _naechste = "kein Handelstag"
            elif _now_ny.date() > _close.date():
                _faellig = False
                _naechste = "Handelstag laeuft"
            elif _now_ny >= _close:
                _faellig = True
                _naechste = f"Schluss {_close.strftime('%H:%M')} New York erreicht"
            else:
                _faellig = False
                _naechste = "Handelstag laeuft"
        except Exception as _e:
            # boersen.py nicht importierbar: auf die Stunde
            # zurueckfallen, aber SICHERN, dass es heute noch
            # passiert - sonst faellt der Report still aus.
            _faellig = now.hour >= 22
            _naechste = "22:00 (Fallback)"
            log.warning("NYSE-Schluss nicht prüfbar: %s", _e)
        # Report fehlt UND der Versand wurde heute nicht schon
        # einmal vergeblich versucht.
        if _faellig and not os.path.exists(sent_marker) \
                and not os.path.exists(fail_marker):
            log.info("=== Daily PDF Report (22:00 MEZ) ===")
            run("tagesverlauf.py", timeout=60)   # Snapshot zuerst (für 7-Tage-Graph)
            run("report_pdf.py", timeout=120)
            run("audit_export.py", timeout=120)
            # PDF per E-Mail senden (SMTP 1&1/IONOS).
            # Der fruehere WhatsApp-Gateway-Pfad ist tot (Port 3000
            # antwortet nicht mehr): der Bericht wurde zwar erzeugt,
            # aber nie zugestellt - die .daily_report_sendfail_*-
            # Marker im Projektordner sind der Beleg dafuer.
            # mail_send.py liest die Zugangsdaten aus der .env
            # (gitignored, 0600) und meldet Fehler zurueck, statt
            # sie zu verschlucken.
            try:
                import os, glob
                from system_log import log_eintrag
                muster = os.path.join(BASE, "reports", f"daily_report_{now.strftime('%Y-%m-%d')}_*.pdf")
                treffer = sorted(glob.glob(muster), reverse=True)
                pdf_path = treffer[0] if treffer else os.path.join(
                    BASE, "reports", f"micro_trader_{now.strftime('%Y-%m-%d')}.pdf")
                if os.path.exists(pdf_path):
                    import mail_send
                    _ok, _meldung = mail_send.sende_bericht(pdf_path)
                    if not _ok:
                        raise RuntimeError(_meldung)
                    log.info("Tagesbericht per E-Mail: %s", _meldung)
                    log_eintrag("cron", f"Daily PDF + Audit erstellt + per E-Mail gesendet ({os.path.basename(pdf_path)})", "ok")
                    # Marker setzen: heute bereits gesendet
                    with open(sent_marker, "w") as f:
                        f.write(now.isoformat())
                else:
                    log.warning("PDF nicht gefunden: %s", pdf_path)
            except Exception as e:
                log.warning("PDF-E-Mail-Versand fehlgeschlagen: %s", e)
                # Einmal markieren: der naechste Takt versucht es
                # nicht wieder. Der Report selbst ist trotzdem
                # erzeugt - er liegt in reports/.
                try:
                    with open(fail_marker, "w") as f:
                        f.write("%s\n%s\n" % (now.isoformat(), e))
                except Exception:
                    pass
                log.warning("Tagesbericht liegt in reports/, Versand "
                            "ausgesetzt bis morgen")
    except Exception as e:
        log.warning("Daily PDF Report fehlgeschlagen: %s", e)

    # ── Analyse-DB Sync (SQLite) ──
    try:
        sys.path.insert(0, BASE)
        from db import MTDB
        db = MTDB()
        db.sync()
        db.close()
        log.info("DB-Sync OK")
    except Exception as e:
        log.warning("DB-Sync fehlgeschlagen: %s", e)

except Exception as e:
    log.exception("Pipeline FEHLER: %s", e)
    sys.exit(1)

log.info("=== Pipeline ENDE ===\n")