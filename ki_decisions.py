#!/usr/bin/env python3
"""KI-Trader – LLM-gestützte Trading-Entscheidungen pro Ticker.

Sammelt pro Ticker: Kurs, Trend, RSI, Position (shares/P&L), KI-bewertete News,
Marktkontext → fragt LLM (deepseek-v4-flash-free) → Entscheidung: kaufen/halten/verkaufen.
Loggt jede Entscheidung in ki_log.json (Typ 'decision').
"""

import json, os, sys, time, threading
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
KI_LOG = os.path.join(BASE, "ki_log.json")
sys.path.insert(0, BASE)


def risk_appetite_profil(v):
    """KI-Strategie-Profil aus Risiko-Appetit (0-100%).
    Steuert das KI-Verhalten (Slider im Dashboard)."""
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
                "ki_regel": "Mehr Spekulation erlaubt. Konfidenz-Schwellen moderat (>=55). Bis zu 3 neue Positionen, hoeheres Risiko-Budget."}
    return {"stufe": "sehr_aggressiv", "label": "Sehr aggressiv",
            "ki_regel": "Volle Spekulations-Freigabe. Konfidenz >=50. Aggressive Positionierung, Risiko-Budget maximal."}


# Settings-Loader (mit Fallback auf Hardcodiertes, falls settings.json fehlt)
try:
    from settings_loader import ki as _ki_set, lernen as _lern_set, bremse as _bremse_set, news_opt as _news_set
except Exception:
    def _ki_set(n, d=None): return d
    def _lern_set(n, d=None): return d
    def _bremse_set(n, d=None): return d
    def _news_set(n, d=None): return d

import strategie  # v2.20.0: zentrale Strategie-Config

# Thread-Safe KI-Log Zugriff
_ki_lock = threading.Lock()

# …Env aus Hermes-Config
for cand in [os.path.join(BASE, ".env"),
             os.path.expanduser("~/AppData/Local/hermes/.env")]:
    if os.path.exists(cand):
        with open(cand) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

# Provider wählbar via Env (gpt-4o-mini ist die stabilste Option)
API_KEY  = (os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") 
            or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENCODE_ZEN_API_KEY"))
# Wenn OPENAI Key, direkt OpenAI nutzen (kein Rate-Limit, schnell)
if os.environ.get("OPENAI_API_KEY"):
    ZEN_URL = "https://api.openai.com/v1"
    MODEL = os.environ.get("KI_MODEL", "gpt-4o-mini")
elif os.environ.get("DEEPSEEK_API_KEY"):
    ZEN_URL = "https://api.deepseek.com"
    MODEL = os.environ.get("KI_MODEL", "deepseek-chat")
else:
    ZEN_URL = os.environ.get("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1")
    MODEL = os.environ.get("KI_MODEL_ZEN", "deepseek-v4-flash-free")

QUIET = "--quiet" in sys.argv

try:
    from openai import OpenAI
except ImportError:
    print("Fehler: 'openai' nicht installiert. uv pip install openai", file=sys.stderr)
    sys.exit(1)

# ─── KI-Client ──────────────────────────────────────────────
_client = None
def get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=API_KEY, base_url=ZEN_URL)
    return _client

# Thread-Safe KI-Log Zugriff
_ki_lock = threading.Lock()

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
    """Schreibt einen Eintrag an ki_log.json (atomar + race-sicher).
    Fix 4: Vorher las die Funktion die Datei, appendete, schrieb zurueck.
    Bei gleichzeitigem Schreiben (Pipeline + Batch-Trader) kam es zu
    Read-Modify-Write-Races UND zum Vollverlust: json.load waehrend eines
    fremden Schreibvorgangs warf JSONDecodeError -> except fing auf [] ->
    ki_log geleert.
    Jetzt: atomarer Write (temp + os.replace) + Optimistic-Retry beim Lesen.
    Kein msvcrt-Lock noetig: os.replace ist atomar, eine halbgeschriebene
    Datei wird nie gelesen. Bei Parse-Fehler wird der alte Stand behalten
    (nicht geleert)."""
    import tempfile as _tf
    for attempt in range(5):
        try:
            with _ki_lock:
                # Aktuellen Stand lesen (optimistisch)
                log = []
                if os.path.exists(KI_LOG) and os.path.getsize(KI_LOG) > 0:
                    try:
                        with open(KI_LOG, encoding="utf-8") as f:
                            log = json.load(f)
                    except (json.JSONDecodeError, ValueError, OSError):
                        # Datei gerade im Schreiben eines anderen Prozesses:
                        # kurz warten und neu versuchen (nicht auf [] zurueckfallen)
                        import time as _t
                        _t.sleep(0.05 * (attempt + 1))
                        continue
                if not isinstance(log, list):
                    log = []
                log.append(eintrag)
                if len(log) > 1000:
                    log = log[-1000:]
                # Atomarer Write: temp -> os.replace (niemals halbgeschrieben)
                _dir = os.path.dirname(KI_LOG) or "."
                _tmp = os.path.join(_dir, ".ki_log_%d.tmp" % os.getpid())
                with open(_tmp, "w", encoding="utf-8") as f:
                    json.dump(log, f, ensure_ascii=False, indent=2)
                os.replace(_tmp, KI_LOG)
            return
        except Exception:
            import time as _t
            _t.sleep(0.1 * (attempt + 1))
    # Alle Retries fehlgeschlagen: Eintrag nicht verlieren
    try:
        with open(os.path.join(os.path.dirname(KI_LOG) or ".", ".ki_log_failed"),
                  "a", encoding="utf-8") as f:
            f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
    except Exception:
        pass

# ─── News für einen Ticker aus ki_log holen ─────────────────
def news_fuer_ticker(ticker, ki_log, max_std=24):
    cutoff = datetime.now() - timedelta(hours=max_std)
    treffer = []
    for e in ki_log:
        if e.get("typ") == "news" and ticker.upper() in [t.upper() for t in e.get("tickers", [])]:
            try:
                z = datetime.fromisoformat(e.get("zeit", ""))
                if z >= cutoff:
                    treffer.append(e)
            except:
                pass
    return treffer[:5]

# ─── VIX-Wert holen (mit Cache, TTL 10min — sonst 48 API-Calls pro Spec-Lauf!) ──
_VIX_CACHE = {"wert": None, "zeit": 0}
def hole_vix():
    now = time.time()
    if _VIX_CACHE["wert"] is not None and (now - _VIX_CACHE["zeit"]) < 600:
        return _VIX_CACHE["wert"]
    try:
        import yfinance as yf
        v = yf.Ticker("^VIX").history(period="5d")["Close"].iloc[-1]
        _VIX_CACHE["wert"] = round(float(v), 1)
        _VIX_CACHE["zeit"] = now
        return _VIX_CACHE["wert"]
    except:
        return _VIX_CACHE["wert"]  # bei Fehler: zuletzt bekannten Wert

# ─── KI-Entscheidung für EINEN Ticker ───────────────────────
def entscheide_ticker(ticker, name, kurs, sma20, sma50, rsi, shares, avg_price,
                       bargeld, depot_start=100, news_liste=None, markt_status="open",
                       sektor="", atr_pct=None, vol_ratio=None, depot_typ="aktien", risk=None):
    """Ruff LLM auf und bekommt kaufen/halten/verkaufen + Begründung."""
    if not API_KEY:
        return {"aktion": "halten", "konfidenz": 0, "grund": "Kein API-Key",
                "decision_id": f"d_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{ticker}_{depot_typ}_{risk if risk is not None else 'na'}",
                "depot_typ": depot_typ, "risk": risk, "ticker": ticker,
                "shadow": False, "regelstand_ref": "v_legacy", "konflikte": [],
                "prioritaetsreihenfolge": ["engine_bremse", "meta_cap", "news_swap", "exit_score", "ki"],
                "konfidenz_original": 0, "konfidenz_nach_cap": 0}

    # Trend-Text
    if kurs > sma20 > sma50:
        trend_txt = "Aufwärtstrend (Kurs > SMA20 > SMA50)"
    elif kurs < sma20 < sma50:
        trend_txt = "Abwärtstrend (Kurs < SMA20 < SMA50)"
    else:
        trend_txt = "Neutral (Kurs zwischen SMA20/SMA50)"

    # Position
    if shares > 0:
        invest = shares * avg_price
        aktuell_wert = shares * kurs
        pnl_prozent = ((kurs / avg_price) - 1) * 100
        pos_text = f"{shares:.2f} Aktien @${avg_price:.2f}, " \
                   f"P&L: ${aktuell_wert-invest:.2f} ({pnl_prozent:+.2f}%)"
    else:
        pos_text = "Keine Position"
        # 🛡 v2.16.8: Leere Spec-Depots (Cash, keine Position) explizit zum KAUFEN
        # auffordern — sonst hält die KI konservativ (wie bei den Aktien-Depots vorher).
        if bargeld >= 20:
            pos_text += f" [LEER: BITTE KAUFEN — {bargeld:.0f}$ Cash verfügbar, Ticker ist in Watchlist!]"

    # Zusatz-Kontext: Konzentration + Sektor + Fundamentals (mit Cache, kein Crash)
    kontext_block = ""
    selbst_text = ""
    try:
        from ki_kontext import kontext_block as kb, selbst_statistik_text
        kontext_block = kb(ticker, sektor=sektor)
        selbst_text = selbst_statistik_text()
    except Exception:
        pass

    # MarketSnapshot (Roadmap Punkt 5, v2.54.0): Snapshot-ID + Datenalter in KI
    snap_kontext = ""
    try:
        from market_snapshot import MarketSnapshot
        _snap = MarketSnapshot([ticker])
        snap_kontext = " " + _snap.kontext()
    except Exception:
        pass

    # ── R1: Gelernte Regeln laden (Top-N nach effektiv_gewicht) ──
    regel_text = ""
    angewandte_regeln = []
    try:
        from learned_rules import lade_live_regeln, is_live_allowed
        _alle_geladen = lade_live_regeln()  # Block 3: nur live-freigegebene
        regeln = _alle_geladen[:12]  # Top-12 nach Decay-gewichtetem Gewicht
        for r in regeln:
            muster = r.get("muster", "")
            ew = r.get("effektiv_gewicht", r.get("gewicht", 0))
            typ = r.get("typ", "positiv")
            if typ in ("anti", "swap") or ew < 0:
                prefix = "VORSICHT/ABWÄGEN"
            elif typ == "meta_conf_cap":
                prefix = "META-CAP"
            else:
                prefix = "BEFOLGEN"
            regel_text += f"  [{prefix}] {muster} (eff.Gewicht {ew:+.2f})\n"
            angewandte_regeln.append({
                "id": r.get("id", f"r_{abs(hash(muster))%100000:05d}"),
                "muster": muster, "typ": typ,
                "gewicht": r.get("gewicht", 0), "effektiv_gewicht": ew,
                "shadow": bool(r.get("shadow", False)),
                "live_allowed": bool(is_live_allowed(r)),
                "freigabe_status": r.get("freigabe_status", "nicht_freigegeben"),
                "status": r.get("status", "stabil"),
                "prioritaet": 1 if typ in ("anti", "swap") else 2,
                "wirkung": "gewichtung" if typ in ("anti", "swap") else "befolgen",
                "durchgesetzt": False,
            })
    except Exception:
        pass

    pnl_prozent = ((kurs / avg_price) - 1) * 100 if avg_price > 0 else 0

    depot_wert = bargeld + shares * kurs
    depot_rendite = ((depot_wert / depot_start) - 1) * 100 if depot_start > 0 else 0

    # News (R4: Einmal-Injektion als kompakte Score-Liste, nicht doppelter Fließtext)
    # Der News-Score ist bereits in news_by_ticker (ki_news-KI-Bewertung) vorhanden.
    # Hier nur verdichtete Liste: Titel + Score, keine Roh-Repetition.
    news_text = ""
    if news_liste:
        for n in news_liste[:5]:  # max 5 relevante, bereits nach Relevanz sortiert
            s = n.get("score", 50)
            news_text += f"  • [{s}] {n.get('title','?')[:70]}\n"

    # Prompt
    prompt = f"""Du bist ein KI-Trading-Assistent für ein Paper-Trading-System.
Analysiere die folgenden Daten und entscheide: KAUFEN, HALTEN oder VERKAUFEN.

TICKER: {ticker} ({name})
KURS: ${kurs:.2f}
TREND: {trend_txt}
RSI (14): {rsi:.1f}
VIX: {hole_vix() or 'unbekannt'}
MARKT: {markt_status}
{('VOLATILITÄT (ATR): ' + str(atr_pct) + '%') if atr_pct is not None else ''}
{('VOLUMEN-RATIO (heute/20d-Schnitt): ' + str(vol_ratio) + 'x') if vol_ratio is not None else ''}

POSITION: {pos_text}
BARGEHLD: ${bargeld:.2f}
DEPOT-WERT: ${depot_wert:.2f} (Rendite {depot_rendite:+.2f}%)

KONTEXT:
{kontext_block if kontext_block else "  Keine Zusatz-Infos"}
{selbst_text if selbst_text else ""}
{snap_kontext if snap_kontext else ""}

GELERNTE REGELN (aus bisherigen Trades, nach Stärke sortiert):
{regel_text if regel_text else "  Keine bisher"}

HINWEIS ZU DEN REGELN: Markierte [VORSICHT/ABWÄGEN] Regeln sind historische Warnsignale,
KEINE harten Verbote. Du darfst bei einem KLAREN Aufwärtssignal (RSI nicht überkauft,
Kurs > SMA20 > SMA50, positive News) trotzdem KAUFEN – aber nur mit hoher Konfidenz (≥60).
Bei [BEFOLGEN]-Regeln folge ihnen. Die FINALE Entscheidung (kaufen/halten/verkaufen)
triffst DU auf Basis aller Daten.

AKTUELLE NEWS:
{news_text if news_text else "  Keine"}

STRATEGIE_HINWEISE (Diversifikation, keine harten Verbote):
{strategie.STRATEGIE_HINWEISE}

WICHTIG: Antworte NUR mit JSON KEINEN anderen Text. Keine Denkprozesse.
Format: {{"ticker": "{ticker}", "aktion": "kaufen", "konfidenz": 75, "grund": "kurze Begründung"}}"""
    try:
        from ki_provider import call_ki, ki_faehig
        if not ki_faehig():
            return {"aktion": "halten", "konfidenz": 0, "grund": "Kein API-Key",
                    "decision_id": f"d_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{ticker}_{depot_typ}_{risk if risk is not None else 'na'}",
                    "depot_typ": depot_typ, "risk": risk, "ticker": ticker,
                    "shadow": False, "regelstand_ref": "v_legacy", "konflikte": [],
                    "provider": "none", "fallback": True}
        # Settings: KI-Temperatur (Default 0.1)
        # P3: Risiko-Appetit aus config.json laden (Slider im Dashboard)
        try:
            import os as _os
            _cf = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "config.json")
            with open(_cf) as _f:
                _cfg = json.load(_f)
            _ra = int(_cfg.get("risk_appetite", 50))
        except Exception:
            _ra = 50
        _ra_label = "sehr konservativ" if _ra < 25 else "konservativ" if _ra < 45 else "ausgewogen" if _ra < 60 else "aggressiv" if _ra < 80 else "sehr aggressiv"
        # KI-Strategie-Profil (2026-08-11): konkrete Handlungsregel statt vager Hinweis
        _prof = risk_appetite_profil(_ra)
        _ra_hinweis = (
            f"RISIKO-APPETIT DES USERS: {_ra}% ({_ra_label}).\n"
            f"STRATEGIE-REGEL (verbindlich): {_prof['ki_regel']}\n"
            f"Einzelne Setup-Qualität schlaegt im Zweifel den Rahmen, aber halte dich "
            f"innerhalb der Positions-/Konfidenz-Grenzen des Profils."
        )
        temp = _ki_set("ki_temperatur", 0.1)
        raus, _provider = call_ki(
            [
                {"role": "system", "content": "Du antwortest NUR mit JSON. Kein Denken, keine Erklärung, nur das JSON-Objekt.\n\n" + _ra_hinweis},
                {"role": "user", "content": prompt}
            ],
            temperature=temp,
            max_tokens=1024,  # 512 war zu klein → JSON abgeschnitten
        )
        if not raus:
            return {"aktion": "halten", "konfidenz": 0, "grund": "KI-Call fehlgeschlagen (alle Provider)",
                    "decision_id": f"d_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{ticker}_{depot_typ}_{risk if risk is not None else 'na'}",
                    "depot_typ": depot_typ, "risk": risk, "ticker": ticker,
                    "provider": _provider or "unknown", "fallback": True,
                    "shadow": False, "regelstand_ref": "v_legacy", "konflikte": [],
                    "prioritaetsreihenfolge": ["engine_bremse", "meta_cap", "news_swap", "exit_score", "ki"],
                    "konfidenz_original": 0, "konfidenz_nach_cap": 0}

        # JSON extrahieren
        start = raus.find("{")
        end = raus.rfind("}") + 1
        if start >= 0 and end > 0:
            raus = raus[start:end]
        try:
            entscheidung = json.loads(raus)
        except (json.JSONDecodeError, ValueError):
            # Bug 2: ungültiges JSON (z.B. HTML-Fehler, "I can't help") -> 1x Retry
            # mit strikterem Prompt, dann sauberer Fallback (KEIN Blindflug, KEIN Crash)
            if not QUIET:
                print(f"   ⚠ {ticker}: KI-JSON ungültig, Retry...", flush=True)
            try:
                raus2, _ = call_ki(
                    [
                        {"role": "system", "content": "Antworte AUSSCHLIESSLICH mit einem einzigen gültigen JSON-Objekt. Kein Text davor/nachher. Format: {\"aktion\":\"kaufen|halten|verkaufen\",\"konfidenz\":0-100,\"grund\":\"...\"}"},
                        {"role": "user", "content": prompt + "\n\nAntworte NUR mit JSON, keine Erklärung."},
                    ],
                    temperature=temp, max_tokens=512,
                )
                s2 = raus2.find("{"); e2 = raus2.rfind("}") + 1
                if s2 >= 0 and e2 > 0:
                    entscheidung = json.loads(raus2[s2:e2])
                else:
                    raise json.JSONDecodeError("retry failed", "", 0)
            except Exception as e:
                # Fix 3: Parse-Fehler sichtbar machen (statt stillem pass)
                try:
                    schreibe_ki_log({
                        "zeit": datetime.now().isoformat(),
                        "typ": "error",
                        "ticker": ticker,
                        "depot_typ": depot_typ,
                        "fehler": "KI-Antwort nicht parsebar (Retry fehlgeschlagen)",
                        "detail": str(e)[:200],
                        "fallback": "halten (konfidenz 50)",
                    })
                except Exception:
                    pass
                # Sauberer Fallback: halte, aber mit echter (nicht 0) Konfidenz,
                # damit ausführen() nicht als "unsicher" abbricht und kein Crash entsteht
                return {"aktion": "halten", "konfidenz": 50,
                        "grund": "KI-Antwort nicht parsebar (Retry fehlgeschlagen) – halte sicher",
                        "decision_id": f"d_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{ticker}_{depot_typ}_{risk if risk is not None else 'na'}",
                        "depot_typ": depot_typ, "risk": risk, "ticker": ticker,
                        "shadow": False, "regelstand_ref": "v_legacy", "konflikte": [],
                        "prioritaetsreihenfolge": ["engine_bremse", "meta_cap", "news_swap", "exit_score", "ki"],
                        "konfidenz_original": 0, "konfidenz_nach_cap": 0}

        # ── Prio 3: Konfidenz-Cap anwenden ──
        try:
            from ki_learning import konfidenz_cap_aktuell
            # Settings: manueller Cap überschreibt auto-Lernen (None = auto)
            cap_setting = _ki_set("konfidenz_cap", None)
            cap = cap_setting if cap_setting is not None else konfidenz_cap_aktuell()
            if cap is not None:
                ki_conf = float(entscheidung.get("konfidenz", 50))
                if ki_conf > cap:
                    entscheidung["konfidenz_original"] = ki_conf
                    entscheidung["konfidenz"] = cap
                    entscheidung["cap_grund"] = f"KI-Konfidenz {ki_conf} > Cap {cap} (Selbstüberschätzung)"
                    entscheidung["grund"] = (entscheidung.get("grund", "") or "") \
                        + f" [Konfidenz auf {cap} gedeckelt: KI überschätzt sich in hohen Bereichen]"
        except Exception:
            pass

        decision = {
            "typ": "decision",
            "zeit": datetime.now().isoformat(),
            "ticker": ticker,
            "aktion": entscheidung.get("aktion", "halten"),
            "konfidenz": entscheidung.get("konfidenz", 50),
            "grund": entscheidung.get("grund", ""),
            "menge": entscheidung.get("menge", "voll"),
            "ziel_kurs": entscheidung.get("ziel_kurs"),
            "kurs": round(kurs, 2),
            "rsi": round(rsi, 1),
            "trend": trend_txt,
            "p_pnl": round(pnl_prozent, 2),
            "depot_rendite": round(depot_rendite, 2),
            "angewandte_regeln": angewandte_regeln,  # R1: Audit-Trail welche Regeln gewirkt haben
            # ── Block1: Audit-Trail (voller Kontext) ──
            "decision_id": f"d_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{ticker}_{depot_typ}_{risk if risk is not None else 'na'}",
            "provider": _provider or "unknown",  # welcher Free-Tier-Provider entschied
            "fallback": False,  # echte KI-Entscheidung (kein Crash-Fallback)
            "depot_typ": depot_typ,
            "risk": risk,
            "quelle": "ki_decisions.entscheide_ticker",
            "regime": (markt_status or "open"),
            "rohdaten": {
                "kurs": round(kurs, 2), "sma20": round(sma20, 2) if sma20 else None,
                "sma50": round(sma50, 2) if sma50 else None, "rsi": round(rsi, 1) if rsi else None,
                "atr_pct": round(atr_pct, 2) if atr_pct is not None else None,
                "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
                "vix": hole_vix(), "trend": trend_txt, "depot_rendite": round(depot_rendite, 2)
            },
            "indikatoren": [f"SMA20>{sma20:.1f}" if sma20 else "",
                            f"SMA50>{sma50:.1f}" if sma50 else "",
                            f"RSI{rsi:.0f}" if rsi else "",
                            f"ATR{atr_pct:.1f}%" if atr_pct is not None else ""],
            "news_score": (news_liste[0].get("score") if news_liste else None) if isinstance(news_liste, list) else None,
            "regelstand_ref": "v_live",  # Block 3: Live-Pfad nutzt freigegebene Regeln
            "konflikte": [],  # wird nach Cap/Exit/News-Swap unten gefuellt
            "prioritaetsreihenfolge": ["engine_bremse", "meta_cap", "news_swap", "exit_score", "ki"],
            "konfidenz_original": entscheidung.get("konfidenz_original", entscheidung.get("konfidenz", 50)),
            "konfidenz_nach_cap": entscheidung.get("konfidenz", 50),
            "konfidenz_cap": cap if 'cap' in dir() else None,
            "erwarteter_ausgang": "unbekannt",
            "shadow": False,  # Vorbereitet fuer spaetere Shadow/Live-Trennung
            "regelstatus_beim_entscheid": {r.get("id", r.get("muster", "?")): "stabil" for r in regeln} if 'regeln' in dir() else {}
        }

        # ── Prio 4: Exit-Score (Verkauf trotz Trend bremsen) ──
        try:
            from ki_learning import exit_score_entscheidung_ueberschreiben
            if shares > 0:  # nur bei bestehender Position
                decision, _ueberschrieben = exit_score_entscheidung_ueberschreiben(
                    decision, ticker, kurs, sma20, sma50, rsi, pnl_prozent,
                    take_profit_preis=None
                )
        except Exception:
            pass

        # ── Prio 5: News-Swap (News-Impact triggert Umschichtung) ──
        # R3: Explizite Konflikt-Priorität. Governance-Reihenfolge:
        #   Engine-Bremsen (hart) > Meta-Cap > News-Swap (News>=75) > Exit-Score > KI
        # Bei Widerspruch (Exit-Score=halten vs News-Swap=verkaufen) GEWINNT News-Swap,
        # da konkreter News-Impact härtere Evidenz ist als Trend-Proxy. Konflikt wird geloggt.
        try:
            from ki_learning import news_swap_entscheidung_ueberschreiben, news_score_fuer_ticker
            if shares > 0:  # nur bei bestehender Position
                ns = news_score_fuer_ticker(ticker, lade_ki_log(), max_std=48)
                ns_min = _ki_set("news_swap_min_score", 75)
                if ns >= ns_min:
                    if decision.get("aktion_original") == "verkaufen":
                        # Exit-Score hatte bereits zu "halten" überschrieben → Konflikt
                        decision["regel_konflikt"] = (
                            f"Exit-Score(halten) vs News-Swap(verkaufen): "
                            f"News-Swap gewinnt (Impact {ns}>=75, härtere Evidenz)"
                        )
                    decision, _swapped = news_swap_entscheidung_ueberschreiben(
                        decision, ticker, pnl_prozent, ns, benchmark_ret=0.0
                    )
        except Exception:
            pass

        # Block1: Konflikte aus regel_konflikt nachtragen
        if decision.get("regel_konflikt"):
            decision["konflikte"] = [decision["regel_konflikt"]]
        schreibe_ki_log(decision)
        if not QUIET:
            sym = "🟢" if decision["aktion"] == "kaufen" else ("🔴" if decision["aktion"] == "verkaufen" else "⚪")
            print(f"  {sym} KI[{ticker}]: {decision['aktion']} (K:{decision['konfidenz']}) – {decision['grund'][:60]}", flush=True)
        return decision

    except Exception as e:
        if not QUIET:
            print(f"  ⚠ KI[{ticker}] Fehler: {e}", file=sys.stderr, flush=True)
        return {"aktion": "halten", "konfidenz": 0, "grund": f"KI-Fehler: {e}", "ticker": ticker,
                "decision_id": f"d_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{ticker}_{depot_typ}_{risk if risk is not None else 'na'}",
                "depot_typ": depot_typ, "risk": risk, "shadow": False,
                "regelstand_ref": "v_legacy", "konflikte": [], "konfidenz_original": 0, "konfidenz_nach_cap": 0}

# ─── Batch für Spec-Trader (parallel) ───────────────────────
def entscheide_spec_batch(ticker_data_list, max_workers=1):
    """Bekommt Liste von dicts mit Ticker-Daten, ruft KI SEQUENZIELL auf.

    P2-Fix (2026-08-10): max_workers=1 (kein Parallel-Burst mehr).
    Free-Tier-Provider (openrouter/nous) drosseln bei 3 gleichzeitigen Calls
    -> ki_cooldown sperrte alle -> 9/20 Spec FAIL_FAST. Sequenziell + 1.5s
    Delay vermeidet das Rate-Limit.
    """
    ki_log = lade_ki_log()
    ergebnisse = [None] * len(ticker_data_list)
    import time
    for i, td in enumerate(ticker_data_list):
        try:
            news = news_fuer_ticker(td["ticker"], ki_log)
            ergebnisse[i] = entscheide_ticker(
                td["ticker"], td.get("name", ""),
                td["kurs"], td["sma20"], td["sma50"],
                td["rsi"], td["shares"], td["avg_price"],
                td["bargeld"], td.get("start", 100),
                news_liste=news, markt_status=td.get("markt", "open"),
                sektor=td.get("sektor", ""),
                atr_pct=td.get("atr_pct"),
                vol_ratio=td.get("vol_ratio"),
                risk=td.get("risk", 20),
            )
        except Exception as e:
            ergebnisse[i] = {"aktion": "halten", "fehler": str(e)[:80]}
        if i < len(ticker_data_list) - 1:
            time.sleep(1.5)  # Rate-Limit-Schutz
    return ergebnisse

# ─── Depot-Entscheidung für Batch-Trader (Aktien) ────────────
def entscheide_aktien_depot(depot, kandidaten, markt_status="open"):
    """KI-Entscheidung für ein Aktien-Depot (mehrere Positionen + Kandidaten).
    
    depot: dict mit ticker, shares, avg_price, bargeld, risk, start, name
    kandidaten: liste von dicts mit ticker, preis, score, tier
    Returns: dict mit aktionen (buy/sell) und ki_letzte
    """
    if not API_KEY:
        return {"aktionen": [], "ki_letzte": None}
    
    # Depot-Info
    pos_liste = []
    for t, pos in depot.get("positions", {}).items():
        if pos.get("shares", 0) > 0:
            preis = hole_kurs_fuer(t)
            pnl = ((preis / pos["avg_price"]) - 1) * 100 if pos["avg_price"] > 0 else 0
            pos_liste.append(f"{t}: {pos['shares']:.2f}st @${pos['avg_price']:.2f} "
                           f"(Kurs ${preis:.2f}, P&L {pnl:+.2f}%)")
    
    depot_wert = depot.get("bargeld", 0)
    for t, pos in depot.get("positions", {}).items():
        if pos.get("shares", 0) > 0:
            depot_wert += pos["shares"] * hole_kurs_fuer(t)
    
    kandidaten_liste = []
    for k in (kandidaten or [])[:8]:
        # Konzentration: in wie vielen Depots liegt der Kandidat schon?
        konz = ""
        try:
            from ki_kontext import ticker_konzentration
            n = ticker_konzentration(k['ticker'])
            if n >= 2:
                konz = f" [⚠ schon in {n} Depots]" if n >= 4 else f" [in {n} Depots]"
        except Exception:
            pass
        atr = k.get("atr", 0) or 0
        vol = k.get("vol_ratio", 1) or 1
        kandidaten_liste.append(f"  {k['ticker']} ${k['preis']:.2f} Score:{k.get('score',0):.0f} Tier:{k.get('tier',2)} ATR:{atr:.1f}% Vol:{vol:.1f}x{konz}")
    
    # Markt- und Positions-News aus KI-Log holen
    ki_log = lade_ki_log()
    news_text = ""
    for t in depot.get("positions", {}):
        news = news_fuer_ticker(t, ki_log)
        for n in news:
            s = n.get("score", 50)
            stern = "⭐" * (s // 30 + 1) if s > 0 else ""
            news_text += f"  • {n.get('title','?')} Score {s} {stern}\n"
    for k in (kandidaten or [])[:3]:
        news = news_fuer_ticker(k["ticker"], ki_log)
        for n in news:
            s = n.get("score", 50)
            stern = "⭐" * (s // 30 + 1) if s > 0 else ""
            news_text += f"  • {n.get('title','?')} Score {s} {stern}\n"
    
    # Lern-Kontext aus vorherigen KI-Entscheidungen
    learning_text = ""
    try:
        from ki_learning import lade_lern_kontext
        learning_text = lade_lern_kontext()
    except:
        pass
    
    # Marktkontext
    vix = hole_vix()
    vix_str = str(vix) if vix else "unbekannt"

    # Selbst-Statistik (wie gut lag die KI zuletzt?)
    selbst_text = ""
    try:
        from ki_kontext import selbst_statistik_text
        selbst_text = selbst_statistik_text()
    except Exception:
        pass

    prompt = f"""Du bist ein KI-Trading-Assistent für ein Aktien-Depot (Paper-Trading).
Analysiere Depot und Kandidaten. Entscheide pro Position/Kandidat: KAUFEN oder VERKAUFEN.

DEPOT: Risk {depot.get('risk','?')} | Cash: ${depot.get('bargeld',0):.2f} | Wert: ${depot_wert:.2f}
VIX: {vix_str} | Markt: {markt_status}
{selbst_text if selbst_text else ""}

AKTUELLE POSITIONEN:
{chr(10).join(pos_liste) if pos_liste else "  Keine Positionen"}

TOP-KANDIDATEN (zum Kauf):
{chr(10).join(kandidaten_liste) if kandidaten_liste else "  Keine"}

NEWS FÜR POSITIONEN/KANDIDATEN:
{news_text if news_text else "  Keine"}

LERN-KONTEXT (aus vorherigen Entscheidungen):
{learning_text if learning_text else "  Noch keine Lern-Notizen"}

REGELN:
- Max {depot.get('max_pos', 3)} Positionen gleichzeitig
- VIX > 25: reduzieren
- Keine Penny-Stocks (Preis < $1)

Antworte NUR mit JSON:
{{"aktionen": [
  {{"ticker": "...", "aktion": "kaufen"|"verkaufen"|"halten", "menge": "voll"|"teil", "grund": "..."}},
  ...
], "konfidenz": 0-100, "analyse": "kurze Zusammenfassung"}}
"""
    try:
        from ki_provider import call_ki, ki_faehig
        if not ki_faehig():
            return {"aktionen": [], "konfidenz": 0, "analyse": "Kein API-Key"}
        raus, _provider = call_ki(
            [
                {"role": "system", "content": "Du antwortest NUR mit JSON. Kein Denken, keine Erklärung, nur das JSON-Objekt."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=1024,  # 512 war zu klein → JSON abgeschnitten
        )
        if not raus:
            return {"aktionen": [], "konfidenz": 0, "analyse": "KI-Call fehlgeschlagen (alle Provider)"}

        # Find erstes und letztes JSON-Objekt
        start = raus.find("{")
        if start < 0:
            start = raus.find("[")
        end = raus.rfind("}") + 1
        if start >= 0 and end > start:
            raus = raus[start:end]
        # Bei mehreren JSON-Objekten nimm das erste
        if raus.startswith("{") and raus.count("{") > 1:
            # Zähle Klammern um das erste Objekt zu finden
            tiefe = 0
            for i, c in enumerate(raus):
                if c == "{":
                    tiefe += 1
                elif c == "}":
                    tiefe -= 1
                    if tiefe == 0:
                        raus = raus[:i+1]
                        break
        entscheidung = json.loads(raus)
        
        ki_letzte = {
            "typ": "decision",
            "zeit": datetime.now().isoformat(),
            "aktion": entscheidung.get("analyse", "")[:60] or "KI-Entscheidung",
            "konfidenz": entscheidung.get("konfidenz", 50),
            "analyse": entscheidung.get("analyse", ""),
            "ticker": f"Risk {depot.get('risk','?')}",
        }
        schreibe_ki_log(ki_letzte)
        
        # Aktionen in das Format konvertieren, das engine.py erwartet
        aktionen = []
        for a in entscheidung.get("aktionen", []):
            ticker = a.get("ticker", "")
            akt = a.get("aktion", "halten")
            grund = a.get("grund", "KI-Entscheidung")
            if akt == "kaufen":
                # Finde den Kandidaten
                cand = next((k for k in (kandidaten or []) if k["ticker"] == ticker), None)
                if cand and cand.get("preis", 0) > 0:
                    menge_faktor = 1.0 if a.get("menge") == "voll" else 0.5
                    budget = depot.get("bargeld", 0) * menge_faktor
                    menge = budget / cand["preis"]
                    aktionen.append({
                        "typ": "kaufen", "ticker": ticker,
                        "menge": round(menge, 4), "preis": cand["preis"],
                        "grund": f"🤖 KI: {grund[:50]}",
                        "tier": cand.get("tier", 2),
                    })
            elif akt == "verkaufen":
                pos = depot.get("positions", {}).get(ticker, {})
                if pos.get("shares", 0) > 0:
                    menge_faktor = 1.0 if a.get("menge") == "voll" else 0.5
                    preis = hole_kurs_fuer(ticker)
                    aktionen.append({
                        "typ": "verkaufen", "ticker": ticker,
                        "menge": round(pos["shares"] * menge_faktor, 4),
                        "preis": preis,
                        "grund": f"🤖 KI: {grund[:50]}",
                    })
        
        if not QUIET:
            print(f"   🤖 KI[Risk {depot.get('risk','?')}]: {len(aktionen)} Aktionen (K:{entscheidung.get('konfidenz', 0)})", flush=True)
        return {"aktionen": aktionen, "ki_letzte": ki_letzte}
    
    except Exception as e:
        if not QUIET:
            print(f"   ⚠ KI[Risk {depot.get('risk','?')}] Fehler: {e}", file=sys.stderr, flush=True)
        return {"aktionen": [], "ki_letzte": None}


def hole_kurs_fuer(ticker):
    """Holt aktuellen Kurs für einen Ticker (Super-Mix Fallback, v2.16.8).

    Delegiert an marktdaten.hole_kurs() — yfinance → Finnhub → TwelveData
    → AlphaVantage. Löst das yfinance-Rate-Limit-Problem (Kurs 0 → Crash).
    """
    try:
        from marktdaten import hole_kurs
        return hole_kurs(ticker)
    except Exception:
        # Notfall-Fallback: Original yfinance
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            hist = t.history(period="2d")
            if len(hist) > 0 and "Close" in hist:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    # Test: Ein Ticker
    test = entscheide_ticker(
        "AAPL", "Apple Inc",
        kurs=245.0, sma20=240.0, sma50=235.0,
        rsi=62, shares=5, avg_price=220.0,
        bargeld=45.0, depot_start=100,
    )
    print(json.dumps(test, indent=2, ensure_ascii=False))
