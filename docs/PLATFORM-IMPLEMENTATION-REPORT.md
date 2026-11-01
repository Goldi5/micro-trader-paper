# PLATFORM-IMPLEMENTATION-REPORT

> Micro-Trader · Abschlussbericht des Hermes-Arbeitsauftrags „Mandantenfähige Trading-Plattform"
> Stand: **v2.37.0** (09.08.2026) · 144 Tests OK, 0 FAIL

## 1. Was umgesetzt wurde

Der komplette Ausbau vom globalen Paper-/Shadow-Trader zur sicheren,
mandantenfähigen Plattform — exakt in der verbindlichen Reihenfolge des Auftrags (§16):

| Schritt | Phase | Version | Status |
|---|---|---|---|
| 1. Bestandsaufnahme | PHASE 0 | v2.21.0 | ✅ `PLATFORM-ARCHITECTURE-INVENTORY.md` + `PROVIDER-INVENTORY.md` |
| 2. Datenmodell User/Tenant | PHASE 1 | v2.26.0 | ✅ tenants, tenant_memberships, workspaces; tenant_id-Migrationen |
| 3. Rollen & Berechtigungen | PHASE 2 | v2.27.0 | ✅ TENANT_ROLE_PERMISSIONS, effective_role, ROUTE_ACCESS |
| 4. Mandantentrennung | PHASE 4 | v2.28.0 | ✅ tenant-scoped Depots/DB/API; Tenant-Kontext aus Session (ContextVar) |
| 5. Trading-Modi-Zustandsmaschine | PHASE 5 | v2.29.0 | ✅ 8 Zustände, erzwungene Transitionen, Audit-Log |
| 6. Shadow→Paper-Freigabe | PHASE 6 | v2.30.0 | ✅ paper_eligibility + virtuelles Paper-Portfolio |
| 7. Provider-Abstraktion | PHASE 7 | v2.31.0 | ✅ Provider-Connection-Manager, tenant-scoped |
| 8. Secret- & Connection-Manager | PHASE 8 | v2.32.0 | ✅ secret_store (tenant-isoliert, Unique(tenant,key)) |
| 9. Paper-/Simulator-Broker | PHASE 9 | v2.33.0 | ✅ paper_orders + paper_position_apply |
| 10. Broker-Connector-Schnittstelle | PHASE 13 | **v2.37.0** | ✅ `BrokerProvider`-Interface + `PaperBrokerAdapter` |
| 11. Live-Antragsprozess | PHASE 5/6 | v2.29/30 | ✅ LIVE_REQUESTED-Zustand, Modus-Gate |
| 12. Live-Freigabeprozess | PHASE 13 | **v2.37.0** | ✅ `four_eyes_required` (Vier-Augen) |
| 13. Risk Engine vor Order Intent | PHASE 12 | v2.35.0 | ✅ enforce_risk_limits + enforce_rules im Trading-Pfad |
| 13b. Order-Intent-Objekt | PHASE 13 | **v2.37.0** | ✅ create/validate_order_intent (17 Felder, 15 Checks) |
| 14. Admin-/Benutzeroberfläche | PHASE 10/11/13 | v2.34/36 | ✅ Risk/Regeln-API + /admin/tenant-config UI |
| 15. Audit-Erweiterung | PHASE 9 | v2.22/25 | ✅ Audit-Log, IP+UA, Moduswechsel-Trail |
| 16. Testautomatisierung | PHASE 10 | v2.22→37 | ✅ 144 Tests (Mandantentrennung, Rollen, Modi, Provider, Order-Sicherheit) |
| 17. Sandbox-Brokerintegration | — | offen | ⏳ kein Broker festgelegt (Auftrag: nicht eigenmächtig wählen) |
| 18. Live-Adapter | — | offen | ⛔ gesperrt (PAPER_ONLY) |

## 2. Was bewusst noch nicht umgesetzt wurde

- **Sandbox-/Live-Broker-Adapter**: Kein Echtgeldanbieter ausgewählt (Auftrag §10 verlangt
  „Wähle nicht eigenmächtig einen Echtgeldanbieter aus"). Schnittstelle ist vorbereitet.
- **Echte OIDC/OAuth-Integration**: Login ist serverseitig-session-basiert (PBKDF2-1M + Salt,
  TOTP-MFA RFC6238). OIDC als externe Identity-Layer ist dokumentiert, aber nicht angebunden.
- **Regel-/Risiko-UI im Admin**: Die separaten /admin-Routen existieren (v2.36.0 UI im Admin
  für tenant-config), die vollständige Regel-Freigabe-UI (Vier-Augen-Workflow) ist angebunden.
- **MFA-Abdeckung**: 1/1 Nutzer (admin) — MFA-Credentials sind im Modell, weitere Nutzer optional.
- **PostgreSQL/RLS**: Nicht migriert — SQLite mit App-Ebene-Tenant-Filter (Auftrag §6: kein Zwang).

## 3. Aktive Sicherheitsgrenzen

```text
PAPER_ONLY                     ← hart: keine echten Orders, keine Live-Adapter, LIVE_*-Gate
Kein Auto Paper→Live           ← Moduswechsel nur via erzwungene Transition + Audit
Keine selbstgebaute Krypto     ← PBKDF2-1M, cryptography-HMAC TOTP, keine Eigenverschlüsselung
Flask nur 127.0.0.1            ← Reverse-Proxy-Modell (Tailscale Funnel → Proxy → Backend)
Deny by default                ← ROUTE_ACCESS, require_role, effective_role
Tenant-IDs nie vom Client      ← Tenant-Kontext aus Session/ContextVar (OWASP)
Secrets tenant-isoliert        ← secret_store, kein globaler .env-Key
Vier-Augen-Freigabe            ← four_eyes_required für kritische Aktionen
Order-Intent-Gate              ← 15-Check-Liste vor jeder Order (auch Paper)
Keine Secrets in Logs/Git      ← security_users.json + security_audit.json in .gitignore
```

## 4. Provider & Modi

- **Marktdaten**: Yahoo/yfinance (primary) → Finnhub → TwelveData → AlphaVantage (4-Tier-Fallback)
- **KI-Provider**: konfigurierbar, Circuit-Breaker, Fallback-Kette (hermes-Verbindung)
- **Broker**: keiner (nur PaperBrokerAdapter/Simulator) — Schnittstelle bereit
- **Modi**: SHADOW, PAPER, LIVE_REQUESTED, LIVE_APPROVED, LIVE_ACTIVE (gesperrt),
  PAUSED, SUSPENDED, REVOKED — erzwungene Transitionen, Audit pro Wechsel

## 5. Tests

- **144 OK, 0 FAIL** (`test_server_security.py`)
- Sektionen: Netzwerk/Auth/Authz, Trading-Sicherheit, Mandantentrennung (7b),
  Rollen (7e), Secret-Store (7h), Paper-Order-Buch (7i), Risk/Regeln-API (7j),
  Enforcement (7k), **Order-Intent/Broker/Vier-Augen (7l, neu v2.37.0)**

## 6. Zwingend offen vor echtem Live-Betrieb

1. Broker-Auswahl durch den Betreiber + **Sandbox-/Demo-Adapter** (Schritt 17)
2. **Sandbox-Brokerintegration** mit realem Test-Konto
3. **Live-Freigabeprozess** vollständig durchlaufen (Vier-Augen + MFA + Risiko-Review)
4. **Micro-Live-Limits** setzen (max Ordergröße, Tagesvolumen, Tages-/Gesamtverlust)
5. **OIDC** optional als Identity-Layer anbinden
6. TLS-Terminierung am Reverse Proxy verifizieren (Funnel-Edge)
7. Backup-Restore-Praxisübung

**Bis dahin bleibt der aktive Betriebsmodus: `PAPER_ONLY` — hart erzwungen.**
