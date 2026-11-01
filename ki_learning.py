#!/usr/bin/env python3
"""KI-Lernmodul – differenzierter Lerneffekt mit KI-Bewertung.

Nach jedem Trading-Zyklus:
1. Sammelt alle KI-Entscheidungen (Typ 'decision') aus ki_log.json
2. Prüft die tatsächliche Kursentwicklung 1h/4h/24h nach der Entscheidung
3. Berechnet einen differenzierten LERNEFFEKT von -5..+5 (nicht nur richtig/falsch)
   - +5..+3 deutlich/klar bestätigt (Kurs ging in die richtige Richtung)
   - +2..+1 leicht bestätigt / neutral
   - -1..-2 leicht widerlegt
   - -3..-5 deutlich widerlegt
4. Lässt die KI die Ergebnisse BEWERTEN: Muster-Analyse, gewichtete Regeln
   → ki_regeln.json (max. 20 Regeln mit Gewicht für künftige Prompts)
5. Schreibt Lern-Notizen (mit lerneffekt + ki_bewertung) ins ki_log.json
6. Diese Notizen/Regeln fließen in zukünftige KI-Prompts ein
"""

import json, os, sys, threading, time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
# 01.11.2026: REGELN wurde im Fallback von lade_regeln()/speichere_regeln()
# benutzt, aber nie definiert (NameError, sobald learned_rules ausfaellt).
REGELN = os.path.join(BASE, "ki_regeln.json")
sys.path.insert(0, BASE)
KI_LOG = os.path.join(BASE, "ki_log.json")

# Settings-Loader (Fallbacks für Lern-Parameter)
import mtlog  # Zentrales Logsystem (Run-Kontext, Rotation)
try:
    from settings_loader import lernen as _lern_set, ki as _ki_set, bremse as _bremse_set, news_opt as _news_set
except Exception:
    def _lern_set(n, d=None): return d
    def _ki_set(n, d=None): return d
    def _bremse_set(n, d=None): return d
    def _news_set(n, d=None): return d

_ki_lock = threading.Lock()

# ─── Env laden (gleiche Logik wie ki_decisions.py) ───────────
for cand in [os.path.join(BASE, ".env"),
             os.path.expanduser("~/AppData/Local/hermes/.env")]:
    if os.path.exists(cand):
        with open(cand) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("OPENAI_API_KEY")
ZEN_URL = "https://api.openai.com/v1"

_regime_cache = {"wert": None, "zeit": None}

def _aktuelles_regime():
    """Phase 5 (S3.6): aktuelles Marktregime (gecached 1h)."""
    from datetime import datetime as _dt
    now = _dt.now()
    if _regime_cache["wert"] and _regime_cache["zeit"]:
        if (now - _regime_cache["zeit"]).total_seconds() < 3600:
            return _regime_cache["wert"]
    try:
        from boersen import markt_regime
        r = markt_regime()
        _regime_cache["wert"] = r
        _regime_cache["zeit"] = now
        return r
    except Exception:
        return "unbekannt"

MODEL = os.environ.get("KI_MODEL", "gpt-5.3-codex")


def lade_ki_log():
    with _ki_lock:
        if not os.path.exists(KI_LOG):
            return []
        try:
            with open(KI_LOG, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            data = []
        return data if isinstance(data, list) else []


def schreibe_ki_log(eintrag):
    with _ki_lock:
        log = lade_ki_log()
        log.append(eintrag)
        if len(log) > 1200:
            log = log[-1200:]
        with open(KI_LOG, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)


def lade_lern_notizen(max_age_stunden=24):
    """Lädt alle 'learned'-Einträge der letzten N Stunden als Kontext."""
    log = lade_ki_log()
    cutoff = datetime.now() - timedelta(hours=max_age_stunden)
    notizen = []
    for e in log:
        if e.get("typ") == "learned":
            try:
                z = datetime.fromisoformat(e.get("zeit", ""))
                if z >= cutoff:
                    notizen.append(e)
            except:
                pass
    return notizen


def lerneffekt(aktion, change):
    """Berechnet differenzierten Lerneffekt -5..+5.

    kaufen:  Kurs stieg  → positiv (richtig),  Kurs fiel   → negativ (falsch)
    verkaufen: Kurs fiel/blieb → positiv (richtig), Kurs stieg → negativ (falsch)
    halten:  kleine Bewegung = gut, große Bewegung = falsch
    """
    if aktion == "kaufen":
        richtung = change
    elif aktion == "verkaufen":
        richtung = -change
    else:  # halten
        richtung = -(abs(change) or 0.0)  # jede große Bewegung widerlegt "halten"

    betrag = abs(richtung)
    if betrag >= 3.0:
        stufe = 5
    elif betrag >= 2.0:
        stufe = 4
    elif betrag >= 1.0:
        stufe = 3
    elif betrag >= 0.5:
        stufe = 2
    else:
        stufe = 0  # unter 0.5% = Rauschen → neutral
    wert = stufe if richtung >= 0 else -stufe

    if wert >= 3:
        kat = "success"
    elif wert >= 1:
        kat = "teilsuccess"
    elif wert == 0:
        kat = "neutral"
    elif wert >= -2:
        kat = "teilfehler"
    else:
        kat = "fehler"
    return wert, kat


def lerneffekt_label(wert):
    labels = {
        5: "Deutlich bestätigt", 4: "Klar bestätigt", 3: "Bestätigt",
        2: "Leicht bestätigt", 1: "Geringfügig bestätigt", 0: "Neutral",
        -1: "Geringfügig widerlegt", -2: "Leicht widerlegt",
        -3: "Widerlegt", -4: "Klar widerlegt", -5: "Deutlich widerlegt",
    }
    return labels.get(wert, "Neutral")


def _atr_normalisiert(ticker, change):
    """Phase 3 (S3.2): Normalisiert %-Change durch 20d-ATR.

    Spekulative Titel (hohe ATR) brauchen größere Bewegungen für gleiches Signal.
    Gibt (norm_change, atr) zurück. Bei Fehler: norm_change = change, atr = None.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="30d", interval="1d")
        if hist is None or len(hist) < 5 or "Close" not in hist:
            return change, None
        close = hist["Close"].dropna()
        if len(close) < 5:
            return change, None
        # ATR ~ typische Tagesrange (High-Low), vereinfacht über Close-Diff
        diffs = close.diff().abs().dropna()
        atr = float(diffs.tail(20).mean()) if len(diffs) >= 20 else float(diffs.mean())
        if atr <= 0:
            return change, None
        preis = float(close.iloc[-1]) or 1.0
        atr_pct = atr / preis * 100.0
        norm = change / atr_pct if atr_pct > 0 else change
        return round(norm, 3), round(atr_pct, 2)
    except Exception:
        return change, None


def multi_timeframe_regel_lernen(entscheidungen, min_divergenz=3.0):
    """Priorität 6: Multi-Timeframe-Regeln.

    Erkennt Momentum-Divergenzen zwischen kurzfristig (15min) und
    langfristig (1d) und lernt daraus Regeln.

    Logik:
      - 15min-Momentum vs 1d-Trend
      - Wenn KI 'kaufen' bei 15min↑ aber 1d↓ → oft Falle (Regel: 'Vorsicht bei
        kurzfristigem Pump gegen Tagestrend')
      - Wenn KI 'verkaufen' bei 15min↓ aber 1d↑ → Verkauf zu früh (Regel: 'Halten
        bei kurzfristigem Dip in Aufwärtstrend')

    Liefert Liste neuer Regel-Dicts zurück (für speichere_regeln).
    """
    neu = []
    try:
        for d in entscheidungen:
            ticker = d.get("ticker")
            aktion = d.get("aktion")
            if not ticker or aktion not in ("kaufen", "verkaufen"):
                continue
            # Momentum aus lerneffekt_multiskalen abrufen (falls verfügbar)
            try:
                wert, kat, detail = lerneffekt_multiskalen(ticker, aktion)
            except Exception:
                continue
            if not detail:
                continue
            c15 = detail.get("change_15m") or 0.0
            c1d = detail.get("change_1d") or 0.0
            # Divergenz?
            if abs(c15 - c1d) < min_divergenz:
                continue
            divergenz_auf = c15 > 0 and c1d < 0
            divergenz_ab = c15 < 0 and c1d > 0
            if aktion == "kaufen" and divergenz_auf:
                # KI kauft den kurzfristigen Pump gegen Tagestrend → riskant
                muster = f"[MTF] Vorsicht Kaufen bei 15min↑/1d↓ ({ticker})"
                neu.append({
                    "muster": muster,
                    "regel": f"KI kaufte {ticker} bei kurzfristigem Anstieg (15min {c15:+.1f}%) "
                             f"trotz fallendem Tagestrend (1d {c1d:+.1f}%). Oft eine Falle.",
                    "typ": "anti",
                    "gewicht": -1.0,
                    "support_count": 1,
                    "violation_count": 0,
                    "avg_effect_when_applied": 0.0,
                    "kontext": {"asset_klasse": [], "sektor": [], "vix_range": [0, 999],
                                "trend_4h": "", "regime": [], "min_konfidenz": 0},
                    "created_at": datetime.now().isoformat(),
                    "oos_confirmed": False,
                    "updated_at": datetime.now().isoformat(),
                    "last_seen_at": datetime.now().isoformat(),
                    "decay_lambda": 0.01,
                })
            elif aktion == "verkaufen" and divergenz_ab:
                # KI verkauft den kurzfristigen Dip in Aufwärtstrend → zu früh
                muster = f"[MTF] Halten bei 15min↓/1d↑ ({ticker})"
                neu.append({
                    "muster": muster,
                    "regel": f"KI verkaufte {ticker} bei kurzfristigem Rücksetzer (15min {c15:+.1f}%) "
                             f"trotz Aufwärtstrends (1d {c1d:+.1f}%). Verkauf war zu früh.",
                    "typ": "positiv",
                    "gewicht": 1.0,
                    "support_count": 1,
                    "violation_count": 0,
                    "avg_effect_when_applied": 0.0,
                    "kontext": {"asset_klasse": [], "sektor": [], "vix_range": [0, 999],
                                "trend_4h": "", "regime": [], "min_konfidenz": 0},
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "last_seen_at": datetime.now().isoformat(),
                    "decay_lambda": 0.01,
                })
    except Exception:
        pass
    return neu


# Mindestalter einer Entscheidung, bevor ihr Lerneffekt gemessen wird.
# Messung nutzt 15m/4h/1d-Bars -> 4h sinnvoll, damit sich der Kurs bewegt hat.
MINDESTALTER_STUNDEN = 4


def lerneffekt_multiskalen(ticker, aktion):
    """Phase 3 (S3.2): Kombiniert 15m/4h/1d + ATR-Normalisierung.

    score = 0.3*s15m + 0.5*s4h + 0.2*s1d  (jede Skala via lerneffekt-Stufen)
    Dann ATR-Normalisierung: spekulative Titel brauchen mehr für gleiches Gewicht.

    Return: (wert, kategorie, detail) oder (None, None, {}) bei Fehler.
    """
    skalen = {}
    entw_15 = hole_kurs_entwicklung_intervall(ticker, "15m", bars=4)  # ~1h
    if entw_15:
        skalen["change_15m"] = entw_15["change_pct"]
    entw_4 = hole_kurs_entwicklung(ticker, 4)
    if entw_4:
        skalen["change_4h"] = entw_4["change_pct"]
    entw_1d = hole_kurs_entwicklung(ticker, 24)
    if entw_1d:
        skalen["change_1d"] = entw_1d["change_pct"]
    if not skalen:
        return None, None, {}
    # Roh-Scores pro Skala (via lerneffekt-Stufen)
    s15 = lerneffekt(aktion, skalen.get("change_15m", 0))[0] if "change_15m" in skalen else 0
    s4 = lerneffekt(aktion, skalen.get("change_4h", 0))[0]
    s1 = lerneffekt(aktion, skalen.get("change_1d", 0))[0] if "change_1d" in skalen else 0
    # Kombiniert (S3.2 Formel)
    kombi = 0.3 * s15 + 0.5 * s4 + 0.2 * s1
    # Auf −5…+5 runden
    wert = max(-5, min(5, round(kombi)))
    # ATR-Normalisierung: bei hoher Volatilität Signal dämpfen
    atr_pct = _atr_normalisiert(ticker, skalen.get("change_4h", 0))[1]
    if atr_pct is not None and atr_pct > 5.0:
        # Spekulativ: nur 70% des Signals werten (weniger hartes "−5")
        wert = round(wert * 0.7)
    kat = ("success" if wert >= 3 else "teilsuccess" if wert >= 1 else
           "neutral" if wert == 0 else "teilfehler" if wert >= -2 else "fehler")
    detail = {
        "change_15m": skalen.get("change_15m"),
        "change_4h": skalen.get("change_4h", 0.0),
        "change_1d": skalen.get("change_1d"),
        "atr_pct": atr_pct,
        "s15": s15, "s4": s4, "s1": s1,
    }
    return wert, kat, detail



def hole_kurs_entwicklung(ticker, stunden):
    """Hole Kurs vor und nach einer Zeit (für Performance-Check).

    Nutzt 1h-Bars = nur echte Handelsstunden. Über Nacht gibt es keine
    neuen Bars, daher misst der Check immer echte Handelszeit.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="3d", interval="1h")
        if len(hist) < 2:
            return None
        aktuell = float(hist["Close"].iloc[-1])
        idx = len(hist) - 1 - max(1, int(stunden))
        if idx < 0:
            idx = 0
        vor = float(hist["Close"].iloc[idx])
        if vor > 0:
            change = ((aktuell / vor) - 1) * 100
            return {"aktuell": aktuell, "vor": vor, "change_pct": change}
        return None
    except:
        return None


def hole_kurs_entwicklung_intervall(ticker, intervall="15m", bars=4):
    """Phase 3 (S3.2): Kurzfristige Bars (15m) für mehrstufiges Signal.

    Lädt `bars` Intervalle zurück. Gibt change_pct über den Zeitraum.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="1d", interval=intervall)
        if len(hist) < 2:
            return None
        aktuell = float(hist["Close"].iloc[-1])
        idx = max(0, len(hist) - 1 - bars)
        vor = float(hist["Close"].iloc[idx])
        if vor > 0:
            change = ((aktuell / vor) - 1) * 100
            return {"aktuell": aktuell, "vor": vor, "change_pct": change}
        return None
    except:
        return None


def hole_verkaeufe_24h(ticker):
    """Nach einem Verkauf: Wie weit ist der Kurs in den nächsten 24h (Handelsstunden) gefallen/gelaufen?

    Positiv = Kurs stieg NACH dem Verkauf weiter (Exit zu früh / falsch).
    Negativ = Kurs fiel weiter (Exit richtig, Timing gut).
    """
    return hole_tendenz_1d(ticker)


def hole_tendenz_1d(ticker):
    """24h-Tendenz eines Tickers (1d-Bars: letzter Schluss vs. Vortag).

    Positiv = Kurs steigt seit gestern, Negativ = fällt.
    Dient als 24h-Zusatzmessung zur 4h-Kursentwicklung:
    „4h +3%, aber 24h −2%" → nur kurzfristige Erholung, kein Trend.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="1mo", interval="1d")
        if len(hist) < 2:
            return None
        aktuell = float(hist["Close"].iloc[-1])
        vor = float(hist["Close"].iloc[-2])
        if vor > 0:
            return round(((aktuell / vor) - 1) * 100, 2)
        return None
    except:
        return None


def kategorie_fuer_ticker(ticker):
    """Sektor/Kategorie eines Tickers aus spec_depots/*.json ziehen (sonst '')."""
    try:
        pfad = os.path.join(BASE, "spec_depots", "%s.json" % ticker.replace("/", "_").replace("^", ""))
        if os.path.exists(pfad):
            with open(pfad, encoding="utf-8") as f:
                d = json.load(f)
            return d.get("kategorie", "") or ""
    except Exception:
        pass
    return ""


def news_swap_score(ticker, pnl_prozent, news_score, benchmark_ret=0.0):
    """Priorität 5: News-Swap — News-Impact triggert Umschichtung.

    Wenn ein Ticker:
      - hohen News-Impact hat (news_score >= 75) UND
      - schwach performt (pnl_prozent < benchmark_ret - 2)
    → Umschichtung sinnvoll (Verkauf + Benchmark/Stärkerer).

    Rückgabe: (score, beg)
      score >= 60 → Swap-Empfehlung
    """
    if news_score < 75:
        return 0, "kein relevanter News-Impact"
    score = 30  # Basis für hohen News-Impact
    teile = [f"News-Impact {news_score} (>=75)"]
    if pnl_prozent < benchmark_ret - 2:
        score += 50
        teile.append(f"schwach vs Benchmark ({pnl_prozent:+.1f}% vs {benchmark_ret:+.1f}%)")
    elif pnl_prozent < 0:
        score += 30
        teile.append(f"im Minus ({pnl_prozent:+.1f}%)")
    else:
        score += 10
        teile.append("trotz News im Plus (abwarten)")
    return score, "; ".join(teile)


def news_score_fuer_ticker(ticker, log, max_std=48):
    """Liefert den KI-News-Score (0-100) fuer einen Ticker aus dem ki_log.

    Nutzt die hoechste bewertete News (typ='news') der letzten max_std Stunden.
    Rueckgabe 0, wenn keine bewertete News vorhanden (neutral, kein Swap-Trigger).
    """
    if not log:
        return 0
    cutoff = datetime.now() - timedelta(hours=max_std)
    beste = 0
    for e in log:
        if e.get("typ") != "news":
            continue
        try:
            z = datetime.fromisoformat(e.get("zeit", ""))
            if z < cutoff:
                continue
        except Exception:
            pass
        tickers = [t.upper() for t in (e.get("tickers") or [])]
        if ticker and ticker.upper() in tickers:
            sc = float(e.get("score", 0) or 0)
            if sc > beste:
                beste = sc
    return beste


def news_swap_entscheidung_ueberschreiben(entscheidung, ticker, pnl_prozent, news_score,
                                          benchmark_ret=0.0, schwelle=60):
    """Priorität 5: Wendet News-Swap auf KI-Entscheidung an.

    Wenn KI 'halten' will ABER News-Swap-Score >= schwelle → wird zu 'verkaufen' (Umschichtung).
    """
    if entscheidung.get("aktion") not in ("halten", "kaufen"):
        return entscheidung, False
    score, beg = news_swap_score(ticker, pnl_prozent, news_score, benchmark_ret)
    if score >= schwelle:
        aktion_alt = entscheidung.get("aktion")
        entscheidung["aktion_original"] = aktion_alt
        entscheidung["aktion"] = "verkaufen"
        entscheidung["grund"] = (entscheidung.get("grund", "") or "") + \
            f" [News-Swap {score}: Impact {news_score} + schwach → Umschichtung]"
        entscheidung["news_swap_score"] = score
        return entscheidung, True
    return entscheidung, False


# 01.11.2026: Hier hing ein verwaister Funktionsrumpf ohne def-Zeile
# (Duplikat von news_score_fuer_ticker) - unerreichbar, entfernt.


def ki_bewerte_lernergebnisse(ergebnisse):
    """Lässt die KI die Lern-Ergebnisse differenziert bewerten.

    ergebnisse: Liste von Dicts {ticker, aktion, konfidenz, grund, change_pct, lerneffekt}
    → liefert {bewertung, regeln: [{muster, regel, gewicht}], anpassung}
    Kein Crash bei Fehler: liefert None.
    """
    if not ergebnisse:
        return None
    try:
        from ki_provider import call_ki
    except Exception:
        return None

    zeilen = []
    for e in ergebnisse:
        extra = []
        if e.get("kategorie"):
            extra.append(f"Sektor: {e['kategorie']}")
        if e.get("news_score"):
            extra.append(f"News-Score: {e['news_score']:.0f}")
        if e.get("konfidenz"):
            extra.append(f"Konfidenz: {e['konfidenz']}")
        if e.get("exit_24h") is not None:
            extra.append(f"Kurs 24h danach: {e['exit_24h']:+.1f}%")
        if e.get("change_24h") is not None:
            extra.append(f"24h-Tendenz: {e['change_24h']:+.1f}%")
        extra_str = (" · " + " | ".join(extra)) if extra else ""
        zeilen.append(
            f"- {e['ticker']}: {e['aktion']} (Konfidenz {e['konfidenz']}), "
            f"Kurs {e['change_pct']:+.1f}% → Lerneffekt {e['lerneffekt']:+d} "
            f"({lerneffekt_label(e['lerneffekt'])}){extra_str}\n"
            f"  Grund der Entscheidung: {e.get('grund','')[:80]}"
        )

    prompt = f"""Du bist das Lernmodul eines KI-Trading-Systems. Bewerte folgende Entscheidungs-Ergebnisse differenziert.

LERN-EFFEKT-SKALA:
- +5..+3: Entscheidung deutlich/klar bestätigt (Kurs ging klar in die richtige Richtung)
- +2..+1: leicht bestätigt, +0: neutral (kein Signal)
- -1..-2: leicht widerlegt, -3..-5: deutlich widerlegt (Kurs ging klar in die falsche Richtung)

ZUSÄTZLICHE SIGNALE IN DEN DATEN:
- "News-Score": 0-100 Bewertung relevanter News vor der Entscheidung. Lerne, ob hohe Scores (≥75) verlässlich waren.
- "Konfidenz": Selbstbewusstsein der KI (0-100). Lerne, ob hohe Konfidenz (≥80) öfter richtig lag als niedrige (<60).
- "Sektor": Branche des Tickers. Lerne Sektor-Muster (z.B. Hype-Sektoren meiden).
- "Kurs 24h danach": Bei Verkäufen – wie der Kurs nach dem Verkauf weiterlief (positiv = zu früh verkauft).
- "24h-Tendenz": Mittelfristige Kursrichtung (1d-Bars). Vergleiche mit dem 4h-Wert: "4h +3%, 24h −2%" = nur kurzfristige Erholung, kein Trend → vorsichtiger bewerten.

ERGEBNISSE:
{chr(10).join(zeilen)}

Antworte NUR mit JSON:
{{"bewertung": "3-5 Sätze: Welche Muster waren verlässlich, welche nicht. Beziehe News-Scores, Konfidenz und Sektoren mit ein. Sei konkret.",
  "regeln": [
    {{"muster": "z.B. RSI<30 + Abwärtstrend bei IONQ", "regel": "Konkrete Handlungsregel (kaufen/halten/verkaufen, wann)", "gewicht": 0.5-2.0}}
  ],
  "anpassung": "1-2 Sätze: Wie sollen künftige Entscheidungen angepasst werden?"}}

Regeln: max. 5, nur wenn wirklich ein Muster erkennbar ist. Gewicht >1.0 = Regel besonders bestätigt, <1.0 = vorsichtig anwenden. Muster-Präfixe: [RSI], [Trend], [News], [Konfidenz], [Sektor], [Exit] – je nachdem, was die Regel betrifft."""
    try:
        raus, _provider = call_ki(
            [
                {"role": "system", "content": "Du antwortest NUR mit JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        if not raus:
            return None
        start = raus.find("{")
        end = raus.rfind("}") + 1
        if start >= 0 and end > start:
            raus = raus[start:end]
        return json.loads(raus)
    except Exception:
        return None


def _decay(gewicht, zeit_iso, faktor=0.85, halbwert_tage=4.3):
    """Regel-Decay: Gewicht schrumpft mit dem Alter (0.85^Tage).

    Eine Regel, die nicht mehr bestätigt wird, stirbt langsam:
    Tag 0: 100% · Tag 2: 72% · Tag 4: 52% · Tag 7: 32% → < 0.5 → fliegt raus.
    Bei jeder Bestätigung wird die Regel 'verjüngt' (zeit = jetzt).
    """
    try:
        z = datetime.fromisoformat(zeit_iso)
        tage = (datetime.now() - z).total_seconds() / 86400.0
        if tage <= 0:
            return gewicht
        return gewicht * (faktor ** tage)
    except Exception:
        return gewicht


def lade_regeln(max_alter_tage=7):
    """Lädt gewichtete Regeln aus ki_regeln.json (max. 7 Tage alt).

    Wendet Regel-Decay an: alte, nicht mehr bestätigte Regeln verlieren
    Gewicht und werden unter 0.5 aussortiert (veraltete Wahrheiten sterben).
    """
    # Phase 0: learned_rules.json ist Source of Truth (auch wenn ki_regeln.json noch existiert)
    try:
        from learned_rules import lade_regeln as _lr_lade
        regeln = _lr_lade(max_alter_tage=max_alter_tage if max_alter_tage else 365)
        # Alte Felder mappen für Kompatibilität (zeit, anti)
        for r in regeln:
            r.setdefault("zeit", r.get("updated_at", r.get("created_at", "")))
            r.setdefault("anti", r.get("typ") == "anti")
        return regeln
    except Exception:
        pass
    if not os.path.exists(REGELN):
        return []
    try:
        with open(REGELN, encoding="utf-8") as f:
            regeln = json.load(f)
        cutoff = datetime.now() - timedelta(hours=max_alter_tage)
        frisch = []
        for r in regeln:
            try:
                z = datetime.fromisoformat(r.get("zeit", ""))
                if z >= cutoff:
                    r = dict(r)
                    r["gewicht"] = round(_decay(float(r.get("gewicht", 1.0)), r.get("zeit", "")), 2)
                    # Anti-Regeln (negative Gewichte / Verbote) IMMER behalten
                    is_anti = r.get("anti") or str(r.get("muster", "")).startswith("[Anti]") or float(r.get("gewicht", 1.0)) < 0
                    if is_anti or r["gewicht"] >= 0.5:
                        frisch.append(r)
            except:
                pass
        frisch.sort(key=lambda r: float(r.get("gewicht", 0)), reverse=True)
        return frisch
    except:
        return []


def speichere_regeln(neue_regeln):
    """Fügt neue Regeln hinzu, gewichtet bestehende hoch, hält max. 20.

    Phase 0: delegiert an learned_rules.py (Source of Truth).
    Schreibt learned_rules.json + kompatiblen Export ki_regeln.json.
    """
    try:
        from learned_rules import speichere_regeln as _lr_speichern
        regeln = _lr_speichern(neue_regeln)
        # Kompatibilität: alte Aufrufer erwarten ki_regeln.json-Format
        result = []
        for r in regeln:
            result.append({
                "muster": r.get("muster", ""),
                "regel": r.get("regel", ""),
                "gewicht": r.get("effektiv_gewicht", r.get("gewicht", 0)),
                "anti": r.get("typ") == "anti",
                "zeit": r.get("updated_at", ""),
            })
        return result
    except Exception:
        pass
    # Fallback: alte Logik
    regeln = lade_regeln(max_alter_tage=365)  # alle laden
    jetzt = datetime.now().isoformat()
    for nr in neue_regeln:
        muster = (nr.get("muster") or "").strip()
        regel = (nr.get("regel") or "").strip()
        if not muster or not regel:
            continue
        gewicht = float(nr.get("gewicht", 1.0))
        # Bestehende Regel mit ähnlichem Muster? → Gewicht mischen
        gefunden = False
        for r in regeln:
            if r.get("muster") == muster:
                alt = float(r.get("gewicht", 1.0))
                r["gewicht"] = round(min(2.5, (alt * 0.7) + (gewicht * 0.3)), 2)
                r["regel"] = regel
                r["zeit"] = jetzt
                gefunden = True
                break
        if not gefunden:
            regeln.append({
                "muster": muster, "regel": regel,
                "gewicht": round(gewicht, 2), "zeit": jetzt,
            })
    # Sortieren nach Gewicht, max. 20 — aber Anti-Regeln (Verbote) IMMER behalten
    regeln.sort(key=lambda r: float(r.get("gewicht", 1.0)), reverse=True)
    # Trenne Anti-Regeln (negatives Gewicht) von positiven
    anti = [r for r in regeln if r.get("anti") or float(r.get("gewicht", 1.0)) < 0]
    positiv = [r for r in regeln if not (r.get("anti") or float(r.get("gewicht", 1.0)) < 0)]
    positiv = positiv[:20 - len(anti)]  # Anti-Regeln bekommen reservierte Plätze
    regeln = positiv + anti
    with open(REGELN, "w", encoding="utf-8") as f:
        json.dump(regeln, f, ensure_ascii=False, indent=2)
    return regeln


def regel_familien_statistik(max_age_h=168):
    """Trefferquote pro Regel-Familie aus learned-Einträgen (letzte 7 Tage).

    Gruppiert die Regel-Muster (ki_regeln.json) nach ihrem Präfix
    ([RSI], [Trend], [News], [Anti], [Exit], [Konfidenz], [Sektor])
    und zählt für jede Familie, wie viele bestätigte (≥1) vs.
    widerlegte (≤−1) Lerneffekte es gab → „Regel X: 7× angewandt, 4× bestätigt".
    """
    try:
        with open(KI_LOG, encoding="utf-8") as f:
            log = json.load(f)
        cutoff = datetime.now() - timedelta(hours=max_age_h)
        fam = {}
        for e in log:
            if e.get("typ") != "learned":
                continue
            le = e.get("lerneffekt")
            if not isinstance(le, (int, float)):
                continue
            try:
                if datetime.fromisoformat(e.get("zeit", "")) < cutoff:
                    continue
            except Exception:
                continue
            notiz = str(e.get("notiz", ""))
            # Familie aus der Notiz ableiten (Präfix-Icons/-Wörter)
            f_ = "Basis"
            if "Gegen-Regel" in notiz or "[Anti]" in notiz:
                f_ = "Anti"
            elif "News-Lernschleife" in notiz or "News-Score" in notiz:
                f_ = "News"
            elif "Exit-Qualität" in notiz or "zu früh verkauft" in notiz:
                f_ = "Exit"
            elif "Konfidenz-Kalibrierung" in notiz:
                f_ = "Konfidenz"
            elif "Sektor" in notiz:
                f_ = "Sektor"
            st = fam.setdefault(f_, {"ges": 0, "pos": 0, "neg": 0})
            st["ges"] += 1
            if le >= 1:
                st["pos"] += 1
            elif le <= -1:
                st["neg"] += 1
        ergebnis = []
        for name, st in sorted(fam.items(), key=lambda kv: -kv[1]["ges"]):
            quote = round(st["pos"] / st["ges"] * 100, 0) if st["ges"] else 0
            ergebnis.append({
                "familie": name,
                "ges": st["ges"], "pos": st["pos"], "neg": st["neg"],
                "quote": int(quote),
            })
        return ergebnis
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
# Deterministische Selbst-Analysen (für jeden Lernlauf)
# ═══════════════════════════════════════════════════════════════

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


def _grund_text_analyse(ergebnisse):
    """Clustert Begründungs-Texte und berechnet Trefferquoten pro Cluster."""
    cluster = {}
    for d in ergebnisse:
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


def _verlust_aversion_check(ergebnisse):
    """Prüft ob KI nach Verlusten riskanter handelt (Revanche-Trading)."""
    # Ergebnisse chronologisch sortieren
    chrono = sorted([d for d in ergebnisse if isinstance(d.get("lerneffekt"), (int, float))],
                    key=lambda d: d.get("zeit", ""))
    nach_verlust = {"konfidenz": [], "voll": 0, "n": 0}
    nach_gewinn = {"konfidenz": [], "voll": 0, "n": 0}
    for i in range(1, len(chrono)):
        vorher = chrono[i - 1].get("lerneffekt")
        jetzt = chrono[i]
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

    def _sum(st):
        if not st["n"]:
            return None
        return {
            "n": st["n"],
            "konfidenz_avg": round(sum(st["konfidenz"]) / len(st["konfidenz"]), 1),
            "voll_quote": round(st["voll"] / st["n"] * 100, 0),
        }

    nv, ng = _sum(nach_verlust), _sum(nach_gewinn)
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


def _regel_abweichungen_check(ergebnisse):
    """Prüft Regel-Abweichungen: RSI-Regeln, Anti-Regeln, Selbst-Widersprüche."""
    from ki_learning import lade_regeln
    regeln = lade_regeln(max_alter_tage=365)
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
            abgewichen = befolgt = 0
            for d in ergebnisse:
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
                    "regel": r.get("muster", ""), "aktion": regel_aktion, "typ": "RSI-Bedingung",
                    "befolgt": befolgt, "abgewichen": abgewichen,
                })
        elif ist_anti:
            abgewichen = befolgt = 0
            for d in ergebnisse:
                aktion = str(d.get("aktion", "")).lower()
                if not aktion:
                    continue
                if aktion == regel_aktion:
                    abgewichen += 1
                else:
                    befolgt += 1
            if abgewichen >= 1:
                ergebnis.append({
                    "regel": r.get("muster", ""), "aktion": regel_aktion, "typ": "Anti-Verletzung",
                    "befolgt": befolgt, "abgewichen": abgewichen,
                })
        else:
            ticker_aktionen = {}
            for d in ergebnisse:
                aktion = str(d.get("aktion", "")).lower()
                if aktion in ("kaufen", "verkaufen"):
                    ticker_aktionen.setdefault(d.get("ticker"), set()).add(aktion)
            widersprueche = {t: a for t, a in ticker_aktionen.items()
                             if len(a) >= 2 and "kaufen" in a and "verkaufen" in a}
            if widersprueche:
                ergebnis.append({
                    "regel": "Selbst-Widerspruch", "aktion": "kaufen/verkaufen",
                    "typ": "Ticker-Widerspruch",
                    "ticker": ", ".join(list(widersprueche.keys())[:5]),
                    "befolgt": len(widersprueche), "abgewichen": 0,
                })
    return ergebnis



def _oos_bestätigung(regel, ergebnisse):
    """Prio4: Regel gilt erst als bestätigt, wenn sie auf NACHFOLGENDEN,
    unabhängigen Trades (nach created_at) mit mindestens min_samples Stützen hält."""
    from settings_loader import lernen as _lernen
    min_samples = int(_lernen("min_samples", 5))
    created = regel.get("created_at", "")
    try:
        ct = datetime.fromisoformat(created) if created else datetime.min
    except Exception:
        ct = datetime.min
    nach = [e for e in ergebnisse
            if e.get("regel_id") == regel.get("id")
            and e.get("zeit")
            and datetime.fromisoformat(e["zeit"]) > ct]
    if len(nach) >= min_samples and any((e.get("lerneffekt", 0) or 0) > 0 for e in nach):
        return True
    return (regel.get("support_count", 0) or 0) >= 2 * min_samples

def anti_muster_regeln(ergebnisse):
    """Gegen-Regel-Lernen: findet Muster, die systematisch falsch lagen.

    Gruppiert (Sektor, Aktion) bzw. (Aktion) — Muster mit ≥5 Widerlegungen (R5:
    Mindest-Sample erhöht, um Ausreißer aus hochvolatilen Spek-Tickern zu filtern)
    und Ø-Lerneffekt ≤ −2 werden als [Anti]-Regel (Verbot) zurückgegeben.
    `kategorie` in ergebnisse-Dicts ist der SEKTOR (nicht die Lerneffekt-Kategorie).
    """
    anti_regeln = []
    # R5: Mindest-Sample aus Settings (anti_min_n, Default 5) — verhindert Überreaktion
    MIN_N = int(_lern_set("anti_min_n", 5))
    if not ergebnisse or len(ergebnisse) < MIN_N:
        return anti_regeln
    global _OOS_ERGEBNISSE
    _OOS_ERGEBNISSE = ergebnisse
    gruppen = {}
    for e in ergebnisse:
        sektor = e.get("sektor") or e.get("kategorie") or ""
        # Schutz: kategorie könnte die Lerneffekt-Kategorie sein (success/fehler…)
        if sektor in ("success", "teilsuccess", "neutral", "teilfehler", "fehler", "confidence"):
            sektor = ""
        aktion = e.get("aktion", "")
        if not aktion:
            # Fallback: Aktion aus der Notiz parsen ("TICKER: verkaufen → …")
            notiz = str(e.get("notiz", ""))
            import re
            m = re.search(r"\b(kaufen|halten|verkaufen)\b", notiz)
            aktion = m.group(1) if m else ""
        schluessel = (sektor, aktion) if sektor else ("*", aktion)
        gruppen.setdefault(schluessel, []).append(e)

    for (sektor, aktion), grp in sorted(gruppen.items(), key=lambda kv: -len(kv[1])):
        if len(grp) < MIN_N:
            continue
        werte = [g["lerneffekt"] for g in grp if isinstance(g.get("lerneffekt"), (int, float))]
        if len(werte) < MIN_N:
            continue
        durchschn = sum(werte) / len(werte)
        widerlegt = sum(1 for w in werte if w <= -2)
        # R5: erst ab n>=5 UND mehrheitlich widerlegt (>=60% der Stichprobe)
        if durchschn <= -2.0 and widerlegt >= max(2, int(MIN_N * 0.6)):
            bezug = f"bei {sektor}-Titeln" if sektor != "*" else "allgemein"
            muster = f"[Anti] {aktion} {bezug}"
            regel = (f"NICHT {aktion} {bezug} – systematisch falsch "
                     f"({widerlegt}/{len(werte)} widerlegt, Ø {durchschn:+.1f}). "
                     f"Ausnahme nur mit sehr starkem Grund")
            gewicht = round(-min(2.5, 1.0 + abs(durchschn) * 0.25), 2)
            anti_regeln.append({"muster": muster, "regel": regel, "gewicht": gewicht, "aktion": "verbot", "anti": True})
    return anti_regeln


def opportunity_cost_lernen(decisions):
    """P2: Misst verpasste Kaufchance (Opportunity-Cost).

    Analysiert 'halten'-Entscheidungen: Wenn die KI 'halten' sagte (nicht gekauft)
    aber der Kurs danach >+3% lief, war das eine verpasste Chance.
    Liefert Statistik für eine [Opp]-Regel.
    """
    verpasst = 0
    ges = 0
    summe = 0.0
    for d in decisions[-80:]:
        aktion = d.get("aktion", "")
        if aktion != "halten":
            continue
        ticker = d.get("ticker", "")
        if not ticker or "Risk" in ticker or ticker.startswith("DEPOT"):
            continue
        bezug = d.get("zeit", "")
        try:
            z = datetime.fromisoformat(bezug)
            if (datetime.now() - z) < timedelta(hours=4):
                continue
        except Exception:
            continue
        entw = hole_kurs_entwicklung(ticker, 4)
        if not entw:
            continue
        change = entw["change_pct"]
        ges += 1
        summe += change
        if change >= 3.0:  # verpasste Chance: +3% oder mehr
            verpasst += 1
    avg = (summe / ges) if ges else 0.0
    quote = (verpasst / ges * 100) if ges else 0.0
    return {"ges": ges, "verpasst": verpasst, "avg": round(avg, 2), "quote": round(quote, 1)}


def swap_score_berechnen(decisions):
    """Phase 2 (Prio 1 erweitert): Counterfactual-Swap-Score mit drei Typen.

    Für jede 'halten'-Position berechne Swap-Score vs. drei Alternativen:
      1. inner_portfolio_swap: bester interner Kandidat (aus Watchlist/Scan)
      2. benchmark_swap: Benchmark-ETF (SPY / Sektor-ETF)
      3. cash_reserve_swap: Cash / Geldmarkt (0% Return)

    Zeitrahmen: 4h, 1d, 1w (4h via 1h-Bars, 1d/1w via 1d-Bars).
    Liefert: {ges, swaps, avg_swap, by_type: {...}, details: [...]}
    """
    # Benchmark (SPY) 1d/1w laden
    bench_1d = bench_1w = None
    try:
        b1d = hole_kurs_entwicklung("SPY", 24)
        if b1d:
            bench_1d = b1d["change_pct"]
        b1w = hole_kurs_entwicklung("SPY", 168)  # 7d
        if b1w:
            bench_1w = b1w["change_pct"]
    except Exception:
        pass

    # Interne Top-Kandidaten approximieren: bester aus decisions mit 'kaufen'
    # und positivem Lerneffekt (vereinfacht: max change_4h unter gekauften)
    internal_best = None
    try:
        buys = [d for d in decisions if d.get("aktion") == "kaufen"
                and isinstance(d.get("lerneffekt"), (int, float)) and d["lerneffekt"] >= 1]
        if buys:
            internal_best = max(buys, key=lambda x: x.get("change_pct", 0))
    except Exception:
        pass

    # Ergebnisse pro Typ sammeln
    results = {
        "ges": 0,
        "swaps": 0,
        "avg_swap": 0.0,
        "by_type": {
            "inner_portfolio": {"ges": 0, "swaps": 0, "avg_swap": 0.0, "sum_swap": 0.0},
            "benchmark":       {"ges": 0, "swaps": 0, "avg_swap": 0.0, "sum_swap": 0.0},
            "cash_reserve":    {"ges": 0, "swaps": 0, "avg_swap": 0.0, "sum_swap": 0.0},
        },
        "details": []
    }

    for d in decisions[-150:]:
        if d.get("aktion") != "halten":
            continue
        ticker = d.get("ticker", "")
        if not ticker or "Risk" in ticker or ticker.startswith("DEPOT"):
            continue
        try:
            z = datetime.fromisoformat(d.get("zeit", ""))
            if (datetime.now() - z) < timedelta(hours=4):
                continue
        except Exception:
            continue
        eig = hole_kurs_entwicklung(ticker, 4)
        if not eig:
            continue
        eigen_ret = eig["change_pct"]
        results["ges"] += 1

        # --- 1. inner_portfolio_swap ---
        int_swap = 0.0
        if internal_best and internal_best.get("change_pct") is not None:
            int_swap = round(internal_best["change_pct"] - eigen_ret, 2)
        r = results["by_type"]["inner_portfolio"]
        r["ges"] += 1
        r["sum_swap"] += int_swap
        if int_swap >= 2.0:
            r["swaps"] += 1

        # --- 2. benchmark_swap (SPY 1d) ---
        bench_swap = 0.0
        if bench_1d is not None:
            bench_swap = round(bench_1d - eigen_ret, 2)
        r = results["by_type"]["benchmark"]
        r["ges"] += 1
        r["sum_swap"] += bench_swap
        if bench_swap >= 2.0:
            r["swaps"] += 1

        # --- 3. cash_reserve_swap (0% Return) ---
        cash_swap = round(0.0 - eigen_ret, 2)
        r = results["by_type"]["cash_reserve"]
        r["ges"] += 1
        r["sum_swap"] += cash_swap
        if cash_swap >= 2.0:
            r["swaps"] += 1

        # Details für Top-3-Swaps (beliebiger Typ)
        best_swap = max(int_swap, bench_swap, cash_swap)
        if best_swap >= 2.0 and len(results["details"]) < 5:
            results["details"].append({
                "ticker": ticker,
                "eigen_ret": round(eigen_ret, 2),
                "swap_scores": {
                    "inner_portfolio": int_swap,
                    "benchmark": bench_swap,
                    "cash_reserve": cash_swap,
                },
                "best_type": ("inner_portfolio" if int_swap == best_swap else
                              "benchmark" if bench_swap == best_swap else
                              "cash_reserve"),
                "best_swap": best_swap,
            })

        results["swaps"] += 1  # Zählt jeden Swap (vereinfacht)

    # Ø berechnen
    for typ in results["by_type"]:
        r = results["by_type"][typ]
        if r["ges"]:
            r["avg_swap"] = round(r["sum_swap"] / r["ges"], 2)

    # Gesamtdurchschnitt (Gewichteter Mittelwert aller Typen)
    total_sum = sum(r["sum_swap"] for r in results["by_type"].values())
    total_n = sum(r["ges"] for r in results["by_type"].values())
    results["avg_swap"] = round(total_sum / total_n, 2) if total_n else 0.0

    return results


def _swap_regel_vorschlag(stat):
    """Erzeugt spezifische Swap-Regeln pro Typ (falls Schwellen erreicht)."""
    regeln = []
    for typ, data in stat.get("by_type", {}).items():
        if data["ges"] >= 5 and data["swaps"] >= 2 and data["avg_swap"] >= 1.0:
            if typ == "inner_portfolio":
                muster = "[Swap] Kapital in Positionen blockiert bessere interne Kandidaten"
                regel = (f"Halte-Positionen liefen Ø {data['avg_swap']:+.1f}% schlechter "
                         f"als bester interner Kandidat. Bei schwachen Setups Kapital freigeben "
                         f"und in stärkere interne Setups umschichten.")
                kontext_regime = ["bull", "bear", "seitwaerts"]
            elif typ == "benchmark":
                muster = "[Swap] Kapital in Positionen blockiert Benchmark (SPY)"
                regel = (f"Halte-Positionen liefen Ø {data['avg_swap']:+.1f}% schlechter "
                         f"als SPY. Bei schwachen Setups in Benchmark-ETF umschichten.")
                kontext_regime = ["bear", "seitwaerts"]
            else:  # cash_reserve
                muster = "[Swap] Kapital in fallenden Positionen besser in Cash"
                regel = (f"Halte-Positionen liefen Ø {data['avg_swap']:+.1f}% schlechter "
                         f"als Cash (0%). Bei stark fallenden Titeln in Cash umschichten.")
                kontext_regime = ["bear"]
            regeln.append({
                "muster": muster,
                "regel": regel,
                "typ": "swap",
                "swap_type": typ,  # NEW: inner_portfolio | benchmark | cash_reserve
                "benchmark_ticker": "SPY" if typ == "benchmark" else None,
                "gewicht": round(min(2.0, 0.5 + data["swaps"] * 0.15), 2),
                "support_count": data["swaps"],
                "violation_count": 0,
                "avg_effect_when_applied": data["avg_swap"],
                "kontext": {"asset_klasse": [], "regime": kontext_regime, "swap_type": typ},
            })
    return regeln


def konzentrations_lernen(max_depots=4, min_anz=4):
    """Priorität 7: Konzentrations-Lernen (Portfolio-Streuung).

    Zählt für jeden Ticker, in wie vielen Depots er als offene Position liegt.
    Ticker mit >= min_anz Depots → Klumpenrisiko → Regel "[Konzentration]".

    Liefert Liste neuer Regel-Dicts (für speichere_regeln).
    """
    regeln = []
    try:
        from ki_kontext import ticker_konzentration
        # Alle Ticker aus ki_log sammeln
        log = lade_ki_log()
        tickers = set()
        for e in log:
            t = e.get("ticker")
            if t and t not in ("Risk",) and not str(t).startswith("DEPOT") and "Risk" not in str(t):
                tickers.add(t.upper())
        for t in sorted(tickers):
            anz = ticker_konzentration(t)
            if anz >= min_anz:
                muster = f"[Konzentration] {t} in {anz} Depots (>= {min_anz})"
                regeln.append({
                    "muster": muster,
                    "regel": f"{t} liegt in {anz} Depots (Klumpenrisiko). "
                             f"Käufe dieses Ticklers in weiteren Depots vermeiden, "
                             f"lieber streuen.",
                    "typ": "anti",
                    "gewicht": round(min(-1.5, -0.2 * anz), 2),
                    "support_count": anz,
                    "violation_count": 0,
                    "avg_effect_when_applied": 0.0,
                    "kontext": {"asset_klasse": [], "sektor": [], "vix_range": [0, 999],
                                "trend_4h": "", "regime": [], "min_konfidenz": 0},
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "last_seen_at": datetime.now().isoformat(),
                    "decay_lambda": 0.01,
                })
    except Exception:
        pass
    return regeln


# 01.11.2026: def-Zeile fehlte (Rumpf hing unerreichbar hinter dem return
# von konzentrations_lernen). Der Aufruf in analysiere_entscheidungen()
# scheiterte still am NameError - regel_history.json wurde nie geschrieben.
def _write_regel_snapshot(regeln):
    """P5: Schreibt einen Regel-Snapshot für die Dashboard-Evolution."""
    try:
        hist_path = os.path.join(BASE, "regel_history.json")
        history = []
        if os.path.exists(hist_path):
            try:
                with open(hist_path, encoding="utf-8") as hf:
                    history = json.load(hf)
            except Exception:
                history = []
        snapshot = {
            "zeit": datetime.now().isoformat(),
            "regeln": [{"muster": r.get("muster", ""), "gewicht": float(r.get("gewicht", 0)),
                        "anti": bool(r.get("anti") or float(r.get("gewicht", 1.0)) < 0)}
                       for r in regeln],
        }
        history.append(snapshot)
        history = history[-30:]
        with open(hist_path, "w", encoding="utf-8") as hf:
            json.dump(history, hf, ensure_ascii=False, indent=2)
    except Exception:
        pass


def analysiere_entscheidungen():
    """Analysiert KI-Entscheidungen und generiert differenzierte Lern-Notizen."""
    log = lade_ki_log()
    decisions = [e for e in log if e.get("typ") == "decision"]
    if not decisions:
        print("Keine Entscheidungen zum Analysieren.")
        return []

    # 🔍 P2: Opportunity-Cost (läuft immer, unabhängig von neu bewerteten)
    lern_notizen_oc = []
    oc = opportunity_cost_lernen(decisions)
    if oc["verpasst"] >= 2 and oc["quote"] >= 40:
        gewicht = round(min(2.0, 0.8 + 0.15 * oc["verpasst"]), 2)
        speichere_regeln([{
            "muster": "[Opp] Halt bei Aufwärts-Signal verpasst",
            "regel": (f"Bei RSI<35 ODER News-Score≥75 KAUFEN statt halten – "
                      f"{oc['verpasst']}/{oc['ges']} 'halten' liefen danach +{oc['avg']:.1f}% "
                      f"(Ø {oc['quote']:.0f}% verpasste Chancen)"),
            "gewicht": gewicht,
        }])
        lern_notizen_oc.append({
            "typ": "learned", "zeit": datetime.now().isoformat(),
            "ticker": "SYSTEM",
            "notiz": (f"💡 Opportunity-Cost: {oc['verpasst']}/{oc['ges']} 'halten'-Entscheidungen "
                      f"liefen danach im Schnitt +{oc['avg']:.1f}% → zu vorsichtig, kaufen bei klaren Signalen"),
            "kategorie": "teilfehler", "lerneffekt": None,
        })

    # 🔍 P2+: Swap/Counterfactual (Prio 1) — läuft immer
    swap_stat = swap_score_berechnen(decisions)
    swap_regeln = _swap_regel_vorschlag(swap_stat)
    if swap_regeln:
        for swap_regel in swap_regeln:
            speichere_regeln([swap_regel])
        # Zusammenfassung für Log
        by_type = swap_stat.get("by_type", {})
        details = []
        for typ, data in by_type.items():
            if data["ges"]:
                details.append(f"{typ}: {data['swaps']}/{data['ges']} swaps, Ø {data['avg_swap']:+.1f}%")
        lern_notizen_oc.append({
            "typ": "learned", "zeit": datetime.now().isoformat(),
            "ticker": "SYSTEM",
            "notiz": (f"🔄 Swap-Analyse: {swap_stat['ges']} Positionen, "
                      f"{'; '.join(details)}"),
            "kategorie": "teilfehler", "lerneffekt": None,
        })

    # Block 4: Bereits bewertete Entscheidungen → nicht doppelt bewerten.
    # Primärer Key: decision_id (eindeutig). Fallback für alte Logs: zeit.
    bewertete = set()
    for e in log:
        if e.get("typ") == "learned" and e.get("bezug"):
            bewertete.add(e["bezug"])
        # decision_id-basiertes Dedupe (robuster als nur zeit).
        # FIX: Key ohne "dec_"-Praefix - der Leser vergleicht ebenfalls
        # gegen die nackte decision_id. Altdaten aus vorigen Laeufen
        # tragen das Praefix noch, darum werden beide Formen erfasst.
        if e.get("typ") == "learned" and e.get("decision_id"):
            _did = str(e["decision_id"])
            bewertete.add(_did)
            bewertete.add("dec_" + _did)

    lern_notizen = []
    ergebnisse = []  # für KI-Bewertung
    _zeitfehler = 0  # FIX: zaehlt unparsebare Zeitstempel statt sie zu schlucken

    # Börsen-Check: Nur bewerten, wenn der Markt des Tickers gerade offen ist.
    # Über Nacht (Markt zu) gibt es keine neuen 1h-Bars → Messung wäre verfälscht.
    try:
        from boersen import ist_offen, boerse_fuer_ticker
        def markt_offen(t):
            return ist_offen(boerse_fuer_ticker(t))
    except Exception:
        def markt_offen(t):
            return True

    for d in decisions[-60:]:  # letzte 60 Entscheidungen
        # Block 4: decision_id als eindeutiger Key (Fallback: zeit für alte Logs)
        did = d.get("decision_id")
        # FIX: decision_id ist KEIN Zeitstempel. Er dient ausschliesslich
        # der Deduplizierung. Als Zeitbezug erzeugte er "dec_d_2026..."
        # und fromisoformat() warf darauf immer ValueError -> 0 gelernte
        # Entscheidungen. Der echte Zeitbezug ist das ISO-Feld "zeit".
        bezug = d.get("zeit") or ""
        if not bezug or (did and did in bewertete):
            continue
        ticker = d.get("ticker", "")
        if ticker.startswith("Risk") or ticker.startswith("DEPOT_") or "Risk" in ticker:
            continue  # Depot-Entscheidungen haben keinen Kursbezug
        aktion = d.get("aktion", "")
        if aktion not in ("kaufen", "verkaufen", "halten"):
            continue
        # Block 4: Regelstatus/Shadow/Live aus dem Audit-Trail auslesen
        angewandte = d.get("angewandte_regeln", []) or []
        regel_states = []
        for r in angewandte:
            if isinstance(r, dict):
                regel_states.append({
                    "id": r.get("id"),
                    "shadow": bool(r.get("shadow", False)),
                    "freigabe_status": r.get("freigabe_status", "nicht_freigegeben"),
                    "status": r.get("status", "unbekannt"),
                    "live_allowed": bool(r.get("live_allowed", False)),
                })
        n_shadow = sum(1 for r in regel_states if r["shadow"])
        n_freigegeben = sum(1 for r in regel_states if r["freigabe_status"] == "freigegeben")
        # Evidenz-Dämpfung: Shadow-Regeln zählen weniger als freigegebene
        shadow_anteil = (n_shadow / len(regel_states)) if regel_states else 0.0
        # Entscheidung muss alt genug sein, damit sich der Kurs bewegt hat.
        # Messung erfolgt ueber 15m/4h/1d-Bars (lerneffekt_multiskalen),
        # also ist 4h die sinnvolle Mindestwartezeit.
        try:
            z = datetime.fromisoformat(str(bezug).replace("Z", ""))
            if z.tzinfo is not None:
                z = z.replace(tzinfo=None)
            if (datetime.now() - z) < timedelta(hours=MINDESTALTER_STUNDEN):
                continue
        except Exception as _e:
            # Frueher: nackter except + continue -> Fehler unsichtbar.
            # Jetzt: zaehlen und melden, damit ein kaputtes Datumsformat
            # nicht wieder lautlos alles verschluckt.
            _zeitfehler += 1
            if _zeitfehler <= 3:
                print(f"   [ki_learning] unabhaengiges Zeitformat: {str(bezug)[:40]!r} ({type(_e).__name__})", flush=True)
            continue
        # 🕐 Zeitfenster-Fix: Bei geschlossener Börse nicht bewerten
        # (keine neuen Bars → 4h-Messung wäre der Stand VOR der Entscheidung)
        if not markt_offen(ticker):
            continue

        # 🕐 Phase 3 (S3.2): Mehrstufiges Lernsignal + Risikoadjustierung
        # Kombiniert 15m/4h/1d, normalisiert durch ATR (Volatilität)
        wert, kat, detail = lerneffekt_multiskalen(ticker, aktion)
        if wert is None:
            continue
        change = detail.get("change_4h", 0.0)
        conf = d.get("konfidenz", 0)
        grund = d.get("grund") or d.get("analyse") or ""

        # 🏭 Sektor des Tickers ermitteln
        sektor = kategorie_fuer_ticker(ticker)
        # 📰 News-Score vor der Entscheidung (max. 48h vorher)
        news_score = news_score_fuer_ticker(ticker, log)
        # 💰 Exit-Qualität bei Verkäufen: 24h-Tendenz nach dem Verkauf
        exit_24h = None
        if aktion == "verkaufen":
            exit_24h = hole_verkaeufe_24h(ticker)
        # 🕐 24h-Zusatzmessung: kurzfristig (4h) vs. mittelfristig (24h)
        # Nur wenn die Entscheidung alt genug ist (≥ 26h), sonst wäre die
        # 24h-Tendenz der Stand VOR der Entscheidung → verfälscht.
        change_24h = None
        try:
            z_bezug = datetime.fromisoformat(bezug)
            if (datetime.now() - z_bezug) >= timedelta(hours=26):
                change_24h = hole_tendenz_1d(ticker)
        except Exception:
            pass

        zusatz = []
        if sektor:
            zusatz.append(f"Sektor {sektor}")
        if news_score >= 75:
            zusatz.append(f"News-Score {news_score:.0f}")
        if exit_24h is not None:
            zusatz.append(f"Kurs 24h danach {exit_24h:+.1f}%")
        if change_24h is not None:
            zusatz.append(f"24h-Tendenz {change_24h:+.1f}%")
        zusatz_str = (" [" + ", ".join(zusatz) + "]") if zusatz else ""

        # Block 4: Regelstatus-Kontext in Notiz
        status_str = ""
        if regel_states:
            status_str = (f" [Regeln: {n_freigegeben} freigegeben, {n_shadow} shadow "
                          f"({shadow_anteil*100:.0f}% shadow)]")
        notiz = (f"{ticker}: {aktion} → Kurs {change:+.1f}% nach 4h "
                 f"(Lerneffekt {wert:+d}, {lerneffekt_label(wert)})."
                 f"{zusatz_str}{status_str} Grund: {grund[:60]}")
        # Block 4: Evidenz-Dämpfung — bei hohem Shadow-Anteil Lerneffekt schwächer
        # gewichten (Shadow-Regeln sind noch nicht validiert)
        eff_wert = wert
        if shadow_anteil > 0.5:
            eff_wert = int(round(wert * 0.6))
        lern_notizen.append({
            "typ": "learned",
            "zeit": datetime.now().isoformat(),
            "ticker": ticker,
            "notiz": notiz,
            "kategorie": kat,
            "lerneffekt": eff_wert,
            "bezug": bezug,
            "decision_id": did if did else None,  # Block 4: eindeutiger Key
            "aktion": aktion,
            "konfidenz": conf,
            "change_pct": round(change, 2),
            "change_24h": change_24h,
            "sektor": sektor,
            "regime": _aktuelles_regime(),
            "news_score": news_score,
            "exit_24h": exit_24h,
            "shadow_anteil": round(shadow_anteil, 2),
            "n_shadow": n_shadow,
            "n_freigegeben": n_freigegeben,
        })
        ergebnisse.append({
            "ticker": ticker, "aktion": aktion, "konfidenz": conf,
            "grund": grund, "change_pct": change, "lerneffekt": wert,
            "kategorie": sektor, "news_score": news_score, "exit_24h": exit_24h,
            "change_24h": change_24h,
        })

    # 🎯 Konfidenz-Kalibrierung: Statistik ohne KI-Call
    # Vergleicht Trefferquote hoher (≥80) vs. niedriger (<60) Konfidenz
    if len(ergebnisse) >= 4:
        hoch = [e for e in ergebnisse if e["konfidenz"] >= 80]
        niedrig = [e for e in ergebnisse if e["konfidenz"] < 60]
        def quote(grp):
            if not grp:
                return None
            pos = sum(1 for e in grp if e["lerneffekt"] >= 1)
            return pos / len(grp) * 100
        q_hoch, q_niedrig = quote(hoch), quote(niedrig)
        if q_hoch is not None and q_niedrig is not None and len(hoch) >= 3 and len(niedrig) >= 3:
            differenz = q_hoch - q_niedrig
            if differenz >= 10:
                kat_k = "success"
                text = (f"Konfidenz-Kalibrierung: Hohe KI-Konfidenz (≥80, n={len(hoch)}) traf in "
                        f"{q_hoch:.0f}% vs. niedrige (<60, n={len(niedrig)}) nur {q_niedrig:.0f}% "
                        f"→ hohe Konfidenz ist verlässlich (+{differenz:.0f}pp)")
            elif differenz <= -10:
                kat_k = "fehler"
                text = (f"Konfidenz-Kalibrierung: Hohe KI-Konfidenz (≥80, n={len(hoch)}) traf nur in "
                        f"{q_hoch:.0f}% vs. niedrige (<60, n={len(niedrig)}) in {q_niedrig:.0f}% "
                        f"→ hohe Konfidenz ist NICHT verlässlich ({differenz:.0f}pp)")
            else:
                kat_k = "neutral"
                text = (f"Konfidenz-Kalibrierung: Hohe (≥80) {q_hoch:.0f}% vs. niedrige (<60) "
                        f"{q_niedrig:.0f}% Trefferquote → Konfidenz sagt wenig aus")
            lern_notizen.append({
                "typ": "learned",
                "zeit": datetime.now().isoformat(),
                "ticker": "SYSTEM",
                "notiz": text,
                "kategorie": kat_k,
                "lerneffekt": None,
                "konfidenz_stat": {"hoch": len(hoch), "niedrig": len(niedrig),
                                   "q_hoch": round(q_hoch, 1), "q_niedrig": round(q_niedrig, 1)},
            })

    # 📰 News-Lernschleife: Deterministische Regel aus News-Scores
    # News ≥75 + gut → Regel verstärken; News ≥75 + schlecht → Regel schwächen
    if len(ergebnisse) >= 3:
        news_treffer = [e for e in ergebnisse if e.get("news_score", 0) >= 75]
        if news_treffer:
            pos_n = sum(1 for e in news_treffer if e["lerneffekt"] >= 1)
            neg_n = sum(1 for e in news_treffer if e["lerneffekt"] <= -1)
            gesamt_n = len(news_treffer)
            if pos_n >= 2 and pos_n >= neg_n:
                gewicht = round(min(2.0, 0.8 + 0.2 * (pos_n - neg_n)), 2)
                speichere_regeln([{
                    "muster": "[News] News-Score ≥75 vor Entscheidung",
                    "regel": f"News-Score ≥75 ist verlässlich ({pos_n}/{gesamt_n} bestätigt) – Vertrauen in News-getriebene Käufe",
                    "gewicht": gewicht,
                }])
                lern_notizen.append({
                    "typ": "learned", "zeit": datetime.now().isoformat(),
                    "ticker": "SYSTEM",
                    "notiz": f"📰 News-Lernschleife: {pos_n}/{gesamt_n} News-getriebene Entscheidungen (Score≥75) bestätigt → Regel verstärkt (G {gewicht})",
                    "kategorie": "teilsuccess", "lerneffekt": None,
                })
            elif neg_n >= 2 and neg_n > pos_n:
                gewicht = round(min(2.0, 0.8 + 0.2 * (neg_n - pos_n)), 2)
                speichere_regeln([{
                    "muster": "[News] News-Score ≥75 vor Entscheidung",
                    "regel": f"Hohe News-Scores sind irreführend ({neg_n}/{gesamt_n} widerlegt) – News-getriebene Käufe meiden",
                    "gewicht": gewicht,
                }])
                lern_notizen.append({
                    "typ": "learned", "zeit": datetime.now().isoformat(),
                    "ticker": "SYSTEM",
                    "notiz": f"📰 News-Lernschleife: {neg_n}/{gesamt_n} News-getriebene Entscheidungen (Score≥75) widerlegt → Gegen-Regel gespeichert (G {gewicht})",
                    "kategorie": "fehler", "lerneffekt": None,
                })

    # 💰 Exit-Qualität: Zu frühe Verkäufe erkennen
    if len(ergebnisse) >= 3:
        exits = [e for e in ergebnisse if e.get("exit_24h") is not None and e["exit_24h"] > 1.0]
        if len(exits) >= 2:
            durchschn = sum(e["exit_24h"] for e in exits) / len(exits)
            if durchschn >= 2.0:
                speichere_regeln([{
                    "muster": "[Exit] Verkauf bei laufendem Trend",
                    "regel": f"Verkäufe kommen zu früh – Kurs lief nach Verkauf im Schnitt {durchschn:+.1f}% weiter (n={len(exits)}). Take-Profit großzügiger setzen",
                    "gewicht": round(min(2.0, 0.7 + 0.1 * len(exits)), 2),
                }])
                lern_notizen.append({
                    "typ": "learned", "zeit": datetime.now().isoformat(),
                    "ticker": "SYSTEM",
                    "notiz": f"💰 Exit-Qualität: {len(exits)} Verkäufe mit Kurs {durchschn:+.1f}% danach → zu früh verkauft, Take-Profit-Regel gespeichert",
                    "kategorie": "teilfehler", "lerneffekt": None,
                })

    # ⚠ Gegen-Regel-Lernen (Anti-Muster): Muster, die systematisch falsch lagen
    # → fließen als [Anti]-Regeln (Verbote) in Prompts und Skill.
    if len(ergebnisse) >= 3:
        anti_regeln = anti_muster_regeln(ergebnisse)
        for ar in anti_regeln:
            lern_notizen.append({
                "typ": "learned", "zeit": datetime.now().isoformat(),
                "ticker": "SYSTEM",
                "notiz": (f"⚠ Gegen-Regel: {ar['muster']} – {ar['regel'][:80]} "
                          f"→ NICHT-Regel gespeichert (G {ar['gewicht']})"),
                "kategorie": "fehler", "lerneffekt": None,
            })
        if anti_regeln:
            speichere_regeln(anti_regeln)

    # 🔍 Deterministische Selbst-Analysen (laufen bei JEDEM Lernlauf, kein KI-Call)
    # 1) Grund-Text-Analyse: Begründungs-Muster clustern + Trefferquote
    grund_clusters = _grund_text_analyse(ergebnisse)

    # 📈 Prio 6: Multi-Timeframe-Regeln (Divergenz 15min vs 1d)
    if len(ergebnisse) >= 2:
        mtf_regeln = multi_timeframe_regel_lernen(ergebnisse)
        for mr in mtf_regeln:
            lern_notizen.append({
                "typ": "learned", "zeit": datetime.now().isoformat(),
                "ticker": "SYSTEM",
                "notiz": f"📈 Multi-Timeframe-Regel: {mr['muster']} → gespeichert (Typ {mr['typ']})",
                "kategorie": "info", "lerneffekt": None,
            })
        if mtf_regeln:
            speichere_regeln(mtf_regeln)

    # 🎯 Prio 7: Konzentrations-Lernen (Klumpenrisiko über Depots)
    try:
        konz_regeln = konzentrations_lernen()
        for kr in konz_regeln:
            lern_notizen.append({
                "typ": "learned", "zeit": datetime.now().isoformat(),
                "ticker": "SYSTEM",
                "notiz": f"🎯 Konzentrations-Regel: {kr['muster']} → gespeichert",
                "kategorie": "info", "lerneffekt": None,
            })
        if konz_regeln:
            speichere_regeln(konz_regeln)
    except Exception:
        pass
    for g in grund_clusters:
        if g["ges"] >= 5:
            q = g["quote"]
            kat = "success" if q >= 50 else ("teilsuccess" if q >= 30 else "fehler")
            lern_notizen.append({
                "typ": "learned", "zeit": datetime.now().isoformat(),
                "ticker": "SYSTEM",
                "notiz": (f"🔤 Begründungs-Muster '{g['cluster']}': {g['pos']}✓/{g['neg']}✗ "
                          f"({q:.0f}% richtig) → Muster {'verlässlich' if q >= 50 else 'unverlässlich'}"),
                "kategorie": kat, "lerneffekt": None,
            })

    # 2) Verlust-Aversion: Verhalten nach Verlusten prüfen
    va = _verlust_aversion_check(ergebnisse)
    if va.get("befund"):
        kat = "success" if "konservativer" in va["befund"] else "teilfehler"
        lern_notizen.append({
            "typ": "learned", "zeit": datetime.now().isoformat(),
            "ticker": "SYSTEM",
            "notiz": f"🎲 Verlust-Verhalten: {va['befund']}",
            "kategorie": kat, "lerneffekt": None,
        })

    # 3) Regel-Abweichungen: KI gegen eigene Regeln
    abweich = _regel_abweichungen_check(ergebnisse)
    for a in abweich:
        if a.get("abgewichen", 0) >= 2:
            typ = a.get("typ", "")
            lern_notizen.append({
                "typ": "learned", "zeit": datetime.now().isoformat(),
                "ticker": "SYSTEM",
                "notiz": (f"⚖️ Regel-Abweichung [{typ}]: '{a['regel'][:50]}' → "
                          f"{a['aktion']}: {a['befolgt']}× befolgt, {a['abgewichen']}× abgewichen"),
                "kategorie": "teilfehler", "lerneffekt": None,
            })

    # 📊 Phase 4 (S3.5): Konfidenz-Kalibrierung (Bins + Speicherung)
    konf_bins = konfidenz_kalibrierung()
    if konf_bins:
        lern_notizen.append({
            "typ": "learned", "zeit": datetime.now().isoformat(),
            "ticker": "SYSTEM",
            "notiz": (f"📊 Konfidenz-Kalibrierung aktualisiert: "
                      f"{len(konf_bins)} Bins, z.B. 80-100: "
                      f"{[b for b in konf_bins if b['bin']=='80-100']}"),
            "kategorie": "ki_bewertung", "lerneffekt": None,
        })

    # KI-Bewertung (1 Call pro Zyklus, differenzierte Regeln)
    ki_bewertung = None
    if ergebnisse:
        ki_bewertung = ki_bewerte_lernergebnisse(ergebnisse[:20])
        if ki_bewertung:
            neue_regeln = ki_bewertung.get("regeln") or []
            if neue_regeln:
                speichere_regeln(neue_regeln)
            lern_notizen.append({
                "typ": "learned",
                "zeit": datetime.now().isoformat(),
                "ticker": "SYSTEM",
                "notiz": "KI-Bewertung: " + (ki_bewertung.get("bewertung") or ""),
                "kategorie": "ki_bewertung",
                "lerneffekt": None,
                "anpassung": ki_bewertung.get("anpassung", ""),
                "regeln": neue_regeln,
            })

    # Schreibe Lern-Notizen ins Log
    if lern_notizen or lern_notizen_oc:
        log = lade_ki_log()
        log.extend(lern_notizen)
        log.extend(lern_notizen_oc)
        if len(log) > 1200:
            log = log[-1200:]
        with open(KI_LOG, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        print(f"✅ {len(lern_notizen)} Lern-Notizen geschrieben "
              f"({sum(1 for n in lern_notizen if n['kategorie'] in ('success','teilsuccess'))} bestätigt, "
              f"{sum(1 for n in lern_notizen if n['kategorie'] in ('fehler','teilfehler'))} widerlegt).")
        if ki_bewertung:
            print(f"🤖 KI-Bewertung: {ki_bewertung.get('bewertung','')[:120]}")
    else:
        print("Keine neuen Entscheidungen zum Bewerten (alle bereits gelernt).")

    # ── P5: Regel-Evolution Snapshot (immer, auch bei Re-Läufen) ──
    try:
        aktuelle = lade_regeln(max_alter_tage=365)
        _write_regel_snapshot(aktuelle)
    except Exception:
        pass

    # ── Prio 2: Lebenszyklus-Update (veraltete Regeln archivieren) ──
    try:
        from learned_rules import aktualisiere_lebenszyklus
        n_arch = aktualisiere_lebenszyklus()
        if n_arch:
            print(f"🗄️ Lebenszyklus: {n_arch} veraltete Regel(n) archiviert.")
    except Exception:
        pass

    return lern_notizen


def konfidenz_kalibrierung(max_age_h=168):
    """Phase 4 (S3.5): Konfidenz-Binning.

    Sammelt (konfidenz, lerneffekt) aus learned-Einträgen der letzten 7 Tage,
    bildet Bins (0-20, 20-40, ..., 80-100), berechnet pro Bin:
      - Trefferquote (Anteil lerneffekt>=1)
      - Ø Lerneffekt
    Schreibt konfidenz_stats.json. Liefert die Bin-Statistik zurück.

    Prio 3: Erkennt schlecht kalibrierte Bins (hohe Konfidenz, niedrige Quote)
    und erzeugt Meta-Regeln (meta_conf_cap), die die KI-Konfidenz deckeln.
    """
    try:
        log = lade_ki_log()
        cutoff = datetime.now() - timedelta(hours=max_age_h)
        daten = []
        for e in log:
            if e.get("typ") != "learned":
                continue
            le = e.get("lerneffekt")
            conf = e.get("konfidenz")
            if not isinstance(le, (int, float)) or not isinstance(conf, (int, float)):
                continue
            try:
                z = datetime.fromisoformat(e.get("zeit", ""))
                if z < cutoff:
                    continue
            except Exception:
                continue
            daten.append((conf, le))
        if not daten:
            return []
        bins = {}
        for conf, le in daten:
            b = min(100, (int(conf) // 20) * 20)
            key = f"{b}-{b+20}"
            st = bins.setdefault(key, {"n": 0, "pos": 0, "sum_le": 0.0})
            st["n"] += 1
            if le >= 1:
                st["pos"] += 1
            st["sum_le"] += le
        result = []
        for key in sorted(bins, key=lambda k: int(k.split("-")[0])):
            st = bins[key]
            result.append({
                "bin": key,
                "n": st["n"],
                "quote": round(st["pos"] / st["n"] * 100, 0) if st["n"] else 0,
                "avg_le": round(st["sum_le"] / st["n"], 2) if st["n"] else 0.0,
            })
        # Speichern
        try:
            with open(os.path.join(BASE, "konfidenz_stats.json"), "w", encoding="utf-8") as f:
                json.dump({"zeit": datetime.now().isoformat(), "bins": result}, f,
                          ensure_ascii=False, indent=2)
        except Exception:
            pass

        # ── Prio 3: Meta-Regeln für Konfidenz-Caps erzeugen ──
        _konfidenz_caps_als_regeln(result)

        return result
    except Exception:
        return []


def _konfidenz_caps_als_regeln(bins):
    """Prio 3: Erkennt überschätzte Konfidenz-Bins und schreibt Meta-Regeln.

    Logik (S3.5 + Prio 3):
      - Bin mit Untergrenze >= 60 (also 60-80, 80-100) UND Quote < 30%
        → KI überschätzt sich in diesem Bereich
      - Cap = Bin-Untergrenze (z.B. 80-100 mit Quote 0% → Cap 80)
        Die KI darf in diesem Bin max. so viel Konfidenz angeben.
      - Regel-Typ: meta_conf_cap, gewichtet nach Schwere (niedrige Quote = höheres Gewicht)
    """
    try:
        from learned_rules import lade_regeln, speichere_regeln
        regeln = lade_regeln(max_alter_tage=365)
        caps = []
        for b in bins:
            lo = int(b["bin"].split("-")[0])
            if lo >= 60 and b["n"] >= 5 and b["quote"] < 30:
                # Cap auf Bin-Untergrenze (die KI darf nicht höher als lo angeben)
                cap_wert = lo
                schwere = round((30 - b["quote"]) / 10.0, 1)  # je niedriger quote, desto haerter
                # Stabile Dedup-Key (OHNE Live-Werte quote/n -> sonst bei jedem Lauf neue Regel)
                dedup_key = f"[Meta] Konfidenz-Cap {cap_wert}"
                muster = f"{dedup_key} (Bin {b['bin']}: {int(b['quote'])}% Treffer, n={b['n']})"
                # bestehende Regel suchen (stabiler Schluessel, nicht das volatile Muster)
                ex = next((r for r in regeln if r.get("muster", "").startswith(dedup_key)), None)
                neu = {
                    "muster": muster,
                    "regel": f"KI überschätzt sich im Konfidenz-Bin {b['bin']} "
                             f"({int(b['quote'])}% Treffer bei n={b['n']}). "
                             f"Konfidenz wird auf max. {cap_wert} gedeckelt.",
                    "typ": "meta_conf_cap",
                    "gewicht": schwere,
                    "support_count": b["n"],
                    "violation_count": 0,
                    "avg_effect_when_applied": 0.0,
                    "kontext": {"asset_klasse": [], "sektor": [], "vix_range": [0, 999],
                                "trend_4h": "", "regime": [], "min_konfidenz": 0},
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "last_seen_at": datetime.now().isoformat(),
                    "decay_lambda": 0.01,
                    "conf_cap": cap_wert,
                }
                if ex:
                    ex.update({
                        "gewicht": schwere,
                        "support_count": b["n"],
                        "updated_at": datetime.now().isoformat(),
                        "last_seen_at": datetime.now().isoformat(),
                        "conf_cap": cap_wert,
                    })
                else:
                    neu["id"] = f"r_{datetime.now():%Y%m%d}_{abs(hash(muster)) % 100000}"
                    regeln.append(neu)
                caps.append(cap_wert)
        if caps:
            speichere_regeln(regeln)
    except Exception:
        pass


def exit_score_berechnen(ticker, kurs, sma20, sma50, rsi, pnl_prozent, take_profit_preis=None):
    """Priorität 4: Exit-Score — wann Verkauf trotz Trend SINNVOLL ist.

    Logik: Die Lern-Regel '[Exit] Verkauf bei laufendem Trend' zeigt:
    Verkäufe kommen zu früh (Kurs lief nach Verkauf +4.4% weiter).
    Dieser Score bremst vorzeitige Verkäufe bei intaktem Trend.

    Score (0-100):
      + Trend intakt (Kurs > SMA20 > SMA50): +40
      + P&L noch unter Take-Profit (Luft nach oben): +30
      + RSI < 70 (nicht überkauft): +20
      + Momentum positiv (Kurs > SMA20): +10

    Rückgabe: (score, begründung)
      score >= 70 → Verkauf wird zu 'halten' überschrieben (Trend läuft noch)
      score < 70  → normale KI-Entscheidung gilt
    """
    score = 0
    teile = []
    trend_intakt = (kurs > sma20 > sma50)
    if trend_intakt:
        score += 40
        teile.append("Trend intakt (+40)")
    if take_profit_preis and kurs < take_profit_preis:
        score += 30
        teile.append("unter Take-Profit (+30)")
    elif take_profit_preis is None and pnl_prozent < 15:
        score += 30
        teile.append("P&L < 15% (Luft nach oben) (+30)")
    if rsi is not None and rsi < 70:
        score += 20
        teile.append("RSI nicht überkauft (+20)")
    if kurs > sma20:
        score += 10
        teile.append("Momentum positiv (+10)")
    return score, "; ".join(teile) if teile else "kein Trend-Signal"


def exit_score_entscheidung_ueberschreiben(entscheidung, ticker, kurs, sma20, sma50, rsi,
                                           pnl_prozent, take_profit_preis=None,
                                           schwelle=70):
    """Priorität 4: Wendet Exit-Score auf eine KI-Entscheidung an.

    Wenn KI 'verkaufen' will ABER Exit-Score >= schwelle → wird zu 'halten'.
    """
    if entscheidung.get("aktion") != "verkaufen":
        return entscheidung, False
    score, beg = exit_score_berechnen(ticker, kurs, sma20, sma50, rsi, pnl_prozent, take_profit_preis)
    if score >= schwelle:
        entscheidung["aktion_original"] = "verkaufen"
        entscheidung["aktion"] = "halten"
        entscheidung["grund"] = (entscheidung.get("grund", "") or "") + \
            f" [Exit-Score {score}: Trend läuft noch → Halten statt Verkauf]"
        entscheidung["exit_score"] = score
        return entscheidung, True
    return entscheidung, False


def konfidenz_cap_aktuell():
    """Prio 3: Liefert das aktuelle minimale Konfidenz-Cap aus meta_conf_cap-Regeln.

    Return: int (z.B. 80) oder None wenn keine Caps aktiv.
    """
    try:
        from learned_rules import lade_regeln
        # FIX: nur_live=True. Ohne diesen Filter laden shadow- und
        # nicht-freigegebene Regeln mit. Verifiziert 27.09.2026:
        #   ohne nur_live: 20 Regeln, Cap 60
        #   mit    nur_live: 13 Regeln, Cap 80
        # Die Governance-Entscheidung "nicht freigegeben" muss hier
        # tatsaechlich greifen, sonst steuern abgelehnte Regeln live.
        regeln = lade_regeln(max_alter_tage=365, nur_live=True)
        caps = [r.get("conf_cap") for r in regeln
                if r.get("typ") == "meta_conf_cap" and r.get("conf_cap")]
        return min(caps) if caps else None
    except Exception:
        return None


def lade_lern_kontext():
    """Lädt Lern-Notizen + gewichtete Regeln als String für KI-Prompts."""
    notizen = lade_lern_notizen(max_age_stunden=48)
    # FIX: Parameter heisst max_alter_tage, nicht max_alter_tage.
    # Der falsche Name war ein TypeError und liess den Lernkontext leer.
    regeln = lade_regeln(max_alter_tage=7)

    parts = []
    # 1) Gewichtete Regeln (das Wichtigste zuerst)
    if regeln:
        parts.append("📌 GEWICHTETE REGELN (aus Lern-Erfahrung):")
        for r in regeln[:8]:
            g = float(r.get("gewicht", 1.0))
            anti = str(r.get("muster", "")).startswith("[Anti]")
            if anti:
                parts.append(f"  • ⚠️ VERBOT [{g:.1f}] {r.get('muster','')} → {r.get('regel','')}")
            else:
                stern = "⭐" * (2 if g >= 1.5 else 1 if g >= 1.0 else 0)
                parts.append(f"  • [{g:.1f}{stern}] {r.get('muster','')} → {r.get('regel','')}")

    # 2) Differenzierte Notizen nach Lerneffekt gruppiert
    if notizen:
        gruppen = {"success": [], "teilsuccess": [], "neutral": [], "teilfehler": [], "fehler": []}
        for n in notizen:
            if n.get("kategorie") == "ki_bewertung":
                continue
            gruppen.setdefault(n.get("kategorie", "neutral"), []).append(n)

        if gruppen["success"]:
            parts.append("\n✅ Bestätigte Entscheidungen (Muster verstärken):")
            for n in gruppen["success"][-4:]:
                parts.append(f"  • {n['notiz'][:110]}")
        if gruppen["teilsuccess"]:
            parts.append("\n🟡 Teilweise bestätigt:")
            for n in gruppen["teilsuccess"][-3:]:
                parts.append(f"  • {n['notiz'][:110]}")
        if gruppen["fehler"]:
            parts.append("\n❌ Deutlich widerlegt (meiden):")
            for n in gruppen["fehler"][-4:]:
                parts.append(f"  • {n['notiz'][:110]}")
        if gruppen["teilfehler"]:
            parts.append("\n🔻 Leicht widerlegt (vorsichtig):")
            for n in gruppen["teilfehler"][-3:]:
                parts.append(f"  • {n['notiz'][:110]}")

    # 📊 Phase 4 (S3.5): Konfidenz-Kalibrierung in den Prompt
    try:
        stats_pfad = os.path.join(BASE, "konfidenz_stats.json")
        if os.path.exists(stats_pfad):
            with open(stats_pfad, encoding="utf-8") as f:
                ks = json.load(f)
            bins = ks.get("bins", [])
            if bins:
                parts.append("\n📊 KONFIDENZ-KALIBRIERUNG (letzte 7 Tage):")
                for b in bins:
                    if b["n"] >= 3:
                        parts.append(f"  • Konfidenz {b['bin']}: {b['quote']:.0f}% Treffer, "
                                     f"Ø LE {b['avg_le']:+.1f} (n={b['n']})")
                parts.append("  → Passe deine Konfidenz so an, dass hohe Werte nur bei klaren Setups!")
    except Exception:
        pass

    return "\n".join(parts)


def statistik():
    """Trefferquote & Ø-Lerneffekt der letzten 24h fürs Dashboard."""
    notizen = lade_lern_notizen(max_age_stunden=24)
    bewertet = [n for n in notizen if isinstance(n.get("lerneffekt"), (int, float))]
    if not bewertet:
        return {"anzahl": 0, "trefferquote": None, "lerneffekt_avg": None,
                "bestätigt": 0, "widerlegt": 0, "neutral": 0}
    pos = sum(1 for n in bewertet if n["lerneffekt"] >= 1)
    neg = sum(1 for n in bewertet if n["lerneffekt"] <= -1)
    neu = sum(1 for n in bewertet if n["lerneffekt"] == 0)
    avg = sum(n["lerneffekt"] for n in bewertet) / len(bewertet)
    return {
        "anzahl": len(bewertet),
        "trefferquote": round(pos / len(bewertet) * 100, 1),
        "lerneffekt_avg": round(avg, 2),
        "bestätigt": pos, "widerlegt": neg, "neutral": neu,
    }


if __name__ == "__main__":
    print("🧠 KI-Lernmodul – differenzierte Lern-Analyse...")
    notizen = analysiere_entscheidungen()
    for n in notizen:
        le = n.get("lerneffekt")
        le_str = f"{le:+d}" if isinstance(le, (int, float)) else "—"
        print(f"  [{le_str}] {n['kategorie']}: {n['notiz'][:90]}")

    print("\n📋 Lern-Kontext für nächste Entscheidungen:")
    ctx = lade_lern_kontext()
    print(ctx[:600] if ctx else "  (keine Notizen)")

    try:
        from trader_status import update_status
        update_status("ki_learning", {"notizen": len(notizen), "statistik": statistik()})
    except Exception:
        pass

    # System-Log
    try:
        from system_log import log_eintrag
        st = statistik()
        if st["anzahl"] > 0:
            log_eintrag("ki_learning", f"Lern-Analyse: {st['anzahl']} Entscheidungen bewertet, "
                        f"Trefferquote {st['trefferquote']}%, Ø Lerneffekt {st['lerneffekt_avg']:+.2f}",
                        "ok" if st["lerneffekt_avg"] >= 0 else "warn")
        else:
            log_eintrag("ki_learning", "Lern-Analyse: keine neuen Entscheidungen", "info")
    except Exception:
        pass

