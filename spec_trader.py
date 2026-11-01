#!/usr/bin/env python3
"""Spec-Trader – KI-gestütztes Trading aller Spekulations-Instrumente.

Nutzt ki_decisions.py (LLM) für jede Trade-Entscheidung.
Jedes Instrument bekommt ein Depot mit 100$.
Daten kommen aus yfinance.
"""

import sys, os, json, time, math
import yfinance as yf
import pandas as pd
import numpy as np
import handelskosten  # 01.11.2026: Gebuehren + Slippage im Paper-Trading
from datetime import datetime
from pathlib import Path

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from spec_watch import WATCHLIST
from ki_decisions import entscheide_spec_batch

# VERDRAHTUNG 2026-09-27 (Rebuild Risiko-Controller): spec_trader hatte laut
# grep NULL Vorkommen von stop_loss/take_profit/max_positions/drawdown – das
# Einzige Gate war "Konfidenz >= 40 und Bargeld > 1.0". Jetzt laeuft jeder
# Kauf durch pruefe_und_bremse() und das Depot fuehrt SL/TP/Drawdown-Lock.
from risk_controller import (
    params as rc_params,
    pruefe_und_bremse as rc_pruefe,
    max_betrag as rc_max_betrag,
    drawdown_pct_von as rc_drawdown_pct,
    HEBEL_TIERS as RC_HEBEL_TIERS,
)
# Die Tier-Quelle ist risk_profile.TICKER_TO_TIER - dieselbe, die
# risk_controller._tier_von_ticker() intern liest und die
# batch_trader.py:65 direkt importiert. So sehen Controller und
# Aufrufer garantiert denselben Wert.
from risk_profile import TICKER_TO_TIER as _TICKER_TO_TIER

# Risikostufe je Spec-Kategorie. Spec-Depots sind per Definition spekulativ,
# deshalb starten sie hoch, aber nicht bei 95: Hebel-Instrumente bekommen
# eine eigene, noch hoehere Stufe.
_KAT_RISK = {
    "lev-bull": 90, "lev-bear": 90, "commodity": 80, "volatility": 85,
    "ai": 75, "meme": 80, "ev": 70, "biotech": 70, "crypto": 80,
}
# Jedes Spec-Depot startet mindestens so defensiv, wie sein Instrument hergibt.
_SPEC_RISK_DEFAULT = 70


def risk_fuer_kat(kategorie, hebel=0):
    """Leitet die Risikostufe eines Spec-Instruments aus seiner Kategorie ab."""
    r = _KAT_RISK.get((kategorie or "").lower(), _SPEC_RISK_DEFAULT)
    try:
        if int(hebel or 0) >= 2:
            r = min(95, r + 5)
    except (TypeError, ValueError):
        pass
    return r

# Settings: max_spec_depots (begrenzt Anzahl aktiver Spec-Depots)
try:
    from settings_loader import depot_struktur
    _MAX_SPEC = int(depot_struktur("max_spec_depots", 60))
except Exception:
    _MAX_SPEC = 48

QUIET = "--quiet" in sys.argv

DEPOT_DIR = os.path.join(BASE, "spec_depots")
# PHASE 5 (§9): PAPER nutzt eigenes Verzeichnis -> getrennte virtuelle Portfolios
DEPOT_DIR_PAPER = os.path.join(BASE, "spec_depots_paper")
os.makedirs(DEPOT_DIR, exist_ok=True)
os.makedirs(DEPOT_DIR_PAPER, exist_ok=True)


class SpecDepot:
    """Ein Depot für ein Spekulations-Instrument ($100 Start)."""
    def __init__(self, ticker, name="", kategorie="", mode="shadow"):
        self.ticker = ticker
        self.name = name
        self.kategorie = kategorie
        self.mode = mode if mode in ("paper", "shadow") else "shadow"
        self.bargeld = 100.0
        self.shares = 0.0
        self.avg_price = 0.0
        self.start = 100.0
        # VERDRAHTUNG 2026-09-27: Risikostufe + Limits je Depot.
        # Die Risikostufe leitet sich aus der Kategorie des Instruments ab.
        self.risk = risk_fuer_kat(kategorie)
        self.stop_loss = None      # wird beim ersten Kauf gesetzt
        self.take_profit = None
        self.peak_wert = 100.0
        self.gesperrt = False
        self.gesperrt_grund = ""
        self.hoch_seit_kauf = None  # 01.11.2026: fuer den Trailing-Stop
        self.historie = []
        self.trades = []
        self.ki_letzte = None  # letzte KI-Entscheidung
        self.laden()
        # Risiko nach dem Laden ggf. aus der Datei uebernehmen
        self.risk = risk_fuer_kat(kategorie or self.kategorie)

    def pfad(self):
        d = DEPOT_DIR_PAPER if self.mode == "paper" else DEPOT_DIR
        return os.path.join(d, "%s.json" % self.ticker.replace("/", "_").replace("^", ""))

    def laden(self):
        p = self.pfad()
        if os.path.exists(p):
            with open(p) as f:
                d = json.load(f)
            self.bargeld = d.get("bargeld", 100.0)
            self.shares = d.get("shares", 0.0)
            self.avg_price = d.get("avg_price", 0.0)
            self.start = d.get("start", 100.0)
            self.historie = d.get("historie", [])
            self.trades = d.get("trades", [])
            self.ki_letzte = d.get("ki_letzte")
            self.exchange = d.get("exchange")
            self.mode = d.get("mode", self.mode)
            # VERDRAHTUNG 2026-09-27: Risiko-Zustand mitpersistieren
            self.risk = d.get("risk", self.risk)
            self.stop_loss = d.get("stop_loss", self.stop_loss)
            self.take_profit = d.get("take_profit", self.take_profit)
            self.peak_wert = d.get("peak_wert", self.peak_wert)
            self.hoch_seit_kauf = d.get("hoch_seit_kauf")
            self.gesperrt = d.get("gesperrt", self.gesperrt)
            self.gesperrt_grund = d.get("gesperrt_grund", self.gesperrt_grund)

    def drawdown_pct(self, kurs=None):
        """Aktueller Drawdown in Prozent gegen den Allzeithoch."""
        return rc_drawdown_pct(self.peak_wert, self.wert(kurs))

    def aktualisiere_peak(self, kurs=None):
        """Allzeithoch nachfuehren und Drawdown-Lock pruefen."""
        w = self.wert(kurs)
        if w > self.peak_wert:
            self.peak_wert = w
        dd = rc_drawdown_pct(self.peak_wert, w)
        if dd >= rc_params(self.risk)["max_drawdown"] and self.shares > 0:
            self.gesperrt = True
            self.gesperrt_grund = ("Drawdown %.1f%% >= Limit %.1f%% (Risk %d)"
                                   % (dd, rc_params(self.risk)["max_drawdown"], self.risk))
        return dd

    def speichern(self):
        p = self.pfad()
        # 01.11.2026: atomar (tmp + os.replace).
        _tmp = p + ".tmp"
        with open(_tmp, "w") as f:
            json.dump({
                "ticker": self.ticker,
                "name": self.name,
                "kategorie": self.kategorie,
                "bargeld": round(self.bargeld, 2),
                "shares": round(self.shares, 6),
                "avg_price": round(self.avg_price, 4),
                "start": self.start,
                "exchange": getattr(self, "exchange", None),
                "historie": self.historie[-100:],
                "trades": self.trades[-50:],
                "ki_letzte": self.ki_letzte,
                "tenant_id": int(getattr(self, "tenant_id", 1) or 1),  # PHASE 3 §2.3
                "mode": self.mode,  # PHASE 5 §9: Portfolio-Modus
                # VERDRAHTUNG 2026-09-27: Risikostufe + Limits persistieren
                "risk": self.risk,
                "stop_loss": self.stop_loss,
                "take_profit": self.take_profit,
                "peak_wert": round(self.peak_wert, 4),
                "hoch_seit_kauf": getattr(self, "hoch_seit_kauf", None),
                "gesperrt": self.gesperrt,
                "gesperrt_grund": self.gesperrt_grund,
            }, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(_tmp, p)

    def wert(self, force_price=None):
        """Depotwert: Bargeld plus Position zum aktuellen Kurs.

        30.09.2026: Der alte Rueckfall "return self.bargeld"
        liess die Position weg, sobald kein force_price
        uebergeben wurde. Bei BB: 69.00 statt 100.00. Die
        Rendite fiel dadurch auf den Startwert zurueck und die
        Anzeige stimmte aus dem falschen Grund - dieselbe
        Fehlerform wie bei den Aktien.

        force_price bleibt fuer Aufrufer, die den Kurs schon
        haben (das haufige der Fall im Lauf). Ohne ihn wird der
        Kurs geholt, und der Einstandspreis ist der Rueckfall:
        lieber eine Position zum Einstand als gar keine.
        """
        if self.shares <= 0:
            return self.bargeld
        # 01.11.2026: Ein force_price von 0 (Rate-Limit) bewertete die
        # Position mit 0. aktualisiere_peak() rechnete daraus einen Drawdown
        # und konnte das Depot DAUERHAFT sperren (gesperrt wird gespeichert).
        if force_price is not None and force_price > 0:
            return self.bargeld + self.shares * force_price
        try:
            from marktdaten import hole_kurs
            preis = hole_kurs(self.ticker)
        except Exception:
            try:
                from engine import hole_kurs
                preis = hole_kurs(self.ticker)
            except Exception:
                preis = 0.0
        if not preis or preis <= 0:
            preis = self.avg_price
        return self.bargeld + self.shares * preis


def fetch_analyse():
    """Holt Kursdaten + Indikatoren fuer alle Instrumente.
    v2.16.10: Super-Mix-Fallback — wenn yfinance im Batch einen Ticker
    auslaesst (Flakiness), einzeln via marktdaten.hole_kurs() nachholen.
    """
    tickers = list(WATCHLIST.keys())
    # Settings: max_spec_depots begrenzen (aber nie weniger als WATCHLIST-Laenge)
    _limit = max(_MAX_SPEC, len(tickers))
    if len(tickers) > _limit:
        tickers = tickers[:_limit]

    # Import fuer Super-Mix-Fallback
    try:
        from marktdaten import hole_kurs as _mix_kurs
        _has_mix = True
    except Exception:
        _has_mix = False

    # Batch-Download via yfinance
    try:
        daten = yf.download(tickers, period="3mo", interval="1d", progress=False, auto_adjust=True, timeout=60)
    except Exception:
        daten = pd.DataFrame()
    # Wenn Batch komplett leer/fehlgeschlagen -> direkt zu marktdaten-Fallback
    if daten is None or daten.empty:
        try:
            from marktdaten import hole_kurs as _mix_kurs
            _mix_ok = True
        except Exception:
            _mix_ok = False
        if _mix_ok:
            print("  ⚡ yfinance Batch fehlgeschlagen -> marktdaten-Fallback für alle", flush=True)
            ergebnis = {}
            for ticker in tickers:
                p = _mix_kurs(ticker)
                if p and p > 0:
                    ergebnis[ticker] = p
            # ergebnis enthaelt nur Kurse; fetch_analyse baut daraus Indikatoren
            if ergebnis:
                return _aus_kursen_aufbauen(ergebnis, tickers)
    ist_multi = isinstance(daten.columns, pd.MultiIndex) if not daten.empty else False
    ergebnis = {}

    # v2.16.10: Fehlende Ticker nach Batch-Download explizit nachholen
    gefunden = set()
    if ist_multi and 'Close' in daten.columns:
        gefunden = set(daten['Close'].columns)
    elif not ist_multi and 'Close' in daten.columns:
        gefunden = set(tickers)  # single-column: alle da
    fehlende = [t for t in tickers if t not in gefunden]

    for ticker in tickers:
        try:
            if ist_multi:
                close = daten['Close'][ticker].dropna() if 'Close' in daten and ticker in daten['Close'] else None
            else:
                close = daten['Close'].dropna() if 'Close' in daten.columns else None

            # Fallback: yfinance single-download wenn Batch fehlschlaegt
            if close is None or len(close) < 50:
                # Single-Download Fallback (yfinance)
                try:
                    sd = yf.download(ticker, period="3mo", interval="1d", progress=False, auto_adjust=True, timeout=30)
                    if 'Close' in sd.columns:
                        close = sd['Close'].dropna()
                except Exception:
                    close = None

            # Fallback: marktdaten.hole_kurs() (4-Tier) fuer aktuellen Kurs
            if (close is None or len(close) < 50) and _has_mix:
                preis = _mix_kurs(ticker)
                if preis and preis > 0:
                    # Minimal-Daten aus aktuellem Kurs + sma20/50 Schaetzung
                    close = pd.Series([preis] * 60)
                    print(f"  ⚡ {ticker}: Super-Mix-Fallback (Kurs ${preis:.2f})", flush=True)

            if close is None or len(close) < 50:
                continue

            # ATR (14) + Volume-Ratio aus den vorhandenen Daten
            atr_pct = None
            vol_ratio = None
            try:
                if ist_multi:
                    high = daten['High'][ticker].dropna() if 'High' in daten and ticker in daten['High'] else None
                    low = daten['Low'][ticker].dropna() if 'Low' in daten and ticker in daten['Low'] else None
                    vol = daten['Volume'][ticker].dropna() if 'Volume' in daten and ticker in daten['Volume'] else None
                else:
                    high = daten['High'].dropna() if 'High' in daten else None
                    low = daten['Low'].dropna() if 'Low' in daten else None
                    vol = daten['Volume'].dropna() if 'Volume' in daten else None
                if high is not None and low is not None and len(high) > 14:
                    tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
                    atr = float(tr.tail(14).mean())
                    aktuell_f = float(close.iloc[-1])
                    atr_pct = round(atr / aktuell_f * 100, 2) if aktuell_f else None
                if vol is not None and len(vol) > 20:
                    vol_avg = float(vol.tail(20).mean())
                    vol_ratio = round(float(vol.iloc[-1]) / vol_avg, 2) if vol_avg > 0 else None
            except Exception:
                pass

            aktuell = float(close.iloc[-1])
            sma20 = float(close.rolling(20).mean().iloc[-1])
            sma50 = float(close.rolling(50).mean().iloc[-1])

            # RSI (robust gegen NaN/Edge-Cases, v2.16.10)
            try:
                delta = close.diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / loss.replace(0, np.nan)
                rsi_val = (100 - (100 / (1 + rs))).iloc[-1]
                rsi = float(rsi_val) if not pd.isna(rsi_val) else 50.0
            except Exception:
                rsi = 50.0

            # Trend
            if aktuell > sma20 > sma50:
                uptrend = 1
            elif aktuell < sma20 < sma50:
                uptrend = 0
            else:
                uptrend = 0.5

            ergebnis[ticker] = {
                "aktuell": round(aktuell, 2),
                "sma20": round(sma20, 2),
                "sma50": round(sma50, 2),
                "uptrend": uptrend,
                "rsi": round(rsi, 1),
                "atr_pct": atr_pct,
                "vol_ratio": vol_ratio,
                "name": WATCHLIST[ticker]["name"],
                "kat": WATCHLIST[ticker]["kat"],
            }
        except Exception as e:
            if not QUIET:
                print(f"  ⚠ {ticker}: {e}", flush=True)
    return ergebnis


def _aus_kursen_aufbauen(kurse, tickers):
    """Minimal-Fallback: aus {ticker: preis} ein ergebnis-Dict bauen.
    yfinance ist komplett ausgefallen -> marktdaten.hole_kurs() liefert
    nur aktuelle Kurse, keine Historie. sma20/sma50 = Kurs (flat),
    uptrend=0.5, rsi=50 (neutral). Besser als gar keine Daten.
    """
    ergebnis = {}
    for ticker in tickers:
        preis = kurse.get(ticker)
        if not preis or preis <= 0:
            continue
        info = WATCHLIST.get(ticker, {})
        ergebnis[ticker] = {
            "aktuell": round(float(preis), 2),
            "sma20": round(float(preis), 2),
            "sma50": round(float(preis), 2),
            "uptrend": 0.5,
            "rsi": 50.0,
            "atr_pct": None,
            "vol_ratio": None,
            "name": info.get("name", ticker),
            "kat": info.get("kat", ""),
        }
    print(f"  ⚡ marktdaten-Fallback lieferte {len(ergebnis)} Kurse", flush=True)
    return ergebnis


# ─── KI-Ausführung ──────────────────────────────────────────
def ausführen(depot, kurs, ki_entscheidung):
    """Führt die KI-Entscheidung aus."""
    if not ki_entscheidung:
        return
    
    aktion = ki_entscheidung.get("aktion", "halten")
    konfidenz = ki_entscheidung.get("konfidenz", 50)
    grund = ki_entscheidung.get("grund", "")
    
    if konfidenz < 40:
        if not QUIET:
            print(f"   [{depot.ticker}] ⚪ KI unsicher (K:{konfidenz}) – halte", flush=True)
        return

    # 🛡 VERDRAHTUNG 2026-09-27 (Befund 4): VOR jeder Order prueft jetzt
    # risk_controller.pruefe_und_bremse(). Vorher war das EINZIGE Gate
    # "konfidenz >= 40 und bargeld > 1.0" – komplett ohne SL, TP,
    # Positionslimit und Drawdown-Lock.

    # 🛡 Drawdown-Lock: bei Ueberschreitung ist das Depot eingefroren
    _dd = depot.aktualisiere_peak(kurs)
    if depot.gesperrt:
        if not QUIET:
            print(f"   [{depot.ticker}] ⛔ {depot.gesperrt_grund}", flush=True)
        return

    # 🛡 Stop-Loss / Take-Profit: bestehende Position pruefen, BEVOR
    # eine neue Order entsteht (Befund 4: fehlte vollstaendig)
    if depot.shares > 0 and kurs > 0:
        # 01.11.2026: Trailing-Stop (exits.py) - Stop zieht mit dem Hoch
        # seit Kauf nach, faellt nie.
        try:
            import exits as _exits
            depot.stop_loss, depot.hoch_seit_kauf = _exits.nachziehen(
                depot.stop_loss, getattr(depot, "hoch_seit_kauf", None) or depot.avg_price,
                kurs, _exits.stop_faktor(depot.risk), _exits.trailing_aktiv())
        except Exception:
            pass
        if depot.stop_loss is not None and kurs <= depot.stop_loss:
            if not QUIET:
                print(f"   [{depot.ticker}] 🛑 Stop-Loss ${kurs:.2f} <= ${depot.stop_loss:.2f}", flush=True)
            _verkauf = depot.shares
            _hv = handelskosten.verkauf(_verkauf, kurs, art="spekulativ")
            depot.bargeld += _hv["erloes"]
            depot.trades.append({
                "zeit": datetime.now().isoformat(), "aktion": "verkaufen",
                "menge": round(_verkauf, 6), "preis": round(kurs, 4),
                "gebuehr": round(_hv["gebuehr"], 2),
                "grund": "stop_loss", "ki_konfidenz": konfidenz,
            })
            depot.shares = 0
            depot.avg_price = 0
            depot.stop_loss = None
            depot.take_profit = None
            depot.hoch_seit_kauf = None
            return
        if depot.take_profit is not None and kurs >= depot.take_profit:
            if not QUIET:
                print(f"   [{depot.ticker}] 🎯 Take-Profit ${kurs:.2f} >= ${depot.take_profit:.2f}", flush=True)
            _verkauf = depot.shares
            _hv = handelskosten.verkauf(_verkauf, kurs, art="spekulativ")
            depot.bargeld += _hv["erloes"]
            depot.trades.append({
                "zeit": datetime.now().isoformat(), "aktion": "verkaufen",
                "menge": round(_verkauf, 6), "preis": round(kurs, 4),
                "gebuehr": round(_hv["gebuehr"], 2),
                "grund": "take_profit", "ki_konfidenz": konfidenz,
            })
            depot.shares = 0
            depot.avg_price = 0
            depot.stop_loss = None
            depot.take_profit = None
            depot.hoch_seit_kauf = None
            return

    if aktion == "kaufen" and depot.bargeld > 1.0 and kurs > 0:
        # 01.11.2026: Earnings-Sperre (earnings.py), fail-open
        try:
            import earnings as _earn
            _gesp, _egrund = _earn.kauf_gesperrt(depot.ticker)
        except Exception:
            _gesp, _egrund = False, None
        if _gesp:
            if not QUIET:
                print(f"   [{depot.ticker}] 📅 {_egrund} - kein Kauf", flush=True)
            depot.trades.append({
                "zeit": datetime.now().isoformat(), "aktion": "kauf_blockiert",
                "menge": 0, "preis": round(kurs, 4),
                "grund": "Earnings-Sperre: " + _egrund, "ki_konfidenz": konfidenz,
            })
            return
        menge_faktor = {"voll": 1.0, "teil": 0.5, "minimal": 0.2}
        menge = ki_entscheidung.get("menge", "voll")
        # BEFUND-4-FIX: "voll" bedeutete 1.0 -> invest = depot.bargeld * 1.0,
        # also 100% des Cash in EINEN Ticker. Der Faktor ist jetzt nur noch
        # eine Obergrenze, die der Controller hart auf position_size,
        # Cash-Boden und ggf. das Hebel-ETF-Limit begrenzt.
        faktor = menge_faktor.get(menge, 0.5)

        # DECKEL-FIX: rc_pruefe() berechnet die Klemme intern MIT
        # tier und hebel (risk_controller.py:499-531). Dieser Aufruf
        # tat das nicht - er bekam den ungeklammerten Betrag zurueck
        # und blockierte sich anschliessend selbst mit
        # "betrag_ueber_limit: Betrag 33.00 > erlaubt 13.29".
        # Dieselbe Fehlerklasse wie im etf_trader.py (26fd17c).
        # Die Tier-Quelle ist dieselbe wie im Controller, damit beide
        # Seiten denselben Wert sehen.
        _tier = int(_TICKER_TO_TIER.get(depot.ticker, 2))
        _hebel = _tier in RC_HEBEL_TIERS
        try:
            import strategie as _strat
            _hebel = _hebel or _strat.ist_hebel_etf(depot.ticker, _tier)
        except Exception:
            pass
        invest = min(depot.bargeld * faktor,
                     rc_max_betrag(depot.bargeld, depot.risk,
                                   tier=_tier, hebel=_hebel))
        _res = rc_pruefe(depot.risk, ticker=depot.ticker, preis=kurs,
                         cash=depot.bargeld, depot_wert=depot.wert(kurs),
                         anzahl_positionen=1 if depot.shares > 0 else 0,
                         positionen=[depot.ticker] if depot.shares > 0 else [],
                         betrag=invest, drawdown_pct=_dd,
                         quelle="spec_trader.ausfuehren")
        if _res.blockiert:
            if not QUIET:
                print(f"   [{depot.ticker}] 🛑 Risiko-Block: {_res.reason}", flush=True)
            depot.trades.append({
                "zeit": datetime.now().isoformat(), "aktion": "kauf_blockiert",
                "menge": 0, "preis": round(kurs, 4), "grund": _res.reason,
                "ki_konfidenz": konfidenz,
            })
            return
        invest = min(invest, _res.max_betrag)
        # 01.11.2026: Handelskosten - Gebuehr und Slippage gehen vom
        # Investbetrag ab, der Einstand enthaelt sie.
        _hk = handelskosten.kauf(invest / kurs, kurs, min(invest, depot.bargeld),
                                 art="spekulativ", nachkommastellen=6)
        if _hk["abgelehnt"]:
            if not QUIET:
                print(f"   [{depot.ticker}] 🛑 {_hk['abgelehnt']}", flush=True)
            depot.trades.append({
                "zeit": datetime.now().isoformat(), "aktion": "kauf_blockiert",
                "menge": 0, "preis": round(kurs, 4),
                "grund": "Handelskosten: " + _hk["abgelehnt"],
                "ki_konfidenz": konfidenz,
            })
            return
        shares = _hk["menge"]
        
        # Penny-Stock-Filter (ausser für Hebelticker)
        if kurs < 1.0 and "3x" not in depot.name and "2x" not in depot.name:
            if not QUIET:
                print(f"   [{depot.ticker}] ⚠ Penny-Stock übersprungen (${kurs:.2f})", flush=True)
            return
        
        depot.shares += shares
        depot.avg_price = ((depot.avg_price * (depot.shares - shares)) + _hk["gesamt"]) / depot.shares if depot.shares > 0 else kurs
        depot.bargeld -= _hk["gesamt"]

        # 🛡 VERDRAHTUNG 2026-09-27: SL/TP aus dem Risk-Controller setzen
        # (vorher wurden sie in spec_trader ueberhaupt nie gespeichert).
        _rcp_s = rc_params(depot.risk)
        if depot.stop_loss is None:
            depot.stop_loss = kurs * _rcp_s["stop_loss"]
            depot.take_profit = kurs * _rcp_s["take_profit"]
        else:
            # Nachkauf: SL/TP auf den neuen Mischkurs nachziehen
            _neu = depot.avg_price
            depot.stop_loss = _neu * _rcp_s["stop_loss"]
            depot.take_profit = _neu * _rcp_s["take_profit"]

        depot.trades.append({
            "zeit": datetime.now().isoformat(),
            "aktion": "kaufen", "menge": round(shares, 6),
            "preis": round(kurs, 4), "gebuehr": round(_hk["gebuehr"], 2),
            "grund": grund,
            "ki_konfidenz": konfidenz,
        })
        # Börse als Metadatum (für Marktzeiten-Skipping)
        try:
            from boersen import boerse_fuer_ticker
            depot.exchange = boerse_fuer_ticker(depot.ticker)
        except Exception:
            depot.exchange = None
        if not QUIET:
            print(f"   [{depot.ticker}] 🟢 KI-Kauf {shares:.4f}st @${kurs:.2f} – {grund[:50]} (K:{konfidenz})", flush=True)
    
    elif aktion == "verkaufen" and depot.shares > 0 and not (kurs and kurs > 0):
        # 01.11.2026: Ohne gueltigen Kurs (Rate-Limit liefert 0) wurde die
        # Position fuer 0 verkauft. Gleiche Regel wie engine.py/paper_trader.py.
        if not QUIET:
            print(f"   [{depot.ticker}] 🛡 KEIN VERKAUF: Kurs {kurs} (Rate-Limit/Fehler) — Position behalten", flush=True)
        return

    elif aktion == "verkaufen" and depot.shares > 0:
        menge_faktor = {"voll": 1.0, "teil": 0.5, "minimal": 0.2}
        menge = ki_entscheidung.get("menge", "voll")
        faktor = menge_faktor.get(menge, 1.0)
        
        shares_verkauf = depot.shares * faktor
        _hv = handelskosten.verkauf(shares_verkauf, kurs, art="spekulativ")
        erlös = _hv["erloes"]
        depot.bargeld += erlös
        depot.shares -= shares_verkauf
        
        if depot.shares < 0.000001:
            depot.shares = 0
            depot.avg_price = 0
            # 01.11.2026: Stop/TP/Hoch zuruecksetzen - sonst erbt der naechste
            # Kauf den alten (Trailing-)Stop und wird sofort ausgestoppt.
            depot.stop_loss = None
            depot.take_profit = None
            depot.hoch_seit_kauf = None
        
        depot.trades.append({
            "zeit": datetime.now().isoformat(),
            "aktion": "verkaufen", "menge": round(shares_verkauf, 6),
            "preis": round(kurs, 4), "gebuehr": round(_hv["gebuehr"], 2),
            "grund": grund,
            "ki_konfidenz": konfidenz,
        })
        if not QUIET:
            print(f"   [{depot.ticker}] 🔴 KI-Verkauf {shares_verkauf:.4f}st @${kurs:.2f} – {grund[:50]} (K:{konfidenz})", flush=True)
    
    # Historie aktualisieren
    wert = depot.wert(force_price=kurs)
    depot.historie.append({"zeit": datetime.now().isoformat(), "wert": round(wert, 2)})


def main():
    # PHASE 5 (§9): Modus bestimmt Portfolio-Satz (shadow/paper)
    try:
        import security as _sec9
        _mode9 = _sec9.get_trading_mode(1) or "SHADOW"
    except Exception:
        _mode9 = "SHADOW"
    if _mode9 in ("PAUSED", "SUSPENDED", "REVOKED") or _mode9.startswith("LIVE"):
        if not QUIET:
            print(f"⏸ Trading-Modus {_mode9} — Spekulation-Trader ueberspringt Lauf.", flush=True)
        return
    _smode = "paper" if _mode9 == "PAPER" else "shadow"
    if not QUIET:
        print(" 🔥 Spekulation-Trader (KI-gestützt) – %d Instrumente" % len(WATCHLIST), flush=True)
    
    daten = fetch_analyse()
    if not QUIET:
        print("   Daten: %d Instrumente" % len(daten), flush=True)
    
    # KI-Daten pro Ticker sammeln
    ticker_data = []
    try:
        from boersen import ist_offen, boerse_fuer_ticker
        def ticker_markt_status(t):
            b = boerse_fuer_ticker(t)
            return "open" if ist_offen(b) else "closed"
    except Exception:
        def ticker_markt_status(t):
            return "open"
    for ticker, info in sorted(daten.items()):
        depot = SpecDepot(ticker, info["name"], info.get("kat", ""), mode=_smode)
        ticker_data.append({
            "ticker": ticker,
            "name": info["name"],
            "kurs": info["aktuell"],
            "sma20": info["sma20"],
            "sma50": info["sma50"],
            "rsi": info["rsi"],
            "shares": depot.shares,
            "avg_price": depot.avg_price,
            "bargeld": depot.bargeld,
            "start": depot.start,
            "markt": ticker_markt_status(ticker),
            "sektor": info.get("kat", ""),
            "atr_pct": info.get("atr_pct"),
            "vol_ratio": info.get("vol_ratio"),
        })

    # ── WELLEN-MODUS: Slice der Ticker (Rate-Limit-Schonung) ──
    # --welle N (0..3): verarbeite nur Ticker[N*13:(N+1)*13] -> ~13 Calls/Lauf
    # statt 49 auf einmal. Über 4 Wellen (Scheduler 30min-Takt) alle abgedeckt.
    if "--welle" in sys.argv:
        try:
            welle = int(sys.argv[sys.argv.index("--welle") + 1])
        except Exception:
            welle = 0
        slice_size = 13
        start = welle * slice_size
        ende = start + slice_size
        ticker_data = ticker_data[start:ende]
        if not QUIET:
            print("   🌊 Welle %d: Ticker %d-%d von %d" % (welle, start, ende, len(daten)), flush=True)

    # KI-Entscheidungen einholen (parallel)
    if not QUIET:
        print("   🤖 KI analysiert %d Ticker..." % len(ticker_data), flush=True)
    ki_ergebnisse = entscheide_spec_batch(ticker_data, max_workers=8)
    if not QUIET:
        anzahl = sum(1 for e in ki_ergebnisse if e.get("aktion") != "halten")
        print("   KI: %d Entscheidungen (davon %d non-Hold)" % (len(ki_ergebnisse), anzahl), flush=True)
    
    # Entscheidungen ausführen
    ergebnisse = []
    for i, ticker_info in enumerate(ticker_data):
        ticker = ticker_info["ticker"]
        info = daten[ticker]
        depot = SpecDepot(ticker, info["name"], info.get("kat", ""), mode=_smode)
        depot.ki_letzte = ki_ergebnisse[i]
        
        if ki_ergebnisse[i]:
            ausführen(depot, info["aktuell"], ki_ergebnisse[i])
        
        depot.speichern()
        
        wert = depot.wert(force_price=info["aktuell"])
        rendite = (wert / depot.start - 1) * 100
        ergebnisse.append((ticker, wert, rendite, depot.shares, len(depot.trades)))
    
    if not QUIET:
        print("\n   Ergebnisse:")
        for ticker, wert, rendite, shares, trades in ergebnisse:
            farbe = "🟢" if rendite > 0 else ("🔴" if rendite < -0.5 else "⚪")
            kat = WATCHLIST[ticker]["kat"] if ticker in WATCHLIST else ""
            print(" %s %-5s $%6.2f %+7.2f%% %5.2f %5d %s" % (farbe, ticker, wert, rendite, shares, trades, kat), flush=True)

    # Status speichern
    try:
        from trader_status import update_status
        ki_anzahl = 0
        for t in os.listdir(os.path.join(BASE, "spec_depots")):
            if t.endswith(".json"):
                try:
                    with open(os.path.join(BASE, "spec_depots", t), encoding="utf-8") as f:
                        d = json.load(f)
                    if d.get("start", 0) > 0:
                        ki_anzahl += 1
                except Exception:
                    pass
        update_status("spec_trader", {"depots": ki_anzahl})
    except Exception as e:
        if not QUIET:
            print(f"⚠ Status-Fehler: {e}", file=sys.stderr)

    # System-Log
    try:
        from system_log import log_eintrag
        log_eintrag("spec", f"Spec-Lauf: {ki_anzahl} Depots analysiert", "ok")
    except Exception:
        pass


if __name__ == "__main__":
    main()
