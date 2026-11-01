"""
MarketSnapshot (Roadmap Punkt 5, v2.54.0) — einheitliches Marktdatenobjekt.

- Liest neuesten Stand pro Ticker aus markt_daten (SQLite)
- Datenalter-Gate: frisch (< 3 Tage) vs. veraltet
- Snapshot-ID für KI-Entscheidung (Traceability)
- Providerqualität + Zeitstempel

Aufruf: from market_snapshot import MarketSnapshot
"""
import os, json, sqlite3, hashlib
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "micro_trader.db")
MAX_ALTER = timedelta(days=3)  # wie paper_eligibility (markt_daten < 3 Tage)


class MarketSnapshot:
    def __init__(self, ticker_liste=None, max_alter=MAX_ALTER, tenant_id=1, workspace_id=None):
        self.max_alter = max_alter
        self.zeit = datetime.now()
        self.snapshot_id = None
        self.ticker_liste = ticker_liste or []
        self.tenant_id = tenant_id
        self.workspace_id = workspace_id
        self.daten = {}
        self.alter_tage = {}
        self.alle_frisch = False
        self._laden()

    def _laden(self):
        if not self.ticker_liste:
            return
        try:
            conn = sqlite3.connect(DB)
            c = conn.cursor()
            for t in self.ticker_liste:
                row = c.execute(
                    "SELECT kurs, rsi, sma20, sma50, zeit FROM markt_daten "
                    "WHERE ticker=? ORDER BY zeit DESC LIMIT 1", (t,)
                ).fetchone()
                if row:
                    kurs, rsi, s20, s50, zeit = row
                    try:
                        ts = datetime.strptime(zeit, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        ts = self.zeit
                    alter = self.zeit - ts
                    self.daten[t] = {
                        "kurs": kurs, "rsi": rsi, "sma20": s20, "sma50": s50,
                        "zeit": zeit, "alter_tage": round(alter.total_seconds() / 86400, 2),
                    }
                    self.alter_tage[t] = alter.total_seconds() / 86400
            conn.close()
        except Exception as e:
            print(f"MarketSnapshot-Fehler: {e}")
        # Snapshot-ID aus Hash der Daten
        payload = json.dumps({t: self.daten.get(t, {}).get("kurs") for t in self.ticker_liste},
                             sort_keys=True)
        self.snapshot_id = hashlib.md5(payload.encode()).hexdigest()[:12]
        self.alle_frisch = bool(self.daten) and all(a <= self.max_alter.total_seconds() / 86400
                                                    for a in self.alter_tage.values())

    def kontext(self):
        """Kompakter Text-Block fuer den KI-Prompt."""
        if not self.daten:
            return "MARKTDATEN: kein Snapshot verfügbar (markt_daten leer)"
        alt = "frisch" if self.alle_frisch else "VERALTET"
        return (f"MARKTDATEN-SNAPSHOT {self.snapshot_id} [{alt}]: "
                + ", ".join(f"{t}={self.daten[t]['kurs']:.2f}" for t in self.ticker_liste[:15]
                            if t in self.daten))


def hole_snapshot(ticker_liste):
    """Bequemlichkeits-Funktion: erzeugt Snapshot + Kontext."""
    s = MarketSnapshot(ticker_liste)
    return s
