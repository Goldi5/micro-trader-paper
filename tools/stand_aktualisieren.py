#!/usr/bin/env python3
"""Schreibt den Block "Letzter Stand" in die README (zwischen den Markierungen
<!-- STAND:START --> und <!-- STAND:END -->): Version, Datum, letzte Aenderungen.

Laeuft automatisch per GitHub-Action bei jedem Push auf main; lokal:
    python3 tools/stand_aktualisieren.py
"""
import json
import os
import re
import subprocess

BASIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(BASIS, "README.md")
START, ENDE = "<!-- STAND:START -->", "<!-- STAND:END -->"


def git(*args):
    return subprocess.run(["git", "-C", BASIS] + list(args), capture_output=True,
                          text=True, timeout=20).stdout.strip()


def version():
    tag = git("describe", "--tags", "--abbrev=0")
    if tag:
        return tag
    try:
        with open(os.path.join(BASIS, "version.json"), encoding="utf-8") as f:
            return "v" + json.load(f).get("version", "?")
    except Exception:
        return "?"


def block():
    datum = git("log", "-1", "--format=%cd", "--date=format:%d.%m.%Y %H:%M")
    commit = git("log", "-1", "--format=%h")
    # Nur die erste Zeile je Commit, ohne Merge- und Stand-Commits
    zeilen = git("log", "-40", "--no-merges", "--format=%cd|%s", "--date=format:%d.%m.%Y").splitlines()
    aenderungen = []
    for z in zeilen:
        d, _, s = z.partition("|")
        if "[skip ci]" in s or s.lower().startswith(("wip", "stand:")):
            continue
        aenderungen.append("- %s – %s" % (d, s))
        if len(aenderungen) == 8:
            break
    return "\n".join([
        START,
        "## Letzter Stand",
        "",
        "| Version | Stand | Commit |",
        "|---|---|---|",
        "| %s | %s | `%s` |" % (version(), datum, commit),
        "",
        "Letzte Änderungen:",
        "",
        *aenderungen,
        "",
        "_Dieser Abschnitt wird bei jedem Update automatisch erzeugt (`tools/stand_aktualisieren.py`)._",
        ENDE,
    ])


def main():
    with open(README, encoding="utf-8") as f:
        text = f.read()
    neu = block()
    if START in text and ENDE in text:
        text = re.sub(re.escape(START) + r".*?" + re.escape(ENDE), lambda m: neu, text, flags=re.S)
    else:
        text = text.rstrip() + "\n\n" + neu + "\n"
    with open(README, "w", encoding="utf-8") as f:
        f.write(text)
    print("README: Stand aktualisiert")


if __name__ == "__main__":
    main()
