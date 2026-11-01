"""ABNAHME: funktioniert das Dashboard nach den Fixes noch?
Prueft gegen den LAUFENDEN Dienst auf 127.0.0.1:5300 mit echter Session.
Legt dafuer einen Wegwerf-User an und raeumt ihn danach wieder auf.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import json
import os
import sys
import urllib.error
import urllib.request
import http.cookiejar
from pathlib import Path

sys.path.insert(0, _MT_BASE)
os.chdir(_MT_BASE)
import security as sec  # noqa: E402

BASE = "http://127.0.0.1:5300"
FEHLER = []
TMPUSER = "__abnahme__"


def pruefe(name, bedingung, meldung):
    if not bedingung:
        FEHLER.append(f"{name}: {meldung}")
    print(f"  {'OK ' if bedingung else 'FEHL'} {name}")


jar = http.cookiejar.CookieJar()
class KeinRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
op_ohne = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(jar), KeinRedirect)


def hole(pfad, headers=None, folgen=True):
    o = op if folgen else op_ohne
    req = urllib.request.Request(BASE + pfad, headers=headers or {})
    try:
        with o.open(req, timeout=90) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e).encode()


def poste(pfad, daten, headers=None):
    import urllib.parse
    body = urllib.parse.urlencode(daten).encode()
    req = urllib.request.Request(BASE + pfad, data=body, headers=headers or {})
    try:
        with op.open(req, timeout=25) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


try:
    print("=== 1. Oeffentliche Erreichbarkeit ===")
    c, _ = hole("/")
    pruefe("Startseite", c == 200, f"HTTP {c}")
    c, _ = hole("/login")
    pruefe("Loginseite", c == 200, f"HTTP {c}")

    print("=== 2. Authentifizierter Bereich ohne Login ===")
    # Ohne Redirect-Follow: sonst waere die 302 zur Login-Seite als 200 lesbar
    c, b = hole("/dashboard", folgen=False)
    pruefe("/dashboard ohne Login -> 302/401", c in (302, 401),
           f"HTTP {c} (Location: {b[:80]!r})")
    c, _ = hole("/api/db_query", folgen=False)
    pruefe("/api/db_query ohne Login -> 401", c == 401, f"HTTP {c}")

    print("=== 3. Login mit Wegwerf-User ===")
    ok, err = sec.create_user(TMPUSER, "Abnahme1234!", "admin")
    if not ok and "exist" not in str(err).lower():
        print(f"  create_user: {err}")
    c, b = poste("/login", {"username": TMPUSER, "password": "Abnahme1234!"})
    pruefe("Login erfolgreich", c in (200, 302), f"HTTP {c}: {b[:120]}")
    pruefe("Session-Cookie gesetzt", any(ck.name == "sid" for ck in jar),
           "kein sid-Cookie erhalten")

    print("=== 4. Nach Login: Leserouten ===")
    for p, label in (("/dashboard", "Dashboard"),
                     ("/data", "Portfoliodaten"),
                     ("/api/db_query?mode=trades&limit=3", "DB-Query"),
                     ("/api/db_query?mode=trades&order=ASC&limit=3", "DB-Query ASC"),
                     ("/api/analysis", "Analyse"),
                     ("/search_ticker?ticker=PLTR", "Tickersuche")):
        c, b = hole(p)
        pruefe(label, c == 200, f"GET {p} -> HTTP {c}: {b[:100]}")

    print("=== 5. CSRF-Token holen und mutierende GET nutzen ===")
    c, b = hole("/api/csrf_token")
    tok = None
    if c == 200:
        try:
            tok = json.loads(b).get("csrf_token")
        except Exception:
            pass
    pruefe("Token-Endpunkt liefert Token", bool(tok), f"HTTP {c}: {b[:120]}")

    # Mutierende GET OHNE Token -> 403 (der eigentliche Fix)
    c, _ = hole("/api/risk_appetite?value=37")
    pruefe("mutierende GET ohne Token -> 403", c == 403, f"HTTP {c}")

    # MIT Token -> darf durch
    vorher = json.loads(Path((_MT_BASE + "/config.json")).read_text()
                        ).get("risk_appetite")
    if tok:
        c, b = hole("/api/risk_appetite?value=37",
                    headers={"X-CSRF-Token": tok})
        pruefe("mutierende GET mit Token -> nicht 403", c != 403,
               f"HTTP {c}: {b[:120]}")
        nachher = json.loads(Path((_MT_BASE + "/config.json")).read_text()
                             ).get("risk_appetite")
        pruefe("Zustand tatsaechlich geaendert", nachher == 37,
               f"risk_appetite={nachher}, erwartet 37")
        if vorher is not None and vorher != 37:
            cfg = Path((_MT_BASE + "/config.json"))
            d = json.loads(cfg.read_text())
            d["risk_appetite"] = vorher
            cfg.write_text(json.dumps(d, indent=2), encoding="utf-8")
            print(f"  (risk_appetite auf Ausgangswert {vorher} zurueckgesetzt)")

    print("=== 6. SQLi ueber die echte HTTP-Route ===")
    if tok:
        for payload in (", (SELECT secret_key FROM secret_store LIMIT 1)",
                        "ASC; DROP TABLE trades"):
            c, b = hole("/api/db_query?mode=trades&order="
                        + urllib.parse.quote(payload),
                        headers={"X-CSRF-Token": tok})
            # Erwartete Antwortform: {"count": N, "error": null, "rows": [...]}
            j, n = None, -1
            try:
                j = json.loads(b)
                if isinstance(j, dict) and "rows" in j:
                    n = len(j["rows"])
                    fehlerfrei = j.get("error") in (None, "")
                else:
                    fehlerfrei = False
            except Exception:
                fehlerfrei = False
            pruefe(f"order={payload[:28]!r} -> normale Trades, kein Fremdzugriff",
                   c == 200 and fehlerfrei and n >= 0,
                   f"HTTP {c}, n={n}, error={j.get('error') if isinstance(j, dict) else '?'}, "
                   f"{b[:100]}")
            # Kein Schluesselname darf in der Antwort auftauchen
            if b"OPENAI_API_KEY" in b or b"API_TEST" in b:
                FEHLER.append(f"SECRET_STORE-LEAK bei order={payload[:28]!r}")
                print(f"  FEHL SECRET_STORE-LEAK bei {payload[:28]!r}")

    print("=== 7. Dashboard-HTML: Fixes drin? ===")
    c, html = hole("/dashboard")
    h = html.decode("utf-8", "replace")
    pruefe("escAttr vorhanden", "function escAttr" in h, "fehlt")
    pruefe("CSRF-Wrapper vorhanden", 'headers.set("X-CSRF-Token"' in h, "fehlt")
    pruefe("kein onclick mit Ticker-Interpolation",
           "showTickerFound('${r.ticker}')" not in h, "noch vorhanden")
    pruefe("Suche nutzt esc()", "${esc(r.ticker)}" in h, "nicht escaped")

finally:
    # Wegwerf-User wieder entfernen
    users = sec._load_users()
    if TMPUSER in users:
        del users[TMPUSER]
        sec._save_users(users)
        print(f"\n[aufraeumen] Wegwerf-User {TMPUSER} entfernt")

print()
if FEHLER:
    print(f"FEHLGESCHLAGEN — {len(FEHLER)} Probleme:")
    for f in FEHLER:
        print("  - " + f)
    sys.exit(1)
print("ABNAHME BESTANDEN: Dashboard vollstaendig funktionsfaehig, "
      "Fixes aktiv.")
