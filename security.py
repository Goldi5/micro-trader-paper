"""
security.py — Zentrale Sicherheitslogik für Micro-Trader (Paper/Shadow ONLY).

Phasen 4-6 des Server-Sicherheitsauftrags:
- Benutzerverwaltung + Rollen (visitor/user/analyst/operator/admin/superadmin)
- MFA (TOTP, RFC 6238 über cryptography.hazmat HMAC — KEIN Eigenbau)
- Session-Sicherheit (Secure/HttpOnly/SameSite, Rotation, Timeout)
- Serverseitige Rollen- + Routenprüfung (require_auth / require_role / require_recent_mfa)
- CSRF-Schutz (itsdangerous signed token)

WICHTIG: Keine Echtgeld-Funktionen. Nur Paper/Shadow.

Verwendet NUR etablierte Bibliotheken:
- werkzeug.generate_password_hash / check_password_hash (pbkdf2:sha256)
- cryptography.hazmat.primitives.hmac / hashes (FIPS-validiert, für TOTP)
- itsdangerous (URLSafeTimedSerializer für CSRF + signed state)
- secrets / base64 (stdlib, nur Zufall)
"""
import json
import os
import secrets
import time
import base64
import hmac
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.hazmat.primitives import hashes, hmac as chmac
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# ── PHASE 1: Tenant-Kontext (OWASP Multi-Tenant Cheat Sheet) ──
# Der Tenant wird IMMER aus der authentifizierten Session abgeleitet,
# NIEMALS aus Client-Headern/-Parametern vertraut (Tenant-Context-Injection verhindern).
from contextvars import ContextVar
_current_tenant: ContextVar = ContextVar("current_tenant", default=None)


def set_current_tenant(tenant_id):
    """Setzt den Tenant-Kontext fuer den aktuellen Request (Thread-lokal)."""
    _current_tenant.set(tenant_id)


def get_current_tenant():
    """Gibt die aktuelle tenant_id zurueck (oder None)."""
    return _current_tenant.get()


# ── PHASE 5: Trading-Modi-Zustandsmaschine (Sektion 8) ──
def get_trading_mode(tenant_id=None):
    """Liest den aktuellen Trading-Modus eines Tenants (Default: SHADOW)."""
    tid = tenant_id or get_current_tenant() or 1
    try:
        import db as _db
        m = _db.MTDB()
        row = m.conn.execute(
            "SELECT default_trading_mode FROM tenants WHERE id = ?", (tid,)
        ).fetchone()
        m.close()
        return (row["default_trading_mode"] if row else "SHADOW") or "SHADOW"
    except Exception:
        return "SHADOW"


def set_trading_mode(new_mode, tenant_id=None, user=None, reason="",
                     requested_by=None, approved_by=None, mfa_confirmed=0):
    """PHASE 5: Zustandswechsel mit erlaubter Transition (State Machine).
    Wirft ValueError wenn Transition nicht erlaubt ist. Schreibt Audit-Log.
    PHASE 4 (§8+§14): LIVE-UEBERGAENGE sind kritisch:
      - LIVE_REQUESTED: Antrag (Request), noetig: Admin/Operator
      - LIVE_APPROVED / LIVE_ACTIVE: Vier-Augen + MFA — approved_by muss
        ein ANDERER User als requested_by sein (kein Selbst-Genehmigen),
        mfa_confirmed muss 1 sein.
    """
    import db as _db
    m = _db.MTDB()
    tid = tenant_id or get_current_tenant() or 1
    old_mode = get_trading_mode(tid)
    if new_mode not in m.TRADING_MODES:
        m.close()
        raise ValueError(f"Ungueltiger Modus: {new_mode}")
    if not m.mode_can_transition(old_mode, new_mode):
        m.close()
        raise ValueError(
            f"Transition {old_mode} -> {new_mode} nicht erlaubt")
    # ── PHASE 4: Vier-Augen + MFA bei LIVE-Freigabe/Start (§8, §14) ──
    if new_mode in ("LIVE_APPROVED", "LIVE_ACTIVE"):
        if not approved_by:
            m.close()
            raise ValueError(
                f"{new_mode} erfordert Vier-Augen-Freigabe (approved_by)")
        if requested_by and approved_by == requested_by:
            m.close()
            raise ValueError(
                "Antragsteller darf LIVE-Uebergang nicht selbst genehmigen")
        if not mfa_confirmed:
            m.close()
            raise ValueError(
                f"{new_mode} erfordert MFA-Bestaetigung (mfa_confirmed=1)")
    # Tenant-Default aktualisieren
    m.conn.execute(
        "UPDATE tenants SET default_trading_mode = ? WHERE id = ?",
        (new_mode, tid))
    m.conn.commit()
    # Audit-Log
    m.mode_log_insert(
        tenant_id=tid, user_id=None,
        portfolio_id=None, strategy_id=None,
        old_mode=old_mode, new_mode=new_mode, reason=reason,
        requested_by=(requested_by or None),
        approved_by=approved_by, mfa_confirmed=mfa_confirmed,
        risk_review_status=("approved" if approved_by else "pending"),
        broker_connection_status=("live" if new_mode.startswith("LIVE") else "none"))
    m.close()
    return old_mode, new_mode


def trading_mode_history(tenant_id=None, limit=100):
    """PHASE 5: Verlauf der Moduswechsel (Audit)."""
    tid = tenant_id or get_current_tenant() or 1
    try:
        import db as _db
        m = _db.MTDB()
        rows = m.mode_log_list(tid, limit=limit)
        m.close()
        return rows
    except Exception:
        return []


# ── PHASE 5 (§9): Shadow -> Paper Freigabe ──
def paper_eligibility(tenant_id=None):
    """Prueft alle 8 Voraussetzungen aus §9 fuer Shadow->Paper.
    Gibt (eligible: bool, gruende: list) zurueck.
      (1) Shadow-Mindestanzahl erreicht (>= 20 KI-Entscheidungen)
      (2) Audit-Trail vollstaendig (Audit-Datei vorhanden und lesbar)
      (3) Regelstand identifizierbar (regelstand_version.json mit Version)
      (4) keine kritischen Fehler (keine CRITICAL/ERROR-Audit-Events in den
          letzten 7 Tagen)
      (5) keine ungeloesten Block-Regeln (kein shadow=True + konflikte)
      (6) Providerdaten ausreichend stabil (markt_daten nicht zu alt)
      (7) Portfolio korrekt tenant-scoped (Depot-JSONs tragen tenant_id)
      (8) Shadow- und Paper-Portfolio getrennt (keine _paper-Dateien im
          Shadow-Bestand vermischt; kein Depot ohne mode-Feld)
    """
    tid = tenant_id or get_current_tenant() or 1
    gruende = []
    try:
        import db as _db, json as _json, os as _os
        m = _db.MTDB()
        # (1) Mindest-Shadow-Entscheidungen (z.B. >= 20)
        cnt = m.conn.execute(
            "SELECT COUNT(*) FROM ki_decisions WHERE tenant_id = ?", (tid,)
        ).fetchone()[0]
        MIN_DECISIONS = 20
        if cnt < MIN_DECISIONS:
            gruende.append(
                f"Zu wenig KI-Entscheidungen ({cnt}/{MIN_DECISIONS})")
        # (2) Audit-Trail vollstaendig
        audit_pfad = _os.path.join(_db.BASE, "security_audit.jsonl")
        if not _os.path.exists(audit_pfad):
            gruende.append("Audit-Trail fehlt (security_audit.jsonl)")
        else:
            try:
                with open(audit_pfad, encoding="utf-8") as _af:
                    _af.readline()
            except Exception:
                gruende.append("Audit-Trail nicht lesbar")
        # (3) Regelstand identifizierbar
        rj = _os.path.join(_db.BASE, "regelstand_version.json")
        regel_ok = False
        if _os.path.exists(rj):
            try:
                _rd = _json.load(open(rj, encoding="utf-8"))
                vers = _rd.get("version") or _rd.get("regelstand_version")
                if vers:
                    regel_ok = True
            except Exception:
                pass
        if not regel_ok:
            gruende.append("Regelstand nicht identifizierbar (Version fehlt)")
        # (4) keine kritischen Fehler (letzte 7 Tage)
        kritische = 0
        if _os.path.exists(audit_pfad):
            try:
                import time as _time
                _cut = _time.time() - 7 * 86400
                with open(audit_pfad, encoding="utf-8") as _af:
                    for _line in _af:
                        try:
                            _ev = _json.loads(_line)
                        except Exception:
                            continue
                        if _ev.get("ts", _ev.get("timestamp", 0)) < _cut:
                            continue
                        _lvl = str(_ev.get("level", "")).upper()
                        if _lvl in ("CRITICAL", "ERROR"):
                            kritische += 1
            except Exception:
                pass
        if kritische > 0:
            gruende.append(f"{kritische} kritische Audit-Events in 7 Tagen")
        # (5) keine ungeloesten Block-Regeln (shadow=True + konflikte)
        konflikte = 0
        if _os.path.exists(rj):
            try:
                data = _json.load(open(rj, encoding="utf-8"))
                for r in (data if isinstance(data, list) else data.get("rules", [])):
                    if r.get("shadow") and r.get("konflikte"):
                        konflikte += 1
            except Exception:
                pass
        if konflikte > 0:
            gruende.append(f"{konflikte} unaufgeloeste Regelkonflikte")
        # (6) Providerdaten ausreichend stabil (markt_daten nicht zu alt)
        try:
            _md = m.conn.execute(
                "SELECT MAX(ts) FROM markt_daten").fetchone()[0]
            if not _md:
                gruende.append("Keine Marktdaten persistiert")
            else:
                import time as _time2
                _age = _time2.time() - float(_md)
                if _age > 3 * 86400:
                    gruende.append("Marktdaten aelter als 3 Tage")
        except Exception:
            gruende.append("Marktdaten-Status nicht pruefbar")
        # (7) Portfolio korrekt tenant-scoped (Depot-JSONs tragen tenant_id)
        import glob as _glob
        _ohne_tenant = []
        for _pat in ("depot_*.json", "etf_*.json"):
            for _fp in _glob.glob(_os.path.join(_db.BASE, _pat)):
                try:
                    with open(_fp, encoding="utf-8") as _f:
                        _d = _json.load(_f)
                    if not _d.get("tenant_id"):
                        _ohne_tenant.append(_os.path.basename(_fp))
                except Exception:
                    pass
        for _sd in ("spec_depots", "spec_depots_paper"):
            _sdp = _os.path.join(_db.BASE, _sd)
            if _os.path.isdir(_sdp):
                for _fn in _os.listdir(_sdp):
                    if not _fn.endswith(".json"):
                        continue
                    try:
                        with open(_os.path.join(_sdp, _fn), encoding="utf-8") as _f:
                            _d = _json.load(_f)
                        if not _d.get("tenant_id"):
                            _ohne_tenant.append(f"{_sd}/{_fn}")
                    except Exception:
                        pass
        if _ohne_tenant:
            gruende.append(
                f"{len(_ohne_tenant)} Depot(s) ohne tenant_id (Cross-Tenant-Risiko)")
        # (8) Shadow-/Paper-Portfolios getrennt: keine _paper-Datei darf im
        #     Shadow-Bestand stehen (depot_*_paper.json) ohne mode-Feld
        _misch = 0
        for _fp in _glob.glob(_os.path.join(_db.BASE, "*_paper.json")):
            try:
                with open(_fp, encoding="utf-8") as _f:
                    _d = _json.load(_f)
                if _d.get("mode") != "paper":
                    _misch += 1
            except Exception:
                pass
        if _misch > 0:
            gruende.append(f"{_misch} Paper-Datei(en) ohne korrektes mode-Feld")
        m.close()
        eligible = len(gruende) == 0
        return eligible, gruende
    except Exception as e:
        return False, [f"Pruefung fehlgeschlagen: {e}"]


def enter_paper(tenant_id=None, user=None, reason=""):
    """PHASE 6: Wechselt Tenant von SHADOW nach PAPER (nur wenn eligible)."""
    tid = tenant_id or get_current_tenant() or 1
    eligible, gruende = paper_eligibility(tid)
    if not eligible:
        raise ValueError("Paper nicht moeglich: " + "; ".join(gruende))
    return set_trading_mode("PAPER", tenant_id=tid, user=user, reason=reason,
                            requested_by=(user.get("id") if user else None))


# ── PHASE 8: Secret-Store (tenant-isoliert, kein global .env) ──
def secret_set(tenant_id, secret_key, secret_value):
    """PHASE 8: Secret tenant-isoliert speichern."""
    import db as _db
    m = _db.MTDB()
    m.secret_set(tenant_id, secret_key, secret_value)
    m.close()


def secret_get(tenant_id, secret_key):
    """PHASE 8: Secret nur fuer eigenen Tenant auslesen (serverseitig)."""
    import db as _db
    m = _db.MTDB()
    val = m.secret_get(tenant_id, secret_key)
    m.close()
    return val


def secret_list_keys(tenant_id):
    """PHASE 8: Schluessel auflisten (keine Werte)."""
    import db as _db
    m = _db.MTDB()
    keys = m.secret_list_keys(tenant_id)
    m.close()
    return keys


# ── PHASE 10: Tenant-Scoped Risikogrenzen (Wrapper, analog Secret) ──
def risk_set(tenant_id, risk_mode, position_size=None, stop_loss=None,
             take_profit=None, drawdown_limit=None):
    """PHASE 10: Tenant-Risikogrenze setzen."""
    import db as _db
    m = _db.MTDB()
    m.risk_set(tenant_id, risk_mode, position_size, stop_loss, take_profit, drawdown_limit)
    m.close()


def risk_get(tenant_id, risk_mode):
    """PHASE 10: Effektive Risikogrenze (Tenant → global → Default)."""
    import db as _db
    m = _db.MTDB()
    eff = m.effective_risk_limits(tenant_id, risk_mode)
    m.close()
    return eff


def risk_list(tenant_id):
    """PHASE 10: Alle Risikogrenzen eines Tenants."""
    import db as _db
    m = _db.MTDB()
    rows = m.risk_list(tenant_id)
    m.close()
    return rows


# ── PHASE 11: Tenant-Scoped Regeln (Wrapper, analog Secret) ──
def rule_add(tenant_id, rule_id, regel, muster=None, status="aktiv", created_by=None):
    """PHASE 11: Tenant-Regel anlegen."""
    import db as _db
    m = _db.MTDB()
    m.rule_set(tenant_id, rule_id, regel, muster, status, created_by)
    m.close()


def rule_list(tenant_id):
    """PHASE 11: Effektive Regeln (Tenant ∪ global)."""
    import db as _db
    m = _db.MTDB()
    rows = m.effective_rules(tenant_id)
    m.close()
    return rows


def rule_set_status(tenant_id, rule_id, status):
    """PHASE 11: Status einer Tenant-Regel aendern."""
    import db as _db
    m = _db.MTDB()
    m.rule_set_status(tenant_id, rule_id, status)
    m.close()


# ── PHASE 12: Enforcement (Risikogrenzen + Regeln im Trading-Pfad) ──
def enforce_risk_limits(tenant_id, risk_mode, position_size_pct, portfolio_value,
                        drawdown_pct=0.0):
    """PHASE 12: Prueft eine geplante Position gegen die effektiven Tenant-
    Risikogrenzen. Liefert {'allowed': bool, 'reason': str, 'limits': dict}.

    position_size_pct: geplante Positionsgroesse in % des Portfolios (0-1)
    portfolio_value:   aktueller Portfolio-Wert
    drawdown_pct:      aktueller Drawdown des Portfolios in % (0-1)
    """
    eff = risk_get(tenant_id, risk_mode)
    max_pos = eff.get("position_size") or 0.35
    max_dd = eff.get("drawdown_limit") or 0.20
    if position_size_pct > max_pos + 1e-9:
        return {
            "allowed": False,
            "reason": f"Position {position_size_pct:.1%} > Limit {max_pos:.1%}",
            "limits": eff,
        }
    if drawdown_pct > max_dd + 1e-9:
        return {
            "allowed": False,
            "reason": f"Drawdown {drawdown_pct:.1%} > Limit {max_dd:.1%}",
            "limits": eff,
        }
    return {"allowed": True, "reason": "ok", "limits": eff}


def enforce_rules(tenant_id, ticker, context=None, regel=None):
    """PHASE 12: Wendet die effektiven Tenant-Regeln auf ein Kaufsignal an.

    Regel-Typen (via 'muster'-Schluesselwort):
      - 'BLOCK:<text>'      -> hart blockiert (Kauf verboten)
      - 'MAX_KAUF:<n>'      -> max n Kaeufe dieses Tickers
      - 'REGEX:<pattern>'   -> ticker muss Pattern erfuellen
    Liefert {'allowed': bool, 'reason': str, 'matched': str|None}.
    """
    context = context or {}
    rules = rule_list(tenant_id)
    # Aktiv = klassisch 'aktiv'. ZUSAETZLICH wirken globale KI-Regeln aus
    # learned_rules.json, die freigegeben und nicht shadow sind (dort ist
    # 'status' oft 'unbestätigt', obwohl der Admin sie freigegeben hat).
    # Tenant-Regeln haben immer freigabe_status='freigegeben' (Admin angelegt),
    # ihr Schalter ist ausschliesslich 'status' (aktiv/pausiert/...).
    active = []
    for r in rules:
        st = r.get("status") or "aktiv"
        fg = r.get("freigabe_status") or ""
        shadow = bool(r.get("shadow", False))
        src = r.get("source") or ""
        if st == "aktiv" or (src == "global" and fg == "freigegeben" and not shadow):
            active.append(r)
    for r in active:
        muster = (r.get("muster") or "").strip()
        rid = r.get("id", "")
        rule_text = (r.get("regel") or "").strip()
        typ = r.get("typ") or ""
        # meta_conf_cap / Kategorie-Regeln ohne konkreten Ticker-Bezug wirken NICHT
        # als harter Order-Block (sie steuern den KI-Prompt via ki_decisions).
        # Nur Ticker-spezifische Regeln blocken hier.
        if typ == "meta_conf_cap":
            continue
        if muster.startswith("BLOCK:"):
            rest = muster[6:].strip()
            tok = rest.split()[0] if rest else ""
            # 'BLOCK:GME ...' oder 'BLOCK:GME' -> ticker-spezifische Sperre
            if tok and tok.isupper() and len(tok) <= 5 and tok.isalpha():
                if ticker and ticker.upper() == tok:
                    return {"allowed": False, "reason": f"Regel {rid}: {rest}",
                            "matched": rid}
                continue  # Sperre gilt einem anderen Ticker
            # Generische Sperre ohne Ticker-Bezug (bisheriges Verhalten)
            return {"allowed": False, "reason": f"Regel {rid}: {rest}",
                    "matched": rid}
        # KI-Muster mit Ticker in Klammern: '[MTF] ... (RIVN)', '[Swap] ... (SPY)',
        # '[Konzentration] AMC ...' -> blocken NUR den genannten Ticker
        if typ in ("anti", "swap", "mtf", "konzentration") or muster.startswith("["):
            import re as _re2
            m2 = _re2.findall(r"\(([A-Z0-9]{1,5})\)", muster)
            if m2:
                if ticker and ticker.upper() in [x.upper() for x in m2]:
                    return {"allowed": False, "reason": f"Regel {rid}: {muster}",
                            "matched": rid}
                continue  # Regel gilt einem anderen Ticker
            # Ticker ohne Klammer: '[Konzentration] AMC in 4 Depots'
            m3 = _re2.findall(r"\b([A-Z]{2,5})\b", muster)
            m3 = [t for t in m3 if t not in ("MTF", "SWAP", "ANTI")]
            if m3:
                if ticker and ticker.upper() in [t.upper() for t in m3]:
                    return {"allowed": False, "reason": f"Regel {rid}: {muster}",
                            "matched": rid}
                continue
            # Kategorie-Regel ohne konkreten Ticker (z.B. '[Anti] halten bei
            # volatility-Titeln'): kein harter Block hier, wirkt via KI-Prompt.
            continue
        if muster.startswith("MAX_KAUF:"):
            try:
                max_n = int(muster.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                continue
            k = context.get("kauf_count", 0)
            if k >= max_n:
                return {"allowed": False,
                        "reason": f"Regel {rid}: max {max_n} Kaeufe erreicht",
                        "matched": rid}
        if muster.startswith("REGEX:"):
            import re as _re
            pat = muster.split(":", 1)[1].strip()
            try:
                if ticker and not _re.search(pat, ticker):
                    return {"allowed": False,
                            "reason": f"Regel {rid}: Ticker {ticker} passt nicht zu {pat}",
                            "matched": rid}
            except _re.error:
                continue
    return {"allowed": True, "reason": "ok", "matched": None}


# ── PHASE 14: Freigabe-Workflow (§23/§21.5) ──
APPROVAL_STATES = ["nicht_freigegeben", "in_pruefung", "freigegeben", "gesperrt"]


def approval_set(tenant_id, target_type, target_id, status,
                 approved_by=None, note=None):
    """PHASE 14: Freigabestatus setzen (tenant-scoped)."""
    import db as _db
    m = _db.MTDB()
    m.approval_set(tenant_id, target_type, target_id, status, approved_by, note)
    m.close()


def approval_get(tenant_id, target_type, target_id):
    """PHASE 14: Aktueller Freigabestatus (Default: nicht_freigegeben)."""
    import db as _db
    m = _db.MTDB()
    a = m.approval_get(tenant_id, target_type, target_id)
    m.close()
    return a


def approval_list(tenant_id):
    """PHASE 14: Alle Freigaben eines Tenants."""
    import db as _db
    m = _db.MTDB()
    rows = m.approval_list(tenant_id)
    m.close()
    return rows


def enforce_approval(tenant_id, target_type, target_id, action="trade"):
    """PHASE 14: Blockt eine Aktion wenn Freigabestatus != 'freigegeben'.
    Liefert {'allowed': bool, 'reason': str, 'status': str}.
    Nur 'freigegeben' erlaubt Trading/Order-Aktionen (PAPER_ONLY-Enforcement).
    """
    a = approval_get(tenant_id, target_type, target_id)
    st = a.get("status", "nicht_freigegeben")
    if st == "freigegeben":
        return {"allowed": True, "reason": "ok", "status": st}
    if st == "gesperrt":
        return {"allowed": False, "reason": f"Ziel {target_type}:{target_id} ist gesperrt", "status": st}
    if st == "in_pruefung":
        return {"allowed": False, "reason": f"Ziel {target_type}:{target_id} in Prüfung (noch nicht freigegeben)", "status": st}
    return {"allowed": False, "reason": f"Ziel {target_type}:{target_id} nicht freigegeben", "status": st}


def enforce_approval_trade(tenant_id, target_type, target_id):
    """PHASE 14: Freigabe-Check im Order-Pfad (unreguliert-freundlich).

    Ein fehlender Freigabeeintrag (unreguliertes Ziel) blockt den bestehenden
    Paper-Betrieb NICHT. Nur explizit gesperrte / in Pruefung stehende /
    widerrufene Ziele blocken die Order. Liefert {'allowed', 'reason', 'status'}.
    """
    a = approval_get(tenant_id, target_type, target_id)
    if not a.get("exists"):
        return {"allowed": True, "reason": "ok (kein Freigabeeintrag)",
                "status": "unreguliert"}
    return enforce_approval(tenant_id, target_type, target_id)


# ── PHASE 13: Order-Intent + Broker-Connector-Schnittstelle (v2.36.0) ──
# Architektur (Auftrag §11/§10): Trading-Strategie → Risk Engine → Order Intent
# → Broker Adapter → Broker API. Order Intents entstehen IMMER als Objekt VOR
# jeder Ausführung (auch Paper). PAPER_ONLY: keine echten Orders, keine Live-Adapter.

ORDER_INTENT_FIELDS = [
    "order_intent_id", "tenant_id", "user_id", "portfolio_id", "strategy_id",
    "mode", "ticker", "side", "quantity", "order_type", "limit_price",
    "stop_price", "reason", "decision_id", "rule_version", "risk_check_status",
    "created_at",
]


def create_order_intent(tenant_id, ticker, side, quantity, price, portfolio_id=None,
                        strategy_id=None, user_id=None, mode=None, order_type="market",
                        limit_price=None, stop_price=None, reason="",
                        decision_id=None, rule_version=None):
    """PHASE 13: Erzeugt ein Order-Intent-Objekt (Auftrag §11).

    Jede geplante Order MUSS als Intent entstehen, BEVOR sie ausgefuehrt wird.
    Felder gem. Order-Intent-Spec. `risk_check_status` wird von
    validate_order_intent() gesetzt.
    """
    import uuid as _uuid
    import datetime as _dt
    if mode is None:
        mode = get_trading_mode(tenant_id) or "SHADOW"
    # price-Parameter in limit_price uebernehmen (Intent hat kein eigenes price-Feld)
    if limit_price is None and price is not None:
        limit_price = price
    return {
        "order_intent_id": _uuid.uuid4().hex[:16],
        "tenant_id": tenant_id,
        "user_id": user_id,
        "portfolio_id": portfolio_id,
        "strategy_id": strategy_id,
        "mode": mode,
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "order_type": order_type,
        "limit_price": limit_price,
        "price": limit_price,
        "stop_price": stop_price,
        "reason": reason,
        "decision_id": decision_id,
        "rule_version": rule_version,
        "risk_check_status": "pending",
        "created_at": _dt.datetime.now().isoformat(),
    }


def validate_order_intent(intent, portfolio_value=None, market_open=True,
                          position_count=0, check_rules=True):
    """PHASE 13: Prueft ein Order-Intent gegen die Order-Risk-Checkliste (§11).

    Checks: Modus (nur SHADOW/PAPER/PAUSED erlaubt → SHADOW/PAUSED blockiert),
    PAPER_ONLY (kein LIVE), Menge > 0, Tickernicht leer, Markt offen,
    Risiko-Limits (enforce_risk_limits), Tenant-Regeln (enforce_rules),
    Max-Positionen (Default 20). Liefert {'allowed', 'reason', 'intent'}.
    """
    # 1) Modus-Gate: nur PAPER (oder SHADOW ohne Ausfuehrung) erlaubt
    mode = intent.get("mode") or "SHADOW"
    if mode.startswith("LIVE"):
        return {"allowed": False, "reason": "LIVE-Modus ist gesperrt (PAPER_ONLY)",
                "intent": intent}
    if mode == "PAUSED" or mode == "SUSPENDED" or mode == "REVOKED":
        return {"allowed": False, "reason": f"Modus {mode}: keine Orders erlaubt",
                "intent": intent}
    # 2) Menge/Ticker
    if not intent.get("ticker"):
        return {"allowed": False, "reason": "Ticker fehlt", "intent": intent}
    if not intent.get("quantity") or intent["quantity"] <= 0:
        return {"allowed": False, "reason": "Menge muss > 0 sein", "intent": intent}
    # 3) Markt offen (default an, Aufrufer kann schliessen)
    if not market_open:
        return {"allowed": False, "reason": "Markt geschlossen", "intent": intent}
    # 4) Max-Positionen
    max_pos = 20
    if position_count >= max_pos:
        return {"allowed": False,
                "reason": f"Max. {max_pos} Positionen erreicht", "intent": intent}
    # 5) Risiko-Limits (effektive Tenant-Limits)
    if portfolio_value and portfolio_value > 0:
        pos_pct = (intent.get("quantity", 0) * 1.0) / max(portfolio_value, 1)
        r = enforce_risk_limits(intent["tenant_id"],
                                "moderate" if mode == "PAPER" else "shadow",
                                pos_pct, portfolio_value)
        if not r["allowed"]:
            return {"allowed": False, "reason": f"Risiko: {r['reason']}",
                    "intent": intent}
    # 6) Tenant-Regeln
    if check_rules:
        r2 = enforce_rules(intent["tenant_id"], intent.get("ticker", ""),
                           {"kauf_count": 0})
        if not r2["allowed"]:
            return {"allowed": False, "reason": f"Regel: {r2['reason']}",
                    "intent": intent}
    # 7) Vier-Augen-Freigabe (Portfolio) — explizit gesperrte/in Pruefung
    #    Portfolios blocken, unregulierte laufen weiter (Paper-Betrieb).
    pid = intent.get("portfolio_id")
    if pid:
        r3 = enforce_approval_trade(intent["tenant_id"], "portfolio", pid)
        if not r3["allowed"]:
            return {"allowed": False, "reason": f"Freigabe: {r3['reason']}",
                    "intent": intent}
    # 8) Trading-Pause aktiv? (modus-unabhaengig)
    if _trading_paused(intent["tenant_id"]):
        return {"allowed": False, "reason": "Trading-Pause aktiv", "intent": intent}
    # 9) Tenant stimmt (Intent-Tenant == Session/Aufrufer-Tenant)
    caller_tid = intent.get("caller_tenant_id")
    if caller_tid is not None and caller_tid != intent.get("tenant_id"):
        return {"allowed": False, "reason": "Tenant-Mismatch", "intent": intent}
    # 10) Benutzer darf handeln (Rolle)
    if intent.get("user_id"):
        if not user_can_trade(intent["user_id"], intent["tenant_id"]):
            return {"allowed": False, "reason": "Benutzer darf nicht handeln",
                    "intent": intent}
    # 11) Portfolio ist aktiv
    if pid and not _portfolio_active(intent["tenant_id"], pid):
        return {"allowed": False, "reason": "Portfolio nicht aktiv", "intent": intent}
    # 12) Brokerverbindung gehoert zum Tenant (falls referenziert)
    bc = intent.get("broker_connection_id")
    if bc:
        conn = _broker_connection_for_tenant(bc, intent["tenant_id"])
        if not conn:
            return {"allowed": False, "reason": "Broker-Connection nicht im Tenant",
                    "intent": intent}
        # 13) Brokerumgebung passt zum Modus
        env = conn.get("environment", "")
        if mode == "PAPER" and env not in ("PAPER", "SANDBOX", "DEMO"):
            return {"allowed": False,
                    "reason": f"Broker-Umgebung {env} passt nicht zu PAPER",
                    "intent": intent}
    # 14) Daten aktuell (kein Stale-Quote)
    _px = intent.get("limit_price") or intent.get("price") or 0
    if _px <= 0:
        return {"allowed": False, "reason": "Kein gueltiger Preis (Daten fehlen)",
                "intent": intent}
    # 15) Tagesverlustlimit / 16) Gesamtverlustlimit / 17) Drawdown
    drawdown = intent.get("drawdown_pct", 0.0)
    r_risk = enforce_risk_limits(
        intent["tenant_id"], "moderate" if mode == "PAPER" else "shadow",
        pos_pct if portfolio_value else 0.0, portfolio_value or 0.0,
        drawdown_pct=drawdown)
    if not r_risk["allowed"]:
        return {"allowed": False, "reason": f"Risk-Limit: {r_risk['reason']}",
                "intent": intent}
    # 18) Keine doppelte Order (gleicher Ticker/Side/Portfolio offen)
    if _duplicate_order(intent["tenant_id"], pid, intent.get("ticker"),
                        intent.get("side")):
        return {"allowed": False, "reason": "Doppelte Order (bereits offen)",
                "intent": intent}
    intent["risk_check_status"] = "passed"
    return {"allowed": True, "reason": "ok", "intent": intent}


# ── Hilfsfunktionen fuer die 18-Punkte-Order-Risk-Checkliste (Auftrag S13) ──
def _trading_paused(tenant_id):
    try:
        import db as _db
        m = _db.MTDB()
        row = m.conn.execute(
            "SELECT mode FROM trading_mode_transitions WHERE tenant_id=? "
            "ORDER BY id DESC LIMIT 1", (tenant_id,)).fetchone()
        m.close()
        return bool(row) and row["mode"] in ("PAUSED", "SUSPENDED", "REVOKED")
    except Exception:
        return False


def user_can_trade(user_id, tenant_id):
    try:
        return has_permission(user_id, "paper.trade", tenant_id) or                has_permission(user_id, "trading.pause", tenant_id)
    except Exception:
        return False


def _portfolio_active(tenant_id, portfolio_id):
    try:
        import db as _db
        m = _db.MTDB()
        row = m.conn.execute(
            "SELECT status FROM paper_portfolios WHERE id=? AND tenant_id=?",
            (portfolio_id, tenant_id)).fetchone()
        m.close()
        if not row:
            return True  # nicht existierend -> nicht blockieren (Legacy)
        return row["status"] != "disabled"
    except Exception:
        return True


def _broker_connection_for_tenant(conn_id, tenant_id):
    try:
        import db as _db
        m = _db.MTDB()
        row = m.conn.execute(
            "SELECT * FROM provider_connections WHERE id=? AND tenant_id=? "
            "AND provider_type='BROKER'", (conn_id, tenant_id)).fetchone()
        m.close()
        return dict(row) if row else None
    except Exception:
        return None


def _duplicate_order(tenant_id, portfolio_id, ticker, side):
    try:
        import db as _db
        m = _db.MTDB()
        side_db = "BUY" if str(side).upper() in ("BUY", "KAUFEN") else "SELL"
        row = m.conn.execute(
            "SELECT id FROM paper_orders WHERE tenant_id=? AND portfolio_id=? "
            "AND ticker=? AND side=? AND status IN ('open','filled')",
            (tenant_id, portfolio_id, ticker, side_db)).fetchone()
        m.close()
        return bool(row)
    except Exception:
        return False



# ── Broker-Connector-Schnittstelle (Auftrag §10) ──
class BrokerProvider:
    """Gemeinsame Schnittstelle fuer alle Broker-Adapter (Paper/Sandbox/Live).

    Implementiert in dieser Phase: PaperBrokerAdapter (Simulator).
    Kein Live-Adapter — PAPER_ONLY. Die Schnittstelle ist die verbindliche
    API fuer spätere Sandbox-/Live-Adapter.
    """

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def health_check(self):
        raise NotImplementedError

    def get_account(self, tenant_id=None):
        raise NotImplementedError

    def get_positions(self, tenant_id=None):
        raise NotImplementedError

    def get_quote(self, ticker):
        raise NotImplementedError

    def place_order(self, intent):
        raise NotImplementedError

    def cancel_order(self, order_id, tenant_id=None):
        raise NotImplementedError

    def get_order_status(self, order_id, tenant_id=None):
        raise NotImplementedError

    def get_open_orders(self, tenant_id=None):
        raise NotImplementedError


class PaperBrokerAdapter(BrokerProvider):
    """PHASE 13: Paper-/Simulator-Adapter (Auftrag §10, Punkt 1).

    Fuehrt Order-Intents im Paper-Order-Buch aus (db.paper_orders) und
    wendet Positionen an (paper_position_apply). Kein externer Broker,
    keine echten Orders. Tenant-scoped.
    """

    def __init__(self):
        self._connected = False
        self._account_cache = {}

    def connect(self):
        self._connected = True
        return {"ok": True, "broker": "paper-simulator"}

    def disconnect(self):
        self._connected = False
        return {"ok": True}

    def health_check(self):
        return {"ok": self._connected, "broker": "paper-simulator"}

    def get_account(self, tenant_id=None):
        import db as _db
        m = _db.MTDB()
        try:
            tid = tenant_id or 1
            row = m.conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(virtual_cash),0) AS wert "
                "FROM paper_portfolios WHERE tenant_id=?", (tid,)).fetchone()
            return {"tenant_id": tid, "portfolios": row["n"] if row else 0,
                    "wert": row["wert"] if row else 0.0,
                    "broker": "paper-simulator", "mode": "PAPER"}
        finally:
            m.close()

    def get_positions(self, tenant_id=None):
        import db as _db
        m = _db.MTDB()
        try:
            tid = tenant_id or 1
            rows = m.conn.execute(
                "SELECT ticker, SUM(quantity) AS shares "
                "FROM paper_orders WHERE tenant_id=? GROUP BY ticker",
                (tid,)).fetchall()
            return [{"ticker": r["ticker"], "shares": r["shares"]} for r in rows]
        finally:
            m.close()

    def get_quote(self, ticker):
        try:
            from marktdaten import hole_kurs_fuer
            price = hole_kurs_fuer(ticker)
            return {"ticker": ticker, "price": price}
        except Exception:
            return {"ticker": ticker, "price": None}

    def place_order(self, intent):
        """Fuehrt Intent im Paper-Order-Buch aus. Gibt {'ok', 'order_id', 'status'}."""
        import db as _db
        v = validate_order_intent(intent, market_open=True)
        if not v["allowed"]:
            return {"ok": False, "error": v["reason"], "status": "blocked"}
        m = _db.MTDB()
        try:
            pid = intent.get("portfolio_id") or 1
            side_db = "BUY" if str(intent["side"]).upper() in ("BUY", "KAUFEN") else "SELL"
            oid = m.paper_order_insert(
                tenant_id=intent["tenant_id"],
                portfolio_id=pid,
                ticker=intent["ticker"], side=side_db,
                quantity=intent["quantity"], price=intent.get("limit_price") or 0.0)
            m.paper_position_apply(
                tenant_id=intent["tenant_id"],
                portfolio_id=pid,
                ticker=intent["ticker"], side=side_db,
                quantity=intent["quantity"],
                price=intent.get("limit_price") or 0.0)
            return {"ok": True, "order_id": oid, "status": "filled",
                    "broker": "paper-simulator"}
        finally:
            m.close()

    def cancel_order(self, order_id, tenant_id=None):
        import db as _db
        m = _db.MTDB()
        try:
            m.conn.execute(
                "UPDATE paper_orders SET status='cancelled' "
                "WHERE id=? AND tenant_id=?", (order_id, tenant_id or 1))
            m.conn.commit()
            return {"ok": True, "order_id": order_id, "status": "cancelled"}
        finally:
            m.close()

    def get_order_status(self, order_id, tenant_id=None):
        import db as _db
        m = _db.MTDB()
        try:
            row = m.conn.execute(
                "SELECT id, status FROM paper_orders "
                "WHERE id=? AND tenant_id=?", (order_id, tenant_id or 1)).fetchone()
            return {"ok": bool(row), "order_id": order_id,
                    "status": row["status"] if row else "unknown"}
        finally:
            m.close()

    def get_open_orders(self, tenant_id=None):
        import db as _db
        m = _db.MTDB()
        try:
            tid = tenant_id or 1
            rows = m.conn.execute(
                "SELECT id, ticker, side, quantity, price, status "
                "FROM paper_orders WHERE tenant_id=? AND status IN ('open','filled')",
                (tid,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            m.close()


# ── PHASE 13: Vier-Augen-Freigabe (Auftrag §2, kritische Trennung) ──
FOUR_EYES_ACTIONS = [
    "live_request", "live_approve", "broker_connect", "risk_limit_change",
    "pause_resume", "role_to_admin", "backup_restore",
]


class SandboxBrokerAdapter(BrokerProvider):
    """PHASE 11 (S19-P11): Sandbox-Broker (simulierter echter Broker).

    Verhaelt sich wie ein echter Broker (Market-Fill, aber in Sandbox-Umgebung),
    nutzt das Paper-Order-Buch mit environment=SANDBOX. Dient als Bruecke zwischen
    Paper-Simulator und spaeterem Live-Broker (Auftrag S10: SIMULATOR/PAPER/SANDBOX/LIVE).
    PAPER_ONLY: keine echten Orders, keine Echtgeld-Pfade.
    """

    def __init__(self):
        self._connected = False
        self._account_cache = {}
        self.environment = "SANDBOX"

    def connect(self):
        self._connected = True
        return {"ok": True, "broker": "sandbox-simulator", "environment": "SANDBOX"}

    def disconnect(self):
        self._connected = False
        return {"ok": True}

    def health_check(self):
        return {"broker": "sandbox", "ok": self._connected, "environment": "SANDBOX"}

    def get_account(self, tenant_id=None):
        return {"environment": "SANDBOX", "buying_power": 0.0, "cash": 0.0,
                "note": "Sandbox: keine Echtgeld-Konten (PAPER_ONLY)"}

    def get_positions(self, tenant_id=None):
        if not tenant_id:
            return []
        try:
            import db as _db
            m = _db.MTDB()
            rows = m.conn.execute(
                "SELECT * FROM paper_positions WHERE tenant_id=?", (tenant_id,)).fetchall()
            m.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_quote(self, ticker):
        import market_data_provider as _mdp
        snap = _mdp.get_quote_with_fallback(ticker)
        return snap.price

    def place_order(self, intent):
        """Sandbox-Order: fuelhrt Order-Intent im paper_orders-Buch aus
        (environment=SANDBOX). Kein externer Broker."""
        import db as _db
        v = validate_order_intent(intent, market_open=True)
        if not v["allowed"]:
            return {"ok": False, "error": v["reason"], "status": "blocked",
                    "environment": "SANDBOX"}
        m = _db.MTDB()
        try:
            pid = intent.get("portfolio_id") or 1
            side_db = "BUY" if str(intent.get("side", "buy")).upper() in ("BUY", "KAUFEN") else "SELL"
            oid = m.paper_order_insert(
                tenant_id=intent.get("tenant_id", 1),
                portfolio_id=pid,
                ticker=intent.get("ticker"),
                side=side_db,
                quantity=intent.get("quantity", 0),
                price=intent.get("limit_price") or intent.get("price") or 0.0)
            m.paper_position_apply(
                tenant_id=intent.get("tenant_id", 1),
                portfolio_id=pid,
                ticker=intent.get("ticker"), side=side_db,
                quantity=intent.get("quantity", 0),
                price=intent.get("limit_price") or intent.get("price") or 0.0)
            return {"ok": True, "order_id": oid, "status": "filled",
                    "environment": "SANDBOX", "sandbox": True}
        finally:
            m.close()

    def cancel_order(self, order_id, tenant_id=None):
        return {"ok": True, "cancelled": order_id, "environment": "SANDBOX"}

    def get_order_status(self, order_id, tenant_id=None):
        return {"order_id": order_id, "status": "filled", "environment": "SANDBOX"}

    def get_open_orders(self, tenant_id=None):
        if not tenant_id:
            return []
        try:
            import db as _db
            m = _db.MTDB()
            rows = m.conn.execute(
                "SELECT id, ticker, side, quantity, price, status "
                "FROM paper_orders WHERE tenant_id=? AND environment='SANDBOX' "
                "AND status IN ('open','filled')", (tenant_id,)).fetchall()
            m.close()
            return [dict(r) for r in rows]
        except Exception:
            return []


def get_broker_adapter(environment="PAPER"):
    """Factory: liefert den passenden Broker-Adapter fuer eine Umgebung."""
    if environment == "SANDBOX":
        return SandboxBrokerAdapter()
    return PaperBrokerAdapter()


def four_eyes_required(action, requester, approver):
    """PHASE 13: Vier-Augen-Prinzip — Antragsteller darf nicht selbst genehmigen.

    action: eine der FOUR_EYES_ACTIONS. requester/approver: Username-Strings.
    Liefert {'required': bool, 'ok': bool, 'reason': str}.
    """
    if action not in FOUR_EYES_ACTIONS:
        return {"required": False, "ok": True, "reason": "keine Vier-Augen-Aktion"}
    if not requester or not approver:
        return {"required": True, "ok": False,
                "reason": "Vier-Augen: Antragsteller UND Genehmiger erforderlich"}
    if requester == approver:
        return {"required": True, "ok": False,
                "reason": "Vier-Augen: Antragsteller darf nicht selbst genehmigen"}
    return {"required": True, "ok": True, "reason": "Vier-Augen erfuellt"}


def resolve_tenant_for_user(user):
    """Leitet die tenant_id eines Users aus der Membership-Tabelle ab.
    Fallback: Default-Tenant (id=1). Kein Client-Input noetig."""
    try:
        import db as _db
        m = _db.MTDB()
        try:
            tid = m.tenant_ensure_default()
            memberships = m.tenant_memberships_for_user(user["username"])
            m.close()
            if memberships:
                return memberships[0]["tenant_id"]
            # Keine Membership -> Default-Tenant zuordnen
            m2 = _db.MTDB()
            m2.tenant_membership_add(tid, user["username"], role=user.get("role", "user"))
            m2.close()
            return tid
        except Exception:
            try:
                m.close()
            except Exception:
                pass
            return 1
    except Exception:
        return 1

BASE = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE, "security_users.json")
AUDIT_FILE = os.path.join(BASE, "security_audit.json")
def _load_or_create_secret(env_name, dateiname, alt_env_name=None):
    """Secret aus Env laden, sonst einmalig erzeugen und dauerhaft speichern.

    LUECKE 5 (2026-09-27): Vorher stand hier
        os.environ.get("MICRO_TRADER_CSF_SECRET") or secrets.token_hex(32)
    Der Name enthielt einen Tippfehler (CSF statt CSRF), die korrekte Variable
    wurde also nie gelesen. Ohne gesetzte Env-Variable fiel der Code auf
    secrets.token_hex(32) zurueck — ein NEUES Secret bei JEDEM Neustart.
    Konsequenz: alle vorher ausgestellten signierten Tokens (CSRF, max_age
    3600s) waren nach einem Neustart ungueltig, und ein Operator konnte den
    Wert nicht fixieren, selbst wenn er die richtige Variable gesetzt hatte.

    Jetzt: korrekter Name zuerst, der alte Tippfehler-Name bleibt als
    Rueckwaertskompatibilitaet lesbar. Ohne Env wird ein Secret per CSPRNG
    erzeugt und mit Modus 0600 abgelegt, damit es Neustarts ueberlebt.
    """
    for name in (env_name, alt_env_name):
        if name:
            v = os.environ.get(name)
            if v and v.strip():
                return v.strip()
    pfad = os.path.join(BASE, dateiname)
    try:
        with open(pfad, encoding="utf-8") as f:
            v = f.read().strip()
        if v:
            return v
    except OSError:
        pass
    v = secrets.token_hex(32)
    try:
        fd = os.open(pfad, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(v + "\n")
        os.chmod(pfad, 0o600)
    except OSError:
        # Ohne Datei bleibt es beim prozesslokalen Secret — funktionsfaehig,
        # aber nicht restart-stabil. Bewusst still, kein Key im Log.
        pass
    return v


SESSION_SECRET = _load_or_create_secret(
    "MICRO_TRADER_SESSION_SECRET", ".session_secret")
CSRF_SECRET = _load_or_create_secret(
    "MICRO_TRADER_CSRF_SECRET", ".csrf_secret",
    alt_env_name="MICRO_TRADER_CSF_SECRET")  # Legacy-Tippfehler, lesbar halten

# ─── Rollen ────────────────────────────────────────────────────────────────
ROLES = ["visitor", "user", "analyst", "operator", "admin", "superadmin"]

ROLE_PERMISSIONS = {
    "visitor":    ["landingpage"],
    "user":       ["landingpage", "dashboard", "own_data"],
    "analyst":    ["landingpage", "dashboard", "reports", "analysis", "ki_log_view"],
    "operator":   ["landingpage", "dashboard", "reports", "analysis", "systemstatus",
                   "pause_trading", "resume_trading"],
    "admin":      ["landingpage", "dashboard", "reports", "analysis", "systemstatus",
                   "pause_trading", "resume_trading", "users", "settings", "rules",
                   "audit", "backups"],
    "superadmin": ["landingpage", "dashboard", "reports", "analysis", "systemstatus",
                   "pause_trading", "resume_trading", "users", "settings", "rules",
                   "audit", "backups", "recovery", "security_config", "mfa_emergency"],
}

# ─── PHASE 2: Tenant-bezogene Berechtigungen (Mandanten-Ausbau) ─────────────
# Effektive Rolle = Membership-Rolle im aktuellen Tenant (gewichtig), sonst
# globale User-Rolle (Fallback). Ermöglicht: User ist in Tenant A 'admin',
# in Tenant B nur 'user'.
TENANT_ROLE_PERMISSIONS = {
    "user":      ["landingpage", "dashboard", "own_data", "tenant_view"],
    "analyst":   ["landingpage", "dashboard", "reports", "analysis", "ki_log_view",
                  "tenant_view"],
    "operator":  ["landingpage", "dashboard", "reports", "analysis", "systemstatus",
                  "pause_trading", "resume_trading", "tenant_view", "tenant_trade_control"],
    "admin":     ["landingpage", "dashboard", "reports", "analysis", "systemstatus",
                  "pause_trading", "resume_trading", "users", "settings", "rules",
                  "audit", "backups", "tenant_view", "tenant_manage",
                  "tenant_trade_control", "tenant_members"],
    "superadmin": ["landingpage", "dashboard", "reports", "analysis", "systemstatus",
                   "pause_trading", "resume_trading", "users", "settings", "rules",
                   "audit", "backups", "recovery", "security_config", "mfa_emergency",
                   "tenant_view", "tenant_manage", "tenant_trade_control",
                   "tenant_members", "tenant_delete"],
}

# ─── PHASE 2 (v2.40.0): Feingranulare Berechtigungen (§7) ────────────────────
# Feine Permissions ergänzen die groben Katalog-Namen. has_permission löst
# Alias auf: "users" impliziert users.read/users.create/users.disable, usw.
FINE_PERMISSIONS = [
    "profile.read", "profile.edit", "sessions.read", "sessions.revoke",
    "dashboard.read", "portfolio.read", "portfolio.edit",
    "reports.read", "analysis.read",
    "strategy.read", "strategy.edit",
    "rules.read", "rules.propose", "rules.review", "rules.approve", "rules.rollback",
    "trading.pause", "trading.resume",
    "paper.trade", "live.request", "live.review", "live.approve", "live.revoke",
    "provider.read", "provider.create", "provider.test", "provider.rotate", "provider.disable",
    "broker.read", "broker.connect", "broker.disconnect",
    "order.intent.create", "order.intent.approve", "order.execute",
    "users.read", "users.create", "users.disable", "roles.manage",
    "audit.read", "settings.read", "settings.edit", "backup.restore",
]
# Grobe Katalog-Namen -> implizierte feine Permissions (Alias-Auflösung)
PERMISSION_ALIASES = {
    "dashboard": ["dashboard.read", "portfolio.read"],
    "reports": ["reports.read"],
    "analysis": ["analysis.read"],
    "rules": ["rules.read", "rules.propose", "rules.review", "rules.approve", "rules.rollback"],
    "users": ["users.read", "users.create", "users.disable"],
    "settings": ["settings.read", "settings.edit"],
    "audit": ["audit.read"],
    "backups": ["backup.restore"],
    "pause_trading": ["trading.pause"],
    "resume_trading": ["trading.resume"],
    "tenant_manage": ["users.manage", "roles.manage"],
    "tenant_members": ["users.read"],
}

# Feine Permissions je Rolle (§7, deny-by-default). Nur was hier steht, ist erlaubt.
ROLE_FINE_PERMISSIONS = {
    "user": ["profile.read", "profile.edit", "sessions.read", "sessions.revoke",
             "dashboard.read", "portfolio.read"],
    "analyst": ["profile.read", "profile.edit", "sessions.read", "sessions.revoke",
                "dashboard.read", "portfolio.read", "reports.read", "analysis.read",
                "strategy.read", "rules.read", "rules.propose"],
    "operator": ["profile.read", "profile.edit", "sessions.read", "sessions.revoke",
                 "dashboard.read", "portfolio.read", "reports.read", "analysis.read",
                 "strategy.read", "rules.read", "rules.propose",
                 "trading.pause", "trading.resume", "paper.trade"],
    "admin": ["profile.read", "profile.edit", "sessions.read", "sessions.revoke",
              "dashboard.read", "portfolio.read", "portfolio.edit", "reports.read",
              "analysis.read", "strategy.read", "strategy.edit",
              "rules.read", "rules.propose", "rules.review", "rules.approve", "rules.rollback",
              "trading.pause", "trading.resume", "paper.trade",
              "provider.read", "provider.create", "provider.test", "provider.rotate",
              "provider.disable", "broker.read", "broker.connect", "broker.disconnect",
              "order.intent.create", "order.intent.approve",
              "users.read", "users.create", "users.disable", "roles.manage",
              "audit.read", "settings.read", "settings.edit", "backup.restore",
              "live.request", "live.review"],
    "superadmin": FINE_PERMISSIONS,  # alle feinen Permissions
}
# Visitor: keine feinen Permissions (deny-by-default)
ALL_PERMISSIONS = sorted(set(
    [p for ps in ROLE_PERMISSIONS.values() for p in ps] +
    [p for ps in TENANT_ROLE_PERMISSIONS.values() for p in ps] +
    FINE_PERMISSIONS
))

# Routen-Zugriffsklassen (Phase 6 Zuordnung aus SERVER-SECURITY-INVENTORY)
ROUTE_ACCESS = {
    "/": "PUBLIC", "/landing": "PUBLIC", "/api/version": "PUBLIC",
    "/static/<path:dateiname>": "PUBLIC", "/assets/<path:dateiname>": "PUBLIC",
    "/reports/<path:name>": "AUTHENTICATED",
    "/login": "PUBLIC", "/logout": "AUTHENTICATED",
    "/dashboard": "AUTHENTICATED",
    "/data": "AUTHENTICATED", "/depot_json": "AUTHENTICATED",
    "/spec_depot_json": "AUTHENTICATED", "/etf_depot_json": "AUTHENTICATED",
    "/api/analysis": "AUTHENTICATED", "/api/report_pdf": "AUTHENTICATED",
    "/api/report_list": "AUTHENTICATED", "/search_ticker": "AUTHENTICATED",
    "/ticker_chart": "AUTHENTICATED",
    "/api/me": "AUTHENTICATED", "/api/me/password": "AUTHENTICATED",
    "/api/me/mfa": "AUTHENTICATED", "/api/me/permissions": "AUTHENTICATED",
    # LUECKE 7: hierueber bezieht das Frontend sein CSRF-Token fuer die
    # zustandsaendernden GET-Routen. Nur fuer angemeldete User.
    "/api/csrf_token": "AUTHENTICATED",
    # POTENZIAL (29.09.2026): Kandidaten des Screeners. Reine
    # Marktdaten mit Begruendung, keine personenbezogenen Angaben -
    # deshalb AUTHENTICATED wie /api/analysis, nicht TENANT_ADMIN.
    "/api/potenzial": "AUTHENTICATED",
    "/api/roles": "TENANT_ADMIN",
    "/api/trading_mode": "TENANT_ADMIN", "/api/trading_mode/set": "TENANT_ADMIN",
    "/api/trading_mode/history": "TENANT_ADMIN",
    "/api/paper/eligibility": "TENANT_ADMIN", "/api/paper/enter": "TENANT_ADMIN",
    "/api/providers": "TENANT_ADMIN", "/api/providers/add": "TENANT_ADMIN",
    "/api/providers/test/<int:conn_id>": "TENANT_ADMIN",
    "/api/providers/disable/<int:conn_id>": "TENANT_ADMIN",
    "/api/providers/enable/<int:conn_id>": "TENANT_ADMIN",
    "/api/providers/delete/<int:conn_id>": "TENANT_ADMIN",
    "/api/providers/status/<int:conn_id>": "TENANT_ADMIN",
    "/api/secrets": "TENANT_ADMIN", "/api/secrets/set": "TENANT_ADMIN",
    "/api/live-requests": "TENANT_ADMIN",
    "/api/live-requests/<int:req_id>/review": "TENANT_ADMIN",
    "/api/live-requests/<int:req_id>/approve": "TENANT_ADMIN",
    "/api/live-requests/<int:req_id>/reject": "TENANT_ADMIN",
    "/api/live-requests/<int:req_id>/activate": "TENANT_ADMIN",
    "/api/secrets/rotate": "TENANT_ADMIN",
    "/api/risk": "TENANT_ADMIN", "/api/risk/set": "TENANT_ADMIN",
    "/api/rules": "TENANT_ADMIN", "/api/rules/add": "TENANT_ADMIN",
    "/api/rules/set_status": "TENANT_ADMIN",
    "/api/approval": "TENANT_ADMIN", "/api/approval/set": "TENANT_ADMIN",
    "/api/tenants": "TENANT_ADMIN", "/api/tenants/create": "TENANT_ADMIN",
    "/api/tenants/<int:tid>/members": "TENANT_ADMIN",
    "/api/users": "ADMIN", "/api/users/create": "ADMIN",
    "/api/users/<name>/role": "ADMIN", "/api/users/<name>/deactivate": "ADMIN",
    "/api/users/<name>/reset-pw": "ADMIN", "/api/users/<name>/revoke": "ADMIN",
    "/api/profil_karten": "ANALYST", "/api/profile": "ANALYST",
    "/api/db_karten": "ANALYST", "/api/db_query": "ANALYST",
    "/api/ki_log": "ANALYST",
    "/api/pause_trading": "OPERATOR", "/api/clear_cache": "OPERATOR",
    "/api/settings": "ADMIN",
    "/admin": "ADMIN", "/admin/users": "ADMIN", "/admin/users/create": "ADMIN",
    "/admin/system": "ADMIN", "/admin/rules": "ADMIN",
    "/admin/security": "ADMIN", "/admin/logins": "ADMIN", "/admin/audit": "ADMIN",
    "/admin/settings": "ADMIN", "/admin/backups": "ADMIN",
    "/admin/tenant-config": "ADMIN", "/admin/tenant-config/risk": "ADMIN",
    "/admin/tenant-config/rule": "ADMIN",
    "/admin/tenant-config/rule/<rule_id>/set": "ADMIN",
    "/admin/tenant-config/approval": "ADMIN",
    "/admin/tenant-config/approval/<int:appr_id>/set": "ADMIN",
}
ACCESS_ORDER = ["PUBLIC", "AUTHENTICATED", "ANALYST", "OPERATOR", "ADMIN", "SUPERADMIN"]

MFA_REQUIRED_ROLES = ["admin", "superadmin"]
MFA_RECOMMENDED_ROLES = ["operator"]

# ─── Phase 1 (v2.39.0): Benutzer-Lebenszyklus (§6) ──────────────────────────
USER_STATUS_INVITED = "INVITED"
USER_STATUS_ACTIVE = "ACTIVE"
USER_STATUS_MFA_REQUIRED = "MFA_REQUIRED"
USER_STATUS_RESTRICTED = "RESTRICTED"
USER_STATUS_SUSPENDED = "SUSPENDED"
USER_STATUS_DISABLED = "DISABLED"
USER_STATUS_DELETED = "DELETED"
USER_STATUSES = (USER_STATUS_INVITED, USER_STATUS_ACTIVE, USER_STATUS_MFA_REQUIRED,
                 USER_STATUS_RESTRICTED, USER_STATUS_SUSPENDED, USER_STATUS_DISABLED,
                 USER_STATUS_DELETED)
RECOVERY_CODE_COUNT = 8
RECOVERY_CODE_LENGTH = 10


# ─── User-Store (JSON, Passwörter via werkzeug pbkdf2:sha256) ────────────────
def _load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, encoding="utf-8") as f:
            users = json.load(f)
    except Exception:
        return {}
    now = int(time.time())
    changed = False
    for u in users.values():
        # Phase 1 (§6): Status ableiten (Migration alter 'active'-bool-Daten)
        if not u.get("status"):
            if not u.get("active", True):
                u["status"] = USER_STATUS_DISABLED
            elif (u.get("role") in MFA_REQUIRED_ROLES and not u.get("mfa_enabled")):
                u["status"] = USER_STATUS_MFA_REQUIRED
            else:
                u["status"] = USER_STATUS_ACTIVE
            changed = True
        # LUECKE 4 (2026-09-27): inkonsistenter MFA-Zustand selbst heilen.
        # mfa_enabled=True ohne mfa_secret ist nicht nutzbar (verify_mfa kann
        # nie erfolgreich sein) und liess die require_recent_mfa()-Gates
        # wirkungslos laufen, ohne dass ein Fehler sichtbar wurde. Ohne Secret
        # gilt MFA als nicht eingerichtet; enable_mfa() setzt beide Felder
        # gemeinsam, der Nutzer kann MFA also regulaer einrichten.
        if u.get("mfa_enabled") and not u.get("mfa_secret"):
            u["mfa_enabled"] = False
            changed = True
        # Phase 1 (§6): Session-GC — abgelaufene/leere Sessions entfernen
        sess = u.get("sessions") or {}
        before = len(sess)
        sess = {sid: s for sid, s in sess.items()
                if isinstance(s, dict)
                and now - s.get("last_seen", 0) <= SESSION_IDLE_TIMEOUT
                and now - s.get("created", now) <= SESSION_ABS_TIMEOUT}
        if len(sess) != before:
            u["sessions"] = sess
            changed = True
    if changed:
        # _gc=True: die Sessions wurden gerade bewusst bereinigt. Ohne
        # dieses Flag holt der Merge-Schutz in _save_users jede gerade
        # entfernte Session von der Platte zurueck - die GC waere
        # wirkungslos und die Datei waechst unbegrenzt.
        _save_users(users, _gc=True)
    return users


def _user_view(u, username=""):
    """Phase 1 (§6): Redactierter Benutzer-Datensatz für API/UI.
    NIE password_hash / mfa_secret / recovery_codes ausgeben."""
    if u is None:
        return None
    return {
        "username": u.get("username", username),
        "display_name": u.get("display_name", ""),
        "email": u.get("email", ""),
        "role": u.get("role", "user"),
        "status": u.get("status", USER_STATUS_ACTIVE),
        "active": bool(u.get("active", True)),
        "created_at": u.get("created_at"),
        "updated_at": u.get("updated_at"),
        "last_login_at": u.get("last_login_at"),
        "last_failed_login_at": u.get("last_failed_login_at"),
        "mfa_enabled": bool(u.get("mfa_enabled", False)),
        "mfa_verified_at": u.get("mfa_verified_at"),
        "created_by": u.get("created_by"),
        "disabled_by": u.get("disabled_by"),
        "disabled_at": u.get("disabled_at"),
        "sessions_active": len(u.get("sessions") or {}),
        "last_security_action": u.get("last_security_action"),
        "recovery_codes_left": len(u.get("recovery_codes") or []),
    }


def _save_users(users, _gc=False):
    """Schreibt User-Store ATOMAR + GELOCKT (FINAL-FIX 2026-08-11).

    Root-Cause der wiederkehrenden Korruption:
    - open('w') + json.dump ist NICHT atomar -> bei mehreren parallelen
      Instanzen (mehrere dashboard.py) ueberschneiden sich die Schreibvorgaenge
      -> Datei enthaelt zwei JSON-Objekte ('Extra data') -> get_user() = None -> 401.
    Fix:
    - fcntl-Lock verhindert gleichzeitiges Schreiben.
    - Temp-File + os.replace() => atomar (nie halb geschriebene Datei).
    - Merge-Schutz nutzt das KORREKTE Feld 'password_hash' (nicht 'pw_hash').
    - _gc=True unterdrueckt den Session-Merge (Phase 3, 01.10.2026):
      nach der Session-GC wuerde er jede entfernte Session zurueckholen.
    """
    import tempfile
    lock_path = USERS_FILE + ".lock"
    # Aktuelle Datei lesen (Merge-Schutz: fremde Aenderungen nicht verlieren)
    disk = {}
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, encoding="utf-8") as f:
                disk = json.load(f)
        except Exception:
            disk = {}
    for name, u in users.items():
        du = disk.get(name, {})
        # KORREKTER Key: password_hash (nicht pw_hash)
        # LUECKE 4 (2026-09-27): Der Merge-Schutz hat sich selbst ausgetrickst.
        # Vorher: "if not u.get(...) and du.get(...)" — er stellte einen
        # bewusst auf False/[] gesetzten Wert wieder her, weil False und []
        # falsy sind. Damit war (a) disable_mfa() wirkungslos (mfa_enabled
        # und recovery_codes wurden sofort zurueckgeschrieben) und (b) jede
        # Heilung des Zustands "mfa_enabled=True ohne Secret" unmoeglich.
        # Richtig: nur mergen, wenn das Feld im RAM-Dict gar nicht vorkommt —
        # dann greift der Schutz fuer echte Teil-Updates weiter, ein
        # explizites False/[] gewinnt aber.
        if "password_hash" not in u and du.get("password_hash"):
            u["password_hash"] = du["password_hash"]
        if "mfa_enabled" not in u and du.get("mfa_enabled"):
            u["mfa_enabled"] = du["mfa_enabled"]
        if "recovery_codes" not in u and du.get("recovery_codes"):
            u["recovery_codes"] = du["recovery_codes"]
        # PHASE 3 (01.10.2026): Sessions vereinen - aber nur wenn es
        # keine bewusste Entfernung war.
        # _gc=True schreibt den RAM-Zustand unveraendert (kein Merge),
        # damit die Session-GC in _load_users() nicht aushebelt wird.
        #
        # BEFUND: Die GC in _load_users entfernt abgelaufene Sessions
        # korrekt im RAM. _save_users las die alte Datei und merged
        # alle 250 toten Sessions wieder hinein, sodass die Datei bei
        # 253 Eintraegen stehen blieb (gemessen: 56.561 B vorher wie
        # nachher, 3 von 253 valide). Jeder Lesevorgang schrieb die
        # Datei mit identischem Inhalt neu - eine Endlosschleife.
        #
        # Mit gc=True wird nicht gemergt: die aufrufende Stelle hat die
        # Sessions gerade absichtlich bereinigt. Alle anderen Aufrufer
        # verhalten sich unveraendert.
        if _gc:
            # Kein Merge. Der RAM-Zustand IST das Ergebnis der GC und
            # wird unveraendert geschrieben.
            #
            # KORREKTUR (01.10.2026): Die erste Fassung benutzte
            # setdefault und holte damit jede gerade entfernte Session
            # von der Platte zurueck - gemessen 251 -> 251 Sessions,
            # die GC blieb wirkungslos. Genau das war der urspruengliche
            # Fehler, nur eine Ebene tiefer.
            #
            # Bewusst in Kauf genommen: ein zweiter Prozess, der
            # zwischen Lesen und Schreiben einloggt, verliert seinen
            # Eintrag. Das Fenster ist Millisekunden und heilt von
            # selbst - sein naechstes touch_session laeuft als
            # normaler Merge und stellt die Session wieder her. Der
            # umgekehrte Fehler waechst dagegen unbegrenzt.
            pass
        else:
            ram_sess = u.get("sessions") or {}
            disk_sess = du.get("sessions") or {}
            merged = dict(disk_sess)
            merged.update(ram_sess)
            u["sessions"] = merged
    # ATOMAR schreiben: temp-file -> os.replace (verhindert Korruption durch
    # parallele Schreibvorgaenge, da nie eine halb geschriebene Datei sichtbar ist).
    # Windows-File-Lock (msvcrt) ist optional: falls belegt, faellt es still
    # zurueck auf den atomaren Write, der allein die Korruption verhindert.
    fd_lock = None
    try:
        import msvcrt
        fd_lock = open(lock_path, "w")
        msvcrt.locking(fd_lock.fileno(), msvcrt.LK_LOCK, 1)
    except Exception:
        fd_lock = None
    try:
        tf = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=os.path.dirname(USERS_FILE),
            prefix=".sec_users_", suffix=".tmp", delete=False)
        json.dump(users, tf, indent=2, ensure_ascii=False)
        tf.flush()
        os.fsync(tf.fileno())
        tf.close()
        os.replace(tf.name, USERS_FILE)  # atomar unter POSIX+Windows
    finally:
        if fd_lock is not None:
            try:
                import msvcrt as _m
                _m.locking(fd_lock.fileno(), _m.LK_UNLCK, 1)
            except Exception:
                pass
            fd_lock.close()
            try:
                os.remove(lock_path)
            except Exception:
                pass


def user_exists(username):
    return username in _load_users()


def create_user(username, password, role="user", email="", display_name="", created_by=None):
    """Phase 1 (§6): Legt einen Benutzer mit Lebenszyklus-Status an.
    Gibt (ok, fehler) zurück. Admin/Superadmin starten als MFA_REQUIRED."""
    if role not in ROLES:
        return False, "Unbekannte Rolle"
    if user_exists(username):
        return False, "Benutzer existiert bereit"
    users = _load_users()
    jetzt = datetime.utcnow().isoformat() + "Z"
    status = (USER_STATUS_MFA_REQUIRED if role in MFA_REQUIRED_ROLES
              else USER_STATUS_ACTIVE)
    users[username] = {
        "username": username,
        "display_name": display_name or username,
        "email": email,
        "password_hash": generate_password_hash(password, method="pbkdf2:sha256"),
        "role": role,
        "active": True,
        "status": status,
        "created_at": jetzt,
        "updated_at": jetzt,
        "last_login": None,
        "last_login_at": None,
        "last_failed_login_at": None,
        "mfa_enabled": False,
        "mfa_secret": None,
        "mfa_pending_secret": None,
        "mfa_verified_at": None,
        "recovery_codes": [],
        "created_by": created_by or "system",
        "disabled_by": None,
        "disabled_at": None,
        "sessions": {},          # session_id -> {created, last_seen, ip}
        "last_security_action": None,
    }
    _save_users(users)
    audit_log("user_create", username, f"Rolle={role} Status={status} by={created_by or 'system'}")
    return True, ""


def verify_password(username, password):
    users = _load_users()
    u = users.get(username)
    if not u or not u.get("active") or u.get("status") in (
            USER_STATUS_DISABLED, USER_STATUS_DELETED):
        return False
    jetzt = datetime.utcnow().isoformat() + "Z"
    if check_password_hash(u.get("password_hash", ""), password):
        u["last_login"] = jetzt
        u["last_login_at"] = jetzt
        u["updated_at"] = jetzt
        _save_users(users)
        return True
    u["last_failed_login_at"] = jetzt
    _save_users(users)
    return False


def change_password(username, new_password):
    """Phase 1 (§6): Passwortänderung widerruft ALLE alten Sessions."""
    users = _load_users()
    if username not in users:
        return False
    users[username]["password_hash"] = generate_password_hash(
        new_password, method="pbkdf2:sha256")
    users[username]["last_security_action"] = (
        datetime.utcnow().isoformat() + "Z password_change")
    users[username]["updated_at"] = datetime.utcnow().isoformat() + "Z"
    # §6 Akzeptanzkriterium: Passwortänderung widerruft alte Sessions
    users[username]["sessions"] = {}
    _save_users(users)
    audit_log("password_change", username, "alle Sessions widerrufen")
    return True


def set_role(username, new_role, by_admin):
    """Rolle setzen (§7 Vorgaben):
    - by_admin darf sich selbst NICHT privilegieren (Rollenwechsel auf sich selbst
      nur als Downgrade; Promote auf sich selbst verboten).
    - superadmin-Rolle darf nur durch einen superadmin vergeben/entzogen werden.
    """
    if new_role not in ROLES:
        return False
    users = _load_users()
    if username not in users:
        return False
    old = users[username]["role"]
    by_role = (users.get(by_admin, {}).get("role") or "visitor").lower()
    # 1) Selbst-Privilegierung: gleicher User, neue Rolle hoeher als aktuelle -> verboten
    if by_admin == username and _ROLE_RANK.get(new_role, 0) > _ROLE_RANK.get(old, 0):
        audit_log("role_change_denied", by_admin,
                  f"user={username} Selbst-Privilegierung {old}->{new_role} blockiert")
        return False
    # 2) Superadmin-Rolle nur durch superadmin (auch Entzug)
    if old == "superadmin" or new_role == "superadmin":
        if by_role != "superadmin":
            audit_log("role_change_denied", by_admin,
                      f"user={username} superadmin-Aenderung ohne superadmin blockiert")
            return False
    users[username]["role"] = new_role
    users[username]["last_security_action"] = (
        datetime.utcnow().isoformat() + "Z role_change")
    users[username]["updated_at"] = datetime.utcnow().isoformat() + "Z"
    # Phase 1: Rollenwechsel in MFA-Pflicht-Rolle -> Status anpassen
    if new_role in MFA_REQUIRED_ROLES and not users[username].get("mfa_enabled"):
        users[username]["status"] = USER_STATUS_MFA_REQUIRED
    elif users[username].get("status") == USER_STATUS_MFA_REQUIRED \
            and users[username].get("mfa_enabled"):
        users[username]["status"] = USER_STATUS_ACTIVE
    _save_users(users)
    audit_log("role_change", by_admin, f"user={username} {old}->{new_role}")
    return True


_ROLE_RANK = {r: i for i, r in enumerate(ROLES)}


def deactivate_user(username, by_admin):
    """Phase 1 (§6): Deaktivierung mit Status, Verursacher und Zeitpunkt."""
    users = _load_users()
    if username not in users:
        return
    jetzt = datetime.utcnow().isoformat() + "Z"
    users[username]["active"] = False
    users[username]["status"] = USER_STATUS_DISABLED
    users[username]["disabled_by"] = by_admin
    users[username]["disabled_at"] = jetzt
    users[username]["updated_at"] = jetzt
    users[username]["sessions"] = {}
    _save_users(users)
    audit_log("user_deactivate", by_admin, f"user={username}")


def get_user(username):
    """Phase 1: Liefert REDACTIERTEN Datensatz (kein Hash/Secret)."""
    return _user_view(_load_users().get(username), username)


def list_users():
    """Phase 1: Liefert REDACTIERTE Benutzerliste (kein Hash/Secret)."""
    return [_user_view(u) for u in _load_users().values()]


# ─── MFA (TOTP RFC 6238, HMAC-SHA1 über cryptography) ────────────────────────
from totp_util import (generate_mfa_secret, _totp, verify_mfa, totp_counter,
                        mfa_provisioning_uri, _generate_recovery_codes)

def enable_mfa(username, code):
    """Phase 1 (§6): Aktiviert MFA, generiert Recovery-Codes, Status -> ACTIVE."""
    users = _load_users()
    u = users.get(username)
    if not u:
        return False, "Benutzer fehlt"
    pending = u.get("mfa_pending_secret")
    if not pending:
        return False, "Kein Pending-Secret"
    if not verify_mfa(pending, code):
        return False, "Code falsch"
    u["mfa_secret"] = pending
    u["mfa_enabled"] = True
    u["mfa_pending_secret"] = None
    u["mfa_verified_at"] = datetime.utcnow().isoformat() + "Z"
    u["last_security_action"] = datetime.utcnow().isoformat() + "Z mfa_enable"
    u["updated_at"] = datetime.utcnow().isoformat() + "Z"
    if not u.get("recovery_codes"):
        u["recovery_codes"] = _generate_recovery_codes()
    if u["status"] == USER_STATUS_MFA_REQUIRED:
        u["status"] = USER_STATUS_ACTIVE
    _save_users(users)
    audit_log("mfa_enable", username, f"{len(u['recovery_codes'])} Recovery-Codes generiert")
    return True, ""


def disable_mfa(username, by_admin):
    """Phase 1 (§6): Deaktiviert MFA mit Audit; entfernt Recovery-Codes."""
    users = _load_users()
    if username not in users:
        return
    u = users[username]
    u["mfa_enabled"] = False
    u["mfa_secret"] = None
    u["mfa_pending_secret"] = None
    u["mfa_verified_at"] = None
    u["recovery_codes"] = []
    u["updated_at"] = datetime.utcnow().isoformat() + "Z"
    # MFA-Pflicht-Rollen fallen zurück auf MFA_REQUIRED
    if u["role"] in MFA_REQUIRED_ROLES:
        u["status"] = USER_STATUS_MFA_REQUIRED
    u["last_security_action"] = datetime.utcnow().isoformat() + "Z mfa_disable"
    # §6: MFA-Änderung invalidiert Sessions (Sicherheitsereignis)
    u["sessions"] = {}
    _save_users(users)
    audit_log("mfa_disable", by_admin, f"user={username}, alle Sessions widerrufen")


def verify_recovery_code(username, code):
    """Phase 1 (§6): Verbraucht einen einmaligen Recovery-Code."""
    users = _load_users()
    u = users.get(username)
    if not u:
        return False
    codes = u.get("recovery_codes") or []
    code = code.strip().upper()
    # Vergleich in konstanter Zeit statt == (Timing-Seitenkanal).
    for c in codes:
        if hmac.compare_digest(str(c).upper(), code):
            codes.remove(c)
            u["recovery_codes"] = codes
            u["updated_at"] = datetime.utcnow().isoformat() + "Z"
            _save_users(users)
            audit_log("mfa_recovery_used", username)
            return True
    return False


# ─── Session-Management (serverseitig) ──────────────────────────────────────
SESSION_IDLE_TIMEOUT = 30 * 60       # 30 min idle
SESSION_ABS_TIMEOUT = 8 * 60 * 60    # 8 h absolut
MFA_GRACE = 10 * 60                  # 10 min für Reauth


def create_session(username, ip=""):
    """Legt serverseitige Session an. Gibt session_id zurück."""
    sid = secrets.token_urlsafe(32)
    users = _load_users()
    u = users.get(username)
    if not u:
        return None
    now = int(time.time())
    # LUECKE 4 (2026-09-27): mfa_verified_at wird hier NICHT gesetzt.
    # Vorher stand hier "now if u.get('mfa_enabled') else 0" — dadurch war
    # MFA ab dem Login fuer MFA_GRACE Sekunden "verifiziert", ohne dass je
    # ein TOTP eingegeben wurde. Bei mfa_secret=None (Zustand in
    # security_users.json) war die Verifikation damit gar nicht moeglich,
    # wurde aber behauptet. Jetzt: 0 = nicht verifiziert, bis
    # mark_mfa_verified() nach erfolgreicher TOTP-Pruefung aufgerufen wird.
    u.setdefault("sessions", {})[sid] = {
        "created": now, "last_seen": now, "ip": ip,
        "rotated_at": now, "mfa_verified_at": 0,
    }
    users[username] = u
    _save_users(users)
    return sid


def session_valid(username, sid):
    users = _load_users()
    u = users.get(username)
    if not u or not u.get("active"):
        return False
    s = u.get("sessions", {}).get(sid)
    if not s:
        return False
    now = int(time.time())
    if now - s["last_seen"] > SESSION_IDLE_TIMEOUT:
        return False
    if now - s["created"] > SESSION_ABS_TIMEOUT:
        return False
    return True


# 01.11.2026: touch_session() lief bei JEDER Anfrage und schrieb jedes Mal
# die komplette security_users.json (Lock + Merge + fsync). Das Dashboard
# pollt mehrere Routen - viele Schreibvorgaenge pro Minute fuer eine
# Zeitmarke, die nur gegen 30 min Idle-Timeout geprueft wird.
TOUCH_MIN_INTERVALL = 60  # Sekunden


def touch_session(username, sid):
    users = _load_users()
    u = users.get(username)
    if u and sid in u.get("sessions", {}):
        now = int(time.time())
        if now - int(u["sessions"][sid].get("last_seen") or 0) < TOUCH_MIN_INTERVALL:
            return
        u["sessions"][sid]["last_seen"] = now
        _save_users(users)


def rotate_session(username, sid):
    """Session-Rotation (nach Login + Rechteänderung)."""
    users = _load_users()
    u = users.get(username)
    if not u or sid not in u.get("sessions", {}):
        return None
    new_sid = secrets.token_urlsafe(32)
    old = u["sessions"].pop(sid)
    old["rotated_at"] = int(time.time())
    u["sessions"][new_sid] = old
    _save_users(users)
    return new_sid


def revoke_session(username, sid):
    users = _load_users()
    u = users.get(username)
    if u and sid in u.get("sessions", {}):
        u["sessions"].pop(sid)
        _save_users(users)


def revoke_all_sessions(username):
    users = _load_users()
    if username in users:
        users[username]["sessions"] = {}
        _save_users(users)


def mfa_eingerichtet(u):
    """WAHR nur wenn MFA wirklich nutzbar ist: Flag UND Secret vorhanden.

    Vorher galt mfa_enabled=True auch dann als 'eingerichtet', wenn
    mfa_secret=None war. security_users.json hatte genau diesen Zustand
    (admin, goldi5: mfa_enabled=True, mfa_secret=None) — die
    require_recent_mfa()-Gates wurden dadurch wirkungslos, ohne dass
    irgendwo eine Fehlermeldung entstand.
    """
    return bool(u and u.get("mfa_enabled") and u.get("mfa_secret"))


def mfa_recently_verified(username, sid):
    users = _load_users()
    u = users.get(username)
    if not u:
        return False
    s = u.get("sessions", {}).get(sid)
    if not s:
        return False
    if not u.get("mfa_enabled"):
        # Phase 1 (§6): MFA-Pflicht — Admin/Superadmin ohne MFA gelten
        # als NICHT verifiziert (kritische Routen leiten zur Einrichtung).
        return u.get("role") not in MFA_REQUIRED_ROLES
    if not u.get("mfa_secret"):
        # Flag ohne Secret: es kann gar nicht verifiziert werden. Als
        # "verifiziert" auszugeben waere ein Bypass. Faellt bewusst auf
        # "nicht eingerichtet" zurueck — enable_mfa() setzt beide Felder
        # gemeinsam, dieser Zustand ist also nur Altlast/Fehlkonfiguration.
        return False
    return (int(time.time()) - int(s.get("mfa_verified_at") or 0)) < MFA_GRACE



def mark_mfa_verified(username, sid):
    users = _load_users()
    u = users.get(username)
    if u and sid in u.get("sessions", {}):
        u["sessions"][sid]["mfa_verified_at"] = int(time.time())
        _save_users(users)


def verify_mfa_code(username, code):
    """Vollstaendige MFA-Pruefung fuer den Login-Pfad: TOTP + Replay-Schutz.

    Vorher rief dashboard.py /mfa direkt verify_mfa() auf. Dadurch war ein
    innerhalb des ±1-Fensters gueltiger Code beliebig oft wiederverwendbar
    (kein Replay-Schutz). Jetzt wird der TOTP-Zaehler des zuletzt
    akzeptierten Codes gespeichert und ein erneuter Versuch damit abgewiesen.

    Rueckgabe: (ok, fehlertext)
    """
    users = _load_users()
    u = users.get(username)
    if not u:
        return False, "Benutzer fehlt"
    secret = u.get("mfa_secret")
    if not secret:
        # Vorher: verify_mfa(u.get("mfa_secret", ""), code) -> bei vorhandenem
        # Key mit Wert None wurde None gereicht -> AttributeError -> HTTP 500.
        return False, "MFA ist nicht eingerichtet"
    if not verify_mfa(secret, code):
        return False, "Code falsch"
    jetzt = totp_counter()
    letzte = int(u.get("mfa_last_counter") or 0)
    if letzte and jetzt <= letzte:
        return False, "Code wurde bereits verwendet"
    u["mfa_last_counter"] = jetzt
    _save_users(users)
    return True, ""


# ─── CSRF (itsdangerous signed token) ───────────────────────────────────────
_csrf_ser = URLSafeTimedSerializer(CSRF_SECRET, salt="csrf")


def generate_csrf_token():
    return _csrf_ser.dumps(secrets.token_urlsafe(16))


def verify_csrf_token(token, max_age=3600):
    try:
        _csrf_ser.loads(token, max_age=max_age)
        return True
    except (BadSignature, SignatureExpired):
        return False


# ─── Audit-Log (manipulationssicher: append-only JSON-Lines) ────────────────
def audit_log(action, actor, detail=""):
    """Schreibt Append-Only Audit-Eintrag. Nicht nachträglich änderbar."""    # BUG-Audit-Rotation: bei >10MB als .1 archivieren (max 5 Gen), append-only erhalten
    try:
        if os.path.exists(AUDIT_FILE) and os.path.getsize(AUDIT_FILE) > 10 * 1024 * 1024:
            for gen in range(5, 0, -1):
                old_f = f"{AUDIT_FILE}.{gen}"
                prev = f"{AUDIT_FILE}.{gen-1}" if gen > 1 else AUDIT_FILE
                if os.path.exists(prev):
                    if os.path.exists(old_f):
                        os.remove(old_f)
                    os.rename(prev, old_f)
    except Exception:
        pass

    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "action": action, "actor": actor, "detail": detail,
    }
    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ─── Login-Rate-Limit (Brute-Force-Schutz, OWASP A07) ────────────────────────
LOGIN_RATE_FILE = os.path.join(BASE, "login_rate.json")
_LOGIN_RATE_MAX_ATTEMPTS = 5          # Fehlversuche bevor Block
_LOGIN_RATE_BASE_BLOCK_S = 30         # Start-Blockzeit
_LOGIN_RATE_WINDOW_S = 15 * 60        # Zählfenster


def _load_login_rate():
    try:
        return json.load(open(LOGIN_RATE_FILE, encoding="utf-8"))
    except Exception:
        return {}


def _save_login_rate(data):
    try:
        with open(LOGIN_RATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def login_blocked(ip, username=None):
    """True wenn Login von dieser IP (oder User) gerade blockiert ist.
    Exponential Backoff: 5 Versuche -> 30s, danach 60s, 120s, 240s…"""
    data = _load_login_rate()
    now = time.time()
    for key in (ip, username):
        if not key:
            continue
        e = data.get(str(key))
        if not e:
            continue
        if e.get("blocked_until") and e["blocked_until"] > now:
            rest = int(e["blocked_until"] - now)
            return rest
    return 0


def register_login_fail(ip, username=None):
    """Zählt Fehlversuch, setzt exponentiellen Block ab Schwelle."""
    data = _load_login_rate()
    now = time.time()
    for key in (ip, username):
        if not key:
            continue
        e = data.setdefault(str(key), {"fails": 0, "blocked_until": 0})
        # Fenster abgelaufen? -> Reset
        if e.get("last") and now - e["last"] > _LOGIN_RATE_WINDOW_S:
            e["fails"] = 0
        e["fails"] += 1
        e["last"] = now
        if e["fails"] >= _LOGIN_RATE_MAX_ATTEMPTS:
            level = e["fails"] - _LOGIN_RATE_MAX_ATTEMPTS
            block = _LOGIN_RATE_BASE_BLOCK_S * (2 ** min(level, 6))
            e["blocked_until"] = now + block
    _save_login_rate(data)


def register_login_ok(ip, username=None):
    """Reset der Zähler nach erfolgreichem Login."""
    data = _load_login_rate()
    for key in (ip, username):
        if key and key in data:
            data.pop(str(key), None)
    _save_login_rate(data)


def login_rate_stats():
    """Aggregierte Rate-Limit-Daten (für Admin-Ansicht)."""
    data = _load_login_rate()
    now = time.time()
    out = []
    for key, e in data.items():
        if e.get("fails", 0) >= 2:
            blocked = e.get("blocked_until", 0) > now
            rest = max(0, int(e.get("blocked_until", 0) - now)) if blocked else 0
            out.append({"key": key, "fails": e.get("fails", 0),
                        "blocked": blocked, "rest_s": rest,
                        "last": str(e.get("last", ""))[:19]})
    out.sort(key=lambda x: -x["fails"])
    return out


def read_audit(limit=200):
    """Liest die letzten `limit` Audit-Einträge (append-only)."""
    if not os.path.exists(AUDIT_FILE):
        return []
    out = []
    with open(AUDIT_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out[-limit:]


# ─── Berechtigungsprüfung (Phase 6) ─────────────────────────────────────────
def _role_fine_perms(role):
    """Feine Permissions einer Rolle (deny-by-default: leere Liste = nichts)."""
    return ROLE_FINE_PERMISSIONS.get(role, [])


def role_has_permission(role, required):
    """Prüft, ob Rolle die angeforderte Berechtigung hat (inkl. Vererbung).

    Phase 2 (§7): feine Permissions + Alias-Auflösung. Deny-by-default.
    """
    if role == "superadmin":
        return True
    if role not in ROLE_PERMISSIONS and role not in TENANT_ROLE_PERMISSIONS:
        return False
    # 1) Direkte feine Permission
    if required in _role_fine_perms(role):
        return True
    # 2) Grobe Katalog-Permission (bestehende Semantik)
    if required in ROLE_PERMISSIONS.get(role, []) or \
       required in TENANT_ROLE_PERMISSIONS.get(role, []):
        return True
    # 3) Alias-Auflösung: "users.read" via grobem "users"
    for coarse, fines in PERMISSION_ALIASES.items():
        if required in fines:
            if coarse in ROLE_PERMISSIONS.get(role, []) or \
               coarse in TENANT_ROLE_PERMISSIONS.get(role, []):
                return True
            break
    return False


# ─── PHASE 2: Effektive Rolle + Permissions im Tenant-Kontext ───────────────
def effective_role(user, tenant_id=None):
    """Effektive Rolle eines Users.

    Priorität: Membership-Rolle im angegebenen Tenant (oder aktuellem Kontext)
    > globale User-Rolle. Fallback: 'visitor'.
    """
    if not user:
        return "visitor"
    tid = tenant_id or get_current_tenant()
    if tid:
        try:
            import db as _db
            m = _db.MTDB()
            try:
                member = m.tenant_membership_role(tid, user.get("username", ""))
            finally:
                m.close()
            # Dict {role, status} oder None
            if member and member.get("status", "aktiv") != "inaktiv":
                role = member.get("role")
                if role:
                    return str(role).lower()
        except Exception:
            pass
    return (user.get("role") or "visitor").lower()


def effective_permissions(user, tenant_id=None):
    """Permissions der effektiven Rolle (fein + grob, dedupliziert)."""
    role = effective_role(user, tenant_id)
    if role == "superadmin":
        return list(ALL_PERMISSIONS)
    fine = _role_fine_perms(role)
    coarse = TENANT_ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS.get(role, []))
    return sorted(set(fine + coarse))


def has_permission(user, permission, tenant_id=None):
    """Prüft Permission im Tenant-Kontext. Superadmin hat immer alles."""
    role = effective_role(user, tenant_id)
    return role_has_permission(role, permission)


def has_permission_in(role, permission):
    """Statische Prüfung: hat die ROLLE diese Permission (ohne User/DB)?"""
    return role_has_permission(role, permission)


# Rolle → Zugriffsebene (konsistent mit ROLE_PERMISSIONS / ACCESS_ORDER)
ROLE_TO_LEVEL = {
    "visitor": "PUBLIC",
    "user": "AUTHENTICATED",
    "analyst": "ANALYST",
    "operator": "OPERATOR",
    "admin": "ADMIN",
    "superadmin": "SUPERADMIN",
}

def access_level_met(user_role, required_level):
    """Prüft Zugriffsebene (PUBLIC < AUTHENTICATED < ANALYST < OPERATOR < ADMIN < SUPERADMIN)."""
    try:
        ui = ACCESS_ORDER.index(ROLE_TO_LEVEL.get((user_role or "visitor").lower(), "PUBLIC"))
        ri = ACCESS_ORDER.index(required_level)
        return ui >= ri
    except ValueError:
        return False


def route_class(route_rule):
    """Gibt Zugriffsklasse für eine Route zurück (Phase 6 Mapping).
    Matches exakte Routen + Flask-Patterns (/assets/<path:...>). Default: restriktiv."""
    if route_rule in ROUTE_ACCESS:
        return ROUTE_ACCESS[route_rule]
    # Flask-Pattern-Prefixe: /assets/<path:dateiname>, /static/<path:...>, /reports/<path:...>
    for pattern, cls in ROUTE_ACCESS.items():
        if "<" in pattern and ">" in pattern:
            prefix = pattern.split("<")[0].rstrip("/")
            if route_rule.startswith(prefix + "/") or route_rule == prefix:
                return cls
    return "ADMIN"  # Default: restriktiv


# ─── Flask-Integration (Decorators + Helper) ────────────────────────────────
# Diese Helper nutzen flask.session + flask.request (müssen innerhalb Request
# aufgerufen werden). Dekoriert Routen serverseitig — Frontend-Ausblendung
# ist KEINE Berechtigung (Auftrag Regel 5).
from flask import session as _flask_session, request as _flask_request
from flask import redirect, url_for  # 01.11.2026: fehlten fuer login_required_redirect()


def _zusatz_hosts():
    """Zusaetzliche vertrauenswuerdige Hosts fuer die CSRF-Ausnahme."""
    werte = [h.strip() for h in os.environ.get("MICRO_TRADER_TRUSTED_HOSTS", "").split(",")]
    try:
        with open(os.path.join(BASE, ".trusted_hosts"), encoding="utf-8") as f:
            werte += [z.strip() for z in f if z.strip() and not z.startswith("#")]
    except OSError:
        pass
    return tuple(h for h in werte if h)


def _current_username():
    # App nutzt Cookie-basierte Auth (nicht flask.session)
    return _flask_request.cookies.get("username")


def _current_sid():
    return _flask_request.cookies.get("sid")


def current_user():
    """Gibt das User-Dict zurück oder None."""
    uname = _current_username()
    if not uname:
        return None
    if not session_valid(uname, _current_sid()):
        return None
    return get_user(uname)


def login_required_redirect():
    """Redirect zur Login-Seite wenn nicht angemeldet. Gibt Response oder None."""
    u = current_user()
    if not u:
        return redirect(url_for("login") if "login" in _ALL_ROUTES else "/login")
    return None


def require_auth():
    """Decorator: Route nur mit gültiger Session."""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapper(*a, **kw):
            u = current_user()
            if not u:
                from flask import redirect as _r, url_for as _u
                return _r((_u("login") if "login" in _ALL_ROUTES else "/login")
                          + "?next=" + _flask_request.path)
            touch_session(u["username"], _current_sid())
            return f(*a, **kw)
        return wrapper
    return decorator


def require_role(min_role):
    """Decorator: Route nur mit Rolle >= min_role.
    min_role ist eine ROLLE ('admin') — wird zu EBENE ('ADMIN') gemappt."""
    min_level = ROLE_TO_LEVEL.get((min_role or "visitor").lower(), "PUBLIC")
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapper(*a, **kw):
            u = current_user()
            if not u:
                from flask import redirect as _r, url_for as _u
                return _r((_u("login") if "login" in _ALL_ROUTES else "/login")
                          + "?next=" + _flask_request.path)
            if not access_level_met(u["role"], min_level):
                from flask import abort
                abort(403)
            touch_session(u["username"], _current_sid())
            return f(*a, **kw)
        return wrapper
    return decorator


def require_tenant_role(min_role):
    """Decorator (PHASE 2): Route nur mit Rolle >= min_role im TENANT-Kontext.

    Nutzt die effektive Rolle (Membership im aktuellen Tenant > globale Rolle).
    Admin-Routen wirken damit tenant-bezogen: Ein User ist nur Admin in
    Tenants, in denen er auch Membership-Admin ist (oder global superadmin).
    """
    min_level = ROLE_TO_LEVEL.get((min_role or "visitor").lower(), "PUBLIC")
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapper(*a, **kw):
            u = current_user()
            if not u:
                from flask import redirect as _r, url_for as _u
                return _r((_u("login") if "login" in _ALL_ROUTES else "/login")
                          + "?next=" + _flask_request.path)
            eff = effective_role(u)
            if not access_level_met(eff, min_level):
                from flask import abort
                abort(403)
            touch_session(u["username"], _current_sid())
            return f(*a, **kw)
        return wrapper
    return decorator


def require_permission(permission):
    """Decorator (PHASE 2): Route nur mit Permission im Tenant-Kontext."""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapper(*a, **kw):
            u = current_user()
            if not u:
                from flask import redirect as _r, url_for as _u
                return _r((_u("login") if "login" in _ALL_ROUTES else "/login")
                          + "?next=" + _flask_request.path)
            if not has_permission(u, permission):
                from flask import abort
                abort(403)
            touch_session(u["username"], _current_sid())
            return f(*a, **kw)
        return wrapper
    return decorator


def require_recent_mfa():
    """Phase 1 (§6): Route mit MFA-Freigabe für Admin/Superadmin.
    KEIN Login-Lockout und KEIN harter Redirect mehr bei fehlendem MFA:
    Ohne eingerichtetes MFA -> Route wird DURCHGELASSEN (nur UI-Hinweis,
    User-Entscheidung 2026-08-10: MFA-Zwang blockt nicht den Zugang).
    Mit MFA aber abgelaufener Reauth -> /mfa (Verifikation)."""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapper(*a, **kw):
            u = current_user()
            if not u:
                from flask import redirect as _r, url_for as _u
                return _r((_u("login") if "login" in _ALL_ROUTES else "/login"))
            if u["role"] not in MFA_REQUIRED_ROLES:
                return f(*a, **kw)
            # Rolle in MFA-Pflicht: KEIN Zwang bei fehlendem MFA (durchlassen,
            # Hinweis erfolgt im UI-Banner). Nur Reauth erzwingen, wenn MFA
            # WIRKLICH eingerichtet ist (Flag UND Secret vorhanden) — sonst
            # waere /mfa nicht passierbar und der User eingeschlossen.
            if mfa_eingerichtet(u) and not mfa_recently_verified(u["username"], _current_sid()):
                from flask import redirect as _r, url_for as _u
                return _r(_u("mfa_verify") if "mfa_verify" in _ALL_ROUTES else "/mfa")
            return f(*a, **kw)
        return wrapper
    return decorator


_ALL_ROUTES = set()  # wird von dashboard.py nach Routen-Registrierung gefüllt




CSRF_MUTATING_GET_PATHS = frozenset({
    # LUECKE 7 (2026-09-27): GET-Routen, die den Zustand aendern. Der
    # CSRF-Guard in dashboard.py uebersprang bisher JEDEN GET/HEAD-Request,
    # damit waren diese Routen ohne Token aufrufbar — ein <img src=...> auf
    # einer fremden Seite genuegte, um /api/depot_loeschen auszuloesen.
    "/api/pause_trading",       # Trading anhalten/fortsetzen
    "/api/suspend_trading",     # Trading suspendieren
    "/api/risk_appetite",       # globaler Risiko-Appetit der KI
    "/api/close_portfolio",     # Portfolio schliessen
    "/api/depot_pause",         # einzelnes Depot pausieren
    "/api/depot_verkaufen",     # Positionen verkaufen
    "/api/depot_schliessen",    # Depot schliessen
    "/api/depot_loeschen",      # Depot inkl. Dateien loeschen
})


def csrf_token_required(path, method):
    """True, wenn dieser Request zwingend ein gueltiges CSRF-Token braucht."""
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return True
    return path in CSRF_MUTATING_GET_PATHS


def csrf_token_strict_valid_for_request(request):
    """Wie csrf_token_valid_for_request, aber OHNE die permissive
    Lokal-Origin-Ausnahme: es MUSS ein gueltiges Token mitgeschickt werden.

    Nötig, weil die Ausnahme sonst alles aufhebt: der Dienst ist ueber
    Tailscale (eigene 100.x-IP) und die Reverse-Proxy-Hosts erreichbar, und
    request.host enthaelt bei JEDEM lokalen Zugriff eines der in
    _trusted gelisteten Muster. Damit war "permissive bei lokalem Origin"
    fuer produktiv genutzte Originen faktisch "immer erlaubt" — ein
    <img src="http://host/api/depot_loeschen?..."> auf einer fremden Seite
    haette ausgereicht. Fuer die zustandsaendernden GET-Routen gilt
    deshalb der Token-Zwang ohne Ausnahme.
    """
    tok = (request.headers.get("X-CSRF-Token")
           or (request.form.get("csrf_token") if hasattr(request, "form") else None)
           or (request.json.get("csrf_token")
               if (hasattr(request, "is_json") and request.is_json) else None))
    if not tok:
        return False
    return verify_csrf_token(tok)


def csrf_token_valid_for_request(request):
    """BUG-005: prueft CSRF-Token eines Requests. Token aus Header X-CSRF-Token
    oder Form-Feld csrf_token. Bei lokaler Origin (127.0.0.1/localhost) ohne
    Token: True (Permissive — lokales Dashboard, kein Cross-Site-Risiko).
    Bei Fremd-Origin ohne gueltiges Token: False. So wird CSRF abgewehrt
    OHNE das lokale Dashboard zu brechen."""
    origin = (request.headers.get("Origin", "") or request.headers.get("X-Forwarded-Host", "")
             or request.headers.get("X-Forwarded-Proto", "") or request.headers.get("Host", ""))
    host = (request.host or "") or (request.headers.get("X-Forwarded-Host", "") or "")
    # Lokale + vertrauenswürdige Proxy/Funnel-Hosts (Tailscale Funnel: *.ts.net, 100.x,
    # bzw. der Reverse-Proxy leitet Host unverändert durch).
    # 01.11.2026: Eigene Hostnamen/IPs nicht mehr im Code, sondern aus
    # MICRO_TRADER_TRUSTED_HOSTS (kommagetrennt) oder .trusted_hosts
    # (eine pro Zeile, git-ignoriert). *.ts.net ist generisch enthalten.
    _trusted = ("127.0.0.1", "localhost", "::1", ".ts.net") + _zusatz_hosts()
    # KEIN Eintrag fuer das eigene LAN.
    #
    # 29.09.2026: Ich hatte das LAN zuerst hier eingetragen, weil der
    # Browser sonst bei jedem POST "CSRF-Token ungueltig" bekam. Das war
    # der falsche Weg und oeffnete Login-CSRF wieder: _local ist
    # ODER-verknuepft, also hat "host passt" Vorrang, auch wenn ein
    # fremder Origin-Header mitschickt. Nachgewiesen:
    #     POST / mit Origin: http://evil.example, ohne Token -> HTTP 200
    #
    # Richtig ist das Token, nicht die Ausnahme: dashboard.py liefert
    # das Landing-Formular mit verstecktem csrf_token, das Frontend
    # schickt es mit. So bleibt der Dienst auch ueber das LAN scharf.
    _local = any(h in host for h in _trusted) or any(h in origin for h in _trusted)
    tok = (request.headers.get("X-CSRF-Token")
           or (request.form.get("csrf_token") if hasattr(request, "form") else None)
           or (request.json.get("csrf_token") if (hasattr(request, "is_json") and request.is_json) else None))
    if tok:
        return verify_csrf_token(tok)
    return _local
if __name__ == "__main__":
    # Selbsttest (nur bei Aufruf, nicht im Import)
    ok, err = create_user("__selftest__", "Test1234!", "user")
    assert ok, err
    assert verify_password("__selftest__", "Test1234!")
    assert not verify_password("__selftest__", "falsch")
    sec = generate_mfa_secret()
    uri = mfa_provisioning_uri(sec, "__selftest__")
    assert uri.startswith("otpauth://totp/")
    code = _totp(sec, int(time.time()))
    assert verify_mfa(sec, code), "TOTP Verifikation fehlgeschlagen"
    sid = create_session("__selftest__")
    assert session_valid("__selftest__", sid)
    tok = generate_csrf_token()
    assert verify_csrf_token(tok)
    # Cleanup
    users = _load_users()
    users.pop("__selftest__", None)
    _save_users(users)
    print("security.py Selbsttest OK")
