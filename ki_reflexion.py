"""KI-Selbstreflexion — die KI liest ihre eigenen Entscheidungen und hinterfragt sich.

4 Mechanismen:
1. 🔤 Grund-Text-Analyse (deterministisch): Begründungs-Wörter cluster + Trefferquote
2. 🎲 Verlust-Aversion (deterministisch): Verhalten nach Verlusten (Revanche-Trading?)
3. ⚖️ Regel-Abweichung (deterministisch): Handelt die KI gegen ihre eigenen Regeln?
4. 🗣️ KI-Selbstreflexion (1 KI-Call/Tag): KI analysiert ihre letzten 50 Entscheidungen
   inkl. eigener Begründungen + Lerneffekte → [Reflexion]-Regeln

Importiert ki_learning NUR lazy (in Funktionen) — ki_learning ruft selbst_reflexion()
am Ende seines main() auf → kein Import-Zyklus (ki_learning → ki_reflexion → ki_learning).
"""
import json
import os
import re
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
KI_LOG = os.path.join(BASE, "ki_log.json")
REGELN = os.path.join(BASE, "ki_regeln.json")
REFLEXION_INTERVALL_H = 24  # Selbst-Reflexion max. 1×/Tag


# ══════════════════════════════════════════════════════════════
# 0) Gemeinsame Helfer
# ══════════════════════════════════════════════════════════════
def _lade_log():
    if not os.path.exists(KI_LOG):
        return []
    try:
        with open(KI_LOG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _verbundene_entscheidungen(max_anzahl=50):
    """Decision-Einträge mit ihrem Lerneffekt (learned, bezug=zeit) verbunden."""
    log = _lade_log()
    learned_by_bezug = {}
    for e in log:
        if e.get("typ") == "learned" and e.get("bezug"):
            learned_by_bezug[e["bezug"]] = e
    verbunden = []
    for e in log:
        if e.get("typ") != "decision":
            continue
        le = learned_by_bezug.get(e.get("zeit"))
        verbunden.append({
            "zeit": e.get("zeit", ""),
            "ticker": e.get("ticker", ""),
            "aktion": e.get("aktion", ""),
            "konfidenz": e.get("konfidenz", ""),
            "menge": e.get("menge", ""),
            "grund": str(e.get("grund", "")),
            "rsi": e.get("rsi", ""),
            "trend": e.get("trend", ""),
            "p_pnl": e.get("p_pnl", ""),
            "lerneffekt": le.get("lerneffekt") if le else None,
            "change_pct": le.get("change_pct") if le else None,
        })
    # Neueste zuerst (stabile Sortierung), dann bewertete an den Anfang:
    # Python-Sort ist stabil → Zeit-Reihenfolge bleibt innerhalb der Gruppen.
    verbunden.sort(key=lambda d: d.get("zeit", ""), reverse=True)
    verbunden.sort(key=lambda d: 0 if isinstance(d.get("lerneffekt"), (int, float)) else 1)
    return verbunden[:max_anzahl]


# ══════════════════════════════════════════════════════════════
# 1) 🔤 Grund-Text-Analyse (deterministisch)
# ══════════════════════════════════════════════════════════════
GRUND_CLUSTER = [
    ("Abwärtstrend", ["abwärtstrend", "abwaertstrend", "abwärts", "sma50", "sma20"]),
    ("Neutral/Vorsicht", ["neutral", "kein signal", "keine signale", "keine neuen", "vorsicht"]),
    ("RSI", ["rsi"]),
    ("Verlustposition", ["verlust", "p_pnl", "verlustposition"]),
    ("News", ["news", "meldung", "nachricht"]),
    ("Klumpenrisiko", ["klumpen", "depots", "konzentration"]),
    ("Überkauft/Überverkauft", ["überkauft", "ueberkauft", "überverkauft", "ueberverkauft"]),
    ("Momentum/Aufwärtspotenzial", ["aufwärts", "aufwaerts", "momentum", "potenzial", "chance"]),
    ("VIX/Volatilität", ["vix", "volatil"]),
    ("Börse/Markt", ["markt geschlossen", "börse", "boerse", "handel"]),
]


def grund_analyse(max_anzahl=200):
    """Clustert die Begründungs-Texte der KI und berechnet Trefferquoten.

    → „Begründung 'Abwärtstrend': 3/9 richtig" — zeigt, mit welchen Worten
    die KI entscheidet, wenn sie falsch liegt.
    """
    entscheidungen = _verbundene_entscheidungen(max_anzahl)
    cluster = {}
    for d in entscheidungen:
        le = d.get("lerneffekt")
        if not isinstance(le, (int, float)):
            continue
        grund = (d.get("grund") or "").lower()
        zugeordnet = False
        for name, woerter in GRUND_CLUSTER:
            if any(w in grund for w in woerter):
                st = cluster.setdefault(name, {"ges": 0, "pos": 0, "neg": 0})
                st["ges"] += 1
                if le >= 1:
                    st["pos"] += 1
                elif le <= -1:
                    st["neg"] += 1
                zugeordnet = True
        if not zugeordnet and grund:
            st = cluster.setdefault("Sonstiges", {"ges": 0, "pos": 0, "neg": 0})
            st["ges"] += 1
            if le >= 1:
                st["pos"] += 1
            elif le <= -1:
                st["neg"] += 1

    ergebnis = []
    for name, st in sorted(cluster.items(), key=lambda kv: -kv[1]["ges"]):
        quote = st["pos"] / st["ges"] * 100 if st["ges"] else 0
        ergebnis.append({
            "cluster": name, "ges": st["ges"], "pos": st["pos"],
            "neg": st["neg"], "quote": round(quote, 0),
        })
    return ergebnis


# ══════════════════════════════════════════════════════════════
# 2) 🎲 Verlust-Aversion / Revanche-Trading (deterministisch)
# ══════════════════════════════════════════════════════════════
def verlust_aversion(max_anzahl=200):
    """Handelt die KI nach Verlusten riskanter?

    Vergleicht Ø-Konfidenz + Menge (voll/teil) direkt NACH einer verlorenen
    Entscheidung (lerneffekt ≤ −1) vs. nach einer gewonnenen (≥ +1).
    """
    entscheidungen = _verbundene_entscheidungen(max_anzahl)
    entscheidungen.sort(key=lambda d: d.get("zeit", ""))
    nach_verlust = {"konfidenz": [], "voll": 0, "n": 0}
    nach_gewinn = {"konfidenz": [], "voll": 0, "n": 0}
    for i in range(1, len(entscheidungen)):
        vorher = entscheidungen[i - 1].get("lerneffekt")
        jetzt = entscheidungen[i]
        if not isinstance(vorher, (int, float)):
            continue
        try:
            konf = float(jetzt.get("konfidenz") or 0)
        except (TypeError, ValueError):
            konf = 0
        menge = str(jetzt.get("menge") or "")
        ziel = nach_verlust if vorher <= -1 else (nach_gewinn if vorher >= 1 else None)
        if ziel is None:
            continue
        ziel["konfidenz"].append(konf)
        if menge == "voll":
            ziel["voll"] += 1
        ziel["n"] += 1

    def _summieren(st):
        if not st["n"]:
            return None
        return {
            "n": st["n"],
            "konfidenz_avg": round(sum(st["konfidenz"]) / len(st["konfidenz"]), 1),
            "voll_quote": round(st["voll"] / st["n"] * 100, 0),
        }

    nv, ng = _summieren(nach_verlust), _summieren(nach_gewinn)
    if not nv or not ng:
        return {"nach_verlust": nv, "nach_gewinn": ng, "befund": None}
    konf_diff = nv["konfidenz_avg"] - ng["konfidenz_avg"]
    voll_diff = nv["voll_quote"] - ng["voll_quote"]
    if konf_diff >= 5 or voll_diff >= 15:
        befund = (f"Revanche-Trading! Nach Verlusten: Konfidenz +{konf_diff:.0f} Punkte, "
                  f"voll-Investitionen +{voll_diff:.0f} Prozentpunkte häufiger")
    elif konf_diff <= -5 or voll_diff <= -15:
        befund = "Nach Verlusten wird KONSERVATIVER (Konfidenz/Menge sinken) — gut."
    else:
        befund = "Kein auffälliges Verlust-Verhalten."
    return {"nach_verlust": nv, "nach_gewinn": ng, "befund": befund}


# ══════════════════════════════════════════════════════════════
# 3) ⚖️ Regel-Abweichung (deterministisch)
# ══════════════════════════════════════════════════════════════
def regel_abweichungen(max_anzahl=100):
    """Handelt die KI gegen ihre eigenen gelernten Regeln?

    Nutzt die Bedingungen der Entscheidung (rsi, trend-Felder) statt pauschal
    zu zählen:
    - RSI-Regeln („kaufen bei RSI<30"): Entscheidungen mit RSI < 35, die NICHT
      kaufen → Regel-Abweichung.
    - Anti-Regeln ([Anti]…): Zählt, wie oft die verbotene Aktion trotzdem
      ausgeführt wurde.
    - Sonstige: gleicher Ticker mit entgegengesetzten Aktionen (kaufen vs.
      verkaufen) innerhalb von 7 Tagen = Selbst-Widerspruch.
    """
    from ki_learning import lade_regeln  # lazy — Import-Zyklus vermeiden

    regeln = lade_regeln(max_alter_tage=365)
    entscheidungen = _verbundene_entscheidungen(max_anzahl)
    ergebnis = []
    for r in regeln:
        muster = str(r.get("muster", "")).lower()
        regel_text = str(r.get("regel", "")).lower()
        ist_anti = muster.startswith("[anti]")
        regel_aktion = None
        for a in ("kaufen", "verkaufen", "halten"):
            if a in muster or a in regel_text:
                regel_aktion = a
                break
        if not regel_aktion:
            continue

        if "rsi" in muster:
            # RSI-Bedingungs-Check: rsi-Feld der Entscheidung nutzen
            abgewichen = befolgt = 0
            for d in entscheidungen:
                try:
                    rsi = float(d.get("rsi") or 0)
                except (TypeError, ValueError):
                    continue
                aktion = str(d.get("aktion", "")).lower()
                if not aktion:
                    continue
                if regel_aktion == "kaufen" and rsi < 35:
                    if aktion == "kaufen":
                        befolgt += 1
                    else:
                        abgewichen += 1
                elif regel_aktion == "verkaufen" and rsi > 65:
                    if aktion == "verkaufen":
                        befolgt += 1
                    else:
                        abgewichen += 1
            if befolgt + abgewichen >= 3:
                ergebnis.append({
                    "regel": r.get("muster", ""),
                    "aktion": regel_aktion, "typ": "RSI-Bedingung",
                    "befolgt": befolgt, "abgewichen": abgewichen,
                })
        elif ist_anti:
            # Anti-Regel: wie oft wurde die verbotene Aktion trotzdem gemacht?
            abgewichen = befolgt = 0
            for d in entscheidungen:
                aktion = str(d.get("aktion", "")).lower()
                if not aktion:
                    continue
                if aktion == regel_aktion:
                    abgewichen += 1
                else:
                    befolgt += 1
            if abgewichen >= 1:
                ergebnis.append({
                    "regel": r.get("muster", ""),
                    "aktion": regel_aktion, "typ": "Anti-Verletzung",
                    "befolgt": befolgt, "abgewichen": abgewichen,
                })
        else:
            # Selbst-Widerspruch: gleicher Ticker, entgegengesetzte Aktionen
            ticker_aktionen = {}
            for d in entscheidungen:
                aktion = str(d.get("aktion", "")).lower()
                if aktion in ("kaufen", "verkaufen"):
                    ticker_aktionen.setdefault(d.get("ticker"), set()).add(aktion)
            widersprueche = {t: a for t, a in ticker_aktionen.items()
                             if len(a) >= 2 and "kaufen" in a and "verkaufen" in a}
            if widersprueche:
                ergebnis.append({
                    "regel": "Selbst-Widerspruch",
                    "aktion": "kaufen/verkaufen", "typ": "Ticker-Widerspruch",
                    "ticker": ", ".join(list(widersprueche.keys())[:5]),
                    "befolgt": len(widersprueche), "abgewichen": 0,
                })
    return ergebnis


# ══════════════════════════════════════════════════════════════
# 4) 🗣️ KI-Selbstreflexion (1 KI-Call/Tag)
# ══════════════════════════════════════════════════════════════
def _letzte_reflexion():
    """Zeitstempel der letzten Reflexion (aus ki_log, typ=reflexion)."""
    for e in reversed(_lade_log()):
        if e.get("typ") == "reflexion":
            try:
                return datetime.datetime.fromisoformat(e.get("zeit", ""))
            except Exception:
                return None
    return None


def _anhangen_ki_log(eintrag):
    log = _lade_log()
    log.append(eintrag)
    try:
        with open(KI_LOG, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def selbst_reflexion(force=False, max_tokens=500, timeout_s=60):
    """KI liest ihre letzten Entscheidungen selbst und hinterfragt sich.

    Läuft max. 1×/Tag (Intervall REFLEXION_INTERVALL_H), speichert
    [Reflexion]-Regeln via speichere_regeln() + Reflexions-Notiz im KI-Log.
    Cron-ready: kleiner Prompt, harte Timeouts, max_tokens begrenzt.
    """
    letzte = _letzte_reflexion()
    if not force and letzte:
        alter_h = (datetime.datetime.now() - letzte).total_seconds() / 3600.0
        if alter_h < REFLEXION_INTERVALL_H:
            print(f"🪞 Reflexion übersprungen (letzte vor {alter_h:.0f}h, Intervall {REFLEXION_INTERVALL_H}h)")
            return None

    entscheidungen = _verbundene_entscheidungen(200)
    bewertet = [d for d in entscheidungen if isinstance(d.get("lerneffekt"), (int, float))]
    if len(bewertet) < 5:
        print("🪞 Reflexion übersprungen (zu wenig bewertete Entscheidungen)")
        return None

    # Deterministische Analysen als Kontext (bereits in ki_learning passiert, hier nur Zusammenfassung)
    grund = grund_analyse(200)
    verlust = verlust_aversion(200)
    abweich = regel_abweichungen(200)

    # NUR Top-3 Fehlermuster für Prompt (Kosten-Kontrolle)
    top_fehler = [g for g in grund if g["ges"] >= 5 and g["quote"] < 30][:3]
    top_abweich = [a for a in abweich if a.get("abgewichen", 0) >= 3][:3]

    zeilen = []
    for d in bewertet[:15]:  # nur 15 für Prompt
        le = d["lerneffekt"]
        le_str = f"{le:+d}" if isinstance(le, (int, float)) else "—"
        zeilen.append(
            f"- {d['ticker']}: {d['aktion']} (K{d.get('konfidenz','?')}) "
            f"→ {d.get('change_pct','?')}% (LE {le_str}) — {d.get('grund','')[:80]}"
        )

    grund_text = "\n".join(
        f"  · '{g['cluster']}': {g['pos']}✓/{g['neg']}✗ ({g['quote']:.0f}%)"
        for g in top_fehler
    ) or "  (keine)"
    verlust_text = verlust.get("befund") or "  (keine Daten)"
    abweich_text = "\n".join(
        f"  · {a['typ']}: '{a['regel'][:40]}' → {a['abgewichen']}× abgewichen"
        for a in top_abweich
    ) or "  (keine)"

    prompt = f"""Du bist ein KI-Trader, der sich SELBST hinterfragt. Deine letzten 15 Entscheidungen MIT deinen Begründungen und gemessenen Lerneffekten (−5…+5):

DEINE ENTSCHEIDUNGEN:
{chr(10).join(zeilen)}

DEINE FEHLMUSTER (deterministisch erkannt):
1. Unverlässliche Begründungen:
{grund_text}

2. Verlust-Verhalten:
{verlust_text}

3. Regel-Abweichungen:
{abweich_text}

SELBST-BEFRAGUNG — antworte KONKRET & EHRLICH:
- Was ist dein größtes systematisches Fehlermuster?
- Wie korrigierst du es in der nächsten Woche?

Antworte NUR mit JSON:
{{"einsicht": "2-3 Sätze: größtes Fehlermuster + Korrektur",
  "regeln": [{{"muster": "[Reflexion] z.B. RSI-Begründung", "regel": "Konkrete Verhaltensänderung", "gewicht": 0.5-2.0}}],
  "anpassung": "1 Satz: Verhalten nächste Woche"}}

Max. 2 Regeln. Gewicht >1.0 = starkes Fehlermuster."""

    try:
        from ki_provider import call_ki
        raus, _provider = call_ki(
            [{"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=max_tokens,
        )
    except Exception as e:
        print(f"🪞 Reflexion KI-Call fehlgeschlagen: {e}")
        return None
    if not raus:
        print("🪞 Reflexion: keine KI-Antwort (alle Provider gescheitert)")
        return None

    # JSON aus Antwort extrahieren
    try:
        start, ende = raus.find("{"), raus.rfind("}")
        antwort = json.loads(raus[start:ende + 1])
    except Exception:
        print("🪞 Reflexion: Antwort nicht als JSON parsebar")
        return None

    regeln = antwort.get("regeln") or []
    if regeln:
        from ki_learning import speichere_regeln
        speichere_regeln(regeln)

    _anhangen_ki_log({
        "typ": "reflexion",
        "zeit": datetime.datetime.now().isoformat(),
        "einsicht": antwort.get("einsicht", ""),
        "anpassung": antwort.get("anpassung", ""),
        "regeln": len(regeln),
    })
    print(f"🪞 Reflexion OK: {len(regeln)} Regeln, Einsicht gespeichert")
    return antwort


def reflexion_wochenbericht():
    """Phase 1: Wöchentlicher deterministischer Bericht (kein KI-Call).

    Analysiert 7-Tage-Entscheidungen, clustert nach Asset-Klasse/Aktion/Lerneffekt,
    schreibt:
      - reflexion_summary_YYYY-Www.md  (lesbar)
      - pending_rules.json            (neue/anzupassende Regeln zur Freigabe)

    Gibt (anzahl_neue_regeln, pfad_summary) zurück.
    """
    from datetime import timedelta
    log = _lade_log()
    cutoff = datetime.datetime.now() - timedelta(days=7)
    # Lerneffekte stehen in 'learned'-Einträgen (nicht 'decision'!)
    ents = [e for e in log if e.get("typ") == "learned"
            and isinstance(e.get("lerneffekt"), (int, float))]
    ents = [e for e in ents if _datum(e) >= cutoff]
    if len(ents) < 5:
        print("🪞 Wochenbericht übersprungen (zu wenig Daten)")
        return (0, None)

    def asset_klasse(t):
        t = (t or "").upper()
        if any(k in t for k in ["BTC", "ETH", "DOGE", "ADA", "SOL", "XRP"]):
            return "crypto"
        if any(k in t for k in ["TQQQ", "SQQQ", "UPRO", "SPXU", "TNA", "JDST", "KOLD", "LABU", "NUGT", "YINN"]):
            return "lev-etf"
        if any(k in t for k in ["VIX", "UVXY", "VXX"]):
            return "volatility"
        return "core"

    fehler = {}
    erfolg = {}
    for e in ents:
        ak = asset_klasse(e["ticker"])
        le = e["lerneffekt"]
        key = (ak, e["aktion"])
        if le <= -2:
            fehler.setdefault(key, []).append(le)
        elif le >= 2:
            erfolg.setdefault(key, []).append(le)

    top_fehler = sorted(fehler.items(), key=lambda kv: -len(kv[1]))[:3]
    top_erfolg = sorted(erfolg.items(), key=lambda kv: -len(kv[1]))[:3]

    pending = []
    for (ak, aktion), les in top_fehler:
        if len(les) >= 3 and aktion == "halten":
            pending.append({
                "muster": f"[Reflexion] {aktion} bei {ak}",
                "regel": f"{aktion.capitalize()} bei {ak}-Titeln systematisch schlecht "
                         f"({len(les)}× LE≤−2, Ø {sum(les)/len(les):.1f})",
                "typ": "anti" if ak in ("crypto", "lev-etf", "volatility") else "positiv",
                "gewicht": round(min(2.0, 0.5 + len(les) * 0.2), 2),
                "support_count": 0,
                "violation_count": len(les),
                "avg_effect_when_applied": round(sum(les) / len(les), 1),
                "kontext": {"asset_klasse": [ak], "regime": ["bear", "seitwaerts", "bull"]},
                "quellBERICHT": "wochenbericht",
            })

    kw = datetime.datetime.now().strftime("%Y-W%W")
    summary_pfad = os.path.join(BASE, f"reflexion_summary_{kw}.md")
    with open(summary_pfad, "w", encoding="utf-8") as f:
        f.write(f"# KI-Reflexion Wochenbericht ({kw})\n\n")
        f.write(f"Analysierte Entscheidungen (7 Tage): **{len(ents)}**\n\n")
        f.write("## 🔴 Top-3 Fehlermuster\n")
        for (ak, aktion), les in top_fehler:
            f.write(f"- **{aktion} bei {ak}**: {len(les)}× LE≤−2, Ø {sum(les)/len(les):.1f}\n")
        f.write("\n## 🟢 Top-3 Erfolgsmuster\n")
        for (ak, aktion), les in top_erfolg:
            f.write(f"- **{aktion} bei {ak}**: {len(les)}× LE≥+2, Ø {sum(les)/len(les):.1f}\n")
        f.write("\n## 📋 Neue Regel-Kandidaten (pending_rules.json)\n")
        for p in pending:
            f.write(f"- `{p['muster']}`: {p['regel']} (G {p['gewicht']})\n")

    pr_pfad = os.path.join(BASE, "pending_rules.json")
    try:
        with open(pr_pfad, encoding="utf-8") as f:
            bestehend = json.load(f)
    except Exception:
        bestehend = []
    bestehend = [p for p in bestehend if p.get("quellBERICHT") != "wochenbericht"]
    bestehend.extend(pending)
    with open(pr_pfad, "w", encoding="utf-8") as f:
        json.dump(bestehend, f, ensure_ascii=False, indent=2)
    # Fix 1: pending -> learned Uebernahme (verhindert ewig 'offene' OOS-Regeln)
    try:
        n = uebernehme_pending_in_learned()
        if n:
            print(f"  [Uebernahme] {n} pending_rules -> learned_rules")
    except Exception as e:
        print(f"  [Uebernahme-Fehler] {e}")

    print(f"🪞 Wochenbericht: {len(ents)} Entscheidungen, {len(pending)} Regel-Kandidaten → {summary_pfad}")
    return (len(pending), summary_pfad)


def _datum(e):
    try:
        return datetime.datetime.fromisoformat(e.get("zeit", ""))
    except Exception:
        return datetime.datetime.min


# ══════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    print("🪞 KI-Selbstreflexion...")
    ergebnis = selbst_reflexion(force=force)
    if ergebnis:
        print("\nEinsicht:", ergebnis.get("einsicht", "")[:300])
        print("\nAnpassung:", ergebnis.get("anpassung", "")[:200])
        for r in ergebnis.get("regeln") or []:
            print(f"  [Reflexion] {r.get('muster','')} → {r.get('regel','')} (G {r.get('gewicht','')})")
    print("\n📊 Grund-Text-Analyse:")
    for g in grund_analyse():
        print(f"  '{g['cluster']}': {g['pos']}✓/{g['neg']}✗ von {g['ges']} ({g['quote']:.0f}%)")
    print("\n🎲 Verlust-Aversion:", verlust_aversion().get("befund"))
    print("\n⚖️ Regel-Abweichungen:")
    for a in regel_abweichungen():
        print(f"  '{a['regel'][:50]}' → {a['aktion']}: {a['befolgt']}× befolgt, {a['abgewichen']}× abgewichen")


def uebernehme_pending_in_learned(schwelle_viol=5):
    """Fix 1: Pending-Regeln mit ausreichend Evidenz in learned_rules uebernehmen.
    Bisher blieben pending_rules ewig 'offen' (OOS offen im Dashboard) weil
    support_count=0 war. Regeln mit violation_count >= schwelle gelten als
    validiert (KI verletzt sie systematisch -> Regel greift)."""
    try:
        from learned_rules import lade_regeln, speichere_regeln
    except Exception:
        return 0
    pr_pfad = os.path.join(BASE, "pending_rules.json")
    if not os.path.exists(pr_pfad):
        return 0
    pending = json.load(open(pr_pfad, encoding="utf-8"))
    if not isinstance(pending, list):
        return 0
    regeln = lade_regeln(max_alter_tage=365)
    uebernommen = 0
    for p in pending:
        viol = p.get("violation_count", 0)
        muster = p.get("muster", "")
        if viol < schwelle_viol:
            continue
        if any(r.get("muster") == muster for r in regeln):
            for r in regeln:
                if r.get("muster") == muster:
                    r["violation_count_alt"] = r.get("violation_count") or 0
                    r["violation_count"] = viol
                    r["last_seen_at"] = datetime.datetime.now().isoformat()
                    # 30.09.2026: Eine Regel, die die Reflexion
                    # verletzt, aber support_count 0 hat, wurde nie
                    # bestaetigt. Sie darf nicht weiter "stabil" und
                    # "freigegeben" heissen - der gelernte Stand
                    # fuehrte sie mit 0 Verletzungen und negativem
                    # Gewicht, die Reflexion misst 7 bis 52.
                    if viol > 0 and not (r.get("support_count") or 0):
                        r["shadow"] = True
                        r["oos_confirmed"] = False
                        r["freigabe_status"] = "wackelig"
                        r["beleg_widerspruch"] = {
                            "erkannt": "2026-09-30",
                            "gelernter_stand": r["violation_count_alt"],
                            "reflexion": viol,
                        }
            uebernommen += 1
            continue
        neu = {
            "muster": muster,
            "regel": p.get("regel", ""),
            "typ": p.get("typ", "anti"),
            "gewicht": p.get("gewicht", 1.0) + min(viol / 20.0, 1.0),
            "support_count": 0,
            "violation_count": viol,
            "avg_effect_when_applied": 0.0,
            "kontext": {"asset_klasse": [], "sektor": [], "vix_range": [0, 999],
                        "trend_4h": "", "regime": [], "min_konfidenz": 0},
            "created_at": datetime.datetime.now().isoformat(),
            "updated_at": datetime.datetime.now().isoformat(),
            "last_seen_at": datetime.datetime.now().isoformat(),
            "decay_lambda": 0.01,
            "aus_pending_uebernommen": True,
        }
        neu["id"] = f"r_{datetime.datetime.now():%Y%m%d}_{abs(hash(muster)) % 100000}"
        regeln.append(neu)
        uebernommen += 1
    if uebernommen:
        speichere_regeln(regeln)
    return uebernommen


# 30.09.2026: Nachlauf. Die Reflexion berechnet Abweichungen,
# speichert sie aber nicht - uebernehme_pending_in_learned() war
# nur im Wochenschicht-Pfad reflexion_wochenbericht() aufgerufen,
# den __main__ nie ausfuehrt. Deshalb blieb learned_rules.json
# 33 Tage unveraendert, obwohl der Timer alle 30 Minuten laeuft.
if __name__ == "__main__":
    try:
        _ueb = uebernehme_pending_in_learned()
        print("\n📥 Pending->learned: %d Regel(n) uebernommen/aktualisiert" % _ueb)
    except Exception as _e:
        print("\n📥 Pending-Uebernahme fehlgeschlagen: %s" % _e)
