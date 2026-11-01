#!/usr/bin/env python3
"""Erzeugt das Handbuch-PDF aus docs/handbuch/HANDBUCH.md (01.11.2026).

Aufruf:
    python3 tools/handbuch_pdf.py [--version v2.60.0] [--aus pfad.pdf]

Ohne --version wird `git describe --tags --always` verwendet, sonst
version.json. Unterstuetzt die Markdown-Teilmenge, die das Handbuch nutzt:
Ueberschriften (#, ##, ###), Absaetze, Aufzaehlungen (-, 1.), eingerueckte
Unterpunkte, Tabellen (| a | b |), Codebloecke (```), **fett**, `code`.
Nur reportlab wird benoetigt (steht in requirements.txt).
"""
import argparse
import html
import json
import os
import re
import subprocess
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (ListFlowable, ListItem, PageBreak, Paragraph,
                                Preformatted, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

HIER = os.path.dirname(os.path.abspath(__file__))
BASIS = os.path.dirname(HIER)
QUELLE = os.path.join(BASIS, "docs", "handbuch", "HANDBUCH.md")
ZIEL = os.path.join(BASIS, "docs", "handbuch", "Micro-Trader-Handbuch.pdf")
VIOLETT = colors.HexColor("#5E4BD8")


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


def inline(text):
    """**fett** und `code` nach reportlab-Markup; alles andere escapen."""
    teile = re.split(r"(`[^`]+`)", text)
    out = []
    for t in teile:
        if t.startswith("`") and t.endswith("`") and len(t) > 1:
            out.append('<font face="Courier" size="8.5">%s</font>' % html.escape(t[1:-1]))
        else:
            e = html.escape(t)
            e = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e)
            out.append(e)
    return "".join(out)


def stile():
    ss = getSampleStyleSheet()
    s = {
        "titel": ParagraphStyle("titel", parent=ss["Title"], textColor=VIOLETT, fontSize=26, spaceAfter=12),
        "h1": ParagraphStyle("h1", parent=ss["Heading1"], textColor=VIOLETT, fontSize=17, spaceBefore=6),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], textColor=VIOLETT, fontSize=13.5, spaceBefore=10),
        "h3": ParagraphStyle("h3", parent=ss["Heading3"], fontSize=11.5, spaceBefore=8),
        "body": ParagraphStyle("body", parent=ss["BodyText"], fontSize=9.5, leading=13, alignment=TA_LEFT),
        "zelle": ParagraphStyle("zelle", parent=ss["BodyText"], fontSize=8.3, leading=10.5),
        "code": ParagraphStyle("code", parent=ss["Code"], fontSize=8.3, leading=10.5,
                               backColor=colors.HexColor("#F3F2FA"), borderPadding=5,
                               leftIndent=4, rightIndent=4),
        "klein": ParagraphStyle("klein", parent=ss["BodyText"], fontSize=8, textColor=colors.grey),
    }
    return s


def tabelle(zeilen, S, breite):
    daten = [[Paragraph(inline(z), S["zelle"]) for z in r] for r in zeilen]
    n = max(len(r) for r in daten)
    daten = [r + [""] * (n - len(r)) for r in daten]
    t = Table(daten, colWidths=[breite / n] * n, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VIOLETT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDE8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7FB")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def liste(eintraege, S, nummeriert):
    items = []
    for e in eintraege:
        text, unter = e[0], e[1]
        inhalt = [Paragraph(inline(text), S["body"])]
        if unter:
            inhalt.append(liste(unter, S, unter[0][2] if len(unter[0]) > 2 else False))
        items.append(ListItem(inhalt, leftIndent=12))
    return ListFlowable(items, bulletType="1" if nummeriert else "bullet",
                        start="1" if nummeriert else None, leftIndent=14,
                        bulletFontSize=8 if not nummeriert else 9)


def parse(md, S, breite):
    el = []
    zeilen = md.splitlines()
    i = 0
    erste_h1 = True
    while i < len(zeilen):
        z = zeilen[i]
        if z.startswith("```"):
            block = []
            i += 1
            while i < len(zeilen) and not zeilen[i].startswith("```"):
                block.append(zeilen[i])
                i += 1
            el.append(Preformatted("\n".join(block), S["code"]))
            el.append(Spacer(1, 4))
            i += 1
            continue
        if z.startswith("# "):
            if not erste_h1:
                el.append(PageBreak())
            erste_h1 = False
            el.append(Paragraph(inline(z[2:]), S["titel"]))
        elif z.startswith("## "):
            el.append(Paragraph(inline(z[3:]), S["h2"]))
        elif z.startswith("### "):
            el.append(Paragraph(inline(z[4:]), S["h3"]))
        elif z.startswith("|"):
            tab = []
            while i < len(zeilen) and zeilen[i].startswith("|"):
                zellen = [c.strip() for c in zeilen[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in zellen):
                    tab.append(zellen)
                i += 1
            el.append(tabelle(tab, S, breite))
            el.append(Spacer(1, 6))
            continue
        elif re.match(r"^(\d+\.|-) ", z):
            eintraege = []
            nummeriert = bool(re.match(r"^\d+\.", z))
            while i < len(zeilen) and (re.match(r"^(\d+\.|-) ", zeilen[i]) or
                                       re.match(r"^\s{2,}(\d+\.|-) ", zeilen[i])):
                if re.match(r"^\s{2,}", zeilen[i]):
                    m = re.match(r"^\s+(\d+\.|-) (.*)", zeilen[i])
                    if eintraege:
                        eintraege[-1][1].append((m.group(2), [], m.group(1)[0].isdigit()))
                else:
                    eintraege.append([re.sub(r"^(\d+\.|-) ", "", zeilen[i]), []])
                i += 1
            el.append(liste([(t, u) for t, u in eintraege], S, nummeriert))
            el.append(Spacer(1, 4))
            continue
        elif z.strip():
            absatz = [z.strip()]
            i += 1
            while i < len(zeilen) and zeilen[i].strip() and not re.match(
                    r"^(#|\||```|\d+\. |- )", zeilen[i]):
                absatz.append(zeilen[i].strip())
                i += 1
            el.append(Paragraph(inline(" ".join(absatz)), S["body"]))
            el.append(Spacer(1, 3))
            continue
        i += 1
    return el


def erzeuge(version=None, aus=None, quelle=QUELLE):
    version = version or version_ermitteln()
    aus = aus or ZIEL
    with open(quelle, encoding="utf-8") as f:
        md = f.read()
    S = stile()
    stand = datetime.now().strftime("%d.%m.%Y")

    def fusszeile(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(2 * cm, 1.2 * cm, "Micro-Trader Handbuch · %s · Stand %s" % (version, stand))
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, "Seite %d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(aus, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.8 * cm, bottomMargin=2 * cm,
                            title="Micro-Trader Handbuch %s" % version, author="Micro-Trader")
    breite = A4[0] - 4 * cm
    el = parse(md, S, breite)
    el.insert(1, Paragraph("Version %s · Stand %s" % (html.escape(version), stand), S["klein"]))
    el.insert(2, Spacer(1, 8))
    doc.build(el, onFirstPage=fusszeile, onLaterPages=fusszeile)
    return aus


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--version")
    ap.add_argument("--aus")
    a = ap.parse_args()
    print(erzeuge(a.version, a.aus))
