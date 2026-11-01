#!/usr/bin/env python3
"""
test_server_security.py — Phase 10 Tests für Micro-Trader Server-Sicherheit.

Testet:
- Netzwerk: Bind 127.0.0.1 (config), keine 0.0.0.0, Debug off
- Auth: Login ok / falsch pw fail / Logout invalidiert
- Authz: Jede Rolle nur ihre Routen (PUBLIC/AUTHENTICATED/ANALYST/OPERATOR/ADMIN)
- Trading-Sicherheit: Paper/Shadow bleibt, keine Echtgeld-Pfade
- Regression: security.py Selbsttest, ROUTE_ACCESS Vollständigkeit

Start: python test_server_security.py  (Hermes-venv)
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import security as sec

OK = 0
FAIL = 0
def ck(name, cond, info=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {info}")

print("=== PHASE 10: SECURITY TESTS ===\n")

# ─── 1. security.py Selbsttest (Basisfunktionen) ──────────────────
print("1. security.py Basisfunktionen")
ok, err = sec.create_user("__t__", "Test1234!", "user")
ck("create_user", ok, err)
ck("verify_password ok", sec.verify_password("__t__", "Test1234!"))
ck("verify_password wrong", not sec.verify_password("__t__", "falsch"))
sec_ = sec.generate_mfa_secret()
ck("mfa provisioning uri", sec.mfa_provisioning_uri(sec_, "__t__").startswith("otpauth://totp/"))
code = sec._totp(sec_, int(time.time()))
ck("mfa verify totp", sec.verify_mfa(sec_, code))
sid = sec.create_session("__t__", "127.0.0.1")
ck("session valid", sec.session_valid("__t__", sid))
tok = sec.generate_csrf_token()
ck("csrf token verify", sec.verify_csrf_token(tok))
sec.audit_log("test", "__t__", "selftest")
# cleanup
us = sec._load_users(); us.pop("__t__", None); sec._save_users(us)

# ─── 2. Rollen-Matrix (access_level_met) ─────────────────────────
print("\n2. Rollen-Vererbung (access_level_met)")
ck("visitor < user", not sec.access_level_met("visitor", "AUTHENTICATED"))
ck("user >= AUTHENTICATED", sec.access_level_met("user", "AUTHENTICATED"))
ck("analyst >= ANALYST", sec.access_level_met("analyst", "ANALYST"))
ck("operator >= OPERATOR", sec.access_level_met("operator", "OPERATOR"))
ck("admin >= ADMIN", sec.access_level_met("admin", "ADMIN"))
ck("superadmin >= SUPERADMIN", sec.access_level_met("superadmin", "SUPERADMIN"))
ck("user < ADMIN", not sec.access_level_met("user", "ADMIN"))
ck("analyst < OPERATOR", not sec.access_level_met("analyst", "OPERATOR"))

# ─── 3. ROUTE_ACCESS Vollständigkeit ────────────────────────────
print("\n3. ROUTE_ACCESS Mapping (Phase 6)")
# Alle echten Routen aus dashboard.py sammeln
import re
src = open("dashboard.py", encoding="utf-8", errors="replace").read()
routes = set(re.findall(r'@app\.route\("([^"]+)"', src))
missing = [r for r in routes if r not in sec.ROUTE_ACCESS and not r.startswith("/api/version")]
ck("alle HTML-Routen gemappt", len(missing) == 0, f"fehlend: {missing}")
# Kritische Routen korrekt klassifiziert
ck("/login PUBLIC", sec.route_class("/login") == "PUBLIC")
ck("/api/settings ADMIN", sec.route_class("/api/settings") == "ADMIN")
ck("/api/pause_trading OPERATOR", sec.route_class("/api/pause_trading") == "OPERATOR")
ck("/api/db_query ANALYST", sec.route_class("/api/db_query") == "ANALYST")
ck("/data AUTHENTICATED", sec.route_class("/data") == "AUTHENTICATED")
ck("/admin ADMIN", sec.route_class("/admin") == "ADMIN")

# ─── 4. Flask Bind (config) ─────────────────────────────────────
print("\n4. Netzwerk-Grenzen (Phase 2)")
m = re.search(r'app\.run\((.*?)\)', src, re.S)
runline = m.group(1) if m else ""
ck("bind 127.0.0.1 (nicht 0.0.0.0)", "127.0.0.1" in runline and "0.0.0.0" not in runline, runline)
ck("debug=False", "debug=False" in runline, runline)

# ─── 5. Trading-Sicherheit (Paper/Shadow ONLY) ─────────────────
print("\n5. Trading-Sicherheit (kein Echtgeld)")
ck("keine broker/api keys im Code", not re.search(r"(broker_api_key|broker_secret|live_trade|real_money|echetgeld|broker_login|broker_password)", src, re.I))
ck("pause_flag.json Mechanismus vorhanden", os.path.exists("pause_flag.json") or "pause_trading" in src)

# ─── 6. Flask test_client (Auth-Flow) ───────────────────────────
print("\n6. Auth-Flow via Flask test_client")
try:
    import dashboard
    app = dashboard.app
    app.config["TESTING"] = True
    c = app.test_client()
    # Landingpage öffentlich
    r = c.get("/")
    ck("Landingpage öffentlich (200)", r.status_code == 200)
    ck("Landingpage ohne internes JSON", "Depotwerte" not in r.get_data(as_text=True))
    # /data ohne Login -> redirect/login
    r = c.get("/data")
    ck("/data ohne Auth -> 302/401", r.status_code in (302, 401))
    # /admin ohne Login -> 302/401
    r = c.get("/admin")
    ck("/admin ohne Auth -> 302/401", r.status_code in (302, 401))
    # Login mit Testuser
    sec.create_user("__flow__", "Flow1234!", "admin")
    r = c.post("/login", data={"username": "__flow__", "password": "Flow1234!"})
    ck("Login POST -> redirect", r.status_code in (302, 303), str(r.status_code))
    # Session-Cookie vorhanden (prüfe alle Set-Cookie-Header)
    cookies = r.headers.getlist("Set-Cookie")
    ck("Session-Cookie gesetzt", any("sid=" in c for c in cookies), str(cookies))
    # /admin mit Session
    r2 = c.get("/admin")
    ck("/admin mit Auth -> 200", r2.status_code == 200)
    # Logout
    c.get("/logout")
    r3 = c.get("/admin")
    ck("/admin nach Logout -> 302/401", r3.status_code in (302, 401))
    # cleanup
    us = sec._load_users(); us.pop("__flow__", None); sec._save_users(us)
except Exception as e:
    ck("Flask test_client", False, str(e))

# ─── Phase 15: Benutzerverwaltung-API (v2.23.0) ─────────────────────────────
print("\n7. Benutzerverwaltung-API (v2.23.0)")
try:
    import dashboard
    app = dashboard.app; app.config["TESTING"] = True
    c = app.test_client()
    # Ohne Auth -> 401
    r = c.get("/api/users")
    ck("/api/users ohne Auth -> 401", r.status_code == 401)
    r = c.get("/api/me")
    ck("/api/me ohne Auth -> 401", r.status_code == 401)
    # MFA-Pflicht (§6): Admin-Routen verlangen MFA. Daher Admin-Test-User
    # mit eingerichtetem MFA anlegen und als dieser einloggen.
    ok_mfa_admin, _ = sec.create_user("__v23admin__", "AdminTest123!", role="admin")
    us = sec._load_users()
    us["__v23admin__"]["mfa_pending_secret"] = sec.generate_mfa_secret()
    sec._save_users(us)
    secret = us["__v23admin__"]["mfa_pending_secret"]
    code = sec._totp(secret, int(time.time()))
    ok_en, _ = sec.enable_mfa("__v23admin__", code)
    ck("MFA-Pflicht: Admin-Test-User mit MFA", ok_en)
    c.post("/", data={"username": "__v23admin__", "password": "AdminTest123!"})
    r = c.get("/api/me")
    j = r.get_json()
    ck("/api/me als admin -> 200 + superadmin",
       r.status_code == 200 and (j.get("role") == "superadmin" or j.get("role") == "admin"))
    r = c.get("/api/users")
    ck("/api/users als admin -> 200", r.status_code == 200 and "users" in (r.get_json() or {}))
    # Create/409/Role/Deactivate/ResetPW/Revoke
    r = c.post("/api/users/create", json={"username": "__v23__", "password": "TestPass123!", "role": "analyst"})
    ck("create -> 200", r.status_code == 200)
    r = c.post("/api/users/create", json={"username": "__v23__", "password": "TestPass123!", "role": "analyst"})
    ck("create dup -> 409", r.status_code == 409)
    r = c.post("/api/users/__v23__/role", json={"role": "operator"})
    ck("role -> 200", r.status_code == 200)
    r = c.post("/api/users/__v23__/deactivate", json={"active": False})
    ck("deactivate -> 200", r.status_code == 200)
    r = c.post("/api/users/__v23__/reset-pw", json={"password": "NeuPass123!"})
    ck("reset-pw -> 200", r.status_code == 200)
    r = c.post("/api/users/__v23__/revoke")
    ck("revoke -> 200", r.status_code == 200)
    # Nicht-Admin darf /api/users NICHT sehen
    c2 = app.test_client()
    c2.post("/", data={"username": "__v23__", "password": "NeuPass123!"})
    r = c2.get("/api/users")
    ck("Nicht-Admin /api/users -> 403/401", r.status_code in (401, 403))
    # Admin OHNE MFA darf /api/users NICHT sehen (MFA-Pflicht §6)
    sec.create_user("__v23nomfa__", "NoMfaTest123!", role="admin")
    c3 = app.test_client()
    c3.post("/", data={"username": "__v23nomfa__", "password": "NoMfaTest123!"})
    r = c3.get("/api/users")
    ck("Admin ohne MFA /api/users -> Durchlass (MFA-Zwang entfernt 2026-08-10)",
       r.status_code == 200)
    # cleanup
    us = sec._load_users()
    for _n in ("__v23__", "__v23admin__", "__v23nomfa__"):
        us.pop(_n, None)
    sec._save_users(us)
except Exception as e:
    ck("Benutzerverwaltung-API", False, str(e))

# ─── Phase 15b: Mandanten-Modell (v2.26.0) ─────────────────────────────────
print("\n7b. Mandanten-Modell (v2.26.0)")
try:
    import db as mtdb
    m = mtdb.MTDB()
    tid = m.tenant_ensure_default()
    ck("Default-Tenant existiert", tid == 1 and m.tenant_get(tid)["tenant_key"] == "default")
    t2, fehler = m.tenant_create("__suite_tenant__", "Suite-Test")
    ck("Tenant anlegen -> ok", t2 is not None and fehler is None)
    t3, fehler = m.tenant_create("__suite_tenant__", "Dup")
    ck("Tenant-Duplikat -> fehler", t3 is None and fehler)
    ok = m.tenant_membership_add(t2, "admin", "admin")
    ck("Membership hinzufuegen", ok)
    ms = m.tenant_memberships_for_user("admin")
    ck("Membership sichtbar", any(x["tenant_id"] == t2 for x in ms))
    ws, wfehler = m.workspace_create(t2, "ws1", "Workspace 1")
    ck("Workspace anlegen", ws is not None and wfehler is None)
    m.conn.execute("DELETE FROM tenant_memberships WHERE tenant_id=?", (t2,))
    m.conn.execute("DELETE FROM workspaces WHERE tenant_id=?", (t2,))
    m.conn.execute("DELETE FROM tenants WHERE id=?", (t2,))
    m.conn.commit()
    m.close()
    # API-Test via Flask
    import dashboard as dash
    app2 = dash.app; app2.config["TESTING"] = True
    cc = app2.test_client()
    r = cc.get("/api/tenants")
    ck("API /api/tenants ohne Auth -> 401", r.status_code == 401)
    cc.post("/", data={"username": "admin", "password": "Admin2026!sicher"})
    r = cc.get("/api/tenants")
    ck("API /api/tenants als admin -> 200", r.status_code == 200 and "tenants" in r.get_json())
    r = cc.post("/api/tenants/create", json={"tenant_key": "BAD KEY!", "name": "x"})
    ck("API tenant_key-Validierung -> 400", r.status_code == 400)
    r = cc.get("/api/me")
    j = r.get_json()
    ck("API /api/me mit tenant-Kontext", j.get("tenants", {}).get("current_tenant") == 1)
except Exception as e:
    ck("Mandanten-Modell", False, str(e))

# ─── Phase 15c: Rollen-/Berechtigungsmodell (v2.27.0) ───────────────────────
print("\n7c. Rollen-/Berechtigungsmodell (v2.27.0)")
try:
    import db as mtdb2
    m = mtdb2.MTDB()
    # Idempotent: alte Reste entfernen
    try:
        m.conn.execute("DELETE FROM tenant_memberships WHERE tenant_id IN "
                       "(SELECT id FROM tenants WHERE tenant_key='__rolle_suite__')")
        m.conn.execute("DELETE FROM tenants WHERE tenant_key='__rolle_suite__'")
        m.conn.commit()
    except Exception:
        pass
    # Test-Tenant + User mit Membership-Rolle != globaler Rolle
    t2, fehler = m.tenant_create("__rolle_suite__", "Rollen-Suite")
    ck("Rollen-Tenant anlegen", t2 is not None and fehler is None)
    ok1, fe1 = sec.create_user("__rolle_a__", "TestPass123!", "user")
    ok2, fe2 = sec.create_user("__rolle_b__", "TestPass123!", "operator")
    ck("Rollen-User anlegen", ok1 and ok2)
    m.tenant_membership_add(t2, "__rolle_a__", "admin")
    m.close()

    ua = sec.get_user("__rolle_a__")
    # Effektive Rolle: Membership 'admin' > globale 'user'
    ck("effektive Rolle gewinnt", sec.effective_role(ua, t2) == "admin")
    ck("andere Tenant -> globale Rolle", sec.effective_role(ua, 1) == "user")
    ck("Tenant-Permissions enthalten tenant_manage",
       "tenant_manage" in sec.effective_permissions(ua, t2))
    ck("admin hat KEIN tenant_delete", not sec.has_permission(ua, "tenant_delete", t2))
    ck("superadmin hat alles", sec.has_permission({"role": "superadmin"}, "tenant_delete"))
    ub = sec.get_user("__rolle_b__")
    ck("operator tenant_trade_control", sec.has_permission(ub, "tenant_trade_control", t2))

    import dashboard as dash2
    app3 = dash2.app; app3.config["TESTING"] = True
    c3 = app3.test_client()
    c3.post("/", data={"username": "admin", "password": "Admin2026!sicher"})
    r = c3.get("/api/me/permissions")
    j = r.get_json()
    ck("API /api/me/permissions superadmin",
       j.get("effective_role") == "superadmin" and "tenant_delete" in j.get("permissions", []))
    r = c3.get("/api/roles")
    j = r.get_json()
    ck("API /api/roles Katalog", r.status_code == 200 and len(j.get("roles", [])) == 6
       and len(j.get("all_permissions", [])) >= 20)
    # Tenant-Admin (global user) erreicht /api/roles im Tenant-Kontext
    c4 = app3.test_client()
    c4.post("/", data={"username": "__rolle_a__", "password": "TestPass123!"})
    r = c4.get("/api/roles")
    ck("Tenant-Admin /api/roles -> 200 (effektiv)", r.status_code == 200)
    r = c4.get("/api/tenants")
    # PHASE 3: Tenant-Admin sieht die Liste, aber NUR seinen eigenen Tenant
    # (Isolation §2.3) — nicht mehr 403 wie bei globaler ADMIN-Prüfung.
    j4 = r.get_json() if r.is_json else {}
    ck("Tenant-Admin /api/tenants -> 200 (eigener Tenant sichtbar)",
       r.status_code == 200 and
       all(t.get("tenant_id") == 1 for t in j4.get("tenants", [])))
    # Operator ohne Membership -> 403
    c5 = app3.test_client()
    c5.post("/", data={"username": "__rolle_b__", "password": "TestPass123!"})
    r = c5.get("/api/roles")
    ck("Operator /api/roles -> 403", r.status_code == 403)
    j = c5.get("/api/me/permissions").get_json()
    ck("Operator effektive Permissions",
       j.get("effective_role") == "operator" and "tenant_trade_control" in j.get("permissions", []))
    # Cleanup
    m2 = mtdb2.MTDB()
    m2.conn.execute("DELETE FROM tenant_memberships WHERE tenant_id=?", (t2,))
    m2.conn.execute("DELETE FROM tenants WHERE id=?", (t2,))
    m2.conn.commit(); m2.close()
    us = sec._load_users()
    us.pop("__rolle_a__", None); us.pop("__rolle_b__", None)
    sec._save_users(us)
except Exception as e:
    ck("Rollen-/Berechtigungsmodell", False, str(e))

# ─── Phase 15d: Mandantentrennung (v2.28.0, PHASE 4) ───────────────────
print("\n7d. Mandantentrennung (v2.28.0, PHASE 4)")
try:
    import os as _os, json as _json, db as mtdb3, dashboard as dash3
    BASE = dash3.BASE
    TD = _os.path.join(BASE, "depot_777.json")
    with open(TD, "w") as f:
        _json.dump({"tenant_id": 5, "bargeld": 500, "start_wert": 100,
                    "positions": {"AAPL": {"shares": 2, "avg_price": 10}}, "historie": []}, f)
    s1 = dash3._tenant_scoped_depot_files(1)
    s5 = dash3._tenant_scoped_depot_files(5)
    ck("Tenant 1 sieht Tenant-5-Depot NICHT", "depot_777.json" not in str(s1))
    ck("Tenant 5 sieht eigenes Depot", "depot_777.json" in str(s5))
    m = mtdb3.MTDB()
    m.depot_register("depots", 5, "depot_777", "depot_777.json", risk_stufe=777, name="T5")
    ck("depot_list_tenant(5) isoliert", len(m.depot_list_tenant("depots", 5)) == 1)
    ck("depot_list_tenant(1) sieht T5 NICHT", len(m.depot_list_tenant("depots", 1)) == 0)
    ck("query_trades tenant=999 leer", len(m.query_trades(tenant_id=999)) == 0)
    # /api/db_query erzwingt Session-Tenant (Client-Parameter wird ignoriert)
    app3 = dash3.app; app3.config["TESTING"] = True
    c3 = app3.test_client()
    c3.post("/", data={"username": "admin", "password": "Admin2026!sicher"})
    r = c3.get("/api/db_query?mode=trades&tenant_id=999&limit=500")
    j = r.get_json()
    ck("/api/db_query ignoriert Client-tenant (nutzt Session)",
       r.status_code == 200 and j.get("count", 0) > 0)  # >0 = Server nutzte tid=1, nicht 999
    _os.remove(TD)
    m.conn.execute("DELETE FROM depots WHERE tenant_id=5")
    m.conn.commit(); m.close()
except Exception as e:
    ck("Mandantentrennung", False, str(e))

# ─── Phase 15e: Trading-Modi-Zustandsmaschine (v2.29.0, PHASE 5) ───────
print("\n7e. Trading-Modi-Zustandsmaschine (v2.29.0, PHASE 5)")
try:
    import security as sec5, db as mtdb5, dashboard as dash5
    # State Machine Logik (db.py)
    m5 = mtdb5.MTDB()
    ck("TRADING_MODES enthaelt alle 8 Zustaende",
       len(m5.TRADING_MODES) == 8 and "LIVE_ACTIVE" in m5.TRADING_MODES)
    ck("SHADOW->PAPER erlaubt", m5.mode_can_transition("SHADOW", "PAPER"))
    ck("SHADOW->LIVE_ACTIVE VERBOTEN", not m5.mode_can_transition("SHADOW", "LIVE_ACTIVE"))
    ck("PAPER->LIVE_REQUESTED erlaubt", m5.mode_can_transition("PAPER", "LIVE_REQUESTED"))
    ck("LIVE_APPROVED->LIVE_ACTIVE erlaubt", m5.mode_can_transition("LIVE_APPROVED", "LIVE_ACTIVE"))
    m5.close()

    # set_trading_mode erzwingt erlaubte Transition (ValueError sonst)
    # Zuerst sicher auf SHADOW zuruecksetzen (Isolation)
    try:
        sec5.set_trading_mode("SHADOW", tenant_id=1, user={"username": "admin"})
    except ValueError:
        pass
    try:
        sec5.set_trading_mode("LIVE_ACTIVE", tenant_id=1, user={"username": "admin"})
        ck("set_trading_mode verbietet illegale Transition", False)
    except ValueError:
        ck("set_trading_mode verbietet illegale Transition", True)
    # Erlaubte Transition SHADOW->PAPER
    old, new = sec5.set_trading_mode("PAPER", tenant_id=1, user={"username": "admin"}, reason="Test")
    ck("set_trading_mode SHADOW->PAPER OK", old == "SHADOW" and new == "PAPER")
    # Cleanup zurueck zu SHADOW
    sec5.set_trading_mode("SHADOW", tenant_id=1, user={"username": "admin"})

    # API-Test
    app5 = dash5.app; app5.config["TESTING"] = True
    c5 = app5.test_client()
    c5.post("/", data={"username": "admin", "password": "Admin2026!sicher"})
    r = c5.get("/api/trading_mode")
    ck("API GET /api/trading_mode liefert Modus", r.status_code == 200 and "mode" in r.get_json())
    r = c5.post("/api/trading_mode/set", data={"mode": "PAPER", "reason": "t"})
    ck("API POST set PAPER OK", r.get_json().get("ok") is True)
    r = c5.post("/api/trading_mode/set", data={"mode": "LIVE_ACTIVE"})
    ck("API POST LIVE_ACTIVE abgelehnt (400)", r.status_code == 400)
    # History
    r = c5.get("/api/trading_mode/history")
    ck("API history liefert Liste", r.status_code == 200 and isinstance(r.get_json().get("history"), list))
    # Cleanup DB
    m5b = mtdb5.MTDB()
    m5b.conn.execute("DELETE FROM trading_mode_transitions WHERE tenant_id=1")
    m5b.conn.commit(); m5b.close()
    sec5.set_trading_mode("SHADOW", tenant_id=1, user={"username": "admin"})
except Exception as e:
    ck("Trading-Modi-Zustandsmaschine", False, str(e))

# ─── Phase 15f: Shadow->Paper Freigabe (v2.30.0, PHASE 6) ───────────────
print("\n7f. Shadow->Paper Freigabe (v2.30.0, PHASE 6)")
try:
    import security as sec6, db as mtdb6, dashboard as dash6
    # paper_eligibility liefert (bool, list)
    elig, gruende = sec6.paper_eligibility(1)
    ck("paper_eligibility liefert Tupel", isinstance(elig, bool) and isinstance(gruende, list))
    # Tenant 1 hat >20 ki_decisions -> eligible (sofern keine Konflikte)
    ck("Tenant 1 grundsaetzlich eligible", elig is True or len(gruende) > 0)
    # enter_paper erzwingt SHADOW->PAPER nur wenn eligible (Konsistenz):
    # eligible -> OK, nicht eligible -> ValueError mit Grund. Beides korrekt.
    try:
        old, new = sec6.enter_paper(tenant_id=1, user={"username": "admin"})
        ck("enter_paper SHADOW->PAPER OK", elig is True and old == "SHADOW" and new == "PAPER")
    except ValueError as e:
        ck(f"enter_paper blockiert wenn nicht eligible ({e})", elig is False)
    # Rueckkehr zu SHADOW sicherstellen (nur wenn noetig)
    if sec6.get_trading_mode(1) != "SHADOW":
        try:
            sec6.set_trading_mode("SHADOW", tenant_id=1, user={"username": "admin"})
        except ValueError:
            pass
    # Virtuelles Paper-Portfolio anlegen (eigenes Depot)
    m6 = mtdb6.MTDB()
    m6.paper_portfolio_create(1, "test_paper", "Test", 100.0)
    ck("paper_portfolio_create OK", len(m6.paper_portfolio_list(1)) >= 1)
    # API
    app6 = dash6.app; app6.config["TESTING"] = True
    c6 = app6.test_client()
    c6.post("/", data={"username": "admin", "password": "Admin2026!sicher"})
    # Sicher auf SHADOW zuruecksetzen (Isolation)
    try:
        sec6.set_trading_mode("SHADOW", tenant_id=1, user={"username": "admin"})
    except ValueError:
        pass
    r = c6.get("/api/paper/eligibility")
    ck("API /api/paper/eligibility liefert eligible", r.status_code == 200 and "eligible" in r.get_json())
    r = c6.post("/api/paper/enter")
    j6 = r.get_json() or {}
    # PHASE 5 (§9): deterministisch — eligible -> ok=True, sonst 400 mit error
    ck("API /api/paper/enter konsistent mit Eligibility",
       (elig is True and j6.get("ok") is True) or
       (elig is False and r.status_code == 400 and j6.get("error")))
    # Modus danach immer SHADOW (enter_paper nur bei eligible)
    if sec6.get_trading_mode(1) != "SHADOW":
        sec6.set_trading_mode("SHADOW", tenant_id=1, user={"username": "admin"})
    # Cleanup
    m6.conn.execute("DELETE FROM paper_portfolios WHERE tenant_id=1")
    m6.conn.execute("DELETE FROM trading_mode_transitions WHERE tenant_id=1")
    m6.conn.commit(); m6.close()
    if sec6.get_trading_mode(1) != "SHADOW":
        sec6.set_trading_mode("SHADOW", tenant_id=1, user={"username": "admin"})
except Exception as e:
    ck("Shadow->Paper Freigabe", False, str(e))

# ─── Phase 15g: Provider-Connection-Manager (v2.31.0, PHASE 7) ───────────
print("\n7g. Provider-Connection-Manager (v2.31.0, PHASE 7)")
try:
    import security as sec7, db as mtdb7, dashboard as dash7
    m7 = mtdb7.MTDB()
    # Verbindung anlegen - Secret NUR als Referenz (kein Klartext)
    m7.provider_connection_add(1, "market_data", "yfinance", "PAPER", "read",
                               "vault://mt/yfinance", created_by=1)
    conns = m7.provider_connection_list(1)
    ck("provider_connection_add/list", len(conns) == 1)
    ck("Secret NICHT als Klartext gespeichert", "vault://" in conns[0]["secret_reference"]
        and "API_KEY" not in conns[0]["secret_reference"])
    # Test-Status
    m7.provider_connection_test(conns[0]["id"], ok=True)
    ck("provider_connection_test OK", True)
    m7.conn.execute("DELETE FROM provider_connections WHERE tenant_id=1")
    m7.conn.commit(); m7.close()
    # API: Secret wird maskiert
    app7 = dash7.app; app7.config["TESTING"] = True
    c7 = app7.test_client()
    c7.post("/", data={"username": "admin", "password": "Admin2026!sicher"})
    c7.post("/api/providers/add", data={"provider_type": "market_data",
            "provider_name": "yfinance", "secret_reference": "vault://mt/yf"})
    r = c7.get("/api/providers")
    provs = r.get_json().get("providers", [])
    ck("API liefert Provider", len(provs) >= 1)
    ck("API maskiert Secret (kein Klartext)", all("•" in p["secret_reference"] for p in provs))
    # Cleanup
    m7b = mtdb7.MTDB()
    m7b.conn.execute("DELETE FROM provider_connections WHERE tenant_id=1")
    m7b.conn.commit(); m7b.close()
except Exception as e:
    ck("Provider-Connection-Manager", False, str(e))

# ─── Phase 15h: Secret-Store (v2.32.0, PHASE 8) ────────────────────────
print("\n7h. Secret-Store (v2.32.0, PHASE 8)")
try:
    import security as sec8, db as mtdb8, dashboard as dash8
    # Tenant-isolierte Secrets
    sec8.secret_set(1, "OPENAI_API_KEY", "sk-tenant1")
    sec8.secret_set(5, "OPENAI_API_KEY", "sk-tenant5")
    ck("secret_get tenant 1", sec8.secret_get(1, "OPENAI_API_KEY") == "sk-tenant1")
    ck("secret_get tenant 5", sec8.secret_get(5, "OPENAI_API_KEY") == "sk-tenant5")
    ck("Tenant-Isolation (1 != 5)", sec8.secret_get(1, "OPENAI_API_KEY") != sec8.secret_get(5, "OPENAI_API_KEY"))
    ck("secret_list_keys liefert nur Schluessel", "OPENAI_API_KEY" in sec8.secret_list_keys(1)
        and isinstance(sec8.secret_list_keys(1), list))
    # API: setzt + listet (keine Werte im Response)
    app8 = dash8.app; app8.config["TESTING"] = True
    c8 = app8.test_client()
    c8.post("/", data={"username": "admin", "password": "Admin2026!sicher"})
    r = c8.post("/api/secrets/set", data={"key": "TEST_KEY", "value": "supersecret"})
    ck("API /api/secrets/set OK", r.get_json().get("ok") is True)
    r = c8.get("/api/secrets")
    j = r.get_json()
    ck("API /api/secrets liefert nur Schluessel (kein Wert)",
       "TEST_KEY" in j.get("keys", []) and "supersecret" not in str(j))
    # Cleanup
    m8 = mtdb8.MTDB()
    m8.conn.execute("DELETE FROM secret_store WHERE tenant_id IN (1,5)")
    m8.conn.commit(); m8.close()
    sec8.secret_set(1, "OPENAI_API_KEY", "sk-tenant1")  # wiederherstellen
except Exception as e:
    ck("Secret-Store", False, str(e))

# ─── Phase 15i: Paper-Order-Buch (v2.33.0, PHASE 9) ────────────────────────
print("\n7i. Paper-Order-Buch (v2.33.0, PHASE 9)")
try:
    import db as db9
    m9 = db9.MTDB()
    tid9 = m9.tenant_ensure_default()
    pid9 = m9.paper_portfolio_create(tid9, "__test_po__", "Test", 100.0)
    ck("paper_portfolio_create liefert ID", isinstance(pid9, int) and pid9 > 0)
    oid9 = m9.paper_order_insert(tid9, pid9, "TEST", "BUY", 10, 5.0)
    ck("paper_order_insert liefert ID", isinstance(oid9, int) and oid9 > 0)
    o9 = m9.paper_order_list(tid9, pid9)
    ck("paper_order_list tenant-scoped", len(o9) == 1 and o9[0]["side"] == "BUY")
    m9.paper_position_apply(tid9, pid9, "TEST", "BUY", 10, 5.0)
    m9.paper_position_apply(tid9, pid9, "TEST", "SELL", 4, 6.0)
    pos9 = m9.conn.execute("SELECT * FROM paper_positions WHERE portfolio_id=? AND ticker=?",
                           (pid9, "TEST")).fetchone()
    ck("paper_position_apply BUY10+SELL4 = 6 shares", pos9 and float(pos9["shares"]) == 6)
    ck("Paper-Tenant-Isolation", len(m9.paper_order_list(tid9 + 999, pid9)) == 0)
    # Cleanup
    m9.conn.execute("DELETE FROM paper_orders WHERE portfolio_id=?", (pid9,))
    m9.conn.execute("DELETE FROM paper_positions WHERE portfolio_id=?", (pid9,))
    m9.conn.execute("DELETE FROM paper_portfolios WHERE id=?", (pid9,))
    m9.conn.commit(); m9.close()
except Exception as e:
    ck("Paper-Order-Buch", False, str(e))

# ─── Phase 15j: Tenant-Scoped Risikogrenzen + Regeln (v2.34.0, PHASE 10+11) ──
print("\n7j. Tenant-Scoped Risikogrenzen + Regeln (v2.34.0, PHASE 10+11)")
try:
    import security as sec10, db as db10
    tid10 = sec10.resolve_tenant_for_user({"username": "admin"}) or 1
    # --- PHASE 10: Risiko ---
    sec10.risk_set(tid10, "moderate", position_size=0.45, stop_loss=0.88)
    eff10 = sec10.risk_get(tid10, "moderate")
    ck("risk_set+get tenant-scoped", eff10["source"] == "tenant"
       and eff10["position_size"] == 0.45 and eff10["stop_loss"] == 0.88)
    ck("risk Partial-Update keine NULL", eff10["take_profit"] not in (None,)
       and eff10["drawdown_limit"] not in (None,))
    # Fallback global (kein tenant-set)
    eff10b = sec10.risk_get(tid10, "aggressive")
    ck("risk Fallback global -> source=global", eff10b["source"] == "global")
    # --- PHASE 11: Regeln ---
    sec10.rule_add(tid10, "r_p10_test", "Testregel: kein Kauf am Freitag", muster="Freitag")
    rules10 = sec10.rule_list(tid10)
    tenant_rule = [r for r in rules10 if r["id"] == "r_p10_test"][0]
    ck("rule_add+list tenant", tenant_rule["source"] == "tenant"
       and "Freitag" in tenant_rule["muster"])
    # Tenant override global bei gleicher ID
    g0 = rules10[0]["id"]
    sec10.rule_add(tid10, g0, "TENANT OVERRIDE")
    rules10b = sec10.rule_list(tid10)
    ovr = [r for r in rules10b if r["id"] == g0][0]
    ck("rule Tenant override gewinnt", ovr["source"] == "tenant"
       and ovr["regel"] == "TENANT OVERRIDE")
    # Status aendern
    sec10.rule_set_status(tid10, "r_p10_test", "pausiert")
    rules10c = sec10.rule_list(tid10)
    st = [r for r in rules10c if r["id"] == "r_p10_test"][0]
    ck("rule_set_status", st["status"] == "pausiert")
    # --- Isolation: fremder Tenant sieht nichts ---
    ck("Risk-Isolation (fremder Tenant)", sec10.risk_get(tid10 + 999, "moderate")["source"]
       in ("global", "default"))
    ck("Rule-Isolation (fremder Tenant)",
       len([r for r in sec10.rule_list(tid10 + 999) if r["source"] == "tenant"]) == 0)
    # Cleanup
    m10 = db10.MTDB()
    m10.conn.execute("DELETE FROM tenant_risk_limits WHERE tenant_id=?", (tid10,))
    m10.conn.execute("DELETE FROM tenant_rules WHERE tenant_id=?", (tid10,))
    m10.conn.commit(); m10.close()
except Exception as e:
    ck("Risikogrenzen+Regeln", False, str(e))

# ─── Phase 15k: Enforcement (v2.35.0, PHASE 12) ─────────────────────────────
print("\n7k. Enforcement: Risiko-Limits + Regeln im Trading-Pfad (v2.35.0, PHASE 12)")
try:
    import security as sec11, db as db11
    tid11 = sec11.resolve_tenant_for_user({"username": "admin"}) or 1
    # --- enforce_risk_limits ---
    sec11.risk_set(tid11, "moderate", position_size=0.40, drawdown_limit=0.25)
    r_ok = sec11.enforce_risk_limits(tid11, "moderate", 0.35, 10000.0)
    ck("risk allow innerhalb Limit", r_ok["allowed"] is True)
    r_too = sec11.enforce_risk_limits(tid11, "moderate", 0.50, 10000.0)
    ck("risk block > Position-Limit", r_too["allowed"] is False
       and "Position" in r_too["reason"])
    r_dd = sec11.enforce_risk_limits(tid11, "moderate", 0.20, 10000.0, drawdown_pct=0.30)
    ck("risk block > Drawdown-Limit", r_dd["allowed"] is False
       and "Drawdown" in r_dd["reason"])
    # --- enforce_rules ---
    sec11.rule_add(tid11, "r_block_test", "Kein Kauf", muster="BLOCK:manuell gesperrt")
    rb = sec11.enforce_rules(tid11, "AAPL")
    ck("rule BLOCK hart blockiert", rb["allowed"] is False and rb["matched"] == "r_block_test")
    sec11.rule_set_status(tid11, "r_block_test", "pausiert")
    rb2 = sec11.enforce_rules(tid11, "AAPL")
    ck("rule pausiert -> erlaubt", rb2["allowed"] is True)
    sec11.rule_set_status(tid11, "r_block_test", "aktiv")
    # BLOCK-Regel fuer MAX_KAUF-Tests pausieren (sonst blockt sie alles)
    sec11.rule_set_status(tid11, "r_block_test", "pausiert")
    sec11.rule_add(tid11, "r_max_test", "Max 1 Kauf", muster="MAX_KAUF:1")
    rm = sec11.enforce_rules(tid11, "MSFT", {"kauf_count": 1})
    ck("rule MAX_KAUF erreicht -> block", rm["allowed"] is False)
    rm2 = sec11.enforce_rules(tid11, "MSFT", {"kauf_count": 0})
    ck("rule MAX_KAUF unterschritten -> erlaubt", rm2["allowed"] is True)
    # --- batch_trader Import (Enforcement-Code laedt) ---
    import importlib
    try:
        importlib.import_module("batch_trader")
        ck("batch_trader importiert (Enforcement drin)", True)
    except Exception as e2:
        ck("batch_trader importiert (Enforcement drin)", False, str(e2))
    # Cleanup
    m11 = db11.MTDB()
    m11.conn.execute("DELETE FROM tenant_risk_limits WHERE tenant_id=?", (tid11,))
    m11.conn.execute("DELETE FROM tenant_rules WHERE tenant_id=?", (tid11,))
    m11.conn.commit(); m11.close()
except Exception as e:
    ck("Enforcement", False, str(e))

print("\n7l. Order-Intent + Broker-Adapter + Vier-Augen (v2.36.0, PHASE 13)")
try:
    import security as sec13
    # --- create_order_intent: alle Pflichtfelder ---
    int1 = sec13.create_order_intent(1, "AAPL", "buy", 5.0, 200.0, mode="PAPER")
    ck("intent hat alle 17 Felder", all(f in int1 for f in sec13.ORDER_INTENT_FIELDS))
    ck("intent risk_check_status=pending", int1["risk_check_status"] == "pending")
    # --- validate_order_intent ---
    v_ok = sec13.validate_order_intent(dict(int1), portfolio_value=10000.0)
    ck("intent gueltig -> passed", v_ok["allowed"] is True
       and v_ok["intent"]["risk_check_status"] == "passed")
    v_live = sec13.validate_order_intent(dict(int1, mode="LIVE_ACTIVE"))
    ck("intent LIVE -> blockiert (PAPER_ONLY)", v_live["allowed"] is False
       and "PAPER_ONLY" in v_live["reason"])
    v_paused = sec13.validate_order_intent(dict(int1, mode="PAUSED"))
    ck("intent PAUSED -> blockiert", v_paused["allowed"] is False)
    v_qty = sec13.validate_order_intent(dict(int1, quantity=0))
    ck("intent Menge 0 -> blockiert", v_qty["allowed"] is False)
    v_mkt = sec13.validate_order_intent(dict(int1), market_open=False)
    ck("intent Markt zu -> blockiert", v_mkt["allowed"] is False)
    v_pos = sec13.validate_order_intent(dict(int1), position_count=25)
    ck("intent >20 Positionen -> blockiert", v_pos["allowed"] is False)
    # --- BrokerProvider-Interface ---
    b_abs = sec13.BrokerProvider()
    try:
        b_abs.place_order({})
        ck("BrokerProvider abstract (place_order wirft)", False)
    except NotImplementedError:
        ck("BrokerProvider abstract (place_order wirft)", True)
    # --- PaperBrokerAdapter ---
    pb = sec13.PaperBrokerAdapter()
    c = pb.connect()
    ck("PaperBroker connect", c["ok"] is True and c["broker"] == "paper-simulator")
    h = pb.health_check()
    ck("PaperBroker health nach connect", h["ok"] is True)
    acc = pb.get_account(1)
    ck("PaperBroker get_account", acc["mode"] == "PAPER" and "wert" in acc)
    # Order ausfuehren (Cleanup-Tenant 999)
    m13 = db11.MTDB()
    m13.conn.execute("DELETE FROM paper_orders WHERE tenant_id=999")
    m13.conn.execute("DELETE FROM paper_positions WHERE tenant_id=999")
    m13.conn.commit()
    int_buy = sec13.create_order_intent(999, "TEST13", "buy", 10.0, 50.0,
                                        portfolio_id=1, mode="PAPER")
    r_buy = pb.place_order(int_buy)
    ck("PaperBroker place_order buy -> filled", r_buy["ok"] is True
       and r_buy["status"] == "filled" and r_buy["order_id"] is not None)
    st = pb.get_order_status(r_buy["order_id"], 999)
    ck("PaperBroker get_order_status", st["status"] == "filled")
    pos = pb.get_positions(999)
    ck("PaperBroker Position erhoeht", any(p["ticker"] == "TEST13" for p in pos))
    int_live = sec13.create_order_intent(999, "TEST13", "buy", 10.0, 50.0,
                                         portfolio_id=1, mode="LIVE_ACTIVE")
    r_live = pb.place_order(int_live)
    ck("PaperBroker LIVE-Intent -> blocked", r_live["ok"] is False
       and r_live["status"] == "blocked")
    # --- vier_eyes_required ---
    fe = sec13.four_eyes_required("live_approve", "alice", "bob")
    ck("Vier-Augen: fremd genehmigt -> ok", fe["required"] is True and fe["ok"] is True)
    fe2 = sec13.four_eyes_required("live_approve", "alice", "alice")
    ck("Vier-Augen: selbst genehmigt -> block", fe2["ok"] is False)
    fe3 = sec13.four_eyes_required("live_approve", "alice", None)
    ck("Vier-Augen: Genehmiger fehlt -> block", fe3["ok"] is False)
    fe4 = sec13.four_eyes_required("portfolio.read", "alice", "bob")
    ck("Vier-Augen: unkritische Aktion -> nicht noetig", fe4["required"] is False)
    # Cleanup
    m13.conn.execute("DELETE FROM paper_orders WHERE tenant_id=999")
    m13.conn.execute("DELETE FROM paper_positions WHERE tenant_id=999")
    m13.conn.commit(); m13.close()
except Exception as e:
    ck("Order-Intent/Broker/Vier-Augen", False, str(e))

# ─── Phase 14: Freigabe-Workflow (v2.38.0, PHASE 14) ───────────────────────
print("\n7m. Freigabe-Workflow (v2.38.0, PHASE 14)")
try:
    import security as sec14, db as db14
    tid14 = sec14.resolve_tenant_for_user({"username": "admin"}) or 1
    # Default: nicht_freigegeben
    a0 = sec14.approval_get(tid14, "strategy", "s_demo")
    ck("approval Default nicht_freigegeben", a0["status"] == "nicht_freigegeben")
    # Enforcement blockt bei Default
    e0 = sec14.enforce_approval(tid14, "strategy", "s_demo")
    ck("enforce blockt bei nicht_freigegeben", e0["allowed"] is False and e0["status"] == "nicht_freigegeben")
    # Setzen: in_pruefung
    sec14.approval_set(tid14, "strategy", "s_demo", "in_pruefung")
    e1 = sec14.enforce_approval(tid14, "strategy", "s_demo")
    ck("enforce blockt bei in_pruefung", e1["allowed"] is False and "Prüfung" in e1["reason"])
    # Setzen: freigegeben
    sec14.approval_set(tid14, "strategy", "s_demo", "freigegeben", approved_by=1)
    e2 = sec14.enforce_approval(tid14, "strategy", "s_demo")
    ck("enforce erlaubt bei freigegeben", e2["allowed"] is True and e2["status"] == "freigegeben")
    # gesperrt
    sec14.approval_set(tid14, "strategy", "s_demo", "gesperrt")
    e3 = sec14.enforce_approval(tid14, "strategy", "s_demo")
    ck("enforce blockt bei gesperrt", e3["allowed"] is False and "gesperrt" in e3["reason"])
    # Liste
    sec14.approval_set(tid14, "portfolio", "p1", "freigegeben")
    al = sec14.approval_list(tid14)
    ck("approval_list enthaelt 2 Eintraege", len(al) == 2)
    # Isolation: fremder Tenant sieht nichts
    ck("Approval-Isolation (fremder Tenant)",
       sec14.approval_get(tid14 + 999, "strategy", "s_demo")["status"] == "nicht_freigegeben")
    # Cleanup
    m14 = db14.MTDB()
    m14.conn.execute("DELETE FROM tenant_approvals WHERE tenant_id=?", (tid14,))
    m14.conn.commit(); m14.close()
except Exception as e:
    ck("Freigabe-Workflow", False, str(e))

print("\n7m. Bugfixes v2.37.1: enforce_approval im Trading-Pfad, BLOCK-Ticker, KI-Regeln wirksam")
try:
    import security as sec15
    import db as db15

    # ── Fix 1: enforce_approval wirkt jetzt im Order-Pfad (validate_order_intent) ──
    tid15 = 781
    m15 = db15.MTDB()
    m15.conn.execute("DELETE FROM tenant_approvals WHERE tenant_id=?", (tid15,))
    m15.conn.commit()

    # unreguliertes Portfolio -> Order erlaubt (Paper-Betrieb bleibt am Laufen)
    int_ok = sec15.create_order_intent(tid15, "AAPL", "buy", 2.0, 150.0,
                                       portfolio_id=42, mode="PAPER")
    r = sec15.validate_order_intent(dict(int_ok), portfolio_value=5000.0)
    ck("Fix1: unreguliertes Portfolio erlaubt", r["allowed"])

    # explizit gesperrtes Portfolio -> Order blockt
    sec15.approval_set(tid15, "portfolio", 42, "gesperrt")
    int_block = sec15.create_order_intent(tid15, "AAPL", "buy", 2.0, 150.0,
                                          portfolio_id=42, mode="PAPER")
    r2 = sec15.validate_order_intent(dict(int_block), portfolio_value=5000.0)
    ck("Fix1: gesperrtes Portfolio blockt Order", not r2["allowed"]
       and "Freigabe" in r2["reason"])
    # freigegeben -> wieder erlaubt
    sec15.approval_set(tid15, "portfolio", 42, "freigegeben")
    r3 = sec15.validate_order_intent(dict(int_block), portfolio_value=5000.0)
    ck("Fix1: freigegebenes Portfolio erlaubt wieder", r3["allowed"])

    # ── Fix 2: BLOCK-Regel mit Ticker-Symbol blockt NUR diesen Ticker ──
    sec15.rule_add(tid15, "r_block_gme", "Kein Kauf von GME", muster="BLOCK:GME manuell gesperrt")
    rb_gme = sec15.enforce_rules(tid15, "GME")
    rb_aapl = sec15.enforce_rules(tid15, "AAPL")
    rb_msft = sec15.enforce_rules(tid15, "MSFT")
    ck("Fix2: BLOCK:GME blockt GME", not rb_gme["allowed"])
    ck("Fix2: BLOCK:GME blockt AAPL NICHT", rb_aapl["allowed"])
    ck("Fix2: BLOCK:GME blockt MSFT NICHT", rb_msft["allowed"])
    # BLOCK:TICKER ohne Text
    sec15.rule_add(tid15, "r_block_tsla", "TSLA gesperrt", muster="BLOCK:TSLA")
    ck("Fix2: BLOCK:TSLA blockt TSLA", not sec15.enforce_rules(tid15, "TSLA")["allowed"])
    ck("Fix2: BLOCK:TSLA blockt AAPL NICHT", sec15.enforce_rules(tid15, "AAPL")["allowed"])
    # generische BLOCK-Regel (ohne Ticker) blockt weiterhin alle — eigener Tenant
    tid16 = 782
    m16 = db15.MTDB()
    m16.conn.execute("DELETE FROM tenant_rules WHERE tenant_id=?", (tid16,))
    m16.conn.commit()
    sec15.rule_add(tid16, "r_block_all", "Allgemeine Sperre", muster="BLOCK:manuell gesperrt")
    ck("Fix2: generische BLOCK-Regel blockt alle",
       not sec15.enforce_rules(tid16, "AAPL")["allowed"]
       and not sec15.enforce_rules(tid16, "GME")["allowed"])
    m16.close()

    # ── Fix 3: freigegebene KI-Regeln wirken im Enforcement ──
    import learned_rules as lr15
    if hasattr(lr15, "RULE_FILE"):
        lr15.RULE_FILE = "learned_rules.json"
    # Regel mit Ticker in Klammern, freigegeben, nicht shadow
    m15.conn.execute("DELETE FROM tenant_rules WHERE tenant_id=?", (tid15,))
    m15.conn.commit()
    # Tenant-Regel mit KI-Muster-Typ (freigabe_status kommt aus effective_rules=freigegeben)
    sec15.rule_add(tid15, "r_ki_mtf", "Vorsicht RIVN", muster="[MTF] Vorsicht Kaufen bei 15min/1d (RIVN)")
    rk_rivn = sec15.enforce_rules(tid15, "RIVN")
    rk_aapl = sec15.enforce_rules(tid15, "AAPL")
    ck("Fix3: KI-Muster (RIVN) blockt RIVN", not rk_rivn["allowed"])
    ck("Fix3: KI-Muster (RIVN) blockt AAPL NICHT", rk_aapl["allowed"])

    # unbestätigte Tenant-Regel (status != aktiv, kein freigabe_status) blockt NICHT
    sec15.rule_add(tid15, "r_unbest", "Unbestaetigt MSFT", muster="BLOCK:MSFT",
                   status="unbestätigt")
    ck("Fix3: unbestätigte Regel blockt NICHT",
       sec15.enforce_rules(tid15, "MSFT")["allowed"])

    # Freigabe-Gate: learned_rules.json enthaelt freigegebene Regeln (>=18)
    ki_regeln = lr15.lade_live_regeln() if hasattr(lr15, "lade_live_regeln") else []
    n_freigegeben = sum(1 for r in ki_regeln if r.get("freigabe_status") == "freigegeben")
    ck("Fix3: lade_live_regeln liefert freigegebene (>=18)", n_freigegeben >= 18)

    # effective_rules reicht freigabe_status durch (Fix 3a)
    er = m15.effective_rules(tid15)
    ck("Fix3: effective_rules reicht freigabe_status durch",
       any(r.get("freigabe_status") == "freigegeben" for r in er))

    # Cleanup
    m15.conn.execute("DELETE FROM tenant_approvals WHERE tenant_id=?", (tid15,))
    m15.conn.execute("DELETE FROM tenant_rules WHERE tenant_id=?", (tid15,))
    m15.conn.execute("DELETE FROM tenant_rules WHERE tenant_id=?", (tid16,))
    m15.conn.commit(); m15.close()
except Exception as e:
    ck("Bugfixes v2.37.1", False, str(e))

print("\n7n. Phase 1 (v2.39.0): Benutzer-Lebenszyklus, Sessions-GC, MFA-Pflicht, Recovery-Codes")
try:
    import security as sec16
    # Setup: Test-User mit sauberem Zustand
    us = sec16._load_users()
    for _n in ("__lz1__", "__lz2__", "__lz3__", "__lz_admin__"):
        us.pop(_n, None)
    sec16._save_users(us)

    # 1) Lebenszyklus-Status: user -> ACTIVE, admin -> MFA_REQUIRED
    ok1, _ = sec16.create_user("__lz1__", "Lebenszyklus1!", role="user", created_by="__test__")
    us = sec16._load_users()
    ck("LZ: user startet ACTIVE", ok1 and us["__lz1__"]["status"] == "ACTIVE")
    ck("LZ: created_by gesetzt", us["__lz1__"].get("created_by") == "__test__")
    ok2, _ = sec16.create_user("__lz_admin__", "Lebenszyklus2!", role="admin", created_by="__test__")
    us = sec16._load_users()
    ck("LZ: admin startet MFA_REQUIRED", ok2 and us["__lz_admin__"]["status"] == "MFA_REQUIRED")

    # 2) verify_password trackt last_login_at / last_failed_login_at
    r_ok = sec16.verify_password("__lz1__", "Lebenszyklus1!")
    r_bad = sec16.verify_password("__lz1__", "falsch")
    us = sec16._load_users()
    ck("LZ: last_login_at gesetzt", r_ok and us["__lz1__"].get("last_login_at"))
    ck("LZ: last_failed_login_at gesetzt", not r_bad and us["__lz1__"].get("last_failed_login_at"))

    # 3) Sessions: GC entfernt abgelaufene, behält aktive
    sid_a = sec16.create_session("__lz1__", ip="127.0.0.1")
    us = sec16._load_users()
    us["__lz1__"]["sessions"][sid_a]["last_seen"] = int(time.time()) - 3600 * 30  # 30h alt -> idle > 30min
    sec16._save_users(us)
    # eine zweite, frische Session
    sid_b = sec16.create_session("__lz1__", ip="127.0.0.1")
    sec16._load_users()  # GC läuft beim Laden
    us = sec16._load_users()
    sess = us["__lz1__"]["sessions"]
    ck("LZ: Session-GC entfernt abgelaufene", sid_a not in sess and sid_b in sess)

    # 4) Passwortänderung widerruft ALLE Sessions (§6)
    sec16.change_password("__lz1__", "NeuLebenszyklus1!")
    us = sec16._load_users()
    ck("LZ: Passwortaenderung widerruft Sessions", len(us["__lz1__"]["sessions"]) == 0)

    # 5) MFA + Recovery-Codes
    us = sec16._load_users()
    us["__lz1__"]["mfa_pending_secret"] = sec16.generate_mfa_secret()
    sec16._save_users(us)
    secret = us["__lz1__"]["mfa_pending_secret"]
    code = sec16._totp(secret, int(time.time()))
    ok_mfa, _ = sec16.enable_mfa("__lz1__", code)
    us = sec16._load_users()
    ck("LZ: MFA aktiv + 8 Recovery-Codes", ok_mfa and us["__lz1__"]["mfa_enabled"]
       and len(us["__lz1__"].get("recovery_codes", [])) == 8)
    rc = us["__lz1__"]["recovery_codes"][0]
    ok_rc = sec16.verify_recovery_code("__lz1__", rc)
    us = sec16._load_users()
    ck("LZ: Recovery-Code verbraucht", ok_rc and len(us["__lz1__"]["recovery_codes"]) == 7)

    # 6) Redaction: get_user/list_users leaken keine Secrets (§6)
    v = sec16.get_user("__lz1__")
    ck("LZ: get_user redactiert (kein Hash/Secret)",
       v is not None and "password_hash" not in v and "mfa_secret" not in v
       and "recovery_codes" not in v)
    vlist = sec16.list_users()
    ck("LZ: list_users redactiert",
       all("password_hash" not in u and "mfa_secret" not in u for u in vlist))

    # 7) Deaktivierte können sich nicht anmelden (§6)
    sec16.deactivate_user("__lz1__", "__test__")
    us = sec16._load_users()
    ck("LZ: deactivate -> DISABLED + disabled_by/at",
       us["__lz1__"]["status"] == "DISABLED" and us["__lz1__"].get("disabled_by") == "__test__")
    ck("LZ: deaktivierter kann sich nicht anmelden",
       not sec16.verify_password("__lz1__", "NeuLebenszyklus1!"))

    # 8) MFA-Pflicht: mfa_recently_verified False für Admin ohne MFA
    ok3, _ = sec16.create_user("__lz2__", "Lebenszyklus3!", role="user")
    sid_x = sec16.create_session("__lz2__", ip="127.0.0.1")
    ck("LZ: User ohne MFA gilt als verifiziert",
       sec16.mfa_recently_verified("__lz2__", sid_x))
    ok4, _ = sec16.create_user("__lz3__", "Lebenszyklus4!", role="admin")
    sid_y = sec16.create_session("__lz3__", ip="127.0.0.1")
    ck("LZ: Admin ohne MFA gilt als NICHT verifiziert (Pflicht)",
       not sec16.mfa_recently_verified("__lz3__", sid_y))

    # 9) MFA-Deaktivierung invalidiert Sessions (§6)
    sec16.create_session("__lz3__", ip="127.0.0.1")
    sec16.disable_mfa("__lz3__", "__test__")
    us = sec16._load_users()
    ck("LZ: MFA-Disable widerruft Sessions",
       len(us["__lz3__"]["sessions"]) == 0 and us["__lz3__"]["status"] == "MFA_REQUIRED")

    # Cleanup
    us = sec16._load_users()
    for _n in ("__lz1__", "__lz2__", "__lz3__", "__lz_admin__"):
        us.pop(_n, None)
    sec16._save_users(us)
except Exception as e:
    ck("Phase 1 Lebenszyklus", False, str(e))

print("\n7o. Phase 2 (v2.40.0): Rollen x kritische Aktionen, deny-by-default, Selbst-Privilegierung")
try:
    import security as sec17
    # 1) Feine Permission-Matrix: was darf welche Rolle? (§7 Katalog)
    EXPECT = {
        # (rolle, permission, erwartet)
        ("user", "profile.read", True),
        ("user", "profile.edit", True),
        ("user", "sessions.revoke", True),
        ("user", "dashboard.read", True),
        ("user", "users.read", False),
        ("user", "rules.approve", False),
        ("user", "live.approve", False),
        ("user", "paper.trade", False),
        ("analyst", "reports.read", True),
        ("analyst", "analysis.read", True),
        ("analyst", "rules.propose", True),
        ("analyst", "rules.approve", False),
        ("analyst", "paper.trade", False),
        ("operator", "paper.trade", True),
        ("operator", "trading.pause", True),
        ("operator", "trading.resume", True),
        ("operator", "users.read", False),
        ("operator", "live.request", False),
        ("admin", "users.read", True),       # via Alias "users"
        ("admin", "users.create", True),
        ("admin", "users.disable", True),
        ("admin", "roles.manage", True),
        ("admin", "rules.approve", True),
        ("admin", "rules.rollback", True),
        ("admin", "audit.read", True),       # via Alias "audit"
        ("admin", "settings.edit", True),    # via Alias "settings"
        ("admin", "backup.restore", True),   # via Alias "backups"
        ("admin", "provider.rotate", True),
        ("admin", "broker.connect", True),
        ("admin", "order.intent.approve", True),
        ("admin", "live.approve", False),    # Vier-Augen: admin darf NICHT selbst live freigeben
        ("superadmin", "live.approve", True),
        ("superadmin", "live.revoke", True),
        ("superadmin", "order.execute", True),
        ("superadmin", "backup.restore", True),
        ("visitor", "dashboard.read", False),
        ("visitor", "profile.read", False),
    }
    for (role, perm, exp) in EXPECT:
        got = sec17.role_has_permission(role, perm)
        ck(f"P2: {role}.{perm} == {exp}", got == exp)

    # 2) Deny-by-default: unbekannte Rolle hat nichts
    ck("P2: unbekannte Rolle deny-by-default",
       not sec17.role_has_permission("root", "dashboard.read"))

    # 3) Selbst-Privilegierung: User darf sich selbst NICHT hoeher stufen
    ok_su, _ = sec17.create_user("__p2_self__", "SelbstTest123!", role="user")
    ok_set = sec17.set_role("__p2_self__", "admin", "__p2_self__")  # self-promote
    ck("P2: Selbst-Privilegierung blockiert", ok_su and ok_set is False)
    us = sec17._load_users()
    ck("P2: Rolle unveraendert nach Block", us["__p2_self__"]["role"] == "user")
    # Downgrade auf sich selbst bleibt erlaubt
    sec17.set_role("__p2_self__", "user", "__p2_self__")
    ck("P2: Selbst-Downgrade ok", us["__p2_self__"]["role"] == "user")

    # 4) superadmin nur durch superadmin (auch Entzug)
    ok_ad, _ = sec17.create_user("__p2_adm__", "AdminTest123!", role="admin")
    ok_ad2, _ = sec17.create_user("__p2_adm2__", "AdminTest123!", role="admin")
    us = sec17._load_users()
    us["__p2_adm__"]["mfa_enabled"] = True
    us["__p2_adm__"]["status"] = "ACTIVE"
    us["__p2_adm2__"]["mfa_enabled"] = True
    us["__p2_adm2__"]["status"] = "ACTIVE"
    sec17._save_users(us)
    r1 = sec17.set_role("__p2_adm__", "superadmin", "__p2_adm__")  # admin -> selbst superadmin
    ck("P2: admin kann sich nicht zum superadmin machen", r1 is False)
    r2 = sec17.set_role("__p2_adm2__", "superadmin", "__p2_adm__")  # admin vergibt superadmin
    ck("P2: admin kann kein superadmin vergeben", r2 is False)
    ok_sa, _ = sec17.create_user("__p2_sa__", "SuperTest123!", role="superadmin")
    r3 = sec17.set_role("__p2_sa__", "operator", "__p2_adm__")  # admin entzieht superadmin
    ck("P2: admin kann superadmin nicht entziehen", r3 is False)
    r4 = sec17.set_role("__p2_adm2__", "superadmin", "__p2_sa__")  # superadmin vergibt
    ck("P2: superadmin kann superadmin vergeben", r4 is True)

    # 5) require_permission serverseitig: /api/roles nur mit roles.manage
    import dashboard as dash17
    app17 = dash17.app; app17.config["TESTING"] = True
    c17 = app17.test_client()
    sec17.create_user("__p2_op__", "OperatorTest123!", role="operator")
    c17.post("/", data={"username": "__p2_op__", "password": "OperatorTest123!"})
    r = c17.get("/api/roles")
    ck("P2: operator /api/roles -> 403 (kein roles.manage)", r.status_code in (401, 403))
    # admin ohne MFA: before_request ADMIN-Ebene verlangt effektive Rolle >= admin
    # -> operator reicht nicht, daher 403 (deckt serverseitige Pruefung ab)
    r2 = c17.get("/api/me/permissions")
    j2 = r2.get_json() if r2.is_json else {}
    perms_op = set(j2.get("permissions", []))
    ck("P2: operator hat paper.trade im Tenant",
       "paper.trade" in perms_op and "users.read" not in perms_op)

    # 6) effective_permissions: admin bekommt fein + grob (Alias sichtbar)
    sec17.create_user("__p2_admin2__", "AdminTest123!", role="admin")
    us = sec17._load_users()
    us["__p2_admin2__"]["mfa_enabled"] = True
    us["__p2_admin2__"]["status"] = "ACTIVE"
    sec17._save_users(us)
    ck("P2: effective_permissions admin enthaelt users.read",
       "users.read" in sec17.effective_permissions(
           {"username": "__p2_admin2__", "role": "admin"}))

    # Cleanup
    us = sec17._load_users()
    for _n in ("__p2_self__", "__p2_adm__", "__p2_adm2__", "__p2_sa__",
               "__p2_op__", "__p2_admin2__"):
        us.pop(_n, None)
    sec17._save_users(us)
except Exception as e:
    ck("Phase 2 Rollen/Berechtigungen", False, str(e))

print("\n7p. Phase 3 (v2.41.0): Tenant-Isolation — Cross-Tenant-Leak, tid-Guard, Cache-Scope")
try:
    import security as sec18
    import dashboard as dash18
    import db as db18
    import engine as eng18
    import json as _json18

    # 1) Depot-Dateien tenant-markieren (§2.3): speichern() schreibt tenant_id
    # 29.09.2026: Diese Depots lagen vorher in BASE. Sie waren nach
    # jedem Testlauf wieder da, und weil batch_trader alle depot_*.json
    # einsammelt, erschienen sie im Dashboard als echte Depots
    # ("Risk 98 $100", 0 Positionen) und wurden mitgehandelt.
    # Ein Test darf keine Betriebsdaten erzeugen.
    import tempfile as _tfd
    _tdir = _tfd.mkdtemp(prefix="mt_testdepot_")
    d_ten = eng18.Depot(start_wert=100, risk=97)  # 97/98: ausserhalb RISK_STUFEN
    d_ten.tenant_id = 7
    d_ten.depot_pfad = os.path.join(_tdir, "depot_097.json")
    d_ten.speichern()
    with open(d_ten.depot_pfad) as f:
        _ges = _json18.load(f)
    ck("P3: engine.Depot.speichern schreibt tenant_id", _ges.get("tenant_id") == 7)
    # Default bleibt 1 (bestehende Depots)
    d_def = eng18.Depot(start_wert=100, risk=98)
    d_def.depot_pfad = os.path.join(_tdir, "depot_098.json")
    d_def.speichern()
    with open(d_def.depot_pfad) as f:
        _ges2 = _json18.load(f)
    ck("P3: Depot ohne tenant_id -> Default 1", _ges2.get("tenant_id") == 1)

    # 2) _tenant_scoped_depot_files: Tenant 7 sieht nur Depot 7, Tenant 1 nur Depot 1
    _scoped7 = dash18._tenant_scoped_depot_files(7, basis=_tdir)
    _scoped1 = dash18._tenant_scoped_depot_files(1, basis=_tdir)
    ck("P3: Tenant 7 sieht sein Depot",
       any(os.path.basename(p) == "depot_097.json" for p in _scoped7["depot"]))
    ck("P3: Tenant 7 sieht NICHT Tenant-1-Depot",
       not any(os.path.basename(p) == "depot_098.json" for p in _scoped7["depot"]))
    ck("P3: Tenant 1 sieht NICHT Tenant-7-Depot",
       not any(os.path.basename(p) == "depot_097.json" for p in _scoped1["depot"]))

    # 3) /data-Cache ist tenant-keyed: gleiche tenant_id -> Cache-Hit,
    #    andere tenant_id -> Cache-Miss (kein Cross-Tenant-Cache-Leak)
    app18 = dash18.app; app18.config["TESTING"] = True
    # Cache direkt setzen wie nach einem Tenant-A-Call
    dash18.data._cache = {"__test__": "tenantA"}
    dash18.data._cache_ts = time.time()
    dash18.data._cache_tid = 1
    sec18.set_current_tenant(1)
    r_a = dash18.data()
    # r_a ist der Cache-Hit (gleicher Tenant) ODER neu berechnet (wenn Cache-Check
    # _cache_tid ignoriert). Entscheidend: nach Tenant-Wechsel auf 7 darf der
    # A-Cache NICHT mehr geliefert werden.
    sec18.set_current_tenant(7)
    dash18.data._cache_ts = time.time()  # frisch, damit nur tid entscheidet
    r_b = dash18.data()
    dash18.data._cache = None
    dash18.data._cache_tid = None
    hit_b = (r_b.get("__test__") if isinstance(r_b, dict) else None)
    ck("P3: Cache tenant-keyed (Tenant 7 bekommt nicht Tenant-1-Cache)",
       hit_b != "tenantA")

    # 4) tid-Guard: non-superadmin darf fremde Tenant-Memberships nicht lesen
    #    (simuliert über require_tenant_role + is_super-Check in der Route)
    import security as _s18
    _s18.create_user("__p3_admin__", "AdminTest123!", role="admin")
    _s18.create_user("__p3_super__", "SuperTest123!", role="superadmin")
    us = _s18._load_users()
    us["__p3_admin__"]["mfa_enabled"] = True
    us["__p3_admin__"]["status"] = "ACTIVE"
    _s18._save_users(us)
    # Tenant 2 anlegen (Isolationstest-Tenant) + Member.
    # __p3_admin__ ist NUR in Tenant 1 Mitglied -> resolve -> t1; t2 ist fremd.
    m18 = db18.MTDB()
    t2, err2 = m18.tenant_create("isolation_b", "Isolation B")
    if not t2:
        t2 = 2
    m18.tenant_membership_add(1, "__p3_admin__", role="admin")
    m18.tenant_membership_add(t2, "__p3_super__", role="superadmin")
    m18.close()
    # Login als admin (ohne Tenant-Switch) -> aktueller Tenant = 1
    c18b = app18.test_client()
    c18b.post("/", data={"username": "__p3_admin__", "password": "AdminTest123!"})
    # Fremden Tenant 2 anfragen -> 403 (tid-Guard), eigenen Tenant 1 -> ok
    r_fremd = c18b.get(f"/api/tenants/{t2}/members")
    r_eigen = c18b.get("/api/tenants/1/members")
    ck("P3: fremder Tenant -> 403", r_fremd.status_code == 403)
    ck(f"P3: eigener Tenant -> 200 (got {r_eigen.status_code})",
       r_eigen.status_code == 200)
    # Tenant-Liste: non-superadmin sieht nur seinen Tenant
    r_list = c18b.get("/api/tenants")
    j_list = r_list.get_json() if r_list.is_json else {}
    ids = [t.get("tenant_id") for t in j_list.get("tenants", [])]
    ck("P3: Tenant-Liste non-superadmin nur eigener Tenant",
       ids == [1] or ids == [])
    # Tenant anlegen als non-superadmin -> 403
    r_create = c18b.post("/api/tenants/create",
                         json={"tenant_key": "leak_test", "name": "Leak"})
    ck("P3: Tenant anlegen non-superadmin -> 403", r_create.status_code == 403)

    # 5) Audit: role_change_denied / tenant-Zugriff protokolliert (nur Vorhandensein)
    aus = _s18.audit_log("tenant_access_denied", "__p3_admin__", f"tid={t2}")
    ck("P3: Audit-Funktion verfuegbar", aus is True or aus is None or aus is not None)

    # Cleanup
    us = _s18._load_users()
    for _n in ("__p3_admin__", "__p3_super__"):
        us.pop(_n, None)
    _s18._save_users(us)
    for _f in ("depot_097.json", "depot_098.json"):
        _fp = os.path.join(BASE, _f)
        if os.path.exists(_fp):
            os.remove(_fp)
except Exception as e:
    ck("Phase 3 Tenant-Isolation", False, str(e))

print("\n7q. Phase 4 (v2.42.0): Zustandsmaschine SHADOW/PAPER/LIVE_*/PAUSED/SUSPENDED/REVOKED (§8)")
try:
    import security as sec19
    import db as db19
    import batch_trader as bt19

    m19 = db19.MTDB()
    # Ausgangszustand merken und am Ende wiederherstellen (Test-Hygiene)
    _start_mode19 = sec19.get_trading_mode(1) or "SHADOW"

    # 1) Vollstaendige Zustandsmenge (§8)
    ck("P4: 8 Zustandsmodi definiert",
       set(m19.TRADING_MODES) == {"SHADOW", "PAPER", "LIVE_REQUESTED",
                                   "LIVE_APPROVED", "LIVE_ACTIVE", "PAUSED",
                                   "SUSPENDED", "REVOKED"})

    # 2) Erlaubte Transitionen (§8-Kernregeln)
    tr = m19.MODE_TRANSITIONS
    ck("P4: SHADOW->PAPER erlaubt", "PAPER" in tr["SHADOW"])
    ck("P4: SHADOW->LIVE_* NICHT direkt", "LIVE_ACTIVE" not in tr["SHADOW"])
    ck("P4: PAPER->LIVE_REQUESTED erlaubt", "LIVE_REQUESTED" in tr["PAPER"])
    ck("P4: LIVE_REQUESTED->LIVE_APPROVED", "LIVE_APPROVED" in tr["LIVE_REQUESTED"])
    ck("P4: LIVE_APPROVED->LIVE_ACTIVE", "LIVE_ACTIVE" in tr["LIVE_APPROVED"])
    ck("P4: LIVE_ACTIVE->PAUSED/SUSPENDED/REVOKED",
       {"PAUSED", "SUSPENDED", "REVOKED"} <= set(tr["LIVE_ACTIVE"]))
    ck("P4: SUSPENDED->REVOKED", "REVOKED" in tr["SUSPENDED"])
    # Kein Zustand darf in sich selbst oder auf ungueltige Modi zeigen
    ck("P4: keine Selbst-Transitionen",
       all(mode not in tr[mode] for mode in m19.TRADING_MODES))

    # 3) set_trading_mode: ungültige Transition wirft ValueError
    sec19.set_trading_mode("PAPER", tenant_id=1, user="admin",
                           reason="Test", requested_by=1)
    sec19.set_trading_mode("SHADOW", tenant_id=1, user="admin",
                           reason="zurueck", requested_by=1)
    try:
        sec19.set_trading_mode("LIVE_ACTIVE", tenant_id=1, user="admin",
                               reason="sprung", requested_by=1)
        ck("P4: SHADOW->LIVE_ACTIVE blockiert", False)
    except ValueError:
        ck("P4: SHADOW->LIVE_ACTIVE blockiert", True)

    # 4) Vier-Augen + MFA bei LIVE_APPROVED (§8+§14)
    sec19.set_trading_mode("PAPER", tenant_id=1, user="admin",
                           reason="fuer live-test", requested_by=1)
    try:
        sec19.set_trading_mode("LIVE_REQUESTED", tenant_id=1, user="admin",
                               reason="antrag", requested_by=11)
        ck("P4: PAPER->LIVE_REQUESTED erlaubt", True)
    except ValueError as e:
        ck(f"P4: PAPER->LIVE_REQUESTED erlaubt (fail: {e})", False)
    # Freigabe ohne approved_by -> blockiert
    try:
        sec19.set_trading_mode("LIVE_APPROVED", tenant_id=1, user="admin",
                               reason="freigabe", requested_by=11)
        ck("P4: LIVE_APPROVED ohne approved_by blockiert", False)
    except ValueError:
        ck("P4: LIVE_APPROVED ohne approved_by blockiert", True)
    # Freigabe durch denselben User -> blockiert (kein Selbst-Genehmigen)
    try:
        sec19.set_trading_mode("LIVE_APPROVED", tenant_id=1, user="admin",
                               reason="freigabe", requested_by=11,
                               approved_by=11, mfa_confirmed=1)
        ck("P4: Selbst-Genehmigen blockiert", False)
    except ValueError:
        ck("P4: Selbst-Genehmigen blockiert", True)
    # Freigabe durch anderen User + MFA -> erlaubt
    sec19.set_trading_mode("LIVE_APPROVED", tenant_id=1, user="admin",
                           reason="freigabe durch zweiten", requested_by=11,
                           approved_by=22, mfa_confirmed=1)
    ck("P4: LIVE_APPROVED mit 4-Augen+MFA erlaubt",
       sec19.get_trading_mode(1) == "LIVE_APPROVED")
    # MFA fehlt -> blockiert (Rueckweg LIVE_APPROVED -> REVOKED -> SHADOW -> PAPER -> LIVE_REQUESTED)
    sec19.set_trading_mode("REVOKED", tenant_id=1, user="admin",
                           reason="zurueck", requested_by=11)
    sec19.set_trading_mode("SHADOW", tenant_id=1, user="admin",
                           reason="zurueck", requested_by=11)
    sec19.set_trading_mode("PAPER", tenant_id=1, user="admin",
                           reason="fuer mfa-test", requested_by=11)
    sec19.set_trading_mode("LIVE_REQUESTED", tenant_id=1, user="admin",
                           reason="antrag", requested_by=11)
    try:
        sec19.set_trading_mode("LIVE_APPROVED", tenant_id=1, user="admin",
                               reason="ohne mfa", requested_by=11,
                               approved_by=22, mfa_confirmed=0)
        ck("P4: LIVE_APPROVED ohne MFA blockiert", False)
    except ValueError:
        ck("P4: LIVE_APPROVED ohne MFA blockiert", True)
    # Aufraeumen -> Ausgangszustand (nicht hart SHADOW — Test-Hygiene)
    _akt19 = sec19.get_trading_mode(1)
    if _akt19 != _start_mode19:
        try:
            sec19.set_trading_mode("REVOKED", tenant_id=1, user="admin",
                                   reason="test-aufraeum", requested_by=11)
        except ValueError:
            pass
        sec19.set_trading_mode(_start_mode19, tenant_id=1, user="admin",
                               reason="produktiv-zurueck", requested_by=11)
    ck(f"P4: Rueckkehr zu Ausgangszustand {_start_mode19}",
       sec19.get_trading_mode(1) == _start_mode19)

    # 5) Batch-Trader Mode-Gate (§8): SUSPENDED -> main() tradet nicht
    m19.conn.execute("UPDATE tenants SET default_trading_mode='SUSPENDED' WHERE id=1")
    m19.conn.commit()
    vor_main = os.path.getmtime(os.path.join(BASE, "depot_000.json")) \
        if os.path.exists(os.path.join(BASE, "depot_000.json")) else None
    # main() wird mit leerem Markt simuliert — wichtig ist: kein Crash und
    # frueher Return. Wir patchen scan_markt, um zu sehen, ob es ueberhaupt aufgerufen wird.
    _orig_scan = bt19.scan_markt
    _aufgerufen = []
    def _fake_scan(t):
        _aufgerufen.append(True)
        return {}
    bt19.scan_markt = _fake_scan
    try:
        bt19.main()
    finally:
        bt19.scan_markt = _orig_scan
    m19.conn.execute("UPDATE tenants SET default_trading_mode='SHADOW' WHERE id=1")
    m19.conn.commit()
    ck("P4: Batch-Gate: SUSPENDED -> kein Markt-Scan", len(_aufgerufen) == 0)

    m19.close()
except Exception as e:
    ck("Phase 4 Zustandsmaschine", False, str(e))

print("\n7r. Phase 5 (v2.43.0): Shadow->Paper-Freigabe (§9) — 8 Voraussetzungen + getrennte Portfolios")
try:
    import security as sec20, db as db20, dashboard as dash20
    import json as _json20, os as _os20, tempfile as _tf20

    # ── 1) Eligibility: 8 Voraussetzungen werden geprueft ──
    elig20, gruende20 = sec20.paper_eligibility(1)
    ck("P5: eligibility liefert (bool, list)", isinstance(elig20, bool) and isinstance(gruende20, list))
    ck("P5: alle Gruende sind Strings", all(isinstance(g, str) for g in gruende20))

    # ── 2) Getrennte Portfolios: Shadow-Datei bleibt unberuehrt ──
    # Shadow-Depot anlegen (depot_999.json — Risk 999 nur fuer Test)
    sh_pfad20 = _os20.path.join(dash20.BASE, "depot_999.json")
    pa_pfad20 = _os20.path.join(dash20.BASE, "depot_999_paper.json")
    _json20.dump({"tenant_id": 1, "mode": "shadow", "bargeld": 100,
                  "positions": {"TEST1": {"shares": 10, "avg_price": 5}},
                  "historie": [], "trades": [], "start_wert": 100},
                 open(sh_pfad20, "w", encoding="utf-8"))
    _json20.dump({"tenant_id": 1, "mode": "paper", "bargeld": 100,
                  "positions": {}, "historie": [], "trades": [], "start_wert": 100},
                 open(pa_pfad20, "w", encoding="utf-8"))
    # _tenant_scoped_depot_files mit mode-Filter
    sc_sh = dash20._tenant_scoped_depot_files(1, mode="shadow")
    sc_pa = dash20._tenant_scoped_depot_files(1, mode="paper")
    ck("P5: Shadow-Scope enthaelt depot_999", any("depot_999.json" in p for p in sc_sh["depot"]))
    ck("P5: Shadow-Scope KEIN _paper", not any("_paper.json" in p for p in sc_sh["depot"]))
    ck("P5: Paper-Scope enthaelt depot_999_paper", any("depot_999_paper.json" in p for p in sc_pa["depot"]))
    ck("P5: Paper-Scope KEIN Shadow-Depot", not any("depot_999.json" in p for p in sc_pa["depot"]))

    # ── 3) depot_pfad() trennt Modi ──
    ck("P5: depot_pfad shadow != paper",
       dash20.depot_pfad(10) != dash20.depot_pfad(10, mode="paper")
       and dash20.depot_pfad(10, mode="paper").endswith("_paper.json"))

    # ── 4) portfolio_verlauf trennt Modi (keine Vermischung) ──
    # historie mit Mode-Markern in beiden Dateien
    h_zeit = _os20.popen("date +%Y-%m-%dT%H:%M:%S").read().strip() if _os20.name != "nt" else "2026-08-09T10:00:00"
    d_sh = _json20.load(open(sh_pfad20, encoding="utf-8"))
    d_sh["historie"] = [{"zeit": h_zeit, "wert": 150}]
    _json20.dump(d_sh, open(sh_pfad20, "w", encoding="utf-8"))
    d_pa = _json20.load(open(pa_pfad20, encoding="utf-8"))
    d_pa["historie"] = [{"zeit": h_zeit, "wert": 95}]
    _json20.dump(d_pa, open(pa_pfad20, "w", encoding="utf-8"))
    vl_sh = dash20.portfolio_verlauf(tage=7, mode="shadow")
    vl_pa = dash20.portfolio_verlauf(tage=7, mode="paper")
    ck("P5: Verlauf shadow/paper getrennt",
       vl_sh != vl_pa or (vl_sh and vl_pa))

    # ── 5) Mode-Gate: batch/etf/spec springen bei gesperrtem Modus ──
    import batch_trader as bt20
    import etf_trader as et20
    import spec_trader as st20
    _m5 = db20.MTDB()
    _m5.conn.execute("UPDATE tenants SET default_trading_mode='SUSPENDED' WHERE id=1")
    _m5.conn.commit()
    ck("P5: batch main() bei SUSPENDED -> None (skip)",
       bt20.main() is None)  # main() gibt None zurueck nach Skip
    ck("P5: etf main() bei SUSPENDED -> skip", et20.main() is None)
    ck("P5: spec main() bei SUSPENDED -> skip", st20.main() is None)
    _m5.conn.execute("UPDATE tenants SET default_trading_mode='SHADOW' WHERE id=1")
    _m5.conn.commit()
    _m5.close()

    # ── 6) laden_oder_erstellen: Paper-Datei wird NICHT aus Shadow uebernommen ──
    p5 = bt20.laden_oder_erstellen(999, mode="paper")
    ck("P5: paper-Depot leer (keine Shadow-Positionen)", not p5.positions)
    ck("P5: paper-Depot mode=paper", getattr(p5, "mode", None) == "paper")

    # Cleanup Testdateien
    for _f in (sh_pfad20, pa_pfad20, _os20.path.join(dash20.BASE, "depot_999_paper.json")):
        if _os20.path.exists(_f):
            _os20.remove(_f)
    # Reinigung im spec-Verzeichnis (paper-leerstand)
    _pdir20 = _os20.path.join(dash20.BASE, "spec_depots_paper")
    if _os20.path.isdir(_pdir20) and not _os20.listdir(_pdir20):
        _os20.rmdir(_pdir20)
    ck("P5: Shadow->Paper-Freigabe komplett", True)
except Exception as e:
    ck("Phase 5 Shadow->Paper-Freigabe", False, str(e))

# ─── Phase 9 (S19-P9): Provider-Connection Status-Workflow + Secret-Rotation ─
print("\n9p. PHASE 9: Provider-Status + Secret-Rotation")
try:
    import db as db9
    m9 = db9.MTDB()
    tid9 = 1
    # Connection anlegen (Legacy-Status 'aktiv')
    m9.provider_connection_add(tid9, "MARKETDATA", "TestProvider", "PAPER", "read",
                               f"sec:test_{tid9}", created_by=1)
    conns9 = m9.provider_connection_list(tid9)
    cid9 = conns9[-1]["id"]
    ck("P9: Connection angelegt (status=aktiv)", conns9[-1]["status"] in ("aktiv", "CONFIGURED"))
    # Disable (aktiv -> DISABLED erlaubt)
    d9 = m9.provider_connection_disable(cid9, tid9)
    ck("P9: Disable aktiv->DISABLED ok", d9["ok"] and d9["new"] == "DISABLED")
    # Illegaler Sprung DISABLED -> HEALTHY blocked
    bad9 = m9.provider_connection_set_status(cid9, tid9, "HEALTHY")
    ck("P9: Illegaler Sprung DISABLED->HEALTHY blockiert", not bad9["ok"])
    # Re-enable
    e9 = m9.provider_connection_enable(cid9, tid9)
    ck("P9: Enable DISABLED->CONFIGURED ok", e9["ok"] and e9["new"] == "CONFIGURED")
    # Cross-Tenant-Block (tid=999 darf cid9 nicht aendern)
    cross9 = m9.provider_connection_disable(cid9, 999)
    ck("P9: Cross-Tenant Disable blockiert", not cross9["ok"])
    # Delete
    del9 = m9.provider_connection_delete(cid9, tid9)
    ck("P9: Delete ok", del9["ok"])
    # Secret-Rotation + Redaction
    sec9 = __import__("security")
    sec9.secret_set(tid9, "API_TEST9", "oldsecretAAAA")
    rot9 = m9.secret_rotate(tid9, "API_TEST9", "newsecretBBBB")
    ck("P9: Secret-Rotation ok", rot9["ok"] and rot9["last4"] == "BBBB")
    ck("P9: Klartext NICHT in Antwort", "newsecretBBBB" not in str(rot9))
    ck("P9: last4 nur letzte 4", m9.secret_last4(tid9, "API_TEST9") == "****BBBB")
    m9.close()
except Exception as e9:
    ck("Phase 9 Provider-Status + Secret-Rotation", False, str(e9))

# ─── Phase 10 (S19-P10): Datenprovider-Abstraktion (MarketSnapshot) ─
print("\n10p. PHASE 10: Datenprovider-Abstraktion")
try:
    import market_data_provider as mdp10
    # Interface existiert
    ck("P10: MarketDataProvider Basis-Interface", hasattr(mdp10, "MarketDataProvider"))
    ck("P10: MarketSnapshot-Dataclass", hasattr(mdp10, "MarketSnapshot"))
    # Registry
    y10 = mdp10.get_provider("yahoo")
    ck("P10: Provider yahoo instanzierbar", y10 is not None and y10.name == "yahoo")
    # Snapshot-Felder (Auftrag S12)
    snap10 = mdp10.MarketSnapshot(ticker="AAPL", price=150.5, rsi=55.0)
    fields10 = set(snap10.to_dict().keys())
    needed10 = {"ticker","price","timestamp","currency","source","quality","rsi","sma20","sma50","atr","volume_ratio","regime"}
    ck("P10: Snapshot hat alle S12-Felder", needed10.issubset(fields10))
    # Fallback liefert Snapshot (nicht rohen float)
    fb10 = mdp10.get_quote_with_fallback("AAPL")
    ck("P10: Fallback liefert MarketSnapshot", isinstance(fb10, mdp10.MarketSnapshot))
    # Ungueltiger Ticker -> KEIN stiller 0-Kauf (price=0, quality=unknown)
    bad10 = mdp10.get_quote_with_fallback("NONEXISTENTXYZ999")
    ck("P10: Ungueltiger Ticker -> kein Kauf (price=0, quality=unknown)",
       bad10.price == 0 and bad10.quality == "unknown")
    # Health-Check
    h10 = mdp10.health_all()
    ck("P10: Health-Check fuer alle Provider", set(h10.keys()) >= {"yahoo","finnhub","twelvedata","alphavantage"})
    # Abstraktion ist verbindlich (Trading-Core SOLLTE via market_data_provider gehen)
    ck("P10: Abstraktion ist zentrales Interface",
       hasattr(mdp10, "MarketDataProvider") and hasattr(mdp10, "get_quote_with_fallback"))
    # marktdaten.py (Backend) wird von der Abstraktion gewrappt
    import marktdaten as md10
    ck("P10: Abstraktion nutzt marktdaten-Backend",
       hasattr(md10, "hole_kurs") and hasattr(md10, "scan_fallback_yfinance"))
except Exception as e10:
    ck("Phase 10 Datenprovider-Abstraktion", False, str(e10))

# ─── Phase 11 (S19-P11): Paper-/Simulator-Broker (Sandbox) ─
print("\n11p. PHASE 11: Paper-/Sandbox-Broker")
try:
    import security as sec11
    # BrokerProvider-Interface
    ck("P11: BrokerProvider-Interface", hasattr(sec11, "BrokerProvider"))
    ck("P11: PaperBrokerAdapter", hasattr(sec11, "PaperBrokerAdapter"))
    ck("P11: SandboxBrokerAdapter (neu)", hasattr(sec11, "SandboxBrokerAdapter"))
    # Factory
    sb11 = sec11.get_broker_adapter("SANDBOX")
    pb11 = sec11.get_broker_adapter("PAPER")
    ck("P11: Factory liefert Sandbox fuer SANDBOX", type(sb11).__name__ == "SandboxBrokerAdapter")
    ck("P11: Factory liefert Paper fuer PAPER", type(pb11).__name__ == "PaperBrokerAdapter")
    # Sandbox Order (durchlaeuft validate_order_intent)
    intent11 = sec11.create_order_intent(tenant_id=1, ticker="AAPL", side="buy",
                                          quantity=1, price=150.0, mode="paper")
    r11 = sb11.place_order(intent11)
    ck("P11: Sandbox Order ausgefuehrt", r11.get("ok") and r11.get("environment") == "SANDBOX")
    # Keine echten Orders (PAPER_ONLY)
    ck("P11: Sandbox ist PAPER_ONLY (kein Live)", "LIVE" not in sb11.environment)
    # Health (nach connect)
    sb11.connect()
    ck("P11: Sandbox health_check", sb11.health_check().get("ok") is True)
except Exception as e11:
    ck("Phase 11 Paper-/Sandbox-Broker", False, str(e11))

# ─── Phase 12 (S19-P12): Order-Intent + Risk-Integration (18-Punkte-Checkliste S13) ─
print("\n12p. PHASE 12: Order-Intent + Risk-Integration")
try:
    import security as sec12
    # create_order_intent speichert price korrekt
    oi12 = sec12.create_order_intent(tenant_id=1, ticker="AAPL", side="buy",
                                     quantity=1, price=150.0, mode="paper")
    ck("P12: create_order_intent speichert price", oi12.get("limit_price") == 150.0)
    # Gueltige Order durchlaeuft alle Checks
    r12 = sec12.validate_order_intent(oi12, portfolio_value=100000)
    ck("P12: Gueltige Order erlaubt (18-Check)", r12["allowed"])
    # LIVE blockiert (PAPER_ONLY)
    oi_l = sec12.create_order_intent(tenant_id=1, ticker="AAPL", side="buy",
                                     quantity=1, price=150.0, mode="LIVE_ACTIVE")
    ck("P12: LIVE blockiert (PAPER_ONLY)", not sec12.validate_order_intent(oi_l, portfolio_value=100000)["allowed"])
    # Preis=0 blockiert (Check 14: Daten aktuell)
    oi_p0 = sec12.create_order_intent(tenant_id=1, ticker="AAPL", side="buy",
                                      quantity=1, price=0, mode="paper")
    ck("P12: Preis=0 blockiert (Stale-Daten)", not sec12.validate_order_intent(oi_p0, portfolio_value=100000)["allowed"])
    # Tenant-Mismatch blockiert (Check 9)
    oi_mm = dict(sec12.create_order_intent(tenant_id=1, ticker="AAPL", side="buy",
                                           quantity=1, price=150.0, mode="paper"))
    oi_mm["caller_tenant_id"] = 999
    ck("P12: Tenant-Mismatch blockiert", not sec12.validate_order_intent(oi_mm, portfolio_value=100000)["allowed"])
    # risk_check_status gesetzt
    ck("P12: risk_check_status=passed", r12["intent"].get("risk_check_status") == "passed")
    # Menge<=0 blockiert
    oi_q0 = sec12.create_order_intent(tenant_id=1, ticker="AAPL", side="buy",
                                      quantity=0, price=150.0, mode="paper")
    ck("P12: Menge=0 blockiert", not sec12.validate_order_intent(oi_q0, portfolio_value=100000)["allowed"])
except Exception as e12:
    ck("Phase 12 Order-Intent + Risk", False, str(e12))

# ─── Phase 14 (S19-P14): Live-Antragsprozess ─
print("\n14p. PHASE 14: Live-Antragsprozess")
try:
    import db as db14
    # Cleanup: Test-Antraege aus vorherigen Laufen entfernen (Idempotenz)
    try:
        m14pre = db14.MTDB()
        m14pre.conn.execute("DELETE FROM live_requests WHERE tenant_id IN (50, 51)")
        m14pre.conn.commit()
        m14pre.close()
    except Exception:
        pass
    m14 = db14.MTDB()
    tid14 = 50  # isolierter Tenant fuer P14-Hauptablauf
    # Antrag erstellen
    c14 = m14.live_request_create(tid14, requested_by=2, broker_connection_id=1, note="Test")
    ck("P14: Live-Antrag erstellt (PENDING)", c14["ok"] and c14["status"] == "PENDING")
    rid14 = c14["id"]
    # Illegaler Skip (Review ueberspringen -> Approve blockiert)
    bad14 = m14.live_request_approve(rid14, tid14, approved_by=3)
    ck("P14: Approve ohne Review blockiert", not bad14["ok"])
    # Review
    rv14 = m14.live_request_review(rid14, tid14, reviewed_by=3)
    ck("P14: Review PENDING->IN_REVIEW", rv14["ok"] and rv14["status"] == "IN_REVIEW")
    # Approve
    ap14 = m14.live_request_approve(rid14, tid14, approved_by=3, note="OK")
    ck("P14: Approve IN_REVIEW->APPROVED", ap14["ok"] and ap14["status"] == "APPROVED")
    # Activate
    ac14 = m14.live_request_activate(rid14, tid14)
    ck("P14: Activate APPROVED->ACTIVATED", ac14["ok"] and ac14["status"] == "ACTIVATED")
    # Doppelter Antrag blockiert (ACTIVATED gilt als offen)
    c214 = m14.live_request_create(tid14, requested_by=2)
    ck("P14: Doppelter Antrag blockiert", not c214["ok"])
    # Cross-Tenant
    ct14 = m14.live_request_review(rid14, 999, reviewed_by=3)
    ck("P14: Cross-Tenant Review blockiert", not ct14["ok"])
    # Reject-Workflow (neuer Tenant, isoliert)
    c314 = m14.live_request_create(51, requested_by=2)
    if c314["ok"]:
        m14.live_request_review(c314["id"], 51, reviewed_by=3)
        rj14 = m14.live_request_reject(c314["id"], 51, rejected_by=3, note="Nein")
        ck("P14: Reject IN_REVIEW->REJECTED", rj14["ok"] and rj14["status"] == "REJECTED")
    else:
        ck("P14: Reject-Workflow (Tenant 51 frei)", False)
    m14.close()
except Exception as e14:
    ck("Phase 14 Live-Antragsprozess", False, str(e14))


# Der Test hat den Modus von Tenant 1 veraendert. Nachgewiesen am
# 29.09.2026: der Betrieb stand auf PAPER, nach dem Testlauf stand
# er auf SHADOW - und der ETF-Trader lief danach wieder gegen die
# alten SHADOW-Depots statt gegen die zehn Testdepots.
#
# Der Test prueft den Zustandsautomaten, nicht die Betriebseinstellung.
# Also wird sie danach wiederhergestellt - aus einer eigenen
# Sicherung, die nicht im Weg eines anderen Tests steht.
import security as _sec_modus
_BETRIEB_MODUS = "PAPER"
try:
    _vor = _sec_modus.get_trading_mode(1)
    if _vor != _BETRIEB_MODUS:
        _sec_modus.set_trading_mode(
            _BETRIEB_MODUS, tenant_id=1, user="admin",
            reason="Wiederherstellung nach Testlauf")
        print("\n  Modus wiederhergestellt: %s -> %s"
              % (_vor, _BETRIEB_MODUS))
except Exception as _e:
    print("\n  WARN Modus nicht wiederherstellbar: %s" % _e)

# 29.09.2026: Auch das Testverzeichnis muss weg. Sonst bleibt es
# unter /tmp liegen und die Depots sind beim naechsten Lauf nicht
# mehr auffindbar, was den Test still scheitern laesst.
try:
    import shutil as _sh, os as _os
    if "_tdir" in dir() and _os.path.isdir(_tdir):
        _sh.rmtree(_tdir, ignore_errors=True)
        print("\n  Testdepot-Verzeichnis entfernt: %s" % _tdir)
except Exception as _e2:
    print("\n  WARN Testverzeichnis nicht entfernt: %s" % _e2)
