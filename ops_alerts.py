"""ops_alerts.py — Phase 12: Monitoring und Alerts.

Erzeugt + speichert Alerts bei kritischen Zuständen. Liest SystemStatus
(ops_status) und erzeugt Alerts bei: DEGRADED/BLOCKED/SAFE_STOP, Providerfehler,
News-Ausfall, Datenalter, P0-News, Release abgelaufen, Recon-Mismatch, etc.

PAPER_ONLY. Keine Secrets. Alerts in ops_alerts.json (isoliert).

Aufruf: from ops_alerts import evaluate_alerts, list_alerts, ack_alert
"""

import os, json, sqlite3
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ALERTS_PF = os.path.join(BASE, "ops_alerts.json")
NEWS_CACHE = os.path.join(BASE, "news_cache.json")

SEVERITY = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load():
    if os.path.exists(ALERTS_PF):
        try:
            return json.load(open(ALERTS_PF, encoding="utf-8"))
        except Exception:
            pass
    return []


def _save(alerts):
    json.dump(alerts[-500:], open(ALERTS_PF, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


def _age_seconds(ts):
    if not ts:
        return None
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - dt).total_seconds()
    except Exception:
        return None


def evaluate_alerts():
    """Prueft SystemStatus und erzeugt neue Alerts. Returns Liste neuer Alerts."""
    from ops_status import build_system_status, build_provider_status, build_reconciliation_status
    alerts = _load()
    new = []

    def add(severity, category, title, desc, resource=""):
        a = {
            "alert_id": f"al_{int(__import__('time').time())}_{len(alerts)+len(new)}",
            "tenant_id": 1, "severity": severity, "category": category,
            "title": title, "description": desc, "created_at": _now(),
            "source": "ops_alerts.evaluate", "related_resource": resource,
            "acknowledged": False, "resolved": False, "resolved_by": None,
            "resolved_at": None,
        }
        new.append(a)

    s = build_system_status()

    # System-Health
    if s["health"] in ("BLOCKED", "OFFLINE", "UNKNOWN"):
        add("CRITICAL", "system", f"System {s['health']}", s.get("health_reason", ""))
    elif s["health"] == "SAFE_STOP":
        add("HIGH", "system", "SAFE_STOP aktiv", s.get("safe_stop_reason", ""))
    elif s["health"] == "DEGRADED":
        add("MEDIUM", "system", "System DEGRADED", s.get("health_reason", ""))

    # Provider-Fehler
    for p in build_provider_status():
        if p["status"] == "ERROR":
            add("HIGH", "provider", f"Provider-Fehler: {p['provider_name']}",
                str(p.get("last_error", "")), p["provider_id"])
        elif p["status"] == "NOT_AVAILABLE" and p["provider_type"] == "LIVE_BROKER":
            pass  # erwartet (PAPER_ONLY), kein Alert

    # News-Ausfall
    if not s["last_news_run"]:
        add("MEDIUM", "news", "Keine News gelaufen", "news_cache.json leer/fehlt")
    else:
        age = _age_seconds(s["last_news_run"])
        if age and age > 7200:
            add("LOW", "news", "News veraltet", f"letzter Lauf vor {int(age//3600)}h")

    # P0-News
    if os.path.exists(NEWS_CACHE):
        try:
            nc = json.load(open(NEWS_CACHE, encoding="utf-8"))
            p0 = [h for h in nc.get("headlines", []) if h.get("urgency") == "P0"]
            if p0:
                add("CRITICAL", "news", f"P0-News: {len(p0)}", p0[0].get("title", "")[:80])
        except Exception:
            pass

    # Reconciliation
    rc = build_reconciliation_status()
    if rc.get("status") == "ERROR" or rc.get("blocking"):
        add("HIGH", "reconciliation", "Reconciliation fehlgeschlagen",
            rc.get("reason", ""))

    # Release abgelaufen
    if s["release"].get("status") == "EXPIRED":
        add("MEDIUM", "release", "Release abgelaufen", s["release"].get("release_id", ""))

    if new:
        alerts.extend(new)
        _save(alerts)
    return new


def list_alerts(unresolved_only=True):
    alerts = _load()
    if unresolved_only:
        alerts = [a for a in alerts if not a["resolved"]]
    return alerts


def ack_alert(alert_id, by="system"):
    alerts = _load()
    for a in alerts:
        if a["alert_id"] == alert_id:
            a["acknowledged"] = True
            _save(alerts)
            return True
    return False


def resolve_alert(alert_id, by="system"):
    alerts = _load()
    for a in alerts:
        if a["alert_id"] == alert_id:
            a["resolved"] = True
            a["resolved_by"] = by
            a["resolved_at"] = _now()
            _save(alerts)
            return True
    return False


if __name__ == "__main__":
    neu = evaluate_alerts()
    print(f"Neue Alerts: {len(neu)}")
    for a in neu:
        print(f"  [{a['severity']}] {a['category']}: {a['title']}")
    print(f"Offene Alerts gesamt: {len(list_alerts())}")
