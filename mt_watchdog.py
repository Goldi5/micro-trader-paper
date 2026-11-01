#!/usr/bin/env python3
"""
mt_watchdog.py — Ausfall-Watchdog fuer den Micro-Trader.

WARUM DIESES SKRIPT EXISTIERT:
  Das System war 4 Wochen still: seit 2026-09-08 keine KI-Entscheidung,
  seit 2026-08-28 kein Trade, und niemand wurde informiert. Ursache war
  nicht ein Fehler, sondern das Fehlen jeder Alarmlogik.

KRITERIUM "DER TRADER ARBEITET" (bewusst NICHT "DB wird geschrieben"):
  Die DB wird taeglich beschrieben — auch dann, wenn der Trader tot ist
  (depot_snapshot waechst weiter, markt_daten ebenfalls). Ein
  DB-Schreibzugriff ist deshalb als Lebenszeichen wertlos.

  Stattdessen:
    LETZTE KI-ENTSCHEIDUNG (ki_decisions.zeit) juenger als 48h
    ODER
    LETZTER TRADE (trades.zeit) juenger als 48h
  waehrend der Marktzeit. Beides weg -> ALARM.

  Zusaetzlich hart (immer, auch ausserhalb der Marktzeit):
    - Scheduler laeuft nicht
    - weniger als 2 DB-Schreibvorgaenge in 24h
    - Disk ueber 85 %

MARKTZEIT: Mo-Fr 15:00-22:00 UTC (deckt die US-Boerse 15:30-22:00 MEZ ab,
identisch zum Zeitfenster der bestehenden mt-gate/mt-monitor-Timer).

KANAL: ntfy.sh (Push, ueber HTTPS ausgehend erreichbar) + Tailscale
Taildrop als Zweitkanal. Beide sind verifiziert.
Postfix ist als Kanal AUSGESCHLOSSEN: relayhost leer,
inet_interfaces=loopback-only, kein ausgehender SMTP (Port 25/587
blockiert) — es gibt dort nachweislich keinen Weg nach draussen.

ENTPREPUNG (Alert-Dedupe): ein Alarm wird nicht bei jedem Timerlauf
erneut gesendet, sondern nur alle ALERT_COOLDOWN_MIN Minuten.

Aufruf:
  python3 mt_watchdog.py              # normal
  python3 mt_watchdog.py --force-alarm  # Alarm unabhaengig vom Zustand (Test)
  python3 mt_watchdog.py --status       # nur Zustand, kein Alarm
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))  # war fest "/opt/micro-trader" (01.11.2026)
DB = os.path.join(BASE, "micro_trader.db")
STATE = os.path.join(BASE, ".watchdog_state.json")
LOG = os.path.join(BASE, "watchdog.log")

# Konfiguration
MAX_AGE_H = 48                      # gefordertes Kriterium
MARKET_START_H = 15                 # Mo-Fr
MARKET_END_H = 22
MIN_DB_WRITES_24H = 2               # darunter: etwas stimmt nicht
DISK_WARN_PCT = 85
ALERT_COOLDOWN_MIN = 60
KI_MIN_AUFRUFE = 5                  # 01.11.2026: erst ab so vielen Aufrufen bewerten
KI_AUSFALL_WARN_PCT = 50            # Alarm, wenn >= 50 % der KI-Aufrufe scheitern

# Alarmkanal
NTFY_TOPIC_FILE = os.path.join(BASE, ".watchdog_ntfy_topic")
NTFY_URL = "https://ntfy.sh/"
# Taildrop-Ziel (Tailscale-Geraetename mit ":"), z. B. "meinpc:".
# Aus MT_TS_TARGET oder der git-ignorierten Datei .watchdog_ts_target;
# leer = Taildrop aus. (01.11.2026: Geraetename stand fest im Code.)
def _ts_target():
    v = os.environ.get("MT_TS_TARGET", "").strip()
    if not v:
        try:
            with open(os.path.join(BASE, ".watchdog_ts_target"), encoding="utf-8") as f:
                v = f.read().strip()
        except OSError:
            v = ""
    return v


TS_TARGET = _ts_target()


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.replace(tzinfo=None).isoformat()


def logline(msg):
    ts = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    line = "[%s] %s" % (ts, msg)
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    try:
        with open(STATE, "w") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


def db_query(sql, args=()):
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=30)
    try:
        return con.execute(sql, args).fetchone()
    finally:
        con.close()


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_market_time(dt=None):
    dt = dt or now_utc()
    return dt.weekday() < 5 and MARKET_START_H <= dt.hour < MARKET_END_H


def collect():
    """Alle Pruefwerte einsammeln. Nichts schreibt ausser den Alarm."""
    ref = now_utc()
    d = {}

    ki = db_query("select max(zeit) from ki_decisions")
    tr = db_query("select max(zeit) from trades")
    dep = db_query("select max(zeit) from depot_snapshot")

    d["last_ki"] = ki[0] if ki else None
    d["last_trade"] = tr[0] if tr else None
    d["last_depot_snapshot"] = dep[0] if dep else None

    t_ki = parse_ts(d["last_ki"])
    t_tr = parse_ts(d["last_trade"])

    d["age_ki_h"] = (ref - t_ki).total_seconds() / 3600.0 if t_ki else None
    d["age_trade_h"] = (ref - t_tr).total_seconds() / 3600.0 if t_tr else None

    # Kernkriterium
    d["ki_fresh"] = d["age_ki_h"] is not None and d["age_ki_h"] < MAX_AGE_H
    d["trade_fresh"] = d["age_trade_h"] is not None and d["age_trade_h"] < MAX_AGE_H
    d["working"] = d["ki_fresh"] or d["trade_fresh"]

    # Harte Checks
    try:
        r = subprocess.run(["systemctl", "is-active", "mt-scheduler"],
                           capture_output=True, text=True, timeout=15)
        d["scheduler_active"] = (r.stdout.strip() == "active")
    except Exception:
        d["scheduler_active"] = None

    d["depot_rows_24h"] = db_query(
        "select count(*) from depot_snapshot where zeit > ?",
        (iso(ref - timedelta(hours=24)),))[0]

    st = os.statvfs("/")
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    d["disk_pct"] = round(100.0 * (total - free) / total, 1)

    d["market_time"] = is_market_time(ref)
    d["checked_at"] = ref.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 01.11.2026: KI-Ausfallquote der letzten 2 h (ki_aufrufe.jsonl) und
    # gesperrte Depots (Drawdown-Sperre) - beides bisher ohne Alarm.
    try:
        import performance
        d["ki_2h"] = performance.ki_kennzahlen(2)
    except Exception:
        d["ki_2h"] = None
    d["gesperrte_depots"] = gesperrte_depots()
    return d


def gesperrte_depots():
    """Namen aller Depot-Dateien mit gesperrt=true (Aktien, ETF, Spec)."""
    import glob
    muster = ["depot_*_paper.json", "etf_*_paper.json",
              os.path.join("spec_depots_paper", "*.json"),
              os.path.join("spec_depots", "*.json")]
    namen = []
    for m in muster:
        for f in glob.glob(os.path.join(BASE, m)):
            try:
                with open(f, encoding="utf-8") as fh:
                    if (json.load(fh) or {}).get("gesperrt"):
                        namen.append(os.path.relpath(f, BASE))
            except Exception:
                continue
    return sorted(namen)


def decide(d):
    """Liefert Liste von Alarmen (leer = alles ok)."""
    alarms = []

    if d["market_time"]:
        if not d["working"]:
            alarms.append({
                "sev": "CRITICAL",
                "title": "Trader arbeitet nicht (Marktzeit)",
                "msg": ("Waehrend der Marktzeit keine KI-Entscheidung seit %.1fh "
                        "und kein Trade seit %.1fh (Grenze %dh). "
                        "Letzte KI: %s | Letzter Trade: %s"
                        % (d["age_ki_h"] if d["age_ki_h"] is not None else -1,
                           d["age_trade_h"] if d["age_trade_h"] is not None else -1,
                           MAX_AGE_H, d["last_ki"], d["last_trade"])),
            })
    else:
        # Ausserhalb der Marktzeit kein Alarm, aber sichtbar protokollieren
        # wie alt die Signale sind.
        if d["age_ki_h"] is not None and d["age_ki_h"] > 24 * 7:
            alarms.append({
                "sev": "HIGH",
                "title": "Keine KI-Entscheidung seit ueber einer Woche",
                "msg": "Letzte KI-Entscheidung vor %.1f Tagen: %s"
                       % (d["age_ki_h"] / 24.0, d["last_ki"]),
            })

    if d["scheduler_active"] is False:
        alarms.append({
            "sev": "CRITICAL",
            "title": "mt-scheduler laeuft nicht",
            "msg": "systemctl is-active mt-scheduler -> nicht active",
        })

    if d["depot_rows_24h"] < MIN_DB_WRITES_24H:
        alarms.append({
            "sev": "HIGH",
            "title": "Kaum DB-Schreibvorgaenge in 24h",
            "msg": "Nur %d depot_snapshot-Zeilen in 24h (Schwelle %d). "
                   "Letzter Snapshot: %s"
                   % (d["depot_rows_24h"], MIN_DB_WRITES_24H,
                      d["last_depot_snapshot"]),
        })

    ki = d.get("ki_2h") or {}
    if d["market_time"] and ki.get("aufrufe", 0) >= KI_MIN_AUFRUFE \
            and ki.get("ausfall_quote_pct", 0) >= KI_AUSFALL_WARN_PCT:
        alarms.append({
            "sev": "HIGH",
            "title": "KI faellt aus",
            "msg": "%.0f %% von %d KI-Aufrufen in 2 h ohne Antwort (Schwelle %d %%). "
                   "Fehler: %s" % (ki["ausfall_quote_pct"], ki["aufrufe"],
                                  KI_AUSFALL_WARN_PCT,
                                  ", ".join("%s %d" % kv for kv in list(ki.get("fehler", {}).items())[:3])),
        })

    bekannt = set(load_state().get("gesperrte_depots") or [])
    neu = [n for n in d.get("gesperrte_depots") or [] if n not in bekannt]
    if neu:
        alarms.append({
            "sev": "HIGH",
            "title": "Depot gesperrt (Drawdown)",
            "msg": "Neu gesperrt: %s. Insgesamt gesperrt: %d."
                   % (", ".join(neu[:8]) + (" ..." if len(neu) > 8 else ""),
                      len(d.get("gesperrte_depots") or [])),
        })

    if d["disk_pct"] >= DISK_WARN_PCT:
        alarms.append({
            "sev": "CRITICAL",
            "title": "Disk kritisch voll",
            "msg": "Root-Dateisystem zu %.1f %% belegt (Schwelle %d %%)"
                   % (d["disk_pct"], DISK_WARN_PCT),
        })

    return alarms


def ntfy_topic():
    if os.path.exists(NTFY_TOPIC_FILE):
        return open(NTFY_TOPIC_FILE).read().strip()
    return None


def send_ntfy(alarm, d, topic):
    body = (
        "MICRO-TRADER ALARM\n"
        "%s\n\n%s\n\n"
        "Letzte KI-Entscheidung: %s (vor %.1fh)\n"
        "Letzter Trade:          %s (vor %.1fh)\n"
        "Marktzeit: %s | Scheduler: %s | DB-Zeilen 24h: %d | Disk: %.1f %%\n"
        "Geprueft: %s"
        % (alarm["title"], alarm["msg"],
           d["last_ki"], d["age_ki_h"] if d["age_ki_h"] is not None else -1,
           d["last_trade"], d["age_trade_h"] if d["age_trade_h"] is not None else -1,
           "JA" if d["market_time"] else "NEIN",
           "aktiv" if d["scheduler_active"] else "INAKTIV",
           d["depot_rows_24h"], d["disk_pct"], d["checked_at"]))

    url = NTFY_URL + topic
    prio = "urgent" if alarm["sev"] == "CRITICAL" else "high"
    req = urllib.request.Request(
        url, data=body.encode("utf-8"), method="POST",
        headers={"Title": "Micro-Trader: " + alarm["title"],
                 "Priority": prio,
                 "Tags": "warning" if alarm["sev"] == "CRITICAL" else "rotating_light"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = r.read().decode("utf-8", "replace")
            return True, "http=%s id=%s" % (
                r.status,
                json.loads(resp).get("id", "?") if resp.strip().startswith("{") else "?")
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


def send_taildrop(alarm, d):
    if not TS_TARGET:
        return False, "kein Ziel konfiguriert (.watchdog_ts_target)"
    body = (
        "MICRO-TRADER ALARM %s\n%s\n\n"
        "letzte KI: %s (%.1fh) | letzter Trade: %s (%.1fh)\n"
        "Marktzeit=%s Scheduler=%s Disk=%.1f%% geprueft=%s"
        % (alarm["title"], alarm["msg"],
           d["last_ki"], d["age_ki_h"] if d["age_ki_h"] is not None else -1,
           d["last_trade"], d["age_trade_h"] if d["age_trade_h"] is not None else -1,
           d["market_time"], d["scheduler_active"], d["disk_pct"], d["checked_at"]))
    fn = "/tmp/mt_alarm_%s.txt" % now_utc().strftime("%Y%m%dT%H%M%SZ")
    with open(fn, "w") as f:
        f.write(body)
    try:
        r = subprocess.run(["tailscale", "file", "cp", fn, TS_TARGET],
                           capture_output=True, text=True, timeout=30)
        return (r.returncode == 0), (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


def alert(alarms, d, force=False):
    topic = ntfy_topic()
    st = load_state()
    last = st.get("last_alert_ts")
    if last and not force:
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            since_min = (now_utc() - last_dt).total_seconds() / 60.0
            if since_min < ALERT_COOLDOWN_MIN:
                logline("Cooldown aktiv: letzter Alarm vor %.0fmin (<%dmin) — "
                        "versandt %d Alarm(e) NICHT erneut"
                        % (since_min, ALERT_COOLDOWN_MIN, len(alarms)))
                return False
        except ValueError:
            pass
    elif last and force:
        logline("Cooldown durch --force-alarm uebergangen (Test)")

    ok_any = False
    for a in alarms:
        logline("ALARM [%s] %s — %s" % (a["sev"], a["title"], a["msg"]))
        if topic:
            ok, detail = send_ntfy(a, d, topic)
            logline("  Kanal ntfy.sh/%s: %s — %s" % (topic, "OK" if ok else "FEHLER", detail))
            ok_any = ok_any or ok
        else:
            logline("  Kanal ntfy: kein Topic konfiguriert (%s fehlt)" % NTFY_TOPIC_FILE)
        ok2, detail2 = send_taildrop(a, d)
        logline("  Kanal Tailscale Taildrop -> %s: %s — %s"
                % (TS_TARGET, "OK" if ok2 else "FEHLER", detail2))
        ok_any = ok_any or ok2

    st["last_alert_ts"] = now_utc().replace(tzinfo=None).isoformat()
    st["last_alarm_count"] = len(alarms)
    st["last_alarm_titles"] = [a["title"] for a in alarms]
    save_state(st)
    return ok_any


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-alarm", action="store_true",
                    help="Alarm unabhaengig vom Zustand senden (Test)")
    ap.add_argument("--status", action="store_true", help="nur Zustand, kein Alarm")
    ap.add_argument("--reset-cooldown", action="store_true")
    args = ap.parse_args()

    if args.reset_cooldown:
        save_state({})
        logline("Cooldown zurueckgesetzt")

    d = collect()
    logline("Zustand: KI=%s (%.1fh) Trade=%s (%.1fh) Marktzeit=%s "
            "Scheduler=%s Disk=%.1f%%"
            % (d["last_ki"], d["age_ki_h"] if d["age_ki_h"] is not None else -1,
               d["last_trade"], d["age_trade_h"] if d["age_trade_h"] is not None else -1,
               d["market_time"], d["scheduler_active"], d["disk_pct"]))
    logline("Kernkriterium arbeitet=%s (ki_fresh=%s trade_fresh=%s, Grenze %dh)"
            % (d["working"], d["ki_fresh"], d["trade_fresh"], MAX_AGE_H))

    if args.status:
        print(json.dumps(d, indent=2))
        return 0

    if args.force_alarm:
        alarms = [{
            "sev": "CRITICAL",
            "title": "TESTALARM (erzwungen)",
            "msg": "Testlauf --force-alarm, ignoriert den echten Zustand.",
        }]
        logline(">>> TESTALARM wird gesendet (Cooldown uebergangen)")
        ok = alert(alarms, d, force=True)
        return 0 if ok else 2

    alarms = decide(d)
    if not alarms:
        _merke_gesperrte(d)
        logline("OK — kein Alarm noetig")
        return 0
    if alert(alarms, d):
        # Erst nach erfolgreichem Versand merken - sonst ginge ein im
        # Cooldown unterdrueckter Sperr-Alarm still verloren.
        _merke_gesperrte(d)
    return 1


def _merke_gesperrte(d):
    st = load_state()
    st["gesperrte_depots"] = d.get("gesperrte_depots") or []
    save_state(st)


if __name__ == "__main__":
    sys.exit(main())
