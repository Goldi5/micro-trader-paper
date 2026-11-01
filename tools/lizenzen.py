#!/usr/bin/env python3
"""Erzeugt THIRD_PARTY_LICENSES.md aus requirements.txt und den Paket-Metadaten.

Aufruf (im venv, in dem requirements.txt installiert ist):
    venv/bin/python tools/lizenzen.py
"""
import os
import re
from importlib import metadata

BASIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Pakete ohne Lizenzangabe in den Metadaten (von der Projektseite geprueft)
BEKANNT = {"peewee": "MIT"}


def lizenz(dist):
    m = dist.metadata
    if (m.get("Name") or "").lower() in BEKANNT:
        return BEKANNT[m["Name"].lower()]
    expr = m.get("License-Expression")
    if expr:
        return expr.strip()
    klass = [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or [])
             if c.startswith("License ::") and "OSI Approved" not in c.split("::")[-1]]
    if klass:
        return ", ".join(sorted(set(klass)))
    lic = (m.get("License") or "").strip()
    if lic and len(lic) < 60 and "\n" not in lic:
        return lic
    if lic:
        return lic.splitlines()[0][:60] + " …"
    return "unbekannt"


def main():
    zeilen = []
    with open(os.path.join(BASIS, "requirements.txt"), encoding="utf-8") as f:
        for z in f:
            z = z.strip()
            if not z or z.startswith("#"):
                continue
            name, _, version = z.partition("==")
            try:
                d = metadata.distribution(name)
                zeilen.append((d.metadata["Name"], version or d.version, lizenz(d),
                               d.metadata.get("Home-page") or
                               next((u.split(",", 1)[1].strip() for u in (d.metadata.get_all("Project-URL") or [])
                                     if re.match(r"(?i)(home|source|repository)", u)), "")))
            except metadata.PackageNotFoundError:
                zeilen.append((name, version, "nicht installiert – bitte pruefen", ""))
    zeilen.sort(key=lambda r: r[0].lower())
    out = ["# Lizenzen verwendeter Software (Third-Party Notices)", "",
           "Micro-Trader nutzt die folgenden Python-Pakete (Versionen aus `requirements.txt`).",
           "Sie werden **nicht** mit diesem Repository verteilt, sondern bei der Installation aus PyPI geladen;",
           "es gelten jeweils deren eigene Lizenzen.",
           "",
           "Erzeugt mit `tools/lizenzen.py`.",
           "",
           "| Paket | Version | Lizenz | Projekt |", "|---|---|---|---|"]
    for n, v, l, u in zeilen:
        out.append("| %s | %s | %s | %s |" % (n, v, l.replace("|", "/"), u))
    out += ["", "Weitere Komponenten:", "",
            "- **Node.js** (Proxy `proxy/proxy-server.mjs`): nur Node-Standardmodule, keine npm-Abhaengigkeiten. Node.js: MIT.",
            "- **Python** selbst: PSF License.", ""]
    with open(os.path.join(BASIS, "THIRD_PARTY_LICENSES.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("%d Pakete -> THIRD_PARTY_LICENSES.md" % len(zeilen))


if __name__ == "__main__":
    main()
