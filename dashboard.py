#!/usr/bin/env python3
"""Dashboard - Web-Oberflaeche fuer alle 20 Depots + Charts + News + Spekulation."""
import json, os, sys, time, glob, re, shutil
# timezone gehoert dazu: der Umrechnungsblock in api_ki_log
# nutzt timezone.utc fuer Zeitstempel ohne Suffix. Ohne den
# Import war das ein NameError, den ein except verschluckt
# hat - die Route lieferte zeit_berlin = None statt einer
# Umrechnung, ohne sichtbaren Fehler.
from datetime import datetime, timedelta, date, timezone
import yfinance as yf
from flask import Flask, send_from_directory, request, jsonify, session, redirect, url_for, make_response

# PHASE 4-6 (Server-Sicherheit): zentrale Sicherheitslogik
import security as sec
from security import (
    require_auth, require_role, require_recent_mfa, current_user,
    login_required_redirect,
)

BASE = os.path.dirname(os.path.abspath(__file__))
# 01.11.2026: /api/ops_news nutzte NEWS_CACHE ohne Definition (NameError ->
# Route lieferte immer ok:false). Gleicher Pfad wie news_monitor.py.
NEWS_CACHE = os.path.join(BASE, "news_cache.json")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5200
sys.path.insert(0, BASE)

# ─── Version (für Admin-Regelstand-Anzeige) ─────────────────────
try:
    with open(os.path.join(BASE, "version.json"), encoding="utf-8") as _vf:
        version = json.load(_vf)
except Exception:
    version = {"version": "?"}

# ─── Ticker → Firmenname (aus externer JSON geladen) ──────────
TICKER_NAMES = {}
NAMES_PATH = os.path.join(BASE, "static", "ticker_names.json")
if os.path.exists(NAMES_PATH):
    with open(NAMES_PATH, encoding="utf-8") as f:
        TICKER_NAMES = json.load(f)

# ─── Ticker → Sektor ─────────────────────────────────────────
TICKER_SEKTOR = {}
SEKTOR_PATH = os.path.join(BASE, "static", "ticker_sectors.json")
if os.path.exists(SEKTOR_PATH):
    with open(SEKTOR_PATH) as f:
        TICKER_SEKTOR = json.load(f)

def name_for(ticker):
    """Liefert 'Ticker – Firmenname' oder fallback nur Ticker."""
    if ticker in TICKER_NAMES:
        n = TICKER_NAMES[ticker]
        if "–" in n:  # hat schon Beschreibung
            return n
        # Füge Sektor hinzu falls bekannt
        sektor = TICKER_SEKTOR.get(ticker, "")
        if sektor:
            return f"{n} [{sektor}]"
        return n
    sektor = TICKER_SEKTOR.get(ticker, "")
    if sektor:
        return f"{ticker} [{sektor}]"
    return f"{ticker} – unbekannt"

# ─── Börsenzeiten ───────────────────────────────────────────
# Anzeige der Handelsplaetze. Die Handelszeiten stehen NICHT hier,
# sondern in boersen.BOERSEN - damit gelten Feiertage und die
# Tokioter Mittagspause automatisch auch im Dashboard.
#
# Vorher stand hier eine eigene Liste mit NYSE UND NASDAQ als zwei
# Zeilen. Beide handeln 09:30-16:00 Eastern - fuer eine
# Handelszeiten-Anzeige eine Zeile zu viel. Dazu waren die Zeiten
# doppelt gepflegt und kannten keine Feiertage.
#
# 'key' verweist auf boersen.BOERSEN, 'name' ist die Anzeige.
# New York deckt NYSE und NASDAQ ab; wer beide Namen will, findet
# sie in 'detail' und im Tooltip.
BOERSEN = [
    {"key": "US",    "name": "New York", "flag": "🇺🇸", "detail": "NYSE/NASDAQ"},
    {"key": "XETRA", "name": "Frankfurt", "flag": "🇪🇺", "detail": "Xetra"},
    {"key": "TSE",   "name": "Tokio",    "flag": "🇯🇵", "detail": "TSE"},
    {"key": "HK",    "name": "Hongkong", "flag": "🇭🇰", "detail": "HKEX"},
]
def _zone(name):
    """Liefert eine echte Zeitzone fuer name.

    Reihenfolge:
      1. zoneinfo - behandelt Europe/Berlin inklusive Sommerzeit.
      2. pytz mit .localize() - pytz.timezone() allein liefert den
         historischen LMT-Eintrag (Offset 0), nicht die Zone.
      3. None - dann rechnet der Aufrufer mit festem Offset.
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        pass
    try:
        import pytz
        return pytz.timezone(name)
    except Exception:
        return None


def _in(tz, dt):
    """Hängt eine Zeitzone an ein naives datetime an.

    zoneinfo akzeptiert tzinfo direkt, pytz braucht .localize().
    """
    if tz is None:
        return dt
    if hasattr(tz, "localize"):
        try:
            return tz.localize(dt)
        except Exception:
            return dt
    return dt.replace(tzinfo=tz)


def _nach_berlin(dt):
    """Umrechnung nach Berlin, oder None wenn keine Zone da ist.

    ACHTUNG: ein naives datetime wird als UTC-ZEITPUNKT behandelt,
    nicht als lokale Zeit. replace(tzinfo=Berlin) wuerde die
    Uhrzeit unverschoben lassen - aus 11:57 UTC wuerde 11:57
    CEST statt 13:57. Deshalb wird die Zone als UTC gesetzt und
    danach erst umgerechnet.
    """
    tz = _zone("Europe/Berlin")
    if tz is None:
        return None
    if dt.tzinfo is None:
        utc = _zone("UTC")
        dt = dt.replace(tzinfo=utc) if utc is not None else dt
    return dt.astimezone(tz)


def _zeitzone_kuerzel(dt_berlin):
    """MESZ im Sommer, MEZ im Winter - passend zum Zeitpunkt."""
    if dt_berlin is None:
        return "Berlin"
    return dt_berlin.tzname() or "Berlin"


BOERSEN_CACHE = None
BOERSEN_CACHE_TIME = 0

def profil_karten():
    """Phase 11 (§18): Profil-/Markt-Karten für Dashboard-Steuerzentrale.

    Zeigt: aktives Profil · aktiver Markt · aktiver Modus · freigegebener Regelstand ·
    Shadow/Live-Badge. Multi-Markt-Ausbau (US/DE/JP Shadow-Profile).
    """
    import profil_schema as ps

    karten = []
    profile = [
        ("us_shadow", "US"),
        ("de_shadow", "DE"),
        ("jp_shadow", "JP"),
    ]
    for name, markt in profile:
        p, fehler, warn = ps.lade_profil(name)
        if not p:
            karten.append({
                "markt": markt,
                "name": name,
                "status": "fehler",
                "modus": "shadow",
                "depotarten": [],
                "warnung": fehler,
            })
            continue
        karten.append({
            "markt": markt,
            "name": p.get("name", name),
            "status": "shadow" if p.get("modus") == "shadow" else "live",
            "modus": p.get("modus", "shadow"),
            "depotarten": p.get("depotarten", []),
            "maerkte": p.get("märkte", []),
            "base_currency": p.get("base_currency", "USD"),
            "regelstand_ref": p.get("regelstand_ref", "unbekannt"),
            "warnung": warn or "",
        })
    return karten


def _naechster_ist_geschliesstag(datum_berlin, boerse_key):
    """Ist der Tag ein Feiertag des jeweiligen Marktes?

    Wird fuer die 'naechste Oeffnung' gebraucht: ein Feiertag
    darf nicht als 'morgen offen' dastehen. Ohne diese Pruefung
    zeigte das Dashboard an einem Feiertag den Folgetag an.
    """
    try:
        from feiertage import markt_geschlossen
        markt_map = {"US": "US", "XETRA": "DE", "TSE": "JP", "HK": "HK"}
        m = markt_map.get(boerse_key, boerse_key)
        geschlossen, _grund = markt_geschlossen(m, datum_berlin.date())
        return bool(geschlossen)
    except Exception:
        return False


def market_status():
    """Status pro Handelsplatz + Gesamtuebersicht.

    Handelszeiten kommen aus boersen.BOERSEN, Feiertage und die
    Tokioter Mittagspause aus boersen.ist_offen(). Gerechnet wird
    in der Zone der Boerse, angezeigt wird Berliner Zeit.

    Die Anzeige zeigt vier echte Handelsplaetze mit vier
    Zeitzonen. New York deckt NYSE und NASDAQ ab - beide handeln
    09:30-16:00 Eastern, und zwei identische Zeilen sind fuer eine
    Handelszeiten-Anzeige eine zu viel.
    """
    global BOERSEN_CACHE, BOERSEN_CACHE_TIME
    now_ts = time.time()
    if BOERSEN_CACHE and (now_ts - BOERSEN_CACHE_TIME) < 30:
        return BOERSEN_CACHE

    try:
        import boersen as _bo
    except Exception:
        _bo = None

    try:
        from datetime import timezone as _tz
        jetzt = datetime.now(_tz.utc)
    except Exception:
        jetzt = datetime.utcnow()
    jetzt_berlin = _nach_berlin(jetzt)
    jetzt_berlin_text = (jetzt_berlin.strftime("%H:%M")
                         if jetzt_berlin else jetzt.strftime("%H:%M"))

    results = []
    overall_open = False

    for eintrag in BOERSEN:
        key = eintrag["key"]

        # Handelszeiten und Zone aus boersen.py - eine Quelle.
        if _bo is not None and key in _bo.BOERSEN:
            bd = _bo.BOERSEN[key]
            oh, om = bd["offen"]
            ch, cm = bd["zu"]
            tz_name = bd["tz"]
            zone_bezeichnung = eintrag["name"]
        else:
            # Sollte nicht vorkommen - boersen.py fehlt. Dann
            # wird nichts erfunden, der Platz wird als unbekannt
            # gemeldet statt mit geratenen Zeiten gefuellt.
            results.append({
                "name": eintrag["name"], "flag": eintrag["flag"],
                "status": "unknown", "label": "Zeiten unbekannt",
                "open": "?", "close": "?", "open_local": "?",
                "close_local": "?", "next_open": "?", "zone_kz": "",
                "zone_bezeichnung": eintrag["name"],
                "spanne_berlin": "?", "spanne_original": "",
                "jetzt_berlin": jetzt_berlin_text,
                "detail": eintrag.get("detail", ""), "feiertag": False,
            })
            continue

        tz = _zone(tz_name)
        if tz is None:
            now_local = jetzt
        elif hasattr(tz, "localize"):
            now_local = tz.localize(jetzt.replace(tzinfo=None))
        else:
            now_local = jetzt.astimezone(tz)

        open_t = now_local.replace(hour=oh, minute=om, second=0,
                                   microsecond=0)
        close_t = now_local.replace(hour=ch, minute=cm, second=0,
                                    microsecond=0)
        open_local = f"{oh:02d}:{om:02d}"
        close_local = f"{ch:02d}:{cm:02d}"

        # Anzeige in Berliner Zeit. Frankfurt IST Berliner Zeit,
        # dort wird nichts verschoben - und genau deshalb sieht
        # man dort keine zweite Zeitangabe.
        _ob = _nach_berlin(open_t)
        _cb = _nach_berlin(close_t)
        if _ob is not None and _cb is not None:
            open_mez = _ob.strftime("%H:%M")
            close_mez = _cb.strftime("%H:%M")
            zone_kz = _zeitzone_kuerzel(_ob)
        else:
            open_mez, close_mez, zone_kz = open_local, close_local, ""

        # Feiertag aus feiertage.py - genau dieselbe Quelle, die
        # der Scheduler benutzt. Vorher kannte das Dashboard keine.
        feiertag = False
        try:
            from feiertage import markt_geschlossen
            markt_map = {"US": "US", "XETRA": "DE", "TSE": "JP", "HK": "HK"}
            m = markt_map.get(key, key)
            geschlossen, grund = markt_geschlossen(m, now_local.date())
            if geschlossen:
                feiertag = True
        except Exception:
            pass

        # Status - boersen.ist_offen() kennt Feiertage UND die
        # Tokioter Mittagspause (11:30-12:30 JST).
        try:
            offen = _bo.ist_offen(key, now_local) if _bo else None
        except Exception:
            offen = None

        if feiertag:
            status = "closed"
            # Kein Datum im Text - das steht ohnehin in der
            # Spalte und in next_open. markt_geschlossen() liefert
            # nur ISO-Daten, keine Namen, und geratene Namen waeren
            # schlimmer als keine.
            label = "Feiertag · geschlossen"
        elif now_local.weekday() >= 5:
            status = "closed"
            label = "Wochenende · geschlossen"
        elif offen is True:
            status = "open"
            min_bis = (close_t - now_local).total_seconds() // 60
            label = f"Offen bis {close_mez} ({int(min_bis)} Min)"
        elif key == "TSE" and 11 * 60 + 30 <= now_local.hour * 60 \
                + now_local.minute < 12 * 60 + 30:
            # Mittagspause: 'zu' ist richtig, 'offen bis' waere
            # eine falsche Zusage.
            status = "closed"
            label = "Mittagspause bis 12:30"
        elif now_local < open_t:
            status = "pre"
            min_bis = (open_t - now_local).total_seconds() // 60
            # Mit Wochentag: 02:00 Berliner Zeit kann heute oder
            # morgen sein - bei Tokio und Hongkong ist das der
            # Normalfall, weil ihr Handel in einer anderen
            # Tagesphase liegt.
            _wt = _nach_berlin(open_t)
            _wtage = _wt.strftime("%a %d.%m.") if _wt else ""
            label = f"Öffnet {_wtage} {open_mez} ({int(min_bis)} Min)"
        elif now_local < close_t:
            status = "open"
            min_bis = (close_t - now_local).total_seconds() // 60
            label = f"Offen bis {close_mez} ({int(min_bis)} Min)"
        else:
            status = "closed"
            # Die naechste Oeffnung wird unten berechnet; hier
            # erstmal nur der Platzhalter, danach wird das Label
            # mit dem fertigen Datum ergaenzt.
            label = "Geschlossen"

        # Naechste Oeffnung - ueber die volle Woche, damit ein
        # Feiertag nicht als 'morgen' dasteht.
        next_open = now_local.replace(hour=oh, minute=om, second=0,
                                      microsecond=0)
        if status in ("open", "pre"):
            pass  # heute noch
        else:
            for _ in range(8):
                next_open += timedelta(days=1)
                if next_open.weekday() >= 5:
                    continue
                if _naechster_ist_geschliesstag(next_open, key):
                    continue
                break
        # Fuer die Anzeige nach Berlin umrechnen. Gerechnet wurde
        # oben in der Zone der Boerse - New York 09:30 Eastern ist
        # 15:30 Berliner Zeit und laesst sich sonst wie ein
        # Vormittag lesen.
        _no_berlin = _nach_berlin(next_open)
        if _no_berlin is not None:
            next_open_str = _no_berlin.strftime("%a %d.%m. %H:%M")
            naechste_uhr = _no_berlin.strftime("%H:%M")
            naechste_tag = _no_berlin.strftime("%a %d.%m.")
        else:
            next_open_str = next_open.strftime("%a %d.%m. %H:%M")
            naechste_uhr = next_open.strftime("%H:%M")
            naechste_tag = next_open.strftime("%a %d.%m.")

        # Das Label geschlossener Markets mit Datum fuellen. Fuer
        # Tokio und Hongkong ist die Uhrzeit ohne Datum mehrdeutig -
        # ihr Handel liegt in einer anderen Tagesphase als der
        # Berliner Nachmittag.
        if status == "closed":
            label = f"Geschlossen · öffnet {naechste_tag} {naechste_uhr}"

        if status == "open":
            overall_open = True

        ist_berlin = (zone_bezeichnung == "Frankfurt")
        results.append({
            "name": eintrag["name"],
            "flag": eintrag["flag"],
            "detail": eintrag.get("detail", ""),
            "status": status,
            "open": open_mez,
            "close": close_mez,
            "open_local": open_local,
            "close_local": close_local,
            "label": label,
            "next_open": next_open_str,
            "zone_kz": zone_kz,
            "zone_bezeichnung": zone_bezeichnung,
            "spanne_berlin": f"{open_mez}-{close_mez}",
            "spanne_original": "" if ist_berlin
                               else f"{open_local}-{close_local}",
            "jetzt_berlin": jetzt_berlin_text,
            "feiertag": feiertag,
            # Fuer die Tooltip-Zeile: bei geschlossenen Markets
            # ist 'wann wieder offen' die eigentliche Information.
            "hinweis": (f"wieder offen {naechste_tag} {naechste_uhr}"
                        if status == "closed" else ""),
        })

    any_open = any(r["status"] == "open" for r in results)
    any_pre = any(r["status"] == "pre" for r in results)
    ges_status = "open" if any_open else ("pre" if any_pre else "closed")
    offene = [r["name"] for r in results if r["status"] == "open"]

    # Bei geschlossenem Markt ist die interessierende Frage nicht
    # 'zu oder auf', sondern 'wann wieder und wo'. Das wird aus
    # den bereits berechneten next_open-Werten der Liste gebildet -
    # keine zweite Berechnung, damit die Kopfzeile nicht von der
    # Tabelle abweichen kann.
    ges_label = "🟢 Börsen geöffnet" if any_open else "🔴 Börsen geschlossen"
    if not any_open:
        termine = []
        for r in results:
            no = r.get("next_open")
            if not no or "?" in no:
                continue
            # '%a %d.%m. %H:%M' ist lexikografisch sortierbar:
            # der Wochentag steht vorn, dann der Tag. Fuer den
            # Vergleich reicht die Uhrzeit des Tages.
            try:
                stunde = int(no.split()[-1].split(":")[0])
            except (ValueError, IndexError):
                continue
            termine.append((no, stunde, r.get("name")))
        if termine:
            # Gleiche Stunde: nach Wochentag/Datum sortieren, nicht
            # nach Uhrzeit - sonst gewinnt Tokio (02:00) vor
            # New York (15:30), obwohl New York zuerst auf ist.
            termine.sort(key=lambda t: t[0][:10])
            no, _h, name = termine[0]
            ges_label = f"🔴 Geschlossen · nächste: {no} {name}"

    out = (ges_status, ges_label, results)
    BOERSEN_CACHE = out
    BOERSEN_CACHE_TIME = time.time()
    return out


def portfolio_verlauf(tage=7, mode=None):
    """Aggregiert depot_*/etf_*/spec_depots historie zu 4 Serien (gesamt/aktien/etf/spec).

    Forward-fill: jedes Depot traegt seinen letzten bekannten Wert <= Zeitpunkt bei,
    damit die Summe pro Zeitpunkt alle Depots enthaelt (keine Luecken durch
    unterschiedliche Speicher-Intervalle). Rendite gegen Startkapital (start_wert/start).
    PHASE 5 (§9): mode='shadow'|'paper' bestimmt den Portfolio-Satz; None = shadow.
    Shadow- und Paper-Outcomes werden nie gemeinsam bewertet (Forderung §9).
    """
    _hmode = mode if mode in ("shadow", "paper") else "shadow"
    cutoff = datetime.now() - timedelta(days=tage)

    # Pro Kategorie: liste von (zeit, wert) pro Depot
    kategorien = {"aktien": [], "etf": [], "spec": []}

    def _depot_historie(f, kat, wert_feld="wert"):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            return
        pts = []
        for h in d.get("historie", []):
            try:
                z = datetime.fromisoformat(h["zeit"])
            except Exception:
                continue
            if z < cutoff:
                continue
            w = float(h.get(wert_feld, 0) or 0)
            pts.append((z, w))
        if pts:
            kategorien[kat].append(pts)

    for risk in RISK_STUFEN:
        _depot_historie(depot_pfad(risk, mode=_hmode), "aktien")
    for risk in range(0, 100, 5):
        _depot_historie(os.path.join(BASE, f"etf_{risk:03d}.json" if _hmode != "paper" else f"etf_{risk:03d}_paper.json"), "etf")
    sdd = os.path.join(BASE, "spec_depots" if _hmode != "paper" else "spec_depots_paper")
    if os.path.isdir(sdd):
        for fn in os.listdir(sdd):
            if fn.endswith(".json"):
                _depot_historie(os.path.join(sdd, fn), "spec")

    # Alle Zeitpunkte (minutengenau) ueber alle Depots
    alle = set()
    for kat in kategorien.values():
        for pts in kat:
            for z, _w in pts:
                alle.add(z.replace(second=0, microsecond=0))
    alle = sorted(alle)

    def _serie(kat_pts):
        # forward-fill: pro Zeitpunkt summiere letzten bekannten Wert jedes Depots
        idx = [0] * len(kat_pts)
        out = []
        for z in alle:
            ssum = 0.0
            for i, pts in enumerate(kat_pts):
                while idx[i] + 1 < len(pts) and pts[idx[i] + 1][0] <= z:
                    idx[i] += 1
                if pts[idx[i]][0] <= z:
                    ssum += pts[idx[i]][1]
            out.append({"zeit": z.strftime("%Y-%m-%d %H:%M"), "wert": round(ssum, 2)})
        return out

    serien = {
        "aktien": _serie(kategorien["aktien"]),
        "etf": _serie(kategorien["etf"]),
        "spec": _serie(kategorien["spec"]),
    }
    # Gesamt = summe der 3 Serien pro Zeitpunkt
    ges = []
    for i, z in enumerate(alle):
        w = (serien["aktien"][i]["wert"] if i < len(serien["aktien"]) else 0) + \
            (serien["etf"][i]["wert"] if i < len(serien["etf"]) else 0) + \
            (serien["spec"][i]["wert"] if i < len(serien["spec"]) else 0)
        ges.append({"zeit": z.strftime("%Y-%m-%d %H:%M"), "wert": round(w, 2)})

    # Startkapital
    def _start_summe(kat):
        total = 0.0
        try:
            if kat == "aktien":
                for risk in RISK_STUFEN:
                    fp = depot_pfad(risk)
                    if os.path.exists(fp):
                        with open(fp, encoding="utf-8") as fh:
                            d = json.load(fh)
                            total += float(d.get("start_wert") or d.get("start") or 0)
            elif kat == "etf":
                for risk in range(0, 100, 5):
                    fp = os.path.join(BASE, f"etf_{risk:03d}.json")
                    if os.path.exists(fp):
                        with open(fp, encoding="utf-8") as fh:
                            d = json.load(fh)
                            total += float(d.get("start_wert") or d.get("start") or 0)
            elif kat == "spec":
                sdd = os.path.join(BASE, "spec_depots")
                if os.path.isdir(sdd):
                    for fn in os.listdir(sdd):
                        if fn.endswith(".json"):
                            with open(os.path.join(sdd, fn), encoding="utf-8") as fh:
                                total += float(json.load(fh).get("start") or 0)
        except Exception:
            pass
        return total

    starts = {"gesamt": 0, "aktien": 0, "etf": 0, "spec": 0}
    starts["aktien"] = _start_summe("aktien")
    starts["etf"] = _start_summe("etf")
    starts["spec"] = _start_summe("spec")
    starts["gesamt"] = starts["aktien"] + starts["etf"] + starts["spec"]

    def _mit_rendite(pts, basis):
        for pt in pts:
            pt["rendite"] = round((pt["wert"] / basis - 1) * 100, 2) if basis else 0.0
        return pts

    return {
        "gesamt": _mit_rendite(ges, starts["gesamt"]),
        "aktien": _mit_rendite(serien["aktien"], starts["aktien"]),
        "etf": _mit_rendite(serien["etf"], starts["etf"]),
        "spec": _mit_rendite(serien["spec"], starts["spec"]),
        "start_gesamt": round(starts["gesamt"], 2),
        "start_aktien": round(starts["aktien"], 2),
        "start_etf": round(starts["etf"], 2),
        "start_spec": round(starts["spec"], 2),
    }



def kategorie_trade_historie(kat, limit=50):
    """Sammelt alle Trades einer Kategorie (aktien/etf/spec) aus den Depot-JSONs.

    Liefert Liste von {zeit, depot_label, typ, ticker, menge, preis, grund}
    sortiert nach Zeit absteigend (neueste zuerst).
    """
    trades = []
    try:
        if kat == "aktien":
            for risk in RISK_STUFEN:
                fp = depot_pfad(risk)
                if not os.path.exists(fp):
                    continue
                with open(fp, encoding="utf-8") as fh:
                    d = json.load(fh)
                label = f"Risk {risk}"
                for t in d.get("trades", []):
                    t2 = dict(t)
                    t2["depot_label"] = label
                    t2["kategorie"] = "aktien"
                    trades.append(t2)
        elif kat == "etf":
            for risk in range(0, 100, 5):
                fp = os.path.join(BASE, f"etf_{risk:03d}.json")
                if not os.path.exists(fp):
                    continue
                with open(fp, encoding="utf-8") as fh:
                    d = json.load(fh)
                stufe = d.get("stufe") or f"Risk {risk}"
                for t in d.get("trades", []):
                    t2 = dict(t)
                    t2["depot_label"] = stufe
                    t2["kategorie"] = "etf"
                    trades.append(t2)
        elif kat == "spec":
            sdd = os.path.join(BASE, "spec_depots")
            if os.path.isdir(sdd):
                for fn in os.listdir(sdd):
                    if not fn.endswith(".json"):
                        continue
                    with open(os.path.join(sdd, fn), encoding="utf-8") as fh:
                        d = json.load(fh)
                    for t in d.get("trades", []):
                        t2 = dict(t)
                        t2["depot_label"] = d.get("ticker", fn.replace(".json", ""))
                        t2["kategorie"] = "spec"
                        # Spec nutzt 'aktion' statt 'typ'
                        t2.setdefault("typ", t2.get("aktion"))
                        trades.append(t2)
    except Exception:
        pass
    # Neueste zuerst sortieren (Zeit als String vergleichbar bei ISO)
    trades.sort(key=lambda t: str(t.get("zeit", "")), reverse=True)
    return trades[:limit]


def boersen_chips():
    """Sammelt die BÖRSEN, DIE IM PORTFOLIO WIRKLICH VORKOMMEN + Wert-Anteil.

    Nutzt die 'exchanges'-Felder der Depots (von engine.py geschrieben) bzw.
    berechnet die Börse aus dem Ticker-Suffix via boersen.boerse_fuer_ticker.
    Zeigt NUR Börsen mit echten Positionen → kein Chip, wenn kein Titel dort.
    Crypto (kein klass. Handelsplatz) → '24/7' als eigener Chip.
    """
    from boersen import boerse_fuer_ticker, BOERSEN, ist_offen, status_mit_next_open

    # 1) Alle gehaltenen Ticker + ihre Börsen + ihre Werte sammeln
    boersen_werte = {}   # boerse -> summe werte
    gesamt = 0.0

    def _add(ticker, wert):
        nonlocal gesamt
        if wert <= 0:
            return
        gesamt += wert
        # Crypto? (aus spec_watch kategorie)
        b = boerse_fuer_ticker(ticker)
        # Crypto erkennen wir an bekannten Suffixen/Symbolen
        if ticker in ("BTC", "ETH", "SOL", "DOGE", "ADA", "XRP", "LTC", "BNB", "AVAX", "MATIC", "DOT", "LINK", "UNI", "ATOM"):
            b = "CRYPTO"
        boersen_werte[b] = boersen_werte.get(b, 0.0) + wert

    # Aktien-Depots ( haben 'exchanges'-Feld, sonst Ticker-Suffix )
    for risk in RISK_STUFEN:
        dp = depot_pfad(risk)
        if os.path.exists(dp):
            with open(dp) as f:
                d = json.load(f)
            ex = d.get("exchanges", {})
            for t, pos in d.get("positions", {}).items():
                shares = pos.get("shares", 0)
                if shares > 0:
                    kurs = pos.get("avg_price", 0)
                    w = shares * kurs
                    b = ex.get(t) or boerse_fuer_ticker(t)
                    if b == "US":
                        b = "NYSE/NASDAQ"
                    _add(t, w)

    # ETF-Depots
    for risk in range(0, 100, 5):
        ep = os.path.join(BASE, f"etf_{risk:03d}.json")
        if os.path.exists(ep):
            with open(ep) as f:
                d = json.load(f)
            for t, pos in d.get("positions", {}).items():
                shares = pos.get("shares", 0)
                if shares > 0:
                    kurs = pos.get("avg_price", 0)
                    _add(t, shares * kurs)

    # Spec-Depots
    sdd = os.path.join(BASE, "spec_depots")
    if os.path.isdir(sdd):
        for fn in os.listdir(sdd):
            if fn.endswith(".json"):
                with open(os.path.join(sdd, fn)) as f:
                    d = json.load(f)
                if d.get("shares", 0) > 0:
                    _add(d.get("ticker", ""), d.get("shares", 0) * d.get("avg_price", 0))

    # 2) Chips bauen (nur Börsen mit Wert > 0)
    chips = []
    for b, wert in sorted(boersen_werte.items(), key=lambda x: -x[1]):
        if wert <= 0:
            continue
        anteil = round(wert / gesamt * 100) if gesamt > 0 else 0
        if b == "CRYPTO":
            chips.append({"boerse": "CRYPTO", "label": "🪙 Crypto", "anteil": anteil,
                          "status": "open", "offen_text": "24/7", "next_open": "-"})
        else:
            offen = ist_offen(b) if b in BOERSEN else False
            label = BOERSEN.get(b, {}).get("label", b)
            kurz = label.split(" ", 1)[-1] if " " in label else label
            # Naechste Oeffnung aus boersen.status_mit_next_open()
            next_open_str = "-"
            try:
                for st in status_mit_next_open():
                    if st["boerse"] == b:
                        next_open_str = st["next_open"]
                        break
            except Exception:
                pass
            chips.append({"boerse": b, "label": kurz, "anteil": anteil,
                          "status": "open" if offen else "closed",
                          "offen_text": "geöffnet" if offen else "geschlossen",
                          "next_open": next_open_str})
    return chips

# ─── SPX Benchmark ───────────────────────────────────────────
SPX_CACHE = None
SPX_CACHE_TIME = 0

def get_spx_data():
    """Holt SPX Schlusskurse der letzten 60 Tage."""
    global SPX_CACHE, SPX_CACHE_TIME
    now = time.time()
    if SPX_CACHE and (now - SPX_CACHE_TIME) < 3600:
        return SPX_CACHE
    try:
        spx = yf.download("^GSPC", period="2mo", interval="1d", progress=False, auto_adjust=True)
        if spx.empty:
            spx = yf.download("SPY", period="2mo", interval="1d", progress=False, auto_adjust=True)
            if spx.empty:
                return []
        # Handle MultiIndex columns
        if hasattr(spx.columns, 'nlevels') and spx.columns.nlevels > 1:
            close = spx['Close'].iloc[:, 0]  # erste (einzige) Spalte unter Close
        elif 'Close' in spx:
            close = spx['Close']
        else:
            return []
        close = close.dropna()
        data = []
        for d, v in close.items():
            # d kann Datum oder Tupel sein (MultiIndex row)
            if isinstance(d, tuple):
                d = d[0]
            iso = d.isoformat() if hasattr(d, 'isoformat') else str(d)
            data.append({"zeit": iso, "wert": round(float(v), 2)})
        SPX_CACHE = data
        SPX_CACHE_TIME = now
        return data
    except Exception as e:
        return []

# ─── Notifications ───────────────────────────────────────────
NOTIF_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notifications.json")

def check_notifications(depots):
    """Prüft Alarme: Drawdown, Top-Performer, etc. Schreibt in JSON."""
    notifs = []
    for dep in depots:
        if dep.get("max_dd", 0) > 15:
            notifs.append({
                "typ": "warn",
                "text": f"Risk {dep['risk']}: MaxDD {dep['max_dd']}%",
                "zeit": datetime.now().isoformat(),
            })
        if dep.get("rendite", 0) > 5:
            notifs.append({
                "typ": "good",
                "text": f"Risk {dep['risk']}: +{dep['rendite']}% Rendite",
                "zeit": datetime.now().isoformat(),
            })
    # Gesamt-Drawdown check
    ges_wert = sum(d["wert"] for d in depots)
    ges_start = sum(d["start"] for d in depots)
    ges_rendite = round((ges_wert / ges_start - 1) * 100, 2) if ges_start > 0 else 0.0

    # Also compute inside check_notifications for backwards compat
    if ges_wert < ges_start * 0.85:
        notifs.append({
            "typ": "alert",
            "text": f"Gesamt-Wert -{((1-ges_wert/ges_start)*100):.1f}% unter 85%",
            "zeit": datetime.now().isoformat(),
        })
    # Nur letzte 50 halten
    if os.path.exists(NOTIF_FILE):
        try:
            with open(NOTIF_FILE) as f:
                old = json.load(f)
            notifs = old[-40:] + notifs
        except:
            pass
    notifs = notifs[-50:]
    with open(NOTIF_FILE, "w") as f:
        json.dump(notifs, f, indent=2)
    return notifs[-10:]

app = Flask(__name__, static_folder=os.path.join(BASE, "assets"), static_url_path="/assets")

def _api_key_ok():
    """Prueft den X-API-Key gegen DASHBOARD_API_KEY, timing-sicher.

    Ein einziger Ort im Code entscheidet damit, ob eine
    Maschinen-Anbindung ohne Session-Cookie erlaubt ist.
    """
    import hmac as _hmac
    erwartet = os.getenv("DASHBOARD_API_KEY")
    if not erwartet:
        return False
    given = request.headers.get("X-API-Key")
    if not given:
        return False
    return _hmac.compare_digest(str(given), str(erwartet))





def _ops_auth_ok():
    """Ops-Routen: Session ODER gueltiger API-Key.

    Wird von den ops-Routen gemeinsam genutzt. Ohne diese Zusammen-
    fuehrung pruefen acht Routen jeweils nur die Session, und die
    Maschinen-Anbindung (Alerting, Monitoring) waere tot.
    """
    if _api_key_ok():
        return True
    u = sec.current_user()
    return bool(u) and sec.access_level_met(u["role"], "AUTHENTICATED")
# API-Key Auth für /api/ops_* Endpoints (erlaubt UI ohne Session-Cookie)
@app.before_request
def _api_key_auth():
    if request.path.startswith("/api/ops_"):
        # 1) Session-Cookie prüfen (bestehende Auth)
        if "user_id" in session:
            return
        # 2) X-API-Key Header prüfen (für UI-Integration)
        api_key = request.headers.get("X-API-Key")
        expected = os.getenv("DASHBOARD_API_KEY")
        if expected and api_key == expected:
            return
        return jsonify({"error": "unauthorized"}), 401



# Explizite Asset-Route (robust, vor allen anderen)
@app.route("/assets/<path:dateiname>")
def serve_assets(dateiname):
    pfad = os.path.join(BASE, "assets", dateiname)
    if os.path.exists(pfad):
        from flask import send_file
        return send_file(pfad)
    return ("Not Found", 404)

from risk_profile import RISK_STUFEN, get_params
def _get_tid():
    """PHASE 4: Aktuelle Tenant-ID aus Session-Kontext (nie Client)."""
    try:
        import security as _sec
        return _sec.get_current_tenant() or 1
    except Exception:
        return 1


def _tenant_scoped_depot_files(tenant_id, mode=None, basis=None):
    """PHASE 4: Gibt nur Depot-Pfade zurueck, die zum Tenant gehoeren.
    Depot-JSONs tragen ein Feld 'tenant_id' (Default 1). Fehlt es, gilt
    Default-Tenant 1. So sieht Tenant B niemals Depots von Tenant A.
    PHASE 5 (§9): mode='shadow'|'paper' filtert zusaetzlich nach Portfolio-Modus —
    Shadow- und Paper-Depots werden nie vermischt (Forderung §9).
    Fehlt das mode-Feld in einer Datei, gilt 'shadow' (Bestand).
    basis: optionaler Ordner statt BASE. Nur fuer Tests - sonst schreibt
    ein Test in den Betrieb und laesst Dateien liegen, die danach als
    echte Depots im Dashboard erscheinen (29.09.2026)."""
    import json as _json, glob as _glob
    scoped = {"depot": [], "etf": [], "spec": []}
    _basis = basis or BASE
    # Aktien-Depots: alle depot_*.json scannen (nicht nur RISK_STUFEN)
    for dp in _glob.glob(os.path.join(_basis, "depot_*.json")):
        try:
            with open(dp) as f:
                d = _json.load(f)
            if d.get("tenant_id", 1) == tenant_id:
                if mode is None or d.get("mode", "shadow") == mode:
                    scoped["depot"].append(dp)
        except Exception:
            pass
    # ETF-Depots: alle etf_*.json scannen
    for ep in _glob.glob(os.path.join(_basis, "etf_*.json")):
        try:
            with open(ep) as f:
                d = _json.load(f)
            if d.get("tenant_id", 1) == tenant_id:
                if mode is None or d.get("mode", "shadow") == mode:
                    scoped["etf"].append(ep)
        except Exception:
            pass
    # Spec-Depots: shadow -> spec_depots/, paper -> spec_depots_paper/
    for _dir, _m in ((os.path.join(_basis, "spec_depots"), "shadow"),
                     (os.path.join(_basis, "spec_depots_paper"), "paper")):
        if not os.path.isdir(_dir):
            continue
        for fn in os.listdir(_dir):
            if fn.endswith(".json"):
                fp = os.path.join(_dir, fn)
                try:
                    with open(fp) as f:
                        d = _json.load(f)
                    if d.get("tenant_id", 1) == tenant_id:
                        if mode is None or d.get("mode", _m) == mode:
                            scoped["spec"].append(fp)
                except Exception:
                    pass
    return scoped


def depot_pfad(risk, mode="shadow"):
    # PHASE 5 (§9): PAPER nutzt depot_<risk>_paper.json (getrenntes Portfolio)
    if mode == "paper":
        return os.path.join(BASE, "depot_%03d_paper.json" % risk)
    return os.path.join(BASE, "depot_%03d.json" % risk)


def regelstand_aggregat(ki_regeln):
    """Block 6: Aggregiert den Regelstand für Dashboard-Anzeige.

    Liefert: anzahl_gesamt, freigegeben, shadow, archiviert, aktiv,
    letzter_sync (regelstand_version der neuesten Regel), oos_bestätigt.
    """
    ges = len(ki_regeln)
    freigegeben = sum(1 for r in ki_regeln
                      if str(r.get("freigabe_status", "")) == "freigegeben")
    shadow = sum(1 for r in ki_regeln if r.get("shadow"))
    archiviert = sum(1 for r in ki_regeln if r.get("archiviert"))
    aktiv = sum(1 for r in ki_regeln if str(r.get("status", "")).lower()
                not in ("veraltet", "expired", "inaktiv"))
    oos = sum(1 for r in ki_regeln if r.get("oos_confirmed"))
    # letzter Sync: neueste last_validated_version / created_at
    letzter = ""
    for r in ki_regeln:
        lv = str(r.get("last_validated_version") or r.get("updated_at")
                 or r.get("created_at") or "")
        if lv > letzter:
            letzter = lv
    return {
        "anzahl_gesamt": ges,
        "freigegeben": freigegeben,
        "shadow": shadow,
        "archiviert": archiviert,
        "aktiv": aktiv,
        "oos_bestätigt": oos,
        "letzter_sync": letzter[:19].replace("T", " ") if letzter else "—",
    }


@app.route("/dashboard")
def index():
    return send_from_directory(BASE, "dashboard.html")


def _build_vergleich():
    """Vergleichs-Daten fuer Dashboard-Karten: Stand gestern Abend, Trades heute,
    Tages-Schnitt. Liest tagesverlauf.json (Tages-Snapshots) + ki_log.json.
    Fails soft: bei Fehler leeres Dict (Karten zeigen nichts Extra)."""
    import json as _json
    out = {"gestrig": None, "trades_heute": {"kaufen": 0, "verkaufen": 0},
           "schnitt_pro_tag": None, "tage": 0}
    try:
        # 1) tagesverlauf.json -> letzter Eintrag = Stand gestern Abend
        tv = os.path.join(BASE, "tagesverlauf.json")
        if os.path.exists(tv):
            verl = _json.load(open(tv, encoding="utf-8"))
            if isinstance(verl, list) and verl:
                letzter = verl[-1]  # neueste = gestern (heute wird abends erst geschrieben)
                out["gestrig"] = {
                    "datum": letzter.get("datum"),
                    "ges_wert": letzter.get("ges_wert"),
                    "pnl_pct": letzter.get("pnl_pct"),
                    "kategorien": letzter.get("kategorien", {}),
                }
                # Schnitt: Ø taegliche Aenderung ges_wert ueber die Historie
                werte = [e.get("ges_wert") for e in verl if e.get("ges_wert")]
                if len(werte) >= 2:
                    # Ø absolute Aenderung pro Schritt
                    diffs = [abs(werte[i] - werte[i-1]) for i in range(1, len(werte))]
                    out["schnitt_pro_tag"] = round(sum(diffs) / len(diffs), 2)
                    out["tage"] = len(werte)
        # 2) ki_log.json -> Trades heute (seit 00:00 Uhr lokal)
        kl = os.path.join(BASE, "ki_log.json")
        if os.path.exists(kl):
            heute = time.strftime("%Y-%m-%d")
            log = _json.load(open(kl, encoding="utf-8"))
            k = sum(1 for e in log if str(e.get("zeit", "")).startswith(heute) and e.get("aktion") == "kaufen")
            v = sum(1 for e in log if str(e.get("zeit", "")).startswith(heute) and e.get("aktion") == "verkaufen")
            out["trades_heute"] = {"kaufen": k, "verkaufen": v}
    except Exception:
        pass
    return out


# 30.09.2026: /data lieferte HTTP 500.
#
#   "trades": len(d.get("trades", [])),
#
# Der Default [] greift nur, wenn der Schluessel FEHLT. In den
# Spekulationsdepots ist "trades" eine Liste von Belegen, in den
# Aktien- und ETF-Depots ein Zaehler. Beide Formen kommen im
# Betrieb vor, mit einer Zahl bricht len() ab:
#
#   TypeError: object of type 'int' has no len()
#
# Der Helfer nimmt beide Formen an. Drei Stellen betroffen.
def _trades_anzahl(d):
    t = (d or {}).get("trades")
    if isinstance(t, list):
        return len(t)
    if isinstance(t, (int, float)):
        return int(t)
    return 0


@app.route("/data")
def data():
    # Modus-Filter aus Query (?mode=shadow|paper|beide) — Frontend waehlt ueber
    # PF_FILTER.modus. Default "beide" = shadow + paper als GETRENUTE Karten.
    _req_mode = request.args.get("mode", "beide")
    # PHASE 1 (01.10.2026): "slim=1" liefert nur die Depotfelder.
    # Gemessen: ki_log + regel_history + system_log + ki_regeln sind
    # 1.001.567 von 1.203.699 Bytes (83 %) und werden ausschliesslich
    # von panel-overview und den KI-Tabs gelesen, nicht von den Karten.
    _slim = (request.args.get("slim", "") or "").lower() in ("1", "true", "ja")
    # ── Cache: nur alle 60s neu berechnen (yfinance entlasten) ──
    # PHASE 3 (Tenant-Isolation): Cache ist TENANT-SCOPED — Tenant B bekommt
    # nie die gecachten Portfolio-Daten von Tenant A (Forderung §2.3).
    now = time.time()
    try:
        import security as _sec
        _tid = _sec.get_current_tenant() or 1
        _dmode = _sec.get_trading_mode(_tid) or "SHADOW"
    except Exception:
        _tid = 1
        _dmode = "SHADOW"
    # PHASE 5 (§9): Portfolio-Satz des aktiven Modus — SHADOW -> shadow-Depots,
    # PAPER -> paper-Depots. Cache ist tenant- UND mode-keyed, damit ein
    # Moduswechsel nie gecachte Daten des anderen Portfolios liefert.
    _pmode = "paper" if _dmode == "PAPER" else "shadow"
    # Cache-Key = gewaehlter Request-Mode (shadow/paper/beide)
    _cache_mode = (_req_mode or "beide")
    if hasattr(data, "_cache") and data._cache and \
            getattr(data, "_cache_tid", None) == _tid and \
            getattr(data, "_cache_mode", None) == _cache_mode and \
            bool(getattr(data, "_cache_slim", False)) == bool(_slim) and \
            (now - data._cache_ts) < 60:
        return data._cache

    depots = []
    ALLE_TICKER = set()
    depot_raw_list = []
    # PHASE 4: Tenant-Scope — nur Dateien des aktiven Tenants (PHASE 3: _tid
    # stammt aus dem Cache-Check oben, kein zweiter Lookup)
    # PHASE 5: + Portfolio-Modus-Filter — lade Modi je nach _req_mode.
    # Der User waehlt im Frontend (PF_FILTER.modus: shadow/paper/alle), das
    # Backend liefert bei "alle"/"beide" BEIDE als GETRENUTE Karten (kein Merge).
    _mode = (_req_mode or "beide").lower()
    if _mode in ("shadow",):
        _scoped = _tenant_scoped_depot_files(_tid, mode="shadow")
    elif _mode in ("paper",):
        _scoped = _tenant_scoped_depot_files(_tid, mode="paper")
    else:  # beide / alle
        _scoped_shadow = _tenant_scoped_depot_files(_tid, mode="shadow")
        _scoped_paper = _tenant_scoped_depot_files(_tid, mode="paper")
        _scoped = {
            "depot": _scoped_shadow["depot"] + _scoped_paper["depot"],
            "etf": _scoped_shadow["etf"] + _scoped_paper["etf"],
            "spec": _scoped_shadow["spec"] + _scoped_paper["spec"],
        }
    # Aktien-Depots (nur Tenant) — Liste (mehrere Depots pro risk moeglich).
    # KEINE Merge mehr: shadow und paper bleiben GETRENUTE Karten mit eigenem
    # modus-Feld ("shadow"/"paper"). Das Frontend filtert ueber PF_FILTER.modus.
    depot_raw_list = []
    for dp in _scoped["depot"]:
        try:
            with open(dp) as f:
                d = json.load(f)
            _m = d.get("mode", "shadow")
            _bn = os.path.basename(dp).split(".")[0]
            _rk = _bn.split("_")[1]
            risk = int(_rk.split("_")[0]) if _rk.split("_")[0].isdigit() else int(_rk)
            depot_raw_list.append((risk, d, dp, {_m}))
            for s, pos_obj in d.get("positions", {}).items():
                if pos_obj.get("shares", 0) > 0:
                    ALLE_TICKER.add(s)
        except Exception:
            pass
    # ETF-Depots (nur Tenant)
    for ep in _scoped["etf"]:
        try:
            with open(ep) as f:
                d = json.load(f)
            for s, pos_obj in d.get("positions", {}).items():
                if pos_obj.get("shares", 0) > 0:
                    ALLE_TICKER.add(s)
        except Exception:
            pass
    # Spec-Depots (nur Tenant)
    for fp in _scoped["spec"]:
        try:
            with open(fp) as f:
                sd = json.load(f)
            if sd.get("ticker") and sd.get("shares", 0) > 0:
                ALLE_TICKER.add(sd["ticker"])
        except Exception:
            pass

    # PHASE 4 (01.10.2026): Kurse ueber marktdaten statt yf.download.
    #
    # GEMESSEN, beide Wege auf derselben Yahoo-API:
    #
    #   Titel   yf.download            42x marktdaten.hole_kurs
    #      4      0,35 s  (29 sleeps)      0,20 s  (0 sleeps)
    #      8      5,69 s (551 sleeps)      0,45 s  (0 sleeps)
    #     16     11,32 s (1101 sleeps)     0,96 s  (0 sleeps)
    #     42     10,91 s (1033 sleeps)     1,14 s  (0 sleeps)
    #
    # Der Sammelabruf faellt ab etwa 8 Titeln in einen Retry-Backoff;
    # der Einzelweg tut das nicht. Ueber /data gemessen: 24,15 s im
    # Kaltbau, davon 23,62 s in time.sleep.
    #
    # marktdaten.hole_kurs hat zwei Dinge, die yf.download nicht hat:
    #   - 5-Minuten-Cache (marktdaten.py:136-140). Belegt: der zweite
    #     Aufruf fuer CABO kostet 0 HTTP und 0,000 s.
    #   - 4-Tier-Fallback yfinance -> Finnhub -> TwelveData ->
    #     AlphaVantage, falls Yahoo einen Titel nicht liefert. Bei 46
    #     Positionen bedeutet das echte Robustheit.
    #
    # Der Rechenweg bleibt unveraendert: Zeile 939-940 faellt weiter
    # auf avg_price zurueck, wenn kein Kurs kommt. /data rechnet
    # nachweislich korrekt mit Live-Kursen - 10 von 10 Depots
    # stimmen exakt mit der Nachrechnung ueberein. Hier aendert sich
    # nur, wie schnell die Preise da sind.
    #
    # Rueckfall auf den Sammelabruf, falls marktdaten fehlt: dann
    # waere /data still 24 s lang, und das faelle niemandem auf,
    # weil die Werte trotzdem stimmen wuerden.
    kurse = {}
    if ALLE_TICKER:
        try:
            from marktdaten import hole_kurs as _hole_kurs
        except Exception:
            _hole_kurs = None
        if _hole_kurs is not None:
            # PHASE 5 (01.10.2026): die Titel parallel holen.
            #
            # GEMESSEN ueber alle 42 Positionen, frischer Prozess:
            #     seriell    6,59 s   43 HTTP   0 time.sleep
            #     8 Threads  1,02 s   42 Treffer, identische Werte
            #
            # Null Wartezeit im seriellen Lauf heisst: es ist kein
            # Backoff mehr, sondern 42 Anfragen hintereinander.
            #
            # hole_kurs ist dafuer geeignet: der Kurs-Cache wird
            # erst nach dem Tier-Durchlauf geschrieben, jede
            # Exception wird je Titel gefangen, und geteilter
            # Zustand wird ausserhalb des Caches nicht mutiert.
            #
            # 8 statt mehr Threads, weil 46 Titel bei 8 Threads
            # bereits 6 Wellen sind und Yahoo auf parallele
            # Abfragen mit Backoff antwortet - der 5-Minuten-Cache
            # in marktdaten.py:136-140 faengt das ab.
            _tk_liste = sorted(ALLE_TICKER)
            try:
                from concurrent.futures import ThreadPoolExecutor as _TP
                with _TP(max_workers=8) as _pool:
                    _erg = list(_pool.map(_hole_kurs, _tk_liste))
            except Exception:
                _erg = []
                for _tk in _tk_liste:
                    try:
                        _erg.append(_hole_kurs(_tk))
                    except Exception:
                        _erg.append(0)
            for _i, _tk in enumerate(_tk_liste):
                try:
                    _k = _erg[_i]
                    if _k and _k > 0:
                        kurse[_tk] = float(_k)
                except Exception:
                    pass
        else:
            # Rueckfall: der alte Weg, langsam aber funktionsfaehig
            try:
                _data = yf.download(list(ALLE_TICKER), period="1d",
                                    progress=False, auto_adjust=True,
                                    timeout=10)
                if not _data.empty:
                    if 'Close' in _data:
                        close = _data['Close']
                        for col in close.columns:
                            vals = close[col].dropna()
                            if len(vals) > 0:
                                kurse[str(col)] = float(vals.iloc[-1])
            except Exception:
                pass  # Netz-Probleme -> avg_price aus Depot nutzen

    for risk, d, _dp, _modes in depot_raw_list:
        p = get_params(risk)
        # depot_id: aus Datei (neu) oder aus risk (Legacy)
        depot_id = d.get("depot_id") or f"aktien:{risk}"
        wert = d.get("bargeld", 0)
        for s, pos_obj in d.get("positions", {}).items():
            aktuell = kurse.get(s)
            if aktuell is None or aktuell <= 0:
                aktuell = pos_obj.get("avg_price", 0)
            wert += pos_obj["shares"] * aktuell
        rendite = (wert / d.get("start_wert", 100) - 1) * 100 if d.get("start_wert", 0) > 0 else 0

        # Stats aus Historie
        hist = d.get("historie", [])
        max_dd = 0
        if hist:
            peak = hist[0]["wert"]
            for h in hist:
                if h["wert"] > peak:
                    peak = h["wert"]
                dd = (peak - h["wert"]) / peak * 100
                if dd > max_dd:
                    max_dd = dd

        depots.append({
            "id": depot_id,
            "risk": risk,
            "mode": d.get("mode", "beide" if len(_modes) > 1 else list(_modes)[0]),
            "wert": round(wert, 2),
            "cash": round(d.get("bargeld", 0), 2),
            "start": d.get("start_wert") or 100,
            "rendite": round(rendite, 2),
            "positionen": len(d.get("positions", {})),
            "trades": _trades_anzahl(d),
            "historie": hist,
            "max_dd": round(max_dd, 1),
            "gesperrt": d.get("gesperrt", False),
            "peak_wert": d.get("peak_wert", d.get("start_wert", 100)),
            "positions": [{"ticker": t, "name": name_for(t), **v} for t, v in d.get("positions", {}).items()],
            "ki_letzte": d.get("ki_letzte"),
            "params": {"position_size": p["position_size"], "stop_loss": p["stop_loss"],
                       "take_profit": p["take_profit"], "min_score": p["min_score"],
                       "max_positions": p["max_positions"]},
        })

    # News
    news = []
    np = os.path.join(BASE, "news_cache.json")
    if os.path.exists(np):
        with open(np) as f:
            nc = json.load(f)
            news = nc.get("headlines", [])

    # ── KI-Log aus ki_log.json laden ──
    KI_LOG = []
    kip = os.path.join(BASE, "ki_log.json")
    if os.path.exists(kip):
        try:
            with open(kip, encoding="utf-8") as f:
                KI_LOG = json.load(f)
            if not isinstance(KI_LOG, list):
                KI_LOG = []
        except:
            KI_LOG = []

    # ── Trader-Status laden ──
    trader_status = {}
    tsp = os.path.join(BASE, "trader_status.json")
    if os.path.exists(tsp):
        try:
            with open(tsp, encoding="utf-8") as f:
                trader_status = json.load(f)
            if not isinstance(trader_status, dict):
                trader_status = {}
        except Exception:
            trader_status = {}

    # ── System-Log laden (neueste zuerst) ──
    SYSTEM_LOG = []
    slp = os.path.join(BASE, "system_log.json")
    if os.path.exists(slp):
        try:
            with open(slp, encoding="utf-8") as f:
                sl = json.load(f)
            if isinstance(sl, list):
                SYSTEM_LOG = sl[-200:][::-1]
        except Exception:
            SYSTEM_LOG = []

    # ── KI-Lern-Statistik + Regeln ──
    ki_statistik = {"anzahl": 0, "trefferquote": None, "lerneffekt_avg": None,
                    "bestaetigt": 0, "widerlegt": 0, "neutral": 0}
    ki_regeln = []
    ki_regel_familien = []
    regel_history = []
    regel_konflikte = []
    konfidenz_cap = None
    try:
        from ki_learning import statistik, lade_regeln, regel_familien_statistik, konfidenz_cap_aktuell
        ki_statistik = statistik()
        ki_regeln = lade_regeln()
        ki_regel_familien = regel_familien_statistik()
        konfidenz_cap = konfidenz_cap_aktuell()
        # P5: Regel-Evolution laden
        hp = os.path.join(BASE, "regel_history.json")
        if os.path.exists(hp):
            with open(hp, encoding="utf-8") as hf:
                regel_history = json.load(hf)
        # Prio 2: Lebenszyklus + Konflikte
        try:
            from learned_rules import regeln_mit_status
            ki_regeln, regel_konflikte = regeln_mit_status(ki_regeln)
        except Exception:
            pass
    except Exception:
        pass

    # Fallback: Regelwerk wenn keine Datei da
    if 'KI_LOG' not in dir() or not isinstance(KI_LOG, list):
        KI_LOG = []
    if not KI_LOG and news:
        for n in news:
            score = 50
            if n.get("date"):
                try:
                    parsed = datetime.strptime(n["date"].replace("GMT","").strip(), "%a, %d %b %Y %H:%M:%S ")
                    alter = (now - parsed).total_seconds() / 3600
                    if alter < 2:       score += 30
                    elif alter < 6:     score += 20
                    elif alter < 24:    score += 10
                except:
                    pass
            topics = n.get("topics", [])
            weight = {"market":15, "earnings":15, "tech":12, "interest rate":12, "inflation":10,
                      "energy":8, "merger":8, "regulation":6, "geopolitics":6, "crypto":6, "":0}
            for t in topics:
                score += weight.get(t.lower(), 4)
            score = min(score, 100)
            stars = "⭐⭐⭐" if score >= 70 else "⭐⭐" if score >= 45 else "⭐" if score >= 20 else ""
            KI_LOG.append({
                "zeit": now.isoformat(),
                "title": n.get("title",""),
                "score": score,
                "stars": stars,
                "topics": topics,
                "tickers": [],
                "reason": "Regelwerk (keine KI)",
                "link": n.get("link",""),
            })


    # ── Market Status ──

    # KI-Log speichern (nur wenn Fallback berechnet wurde)
    if KI_LOG and not os.path.exists(kip):
        KI_LOG = KI_LOG[-200:]
        with open(kip, "w", encoding="utf-8") as f:
            json.dump(KI_LOG, f, indent=2, ensure_ascii=False)

    # Zusammenfassung
    summary = {}
    sp = os.path.join(BASE, "batch_summary.json")
    if os.path.exists(sp):
        with open(sp) as f:
            summary = json.load(f)

    # Spekulation-Watch
    spec_watch = {}
    swp = os.path.join(BASE, "spec_watch.json")
    if os.path.exists(swp):
        with open(swp) as f:
            spec_watch = json.load(f)

    # Spekulation-Depots
    # 30.09.2026: Modusabhaengiges Verzeichnis.
    #
    # spec_trader.py laeuft bei PAPER in spec_depots_paper/,
    # shadow in spec_depots/. /data las fest spec_depots/ und
    # zeigte damit einen anderen Bestand als der Trader
    # handelt: BB stand auf Platte mit shares=3.555 und
    # bargeld=69, in der API kam es mit shares=0 und bargeld=70
    # an. Von zehn echten Depots wurden fuenf angezeigt.
    spec_depots = []
    # Achtung: get_trading_mode() liefert aus der Datenbank
    # GROSSBUCHSTABEN ("SHADOW", "PAPER"). Ohne lower() ist
    # der Vergleich nie wahr, es wird spec_depots/ gelesen und
    # das Portfolio erscheint leer.
    try:
        from security import get_trading_mode as _gtr
        _smode = (_gtr() or "paper").lower()
    except Exception:
        _smode = "paper"
    sdd = os.path.join(BASE, "spec_depots" if _smode != "paper"
                       else "spec_depots_paper")
    if os.path.isdir(sdd):
        for fn in sorted(os.listdir(sdd)):
            if fn.endswith(".json"):
                with open(os.path.join(sdd, fn)) as f:
                    sd = json.load(f)
                # Nur echte Depots (gestartet/gehandelt) zählen – Platzhalter ohne
                # Startkapital gehören in die Watchlist, nicht ins Portfolio
                if not (sd.get("start") or sd.get("shares") or sd.get("trades")):
                    continue
                spec_depots.append({
                    "ticker": sd.get("ticker", fn.replace(".json","")),
                    "name": sd.get("name", ""),
                    "kategorie": sd.get("kategorie", ""),
                    "wert": sd.get("bargeld", 0) + sd.get("shares", 0) * sd.get("avg_price", 0),
                    "bargeld": sd.get("bargeld", 0),
                    "shares": sd.get("shares", 0),
                    "avg_price": sd.get("avg_price", 0),
                    "start": sd.get("start") or 0,
                    "trades": _trades_anzahl(sd),
                    "historie": sd.get("historie", []),
                    "ki_letzte": sd.get("ki_letzte"),
                })
    
    # ETF-Depots
    # 29.09.2026: Diese Schleife las fest etf_NNN.json in
    # range(0, 100, 5). Das sind die alten SHADOW-Depots mit 100 EUR
    # Start. Die zehn Testdepots heissen etf_NNN_01_paper.json und
    # haben 200 EUR. Die Uebersicht zeigte deshalb einen anderen
    # Bestand als die Detailseite, und "Gesamtwert 0 EUR" oben.
    # Dieselbe Logik wie in etf_depot_json().
    try:
        import security as _sec_etf
        _tid_etf = _sec_etf.get_current_tenant() or 1
        _modus_etf = _sec_etf.get_trading_mode(_tid_etf) or "SHADOW"
    except Exception:
        _modus_etf = "SHADOW"
    _sfx_etf = "_01_paper" if _modus_etf == "PAPER" else ""
    _stufen_etf = (range(0, 100, 10) if _modus_etf == "PAPER"
                   else range(0, 100, 5))
    etf_depots = []
    for risk in _stufen_etf:
        ep = os.path.join(BASE, f"etf_{risk:03d}{_sfx_etf}.json")
        if os.path.exists(ep):
            with open(ep) as f:
                d = json.load(f)
            wert = d.get("bargeld", 0)
            for s, pos_obj in d.get("positions", {}).items():
                aktuell = kurse.get(s)
                if aktuell is None or aktuell <= 0:
                    aktuell = pos_obj.get("avg_price", 0)
                wert += pos_obj["shares"] * aktuell
            rendite = (wert / d.get("start_wert", 100) - 1) * 100 if d.get("start_wert", 0) > 0 else 0
            hist = d.get("historie", [])
            max_dd = 0
            if hist:
                peak = hist[0]["wert"]
                for h in hist:
                    if h["wert"] > peak: peak = h["wert"]
                    dd = (peak - h["wert"]) / peak * 100
                    if dd > max_dd: max_dd = dd
            etf_depots.append({
                "risk": risk,
                # Der Frontend-Filter liest "modus", die Depot-Datei
                # speichert "mode". Ohne dieses Feld blieb der
                # Modus-Filter leer und die Karten nicht zuordenbar.
                "mode": (d.get("mode") or _modus_etf).lower(),
                "modus": (d.get("mode") or _modus_etf).lower(),
                "wert": round(wert, 2),
                "cash": round(d.get("bargeld", 0), 2),
                "start": d.get("start_wert") or 100,
                "rendite": round(rendite, 2),
                "positionen": len(d.get("positions", {})),
                "trades": _trades_anzahl(d),
                "historie": hist[-50:],
                "max_dd": round(max_dd, 1),
                "gesperrt": d.get("gesperrt", False),
                "positions": [{"ticker": t, **v} for t, v in d.get("positions", {}).items()],
            })

    # ETF-Summary
    etf_summary = {}
    esp = os.path.join(BASE, "etf_summary.json")
    if os.path.exists(esp):
        with open(esp) as f:
            etf_summary = json.load(f)

    akt = "-"
    if depots and len(depots) > 1:
        # BUG-FIX (2026-08-14): "Stand" = echte letzte Aktualisierung =
        # aeltestes mtime der Depot-Dateien auf Disk (wann Pipeline zuletzt
        # geschrieben hat), NICHT der alte Historie-Eintrag (der beim Umbau
        # eingefroren wurde und nie aktualisiert wird).
        try:
            import glob
            files = glob.glob(os.path.join(BASE, "depot_*.json")) + \
                     glob.glob(os.path.join(BASE, "etf_*.json")) + \
                     glob.glob(os.path.join(BASE, "spec_depots", "*.json"))
            if files:
                newest = max(os.path.getmtime(f) for f in files)
                # ISO-Format liefern (nicht DE-Format!), damit formatDeutsch()
                # im Frontend es per new Date() parsen kann (sonst NaN.NaN).
                akt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(newest))
        except Exception:
            akt = "-"

    # Ranking (sortiert nach Rendite absteigend)
    ranking = sorted(depots, key=lambda d: d["rendite"], reverse=True)
    ranking_mit_platz = [
        {"platz": i+1, **r} for i, r in enumerate(ranking)
    ]

    # Marktstatus
    mk_status, mk_label, boersen = market_status()

    # SPX Benchmark
    spx = get_spx_data()

    # Notifications
    notifs = check_notifications(depots)

    # Letzte Aktualisierung als lesbares Datum
    akt_dt = akt if akt != "-" else datetime.now().strftime("%H:%M") if depots else "-"

    # Gesamt-Wert und Rendite
    ges_wert = sum(d["wert"] for d in depots)
    ges_start = sum(d["start"] for d in depots)
    ges_rendite = round((ges_wert / ges_start - 1) * 100, 2) if ges_start > 0 else 0.0

    # ── Live-Summen aller Kategorien (fuer Verlaufs-Graph-Sync) ──
    akt_wert = ges_wert; akt_start = ges_start; akt_rendite = ges_rendite
    etf_wert = sum(e["wert"] for e in etf_depots); etf_start = sum(e["start"] for e in etf_depots)
    etf_rendite = round((etf_wert / etf_start - 1) * 100, 2) if etf_start > 0 else 0.0
    spec_wert = sum(sd["wert"] for sd in spec_depots); spec_start = sum(sd["start"] for sd in spec_depots)
    spec_rendite = round((spec_wert / spec_start - 1) * 100, 2) if spec_start > 0 else 0.0
    total_wert = akt_wert + etf_wert + spec_wert
    total_start = akt_start + etf_start + spec_start
    total_rendite = round((total_wert / total_start - 1) * 100, 2) if total_start > 0 else 0.0
    # Verlauf berechnen und letzten Punkt jeder Serie mit Live-Werten syncen
    # PHASE 5 (§9): Verlauf nur des aktiven Portfolio-Modus
    verlauf = portfolio_verlauf(tage=7, mode=_pmode)
    jetzt_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    if verlauf.get("gesamt"):
        verlauf["gesamt"][-1] = {"zeit": jetzt_str, "wert": round(total_wert, 2), "rendite": total_rendite}
    if verlauf.get("aktien"):
        verlauf["aktien"][-1] = {"zeit": jetzt_str, "wert": round(akt_wert, 2), "rendite": akt_rendite}
    if verlauf.get("etf"):
        verlauf["etf"][-1] = {"zeit": jetzt_str, "wert": round(etf_wert, 2), "rendite": etf_rendite}
    if verlauf.get("spec"):
        verlauf["spec"][-1] = {"zeit": jetzt_str, "wert": round(spec_wert, 2), "rendite": spec_rendite}

    # ── News-Score pro Ticker (für A: News-Impact) ──
    # Nutze bewertete News aus KI_LOG (typ=news) wo echte Scores vorhanden sind
    # Nachfilter: News mit Score < NEWS_MIN_SCORE (aus Settings) werden als irrelevant ausgeblendet
    try:
        from settings_loader import news_opt
        NEWS_MIN_SCORE = int(news_opt("news_min_score", 20))
    except Exception:
        NEWS_MIN_SCORE = 20
    news_by_ticker = {}
    for e in KI_LOG:
        if e.get("typ") == "news":
            sc = e.get("score", 0)
            if sc < NEWS_MIN_SCORE:
                continue  # irrelevante News raus
            for t in (e.get("tickers") or []):
                t = t.upper()
                if t not in news_by_ticker or sc > news_by_ticker[t][0]:
                    news_by_ticker[t] = (sc, e.get("stars", ""), e.get("topics", []))
    # Fallback: falls KI_LOG keine News hat, nimm news_cache Headlines (Score 0)
    if not news_by_ticker:
        for n in news:
            for t in (n.get("tickers") or []):
                t = t.upper()
                if t not in news_by_ticker:
                    news_by_ticker[t] = (0, "", n.get("topics", []))

    # ── KI-Konfidenz-Verlauf (für C) ──
    ki_konfidenz_history = []
    for e in KI_LOG:
        if e.get("typ") == "decision" and e.get("konfidenz") is not None and e.get("zeit"):
            try:
                ki_konfidenz_history.append({
                    "zeit": e["zeit"],
                    "konfidenz": int(e["konfidenz"]),
                    "aktion": e.get("aktion", ""),
                })
            except Exception:
                pass
    ki_konfidenz_history = sorted(ki_konfidenz_history, key=lambda x: x["zeit"])[-20:]

    # ── KI-Lern-Notizen (letzter Lernlauf) ──
    ki_lern_notizen = []
    try:
        from ki_learning import lade_lern_notizen
        ki_lern_notizen = lade_lern_notizen(max_age_stunden=72)
    except Exception:
        pass

    # ── Pending Rules (noch nicht bestätigt = wackelig/veraltet in ki_regeln) ──
    pending_rules = [r for r in ki_regeln if r.get("status") in ("wackelig", "veraltet")]

    result = {
            'depots': depots,
            'ranking': ranking_mit_platz,
            # 29.09.2026: Das sind die Kennzahlen in der Kopfzeile
            # ("Aktien-Gesamtwert"). Sie summierten nur die Aktien-Depots,
            # also stand dort 0 EUR, obwohl zehn ETF-Depots mit Positionen
            # liefen. Die Summen ueber alle Kategorien stehen als
            # total_wert/total_rendite bereits an derselben Stelle, speisten
            # aber nur den Graphen.
            'ges_rendite': total_rendite,
            'ges_wert': total_wert,
            # Die Aufteilung bleibt sichtbar, damit klar ist, woher der
            # Gesamtwert kommt.
            'rendite_aktien': ges_rendite,
            'wert_aktien': round(ges_wert, 2),
            'wert_etf': round(etf_wert, 2),
            'wert_spec': round(spec_wert, 2),
            'spec_depots': spec_depots,
            'etf_depots': etf_depots,
            'etf_summary': etf_summary,
            'news': news[:20],
            'news_by_ticker': news_by_ticker,
            'summary': summary,
            'spec_watch': spec_watch,
            'vergleich': _build_vergleich(),
            'aktualisiert': akt_dt,
            'markt_status': mk_status,
            'markt_label': mk_label,
            'boersen': boersen,
            'boersen_chips': boersen_chips(),
            'portfolio_verlauf': verlauf,
            'trade_hist_aktien': kategorie_trade_historie("aktien", 60),
            'trade_hist_etf': kategorie_trade_historie("etf", 60),
            'trade_hist_spec': kategorie_trade_historie("spec", 60),
            'ki_log': KI_LOG,
            'ki_konfidenz_history': ki_konfidenz_history,
            'system_log': SYSTEM_LOG,
            'ki_statistik': ki_statistik,
            'ki_regeln': ki_regeln,
            'ki_regel_familien': ki_regel_familien,
            'regelstand': regelstand_aggregat(ki_regeln),
            'regel_history': regel_history,
            'regel_konflikte': regel_konflikte,
            'konfidenz_cap': konfidenz_cap,
            'ki_lern_notizen': ki_lern_notizen,
            'pending_rules': pending_rules,
            'trader_status': trader_status,
            'spx_historie': spx,
            'notifications': notifs,
            'health': _health_status(),
            'paused': _ist_pausiert(),
            'profil': _profil_info(),
            'verfuegbare_profile': _profile_liste(),
        }
    # PHASE 1 (01.10.2026): erst filtern, DANN cachen.
    #
    # Die Reihenfolge ist nicht kosmetisch. Mit "data._cache = result"
    # VOR dem Filtern behaelt der Cache die ungefilterte Referenz und
    # liefert 44 Felder - unabhaengig von slim. Gemessen:
    #   ?slim=1                -> 197.079 B (21 Felder, frisch gebaut)
    #   ?mode=beide&slim=1   -> 1.209.777 B (44 Felder, aus dem Cache)
    # Der Cache-Schluessel allein nuetzte nichts, weil er einen bereits
    # verschmutzten Eintrag beschuetzte.
    if _slim:
        # Die Depotkarten brauchen diese Felder. Alles KI-/Log-spezifische
        # bleibt draussen und wird von den KI-Tabs ueber ihre eigenen
        # Endpunkte geholt (/api/ki_log, /api/rules, /api/pending_rules).
        _SLIM = (
            "depots", "etf_depots", "spec_depots", "etf_summary", "summary",
            "ges_wert", "ges_rendite", "ranking", "portfolio_verlauf",
            "aktualisiert", "markt_status", "markt_label", "boersen",
            "boersen_chips", "health", "paused", "notifications",
            "trader_status", "spec_watch", "konfidenz_cap", "vergleich",
            "gesperrt_am",
        )
        result = {k: v for k, v in result.items() if k in _SLIM}

    # Cache aktualisieren (PHASE 3: tenant-keyed; PHASE 5: + mode-keyed)
    data._cache = result
    data._cache_ts = time.time()
    data._cache_tid = _tid
    data._cache_mode = _req_mode or "beide"
    # Vierter Cache-Schluessel: ein Vollabruf darf die schmale Nutzlast
    # nicht erben und umgekehrt.
    data._cache_slim = bool(_slim)
    return result




def _health_status():
    """Sammelt operativen Gesundheitsstatus für die Dashboard-Health-Karte (v2.15.9)."""
    import glob as _glob
    h = {"gateway": False, "dashboard": True, "letzter_batch": None,
         "offene_boersen": [], "pipeline_aktiv": False, "fehler_24h": 0}

    # Gateway-State (Hermes WhatsApp/Node-Bridge)
    try:
        gsp = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                          "hermes", "gateway_state.json")
        if os.path.exists(gsp):
            with open(gsp) as f:
                gs = json.load(f)
            # connected wenn whatsapp.state == 'connected' ODER gateway 'running'
            pl = gs.get("platforms", {}).get("whatsapp", {})
            h["gateway"] = pl.get("state") == "connected" or gs.get("status") == "running"
    except Exception:
        pass

    # Letzter batch_trader-Lauf aus cron_pipeline.log
    try:
        logp = os.path.join(BASE, "cron_pipeline.log")
        if os.path.exists(logp):
            with open(logp, errors="ignore") as f:
                lines = f.readlines()
            for ln in reversed(lines[-400:]):
                if "batch_trader.py" in ln:
                    if "OK" in ln:
                        h["letzter_batch"] = ln.strip() + " ✅"
                    elif "FEHLER" in ln or "TIMEOUT" in ln:
                        h["letzter_batch"] = ln.strip() + " ❌"
                        h["fehler_24h"] += 1
                    else:
                        h["letzter_batch"] = ln.strip()
                    break
    except Exception:
        pass

    # Offene Börsen (nutzt boersen.ist_offen)
    try:
        from boersen import BOERSEN, ist_offen
        for name, b in BOERSEN.items():
            if ist_offen(name):
                h["offene_boersen"].append(b.get("label", name))
    except Exception:
        pass

    # Naechster Scheduler-Lauf (alle 15min: Minute 0,15,30,45)
    try:
        from datetime import datetime
        now = datetime.now()
        minute = now.minute
        # naechste 15min-Grenze
        if minute < 15: nxt = 15 - minute
        elif minute < 30: nxt = 30 - minute
        elif minute < 45: nxt = 45 - minute
        else: nxt = 60 - minute
        h["naechster_lauf_min"] = nxt
    except Exception:
        h["naechster_lauf_min"] = None

    # Pipeline aktiv? (subprocess pruefen)
    try:
        import subprocess as _sp
        out = _sp.run(["tasklist", "/FI", "IMAGENAME eq pythonw.exe", "/NH"],
                      capture_output=True, text=True, timeout=5)
        h["pipeline_aktiv"] = "micro-trader-pipeline" in out.stdout
    except Exception:
        pass

    return h




@app.route("/api/pause_trading")
def pause_trading():
    """Setzt oder liest das Pause-Flag (v2.16.2)."""
    pf = os.path.join(BASE, "pause_flag.json")
    state = request.args.get("state", "").lower()
    if state in ("on", "off", "1", "0"):
        paused = state in ("on", "1")
        grund = request.args.get("grund", "manuell")
        try:
            with open(pf, "w") as f:
                json.dump({"paused": paused, "grund": grund,
                           "zeit": time.strftime("%Y-%m-%d %H:%M")}, f)
            return {"ok": True, "paused": paused, "grund": grund}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    # GET ohne state -> Status
    if os.path.exists(pf):
        try:
            with open(pf) as f:
                return {"ok": True, **json.load(f)}
        except Exception:
            pass
    return {"ok": True, "paused": False}

@app.route("/api/risk_appetite")
def risk_appetite():
    """Liest/Schreibt den globalen Risiko-Appetit (0-100%) aus config.json.
    P3 (2026-08-10): Slider im Dashboard -> KI-Strategie (aggressiv/konservativ).
    Erweitert 2026-08-11: KI-Strategie-Profile + Merge-Schutz fuer config.json."""
    cf = os.path.join(BASE, "config.json")
    if request.args.get("value") is not None:
        try:
            v = max(0, min(100, int(request.args.get("value"))))
            # Merge-Schutz: bestehende config erhalten (keine Keys loeschen)
            cur = {}
            if os.path.exists(cf):
                try:
                    cur = json.load(open(cf, encoding="utf-8"))
                except Exception:
                    cur = {}
            cur["risk_appetite"] = v
            cur["risk_appetite_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            with open(cf, "w") as f:
                json.dump(cur, f, indent=2)
            return {"ok": True, "value": v, "profil": risk_appetite_profil(v)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    try:
        with open(cf, encoding="utf-8") as f:
            d = json.load(f)
        v = int(d.get("risk_appetite", 50))
        return {"ok": True, "value": v, "profil": risk_appetite_profil(v)}
    except Exception:
        return {"ok": True, "value": 50, "profil": risk_appetite_profil(50)}


def risk_appetite_profil(v):
    """KI-Strategie-Profil aus Risiko-Appetit (0-100%).
    Steuert das KI-Verhalten (siehe ki_decisions.py Prompt-Injektion)."""
    if v < 25:
        return {"stufe": "sehr_konservativ", "label": "Sehr konservativ",
                "ki_regel": "Nur A-/B-Klassen-Titel. Minimale Positionen, kein Hebel, keine Spekulation. Konfidenz-Schwellen hoch (>=75)."}
    if v < 45:
        return {"stufe": "konservativ", "label": "Konservativ",
                "ki_regel": "Bevorzuge Aktien/ETF mit klarem Setup. Spekulation nur bei sehr starker Lage. Max 1 neue Position pro Lauf."}
    if v < 60:
        return {"stufe": "ausgewogen", "label": "Ausgewogen",
                "ki_regel": "Normale Regeln. Aktien/ETF/Spekulation ausgewogen, bis zu 2 neue Positionen pro Lauf."}
    if v < 80:
        return {"stufe": "aggressiv", "label": "Aggressiv",
                "ki_regel": "Mehr Spekulation erlaubt. Konfidenz-Schwellen moderat (>=55). Bis zu 3 neue Positionen, höheres Risiko-Budget."}
    return {"stufe": "sehr_aggressiv", "label": "Sehr aggressiv",
            "ki_regel": "Volle Spekulations-Freigabe. Konfidenz >=50. Aggressive Positionierung, Risiko-Budget maximal."}

@app.route("/api/pending_rules")
def api_pending_rules():
    """Lerneffekte: automatisch vorgeschlagene Regeln aus pending_rules.json."""
    p = os.path.join(BASE, "pending_rules.json")
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


@app.route("/api/close_portfolio")
def close_portfolio():
    """P5 (2026-08-11): Schließt ALLE Positionen eines Portfolios (Paper-Simulation).
    Verkauft alle shares zu aktuellem Kurs, Cash ins Bargeld, Zustand CLOSED.
    Nur admin (goldi5)."""
    u = sec.current_user()
    if not u or u.get("role") != "superadmin":
        return {"ok": False, "error": "nur superadmin"}, 403
    pfad = request.args.get("pfad", "")
    if not pfad or not os.path.exists(os.path.join(BASE, pfad)):
        return {"ok": False, "error": "Depot-Pfad fehlt/ungueltig"}
    try:
        f = os.path.join(BASE, pfad)
        d = json.load(open(f, encoding="utf-8"))
        from marktdaten import hole_kurs
        erloes = 0
        # Format A: Spec-Depot (shares/avg_price auf Top-Level)
        sh = d.get("shares", 0) or 0
        if sh > 0:
            t = d.get("ticker", "")
            k = hole_kurs(t) or d.get("avg_price", 0) or 0
            erloes += sh * k
            d["bargeld"] = (d.get("bargeld", 0) or 0) + erloes
            d["shares"] = 0
        # Format B: Aktien/ETF (positions-dict)
        pos = d.get("positions", {})
        if isinstance(pos, dict) and pos:
            for t, p in pos.items():
                psh = p.get("shares", 0) or 0
                k = hole_kurs(t) or p.get("avg_price", 0) or 0
                erloes += psh * k
            d["bargeld"] = (d.get("bargeld", 0) or 0) + erloes
            d["positions"] = {}
        d["zustand"] = "CLOSED"
        d["closed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        json.dump(d, open(f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        return {"ok": True, "pfad": pfad, "erloes": round(erloes, 2), "zustand": "CLOSED"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.route("/api/suspend_trading")
def suspend_trading():
    """P5 (2026-08-11): Härtester Notfall-Schalter. Pausiert Pipeline + KI +
    markt_daten + News (suspend_flag.json). Nur superadmin."""
    u = sec.current_user()
    if not u or u.get("role") != "superadmin":
        return {"ok": False, "error": "nur superadmin"}, 403
    sf = os.path.join(BASE, "suspend_flag.json")
    state = request.args.get("state", "").lower()
    if state in ("on", "off"):
        suspended = state == "on"
        grund = request.args.get("grund", "manuell (Kill-Switch)")
        try:
            with open(sf, "w") as f:
                json.dump({"suspended": suspended, "grund": grund,
                           "zeit": time.strftime("%Y-%m-%d %H:%M")}, f)
            return {"ok": True, "suspended": suspended, "grund": grund}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if os.path.exists(sf):
        try:
            with open(sf) as f:
                return {"ok": True, **json.load(f)}
        except Exception:
            pass
    return {"ok": True, "suspended": False}

@app.route("/api/broker_status")
def broker_status():
    """Broker-Status (Roadmap Punkt 8): PaperBrokerAdapter + Sync-Zustand.
    Zeigt NIE Keys — nur Status/Umgebung (Sicherheits-Regel)."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    try:
        # PAPER-Simulator
        pb = sec.PaperBrokerAdapter()
        pb.connect()
        health = pb.health_check()
        acct = pb.get_account()
        # SANDBOX-Broker
        sb = sec.SandboxBrokerAdapter()
        sb.connect()
        sb_health = sb.health_check()
        sb_acct = sb.get_account()
        # Sync-Status: paper_orders vs. paper_positions
        sync = "SYNCED"
        pos_count = 0
        order_count = 0
        top_positions = []
        try:
            import db as _db
            m = _db.MTDB()
            try:
                orders = m.conn.execute("SELECT COUNT(*) AS n FROM paper_orders").fetchone()
                pos = m.conn.execute("SELECT COUNT(*) AS n FROM paper_positions").fetchone()
                pos_count = pos["n"] if pos else 0
                order_count = orders["n"] if orders else 0
                sync = "SYNCED" if (order_count or pos_count) else "LEER"
                # Top 5 Positionen nach Wert (fuer Broker-Tab-Anzeige)
                try:
                    rows = m.conn.execute(
                        "SELECT ticker, markt, shares, avg_cost, current_price FROM paper_positions "
                        "ORDER BY (shares*COALESCE(current_price,avg_cost)) DESC LIMIT 8").fetchall()
                    for r in rows:
                        wert = (r["shares"] or 0) * (r["current_price"] or r["avg_cost"] or 0)
                        top_positions.append({
                            "ticker": r["ticker"], "markt": r["markt"],
                            "shares": r["shares"], "wert": round(wert, 2)
                        })
                except Exception:
                    pass
            finally:
                m.close()
        except Exception:
            sync = "BROKER_ERROR"
        return {
            "ok": True,
            "paper": {
                "broker": "PaperBrokerAdapter (Simulator)",
                "umgebung": "PAPER",
                "status": "verbunden" if health.get("ok") else "getrennt",
                "portfolios": acct.get("portfolios", 0),
                "wert": acct.get("wert", 0.0),
            },
            "sandbox": {
                "broker": "SandboxBrokerAdapter",
                "umgebung": "SANDBOX",
                "status": "verbunden" if sb_health.get("ok") else "getrennt",
                "buying_power": sb_acct.get("buying_power", 0.0),
            },
            "sync_status": sync,
            "key_hinweis": "kein Key — reine Simulatoren, keine Live-Orders (PAPER_ONLY)",
            "letzter_check": time.strftime("%H:%M:%S"),
            "positionen_anzahl": pos_count,
            "orders_anzahl": order_count,
            "top_positionen": top_positions,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _depot_pfad_aus_id(depot_id):
    """'spec:BBAI' -> spec_depots/BBAI.json | 'aktien:50' -> depot_050_paper.json | 'etf:30' -> etf_030_paper.json"""
    try:
        kat, key = depot_id.split(":", 1)
    except Exception:
        return None
    if kat == "spec":
        f = os.path.join(BASE, "spec_depots", f"{key}.json")
        return f if os.path.exists(f) else None
    if kat == "etf":
        for cand in [os.path.join(BASE, f"etf_{int(key):03d}_paper.json"),
                     os.path.join(BASE, f"etf_{int(key):03d}.json")]:
            if os.path.exists(cand):
                return cand
        return None
    if kat == "aktien":
        # key kann "100" (Legacy) oder "100:1" (seq) sein
        if ":" in key:
            rk, sk = key.split(":", 1)
            cands = [os.path.join(BASE, f"depot_{int(rk):03d}_{int(sk):02d}_paper.json"),
                     os.path.join(BASE, f"depot_{int(rk):03d}_{int(sk):02d}.json")]
        else:
            rk = key
            cands = [os.path.join(BASE, f"depot_{int(rk):03d}_paper.json"),
                     os.path.join(BASE, f"depot_{int(rk):03d}.json")]
        for cand in cands:
            if os.path.exists(cand):
                return cand
        return None
    return None

def depot_erstellen(kat, risk, budget, name=None):
    """Erstellt ein NEUES Depot der Kategorie kat (aktien/etf/spec).
    risk: 0-100 (bei aktien/etf = Dateiname-Nummer), budget: $ Startkapital.
    Gibt (depot_id, pfad) zurueck, oder (None, Fehlermeldung) wenn schon existiert.
    Andockpunkt: analog zu depot_schliessen()/depot_loeschen()."""
    try:
        risk = int(risk)
        budget = float(budget)
    except (ValueError, TypeError):
        return None, "risk/budget muessen Zahlen sein"
    if kat == "spec":
        key = (name or f"SPEC{risk:03d}").strip()
        if not key:
            return None, "Spec-Depot braucht einen Namen"
        pfad = os.path.join(BASE, "spec_depots", f"{key}.json")
        depot_id = f"spec:{key}"
        # seq wird unten im Depot-Dict mitgeschrieben, aber nur
        # im aktien-/etf-Zweig gesetzt. Ein Spec-Depot aus der
        # Oberflaeche ("Neues Depot" -> Spekulation) brach deshalb
        # mit UnboundLocalError ab. 29.09.2026 gefunden, als die
        # Spec-Depots neu angelegt werden sollten.
        seq = 0
    elif kat in ("aktien", "etf"):
        prefix = "depot" if kat == "aktien" else "etf"
        # Eindeutige seq finden: depot_<risk>_<seq:02d>_paper.json
        # Legacy-Depots (depot_<risk>_paper.json, seq=00) bleiben erhalten.
        seq = 0
        while True:
            if seq == 0:
                pfad = os.path.join(BASE, f"{prefix}_{risk:03d}_paper.json")
            else:
                pfad = os.path.join(BASE, f"{prefix}_{risk:03d}_{seq:02d}_paper.json")
            if not os.path.exists(pfad):
                break
            seq += 1
            if seq > 99:
                return None, "Zu viele Depots mit diesem Risiko"
        depot_id = f"{kat}:{risk}" if seq == 0 else f"{kat}:{risk}:{seq}"
    else:
        return None, "Falsche Kategorie (aktien/etf/spec)"
    if os.path.exists(pfad):
        return None, f"Depot existiert schon: {depot_id}"
    d = {
        "risk": risk,
        "bargeld": budget,
        "start_wert": budget,
        "positions": {},
        "shares": 0,
        "zustand": "ACTIVE",
        "erstellt_am": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "name": name or f"{kat.title()} {risk}",
        "mode": "paper",
        "depot_id": depot_id,
        "seq": seq,
    }
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return depot_id, pfad


@app.route("/api/depot_pause")
def depot_pause():
    """Pausiert/Resumt EIN Depot (depot_pause.json, pro Depot-ID).
    Toggle: 1. Aufruf pausiert, 2. hebt Pause auf."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    depot_id = request.args.get("id", "")
    pf = os.path.join(BASE, "depot_pause.json")
    flags = {}
    if os.path.exists(pf):
        try:
            flags = json.load(open(pf))
        except Exception:
            flags = {}
    aktuell = bool(flags.get(depot_id, {}).get("paused"))
    flags[depot_id] = {"paused": not aktuell, "zeit": time.strftime("%Y-%m-%d %H:%M")}
    with open(pf, "w") as f:
        json.dump(flags, f, indent=2)
    return {"ok": True, "paused": not aktuell, "depot": depot_id}

@app.route("/api/depot_verkaufen")
def depot_verkaufen():
    """Verkauft ALLE Positionen eines Depots (Paper-Sim), behält Depot offen."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    depot_id = request.args.get("id", "")
    f = _depot_pfad_aus_id(depot_id)
    if not f:
        return {"ok": False, "error": "Depot nicht gefunden: " + depot_id}
    try:
        d = json.load(open(f, encoding="utf-8"))
        from marktdaten import hole_kurs
        erloes = 0
        # Format A: Spec (top-level shares)
        sh = d.get("shares", 0) or 0
        if sh > 0:
            k = hole_kurs(d.get("ticker", "")) or d.get("avg_price", 0) or 0
            erloes += sh * k
            d["bargeld"] = (d.get("bargeld", 0) or 0) + erloes
            d["shares"] = 0
        # Format B: positions-dict
        pos = d.get("positions", {})
        if isinstance(pos, dict) and pos:
            for t, p in pos.items():
                psh = p.get("shares", 0) or 0
                k = hole_kurs(t) or p.get("avg_price", 0) or 0
                erloes += psh * k
            d["bargeld"] = (d.get("bargeld", 0) or 0) + erloes
            d["positions"] = {}
        json.dump(d, open(f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        return {"ok": True, "erloes": round(erloes, 2), "depot": depot_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.route("/api/depot_schliessen")
def depot_schliessen():
    """Schließt ein Depot: verkauft alles + Zustand CLOSED + Pause-Flag."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    depot_id = request.args.get("id", "")
    f = _depot_pfad_aus_id(depot_id)
    if not f:
        return {"ok": False, "error": "Depot nicht gefunden: " + depot_id}
    try:
        # Erst verkaufen
        d = json.load(open(f, encoding="utf-8"))
        from marktdaten import hole_kurs
        erloes = 0
        sh = d.get("shares", 0) or 0
        if sh > 0:
            k = hole_kurs(d.get("ticker", "")) or d.get("avg_price", 0) or 0
            erloes += sh * k
            d["bargeld"] = (d.get("bargeld", 0) or 0) + erloes
            d["shares"] = 0
        pos = d.get("positions", {})
        if isinstance(pos, dict) and pos:
            for t, p in pos.items():
                psh = p.get("shares", 0) or 0
                k = hole_kurs(t) or p.get("avg_price", 0) or 0
                erloes += psh * k
            d["bargeld"] = (d.get("bargeld", 0) or 0) + erloes
            d["positions"] = {}
        d["zustand"] = "CLOSED"
        d["closed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        json.dump(d, open(f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        # Pause-Flag setzen
        pf = os.path.join(BASE, "depot_pause.json")
        flags = {}
        if os.path.exists(pf):
            try:
                flags = json.load(open(pf))
            except Exception:
                flags = {}
        flags[depot_id] = {"paused": True, "zustand": "CLOSED", "zeit": time.strftime("%Y-%m-%d %H:%M")}
        with open(pf, "w") as f:
            json.dump(flags, f, indent=2)
        return {"ok": True, "erloes": round(erloes, 2), "zustand": "CLOSED", "depot": depot_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.route("/api/depot_loeschen")
def depot_loeschen():
    """Löscht ein Depot NUR in der Kette: verkauft (0 Shares) + CLOSED.
    Verschiebt die Datei nach .backup/geloeschte_depots/ (kein hartes Löschen).
    Kette laut User: erst verkaufen -> dann schließen -> dann löschen."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    depot_id = request.args.get("id", "")
    f = _depot_pfad_aus_id(depot_id)
    if not f:
        return {"ok": False, "error": "Depot nicht gefunden: " + depot_id}
    try:
        d = json.load(open(f, encoding="utf-8"))
        # Kette prüfen: keine Shares/Positionen mehr
        sh = d.get("shares", 0) or 0
        pos = d.get("positions", {}) or {}
        if sh > 0 or (isinstance(pos, dict) and pos):
            return {"ok": False, "error": "Depot hat noch Positionen — erst verkaufen!", "kette": "verkaufen"}
        if d.get("zustand") != "CLOSED":
            return {"ok": False, "error": "Depot ist nicht CLOSED — erst schließen!", "kette": "schliessen"}
        # Verschieben nach .backup/geloeschte_depots/
        ziel_dir = os.path.join(BASE, ".backup", "geloeschte_depots")
        os.makedirs(ziel_dir, exist_ok=True)
        ziel = os.path.join(ziel_dir, os.path.basename(f))
        shutil.move(f, ziel)
        # Pause-Flag entfernen
        pf = os.path.join(BASE, "depot_pause.json")
        if os.path.exists(pf):
            try:
                flags = json.load(open(pf))
                flags.pop(depot_id, None)
                with open(pf, "w") as fh:
                    json.dump(flags, fh, indent=2)
            except Exception:
                pass
        return {"ok": True, "depot": depot_id, "verschoben": os.path.basename(f)}
    except Exception as e:
        return {"ok": False, "error": str(e)}



def _ist_pausiert():
    """Liest das Pause-Flag (v2.16.2) + Kill-Switch suspend_flag (P5, v2.53.0)."""
    # Kill-Switch (härteste Stufe) schlägt alles
    sf = os.path.join(BASE, "suspend_flag.json")
    if os.path.exists(sf):
        try:
            with open(sf) as f:
                sd = json.load(f)
            if sd.get("suspended"):
                return {"paused": True, "grund": "KILL-SWITCH: " + str(sd.get("grund", "")),
                        "zeit": sd.get("zeit", ""), "kill_switch": True}
        except Exception:
            pass
    pf = os.path.join(BASE, "pause_flag.json")
    if os.path.exists(pf):
        try:
            with open(pf) as f:
                d = json.load(f)
            return {"paused": bool(d.get("paused")), "grund": d.get("grund", ""),
                    "zeit": d.get("zeit", ""), "kill_switch": False}
        except Exception:
            pass
    return {"paused": False, "grund": "", "zeit": "", "kill_switch": False}




@app.route("/api/depot_neu", methods=["POST"])
def depot_neu():
    """Erstellt ein NEUES Depot (aktien/etf/spec) mit Budget + Risiko.
    Andockpunkt: analog zu depot_schliessen()/depot_loeschen()."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    kat = (data.get("kategorie") or "aktien").lower()
    if kat not in ("aktien", "etf", "spec"):
        return {"ok": False, "error": "Falsche Kategorie (aktien/etf/spec)"}
    try:
        risk = int(data.get("risk", 20))
        budget = float(data.get("budget", 100))
    except (ValueError, TypeError):
        return {"ok": False, "error": "risk/budget muessen Zahlen sein"}
    name = data.get("name") or None
    depot_id, pfad = depot_erstellen(kat, risk, budget, name)
    if depot_id is None:
        return {"ok": False, "error": pfad}
    return {"ok": True, "depot_id": depot_id, "pfad": pfad,
            "depot": {"risk": risk, "budget": budget, "kategorie": kat, "name": name}}

@app.route("/api/ops_system")
def api_ops_system():
    """Phase 2: Operations Center — zentraler SystemStatus."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    from ops_status import build_system_status
    try:
        return {"ok": True, "status": build_system_status()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/ops_news")
def api_ops_news():
    """Phase 2/5: News-Cockpit-Daten (Priorität, Ticker, Impact)."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    try:
        if not os.path.exists(NEWS_CACHE):
            return {"ok": True, "news": [], "feed_status": {}}
        nc = json.load(open(NEWS_CACHE, encoding="utf-8"))
        return {"ok": True, "news": nc.get("headlines", []),
                "feed_status": nc.get("feed_status", {}),
                "total": nc.get("total"), "relevant": nc.get("relevant")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/ops_provider")
def api_ops_provider():
    """Phase 2/8: Provider-/Broker-Cockpit."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    from ops_status import build_provider_status
    try:
        return {"ok": True, "providers": build_provider_status()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/ops_release")
def api_ops_release():
    """Phase 2/7: Release-/Freigabe-Cockpit."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    from ops_status import build_release_status
    try:
        return {"ok": True, "release": build_release_status()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/ops_risk")
def api_ops_risk():
    """Phase 2/6: Portfolio-/Risiko-Cockpit."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    from ops_status import build_portfolio_status
    try:
        return {"ok": True, "portfolios": build_portfolio_status()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/ops_recon")
def api_ops_recon():
    """Phase 2/9: Reconciliation-Cockpit."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    from ops_status import build_reconciliation_status
    try:
        return {"ok": True, "reconciliation": build_reconciliation_status()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/ops_alerts")
def api_ops_alerts():
    """Phase 12: Monitoring/Alerts."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    from ops_alerts import evaluate_alerts, list_alerts
    try:
        new = evaluate_alerts()
        return {"ok": True, "new_alerts": len(new), "alerts": list_alerts()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/ops_staging", methods=["POST"])
def api_ops_staging():
    """Phase 2/11: Staging E2E-Durchlauf (PAPER_ONLY, Test-Tenant).
    Fuehrt die Kette News→KI→Snapshot→Order-Intent→Recon aus (Simulator)."""
    u = sec.current_user()
    if not u or not sec.access_level_met(u["role"], "ADMIN"):
        return {"ok": False, "error": "unauthorized"}, 401
    try:
        from ops_staging import run_staging
        result = run_staging()
        return {"ok": True, "staging": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/live_kill_switch", methods=["POST"])
def api_live_kill_switch():
    """Phase 11: Manueller Kill-Switch für Live-System (PAPER_ONLY: nur Struktur).
    Body: {aktion:'on'|'off', grund:'...'}"""
    u = sec.current_user()
    if not u or not sec.access_level_met(u["role"], "ADMIN"):
        return {"ok": False, "error": "unauthorized"}, 401
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    aktion = data.get("aktion", "on")
    grund = data.get("grund", "Manuell")
    try:
        from live_system import LiveSystem
        ls = LiveSystem(tenant_id=int(u.get("tenant_id", 1)))
        if aktion == "off":
            ls.kill_switch_freigeben(grund)
        else:
            ls.kill_switch_aktivieren(grund)
        return {"ok": True, "safe_stop": ls.ist_gestoppt, "grund": grund}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/live_status")
def api_live_status():
    """Phase 11: Monitoring-Schicht — Live-System-Status (PAPER_ONLY)."""
    if not _ops_auth_ok():
        return {"ok": False, "error": "unauthorized"}, 401
    try:
        from live_system import LiveSystem
        # 01.11.2026: vorher u.get(...) ohne u -> NameError, Route lieferte
        # immer ok:false. Tenant wie ueberall aus dem Session-Kontext.
        ls = LiveSystem(tenant_id=int(_get_tid()))
        return {"ok": True, "status": ls.status()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/profil_karten")
def api_profil_karten():
    """Phase 11 (§18): Profil-/Markt-Karten für Dashboard-Steuerzentrale.
    Nutzt profil_schema (neu, §29.A). Multi-Markt-Ausbau US/DE/JP."""
    try:
        from profil_schema import lade_profil
        karten = []
        for name, markt in [("us_shadow", "US"), ("de_shadow", "DE"), ("jp_shadow", "JP")]:
            p, fehler, warn = lade_profil(name)
            if not p:
                karten.append({"markt": markt, "name": name, "status": "fehler",
                               "modus": "shadow", "depotarten": [], "warnung": fehler})
                continue
            karten.append({
                "markt": markt,
                "name": p.get("name", name),
                "status": "shadow" if p.get("modus") == "shadow" else "live",
                "modus": p.get("modus", "shadow"),
                "depotarten": p.get("depotarten", []),
                "maerkte": p.get("märkte", []),
                "base_currency": p.get("base_currency", "USD"),
                "regelstand_ref": p.get("regelstand_ref", "unbekannt"),
                "warnung": warn or "",
            })
        return {"ok": True, "karten": karten}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/profile")
def api_profile():
    """Liefert/setzt das aktive Profil (Phase 2)."""
    set_name = request.args.get("set", "").strip()
    if set_name:
        try:
            from profile_schema import setze_aktives_profil, lade_aktives_profil
            if setze_aktives_profil(set_name):
                # Cache invalidieren, damit /data sofort das neue Profil liefert
                if hasattr(data, "_cache"):
                    data._cache = None
                    if hasattr(data, "_cache_tid"):
                        data._cache_tid = None
                    if hasattr(data, "_cache_mode"):
                        data._cache_mode = None
                p = lade_aktives_profil()
                return {"ok": True, "gewechselt_zu": p.name, **p.to_dict()}
            return {"ok": False, "error": f"Profil {set_name} nicht gefunden"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    try:
        from profile_schema import lade_aktives_profil, liste_profile, aktives_profil_name
        p = lade_aktives_profil()
        return {"ok": True, "aktiv": aktives_profil_name(),
                "verfuegbar": liste_profile(), **p.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}



def _profil_info():
    """Liefert Profil-Metadaten für Dashboard (Phase 2)."""
    try:
        from profile_schema import lade_aktives_profil, MODUS_ICON
        p = lade_aktives_profil()
        return {
            "name": p.name,
            "modus": p.modus,
            "modus_icon": MODUS_ICON.get(p.modus, "👁️"),
            "märkte": p.märkte(),
            "depotarten": p.depotarten(),
            "base_currency": p.base_currency,
            "version": p.get("version", ""),
        }
    except Exception:
        return None




def _profile_liste():
    """Liste aller verfügbaren Profile für Wechsel-Dropdown (Phase 2)."""
    try:
        from profile_schema import liste_profile
        return liste_profile()
    except Exception:
        return []


@app.route("/search_ticker")
def search_ticker():
    """Sucht einen Ticker über alle Depots."""
    ticker = request.args.get("ticker", "").upper().strip()
    if not ticker:
        return {"results": []}
    results = []
    for risk in RISK_STUFEN:
        dp = depot_pfad(risk)
        if not os.path.exists(dp):
            continue
        with open(dp) as f:
            d = json.load(f)
        for t, pos in d.get("positions", {}).items():
            if t.upper() == ticker or ticker in t.upper():
                wert = pos["shares"] * pos.get("avg_price", 0)
                results.append({
                    "risk": risk,
                    "ticker": t,
                    "name": name_for(t),
                    "shares": pos["shares"],
                    "avg_price": pos.get("avg_price", 0),
                    "wert": round(wert, 2),
                })
    # Auch Spekulation-Depots durchsuchen
    sdd = os.path.join(BASE, "spec_depots")
    if os.path.isdir(sdd):
        for fn in sorted(os.listdir(sdd)):
            if fn.endswith(".json"):
                t = fn.replace(".json", "")
                if t.upper() == ticker or ticker in t.upper():
                    with open(os.path.join(sdd, fn)) as f:
                        sd = json.load(f)
                    results.append({
                        "risk": "🔥",
                        "ticker": t,
                        "name": sd.get("name", t),
                        "shares": sd.get("shares", 0),
                        "avg_price": sd.get("avg_price", 0),
                        "wert": sd.get("bargeld", 0) + sd.get("shares", 0) * sd.get("avg_price", 0),
                    })
    return {"results": results}


@app.route("/api/clear_cache")
def clear_cache():
    if hasattr(data, '_cache'):
        delattr(data, '_cache')
    if hasattr(data, '_cache_ts'):
        delattr(data, '_cache_ts')
    if hasattr(data, '_cache_tid'):
        delattr(data, '_cache_tid')
    if hasattr(data, '_cache_mode'):
        delattr(data, '_cache_mode')
    return {"ok": True}

# Einmal-Meldung fuer den ersten Umrechnungsfehler - siehe
# den except-Block in api_ki_log.
_ZEITFEHLER_GEMELDET = []

@app.route("/api/ki_log")
def api_ki_log():
    # PHASE 4: Tenant-Scope — nur Eintraege des aktiven Tenants
    kip = os.path.join(BASE, "ki_log.json")
    typ = request.args.get("typ")
    tage = request.args.get("tage")
    if not os.path.exists(kip):
        return []
    try:
        with open(kip, encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return []
    if isinstance(data, list):
        try:
            import security as _sec
            tid = _get_tid()
        except Exception:
            tid = 1
        data = [e for e in data if e.get("tenant_id", 1) == tid]
        if typ:
            data = [e for e in data if e.get("typ") == typ]
        if tage:
            try:
                from datetime import datetime as _dt, timedelta as _td
                cutoff = (_dt.utcnow() - _td(days=int(tage))).isoformat()
                data = [e for e in data if (e.get("zeit") or "") >= cutoff]
            except Exception:
                pass

        # 29.09.2026: harte Obergrenze. Das Log waechst
        # unbegrenzt - ki_log.json hatte an einem einzigen Tag
        # 699 Eintraege, davon 656 Decisions aus einem
        # Testlauf. Die Seite lud die ganze Datei, filterte sie
        # und bekam 905 KB uebertragen, davon 647 KB allein
        # fuer diesen einen Endpunkt.
        #
        # Der Zeitfilter allein half nicht: er filtert nach Datum,
        # und ein Tag kann Hunderte Eintraege haben. Die Grenze
        # greift deshalb unabhaengig vom Zeitraum, sortiert nach
        # Zeit - das sind die juengsten, nicht die aeltesten im
        # Fenster.
        _MAX = 300
        if len(data) > _MAX:
            data = sorted(data, key=lambda e: (e.get("zeit") or ""),
                      reverse=True)[:_MAX]

        # 01.10.2026: 'zeit' kommt aus datetime.now() OHNE Zone.
        # Damals lief der Container auf Etc/UTC, also war der Wert
        # UTC, und das Frontend schnitt nur die Zeichenkette ab und
        # zeigte dem Nutzer eine Zeit, die 2 Stunden hinten lag
        # (19:32 statt 21:32).
        #
        # 04.10.2026: Der Container laeuft auf Europe/Berlin, der
        # Wert ist also Berliner Zeit. Der Block unten entscheidet
        # das an der tatsaechlichen Container-Zone, damit er in
        # beiden Zustaenden stimmt.
        #
        # 'zeit' bleibt unveraendert: ki_learning.py und
        # news_evaluator vergleichen danach. 'zeit_berlin' kommt
        # additiv dazu - der Zeitstempel zum Sortieren bleibt der
        # UTC-Wert, damit die Reihenfolge der Datei erhalten
        # bleibt.
        _tzb = _zone("Europe/Berlin")
        if _tzb is not None:
            for e in data:
                if not isinstance(e, dict):
                    continue
                roh = e.get("zeit")
                if not roh:
                    continue
                try:
                    _s = str(roh)
                    if _s.endswith("Z"):
                        _d = datetime.fromisoformat(_s[:-1]).replace(
                            tzinfo=timezone.utc)
                    elif "+" in _s[10:]:
                        _d = datetime.fromisoformat(_s)
                    else:
                        # 04.10.2026: Der Container laeuft jetzt auf
                        # Europe/Berlin (timedatectl), und
                        # ki_decisions.py schreibt mit
                        # datetime.now() - also Berliner Zeit. Ein
                        # Wert ohne Suffix ist damit Berliner Zeit
                        # und darf NICHT noch einmal umgerechnet
                        # werden: das ergaebe +2h und zeigte
                        # "vor -38 Min".
                        #
                        # Die Zone wird NICHT angenommen, sondern
                        # gemessen: datetime.now().tzname() nennt
                        # dieselbe Zone, die Python selbst benutzt.
                        # Laeuft der Container wieder auf UTC, greift
                        # der alte Zweig - der Code ist in beiden
                        # Zustaenden richtig.
                        _jetzt = datetime.now().astimezone().tzname()
                        if _jetzt in ("UTC", "GMT"):
                            _d = datetime.fromisoformat(_s).replace(
                                tzinfo=timezone.utc)
                        else:
                            # bereits lokale Zeit: als solche lesen
                            _d = datetime.fromisoformat(_s).astimezone(
                                _tzb)
                    e["zeit_berlin"] = _d.astimezone(_tzb).strftime(
                        "%Y-%m-%dT%H:%M:%S")
                    e["zone_kz"] = _d.astimezone(_tzb).tzname()
                except Exception as _zerr:
                    # Das war still: ein NameError in diesem Block
                    # hat zeit_berlin auf None gesetzt, ohne dass
                    # irgendwo ein Fehler sichtbar wurde. Ein
                    # kaputter Eintrag ist normal und wird
                    # uebersprungen - aber der ERSTE Fehler wird
                    # gemeldet, damit er nicht wieder unbemerkt
                    # bleibt.
                    if not _ZEITFEHLER_GEMELDET:
                        _ZEITFEHLER_GEMELDET.append(1)
                        import sys as _s2
                        print("  zeit_berlin-Umrechnung fehlgeschlagen: "
                              "%s: %s" % (type(_zerr).__name__, _zerr),
                              file=_s2.stderr, flush=True)
                    e["zeit_berlin"] = None
                    e["zone_kz"] = None
        return data
    return data


# ── PHASE 5: Trading-Modi-Zustandsmaschine (Sektion 8) ──
@app.route("/api/trading_mode", methods=["GET"])
def api_trading_mode():
    import security as _sec
    import db as _db8
    tid = _get_tid()
    mode = _sec.get_trading_mode(tid)
    # PHASE 4: erlaubte Transitionen aus der State-Machine liefern (Frontend-Basis)
    try:
        m8 = _db8.MTDB()
        allowed = list(m8.MODE_TRANSITIONS.get(mode, []))
        m8.close()
    except Exception:
        allowed = []
    return {"tenant_id": tid, "mode": mode,
            "allowed_transitions": allowed}


@app.route("/api/trading_mode/set", methods=["POST"])
def api_trading_mode_set():
    import security as _sec
    u = _sec.current_user()
    if not u:
        return {"error": "nicht eingeloggt"}, 401
    # Nur TENANT_ADMIN oder ADMIN duerfen Modus wechseln (§7 kritische Trennung)
    role = _sec.effective_role(u)
    if role not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung fuer Moduswechsel"}, 403
    tid = _get_tid()
    new_mode = (request.form.get("mode") or request.json.get("mode") if request.is_json else request.form.get("mode"))
    if not new_mode:
        return {"error": "mode Parameter fehlt"}, 400
    reason = request.form.get("reason", "") or (request.json.get("reason", "") if request.is_json else "")
    try:
        old, new = _sec.set_trading_mode(
            new_mode, tenant_id=tid, user=u, reason=reason,
            requested_by=(u.get("id") if u else None))
    except ValueError as e:
        return {"error": str(e)}, 400
    return {"ok": True, "old_mode": old, "new_mode": new}


@app.route("/api/trading_mode/history")
def api_trading_mode_history():
    import security as _sec
    tid = _get_tid()
    return {"tenant_id": tid, "history": _sec.trading_mode_history(tid)}


# ── PHASE 6: Shadow -> Paper Freigabe (Sektion 9) ──
@app.route("/api/paper/eligibility")
def api_paper_eligibility():
    import security as _sec
    tid = _get_tid()
    eligible, gruende = _sec.paper_eligibility(tid)
    return {"tenant_id": tid, "eligible": eligible, "gruende": gruende}


@app.route("/api/paper/enter", methods=["POST"])
def api_paper_enter():
    import security as _sec
    u = _sec.current_user()
    if not u:
        return {"error": "nicht eingeloggt"}, 401
    role = _sec.effective_role(u)
    if role not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung"}, 403
    tid = _get_tid()
    try:
        old, new = _sec.enter_paper(tenant_id=tid, user=u, reason="Shadow->Paper Freigabe")
    except ValueError as e:
        return {"error": str(e)}, 400
    return {"ok": True, "old_mode": old, "new_mode": new}


# ── PHASE 7: Provider-Connection-Manager (Sektion 10) ──
@app.route("/api/providers", methods=["GET"])
def api_providers():
    import security as _sec
    tid = _get_tid()
    try:
        from db import MTDB
        m = MTDB()
        conns = m.provider_connection_list(tid)
        m.close()
        # Secrets NICHT ausliefern - nur Referenz-Maske anzeigen
        for c in conns:
            ref = c.get("secret_reference", "")
            if ref:
                c["secret_reference"] = "••••••••" + ref[-4:] if len(ref) > 4 else "••••"
        return {"tenant_id": tid, "providers": conns}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/api/providers/add", methods=["POST"])
def api_providers_add():
    import security as _sec
    u = _sec.current_user()
    if not u:
        return {"error": "nicht eingeloggt"}, 401
    role = _sec.effective_role(u)
    if role not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung"}, 403
    tid = _get_tid()
    ptype = request.form.get("provider_type") or (request.json.get("provider_type") if request.is_json else "")
    pname = request.form.get("provider_name") or (request.json.get("provider_name") if request.is_json else "")
    env = request.form.get("environment", "PAPER") or (request.json.get("environment", "PAPER") if request.is_json else "PAPER")
    secret_ref = request.form.get("secret_reference", "") or (request.json.get("secret_reference", "") if request.is_json else "")
    if not ptype or not pname:
        return {"error": "provider_type/name fehlt"}, 400
    try:
        from db import MTDB
        m = MTDB()
        m.provider_connection_add(tid, ptype, pname, env, "read",
                                 secret_ref or "vault://pending", created_by=1)
        m.close()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/api/providers/test/<int:conn_id>", methods=["POST"])
def api_providers_test(conn_id):
    import security as _sec
    u = _sec.current_user()
    if not u:
        return {"error": "nicht eingeloggt"}, 401
    try:
        from db import MTDB
        m = MTDB()
        # nur Verbindungen des eigenen Tenants testen
        conn = m.conn.execute(
            "SELECT * FROM provider_connections WHERE id = ? AND tenant_id = ?",
            (conn_id, _get_tid())).fetchone()
        if not conn:
            m.close()
            return {"error": "nicht gefunden"}, 404
        # Simulierter Test (kein echter API-Call im PAPER_ONLY-Modus)
        m.provider_connection_test(conn_id, ok=True)
        m.close()
        return {"ok": True, "status": "getestet"}
    except Exception as e:
        return {"error": str(e)}, 500


# ── PHASE 9 (S19-P9): Provider-Connection Status-Workflow (tenant-scoped) ──
@app.route("/api/providers/disable/<int:conn_id>", methods=["POST"])
def api_providers_disable(conn_id):
    import security as _sec
    if not _sec.current_user():
        return {"error": "nicht eingeloggt"}, 401
    tid = _get_tid()
    from db import MTDB
    m = MTDB()
    r = m.provider_connection_disable(conn_id, tid)
    m.close()
    if not r["ok"]:
        return {"error": r["reason"]}, 400
    sec.audit_log("provider_disable", str(conn_id), f"{r.get('old')} -> {r.get('new')}")
    return {"ok": True, "result": r}


@app.route("/api/providers/enable/<int:conn_id>", methods=["POST"])
def api_providers_enable(conn_id):
    import security as _sec
    if not _sec.current_user():
        return {"error": "nicht eingeloggt"}, 401
    tid = _get_tid()
    from db import MTDB
    m = MTDB()
    r = m.provider_connection_enable(conn_id, tid)
    m.close()
    if not r["ok"]:
        return {"error": r["reason"]}, 400
    sec.audit_log("provider_enable", str(conn_id), f"{r.get('old')} -> {r.get('new')}")
    return {"ok": True, "result": r}


@app.route("/api/providers/delete/<int:conn_id>", methods=["POST"])
def api_providers_delete(conn_id):
    import security as _sec
    if not _sec.current_user():
        return {"error": "nicht eingeloggt"}, 401
    tid = _get_tid()
    from db import MTDB
    m = MTDB()
    r = m.provider_connection_delete(conn_id, tid)
    m.close()
    if not r["ok"]:
        return {"error": r["reason"]}, 400
    sec.audit_log("provider_delete", str(conn_id))
    return {"ok": True, "result": r}


@app.route("/api/providers/status/<int:conn_id>", methods=["POST"])
def api_providers_status(conn_id):
    import security as _sec
    if not _sec.current_user():
        return {"error": "nicht eingeloggt"}, 401
    tid = _get_tid()
    new_status = request.form.get("status") or (request.json.get("status") if request.is_json else "")
    from db import MTDB
    m = MTDB()
    r = m.provider_connection_set_status(conn_id, tid, new_status)
    m.close()
    if not r["ok"]:
        return {"error": r["reason"]}, 400
    sec.audit_log("provider_status", str(conn_id), f"{r.get('old')} -> {r.get('new')}")
    return {"ok": True, "result": r}


@app.route("/api/secrets/rotate", methods=["POST"])
def api_secrets_rotate():
    import security as _sec
    u = _sec.current_user()
    if not u or _sec.effective_role(u) not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung"}, 403
    tid = _get_tid()
    skey = request.form.get("key") or (request.json.get("key") if request.is_json else "")
    sval = request.form.get("value") or (request.json.get("value") if request.is_json else "")
    if not skey or not sval:
        return {"error": "key und value erforderlich"}, 400
    from db import MTDB
    m = MTDB()
    r = m.secret_rotate(tid, skey, sval)
    m.close()
    if not r["ok"]:
        return {"error": r["reason"]}, 400
    sec.audit_log("secret_rotate", str(skey), "None -> rotated")
    # NIEMALS Klartext zurueckgeben - nur last4
    return {"ok": True, "rotated": skey, "last4": r.get("last4")}

# ── PHASE 14 (S19-P14): Live-Antragsprozess ─────────────────────────────
def _live_db():
    """01.11.2026: Die Live-Antrags-Routen riefen db.live_request_*() auf,
    ein Name db existierte nie (NameError -> HTTP 500). Zugriff bleibt
    TENANT_ADMIN (security.ROUTE_ACCESS)."""
    from db import MTDB
    return MTDB()


@app.route("/api/live-requests", methods=["GET", "POST"])
def api_live_requests():
    tid = _get_tid()
    if not tid:
        return {"error": "tenant?"}, 400
    if request.method == "POST":
        d = request.get_json(force=True, silent=True) or {}
        res = _live_db().live_request_create(
            tid, d.get("requested_by", session.get("user_id")),
            broker_connection_id=d.get("broker_connection_id"),
            risk_assessment=d.get("risk_assessment"),
            note=d.get("note"))
        if not res["ok"]:
            return res, 409
        sec.audit_log("live_request_create", session.get("user_id"), f"tenant={tid} req={res['id']}")
        return res, 201
    return {"requests": _live_db().live_request_list(tid)}


@app.route("/api/live-requests/<int:req_id>/review", methods=["POST"])
def api_live_request_review(req_id):
    tid = _get_tid()
    if not tid:
        return {"error": "tenant?"}, 400
    d = request.get_json(force=True, silent=True) or {}
    res = _live_db().live_request_review(req_id, tid, d.get("reviewed_by", session.get("user_id")))
    if not res["ok"]:
        return res, 400
    sec.audit_log("live_request_review", session.get("user_id"), f"req={req_id} tenant={tid}")
    return res


@app.route("/api/live-requests/<int:req_id>/approve", methods=["POST"])
def api_live_request_approve(req_id):
    tid = _get_tid()
    if not tid:
        return {"error": "tenant?"}, 400
    d = request.get_json(force=True, silent=True) or {}
    res = _live_db().live_request_approve(req_id, tid, d.get("approved_by", session.get("user_id")),
                                   note=d.get("note"))
    if not res["ok"]:
        return res, 400
    sec.set_trading_mode("LIVE_REQUESTED", tenant_id=tid, user=session.get("user_id"),
                         reason=f"Live-Antrag {req_id} freigegeben")
    sec.audit_log("live_request_approve", session.get("user_id"), f"req={req_id} tenant={tid}")
    return res


@app.route("/api/live-requests/<int:req_id>/reject", methods=["POST"])
def api_live_request_reject(req_id):
    tid = _get_tid()
    if not tid:
        return {"error": "tenant?"}, 400
    d = request.get_json(force=True, silent=True) or {}
    res = _live_db().live_request_reject(req_id, tid, d.get("rejected_by", session.get("user_id")),
                                  note=d.get("note"))
    if not res["ok"]:
        return res, 400
    sec.audit_log("live_request_reject", session.get("user_id"), f"req={req_id} tenant={tid}")
    return res


@app.route("/api/live-requests/<int:req_id>/activate", methods=["POST"])
def api_live_request_activate(req_id):
    tid = _get_tid()
    if not tid:
        return {"error": "tenant?"}, 400
    res = _live_db().live_request_activate(req_id, tid)
    if not res["ok"]:
        return res, 400
    sec.set_trading_mode("LIVE_APPROVED", tenant_id=tid, user=session.get("user_id"),
                         reason=f"Live-Antrag {req_id} aktiviert")
    sec.audit_log("live_request_activate", session.get("user_id"), f"req={req_id} tenant={tid}")
    return res



# ── PHASE 8: Secret-Store (tenant-isoliert, kein global .env) ──
@app.route("/api/secrets", methods=["GET"])
def api_secrets_list():
    import security as _sec
    u = _sec.current_user()
    if not u or _sec.effective_role(u) not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung"}, 403
    tid = _get_tid()
    # Nur Schluessel, NIEMALS Werte
    return {"tenant_id": tid, "keys": _sec.secret_list_keys(tid)}


@app.route("/api/secrets/set", methods=["POST"])
def api_secrets_set():
    import security as _sec
    u = _sec.current_user()
    if not u or _sec.effective_role(u) not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung"}, 403
    tid = _get_tid()
    skey = request.form.get("key") or (request.json.get("key") if request.is_json else "")
    sval = request.form.get("value") or (request.json.get("value") if request.is_json else "")
    if not skey or not sval:
        return {"error": "key/value fehlt"}, 400
    _sec.secret_set(tid, skey, sval)
    return {"ok": True, "key": skey, "stored": "tenant-scoped"}


# ── PHASE 10: Tenant-Scoped Risikogrenzen ──
@app.route("/api/risk", methods=["GET"])
def api_risk_list():
    import security as _sec
    u = _sec.current_user()
    if not u or _sec.effective_role(u) not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung"}, 403
    tid = _get_tid()
    return {"tenant_id": tid, "mode": request.args.get("mode", "moderate"),
            "limits": _sec.risk_get(tid, request.args.get("mode", "moderate"))}


@app.route("/api/risk/set", methods=["POST"])
def api_risk_set():
    import security as _sec
    u = _sec.current_user()
    if not u or _sec.effective_role(u) not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung"}, 403
    tid = _get_tid()
    mode = (request.form.get("mode") or (request.json.get("mode") if request.is_json else "")) or "moderate"
    _sec.risk_set(
        tid, mode,
        position_size=_opt_float(request, "position_size"),
        stop_loss=_opt_float(request, "stop_loss"),
        take_profit=_opt_float(request, "take_profit"),
        drawdown_limit=_opt_float(request, "drawdown_limit"))
    return {"ok": True, "tenant_id": tid, "mode": mode}


# ── PHASE 11: Tenant-Scoped Regeln ──
@app.route("/api/rules", methods=["GET"])
def api_rules_list():
    import security as _sec
    u = _sec.current_user()
    if not u or _sec.effective_role(u) not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung"}, 403
    tid = _get_tid()
    return {"tenant_id": tid, "rules": _sec.rule_list(tid)}


@app.route("/api/rules/add", methods=["POST"])
def api_rules_add():
    import security as _sec
    u = _sec.current_user()
    if not u or _sec.effective_role(u) not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung"}, 403
    tid = _get_tid()
    rid = (request.form.get("rule_id") or (request.json.get("rule_id") if request.is_json else ""))
    regel = (request.form.get("regel") or (request.json.get("regel") if request.is_json else ""))
    if not rid or not regel:
        return {"error": "rule_id/regel fehlt"}, 400
    _sec.rule_add(tid, rid, regel,
                  muster=(request.form.get("muster") or (request.json.get("muster") if request.is_json else "")) or None,
                  status=(request.form.get("status") or (request.json.get("status") if request.is_json else "")) or "aktiv",
                  created_by=u.get("id") if isinstance(u, dict) else None)
    return {"ok": True, "rule_id": rid, "tenant_id": tid}


@app.route("/api/rules/set_status", methods=["POST"])
def api_rules_set_status():
    import security as _sec
    u = _sec.current_user()
    if not u or _sec.effective_role(u) not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung"}, 403
    tid = _get_tid()
    rid = (request.form.get("rule_id") or (request.json.get("rule_id") if request.is_json else ""))
    status = (request.form.get("status") or (request.json.get("status") if request.is_json else ""))
    if not rid or not status:
        return {"error": "rule_id/status fehlt"}, 400
    _sec.rule_set_status(tid, rid, status)
    return {"ok": True, "rule_id": rid, "status": status}


def _opt_float(req, name):
    """Hilfsfunktion: Form/JSON-Float optional auslesen (None wenn leer)."""
    v = req.form.get(name) or (req.json.get(name) if req.is_json else "")
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


@app.route("/api/db_query")
def api_db_query():
    try:
        from db import MTDB
        db = MTDB()
        mode = request.args.get("mode", "trades")
        typ = request.args.get("typ", "")
        ticker = request.args.get("ticker", "")
        aktion = request.args.get("aktion", "")
        tage = request.args.get("tage", type=int, default=30)
        order = request.args.get("order", "DESC")
        limit = request.args.get("limit", type=int, default=500)
        provider = request.args.get("provider", "")
        regel_id = request.args.get("regel_id", "")
        fallback = request.args.get("fallback", "")
        # PHASE 4: Tenant-Scope erzwingen (nie global, nie aus Client)
        _tid = 1
        try:
            import security as _sec
            _tid = _sec.get_current_tenant() or 1
        except Exception:
            pass
        if mode == "ki":
            rows = db.query_ki(ticker=ticker, limit=limit, provider=provider or None,
                               regel_id=regel_id or None,
                               fallback=(fallback == "true") if fallback else None,
                               tenant_id=_tid)
        else:
            rows = db.query_trades(typ=typ, ticker=ticker, aktion=aktion, tage=tage, order=order, limit=limit,
                                   tenant_id=_tid)
        db.close()
        return {"error": None, "count": len(rows), "rows": rows}
    except Exception as e:
        return {"error": str(e), "count": 0, "rows": []}


@app.route("/api/db_karten")
def api_db_karten():
    try:
        from db import MTDB
        db = MTDB()
        tage = request.args.get("tage", type=int, default=30)
        karten = db.analyse_karten(tage=tage)
        db.close()
        return {"error": None, "karten": karten}
    except Exception as e:
        return {"error": str(e), "karten": {}}


@app.route("/depot_json")
def depot_json():
    depot_id_arg = request.args.get("id", "")
    risk = request.args.get("risk", type=int)
    # Neue Depots: id=aktien:100:1 -> _depot_pfad_aus_id
    if depot_id_arg:
        dp = _depot_pfad_aus_id(depot_id_arg)
        if not dp:
            return {"error": "not found"}
    else:
        if risk is None:
            return {"error": "risk or id parameter required"}
        dp = depot_pfad(risk)
        if not os.path.exists(dp):
            return {"error": "not found"}
    # PHASE 4: Tenant-Scope
    try:
        import security as _sec, json as _j
        tid = _sec.get_current_tenant() or 1
        with open(dp, encoding='utf-8') as f:
            d = _j.load(f)
        if d.get("tenant_id", 1) != tid:
            return {"error": "forbidden"}, 403
        return d
    except Exception:
        with open(dp) as f:
            return json.load(f)

@app.route("/spec_depot_json")
def spec_depot_json():
    ticker = request.args.get("ticker", "")
    if not ticker:
        return {"error": "ticker parameter required"}
    dp = os.path.join(BASE, "spec_depots", "%s.json" % ticker)
    if not os.path.exists(dp):
        return {"error": "not found"}
    with open(dp) as f:
        return json.load(f)


@app.route("/etf_depot_json")
def etf_depot_json():
    """Liefert das vollständige ETF-Depot-JSON für die Detailseite.
    Kompatibel mit showDepot(): enthält positions, trades, historie, ki_letzte."""
    risk = request.args.get("risk", type=int)
    if risk is None:
        return {"error": "risk parameter required"}
    # 29.09.2026: Die Route las fest etf_NNN.json - das sind die
    # alten SHADOW-Depots, die am 29.09. archiviert wurden. Die
    # zehn Testdepots heissen etf_NNN_01_paper.json, und welcher
    # Satz gilt, steht in der Datenbank. Dieselbe Logik wie in
    # etf_trader.etf_pfad(): sonst zeigt die Detailseite nichts -
    # oder, im Modusfehler, ein Depot aus einem anderen Test.
    try:
        import security as _sec
        _tid = _sec.get_current_tenant() or 1
        _mode = _sec.get_trading_mode(_tid) or "SHADOW"
    except Exception:
        _mode = "SHADOW"
    _suffix = "_01_paper" if _mode == "PAPER" else ""
    ep = os.path.join(BASE, "etf_%03d%s.json" % (risk, _suffix))
    if not os.path.exists(ep):
        return {"error": "not found"}
    with open(ep) as f:
        d = json.load(f)
    # 29.09.2026: Die Depot-Dateien speichern keinen Gesamtwert, nur
    # Bargeld und Positionen. Die Detailseite hatte deshalb immer 0.
    # Gerechnet wird aus Bargeld + Anteile x Einstandspreis; das ist
    # bewusst konservativ, es zaehlt nichts als Gewinn, was nicht
    # realisiert wurde.
    try:
        _bargeld = d.get("bargeld") or 0.0
        _wert = _bargeld
        for _t, _p in (d.get("positions") or {}).items():
            _wert += (_p.get("shares") or 0) * (_p.get("avg_price") or 0)
        d["depot_wert"] = round(_wert, 2)
        _start = d.get("start_wert") or 0
        d["rendite_pct"] = (round((_wert / _start - 1) * 100, 2)
                            if _start else None)
    except Exception:
        d.setdefault("depot_wert", None)
        d.setdefault("rendite_pct", None)

    # stufe fuer Anzeige ergaenzen (falls fehlt)
    if "stufe" not in d:
        try:
            stufen = ["Sehr konservativ", "Konservativ", "Ausgewogen",
                      "Wachstum", "Aggressiv", "Sehr aggressiv"]
            d["stufe"] = stufen[min(5, risk // 20)]
        except Exception:
            d["stufe"] = "Risk %d" % risk
    return d

@app.route("/ticker_chart")
def ticker_chart():
    """6-Monats-Kursverlauf für einen Ticker (JSON für Chart.js)."""
    import yfinance as yf
    ticker = request.args.get("ticker", "").upper().strip()
    if not ticker:
        return {"error": "ticker parameter required", "data": [], "dates": []}
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="6mo", interval="1d")
        if hist.empty:
            return {"ticker": ticker, "dates": [], "data": [], "error": "keine Daten"}
        close = hist["Close"]
        return {
            "ticker": ticker,
            "name": name_for(ticker),
            "dates": [str(d.date()) for d in close.index],
            "data": [round(float(v), 2) for v in close.values],
        }
    except Exception as e:
        return {"ticker": ticker, "dates": [], "data": [], "error": str(e)}

@app.route("/api/analysis")
def api_analysis():
    cache_path = os.path.join(BASE, "analysis_cache.json")
    # Cache nur nutzen, wenn valide (Race-Condition-sicher)
    if os.path.exists(cache_path) and time.time() - os.path.getmtime(cache_path) < 300:
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError):
            pass  # korrupter Cache -> neu berechnen
    from analysis import run_all
    try:
        result = run_all()
    except Exception:
        return jsonify({"zeit": "", "aktien": {}, "etf": {}, "spekulation": {},
                         "risiko_aktien": {}, "risiko_etf": {}, "risiko_spekulation": {}})
    # Atomar schreiben: temp-file + rename (verhindert truncated cache bei Concurrent-Writes)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    os.replace(tmp, cache_path)
    return result

# ─── Settings API (KI + Lernen + Bremsen + News) ─────────────
@app.route("/api/version")
def api_version():
    """Liefert version.json (Changelog/Version-Log)."""
    try:
        with open(os.path.join(BASE, "version.json"), encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({"version": "?", "released_at": "?", "codename": "", "changes": []})

@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    from settings_loader import lade_settings, LIMITS, BOOLS, LABELS
    return jsonify({
        "settings": lade_settings(),
        "limits": {k: {"min": v[0], "max": v[1], "emp_min": v[2], "emp_max": v[3],
                        "einheit": v[4], "warn_unter": v[5], "warn_ueber": v[6]}
                    for k, v in LIMITS.items() if k not in BOOLS},
        "bools": BOOLS,
        "labels": {k: {"name": v[0], "desc": v[1]} for k, v in LABELS.items()},
    })

@app.route("/api/settings", methods=["POST"])
@app.route("/api/report_pdf")
def api_report_pdf():
    """Phase 10 (§17): Manueller PDF-Report-Trigger (neben 22:00-Cron)."""
    try:
        import subprocess, os
        from datetime import datetime
        # report_pdf.py im gleichen Verzeichnis ausführen
        subprocess.run(
            [sys.executable, os.path.join(BASE, "report_pdf.py")],
            capture_output=True, timeout=120
        )
        heute = datetime.now().strftime("%Y-%m-%d")
        pfad = os.path.join(BASE, "reports", f"micro_trader_{heute}.pdf")
        if os.path.exists(pfad):
            return {"ok": True, "pfad": pfad,
                    "url": f"/reports/micro_trader_{heute}.pdf"}
        return {"ok": False, "error": "PDF nicht erstellt"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/report_list")
def api_report_list():
    """Liste aller archivierten PDFs (reports/)."""
    try:
        import glob, os
        files = sorted(glob.glob(os.path.join(BASE, "reports", "*.pdf")),
                       key=os.path.getmtime, reverse=True)
        return {"ok": True, "reports": [
            {"name": os.path.basename(f),
             "url": f"/reports/{os.path.basename(f)}",
             "size": os.path.getsize(f),
             "datum": datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M")}
            for f in files[:30]
        ]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/reports/<path:name>")
def serve_report(name):
    """PDF direkt ausliefern (Download/Anzeige)."""
    from flask import send_from_directory
    return send_from_directory(os.path.join(BASE, "reports"), name)


def api_settings_post():
    from settings_loader import speichere_settings, validiere_und_risiko
    payload = request.get_json(force=True, silent=True) or {}
    neue = payload.get("settings", {})
    bestaetigt = payload.get("bestaetigt", False)
    ok, meldung, warnungen = speichere_settings(neue, bestaetigt=bestaetigt)
    if not ok and warnungen and not bestaetigt:
        # Risikowarnung → Frontend muss erneut mit bestaetigt=true senden
        return jsonify({"ok": False, "warnung": True, "meldung": meldung,
                        "warnungen": warnungen}), 200
    return jsonify({"ok": ok, "meldung": meldung, "warnungen": warnungen}), 200

# ─── PHASE 4-6: Security-Hooks (serverseitige Routenprüfung + Header) ───────
import functools

@ app.after_request
def _security_headers(resp):
    """Setzt OWASP-konforme Security-Header (Phase 5)."""
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; base-uri 'self'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


@ app.route("/api/csrf_token")
def api_csrf_token():
    """LUECKE 7 (2026-09-27): stellt dem angemeldeten Frontend ein CSRF-Token
    aus. Vorher gab es keinen Token-Endpunkt und das Frontend schickte nie
    einen X-CSRF-Token-Header — der Guard fiel damit immer auf die
    permissive Lokal-Origin-Regel zurueck."""
    u = sec.current_user()
    if not u:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"csrf_token": sec.generate_csrf_token()})


@ app.before_request
def _csrf_protect():
    """BUG-005: CSRF-Schutz fuer alle mutierenden Requests (POST/PUT/DELETE).
    Token aus X-CSRF-Token-Header (vom Frontend global mitgeschickt) oder
    csrf_token-Formfeld. Bei Fremd-Origin ohne gueltiges Token -> 403.
    Lokale Origin (127.0.0.1/localhost) bleibt permissiv (kein Cross-Site-
    Risiko), damit das lokale Dashboard nicht bricht. Login/Public ausgenommen.

    LUECKE 7 (2026-09-27): GET/HEAD werden nicht mehr pauschal uebersprungen.
    sec.CSRF_MUTATING_GET_PATHS enthaelt die GET-Routen, die den Zustand
    aendern (Trading-Pause, Risiko-Appetit, Depot loeschen/verkaufen/...).
    Fuer diese gilt derselbe Token-Zwang wie fuer POST. Reine Lese-GETs
    bleiben unveraendert token-frei — das Dashboard-Verhalten bleibt gleich.
    """
    if request.method in ("GET", "HEAD"):
        # Nur zustandsaendernde GETs brauchen ein Token — und hier OHNE die
        # permissive Lokal-Origin-Ausnahme (siehe
        # sec.csrf_token_strict_valid_for_request): der Dienst ist ueber
        # Tailscale/Reverse-Proxy erreichbar, die Ausnahme haette den Schutz
        # komplett aufgehoben.
        if not sec.csrf_token_required(request.path, request.method):
            return
        if not sec.csrf_token_strict_valid_for_request(request):
            return jsonify({"error": "csrf_token_invalid"}), 403
        return
    if request.method == "OPTIONS":
        return
    _public = ("/login", "/logout", "/static/", "/api/health", "/api/csrf_token")
    if request.path in _public or request.path.startswith(_public):
        return
    if not sec.csrf_token_valid_for_request(request):
        # Fremd-Origin-Angriff ohne Token -> blocken
        if request.path.startswith("/api/") or "application/json" in (request.headers.get("Accept", "") or ""):
            return jsonify({"error": "csrf_token_invalid"}), 403
        return "CSRF-Token ungueltig", 403


@ app.before_request
def _route_access_control():
    """PHASE 6: serverseitige Zugriffskontrolle für ALLE Routen.
    Frontend-Ausblendung ist KEINE Berechtigung (Auftrag Regel 5)."""
    rule = request.path
    cls = sec.route_class(rule)
    if cls == "PUBLIC":
        return
    # FIX 27.09.2026: Maschinen-Authentifizierung zentral einloesen.
    # Vorher gab es zwei Guards (_api_key_auth und dieser hier), und der
    # API-Key konnte konstruktionsbedingt nie greifen, weil dieser Hook
    # ausschliesslich die Session prueft. Der Vergleich nutzt
    # hmac.compare_digest, damit die Laufzeit nichts ueber den Key
    # verraten kann.
    if cls != "PUBLIC" and _api_key_ok():
        return
    # JSON-Routen (API/JS-Fetch) bekommen bei fehlendem Auth IMMER 401/403 JSON,
    # nie einen HTML-Redirect (sonst parse-Fehler "Unexpected token '<'" im Frontend).
    json_routes = ("/api/", "/search_ticker", "/ticker_chart", "/data",
                   "/depot_json", "/spec_depot_json", "/etf_depot_json", "/reports/")
    wants_json = request.path.startswith(json_routes) or \
        "application/json" in (request.headers.get("Accept", "") or "")
    u = sec.current_user()
    if cls == "AUTHENTICATED":
        if not u or not sec.access_level_met(u["role"], "AUTHENTICATED"):
            if wants_json:
                return jsonify({"error": "unauthorized"}), 401
            return redirect("/login?next=" + rule)
        sec.touch_session(u["username"], sec._current_sid())
        # PHASE 1: Tenant-Kontext aus der Session ableiten (nie aus Client-Input)
        sec.set_current_tenant(sec.resolve_tenant_for_user(u))
        return
    # PHASE 2: TENANT_ADMIN — Prüfung gegen EFFEKTIVE Rolle (Membership gewinnt).
    # Setzt den Tenant-Kontext ebenfalls (wie AUTHENTICATED), damit
    # require_tenant_role im Handler im richtigen Kontext prüft.
    if cls == "TENANT_ADMIN":
        if not u:
            if wants_json:
                return jsonify({"error": "unauthorized"}), 401
            return redirect("/login?next=" + rule)
        sec.set_current_tenant(sec.resolve_tenant_for_user(u))
        eff = sec.effective_role(u)
        if not sec.access_level_met(eff, "ADMIN"):
            return jsonify({"error": "forbidden"}), 403
        sec.touch_session(u["username"], sec._current_sid())
        return
    # ANALYST / OPERATOR / ADMIN / SUPERADMIN
    if not u:
        if wants_json:
            return jsonify({"error": "unauthorized"}), 401
        return redirect("/login?next=" + rule)
    if not sec.access_level_met(u["role"], cls):
        if wants_json:
            return jsonify({"error": "forbidden"}), 403
        return jsonify({"error": "forbidden"}), 403
    sec.touch_session(u["username"], sec._current_sid())
    return


# ─── PHASE 4: Auth-Routen (Login/Logout/MFA) ────────────────────────────────
@ app.route("/login", methods=["GET", "POST"])
def login():
    """Login (Phase 4). Setzt sichere Session-Cookies."""
    if request.method == "POST":
        uname = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        rest = sec.login_blocked(request.remote_addr or "?", uname)
        if rest:
            sec.audit_log("login_blocked", uname or "?", f"ip={request.remote_addr or '?'} rest={rest}s")
            return make_response(f"<h1>Zu viele Fehlversuche</h1><p>Bitte warte {rest} Sekunden.</p><a href='/login'>zurück</a>"), 429
        if sec.verify_password(uname, pw):
            sid = sec.create_session(uname, request.remote_addr or "")
            # Session-Rotation nach Login (Phase 5)
            sid = sec.rotate_session(uname, sid) or sid
            _login_ctx = f"ip={request.remote_addr or '?'} ua={(request.user_agent.string or '?')[:80]}"
            sec.audit_log("login", uname, _login_ctx)
            sec.register_login_ok(request.remote_addr or "?", uname)
            resp = make_response(redirect(request.args.get("next") or "/dashboard"))
            resp.set_cookie("username", uname, httponly=True, samesite="Lax",
                            secure=False)  # secure=True erst bei HTTPS/Funnel
            resp.set_cookie("sid", sid, httponly=True, samesite="Lax",
                            secure=False)
            u = sec.get_user(uname)
            u["last_login"] = datetime.utcnow().isoformat() + "Z"
            sec.audit_log("login", uname, f"ip={request.remote_addr or '?'} ua={(request.user_agent.string or '?')[:80]}")
            return resp
        sec.audit_log("login_failed", uname, f"ip={request.remote_addr or '?'} ua={(request.user_agent.string or '?')[:80]}")
        sec.register_login_fail(request.remote_addr or "?", uname)
        return make_response("<h1>Login fehlgeschlagen</h1><a href='/login'>neu</a>"), 401
    # GET: gestylte Login-Card (konsistent mit /landing Stil)
    return make_response(f"""<!doctype html><html lang='de'><head><meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Micro-Trader – Anmeldung</title>
<style>
body{{font-family:'Segoe UI Variable','Segoe UI',system-ui,sans-serif;margin:0;padding:0;background:#f8fafc;background-image:radial-gradient(ellipse at 15% 0%,rgba(37,99,235,.08) 0%,transparent 55%),radial-gradient(ellipse at 85% 0%,rgba(16,185,129,.05) 0%,transparent 50%);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:32px 24px;box-sizing:border-box}}
.card{{max-width:400px;width:100%;background:rgba(255,255,255,.92);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.95);border-radius:18px;box-shadow:0 24px 48px rgba(61,93,153,.12);overflow:hidden}}
.banner{{width:100%;height:92px;display:flex;align-items:center;justify-content:center;background:#0f172a;color:#fff;font-size:20px;font-weight:700;letter-spacing:.3px}}
.banner .dot{{width:10px;height:10px;border-radius:50%;background:#22c55e;margin-right:10px;box-shadow:0 0 0 4px rgba(34,197,94,.25)}}
.inner{{padding:24px 26px 26px}}
h2{{font-size:22px;margin:0 0 4px;color:#0f172a}}
.badge{{display:inline-block;background:#e8f5e9;color:#1b5e20;border-radius:999px;padding:3px 11px;font-size:11.5px;font-weight:600;margin-bottom:14px}}
label{{display:block;margin-top:14px;font-size:13px;font-weight:600;color:#334155}}
input{{display:block;width:100%;box-sizing:border-box;margin-top:5px;padding:11px 13px;font-size:16px;border:1px solid #cbd5e1;border-radius:10px;background:#fff;font-family:inherit;transition:border-color .15s,box-shadow .15s}}
input:focus{{outline:none;border-color:#2563eb;box-shadow:0 0 0 4px rgba(37,99,235,.12)}}
button{{margin-top:18px;width:100%;background:#2563eb;color:#fff;border:none;padding:12px 0;border-radius:12px;font-size:15.5px;font-weight:600;cursor:pointer;transition:background .15s,transform .05s}}
button:hover{{background:#1d4ed8}}
button:active{{transform:translateY(1px)}}
.hint{{margin-top:14px;font-size:11.5px;color:#94a3b8;text-align:center}}
a{{color:#2563eb;text-decoration:none;font-weight:600}}
</style></head><body>
<div class='card'>
  <div class='banner'><span class='dot'></span>Micro-Trader</div>
  <div class='inner'>
    <h2>Anmeldung</h2>
    <span class='badge'>Paper-/Shadow-Trading · kein Echtgeld</span>
    <form method='POST'>
      <label for='u'>Benutzer</label>
      <input id='u' name='username' autocomplete='username' placeholder='goldi5'>
      <label for='p'>Passwort</label>
      <input id='p' name='password' type='password' autocomplete='current-password' placeholder='••••••••'>
      <button type='submit'>Einloggen</button>
    </form>
    <div class='hint'><a href='/landing'>← Zurück zur Übersicht</a></div>
  </div>
</div></body></html>""")


@ app.route("/logout")
def logout():
    uname = request.cookies.get("username")
    sid = request.cookies.get("sid")
    if uname and sid:
        sec.revoke_session(uname, sid)
    resp = make_response(redirect("/landing"))
    resp.delete_cookie("username")
    resp.delete_cookie("sid")
    return resp


@ app.route("/mfa", methods=["GET", "POST"])
def mfa_verify():
    """MFA-Verifizierung (Phase 4). Erforderlich für admin/superadmin."""
    uname = request.cookies.get("username")
    sid = request.cookies.get("sid")
    if not uname or not sid or not sec.session_valid(uname, sid):
        return redirect("/login")
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        # LUECKE 4 (2026-09-27): ueber verify_mfa_code() mit Replay-Schutz.
        # Vorher: sec.verify_mfa(u.get("mfa_secret", ""), code) — das liefert
        # bei mfa_secret=None ein None (Key existiert, Wert ist None) und
        # crashte mit AttributeError -> HTTP 500. Ausserdem war derselbe
        # TOTP-Code im ±1-Fenster beliebig oft wiederverwendbar.
        ok, _fehler = sec.verify_mfa_code(uname, code)
        if ok:
            sec.mark_mfa_verified(uname, sid)
            sec.audit_log("mfa_verify", uname)
            return redirect("/admin")
        return make_response("<h1>MFA falsch</h1><a href='/mfa'>neu</a>"), 401
    return make_response(
        "<form method='POST'>MFA-Code:<input name='code'><br>"
        "<input type='submit' value='OK'></form>")


@ app.route("/setup_mfa", methods=["GET", "POST"])
@ sec.require_role("admin")
def setup_mfa():
    """MFA für aktuellen User einrichten (Provisioning)."""
    uname = request.cookies.get("username")
    u = sec.get_user(uname)
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        if sec.enable_mfa(uname, code):
            return redirect("/data")
        return make_response("<h1>Code falsch</h1><a href='/setup_mfa'>neu</a>")
    pending = sec.generate_mfa_secret()
    u["mfa_pending_secret"] = pending
    sec._save_users({x["username"]: x for x in sec.list_users()})
    uri = sec.mfa_provisioning_uri(pending, uname)
    return make_response(
        f"<h1>MFA einrichten</h1><p>Secret: {pending}</p>"
        f"<p><a href='{uri}'>otpauth-Link</a></p>"
        f"<form method='POST'>Code:<input name='code'><br>"
        f"<input type='submit' value='Aktivieren'></form>")


# ─── Öffentliche Landingpage (nur allgemeine Infos, kein internes JSON) ──
@app.route("/", methods=["GET", "POST"])
@app.route("/landing", methods=["GET", "POST"])
def landing():
    """Öffentliche Landingpage (PUBLIC).
    Darf NUR: Projektname, Kurzbeschreibung, Paper-/Shadow-Hinweis,
    Betriebsstatus OHNE interne Details, Login-Formular direkt auf der Seite.
    Lädt KEINE internen JSON-Daten (Depot/KI/Regeln/Provider/Logs)."""
    status = "Paper-/Shadow-Trading-System (kein Echtgeld)"
    fehler = ""
    if request.method == "POST":
        uname = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        rest = sec.login_blocked(request.remote_addr or "?", uname)
        if rest:
            sec.audit_log("login_blocked", uname or "?", f"ip={request.remote_addr or '?'} rest={rest}s")
            fehler = f"<div style='margin:10px 0 0;color:#b91c1c;background:#fee2e2;border:1px solid #fecaca;border-radius:8px;padding:8px 12px;font-size:13px'>Zu viele Fehlversuche – bitte warte {rest} Sekunden.</div>"
            return make_response(f"""<!doctype html><html lang='de'><head><meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'><title>Micro-Trader – Anmeldung</title></head><body style='font-family:Segoe UI,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#f8fafc'>
<div style='background:#fff;border-radius:18px;box-shadow:0 24px 48px rgba(61,93,153,.12);padding:32px;max-width:380px;text-align:center'>
<h2 style='margin:0 0 12px;color:#0f172a'>⏳ Zu viele Fehlversuche</h2>
<p style='color:#475569;font-size:14px'>Bitte warte <b>{rest} Sekunden</b>, bevor du es erneut versuchst.</p>
<a href='/' style='display:inline-block;margin-top:14px;color:#2563eb;text-decoration:none;font-weight:600'>← Zurück</a>
</div></body></html>"""), 429
        if sec.verify_password(uname, pw):
            sid = sec.create_session(uname, request.remote_addr or "")
            sid = sec.rotate_session(uname, sid) or sid
            resp = make_response(redirect("/dashboard"))
            resp.set_cookie("username", uname, httponly=True, samesite="Lax", secure=False)
            resp.set_cookie("sid", sid, httponly=True, samesite="Lax", secure=False)
            u = sec.get_user(uname)
            u["last_login"] = datetime.utcnow().isoformat() + "Z"
            sec.audit_log("login", uname, f"ip={request.remote_addr or '?'} ua={(request.user_agent.string or '?')[:80]}")
            sec.register_login_ok(request.remote_addr or "?", uname)
            return resp
        sec.audit_log("login_failed", uname, f"ip={request.remote_addr or '?'} ua={(request.user_agent.string or '?')[:80]}")
        sec.register_login_fail(request.remote_addr or "?", uname)
        fehler = "<div style='margin:10px 0 0;color:#b91c1c;background:#fee2e2;border:1px solid #fecaca;border-radius:8px;padding:8px 12px;font-size:13px'>Anmeldung fehlgeschlagen – Benutzername oder Passwort falsch.</div>"
    return make_response(f"""<!doctype html><html lang='de'><head><meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Micro-Trader – Anmeldung</title>
<style>
body{{font-family:'Segoe UI Variable','Segoe UI',system-ui,sans-serif;margin:0;padding:0;background:#f8fafc;background-image:radial-gradient(ellipse at 15% 0%,rgba(37,99,235,.08) 0%,transparent 55%),radial-gradient(ellipse at 85% 0%,rgba(16,185,129,.05) 0%,transparent 50%);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:32px 24px;box-sizing:border-box}}
.shell{{display:flex;gap:40px;max-width:960px;width:100%;align-items:center;flex-wrap:wrap;justify-content:center}}
.hero{{flex:1.2;min-width:300px;max-width:520px}}
.hero .brand{{display:flex;align-items:center;gap:12px;margin-bottom:10px}}
.hero .brand img{{width:48px;height:48px;border-radius:12px}}
.hero h1{{font-size:34px;line-height:1.15;margin:0 0 10px;color:#0f172a;font-weight:700}}
.hero p.lead{{font-size:15px;line-height:1.6;color:#475569;margin:0 0 20px}}
.features{{display:flex;flex-direction:column;gap:10px;margin-bottom:18px}}
.feature{{display:flex;align-items:flex-start;gap:12px;background:rgba(255,255,255,.75);backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.9);border-radius:14px;padding:12px 14px;box-shadow:0 4px 16px rgba(61,93,153,.06)}}
.feature .ic{{width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:17px;flex-shrink:0;background:rgba(37,99,235,.08)}}
.feature b{{font-size:13.5px;color:#0f172a;display:block}}
.feature span{{font-size:12px;color:#64748b;line-height:1.4}}
.meta{{font-size:11.5px;color:#94a3b8}}
.card{{max-width:400px;width:100%;background:rgba(255,255,255,.9);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.95);border-radius:18px;box-shadow:0 24px 48px rgba(61,93,153,.12);overflow:hidden}}
.banner{{width:100%;height:96px;display:block;object-fit:contain;object-position:center;background:#0f172a;border-bottom:1px solid rgba(15,23,42,.07)}}
.inner{{padding:24px 26px 26px}}
.head{{display:flex;align-items:center;gap:10px;margin-bottom:6px}}
.logo{{width:36px;height:36px;border-radius:9px}}
h2{{font-size:22px;margin:0;color:#0f172a}}
.badge{{display:inline-block;background:#e8f5e9;color:#1b5e20;border-radius:999px;padding:3px 11px;font-size:11.5px;font-weight:600;margin-bottom:10px}}
p{{line-height:1.55;color:#475569;margin:6px 0}}
.status{{color:#64748b;font-size:12px}}
label{{display:block;margin-top:12px;font-size:13px;font-weight:600;color:#334155}}
input{{display:block;width:100%;box-sizing:border-box;margin-top:5px;padding:11px 13px;font-size:16px;border:1px solid #cbd5e1;border-radius:10px;background:#fff;font-family:inherit;transition:border-color .15s,box-shadow .15s}}
input:focus{{outline:none;border-color:#2563eb;box-shadow:0 0 0 4px rgba(37,99,235,.12)}}
button{{margin-top:16px;width:100%;background:#2563eb;color:#fff;border:none;padding:12px 0;border-radius:12px;font-size:15.5px;font-weight:600;cursor:pointer;transition:background .15s,transform .05s}}
button:hover{{background:#1d4ed8}}
button:active{{transform:translateY(1px)}}
.hint{{margin-top:12px;font-size:11.5px;color:#94a3b8;text-align:center}}
</style></head><body>
<div class='shell'>
<div class='hero'>
<div class='brand'><img src='/assets/logo.png' alt='Logo'><div><div style='font-size:15px;font-weight:700;color:#0f172a'>Micro-Trader</div><div style='font-size:11px;color:#64748b'>GOVERNED AI MARKET OPERATIONS</div></div></div>
<h1>Automatisiertes Paper-Trading,<br>sicher und kontrolliert.</h1>
<p class='lead'>Die KI analysiert Aktien, ETF und Spekulation – alle Entscheidungen laufen ausschließlich in simulierten Depots. <b>Kein Echtgeldeinsatz.</b></p>
<div class='features'>
<div class='feature'><div class='ic'>🤖</div><div><b>KI-gesteuerte Entscheidungen</b><span>Kauf-/Verkaufs-Signale mit Konfidenz-Score, Regeln und Audit-Trail.</span></div></div>
<div class='feature'><div class='ic'>🛡️</div><div><b>Mehrbenutzer mit Rollen</b><span>Benutzerverwaltung, MFA und Audit-Log – nur Berechtigte kommen rein.</span></div></div>
<div class='feature'><div class='ic'>📊</div><div><b>Live-Dashboard</b><span>Portfolio-Verlauf, Depot-Rankings und KI-Log in Echtzeit.</span></div></div>
</div>
<div class='meta'>Systemstatus: aktiv · NYSE Mo–Fr 15:30–22:00 MEZ · Paper-/Shadow-System</div>
</div>
<div class='card'>
<img class='banner' src='/assets/banner.png' alt='Micro Trader System'>
<div class='inner'>
<div class='head'><img class='logo' src='/assets/logo.png' alt='Logo'><h2>Anmelden</h2></div>
<span class='badge'>{status}</span>
<form method='POST' action='/'>
  <input type='hidden' name='csrf_token'
         value='{sec.generate_csrf_token()}'>
<label for='login-user'>Benutzername</label>
<input id='login-user' name='username' autocomplete='username' required autofocus>
<label for='login-pass'>Passwort</label>
<input id='login-pass' name='password' type='password' autocomplete='current-password' required>
<button type='submit'>Anmelden</button>
{fehler}
</form>
<p class='hint'>Zugriff nur für berechtigte Benutzer</p>
</div></div>
</div></body></html>""")


# ─── PHASE 8: Admin-Bereich (nur ADMIN/SUPERADMIN via before_request) ──────────

# ─── PHASE 8+ : Admin-Bereich (StufenPilot-Design, v2.24.0) ──────────────────
ADMIN_CSS = """
:root{--bg1:#f8fafc;--bg2:#f1f5f9;--card-bg:rgba(255,255,255,.82);--card-border:rgba(15,23,42,.07);
--accent:#2563eb;--accent-dark:#1d4ed8;--green:#10b981;--amber:#f59e0b;--red:#ef4444;
--text:#0f172a;--text-dim:#64748b;--radius:14px;--r-lg:18px;
--shadow:0 10px 28px rgba(15,23,42,.08);--shadow-lg:0 24px 48px rgba(61,93,153,.12)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI Variable','Segoe UI',system-ui,sans-serif;background:linear-gradient(160deg,var(--bg1),var(--bg2));
background-image:radial-gradient(ellipse at 15% 0%,rgba(37,99,235,.07) 0%,transparent 55%),radial-gradient(ellipse at 85% 0%,rgba(16,185,129,.05) 0%,transparent 50%);
min-height:100vh;color:var(--text);-webkit-font-smoothing:antialiased}
.wrap{max-width:1100px;margin:0 auto;padding:24px 20px 60px}
.top{display:flex;align-items:center;gap:14px;margin-bottom:22px}
.top img{width:40px;height:40px;border-radius:10px}
.top h1{font-size:21px;font-weight:700}
.top .sub{font-size:11.5px;color:var(--text-dim)}
.top .right{margin-left:auto;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.pill{background:var(--card-bg);backdrop-filter:blur(10px);border:1px solid var(--card-border);border-radius:999px;padding:6px 14px;font-size:12px;font-weight:600;box-shadow:var(--shadow)}
a.pill{color:var(--accent);text-decoration:none}
.nav{display:flex;gap:4px;background:rgba(118,118,128,.10);padding:4px;border-radius:999px;margin-bottom:22px;overflow-x:auto;scrollbar-width:none}
.nav a{padding:7px 16px;border-radius:999px;font-size:12.5px;font-weight:600;color:var(--text-dim);text-decoration:none;white-space:nowrap;transition:all .18s}
.nav a:hover{color:var(--text)}
.nav a.active{background:#fff;color:var(--text);box-shadow:0 1px 4px rgba(0,0,0,.1)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:22px}
.stat{background:var(--card-bg);backdrop-filter:blur(14px);border:1px solid var(--card-border);border-radius:var(--radius);padding:16px;box-shadow:var(--shadow)}
.stat .num{font-size:22px;font-weight:700;margin-bottom:2px}
.stat .lbl{font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.05em}
.glass{background:var(--card-bg);backdrop-filter:blur(14px);border:1px solid var(--card-border);border-radius:var(--radius);padding:18px 20px;box-shadow:var(--shadow);margin-bottom:14px}
.glass h2{font-size:14px;font-weight:700;margin-bottom:12px;color:var(--text)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;color:var(--text-dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;padding:8px 10px;border-bottom:1px solid var(--card-border)}
td{padding:9px 10px;border-bottom:1px solid var(--card-border);vertical-align:top}
tr:last-child td{border-bottom:none}
code{background:rgba(15,23,42,.06);padding:2px 7px;border-radius:6px;font-size:11.5px}
.b{font-weight:600}
.ok{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--amber)}
.btn{display:inline-block;padding:8px 16px;border-radius:10px;border:none;cursor:pointer;font-size:12.5px;font-weight:600;font-family:inherit;transition:all .15s;text-decoration:none}
.btn.primary{background:var(--accent);color:#fff}.btn.primary:hover{background:var(--accent-dark)}
.btn.ghost{background:transparent;border:1px solid var(--card-border);color:var(--text)}
.btn.ghost:hover{background:rgba(15,23,42,.05)}
.btn.danger{background:rgba(239,68,68,.12);color:var(--red)}
.hint{font-size:11px;color:var(--text-dim);margin-top:10px}
.src{display:inline-block;font-size:9.5px;font-weight:700;border-radius:6px;padding:1px 7px;text-transform:uppercase;letter-spacing:.03em}
.src-tenant{background:rgba(37,99,235,.12);color:var(--accent)}
.src-global{background:rgba(118,118,128,.14);color:var(--text-dim)}
.src-default{background:rgba(16,185,129,.12);color:var(--green)}
"""


def _admin_layout(aktiver_tab, u, titel, inhalt):
    """Gemeinsames Admin-Layout (StufenPilot-Design)."""
    tabs = [
        ("overview", "/admin", "📊 Übersicht"),
        ("system", "/admin/system", "🩺 System"),
        ("users", "/admin/users", "👥 Benutzer"),
        ("tenant", "/admin/tenant-config", "🏢 Mandanten"),
        ("logins", "/admin/logins", "🌐 Logins"),
        ("security", "/admin/security", "🛡️ Sicherheit"),
        ("audit", "/admin/audit", "📜 Audit"),
        ("backups", "/admin/backups", "💾 Backups"),
    ]
    nav = "".join(
        f"<a href='{href}' class='{'active' if key == aktiver_tab else ''}'>{label}</a>"
        for key, href, label in tabs)
    mfa = "🛡️ MFA" if u.get("mfa_secret") else "⚠️ kein MFA"
    return f"""<!doctype html><html lang='de'><head><meta charset='utf-8'>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Admin – Micro-Trader</title><style>{ADMIN_CSS}</style></head><body>
<div class='wrap'>
<div class='top'>
<img src='/assets/logo.png' alt='Logo'>
<div><h1>🔧 Admin-Bereich</h1><div class='sub'>Micro-Trader · Server-Sicherheit · Audit-Trail aktiv</div></div>
<div class='right'>
<span class='pill'>{u['username']} · {u['role']} · {mfa}</span>
<a class='pill' href='/dashboard'>📊 Dashboard</a>
<a class='pill' href='/logout'>🚪 Logout</a>
</div>
</div>
<div class='nav'>{nav}</div>
{titel}
{inhalt}
</div></body></html>"""


@app.route("/admin")
@sec.require_role("admin")
def admin_overview():
    """Admin-Übersicht: Stat-Cards + letzte Audit-Einträge."""
    u = sec.current_user()
    users = sec.list_users()
    aktive = sum(1 for x in users if x.get("active", True))
    mfa_on = sum(1 for x in users if x.get("mfa_secret"))
    sessions = sum(len(x.get("sessions", {}) or {}) for x in users)
    audit = sec.read_audit(200)
    login_fails = sum(1 for a in audit if a.get("event") == "login_failed")
    bdir = os.path.join(BASE, ".backup")
    backups = len(glob.glob(os.path.join(bdir, "*"))) if os.path.isdir(bdir) else 0
    pause = {}
    pf = os.path.join(BASE, "pause_flag.json")
    if os.path.exists(pf):
        try:
            pause = json.load(open(pf, encoding="utf-8"))
        except Exception:
            pause = {}
    paused = pause.get("paused") or pause.get("state") == "on"
    stats = f"""
<div class='cards'>
<div class='stat'><div class='num'>{len(users)}</div><div class='lbl'>Benutzer</div></div>
<div class='stat'><div class='num'>{aktive}</div><div class='lbl'>Aktiv</div></div>
<div class='stat'><div class='num'>{mfa_on}</div><div class='lbl'>MFA aktiv</div></div>
<div class='stat'><div class='num'>{sessions}</div><div class='lbl'>Sessions</div></div>
<div class='stat'><div class='num'>{len(audit)}</div><div class='lbl'>Audit</div></div>
<div class='stat'><div class='num bad'>{login_fails}</div><div class='lbl'>Login-Fails</div></div>
<div class='stat'><div class='num'>{backups}</div><div class='lbl'>Backups</div></div>
<div class='stat'><div class='num {'bad' if paused else 'ok'}'>{'⏸' if paused else '▶'}</div><div class='lbl'>Trading {'pausiert' if paused else 'aktiv'}</div></div>
</div>"""
    letzte = "".join(
        f"<tr><td class='b'>{a.get('event','')}</td><td>{a.get('actor','')}</td>"
        f"<td style='color:var(--text-dim)'>{a.get('detail','')}</td>"
        f"<td style='color:var(--text-dim);white-space:nowrap'>{str(a.get('ts',''))[:19]}</td></tr>"
        for a in audit[:8])
    # Warnungen: Drawdown + fehlgeschlagene Läufe
    warnungen = []
    for name in sec.list_users():
        pass
    # Drawdown-Warnungen aus Depot-Dateien
    dd_warn = []
    try:
        for f in sorted(glob.glob(os.path.join(BASE, "depot_*.json"))):
            try:
                depot = json.load(open(f, encoding="utf-8"))
                if depot.get("max_dd") and depot["max_dd"] < -30:
                    dd_warn.append(f"Risk {depot.get('risk','?')}: MaxDD {depot['max_dd']:.1f}%")
            except Exception:
                pass
    except Exception:
        pass
    if dd_warn:
        warnungen.append(("🔴 Drawdown", " · ".join(dd_warn[:4]) + (" …" if len(dd_warn) > 4 else "")))
    # Letzte System-Ereignisse (system_log)
    letzte_laeufe = []
    try:
        slog = json.load(open(os.path.join(BASE, "system_log.json"), encoding="utf-8"))
        letzte_laeufe = slog[-5:][::-1] if isinstance(slog, list) else []
    except Exception:
        letzte_laeufe = []
    lauf_rows = "".join(
        f"<tr><td class='b'>{e.get('quelle','?')}</td><td style='color:var(--text-dim)'>{str(e.get('text',''))[:70]}</td>"
        f"<td style='color:var(--text-dim);white-space:nowrap'>{str(e.get('zeit',''))[:16].replace('T',' ')}</td></tr>"
        for e in letzte_laeufe)
    warn_html = ""
    if warnungen:
        warn_html = "<div class='glass'><h2>⚠️ Warnungen</h2>" + "".join(
            f"<div style='display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--card-border)'>"
            f"<b style='font-size:12.5px'>{t}</b><span style='font-size:12px;color:var(--text-dim)'>{d}</span></div>"
            for t, d in warnungen) + "</div>"
    inhalt = f"""{stats}
{warn_html}
<div class='glass'><h2>🕘 Letzte Audit-Einträge</h2>
<table><tr><th>Ereignis</th><th>Wer</th><th>Detail</th><th>Zeit</th></tr>{letzte or '<tr><td colspan=4 style="color:var(--text-dim)">Keine Einträge</td></tr>'}</table>
<div class='hint'><a href='/admin/audit' style='color:var(--accent)'>Alle Einträge →</a></div></div>
<div class='glass'><h2>⏱ Letzte System-Ereignisse</h2>
<table><tr><th>Quelle</th><th>Ereignis</th><th>Zeit</th></tr>{lauf_rows or '<tr><td colspan=3 style="color:var(--text-dim)">Keine Einträge</td></tr>'}</table>
<div class='hint'><a href='/admin/system' style='color:var(--accent)'>System-Details →</a></div></div>
<div class='glass'><h2>🩺 Schnellzugriff</h2>
<a class='btn primary' href='/admin/users'>👥 Benutzerverwaltung</a>&nbsp;
<a class='btn ghost' href='/admin/system'>🩺 Systemstatus</a>&nbsp;
<a class='btn ghost' href='/admin/backups'>💾 Backups</a>&nbsp;
<a class='btn ghost' href='/dashboard'>📊 Zum Dashboard</a></div>"""
    return _admin_layout("overview", u,
        f"<h2 style='font-size:17px;margin-bottom:4px'>Übersicht</h2>"
        f"<div style='font-size:12px;color:var(--text-dim);margin-bottom:16px'>Angemeldet als <b>{u['username']}</b> · Rolle <b>{u['role']}</b></div>",
        inhalt)


@app.route("/admin/system")
@sec.require_role("admin")
def admin_system():
    """Systemstatus (Phase 8 Bereich 1) – erweitert."""
    u = sec.current_user()
    pause = {}
    pf = os.path.join(BASE, "pause_flag.json")
    if os.path.exists(pf):
        try:
            pause = json.load(open(pf, encoding="utf-8"))
        except Exception:
            pause = {}
    paused = pause.get("paused") or pause.get("state") == "on"
    grund = pause.get("grund", "manuell")
    # Dashboard-Prozess-Check
    port_offen = False
    try:
        import socket
        s = socket.socket(); s.settimeout(1)
        port_offen = s.connect_ex(("127.0.0.1", PORT)) == 0
        s.close()
    except Exception:
        port_offen = False
    status_rows = [
        ("Dashboard (Port %d)" % PORT, port_offen),
        ("Paper-/Shadow-Modus", True),
        ("Echtgeld-Funktionen", False),
        ("Trading-Pause", paused),
    ]
    rows = "".join(
        f"<tr><td class='b'>{name}</td><td class='{'ok' if val else 'bad'}'>{'✅ aktiv' if val else '❌ inaktiv'}</td></tr>"
        for name, val in status_rows)
    # Datei-Größen (Datenbestand)
    dateien = [
        ("system_log.json", "system_log.json"),
        ("cron_pipeline.log", "cron_pipeline.log"),
        ("ki_log.json", "ki_log.json"),
        ("batch_summary.json", "batch_summary.json"),
        ("security_audit.json", "security_audit.json"),
    ]
    file_rows = ""
    for name, fname in dateien:
        fp = os.path.join(BASE, fname)
        if os.path.exists(fp):
            size = os.path.getsize(fp)
            file_rows += f"<tr><td class='b'>{name}</td><td>{size//1024} KB</td>"
            file_rows += f"<td style='color:var(--text-dim)'>{time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(fp)))}</td></tr>"
    depot_count = len(glob.glob(os.path.join(BASE, "depot_*.json")))
    file_rows += f"<tr><td class='b'>Depot-Dateien</td><td>{depot_count} Dateien</td><td style='color:var(--text-dim)'>–</td></tr>"
    inhalt = f"""
<div class='cards'>
<div class='stat'><div class='num {'ok' if port_offen else 'bad'}'>{'🟢' if port_offen else '🔴'}</div><div class='lbl'>Dashboard</div></div>
<div class='stat'><div class='num ok'>✅</div><div class='lbl'>Shadow-Modus</div></div>
<div class='stat'><div class='num {'bad' if paused else 'ok'}'>{'⏸' if paused else '▶'}</div><div class='lbl'>Trading</div></div>
<div class='stat'><div class='num'>{'Mo–Fr 15–22 MEZ'}</div><div class='lbl'>Cron-Zeitfenster</div></div>
</div>
<div class='glass'><h2>🩺 Systemstatus</h2><table><tr><th>Komponente</th><th>Status</th></tr>{rows}</table></div>
<div class='glass'><h2>📁 Datenbestand</h2><table><tr><th>Datei</th><th>Größe</th><th>Zuletzt geändert</th></tr>{file_rows}</table></div>
<div class='glass'><h2>⏸ Trading-Pause</h2>
<p style='font-size:13px;margin-bottom:12px'>Status: <b class='{'bad' if paused else 'ok'}'>{'PAUSIERT (' + grund + ')' if paused else 'aktiv'}</b></p>
<a class='btn primary' href='/api/pause_trading?state={'off' if paused else 'on'}&grund=admin_ui'>▶ {'Trading wieder aktivieren' if paused else 'Trading pausieren'}</a>
<div class='hint'>Pause-Flag: <code>pause_flag.json</code> · Wird vom Cron-Pipeline respektiert.</div></div>"""
    return _admin_layout("system", u,
        f"<h2 style='font-size:17px;margin-bottom:4px'>Systemstatus</h2>"
        f"<div style='font-size:12px;color:var(--text-dim);margin-bottom:16px'>Server-Sicherheit Phasen 2–9 · Netzwerk-Grenze: 127.0.0.1</div>",
        inhalt)


@app.route("/admin/users")
@sec.require_role("admin")
@sec.require_recent_mfa()
def admin_users():
    """Benutzerverwaltung (StufenPilot-Design). MFA-Pflicht (§6)."""
    u = sec.current_user()
    rows = ""
    for usr in sec.list_users():
        name = usr.get("username", "?")
        role = usr.get("role", "user")
        aktiv = usr.get("active", True)
        mfa = bool(usr.get("mfa_secret"))
        sess = len(usr.get("sessions", {}) or {})
        last = str(usr.get("last_login", "") or "")[:19] or "–"
        rows += f"""<tr>
<td class='b'>{name}{' <span class="warn">(du)</span>' if name == u['username'] else ''}</td>
<td><code>{role}</code></td>
<td class='{'ok' if aktiv else 'bad'}'>{'✅ aktiv' if aktiv else '⛔ inaktiv'}</td>
<td>{'🛡️' if mfa else '–'}</td>
<td>{sess}</td>
<td style='color:var(--text-dim)'>{last}</td>
</tr>"""
    inhalt = f"""<div class='glass'><h2>👥 Benutzerverwaltung</h2>
<div style='margin-bottom:10px;font-size:12.5px;color:var(--text-dim)'>Benutzer anlegen, Rollen und Status ändern → im Dashboard unter <b>Einstellungen → Benutzer</b> (voll interaktiv).</div>
<table><tr><th>Benutzer</th><th>Rolle</th><th>Status</th><th>MFA</th><th>Sessions</th><th>Letzter Login</th></tr>{rows or '<tr><td colspan=6 style="color:var(--text-dim)">Keine Benutzer</td></tr>'}</table>
<div class='hint'>Passwörter/MFA-Secrets werden niemals angezeigt. Admin-Aktionen → <a href='/admin/audit' style='color:var(--accent)'>Audit</a>.</div></div>"""
    return _admin_layout("users", u,
        f"<h2 style='font-size:17px;margin-bottom:4px'>Benutzer</h2>"
        f"<div style='font-size:12px;color:var(--text-dim);margin-bottom:16px'>{len(sec.list_users())} Benutzer · volle Verwaltung im Dashboard</div>",
        inhalt)


@app.route("/admin/security")
@sec.require_role("admin")
@sec.require_recent_mfa()
def admin_security():
    """Security-Status: Passwort-Hashing, Headers, Netzwerk, Login-Schutz (OWASP-Checkliste). MFA-Pflicht (§6)."""
    u = sec.current_user()
    checks = []
    # 1. Passwort-Hashing
    users = sec.list_users()
    hashes = [x.get("password_hash", "") for x in users]
    algos = set()
    for h in hashes:
        if not h:
            algos.add("LEER")
        else:
            algos.add(h.split("$")[0])
    if "LEER" in algos or not hashes:
        checks.append(("❌", "Passwort-Hashing", "Ein Benutzer hat KEINEN Passwort-Hash!", False))
    elif all(a.startswith(("pbkdf2", "scrypt")) for a in algos):
        a_str = ", ".join(sorted(algos))
        checks.append(("✅", "Passwort-Hashing", f"Stark: {a_str} mit Salt – OWASP-konform (bcrypt/argon2/PBKDF2 empfohlen, hier: {a_str})", True))
    else:
        checks.append(("⚠️", "Passwort-Hashing", f"Schwacher/alter Algorithmus: {algos}", False))
    # 2. Security-Headers (aus before_request)
    headers = {
        "Content-Security-Policy": "CSP gesetzt (script-src 'self', frame-ancestors 'none')",
        "X-Content-Type-Options": "nosniff – verhindert MIME-Sniffing",
        "X-Frame-Options": "DENY – kein Clickjacking",
        "Referrer-Policy": "no-referrer – keine URL-Leaks",
        "Permissions-Policy": "Geo/Mic/Cam gesperrt",
    }
    hdr_str = ""
    try:
        test_r = app.test_client().get("/")
        for h, desc in headers.items():
            present = h in test_r.headers
            checks.append(("✅" if present else "❌", f"Header {h}", desc + (" – gesetzt" if present else " – FEHLT"), present))
    except Exception as e:
        checks.append(("⚠️", "Header-Check", str(e), False))
    # 3. Netzwerk-Exposition (echter Listener des dashboard-Prozesses)
    lokal = True
    try:
        import subprocess
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, errors="replace").stdout
        # Finde alle Ports, auf denen ein python-Prozess lauscht (dashboard.py)
        listen_lines = [l for l in out.splitlines() if "LISTENING" in l and ("5300" in l or "5200" in l)]
        bind_all = any(("0.0.0.0" in l or "[::]" in l) for l in listen_lines)
        bind_local = any(("127.0.0.1" in l or "127.0.0.1" in l) for l in listen_lines)
        # Nur wenn wir einen python/dashboard Listener finden, bewerten
        if listen_lines:
            lokal = bind_local and not bind_all
    except Exception:
        lokal = True
    checks.append(("✅" if lokal else "❌", "Netzwerk-Exposition",
                   f"Dashboard lauscht auf Port {PORT} " + ("NUR auf 127.0.0.1 (localhost) – von außen nicht erreichbar" if lokal else "AUF ALLEN INTERFACES – von außen erreichbar!"), lokal))
    # 4. Login-Schutz (Rate-Limit)
    rate = sec.login_rate_stats()
    aktive_blocks = sum(1 for r in rate if r["blocked"])
    checks.append(("✅", "Brute-Force-Schutz", f"Rate-Limit aktiv: 5 Fehlversuche → exponentieller Block (30s+). Aktuell {len(rate)} Einträge, {aktive_blocks} blockiert.", True))
    # 5. MFA-Abdeckung
    mfa_on = sum(1 for x in users if x.get("mfa_secret"))
    mfa_pct = int(100 * mfa_on / len(users)) if users else 0
    checks.append(("✅" if mfa_pct >= 50 else "⚠️", "MFA-Abdeckung",
                   f"{mfa_on}/{len(users)} Benutzer haben MFA ({mfa_pct}%)" + (" – empfohlen: alle Admins", " – unter 50%: MFA für Admins empfohlen")[mfa_pct < 50], mfa_pct >= 50))
    # 6. Session-Cookies
    checks.append(("✅", "Session-Cookies", "HttpOnly + SameSite=Lax gesetzt (secure erst bei HTTPS/Funnel)", True))
    # 7. HSTS (nur bei HTTPS sinnvoll)
    checks.append(("ℹ️", "HSTS", "Nur relevant bei HTTPS (Tailscale Funnel). Lokal auf http://127.0.0.1 kein HSTS nötig.", True))
    rows = "".join(
        f"<tr><td style='font-size:15px'>{ic}</td><td class='b'>{name}</td>"
        f"<td style='color:var(--text-dim)'>{desc}</td></tr>"
        for ic, name, desc, _ok in checks)
    gut = sum(1 for c in checks if c[0] == "✅")
    gesamt = len(checks)
    inhalt = f"""
<div class='cards'>
<div class='stat'><div class='num ok'>{gut}/{gesamt}</div><div class='lbl'>Checks bestanden</div></div>
<div class='stat'><div class='num {'ok' if all(c[3] for c in checks if c[0]!='ℹ️') else 'warn'}'>{'🟢' if all(c[3] for c in checks if c[0]!='ℹ️') else '🟡'}</div><div class='lbl'>Gesamtstatus</div></div>
<div class='stat'><div class='num'>{len(users)}</div><div class='lbl'>Benutzer</div></div>
<div class='stat'><div class='num'>{mfa_on}</div><div class='lbl'>MFA aktiv</div></div>
</div>
<div class='glass'><h2>🛡️ Security-Checkliste (OWASP-orientiert)</h2>
<table><tr><th>Status</th><th>Bereich</th><th>Befund</th></tr>{rows}</table>
<div class='hint'>Automatischer Check · Stichprobe der Live-Headers · Quelle: OWASP Top 10 2021/2025 (A02 Crypto, A05 Misconfig, A07 Auth).</div></div>
<div class='glass'><h2>🌐 Login-Aktivität (Rate-Limit)</h2>
<table><tr><th>Schlüssel (IP/User)</th><th>Fehlversuche</th><th>Blockiert?</th><th>Restzeit</th></tr>
{''.join(f"<tr><td class='b'>{r['key']}</td><td>{r['fails']}</td><td class='{'bad' if r['blocked'] else 'ok'}'>{'⛔ ja' if r['blocked'] else '–'}</td><td>{r['rest_s']}s</td></tr>" for r in rate[:12]) or '<tr><td colspan=4 style="color:var(--text-dim)">Keine auffälligen Login-Versuche</td></tr>'}
</table>
<div class='hint'>Fehlversuche werden pro IP UND pro Benutzername gezählt (15-Min-Fenster).</div></div>"""
    return _admin_layout("security", u,
        f"<h2 style='font-size:17px;margin-bottom:4px'>Sicherheit</h2>"
        f"<div style='font-size:12px;color:var(--text-dim);margin-bottom:16px'>Automatischer Sicherheits-Check · OWASP-orientiert</div>",
        inhalt)


@app.route("/admin/logins")
@sec.require_role("admin")
def admin_logins():
    """Login-Analytik: welche IPs, woher, wie oft, Brute-Force-Erkennung."""
    u = sec.current_user()
    entries = sec.read_audit(2000)
    logins = [a for a in entries if a.get("action") in ("login", "login_failed", "login_blocked", "logout")]
    # IP-Aggregation
    from collections import Counter, defaultdict
    ip_info = defaultdict(lambda: {"ok": 0, "fail": 0, "users": set(), "ua": set(), "last": ""})
    for a in logins:
        detail = a.get("detail", "")
        ip = ""
        m = re.search(r"ip=([^\s]+)", detail)
        if m:
            ip = m.group(1)
        act = a.get("action", "")
        ip_info[ip]["last"] = str(a.get("ts", ""))[:19]
        if ip:
            ip_info[ip]["ok" if act == "login" else "fail"] += 1
            ip_info[ip]["users"].add(a.get("actor", "?"))
            um = re.search(r"ua=([^\s]*)", detail)
            if um and um.group(1):
                ip_info[ip]["ua"].add(um.group(1)[:30])
    # Nur IPs mit Aktivität zeigen, sortiert nach Gesamt
    rows = ""
    for ip, info in sorted(ip_info.items(), key=lambda kv: -(kv[1]["ok"] + kv[1]["fail"])):
        if not ip:
            continue
        gesamt = info["ok"] + info["fail"]
        verdaechtig = info["fail"] >= 5
        lokal = ip.startswith(("127.", "192.168.", "10.", "172.16.", "::1"))
        ort = "🏠 lokal" if lokal else "🌍 extern"
        rows += f"""<tr>
<td class='b'>{ip}</td><td>{ort}</td><td>{gesamt}</td>
<td class='ok'>{info['ok']}</td><td class='{'bad' if info['fail'] else ''}'>{info['fail']}</td>
<td>{', '.join(sorted(info['users']))}</td>
<td style='color:var(--text-dim)'>{', '.join(list(info['ua'])[:1])[:40]}</td>
<td>{'⛔ BRUTE-FORCE-VERDACHT' if verdaechtig else '–'}</td>
<td style='color:var(--text-dim)'>{info['last']}</td></tr>"""
    inhalt = f"""
<div class='glass'><h2>🌐 Login-Aktivität nach IP</h2>
<div style='overflow-x:auto'><table>
<tr><th>IP</th><th>Ort</th><th>Gesamt</th><th>Erfolgreich</th><th>Fehlversuche</th><th>Benutzer</th><th>User-Agent</th><th>Verdacht</th><th>Zuletzt</th></tr>
{rows or '<tr><td colspan=9 style="color:var(--text-dim)">Noch keine IP-Daten (Logins seit v2.24.0 werden mit IP erfasst)</td></tr>'}
</table></div>
<div class='hint'>⚠️ 5+ Fehlversuche = Brute-Force-Verdacht · IPs werden seit v2.24.0 bei jedem Login/Fehlversuch mitgeloggt.</div></div>"""
    return _admin_layout("logins", u,
        f"<h2 style='font-size:17px;margin-bottom:4px'>Logins</h2>"
        f"<div style='font-size:12px;color:var(--text-dim);margin-bottom:16px'>Welche Geräte/IPs greifen zu · Brute-Force-Erkennung</div>",
        inhalt)


@app.route("/admin/audit")
@sec.require_role("admin")
def admin_audit():
    u = sec.current_user()
    q = request.args.get("q", "").strip().lower()
    entries = sec.read_audit(300)
    if q:
        entries = [a for a in entries if q in str(a.get("event", "")).lower()
                   or q in str(a.get("actor", "")).lower()
                   or q in str(a.get("detail", "")).lower()]
    rows = "".join(
        f"<tr><td class='b'>{a.get('event','')}</td><td>{a.get('actor','')}</td>"
        f"<td style='color:var(--text-dim)'>{a.get('detail','')}</td>"
        f"<td style='color:var(--text-dim);white-space:nowrap'>{str(a.get('ts',''))[:19]}</td></tr>"
        for a in entries)
    inhalt = f"""<div class='glass'><h2>📜 Audit-Log ({len(entries)} Einträge)</h2>
<form method='get' action='/admin/audit' style='margin-bottom:4px'>
<input class='search' name='q' placeholder='🔍 Suchen (Ereignis, Benutzer, Detail)…' value='{request.args.get("q","")}'>
</form>
<div style='overflow-x:auto'><table><tr><th>Ereignis</th><th>Wer</th><th>Detail</th><th>Zeit</th></tr>{rows or '<tr><td colspan=4 style="color:var(--text-dim)">Keine Einträge gefunden</td></tr>'}</table></div>
<div class='hint'>Append-only · nicht nachträglich änderbar. Letzte {len(entries)} Einträge (gefiltert: {'ja' if q else 'nein'}).</div></div>"""
    return _admin_layout("audit", u,
        f"<h2 style='font-size:17px;margin-bottom:4px'>Audit</h2>"
        f"<div style='font-size:12px;color:var(--text-dim);margin-bottom:16px'>Sicherheitsrelevante Aktionen, append-only</div>",
        inhalt)


@app.route("/admin/backups")
@sec.require_role("admin")
def admin_backups():
    """Backups (StufenPilot-Design) mit Details."""
    u = sec.current_user()
    bdir = os.path.join(BASE, ".backup")
    items = sorted(glob.glob(os.path.join(bdir, "*")), reverse=True)[:15] if os.path.isdir(bdir) else []
    rows = "".join(
        f"<tr><td class='b'>{os.path.basename(i)}</td><td>{os.path.getsize(i)//1024} KB</td>"
        f"<td style='color:var(--text-dim)'>{time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(i)))}</td></tr>"
        for i in items)
    inhalt = f"""<div class='glass'><h2>💾 Backups (zuletzt {len(items)})</h2>
<table><tr><th>Name</th><th>Größe</th><th>Erstellt</th></tr>{rows or '<tr><td colspan=3 style="color:var(--text-dim)">Keine Backups</td></tr>'}</table>
<div class='hint'>Backup-Ordner: <code>.backup/</code> · wird via <code>backup.py</code> erzeugt (Regel Nr. 1).</div></div>"""
    return _admin_layout("backups", u,
        f"<h2 style='font-size:17px;margin-bottom:4px'>Backups</h2>"
        f"<div style='font-size:12px;color:var(--text-dim);margin-bottom:16px'>Snapshot-Sicherungen vor Änderungen</div>",
        inhalt)


# ─── PHASE 13: Mandanten-Config (v2.36.0) — Risikogrenzen + Regeln im Admin ───
@app.route("/admin/tenant-config")
@sec.require_role("admin")
def admin_tenant_config():
    """PHASE 13: Tenant-Scoped Risikogrenzen + Regeln verwalten (Admin)."""
    u = sec.current_user()
    tid = _get_tid()
    # Risiko (beide Modi)
    rm = sec.risk_get(tid, "moderate")
    ra = sec.risk_get(tid, "aggressive")
    risk_html = _tenant_risk_block("moderate", rm) + _tenant_risk_block("aggressive", ra)
    # Regeln (effektiv: Tenant ∪ global)
    rules = sec.rule_list(tid)
    rules_rows = "".join(
        f"<tr><td class='b'>{r.get('id','')}</td>"
        f"<td><span class='src src-{r.get('source','global')}'>{r.get('source','global')}</span></td>"
        f"<td>{r.get('status','aktiv')}</td>"
        f"<td style='color:var(--text-dim)'>{str(r.get('muster',''))[:30]}</td>"
        f"<td style='color:var(--text-dim)'>{str(r.get('regel',''))[:60]}</td>"
        f"<td>{_tenant_rule_actions(tid, r)}</td></tr>"
        for r in rules)
    no_rules = "<tr><td colspan=6 style=\"color:var(--text-dim)\">Keine Regeln</td></tr>"
    inhalt = f"""
<div class='glass'><h2>🎚️ Risikogrenzen (effektiv, Tenant → global)</h2>
{risk_html}
<form method='post' action='/admin/tenant-config/risk' style='margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:end'>
  <label style='font-size:11px'>Modus<select name='mode' style='margin-left:4px'>
    <option value='moderate'>moderate</option><option value='aggressive'>aggressive</option></select></label>
  <label style='font-size:11px'>Pos-Size<input name='position_size' type='number' step='0.01' min='0' max='1' style='width:70px;margin-left:4px'></label>
  <label style='font-size:11px'>Stop-Loss<input name='stop_loss' type='number' step='0.01' min='0' max='1' style='width:70px;margin-left:4px'></label>
  <label style='font-size:11px'>Take-Profit<input name='take_profit' type='number' step='0.01' min='0' max='3' style='width:70px;margin-left:4px'></label>
  <label style='font-size:11px'>Drawdown<input name='drawdown_limit' type='number' step='0.01' min='0' max='1' style='width:70px;margin-left:4px'></label>
  <button class='btn primary' type='submit'>💾 Speichern</button>
</form></div>

<div class='glass'><h2>📜 Regeln (effektiv: Tenant ∪ global)</h2>
<table><tr><th>ID</th><th>Quelle</th><th>Status</th><th>Muster</th><th>Regel</th><th>Aktion</th></tr>
{rules_rows or no_rules}</table>
<form method='post' action='/admin/tenant-config/rule' style='margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:end'>
  <label style='font-size:11px'>Regel-ID<input name='rule_id' style='width:120px;margin-left:4px'></label>
  <label style='font-size:11px'>Muster<input name='muster' placeholder='BLOCK: / MAX_KAUF:n / REGEX:' style='width:160px;margin-left:4px'></label>
  <label style='font-size:11px'>Regel-Text<input name='regel' style='width:220px;margin-left:4px'></label>
  <button class='btn primary' type='submit'>➕ Regel hinzufügen</button>
</form>
<div class='hint'>Muster-Typen: <code>BLOCK:Text</code> (hart blockiert), <code>MAX_KAUF:n</code> (max n Käufe), <code>REGEX:pattern</code> (Ticker-Filter). Nur Status <b>aktiv</b> wird angewendet.</div>
</div>
{_render_approvals(tid)}
"""
    return _admin_layout("tenant", u,
        f"<h2 style='font-size:17px;margin-bottom:4px'>🏢 Mandanten-Config</h2>"
        f"<div style='font-size:12px;color:var(--text-dim);margin-bottom:16px'>Tenant-ID {tid} · Risikogrenzen &amp; Regeln &amp; Freigaben (PHASE 13/14)</div>",
        inhalt)


def _tenant_risk_block(mode, eff):
    p = eff.get("position_size", 0.35); sl = eff.get("stop_loss", 0.92)
    tp = eff.get("take_profit", 1.12); dd = eff.get("drawdown_limit", 0.20)
    src = eff.get("source", "default")
    return f"""<div style='padding:8px 0;border-bottom:1px solid var(--card-border)'>
  <b>{mode}</b> <span class='src src-{src}'>{src}</span>
  <span style='font-size:11px;color:var(--text-dim)'>Pos {p:.0%} · SL {sl:.0%} · TP {tp:.0%} · DD {dd:.0%}</span></div>"""


def _tenant_rule_actions(tid, r):
    rid = r.get("id", "")
    if r.get("source") != "tenant":
        return "<span style='color:var(--text-dim);font-size:11px'>global (read-only)</span>"
    # Toggle Status
    nxt = "pausiert" if r.get("status") == "aktiv" else "aktiv"
    return (f"<a class='btn ghost' href='/admin/tenant-config/rule/{rid}/set?status={nxt}'>"
            f"{'⏸ pausieren' if r.get('status') == 'aktiv' else '▶ aktivieren'}</a>")


@app.route("/admin/tenant-config/risk", methods=["POST"])
@sec.require_role("admin")
def admin_tenant_risk_save():
    tid = _get_tid()
    mode = request.form.get("mode", "moderate")
    sec.risk_set(tid, mode,
                 position_size=request.form.get("position_size") or None,
                 stop_loss=request.form.get("stop_loss") or None,
                 take_profit=request.form.get("take_profit") or None,
                 drawdown_limit=request.form.get("drawdown_limit") or None)
    return redirect("/admin/tenant-config")


@app.route("/admin/tenant-config/rule", methods=["POST"])
@sec.require_role("admin")
def admin_tenant_rule_add():
    tid = _get_tid()
    rid = request.form.get("rule_id", "").strip()
    if rid:
        sec.rule_add(tid, rid, request.form.get("regel", ""),
                     muster=request.form.get("muster") or None,
                     created_by=u_name())
    return redirect("/admin/tenant-config")


@app.route("/admin/tenant-config/rule/<rule_id>/set")
@sec.require_role("admin")
def admin_tenant_rule_set(rule_id):
    tid = _get_tid()
    status = request.args.get("status", "aktiv")
    sec.rule_set_status(tid, rule_id, status)
    return redirect("/admin/tenant-config")


def u_name():
    u = sec.current_user()
    return u["username"] if u else "unbekannt"

# ─── PHASE 14: Freigabe-Workflow APIs + Admin-UI (§23/§21.5) ───
@app.route("/api/approval", methods=["GET"])
def api_approval_get():
    import security as _sec
    u = _sec.current_user()
    if not u or _sec.effective_role(u) not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung"}, 403
    tid = _get_tid()
    ttype = request.args.get("target_type", "strategy")
    tid_id = request.args.get("target_id", "")
    return {"tenant_id": tid, "target_type": ttype, "target_id": tid_id,
            "approval": _sec.approval_get(tid, ttype, tid_id)}


@app.route("/api/approval/set", methods=["POST"])
def api_approval_set():
    import security as _sec
    u = _sec.current_user()
    if not u or _sec.effective_role(u) not in ("tenant_admin", "admin", "superadmin"):
        return {"error": "keine Berechtigung"}, 403
    tid = _get_tid()
    ttype = (request.form.get("target_type") or (request.json.get("target_type") if request.is_json else "")) or "strategy"
    tid_id = (request.form.get("target_id") or (request.json.get("target_id") if request.is_json else "")) or ""
    status = (request.form.get("status") or (request.json.get("status") if request.is_json else "")) or "nicht_freigegeben"
    note = (request.form.get("note") or (request.json.get("note") if request.is_json else "")) or None
    _sec.approval_set(tid, ttype, tid_id, status, approved_by=u.get("id"), note=note)
    return {"ok": True, "tenant_id": tid, "target_type": ttype, "target_id": tid_id, "status": status}


def _render_approvals(tid):
    """PHASE 14: HTML-Block fuer Freigaben (in /admin/tenant-config eingebunden)."""
    rows = sec.approval_list(tid)
    state_labels = {"nicht_freigegeben": "⚪ nicht freigegeben",
                    "in_pruefung": "🟡 in Prüfung", "freigegeben": "🟢 freigegeben",
                    "gesperrt": "🔴 gesperrt"}
    body = "".join(
        f"<tr><td class='b'>{r.get('target_type','')}</td><td>{r.get('target_id','')}</td>"
        f"<td><span class='src src-{'tenant' if r.get('status')=='freigegeben' else 'global'}'>"
        f"{state_labels.get(r.get('status',''), r.get('status',''))}</span></td>"
        f"<td style='color:var(--text-dim);font-size:11px'>{str(r.get('note',''))[:40]}</td>"
        f"<td>{_approval_actions(tid, r)}</td></tr>"
        for r in rows) or "<tr><td colspan=5 style='color:var(--text-dim)'>Keine Freigaben erfasst</td></tr>"
    return f"""
<div class='glass'><h2>✅ Freigaben (Status-Workflow, §23)</h2>
<table><tr><th>Typ</th><th>ID</th><th>Status</th><th>Notiz</th><th>Aktion</th></tr>{body}</table>
<form method='post' action='/admin/tenant-config/approval' style='margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:end'>
  <label style='font-size:11px'>Typ<select name='target_type' style='margin-left:4px'>
    <option value='strategy'>strategy</option><option value='portfolio'>portfolio</option>
    <option value='depot'>depot</option><option value='profile'>profile</option></select></label>
  <label style='font-size:11px'>ID<input name='target_id' style='width:120px;margin-left:4px'></label>
  <label style='font-size:11px'>Status<select name='status' style='margin-left:4px'>
    <option value='nicht_freigegeben'>nicht freigegeben</option>
    <option value='in_pruefung'>in Prüfung</option>
    <option value='freigegeben'>freigegeben</option>
    <option value='gesperrt'>gesperrt</option></select></label>
  <label style='font-size:11px'>Notiz<input name='note' style='width:160px;margin-left:4px'></label>
  <button class='btn primary' type='submit'>💾 Setzen</button>
</form>
<div class='hint'>Zustände: ⚪ nicht freigegeben · 🟡 in Prüfung · 🟢 freigegeben · 🔴 gesperrt. Nur <b>freigegeben</b> erlaubt Trading (Enforcement, PHASE 14).</div>
</div>"""


def _approval_actions(tid, r):
    rid = r.get("id")
    cur = r.get("status")
    nxt = {"nicht_freigegeben": "in_pruefung", "in_pruefung": "freigegeben",
           "freigegeben": "gesperrt", "gesperrt": "nicht_freigegeben"}.get(cur, "freigegeben")
    return (f"<a class='btn ghost' href='/admin/tenant-config/approval/{rid}/set?status={nxt}'>"
            f"{'▶ Prüfen' if cur=='nicht_freigegeben' else '✅ Freigeben' if cur=='in_pruefung' else '🔒 Sperren' if cur=='freigegeben' else '↺ Zurücksetzen'}</a>")


@app.route("/admin/tenant-config/approval", methods=["POST"])
@sec.require_role("admin")
def admin_tenant_approval_set():
    tid = _get_tid()
    sec.approval_set(tid, request.form.get("target_type", "strategy"),
                     request.form.get("target_id", ""), request.form.get("status", "nicht_freigegeben"),
                     approved_by=None, note=request.form.get("note") or None)
    return redirect("/admin/tenant-config")


@app.route("/admin/tenant-config/approval/<int:appr_id>/set")
@sec.require_role("admin")
def admin_tenant_approval_toggle(appr_id):
    tid = _get_tid()
    status = request.args.get("status", "freigegeben")
    import db as _db
    m = _db.MTDB()
    row = m.conn.execute("SELECT target_type, target_id FROM tenant_approvals WHERE id=? AND tenant_id=?",
                         (appr_id, tid)).fetchone()
    if row:
        sec.approval_set(tid, row["target_type"], row["target_id"], status, approved_by=None)
    m.close()
    return redirect("/admin/tenant-config")


# ─── PHASE 15: Benutzerverwaltung-API (v2.23.0) ─────────────────────────────
def _admin_actor():
    """Gibt den aktuellen Admin-Namen fuer Audit zurueck."""
    u = sec.current_user()
    return u["username"] if u else "unbekannt"


@app.route("/api/users", methods=["GET"])
@sec.require_role("admin")
@sec.require_recent_mfa()
def api_users_list():
    """Liste aller Benutzer (Admin). MFA-Pflicht (§6)."""
    rows = []
    for u in sec.list_users():  # list_users() liefert redactierte User-Views (§6)
        rows.append({
            "username": u.get("username", "?"),
            "role": u.get("role", "user"),
            "active": u.get("active", True),
            "status": u.get("status", "ACTIVE"),
            "mfa": bool(u.get("mfa_enabled")),
            "last_login": u.get("last_login_at", ""),
            "sessions": u.get("sessions_active", 0),
        })
    return jsonify({"ok": True, "users": rows})


@app.route("/api/users/create", methods=["POST"])
@sec.require_role("admin")
@sec.require_recent_mfa()
def api_users_create():
    """Neuen Benutzer anlegen (Admin). MFA-Pflicht (§6)."""
    data = request.get_json(force=True, silent=True) or {}
    name = str(data.get("username", "")).strip()
    pw = str(data.get("password", "") or "")
    role = str(data.get("role", "user")).strip() or "user"
    email = str(data.get("email", "")).strip()
    display = str(data.get("display_name", "")).strip()
    if not name or not pw:
        return jsonify({"ok": False, "error": "Benutzername und Passwort erforderlich"}), 400
    if len(pw) < 8:
        return jsonify({"ok": False, "error": "Passwort muss mind. 8 Zeichen haben"}), 400
    if sec.user_exists(name):
        return jsonify({"ok": False, "error": f"Benutzer '{name}' existiert bereits"}), 409
    sec.create_user(name, pw, role, email=email, display_name=display,
                    created_by=_admin_actor())
    return jsonify({"ok": True})


@app.route("/api/users/<name>/role", methods=["POST"])
@sec.require_role("admin")
@sec.require_recent_mfa()
def api_users_role(name):
    """Rolle eines Benutzers setzen (Admin). MFA-Pflicht (§6)."""
    data = request.get_json(force=True, silent=True) or {}
    role = str(data.get("role", "")).strip()
    if not sec.user_exists(name):
        return jsonify({"ok": False, "error": "Benutzer nicht gefunden"}), 404
    if role not in sec.ROLES:
        return jsonify({"ok": False, "error": f"Unbekannte Rolle: {role}"}), 400
    ok_role = sec.set_role(name, role, _admin_actor())
    if not ok_role:
        return jsonify({"ok": False,
                        "error": "Rollenwechsel verweigert (Selbst-Privilegierung oder superadmin-Schutz)"}), 403
    return jsonify({"ok": True})


@app.route("/api/users/<name>/deactivate", methods=["POST"])
@sec.require_role("admin")
@sec.require_recent_mfa()
def api_users_deactivate(name):
    """Benutzer aktivieren/deaktivieren (Admin). MFA-Pflicht (§6)."""
    data = request.get_json(force=True, silent=True) or {}
    active = bool(data.get("active", False))
    if not sec.user_exists(name):
        return jsonify({"ok": False, "error": "Benutzer nicht gefunden"}), 404
    if name == _admin_actor():
        return jsonify({"ok": False, "error": "Du kannst dein eigenes Konto nicht deaktivieren"}), 400
    if active:
        # Phase 1: Reaktivierung setzt Status zurueck (MFA-Pflicht beachten)
        users = sec._load_users()
        users[name]["active"] = True
        if users[name].get("role") in sec.MFA_REQUIRED_ROLES \
                and not users[name].get("mfa_enabled"):
            users[name]["status"] = sec.USER_STATUS_MFA_REQUIRED
        else:
            users[name]["status"] = sec.USER_STATUS_ACTIVE
        users[name]["updated_at"] = datetime.utcnow().isoformat() + "Z"
        sec._save_users(users)
        sec.audit_log("user_activate", _admin_actor(), f"user={name}")
    else:
        sec.deactivate_user(name, _admin_actor())
    return jsonify({"ok": True})


@app.route("/api/users/<name>/reset-pw", methods=["POST"])
@sec.require_role("admin")
@sec.require_recent_mfa()
def api_users_reset_pw(name):
    """Passwort eines Benutzers zuruecksetzen (Admin). MFA-Pflicht (§6)."""
    data = request.get_json(force=True, silent=True) or {}
    pw = str(data.get("password", "") or "")
    if not sec.user_exists(name):
        return jsonify({"ok": False, "error": "Benutzer nicht gefunden"}), 404
    if len(pw) < 8:
        return jsonify({"ok": False, "error": "Passwort muss mind. 8 Zeichen haben"}), 400
    sec.change_password(name, pw)
    sec.audit_log("user_reset_pw", _admin_actor(), f"user={name}")
    return jsonify({"ok": True})


@app.route("/api/users/<name>/revoke", methods=["POST"])
@sec.require_role("admin")
@sec.require_recent_mfa()
def api_users_revoke(name):
    """Alle Sessions eines Benutzers beenden (Admin). MFA-Pflicht (§6)."""
    if not sec.user_exists(name):
        return jsonify({"ok": False, "error": "Benutzer nicht gefunden"}), 404
    sec.revoke_all_sessions(name)
    sec.audit_log("user_revoke_sessions", _admin_actor(), f"user={name}")
    return jsonify({"ok": True})


@app.route("/api/me", methods=["GET"])
def api_me():
    """Eigenes Profil (eingeloggt) + Tenant-Kontext (PHASE 1)."""
    u = sec.current_user()
    if not u:
        return jsonify({"error": "unauthorized"}), 401
    tenant_info = None
    try:
        import db as _db
        m = _db.MTDB()
        tenant_info = {
            "current_tenant": sec.get_current_tenant() or 1,
            "memberships": m.tenant_memberships_for_user(u["username"]),
        }
        m.close()
    except Exception:
        tenant_info = {"current_tenant": 1, "memberships": []}
    return jsonify({
        "ok": True,
        "username": u["username"],
        "role": u.get("role", "user"),
        "active": u.get("active", True),
        "mfa": bool(u.get("mfa_secret")),
        "last_login": u.get("last_login", ""),
        "permissions": sec.ROLE_PERMISSIONS.get(u.get("role", "user"), []),
        "tenants": tenant_info,
        "effective_role": sec.effective_role(u),
        "tenant_permissions": sec.effective_permissions(u),
    })


@app.route("/api/tenants", methods=["GET"])
@sec.require_tenant_role("admin")
def api_tenants():
    """Tenant-Liste (Admin) — PHASE 1. PHASE 3: effektive Rolle (Membership),
    nicht globale Rolle; non-superadmin sieht nur seinen eigenen Tenant."""
    try:
        import db as _db
        m = _db.MTDB()
        tenants = m.tenant_list()
        m.close()
        u = sec.current_user()
        if u and u.get("role", "").lower() == "superadmin":
            return jsonify({"ok": True, "tenants": tenants})
        # non-superadmin: nur der eigene Tenant (Isolation §2.3)
        cur = sec.get_current_tenant() or 1
        mine = [t for t in tenants if t.get("tenant_id") == cur]
        return jsonify({"ok": True, "tenants": mine})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/tenants/create", methods=["POST"])
@sec.require_tenant_role("admin")
def api_tenants_create():
    """Neuen Tenant anlegen (Admin) — PHASE 1. PHASE 3: nur superadmin darf
    neue Tenants anlegen (non-superadmin bleibt auf seinen Tenant beschraenkt)."""
    u = sec.current_user()
    if not (u and u.get("role", "").lower() == "superadmin"):
        return jsonify({"ok": False, "error": "Tenant anlegen erfordert superadmin"}), 403
    data = request.get_json(silent=True) or {}
    key = str(data.get("tenant_key", "")).strip()
    name = str(data.get("name", "")).strip()
    plan = str(data.get("plan_or_type", "personal")).strip() or "personal"
    mode = str(data.get("default_trading_mode", "SHADOW")).strip().upper() or "SHADOW"
    if not key or not name:
        return jsonify({"ok": False, "error": "tenant_key und name erforderlich"}), 400
    import re as _re
    if not _re.match(r"^[a-z0-9_\-]{2,32}$", key):
        return jsonify({"ok": False, "error": "tenant_key: 2-32 Zeichen, nur a-z0-9_-"}), 400
    try:
        import db as _db
        m = _db.MTDB()
        tid, fehler = m.tenant_create(key, name, plan, mode)
        m.close()
        if fehler:
            return jsonify({"ok": False, "error": fehler}), 409
        sec.audit_log("tenant_create", _admin_actor(), f"tenant={key} name={name} mode={mode}")
        return jsonify({"ok": True, "tenant_id": tid})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/tenants/<int:tid>/members", methods=["GET"])
@sec.require_tenant_role("admin")
def api_tenants_members(tid):
    """Mitglieder eines Tenants (Admin) — PHASE 1.
    PHASE 3: tid aus der URL wird NICHT blind vertraut — non-superadmin darf
    nur seinen eigenen Tenant sehen (Isolation §2.3 / §18)."""
    u = sec.current_user()
    is_super = bool(u and u.get("role", "").lower() == "superadmin")
    if not is_super and tid != (sec.get_current_tenant() or 1):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    try:
        import db as _db
        m = _db.MTDB()
        t = m.tenant_get(tid)
        if not t:
            m.close()
            return jsonify({"ok": False, "error": "tenant nicht gefunden"}), 404
        user_ids = m.tenant_user_ids(tid)
        members = []
        for uid in user_ids:
            u = sec.get_user(uid)
            if u:
                members.append({"username": uid, "role": u.get("role", "user"),
                                "active": u.get("active", True)})
        workspaces = m.workspace_list(tid)
        m.close()
        return jsonify({"ok": True, "tenant": t, "members": members, "workspaces": workspaces})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/tenants/<int:tid>/members", methods=["POST"])
@sec.require_tenant_role("admin")
def api_tenants_members_add(tid):
    """User einem Tenant zuordnen (Admin) — PHASE 1.
    PHASE 3: tid-Guard wie GET — non-superadmin darf nur im eigenen Tenant
    Mitglieder verwalten."""
    u = sec.current_user()
    is_super = bool(u and u.get("role", "").lower() == "superadmin")
    if not is_super and tid != (sec.get_current_tenant() or 1):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    role = str(data.get("role", "user")).strip() or "user"
    if not username:
        return jsonify({"ok": False, "error": "username erforderlich"}), 400
    if not sec.user_exists(username):
        return jsonify({"ok": False, "error": "User existiert nicht"}), 404
    try:
        import db as _db
        m = _db.MTDB()
        ok = m.tenant_membership_add(tid, username, role)
        m.close()
        if not ok:
            return jsonify({"ok": False, "error": "Zuordnung fehlgeschlagen"}), 409
        sec.audit_log("tenant_membership_add", _admin_actor(), f"tenant={tid} user={username} role={role}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/roles", methods=["GET"])
@sec.require_tenant_role("admin")
@sec.require_permission("roles.manage")
def api_roles():
    """Rollenkatalog + Permissions (Admin, PHASE 2)."""
    catalog = []
    for role in sec.ROLES:
        catalog.append({
            "role": role,
            "level": sec.ROLE_TO_LEVEL.get(role, "PUBLIC"),
            "permissions": sorted(set(
                sec.TENANT_ROLE_PERMISSIONS.get(
                    role, sec.ROLE_PERMISSIONS.get(role, [])) +
                sec.ROLE_FINE_PERMISSIONS.get(role, []))),
        })
    return jsonify({"ok": True, "roles": catalog,
                    "all_permissions": sec.ALL_PERMISSIONS})


@app.route("/api/me/permissions", methods=["GET"])
def api_me_permissions():
    """Effektive Permissions im aktuellen Tenant (eingeloggt, PHASE 2)."""
    u = sec.current_user()
    if not u:
        return jsonify({"error": "unauthorized"}), 401
    tid = sec.get_current_tenant()
    return jsonify({
        "ok": True,
        "username": u.get("username"),
        "tenant_id": tid,
        "effective_role": sec.effective_role(u),
        "permissions": sec.effective_permissions(u),
    })


@app.route("/api/me/password", methods=["POST"])
def api_me_password():
    """Eigenes Passwort aendern (eingeloggt)."""
    u = sec.current_user()
    if not u:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    alt = str(data.get("altes_passwort", "") or "")
    neu = str(data.get("neues_passwort", "") or "")
    if not sec.verify_password(u["username"], alt):
        return jsonify({"ok": False, "error": "Aktuelles Passwort falsch"}), 400
    if len(neu) < 8:
        return jsonify({"ok": False, "error": "Neues Passwort muss mind. 8 Zeichen haben"}), 400
    sec.change_password(u["username"], neu)
    sec.audit_log("password_change", u["username"])
    return jsonify({"ok": True})


@app.route("/api/me/mfa", methods=["POST"])
def api_me_mfa():
    """MFA einrichten/deaktivieren (eingeloggt)."""
    u = sec.current_user()
    if not u:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    aktion = str(data.get("aktion", "")).strip()  # "einrichten" | "verifizieren" | "deaktivieren"
    if aktion == "einrichten":
        if u.get("mfa_secret"):
            return jsonify({"ok": False, "error": "MFA ist bereits aktiv"}), 400
        secret = sec.generate_mfa_secret()
        users = sec._load_users()
        users[u["username"]]["mfa_pending_secret"] = secret
        sec._save_users(users)
        uri = sec.mfa_provisioning_uri(u["username"], secret)
        return jsonify({"ok": True, "secret": secret, "uri": uri})
    if aktion == "verifizieren":
        code = str(data.get("code", "") or "")
        secret = u.get("mfa_pending_secret") or u.get("mfa_secret")
        if not secret:
            return jsonify({"ok": False, "error": "Kein MFA-Secret vorhanden"}), 400
        if sec.verify_mfa(secret, code):
            users = sec._load_users()
            users[u["username"]]["mfa_secret"] = secret
            users[u["username"]].pop("mfa_pending_secret", None)
            sec._save_users(users)
            sec.audit_log("mfa_enable", u["username"])
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "Code ungültig"}), 400
    if aktion == "deaktivieren":
        code = str(data.get("code", "") or "")
        secret = u.get("mfa_secret")
        if not secret:
            return jsonify({"ok": False, "error": "MFA ist nicht aktiv"}), 400
        if sec.verify_mfa(secret, code):
            users = sec._load_users()
            users[u["username"]].pop("mfa_secret", None)
            users[u["username"]].pop("mfa_pending_secret", None)
            sec._save_users(users)
            sec.audit_log("mfa_disable", u["username"])
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "Code ungültig"}), 400
    return jsonify({"ok": False, "error": "Unbekannte Aktion"}), 400


# before_request-Guard, Antwortet nur bei gueltiger Session.
@app.route("/api/potenzial")
def api_potenzial():
    """Kandidaten je Risikostufe, mit Begruendung und Aktualitaet.

    Query-Parameter:
      art  = alle | aktien | etf   (Standard: alle)
      risikostufe = 0..90, optional, filtert auf eine Stufe
    """
    _kand = os.path.join(BASE, "screener_kandidaten.json")
    if not os.path.exists(_kand):
        return jsonify({
            "ok": False,
            "error": "keine_kandidatendatei",
            "hinweis": "screener.py ist noch nie gelaufen",
        }), 503

    try:
        with open(_kand, encoding="utf-8") as _f:
            _daten = json.load(_f)
    except Exception as _e:
        return jsonify({"ok": False, "error": "datei_unlesbar",
                        "detail": str(_e)[:100]}), 500

    _art = (request.args.get("art") or "alle").lower()
    if _art not in ("alle", "aktien", "etf"):
        _art = "alle"

    # Struktur erhalten: getrennte Eintraege je Stufe, nicht flach.
    _stufen = []
    for _key, _label in (("aktien", "Aktien"), ("etf", "ETF")):
        if _art != "alle" and _key != _art:
            continue
        for _s in sorted((_daten.get(_key) or {}).keys(), key=lambda x: int(x)):
            _liste = _daten[_key].get(_s) or []
            if not _liste:
                continue
            _stufen.append({
                "stufe": int(_s),
                "art": _key,
                "label": _label,
                "anzahl": len(_liste),
                "kandidaten": [
                    dict(_k, stufe=int(_s), art=_key) for _k in _liste
                ],
            })

    # Wie viele Titel stehen in mehreren Stufen? Das ist bei ETFs
    # normal (Jahresrendite ist ein Band), bei Aktien sollte es nie
    # vorkommen (Beta-Fenster sind disjunkt).
    _zaehler = {}
    for _s in _stufen:
        for _k in _s["kandidaten"]:
            _zaehler[_k["ticker"]] = _zaehler.get(_k["ticker"], 0) + 1
    for _s in _stufen:
        for _k in _s["kandidaten"]:
            _k["mehrfach"] = _zaehler[_k["ticker"]] > 1

    # Filter NACH dem Zaehler, aber die Ausgabezahlen NACH dem Filter.
    # Erster Versuch (29.09.2026) zaehlte "eindeutig" ueber alle
    # Stufen und meldete bei art=etf&risikostufe=90 "13 Kandidaten,
    # 121 eindeutig" - zwei Zahlen fuer zwei verschiedene Mengen,
    # was auf der Seite als Widerspruch erscheint.
    _filter_stufe = request.args.get("risikostufe")
    if _filter_stufe:
        try:
            _fs = int(_filter_stufe)
            _stufen = [s for s in _stufen if s["stufe"] == _fs]
        except ValueError:
            pass

    _eindeutig = len({k["ticker"] for s in _stufen
                      for k in s["kandidaten"]})
    _mehrfach = sum(1 for s in _stufen
                    if s["art"] == "aktien" and any(k["mehrfach"]
                                                    for k in s["kandidaten"]))

    try:
        _alter_s = time.time() - os.path.getmtime(_kand)
    except Exception:
        _alter_s = None

    _verlauf = []
    try:
        with open(os.path.join(BASE, "screener_verlauf.json"),
                  encoding="utf-8") as _f:
            _verlauf = json.load(_f)
    except Exception:
        pass

    _gesamt = sum(s["anzahl"] for s in _stufen)
    return jsonify({
        "ok": True,
        "zeitpunkt": _daten.get("zeitpunkt"),
        "quelle": _daten.get("quelle"),
        "alter_stunden": (round(_alter_s / 3600, 1)
                           if _alter_s is not None else None),
        "anzahl": _gesamt,
        "eindeutig": _eindeutig,
        "aktien_mehrfach": _mehrfach,
        "stufen": _stufen,
        "verlauf": _verlauf[-8:],
    })


if __name__ == "__main__":
    # SINGLE-INSTANCE-GUARD (FIX 2026-08-11):
    # Verhindert, dass mehrere dashboard.py-Instanzen gleichzeitig starten
    # (Hermes auto-restart, background-starts, Doppelklicks) und sich gegenseitig
    # den Port 5300 wegnehmen + security_users.json korrumpiert.
    import socket as _sock
    # Echter Listener-Check: wenn ein Server auf 5300 ANTWORTET -> belegt.
    # Reines bind() schlaegt bei TIME_WAIT-Sockets fehl (Ghost-Belegung).
    _probe = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
    _probe.settimeout(1.5)
    try:
        _probe.connect(("127.0.0.1", PORT))
        _probe.close()
        print("[GUARD] Port %d bereits belegt (Listener aktiv) — beende diese Instanz." % PORT)
        sys.exit(0)
    except (OSError, ConnectionRefusedError):
        # Kein Listener -> Port frei, wir duerfen starten
        pass
    finally:
        try:
            _probe.close()
        except Exception:
            pass
    print("Dashboard -> http://localhost:%d" % PORT)
    # PHASE 2 (Server-Sicherheit): nur intern binden, niemals 0.0.0.0 (Regel 4).
    # Interner Port bleibt 5300; der Reverse Proxy (Phase 3) ist der einzige
    # öffentliche Einstiegspunkt. Flask darf niemals direkt public sein.
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)

# \U0001F9E0 POTENZIAL (2026-09-29): Kandidaten des Screeners, lesend.
#
# ANLASS: Der Nutzer wollte eine Seite, die zeigt "welche moeglichen
# Aktien, ETFs und Spekstitel gibt es und warum". Das System konnte das
# vorher nicht beantworten: es hatte 684 fest eingetragene Ticker ohne
# erklaerbare Auswahlkriterien. screener.py erzeugt die Kandidaten aus
# messbaren Kriterien (Beta-Baender, Liquiditaet, Marktkapitalisierung,
# Jahresrendite), diese Route macht sie sichtbar.
#
# SICHERHEIT: Nur lesend. Keine Position, kein Handel, keine Secret.
# In security.py als AUTHENTICATED eingetragen, erbt den
