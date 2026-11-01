#!/usr/bin/env python3
"""
Engine – Kernlogik für Trading.
Tier-basiertes Scoring + Random-Auswahl für Diversifikation.
"""
import json, time, os, math, sys, hashlib, random
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import numpy as np
import mtlog  # Zentrales Logsystem (Run-Kontext, Rotation)
import handelskosten  # 01.11.2026: Gebuehren + Slippage im Paper-Trading

# Ticker→Tier Lookup wird vom risk_profile importiert
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".scan_cache.json")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Settings-Loader (Engine-Bremsen)
try:
    sys.path.insert(0, BASE_DIR)
    from settings_loader import bremse as _bremse_set
except Exception:
    def _bremse_set(n, d=None): return d

import strategie  # v2.20.0: zentrale Strategie-Config (Single Source of Truth)

# VERDRAHTUNG 2026-09-27 (Rebuild Risiko-Controller):
# risk_controller.py ist die EINFACHE Risikostuerung. engine.py bezieht
# Positionen-Groesse, Stop-Loss, Take-Profit, Tier-Gate und Drawdown-Lock
# jetzt von dort statt aus params-Defaults. Die frueher an mehreren Stellen
# hartkodierten Bremsen sind damit entfernt.
from risk_controller import (
    params as rc_params,
    pruefe_und_bremse as rc_pruefe,
    max_betrag as rc_max_betrag,
    drawdown_pct_von as rc_drawdown_pct,
)

# BUGFIX 2026-09-27 (Baseline 8da05cd): QUIET war in engine.py an 6 Stellen
# benutzt, aber nirgends modulweit definiert. Jeder Aufruf von scan_markt()
# endete mit NameError - sobald yfinance leer oder rate-limited lieferte,
# starben der komplette Batch- UND ETF-Lauf (281 Abbrueche im Log).
# Definition analog zu etf_trader.py:17 und batch_trader.py:66.
QUIET = "--quiet" in sys.argv

def max_depot_pro_ticker():
    return int(_bremse_set("max_depot_pro_ticker", 4))

def drawdown_sperre_prozent():
    return float(_bremse_set("drawdown_sperre_prozent", 30))

# 30.09.2026: Ticker -> Tier aus der Yahoo-Aktien-Datenbasis,
# einmal berechnet und dann wiederverwendet.
_AKT_TIER_CACHE = {}


def ticker_zu_tier():
    """Ticker -> Tier: alte Handliste plus Yahoo-Ableitung.

    Die 686er-Liste aus risk_profile deckt nur 26 Prozent der
    aktuellen Yahoo-Kandidaten ab (37 von 143). Die uebrigen
    bekamen den Default-Tier 2, und engine.bewerte() verwarf sie
    bei den meisten Risikostufen, weil allowed_tiers dort nicht 2
    enthaelt. Beispiel Risk 10: 19 Kandidaten, 12 davon ohne
    Tier, erlaubt sind [0, 1, 4] - Ergebnis 0 Titel.

    Deshalb wird die Tabelle aus der Yahoo-Datenbasis ergaenzt.
    Die alte Liste bleibt und hat Vorrang: sie ist gepflegt, die
    Ableitung ist es nicht. Nur Titel, die dort fehlen, bekommen
    ihr Tier aus beta, branche, ma_cap und volumen.
    """
    tabelle = {}
    try:
        sys.path.insert(0, BASE_DIR)
        from risk_profile import TICKER_TO_TIER
        tabelle.update(TICKER_TO_TIER)
    except Exception:
        pass
    if not _AKT_TIER_CACHE:
        try:
            import aktien_tier
            _t, _z = aktien_tier.baue_tier_tabelle(
                os.path.join(BASE_DIR, "screener_aktien_beta.json"))
            _AKT_TIER_CACHE.update(_t)
        except Exception:
            pass
    for _tk, _tr in _AKT_TIER_CACHE.items():
        tabelle.setdefault(_tk, _tr)
    return tabelle

# ─── Depot-Klasse ────────────────────────────────────────────
class Depot:
    def __init__(self, start_wert=100, risk=50, depot_pfad=None):
            self.start_wert = start_wert
            self.risk = risk
            self.bargeld = start_wert
            self.positions = {}        # {ticker: {"shares": x, "avg_price": y, "stop_loss": z, "take_profit": w}}
            self.historie = []
            self.trades = []  # Immer Liste
            self.ki_letzte = None
            # BUG-FIX: Felder, die die Klasse nicht kennt (zum
            # Beispiel depot["empfehlung"] mit erlaubte_ticker und
            # min_score), sind beim Speichern verloren gegangen und
            # wurden beim naechsten Trade ueberschrieben. Deshalb
            # werden alle unbekannten Schluessel hier gesammelt und
            # wieder zurueckgeschrieben.
            self.zusatz = {}
            self.depot_pfad = depot_pfad or os.path.join(BASE_DIR, f"depot_{risk:03d}.json")

    def wert(self):
        # 01.11.2026: hole_kurs() liefert bei einem Fehler 0.0 statt einer
        # Exception. Die Position zaehlte dann mit 0 - der Depotwert brach
        # rechnerisch ein und konnte die Drawdown-Sperre ausloesen. Ohne
        # gueltigen Kurs gilt jetzt der Einstandspreis (wie bei Exceptions).
        w = self.bargeld
        for s, p in self.positions.items():
            try:
                preis = hole_kurs(s)
            except Exception:
                preis = None
            if not preis or preis <= 0:
                preis = p.get("avg_price", 0) or 0
            w += p["shares"] * preis
        return w

    def speichern(self):
        data = {
            "start_wert": self.start_wert,
            "risk": self.risk,
            "bargeld": self.bargeld,
            "positions": self.positions,
            "historie": self.historie[-100:],
            "trades": self.trades[-50:],
            "ki_letzte": self.ki_letzte,
            "aktualisiert": datetime.now().isoformat(),
        }
        # PHASE 3 (Tenant-Isolation §2.3): Depot-Datei tenant-markieren, damit
        # _tenant_scoped_depot_files() das Depot dem richtigen Tenant zuordnet.
        # Default 1 = bestehende Einzel-Tenant-Depots.
        data["tenant_id"] = int(getattr(self, "tenant_id", 1) or 1)
        # PHASE 5 (§9): Portfolio-Modus (shadow/paper) — getrennte virtuelle
        # Portfolios, Shadow-Positionen werden nie in Paper übernommen.
        data["mode"] = getattr(self, "mode", "shadow") or "shadow"
        # Börsen-Metadaten pro Position (für Marktzeiten-Skipping)
        try:
            from boersen import boerse_fuer_ticker
            data["exchanges"] = {t: boerse_fuer_ticker(t) for t in self.positions}
        except Exception:
            pass
        # BUG-FIX: Zusatzfelder mitschreiben, sonst gehen sie bei
        # jedem Trade verloren (siehe __init__).
        for _k, _v in (getattr(self, "zusatz", None) or {}).items():
            # Die klassischen Felder duerfen nicht ueberschrieben
            # werden - sonst wuerde ein Zusatzfeld wie "positions"
            # den echten Depot-Zustand zerstoeren.
            if _k not in data:
                data[_k] = _v
        # 01.11.2026: atomar schreiben. Vorher direkt in die Zieldatei - ein
        # Abbruch mitten im Schreiben (Neustart, Timeout, voller Speicher)
        # hinterliess eine halbe JSON-Datei und damit ein unlesbares Depot.
        _tmp = self.depot_pfad + ".tmp"
        with open(_tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(_tmp, self.depot_pfad)

    def laden():
        # geladene Instanz zurückgeben
        pass

# ─── Daten ───────────────────────────────────────────────────
CACHE_DURATION = 7200  # 2h Cache

def scan_markt(tickers=None, force=False):
    """Scant Aktien und cached Ergebnis."""
    # BUG-FIX: der Cache wird IMMER eingelesen, auch bei force=True.
    # Vorher war die Bedingung "and not force" - ein Aufruf mit
    # force=True startete also bei {} und schrieb am Ende nur die
    # neu geholten Titel zurueck. Ein Testlauf mit
    # scan_markt(['AAPL'], force=True) hat damit 656 von 657
    # Titeln aus dem Produktivbestand geloescht.
    #
    # force=True heisst jetzt: "Daten neu holen". "Bestand
    # verwerfen" gibt es nicht mehr.
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            age = time.time() - os.path.getmtime(CACHE_FILE)
            if force or age < CACHE_DURATION:
                with open(CACHE_FILE) as f:
                    cache = json.load(f)
        except Exception:
            cache = {}

    fehlen = [t for t in (tickers or []) if t not in cache]
    if not fehlen:
        return cache

    # ── v2.16.8: yfinance Primary, TwelveData-Fallback bei Exception ──
    try:
        daten = yf.download(fehlen, period="3mo", interval="1d", progress=False, auto_adjust=True)
        # yfinance liefert bei Rate-Limit manchmal leeres DataFrame ohne Exception
        if daten is None or (hasattr(daten, "empty") and daten.empty):
            raise ValueError("yfinance empty result (rate-limit?)")
    except Exception as e:
        if not QUIET:
            print(f"   ⚠ yfinance-Scan fehlgeschlagen ({e}), versuche TwelveData-Fallback...", flush=True)
        try:
            from marktdaten import scan_fallback_yfinance
            cache = scan_fallback_yfinance(fehlen, cache)
            # Cache speichern
            with open(CACHE_FILE, "w") as f:
                json.dump(cache, f, indent=1)
            return cache
        except Exception as e2:
            if not QUIET:
                print(f"   ⚠ Scan-Fallback fehlgeschlagen: {e2}", flush=True)
            return cache

    for ticker in fehlen:
        try:
            if isinstance(daten.columns, pd.MultiIndex):
                close = daten['Close'][ticker] if 'Close' in daten else None
                vol = daten['Volume'][ticker] if 'Volume' in daten else None
                high = daten['High'][ticker] if 'High' in daten else None
                low = daten['Low'][ticker] if 'Low' in daten else None
            else:
                close = daten['Close'] if 'Close' in daten else None
                vol = daten['Volume'] if 'Volume' in daten else None
                high = daten['High'] if 'High' in daten else None
                low = daten['Low'] if 'Low' in daten else None
        except:
            continue

        if close is None or len(close.dropna()) < 20:
            continue

        close_s = close.dropna()
        aktuell = float(close_s.iloc[-1])
        sma50 = float(close_s.tail(50).mean())
        sma20 = float(close_s.tail(20).mean())

        # RSI
        delta = close_s.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = float((100 - 100 / (1 + rs)).iloc[-1]) if not rs.isna().all() else 50

        # MACD
        ema12 = close_s.ewm(span=12).mean()
        ema26 = close_s.ewm(span=26).mean()
        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm(span=9).mean()
        macd_bullish = float(macd_line.iloc[-1] > macd_signal.iloc[-1]) if not macd_line.isna().all() else 0

        # Bollinger Bands
        bb_mid = sma20
        bb_std = close_s.tail(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_pos = (aktuell - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) != 0 else 0.5

        # ATR
        if high is not None and low is not None:
            high_s = high.dropna()
            low_s = low.dropna()
            if len(high_s) > 14 and len(low_s) > 14:
                atr = (high_s - low_s).tail(14).mean()
                atr_pct = float(atr / aktuell * 100) if aktuell else 0
            else:
                atr_pct = 0
        else:
            atr_pct = 0

        vol_avg = float(vol.tail(20).mean()) if vol is not None and len(vol.dropna()) > 20 else 0
        vol_aktuell = float(vol.iloc[-1]) if vol is not None and len(vol.dropna()) > 0 else 0

        cache[ticker] = {
            "aktuell": aktuell,
            "sma50": sma50,
            "sma20": sma20,
            "rsi": round(rsi, 1),
            "macd_bullish": macd_bullish,
            "bb_pos": round(bb_pos, 2),
            "atr_pct": round(atr_pct, 2),
            "vol_ratio": round(vol_aktuell / vol_avg, 2) if vol_avg > 0 else 1,
            "uptrend": 1 if aktuell > sma50 else 0,
            "datetime": datetime.now().isoformat(),
        }
        # BUG-003: Marktschnappschuss persistieren (tenant-isoliert, Upsert)
        try:
            from db import MTDB
            _db = MTDB()
            _db.save_markt_daten(
                1, ticker, aktuell,
                rsi=round(rsi, 1), sma20=sma20, sma50=sma50)
        except Exception:
            pass  # Persistenz darf den Scan nie blockieren

    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=1)
    return cache

def hole_kurs(ticker):
    """Live-Kurs für einen Ticker (Super-Mix Fallback, v2.16.8).

    Delegiert an marktdaten.hole_kurs() — yfinance → Finnhub → TwelveData
    → AlphaVantage. Verhindert Kurs=0 bei yfinance-Rate-Limit (P55-Crash).
    """
    try:
        from marktdaten import hole_kurs as _mix_kurs
        return _mix_kurs(ticker)
    except Exception:
        try:
            t = yf.Ticker(ticker)
            data = t.history(period="1d", interval="1m")
            if len(data) > 0:
                return float(data['Close'].iloc[-1])
        except Exception:
            pass
        return 0

# ─── Bewertung ───────────────────────────────────────────────
def bewerte(aktien, budget, risk_params=None, tier_ignore=False):
    """
    Bewertet Aktien mit Tier-Bonus.
    risk_params = {"allowed_tiers": [...], "tier_bonus": {...}, "min_score": N, "volatility_bonus": N}

    tier_ignore=True hebt die Tier-Freigabe auf, verlangt aber
    zwingend risk_params["erlaubte_ticker"] als Whitelist. Ohne
    diese Liste passiert ein Titel-Check nichts, die Titel werden
    also verworfen - das ist der sichere Ausgang.
    """
    if risk_params is None:
        # VERDRAHTUNG: Default kommt aus dem Risk-Controller, nicht mehr aus
        # hartkodierten Werten. Vorher stand hier allowed_tiers=[0..4] und
        # tier_bonus={} -> Risk-0 verhielt sich wie Risk-95.
        risk_params = rc_params(50)

    T2T = ticker_zu_tier()
    allowed = risk_params.get("allowed_tiers") or [0, 1, 2, 3, 4]
    # Whitelist aus dem Depot. Nur belegt, wenn das Depot eine
    # eigene erlaubte Liste mitbringt (siehe depot_umwandeln.py).
    whitelist = set(risk_params.get("erlaubte_ticker") or [])
    tier_bonus = risk_params.get("tier_bonus") or {}
    min_score = risk_params.get("min_score", 40)
    vol_bonus = risk_params.get("volatility_bonus", 5)

    bewertet = []
    for a in aktien:
        ticker = a.get("ticker", "")
        tier = T2T.get(ticker, 2)  # default tier 2

        # Darf diese Aktie überhaupt?
        # tier_ignore: nur mit Whitelist. Ohne die Liste waere es
        # eine Freigabe des gesamten Universums - deshalb wird sie
        # hier erzwungen, nicht nur angenommen.
        if tier_ignore:
            if not whitelist or ticker not in whitelist:
                continue
        elif tier not in allowed:
            continue

        score = 0

        # Hartes Minimum: Aktien unter $1 grundsätzlich ausschließen
        preis = a.get("aktuell", 0)
        if preis < 1.0:
            continue

        # Budget-Anpassung (zentral aus strategie.py v2.20.0)
        if preis <= budget:
            score += strategie.preis_score(preis, budget)  # Penny-Penalty / Small-Cap-Bonus
        else:
            score -= 25  # zu teuer für Budget, kaum Chancen

        # Trend (SMA50)
        if a.get("uptrend", 0):
            score += 15

        # RSI
        rsi = a.get("rsi", 50)
        if 40 <= rsi <= 70:
            score += 10
        elif 30 <= rsi < 40 or 70 < rsi <= 80:
            score += 5
        elif rsi < 30:
            score += 15  # überverkauft

        # MACD
        if a.get("macd_bullish", 0):
            score += 10

        # BB Position
        bb = a.get("bb_pos", 0.5)
        if bb < 0.3:
            score += 10  # günstig
        elif bb < 0.5:
            score += 5

        # Volumen
        if a.get("vol_ratio", 1) > 1.5:
            score += 5

        # ATR (Volatilität)
        atr = a.get("atr_pct", 0)
        score += atr * vol_bonus / 10  # Volatilitäts-Bonus

        # ⭐ TIER-BONUS
        bonus = tier_bonus.get(tier, 0)
        score += bonus

        # Volatilitäts-Bonus nur für Aktien, die genug Bewegung haben
        if atr > 3:
            score += vol_bonus * 0.5

        bewertet.append({
            "ticker": ticker,
            "score": round(score, 1),
            "preis": preis,
            "tier": tier,
            "uptrend": a.get("uptrend", 0),
            "rsi": a.get("rsi", 50),
            "macd": a.get("macd_bullish", 0),
            "bb_pos": a.get("bb_pos", 0.5),
            "atr": a.get("atr_pct", 0),
            "vol_ratio": a.get("vol_ratio", 1),
        })

    gefiltert = [b for b in bewertet if b["score"] >= min_score]
    gefiltert.sort(key=lambda x: -x["score"])
    return gefiltert

def signal_aktion(depot, aktien_bewertet, params):
    """
    Vergleicht Depot-Positionen mit aktuellen Bewertungen.
    Gibt Liste von Aktionen: kaufen/verkaufen/halten.
    """
    aktionen = []
    # VERDRAHTUNG: SL/TP/Positionslimit kommen aus dem Risk-Controller.
    # Die Defaults hier sind nur noch der Fallback, falls ein Aufrufer
    # unvollstaendige params uebergibt.
    _risk = int(getattr(depot, "risk", 50))
    _rcp = rc_params(_risk)
    max_pos = params.get("max_positions", _rcp["max_positions"])
    pos_size = params.get("position_size", _rcp["position_size"])
    stop_loss = params.get("stop_loss", _rcp["stop_loss"])
    take_profit = params.get("take_profit", _rcp["take_profit"])

    # ─── Volatilitäts-Bremse ────────────────────────────────────
    # Bei hohem VIX reduzieren wir die Positionsgrößen
    try:
        vix_data = yf.download("^VIX", period="5d", progress=False, auto_adjust=True)
        if 'Close' in vix_data:
            aktueller_vix = float(vix_data['Close'].iloc[-1])
        else:
            aktueller_vix = float(vix_data.iloc[-1].iloc[0])
    except:
        aktueller_vix = 18  # Fallback

    vola_anpassung = 1.0
    if aktueller_vix > 35:
        vola_anpassung = 0.4  # 60% weniger Positionen
    elif aktueller_vix > 30:
        vola_anpassung = 0.6
    elif aktueller_vix > 25:
        vola_anpassung = 0.8
    elif aktueller_vix > 22:
        vola_anpassung = 0.9

    # Angepasste max_positions basierend auf Volatilität
    max_pos = max(1, int(max_pos * vola_anpassung))
    # Angepasste Positionsgröße
    pos_size = min(pos_size * (1 + (1 - vola_anpassung) * 0.3), 0.95)

    # ─── Drawdown-Limit ─────────────────────────────────────────
    # Wenn Depot zu weit unter Allzeithoch, einfrieren.
    # VERDRAHTUNG: Das Limit kommt jetzt aus dem Risk-Controller und ist damit
    # PRO RISIKOSTUFE verschieden (Risk 0: 15%, Risk 95: 34%). Vorher galt
    # fuer alle Depots derselbe globale Wert aus den Settings.
    depot_peak = getattr(depot, "peak_wert", depot.start_wert)
    aktueller_wert = depot.wert()
    dd_prozent = rc_drawdown_pct(depot_peak, aktueller_wert)
    dd_limit = _rcp["max_drawdown"]
    if dd_prozent >= dd_limit and len(depot.positions) > 0:
        # Notverkauf aller Positionen und Depot einfrieren
        for ticker, pos in list(depot.positions.items()):
            if depot.positions[ticker].get("shares", 0) > 0:
                aktionen.append({"typ": "verkaufen", "ticker": ticker, "grund": "drawdown_limit",
                                 "menge": depot.positions[ticker]["shares"],
                                 "preis": depot.positions[ticker].get("avg_price", 0)})
        depot.gesperrt = True
        depot.gesperrt_bei_wert = aktueller_wert
        return aktionen  # Nichts weiter tun
    elif aktueller_wert > depot_peak:
        depot.peak_wert = aktueller_wert  # Neues Allzeithoch

    # Sektor-Mapping laden (für Diversifikation)
    SECTOR_PATH = os.path.join(BASE_DIR, "static", "ticker_sectors.json")
    TICKER_SEKTOR = {}
    if os.path.exists(SECTOR_PATH):
        try:
            with open(SECTOR_PATH) as f:
                TICKER_SEKTOR = json.load(f)
        except:
            pass

    gehaltene_ticker = set(depot.positions.keys())
    bewertete_ticker = set(b["ticker"] for b in aktien_bewertet)

    # 1. Verkaufen: Positionen deren Score eingebrochen ist
    bewerte_map = {b["ticker"]: b for b in aktien_bewertet}
    for ticker in list(gehaltene_ticker):
        pos = depot.positions[ticker]
        if ticker in bewerte_map:
            b = bewerte_map[ticker]
            aktuell = b["preis"]  # Kurse aus Cache, nicht Live-API

            # Stop-Loss
            sl = pos.get("stop_loss", pos["avg_price"] * stop_loss)
            if aktuell < sl:
                depot.positions[ticker]["aktuell"] = aktuell
                aktionen.append({"typ": "verkaufen", "ticker": ticker, "grund": "stop_loss",
                                 "menge": pos["shares"], "preis": aktuell})
                continue

            # Take-Profit
            tp = pos.get("take_profit", pos["avg_price"] * take_profit)
            if aktuell > tp:
                aktionen.append({"typ": "verkaufen", "ticker": ticker, "grund": "take_profit",
                                 "menge": pos["shares"], "preis": aktuell})
                continue

            # Trend gekippt
            if not b["uptrend"] and b["score"] < 30:
                aktionen.append({"typ": "verkaufen", "ticker": ticker, "grund": "trend_ende",
                                 "menge": pos["shares"], "preis": aktuell})
                continue

        # Score zu tief (aus Bewertung gefallen)
        if ticker not in bewertete_ticker:
            aktuell = pos.get("avg_price", 0)
            aktionen.append({"typ": "verkaufen", "ticker": ticker, "grund": "aus_bewertung",
                             "menge": pos["shares"], "preis": aktuell})
            continue

    # 4. Auto-Upgrade: schwache Positionen ersetzen (wenn bessere da sind)
    # Prüfe: hält Depot eine Aktie mit Score < 35 und gibt es einen Kandidaten mit Score > 55?
    gehaltene_ticker = set(depot.positions.keys())
    for ticker in list(gehaltene_ticker):
        if ticker in bewerte_map:
            b = bewerte_map[ticker]
            if b["score"] < 35 and depot.positions[ticker].get("shares", 0) > 0:
                # Gibt es bessere Kandidaten?
                beste = sorted(
                    [x for x in aktien_bewertet if x["ticker"] not in gehaltene_ticker and x["score"] > 55],
                    key=lambda x: -x["score"]
                )
                if beste:
                    aktuell = b["preis"]
                    aktionen.append({"typ": "verkaufen", "ticker": ticker, "grund": "upgrade",
                                     "menge": depot.positions[ticker]["shares"], "preis": aktuell})
                    break  # Nur eine Position pro Durchlauf upgraden

    # 2. Halten: bestehende Positionen aktualisieren
    gehalten_ticker = set(depot.positions.keys())

    # Welche Sektoren sind bereits belegt?
    belegte_sektoren = set()
    for t in gehalten_ticker:
        if t in TICKER_SEKTOR and TICKER_SEKTOR[t]:
            belegte_sektoren.add(TICKER_SEKTOR[t])

    # 3. Kaufen: freie Plätze füllen – mit Zufallsauswahl aus Top 3 + Sektor-Diversifikation
    offene_plaetze = max_pos - len(gehalten_ticker)
    if offene_plaetze > 0 and depot.bargeld > 5:
        kauf_kandidaten = [b for b in aktien_bewertet if b["ticker"] not in gehalten_ticker]

        for _ in range(offene_plaetze):
            if not kauf_kandidaten or depot.bargeld < 5:
                break
            kauf_kandidaten.sort(key=lambda x: -x["score"])
            # Filtere Kandidaten: gleicher Sektor wie existierende Position? Dann ausschließen
            sektor_ok = []
            for k in kauf_kandidaten:
                k_sektor = TICKER_SEKTOR.get(k["ticker"], "")
                if k_sektor and k_sektor in belegte_sektoren:
                    continue  # Sektor bereits im Depot – nicht kaufen
                sektor_ok.append(k)
            if sektor_ok:
                kauf_kandidaten = sektor_ok

            # Zufällig aus Top min(3, len) wählen – Diversifikation
            top_n = min(3, len(kauf_kandidaten))
            k = random.choice(kauf_kandidaten[:top_n])
            kauf_kandidaten.remove(k)
            belegte_sektoren.add(TICKER_SEKTOR.get(k["ticker"], ""))

            invest = depot.bargeld * pos_size
            # VERDRAHTUNG: Zentraler Eintritt. Jeder Kauf laeuft durch
            # risk_controller.pruefe_und_bremse(). Bei Verletzung wird
            # blockiert und der konkrete Grund protokolliert – der Kauf
            # faellt nicht stillschweigend aus.
            _chk = rc_pruefe(
                _risk, ticker=k["ticker"], tier=k.get("tier", 2), preis=k["preis"],
                cash=depot.bargeld, depot_wert=depot.wert(),
                anzahl_positionen=len(depot.positions), betrag=invest,
                positionen=list(depot.positions),
                vol_ratio=k.get("vol_ratio"), score=k.get("score"),
                quelle="engine.signal_aktion")
            if _chk.blockiert:
                if not QUIET:
                    print(f"   🛑 {k['ticker']} abgewiesen: {_chk.reason}", flush=True)
                depot.trades.append({
                    "typ": "kauf_blockiert", "ticker": k["ticker"], "menge": 0,
                    "preis": round(k["preis"], 2), "grund": _chk.reason,
                    "zeit": datetime.now().isoformat(),
                })
                continue
            invest = _chk.max_betrag
            aktien = invest / k["preis"]
            if aktien > 0 and invest > 5:
                # ABRUNDEN statt RUNDEN. Mit round(aktien, 2) konnte die
                # gerundete Stueckzahl den Kauf um bis zu ~0.8 EUR ueber das
                # freigegebene Limit heben – der Controller blockierte dann
                # korrekt, aber grundlos. math.floor haelt kosten <= invest.
                aktien = math.floor(aktien * 100) / 100.0
                if aktien <= 0:
                    continue
                aktionen.append({
                    "typ": "kaufen", "ticker": k["ticker"],
                    "menge": round(aktien, 2),
                    "preis": k["preis"],
                    "score": k["score"],
                    "tier": k.get("tier", 2),
                    "grund": f"Score {k['score']} (#{top_n})",
                })

    return aktionen

try:
    from security import get_broker_adapter
except Exception:
    get_broker_adapter = None

def ausführen(depot, aktionen, params, broker=None, alternatives=None):
    """Führt Aktionen aus, aktualisiert Depot.
    `alternatives`: Liste weiterer Kauf-Kandidaten (je {'ticker','preis',...}),
    die bei einer Konzentrations-Bremse als Ausweich-Kandidaten versucht werden,
    damit leere Depots nicht unnötig leer bleiben.

    30.09.2026: Rueckgabe. Die Funktion gibt die AUSGEFUEHRTEN
    Aktionen zurueck, nicht None. Vorher nahm der Aufrufer an,
    jeder Aufruf sei ein Erfolg, und druckte das auch so:

        🟢 Kauf STUB 11.30st @$5.31 (Tier 4)

    stand im Protokoll, waehrend Risk 80 bei 200 Euro und null
    Positionen blieb: die Konzentrations-Bremse hatte den Kauf
    still uebersprungen. Der Aufrufer meldet seitdem nur noch,
    was tatsaechlich ausgefuehrt wurde."""
    # VERDRAHTUNG 2026-09-27: Risikoparameter des Depots EINMAL hier holen.
    # Sie werden im Kaufpfad (SL/TP beim Neuanlegen) und im Ausweichpfad
    # gebraucht – params.get(..., _rcp[...]) wertet seinen Default IMMER aus,
    # also muss _rcp in JEDEM Kaufzweig definiert sein.
    _risk = int(getattr(depot, "risk", 50))
    _rcp = rc_params(_risk)
    # Was tatsaechlich ausgefuehrt wurde. Der Aufrufer meldet
    # danach nur noch diese Aktionen.
    _ausgefuehrt = []
    for a in aktionen:
        if a["typ"] == "kaufen":
            kosten = a["menge"] * a["preis"]
            ticker = a["ticker"]
            # ⚠️ P4: Konzentrations-Bremse (harte Engine-Grenze)
            # Ticker darf max. in N Depots liegen (Klumpenrisiko vermeiden, aus Settings)
            try:
                from ki_kontext import ticker_konzentration
                # BUGFIX 2026-09-27: 'from ki_decisions import QUIET' entfernt.
                # Der Import stand in diesem Zweig, wodurch Python QUIET fuer die
                # GANZE Funktion als Lokal kompilierte -> UnboundLocalError bei
                # Verkaufsaktionen ohne vorherigen Kauf. Modulweit definiert.
                max_dt = max_depot_pro_ticker()
                anz = ticker_konzentration(ticker)
                if anz >= max_dt:
                    # Ausweich-Kandidaten versuchen (bei leeren Depots sinnvoll)
                    _alt = None
                    if alternatives:
                        for alt in alternatives:
                            at = alt.get("ticker")
                            if at and at != ticker and ticker_konzentration(at) < max_dt:
                                _alt = alt
                                break
                    if _alt:
                        if not QUIET:
                            print(f"   🛑 BREMSE {ticker} (Max {max_dt}) — Ausweich auf {_alt['ticker']}", flush=True)
                        ticker = _alt["ticker"]
                        _alt_preis = _alt.get("preis", a["preis"])
                        # BEFUND-1-FIX 2026-09-27: der Ausweichpfad benutzte
                        # `_budget = depot.bargeld` und kaufte damit 100% des
                        # Depot-Cash – riskanter als der Normalpfad und eine
                        # Umgehung von position_size und max_positions.
                        # Jetzt: der Ausweichkauf ist auf denselben Betrag
                        # geklemmt wie ein regulaerer Kauf.
                        _budget = rc_max_betrag(depot.bargeld, _risk)
                        if _budget <= 0:
                            if not QUIET:
                                print(f"   🛑 BREMSE {ticker} → {_alt['ticker']}: "
                                      f"kein Betrag freigegeben (Cash-Boden Risk {_risk})",
                                      flush=True)
                            depot.trades.append({
                                "typ": "kauf_blockiert", "ticker": ticker,
                                "menge": 0, "preis": round(a["preis"], 2),
                                "grund": f"Ausweichk {_alt['ticker']}: Cash-Boden bei Risk {_risk}",
                                "zeit": datetime.now().isoformat(),
                            })
                            continue
                        _neue_menge = _budget / _alt_preis if _alt_preis > 0 else a["menge"]
                        # 01.11.2026: tier des AUSWEICH-Titels, nicht den des
                        # urspruenglichen - sonst prueft der Controller unten
                        # das falsche Tier (z. B. Aktie statt Hebel-ETF).
                        a = dict(a, ticker=ticker, preis=_alt_preis, menge=_neue_menge,
                                 tier=_alt.get("tier"))
                        kosten = a["menge"] * a["preis"]
                    else:
                        if not QUIET:
                            print(f"   🛑 BREMSE {ticker}: bereits in {anz} Depots (Max {max_dt}) — Kauf blockiert", flush=True)
                        depot.trades.append({
                            "typ": "kauf_blockiert", "ticker": ticker,
                            "menge": a["menge"], "preis": round(a["preis"], 2),
                            "grund": f"Konzentrations-Bremse: bereits in {anz} Depots",
                            "zeit": datetime.now().isoformat(),
                        })
                        continue
            except Exception:
                pass
            # 🛡 VERDRAHTUNG 2026-09-27: DER zentrale Eintritt fuer JEDEN Kauf.
            # Er sitzt bewusst NACH der Konzentrations-Bremse, damit er genau
            # den Ticker und genau den Betrag prueft, der am Ende wirklich
            # gehandelt wird – egal ob Normalpfad oder Ausweichpfad.
            # Vorher lief nur der Ausweichpfad durch eine Pruefung; ein
            # regulaerer Kauf aus batch_trader.py:626 konnte ungeprueft
            # ein Tier kaufen, das dem Depot verboten ist.
            _kauf_tier = a.get("tier")
            if _kauf_tier is None:
                _kauf_tier = ticker_zu_tier().get(a["ticker"], 2)
            # 01.11.2026: depot.wert() holt fuer JEDE Position einen Live-
            # Kurs (Netz). Vorher zweimal pro Kauf aufgerufen - jetzt einmal.
            _dwert = depot.wert()
            _gate = rc_pruefe(
                _risk, ticker=a["ticker"], tier=_kauf_tier, preis=a["preis"],
                cash=depot.bargeld, depot_wert=_dwert,
                anzahl_positionen=len(depot.positions),
                positionen=list(depot.positions), betrag=kosten,
                drawdown_pct=rc_drawdown_pct(getattr(depot, "peak_wert",
                                                    depot.start_wert),
                                             _dwert),
                quelle="engine.ausfuehren")
            if _gate.blockiert:
                if not QUIET:
                    print(f"   🛑 {a['ticker']} abgewiesen: {_gate.reason}", flush=True)
                depot.trades.append({
                    "typ": "kauf_blockiert", "ticker": a["ticker"],
                    "menge": 0, "preis": round(a["preis"], 2),
                    "grund": _gate.reason, "zeit": datetime.now().isoformat(),
                })
                continue
            # 01.11.2026: Earnings-Sperre - kein Neukauf kurz vor Quartalszahlen
            # (earnings.py; ETFs haben keine, Tier 4 wird nicht abgefragt).
            try:
                if str(_kauf_tier) != "4":
                    import earnings as _earn
                    _gesp, _egrund = _earn.kauf_gesperrt(a["ticker"])
                    if _gesp:
                        if not QUIET:
                            print(f"   📅 {a['ticker']}: {_egrund} - kein Kauf", flush=True)
                        depot.trades.append({
                            "typ": "kauf_blockiert", "ticker": a["ticker"],
                            "menge": 0, "preis": round(a["preis"], 2),
                            "grund": "Earnings-Sperre: " + _egrund,
                            "zeit": datetime.now().isoformat(),
                        })
                        continue
            except Exception:
                pass  # fail-open: ohne Termin-Daten wird gekauft
            # 01.11.2026: Handelskosten (Gebuehr + Slippage, handelskosten.py).
            # Die Menge wird ggf. so verkleinert, dass Kauf + Gebuehr ins
            # Bargeld passen. Der Einstandspreis enthaelt die Kosten.
            _hk = handelskosten.kauf(a["menge"], a["preis"], depot.bargeld,
                                     tier=_kauf_tier)
            if _hk["abgelehnt"]:
                if not QUIET:
                    print(f"   🛑 {a['ticker']}: {_hk['abgelehnt']}", flush=True)
                depot.trades.append({
                    "typ": "kauf_blockiert", "ticker": a["ticker"],
                    "menge": 0, "preis": round(a["preis"], 2),
                    "grund": "Handelskosten: " + _hk["abgelehnt"],
                    "zeit": datetime.now().isoformat(),
                })
                continue
            a = dict(a, menge=_hk["menge"])
            kosten = _hk["gesamt"]
            if kosten <= depot.bargeld:
                depot.bargeld -= kosten
                ticker = a["ticker"]
                if ticker in depot.positions:
                    p = depot.positions[ticker]
                    gesamt = p["shares"] * p["avg_price"] + kosten
                    p["shares"] += a["menge"]
                    p["avg_price"] = gesamt / p["shares"]
                else:
                    depot.positions[ticker] = {
                        "shares": a["menge"],
                        "avg_price": kosten / a["menge"],
                        "stop_loss": a["preis"] * params.get("stop_loss", _rcp["stop_loss"]),
                        "take_profit": a["preis"] * params.get("take_profit", _rcp["take_profit"]),
                        "kauf_datum": datetime.now().isoformat(),
                    }
                    # Börse des Tickers als Metadatum (für Marktzeiten-Skipping)
                    try:
                        from boersen import boerse_fuer_ticker
                        depot.positions[ticker]["exchange"] = boerse_fuer_ticker(ticker)
                    except Exception:
                        pass
                # 01.11.2026: Ausgefuehrt, nicht nur aufgerufen. Stand vorher im
                # try des boersen-Imports: Nachkaeufe in bestehende Positionen
                # (und Kaeufe bei Importfehler) fehlten im Rueckgabewert.
                _ausgefuehrt.append(a)
                depot.trades.append({
                    "typ": "kauf", "ticker": a["ticker"],
                    "menge": a["menge"], "preis": round(a["preis"], 2),
                    "kurs_eff": round(_hk["kurs_eff"], 4),
                    "gebuehr": round(_hk["gebuehr"], 2),
                    "grund": a["grund"], "zeit": datetime.now().isoformat(),
                })
                # P19: Broker-Adapter (Sandbox/Paper) für Order-Tracking/Audit
                if broker is not None:
                    try:
                        broker.place_order(a["ticker"], "BUY", a["menge"], a["preis"])
                    except Exception:
                        pass

        elif a["typ"] == "verkaufen":
            ticker = a["ticker"]
            # 🛡 Fix: Verkauf zum Preis 0/None verhindern (yfinance Rate-Limit -> 0 -> Erlös 0,
            # Position verschwindet ohne Bargeld-Gutschrift => Depot-Wert stürzt ab)
            preis = a.get("preis") or 0
            if preis <= 0:
                if not QUIET:
                    print(f"   🛡 KEIN VERKAUF {ticker}: Kurs {preis} (Rate-Limit/Fehler) — Position behalten", flush=True)
                continue
            if ticker in depot.positions:
                p = depot.positions[ticker]
                # 01.11.2026: Menge auf den Bestand begrenzen. Vorher wurde
                # a["menge"] * preis gutgeschrieben, auch wenn die Aktion mehr
                # Stueck verkaufen wollte als vorhanden - Bargeld aus dem Nichts.
                if a["menge"] > p["shares"]:
                    a = dict(a, menge=p["shares"])
                # 01.11.2026: Erloes nach Slippage und Gebuehr
                _hv = handelskosten.verkauf(
                    a["menge"], preis,
                    tier=a.get("tier", ticker_zu_tier().get(ticker)))
                erlös = _hv["erloes"]
                depot.bargeld += erlös
                depot.trades.append({
                    "typ": "verkauf", "ticker": ticker,
                    "menge": a["menge"], "preis": round(a["preis"], 2),
                    "kurs_eff": round(_hv["kurs_eff"], 4),
                    "gebuehr": round(_hv["gebuehr"], 2),
                    "grund": a["grund"], "zeit": datetime.now().isoformat(),
                })
                # P19: Broker-Adapter (Sandbox/Paper) für Order-Tracking/Audit
                if broker is not None:
                    try:
                        broker.place_order(ticker, "SELL", a["menge"], preis)
                    except Exception:
                        pass
                # Position entfernen oder reduzieren
                if a["menge"] >= p["shares"] - 0.001:
                    del depot.positions[ticker]
                else:
                    p["shares"] -= a["menge"]
                # Ausgefuehrt, nicht nur aufgerufen.
                _ausgefuehrt.append(a)
    # Was wirklich passiert ist. Der Aufrufer druckt nur noch das.
    return _ausgefuehrt


def rendite(depot):
    """Berechnet aktuelle Rendite in Prozent."""
    w = depot.wert()
    if depot.start_wert > 0:
        return (w / depot.start_wert - 1) * 100
    return 0


def depot_stats(depot):
    """Berechnet Sharpe, MaxDD, Vola für ein Depot aus der Historie."""
    hist = getattr(depot, "historie", [])
    stats = {
        "sharpe": 0,
        "max_dd": 0,
        "vola": 0,
        "peak_wert": getattr(depot, "peak_wert", depot.start_wert),
        "gesperrt": getattr(depot, "gesperrt", False),
    }
    if len(hist) < 3:
        return stats

    werte = [h["wert"] for h in hist]
    # Max Drawdown
    peak = werte[0]
    max_dd = 0
    for w in werte:
        if w > peak:
            peak = w
        dd = (peak - w) / peak * 100
        if dd > max_dd:
            max_dd = dd
    stats["max_dd"] = round(max_dd, 1)

    # Volatilität der täglichen Renditen
    renditen = []
    for i in range(1, len(werte)):
        if werte[i-1] > 0:
            renditen.append((werte[i] / werte[i-1]) - 1)
    if len(renditen) > 2:
        import numpy as np
        vola = np.std(renditen) * np.sqrt(252) * 100  # annualisiert
        stats["vola"] = round(vola, 1)
        # Sharpe (vereinfacht, rf=0)
        if vola > 0:
            mean_ret = np.mean(renditen) * 252  # annualisiert
            stats["sharpe"] = round(mean_ret / (vola/100), 2)

    return stats

def historie_aktualisieren(depot):
    """Fügt aktuellen Depotwert zur Historie hinzu."""
    depot.historie.append({
        "zeit": datetime.now().isoformat(),
        "wert": round(depot.wert(), 2),
        "bargeld": round(depot.bargeld, 2),
    })

