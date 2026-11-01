#!/usr/bin/env python3
"""Erzeugt das gestaltete Handbuch-PDF aus docs/handbuch/HANDBUCH.md.

Aufruf:
    python3 tools/handbuch_pdf.py [--version v2.60.0] [--aus pfad.pdf] [--html seite.html]

Weg: Markdown -> HTML mit eigenem Design (docs/handbuch/handbuch.css)
-> Chromium druckt das PDF (Titelseite, Inhaltsverzeichnis, Kapitel,
Kästen, Grafiken, Seitenzahlen, PDF-Lesezeichen).

Benötigt das Paket ``markdown`` und einen Chromium/Chrome. Pfad über
CHROMIUM_PATH oder automatisch gesucht. Fehlt eins davon, entsteht ein
einfaches PDF über tools/handbuch_pdf_einfach.py (nur reportlab).

Markdown-Erweiterungen, die GitHub ebenfalls darstellt:
  > [!TIP] / [!NOTE] / [!IMPORTANT] / [!WARNING]   -> farbige Kästen
  <!-- grafik: ablauf | risikoleiter | kennzahlen --> -> Grafiken
                                                       (auf GitHub unsichtbar)
Kapitel sind die Überschriften ``## N. Titel``.
"""
import argparse
import base64
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime

HIER = os.path.dirname(os.path.abspath(__file__))
BASIS = os.path.dirname(HIER)
QUELLE = os.path.join(BASIS, "docs", "handbuch", "HANDBUCH.md")
CSS = os.path.join(BASIS, "docs", "handbuch", "handbuch.css")
ZIEL = os.path.join(BASIS, "docs", "handbuch", "Micro-Trader-Handbuch.pdf")
LOGO = os.path.join(BASIS, "assets", "logo.png")
REPO = "github.com/Goldi5/micro-trader-paper"
LEITER = [10, 25, 40, 55, 70, 85, 95]          # Aktien-Risikoleiter (Kapitel 2)
SCHRIFTEN = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
             "&family=Space+Grotesk:wght@500;700&family=JetBrains+Mono:wght@400&display=swap")
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]


def version_ermitteln():
    try:
        v = subprocess.run(["git", "-C", BASIS, "describe", "--tags", "--always"],
                           capture_output=True, text=True, timeout=10).stdout.strip()
        if v:
            return v
    except Exception:
        pass
    try:
        with open(os.path.join(BASIS, "version.json"), encoding="utf-8") as f:
            return "v" + json.load(f).get("version", "?")
    except Exception:
        return "unbekannt"


def _slug(text, n):
    t = re.sub(r"<[^>]+>", "", text).lower()
    return re.sub(r"[^a-z0-9äöüß]+", "-", t).strip("-") + "-%d" % n


# ── Schriften: einmal laden und einbetten (ohne Netz: Systemschriften) ──
def schriften_css(timeout=10):
    if os.environ.get("MT_HANDBUCH_OFFLINE"):
        return ""
    ua = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
    try:
        req = urllib.request.Request(SCHRIFTEN, headers=ua)
        css = urllib.request.urlopen(req, timeout=timeout).read().decode()
        bloecke = re.findall(r"/\* (latin(?:-ext)?) \*/\s*(@font-face \{.*?\})", css, re.S)
        out = []
        for _, block in bloecke:
            url = re.search(r"url\((https://[^)]+)\)", block).group(1)
            daten = urllib.request.urlopen(urllib.request.Request(url, headers=ua),
                                           timeout=timeout).read()
            b64 = base64.b64encode(daten).decode()
            out.append(block.replace(url, "data:font/woff2;base64," + b64))
        return "\n".join(out)
    except Exception as e:
        print("  (Schriften nicht geladen, nutze Systemschriften: %s)" % e, file=sys.stderr)
        return ""


def _bild_data(pfad):
    try:
        with open(pfad, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    except Exception:
        return ""


# ── Grafiken ──────────────────────────────────────────────────────────
def grafik_ablauf():
    schritte = [
        ("1", "Scheduler", ["alle 15 min", "KI-Welle je Trader"], "#20D9FF"),
        ("2", "Ausstiege", ["Stop-Loss, Trailing,", "Take-Profit zuerst"], "#20D9FF"),
        ("3", "KI-Vorschlag", ["ein Aufruf für", "alle Depots"], "#7B5CFF"),
        ("4", "Earnings", ["kein Kauf kurz", "vor Quartalszahlen"], "#7B5CFF"),
        ("5", "Risiko-Check", ["entscheidet:", "ja · kleiner · nein"], "#1FA97A"),
        ("6", "Ausführung", ["Paper, mit Gebühr", "und Slippage"], "#1FA97A"),
    ]
    w, gap, bw, bh = 680, 14, 102, 92
    teile = ['<svg viewBox="0 0 %d 178" xmlns="http://www.w3.org/2000/svg" font-family="Inter, Arial, sans-serif">' % w,
             '<defs><linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="#20D9FF"/>'
             '<stop offset="1" stop-color="#7B5CFF"/></linearGradient>'
             '<marker id="pf" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">'
             '<path d="M0 0 L10 5 L0 10 z" fill="#9AA3BC"/></marker></defs>']
    for i, (n, titel, zeilen, farbe) in enumerate(schritte):
        x = i * (bw + gap)
        teile.append('<rect x="%d" y="1" width="%d" height="%d" rx="12" fill="#F5F6FB" stroke="#E3E6EF"/>' % (x, bw, bh))
        teile.append('<rect x="%d" y="1" width="%d" height="5" rx="2.5" fill="%s"/>' % (x + 12, bw - 24, farbe))
        teile.append('<circle cx="%d" cy="30" r="11" fill="%s"/><text x="%d" y="34.5" text-anchor="middle" '
                     'font-size="12" font-weight="700" fill="#fff">%s</text>' % (x + 22, farbe, x + 22, n))
        teile.append('<text x="%d" y="62" font-size="12.5" font-weight="700" fill="#0B1220">%s</text>' % (x + 11, titel))
        for k, z in enumerate(zeilen):
            teile.append('<text x="%d" y="%d" font-size="9.4" fill="#5B6475">%s</text>' % (x + 11, 76 + k * 11.5, html.escape(z)))
        if i < len(schritte) - 1:
            teile.append('<line x1="%d" y1="47" x2="%d" y2="47" stroke="#9AA3BC" stroke-width="1.6" marker-end="url(#pf)"/>'
                         % (x + bw + 1, x + bw + gap - 1))
    # Ergebnisleiste
    teile.append('<path d="M%d %d v14 M%d %d v14" stroke="#C9CEDD" stroke-width="1.4" stroke-dasharray="3 3"/>'
                 % (bw // 2, bh + 2, w - bw // 2, bh + 2))
    teile.append('<rect x="0" y="%d" width="%d" height="58" rx="12" fill="#0B1220"/>' % (bh + 18, w))
    teile.append('<rect x="0" y="%d" width="5" height="58" rx="2" fill="url(#g)"/>' % (bh + 18))
    teile.append('<text x="20" y="%d" font-size="10" font-weight="700" fill="#20D9FF" letter-spacing="1.5">ERGEBNIS</text>' % (bh + 40))
    teile.append('<text x="20" y="%d" font-size="11.5" fill="#E4E8FF">Depot-Dateien · SQLite · Logs  →  '
                 '<tspan font-weight="700" fill="#fff">Tagesbericht (PDF) · Dashboard · ntfy-Alarme</tspan></text>' % (bh + 58))
    teile.append("</svg>")
    return ('<figure>%s<figcaption>Ein Handelslauf: Erst greifen die harten Ausstiege, dann macht die KI '
            'Vorschläge, und der Risiko-Controller hat das letzte Wort.</figcaption></figure>' % "".join(teile))


def grafik_risikoleiter():
    try:
        sys.path.insert(0, BASIS)
        import risk_controller as rc
        import risk_profile as rp
    except Exception as e:
        print("  (Risikoleiter übersprungen: %s)" % e, file=sys.stderr)
        return ""
    namen = getattr(rc, "TIER_NAMEN", {})
    zeilen = []
    max_dd = max(float(rc.params(r)["max_drawdown"]) for r in LEITER) or 1
    for r in LEITER:
        p = rc.params(r)
        sl = (1 - float(p["stop_loss"])) * 100
        tp = (float(p["take_profit"]) - 1) * 100
        dd = float(p["max_drawdown"])
        tiers = "".join('<span class="t%d">%s</span>' % (t, html.escape(namen.get(t, str(t))))
                        for t in rp.get_allowed_tiers(r))
        zeile = (
            ("<tr><td class='stufe'>%d</td><td>%d</td><td>%.1f %%</td><td>%.0f %%</td>"
             "<td class='neg'>−%.1f %%</td><td class='pos'>+%.0f %%</td>"
            "<td><div class='bwrap'><div class='balken' style='width:%.0f%%'></div></div>"
            "<span style='font-size:7pt;color:#5B6475'>%.0f %%</span></td><td class='tiers'>%s</td></tr>")
            % (r, p["max_positions"], float(p["position_size"]) * 100, float(p["cash_floor"]) * 100,
               sl, tp, dd / max_dd * 100, dd, tiers))
        zeilen.append(zeile.replace(".", ","))
    return ("<table class='leiter'><thead><tr><th>Risk</th><th>Pos.</th><th>Größe</th><th>Cash</th>"
            "<th>Stop</th><th>Ziel</th><th>Drawdown-Sperre</th><th>Erlaubte Tiers</th></tr></thead><tbody>%s"
            "</tbody></table><p style='font-size:8pt;color:#5B6475;margin-top:-3mm'>Werte direkt aus "
            "<code>risk_controller.params()</code> beim Bau dieses Handbuchs. Pos. = max. Positionen, "
            "Größe = Anteil je Position, Cash = Mindest-Bargeld.</p>" % "".join(zeilen))


def grafik_kennzahlen():
    try:
        with open(os.path.join(BASIS, "run_tests.sh"), encoding="utf-8") as f:
            m = re.search(r"OFFLINE=\((.*?)\)", f.read(), re.S)
        tests = len(re.findall(r"test_\w+\.py", m.group(1))) if m else 0
    except Exception:
        tests = 0
    k = [
        ("3", "", "Depotarten", "Aktien · ETF · Spekulation"),
        (str(len(LEITER)), "", "Risikostufen", "Aktien-Leiter Risk %d–%d" % (LEITER[0], LEITER[-1])),
        ("15 min", "", "Takt", "Scheduler, bei offener US-Börse"),
        ("0 €", "gruen", "echtes Geld", "PAPER_ONLY, echte Orders gesperrt"),
        ("1", "", "Tor für Käufe", "zentraler Risiko-Controller"),
        (str(tests) if tests else "✓", "", "Offline-Tests", "laufen vor jedem Neustart"),
    ]
    return "<div class='kacheln'>%s</div>" % "".join(
        "<div class='kachel'><div class='wert %s'>%s</div><div class='lbl'>%s</div><div class='sub'>%s</div></div>"
        % (c, html.escape(w), html.escape(l), html.escape(s)) for w, c, l, s in k)


GRAFIKEN = {"ablauf": grafik_ablauf, "risikoleiter": grafik_risikoleiter, "kennzahlen": grafik_kennzahlen}


def titelbild():
    """Dekoratives Kurs-Chart für die Titelseite (Kerzen + Puls-Linie)."""
    import random
    rnd = random.Random(7)
    w, h, n = 660, 250, 34
    kurs, kerzen = 120.0, []
    for i in range(n):
        auf = 0.6 + i * 0.05
        o = kurs
        c = max(30, o + rnd.uniform(-7, 7 + auf))
        hi, lo = max(o, c) + rnd.uniform(1, 6), min(o, c) - rnd.uniform(1, 6)
        kerzen.append((o, hi, lo, c))
        kurs = c
    alle = [v for k in kerzen for v in k]
    mn, mx = min(alle), max(alle)
    y = lambda v: h - 12 - (v - mn) / (mx - mn) * (h - 40)  # noqa: E731
    sw = w / n
    teile = ['<svg class="chart" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg">' % (w, h),
             '<defs><linearGradient id="tp" x1="0" x2="1"><stop offset="0" stop-color="#20D9FF"/>'
             '<stop offset="1" stop-color="#7B5CFF"/></linearGradient>'
             '<linearGradient id="tf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7B5CFF" stop-opacity=".35"/>'
             '<stop offset="1" stop-color="#7B5CFF" stop-opacity="0"/></linearGradient></defs>']
    for g in range(5):
        gy = 20 + g * (h - 30) / 4
        teile.append('<line x1="0" x2="%d" y1="%.1f" y2="%.1f" stroke="#fff" stroke-opacity=".06"/>' % (w, gy, gy))
    for i, (o, hi, lo, c) in enumerate(kerzen):
        cx = i * sw + sw / 2
        farbe = "#73E6B0" if c >= o else "#E04F5F"
        teile.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-opacity=".55"/>'
                     % (cx, cx, y(hi), y(lo), farbe))
        teile.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5" fill="%s" fill-opacity=".55"/>'
                     % (cx - sw * .3, y(max(o, c)), sw * .6, max(1.5, abs(y(o) - y(c))), farbe))
    pkt = " ".join("%.1f,%.1f" % (i * sw + sw / 2, y(c)) for i, (_, _, _, c) in enumerate(kerzen))
    teile.append('<polygon points="%.1f,%d %s %.1f,%d" fill="url(#tf)"/>' % (sw / 2, h, pkt, w - sw / 2, h))
    teile.append('<polyline points="%s" fill="none" stroke="url(#tp)" stroke-width="3.2" stroke-linejoin="round"/>' % pkt)
    lx, ly = (n - 1) * sw + sw / 2, y(kerzen[-1][3])
    teile.append('<circle cx="%.1f" cy="%.1f" r="9" fill="#7B5CFF" fill-opacity=".3"/>'
                 '<circle cx="%.1f" cy="%.1f" r="4.5" fill="#fff"/>' % (lx, ly, lx, ly))
    teile.append("</svg>")
    return "".join(teile)


# ── Markdown -> HTML ─────────────────────────────────────────────────
def _alert_kaesten(md):
    """> [!TIP] ... -> <div class="box tip"> (Markdown im Kasten bleibt aktiv)."""
    titel = {"tip": "Tipp", "note": "Hinweis", "important": "Wichtig", "warning": "Achtung", "caution": "Vorsicht"}
    out, zeilen, i = [], md.splitlines(), 0
    while i < len(zeilen):
        m = re.match(r"^>\s*\[!(TIP|NOTE|IMPORTANT|WARNING|CAUTION)\]\s*$", zeilen[i])
        if not m:
            out.append(zeilen[i])
            i += 1
            continue
        art = m.group(1).lower()
        inhalt = []
        i += 1
        while i < len(zeilen) and zeilen[i].startswith(">"):
            inhalt.append(re.sub(r"^>\s?", "", zeilen[i]))
            i += 1
        out += ["", '<div class="box %s" markdown="1">' % art, "",
                '<div class="box-titel">%s</div>' % titel[art], ""] + inhalt + ["", "</div>", ""]
    return "\n".join(out)


def vorbereiten(md):
    zeilen = md.splitlines()
    # Titel und Einleitungssatz stehen auf der Titelseite
    if zeilen and zeilen[0].startswith("# "):
        zeilen = zeilen[1:]
        while zeilen and not zeilen[0].startswith("## "):
            zeilen = zeilen[1:]
    neu = []
    for z in zeilen:
        m = re.match(r"^## (\d+)\.\s+(.*)$", z)
        if m:
            z = "# " + m.group(2)
        elif z.startswith("### "):
            z = "## " + z[4:]
        m = re.match(r"^( +)((?:-|\d+\.) .*)$", z)       # Unterlisten auf 4er-Einrückung
        if m:
            z = " " * (4 * max(1, round(len(m.group(1)) / 3))) + m.group(2)
        g = re.match(r"^<!--\s*grafik:\s*(\w+)\s*-->$", z.strip())
        if g and g.group(1) in GRAFIKEN:
            z = "\n" + GRAFIKEN[g.group(1)]() + "\n"
        neu.append(z)
    return _alert_kaesten("\n".join(neu))


def _code_faerben(html_text):
    def pre(m):
        zeilen = []
        for z in m.group(2).split("\n"):
            if re.match(r"^\s*#", z):
                z = '<span class="kommentar">%s</span>' % z
            else:
                z = re.sub(r"(\s{2,}#\s.*)$", r'<span class="kommentar">\1</span>', z)
            zeilen.append(z)
        return m.group(1) + "\n".join(zeilen) + "</code></pre>"
    return re.sub(r"(<pre><code[^>]*>)(.*?)</code></pre>", pre, html_text, flags=re.S)


def html_bauen(md_text, version, stand_datum=None, schriften=None):
    import markdown
    d = stand_datum or datetime.now()
    datum = "%d. %s %d" % (d.day, MONATE[d.month - 1], d.year)
    rumpf = markdown.markdown(vorbereiten(md_text),
                              extensions=["tables", "fenced_code", "md_in_html", "sane_lists"])
    rumpf = _code_faerben(rumpf)

    kapitel, n = [], 0

    def ueberschrift(m):
        nonlocal n
        lvl, text = int(m.group(1)), m.group(2)
        anker = _slug(text, len(kapitel) * 100 + n)
        n += 1
        if lvl == 1:
            kapitel.append({"text": text, "id": anker, "unter": []})
            return '<h1 id="%s"><span class="num">%02d</span>%s</h1>' % (anker, len(kapitel), text)
        if kapitel:
            kapitel[-1]["unter"].append(re.sub(r"<[^>]+>", "", text))
        return '<h2 id="%s">%s</h2>' % (anker, text)
    rumpf = re.sub(r"<h([12])>(.*?)</h\1>", ueberschrift, rumpf)
    # erster Absatz eines Kapitels als Einleitung hervorheben
    rumpf = re.sub(r"(</h1>\s*)<p>", r'\1<p class="lead">', rumpf)
    # Überschrift nie allein am Seitenende: mit dem ersten Block zusammenhalten
    rumpf = re.sub(r"(<h[12] [^>]*>.*?</h[12]>\s*(?:<h2 [^>]*>.*?</h2>\s*)?"
                   r"(?:<p[ >].*?</p>|<figure>.*?</figure>|<table>.*?</table>|<pre>.*?</pre>))",
                   r'<div class="zusammen">\1</div>', rumpf, flags=re.S)

    toc = "".join(
        '<li class="c"><span class="n">%d</span><a href="#%s"><span class="t">%s</span>%s</a></li>'
        % (i + 1, k["id"], k["text"],
           '<span class="s">%s</span>' % html.escape(" · ".join(k["unter"])) if k["unter"] else "")
        for i, k in enumerate(kapitel))

    with open(CSS, encoding="utf-8") as f:
        css = f.read()
    css = css.replace('content: "Micro-Trader · Handbuch";',
                      'content: "Micro-Trader · Handbuch %s · Stand %s";'
                      % (version.replace('"', ""), d.strftime("%d.%m.%Y")))
    schrift = schriften_css() if schriften is None else schriften
    logo = _bild_data(LOGO)
    logo_html = '<img class="logo" src="%s" alt="">' % logo if logo else ""

    return """<!doctype html><html lang="de"><head><meta charset="utf-8">
<title>Micro-Trader – Handbuch %(v)s</title>
<meta name="author" content="Micro-Trader"><meta name="subject" content="Handbuch">
<style>%(schrift)s
%(css)s</style></head><body>
<section class="cover">
  <div class="oben">%(logo)s<div class="kicker">Paper-Trading · KI · Risikomanagement</div></div>
  <h1 class="title">Micro-<span>Trader</span></h1>
  <div class="subtitle">Handbuch – <b>Die KI schlägt vor,</b> deterministische Regeln entscheiden.</div>
  <div class="pills"><span class="pill gruen">● Nur Paper-Trading</span><span class="pill">Version %(v)s</span>
    <span class="pill">Open Source · AGPL-3.0</span></div>
  %(chart)s
  <div class="meta"><div><b>Handbuch</b><br>Funktionen · Bedienung · Betrieb</div>
    <div style="text-align:right">Stand %(datum)s<br>%(repo)s</div></div>
</section>
<section class="toc"><div class="kopf"><h2>Inhalt</h2><span>%(anz)d Kapitel</span></div>
<div class="bar"></div><ol>%(toc)s</ol></section>
<main>%(rumpf)s
<div class="ende"><b>Keine Anlageberatung.</b> Micro-Trader ist ein Lern- und Experimentierprojekt mit
virtuellem Geld, ohne Gewährleistung. Details in <code>RECHTLICHES.md</code>.<br>
Dieses Handbuch wird bei jedem Release automatisch aus <code>docs/handbuch/HANDBUCH.md</code> erzeugt.</div>
</main></body></html>""" % {
        "v": html.escape(version), "schrift": schrift, "css": css, "logo": logo_html,
        "chart": titelbild(), "datum": datum, "repo": REPO, "anz": len(kapitel),
        "toc": toc, "rumpf": rumpf}


# ── Drucken ──────────────────────────────────────────────────────────
def chromium_finden():
    pfad = os.environ.get("CHROMIUM_PATH")
    if pfad and os.path.exists(pfad):
        return pfad
    shell = sorted(glob.glob("/opt/pw-browsers/chromium_headless_shell-*/*/chrome-headless-shell") +
                   glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell")))
    if shell:
        return shell[-1]
    for name in ("chrome-headless-shell", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    treffer = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome") +
                     glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")))
    return treffer[-1] if treffer else None


def drucken(html_text, aus, chrome):
    with tempfile.TemporaryDirectory() as tmp:
        seite = os.path.join(tmp, "handbuch.html")
        with open(seite, "w", encoding="utf-8") as f:
            f.write(html_text)
        cmd = [chrome, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
               "--disable-background-networking", "--disable-component-update", "--no-first-run",
               "--disable-sync", "--disable-default-apps", "--mute-audio",
               "--no-pdf-header-footer", "--generate-pdf-document-outline",
               "--user-data-dir=" + os.path.join(tmp, "profil"),
               "--print-to-pdf=" + os.path.abspath(aus),
               "file://" + seite]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if not os.path.exists(aus) or os.path.getsize(aus) < 1000:
            raise RuntimeError("Chromium hat kein PDF erzeugt: %s" % (r.stderr.strip()[-400:]))


def erzeuge(version=None, aus=None, quelle=QUELLE, html_aus=None, einfach=False):
    version = version or version_ermitteln()
    aus = aus or ZIEL
    chrome = None if einfach else chromium_finden()
    try:
        import markdown  # noqa: F401
    except ImportError:
        chrome = None
    if not chrome:
        if not einfach:
            print("  (kein Chromium oder Paket 'markdown' - erzeuge einfaches PDF)", file=sys.stderr)
        import handbuch_pdf_einfach
        return handbuch_pdf_einfach.erzeuge(version, aus, quelle)
    with open(quelle, encoding="utf-8") as f:
        seite = html_bauen(f.read(), version)
    if html_aus:
        with open(html_aus, "w", encoding="utf-8") as f:
            f.write(seite)
    try:
        drucken(seite, aus, chrome)
    except Exception as e:
        print("  (Chromium-Druck fehlgeschlagen: %s - erzeuge einfaches PDF)" % e, file=sys.stderr)
        import handbuch_pdf_einfach
        return handbuch_pdf_einfach.erzeuge(version, aus, quelle)
    return aus


if __name__ == "__main__":
    sys.path.insert(0, HIER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--version")
    ap.add_argument("--aus")
    ap.add_argument("--html", help="HTML zusätzlich speichern (zum Prüfen)")
    ap.add_argument("--einfach", action="store_true", help="einfaches PDF ohne Chromium")
    a = ap.parse_args()
    print(erzeuge(a.version, a.aus, html_aus=a.html, einfach=a.einfach))
