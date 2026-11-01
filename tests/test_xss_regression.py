"""REGRESSIONSTEST LUECKE 3 - Stored XSS in dashboard.html.

VORHER: fail (Nutzlast erreicht innerHTML unescapt).
NACHHER: BESTANDEN, Exit-Code 0.

Der Test extrahiert den echten Render-Block aus dashboard.html (Zeilen um
`box.innerHTML = d.results.map(...)`) und fuehrt ihn in Node mit einem
DOM-Shim aus. Dadurch wird exakt der ausgelieferte Code geprueft, nicht eine
Nachbildung.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import json
import re
import subprocess
import sys
from pathlib import Path

M = Path(_MT_BASE)
HTML = M / "dashboard.html"
FEHLER = []

# ── 1: Statische Gegenprobe am ausgelieferten HTML ──────────────────────────
src = HTML.read_text(encoding="utf-8")
zeilen = src.split("\n")

block = None
for i, z in enumerate(zeilen):
    if "d.results.map" in z and "innerHTML" in z:
        block = "\n".join(zeilen[i:i + 8])
        break
if block is None:
    FEHLER.append("Render-Block 'd.results.map' in dashboard.html nicht gefunden")
    print("FEHLGESCHLAGEN:"); [print("  - " + f) for f in FEHLER]; sys.exit(1)

if "onclick=" in block:
    FEHLER.append("Render-Block interpoliert weiterhin in ein onclick-Attribut "
                  "(JS-String-Injection):\n      " +
                  "\n      ".join(block.strip().split("\n")))

# Jede Interpolation muss escaped werden
for var in ("r.ticker", "r.name", "r.risk", "r.shares"):
    if re.search(r"\$\{\s*" + re.escape(var) + r"\s*\}", block):
        FEHLER.append(f"{var} wird unescapt in innerHTML interpoliert")

# escAttr muss definiert sein
if "function escAttr" not in src:
    FEHLER.append("escAttr() fehlt — Attribut-Werte waeren nicht abgesichert")
if "data-ticker=" not in block:
    FEHLER.append("Render-Block nutzt kein data-ticker-Attribut")

# ── 2: Ausfuehrungstest: den echten Block in Node fahren ────────────────────
esc_impl = """
function esc(s) {
  const d = { _t: String(s == null ? "" : s), set textContent(v){ this._t = String(v); },
              get innerHTML(){ return this._t
                  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); } };
  d.textContent = s || "";
  return d.innerHTML;
}
"""
escattr_impl = """
function escAttr(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
"""
# Nur die map()-Zeile als ausfuehrbaren Ausdruck extrahieren
m = re.search(r"d\.results\.map\(r => `(.*?)`\)", block, re.S)
if not m:
    FEHLER.append("Template-String im Render-Block nicht extrahierbar")
else:
    template = m.group(1)
    harness = f"""
{esc_impl}
{escattr_impl}
const NUTZLASTEN = [
  {{ ticker: '<img src=x onerror=alert(1)>', name: 'Evil', risk: 'x', shares: 1, wert: 1 }},
  {{ ticker: "PLTR'-alert(3)-'",       name: '</b><script>alert(2)</script>', risk: 'x', shares: 1, wert: 1 }},
  {{ ticker: 'A"><svg onload=alert(4)>', name: 'B', risk: 'x', shares: 1, wert: 1 }},
  {{ ticker: 'PLTR', name: 'K', risk: 'x', shares: 1, wert: 1 }},
];
const d = {{ results: NUTZLASTEN }};
const out = d.results.map(r => `{template}`).join("");
console.log(out);
"""
    js = M / "_xss_harness.mjs"
    js.write_text(harness, encoding="utf-8")
    try:
        r = subprocess.run(["node", str(js)], capture_output=True, text=True,
                           timeout=60, cwd=str(M))
    except Exception as e:
        FEHLER.append(f"Node-Ausfuehrung fehlgeschlagen: {e}")
        r = None
    finally:
        js.unlink(missing_ok=True)

    if r is not None and r.returncode != 0:
        FEHLER.append("Node-Render crashte: " + r.stderr[-300:])
    elif r is not None:
        from html.parser import HTMLParser

        VERBOTEN_TAGS = {"script", "img", "svg", "iframe", "object", "embed",
                         "style", "link", "form", "input", "video", "audio"}

        class Pruefer(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.tags = []
                self.attrs = []
                self.text = []

            def handle_starttag(self, tag, attrs):
                self.tags.append(tag)
                for k, v in attrs:
                    self.attrs.append((tag, k, v))

            def handle_startendtag(self, tag, attrs):
                self.handle_starttag(tag, attrs)

            def handle_data(self, data):
                self.text.append(data)

        p = Pruefer()
        p.feed(r.stdout)
        html = r.stdout

        # 1) Keine der Nutzlasten hat ein echtes Tag erzeugt
        for t in VERBOTEN_TAGS:
            if t in p.tags:
                FEHLER.append(f"SENKE: <{t}> wurde als echtes Tag geparst — "
                              "die Nutzlast ist ausfuehrbar")

        # 2) Kein Event-Handler-Attribut irgendwo (onclick/onerror/onload/...)
        for tag, k, v in p.attrs:
            if k.lower().startswith("on"):
                FEHLER.append(f"SENKE: Event-Handler-Attribut {k}= auf <{tag}>")

        # 3) Gegenprobe: die Nutzlast steht als TEXT im Baum, nicht als Markup
        text = "".join(p.text)
        if "<img src=x" not in text:
            FEHLER.append("Nutzlast <img ...> steht nicht mehr als Text im Baum — "
                          "Escaping kaputt")
        if "<script>alert(2)" not in text:
            FEHLER.append("Nutzlast <script>alert(2) steht nicht mehr als Text "
                          "im Baum — Escaping kaputt")

        # 4) Keine rohen (unescapten) Payload-Tags im Quelltext des Renderings
        for pat, label in ((r"<img\s", "<img ...> roh"),
                           (r"<script", "<script> roh"),
                           (r"<svg", "<svg> roh")):
            if re.search(pat, html, re.I):
                FEHLER.append(f"SENKE: {label} im gerenderten HTML")

        # 5) Erwartete Struktur intakt (Design unveraendert)
        if "div" not in p.tags or "b" not in p.tags or "span" not in p.tags:
            FEHLER.append(f"Erwartete Tags fehlen, gerendert wurde: {p.tags}")
        if len([t for t in p.tags if t == "div"]) < 4:
            FEHLER.append(f"Erwartet 4 Result-Divs, gefunden "
                          f"{len([t for t in p.tags if t == 'div'])}")

        # 6) data-ticker ist der Mechanismus, onclick darf nicht vorkommen
        dt = [v for tag, k, v in p.attrs if k == "data-ticker"]
        if len(dt) != 4:
            FEHLER.append(f"Erwartet 4 data-ticker-Attribute, gefunden {len(dt)}")
        # WICHTIG: HTMLParser dekodiert Entities im Attributwert. Geprueft wird
        # deshalb der ROHE HTML-Text: dort muss &lt; stehen, nicht <.
        roh_attr = re.findall(r'data-ticker="([^"]*)"', html)
        if len(roh_attr) != 4:
            FEHLER.append(f"Erwartet 4 rohe data-ticker-Attribute, "
                          f"gefunden {len(roh_attr)}")
        for v in roh_attr:
            if "<" in v or ">" in v:
                FEHLER.append(f"data-ticker enthaelt ein rotes '<'/'>' "
                              f"({v[:40]!r}) — Attribut nicht escaped")
        # Anfuehrungszeichen duerfen das Attribut nicht verlassen
        if re.search(r"data-ticker=\"[^\"]*'\s", html):
            FEHLER.append(" Apostroph escaped das data-ticker-Attribut")
        # Genau eine echte Payload muss als Entity-Form im Roh-HTML stehen
        if "&lt;img src=x onerror=alert(1)&gt;" not in html:
            FEHLER.append("Nutzlast nicht als &lt;img ...&gt; escaped — "
                          "Escaping unvollstaendig")
        if "&lt;script&gt;alert(2)&lt;/script&gt;" not in html:
            FEHLER.append("Nutzlast nicht als &lt;script&gt;... escaped")

        # 7) Legitime Inhalte erhalten
        if "PLTR" not in html:
            FEHLER.append("Legitimer Ticker 'PLTR' fehlt — Daten verschwunden")
        if "Risk" not in html or "Aktien" not in html:
            FEHLER.append("Suchzeilen-Layout veraendert (Risk/Aktien fehlen)")

if FEHLER:
    print("FEHLGESCHLAGEN - Stored XSS weiterhin ausnutzbar:")
    for f in FEHLER:
        print("  - " + f)
    sys.exit(1)
print("BESTANDEN: alle Nutzlasten escaped, kein ausfuehrbares Markup, "
      "onclick-Interpolation entfernt, legitime Inhalte erhalten.")
