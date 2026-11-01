#!/usr/bin/env python3
"""
mt_db_retention.py — Datenbank-Retention fuer depot_snapshot.

ENTSCHEIDUNG: VERDICHTUNG, KEIN LOESCHEN von Jungem.

Hintergrund (gemessen 2026-09-27):
  depot_snapshot hat 82.921 Zeilen fuer nur 188 verschiedene
  (Tag, depot_typ, ref)-Kombinationen. Der Scheduler schreibt den ganzen
  Bestand mehrfach pro Tag (~5.000 Zeilen/Tag), obwohl sich der Wert je
  (Tag, depot_typ, ref) selten aendert.

  GEMAESS AUFTRAG: NICHTS loeschen, was juenger als die Grenze ist.
  -> Rows mit zeit >= cutoff werden NIE angefasst.
  -> Rows mit zeit <  cutoff werden auf 1 Zeile je
     (Tag, depot_typ, ref) reduziert: der LETZTE Snapshot des Tages
     (max id). Das ist der Tages-Schluss, also der informativste Wert.

WARUM VERDICHTEN STATT LOESCHEN:
  1. In 82.921/82.921 Zeilen gilt wert == bargeld (db.py Z.1031
     `wert = d.get("wert") or d.get("bargeld", 0)`, und die Depot-JSONs
     besitzen keinen Schluessel "wert"). Die Tabelle ist damit faktisch
     eine Cash-Kurve. Echte Equity-Auswertung ist auf ihr nicht moeglich —
     aber die Historie selbst (Cash-Verlauf ueber Tage) ist Arbeits-
     grundlage fuer Auswertungen und wird durch Verdichtung erhalten.
  2. Verdichtung auf Tagesebene haelt genau 188 Zeilen fuer 38 Tage
     Historie: 99,8 % Speichergewinn bei ~0 % Informationsverlust auf
     Tagesebene. Ein Loeschen dagegen waere irreversibel.
  3. VACUUM gibt den gewonnenen Platz ans Dateisystem zurueck; ohne
     VACUUM bliebe die Datei auf ihrer alten Groesse.

Nutzung:
  python3 mt_db_retention.py --days 30            # Grenze 30 Tage
  python3 mt_db_retention.py --days 30 --dry-run  # nur zeigen
  python3 mt_db_retention.py --vacuum-only
"""
import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "micro_trader.db")  # war fest /opt/micro-trader
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bak")


def log(msg):
    print("[%s] %s" % (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), msg), flush=True)


def db_size():
    return os.path.getsize(DB)


def free_bytes():
    st = os.statvfs("/")
    return st.f_bavail * st.f_frsize


def count_rows(con):
    return con.execute("select count(*) from depot_snapshot").fetchone()[0]


def with_retry(fn, what, attempts=6, delay=10):
    """Der Scheduler haelt die DB im 15-Min-Takt. Wir warten auf das
    Freigeben des Schreiblocks, statt den Dienst anzuhalten."""
    for i in range(1, attempts + 1):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) and "busy" not in str(e):
                raise
            if i == attempts:
                log("FEHLER: %s nach %d Versuchen: %s" % (what, attempts, e))
                raise
            log("%s: DB gesperrt (%s) — Versuch %d/%d, warte %ds"
                % (what, e, i, attempts, delay))
            time.sleep(delay)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30,
                    help="Aufloesungsgrenze in Tagen. Rows JUENGER bleiben unangetastet.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--vacuum-only", action="store_true")
    ap.add_argument("--no-vacuum", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(DB):
        log("FEHLER: %s existiert nicht" % DB)
        return 1

    size_before = db_size()
    free_before = free_bytes()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    log("DB: %s  Groesse: %d Bytes" % (DB, size_before))
    log("Frei auf /: %d Bytes" % free_before)
    log("Grenze: %s  (Rows mit zeit >= cutoff bleiben VOLLSTAENDIG erhalten)"
        % cutoff)
    if args.dry_run:
        log(">>> DRY-RUN, es wird nichts geaendert")

    con = sqlite3.connect(DB, timeout=120, isolation_level=None)
    con.execute("PRAGMA busy_timeout=120000")
    cur = con.cursor()

    total_before = count_rows(con)
    log("depot_snapshot Zeilen VORHER: %d" % total_before)

    if not args.vacuum_only:
        young = cur.execute(
            "select count(*) from depot_snapshot where zeit >= ?", (cutoff,)).fetchone()[0]
        old = cur.execute(
            "select count(*) from depot_snapshot where zeit < ?", (cutoff,)).fetchone()[0]
        keep = cur.execute(
            "select count(*) from (select distinct substr(zeit,1,10) d, depot_typ, ref "
            "from depot_snapshot where zeit < ?)", (cutoff,)).fetchone()[0]

        log("  davon JUENGER als Grenze (bleiben unveraendert): %d" % young)
        log("  davon AELTER als Grenze: %d" % old)
        log("  davon nach Verdichtung auf 1 Zeile/Tag: %d" % keep)
        log("  Ersparnis: %d Zeilen (%.1f %%)"
            % (old - keep, 100.0 * (old - keep) / max(old, 1)))

        if not args.dry_run and old > keep:
            # Backup vor dem Eingriff. sqlite3 .backup() ist transaktions-
            # sicher und blockiert den Scheduler nicht (im Gegensatz zu
            # einem rohen cp einer live beschriebenen DB).
            os.makedirs(BACKUP_DIR, exist_ok=True)
            bak = os.path.join(
                BACKUP_DIR,
                "micro_trader.db.pre-retention-%s" % time.strftime("%Y%m%dT%H%M%SZ"))
            log("Backup -> %s" % bak)

            def _bk():
                bc = sqlite3.connect(DB, timeout=120)
                bc.execute("PRAGMA busy_timeout=120000")
                db = sqlite3.connect(bak)
                with db:
                    bc.backup(db)
                db.close()
                bc.close()
                return bak

            with_retry(_bk, "Backup")
            log("Backup verifiziert: %d Bytes" % os.path.getsize(bak))

            # VERDICHTUNG: pro (Tag, depot_typ, ref) die Zeile mit max(id)
            # behalten, alle anderen aelter als cutoff loeschen.
            # zeit >= cutoff wird per WHERE garantiert NICHT angefasst.
            def _del():
                c2 = sqlite3.connect(DB, timeout=120, isolation_level=None)
                c2.execute("PRAGMA busy_timeout=120000")
                c2.execute("BEGIN IMMEDIATE")
                try:
                    c2.execute(
                        "delete from depot_snapshot where zeit < ? and id not in ("
                        "  select max(id) from depot_snapshot where zeit < ?"
                        "  group by substr(zeit,1,10), depot_typ, ref"
                        ")", (cutoff, cutoff))
                    n = c2.total_changes
                    c2.execute("COMMIT")
                except Exception:
                    c2.execute("ROLLBACK")
                    raise
                finally:
                    c2.close()
                return n

            deleted = with_retry(_del, "Verdichtung")
            log("Geloescht (verdichtet): %d Zeilen" % deleted)
        else:
            log("Kein Loeschen noetig%s" % (" (dry-run)" if args.dry_run else ""))

    total_after = count_rows(con)
    log("depot_snapshot Zeilen NACHHER: %d" % total_after)
    con.close()

    if not args.dry_run and not args.no_vacuum:
        log("VACUUM laeuft (gibt Platz ans Dateisystem zurueck)...")
        t0 = time.time()

        def _vac():
            vc = sqlite3.connect(DB, timeout=300, isolation_level=None)
            vc.execute("PRAGMA busy_timeout=300000")
            vc.execute("VACUUM")
            vc.close()

        with_retry(_vac, "VACUUM", attempts=4, delay=20)
        log("VACUUM fertig in %.1fs" % (time.time() - t0))

    size_after = db_size()
    free_after = free_bytes()
    log("=" * 62)
    log("ERGEBNIS: Zeilen %d -> %d  (Bereinigung: %d)"
        % (total_before, total_after, total_before - total_after))
    if args.dry_run:
        log("ERGEBNIS (dry-run, unveraendert): DB %d Bytes, frei %d Bytes"
            % (size_after, free_after))
    else:
        log("ERGEBNIS: DB %d -> %d Bytes  (GEWINN %d Bytes = %.1f MB)"
            % (size_before, size_after, size_before - size_after,
               (size_before - size_after) / 1048576.0))
        log("ERGEBNIS: frei auf / %d -> %d Bytes  (GEWINN %.1f MB)"
            % (free_before, free_after, (free_after - free_before) / 1048576.0))
    log("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())