#!/usr/bin/env python3
"""
Micro-Trader – Dein Geld vermehren, ein Trade nach dem anderen
===============================================================
Du sagst mir einen Betrag (z.B. 50€), ich such passende Aktien raus und trade.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from tabulate import tabulate
import json, os, sys, requests

# VERDRAHTUNG 2026-09-27 (Rebuild Risiko-Controller): paper_trader hatte laut
# grep NULL Vorkommen von stop_loss/take_profit/max_positions/drawdown – also
# keinerlei Risikokontrolle. Ausserdem verkaufte verkaufen() bei Kurs <= 0
# (yfinance-Rate-Limit) die Position fuer 0 EUR. Beides ist jetzt behoben.
from risk_controller import (
    params as rc_params,
    pruefe_und_bremse as rc_pruefe,
    max_betrag as rc_max_betrag,
    drawdown_pct_von as rc_drawdown_pct,
)

DATEI_DEPOT = "paper_depot.json"

# Risikostufe des Paper-Depots. Ueber PAPER_RISK (env) anpassbar, Default 50.
try:
    PAPER_RISK = int(os.environ.get("PAPER_RISK", "50"))
except (TypeError, ValueError):
    PAPER_RISK = 50

# ─── Erweiterte Watchlist ─────────────────────────────────────
# Große Auswahl: bekannte Aktien + günstigere Werte
WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "AMD", "INTC",
    "JPM", "BAC", "GS", "V", "MA", "PYPL", "SQ",
    "JNJ", "PFE", "MRK", "ABBV", "UNH", "CVS",
    "WMT", "COST", "HD", "LOW", "MCD", "SBUX", "NKE", "DIS",
    "XOM", "CVX", "COP", "SHEL", "BP",
    "KO", "PEP", "PG", "BA", "CAT", "GE",
    "IBM", "CSCO", "ORCL", "CRM", "ADBE", "NFLX",
    "BABA", "JD", "NIO", "PLTR", "SOFI", "RIVN", "LCID",
    "F", "GM", "AAL", "UAL", "DAL", "CCL", "RCL", "NCLH",
    "AMC", "GME", "BB", "MARA", "COIN", "RIOT", "CAN", "SNAP",
    "DKNG", "PENN", "MGM", "WBD", "PARA", "C", "WFC", "T", "VZ",
]

# ─── Scanner ──────────────────────────────────────────────────
def scan_neuigkeiten():
    """Sucht nach besonders günstigen/trendstarken Aktien."""
    print("  🔍 Scanne Markt nach vielversprechenden Aktien...\n")
    funde = []

    for sym in WATCHLIST:
        try:
            df = yf.download(sym, period="3mo", progress=False, auto_adjust=True)
            if df.empty:
                continue

            # Close-Series holen (yfinance 1.5+ MultiIndex)
            if isinstance(df.columns, pd.MultiIndex):
                close = df["Close"][sym].dropna()
            else:
                close = df["Close"].dropna()

            if len(close) < 20:
                continue

            aktuell = float(close.iloc[-1])
            sma20 = float(close.rolling(20).mean().iloc[-1])
            sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else aktuell

            # RSI
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi = float((100 - (100 / (1 + rs))).iloc[-1]) if not pd.isna(rs.iloc[-1]) else 50

            # Volumen
            if isinstance(df.columns, pd.MultiIndex):
                vol = df["Volume"][sym]
            else:
                vol = df["Volume"]
            avg_vol = float(vol.tail(20).mean())

            change_1w = ((aktuell / float(close.iloc[-5])) - 1) * 100 if len(close) >= 5 else 0
            change_1m = ((aktuell / float(close.iloc[-21])) - 1) * 100 if len(close) >= 21 else 0

            funde.append({
                "symbol": sym, "kurs": aktuell,
                "sma20": sma20, "sma50": sma50,
                "rsi": rsi, "volume": avg_vol,
                "1w": change_1w, "1m": change_1m,
                "auf_trend": aktuell > sma50,
                "score": 0  # wird gleich berechnet
            })
        except:
            continue

    return funde

def bewerte_aktien(aktien, budget):
    """Bewertet Aktien nach Eignung für unser Budget."""
    for a in aktien:
        score = 0
        # Je günstiger, desto besser (mehr Stücke kaufbar)
        if a["kurs"] < budget * 0.3:
            score += 30
        elif a["kurs"] < budget * 0.5:
            score += 20
        elif a["kurs"] < budget:
            score += 10
        else:
            score -= 10

        # Trend
        if a["auf_trend"]:
            score += 25
        if a["1m"] > 5:
            score += 15
        elif a["1m"] > 0:
            score += 5

        # RSI (nicht überkauft, nicht überverkauft)
        if 40 <= a["rsi"] <= 60:
            score += 20
        elif 30 <= a["rsi"] <= 70:
            score += 10

        # Momentum
        if a["1w"] > 2:
            score += 10

        # Volumen
        if a["volume"] > 5_000_000:
            score += 10
        elif a["volume"] > 1_000_000:
            score += 5

        a["score"] = score
    return aktien

def vorschlaege_zeigen(aktien, budget, depot):
    """Zeigt die Top-Vorschläge an und fragt ob gehandelt werden soll."""
    aktien.sort(key=lambda x: x["score"], reverse=True)
    top = [a for a in aktien if a["score"] > 20][:8]

    if not top:
        print("  ⚠ Keine überzeugenden Aktien gefunden. Senke Kriterien...")
        top = sorted(aktien, key=lambda x: x["score"], reverse=True)[:5]

    rows = []
    for a in top:
        signal = "🟢 KAUF" if a["auf_trend"] else "🔴"
        stuecke = max(1, int(budget * 0.3 / a["kurs"]))
        invest = stuecke * a["kurs"]
        rows.append([
            a["symbol"], f"${a['kurs']:.2f}", f"{a['1w']:+.1f}%", f"{a['1m']:+.1f}%",
            f"{a['rsi']:.0f}", f"{invest:.0f}€ ({stuecke}x)", a["score"]
        ])

    print("  ─── Top-Vorschläge ───")
    print(tabulate(rows,
                   headers=["Symbol", "Kurs", "1W%", "1M%", "RSI", "Invest", "Score"],
                   tablefmt="rounded_grid", numalign="right"))
    return top

# ─── Depot ──────────────────────────────────────────────────────
class Depot:
    def __init__(self, start=100, risk=None):
        self.bargeld = start
        self.start_wert = start
        self.positions = {}
        self.trades = []
        # VERDRAHTUNG 2026-09-27: Risikostufe + Drawdown-Zustand
        self.risk = PAPER_RISK if risk is None else int(risk)
        self.peak_wert = start
        self.gesperrt = False
        self.gesperrt_grund = ""

    def params(self):
        """Risikoparameter dieses Depots (aus dem Risk-Controller)."""
        return rc_params(self.risk)

    def drawdown_pct(self, kurse=None):
        w = self.depotwert(kurse)
        if w > self.peak_wert:
            self.peak_wert = w
        return rc_drawdown_pct(self.peak_wert, w)

    def laden(self):
        if os.path.exists(DATEI_DEPOT):
            with open(DATEI_DEPOT) as f:
                d = json.load(f)
                self.bargeld = d.get("bargeld", self.start_wert)
                self.start_wert = d.get("start_wert", self.start_wert)
                self.positions = {k: v for k, v in d.get("positions", {}).items() if v["shares"] > 0}
                self.trades = d.get("trades", [])
                self.risk = d.get("risk", self.risk)
                self.peak_wert = d.get("peak_wert", self.start_wert)
                self.gesperrt = d.get("gesperrt", False)
                self.gesperrt_grund = d.get("gesperrt_grund", "")
                # Altbestand ohne SL/TP: aus dem Controller nachziehen
                _p = self.params()
                for _sym, _pos in self.positions.items():
                    if "stop_loss" not in _pos:
                        _pos["stop_loss"] = _pos["avg_price"] * _p["stop_loss"]
                    if "take_profit" not in _pos:
                        _pos["take_profit"] = _pos["avg_price"] * _p["take_profit"]

    def speichern(self):
        with open(DATEI_DEPOT, "w") as f:
            json.dump({"bargeld": self.bargeld, "start_wert": self.start_wert,
                       "positions": self.positions, "trades": self.trades,
                       # VERDRAHTUNG 2026-09-27: Risikozustand mitpersistieren
                       "risk": self.risk,
                       "peak_wert": round(self.peak_wert, 4),
                       "gesperrt": self.gesperrt,
                       "gesperrt_grund": self.gesperrt_grund,
                       "tenant_id": int(getattr(self, "tenant_id", 1) or 1)}, f, indent=2)  # PHASE 3 §2.3

    def kaufen(self, symbol, kurs, budget_anteil=0.3):
        """Kauft mit budget_anteil des verfügbaren Bargelds – durch den
        Risk-Controller begrenzt (Positionslimit, Cash-Boden, SL/TP)."""
        # 🛡 BEFUND-5-FIX: Kurs-Guard VOR dem Rechnen. Bei yfinance-Rate-Limit
        # kommt 0 oder None zurueck; ein Kauf auf Kurs 0 waere blind.
        try:
            kurs = float(kurs)
        except (TypeError, ValueError):
            return False, "Kurs ungueltig (%r) - kein Kauf" % (kurs,)
        if kurs <= 0:
            return False, "Kurs %s ist <= 0 (Rate-Limit/Fehler) - kein Kauf" % kurs

        p = self.params()

        # 🛡 Drawdown-Lock
        dd = self.drawdown_pct()
        if dd >= p["max_drawdown"]:
            self.gesperrt = True
            self.gesperrt_grund = ("Drawdown %.1f%% >= Limit %.1f%% (Risk %d)"
                                   % (dd, p["max_drawdown"], self.risk))
            return False, "⛔ " + self.gesperrt_grund

        # 🛡 Zentraler Eintritt: Positionslimit + Cash-Boden + Betrag.
        # budget_anteil ist ein WUNSCH des Aufrufers, deshalb wird bewusst
        # KEIN betrag= uebergeben: der Controller liefert stattdessen den
        # erlaubten Maximalbetrag (position_size, Cash-Boden, ggf. Hebel-Limit)
        # zurueck, und budget_anteil deckelt zusätzlich von oben.
        res = rc_pruefe(self.risk, ticker=symbol, preis=kurs, cash=self.bargeld,
                        depot_wert=self.depotwert(), anzahl_positionen=len(self.positions),
                        positionen=list(self.positions),
                        drawdown_pct=dd, quelle="paper_trader.kaufen")
        if res.blockiert:
            return False, "🛑 Risiko-Block: " + res.reason

        betrag = min(self.bargeld * budget_anteil, res.max_betrag)
        if betrag < 10:
            return False, "Betrag zu klein (<10€)"

        shares = round(betrag / kurs, 4)
        kosten = shares * kurs
        if kosten > self.bargeld:
            shares = round(self.bargeld * 0.95 / kurs, 4)
            kosten = shares * kurs
        if kosten < 5:
            return False, "Selbst minimale Position zu klein"

        self.bargeld -= kosten
        if symbol in self.positions:
            alt = self.positions[symbol]
            gesamt = alt["shares"] * alt["avg_price"] + kosten
            neue_shares = alt["shares"] + shares
            self.positions[symbol] = {"shares": neue_shares, "avg_price": gesamt / neue_shares,
                                      "stop_loss": (gesamt / neue_shares) * p["stop_loss"],
                                      "take_profit": (gesamt / neue_shares) * p["take_profit"]}
        else:
            self.positions[symbol] = {"shares": shares, "avg_price": kurs,
                                      "stop_loss": kurs * p["stop_loss"],
                                      "take_profit": kurs * p["take_profit"]}

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.trades.append({"zeit": ts, "symbol": symbol, "side": "BUY",
                            "shares": shares, "price": round(kurs, 2),
                            "value": round(kosten, 2), "trade_id": len(self.trades) + 1})
        return True, f"Gekauft {shares:.4f} {symbol} @ ${kurs:.2f} (${kosten:.2f})"

    def verkaufen(self, symbol, kurs, grund="manuell"):
        # 🛡 BEFUND-5-FIX (KRITISCH): es gab KEINEN Guard gegen kurs <= 0.
        # Bei einem yfinance-Rate-Limit lieferte hole_kurs() 0, die Position
        # wurde fuer 0 EUR verkauft, del positions[symbol] riss sie aus dem
        # Depot und der Depotwert stuerzte ein. Jetzt: kein Verkauf ohne Kurs.
        try:
            kurs = float(kurs)
        except (TypeError, ValueError):
            return False, "Kurs ungueltig (%r) - Position behalten" % (kurs,)
        if kurs <= 0:
            self.trades.append({
                "zeit": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "symbol": symbol, "side": "SELL_BLOCKED", "shares": 0,
                "price": kurs, "value": 0.0,
                "grund": "Kurs <= 0 (Rate-Limit) - Verkauf verweigert",
                "trade_id": len(self.trades) + 1})
            return False, ("🛑 KEIN VERKAUF %s: Kurs %s (Rate-Limit/Fehler) - "
                           "Position behalten" % (symbol, kurs))
        if symbol not in self.positions:
            return False, "Position nicht vorhanden"
        pos = self.positions[symbol]
        erloes = pos["shares"] * kurs
        gewinn = erloes - (pos["shares"] * pos["avg_price"])
        self.bargeld += erloes

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.trades.append({"zeit": ts, "symbol": symbol, "side": "SELL",
                            "shares": pos["shares"], "price": round(kurs, 2),
                            "value": round(erloes, 2), "pnl": round(gewinn, 2),
                            "trade_id": len(self.trades) + 1})
        del self.positions[symbol]
        return True, f"Verkauft {pos['shares']:.4f} {symbol} @ ${kurs:.2f} (PnL: ${gewinn:+.2f})"

    def depotwert(self, kurse=None):
        # VERDRAHTUNG 2026-09-27: Default None, und fehlende Kurse fallen auf
        # den Einstandskurs zurueck statt auf 0 (sonst wertete ein
        # Rate-Limit die Position als wertlos und riss den Depotwert ein).
        wert = self.bargeld
        for s, p in self.positions.items():
            k = (kurse or {}).get(s)
            if k is None or k <= 0:
                k = p["avg_price"]
            wert += p["shares"] * k
        return wert

    def rendite(self, kurse):
        return (self.depotwert(kurse) / self.start_wert - 1) * 100 if self.start_wert > 0 else 0

# ─── Strategie-Signal ─────────────────────────────────────────
def signal(close):
    if len(close) < 50:
        return 0
    aktuell = close.iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = float((100 - (100 / (1 + rs))).iloc[-1]) if not pd.isna(rs.iloc[-1]) else 50

    if aktuell > sma50 and rsi < 75:
        return 1
    elif aktuell < sma50 and rsi > 25:
        return -1
    return 0

# ─── Hauptprogramm ──────────────────────────────────────────────
def main():
    # Budget: wenn angegeben → neues Depot; wenn nicht → existierendes fortsetzen
    quiet = "--quiet" in sys.argv
    neues_depot = False
    if len(sys.argv) > 1:
        try:
            budget = float(sys.argv[1].replace("€", "").replace("$", "").replace(",", "."))
            neues_depot = True
        except:
            budget = 50.0
    else:
        budget = 50.0  # Fallback

    depot = Depot(budget)
    depot.laden()
    if neues_depot or not depot.trades:
        # Neues Depot initialisieren
        depot.bargeld = budget
        depot.start_wert = budget
        depot.positions = {}
        depot.trades = []
        titel = f"{budget:>5.0f}€ im Einsatz!"
    else:
        # Bestehendes Depot fortsetzen – Budget aus Depot nehmen
        budget = depot.bargeld + sum(p["shares"] * p["avg_price"] for p in depot.positions.values())
        titel = "↻ Depot fortsetzen"
        print(f"  ↻ Weiter mit Depot: ${depot.bargeld:.2f} Cash, {len(depot.positions)} Position(en)")

    print(f"""
  ╔═══════════════════════════════════════════════╗
  ║    📈  MICRO-TRADER  —  {titel:<15s}  ║
  ╠═══════════════════════════════════════════════╣
  ║  Ich such passende Aktien und trade für dich  ║
  ╚═══════════════════════════════════════════════╝""")

    # Markt scannen
    alle = scan_neuigkeiten()
    bewertet = bewerte_aktien(alle, budget)
    top = vorschlaege_zeigen(bewertet, budget, depot)

    # Aktuelle Kurse für Depotberechnung
    kurse = {}

    print(f"\n  ─── Trades ───")
    trades_heute = 0

    for a in top[:4]:  # Top 4 anschauen
        sym = a["symbol"]
        # Live-Kurs holen
        try:
            df = yf.download(sym, period="5d", progress=False, auto_adjust=True)
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                close = df["Close"][sym].dropna()
            else:
                close = df["Close"].dropna()
            if close.empty:
                continue
            kurs = float(close.iloc[-1])
            kurse[sym] = kurs
        except:
            kurse[sym] = a["kurs"]
            kurs = a["kurs"]

        sig = a["auf_trend"]

        # Bestehende Positionen checken
        if sym in depot.positions:
            # Haben wir schon eine Position -> Signale prüfen
            try:
                df = yf.download(sym, period="3mo", progress=False, auto_adjust=True)
                if isinstance(df.columns, pd.MultiIndex):
                    cs = df["Close"][sym].dropna()
                else:
                    cs = df["Close"].dropna()
                sig_v = signal(cs)
                if sig_v == -1:
                    ok, msg = depot.verkaufen(sym, kurs)
                    if ok:
                        print(f"  🔴 {msg}")
                        trades_heute += 1
                else:
                    # Halten, Rebalancing? Nein, lassen
                    pos = depot.positions[sym]
                    gewinn = ((kurs / pos["avg_price"]) - 1) * 100
                    # 🛡 VERDRAHTUNG 2026-09-27 (Befund 5): statt des
                    # festen -15% kommt jetzt der Stop-Loss der Position aus
                    # dem Risk-Controller (pro Risikostufe verschieden).
                    sl = pos.get("stop_loss", pos["avg_price"] * depot.params()["stop_loss"])
                    tp = pos.get("take_profit", pos["avg_price"] * depot.params()["take_profit"])
                    if kurs <= sl:
                        ok, msg = depot.verkaufen(sym, kurs, grund="stop_loss")
                        if ok:
                            print(f"  🛑 Stop-Loss: {msg}")
                            trades_heute += 1
                    elif kurs >= tp:
                        ok, msg = depot.verkaufen(sym, kurs, grund="take_profit")
                        if ok:
                            print(f"  🎯 Take-Profit: {msg}")
                            trades_heute += 1
            except:
                pass
        elif sig and sym not in depot.positions:
            # Neu-Kauf
            ok, msg = depot.kaufen(sym, kurs)
            if ok:
                print(f"  🟢 {msg}")
                trades_heute += 1

    # Nachkaufen: wenn unter 20% invested, kauf die beste Gelegenheit
    depotwert_aktuell = depot.depotwert(kurse) if kurse else depot.bargeld
    invested = depotwert_aktuell - depot.bargeld
    invest_quote = (invested / depotwert_aktuell * 100) if depotwert_aktuell > 0 else 0

    if invest_quote < 15 and trades_heute == 0:
        # Nochmal die beste Chance nehmen
        for a in top[:2]:
            if a["symbol"] not in depot.positions and a["auf_trend"]:
                kurs = kurse.get(a["symbol"], a["kurs"])
                ok, msg = depot.kaufen(a["symbol"], kurs, budget_anteil=0.4)
                if ok:
                    print(f"  🟢 [Nachkauf] {msg}")
                    trades_heute += 1
                    break

    if trades_heute == 0:
        if quiet:
            print("  ⚪ Nichts zu tun.")
            depot.speichern()
            return
        print("  ⚪ Keine neuen Trades – Positionen laufen.")

    # ─── Depot-Status ──────────────────────────────────────────
    depotwert = depot.depotwert(kurse) if kurse else depot.bargeld
    pnl = depotwert - depot.start_wert
    rendite = (depotwert / depot.start_wert - 1) * 100 if depot.start_wert > 0 else 0

    pos_rows = []
    for s, p in depot.positions.items():
        k = kurse.get(s, 0)
        wert = p["shares"] * k
        kostb = p["shares"] * p["avg_price"]
        gewinn = ((k / p["avg_price"]) - 1) * 100 if p["avg_price"] > 0 else 0
        pos_rows.append([s, f"{p['shares']:.4f}", f"${p['avg_price']:.2f}",
                        f"${k:.2f}", f"${wert:.2f}", f"{gewinn:+.2f}%"])

    print(f"\n  ─── Depot ───")
    print(f"  💰 Bargeld:       ${depot.bargeld:>8.2f}  ({depot.bargeld/depotwert*100:.0f}%)")
    if pos_rows:
        print(f"  📊 Positionen:")
        print(tabulate(pos_rows,
                       headers=["Symbol", "Shares", "Ø-Kauf", "Kurs", "Wert", "Gewinn"],
                       tablefmt="simple", numalign="right"))
    else:
        print(f"  📭 Keine offenen Positionen")
    print(f"  ───────────────────────────")
    print(f"  📈 Depotwert:     ${depotwert:>8.2f}")
    print(f"  📉 PnL:           ${pnl:>+8.2f}  ({rendite:+.2f}%)")

    # ─── Letzte Trades ──────────────────────────────────────────
    if depot.trades:
        letzte = depot.trades[-6:]
        t_rows = []
        for t in reversed(letzte):
            s = "🟢" if t["side"] == "BUY" else "🔴"
            pnl_s = f"${t.get('pnl',0):+.2f}" if "pnl" in t else ""
            t_rows.append([t.get("trade_id", ""), s, t["symbol"], t["side"],
                          f"{t['shares']:.2f}", f"${t['price']:.2f}", pnl_s, t["zeit"]])
        print(f"\n  ─── Letzte Trades ({len(depot.trades)} gesamt) ───")
        print(tabulate(t_rows,
                       headers=["#", "", "Sym", "Side", "Shares", "Price", "PnL", "Zeit"],
                       tablefmt="simple"))

    depot.speichern()

    print(f"""
  ╔═══════════════════════════════════════════════╗
  ║  💎  Depot: ${depotwert:>7.2f}  |  PnL: ${pnl:>+6.2f} ({rendite:+.2f}%)  ║
  ║  Nächster Lauf: python paper_trader.py [BETRAG]║
  ╚═══════════════════════════════════════════════╝""")

if __name__ == "__main__":
    main()
