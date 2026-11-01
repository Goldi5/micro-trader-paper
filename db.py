#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Micro-Trader Analyse-Datenbank (SQLite).

Sekundaerer Store fuer schnelles Auslesen + Quer-Analysen.
Primary bleiben die JSON-Depot-Dateien; diese DB spiegelt sie regelmaessig
(_sync()) fuer Dashboard/Reports/Auswertungen. Kein Server noetig.

Schemas:
  trades          Alle Ausfuehrungen (Aktien/ETF/Spec)
  ki_decisions    Alle KI-Entscheidungen (ki_log.json)
  depot_snapshot  Wert-Stand pro Depot + Zeit
  markt_daten     Kurs/RSI/SMA pro Ticker + Zeit

Nutzung:
  from db import MTDB
  db = MTDB()            # oeffnet micro_trader.db
  db.sync()              # spiegelt alle JSONs -> DB
  db.trades_letzte(7)    # alle Trades der letzten 7 Tage
  db.ki_aktionen_vert()  # Verteilung kaufen/verkaufen/halten
"""
import os, json, sqlite3, glob
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PFAD = os.path.join(BASE, "micro_trader.db")

# Erlaubte Sortierrichtungen fuer ORDER BY. Alles andere wird verworfen —
# verhindert SQL-Injection ueber den order-Parameter (frueher direkt in einen
# f-string interpoliert, u.a. mit Zugriff auf fremde Tabellen wie secret_store).
ORDER_RICHTUNGEN = ("ASC", "DESC")


def _safe_order(order):
    """Whitelist fuer ORDER BY-Richtung. Unbekanntes -> DESC (Default).

    Keine Spaltennamen, keine Ausdruecke, keine Subqueries: nur die zwei
    zulaessigen Schluesselwoerter. Vergleiche bewusst case-insensitiv
    grossgeschrieben, damit die Semantik unveraendert bleibt.
    """
    v = (order or "").strip().upper()
    return v if v in ORDER_RICHTUNGEN else "DESC"


class MTDB:
    def __init__(self, pfad=DB_PFAD):
        self.pfad = pfad
        self.conn = sqlite3.connect(pfad)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._init_trading_mode_tables()
        self._init_paper_tables()
        self._init_provider_tables()
        self._init_secret_store()
        self._init_risk_tables()
        self._init_rule_tables()
        self._init_approval_tables()
        self._migrate_schema()

    # ── PHASE 8: Secret-Store (tenant-isoliert, kein global .env) ──
    def _init_secret_store(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS secret_store (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            secret_key TEXT NOT NULL,
            secret_value TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tenant_id, secret_key)
        );
        CREATE INDEX IF NOT EXISTS idx_ss_tenant
            ON secret_store(tenant_id);
        """)

    # ── PHASE 10: Tenant-Scoped Risikogrenzen (statt globaler settings.json risk_parameter) ──
    def _init_risk_tables(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS tenant_risk_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            risk_mode TEXT NOT NULL DEFAULT 'moderate',
            position_size REAL DEFAULT 0.35,
            stop_loss REAL DEFAULT 0.92,
            take_profit REAL DEFAULT 1.12,
            drawdown_limit REAL DEFAULT 0.20,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tenant_id, risk_mode)
        );
        CREATE INDEX IF NOT EXISTS idx_trl_tenant
            ON tenant_risk_limits(tenant_id);
        """)
        self.conn.commit()

    def risk_set(self, tenant_id, risk_mode, position_size=None, stop_loss=None,
                 take_profit=None, drawdown_limit=None):
        """PHASE 10: Tenant-Scoped Risikogrenze setzen (Partial-Update)."""
        cur = self.conn.execute(
            "SELECT * FROM tenant_risk_limits WHERE tenant_id = ? AND risk_mode = ?",
            (tenant_id, risk_mode))
        row = cur.fetchone()
        if row:
            if position_size is None: position_size = row["position_size"]
            if stop_loss is None: stop_loss = row["stop_loss"]
            if take_profit is None: take_profit = row["take_profit"]
            if drawdown_limit is None: drawdown_limit = row["drawdown_limit"]
            self.conn.execute(
                "UPDATE tenant_risk_limits SET position_size=?, stop_loss=?, "
                "take_profit=?, drawdown_limit=?, updated_at=datetime('now') "
                "WHERE tenant_id=? AND risk_mode=?",
                (position_size, stop_loss, take_profit, drawdown_limit, tenant_id, risk_mode))
        else:
            # Neue Zeile: fehlende Felder auf Standard-Defaults fallen (nie NULL)
            if position_size is None: position_size = 0.35
            if stop_loss is None: stop_loss = 0.92
            if take_profit is None: take_profit = 1.12
            if drawdown_limit is None: drawdown_limit = 0.20
            self.conn.execute(
                "INSERT INTO tenant_risk_limits "
                "(tenant_id, risk_mode, position_size, stop_loss, take_profit, drawdown_limit) "
                "VALUES (?,?,?,?,?,?)",
                (tenant_id, risk_mode, position_size, stop_loss, take_profit, drawdown_limit))
        self.conn.commit()

    def risk_get(self, tenant_id, risk_mode):
        """PHASE 10: Tenant-Limit holen (None wenn nicht gesetzt)."""
        row = self.conn.execute(
            "SELECT * FROM tenant_risk_limits WHERE tenant_id = ? AND risk_mode = ?",
            (tenant_id, risk_mode)).fetchone()
        return dict(row) if row else None

    def risk_list(self, tenant_id):
        """PHASE 10: Alle Limits eines Tenants."""
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM tenant_risk_limits WHERE tenant_id = ?", (tenant_id,)).fetchall()]

    def effective_risk_limits(self, tenant_id, risk_mode):
        """PHASE 10: Tenant-Limit, Fallback globaler settings.json risk_parameter, dann Default."""
        row = self.risk_get(tenant_id, risk_mode)
        if row:
            return {"position_size": row["position_size"], "stop_loss": row["stop_loss"],
                    "take_profit": row["take_profit"], "drawdown_limit": row["drawdown_limit"],
                    "source": "tenant"}
        # Fallback: globaler settings.json risk_parameter (moderate_/aggressive_)
        try:
            import json
            sp = json.load(open("settings.json", encoding="utf-8")).get("risk_parameter", {})
            pre = "moderate_" if risk_mode == "moderate" else "aggressive_"
            if f"{pre}position_size" in sp:
                return {"position_size": sp.get(f"{pre}position_size", 0.35),
                        "stop_loss": sp.get(f"{pre}stop_loss", 0.92),
                        "take_profit": sp.get(f"{pre}take_profit", 1.12),
                        "drawdown_limit": 0.20, "source": "global"}
        except Exception:
            pass
        return {"position_size": 0.35, "stop_loss": 0.92, "take_profit": 1.12,
                "drawdown_limit": 0.20, "source": "default"}
        self.conn.commit()

    # ── PHASE 11: Tenant-Scoped Regeln (statt globaler learned_rules.json) ──
    def _init_rule_tables(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS tenant_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            rule_id TEXT NOT NULL,
            muster TEXT,
            regel TEXT NOT NULL,
            status TEXT DEFAULT 'aktiv',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tenant_id, rule_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tr_tenant
            ON tenant_rules(tenant_id);
        """)
        self.conn.commit()

    def rule_set(self, tenant_id, rule_id, regel, muster=None, status="aktiv", created_by=None):
        """PHASE 11: Tenant-Regel anlegen/aktualisieren (INSERT OR REPLACE)."""
        self.conn.execute(
            "INSERT OR REPLACE INTO tenant_rules "
            "(tenant_id, rule_id, muster, regel, status, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,datetime('now'))",
            (tenant_id, rule_id, muster, regel, status, created_by))
        self.conn.commit()

    def rule_list(self, tenant_id):
        """PHASE 11: Alle Regeln eines Tenants."""
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM tenant_rules WHERE tenant_id = ?", (tenant_id,)).fetchall()]

    def rule_set_status(self, tenant_id, rule_id, status):
        """PHASE 11: Status einer Tenant-Regel aendern."""
        self.conn.execute(
            "UPDATE tenant_rules SET status=? WHERE tenant_id=? AND rule_id=?",
            (status, tenant_id, rule_id))
        self.conn.commit()

    # ── PHASE 14: Tenant-Scoped Freigabe-Workflow (§23/§21.5) ──
    def _init_approval_tables(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS tenant_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'nicht_freigegeben',
            requested_by INTEGER,
            approved_by INTEGER,
            approved_at TEXT,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tenant_id, target_type, target_id)
        );
        CREATE INDEX IF NOT EXISTS idx_appr_tenant
            ON tenant_approvals(tenant_id);
        CREATE TABLE IF NOT EXISTS live_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            requested_by INTEGER,
            status TEXT NOT NULL DEFAULT 'PENDING',
            broker_connection_id INTEGER,
            risk_assessment TEXT,
            requested_at TEXT DEFAULT (datetime('now')),
            reviewed_by INTEGER,
            reviewed_at TEXT,
            activated_at TEXT,
            note TEXT,
            UNIQUE(tenant_id, status)
        );
        CREATE INDEX IF NOT EXISTS idx_livereq_tenant
            ON live_requests(tenant_id);
        """)
        self.conn.commit()

    def approval_set(self, tenant_id, target_type, target_id, status,
                    approved_by=None, note=None):
        """PHASE 14: Freigabestatus setzen (INSERT OR REPLACE)."""
        existing = self.conn.execute(
            "SELECT approved_at FROM tenant_approvals "
            "WHERE tenant_id=? AND target_type=? AND target_id=?",
            (tenant_id, target_type, target_id)).fetchone()
        approved_at = None
        if status == "freigegeben" and (not existing or existing["approved_at"] is None):
            approved_at = __import__("datetime").datetime.utcnow().isoformat() + "Z"
        if status != "freigegeben":
            approved_at = None
        self.conn.execute(
            "INSERT OR REPLACE INTO tenant_approvals "
            "(tenant_id, target_type, target_id, status, requested_by, "
            " approved_by, approved_at, note, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
            (tenant_id, target_type, target_id, status,
             None, approved_by, approved_at, note))
        self.conn.commit()

    def approval_get(self, tenant_id, target_type, target_id):
        """PHASE 14: Aktuellen Freigabestatus (oder Default 'nicht_freigegeben')."""
        row = self.conn.execute(
            "SELECT status, approved_by, approved_at, note FROM tenant_approvals "
            "WHERE tenant_id=? AND target_type=? AND target_id=?",
            (tenant_id, target_type, target_id)).fetchone()
        if row:
            d = dict(row)
            d["exists"] = True
            return d
        return {"status": "nicht_freigegeben", "approved_by": None,
                "approved_at": None, "note": None, "exists": False}

    def approval_list(self, tenant_id):
        """PHASE 14: Alle Freigaben eines Tenants."""
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM tenant_approvals WHERE tenant_id = ?",
            (tenant_id,)).fetchall()]

    # ── Live-Antragsprozess (S19-P14) ───────────────────────────────────
    def live_request_create(self, tenant_id, requested_by, broker_connection_id=None,
                            risk_assessment=None, note=None):
        """Erstellt einen Live-Antrag (PENDING). Nur einer pro Tenant gleichzeitig."""
        active = self.conn.execute(
            "SELECT id FROM live_requests WHERE tenant_id=? AND status IN "
            "('PENDING','IN_REVIEW','APPROVED','ACTIVATED')", (tenant_id,)).fetchone()
        if active:
            return {"ok": False, "reason": "Tenant hat bereits aktiven/offenen Live-Antrag",
                    "id": active["id"]}
        cur = self.conn.execute(
            "INSERT INTO live_requests (tenant_id, requested_by, " 
            "broker_connection_id, risk_assessment, note) VALUES (?,?,?,?,?)",
            (tenant_id, requested_by, broker_connection_id, risk_assessment, note))
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid, "status": "PENDING"}

    def live_request_review(self, req_id, tenant_id, reviewed_by):
        """Verschiebt PENDING -> IN_REVIEW."""
        row = self.conn.execute(
            "SELECT * FROM live_requests WHERE id=? AND tenant_id=?",
            (req_id, tenant_id)).fetchone()
        if not row:
            return {"ok": False, "reason": "Antrag nicht gefunden (tenant-scoped)"}
        if row["status"] != "PENDING":
            return {"ok": False, "reason": f"Status {row['status']} erlaubt kein Review"}
        self.conn.execute(
            "UPDATE live_requests SET status='IN_REVIEW', reviewed_by=?, " 
            "reviewed_at=datetime('now') WHERE id=?",
            (reviewed_by, req_id))
        self.conn.commit()
        return {"ok": True, "status": "IN_REVIEW"}

    def live_request_approve(self, req_id, tenant_id, approved_by, note=None):
        """IN_REVIEW -> APPROVED."""
        row = self.conn.execute(
            "SELECT * FROM live_requests WHERE id=? AND tenant_id=?",
            (req_id, tenant_id)).fetchone()
        if not row:
            return {"ok": False, "reason": "Antrag nicht gefunden (tenant-scoped)"}
        if row["status"] != "IN_REVIEW":
            return {"ok": False, "reason": f"Status {row['status']} erlaubt keine Freigabe"}
        self.conn.execute(
            "UPDATE live_requests SET status='APPROVED', reviewed_by=?, " 
            "reviewed_at=datetime('now'), note=? WHERE id=?",
            (approved_by, note, req_id))
        self.conn.commit()
        return {"ok": True, "status": "APPROVED"}

    def live_request_reject(self, req_id, tenant_id, rejected_by, note=None):
        """IN_REVIEW -> REJECTED."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT status FROM live_requests WHERE id=? AND tenant_id=?",
            (req_id, tenant_id))
        r = cur.fetchone()
        if not r:
            return {"ok": False, "reason": "Antrag nicht gefunden (tenant-scoped)"}
        status = r[0]
        if status not in ("PENDING", "IN_REVIEW"):
            return {"ok": False, "reason": f"Status {status} erlaubt keine Ablehnung"}
        self.conn.execute(
            "UPDATE live_requests SET status='REJECTED', reviewed_by=?, " 
            "reviewed_at=datetime('now'), note=? WHERE id=?",
            (rejected_by, note, req_id))
        self.conn.commit()
        return {"ok": True, "status": "REJECTED"}

    def live_request_activate(self, req_id, tenant_id):
        """APPROVED -> ACTIVATED."""
        row = self.conn.execute(
            "SELECT * FROM live_requests WHERE id=? AND tenant_id=?",
            (req_id, tenant_id)).fetchone()
        if not row:
            return {"ok": False, "reason": "Antrag nicht gefunden (tenant-scoped)"}
        if row["status"] != "APPROVED":
            return {"ok": False, "reason": f"Status {row['status']} erlaubt keine Aktivierung"}
        self.conn.execute(
            "UPDATE live_requests SET status='ACTIVATED', activated_at=datetime('now') " 
            "WHERE id=?", (req_id,))
        self.conn.commit()
        return {"ok": True, "status": "ACTIVATED"}

    def live_request_list(self, tenant_id):
        """Alle Live-Antraege eines Tenants."""
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM live_requests WHERE tenant_id=? ORDER BY id DESC",
            (tenant_id,)).fetchall()]

    def live_request_get(self, req_id, tenant_id):
        """Einzelner Live-Antrag (tenant-scoped)."""
        row = self.conn.execute(
            "SELECT * FROM live_requests WHERE id=? AND tenant_id=?",
            (req_id, tenant_id)).fetchone()
        return dict(row) if row else None

    def effective_rules(self, tenant_id):
        """PHASE 11 + BUG-Regel-Review: Tenant-Regeln ∪ globale learned_rules.json
        (Tenant gewinnt bei ID-Kollision). PFLICHT-GATE (Regel-Review-Workflow):
        nur Regeln mit status ACTIVATED (oder APPROVED bei globalen Regeln mit
        freigabe_status='freigegeben') sind wirksam. Unreviewed/PENDING/IN_REVIEW
        Regeln werden NICHT angewendet."""
        out = {}
        # Global-Basis
        try:
            import json
            g = json.load(open("learned_rules.json", encoding="utf-8"))
            for r in g.get("rules", []):
                status = r.get("status", "aktiv")
                freigabe = r.get("freigabe_status", "nicht_freigegeben")
                # Global: nur freigegebene
                if freigabe != "freigegeben":
                    continue
                out[r["id"]] = {"id": r["id"], "muster": r.get("muster"),
                                "regel": r.get("regel"), "status": status,
                                "freigabe_status": freigabe,
                                "shadow": bool(r.get("shadow", False)),
                                "typ": r.get("typ", ""),
                                "source": "global"}
        except Exception:
            pass
        # Tenant ueberschreibt — aber nur ACTIVATED (Pflicht-Gate!)
        for r in self.rule_list(tenant_id):
            if r.get("status") != "ACTIVATED":
                continue
            out[r["rule_id"]] = {"id": r["rule_id"], "muster": r.get("muster"),
                                 "regel": r["regel"], "status": r["status"],
                                 "freigabe_status": "freigegeben", "shadow": False,
                                 "typ": "tenant", "source": "tenant"}
        return list(out.values())

    def secret_set(self, tenant_id, secret_key, secret_value):
        """PHASE 8: Secret tenant-isoliert speichern (kein globaler .env-Key)."""
        self.conn.execute(
            "INSERT OR REPLACE INTO secret_store "
            "(tenant_id, secret_key, secret_value, updated_at) "
            "VALUES (?,?,?,datetime('now'))",
            (tenant_id, secret_key, secret_value))
        self.conn.commit()

    def secret_get(self, tenant_id, secret_key):
        """PHASE 8: Secret nur fuer den eigenen Tenant auslesen."""
        row = self.conn.execute(
            "SELECT secret_value FROM secret_store WHERE tenant_id = ? AND secret_key = ?",
            (tenant_id, secret_key)).fetchone()
        return row["secret_value"] if row else None

    def secret_list_keys(self, tenant_id):
        """PHASE 8: Nur Schluessel auflisten (NIEMALS Werte)."""
        return [r["secret_key"] for r in self.conn.execute(
            "SELECT secret_key FROM secret_store WHERE tenant_id = ?",
            (tenant_id,)).fetchall()]

    # ── PHASE 7: Provider-Connection-Tabellen (Sektion 10) ──
    def _init_provider_tables(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS provider_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            workspace_id INTEGER,
            user_id INTEGER,
            provider_type TEXT NOT NULL,
            provider_name TEXT NOT NULL,
            environment TEXT DEFAULT 'PAPER',
            status TEXT DEFAULT 'aktiv',
            permissions TEXT,
            secret_reference TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            last_test_at TEXT,
            last_error TEXT,
            rate_limit INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_pc_tenant
            ON provider_connections(tenant_id);
        """)
        self.conn.commit()
        self.provider_connection_ensure_columns()

    # ── PHASE 6: Virtuelles Paper-Portfolio (eigenes Depot, nicht mit Shadow mischen) ──
    def _init_paper_tables(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS paper_portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            portfolio_key TEXT NOT NULL,
            name TEXT,
            virtual_cash REAL DEFAULT 100.0,
            status TEXT DEFAULT 'aktiv',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tenant_id, portfolio_key)
        );
        CREATE TABLE IF NOT EXISTS paper_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER NOT NULL,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            ticker TEXT NOT NULL,
            shares REAL DEFAULT 0,
            avg_price REAL DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_pp_tenant
            ON paper_portfolios(tenant_id);
        CREATE TABLE IF NOT EXISTS paper_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            portfolio_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            status TEXT DEFAULT 'filled',
            order_type TEXT DEFAULT 'market',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_po_tenant
            ON paper_orders(tenant_id);
        """)
        self.conn.commit()

    def paper_portfolio_create(self, tenant_id, portfolio_key, name=None, virtual_cash=100.0):
        cur = self.conn.execute(
            "INSERT OR REPLACE INTO paper_portfolios "
            "(tenant_id, portfolio_key, name, virtual_cash, status) "
            "VALUES (?,?,?,?,'aktiv')",
            (tenant_id, portfolio_key, name, virtual_cash))
        self.conn.commit()
        return cur.lastrowid

    def paper_portfolio_list(self, tenant_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM paper_portfolios WHERE tenant_id = ? AND status != 'geloescht'",
            (tenant_id,)).fetchall()]

    def paper_order_insert(self, tenant_id, portfolio_id, ticker, side, quantity,
                           price, status="filled", order_type="market"):
        """PHASE 9: Order im Paper-Buch speichern (tenant-scoped)."""
        cur = self.conn.execute(
            "INSERT INTO paper_orders "
            "(tenant_id, portfolio_id, ticker, side, quantity, price, status, order_type) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (tenant_id, portfolio_id, ticker, side, quantity, price, status, order_type))
        self.conn.commit()
        return cur.lastrowid

    def paper_order_list(self, tenant_id, portfolio_id=None):
        q = "SELECT * FROM paper_orders WHERE tenant_id = ?"
        p = [tenant_id]
        if portfolio_id:
            q += " AND portfolio_id = ?"
            p.append(portfolio_id)
        return [dict(r) for r in self.conn.execute(q, p).fetchall()]

    def paper_position_apply(self, tenant_id, portfolio_id, ticker, side, quantity, price):
        """PHASE 9: Position aktualisieren (Buy erhoeht, Sell verringert)."""
        row = self.conn.execute(
            "SELECT * FROM paper_positions WHERE portfolio_id = ? AND ticker = ?",
            (portfolio_id, ticker)).fetchone()
        q = float(quantity)
        if side == "BUY":
            if row:
                old_shares = float(row["shares"]); old_avg = float(row["avg_price"])
                new_shares = old_shares + q
                new_avg = (old_shares * old_avg + q * float(price)) / new_shares if new_shares else 0
                self.conn.execute(
                    "UPDATE paper_positions SET shares=?, avg_price=?, updated_at=datetime('now') "
                    "WHERE portfolio_id=? AND ticker=?",
                    (new_shares, new_avg, portfolio_id, ticker))
            else:
                self.conn.execute(
                    "INSERT INTO paper_positions (portfolio_id, tenant_id, ticker, shares, avg_price) "
                    "VALUES (?,?,?,?,?)",
                    (portfolio_id, tenant_id, ticker, q, float(price)))
        else:  # SELL
            if row:
                new_shares = float(row["shares"]) - q
                if new_shares <= 0:
                    self.conn.execute(
                        "DELETE FROM paper_positions WHERE portfolio_id=? AND ticker=?",
                        (portfolio_id, ticker))
                else:
                    self.conn.execute(
                        "UPDATE paper_positions SET shares=?, updated_at=datetime('now') "
                        "WHERE portfolio_id=? AND ticker=?",
                        (new_shares, portfolio_id, ticker))
        # Cash anpassen
        sign = -1 if side == "BUY" else 1
        self.conn.execute(
            "UPDATE paper_portfolios SET virtual_cash = virtual_cash + ? "
            "WHERE id = ? AND tenant_id = ?",
            (sign * q * float(price), portfolio_id, tenant_id))
        self.conn.commit()

    # ── PHASE 1/BUG-003: markt_daten persistieren ──────────────────────────
    def ensure_markt_daten_columns(self):
        """BUG-003: tenant_id-Spalte sicherstellen (Tabelle war urspruenglich
        tenant-agnostisch). Idempotent via PRAGMA-Check."""
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(markt_daten)")]
        if "tenant_id" not in cols:
            self.conn.execute("ALTER TABLE markt_daten ADD COLUMN tenant_id INTEGER DEFAULT 1")
            self.conn.commit()

    def save_markt_daten(self, tenant_id, ticker, kurs, rsi=None, sma20=None, sma50=None):
        """BUG-003: aktuellen Marktschnappschuss persistieren. Upsert pro
        (tenant_id, ticker) — behaelt nur den letzten Stand je Ticker."""
        self.ensure_markt_daten_columns()
        self.conn.execute(
            "DELETE FROM markt_daten WHERE tenant_id=? AND ticker=?",
            (tenant_id, ticker))
        self.conn.execute(
            "INSERT INTO markt_daten (zeit, ticker, kurs, rsi, sma20, sma50, tenant_id) "
            "VALUES (datetime('now'), ?, ?, ?, ?, ?, ?)",
            (ticker, float(kurs), rsi, sma20, sma50, tenant_id))
        self.conn.commit()

    def get_markt_daten(self, tenant_id, ticker=None, limit=100):
        """BUG-003: gespeicherte Marktdaten lesen (fuer Shadow->Paper-Eligibility
        'Providerdaten stabil' + Dashboard-Anzeige)."""
        self.ensure_markt_daten_columns()
        if ticker:
            rows = self.conn.execute(
                "SELECT * FROM markt_daten WHERE tenant_id=? AND ticker=? "
                "ORDER BY zeit DESC LIMIT ?", (tenant_id, ticker, limit)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM markt_daten WHERE tenant_id=? ORDER BY zeit DESC LIMIT ?",
                (tenant_id, limit)).fetchall()
        return [dict(r) for r in rows]

    # ── PHASE 7: Provider-Connection-Manager (Sektion 10) ──
    def provider_connection_add(self, tenant_id, provider_type, provider_name,
                                environment, permissions, secret_reference,
                                created_by=None):
        """PHASE 7: Verbindung anlegen (Secret NICHT als Klartext, nur Referenz).
        environment: DEMO/PAPER/SANDBOX/LIVE"""
        self.conn.execute(
            "INSERT INTO provider_connections "
            "(tenant_id, provider_type, provider_name, environment, status, "
            " permissions, secret_reference, created_by) "
            "VALUES (?,?,?,?, 'aktiv', ?, ?, ?)",
            (tenant_id, provider_type, provider_name, environment,
             permissions, secret_reference, created_by))
        self.conn.commit()

    def provider_connection_list(self, tenant_id, provider_type=None):
        q = "SELECT * FROM provider_connections WHERE tenant_id = ?"
        p = [tenant_id]
        if provider_type:
            q += " AND provider_type = ?"
            p.append(provider_type)
        return [dict(r) for r in self.conn.execute(q, p).fetchall()]

    def provider_connection_ensure_columns(self):
        """PHASE 7: Migration - fehlende Spalten ergaenzen (idempotent)."""
        if not self._spalte_existiert("provider_connections", "created_by"):
            self.conn.execute(
                "ALTER TABLE provider_connections ADD COLUMN created_by INTEGER")
            self.conn.commit()

    def provider_connection_test(self, conn_id, ok=True, err=None):
        """PHASE 7: Test-Status aktualisieren (kein Secret im Log)."""
        self.conn.execute(
            "UPDATE provider_connections SET last_test_at = datetime('now'), "
            "last_error = ?, status = ? WHERE id = ?",
            (err, "aktiv" if ok else "fehler", conn_id))
        self.conn.commit()
    # ── PHASE 9 (S19-P9): Provider-Connection-Status-Workflow ──
    PROVIDER_CONN_STATES = (
        "UNCONFIGURED", "CONFIGURED", "TESTING", "HEALTHY",
        "DEGRADED", "FAILED", "DISABLED", "EXPIRED",
    )
    PROVIDER_CONN_TRANSITIONS = {
        # Legacy-States (deutsch) -> englisches ENUM-Mapping (Backward-Compat)
        "aktiv":        {"DISABLED", "TESTING", "CONFIGURED"},
        "fehler":       {"DISABLED", "TESTING", "CONFIGURED"},
        "UNCONFIGURED": {"CONFIGURED", "DISABLED"},
        "CONFIGURED":   {"TESTING", "DISABLED", "EXPIRED"},
        "TESTING":       {"HEALTHY", "DEGRADED", "FAILED", "DISABLED"},
        "HEALTHY":       {"TESTING", "DEGRADED", "FAILED", "DISABLED", "EXPIRED"},
        "DEGRADED":      {"TESTING", "HEALTHY", "FAILED", "DISABLED", "EXPIRED"},
        "FAILED":        {"TESTING", "DISABLED", "CONFIGURED", "EXPIRED"},
        "DISABLED":      {"CONFIGURED", "UNCONFIGURED", "aktiv"},
        "EXPIRED":       {"CONFIGURED", "DISABLED"},
    }

    def provider_connection_get(self, conn_id, tenant_id=None):
        q = "SELECT * FROM provider_connections WHERE id = ?"
        pa = [conn_id]
        if tenant_id is not None:
            q += " AND tenant_id = ?"
            pa.append(tenant_id)
        r = self.conn.execute(q, pa).fetchone()
        return dict(r) if r else None

    def provider_connection_set_status(self, conn_id, tenant_id, new_status):
        if new_status not in self.PROVIDER_CONN_STATES:
            return {"ok": False, "reason": f"Unbekannter Status: {new_status}"}
        cur = self.provider_connection_get(conn_id, tenant_id)
        if not cur:
            return {"ok": False, "reason": "Verbindung nicht gefunden (tenant-scoped)"}
        old = cur["status"]
        allowed = self.PROVIDER_CONN_TRANSITIONS.get(old, set())
        if new_status not in allowed:
            return {"ok": False, "reason": f"Transition {old} -> {new_status} nicht erlaubt"}
        self.conn.execute(
            "UPDATE provider_connections SET status = ?, updated_at = datetime('now') "
            "WHERE id = ? AND tenant_id = ?",
            (new_status, conn_id, tenant_id))
        self.conn.commit()
        return {"ok": True, "old": old, "new": new_status}

    def provider_connection_disable(self, conn_id, tenant_id):
        return self.provider_connection_set_status(conn_id, tenant_id, "DISABLED")

    def provider_connection_enable(self, conn_id, tenant_id):
        return self.provider_connection_set_status(conn_id, tenant_id, "CONFIGURED")

    def provider_connection_delete(self, conn_id, tenant_id):
        cur = self.provider_connection_get(conn_id, tenant_id)
        if not cur:
            return {"ok": False, "reason": "Verbindung nicht gefunden (tenant-scoped)"}
        self.conn.execute(
            "DELETE FROM provider_connections WHERE id = ? AND tenant_id = ?",
            (conn_id, tenant_id))
        self.conn.commit()
        return {"ok": True, "deleted": conn_id}

    # ── PHASE 9 (S19-P9): Secret-Rotation (tenant-isolated) ──
    def secret_rotate(self, tenant_id, secret_key, new_secret_value):
        existing = self.secret_get(tenant_id, secret_key)
        if existing is None:
            return {"ok": False, "reason": "Secret existiert nicht (setze es zuerst)"}
        self.secret_set(tenant_id, secret_key, new_secret_value)
        return {"ok": True, "rotated": secret_key,
                "last4": new_secret_value[-4:] if new_secret_value else "****"}

    def secret_last4(self, tenant_id, secret_key):
        v = self.secret_get(tenant_id, secret_key)
        if v is None:
            return None
        return "****" + (v[-4:] if v else "")


    # ── PHASE 5: Trading-Modi-Zustandsmaschine (Sektion 8) ──
    TRADING_MODES = ("SHADOW", "PAPER", "LIVE_REQUESTED", "LIVE_APPROVED",
                     "LIVE_ACTIVE", "PAUSED", "SUSPENDED", "REVOKED")
    # Erlaubte Transitionen (von -> [nach])
    MODE_TRANSITIONS = {
        "SHADOW": ["PAPER", "SUSPENDED"],
        "PAPER": ["SHADOW", "LIVE_REQUESTED", "PAUSED", "SUSPENDED"],
        "LIVE_REQUESTED": ["LIVE_APPROVED", "PAPER", "SHADOW", "REVOKED", "SUSPENDED"],
        "LIVE_APPROVED": ["LIVE_ACTIVE", "REVOKED", "SUSPENDED"],
        "LIVE_ACTIVE": ["PAUSED", "SUSPENDED", "REVOKED"],
        "PAUSED": ["SHADOW", "PAPER", "LIVE_ACTIVE", "SUSPENDED", "REVOKED"],
        "SUSPENDED": ["SHADOW", "PAPER", "REVOKED"],
        "REVOKED": ["SHADOW", "PAPER"],
    }

    def _init_trading_mode_tables(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS trading_mode_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            user_id INTEGER,
            portfolio_id INTEGER,
            strategy_id INTEGER,
            old_mode TEXT NOT NULL,
            new_mode TEXT NOT NULL,
            reason TEXT,
            requested_by INTEGER,
            approved_by INTEGER,
            timestamp TEXT DEFAULT (datetime('now')),
            mfa_confirmed INTEGER DEFAULT 0,
            risk_review_status TEXT DEFAULT 'pending',
            broker_connection_status TEXT DEFAULT 'none',
            audit_event_id INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_tmt_tenant
            ON trading_mode_transitions(tenant_id);
        """)
        self.conn.commit()

    def mode_is_valid(self, mode):
        return mode in self.TRADING_MODES

    def mode_can_transition(self, old_mode, new_mode):
        return new_mode in self.MODE_TRANSITIONS.get(old_mode, [])

    def mode_log_insert(self, tenant_id, user_id, portfolio_id, strategy_id,
                        old_mode, new_mode, reason, requested_by, approved_by=None,
                        mfa_confirmed=0, risk_review_status="pending",
                        broker_connection_status="none", audit_event_id=None):
        """PHASE 5: Schreibt jeden Zustandswechsel ins Audit-Log (Sektion 8 Pflichtfelder)."""
        self.conn.execute(
            "INSERT INTO trading_mode_transitions "
            "(tenant_id, user_id, portfolio_id, strategy_id, old_mode, new_mode, "
            " reason, requested_by, approved_by, mfa_confirmed, risk_review_status, "
            " broker_connection_status, audit_event_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tenant_id, user_id, portfolio_id, strategy_id, old_mode, new_mode,
             reason, requested_by, approved_by, mfa_confirmed, risk_review_status,
             broker_connection_status, audit_event_id))
        self.conn.commit()

    def mode_log_list(self, tenant_id, limit=100):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM trading_mode_transitions WHERE tenant_id = ? "
            "ORDER BY id DESC LIMIT ?", (tenant_id, limit)).fetchall()]

    def _spalte_existiert(self, tabelle, spalte):
        res = self.conn.execute(f'PRAGMA table_info("{tabelle}")').fetchall()
        return any(r[1] == spalte for r in res)

    def _migrate_schema(self):
        """Idempotent: fuegt Audit-Felder hinzu (decision_id/provider/regel_id/fallback).
        Bereits vorhandene Spalten werden uebersprungen.
        PHASE 1: tenant_id-Spalten fuer Mandanten-Trennung."""
        c = self.conn.cursor()
        for spalte in ["decision_id", "provider", "regel_id", "fallback"]:
            if not self._spalte_existiert("trades", spalte):
                c.execute(f'ALTER TABLE trades ADD COLUMN {spalte} TEXT')
        for spalte in ["decision_id", "provider", "regel_id", "fallback"]:
            if not self._spalte_existiert("ki_decisions", spalte):
                c.execute(f'ALTER TABLE ki_decisions ADD COLUMN {spalte} TEXT')
        # PHASE 1: tenant_id + user_id auf Bestandstabellen (Default 1 = Haupt-Tenant)
        for tabelle, spalten in {
            "trades": ["tenant_id", "user_id"],
            "ki_decisions": ["tenant_id", "user_id"],
            "depot_snapshot": ["tenant_id", "user_id"],
            "markt_daten": ["tenant_id"],
        }.items():
            for spalte in spalten:
                if not self._spalte_existiert(tabelle, spalte):
                    c.execute(f'ALTER TABLE {tabelle} ADD COLUMN {spalte} INTEGER DEFAULT 1')
        self.conn.commit()

    # ── PHASE 4: Mandantentrennung ──
    def tenant_scope_where(self, tenant_id=None):
        """Liefert SQL-Fragment 'AND tenant_id = ?' + Parameter fuer Scope."""
        tid = tenant_id or 1
        return "AND tenant_id = ?", (tid,)

    def depot_register(self, table, tenant_id, depot_key, pfad, risk_stufe=None,
                       ticker=None, name=None, modus='SHADOW'):
        """Registriert/aktualisiert ein Depot im tenant-Scope (idempotent)."""
        if table == 'spec_depots':
            self.conn.execute(
                f"INSERT OR REPLACE INTO {table} "
                "(tenant_id, ticker, depot_key, pfad, name, modus, status) "
                "VALUES (?,?,?,?,?,?,'aktiv')",
                (tenant_id, ticker, depot_key, pfad, name, modus))
        else:
            self.conn.execute(
                f"INSERT OR REPLACE INTO {table} "
                "(tenant_id, risk_stufe, depot_key, pfad, name, modus, status) "
                "VALUES (?,?,?,?,?,?,'aktiv')",
                (tenant_id, risk_stufe, depot_key, pfad, name, modus))
        self.conn.commit()

    def depot_list_tenant(self, table, tenant_id):
        """Listet Depots eines Tenants (tenant-scoped)."""
        return [dict(r) for r in self.conn.execute(
            f"SELECT * FROM {table} WHERE tenant_id = ? AND status != 'geloescht'",
            (tenant_id,)).fetchall()]

    def _init_schema(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zeit TEXT, depot_typ TEXT, ticker TEXT, aktion TEXT,
            menge REAL, preis REAL, grund TEXT, konfidenz REAL
        );
        CREATE INDEX IF NOT EXISTS idx_trades_zeit ON trades(zeit);
        CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);

        CREATE TABLE IF NOT EXISTS ki_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zeit TEXT, ticker TEXT, aktion TEXT, konfidenz REAL,
            grund TEXT, depot_typ TEXT, risk INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_ki_zeit ON ki_decisions(zeit);

        CREATE TABLE IF NOT EXISTS depot_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zeit TEXT, depot_typ TEXT, ref TEXT, wert REAL,
            rendite REAL, shares REAL, bargeld REAL
        );
        CREATE INDEX IF NOT EXISTS idx_snap_zeit ON depot_snapshot(zeit);

        CREATE TABLE IF NOT EXISTS markt_daten (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zeit TEXT, ticker TEXT, kurs REAL, rsi REAL,
            sma20 REAL, sma50 REAL
        );
        CREATE INDEX IF NOT EXISTS idx_markt_ticker ON markt_daten(ticker);

        -- ── PHASE 1: Mandanten-Modell (v2.26.0) ──
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_key TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'aktiv',
            plan_or_type TEXT DEFAULT 'personal',
            default_trading_mode TEXT DEFAULT 'SHADOW',
            risk_policy_id TEXT DEFAULT 'default',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS tenant_memberships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            status TEXT DEFAULT 'aktiv',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tenant_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS workspaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            workspace_key TEXT NOT NULL,
            name TEXT NOT NULL,
            trading_mode TEXT DEFAULT 'SHADOW',
            status TEXT DEFAULT 'aktiv',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tenant_id, workspace_key)
        );
        -- PHASE 4: Mandantentrennung fuer Depot-Datentraeger (Mirror der JSONs)
        CREATE TABLE IF NOT EXISTS depots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            risk_stufe INTEGER NOT NULL,
            depot_key TEXT NOT NULL,
            pfad TEXT NOT NULL,
            name TEXT,
            modus TEXT DEFAULT 'SHADOW',
            status TEXT DEFAULT 'aktiv',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tenant_id, depot_key)
        );
        CREATE TABLE IF NOT EXISTS etf_depots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            risk_stufe INTEGER NOT NULL,
            depot_key TEXT NOT NULL,
            pfad TEXT NOT NULL,
            name TEXT,
            modus TEXT DEFAULT 'SHADOW',
            status TEXT DEFAULT 'aktiv',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tenant_id, depot_key)
        );
        CREATE TABLE IF NOT EXISTS spec_depots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            ticker TEXT NOT NULL,
            depot_key TEXT NOT NULL,
            pfad TEXT NOT NULL,
            name TEXT,
            modus TEXT DEFAULT 'SHADOW',
            status TEXT DEFAULT 'aktiv',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tenant_id, depot_key)
        );
        """)
        self.conn.commit()

    # ── Sync: JSON -> DB ──
    def sync(self, verbose=False):
        self._sync_trades()
        self._sync_ki()
        self._sync_snapshots()
        self.match_trades_ki()  # weicher Match Trade<->KI (ehrlich, nur eindeutige)
        self.conn.commit()
        if verbose:
            print("DB-Sync fertig:", self.stats())

    def _sync_trades(self):
        c = self.conn.cursor()
        # Letzter Stand, um Duplikate zu vermeiden
        last = c.execute("SELECT MAX(zeit) FROM trades").fetchone()[0] or "0"
        # Aktien
        for fn in glob.glob(os.path.join(BASE, "depot_*.json")):
            self._trades_aus_datei(fn, "aktien", last)
        # ETF
        for fn in glob.glob(os.path.join(BASE, "etf_0*.json")):
            self._trades_aus_datei(fn, "etf", last)
        # Spec
        for fn in glob.glob(os.path.join(BASE, "spec_depots", "*.json")):
            self._trades_aus_datei(fn, "spec", last, ticker_aus_dateiname=True)

    def _trades_aus_datei(self, fn, typ, last, ticker_aus_dateiname=False):
        c = self.conn.cursor()
        try:
            d = json.load(open(fn, encoding="utf-8"))
        except Exception:
            return
        ticker = d.get("ticker")
        if ticker_aus_dateiname and not ticker:
            ticker = os.path.basename(fn).replace(".json", "")
        for t in d.get("trades", []):
            if not isinstance(t, dict):
                continue
            zeit = t.get("zeit", "")
            if zeit <= last:
                continue
            aktion = t.get("aktion") or t.get("typ") or "?"
            c.execute(
                "INSERT INTO trades (zeit, depot_typ, ticker, aktion, menge, preis, grund, konfidenz, decision_id) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (zeit, typ, ticker, aktion,
                 t.get("menge", 0), t.get("preis", 0),
                 str(t.get("grund", ""))[:200], t.get("konfidenz"),
                 t.get("decision_id")))  # aus Depot-JSON-Trade falls vorhanden (sonst NULL)

    def _sync_ki(self):
        c = self.conn.cursor()
        last = c.execute("SELECT MAX(zeit) FROM ki_decisions").fetchone()[0] or "0"
        pfad = os.path.join(BASE, "ki_log.json")
        if not os.path.exists(pfad):
            return
        try:
            data = json.load(open(pfad, encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, list):
            return
        for e in data:
            zeit = e.get("zeit", "")
            if zeit <= last:
                continue
            # regel_id: erste angewandte Regel (aus angewandte_regeln[].id)
            ar = e.get("angewandte_regeln") or []
            regel_id = ar[0].get("id") if ar and isinstance(ar[0], dict) else None
            c.execute(
                "INSERT INTO ki_decisions (zeit, ticker, aktion, konfidenz, grund, depot_typ, risk, decision_id, regel_id, provider, fallback) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (zeit, e.get("ticker"), e.get("aktion"), e.get("konfidenz"),
                 str(e.get("grund", ""))[:200], e.get("depot_typ"), e.get("risk"),
                 e.get("decision_id"), regel_id, e.get("provider"), e.get("fallback")))

    def _sync_snapshots(self):
        c = self.conn.cursor()
        jetzt = datetime.now().isoformat()
        # Aktien
        for fn in glob.glob(os.path.join(BASE, "depot_*.json")):
            self._snapshot_aus_datei(fn, "aktien", jetzt)
        for fn in glob.glob(os.path.join(BASE, "etf_0*.json")):
            self._snapshot_aus_datei(fn, "etf", jetzt)
        # spec_depots_paper/ bei PAPER, spec_depots/ bei SHADOW.
        # Fester Pfad "spec_depots" liest seit 30.09. ein leeres Verzeichnis:
        # die Depots liegen in spec_depots_paper/, deshalb blieb die
        # letzte Spec-Zeile in depot_snapshot auf dem 30.09. stehen und
        # jede Auswertung darauf zeigte veraltete Werte.
        _spec_dir = os.path.join(BASE, "spec_depots")
        try:
            from report_pdf import _trading_mode as _tm
            if _tm() == "paper":
                _spec_dir = os.path.join(BASE, "spec_depots_paper")
        except Exception:
            if os.path.isdir(os.path.join(BASE, "spec_depots_paper")):
                _spec_dir = os.path.join(BASE, "spec_depots_paper")
        for fn in glob.glob(os.path.join(_spec_dir, "*.json")):
            self._snapshot_aus_datei(fn, "spec", jetzt, ticker_aus_dateiname=True)

    @staticmethod
    def _depot_schluessel(d, fn):
        """Eindeutiger Schluessel fuer ein Depot.

        Reihenfolge nach Verlaesslichkeit: depot_id (maschinell),
        ticker, name, dann das Ticker-Feld der ETF-Depots, dann der
        Dateiname. Ein leeres '?' waere still - es wuerde mehrere
        Depots in einer Zeile verschmelzen.
        """
        for feld in ("depot_id", "ticker", "name"):
            v = d.get(feld)
            if isinstance(v, str) and v.strip():
                return v.strip()
        sh = d.get("shares")
        if isinstance(sh, str) and sh.strip():
            return sh.strip()
        return os.path.basename(fn).replace(".json", "") or "unbekannt"

    @staticmethod
    def _skalar(v):
        """Liefert einen fuer SQLite bindbaren Wert oder None.

        Ein Dict, eine Liste oder ein nicht-numerischer String sind
        keine Anteilszahlen. Sie liefern None - und None heisst
        "unbekannt", nicht 0. Ein erfundener Nullwert wuerde in der
        Auswertung wie ein leeres Depot aussehen.
        """
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.strip().replace(",", ".")
            try:
                return float(s)
            except ValueError:
                return None
        return None

    def _anteile_aus_depot(self, d):
        """Tatsaechlich gehaltene Anteile, egal wo sie stehen.

        Aktiendepots fuehren 'shares' als leeres Dict und die
        Struktur in 'positions'. ETF-Depots fuehren 'shares' als
        Ticker-String. Nur 'positions' ist in beiden Faellen die
        belastbare Quelle.
        """
        pos = d.get("positions")
        if isinstance(pos, dict):
            summe = 0.0
            gefunden = False
            for p in pos.values():
                if not isinstance(p, dict):
                    continue
                s = self._skalar(p.get("shares", p.get("menge")))
                if s is not None:
                    summe += s
                    gefunden = True
            if gefunden:
                return summe
        # Flache Struktur: Positionen liegen direkt in 'shares'
        sh = d.get("shares")
        if isinstance(sh, dict):
            summe = 0.0
            gefunden = False
            for v in sh.values():
                s = self._skalar(v.get("shares") if isinstance(v, dict)
                                 else v)
                if s is not None:
                    summe += s
                    gefunden = True
            if gefunden:
                return summe
        return self._skalar(sh)

    def _snapshot_aus_datei(self, fn, typ, jetzt, ticker_aus_dateiname=False):
        c = self.conn.cursor()
        try:
            d = json.load(open(fn, encoding="utf-8"))
        except Exception:
            return
        # Der Schluessel muss jedes Depot eindeutig bezeichnen -
        # '?' wuerde zehn Depots in einer Zeile verschmelzen.
        ref = self._depot_schluessel(d, fn)
        if ticker_aus_dateiname and ref == os.path.basename(fn)[:-5]:
            pass  # Dateiname ist fuer Spec-Depots genau richtig
        bargeld = self._skalar(d.get("bargeld"))
        marktwert = self._skalar(d.get("marktwert"))
        wert = self._skalar(d.get("wert"))
        if wert is None:
            # Ohne persistierte Bewertung rechnen wir cash + Marktwert.
            # Sonst wuerde ein leeres Depot wie ein Verlust aussehen.
            if bargeld is not None and marktwert is not None:
                wert = bargeld + marktwert
            else:
                wert = bargeld if bargeld is not None else 0.0
        rendite = self._skalar(d.get("rendite"))
        if rendite is None:
            start = self._skalar(d.get("start_wert"))
            rendite = ((wert / start) - 1) * 100 if start else 0.0
        anteile = self._anteile_aus_depot(d)
        if ref is None:
            ref = "?"
        try:
            c.execute(
                "INSERT INTO depot_snapshot (zeit, depot_typ, ref, wert, "
                "rendite, shares, bargeld) VALUES (?,?,?,?,?,?,?)",
                (jetzt, typ, ref, wert, rendite, anteile, bargeld))
        except Exception:
            # Ein einzelnes kaputtes Depot darf den Sync nicht
            # abbrechen - die anderen Depots waeren sonst ebenfalls
            # verloren.
            try:
                self.conn.rollback()
            except Exception:
                pass
            return

    # ── Abfragen ──
    def stats(self):
        c = self.conn.cursor()
        return {
            "trades": c.execute("SELECT COUNT(*) FROM trades").fetchone()[0],
            "ki_decisions": c.execute("SELECT COUNT(*) FROM ki_decisions").fetchone()[0],
            "snapshots": c.execute("SELECT COUNT(*) FROM depot_snapshot").fetchone()[0],
        }

    def trades_letzte(self, tage=7):
        since = (datetime.now() - timedelta(days=tage)).isoformat()
        rows = self.conn.execute(
            "SELECT zeit, depot_typ, ticker, aktion, menge, preis FROM trades "
            "WHERE zeit >= ? ORDER BY zeit DESC", (since,)).fetchall()
        return [dict(r) for r in rows]

    def ki_aktionen_vert(self):
        c = self.conn.cursor()
        rows = c.execute(
            "SELECT aktion, COUNT(*) FROM ki_decisions GROUP BY aktion").fetchall()
        return {r["aktion"]: r["COUNT(*)"] for r in rows}

    def trades_nach_typ(self, tage=7):
        since = (datetime.now() - timedelta(days=tage)).isoformat()
        c = self.conn.cursor()
        rows = c.execute(
            "SELECT depot_typ, aktion, COUNT(*) FROM trades WHERE zeit >= ? "
            "GROUP BY depot_typ, aktion", (since,)).fetchall()
        res = {}
        for r in rows:
            res.setdefault(r["depot_typ"], {})[r["aktion"]] = r["COUNT(*)"]
        return res

    def query_trades(self, typ=None, ticker=None, aktion=None, tage=30,
                     limit=200, order="DESC", tenant_id=1):
        """Flexible Trade-Suche mit Filtern.
        typ: 'aktien'|'etf'|'spec'|None (alle)
        ticker: Teilstring-Suche (LIKE %x%)
        aktion: 'kaufen'|'verkaufen'|None
        tage: nur Trades der letzten N Tage
        order: 'DESC'|'ASC' (Zeit)
        """
        since = (datetime.now() - timedelta(days=tage)).isoformat()
        sql = ("SELECT zeit, depot_typ, ticker, aktion, menge, preis, grund, konfidenz "
               "FROM trades WHERE zeit >= ? AND tenant_id = ?")
        params = [since, tenant_id]
        if typ:
            sql += " AND depot_typ = ?"
            params.append(typ)
        if ticker:
            sql += " AND ticker LIKE ?"
            params.append(f"%{ticker}%")
        if aktion:
            sql += " AND aktion = ?"
            params.append(aktion)
        sql += f" ORDER BY zeit {_safe_order(order)} LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def query_ki(self, typ=None, ticker=None, aktion=None, tage=30,
                 limit=200, order="DESC", provider=None, regel_id=None, fallback=None,
                 tenant_id=1):
        """Flexible KI-Entscheidungs-Suche (ki_decisions Tabelle).
        Neu (v2.19.1): Filter provider/regel_id/fallback."""
        since = (datetime.now() - timedelta(days=tage)).isoformat()
        sql = ("SELECT zeit, ticker, aktion, konfidenz, grund, depot_typ, risk, "
               "decision_id, provider, regel_id, fallback "
               "FROM ki_decisions WHERE zeit >= ? AND tenant_id = ?")
        params = [since, tenant_id]
        if typ:
            sql += " AND depot_typ = ?"
            params.append(typ)
        if ticker:
            sql += " AND ticker LIKE ?"
            params.append(f"%{ticker}%")
        if aktion:
            sql += " AND aktion = ?"
            params.append(aktion)
        if provider:
            sql += " AND provider = ?"
            params.append(provider)
        if regel_id:
            sql += " AND regel_id = ?"
            params.append(regel_id)
        if fallback is not None:
            sql += " AND fallback = ?"
            params.append("True" if fallback else "False")
        sql += f" ORDER BY zeit {_safe_order(order)} LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def analyse_karten(self, tage=30):
        """Phase E: Kompakte Kennzahlen für Analyse-Tab (ehrlich, keine erfundenen Felder)."""
        since = (datetime.now() - timedelta(days=tage)).isoformat()
        c = self.conn
        trades = c.execute("SELECT aktion, konfidenz FROM trades WHERE zeit >= ?", (since,)).fetchall()
        kis = c.execute("SELECT aktion, konfidenz FROM ki_decisions WHERE zeit >= ?", (since,)).fetchall()
        n_trades = len(trades)
        n_ki = len(kis)
        kauf = sum(1 for t in trades if t["aktion"] == "kauf")
        verkauf = sum(1 for t in trades if t["aktion"] == "verkauf")
        halten = sum(1 for t in kis if t["aktion"] == "halten")
        # Konfidenz-Durchschnitt (nur wo vorhanden)
        konf_vals = [t["konfidenz"] for t in kis if t["konfidenz"] is not None]
        konf_schnitt = round(sum(konf_vals)/len(konf_vals), 1) if konf_vals else None
        # Neue Felder (v2.19.1): echt aus DB, nicht mehr n/a
        n_mit_decision = c.execute(
            "SELECT COUNT(*) FROM ki_decisions WHERE zeit >= ? AND decision_id IS NOT NULL", (since,)).fetchone()[0]
        n_fallback = c.execute(
            "SELECT COUNT(*) FROM ki_decisions WHERE zeit >= ? AND fallback = 'True'", (since,)).fetchone()[0]
        n_provider_unknown = c.execute(
            "SELECT COUNT(*) FROM ki_decisions WHERE zeit >= ? AND (provider IS NULL OR provider = 'unknown')", (since,)).fetchone()[0]
        n_mit_regel = c.execute(
            "SELECT COUNT(*) FROM ki_decisions WHERE zeit >= ? AND regel_id IS NOT NULL", (since,)).fetchone()[0]
        # trades mit decision_id (weicher Match)
        n_trades_mit_di = c.execute(
            "SELECT COUNT(*) FROM trades WHERE zeit >= ? AND decision_id IS NOT NULL", (since,)).fetchone()[0]
        # provider_verteilung
        prov_rows = c.execute(
            "SELECT provider, COUNT(*) FROM ki_decisions WHERE zeit >= ? GROUP BY provider", (since,)).fetchall()
        provider_vert = {r["provider"] or "unbekannt": r["COUNT(*)"] for r in prov_rows}
        return {
            "trades_zeitraum": n_trades,
            "ki_entscheidungen": n_ki,
            "kauf_verkauf_halte": {"kauf": kauf, "verkauf": verkauf, "halten": halten},
            "entscheidungen_mit_decision_id": f"{n_mit_decision}/{n_ki}",
            "legacy_fallbacks": n_fallback,
            "konfidenz_schnitt": konf_schnitt,
            "konfidenz_ohne_treffer": "n/a",
            "provider_fehler": n_provider_unknown,
            "provider_verteilung": provider_vert,
            "entscheidungen_mit_regel": f"{n_mit_regel}/{n_ki}",
            "trades_mit_decision_id": f"{n_trades_mit_di}/{n_trades}",
            "cooldown_ereignisse": "siehe ki_cooldown.json",
            "trades_ohne_ki_zuordnung": f"{n_trades - n_trades_mit_di}/{n_trades} (weicher Match)",
        }

    def match_trades_ki(self, zeitfenster_min=10):
        """Weicher Match: Trades ohne decision_id <-> ki_decisions ueber Ticker + Zeitfenster.
        EHRLICH: nur als 'unsichere' Zuordnung markiert, wenn kein direkter decision_id-Key existiert.
        Direkter Key (trade.decision_id == ki_decisions.decision_id) hat Vorrang."""
        c = self.conn.cursor()
        # 1) Direkte Keys bereits gesetzt?
        direkt = c.execute(
            "SELECT COUNT(*) FROM trades t JOIN ki_decisions k ON t.decision_id = k.decision_id "
            "WHERE t.decision_id IS NOT NULL").fetchone()[0]
        # 2) Weicher Match (nur trades ohne decision_id)
        weich = c.execute("""
            SELECT t.id, k.decision_id FROM trades t
            JOIN ki_decisions k ON t.ticker = k.ticker
                AND abs(julianday(t.zeit) - julianday(k.zeit)) * 1440 <= ?
            WHERE t.decision_id IS NULL
            ORDER BY t.zeit
        """, (zeitfenster_min,)).fetchall()
        # Update (nur wo eindeutig: gleicher ticker, nur 1 ki im Fenster)
        geaendert = 0
        for tid, dec_id in weich:
            anz = c.execute(
                "SELECT COUNT(*) FROM ki_decisions k WHERE k.ticker = (SELECT ticker FROM trades WHERE id=?) "
                "AND abs(julianday(k.zeit) - julianday((SELECT zeit FROM trades WHERE id=?))) * 1440 <= ?",
                (tid, tid, zeitfenster_min)).fetchone()[0]
            if anz == 1:  # eindeutig
                c.execute("UPDATE trades SET decision_id = ? WHERE id = ?", (dec_id, tid))
                geaendert += 1
        self.conn.commit()
        return {"direkt": direkt, "weich_gematched": geaendert,
                "hinweis": "Weicher Match nur wo eindeutig (1 KI im Zeitfenster). Sonst NULL (ehrlich)."}

    def close(self):
        self.conn.close()

    # ── PHASE 1: Tenant-Helper (Mandanten-Modell v2.26.0) ──
    def tenant_ensure_default(self):
        """Stellt sicher, dass der Default-Tenant existiert. Gibt tenant_id zurueck."""
        c = self.conn.cursor()
        row = c.execute("SELECT id FROM tenants WHERE tenant_key = 'default'").fetchone()
        if row:
            return row["id"]
        c.execute("INSERT INTO tenants (tenant_key, name, status, plan_or_type, default_trading_mode) "
                  "VALUES ('default', 'Micro-Trader Hauptmandant', 'aktiv', 'personal', 'SHADOW')")
        self.conn.commit()
        return c.lastrowid

    def tenant_create(self, key, name, plan_or_type="personal", default_mode="SHADOW"):
        """Neuen Tenant anlegen. Gibt (tenant_id, fehler) zurueck."""
        c = self.conn.cursor()
        try:
            c.execute("INSERT INTO tenants (tenant_key, name, status, plan_or_type, default_trading_mode) "
                      "VALUES (?, ?, 'aktiv', ?, ?)", (key, name, plan_or_type, default_mode))
            self.conn.commit()
            return c.lastrowid, None
        except sqlite3.IntegrityError:
            return None, "tenant_key existiert bereits"

    def tenant_list(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT id, tenant_key, name, status, plan_or_type, default_trading_mode, created_at "
            "FROM tenants ORDER BY id").fetchall()]

    def tenant_get(self, tenant_id):
        row = self.conn.execute(
            "SELECT id, tenant_key, name, status, plan_or_type, default_trading_mode, risk_policy_id, created_at "
            "FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        return dict(row) if row else None

    def tenant_membership_add(self, tenant_id, user_id, role="user"):
        """User einem Tenant zuordnen (idempotent)."""
        c = self.conn.cursor()
        try:
            c.execute("INSERT OR IGNORE INTO tenant_memberships (tenant_id, user_id, role, status) "
                      "VALUES (?, ?, ?, 'aktiv')", (tenant_id, user_id, role))
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    def tenant_memberships_for_user(self, user_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT tm.tenant_id, tm.role, tm.status, t.name, t.tenant_key, t.default_trading_mode "
            "FROM tenant_memberships tm JOIN tenants t ON t.id = tm.tenant_id "
            "WHERE tm.user_id = ? ORDER BY tm.tenant_id", (user_id,)).fetchall()]

    def tenant_membership_role(self, tenant_id, user_id):
        row = self.conn.execute(
            "SELECT role, status FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?",
            (tenant_id, user_id)).fetchone()
        return dict(row) if row else None

    def tenant_user_ids(self, tenant_id):
        return [r["user_id"] for r in self.conn.execute(
            "SELECT user_id FROM tenant_memberships WHERE tenant_id = ?", (tenant_id,)).fetchall()]

    def workspace_create(self, tenant_id, key, name, trading_mode="SHADOW"):
        c = self.conn.cursor()
        try:
            c.execute("INSERT INTO workspaces (tenant_id, workspace_key, name, trading_mode, status) "
                      "VALUES (?, ?, ?, ?, 'aktiv')", (tenant_id, key, name, trading_mode))
            self.conn.commit()
            return c.lastrowid, None
        except sqlite3.IntegrityError:
            return None, "workspace_key existiert bereits in diesem Tenant"

    def workspace_list(self, tenant_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT id, tenant_id, workspace_key, name, trading_mode, status, created_at "
            "FROM workspaces WHERE tenant_id = ? ORDER BY id", (tenant_id,)).fetchall()]


if __name__ == "__main__":
    db = MTDB()
    db.sync(verbose=True)
    print("\nKI-Aktionen (gesamt):", db.ki_aktionen_vert())
    print("Trades letzte 7 Tage:", db.trades_nach_typ(7))
