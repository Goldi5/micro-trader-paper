"""REGRESSIONSTEST LUECKE 2 - Node-Proxy ohne Authentifizierung.

VORHER: fail (Daten ohne Credential, ACAO: *, Bind 0.0.0.0).
NACHHER: BESTANDEN, Exit-Code 0.

Prueft den LAUFENDEN Dienst auf 127.0.0.1:8765 aus dem CT heraus:
  1. Ohne Token -> 401 und KEINE Portfoliodaten
  2. Mit falschem Token -> 401
  3. Mit korrektem Token -> 200
  4. Kein ACAO: * mehr
  5. Bind auf 127.0.0.1, nicht 0.0.0.0
  6. /api/health ohne Token, gibt aber nur {ok,ts} zurueck
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

M = Path(_MT_BASE)
BASE_URL = "http://127.0.0.1:8765"
TOKEN_FILE = M / "proxy_token"
FEHLER = []


def hole(pfad, token=None):
    req = urllib.request.Request(BASE_URL + pfad)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)
    except Exception as e:
        return None, str(e).encode(), {}


# ── 0: Dienst laeuft ueberhaupt ─────────────────────────────────────────────
rc = subprocess.run(["systemctl", "is-active", "micro-trader-proxy"],
                    capture_output=True, text=True, timeout=30)
if rc.stdout.strip() != "active":
    FEHLER.append(f"micro-trader-proxy ist nicht active (={rc.stdout.strip()})")

# ── 5: Bind-Adresse ─────────────────────────────────────────────────────────
rc = subprocess.run(["ss", "-ltn"], capture_output=True, text=True, timeout=30)
zeilen = [z for z in rc.stdout.splitlines() if ":8765" in z]
if not zeilen:
    FEHLER.append("nichts lauscht auf Port 8765")
for z in zeilen:
    if "0.0.0.0:8765" in z or "*:8765" in z:
        FEHLER.append(f"Proxy lauscht weiterhin auf allen Interfaces: {z.strip()}")
    elif "127.0.0.1:8765" not in z:
        FEHLER.append(f"unerwartete Bind-Adresse: {z.strip()}")

if not TOKEN_FILE.exists():
    FEHLER.append(f"Token-Datei {TOKEN_FILE} fehlt")
    print("FEHLGESCHLAGEN:"); [print("  - " + f) for f in FEHLER]; sys.exit(1)

mode = oct(TOKEN_FILE.stat().st_mode & 0o777)
if mode != "0o600":
    FEHLER.append(f"Token-Datei hat Modus {mode}, erwartet 0o600")

token = TOKEN_FILE.read_text(encoding="utf-8").strip()
if len(token) < 32:
    FEHLER.append(f"Token zu kurz (Laenge {len(token)}) — vermutlich geraten "
                  "statt per CSPRNG erzeugt")

# ── 1: ohne Token keine Daten ───────────────────────────────────────────────
for pfad in ("/api/portfolios", "/api/system", "/api/ki-decisions",
             "/api/analysis", "/api/quotes"):
    code, body, hdr = hole(pfad)
    if code != 401:
        FEHLER.append(f"{pfad} ohne Token -> HTTP {code}, erwartet 401")
    else:
        try:
            j = json.loads(body)
        except Exception:
            j = {}
        # Keinerlei Fachdaten im Body
        verboten = ("portfolios", "holdings", "raw", "decisions", "quotes",
                    "topTickers", "cash", "uptime")
        for k in verboten:
            if k in j:
                FEHLER.append(f"{pfad} ohne Token liefert '{k}' im Body — Datenleck")

# ── 2: falscher Token ──────────────────────────────────────────────────────
for schlecht in ("falsch", "x" * 64, token[:-1], token.upper()):
    code, body, _ = hole("/api/portfolios", token=schlecht)
    if code != 401:
        FEHLER.append(f"falscher Token {schlecht[:12]!r} -> HTTP {code}, "
                      "erwartet 401")
    if b"portfolios" in body:
        FEHLER.append(f"falscher Token {schlecht[:12]!r} liefert trotzdem Daten")

# ── 3: korrekter Token funktioniert ─────────────────────────────────────────
code, body, hdr = hole("/api/portfolios", token=token)
if code != 200:
    FEHLER.append(f"korrekter Token -> HTTP {code}, erwartet 200 (Proxy kaputt?)")
else:
    j = json.loads(body)
    if not j.get("portfolios"):
        FEHLER.append("korrekter Token liefert keine Portfolios — Proxy verletzt")

# ── 4: kein Wildcard-CORS ──────────────────────────────────────────────────
_, _, hdr = hole("/api/portfolios", token=token)
acao = hdr.get("Access-Control-Allow-Origin", "")
if acao == "*":
    FEHLER.append("ACAO: * weiterhin gesetzt — jeder Origin darf lesen")

# ── 6: /api/health ohne Token, aber ohne Fachdaten ─────────────────────────
code, body, _ = hole("/api/health")
if code != 200:
    FEHLER.append(f"/api/health ohne Token -> HTTP {code}, erwartet 200")
else:
    j = json.loads(body)
    if set(j.keys()) - {"ok", "ts"}:
        FEHLER.append(f"/api/health gibt zusaetzliche Felder preis: {list(j.keys())}")

# ── Quelltext-Gegenprobe ────────────────────────────────────────────────────
src = (M / "proxy" / "proxy-server.mjs").read_text(encoding="utf-8")
if "'0.0.0.0'" in src and "listen" in src:
    FEHLER.append("proxy-server.mjs bindet weiterhin auf 0.0.0.0")
if "Access-Control-Allow-Origin" in src:
    FEHLER.append("proxy-server.mjs setzt weiterhin Access-Control-Allow-Origin")
if "timingSafeEqual" not in src:
    FEHLER.append("Token-Vergleich nutzt nicht timingSafeEqual (timing-Angriff)")

if FEHLER:
    print("FEHLGESCHLAGEN - Proxy weiterhin unauthentifiziert:")
    for f in FEHLER:
        print("  - " + f)
    sys.exit(1)
print("BESTANDEN: Loopback-Bind, 401 ohne/falschem Token, 200 mit Token, "
      "kein ACAO:*, /api/health ohne Fachdaten, timingSafeEqual genutzt.")
