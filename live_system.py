"""live_system.py — Phase 7: Getrenntes Live-System (Gerüst).

AUFTRAG §2.2: Live-System ist strikt getrennt vom Lern-/Paper-System:
- eigene Secrets (live_secret_store, tenant-isoliert)
- eigene Brokerverbindung (nur via Simulator/Sandbox, NIEMALS echte Orders hier)
- eigener Scheduler (live_loop, separat vom batch_trader)
- eigene Risiko-Limits (live_risk_limits)
- eigener Audit-Log (live_audit)
- eigener Kill-Switch (live_kill_switch)
- eigene Monitoring-Schicht
- nur freigegebene Releases (live_release Gate, siehe freigabe.py / Phase 8)

SICHERHEIT: PAPER_ONLY gilt weiter. Dieses Modul enthält KEINE echten
Broker-Orders. Broker-Adapter ist Phase 9 (Simulator/Sandbox). Live-Aktivierung
nur durch manuellen Prozess Phase 14.

Aufruf: from live_system import LiveSystem
"""

import os, json, sqlite3, time, threading
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "micro_trader.db")

# Eigener Kill-Switch-State (nur Live)
_KILL_SWITCH_FILE = os.path.join(BASE, "live_kill_switch.json")
_LIVE_CONFIG_FILE = os.path.join(BASE, "live_config.json")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class LiveSystem:
    """Kapselt den isolierten Live-Bereich. Liest KEINE Lern-JSON / Paper-Depots."""

    def __init__(self, tenant_id=1):
        self.tenant_id = tenant_id
        self.config = self._lade_config()
        self.kill_switch = self._lade_kill_switch()

    def _lade_config(self):
        if os.path.exists(_LIVE_CONFIG_FILE):
            try:
                return json.load(open(_LIVE_CONFIG_FILE, encoding="utf-8"))
            except Exception:
                pass
        # Default: deaktiviert (PAPER_ONLY), nur Zielzustand vorbereitet
        return {
            "aktiv": False,            # NIEMALS True ohne Phase-14-Freigabe
            "modus": "PAPER_ONLY",
            "broker": None,             # Phase 9: Simulator/Sandbox
            "max_positions": 1,         # Micro-Live: 1 Portfolio (Phase 13)
            "max_pos_groesse": 100.0,   # harte Limits (Phase 13)
            "tagesverlust_limit": 10.0,
            "gesamtverlust_limit": 20.0,
            "drawdown_limit": 15.0,
            "erstellt": _now(),
        }

    def _lade_kill_switch(self):
        if os.path.exists(_KILL_SWITCH_FILE):
            try:
                return json.load(open(_KILL_SWITCH_FILE, encoding="utf-8"))
            except Exception:
                pass
        return {"safe_stop": True, "grund": "Initial (PAPER_ONLY)", "zeit": _now()}

    def speichern(self):
        json.dump(self.config, open(_LIVE_CONFIG_FILE, "w", encoding="utf-8"),
                  indent=2, ensure_ascii=False)
        json.dump(self.kill_switch, open(_KILL_SWITCH_FILE, "w", encoding="utf-8"),
                  indent=2, ensure_ascii=False)

    # ── Kill-Switch (eigen, Phase 11 detailliert) ──
    def kill_switch_aktivieren(self, grund="Manuell"):
        self.kill_switch = {"safe_stop": True, "grund": grund, "zeit": _now()}
        self.speichern()
        self._audit("KILL_SWITCH_ON", grund)
        return True

    def kill_switch_freigeben(self, grund="Manuell"):
        # Nur mit autorisierter Freigabe (Phase 14). Hier nur Platzhalter.
        self.kill_switch = {"safe_stop": False, "grund": grund, "zeit": _now()}
        self.speichern()
        self._audit("KILL_SWITCH_OFF", grund)
        return True

    @property
    def ist_gestoppt(self):
        return bool(self.kill_switch.get("safe_stop"))

    # ── eigene Audit-Log (isoliert von Paper-Audit) ──
    def _audit(self, aktion, detail=""):
        pf = os.path.join(BASE, "live_audit.json")
        log = []
        if os.path.exists(pf):
            try:
                log = json.load(open(pf, encoding="utf-8"))
            except Exception:
                log = []
        log.append({"zeit": _now(), "tenant": self.tenant_id, "aktion": aktion,
                    "detail": detail})
        json.dump(log[-500:], open(pf, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    # ── Release-Gate (Phase 8): nur freigegebene Releases ausführen ──
    def release_erlaubt(self, release_hash):
        """Prüft ob Release im live_release Gate freigegeben ist (live_releases Tabelle)."""
        import sqlite3
        try:
            row = sqlite3.connect(DB).execute(
                "SELECT status FROM live_releases WHERE release_hash=? AND tenant_id=?",
                (release_hash, self.tenant_id)).fetchone()
            return bool(row and row[0] == "APPROVED")
        except Exception:
            return False

    def status(self):
        return {
            "tenant": self.tenant_id,
            "aktiv": self.config.get("aktiv"),
            "modus": self.config.get("modus"),
            "safe_stop": self.ist_gestoppt,
            "broker": self.config.get("broker"),
            "limits": {
                "max_positions": self.config.get("max_positions"),
                "max_pos_groesse": self.config.get("max_pos_groesse"),
                "tagesverlust": self.config.get("tagesverlust_limit"),
                "gesamtverlust": self.config.get("gesamtverlust_limit"),
                "drawdown": self.config.get("drawdown_limit"),
            },
        }

    # ── Phase 13: Micro-Live-Vorbereitung ──
    def vorbereiten_micro_live(self):
        """Setzt Micro-Live-Zielkonfiguration (1 Portfolio, harte Limits).
        AKTIV bleibt False (keine Aktivierung ohne Phase-14-Freigabe)."""
        self.config.update({
            "aktiv": False,               # unveraendert: PAPER_ONLY
            "modus": "MICRO_LIVE_TARGET",
            "max_positions": 1,          # Micro-Live: 1 Portfolio
            "max_pos_groesse": 100.0,    # harte Limits (Auftrag §13)
            "tagesverlust_limit": 10.0,
            "gesamtverlust_limit": 20.0,
            "drawdown_limit": 15.0,
            "vorbereitet": _now(),
        })
        self.speichern()
        self._audit("MICRO_LIVE_VORBEREITET", "1 Portfolio, Limits gesetzt")
        return self.config

    def validiere_limits(self, positionen_anzahl, pos_groesse, tagesverlust, gesamtverlust):
        """Prüft ob Live-Parameter innerhalb der harten Limits bleiben.
        Returns: (ok, gruende[])."""
        gruende = []
        if positionen_anzahl > self.config.get("max_positions", 1):
            gruende.append(f"zu viele Positionen ({positionen_anzahl} > "
                           f"{self.config.get('max_positions')})")
        if pos_groesse > self.config.get("max_pos_groesse", 100):
            gruende.append(f"Position zu gross ({pos_groesse} > "
                           f"{self.config.get('max_pos_groesse')})")
        if tagesverlust > self.config.get("tagesverlust_limit", 10):
            gruende.append(f"Tagesverlust ueberschritten ({tagesverlust} > "
                           f"{self.config.get('tagesverlust_limit')})")
        if gesamtverlust > self.config.get("gesamtverlust_limit", 20):
            gruende.append(f"Gesamtverlust ueberschritten ({gesamtverlust} > "
                           f"{self.config.get('gesamtverlust_limit')})")
        return (len(gruende) == 0, gruende)


class ReleaseRegistry:
    """Phase 8: Registry + Gate für freigegebene Releases.

    Flow (Auftrag §Freigabemodell):
      Learning/Paper -> Rule Candidate -> Validation -> Review -> Approval
      -> Signed/Hashed Release -> Live-Release-Gate -> Live-System

    Diese Klasse verwaltet die Registry (live_requests Tabelle) + das Gate.
    PAPER_ONLY: keine echte Aktivierung, nur Struktur/Metadaten.
    """

    def __init__(self, tenant_id=1):
        self.tenant_id = tenant_id

    def _conn(self):
        return sqlite3.connect(DB)

    def _migrate(self):
        """Erstellt eigene live_releases-Tabelle für Release-Gate (idempotent)."""
        conn = self._conn()
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS live_releases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL DEFAULT 1,
                    release_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    meta TEXT,
                    requested_by TEXT,
                    reviewed_by TEXT,
                    signatur TEXT,
                    freigegeben TEXT,
                    erstellt TEXT
                )""")
            conn.commit()
        except Exception as e:
            print(f"ReleaseRegistry._migrate Fehler: {e}")
        finally:
            conn.close()

    def registrieren(self, release_hash, meta=None):
        """Registriert ein Release (aus Learning/Paper validiert). Status PENDING."""
        self._migrate()
        meta = meta or {}
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO live_releases
                   (tenant_id, release_hash, status, meta, requested_by, erstellt)
                   VALUES (?, ?, 'PENDING', ?, 'system', ?)""",
                (self.tenant_id, release_hash, json.dumps(meta, ensure_ascii=False), _now()))
            conn.commit()
            return True
        except Exception as e:
            print(f"ReleaseRegistry.registrieren Fehler: {e}")
            return False
        finally:
            conn.close()

    def approve(self, release_hash, approved_by, signatur=None):
        """Approval (Vier-Augen, MFA) -> Status APPROVED + Signatur."""
        conn = self._conn()
        try:
            conn.execute(
                """UPDATE live_releases SET status='APPROVED', reviewed_by=?,
                   signatur=?, freigegeben=? WHERE release_hash=? AND tenant_id=?""",
                (approved_by, signatur or "", _now(), release_hash, self.tenant_id))
            conn.commit()
            return True
        except Exception as e:
            print(f"ReleaseRegistry.approve Fehler: {e}")
            return False
        finally:
            conn.close()

    def status(self, release_hash):
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT status, reviewed_by, signatur FROM live_releases WHERE release_hash=?",
                (release_hash,)).fetchone()
            return dict(zip(["status", "approved_by", "signatur"], row)) if row else None
        finally:
            conn.close()

    def liste(self, status=None):
        conn = self._conn()
        try:
            if status:
                rows = conn.execute(
                    "SELECT release_hash, status, reviewed_by FROM live_releases WHERE status=?",
                    (status,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT release_hash, status, reviewed_by FROM live_releases").fetchall()
            return [dict(zip(["hash", "status", "by"], r)) for r in rows]
        finally:
            conn.close()


if __name__ == "__main__":
    ls = LiveSystem(tenant_id=1)
    print(json.dumps(ls.status(), indent=2, ensure_ascii=False))
    print("Kill-Switch aktiv?", ls.ist_gestoppt)
    rr = ReleaseRegistry(1)
    print("Release-Registry bereit:", hasattr(rr, "registrieren"))
