#!/usr/bin/env python3
"""
Backup-Helper für Micro-Trader — REGEL #1: Vor jeder Änderung Backup.

Verwendung:
  python backup.py before <beschreibung>        # Snapshot vor Änderung
  python backup.py after  <beschreibung>        # Snapshot nach Änderung (optional)
  python backup.py list                         # Alle Backups auflisten
  python backup.py restore <backup_id>          # Backup zurückspielen
  python backup.py rollback <n>                 # Letzte n Backups ignorieren (neueste zuerst)

Jeder Snapshot speichert ALLE *.py + *.json + *.html + *.md + settings in
einen zeitstempelierten Ordner unter backups/.

Regel #1: KEIN File wird editiert, ohne ZUVOR `backup.py before` auszuführen.
"""
import os, sys, shutil, json, time, glob

BASE = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE, "backups")
EXTS = ("*.py", "*.json", "*.html", "*.md", "*.cfg", "*.ini", "*.txt")

def _ts():
    return time.strftime("%Y%m%d_%H%M%S")

def _snapshot_id(desc):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in desc)[:40]
    return f"{_ts()}__{safe}"

def create_snapshot(desc, phase):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    sid = _snapshot_id(desc)
    dest = os.path.join(BACKUP_DIR, sid)
    os.makedirs(dest, exist_ok=True)
    copied = 0
    for ext in EXTS:
        for f in glob.glob(os.path.join(BASE, ext)):
            if os.path.basename(f).startswith("backups"):
                continue
            # ignoriere riesige Log-Files (ki_log, spec_log, system_log) – nur Meta
            base = os.path.basename(f)
            if base in ("ki_log.json", "spec_log.json", "system_log.json", "regel_history.json"):
                # nur kopieren wenn klein (<5MB), sonst Symlink-Info
                try:
                    if os.path.getsize(f) > 5_000_000:
                        # schreibe nur einen Hinweis
                        with open(os.path.join(dest, base + ".SKIPPED"), "w") as ff:
                            ff.write(f"Skipped (>{5}MB): {base} – nicht im Backup, nur live-State")
                        continue
                except Exception:
                    pass
            shutil.copy2(f, dest)
            copied += 1
    # Metadaten
    meta = {
        "id": sid, "desc": desc, "phase": phase, "time": time.time(),
        "time_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": copied, "base": BASE,
    }
    with open(os.path.join(dest, "_META.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"✅ Backup erstellt: {sid} ({copied} Dateien) – {desc}")
    return sid

def list_backups():
    if not os.path.exists(BACKUP_DIR):
        print("Keine Backups vorhanden.")
        return []
    entries = []
    for d in sorted(os.listdir(BACKUP_DIR), reverse=True):
        meta_p = os.path.join(BACKUP_DIR, d, "_META.json")
        if os.path.exists(meta_p):
            with open(meta_p, encoding="utf-8") as f:
                entries.append(json.load(f))
        else:
            entries.append({"id": d, "desc": "?", "time_iso": "?", "files": "?"})
    print(f"{'#':<4} {'ID':<26} {'ZEIT':<20} {'PHASE':<8} {'DATEIEN':<7} BESCHREIBUNG")
    for i, e in enumerate(entries):
        print(f"{i:<4} {e['id'][:24]:<26} {str(e.get('time_iso','?')):<20} "
              f"{str(e.get('phase','?')):<8} {str(e.get('files','?')):<7} {e.get('desc','?')}")
    return entries

def restore(sid_or_idx):
    # idx oder id?
    entries = list_backups()
    target = None
    if sid_or_idx.isdigit():
        idx = int(sid_or_idx)
        if 0 <= idx < len(entries):
            target = entries[idx]["id"]
    else:
        for e in entries:
            if e["id"].startswith(sid_or_idx) or sid_or_idx in e["id"]:
                target = e["id"]
                break
    if not target:
        print(f"❌ Backup nicht gefunden: {sid_or_idx}")
        return False
    src = os.path.join(BACKUP_DIR, target)
    # Restore: nur Dateien, keine _META / .SKIPPED
    restored = 0
    for f in os.listdir(src):
        if f.startswith("_META") or f.endswith(".SKIPPED"):
            continue
        shutil.copy2(os.path.join(src, f), os.path.join(BASE, f))
        restored += 1
    print(f"✅ Wiederhergestellt aus {target}: {restored} Dateien nach {BASE}")
    return True

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "before":
        desc = " ".join(sys.argv[2:]) or "unbenannt"
        create_snapshot(desc, "before")
    elif cmd == "after":
        desc = " ".join(sys.argv[2:]) or "unbenannt"
        create_snapshot(desc, "after")
    elif cmd == "list":
        list_backups()
    elif cmd == "restore":
        if len(sys.argv) < 3:
            print("Usage: backup.py restore <id|idx>")
            return
        restore(sys.argv[2])
    elif cmd == "rollback":
        # letzte n Backups "verwerfen" = einfach anzeigen, welche das wären
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        entries = list_backups()
        print(f"\n⚠️ Rollback würde die letzten {n} Snapshots betreffen:")
        for e in entries[:n]:
            print(f"  → {e['id']} ({e.get('desc')})")
        print("Nutze 'restore <id>' um einen FRÜHEREN Stand zu reaktivieren.")
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
