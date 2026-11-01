"""broker_simulator.py — Phase 9: Broker-Simulator + Sandbox-Adapter.

AUFTRAG §Phase 9: Broker-Simulator und Sandbox-Adapter (KEIN echter Broker).
PAPER_ONLY gilt: dieser Simulator führt KEINE echten Orders aus, keine echten
API-Keys, keine Netzwerk-Calls zu Brokern. Er simuliert Fill/Rejection für
Tests + späteres Live-Gate (Phase 11).

Echter Broker-Adapter (Alpaca etc.) ist Phase 9 erst NACH Phase 14-Freigabe
und wird hier nur als Interface vorbereitet (BrokerAdapter ABC).

Aufruf: from broker_simulator import BrokerSimulator, BrokerAdapter
"""

import os, json, time, uuid
from datetime import datetime
from abc import ABC, abstractmethod

BASE = os.path.dirname(os.path.abspath(__file__))


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class BrokerAdapter(ABC):
    """Interface für echte Broker (Phase 14+). Hier nur Definition, keine Impl."""

    @abstractmethod
    def submit_order(self, order):
        """Sendet Order. Returns Fill- oder Reject-Objekt."""
        raise NotImplementedError

    @abstractmethod
    def get_positions(self):
        raise NotImplementedError

    @abstractmethod
    def get_status(self):
        """UNKNOWN / CONNECTED / ERROR (Auftrag §Broker: Status UNKNOWN)."""
        raise NotImplementedError


class BrokerSimulator(BrokerAdapter):
    """Simuliert einen Broker ohne echte Orders.

    - Fill bei ausreichendem Cash + gültigem Ticker.
    - Reject bei unzureichendem Cash / Kill-Switch aktiv.
    - Schreibt fills in `sim_broker_fills.json` (isoliert vom Paper-Trading).
    """

    def __init__(self, cash=100.0, live_system=None):
        self.cash = cash
        self.live_system = live_system  # LiveSystem für Kill-Switch-Check
        self.positions = {}
        self.fills_pf = os.path.join(BASE, "sim_broker_fills.json")

    def get_status(self):
        if self.live_system and self.live_system.ist_gestoppt:
            return "SAFE_STOP"  # Kill-Switch aktiv -> kein Handel
        return "CONNECTED (SIM)"

    def submit_order(self, order):
        """order: {ticker, side:'buy'|'sell', qty, price}"""
        ticker = order.get("ticker")
        side = order.get("side")
        qty = float(order.get("qty", 0))
        price = float(order.get("price", 0))
        order_id = uuid.uuid4().hex[:12]

        # Kill-Switch (Phase 11): keine Orders während SAFE_STOP
        if self.live_system and self.live_system.ist_gestoppt:
            return self._reject(order_id, ticker, side, qty, "SAFE_STOP aktiv")

        if side == "buy":
            kosten = qty * price
            if kosten > self.cash:
                return self._reject(order_id, ticker, side, qty, "unzureichendes Cash")
            self.cash -= kosten
            self.positions[ticker] = self.positions.get(ticker, 0) + qty
            return self._fill(order_id, ticker, side, qty, price, "SIM")
        elif side == "sell":
            held = self.positions.get(ticker, 0)
            if qty > held:
                return self._reject(order_id, ticker, side, qty, "nicht genug Position")
            self.positions[ticker] = held - qty
            self.cash += qty * price
            return self._fill(order_id, ticker, side, qty, price, "SIM")
        return self._reject(order_id, ticker, side, qty, "unbekannte Seite")

    def _fill(self, oid, ticker, side, qty, price, prov):
        fill = {
            "order_id": oid, "ticker": ticker, "side": side, "qty": qty,
            "price": price, "status": "FILLED", "provider": prov,
            "zeit": _now(), "cash_nach": round(self.cash, 2),
        }
        self._log(fill)
        return fill

    def _reject(self, oid, ticker, side, qty, grund):
        rej = {
            "order_id": oid, "ticker": ticker, "side": side, "qty": qty,
            "status": "REJECTED", "grund": grund, "zeit": _now(),
        }
        self._log(rej)
        return rej

    def _log(self, eintrag):
        log = []
        if os.path.exists(self.fills_pf):
            try:
                log = json.load(open(self.fills_pf, encoding="utf-8"))
            except Exception:
                log = []
        log.append(eintrag)
        json.dump(log[-1000:], open(self.fills_pf, "w", encoding="utf-8"),
                  indent=2, ensure_ascii=False)

    def get_positions(self):
        return dict(self.positions)

    def reconcile(self, depot_json_pfad):
        """Phase 10: Reconciliation — gleicht Sim-Positionen mit Depot-Datei ab.
        Returns: {match: bool, unterschiede: [...], sim_cash, depot_bargeld}."""
        try:
            d = json.load(open(depot_json_pfad, encoding="utf-8"))
        except Exception as e:
            return {"match": False, "fehler": str(e)}
        # Depot-Positionen sammeln (Format B: positions-dict)
        dep_pos = {}
        pos = d.get("positions", {})
        if isinstance(pos, dict):
            for t, p in pos.items():
                dep_pos[t] = (p.get("shares", 0) or 0)
        # Format A: Spec top-level shares
        if d.get("ticker") and d.get("shares"):
            dep_pos[d["ticker"]] = d["shares"]
        unterschiede = []
        alle = set(self.positions) | set(dep_pos)
        for t in alle:
            sim_q = self.positions.get(t, 0)
            dep_q = dep_pos.get(t, 0)
            if abs(sim_q - dep_q) > 1e-6:
                unterschiede.append({"ticker": t, "sim": sim_q, "depot": dep_q})
        return {
            "match": len(unterschiede) == 0,
            "unterschiede": unterschiede,
            "sim_cash": round(self.cash, 2),
            "depot_bargeld": d.get("bargeld", 0),
        }


if __name__ == "__main__":
    sim = BrokerSimulator(cash=200)
    print("Status:", sim.get_status())
    print("BUY AAPL:", sim.submit_order({"ticker": "AAPL", "side": "buy", "qty": 2, "price": 10}))
    print("SELL AAPL:", sim.submit_order({"ticker": "AAPL", "side": "sell", "qty": 1, "price": 11}))
    print("Cash:", sim.cash, "| Pos:", sim.get_positions())
