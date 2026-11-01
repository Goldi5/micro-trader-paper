"""Zentrales Logsystem fuer den Micro-Trader.

AUSGANGSLAGE (gemessen am 27.09.2026):
  - 0 von 85 Python-Dateien importieren `logging`.
  - 104 Dateien schreiben per `print()`.
  - cron_pipeline.log hatte 23.081 Zeilen OHNE Datumsangabe, nur HH:MM:SS.
    Die Zeitachse war damit nicht rekonstruierbar.
  - Es gibt keine Korrelation: man konnte nicht herausfinden, welche
    Zeile zu welchem Trade, welcher KI-Entscheidung oder welchem
    Kursabruf gehoert.

DESHALB DIESES MODUL. Es liefert:

  1. STRUKTURIERTE JSONL-Logs. Jede Zeile ist ein vollstaendiges
     JSON-Objekt mit Zeitstempel, Level, Modul, Prozess-PID und
     optionaler Korrelations-ID. Maschinell auswertbar, im
     Notfall trotzdem lesbar.

  2. KORRELATIONS-IDs. Ein Lauf bekommt eine run_id. Alles, was
     innerhalb dieses Laufs passiert - Kursabruf, KI-Call,
     Risikopruefung, Trade, Lernschritt - traegt dieselbe ID.
     Damit laesst sich exakt rekonstruieren, was wann passiert ist.

  3. EINE ZENTRALE ROTATION. Groesse- und zeitbasiert, mit
     Kompression. Kein Modul pflegt eigene Log-Dateien.

  4. TRACING fuer Fehler. Kontextvariablen koennen an einen
     Aufruf gehaengt werden, ohne sie ueber zehn Funktionssignaturen
     zu schleppen.

  5. MENSCHENLESBAR parallel. Wer tailt, sieht sofort Zeile 12.
     Wer analysiert, nimmt JSONL.

NUTZUNG - die drei ueblichen Faelle:

    from mtlog import log, run, schritt

    # Ein ganzer Lauf unter einer Korrelations-ID
    with run("pipeline", risk=50) as r:
        log.info("Kurse laden", anzahl=len(kurse))
        with schritt("ki_call", ticker="AAPL"):
            ...

    # Oder ohne Kontextmanager
    log.warn("Depot gesperrt", depot="risk_050", grund="drawdown")

    # Fehler mit vollem Trace
    try:
        ...
    except Exception as e:
        log.error("Kursabruf fehlgeschlagen", exc_info=True, ticker=t)

GRUNDSAETZE:
  a) Niemals Secrets loggen. Es gibt eine Filterfunktion, die
     Schluesselwoerter gegen den Text prueft.
  b) Log-Ausgabe darf niemals einen Trade stoppen. Jeder Fehler
     im Logger wird geschluckt und einmal gemeldet.
  c) Threads und Prozesse duerfen parallel schreiben. Jeder Prozess
     schreibt in seine eigene Datei, jeder Thread ueber einen Lock.
"""

import contextlib
import contextvars
import json
import logging
import logging.handlers
import os
import re
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────
# Konfiguration
# ─────────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE, "logs")

# Groesse und Zeit, damit nie eine Datei unbegrenzt waechst.
MAX_BYTES = 20 * 1024 * 1024      # 20 MB pro Datei
BACKUP_COUNT = 14                 # 14 Generationen = ca. 280 MB

LEVEL = os.getenv("MT_LOG_LEVEL", "INFO").upper()

# Aktueller Lauf. Wird von run() gesetzt und an alle Log-Ausgaben
# angehaengt. Genau das fehlte vorher: die Korrelation.
_lauf_id = contextvars.ContextVar("mt_lauf_id", default=None)
_schritt = contextvars.ContextVar("mt_schritt", default=None)

# Mutex fuer das erstmalige Aufbauen (wichtig bei many-process-fork)
_setup_lock = threading.Lock()
_fertig = False

# Wohlgeformtheitszaehler: zeigt, ob der Logger selbst je ausgefallen ist.
# ACHTUNG: KEIN threading.local() - diagnose() liest aus dem
# Hauptthread und wuerde die Fehler der Arbeitsthreads nie sehen.
# Genau das war ein Befund aus dem ersten Testlauf: der Zaehler stand
# auf 1, obwohl die Arbeitsthreads sauber liefen.
_logger_fehler_zaehler = [0]
_logger_fehler_lock = threading.Lock()

# Schluesselwoerter, deren Nennung im Log vermieden werden muss
_VERBOTEN = (
    "api_key", "apikey", "secret", "password", "passwort", "token",
    "authorization", "bearer", "private_key", "credential", "geheim",
)


def _maskiere(text):
    """Entfernt Secret-aehnliche Muster aus einem Text.

    Absichtlich konservativ: es filtert Schluessel-NAMEN und
    Authorization-Header. Es ist kein Ersatz fuer richtige
    Secret-Verwaltung, aber ein Sicherheitsnetz.

    WICHTIG: der Wert wird bis zum NAECHSTEN Trennzeichen entfernt,
    nicht nur bis zum ersten Leerzeichen. Sonst bleibt bei
    "Authorization: Bearer abcdef123" das eigentliche Token stehen,
    weil "Bearer" und der Token durch ein Leerzeichen getrennt sind.
    """
    if not text:
        return text
    t = str(text)
    # Bearer-Token zuerst: der Sonderfall, der beim ersten Test
    # durchgerutscht ist.
    t = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}", "Bearer ***", t)
    # Dann generisch: name=value und name: value.
    #
    # WICHTIG: \b matcht nicht vor "OPENROUTER_API_KEY", weil "_" ein
    # Wortzeichen ist. Ohne (?<![A-Za-z0-9_]) rutschten die echten
    # Schluesselnamen des Projekts durch - genau die, die man schuetzen
    # muss. Der negative Blickblick verhindert das.
    #
    # Der Wert (\S+) wird mitentfernt, sonst bliebe bei
    # "password=hunter2 ok" das Geheimnis sichtbar.
    muster = (r"(?i)(?<![A-Za-z0-9_])"
              r"([a-z0-9_]*(?:api[_-]?key|apikey|secret|password|passwort|"
              r"token|authorization|private[_-]?key|credential|geheimnis?))"
              r"\s*[:=]\s*(\S+)")
    t = re.sub(muster, lambda m: m.group(1) + "=***", t)
    return t


# ─────────────────────────────────────────────────────────────────────
# Datumsformat: ISO mit Millisekunden und Zeitzone.
# Ohne das ist die Zeitachse nicht rekonstruierbar - genau der
# Fehler, der cron_pipeline.log unbrauchbar machte.
# ─────────────────────────────────────────────────────────────────────
class _IsoFormatter(logging.Formatter):
    """Formatiert als JSON. Der Text-Schlüssel bleibt fuer tail -f."""

    def format(self, record):
        eintrag = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "modul": record.name,
            "pid": record.process,
            "msg": _maskiere(record.getMessage()),
        }
        lauf = getattr(record, "lauf_id", None)
        if lauf:
            eintrag["run"] = lauf
        schritt_name = getattr(record, "schritt", None)
        if schritt_name:
            eintrag["schritt"] = schritt_name
        # Zusatzfelder wie risk=50, ticker="AAPL"
        for k, v in record.__dict__.items():
            if k in _RESERVIERT:
                continue
            try:
                json.dumps(v)
                eintrag[k] = _maskiere(v) if isinstance(v, str) else v
            except (TypeError, ValueError):
                eintrag[k] = repr(v)[:200]
        if record.exc_info and record.exc_info[0] is not None:
            # WICHTIG: exc_info kann (None, None, None) sein, wenn der
            # Aufrufer exc_info=True ohne aktiven Exception-Kontext
            # setzt. format_exception() wirft dann. Genau das war der
            # Logger-Fehler, den der Test gefunden hat.
            eintrag["traceback"] = _maskiere(
                "".join(traceback.format_exception(*record.exc_info)))[-2500:]
        quelle = getattr(record, "src", None)
        if quelle:
            eintrag["src"] = quelle
        return json.dumps(eintrag, ensure_ascii=False)


_RESERVIERT = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "lauf_id", "schritt",
    "message", "asctime",
}

# Felder, die Python NICHT auf einem LogRecord duldet. Wird ein
# solches Feld als Keyword uebergeben, benennt mtlog es um statt den
# Eintrag zu verlieren. Ohne das kostet log.info("x", name="y") den
# kompletten Log-Eintrag durch eine KeyError.
_FELD_KOLLISIONEN = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
})


class _TextFormatter(logging.Formatter):
    """Lesbare Zeile fuer tail -f. Gleiche Information, flacher."""

    def format(self, record):
        ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        lauf = getattr(record, "lauf_id", None)
        teil = [ts, f"{record.levelname:<7}", f"[{record.name}]"]
        if lauf:
            teil.append(f"<{lauf[:8]}>")
        schritt_name = getattr(record, "schritt", None)
        if schritt_name:
            teil.append(f"({schritt_name})")
        extra = []
        for k, v in record.__dict__.items():
            if k in _RESERVIERT:
                continue
            extra.append(f"{k}={v}")
        zeile = " ".join(teil) + " " + _maskiere(record.getMessage())
        if extra:
            zeile += "  " + " ".join(extra[:8])
        if record.exc_info and record.exc_info[0] is not None:
            zeile += "\n" + _maskiere(
                "".join(traceback.format_exception(*record.exc_info)))
        return zeile


class _LaufZeilenFormatter(logging.Formatter):
    """Für die lauf-spezifische Datei: nur eine Zeile pro Log."""

    def format(self, record):
        return _maskiere(record.getMessage())


# ─────────────────────────────────────────────────────────────────────
# Aufbau
# ─────────────────────────────────────────────────────────────────────
def setup():
    """Baut das Logsystem auf. Idempotent."""
    global _fertig
    with _setup_lock:
        if _fertig:
            return
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            wurzel = logging.getLogger("mt")
            wurzel.setLevel(getattr(logging, LEVEL, logging.INFO))
            wurzel.propagate = False
            # Eigene Handler entfernen, falls setup zweimal laeuft
            for h in list(wurzel.handlers):
                wurzel.removeHandler(h)
                with contextlib.suppress(Exception):
                    h.close()

            fmt = _IsoFormatter()

            # 1) Hauptlog: alle Ereignisse, strukturiert
            haupt = logging.handlers.RotatingFileHandler(
                os.path.join(LOG_DIR, "events.jsonl"),
                maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                encoding="utf-8", delay=True)
            haupt.setFormatter(fmt)
            wurzel.addHandler(haupt)

            # 2) Menschenlesbar
            lesbar = logging.handlers.RotatingFileHandler(
                os.path.join(LOG_DIR, "trader.log"),
                maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                encoding="utf-8", delay=True)
            lesbar.setFormatter(_TextFormatter())
            wurzel.addHandler(lesbar)

            # 3) Nur Fehler, fuer schnelle Sichtbarkeit
            fehler = logging.handlers.RotatingFileHandler(
                os.path.join(LOG_DIR, "fehler.log"),
                maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                encoding="utf-8", delay=True)
            fehler.setLevel(logging.ERROR)
            fehler.setFormatter(_TextFormatter())
            wurzel.addHandler(fehler)

            # 4) Konsole, damit systemctl journal etwas brauchbares hat
            konsole = logging.StreamHandler(sys.stdout)
            konsole.setFormatter(_TextFormatter())
            wurzel.addHandler(konsole)

            # 5) Ein einziger Filter gegen rekursive Log-Fehler
            wurzel.addFilter(_KeinRekurs())

            _fertig = True
        except Exception as e:
            # Logger darf den Prozess nie killen
            sys.stderr.write(f"mtlog: setup fehlgeschlagen: {e}\n")
            logging.basicConfig(level=logging.INFO)
            _fertig = True


class _KeinRekurs(logging.Filter):
    """Verhindert, dass ein Log-Fehler sich selbst protokolliert."""

    def filter(self, record):
        with _logger_fehler_lock:
            if _logger_fehler_zaehler[0] > 3:
                return False
        return True


def _sicher(handler_fn, *args, **kwargs):
    """Fuehrt eine Log-Aktion aus, ohne dass sie werfen kann."""
    try:
        return handler_fn(*args, **kwargs)
    except Exception:
        try:
            with _logger_fehler_lock:
                _logger_fehler_zaehler[0] += 1
        except Exception:
            pass
        return None


# ─────────────────────────────────────────────────────────────────────
# Öffentliche API
# ─────────────────────────────────────────────────────────────────────
class _Log:
    """Der Logger. Leitet Feldnamen als Keyword-Argumente weiter."""

    def __init__(self, name="mt"):
        self._name = name

    def _l(self, level, msg, exc_info=False, **kwargs):
        setup()
        # Python verbietet das Ueberschreiben reservierter LogRecord-
        # Felder mit KeyError. Ein Aufrufer, der log.info("x", name="y")
        # schreibt, wuerde damit den ganzen Log-Eintrag verlieren.
        # Stattdessen wird das Feld umbenannt.
        extra = dict(lauf_id=_lauf_id.get(), schritt=_schritt.get(), **kwargs)
        for feld in _FELD_KOLLISIONEN:
            if feld in extra:
                wert = extra.pop(feld)
                extra[f"feld_{feld}"] = wert
        _sicher(logging.getLogger(self._name).log, level, msg,
                exc_info=exc_info, extra=extra)

    def debug(self, msg, **kw):
        self._l(logging.DEBUG, msg, **kw)

    def info(self, msg, **kw):
        self._l(logging.INFO, msg, **kw)

    def warn(self, msg, **kw):
        self._l(logging.WARNING, msg, **kw)

    warning = warn

    def error(self, msg, exc_info=False, **kw):
        self._l(logging.ERROR, msg, exc_info=exc_info, **kw)

    def critical(self, msg, exc_info=False, **kw):
        self._l(logging.CRITICAL, msg, exc_info=exc_info, **kw)


log = _Log()


# ─────────────────────────────────────────────────────────────────────
# Lauf-Kontext: die Korrelations-ID
# ─────────────────────────────────────────────────────────────────────
@contextlib.contextmanager
def run(art, **kwargs):
    """Ein kompletter Lauf unter einer Korrelations-ID.

    Alles innerhalb dieses Blocks - Kurse, KI, Risiko, Trade - traegt
    dieselbe run_id. Danach steht in events.jsonl:

        {"run":"a1b2c3d4","schritt":"ki_call","ticker":"AAPL",...}
        {"run":"a1b2c3d4","schritt":"trade","qty":12,...}

    und laesst sich als ein zusammenhaengender Vorgang lesen.
    """
    rid = uuid.uuid4().hex[:12]
    token = _lauf_id.set(rid)
    alt = _schritt.set(None)
    start = time.time()
    try:
        _sicher(logging.getLogger("mt").log, logging.INFO,
                f"Lauf START: {art}", extra=dict(
                    lauf_id=rid, schritt="start", event=art, **kwargs))
        yield rid
    except Exception as e:
        _sicher(logging.getLogger("mt").log, logging.ERROR,
                f"Lauf FEHLGESCHLAGEN: {art}: {e}", exc_info=True,
                extra=dict(lauf_id=rid, schritt="abbruch", event=art,
                           dauer_s=round(time.time() - start, 2)))
        raise
    else:
        _sicher(logging.getLogger("mt").log, logging.INFO,
                f"Lauf ENDE: {art}", extra=dict(
                    lauf_id=rid, schritt="ende", event=art,
                    dauer_s=round(time.time() - start, 2), **kwargs))
    finally:
        _lauf_id.reset(token)
        _schritt.reset(alt)


@contextlib.contextmanager
def schritt(name, **kwargs):
    """Ein Teilschritt innerhalb eines Laufs.

    Damit laesst sich im Log sehen, welcher Teil des Laufs wie lange
    gedauert hat und ob er geklappt hat.
    """
    alt = _schritt.set(name)
    rid = _lauf_id.get()
    start = time.time()
    ok = True
    try:
        _sicher(logging.getLogger("mt").log, logging.DEBUG,
                f"Schritt START: {name}", extra=dict(
                    lauf_id=rid, schritt=name, phase="start", **kwargs))
        yield
    except Exception as e:
        ok = False
        _sicher(logging.getLogger("mt").log, logging.ERROR,
                f"Schritt FEHLGESCHLAGEN: {name}: {e}", exc_info=True,
                extra=dict(lauf_id=rid, schritt=name, phase="fehler",
                           dauer_s=round(time.time() - start, 2), **kwargs))
        raise
    else:
        _sicher(logging.getLogger("mt").log, logging.DEBUG,
                f"Schritt ENDE: {name}", extra=dict(
                    lauf_id=rid, schritt=name, phase="ende",
                    ok=ok, dauer_s=round(time.time() - start, 2), **kwargs))
    finally:
        _schritt.reset(alt)


# ─────────────────────────────────────────────────────────────────────
# Entscheidungsprotokoll
# ─────────────────────────────────────────────────────────────────────
def entscheidung(**kwargs):
    """Protokolliert eine Entscheidung mit Begruendung.

    Getrennt vom normalen Log, weil das die interessanteste Zeile
    des ganzen Systems ist: warum wurde gekauft, verkauft oder
    nicht gekauft.
    """
    setup()
    _sicher(logging.getLogger("mt.decision").log, logging.INFO,
            "entscheidung", extra=dict(
                lauf_id=_lauf_id.get(), schritt=_schritt.get(),
                typ="entscheidung", **kwargs))


def trade(**kwargs):
    """Protokolliert eine Ausfuehrung."""
    setup()
    _sicher(logging.getLogger("mt.trade").log, logging.INFO,
            "trade", extra=dict(
                lauf_id=_lauf_id.get(), schritt=_schritt.get(),
                typ="trade", **kwargs))


def metrik(name, wert, **kwargs):
    """Protokolliert eine Kennzahl, etwa Kosten oder Latenz.

    ACHTUNG: das Feld heisst bewusst "metrik" und NICHT "name".
    Python verbietet das Ueberschreiben reservierter LogRecord-Felder
    (KeyError: "Attempt to overwrite 'name' in LogRecord") - das war
    ein echter Befund aus dem Testlauf. Wer nach "name" filtert,
    nutzt "metrik".
    """
    setup()
    _sicher(logging.getLogger("mt.metrik").log, logging.INFO,
            name, extra=dict(
                lauf_id=_lauf_id.get(), schritt=_schritt.get(),
                typ="metrik", metrik=name, wert=wert, **kwargs))


# ─────────────────────────────────────────────────────────────────────
# Schlussdiagnose
# ─────────────────────────────────────────────────────────────────────
def diagnose(stunden=24):
    """Prueft das Logsystem auf eigene Fehler.

    Ein Logger, der still ausfaellt, ist schlimmer als keiner.
    """
    setup()
    bericht = {"logger_fehler": 0, "zeilen": {}, "grosse": {}, "probleme": []}

    if not os.path.isdir(LOG_DIR):
        bericht["probleme"].append("Log-Verzeichnis fehlt")
        return bericht

    for datei in ("events.jsonl", "trader.log", "fehler.log"):
        p = os.path.join(LOG_DIR, datei)
        if not os.path.exists(p):
            bericht["zeilen"][datei] = 0
            bericht["grosse"][datei] = 0
            continue
        g = os.path.getsize(p)
        bericht["grosse"][datei] = g
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                n = sum(1 for _ in f)
            bericht["zeilen"][datei] = n
        except Exception as e:
            bericht["probleme"].append(f"{datei} nicht lesbar: {e}")
            n = 0

    # Ungueltige JSON-Zeilen zaehlen: das waere ein echter Defekt
    pfad = os.path.join(LOG_DIR, "events.jsonl")
    if os.path.exists(pfad):
        kaputt = 0
        with open(pfad, encoding="utf-8", errors="replace") as f:
            for z in f:
                z = z.strip()
                if not z:
                    continue
                try:
                    json.loads(z)
                except json.JSONDecodeError:
                    kaputt += 1
        bericht["kaputte_json_zeilen"] = kaputt
        if kaputt:
            bericht["probleme"].append(
                f"{kaputt} Zeilen in events.jsonl sind kein gueltiges JSON")

    with _logger_fehler_lock:
        bericht["logger_fehler"] = _logger_fehler_zaehler[0]
    if bericht["logger_fehler"]:
        bericht["probleme"].append(
            f"{bericht['logger_fehler']} eigene Logger-Fehler")

    return bericht


if __name__ == "__main__":
    # Selbsttest
    setup()
    with run("selbsttest", risk=50) as rid:
        log.info("Normaler Eintrag", anzahl=5)
        log.debug("Debug-Eintrag", ticker="AAPL")
        log.warn("Warnung", depot="risk_050", grund="drawdown")
        with schritt("ki_call", ticker="AAPL"):
            log.info("KI antwortet", konfidenz=60)
        try:
            raise ValueError("Testfehler")
        except ValueError:
            log.error("Kursabruf fehlgeschlagen", exc_info=True, ticker="MSFT")
        entscheidung(aktion="kaufen", ticker="AAPL", grund="RSI 28, Cash da",
                     konfidenz=72)
        trade(aktion="kaufen", ticker="AAPL", menge=12, preis=341.07)
        metrik("latenz_ms", 2340)

    import pprint
    print("=" * 70)
    print(" SELBSTTEST-DIAGNOSE")
    pprint.pprint(diagnose())

    print()
    print("=" * 70)
    print(" LETZTE ZEILEN aus events.jsonl")
    with open(os.path.join(LOG_DIR, "events.jsonl"), encoding="utf-8") as f:
        zeilen = f.readlines()[-6:]
    for z in zeilen:
        print(" ", z.rstrip()[:190])
