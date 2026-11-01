"""ops_status.py — Phase 1: Datenmodell für den Betriebsstatus (Operations Center).

Aggregiert den zentralen SystemStatus aus vorhandenen Modulen. NUR LESEND.
PAPER_ONLY: keine echten Orders/Keys. Live-Broker = NOT_AVAILABLE.

Aufruf: from ops_status import build_system_status, Health, OpsStatusError
"""

import os, json, time, sqlite3, glob
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "micro_trader.db")
NEWS_CACHE = os.path.join(BASE, "news_cache.json")

# Health-Status
HEALTH = ["HEALTHY", "DEGRADED", "WARNING", "BLOCKED", "SAFE_STOP", "OFFLINE", "UNKNOWN"]

# Risiko-Zustände
RISK_STATES = ["NORMAL", "WATCH", "LIMIT_NEAR", "LIMIT_REACHED",
               "BLOCKED", "SUSPENDED", "SAFE_STOP"]

# Provider-Typen
PROVIDER_TYPES = ["MARKET_DATA", "NEWS", "KI", "PAPER_BROKER", "SANDBOX_BROKER", "LIVE_BROKER"]


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _age_seconds(ts_str):
    """Alter eines Timestamp-Strings in Sekunden (None wenn nicht parsebar)."""
    if not ts_str:
        return None
    try:
        try:
            dt = datetime.fromisoformat(ts_str)
        except Exception:
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - dt).total_seconds()
    except Exception:
        return None


class OpsStatusError(Exception):
    pass


# ── ProviderStatus ──────────────────────────────────────────────
def build_provider_status():
    """Sammelt Provider/Quell-Status aus news_cache + markt_daten."""
    providers = []
    if os.path.exists(NEWS_CACHE):
        try:
            nc = json.load(open(NEWS_CACHE, encoding="utf-8"))
            fs = nc.get("feed_status", {})
            for host, (count, err) in fs.items():
                providers.append({
                    "provider_id": f"news:{host}",
                    "provider_name": host,
                    "provider_type": "NEWS",
                    "environment": "PAPER",
                    "status": "ERROR" if err else "OK",
                    "last_error": err,
                    "rate_limit_state": "unknown",
                    "api_key_configured": True,
                    "secret_reference": None,
                })
        except Exception:
            pass
    try:
        import marktdaten
        for name in getattr(marktdaten, "PROVIDER_CHAIN", ["yfinance", "finnhub",
                                                           "twelvedata", "alphavantage"]):
            providers.append({
                "provider_id": f"md:{name}",
                "provider_name": name,
                "provider_type": "MARKET_DATA",
                "environment": "PAPER",
                "status": "UNKNOWN",
                "last_error": None,
                "rate_limit_state": "unknown",
                "api_key_configured": True,
                "secret_reference": None,
            })
    except Exception:
        pass
    providers.append({
        "provider_id": "ki:openrouter", "provider_name": "openrouter (ki_provider Pool)",
        "provider_type": "KI", "environment": "PAPER",
        "status": "OK", "last_error": None,
        "rate_limit_state": "unknown", "api_key_configured": True, "secret_reference": None,
    })
    providers.append({
        "provider_id": "broker:simulator", "provider_name": "BrokerSimulator",
        "provider_type": "SANDBOX_BROKER", "environment": "PAPER",
        "status": "CONNECTED (SIM)", "last_error": None,
        "rate_limit_state": "n/a", "api_key_configured": False, "secret_reference": None,
    })
    providers.append({
        "provider_id": "broker:live", "provider_name": "Live-Broker",
        "provider_type": "LIVE_BROKER", "environment": "LIVE",
        "status": "NOT_AVAILABLE", "last_error": "Live deaktiviert (PAPER_ONLY)",
        "rate_limit_state": "n/a", "api_key_configured": False, "secret_reference": None,
    })
    return providers


# ── ReleaseStatus ───────────────────────────────────────────────
def build_release_status():
    """Letzter freigegebener Release aus live_releases (Phase 8 Tabelle)."""
    try:
        conn = sqlite3.connect(DB)
        row = conn.execute(
            "SELECT release_hash, status, approved_by, freigegeben FROM live_releases "
            "ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        if row:
            return {
                "release_id": row[0], "status": row[1], "approved_by": row[2],
                "approved_at": row[3], "is_valid": row[1] == "APPROVED",
                "expires_at": None, "validation_summary": "manual approval",
            }
    except Exception:
        pass
    return {"release_id": None, "status": "NONE", "is_valid": False,
            "approved_by": None, "approved_at": None, "expires_at": None}


# ── PortfolioStatus ─────────────────────────────────────────────
def build_portfolio_status(tenant_id=1):
    """Aggregiert Depot-Status aus depot_*.json."""
    portfolios = []
    for dp in glob.glob(os.path.join(BASE, "depot_*.json")):
        try:
            d = json.load(open(dp, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        kind = "aktien" if "aktien" in os.path.basename(dp) else (
            "etf" if "etf" in os.path.basename(dp) else "spec")
        val = d.get("wert", 0) or 0
        cash = d.get("bargeld", 0) or 0
        risk_state = "SAFE_STOP" if d.get("paused") else "NORMAL"
        portfolios.append({
            "tenant_id": tenant_id,
            "workspace_id": d.get("depot_id") or os.path.basename(dp),
            "portfolio_id": d.get("depot_id") or os.path.basename(dp).replace(".json", ""),
            "portfolio_type": kind,
            "mode": "PAPER",
            "status": "PAUSED" if d.get("paused") else "OPEN",
            "value": round(val, 2),
            "cash": round(cash, 2),
            "return_percent": d.get("rendite_pct", 0),
            "drawdown_percent": 0,
            "open_positions": len(d.get("positions", {}) or {}),
            "pending_orders": 0,
            "risk_state": risk_state,
            "close_state": "CLOSED" if d.get("closed") else "OPEN",
            "last_update": d.get("updated_at") or _now(),
        })
    return portfolios


# ── ReconciliationStatus ────────────────────────────────────────
def build_reconciliation_status(tenant_id=1):
    """Status aus sim_broker_fills (falls vorhanden)."""
    fills = os.path.join(BASE, "sim_broker_fills.json")
    if not os.path.exists(fills):
        return {"status": "NO_DATA", "blocking": False,
                "reason": "kein Sim-Lauf (PAPER_ONLY)", "timestamp": _now()}
    return {"status": "RECONCILED", "blocking": False, "reason": None, "timestamp": _now()}


# ── SystemStatus (zentral) ──────────────────────────────────────
def build_system_status():
    """Baut das zentrale SystemStatus-Aggregat."""
    news_run = None
    if os.path.exists(NEWS_CACHE):
        try:
            news_run = json.load(open(NEWS_CACHE, encoding="utf-8")).get("zeit")
        except Exception:
            pass
    snap_age = None
    try:
        import market_snapshot
        ms = market_snapshot.MarketSnapshot(["AAPL"])
        snap_age = _age_seconds(ms.zeit.isoformat()) if ms else None
    except Exception:
        pass

    try:
        from live_system import LiveSystem
        ls = LiveSystem(tenant_id=1)
        safe_stop = ls.ist_gestoppt
        live_mode = ls.config.get("modus")
        ss_reason = ls.config.get("safe_stop_reason")
    except Exception:
        safe_stop = True
        live_mode = "UNKNOWN"
        ss_reason = "LiveSystem unerreichbar"

    health = "HEALTHY"
    health_reason = "alle Kernsysteme ok"
    if safe_stop:
        health = "SAFE_STOP"
        health_reason = "Live Kill-Switch aktiv"
    elif snap_age and snap_age > 3600:
        health = "WARNING"
        health_reason = "MarketSnapshot veraltet"

    providers = build_provider_status()
    broken = [p for p in providers if p["status"] in ("ERROR", "NOT_AVAILABLE")
              and p["provider_type"] != "LIVE_BROKER"]

    release = build_release_status()
    portfolios = build_portfolio_status()
    recon = build_reconciliation_status()

    return {
        "system_status_id": f"sys_{int(time.time())}",
        "timestamp": _now(),
        "environment": "PAPER",
        "mode": live_mode,
        "paper_only": True,
        "health": health,
        "health_reason": health_reason,
        "active_release_id": release.get("release_id"),
        "active_release_version": None,
        "last_pipeline_run": news_run,
        "last_news_run": news_run,
        "last_market_snapshot": _now() if snap_age is not None else None,
        "last_learning_run": None,
        "last_reconciliation": recon.get("timestamp"),
        "broker_status": "CONNECTED (SIM)" if not safe_stop else "SAFE_STOP",
        "provider_status": "DEGRADED" if broken else "OK",
        "risk_status": "NORMAL",
        "audit_status": "OK",
        "active_alert_count": len(broken) + (1 if safe_stop else 0),
        "safe_stop": safe_stop,
        "safe_stop_reason": ss_reason,
        "providers": providers,
        "release": release,
        "portfolios": portfolios,
        "reconciliation": recon,
        "alerts": [],
    }


if __name__ == "__main__":
    import pprint
    s = build_system_status()
    pprint.pprint({k: v for k, v in s.items() if k not in
                   ("providers", "portfolios", "release", "reconciliation")})
    print(f"\nProviders: {len(s['providers'])} | Portfolios: {len(s['portfolios'])}")
