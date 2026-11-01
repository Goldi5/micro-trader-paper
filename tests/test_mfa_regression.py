"""REGRESSIONSTEST LUECKE 4 - MFA faktisch tot / TOTP-Implementierung.

VORHER: fail.
NACHHER: BESTANDEN, Exit-Code 0.

Geprueft wird das VERHALTEN der echten security.py/totp_util.py gegen eine
temporaere Testkopie des User-Stores — die produktive security_users.json wird
nicht veraendert.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

M = Path(_MT_BASE)
FEHLER = []


def pruefe(name, bedingung, meldung):
    if not bedingung:
        FEHLER.append(f"{name}: {meldung}")


# ── 0: Import gegen isolierte Kopie, damit der echte Store unberuehrt bleibt
sichere_kopie = M / "security_users.json"
tmpdir = Path(tempfile.mkdtemp(prefix="mfa_test_"))
test_users = tmpdir / "security_users.json"
shutil.copy2(sichere_kopie, test_users)
orig_users_const = None

import security as sec  # noqa: E402
import totp_util  # noqa: E402

orig_users_const = sec.USERS_FILE
sec.USERS_FILE = str(test_users)          # Umleitung auf die Kopie
sec._load_users.cache_clear() if hasattr(sec._load_users, "cache_clear") else None

try:
    users = sec._load_users()
    # Wir arbeiten auf einem synthetischen User, nicht auf einem echten.
    sec.USERS_FILE = str(test_users)
    u = {
        "username": "mfa_probe", "role": "superadmin", "active": True,
        "status": "active", "password_hash": sec.generate_password_hash("x"),
        "mfa_enabled": True, "mfa_secret": None, "sessions": {},
    }
    users["mfa_probe"] = u
    sec._save_users(users)

    # ── A) Kern-Bypass: Login darf MFA nicht als verifiziert melden ────────
    sid = sec.create_session("mfa_probe", "127.0.0.1")
    store = json.loads(test_users.read_text())["mfa_probe"]["sessions"][sid]
    pruefe("A1", store.get("mfa_verified_at") == 0,
           f"create_session() setzt mfa_verified_at={store.get('mfa_verified_at')} "
           "statt 0 — MFA gilt ab Login als verifiziert, ohne TOTP")
    pruefe("A2", sec.mfa_recently_verified("mfa_probe", sid) is False,
           "mfa_recently_verified() -> True bei mfa_secret=None (Bypass)")

    # Quelltext-Gegenprobe: die alte Formel darf nicht mehr dastehen
    src = (M / "security.py").read_text(encoding="utf-8")
    pruefe("A3", '"mfa_verified_at": now if u.get("mfa_enabled") else 0' not in src,
           "security.py enthaelt weiterhin die Vorab-Verifikation "
           "'mfa_verified_at': now if u.get('mfa_enabled')")

    # ── B) Inkonsistenter Zustand wird selbst geheilt ────────────────────
    users = json.loads(test_users.read_text())
    users["mfa_probe"]["mfa_enabled"] = True
    users["mfa_probe"]["mfa_secret"] = None
    sec._save_users(users)
    neu = sec._load_users()
    pruefe("B1", neu["mfa_probe"].get("mfa_enabled") is False,
           "mfa_enabled=True ohne Secret bleibt bestehen — Gates bleiben "
           "wirkungslos und der Zustand ist nicht ehrlich")

    # ── C) MIT Secret muss MFA wirklich durchgesetzt werden ───────────────
    geheim = totp_util.generate_mfa_secret()
    users = json.loads(test_users.read_text())
    users["mfa_probe"]["mfa_enabled"] = True
    users["mfa_probe"]["mfa_secret"] = geheim
    users["mfa_probe"].pop("mfa_last_counter", None)
    sec._save_users(users)

    sid2 = sec.create_session("mfa_probe", "127.0.0.1")
    pruefe("C1", sec.mfa_recently_verified("mfa_probe", sid2) is False,
           "Mit eingerichtetem MFA gilt die Session direkt nach Login als "
           "verifiziert — der require_recent_mfa-Gate waere ein No-Op")
    sec.mark_mfa_verified("mfa_probe", sid2)
    pruefe("C2", sec.mfa_recently_verified("mfa_probe", sid2) is True,
           "Nach erfolgreicher Verifikation weiterhin 'nicht verifiziert'")
    # Abgelaufene Verifikation
    users = json.loads(test_users.read_text())
    users["mfa_probe"]["sessions"][sid2]["mfa_verified_at"] = \
        int(time.time()) - sec.MFA_GRACE - 10
    sec._save_users(users)
    pruefe("C3", sec.mfa_recently_verified("mfa_probe", sid2) is False,
           "Abgelaufene MFA-Verifikation wird noch akzeptiert")

    # ── D) TOTP-Implementierung: korrekt, aber ohne Replay-Schutz ─────────
    code = totp_util._totp(geheim, int(time.time()))
    pruefe("D1", totp_util.verify_mfa(geheim, code) is True,
           "Ein korrekter TOTP-Code wird abgewiesen — TOTP defekt")
    pruefe("D2", totp_util.verify_mfa(geheim, "000000") is False
           or code == "000000", "Ein falscher Code wird akzeptiert")
    # Fenster-Toleranz: 30s in der Zukunft muss noch gueltig sein
    zukunft = totp_util._totp(geheim, int(time.time()) + 30)
    pruefe("D3", totp_util.verify_mfa(geheim, zukunft) is True,
           "±1-Fenster funktioniert nicht (TOTP zu streng)")
    # 2 Minuten in der Zukunft muss draussen sein
    zuweit = totp_util._totp(geheim, int(time.time()) + 300)
    pruefe("D4", totp_util.verify_mfa(geheim, zuweit) is False,
           "Code aus 5 Minuten Zukunft wird akzeptiert — Fenster zu weit")

    # Replay: derselbe Code zweimal ueber den Login-Pfad
    users = json.loads(test_users.read_text())
    users["mfa_probe"].pop("mfa_last_counter", None)
    sec._save_users(users)
    if hasattr(sec, "verify_mfa_code"):
        ok1, _ = sec.verify_mfa_code("mfa_probe", code)
        ok2, f2 = sec.verify_mfa_code("mfa_probe", code)
        pruefe("D5", ok1 is True, "Erster Versuch mit korrektem Code schlug fehl")
        pruefe("D6", ok2 is False,
               f"Derselbe TOTP-Code wurde erneut akzeptiert ({f2!r}) — "
               "kein Replay-Schutz")
    else:
        FEHLER.append(
            "D5/D6: security.verify_mfa_code() fehlt — es gibt keinen "
            "Replay-Schutz. Beleg des Altverhaltens: derselbe Code wird von "
            f"verify_mfa() {sum(1 for _ in range(2) if totp_util.verify_mfa(geheim, code))}"
            "/2 Mal akzeptiert")

    # ── E) Kein 500 mehr bei mfa_secret=None ──────────────────────────────
    users = json.loads(test_users.read_text())
    users["mfa_probe"]["mfa_secret"] = None
    users["mfa_probe"]["mfa_enabled"] = False
    sec._save_users(users)
    try:
        if hasattr(sec, "verify_mfa_code"):
            ok, fehler = sec.verify_mfa_code("mfa_probe", "123456")
            pruefe("E1", ok is False,
                   "Code wird ohne eingerichtetes MFA akzeptiert")
        else:
            # Altverhalten nachstellen: das war der Aufruf in dashboard.py /mfa
            r = totp_util.verify_mfa(users["mfa_probe"].get("mfa_secret", ""),
                                     "123456")
            pruefe("E1", r is False, "Code wird ohne MFA akzeptiert")
    except Exception as e:
        FEHLER.append(f"E2: MFA-Pruefung crashte bei mfa_secret=None: "
                      f"{type(e).__name__}: {e}")
    try:
        r = totp_util.verify_mfa(None, "123456")
        pruefe("E3", r is False,
               f"verify_mfa(None, ...) liefert {r!r} statt False")
    except Exception as e:
        FEHLER.append(f"E3: verify_mfa(None, ...) crasht weiterhin: "
                      f"{type(e).__name__}: {e}")

    # ── F) compare_digest statt == ────────────────────────────────────────
    tsrc = (M / "totp_util.py").read_text(encoding="utf-8")
    pruefe("F1", "hmac.compare_digest" in tsrc,
           "totp_util.py vergleicht TOTP-Codes nicht mit hmac.compare_digest")
    pruefe("F2", "hmac.compare_digest" in src,
           "security.py nutzt hmac.compare_digest nirgends "
           "(Recovery-Code-Vergleich war ein Timing-Kanal)")

finally:
    sec.USERS_FILE = orig_users_const
    shutil.rmtree(tmpdir, ignore_errors=True)

if FEHLER:
    print("FEHLGESCHLAGEN - MFA weiterhin unwirksam:")
    for f in FEHLER:
        print("  - " + f)
    sys.exit(1)
print("BESTANDEN: keine Vorab-Verifikation, inkonsistenter Zustand geheilt, "
      "Gate erzwingt MFA wenn eingerichtet, TOTP korrekt, Replay abgewiesen, "
      "kein 500 bei fehlendem Secret, compare_digest genutzt.")
