"""REGRESSIONSTEST LUECKE 5 + LUECKE 7 - CSRF-Secret und mutierende GET-Routen.

VORHER: fail.
NACHHER: BESTANDEN, Exit-Code 0.

Geprueft wird gegen die echte Flask-App im test_client. Auth wird dabei nur
in-process vorgetaeuscht (kein Login noetig, keine echten Credentials).
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, _MT_BASE)
os.chdir(_MT_BASE)
import security as sec  # noqa: E402
import dashboard  # noqa: E402

FEHLER = []


def pruefe(name, bedingung, meldung):
    if not bedingung:
        FEHLER.append(f"{name}: {meldung}")


# ── LUECKE 5: CSRF-Secret ───────────────────────────────────────────────────
src = (Path(_MT_BASE) / "security.py").read_text(encoding="utf-8")

pruefe("5a", "MICRO_TRADER_CSRF_SECRET" in src,
       "security.py liest die korrekte Variable MICRO_TRADER_CSRF_SECRET nicht")
# 5b: Die alte Ein-Zeilen-Zuweisung darf nicht mehr AKTIV sein. Der alte
# Ausdruck erscheint weiterhin im Docstring als historische Notiz — das ist
# gewollt und kein Fehler, deshalb wird nur die tatsaechliche Zuweisung
# geprueft.
_pruefe_5b = True
for _z in src.split("\n"):
    _c = _z.split("#", 1)[0].strip()
    if _c.startswith("CSRF_SECRET =") and "_load_or_create_secret" not in _c:
        _pruefe_5b = False
        FEHLER.append(
            f"5b: CSRF_SECRET wird noch direkt zugewiesen: {_c!r} — "
            "der Tippfehler-Zugriff ist weiterhin aktiv")
pruefe("5c", ".csrf_secret" in src,
       "CSRF-Secret wird nicht in einer Datei persistiert")

# Persistenz: Secret muss einen Neustart ueberleben
sekret_datei = Path(_MT_BASE) / ".csrf_secret"
pruefe("5d", sekret_datei.exists(), f"{sekret_datei} wurde nicht angelegt")
if sekret_datei.exists():
    m = oct(sekret_datei.stat().st_mode & 0o777)
    pruefe("5e", m == "0o600", f"Secret-Datei hat Modus {m}, erwartet 0600")
    wert = sekret_datei.read_text(encoding="utf-8").strip()
    pruefe("5f", len(wert) >= 32, f"Secret zu kurz (Laenge {len(wert)})")
    # Neustart-Simulation: Modul neu laden, CSRF_SECRET muss gleich bleiben
    alt = sec.CSRF_SECRET
    rc = subprocess.run(
        [(_MT_BASE + "/venv/bin/python"), "-c",
         "import security; print(len(security.CSRF_SECRET))"],
        capture_output=True, text=True, timeout=120,
        cwd=_MT_BASE)
    pruefe("5g", rc.returncode == 0 and rc.stdout.strip() == str(len(alt)),
           "CSRF_SECRET aendert sich zwischen zwei Prozessstarts "
           f"(neu: {rc.stdout.strip()!r}, alt: {len(alt)}) — nicht restart-stabil")

# Ein Token muss jetzt laenger als ein Prozessstart gueltig bleiben:
# gleicher Serializer, Token gegen die NEU geladene Instanz pruefen.
tok = sec.generate_csrf_token()
rc = subprocess.run(
    [(_MT_BASE + "/venv/bin/python"), "-c",
     "import security,sys; sys.exit(0 if security.verify_csrf_token(sys.argv[1]) "
     "else 1)", tok],
    capture_output=True, text=True, timeout=120, cwd=_MT_BASE)
pruefe("5h", rc.returncode == 0,
       "Ein CSRF-Token wird von einem zweiten Prozess nicht anerkannt — "
       "das Secret ist nicht restart-stabil")

# ── LUECKE 7: mutierende GET-Routen brauchen Token ─────────────────────────
# 5a-5h laufen auch auf dem alten Code durchfuehrbar; ab hier gibt es die
# neuen Symbole erst nach dem Fix. Ohne sie ist die Luecke per Definition
# offen, das wird als solches gemeldet (nicht als Crash).
if not (hasattr(sec, "CSRF_MUTATING_GET_PATHS")
        and hasattr(sec, "csrf_token_strict_valid_for_request")):
    FEHLER.append(
        "7a: security.CSRF_MUTATING_GET_PATHS fehlt — es gibt keine Liste "
        "zustandsaendernder GET-Routen. Der CSRF-Guard uebersprang bisher "
        "JEDEN GET/HEAD-Request, d.h. /api/depot_loeschen, /api/pause_trading, "
        "/api/depot_verkaufen u.a. waren ohne CSRF-Token aufrufbar.")
    FEHLER.append(
        "7x: security.csrf_token_strict_valid_for_request() fehlt — die "
        "zustandsaendernden GETs werden nicht strikt geprueft.")
    print("FEHLGESCHLAGEN - CSRF-Schutz unvollstaendig:")
    for f in FEHLER:
        print("  - " + f)
    sys.exit(1)

app = dashboard.app
app.config["TESTING"] = True

# Auth in-process vorzaeubern
sec.current_user = lambda: {"username": "probe", "role": "superadmin",
                            "status": "active", "active": True}
sec.resolve_tenant_for_user = lambda u: 1
sec.effective_role = lambda u: "superadmin"
sec.touch_session = lambda *a, **k: None
sec.set_current_tenant = lambda t: None
dashboard.sec = sec

c = app.test_client()

pruefe("7a", len(sec.CSRF_MUTATING_GET_PATHS) >= 8,
       f"nur {len(sec.CSRF_MUTATING_GET_PATHS)} mutierende GET-Routen erfasst")

# Die gefaehrlichen Routen MUSSEN im Set stehen
pflicht = ["/api/pause_trading", "/api/depot_loeschen", "/api/depot_schliessen",
           "/api/depot_verkaufen", "/api/depot_pause", "/api/suspend_trading",
           "/api/risk_appetite", "/api/close_portfolio"]
for p in pflicht:
    pruefe("7b", p in sec.CSRF_MUTATING_GET_PATHS,
           f"{p} fehlt in CSRF_MUTATING_GET_PATHS — weiterhin ohne Token aufrufbar")

# Reine Lese-GETs duerfen NICHT im Set stehen (sonst bricht das Dashboard)
verboten = ["/data", "/api/analysis", "/api/db_query", "/search_ticker",
            "/api/ki_decisions", "/depot_json"]
for p in verboten:
    pruefe("7c", p not in sec.CSRF_MUTATING_GET_PATHS,
           f"{p} ist eine Lese-Route und wurde faelschlich token-pflichtig")

# Guard-Verhalten: csrf_token_required
pruefe("7d", sec.csrf_token_required("/api/depot_loeschen", "GET") is True,
       "csrf_token_required() erkennt mutierende GETs nicht")
pruefe("7e", sec.csrf_token_required("/data", "GET") is False,
       "Lese-GET wurde faelschlich als mutierend eingestuft")
pruefe("7f", sec.csrf_token_required("/api/anything", "POST") is True,
       "POST wird nicht als token-pflichtig erkannt")

# Echter Request ohne Token muss 403 liefern
for p in ("/api/pause_trading?state=on", "/api/risk_appetite?value=99"):
    r = c.get(p)
    pruefe("7g", r.status_code == 403,
           f"GET {p} ohne Token -> HTTP {r.status_code}, erwartet 403 "
           "(zustandsaendernde GET-Route ohne CSRF-Schutz)")

# Mit gueltigem Token muss es durchgehen
tok = sec.generate_csrf_token()
r = c.get("/api/risk_appetite?value=37", headers={"X-CSRF-Token": tok})
pruefe("7h", r.status_code != 403,
       f"GET mit gueltigem Token -> HTTP {r.status_code}: "
       f"{r.get_data(as_text=True)[:120]}")

# Zustand darf sich durch den Angriff ohne Token nicht geaendert haben
import json as _json
cfg = Path((_MT_BASE + "/config.json"))
ist = _json.loads(cfg.read_text()) if cfg.exists() else {}
pruefe("7i", ist.get("risk_appetite") != 99,
       f"config.json risk_appetite wurde auf 99 gesetzt (Wert: "
       f"{ist.get('risk_appetite')}) — der Angriff ohne Token war wirksam")
soll = ist.get("risk_appetite")
# Auf den Wert zuruecksetzen, den der Token-Request gesetzt hat
if soll == 37:
    cfg.write_text(_json.dumps({**ist, "risk_appetite": 37}, indent=2),
                   encoding="utf-8")
    print(f"[aufraeumen] config.json risk_appetite={ist.get('risk_appetite')} "
          "(Wert war vorher gesetzt)")

# 7j: POST bleibt unveraendert. Der permissive Lokal-Origin-Fallback in
# csrf_token_valid_for_request() gilt fuer POST weiter (Bestandteil des
# urspruenglichen BUG-005-Designs, Aenderung waere ein Redesign). Fuer die
# mutierenden GETs wurde er per csrf_token_strict_valid_for_request()
# abgeschaltet — genau das pruefen 7g/7h. Hier nur kontrollieren, dass die
# bestehende POST-Semantik nicht kaputt ist: ein Request mit gueltigem
# Token muss durchgelassen werden.
tok = sec.generate_csrf_token()
import time as _t7
_t0 = _t7.time()
r = c.post("/api/depot_neu", json={"kategorie": "aktien"},
           headers={"X-CSRF-Token": tok})
pruefe("7j", r.status_code != 403,
       f"POST mit gueltigem Token -> HTTP {r.status_code}: "
       f"{r.get_data(as_text=True)[:120]} — die bestehende POST-Semantik "
       "ist kaputt")

# 29.09.2026: Der Aufruf legte ein echtes Depot an
# (depot_020_paper.json, 100 EUR, leer) und liess es liegen. Der Test
# prueft den Statuscode, nicht den Bestand - aber der Betrieb sieht die
# Datei danach, und batch_trader sammelt sie per glob ein.
try:
    _pfad = (r.get_json(silent=True) or {}).get("pfad")
except Exception:
    _pfad = None
if _pfad and os.path.exists(_pfad):
    os.remove(_pfad)
    print("  [OK]   7j-r: Testdepot entfernt: %s" % os.path.basename(_pfad))
else:
    try:
        import glob as _g7
        for _f in _g7.glob((_MT_BASE + "/depot_0[0-9]0_paper.json")):
            if abs(os.path.getmtime(_f) - _t0) < 120:
                os.remove(_f)
                print("  [OK]   7j-r: Testdepot entfernt: %s"
                      % os.path.basename(_f))
    except Exception as _e7:
        print("  [!!]   7j-r: Aufraeumen fehlgeschlagen: %s" % _e7)

# Token-Endpunkt existiert
pruefe("7k", "/api/csrf_token" in [str(x) for x in app.url_map.iter_rules()],
       "Route /api/csrf_token fehlt — das Frontend kann kein Token beziehen")
r = c.get("/api/csrf_token")
pruefe("7l", r.status_code == 200 and r.get_json().get("csrf_token"),
       f"/api/csrf_token -> HTTP {r.status_code} ohne Token")

# Frontend schickt den Header ueberhaupt
html = (Path(_MT_BASE) / "dashboard.html").read_text(encoding="utf-8")
pruefe("7m", 'headers.set("X-CSRF-Token"' in html,
       "dashboard.html haengt den X-CSRF-Token nie an Requests an")
pruefe("7n", "/api/csrf_token" in html,
       "dashboard.html holt kein Token")

if FEHLER:
    print("FEHLGESCHLAGEN - CSRF-Schutz unvollstaendig:")
    for f in FEHLER:
        print("  - " + f)
    sys.exit(1)
print(f"BESTANDEN: CSRF-Secret korrekt benannt und restart-stabil, "
      f"{len(sec.CSRF_MUTATING_GET_PATHS)} mutierende GET-Routen token-pflichtig, "
      "Lese-GETs unveraendert, Frontend sendet Token.")
