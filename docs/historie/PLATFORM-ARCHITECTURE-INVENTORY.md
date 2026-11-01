# PLATFORM-ARCHITECTURE-INVENTORY.md

> **Bestandsaufnahme Micro-Trader** · Stand: 2026-08-08 · Version: v2.25.1
> Erstellt im Rahmen von **PHASE 0** des Mandanten-Ausbauauftrags.
> Keine funktionalen Änderungen — reine Ist-Analyse.

---

## 1. Systemüberblick

Micro-Trader ist ein **autonomes Paper-/Shadow-Trading-System**:
- Aktien- (20 Depots), ETF- (20 Depots), Spekulations-Logik (49 aktiv)
- KI-Entscheidungen (Provider-Rotation), Lern- und Regelwerk
- Flask-Dashboard (Port 5300, nur 127.0.0.1)
- SQLite (Trades, KI-Entscheidungen, Depot-Snapshots) + JSON-Dateien
- Benutzerverwaltung (Login, Sessions, Rollen, MFA, Audit, Rate-Limit)
- Tailscale-Server, **PAPER_ONLY** (kein Echtgeld)

**Betriebsmodus heute:** `PAPER_ONLY` / Shadow-Paper. Kein Live-Code, keine Broker-Anbindung.

---

## 2. Identität (Bestand)

| Bereich | Status | Details |
|---------|--------|---------|
| Login | ✅ | `POST /` + `/landing` (Inline-Formular), cookie-basiert (`username` + `sid`, HttpOnly, SameSite=Lax) |
| Sessions | ✅ | `security.py`: `create_session`, `rotate_session` (nach Login), `session_valid`, `touch_session`, `revoke_session/all`, Timeout |
| Rollen | ✅ | `visitor, user, analyst, operator, admin, superadmin` → `ROLE_TO_LEVEL` Mapping |
| MFA | ✅ | TOTP (RFC6238, HMAC-SHA1), `generate_mfa_secret`, `verify_mfa`, `require_recent_mfa`, Provisioning-URI |
| Rate-Limit | ✅ | v2.25.0: 5 Fehlversuche → Exp-Backoff 30s+ pro IP+User (`login_rate.json`) |
| CSRF | ⚠️ | `generate_csrf_token`/`verify_csrf_token` vorhanden, aber **nicht im HTML-Rendering verdrahtet** |
| Benutzerverwaltung | ✅ | 8 API-Routen (`/api/users*`, `/api/me*`), UI-Tabs "Mein Konto" + "Benutzer" (nur Admin) |
| **Tenant-Modell** | ❌ | **Existiert NICHT.** Keine `tenant_id`, keine Workspaces, kein OIDC/OAuth/JWT |
| Passwort-Hashing | ✅ | werkzeug `pbkdf2:sha256:1000000` mit Salt (OWASP-konform; `scrypt` verfügbar als Option) |
| Secret-Store | ❌ | Nur `.env` (gitignored) — kein OS-Store/Vault, keine Verschlüsselung |

**Kernlücke:** Es gibt Benutzer, aber **keine Mandanten/Workspaces**. Alle Daten sind global.

---

## 3. Datenhaltung (Bestand)

### 3.1 SQLite (`micro_trader.db`, ~2.4 MB)

| Tabelle | Zeilen | Spalten | Zweck |
|---------|--------|---------|-------|
| `trades` | 1.783 | 13 | Ausgeführte (Papier-)Trades |
| `ki_decisions` | 922 | 12 | KI-Entscheidungen (Ticker/Aktion/Konfidenz/Grund) |
| `depot_snapshot` | 17.533 | 8 | Historische Depotwerte/Renditen |
| `markt_daten` | 0 | 7 | (vorbereitet, ungenutzt) |

**Keine Tabellen:** users/tenants/roles/permissions/sessions/mfa — Benutzer liegen in **JSON** (`security_users.json`).

### 3.2 JSON-Dateien (Daten)

| Gruppe | Dateien | Zweck | Global? |
|--------|---------|-------|---------|
| Depots | `depot_000…095.json` (20), `etf_000…100.json` (21), `profile_*.json`, `paper_depot.json`, `depot.json` | Depot-Daten (Positionen, Cash, Rendite) | ⚠️ **global**, nur per Datei getrennt |
| KI/Regeln | `ki_log.json`, `ki_regeln.json`, `learned_rules.json`, `learned_rules_global.json`, `pending_rules.json`, `konfidenz_stats.json`, `ki_cooldown.json` | KI-Entscheidungen, gelernte Regeln | ⚠️ global |
| System | `settings.json`, `pause_flag.json`, `login_rate.json`, `trader_status.json`, `system_log.json`, `batch_summary.json` | Einstellungen, Pause, Status | ⚠️ global |
| Sicherheit | `security_users.json`, `security_audit.json` (beide **gitignored**) | Benutzer, Audit | ⚠️ global |
| Sonst | `active_profile.json`, `notifications.json`, `spec_log.json`, `spec_watch.json`, `tagesverlauf.json`, `regel_history.json`, `version.json`, `whatsapp_config.json` | Verschiedenes | ⚠️ global |

### 3.3 Fazit Datenhaltung
- **Alles global** — kein `tenant_id`, keine userbezogene Trennung außer Dateinamen-Muster (`depot_<risk>.json`).
- SQLite-Tabellen haben **keine** tenant/user-Spalte.
- Für Phase 1: `tenant_id` + `user_id` müssen in JSON-Strukturen + SQLite ergänzt werden (Migrationspfad).

---

## 4. Routen-Inventar (40 Routen)

### 4.1 Zugriffsklassen-Schema (existiert ✅)

`ROUTE_ACCESS` in `security.py` + `before_request` → `route_class()` → `access_level_met()`.
Default = **ADMIN** (deny by default ✅). Klassen: `PUBLIC → AUTHENTICATED → ANALYST → OPERATOR → ADMIN → SUPERADMIN`.

### 4.2 Routen nach Klasse

| Klasse | Routen |
|--------|--------|
| **PUBLIC** | `/`, `/landing`, `/api/version`, `/static/*`, `/assets/*` |
| **AUTHENTICATED** | `/dashboard`, `/data`, `/depot_json`, `/spec_depot_json`, `/etf_depot_json`, `/api/analysis`, `/api/report_pdf`, `/api/report_list`, `/search_ticker`, `/ticker_chart`, `/reports/*`, `/api/me*` |
| **ANALYST** | `/api/profil_karten`, `/api/profile`, `/api/db_karten`, `/api/db_query`, `/api/ki_log` |
| **OPERATOR** | `/api/pause_trading`, `/api/clear_cache` |
| **ADMIN** | `/api/users*`, `/api/settings`, `/admin*` (7 Seiten) |
| **SUPERADMIN** | (via ADMIN-Fallback; keine exklusiven Routen) |

### 4.3 Fehlende Zuordnungen (Lücken)
- `/api/db_query` ist **ANALYST** — direkter SQL-Zugriff, kritisch zu prüfen (Tenant-Filter nötig!)
- `/api/pause_trading` nur OPERATOR — OK, aber ohne Tenant-Bezug
- Keine Route hat Tenant-Kontext (session-basiert wäre neu)

---

## 5. Provider (Bestand)

### 5.1 Marktdaten (`marktdaten.py`)

| Provider | Funktion | Key-Quelle | Status |
|----------|----------|-----------|--------|
| yfinance | `_yfinance_kurs`, `scan_fallback_yfinance` | keiner (frei) | ✅ primär |
| Finnhub | `_finnhub_kurs` | `FINNHUB_KEY` aus `.env` | ✅ Fallback |
| TwelveData | `_twelvedata_kurs` | `TWELVEDATA_KEY` aus `.env` | ✅ Fallback |
| AlphaVantage | `_alphavantage_kurs` | `ALPHAVANTAGE_KEY` aus `.env` | ✅ Fallback |

- Super-Mix: yfinance primär, gedrosselte Fallbacks (Rate-Limit-Schutz `_gedrosselt`)
- **Alle global** — keine userbezogene Providerwahl

### 5.2 KI-Provider (`ki_provider.py`)

| Funktion | Zweck |
|----------|-------|
| `call_ki` / `call_ki_batched` / `call_ki_chat` / `call_ki_cron` | KI-Calls mit Provider-Pool |
| `_baue_provider_liste*` | Provider-Rotation (Nous/OpenAI/Deepseek/opencode) |
| `_call_ki_with_pool` | Pool-Fallback bei Fehlern/Rate-Limits |
| `_nous_creds` / `_nous_refresh` | Nous-Auth (nous_auth.json) |
| `_cooldown_laden`/`_speichern` | KI-Cooldown (ki_cooldown.json) |

- Keys: Nous-Auth-Datei + OpenAI + Deepseek (via Hermes-Verbindung / .env)
- **Alle global** — kein userbezogener Provider

### 5.3 Broker / Execution
- **Keine** Broker-Anbindung, keine Exchange-APIs, kein Order-Routing.
- Trading läuft nur intern (Papier-Simulation in `engine.py`/`trader.py`/`spec_trader.py`).
- `markt_daten`-Tabelle existiert, ist aber leer (vorbereitet).

---

## 6. Sicherheits-Stand (Bestand, v2.25.1)

| Bereich | Status |
|---------|--------|
| 127.0.0.1-Bind | ✅ Flask nur lokal (kein 0.0.0.0) |
| Security-Header | ✅ CSP, X-Frame-Options DENY, nosniff, no-referrer, Permissions-Policy |
| Passwort-Hashing | ✅ PBKDF2-1M (werkzeug) |
| Login-Rate-Limit | ✅ v2.25.0 |
| Audit-Log | ✅ `security_audit.json` (append-only), mit IP+UA |
| Admin-Analytik | ✅ Logins-Tab (IP/Brute-Force), Sicherheit-Checkliste |
| CSRF | ⚠️ Token-Logik da, nicht im Rendering |
| HSTS | ⚠️ nur bei HTTPS-Funnel relevant (lokal HTTP) |
| **Tenant-Isolation** | ❌ **Fehlt komplett** (kein Tenant-Modell) |
| **Secret-Store** | ❌ Nur .env |

---

## 7. Lücken-Analyse für Mandanten-Ausbau

### Sofort relevant (Phase 1-2)
1. **Tenant-Modell fehlt** — `users` braucht `tenant_id`, neue Tabellen: `tenants`, `tenant_memberships`, `workspaces`
2. **Alle Daten global** — Depot/Regeln/KI-Log/Audit brauchen Tenant-Scoping
3. **Kein OIDC/OAuth** — Auftrag verlangt etablierte Verfahren (Phase 1+)
4. **CSRF nicht verdrahtet** — vor Mandanten-Ausbau fixen

### Mittelfristig (Phase 3-6)
5. **Trading-Modi nur implizit** — Shadow/Paper sind Text-Flags in `active_profile.json`/Profil-Dateien, keine Zustandsmaschine
6. **Kein Order-Intent-Modell** — Trades gehen direkt in SQLite `trades`
7. **Provider global** — keine Connection-Tabelle, Keys global in .env
8. **Kein Broker-Adapter** — Schnittstelle fehlt komplett

### Bewusst NICHT vorhanden (gut für Sicherheit)
- Kein Echtgeld-Code, keine Live-Keys, keine Orderroute
- `markt_daten` leer, `broker_*`-Tabellen existieren nicht

---

## 8. Nächste Schritte (aus Auftrag)

1. ✅ **PHASE 0 abgeschlossen** (dieses Dokument + PROVIDER-INVENTORY.md)
2. Phase 1: Datenmodell User/Tenant (SQLite-Erweiterung)
3. Phase 2: Rollen/Berechtigungsmodell (Rechte-Katalog)
4. Phase 3: Trading-Modi-Zustandsmaschine
5. … (Reihenfolge laut Auftrag §16)

**Harte Grenze:** Kein Echtgeld, kein Live-Broker, PAPER_ONLY bleibt bis Phase 17 abgeschlossen + getestet.
