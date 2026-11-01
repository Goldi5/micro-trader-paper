#!/usr/bin/env python3
"""Skill-Sync: übernimmt die stärksten KI-Regeln aus ki_regeln.json
in den Hermes-Skill 'ki-trading-learning-loop' (references/aktuelle-ki-regeln.md).

Damit sieht der Nutzer im Skill, was die KI gelernt hat und wie künftige
Entscheidungen besser werden. Wird von der Cron-Pipeline aufgerufen.

Aufruf:  python skill_sync.py [--quiet]
"""
import os, sys, json, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
SKILL_REF = os.path.expanduser(
    "~/AppData/Local/hermes/skills/ki-trading-learning-loop/references/aktuelle-ki-regeln.md")
MAX_REGELN = 15  # Top-N Regeln in den Skill übernehmen (aktiv + nicht veraltet)


def lade_regeln():
    """Phase 0: lädt aus learned_rules.json (Source of Truth)."""
    try:
        from learned_rules import lade_regeln as _lr
        regeln = _lr(include_decay=True)
        # Mapping für markdown(): gewicht = effektiv_gewicht
        for r in regeln:
            r["gewicht"] = r.get("effektiv_gewicht", r.get("gewicht", 0))
        return regeln
    except Exception:
        pass
    pfad = os.path.join(BASE, "ki_regeln.json")
    if not os.path.exists(pfad):
        return []
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


# ── Block 5: Exportfreigabe-Hilfsfunktionen ──────────────────────────────

# Mindestschwellen für den Skill-Export (Block 5)
# MIN_SUPPORT_COUNT: freigegebene OOS-Regeln haben i.d.R. support_count=10
#   (kleine aber verlässliche Basis) -> Schwelle auf 10 gesetzt, damit die
#   echten freigegebenen Regeln durchkommen (statt Fallback auf alles).
MIN_SUPPORT_COUNT = 10      # ausreichende Evidenzbasis
MIN_EFFEKTIV_GEWICHT = 0.0  # nur positiv gewichtete Regeln (AUSNAHME: [Anti]/anti)
MAX_EXPORT_REGELN = 25      # Begrenzung der Skill-Regelmasse

EXPORT_KRITERIEN = [
    "freigabe_status == 'freigegeben'",
    "shadow == False",
    "archiviert == False (Feld, falls vorhanden)",
    "oos_confirmed == True",
    f"support_count >= {MIN_SUPPORT_COUNT}",
    f"effektiv_gewicht > {MIN_EFFEKTIV_GEWICHT}",
    "keine unauflösbare Konflikte (konfliktgruppe bereinigt)",
]


def _regel_exportierbar(r):
    """Block 5: Grundfilter — darf diese Regel in den Skill?

    Strenge Kriterien:
    - freigegeben (nicht shadow, nicht nicht_freigegeben)
    - nicht archiviert (Feld, falls vorhanden)
    - OOS-bestätigt
    - ausreichende Evidenz (support_count)
    - positiv gewichtet (effektiv_gewicht > 0)
    """
    if str(r.get("freigabe_status", "")) != "freigegeben":
        return False
    if r.get("shadow"):
        return False
    if r.get("archiviert"):
        return False
    if not r.get("oos_confirmed"):
        return False
    if int(r.get("support_count", 0) or 0) < MIN_SUPPORT_COUNT:
        return False
    ew = float(r.get("effektiv_gewicht", 0) or 0)
    # Positiv gewichtete Regeln: ew > 0 (Handlungs-Regeln)
    # [Anti]-Regeln (typ=anti / [Anti]-Präfix): bewusst negativ gewichtet
    #   (Verbote) -> als freigegebene OOS-Regeln erlaubt.
    ist_anti = str(r.get("typ", "")).lower() == "anti" or str(
        r.get("muster", "")).startswith("[Anti]")
    if not ist_anti and ew <= MIN_EFFEKTIV_GEWICHT:
        return False
    return True


def konfliktbereinigung(regeln):
    """Block 5: Bei gleichem Muster / gleicher Konfliktgruppe nur die
    stärkste freigegebene Regel behalten.

    - gleiches `muster` oder gleiche `konfliktgruppe` -> Duplikat-Konflikt
    - behalte Regel mit höchstem effektiv_gewicht
    - bei Gleichstand: zuerst die mit höherem support_count
    """
    beste = {}
    for r in regeln:
        # Konflikt-Schlüssel: explizite Gruppe, sonst Muster
        key = r.get("konfliktgruppe") or r.get("muster") or r.get("regel") or id(r)
        gw = float(r.get("effektiv_gewicht", 0) or 0)
        sc = int(r.get("support_count", 0) or 0)
        if key not in beste:
            beste[key] = r
            continue
        alt = beste[key]
        agw = float(alt.get("effektiv_gewicht", 0) or 0)
        asc = int(alt.get("support_count", 0) or 0)
        # höheres Gewicht gewinnt; bei Gleichstand mehr Support
        if gw > agw or (gw == agw and sc > asc):
            beste[key] = r
    return list(beste.values())


def exportierbare_regeln(regeln):
    """Block 5: Vollständiger Export-Pipeline.

    1. Grundfilter (_regel_exportierbar)
    2. Konfliktbereinigung
    3. Sortierung nach effektiv_gewicht absteigend
    4. Begrenzung auf MAX_EXPORT_REGELN (Top-N)

    Fallback: wenn nach strengem Filter zu wenig da ist (< 3),
    wird auf die lockere freigegeben+oos-Filterung zurückgefallen,
    damit der Skill eine kleine saubere Basis bekommt statt leer zu bleiben.
    """
    streng = [r for r in regeln if _regel_exportierbar(r)]
    bereinigt = konfliktbereinigung(streng)
    if len(bereinigt) < 3:
        # Fallback: freigegeben + OOS, ohne harte support/gewicht-Grenze
        locker = [r for r in regeln
                  if str(r.get("freigabe_status", "")) == "freigegeben"
                  and not r.get("shadow")
                  and r.get("oos_confirmed")]
        bereinigt = konfliktbereinigung(locker)
    sortiert = sorted(bereinigt,
                      key=lambda r: float(r.get("effektiv_gewicht", 0) or 0),
                      reverse=True)
    return sortiert[:MAX_EXPORT_REGELN]


def _ist_aktiv(r):
    """Alias auf Exportierbarkeit (Backward-Compat für alte Aufrufe)."""
    return _regel_exportierbar(r)


def regeln_nach_gewicht(regeln):
    """Alias auf exportierbare_regeln() (Block 5 Export-Pipeline).
    Behält die alte Signatur bei, nutzt aber jetzt den strengen
    Exportfilter + Konfliktbereinigung."""
    return exportierbare_regeln(regeln)


def export_metadaten(regeln_alle, regeln_exportiert):
    """Block 5: Metadaten-Objekt für den Export-Stand.

    Enthält: regelstand_version, zeitpunkt, anzahl, kriterien,
    freigabe-status, shadow-ausschluss, konfliktbereinigung.
    """
    jetzt = datetime.datetime.now()
    return {
        "regelstand_version": jetzt.strftime("%Y-%m-%d_%H%M"),
        "export_zeitpunkt": jetzt.strftime("%d.%m.%Y %H:%M"),
        "anzahl_exportiert": len(regeln_exportiert),
        "anzahl_verfuegbar": len(regeln_alle),
        "filter_kriterien": EXPORT_KRITERIEN,
        "freigabe_basis": "nur freigegebene Regeln (freigabe_status=freigegeben)",
        "shadow_ausgeschlossen": True,
        "archiviert_ausgeschlossen": True,
        "konfliktbereinigt": True,
        "modell": "effektiv_gewicht-absteigend, Top-N",
    }


def markdown(regeln, gesamt=None):
    """Baut die Markdown-Referenz für den Skill — 3 Sektionen:
    1. ⭐ Bestätigte Regeln (Top-N nach Gewicht, aktiv + nicht veraltet)
    2. ⚠ Widerlegte Muster / Gegen-Regeln ([Anti]-Präfix)
    3. 📊 Status-Kennzahlen (Trefferquote, Ø-Lerneffekt, Sektor-Bilanz)
    """
    jetzt = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    if not regeln:
        return (f"# Aktuelle KI-Regeln\n\n_Keine Regeln vorhanden (Stand {jetzt})._\n"
                "Die KI hat noch keine bestätigten Muster gelernt.\n")

    positiv = [r for r in regeln if not str(r.get("muster", "")).startswith("[Anti]")]
    anti = [r for r in regeln if str(r.get("muster", "")).startswith("[Anti]")]

    meta = export_metadaten(lade_regeln(), regeln)
    zeilen = [f"# Aktuelle KI-Regeln (Stand {jetzt})",
              "",
              f"**📌 Export-Stand:** `{meta['regelstand_version']}` · "
              f"{meta['anzahl_exportiert']} Regeln exportiert "
              f"(von {meta['anzahl_verfuegbar']} verfügbar)",
              "",
              "_Basis: **nur freigegebene, nicht-shadow, nicht-archivierte, "
              "OOS-bestätigte Regeln** (Block 5). Shadow-/Archivregeln sind "
              "ausgeschlossen. Konflikte wurden vor Export bereinigt._",
              "",
              f"Die {len(regeln)} stärksten Regeln aus der KI-Lern-Bewertung "
              "(`learned_rules.json`), automatisch per Cron synchronisiert:",
              ""]

    # ── Phase 6 (S3.7): Komprimierte Zusammenfassung (3-5 Sätze) ──
    top5 = (positiv + anti)[:5]
    if top5:
        zeilen.append("## 📋 Kurzfassung (Top-5)")
        zeilen.append("")
        for r in top5:
            typ_wort = "Verbot" if str(r.get("muster", "")).startswith("[Anti]") else "Regel"
            zeilen.append(f"- **{typ_wort}:** {r.get('regel','')[:90]}")
        zeilen.append("")

    # Sektion 1: bestätigte Regeln
    zeilen.append("## ⭐ Bestätigte Regeln (Handlungs-Regeln)")
    zeilen.append("")
    if positiv:
        for i, r in enumerate(positiv[:5], 1):
            gewicht = float(r.get("gewicht", 0) or 0)
            sterne = "⭐" * min(5, max(1, round(gewicht)))
            zeilen.append(f"### {i}. {sterne} Gewicht {gewicht:g}")
            zeilen.append("")
            zeilen.append(f"- **Muster:** {r.get('muster', '?')}")
            zeilen.append(f"- **Regel:** {r.get('regel', '?')}")
            zeit = str(r.get("updated_at") or r.get("created_at") or r.get("zeit", ""))[:16].replace("T", " ")
            zeilen.append(f"- **Gelernt:** {zeit}")
            zeilen.append("")
    else:
        zeilen.append("_Noch keine bestätigten Regeln._")
        zeilen.append("")

    # Sektion 2: widerlegte Muster (Anti-Regeln) — das Wichtigste für die Zukunft
    zeilen.append("## ⚠ Widerlegte Muster (was die KI NICHT tun soll)")
    zeilen.append("")
    if anti:
        zeilen.append("_Systematisch widerlegte Muster — gelten als Verbote und "
                      "werden mit hohem Gewicht in die KI-Prompts gegeben:_")
        zeilen.append("")
        for i, r in enumerate(anti[:5], 1):
            gewicht = float(r.get("gewicht", 0) or 0)
            zeilen.append(f"### {i}. ⛔ Gewicht {gewicht:g}")
            zeilen.append("")
            zeilen.append(f"- **Muster:** {r.get('muster', '?')}")
            zeilen.append(f"- **Regel:** {r.get('regel', '?')}")
            zeit = str(r.get("updated_at") or r.get("created_at") or r.get("zeit", ""))[:16].replace("T", " ")
            zeilen.append(f"- **Gelernt:** {zeit}")
            zeilen.append("")
    else:
        zeilen.append("_Noch keine widerlegten Muster._")
        zeilen.append("")

    # Sektion 3: Status-Kennzahlen
    zeilen.append("## 📊 Status der Lern-Schleife")
    zeilen.append("")
    zeilen.append(_status_block())
    # Hinweis: weitere Regeln existieren
    gesamt = gesamt if gesamt is not None else len(regeln)
    if gesamt > MAX_REGELN:
        zeilen.append("---")
        zeilen.append(f"_Hinweis: Es gibt insgesamt {gesamt} aktive Regeln in "
                      f"`learned_rules.json`. Hier sind die {MAX_REGELN} aktuell "
                      f"stärksten/aktivsten Regeln. Die vollständige Liste liegt in "
                      f"`learned_rules.json` (Source of Truth)._")
    zeilen.append("---")
    zeilen.append("_Diese Datei wird automatisch bei jedem Cron-Lauf aktualisiert "
                  "(`skill_sync.py` in der Pipeline). Manuelle Änderungen gehen beim "
                  "nächsten Sync verloren._")
    return "\n".join(zeilen)


def _status_block():
    """Trefferquote, Ø-Lerneffekt + Sektor-Bilanz aus ki_log.json (7 Tage)."""
    pfad = os.path.join(BASE, "ki_log.json")
    try:
        with open(pfad, encoding="utf-8") as f:
            log = json.load(f)
    except Exception:
        return "_Kein ki_log.json verfügbar._"

    cutoff = datetime.datetime.now() - datetime.timedelta(hours=168)
    werte, sektoren = [], {}
    for e in log:
        if e.get("typ") != "learned":
            continue
        le = e.get("lerneffekt")
        if not isinstance(le, (int, float)):
            continue
        try:
            z = datetime.datetime.fromisoformat(e.get("zeit", ""))
            if z < cutoff:
                continue
        except Exception:
            continue
        werte.append(le)
        sektor = e.get("sektor") or ""
        if sektor:
            sektoren.setdefault(sektor, []).append(le)

    if not werte:
        return "_In den letzten 7 Tagen keine bewerteten Lerneffekte._"

    pos = sum(1 for w in werte if w >= 1)
    neg = sum(1 for w in werte if w <= -1)
    quote = pos / len(werte) * 100 if werte else 0
    avg = sum(werte) / len(werte)

    zeilen = [f"- **Bewertete Lerneffekte (7 Tage):** {len(werte)}",
              f"- **Bestätigt:** {pos} · **Widerlegt:** {neg}",
              f"- **Trefferquote:** {quote:.0f}%",
              f"- **Ø-Lerneffekt:** {avg:+.2f} (Skala −5…+5)"]

    if sektoren:
        zeilen.append("")
        zeilen.append("**Sektor-Bilanz (Ø-Lerneffekt):**")
        sortiert = sorted(sektoren.items(), key=lambda kv: sum(kv[1]) / len(kv[1]), reverse=True)
        for sektor, ws in sortiert[:3]:
            zeilen.append(f"- 🟢 {sektor}: {sum(ws)/len(ws):+.2f} (n={len(ws)})")
        for sektor, ws in sortiert[-2:]:
            if sum(ws) / len(ws) < 0:
                zeilen.append(f"- 🔴 {sektor}: {sum(ws)/len(ws):+.2f} (n={len(ws)})")
    return "\n".join(zeilen)


def sync():
    alle = lade_regeln()
    regeln = exportierbare_regeln(alle)
    meta = export_metadaten(alle, regeln)
    os.makedirs(os.path.dirname(SKILL_REF), exist_ok=True)
    with open(SKILL_REF, "w", encoding="utf-8") as f:
        f.write(markdown(regeln, gesamt=len(alle)))
    return len(regeln), meta


if __name__ == "__main__":
    quiet = "--quiet" in sys.argv
    n, meta = sync()
    try:
        from system_log import log_eintrag
        log_eintrag("skill", f"Skill-Sync: {n} Regeln in Skill übernommen "
                     f"(Stand {meta['regelstand_version']}, "
                     f"{meta['anzahl_verfuegbar']} verfügbar)", "info")
    except Exception:
        pass
    if not quiet:
        print(f"Skill-Sync OK: {n} Regeln nach {SKILL_REF} "
              f"(Stand {meta['regelstand_version']})")
