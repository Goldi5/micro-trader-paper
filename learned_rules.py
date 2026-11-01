#!/usr/bin/env python3
"""learned_rules.py — Zentrale Regelbasis (Source of Truth).

Phase 0 (2026-08-01): Ersetzt die flache ki_regeln.json durch ein
strukturiertes Schema mit Metriken, Kontext und Zeitstempeln.

Schema einer Regel:
{
  "id": "r_20260801_crypto_halt",
  "muster": "[Anti] halten bei crypto-Titeln",
  "regel": "NICHT halten bei crypto-Titeln – systematisch falsch (6/6 widerlegt, Ø -3.3)",
  "typ": "anti",            // anti | positiv | swap | opportunitaet
  "gewicht": -1.82,         // Roh-Gewicht (ohne Decay)
  "support_count": 6,       // wie oft bestätigt
  "violation_count": 0,     // wie oft widerlegt
  "avg_effect_when_applied": -3.3,
  "kontext": {
    "asset_klasse": ["crypto", "lev-bull", "volatility"],
    "sektor": ["crypto", "spekulativ"],
    "vix_range": [0, 999],
    "trend_4h": "<-2%",
    "regime": ["bear", "seitwaerts", "bull"],
    "min_konfidenz": 0
  },
  "created_at": "2026-07-31T20:35:00",
  "updated_at": "2026-08-01T12:24:00",
  "last_seen_at": "2026-08-01T10:21:00",
  "decay_lambda": 0.01,     // pro Tag
  "effektiv_gewicht": -1.55 // gewicht * exp(-lambda * tage)
}

Decay: effektiv_gewicht = gewicht * exp(-decay_lambda * tage_seit_updated)
"""
import os, json, math
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
LEARNED = os.path.join(BASE, "learned_rules.json")
REGELN_LEGACY = os.path.join(BASE, "ki_regeln.json")  # kompatibler Export

# Settings-Loader (Decay-Lambda aus settings.json)
try:
    from settings_loader import lernen as _lern_set
except Exception:
    def _lern_set(n, d=None): return d

def decay_lambda_global():
    """Globaler Decay-Wert aus Settings (Default 0.01/Tag)."""
    return float(_lern_set("decay_lambda", 0.01))


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _parse_counts(regel_text):
    """Extrahiert support/violation aus Regel-Text wie '(6/6 widerlegt)'."""
    import re
    m = re.search(r"\((\d+)/(\d+)\s*(widerlegt|bestätigt|bestaetigt)\)", regel_text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if "widerlegt" in m.group(3):
            return 0, b  # alle widerlegt
        return b, 0
    m2 = re.search(r"\(n=(\d+)\)", regel_text)
    if m2:
        return int(m2.group(1)), 0
    return 0, 0


def _asset_klasse_aus_muster(muster):
    m = muster.lower()
    if "crypto" in m: return ["crypto"]
    if "lev-bull" in m or "lev-bear" in m: return ["lev-bull", "lev-bear"]
    if "volatility" in m: return ["volatility"]
    if "meme" in m: return ["meme"]
    if "space" in m: return ["space"]
    if "ai" in m: return ["ai"]
    if "commodity" in m: return ["commodity"]
    if "biotech" in m: return ["biotech"]
    if "ev" in m: return ["ev"]
    if "index" in m: return ["index"]
    return []


def migriere_aus_ki_regeln():
    """Liest ki_regeln.json (altes Format) und erzeugt learned_rules.json.

    Gibt Anzahl migrierter Regeln zurück.
    """
    if os.path.exists(LEARNED):
        return 0  # bereits migriert
    if not os.path.exists(REGELN_LEGACY):
        return 0
    try:
        with open(REGELN_LEGACY, encoding="utf-8") as f:
            alt = json.load(f)
    except Exception:
        return 0

    regeln = []
    for i, r in enumerate(alt, 1):
        muster = r.get("muster", "")
        regel = r.get("regel", "")
        gewicht = float(r.get("gewicht", 1.0))
        is_anti = r.get("anti") or muster.startswith("[Anti]") or gewicht < 0
        support, violation = _parse_counts(regel)
        if is_anti:
            typ = "anti"
        else:
            typ = "positiv"
        ak = _asset_klasse_aus_muster(muster)
        zeit = str(r.get("zeit", _now_iso()))
        regeln.append({
            "id": f"r_legacy_{i}_{abs(hash(muster)) % 100000:05d}",
            "muster": muster,
            "regel": regel,
            "typ": typ,
            "gewicht": round(gewicht, 2),
            "support_count": support,
            "violation_count": violation,
            "avg_effect_when_applied": round(gewicht * 2, 1) if support + violation else 0.0,
            "kontext": {
                "asset_klasse": ak,
                "sektor": ak,
                "vix_range": [0, 999],
                "trend_4h": "",
                "regime": ["bear", "seitwaerts", "bull"],
                "min_konfidenz": 0,
            },
            "created_at": zeit,
            "updated_at": zeit,
            "last_seen_at": zeit,
            "decay_lambda": 0.01,
            "effektiv_gewicht": round(gewicht, 2),
        })
    if regeln:
        _schreiben(regeln)
    return len(regeln)


def _regelstand_meta_lesen():
    """Liest Regelstand-Metadaten (Version, Hash) aus Header, falls vorhanden."""
    try:
        with open(LEARNED, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("_regelstand", {})
    except Exception:
        return {}


def _regelstand_meta_schreiben(regeln):
    """Berechnet Regelstand-Meta (Version, Hash, Status) für den Gesamtstand."""
    meta = _regelstand_meta_lesen()
    version = meta.get("regelstand_version", 0) + 1
    import hashlib
    h = hashlib.sha256(json.dumps(
        [{"id": r.get("id"), "ew": r.get("effektiv_gewicht", r.get("gewicht")),
         "status": r.get("status")} for r in regeln],
        sort_keys=True).encode()).hexdigest()[:12]
    now = _now_iso()
    return {
        "regelstand_version": version,
        "regelstand_created_at": meta.get("regelstand_created_at", now),
        "regelstand_last_sync": now,
        "regelstand_status": "shadow" if any(r.get("shadow") for r in regeln) else "freigegeben",
        "regelstand_hash": h,
    }


def _schreiben(regeln):
    meta = _regelstand_meta_schreiben(regeln)
    with open(LEARNED, "w", encoding="utf-8") as f:
        json.dump({"schema_version": "2.0", "_regelstand": meta, "rules": regeln}, f,
                  ensure_ascii=False, indent=2)


def lade_regeln(include_decay=True, max_alter_tage=365, inkl_arktiviert=False, nur_live=False):
    """Lädt learned_rules.json.

    - migriert automatisch aus ki_regeln.json falls nicht vorhanden
    - berechnet effektiv_gewicht (Decay) falls include_decay
    - filtert nach Alter (max_alter_tage)
    - Prio 2: blendet archivierte Regeln aus (außer inkl_arktiviert=True)
    """
    if not os.path.exists(LEARNED):
        migriere_aus_ki_regeln()
    try:
        with open(LEARNED, encoding="utf-8") as f:
            data = json.load(f)
        regeln = data.get("rules", [])
    except Exception:
        return []

    cutoff = datetime.now() - timedelta(days=max_alter_tage)
    result = []
    for r in regeln:
        try:
            upd = datetime.fromisoformat(r.get("updated_at", r.get("created_at", _now_iso())))
            if upd < cutoff:
                continue
        except Exception:
            pass
        # Prio 2: archivierte Regeln ausblenden (außer explizit gewünscht)
        if r.get("archiviert") and not inkl_arktiviert:
            continue
        # Block2: nur_live filtert shadow + nicht-freigegebene Regeln raus
        if nur_live and (r.get("shadow") or r.get("freigabe_status") != "freigegeben"):
            continue
        r = dict(r)
        # Block2: fehlende Felder mit Defaults füllen (Rückwärtskompatibilität)
        r.setdefault("id", f"r_{abs(hash(r.get('muster','')) % 100000):05d}")
        r.setdefault("typ", "anti" if r.get("muster", "").startswith("[Anti]") else "positiv")
        r.setdefault("shadow", False)
        r.setdefault("oos_confirmed", False)
        r.setdefault("support_count", 0)
        r.setdefault("violation_count", 0)
        r.setdefault("freigabe_status", "freigegeben")  # alte Regeln galten als live
        r.setdefault("prioritaet", 1 if r.get("typ") in ("anti", "swap", "meta_conf_cap") else 2)
        r.setdefault("konfliktgruppe", r.get("muster", "")[:30])
        r.setdefault("created_in_version", 0)
        r.setdefault("last_validated_version", 0)
        r.setdefault("status", "unbestätigt")
        if include_decay:
            tage = max(0, (datetime.now() - upd).days)
            lam = decay_lambda_global()  # aus Settings
            r["effektiv_gewicht"] = round(float(r.get("gewicht", 0)) * math.exp(-lam * tage), 2)
        result.append(r)
    # R2: Decay-respektierende Sortierung (effektiv_gewicht, absteigend nach Betrag)
    result.sort(key=lambda r: abs(float(r.get("effektiv_gewicht", r.get("gewicht", 0)))), reverse=True)
    return result


def speichere_regeln(neue_regeln):
    """Fügt neue Regeln hinzu / aktualisiert bestehende (per muster).

    neue_regeln: Liste von Dicts mit mind. muster/regel/gewicht/typ.
    Schreibt learned_rules.json + kompatiblen Export ki_regeln.json.
    """
    regeln = lade_regeln(include_decay=False)
    jetzt = _now_iso()
    for nr in neue_regeln:
        muster = (nr.get("muster") or "").strip()
        regel = (nr.get("regel") or "").strip()
        if not muster or not regel:
            continue
        gewicht = float(nr.get("gewicht", 1.0))
        typ = nr.get("typ", "anti" if (muster.startswith("[Anti]") or gewicht < 0) else "positiv")
        gefunden = False
        for r in regeln:
            if r.get("muster") == muster:
                alt = float(r.get("gewicht", 1.0))
                r["gewicht"] = round(min(2.5, (alt * 0.7) + (gewicht * 0.3)), 2)
                r["regel"] = regel
                r["typ"] = typ
                r["updated_at"] = jetzt
                # Block2: neue Metadaten erhalten
                if nr.get("shadow") is not None: r["shadow"] = nr["shadow"]
                if nr.get("freigabe_status"): r["freigabe_status"] = nr["freigabe_status"]
                if nr.get("prioritaet") is not None: r["prioritaet"] = nr["prioritaet"]
                if nr.get("konfliktgruppe"): r["konfliktgruppe"] = nr["konfliktgruppe"]
                if nr.get("oos_confirmed") is not None: r["oos_confirmed"] = nr["oos_confirmed"]
                if nr.get("last_validated_version") is not None: r["last_validated_version"] = nr["last_validated_version"]
                if nr.get("last_validated_at"): r["last_validated_at"] = nr["last_validated_at"]
                if nr.get("support_count") is not None:
                    r["support_count"] = nr["support_count"]
                if nr.get("violation_count") is not None:
                    r["violation_count"] = nr["violation_count"]
                if nr.get("avg_effect_when_applied") is not None:
                    r["avg_effect_when_applied"] = nr["avg_effect_when_applied"]
                if nr.get("swap_type") is not None:
                    r["swap_type"] = nr["swap_type"]
                if nr.get("benchmark_ticker") is not None:
                    r["benchmark_ticker"] = nr["benchmark_ticker"]
                if nr.get("kontext"):
                    r["kontext"] = nr["kontext"]
                if nr.get("conf_cap") is not None:
                    r["conf_cap"] = nr["conf_cap"]
                gefunden = True
                break
        if not gefunden:
            regeln.append({
                "id": f"r_{jetzt[:10].replace('-', '')}_{abs(hash(muster)) % 100000:05d}",
                "muster": muster,
                "regel": regel,
                "typ": typ,
                "gewicht": round(gewicht, 2),
                "swap_type": nr.get("swap_type"),
                "support_count": nr.get("support_count", 0),
                "violation_count": nr.get("violation_count", 0),
                "avg_effect_when_applied": nr.get("avg_effect_when_applied", 0.0),
                "kontext": nr.get("kontext", {
                    "asset_klasse": [], "sektor": [], "vix_range": [0, 999],
                    "trend_4h": "", "regime": ["bear", "seitwaerts", "bull"],
                    "min_konfidenz": 0,
                }),
                "benchmark_ticker": nr.get("benchmark_ticker"),
                "conf_cap": nr.get("conf_cap"),
                "created_at": jetzt,
                "updated_at": jetzt,
                "last_seen_at": jetzt,
                "decay_lambda": 0.01,
                "effektiv_gewicht": round(gewicht, 2),
                # Block2: Versions-/Lifecycle-Metadaten
                "shadow": nr.get("shadow", True),  # neue Regeln starten als shadow
                "oos_confirmed": nr.get("oos_confirmed", False),
                "freigabe_status": nr.get("freigabe_status", "nicht_freigegeben"),
                "prioritaet": nr.get("prioritaet", 1 if typ in ("anti", "swap", "meta_conf_cap") else 2),
                "konfliktgruppe": nr.get("konfliktgruppe", muster[:30]),
                "created_in_version": _regelstand_meta_lesen().get("regelstand_version", 0),
                "last_validated_version": 0,
                "last_validated_at": None,
            })
    # Anti-/swap-/opportunitaet-/meta_conf_cap-Regeln immer behalten; positiv max. 20
    immer_behalten = ("anti", "swap", "opportunitaet", "meta_conf_cap")
    anti = [r for r in regeln if r.get("typ") in immer_behalten]
    positiv = [r for r in regeln if r.get("typ") == "positiv"]
    # R2: Decay-respektierende Sortierung (effektiv_gewicht, nicht rohes gewicht)
    _gw = lambda r: abs(float(r.get("effektiv_gewicht", r.get("gewicht", 0))))
    positiv.sort(key=_gw, reverse=True)
    positiv = positiv[:20 - len(anti)] if len(anti) < 20 else []
    anti.sort(key=_gw, reverse=True)
    regeln = positiv + anti
    _schreiben(regeln)
    # Kompatibler Export für alte Loader
    _export_legacy(regeln)
    return regeln


def _export_legacy(regeln):
    """Schreibt ki_regeln.json im alten Format (für Backcompat)."""
    alt = []
    for r in regeln:
        alt.append({
            "muster": r.get("muster", ""),
            "regel": r.get("regel", ""),
            "gewicht": r.get("effektiv_gewicht", r.get("gewicht", 0)),
            "anti": r.get("typ") == "anti",
            "zeit": r.get("updated_at", _now_iso()),
        })
    with open(REGELN_LEGACY, "w", encoding="utf-8") as f:
        json.dump(alt, f, ensure_ascii=False, indent=2)


def regel_qualitaet(regel):
    """Qualitäts-Score für Sortierung (S3.3.2): Bestätigungsrate * Effekt."""
    ges = (regel.get("support_count", 0) or 0) + (regel.get("violation_count", 0) or 0)
    if ges == 0:
        return float(regel.get("effektiv_gewicht", regel.get("gewicht", 0)))
    quote = regel.get("support_count", 0) / ges
    eff = regel.get("avg_effect_when_applied", 0) or 0
    return round(quote * abs(eff), 3)


# ────────────────────────────────────────────────────────────
# Prio 2: Regel-Lebenszyklus + Konflikte
# ────────────────────────────────────────────────────────────

# Aktionen, die eine Regel betrifft (kaufen/verkaufen/halten)
_AKTION_WOERTER = ("kaufen", "verkaufen", "halten")


def _regel_aktion(regel):
    """Extrahiert die betroffene Aktion aus muster/regel (oder None)."""
    text = (str(regel.get("muster", "")) + " " + str(regel.get("regel", ""))).lower()
    for a in _AKTION_WOERTER:
        if a in text:
            return a
    return None


def _regel_asset_klasse(regel):
    """Asset-Klasse(n) aus kontext.asset_klasse (oder [])."""
    k = regel.get("kontext") or {}
    ak = k.get("asset_klasse") or []
    return [a for a in ak if a]  # leere Strings raus


def finde_konflikte(regeln=None):
    """Findet widersprüchliche Regeln (Prio 2).

    Ein Konflikt liegt vor, wenn:
      - Zwei Regeln betreffen dieselbe Aktion UND dieselbe Asset-Klasse
      - ABER gegensätzlichen Typ (eine anti/verbot, eine positiv/erlaubt)
      - UND beide noch aktiv (effektiv_gewicht über Schwelle)

    Beispiel: '[Anti] halten bei crypto' (verbot) vs. '[Reflexion] halten
    bei core' (positiv) → KONFLIKT, wenn 'core' als crypto-gegenteil
    interpretiert wird. Robust: nur bei exakt gleicher Asset-Klasse.

    Return: Liste von {a, b, aktion, asset_klasse, befund}
    """
    if regeln is None:
        regeln = lade_regeln()
    if len(regeln) < 2:
        return []

    # Aktive Regeln (nicht archiviert)
    aktive = [r for r in regeln
              if not r.get("archiviert")
              and abs(float(r.get("effektiv_gewicht", r.get("gewicht", 0)))) >= 0.3]
    konflikte = []
    for i in range(len(aktive)):
        for j in range(i + 1, len(aktive)):
            a, b = aktive[i], aktive[j]
            akt_a = _regel_aktion(a)
            akt_b = _regel_aktion(b)
            if not akt_a or akt_a != akt_b:
                continue  # verschiedene Aktion → kein direkter Konflikt
            ak_a = set(_regel_asset_klasse(a))
            ak_b = set(_regel_asset_klasse(b))
            # Gemeinsame Asset-Klassen?
            gemeinsam = ak_a & ak_b
            if not gemeinsam:
                continue
            # Gegensätzlicher Typ?
            typ_a = a.get("typ", "anti" if float(a.get("gewicht", 0)) < 0 else "positiv")
            typ_b = b.get("typ", "anti" if float(b.get("gewicht", 0)) < 0 else "positiv")
            anti_a = typ_a in ("anti", "swap") and float(a.get("gewicht", 0)) < 0
            anti_b = typ_b in ("anti", "swap") and float(b.get("gewicht", 0)) < 0
            # Einer verbietet, einer erlaubt dieselbe Aktion bei gleicher AK
            if anti_a != anti_b:
                konflikte.append({
                    "a": a.get("muster", ""),
                    "b": b.get("muster", ""),
                    "aktion": akt_a,
                    "asset_klasse": sorted(gemeinsam),
                    "befund": (f"Widerspruch: eine Regel verbietet '{akt_a}' bei "
                               f"{'/'.join(sorted(gemeinsam))}, die andere erlaubt es"),
                })
    return konflikte


def lebenszyklus_status(regel):
    """Status einer Regel (Prio 2 + Prio4): unbestätigt | stabil | wackelig | veraltet.

    - unbestätigt: zu wenig Samples (< min_samples) ODER keine OOS-Bestätigung
    - veraltet:    effektiv_gewicht < 0.3 (Anti: |ew| < 0.3)
    - wackelig:    violation_count > support_count
    - stabil:      sonst
    """
    from settings_loader import lernen as _lernen
    min_samples = int(_lernen("min_samples", 5))
    ew = abs(float(regel.get("effektiv_gewicht", regel.get("gewicht", 0))))
    sup = regel.get("support_count", 0) or 0
    vio = regel.get("violation_count", 0) or 0
    oos = bool(regel.get("oos_confirmed", False))
    fg = regel.get("freigabe_status", "nicht_freigegeben")
    if regel.get("shadow"):
        return "shadow"
    if fg == "gesperrt":
        return "archiviert"
    if sup < min_samples or not oos:
        return "unbestätigt"
    if ew < 0.3:
        return "veraltet"
    if vio > sup:
        return "wackelig"
    return "stabil"


# ── Block 3: Shadow-/Live-Gating ──────────────────────────────────────────
def is_live_allowed(regel):
    """True nur wenn Regel im Live-Pfad wirken darf.

    Bedingungen:
    - nicht shadow
    - freigabe_status == 'freigegeben'
    - nicht archiviert
    - nicht gesperrt
    """
    if regel.get("shadow"):
        return False
    if regel.get("freigabe_status") != "freigegeben":
        return False
    if regel.get("archiviert"):
        return False
    if regel.get("freigabe_status") == "gesperrt":
        return False
    return True


def lade_live_regeln(include_decay=True):
    """Lädt NUR live-freigegebene Regeln (Block 3 Gate).

    Fallback: wenn keine freigegebenen Regeln vorhanden, wird der
    letzte freigegebene Regelstand (Regelstand-Meta) oder eine
    konservative Baseline zurückgegeben (vorhersehbar, nie implizit).
    """
    regeln = lade_regeln(include_decay=include_decay, nur_live=True)
    if regeln:
        return regeln
    # Fallback 1: letzter freigegebener Stand (regelstand_status == freigegeben)
    meta = _regelstand_meta_lesen()
    if meta.get("regelstand_status") == "freigegeben":
        # Regelstand war freigegeben -> alle Regeln dieses Stands laden (ohne nur_live)
        basis = lade_regeln(include_decay=include_decay)
        basis = [r for r in basis if r.get("freigabe_status") == "freigegeben" and not r.get("shadow")]
        if basis:
            return basis
    # Fallback 2: konservative Baseline (nur Anti-Regeln mit hohem Gewicht)
    alle = lade_regeln(include_decay=include_decay)
    baseline = [r for r in alle if r.get("typ") in ("anti", "swap") and abs(float(r.get("gewicht", 0) or 0)) >= 1.0]
    return baseline


def freigabe_pruefen(regel):
    """Prüft ob eine Regel die Freigabekriterien erfüllt (ohne sie freizugeben).

    Return: (ok: bool, gruende: list[str])
    Kriterien: Mindestfallzahl, OOS-Bestätigung, Konfliktfreiheit, Stabilität.
    """
    from settings_loader import lernen as _lernen
    min_samples = int(_lernen("min_samples", 5))
    gruende = []
    sup = regel.get("support_count", 0) or 0
    vio = regel.get("violation_count", 0) or 0
    oos = bool(regel.get("oos_confirmed", False))
    ew = abs(float(regel.get("effektiv_gewicht", regel.get("gewicht", 0)) or 0))
    if sup < min_samples:
        gruende.append(f"Fallzahl {sup} < {min_samples} (min_samples)")
    if not oos:
        gruende.append("keine OOS-Bestätigung")
    if vio > sup:
        gruende.append(f"Violations {vio} > Support {sup}")
    if ew < 0.3:
        gruende.append(f"eff.Gewicht {ew:.2f} < 0.3 (instabil)")
    return (len(gruende) == 0, gruende)


def freigabe_durchfuehren(regel_id):
    """Bewusste Freigabe-Aktion: setzt shadow=False, freigabe_status='freigegeben'.

    Nur zulässig wenn freigabe_pruefen() bestanden. Schreibt Regelstand-Meta
    (regelstand_status='freigegeben') mit. Kein Auto-Upgrade.
    """
    regeln = lade_regeln(include_decay=False, max_alter_tage=365)
    for r in regeln:
        if r.get("id") == regel_id:
            ok, gruende = freigabe_pruefen(r)
            if not ok:
                return False, gruende
            r["shadow"] = False
            r["freigabe_status"] = "freigegeben"
            r["freigegeben_am"] = _now_iso()
            speichere_regeln(regeln)
            return True, []
    return False, ["Regel nicht gefunden"]

    return "stabil"


def aktualisiere_lebenszyklus():
    """Prio 2: Markiert veraltete Regeln als archiviert (statt löschen).

    Regeln mit effektiv_gewicht < 0.3 nach Decay werden archiviert
    (Feld 'archiviert': True + 'archiviert_am': ISO). Beim Laden werden
    archivierte Regeln ausgeblendet, bleiben aber in der JSON erhalten
    (für Audit/Recovery).

    Return: Anzahl neu archivierter Regeln.
    """
    regeln = lade_regeln(include_decay=True, max_alter_tage=365)
    jetzt = _now_iso()
    neu_arch = 0
    for r in regeln:
        if r.get("archiviert"):
            continue
        ew = float(r.get("effektiv_gewicht", r.get("gewicht", 0)))
        # Anti-Regeln (Verbote) IMMER behalten – die sind wertvoll auch bei 0 Decay
        is_anti = r.get("typ") == "anti" or float(r.get("gewicht", 0)) < 0
        if ew < 0.3 and not is_anti:
            r["archiviert"] = True
            r["archiviert_am"] = jetzt
            neu_arch += 1
    if neu_arch:
        _schreiben(regeln)
        _export_legacy(regeln)
    return neu_arch


def regeln_mit_status(regeln=None):
    """Lädt Regeln + berechnet Qualität, Lebenszyklus-Status, Konflikte.

    Return: (regeln_bereichert, konflikte)
      regeln_bereichert: Liste mit zusätzlichen Feldern:
        - qualitaet (float)
        - status (stabil|wackelig|veraltet)
        - konflikt (bool, ob in Konflikt verwickelt)
    """
    if regeln is None:
        regeln = lade_regeln()
    konflikte = finde_konflikte(regeln)
    konflikt_muster = set()
    for k in konflikte:
        konflikt_muster.add(k["a"])
        konflikt_muster.add(k["b"])
    out = []
    for r in regeln:
        rr = dict(r)
        rr["qualitaet"] = regel_qualitaet(r)
        rr["status"] = lebenszyklus_status(r)
        rr["konflikt"] = r.get("muster", "") in konflikt_muster
        out.append(rr)
    return out, konflikte


GLOBAL_PFAD = os.path.join(BASE, "learned_rules_global.json")


def cross_depot_lernen():
    """Phase 7 (S3.8): Globale Muster über alle Depots hinweg erkennen.

    Liest alle Regeln aus learned_rules.json, gruppiert nach asset_klasse/sektor
    und prüft, ob Muster in ALLEN Depots gleicher Asset-Klasse auftreten.
    Schreibt learned_rules_global.json mit globalen Mustern.

    Vereinfachte Implementierung: Regeln mit identischem Muster-Präfix
    (z.B. '[Anti] halten bei crypto') die in >1 Depot vorkommen → global bestätigt.
    """
    regeln = lade_regeln(include_decay=False)
    if not regeln:
        return []
    # Gruppiere nach (muster, typ)
    gruppen = {}
    for r in regeln:
        key = (r.get("muster", ""), r.get("typ", ""))
        gruppen.setdefault(key, []).append(r)
    global_regeln = []
    for (muster, typ), liste in gruppen.items():
        if len(liste) >= 2:  # in ≥2 Depots → globales Muster
            sup = sum(r.get("support_count", 0) or 0 for r in liste)
            vio = sum(r.get("violation_count", 0) or 0 for r in liste)
            gew = round(sum(float(r.get("gewicht", 0)) for r in liste) / len(liste), 2)
            global_regeln.append({
                "muster": muster,
                "typ": typ,
                "gewicht": gew,
                "depot_count": len(liste),
                "support_count": sup,
                "violation_count": vio,
                "global": True,
                "kontext": liste[0].get("kontext", {}),
            })
    try:
        with open(GLOBAL_PFAD, "w", encoding="utf-8") as f:
            json.dump({"schema_version": "1.0", "global_rules": global_regeln},
                      f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return global_regeln


if __name__ == "__main__":
    n = migriere_aus_ki_regeln()
    print(f"Migration: {n} Regeln aus ki_regeln.json")
    rs = lade_regeln()
    print(f"learned_rules.json: {len(rs)} Regeln")
    for r in sorted(rs, key=lambda x: -float(x.get("effektiv_gewicht", 0))):
        print(f"  {r.get('effektiv_gewicht', 0):+.2f} | {r.get('typ'):8} | {r.get('muster', '')[:35]}")
    gr = cross_depot_lernen()
    print(f"learned_rules_global.json: {len(gr)} globale Muster")
