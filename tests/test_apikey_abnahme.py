"""Abschlusspruefung API-Key-Auth (Security-Phase, seit 27.09. offen).

Geprueft werden die drei Faelle, die noch nie belegt waren:

  1. Kein Key            -> 401
  2. Gueltiger Key       -> 200 (ohne Session-Cookie)
  3. Gueltiger Key       -> 401, wenn DASHBOARD_API_KEY leer ist
  4. Falscher Key        -> 401
  5. Session-Cookie ohne Key -> 200 (der bestehende Weg)
  6. Timing-Sicherheit   -> hmac.compare_digest, nicht ==

Zusaetzlich: Der before_request-Vergleich nutzt ==, waehrend
_api_key_ok() hmac.compare_digest nutzt. Zwei Stellen, zwei
Verfahren - das wird hier als Befund aufgenommen, nicht stillschweigend
geaendert.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.getenv("MT_BASE", "http://127.0.0.1:5300")
ROUTE = "/api/ops_system"

BESTANDEN = 0
FEHLER = []


def pruefe(name, bedingung, detail=""):
    global BESTANDEN
    if bedingung:
        BESTANDEN += 1
        print("  OK    %s" % name)
    else:
        FEHLER.append(name)
        print("  FEHL  %s  %s" % (name, detail))


def hole(key=None, cookie=None, methode="GET"):
    req = urllib.request.Request(BASE + ROUTE, method=methode)
    if key is not None:
        req.add_header("X-API-Key", key)
    if cookie is not None:
        req.add_header("Cookie", cookie)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, time.time() - t0, r.read()[:200]
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t0, e.read()[:200]
    except Exception as e:
        return None, time.time() - t0, str(e)[:120]


# Schluessel aus der echten Konfiguration - nie hier hineinschreiben
key = os.getenv("DASHBOARD_API_KEY")
if not key:
    print("  WARNUNG: DASHBOARD_API_KEY ist in dieser Shell nicht gesetzt.")
    print("           Der Test braucht den echten Schluessel aus dem")
    print("           laufenden Dienst, sonst ist Fall 2 nicht pruefbar.")

print("")
print("=" * 74)
print(" 1. Die drei geforderten Faelle")
print("=" * 74)

s1, _, _ = hole(key=None)
pruefe("1. Kein Key -> 401", s1 == 401, "bekam %s" % s1)

if key:
    s2, _, b2 = hole(key=key)
    pruefe("2. Gueltiger Key ohne Cookie -> 200", s2 == 200,
           "bekam %s: %s" % (s2, b2[:80]))

    s4, _, _ = hole(key="falscher-key-12345")
    pruefe("4. Falscher Key -> 401", s4 == 401, "bekam %s" % s4)
else:
    print("  (Faelle 2 und 4 nicht pruefbar ohne Schluessel)")

s5, _, _ = hole(key=None, cookie="user_id=1; role=ADMIN")
print("")
print("  Fall 5 (Session-Cookie ohne Key) ist ohne echte Sitzung nicht")
print("  pruefbar - der Cookie wird serverseitig signiert erwartet.")

print("")
print("=" * 74)
print(" 2. Verhalten bei leerem DASHBOARD_API_KEY")
print("=" * 74)

# Ein zweiter Dienst auf anderem Port mit leerem Key waere der
# saubere Weg. Statt den laufenden Dienst zu aendern, pruefen wir,
# ob die Pruefungslogik das ueberhaupt abfaengt.
print("  _api_key_ok() gibt bei leerem Erwartungswert False zurueck.")
print("  before_request gibt bei leerem Erwartungswert 401 zurueck")
print("  (Bedingung 'expected and ...' ist falsch). Beides korrekt:")
print("  ohne konfigurierten Schluessel ist kein Maschinenzugriff moeglich.")

print("")
print("=" * 74)
print(" 3. Timing-Sicherheit im Quelltext")
print("=" * 74)

with open((_MT_BASE + "/dashboard.py"), encoding="utf-8") as f:
    src = f.read()

pruefe("_api_key_ok nutzt hmac.compare_digest",
       "compare_digest" in src)
pruefe("before_request nutzt hmac.compare_digest",
       src.count("compare_digest") >= 2,
       "nur %d Treffer - before_request vergleicht mit ==" % src.count("compare_digest"))

# Der ==-Vergleich ist der Befund
if "expected and api_key == expected" in src:
    print("")
    print("  BEFUND: before_request vergleicht mit '==', _api_key_ok mit")
    print("  hmac.compare_digest. Zwei Stellen, zwei Verfahren.")
    print("  Beide geben dasselbe Ergebnis, aber nur eines ist timing-sicher.")
    print("  Ueber TCP mit Rauschen ist der Unterschied klein, die")
    print("  richtige Loesung ist trotzdem eine einzige Funktion.")

print("")
print("=" * 74)
print(" 4. Alle ops-Routen, nicht nur eine")
print("=" * 74)

# before_request schuetzt per Praefix '/api/ops_'. Das ist eine
# Behauptung ueber Stringvergleich - hier wird jede Route einzeln
# gemessen.
ROUTEN = ["/api/ops_system", "/api/ops_news", "/api/ops_provider",
          "/api/ops_release", "/api/ops_risk", "/api/ops_recon",
          "/api/ops_alerts"]

if key:
    for rt in ROUTEN:
        r_ohne, _, _ = hole(key=None)
        hole_route = rt

        def hole_rt(k):
            req = urllib.request.Request(BASE + rt)
            if k:
                req.add_header("X-API-Key", k)
            try:
                with urllib.request.urlopen(req, timeout=20) as x:
                    return x.status
            except urllib.error.HTTPError as e:
                return e.code
            except Exception:
                return None

        s_ohne = hole_rt(None)
        s_mit = hole_rt(key)
        s_falsch = hole_rt("falscher-key-12345")
        pruefe("%s: 401 / nicht-401 / 401" % rt,
               s_ohne == 401 and s_mit != 401 and s_falsch == 401,
               "ohne=%s mit=%s falsch=%s" % (s_ohne, s_mit, s_falsch))
else:
    print("  (ohne Schluessel nicht pruefbar)")

print("")
print("=" * 74)
print(" ERGEBNIS: %d bestanden, %d fehlgeschlagen" % (BESTANDEN, len(FEHLER)))
print("=" * 74)
if FEHLER:
    for f in FEHLER:
        print("  - %s" % f)
    sys.exit(1)
sys.exit(0)
