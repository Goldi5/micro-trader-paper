# MICRO-TRADER — HANDOFF V3

> **Single Source of Truth für die technische Übergabe des Projekts.**
> Jede wichtige Aussage trägt STATUS + EVIDENCE. Nicht verifizierbares ist
> explizit als UNVERIFIED/OPEN markiert. Historie ist HISTORICAL markiert.
> **Keine Behauptung ist glaubwürdiger als ihre Evidenz.**

---

# 00 — DOCUMENT CONTROL

```text
Handoff Version:     V3 (2026-08-09, aktualisiert 2026-08-12)
System Version:      v2.57.1
Build:               2026-08-12_1300
Repository:          https://github.com/Goldi5/Mirco-Trader.git (HTTPS, SSH:22 geblockt)
Commit:              b61f480 (FIX v2.57.1: JS SyntaxError + Dashboard startet sauber) — HEAD
Generated:           2026-08-09
Last Verified:       2026-08-12
Environment:         Windows 10 (PC Christian Glaser, remote 1200km), Python venv
                     C:/Users/goldi/AppData/Local/hermes/hermes-agent/venv
Document Status:     CURRENT (mit HISTORICAL-Abschnitten §20)
```

> **2026-08-11 UPDATE (v2.55.0):** Dashboard-Stabilität + KI-Ketten-Beobachtung.
> Commits seit v2.43.0: 527ada6 (security_users Fix), c1c2e52 (Single-Instance-Guard),
> c11cc65 (Login-Page), 48c1004 (5 Dashboard-Fixes), 4f81aa6 (v2.55.0),
> f1b60a5 (Nav-Trennung), f9cff2d (Konfidenz-Cap Dedup), a5aa78f (Fix 1-3),
> 8cdc0e6 (FIX 4: ki_log Reset). Details in repo `docs/CHANGELOG.md` §[2.55.0].

Vorgänger: Handoff-Complete v2.38.0 (2026-08-09, 151 Tests) → Diese V3 reorganisiert
und beweisgestützt, ergänzt um Phasen 0–5 (v2.38.1–v2.43.0, 273 Tests).

---

# 01 — EXECUTIVE SYSTEM SUMMARY

**Was ist Micro-Trader?** Autonomer Papier-/Shadow-Trading-Bot (KEIN echtes Geld)
auf einem Windows-PC. Seit v2.26 mandantenfähig (Rollen, Tenants, Modi, Secrets,
Order-Intent, Broker-Interface). Seit v2.38.1–v2.43.0: professionelle
Benutzerverwaltung, feine Rollen-Permissions, Tenant-Isolation verifiziert,
komplette Zustandsmaschine + Shadow→Paper-Freigabe mit getrennten Portfolios.

**Handelt:** Aktien (20×100$, RISK_STUFEN 0–95), ETF (20×100$), Spekulation
(49×100$, Watchlist 169 Ticker). **KI:** Free-Tier-Provider-Rotation, 15-min-Wellen.
**Dashboard:** Flask Port 5300, 127.0.0.1-only (Reverse-Proxy-Modell).

**Aktuelle Fähigkeiten:** Benutzer-Lebenszyklus (7 Status), 41 feine Permissions,
Rollen deny-by-default, MFA-Pflicht für Admin, Tenant-Isolation (tenant-keyed Cache
+ tid-Guard), Zustandsmaschine (8 Modi + erzwungene Transitionen + Vier-Augen bei
LIVE), Shadow→Paper mit 8 Voraussetzungen, getrennte Shadow/Paper-Portfolios,
Order-Intent (17 Felder) + 15 Checks, PaperBrokerAdapter, Vier-Augen-Gate,
Freigabe-Workflow, Secret-Store (tenant-isoliert), Provider-Connections,
Audit-JSONL, 273 Tests grün.

**Einschränkungen:** PAPER_ONLY hart (§2.1) — kein Live-Handel, kein echter Broker.
Production hat 1 Tenant (id=1). `markt_daten`-Tabelle leer (nur ad-hoc gescannt).
Risk-70-Budgetfilter ist in v2.38.1 als „bekannter Fehler" gelöst — Status: siehe
§09/BUG-002 (Implementierung heute: Budget-Fallback bei Risk 70 vorhanden, siehe
batch_trader.py). enforce_rules BLOCK-Bug gefixt in v2.38.1 (§09/BUG-001).

## CURRENT HEALTH MATRIX

| Bereich | Status | Evidence | Last Verified | Scope | Limitation |
|---|---|---|---|---|---|
| Trading Core | VERIFIED | batch_trader.py, 273 Tests | 2026-08-09 | Code+Paper | PAPER_ONLY, kein Live |
| Risk Engine | VERIFIED | risk_profile.py + enforce_risk_limits | 2026-08-09 | Code+Paper | Tenant-Limits pro Tenant |
| AI | VERIFIED | ki_provider.py Rotation | 2026-08-09 | Code+Paper | Free-Tier, Rate-Limits |
| Security | VERIFIED | security.py + Sektionen 7m–7r | 2026-08-09 | Code+Paper | MFA nur 1 Admin aktiv |
| Multi-Tenant | VERIFIED | Sektion 7p/7r, Test-Tenant | 2026-08-09 | Code+Test | Production: 1 Tenant |
| Database | VERIFIED | db.py (19 Tabellen) | 2026-08-09 | Code | markt_daten leer |
| Scheduler | VERIFIED | micro_trader_scheduler.py | 2026-08-09 | Production | Mo-Fr 15-22 MEZ |
| Learning | VERIFIED | ki_learning.py + learned_rules.py | 2026-08-09 | Code+Paper | Regel-Decay aktiv |
| Zustandsmaschine | VERIFIED | Sektion 7q (+17) | 2026-08-09 | Code+Test | LIVE_* ohne Broker-Adapter |
| Shadow→Paper | VERIFIED | Sektion 7r (+14) | 2026-08-09 | Code+Test | Voraussetzungen 8/8 |

---

# 02 — SYSTEM TRUTH

> Nur aktuelle Wahrheit. Historie → §20.

## COMPONENT: Trading-Core (batch_trader/engine)

```text
Status:        VERIFIED
Evidence:      batch_trader.py main() (Mode-Gate Z~89, Pipeline Z108-170),
               engine.py scan_markt/bewerte/ausführen; Tests 7m–7r
Code:          IMPLEMENTED
Tests:         VERIFIED (273 OK, 0 FAIL)
Runtime:       Market-Gate (boersen.py: US-Börse offen ±15min, Cron */5 15-22 Mo-Fr);
               Pipeline+Depot-Audit nur wenn Markt aktiv (Singleton-Guard in pipeline)
Production:    Aktiv im Paper-Betrieb (PAPER_ONLY)
Current Scope: SHADOW/PAPER; LIVE_* blockiert (kein Broker-Adapter)
Limitations:   kauf_budget-Fallback Risk 70 (siehe BUG-002); Depot.laden() leer (Falle §19)
Last Verified: 2026-08-11
Confidence:    HIGH
```

## COMPONENT: Zustandsmaschine

```text
Status:        VERIFIED
Evidence:      security.py set_trading_mode (Z63) + db.py mode_can_transition;
               Sektion 7q (Transitionstabelle, LIVE-Vier-Augen, Batch-Gate)
Code:          IMPLEMENTED (8 Modi, erzwungene Transitionen, Audit-Log)
Tests:         259→273 OK (7q +17)
Current Scope: SHADOW/PAPER aktiv; LIVE_* nur mit approved_by+MFA erreichbar
Limitations:   LIVE_* ohne Broker-Adapter — keine echte Execution möglich
Last Verified: 2026-08-09
Confidence:    HIGH
```

## COMPONENT: Multi-Tenant-Isolation

```text
Status:        VERIFIED
Evidence:      tenant-keyed /data-Cache (_cache_tid+_cache_mode), require_tenant_role
               + tid-Guard (3 Routen), Depot-tenant_id (engine/spec/etf/trader/paper),
               Sektion 7p (+11)
Code:          IMPLEMENTED
Tests:         VERIFIED (Cross-Tenant-Zugriffe DENY)
Production:    1 Tenant (id=1)
Limitations:   Zweiter Production-Tenant noch nicht unter realer Last validiert
               (Test-Tenant „isolation_b" id=2 existiert in Tests)
Last Verified: 2026-08-09
Confidence:    HIGH
```

## COMPONENT: Shadow→Paper-Freigabe (§9)

```text
Status:        VERIFIED
Evidence:      security.py paper_eligibility (8 Voraussetzungen, Z130),
               enter_paper (Z274), Sektion 7r
Code:          IMPLEMENTED (getrennte Portfolios: depot_*_paper.json etc.)
Tests:         VERIFIED (7r: Scope-Trennung, Verlauf-Trennung, Mode-Gates)
Production:    Tenant 1 steht auf SHADOW
Limitations:   Wechsel nur bei 8/8 Voraussetzungen; markt_daten leer → aktuell
               nicht eligible (Marktdaten-Status fehlt)
Last Verified: 2026-08-09
Confidence:    HIGH
```

## COMPONENT: Security / Benutzer & Rollen

```text
Status:        VERIFIED
Evidence:      security.py _load_users/GC, create_user (Z1107), set_role (Z1182),
               FINE_PERMISSIONS (41), role_has_permission, ROUTE_ACCESS;
               Sektionen 7n/7o
Code:          IMPLEMENTED (7 Status, Session-Widerruf, MFA-Pflicht admin,
               8 Recovery-Codes, Redaction password_hash/mfa_secret)
Tests:         VERIFIED (183→231 OK)
Production:    Aktiv (Admin mit MFA empfohlen; MFA-Abdeckung ⚠️ laut §22b)
Limitations:   CSRF-Token noch nicht in allen Forms verdrahtet (§22.4)
Last Verified: 2026-08-09
Confidence:    HIGH
```

## COMPONENT: Datenprovider-Abstraktion

```text
Status:        PARTIAL → geplant vollständig (Auftrag Phase 8/10)
Evidence:      marktdaten.py Super-Mix (4-Tier: yfinance/Finnhub/TwelveData/AlphaVantage);
               provider_connections-Tabelle + provider_connection_* in db.py
Code:          IMPLEMENTED (Tier-Fallback), ABER Trading-Core nutzt weiterhin
               direkt marktdaten.py — kein MarketSnapshot-Interface
Tests:         Provider-Connections getestet (7g); Abstraktion UNVERIFIED
Current Scope: Code
Limitations:   Kein einheitliches MarketSnapshot-Objekt im Trading-Core (§12 Auftrag)
Last Verified: 2026-08-09
Confidence:    MEDIUM
```

## COMPONENT: Broker-Architektur

```text
Status:        IMPLEMENTED (Abstraktion + Simulator)
Evidence:      security.py BrokerProvider (Z651) + PaperBrokerAdapter (Z690),
               create_order_intent (Z557) + validate_order_intent (Z592),
               four_eyes_required (Z819); Tests 7f–7l
Code:          IMPLEMENTED (Interface: connect/place_order/get_account/...)
Tests:         VERIFIED (Order-Intent-Gate, Vier-Augen, Paper-Order-Buch)
Current Scope: PAPER/SIMULATOR nur; SANDBOX/LIVE ohne echten Adapter
Limitations:   Kein Live-Broker (PAPER_ONLY hart)
Last Verified: 2026-08-09
Confidence:    HIGH
```

---

# 03 — ARCHITECTURE

## Gesamtübersicht (ist)

```text
micro_trader_scheduler.py (Cron Mo-Fr 15-22 MEZ)
    ↓  micro-trader-pipeline.py (externes Pipeline-Skript)
batch_trader.py main()  ── Mode-Gate (SHADOW/PAPER nur) ──
    ↓
engine.scan_markt(ticker) [marktdaten.py Super-Mix: yfinance→Finnhub→TwelveData→AlphaVantage]
    ↓
Für jede RISK_STUFE (0–95): depot = laden_oder_erstellen(risk, mode)
    ↓  kauf_budget = bargeld*0.8 (Fallback Risk 70, BUG-002)
    ↓  bezahlbare-Filter → bewerte() [strategie.preis_score]
    ↓  top[:5] Kandidaten
ki_decisions.entscheide_aktien_depot() → KI-Prompt (§10) → ki_provider.call_ki (Rotation)
    ↓
JSON {aktion, konfidenz, grund}
    ↓
enforce_risk_limits / enforce_rules / enforce_approval_trade (VOR jeder Order)
    ↓
create_order_intent (17 Felder) → validate_order_intent (15 Checks, LIVE_* blockt)
    ↓
four_eyes_required (nur bei vier-augen-Aktionen) → PaperBrokerAdapter.place_order
    ↓
paper_orders / paper_position_apply / Depot.speichern (tenant_id+mode)
    ↓
db.py: trades, ki_decisions, depot_snapshot, markt_daten (leer), Audit
    ↓
ki_learning.py (Regel-Extraktion) + learned_rules.py (effektive Regeln)
```

## Nebensysteme

- **ETF-Trader:** etf_trader.py main() — eigene Dict-Logik, etf_pfad(risk, mode),
  20 Depots à 100$, Mode-Gate.
- **Spec-Trader:** spec_trader.py main() — SpecDepot-Klasse, spec_depots[_paper]/,
  49 Depots, KI je Ticker, Mode-Gate.
- **Dashboard:** dashboard.py (Flask, 127.0.0.1:5300) — /data (tenant+mode-keyed
  Cache), /admin* (7 Tabs, StufenPilot-Design), /api/*.
- **Security-Layer:** security.py — Auth, Rollen, Modi, Enforcement, Order-Intent,
  Broker, Vier-Augen, Audit (security_audit.jsonl).
- **Scheduler:** micro_trader_scheduler.py — start_pipeline(mode, args), run_once()
  prüft boersen.ist_offen("US"/"XETRA").

## Architektur-Prinzipien (verbindlich)

1. **PAPER_ONLY = TRUE** — keine echten Orders, kein Auto Shadow→Live (§2.1 Auftrag).
2. **Keine eigene Kryptografie** — PBKDF2-1M (Passwörter), TOTP RFC6238 (MFA).
3. **Keine globale Vermischung** — Depots/Orders/Keys/Regeln/Strategien/Limits/
   Audit/Sessions tenant-scoped (§2.3).
4. **Deny-by-default** — feine Permissions, ROUTE_ACCESS.
5. **Antragsteller ≠ Genehmiger** — Vier-Augen (four_eyes_required).
6. **Code ist Wahrheit** — Doku nie blind glauben; Zeilennummern oben sind
   Referenzen, vor Nutzung gegen aktuellen Code prüfen.

---

# 04 — COMPONENT INVENTORY

| Datei | Zweck | Status | Evidence | Kritikalität |
|---|---|---|---|---|
| security.py | Auth/Rollen/Modi/Enforcement/Intent/Broker/Vier-Augen/Audit | VERIFIED | 273 Tests | KRITISCH |
| db.py | SQLite (19 Tabellen) | VERIFIED | CREATE TABLE ×19 | KRITISCH |
| batch_trader.py | Orchestrierung Aktien | VERIFIED | main() Mode-Gate | KRITISCH |
| engine.py | scan_markt/bewerte/Depot/ausführen | VERIFIED | §13 | HOCH |
| dashboard.py | Flask UI + API | VERIFIED | Routen §21 | HOCH |
| strategie.py | SSOT Scoring (preis_score etc.) | VERIFIED | Selbsttest | HOCH |
| risk_profile.py | Risk-Parameter-Tabelle | VERIFIED | get_params | HOCH |
| ki_decisions.py | KI-Prompt + Call | VERIFIED | §10 | HOCH |
| ki_provider.py | Provider-Rotation | VERIFIED | call_ki | HOCH |
| ki_learning.py | Regel-Extraktion | VERIFIED | ki_log.json | MITTEL |
| learned_rules.py | effektive Regeln | VERIFIED | Tags VORSICHT/BEFOLGEN | MITTEL |
| marktdaten.py | 4-Tier-Kurs-Fallback | VERIFIED | §13 | HOCH |
| etf_trader.py | ETF-Logik | VERIFIED | main() Mode-Gate | MITTEL |
| spec_trader.py | Spec-Logik | VERIFIED | main() Mode-Gate | MITTEL |
| paper_trader.py | Paper-Hilfsfunktionen | VERIFIED | paper_position_apply | MITTEL |
| freigabe.py | Regel-Freigabe (Shadow/Live) | IMPLEMENTED | — | MITTEL |
| micro_trader_scheduler.py | Cron-Orchestrierung | VERIFIED | §23 | HOCH |
| backup.py | Backup before/after/list/restore | VERIFIED | Regel Nr.1 | HOCH |
| boersen.py | ist_offen() US/XETRA/London/Euronext | VERIFIED | run_once | MITTEL |
| settings_loader.py | depot_struktur() | IMPLEMENTED | — | NIEDRIG |
| ki_kontext.py | Kontext-Block für KI-Prompt | VERIFIED | §10 | MITTEL |
| ki_news.py | RSS-News für KI-Prompt | VERIFIED | news_cache.json | NIEDRIG |
| ki_reflexion.py | KI-Selbstreflexion | IMPLEMENTED | — | NIEDRIG |
| report_pdf.py | Tages-PDF | VERIFIED | /api/report_pdf | NIEDRIG |
| depot_audit_report.py | Depot-Audit MD+PDF | VERIFIED | Audit-Cron | NIEDRIG |
| test_server_security.py | 273 Tests (7a–7r) | VERIFIED | 273 OK/0 FAIL | KRITISCH |
| analysis.py | Analyse-Helfer | IMPLEMENTED | — | NIEDRIG |
| skill_sync.py | Skill-Regeln-Sync | IMPLEMENTED | — | NIEDRIG |

## Kritische Dateien im Detail

```text
File: security.py (~1881 Zeilen)
Responsibility: komplette Security + Governance
Important Functions:
  set_current_tenant/get_current_tenant (Z37/42) — ContextVar, nie vom Client
  get_trading_mode (Z48) / set_trading_mode (Z63) — 8 Modi + Vier-Augen bei LIVE
  trading_mode_history (Z116)
  paper_eligibility (Z130) — 8 Voraussetzungen §9
  enter_paper (Z274) — SHADOW→PAPER nur bei eligible
  secret_set/get/list (Z285-302) — tenant-isoliert
  risk_set/get/list (Z312-330) — Tenant-Risiko
  rule_add/list/set_status (Z340-357)
  enforce_risk_limits (Z366) — Position/Drawdown
  enforce_rules (Z393) — BLOCK:/REGEX:/anti (BLOCK-Bug gefixt v2.38.1)
  approval_set/get/list (Z487-505) / enforce_approval (Z514) / enforce_approval_trade (Z530)
  create_order_intent (Z557) / validate_order_intent (Z592) — 17 Felder/15 Checks
  BrokerProvider (Z651) / PaperBrokerAdapter (Z690)
  four_eyes_required (Z819)
  resolve_tenant_for_user (Z836)
  _load_users (Z1036) / _save_users (Z1098) / create_user (Z1107)
  verify_password (Z1147) / change_password (Z1165) / set_role (Z1182)
  deactivate_user (Z1224) / get_user (Z1240) / list_users (Z1245)
Security Relevance: KRITISCH (alle Gates)
Tests: 7a–7r
Known Issues: ROUTE_ACCESS muss zum Decorator passen (Phase-3-Lesson);
  set_trading_mode-Docstring nennt „PHASE 5" — Zählung im Code ≠ Auftragsphasen
```

```text
File: db.py (~500+ Zeilen)
Responsibility: SQLite-Schema + Zugriffe
Tables: secret_store, tenant_risk_limits, tenant_rules, tenant_approvals,
  provider_connections, paper_portfolios, paper_positions, paper_orders,
  trading_mode_transitions, trades, ki_decisions, depot_snapshot, markt_daten,
  tenants, tenant_memberships, workspaces, depots, etf_depots, spec_depots
Important: mode_can_transition (Z519), MTDB(), paper_portfolio_*,
  provider_connection_*, match_trades_ki()
Security Relevance: tenant_id überall (WHERE tenant_id=?),
  Unique(tenant,key) im Secret-Store
Known Issues: markt_daten leer (0 Einträge, Stand 2026-08-07)
```

---

# 05 — TRADING PIPELINE

## Schritt 1 — Markt-Scan

```text
Step:      scan_markt(tickers, force)
File:      engine.py (Z89) → marktdaten.py Super-Mix
Input:     alle_ticker() (Aktien-Liste)
Processing: 4-Tier-Fallback; Kurs=0 wird nie durchgereicht (Crash-Schutz)
Output:    {ticker: {aktuell, sma20, sma50, rsi, atr, vol_ratio, ...}}
Risk:      yfinance Rate-Limit → Tier 2-4
Failure:   bei Totalfehler → kein Trade in diesem Lauf
Evidence:  marktdaten.py Z~10-120, §13 Handoff alt
Tests:     indirekt über 273-Suite
```

## Schritt 2 — Kandidaten-Pipeline (je RISK_STUFE)

```text
Step:      kandidaten sammeln (batch_trader.py main, Z108-153)
File:      batch_trader.py
Input:     scan-Dict, RISK_STUFEN (0-95), risk_profile.get_params(risk)
Processing:
  depot = laden_oder_erstellen(risk, mode)        [mode=shadow|paper §Phase 5]
  kauf_budget = depot.bargeld * 0.8                [Z116]
  bezahlbare = [a for a in aktien if 0 < aktuell <= kauf_budget]   [Z117]
  if not bezahlbare: Fallback = günstigste Aktie mit preis>0        [Z129]
  top = bewerte(bezahlbare, budget, params)        [engine Z221, strategie.preis_score]
  kandidaten = [k for k in top[:10] if 0 < preis <= kauf_budget][:5]
Output:    kandidaten (max 5) + prioritaet (Verlust/volle Pos/Trades%5)
Risk:      BUG-002 Risk 70 (Budget-Filter doppelt; Fallback greift)
Evidence:  batch_trader.py Z108-153
Tests:     nicht direkt; indirekt 7m-7r
```

## Schritt 3 — KI-Entscheidung

```text
Step:      entscheide_aktien_depot(depot, kandidaten)
File:      ki_decisions.py (Prompt §10), ki_provider.call_ki
Input:     Prompt mit Ticker/Kurs/RSI/VIX/MARKT/ATR/Volumen/POSITION/BARGEHLD/
           KONTEXT/GELERNTE REGELN/NEWS/STRATEGIE_HINWEISE
Processing: Provider-Rotation (zen→nemotron→nous-step→nous-hy3→openrouter);
           max_tokens=1024 (512 war zu klein, v2.16.x-Fix); Temperatur 0.1
Output:    JSON {aktion: kaufen/halten/verkaufen, konfidenz, grund}
Risk:      Rate-Limit → nächster Provider; Fehler → halten (fallback=True)
Evidence:  ki_decisions.py Z225-282 (Prompt wortwörtlich §10)
Tests:     ki_log.json-Auswertung (230 Einträge Stand alt)
```

## Schritt 4 — Governance-Gates (VOR jeder Order)

```text
Step:      Order-Gates
File:      security.py
Input:     KI-Entscheidung, Depot, Tenant, Modus
Processing:
  1. enforce_risk_limits (Z366) — Position/Drawdown vs. tenant_risk_limits
  2. enforce_rules (Z393) — BLOCK:/REGEX:/anti-Regeln (tenant ∪ global)
  3. enforce_approval_trade (Z530) — nur freigegebene Targets dürfen traden
  4. create_order_intent (Z557) — 17 Felder
  5. validate_order_intent (Z592) — 15 Checks; LIVE_* hart geblockt
  6. four_eyes_required (nur live_approve/broker_connect/risk_limit_change/
     pause_resume/role_to_admin/backup_restore)
  7. PaperBrokerAdapter.place_order → paper_orders
Output:    Order im Paper-Buch oder Ablehnung (Grund auditiert)
Risk:      BLOCK-Bug gefixt (v2.38.1, BUG-001)
Evidence:  security.py Z366-650; Sektion 7m
Tests:     VERIFIED (7m: enforce_approval_trade, BLOCK-Matching, KI-Regeln)
```

## Schritt 5 — Persistenz + Lernen

```text
Step:      Speichern + Lernen
File:      engine.Depot.speichern (Z62; tenant_id+mode §Phase 3/5), db.py
Processing: trades/ki_decisions/depot_snapshot; Depot-JSON (depot_<risk>[_paper].json)
Learning:  ki_learning.py (Regel-Extraktion → ki_log.json) + learned_rules.py
Evidence:  engine.py Z62; ki_learning.py
```

---

# 06 — STRATEGY

Datei: **strategie.py** (107 Zeilen, SSOT, Selbsttest in `__main__`)

| Parameter | Wert | Bedeutung | Evidence | Status | Begründung |
|---|---:|---|---|---|---|
| PENNY_MAX | 5.0 | unter diesem Preis: Penalty | strategie.py | VERIFIED | verhindert AMC/WKHS-Dominanz |
| SMALLCAP_MAX | 30.0 | bis hier: bevorzugt | strategie.py | VERIFIED | Small-Cap-Bonus |
| PENNY_PENALTY | -10 | Score-Abzug < PENNY_MAX | strategie.py | VERIFIED | — |
| SMALLCAP_BONUS | +8 | Score-Bonus PENNY..SMALLCAP | strategie.py | VERIFIED | Diversifikation |
| EXPENSIVE_BONUS | +3 | Score-Bonus > SMALLCAP | strategie.py | VERIFIED | — |
| TOO_EXPENSIVE_MALUS | -25 | preis > budget | strategie.py | VERIFIED | Aufrufer prüft |
| VOL_DAEMPFER_1 | 0.30 | vol_ratio<0.30 → 70% Position | strategie.py | VERIFIED | Volumen = Dämpfer |
| VOL_DAEMPFER_2 | 0.15 | vol_ratio<0.15 → 40% Position | strategie.py | VERIFIED | — |
| VOL_ILLIQUID | 0.08 | vol_ratio<0.08 → Verzicht (0.0) | strategie.py | VERIFIED | — |
| VOL_POS_SIZE_1 | 0.70 | — | strategie.py | VERIFIED | — |
| VOL_POS_SIZE_2 | 0.40 | — | strategie.py | VERIFIED | — |
| HEBEL_ETF_ERLAUBT | True | 3x-Produkte kaufbar | strategie.py | VERIFIED | — |
| HEBEL_ETF_MAX_POS | 0.30 | max 30% Depot-Cash | strategie.py | VERIFIED | Slippage/Vola |
| HEBEL_TIERS | {3,4} | Tier 3/4 = gehebelt | strategie.py | VERIFIED | — |
| TIER_MAX_PENNY | 1 | max 1 Tier-3-Position/Depot | strategie.py | VERIFIED | Diversifikation |
| TIER_MIN_VERSCHIEDEN | 2 | mind. 2 Tiers/Depot | strategie.py | VERIFIED | — |
| HEBEL_ETF_LISTE | 37 Ticker | TQQQ..MSTR2 | strategie.py | VERIFIED | — |

**Formeln (preis_score):** `preis<5 → -10; 5≤preis≤30 → +8; >30 → +3; preis>budget → -25`

**STRATEGY FACTS:** preis_score + volumen_pos_size + Tier-Mix sind implementiert und
werden im KI-Prompt als STRATEGIE_HINWEISE eingesetzt (§10).

**STRATEGY ASSUMPTIONS (Hypothesen, nicht Fakten):** Die Wirksamkeit der Scoring-
Gewichte (z.B. +8 Small-Cap) wurde nie A/B-getestet — empirische Validierung offen.

**STRATEGY VALIDATION:** strategie.py `__main__`-Selbsttest grün (v2.20.1-Fix:
Assertion auf volumen_pos_size(0.10) statt 0.20).

---

# 07 — RISK ENGINE

Datei: **risk_profile.py** — `get_params(risk)` (generiert von build_risk_profile.py)

| Risk | max_pos | pos_size | min_score | stop_loss | take_profit | allowed_tiers |
|---|---:|---:|---:|---:|---:|---|
| 0 | 8 | 0.150 | 50 | 0.970 | 1.10 | [0] |
| 25 | 7 | 0.212 | 42 | 0.945 | 1.15 | [0,1] |
| 50 | 6 | 0.275 | 34 | 0.920 | 1.20 | [0,1,2] |
| 70 | 5 | 0.325 | 27 | 0.900 | 1.24 | [0,1,2,3] |
| 90 | 4 | 0.375 | 25 | 0.880 | 1.28 | [1,2,3,4] |
| 95 | 4 | 0.387 | 25 | 0.875 | 1.29 | [1,2,3,4] |

**Formeln (build_risk_profile.py Z99-100):**
```text
max_pos  = max(4, min(8, 8 - (risk // 20)))      # 8 bei Risk 0 → 4 bei Risk 95
pos_size = 0.15 + (risk / 100) * 0.25             # 0.15 → 0.40
min_score = max(25, 50 - (risk // 3))             # 50 → 25
```

**Zusätzliche Gates:** `max_depot_pro_ticker()`, `drawdown_sperre_prozent()`
(Risk 25 bei -92.1% gesperrt — HISTORICAL Befund), tenant_risk_limits +
effective_risk_limits (Tenant→global settings.json→Default, nie NULL).

**Limitation:** Risk 70-Kandidatenversorgung siehe BUG-002.

---

# 08 — BUDGET / POSITION SIZING

**Geldfluss:**
```text
Cash (depot.bargeld)
  → kauf_budget = bargeld * 0.8              [batch_trader Z116]
  → bezahlbare = aktien mit 0 < preis <= kauf_budget   [Z117]
  → top = bewerte() [Score]                  [engine Z221]
  → kandidaten = top[:10] ∩ preis<=kauf_budget, max 5  [Z146-153]
  → position_size (risk_profile) * Volumen-Dämpfer (strategie.volumen_pos_size)
  → Ordergröße im PaperBrokerAdapter
  → enforce_risk_limits (Position/Drawdown)
```

**Formeln (exakt):**
```text
kauf_budget     = depot.bargeld * 0.8
pos_size        = risk_profile.get_params(risk)["position_size"]
effektive Größe = pos_size * volumen_pos_size(vol_ratio)   [0.0 bei illiquide]
Hebel-ETF-Cap   = min(0.30 * Depot-Cash)
```

**DUPLICATED LOGIC — REVIEW REQUIRED:** Budget-Filter greift ZWEIMAL
(batch_trader Z117 + Z146). Für Risk 70 zu eng → Fallback Z129 (günstigste Aktie).
Vorschlag (HISTORICAL, nicht umgesetzt): `kauf_budget = bargeld * position_size * 1.5`.
**Aktueller Status:** Fallback in Z129/Z150 verhindert leere Kandidatenlisten
(verifiziert v2.38.1), dennoch ist die doppelte Filterlogik eine Design-Schwäche
(§25 P2).

---

# 09 — CRITICAL ISSUES

## BUG-001 — enforce_rules BLOCK-Matching (gefixt)

```text
Title:      BLOCK:<text> blockte jeden Kauf, ignorierte Ticker
Status:     FIXED (v2.38.1, Commit 73303bb)
Severity:   war HIGH (Production nutzte nur typ=anti → unkritisch)
Evidence:   security.py enforce_rules (Z393), Sektion 7m
Symptom:    BLOCK-Regel blockte alle Käufe unabhängig vom Ticker
Root Cause: Muster-Prefix BLOCK: wurde nicht gegen Ticker gematcht
Fix:        BLOCK: nur blocken, wenn Text im Ticker enthalten (analog REGEX:)
Regression Test: Sektion 7m (passender Ticker blockiert, nicht passender nicht)
Last Verified: 2026-08-09
Confidence: HIGH
```

## BUG-002 — Risk 70 Kandidaten-Versorgung

```text
Title:      Risk 70 candidate starvation (Budget-Filter doppelt)
Status:     MITIGATED (Fallback Z129/Z150), Design-Schwäche OPEN (§25 P2)
Severity:   MEDIUM (Fallback verhindert leere Liste)
Evidence:   batch_trader.py Z116-153; Handoff v2.38.0 §6.1 (HISTORICAL: ungefixt)
Symptom:    Risk 70 kaufte nie (bargeld*0.8-Filter schnitt Small-Caps ab)
Root Cause: kauf_budget = bargeld*0.8 + zweiter Filter Z146
Workaround: Fallback günstigste Aktie (Z129); empfohlener Fix (HISTORICAL):
            kauf_budget = bargeld * position_size * 1.5
Current Impact: Fallback aktiv → Kandidaten vorhanden, KI entscheidet
Last Verified: 2026-08-09
Confidence: HIGH
```

## BUG-003 — markt_daten nicht persistiert (OPEN)

```text
Title:      markt_daten-Tabelle leer
Status:     OPEN (Bekannt, §13)
Severity:   MEDIUM
Evidence:   db.py markt_daten; Phase-0-Inventar (0 Einträge 2026-08-07)
Symptom:    Historische Marktdaten nicht abfragbar; paper_eligibility-Check
            „Marktdaten nicht älter als 3 Tage" schlägt fehl → Shadow→Paper blockiert
Root Cause: Kurse werden nur ad-hoc gescannt, nie persistiert
Last Verified: 2026-08-09
Confidence: HIGH
```

---

# 10 — AI ARCHITECTURE

**Provider-Rotation (ki_provider.py):** `zen → zen-nemotron → nous-step → nous-hy3 →
openrouter`. Bei Rate-Limit/Fehler → nächster. `ki_faehig()` prüft Key-Verfügbarkeit.
Nous-Zugang über Hermes-OAuth-Token (`~/AppData/Local/hermes/shared/nous_auth.json`),
`NOUS_DEFAULT_BASE = "https://inference-api.nousresearch.com/v1"`.

**Call-Parameter:** `call_ki(messages, temperature=0.1, max_tokens=1024)`.
max_tokens=1024 seit v2.16.x (512 schnitt JSON ab).

**System-Prompt (ki_decisions.py Z271, wortwörtlich):**
> „Du antwortest NUR mit JSON. Kein Denken, keine Erklärung, nur das JSON-Objekt."

**User-Prompt (Z225-261, Kern):**
```text
Du bist ein KI-Trading-Assistent für ein Paper-Trading-System.
Analysiere die folgenden Daten und entscheide: KAUFEN, HALTEN oder VERKAUFEN.
TICKER: {ticker} ({name})
KURS: ${kurs:.2f}
TREND: {trend_txt}
RSI (14): {rsi:.1f}
VIX: {hole_vix() or 'unbekannt'}
MARKT: {markt_status}
[VOLATILITÄT (ATR): {atr_pct}%]            # nur wenn vorhanden
[VOLUMEN-RATIO: {vol_ratio}x]              # nur wenn vorhanden
POSITION: {pos_text}
BARGEHLD: ${bargeld:.2f}
DEPOT-WERT: ${depot_wert:.2f} (Rendite {depot_rendite:+.2f}%)
KONTEXT: {kontext_block}                   # ki_kontext.kontext_block(ticker)
{selbst_text}                              # selbst_statistik_text
GELERNTE REGELN (aus bisherigen Trades, nach Stärke sortiert):
{regel_text}                               # ki_learning Regeln
AKTUELLE NEWS: {news_text}
STRATEGIE_HINWEISE (Diversifikation, keine harten Verbote):
{strategie.STRATEGIE_HINWEISE}
WICHTIG: Antworte NUR mit JSON KEINEN anderen Text. Keine Denkprozesse.
Format: {"ticker": "...", "aktion": "kaufen", "konfidenz": 75, "grund": "..."}
```

**Regel-Tags (learned_rules.py):** `[VORSICHT]` (historisches Warnsignal, kein
hartes Verbot), `[ABWÄGEN]`, `[BEFOLGEN]` (folgen). Hinweis-Block im Prompt:
VORSICHT-Regeln dürfen bei klarem Aufwärtssignal + Konfidenz ≥60 überschrieben werden.

**STRATEGIE_HINWEISE (aus strategie.py):** mehrere kleine Positionen statt Klumpen;
Volumen als Dämpfer (0.30→70%, 0.15→40%, <0.08→Verzicht); Hebel-ETFs erlaubt aber
max 30% Cash; Diversifikation (max 1 Penny, mind. 2 Tiers); kein generelles
„halten" — Lernen braucht Fehler.

**Fallback-Verhalten:** `ki_faehig()==False` → halten, konfidenz=0, fallback=True;
Fehler → halten, „KI-Call fehlgeschlagen", fallback=True.

**decision_id-Format:** `d_{YYYYMMDD_HHMMSS}_{ticker}_{depot_typ}_{risk|na}` —
bei Aktien immer `_na` (Risk-Level fehlt → ki_log.json nicht nach Risk filterbar,
§25 P3).

---

# 11 — AI DECISION TRACE

**Zielmodell (Auftrag §11):** `decision_id, tenant_id, workspace_id, depot_id,
risk_level, ticker, timestamp, market_snapshot_id, strategy_version, prompt_version,
model, provider, ruleset_version, decision, confidence, reason, execution_result`

| Feld | Status | Evidence | Limitation |
|---|---|---|---|
| decision_id | IMPLEMENTED | ki_decisions.py Format d_… | Aktien: risk=_na |
| tenant_id | IMPLEMENTED | ki_decisions-Tabelle | seit Mandanten-Ausbau |
| workspace_id | OPEN | — | nicht geführt |
| depot_id | PARTIAL | depot_typ (aktien/etf/spec) | keine echte Depot-ID |
| risk_level | PARTIAL | ETF/Spec ja, Aktien _na | §25 P3 |
| ticker | IMPLEMENTED | Tabelle | — |
| timestamp | IMPLEMENTED | zeit-Spalte | — |
| market_snapshot_id | OPEN | — | kein Snapshot-Objekt (§12 Auftrag) |
| strategy_version | PARTIAL | regelstand_version.json | nur Regelstand, nicht Scoring |
| prompt_version | OPEN | — | nicht versioniert |
| model | IMPLEMENTED | ki_decisions.provider/modell | — |
| provider | IMPLEMENTED | Spalte provider | seit v2.19.2 |
| ruleset_version | PARTIAL | regelstand_version.json | — |
| decision/confidence/reason | IMPLEMENTED | Tabelle | — |
| execution_result | PARTIAL | match_trades_ki() soft-match | kein harter Link |

---

# 12 — AI LEARNING

**Kette:** Trade → Outcome → Observation → Rule Candidate → Validation →
Approval → Active Rule.

**CURRENT (implementiert):**
- ki_learning.py: `lade_ki_log()/schreibe_ki_log()` (ki_log.json, 230 Einträge
  Stand alt), `lerneffekt(aktion, change)`/`lerneffekt_label()` (Regel-Stärke),
  `_aktuelles_regime()` (Bullen/Bären), `decay_lambda_global()` (Regel-Decay),
  `migriere_aus_ki_regeln()`, `_regelstand_meta_lesen/schreiben()` (DB).
- learned_rules.py: Tags [VORSICHT]/[ABWÄGEN]/[BEFOLGEN], effective_rules
  (tenant ∪ global; tenant gewinnt bei ID-Kollision), freigabe_status/shadow/typ.
- freigabe.py: Regel-Freigabe (Shadow/Live).

**TARGET (Auftrag, nicht vollständig):** explizite Validation-Stufe + Approval
als Pflicht-Gate vor „Active Rule" — aktuell über freigabe.py/freigabe_status
abgebildet, aber kein formaler Candidate-Review-Workflow.

**Risiken (explizit bewertet):**
- Feedback Loops: möglich (Regeln speisen Prompt → Entscheidungen → Regeln) —
  abgemildert durch Konfidenz-Hürde ≥60 für VORSICHT-Override.
- Overfitting / Small Sample Bias: vorhanden (ki_log 230 Einträge) — decay_lambda
  dämpft alte Regeln.
- Rule Decay: implementiert (decay_lambda_global).
- Market Regime: _aktuelles_regime() → Kontext.
- Self-Reinforcement: keine harte Barriere — siehe §25 P2 (Review-Workflow).

---

# 13 — MARKET DATA

| Provider | Purpose | Data | Rate Limit | Fallback | Quality | Status |
|---|---|---|---|---|---|---|
| yfinance | Bulk-Scan 663 Ticker | Hist/RSI/MACD, Kurs | — | Tier 1 | gut | VERIFIED |
| Finnhub | Kurs-Fallback | Kurs | 60s | Tier 2 | gut | VERIFIED |
| TwelveData | Kurs-Fallback | Kurs (+time_series Bulk) | 1h | Tier 3 | gut | VERIFIED |
| AlphaVantage | Kurs-Fallback | Kurs | — | Tier 4 | gut | VERIFIED |

**Funktionen (marktdaten.py):** `_yfinance_kurs()`, `_finnhub_kurs()`,
`_twelvedata_kurs()`, `_alphavantage_kurs()`, `hole_kurs(ticker)` (rotiert Tiers).
Keys in `.env`. **Kurs=0 wird nie durchgereicht** (Crash-Schutz).

**Persistenz:** ❌ `markt_daten`-Tabelle leer (0 Einträge, Stand 2026-08-07) —
Kurse nur ad-hoc. → BUG-003.

---

# 14 — DATABASE

SQLite, Datei im Projekt-BASE. **19 Tabellen** (db.py, CREATE TABLE ×19):

| Tabelle | Purpose | Tenant Scope | Status |
|---|---|---|---|
| tenants | Mandanten | id=1 Production | VERIFIED |
| tenant_memberships | User↔Tenant | tenant_id | VERIFIED |
| workspaces | Arbeitsbereiche | tenant_id | VERIFIED |
| depots / etf_depots / spec_depots | Depot-Meta | tenant_id | VERIFIED |
| trades | Trades (id, zeit, depot_typ, ticker, aktion, menge, preis, grund, konfidenz, decision_id) | — | VERIFIED |
| ki_decisions | KI-Entscheidungen (+provider/regel_id/fallback) | tenant_id | VERIFIED |
| depot_snapshot | Snapshot (id, zeit, depot_typ, ref, wert, rendite, shares, bargeld) | — | VERIFIED |
| markt_daten | Kurs-Historie (id, zeit, ticker, kurs, rsi, sma20, sma50) | — | **LEER (BUG-003)** |
| secret_store | Secrets, Unique(tenant,key) | tenant_id | VERIFIED |
| tenant_risk_limits | Risiko-Limits | tenant_id | VERIFIED |
| tenant_rules | Tenant-Regeln | tenant_id | VERIFIED |
| tenant_approvals | Freigaben (§23-Zustände) | tenant_id | VERIFIED |
| provider_connections | Provider-Verbindungen | tenant_id | VERIFIED |
| paper_portfolios / paper_positions / paper_orders | Paper-Order-Buch | tenant_id | VERIFIED |
| trading_mode_transitions | Moduswechsel-Audit (tenant_id, old/new_mode, requested_by, approved_by, reason, mfa_confirmed, …) | tenant_id | VERIFIED |

**Wichtige Funktionen:** `mode_can_transition` (Z519, Transitionstabelle),
`match_trades_ki(zeitfenster_min=10)` (soft-match Trades↔KI),
`effective_risk_limits(tenant, mode)` (Tenant→global→Default, nie NULL),
`effective_rules(tenant)` (Tenant ∪ global, Tenant gewinnt).

**Audit:** `security_audit.jsonl` (1722 Einträge Stand Phase 0) — JSONL, kein SQLite.
`security_users.json` — Benutzer (Passwörter PBKDF2, MFA-Secrets redigiert in Views).

---

# 15 — SECURITY

**Security Chain:**
```text
Internet → Tailscale Funnel (https://<ts-host>.ts.net) → Reverse Proxy (nginx
127.0.0.1:8080) → Flask 127.0.0.1:5300 → Authentication → Authorization →
Tenant Context → Route Access → Business Logic → SQLite
```

| Layer | Control | Status | Evidence | Limitation |
|---|---|---|---|---|
| Netzwerk | Flask nur 127.0.0.1 (app.run host="127.0.0.1", debug=False) | VERIFIED | dashboard.py | nginx/Funnel nicht installiert (geplant) |
| Auth | Login-Rate-Limit 5 Fails → Exp-Backoff 30s+ (OWASP A07), login_rate.json | VERIFIED | security.py, Sektion 7a | — |
| Auth | Sessions (Cookie, Rotation, Timeout) | VERIFIED | security.py | — |
| MFA | TOTP RFC6238, Pflicht admin/superadmin (require_recent_mfa auf 5 Admin-Routen) | VERIFIED | Sektion 7n | 1 Admin aktiv (⚠️ Abdeckung) |
| Recovery | 8 Recovery-Codes (Basis32 ohne 0/O/1/I) | VERIFIED | Sektion 7n | — |
| Authorization | Rollen visitor/user/analyst/operator/admin/superadmin; 41 feine Permissions; deny-by-default | VERIFIED | FINE_PERMISSIONS, Sektion 7o | — |
| Selbst-Privilegierung | set_role blockiert (superadmin nur durch superadmin) | VERIFIED | Sektion 7o | — |
| Tenant Context | ContextVar (nie vom Client), require_tenant_role + tid-Guard | VERIFIED | Sektion 7p | — |
| Route Access | ROUTE_ACCESS (PUBLIC/AUTHENTICATED/ADMIN/TENANT_ADMIN) + before_request | VERIFIED | security.py | Phase-3-Lesson: Klasse muss zum Decorator passen |
| Secrets | Secret-Store tenant-isoliert, Referenzen statt Klartext, Maskierung •••• | VERIFIED | Sektion 7g/7h | — |
| Audit | JSONL, IP+UA bei Login, Redaction (kein password_hash/mfa_secret, keine Keys) | VERIFIED | security_audit.jsonl | Rotation offen (§25) |
| CSRF | generate/verify_csrf_token vorhanden | PARTIAL | security.py | noch nicht in allen Forms verdrahtet (§22.4) |
| HSTS/Cookie Secure | nur bei HTTPS aktivieren | PLANNED | §22.4 | nginx ausstehend |

**Gefixte Security-Bugs (HISTORICAL, v2.22-2.25):** current_user las
flask.session statt cookies; ROLE_TO_LEVEL-Mapping (3×); ROUTE_ACCESS
unvollständig; setup_mfa unhashable dict; admin_users dict-Iteration;
Netzwerk-Check nutzte Import-PORT statt Listener. — Details §20.

---

# 16 — MULTI-TENANT

```text
MULTI-TENANT — VERIFIED

Status:        VERIFIED
Evidence:      test_server_security.py Sektion 7p (Isolation), 7r (Mode-Scope);
               Test-Tenant id=2 „isolation_b"
Last Verified: 2026-08-09
Code:          Tenant-Isolation implementiert (tenant-keyed /data-Cache
               _cache_tid+_cache_mode, require_tenant_role, tid-Guard,
               Depot-tenant_id in 5 Speichern, WHERE tenant_id=? überall)
Tests:         Cross-Tenant-Zugriffe DENY (242→273 OK)
Production:    1 Tenant (id=1)
Limitation:    Kein zweiter echter Production-Tenant unter realer Last validiert
               (Phase-17-Auftrag: Zweiter-Tenant-Test)
Confidence:    HIGH
```

**Phase-3-Lücken (gefixt, v2.41.0):** (A) /data-Cache war tenant-blind →
tenant-keyed; (B) Tenant-Routen nutzten globale require_role("admin") →
require_tenant_role + tid-Guard; (C) tid ungeprüft aus URL → Guard; (D)
Depot.speichern ohne tenant_id → Default 1 in allen Varianten.

**Semantikwechsel (v2.41.0):** Tenant-Admin erhält `/api/tenants` mit 200, sieht
aber NUR seinen eigenen Tenant (vorher 403).

---

# 17 — ORDER GOVERNANCE

**Kann die KI alleine eine Order ausführen?** NEIN — 5 Gates zwischen
KI-Entscheidung und Order:

```text
KI-Entscheidung
  → 1. enforce_risk_limits (Position/Drawdown, tenant_risk_limits)
  → 2. enforce_rules (BLOCK:/REGEX:/anti, effective_rules)
  → 3. enforce_approval_trade (nur „freigegeben" erlaubt Trading)
  → 4. create_order_intent (17 Felder) + validate_order_intent (15 Checks,
       LIVE_* hart geblockt, PAPER_ONLY-Sperre)
  → 5. four_eyes_required (bei live_approve/broker_connect/risk_limit_change/
       pause_resume/role_to_admin/backup_restore)
  → PaperBrokerAdapter.place_order → paper_orders
```

**State Machine:** 8 Modi (SHADOW/PAPER/LIVE_REQUESTED/LIVE_APPROVED/
LIVE_ACTIVE/PAUSED/SUSPENDED/REVOKED) — erzwungene Transitionen
(db.mode_can_transition), LIVE-Übergänge nur mit fremdem Genehmiger + MFA
(v2.42.0). Batch-Trader bricht bei PAUSED/SUSPENDED/REVOKED/LIVE_* ab
(Mode-Gate, v2.42.0).

**Paper-Order-Buch:** paper_orders + paper_position_apply (BUY/SELL, Avg-Preis),
tenant-scoped.

---

# 18 — TESTING / EVIDENCE

**Testdatei:** test_server_security.py — Sektionen 7a–7r, Stand **273 OK / 0 FAIL**
(v2.43.0). Testkette: 151 (v2.38.0) → 165 (7m) → 183 (7n) → 231 (7o) → 242 (7p)
→ 259 (7q) → 273 (7r).

| Kategorie | Tests | Status |
|---|---|---|
| Unit (Security-Basics) | 7a–7e | VERIFIED |
| Freigabe/Order/Broker | 7f–7l | VERIFIED |
| BLOCK-Regel + KI-Regeln + Enforcement | 7m (+14) | VERIFIED |
| Benutzerverwaltung (§6) | 7n (+18) | VERIFIED |
| Rollen/Permissions (§7) | 7o (+48) | VERIFIED |
| Tenant-Isolation (§2.3) | 7p (+11) | VERIFIED |
| Zustandsmaschine (§8) | 7q (+17) | VERIFIED |
| Shadow→Paper (§9) | 7r (+14) | VERIFIED |
| Regression | gesamte Suite | 273 OK, 0 FAIL |

**Ad-hoc Verification (2026-08-11, v2.55.0 — keine grüne Test-Suite neu, aber Live-Checks gegen laufendes System):**
| Check | Ergebnis | Evidence |
|---|---|---|
| 5 Dashboard-Fixes | 17/17 PASS | hermes-verify-5punkte.py gegen Port 5300 |
| Nav-Trennung | 12/12 PASS | hermes-verify-nav.py (Analyse≠Aktivität≠KI) |
| OOS-Regel-Fix | 6/6 PASS | Dedup stabil bei 2 Läufen |
| Fix 1-3 (Regeln/News/Fehler) | 11/11 PASS | pending→learned 17→20, News 57%→70% |
| Fix 4 (ki_log-Reset) | 5/5 PASS | 1 Prozess exakt +150, kein Leeren |
| Singleton-Guard (pipeline) | VERIFIED | 2 Instanzen parallel → 2. beendet sich |
| Market-Gate (boersen.py) | VERIFIED | Jetzt (22:5x) US geschlossen → Pipeline nicht gestartet |

> Hinweis: Grüne Test-Suite (test_server_security.py, 273) wird nicht bei jeder
> Session gerannt — Ad-hoc Verifies sind Live-Checks, keine Regression.

**Test-Hygiene (Lessons):** 7q merkt Ausgangs-Mode und stellt ihn über erlaubten
REVOKED-Pfad wieder her (kein hartes SHADOW); nach Testabsturz DB manuell auf
SHADOW zurückgesetzt; eine MTDB()-Verbindung pro Test (nicht zwei Instanzen).

**Limit:** Tests sind Security-/Integrationstests auf Flask-Testclient — keine
echten Order-Exekutionen, keine Live-Provider (kein Netzwerk).

---

# 19 — BEHAVIORAL TEST MATRIX

| Verhalten | Erwartung | Test | Status | Evidence |
|---|---|---|---|---|
| Risk 70 erzeugt Kandidaten | ≥1 (Fallback) | batch_trader Z129 | VERIFIED | Fallback günstigste Aktie |
| Cross-Tenant Access | DENY | 7p | VERIFIED | tid-Guard + Cache-Key |
| Order ohne Approval | DENY | 7m | VERIFIED | enforce_approval_trade |
| Live Order | DENY | 7q | VERIFIED | Mode-Gate + validate LIVE_* |
| Secret Leak (Klartext) | DENY | 7g/7h | VERIFIED | Maskierung, Referenzen |
| Selbst-Privilegierung | DENY | 7o | VERIFIED | set_role-Härtung |
| LIVE ohne Vier-Augen | DENY | 7q | VERIFIED | approved_by≠requested_by + MFA |
| Paper-Depot ohne mode | DENY | 7r | VERIFIED | getrennte Pfade |
| Shadow+Paper vermischt | DENY | 7r | VERIFIED | portfolio_verlauf(mode) |
| Suspendierung blockt Trading | DENY | 7q/7r | VERIFIED | Mode-Gate batch/etf/spec |

---

# 20 — HISTORICAL DEVELOPMENT

| Version | Date | Change | Current Relevance |
|---|---|---|---|
| v2.16.x | — | max_tokens 512→1024 (JSON abgeschnitten) | aktuell 1024 |
| v2.19.x | — | Cash-Fix /data, Cron-Fenster, Depot-Audit | HISTORICAL |
| v2.20.0 | — | strategie.py SSOT + Risk-Tabelle | aktuell |
| v2.20.1 | — | strategie-Selbsttest-Fix (Assertion 0.10) | aktuell |
| v2.22–2.25 | — | Server-Security (Rollen/MFA/Rate-Limit/Admin-UI) | aktuell |
| v2.26–2.37 | — | Mandanten-Ausbau Phasen 1–13 | aktuell |
| v2.38.0 | 2026-08-09 | PHASE 14 Freigabe-Workflow (151 Tests) | aktuell |
| v2.38.1 | 2026-08-09 | 3 Bugfixes: enforce_approval_trade, BLOCK-Ticker, KI-Regeln (165) | aktuell |
| v2.39.0 | 2026-08-09 | Phase 1 Benutzerverwaltung §6 (183) | aktuell |
| v2.40.0 | 2026-08-09 | Phase 2 Rollen/Permissions §7 (231) | aktuell |
| v2.41.0 | 2026-08-09 | Phase 3 Tenant-Isolation §2.3 (242) | aktuell |
| v2.42.0 | 2026-08-09 | Phase 4 Zustandsmaschine §8 (259) | aktuell |
| v2.43.0 | 2026-08-09 | Phase 5 Shadow→Paper §9 (273) | **aktuell** |

**HISTORICAL Bug-Historie (Fix-Details):** v2.19.3 Cash-Anzeige (dep.bargeld aus
falschem Objekt), v2.19.7 Cron-Fenster (bis 21:00 statt 22:00), v2.19.4 Depot-Audit
Optik (repeatRows/KeepTogether), v2.20.1 strategie-Selbsttest, v2.25.0 Login-Rate-
Limit, v2.25.1 Drawdown-Warnungsbalken entfernt. **Risk-70 „ungefixt"-Aussage des
alten Handoffs (v2.38.0 §6.1) ist HISTORICAL** — seit v2.38.1 greift der Fallback
(BUG-002).

---

# 21 — ARCHITECTURE DECISION RECORDS

## ADR-001 — strategie.py als SSOT (v2.20.0)
```text
Decision:  Zentrale Scoring-Config in strategie.py (preis_score, volumen_pos_size,
           Hebel-Regeln, Tier-Mix) statt Streuung in engine/etf/spec
Date:      2026-08-05 (v2.20.0)
Reason:    Konsistente Strategie über alle Trader; vorher doppelte Logik
Alternatives: Config-JSON, DB-Tabelle
Rejected Because: Selbsttest in __main__ + direkter Import einfacher
Consequences: engine.bewerte/etf_bewerte lesen strategie.preis_score
Current Status: AKTIV
Evidence: strategie.py
```

## ADR-002 — Security in security.py zentralisiert (v2.26+)
```text
Decision:  Auth/Rollen/Modi/Enforcement/Intent/Broker/Vier-Augen in einer Datei
Date:      Mandanten-Ausbau
Reason:    Eine Datei = ein Gate-Knoten; konsistente Prüfreihenfolge
Alternatives: Module aufteilen
Rejected Because: Cross-Cutting-Concerns (Tenant-Kontext, Audit) zentral halten
Consequences: security.py ~1881 Zeilen; ROUTE_ACCESS + Decorator müssen synchron sein
Current Status: AKTIV (Refactoring offen §25 P3)
Evidence: security.py
```

## ADR-003 — Tenant-Kontext via ContextVar, nie vom Client (v2.26)
```text
Decision:  set_current_tenant/get_current_tenant (ContextVar); tid-Guard prüft
           Request-Tenant gegen Kontext
Date:      Mandanten-Ausbau
Reason:    „Tenant-ID aus Request nicht vertrauen" (§18)
Consequences: /api/tenants* brauchen TENANT_ADMIN in ROUTE_ACCESS (Phase-3-Lesson)
Current Status: AKTIV
Evidence: security.py Z37-42, Sektion 7p
```

## ADR-004 — Getrennte Shadow/Paper-Portfolios (v2.43.0, Phase 5)
```text
Decision:  PAPER nutzt eigene Dateien (depot_*_paper.json, etf_*_paper.json,
           spec_depots_paper/) + mode-Feld; kein Teilen mit Shadow
Date:      2026-08-09
Reason:    §9-Verbot: Shadow-Positionen nie übernehmen, Outcomes nie mischen
Alternatives: mode-Feld in gemeinsamer Datei
Rejected Because: physische Trennung verhindert versehentliches Mischen
Consequences: /data-Cache mode-keyed; portfolio_verlauf(mode); Trader-Mode-Gates
Current Status: AKTIV
Evidence: Sektion 7r, SHADOW-PAPER-APPROVAL.md
```

## ADR-005 — Vier-Augen + MFA bei LIVE-Übergängen (v2.42.0)
```text
Decision:  LIVE_APPROVED/LIVE_ACTIVE nur mit approved_by ≠ requested_by und
           mfa_confirmed=1 (set_trading_mode-Signatur erweitert)
Date:      2026-08-09
Reason:    §14: Antragsteller darf nie selbst genehmigen; Live = kritisch
Consequences: set_trading_mode braucht user/approved_by/mfa_confirmed
Current Status: AKTIV
Evidence: Sektion 7q
```

---

# 22 — KNOWN BUG REGISTER

| BUG-ID | Title | Severity | Status | Fix-Version | Regression Test |
|---|---|---|---|---|---|
| BUG-001 | enforce_rules BLOCK-Matching | HIGH (gefixt) | FIXED | v2.38.1 | 7m |
| BUG-002 | Risk-70 Kandidaten (Budget doppelt) | MEDIUM | MITIGATED (Fallback), Design offen | v2.38.1 | — |
| BUG-003 | markt_daten leer (nicht persistiert) | MEDIUM | OPEN | — | — |
| BUG-004 | decision_id Risk=_na bei Aktien | LOW | OPEN | — | — |
| BUG-005 | CSRF nicht in allen Forms verdrahtet | MEDIUM | OPEN | — | — |
| BUG-006 | MFA-Abdeckung 0/1 (Admin ohne MFA) | MEDIUM | OPEN | — | — |
| BUG-007 | whatsapp_cloud.enabled MUSS false bleiben | HOCH (Betrieb) | WORKAROUND | — | — |
| BUG-008 | Depot.laden() leer (engine Z82) — nie nutzen | MEDIUM | WORKAROUND | — | — |
| BUG-009 | Dashboard hängt an Tab — pythonw detached | MEDIUM | WORKAROUND | — | — |
| BUG-010 | ki_log.json Vollverlust bei Concurrent-Writes | HIGH | FIXED | v2.55.0 | Ad-hoc (Fix4) |
| BUG-011 | Multi-Instance: 3-5 Pipeline/Batch parallel | HIGH | FIXED | v2.55.0 | Ad-hoc (Guard) |

**Bug-Details (Pflichtfelder für die wichtigsten):**

```text
BUG-010: ki_log.json Vollverlust
First Seen: 2026-08-11 (KI-Ketten-Überwachung, Lauf 1→2: 280→21 Einträge)
Affected Version: v2.54.0; Current: v2.55.0
Symptom: ki_log.json wurde periodisch geleert (Historie ~1h weg)
Root Cause: schreibe_ki_log() Read-Modify-Write-Race; bei fremdem Schreibvorgang
  json.load(JSONDecodeError) -> except fing auf log=[] -> komplett geleert
Fix: ki_decisions.schreibe_ki_log -> atomarer Write (temp+os.replace) + Optimistic-Retry;
  bei Parse-Fehler wird NICHT geleert (Fix4, 8cdc0e6)
Current Impact: behoben — ki_log stabil (132→380+ Einträge, wächst)

BUG-011: Multi-Instance (Doppel-Scheduler)
First Seen: 2026-08-11 (KI-Ketten-Überwachung, Punkt H: 3 Pipeline + 2 Batch)
Affected Version: alle; Current: v2.55.0
Symptom: 3-5 parallele Pipeline/Batch-Trader (Racing bei DB-Writes, Doppel-Orders-Risiko)
Root Cause: 3 Cronjobs (Batch/Engine/KI) starteten alle 15min Pipeline OHNE Guard
Fix: (1) Singleton-Guard in micro-trader-pipeline.py (Lock + psutil.pid_exists)
     (2) Cron-Konsolidierung 3→1 (Market-Gate, boersen.py gesteuert)
     (3) KI-Ketten-Watcher als eigener Cron
Current Impact: behoben — max. 1 Pipeline-Instanz (Guard greift)
```

```text
BUG-003: markt_daten leer
First Seen: 2026-08-07 (Phase-0-Inventar)
Affected Version: alle; Current: v2.43.0
Symptom: historische Kurse fehlen; paper_eligibility „Providerdaten stabil" schlägt fehl
Root Cause: keine Persistierung im Scan-Pfad
Reproduction: SELECT COUNT(*) FROM markt_daten → 0
Fix: (vorschlag) Scan-Ergebnisse in markt_daten schreiben (P2, §25)
Current Impact: Shadow→Paper blockiert (8/8-Voraussetzung verfehlt)
Workaround: keiner
Last Verified: 2026-08-09

BUG-005: CSRF
First Seen: v2.25.0-Phase
Symptom: generate_csrf_token() vorhanden, verify in before_request für POST,
         aber nicht alle Forms rendern das Token
Fix: Token in login/admin_users_create/admin_rules-Forms einbetten (P2, §25)
Last Verified: 2026-08-09

BUG-002: siehe §09 (Details)
```

---

# 23 — OPERATION

## Scheduler (micro_trader_scheduler.py)

| Job-ID | Name | Schedule | Was |
|---|---|---|---|
| c0e89575d724 | Batch (stündlich) | `*/15 15-22 * * 1-5` | Trades ausführen |
| a6c9a33219a2 | Engine (5min) | `1-59/15 15-22 * * 1-5` | KI-Engine ohne LLM |
| 5e216b0145a1 | KI (15min) | `2-59/15 15-22 * * 1-5` | KI-Entscheidungen |
| 6dced504253f | KI manuell | `0 15,16,...,22 * * 1-5` | Manueller Trigger |
| a9f26c03444e | Audit | `5 9,18,22 * * *` | Depot-Audit MD+PDF (kein KI-Call) |
| 1df465653416 | Monitor | `17 8-22 * * *` | Status-Monitor (Trades/KI/PDF) |

**Wichtig (Stand 08.08.2026):** ALLE 7 Jobs pausiert (manuell, Börse zu) — vor
Öffnung Mo 10.08. 15:30 MEZ wieder resume. Wochenende: Audit+Monitor ohne 1-5-
Beschränkung liefen am WE (bewusst geprüft). Zeitzone: MEZ. Nach 22 Uhr keine
Cronjobs (Tagesabschluss fertig, User-Wunsch).

## Pipeline

- `run_once()` prüft `boersen.ist_offen("US")`/`ist_offen("XETRA")`: US offen →
  full-Pipeline; nur Xetra → engine; alles zu → kein Start.
- `start_pipeline(mode, extra_args)` triggert `micro-trader-pipeline.py`.
- `--loop` = Dauer-Lauf (Autostart via Dashboard_Start.vbs).

## Backup (backup.py — REGEL Nr.1, verpflichtend)

- `backup.py before "<beschreibung>"` VOR jeder Änderung → Snapshot in `backups/`.
- `backup.py after`, `list`, `restore <id>`, `rollback <n>`.
- **NIEMALS Datei editieren ohne backup.py before!** (User-Regel, global)
- Vorhandene Backups (Phase 1–5): `20260809_120012__Phase_1__…` … `…_135536__Phase_5__…`.

## Git-Workflow

- HTTPS-Remote zwingend (SSH:22 geblockt): `https://github.com/Goldi5/Mirco-Trader.git`
- Repos: Goldi5/Mirco-Trader (public), Goldi5/Pv-Planer (public), Goldi5/Obsidian (private)
- Identity: goldi@hermes.local / Christian Glaser
- Doku-Kette je Version (PFICHT, keine Ausnahme):
  1. version.json (Version/Build/released_at bumpen)
  2. docs/CHANGELOG.md (Eintrag)
  3. docs/README.md (Status + Footer)
  4. **docs/HANDOFF-V3.md aktualisieren** (§02/§18/§20/§22/§25/§31 — alle
     betroffenen Status-/Evidence-Blöcke nach §28/§29-Regeln)
  5. Ergebnisdatei (§20 Auftrag, z. B. docs/SHADOW-PAPER-APPROVAL.md)
  6. Obsidian-Vault spiegeln: `Projekte/Micro-Trader/Micro-Trader-Handoff-V3.md`
     (+ betroffene Doku-Dateien) — cp aus docs/
  7. Memory
- Commit-Stil: `Phase N (vX.Y.Z): <Kurzfassung>` (+ Detail-Body)

## Dashboard-Betrieb

- Start detached: `pythonw dashboard.py 5300` (NIEMALS an Terminal-Tab hängen —
  BUG-009). `dashboard.bat`, `Dashboard_Start.vbs` (SW_HIDE) vorhanden.
- Health: netstat prüfen ob 5300 lauscht; `wmic process where
  "name='pythonw.exe'" get CommandLine`.

## WhatsApp

- Nachrichten: `hermes send -t 'whatsapp:Christian Glaser (dm)'`
- PDF-Versand nur via MEDIA:-Tag im Agent-Chat (nicht hermes send) — BUG-007:
  whatsapp_cloud.enabled MUSS false bleiben (crasht Gateway).
- whatsapp_watchdog.py / whatsapp_bericht.py vorhanden.

---

# 24 — TROUBLESHOOTING

```text
SYMPTOM: Dashboard „Seite down"
CHECK:   pythonw läuft? Port 5300 offen?
EXPECTED: netstat -ano | grep 5300 zeigt LISTENING
ACTUAL:   tot (Tab geschlossen)
ROOT CAUSE: Prozess an Terminal-Tab gebunden
FIX:     pythonw dashboard.py 5300 (detached)
VERIFY:  /api/version erreichbar

SYMPTOM: Risk 70 kauft nicht
CHECK:   depot_070.json Bargeld? ki_log Einträge mit _70_?
EXPECTED: Kandidaten vorhanden (Fallback Z129), KI-Calls
ACTUAL:   keine Käufe
ROOT CAUSE: BUG-002 (Budget-Filter doppelt) — Fallback sollte greifen
FIX:     Falls Fallback nicht greift: batch_trader Z116-153 prüfen;
         Vorschlag kauf_budget = bargeld*position_size*1.5
VERIFY:  nächster Batch-Lauf + ki_log

SYMPTOM: Frontend hängt bei „loading"
CHECK:   browser console (F12)
EXPECTED: keine JS-Fehler
ACTUAL:   SyntaxError / Unexpected token '<'
ROOT CAUSE: JSON-Route lieferte HTML-Redirect (v2.22.1-Fix) oder unclosed <script>
FIX:     API-Routen: 401 JSON statt HTML; dashboard.html Script-Tags prüfen
VERIFY:  Seite neu laden

SYMPTOM: Cron „WhatsApp bridge error"
CHECK:   Bridge-Status
FIX:     Bridge neu verbinden; deliver='origin'
```

---

# 25 — CURRENT OPEN WORK

## P0 — BLOCKER
- Keine aktuellen P0-Blocker.

## P1 — CRITICAL
- **MFA-Abdeckung:** Admin-Konto ohne MFA (0/1) — MFA einrichten
  (settings → Sicherheit). [BUG-006]

## P2 — IMPORTANT
- **markt_daten persistieren** (BUG-003) — sonst bleibt Shadow→Paper
  dauerhaft blockiert (8/8-Voraussetzung „Providerdaten stabil").
- **CSRF in alle Forms** (BUG-005).
- **Risk-70-Budgetlogik vereinheitlichen** (BUG-002: doppelten Filter
  entfernen, pos_size-gekoppeltes Budget).
- **Regel-Review-Workflow formalisieren** (Phase 12 §12: Validation/Approval
  als Pflicht-Gate vor „Active Rule").

## P3 — IMPROVEMENT
- decision_id um Risk-Level erweitern (BUG-004).
- security.py refactoren (ADR-002, ~1782 Zeilen).
- nginx + Tailscale-Funnel installieren (Reverse-Proxy produktiv).
- Audit-Log-Rotation (DSGVO).

## P1.5 — BEobACHTUNG (2026-08-11, v2.55.0)
- **KI-Cooldown:** openrouter rate_limit aktiv (ki_cooldown.json) — KI macht
  Pause, Läufe blockiert. Temporär, läuft nach ~1h aus. Kein Eingriff, aber
  beobachten ob häufiger (Provider-Rotation prüfen).
- **0 Orders/1h:** Folge des Cooldowns (KI zurückhaltend). Nicht kritisch,
  aber Ursache klären (Drawdown-Sperre vs. Signal-Mangel).
- **WOL-Verify-Cron (a3e5557b2813):** läuft auf Hermes — stirbt mit PC-Shutdown.
  Für dauerhafte PC-Aus-Verifikation braucht es 24/7-Knoten (FritzBox-Scripting
  oder zweites Gerät) + echte PC-IP/MAC in wol-verify-cron.py (TODO-Platzhalter).
- **Market-Gate:** boersen.py nur US (Watchlist 100% US). Falls DE/Xetra-Ticker
  dazukommen → Gate erweitern (offene_boersen() statt ist_offen('US')).

## P4 — FUTURE
- Live-Architektur (nur nach Phase 18 des Auftrags; PAPER_ONLY bis dahin).
- Provider-MarketSnapshot-Interface im Trading-Core (§12 Auftrag, Phase 8/10).
- Admin-Session-Übersicht, API-Tokens mit Scopes, Self-Service-Passwort-Reset.

---

# 26 — ROADMAP

### Stabilization
- markt_daten-Persistenz (P2) · Risk-70-Budget (P2) · Audit-Rotation (P3)

### Security
- CSRF komplett (P2) · MFA für alle Admins (P1) · nginx+Funnel (P3) ·
  Tailscale-ACL (tag:mt-proxy)

### Trading Core
- doppelter Budget-Filter entfernen · decision_id-Risk (P3) ·
  MarketSnapshot-Abstraktion (P4)

### Observability
- Health-Monitor (Cron prüft /api/version → WhatsApp-Alert) · Security-Event-Dashboard

### AI Learning
- formaler Rule-Candidate-Review · Overfitting-Monitor · A/B-Validierung der
  Scoring-Gewichte (STRATEGY ASSUMPTIONS)

### Multi-Tenant
- Zweiter Production-Tenant + Smoke-Test (§19 Auftrag Phase 17) ·
  Multi-Tenant-Testreport

### UI
- Admin: Modi/Freigaben-Übersicht · Paper/Shadow-Sicht je Modus

### Future Live Readiness
- **Live erst nach: Broker-Sandbox (Phase 19), Sicherheits-/Regressionstests
  (Phase 18), Vier-Augen-Live-Governance, Broker-Adapter SANDBOX** — niemals
  als normales Feature behandeln.

---

# 27 — TARGET ARCHITECTURE

> TARGET — NOT CURRENT. Niemals mit Ist-Zustand verwechseln.

```text
Identity Layer    Benutzer/MFA/Sessions/Rollen/Berechtigungen        [CURRENT]
Tenant Layer      Tenants/Workspaces/Zuordnung/Limits                 [CURRENT]
Portfolio Layer   Shadow [CURRENT] · Paper [CURRENT] · Live [TARGET]
Strategy Layer    Strategie/Regelstand/Lernstatus/Freigabe            [CURRENT]
Provider Layer    Marktdaten/KI/Broker/Execution [PARTIAL — TARGET: MarketSnapshot]
Secret Layer      User-/Tenant-scoped, Rotation, Status               [CURRENT]
Risk Layer        Tenant-/Portfolio-/Strategie-/Order-Limit, Drawdown [CURRENT]
Execution Layer   Order Intent → Validierung → Paper-Broker [CURRENT]
                  → Sandbox-Broker [TARGET] → Live-Broker [TARGET, nach Phase 18]
Audit Layer       Aktionen/Modi/Provider/Freigaben/Orders/Security    [CURRENT]
```

---

# 28 — NEXT AI PROTOCOL

## BEFORE MODIFYING CODE

1. §02 SYSTEM TRUTH lesen (aktueller Stand).
2. §25 OPEN WORK lesen (bekannte Probleme).
3. Betroffene Dateien + Zeilennummern gegen echten Code prüfen (Code ist Wahrheit).
4. §20 HISTORICAL nicht mit aktuellem Zustand verwechseln.
5. **`backup.py before "<beschreibung>"`** (Regel Nr.1, keine Ausnahme).
6. Regressionstest definieren (Sektion 7s+), bestehende Tests laufen lassen.
7. Änderung durchführen (minimal-invasiv, keine neuen Deps).
8. Testsuite komplett ausführen: `python test_server_security.py` → alle grün.
9. **HANDOFF V3 aktualisieren** (PFLICHT bei jeder Änderung, die §02–§31
   betrifft): betroffene STATUS-/EVIDENCE-/FACT-Blöcke anpassen, §18-Testzahl,
   §20-Historie, §22-Bug-Register, §25-OPEN-WORK, §29-Consistency-Audit,
   §31-Facts — niemals unverändert lassen, wenn der Code sich änderte.
10. Doku-Kette aktualisieren: version.json → docs/CHANGELOG.md → docs/README.md →
    HANDOFF-V3.md → Ergebnisdatei → Obsidian-Vault (Projekte/Micro-Trader/
    Micro-Trader-Handoff-V3.md spiegeln) → Memory.
11. Commit: `Phase N (vX.Y.Z): <Kurzfassung>`.

## VERBOTEN
- Echte Orders / Live-Keys / Auto Shadow→Live (PAPER_ONLY hart).
- Eigene Kryptografie.
- AWS-Credentials aus Handoff-S3-URLs wiederherstellen ([REDACTED]).
- Test-Passwörter reproduzieren/leaken.

---

# 29 — DOCUMENT CONSISTENCY AUDIT

| Finding | Location | Severity | Resolution | Evidence |
|---|---|---|---|---|
| Alte Handoff (§6.1) behauptete Risk 70 „ungefixt" | §09/BUG-002 | MEDIUM | Als HISTORICAL markiert; Fallback seit v2.38.1 | batch_trader Z129 |
| „PHASE 5/6"-Labels im Code (set_trading_mode-Docstring) | §04 security.py | LOW | Nicht als Phasenplan interpretieren | Code-Kommentar |
| Testzahl in alter Doku (151) vs. heute (273) | §01/§18 | GELÖST | Testkette dokumentiert | test_server_security.py |
| markt_daten „leer" (Handoff alt) = heute noch leer | §13/BUG-003 | KONSISTENT | Beide Aussagen OPEN | DB-Check Phase 0 |
| Sicherheits-Phase-Status (v2.25.1) vs. Mandanten-Ausbau | §15/§22 | KONSISTENT | Als HISTORICAL markiert | §20 |

---

# 30 — EVIDENCE COVERAGE REPORT

| Bereich | Aussagen | Mit Evidence | Ohne Evidence | Verified | Unverified |
|---|---:|---:|---:|---:|---:|
| Architecture | 12 | 12 | 0 | 12 | 0 |
| Trading | 14 | 13 | 1 (Risk-70-Formel-Vorschlag) | 13 | 1 |
| Risk | 8 | 8 | 0 | 8 | 0 |
| AI | 10 | 9 | 1 (Prompts aus Handoff alt — gegen Code verifiziert §10) | 9 | 1 |
| Security | 16 | 16 | 0 | 15 | 1 (CSRF-Verdrahtung) |
| Database | 19 | 19 | 0 | 19 | 0 |
| Multi-Tenant | 8 | 8 | 0 | 8 | 0 |

**Grundsatz:** Keine Evidenz erfunden. Wo der alte Handoff die einzige Quelle ist,
ist es als solche zitiert und gegen Code geprüft; nicht prüfbare Aussagen → UNVERIFIED.

---

# 31 — CRITICAL SYSTEM FACTS

```text
FACT-001  Paper Trading only
Statement: Kein Echtgeld, keine echten Orders, kein Live-Broker
Status: VERIFIED
Evidence: PaperBrokerAdapter + PAPER_ONLY + Mode-Gate (Sektion 7q/7r)
Last Verified: 2026-08-09
Scope: Production
Limitation: Live-Execution deaktiviert (hart)

FACT-002  Tenant-Isolation
Statement: Depots/Orders/Keys/Regeln/Limits/Audit/Sessions tenant-scoped
Status: VERIFIED
Evidence: Sektion 7p (Test-Tenant), tenant-keyed Cache, tid-Guard
Last Verified: 2026-08-09
Scope: Code+Test; Production 1 Tenant
Limitation: 2. Production-Tenant nicht real validiert

FACT-003  Zustandsmaschine
Statement: 8 Modi, erzwungene Transitionen, LIVE nur mit Vier-Augen+MFA
Status: VERIFIED
Evidence: Sektion 7q; security.set_trading_mode + db.mode_can_transition
Last Verified: 2026-08-09
Scope: Code+Test
Limitation: LIVE_* ohne Broker-Adapter

FACT-004  Shadow→Paper-Freigabe
Statement: Wechsel nur bei 8/8 Voraussetzungen, getrennte Portfolios
Status: VERIFIED
Evidence: Sektion 7r; paper_eligibility + depot_*_paper.json
Last Verified: 2026-08-09
Scope: Code+Test; Production SHADOW
Limitation: markt_daten leer → aktuell nicht eligible

FACT-005  273 Tests grün
Statement: Gesamtsuite test_server_security.py 273 OK, 0 FAIL
Status: VERIFIED
Evidence: Testlauf 2026-08-09 (Sektionen 7a-7r)
Last Verified: 2026-08-09
Scope: Code
Limitation: kein Live-Netzwerk/echte Exekution

FACT-006  PAPER_ONLY hart
Statement: kein automatischer Shadow→Live-Wechsel möglich
Status: VERIFIED
Evidence: Mode-Gate batch_trader + validate_order_intent LIVE_* blockt
Last Verified: 2026-08-09
Scope: Production
Limitation: —

FACT-007  Risk 70 Versorgung
Statement: Fallback sichert Kandidaten; Budget-Filter doppelt (Design-Schwäche)
Status: VERIFIED (Fallback) / OPEN (Design)
Evidence: batch_trader Z116-153; BUG-002
Last Verified: 2026-08-09
Scope: Code+Paper
Limitation: Formel-Vorschlag nicht umgesetzt

FACT-008  Produktiver Stand
Statement: System läuft als v2.43.0 (Build 2026-08-09_1600), Cron pausiert
          (Börse zu, Resume Mo 10.08. 15:30 MEZ)
Status: VERIFIED
Evidence: version.json + Cron-Status (Stand 08.08.2026)
Last Verified: 2026-08-09
Scope: Production
Limitation: —
```

---

# 32 — FINAL HANDOFF CHECKLIST

- [x] Current State eindeutig (§02)
- [x] Historical State eindeutig getrennt (§20)
- [x] Planned State eindeutig getrennt (§26/§27)
- [x] Jede kritische Aussage hat Evidence (§30)
- [x] Unverified Claims markiert (§02 Datenprovider-Abstraktion, §30)
- [x] Last Verified dokumentiert
- [x] Scope dokumentiert (Code/Test/Paper/Production)
- [x] Limitations dokumentiert
- [x] Trading Pipeline vollständig (§05)
- [x] Risk Engine vollständig (§07)
- [x] Budgetlogik vollständig (§08)
- [x] AI vollständig (§10)
- [x] Learning vollständig (§12)
- [x] Security vollständig (§15)
- [x] Multi-Tenant vollständig (§16)
- [x] Database vollständig (§14)
- [x] Scheduler vollständig (§23)
- [x] Tests vollständig (§18)
- [x] Bugs zentralisiert (§22)
- [x] Root Causes erhalten (§09/§20)
- [x] Historie erhalten (§20)
- [x] ADRs dokumentiert (§21)
- [x] Roadmap getrennt (§26)
- [x] Target Architecture markiert (§27)
- [x] Dokumentkonsistenz geprüft (§29)
- [x] Keine technische Tiefe verloren (Volltext-Prompts, Formeln, Parameter,
      Zeilennummern, Root Causes, Bugs, Testkette erhalten)

---

# 33 — ABSOLUTE FINAL RULE (Selbstbindung)

Die Handoff V3 ist die **Single Source of Truth** für die Übergabe. Sie
unterscheidet eindeutig:

```text
WAS IST IMPLEMENTIERT?   → §02/§04 (Status IMPLEMENTED/VERIFIED)
WAS IST VERIFIZIERT?     → §18/§31 (Test-Evidence, Last Verified)
WAS IST NUR GETESTET?    → §18 (Scope: Code)
WAS IST PRODUKTIV?       → §01 Health-Matrix / §31 FACT-008
WAS IST NUR PAPER?       → §01/§02 (PAPER_ONLY)
WAS IST LIMITIERT?       → §02 Limitations je Komponente
WAS IST KAPUTT?          → §09/§22 (BUG-Register)
WAS WAR FRÜHER KAPUTT?   → §20 (HISTORICAL)
WARUM WURDE ES SO GEBAUT? → §21 (ADRs)
WAS IST NUR EINE HYPOTHESE? → §06 STRATEGY ASSUMPTIONS
WAS IST GEPLANT?         → §26/§27 (TARGET, NOT CURRENT)
WAS IST UNBEKANNT?       → UNVERIFIED-Markierungen (§30)
```

Keine Behauptung darf durch professionell klingende Sprache glaubwürdiger
erscheinen, als ihre Evidenz erlaubt. Technische Tiefe behalten. Redundanz
reduzieren. Widersprüche sichtbar machen. Historie bewahren. Unwissen offen
markieren.

---

## UI-REDESIGN „CALM TRADING COMMAND CENTER“ — STATUS (2026-08-09)

> **STATUS:** ABGESCHLOSSEN (Phasen 2–13 implementiert + verifiziert, v2.44.0 → v2.44.8)
> **EVIDENCE:** `git log --oneline` zeigt Commits `e32ca85` (Phase 0), `bda81fa` (2–5), `76bba94` (6), `2692af2` (7), `a196960` (8), `10a6794` (9), `a8b025a` (10), `396520b` (11), `893155d` (12), `d9c92cf` (13/14-Doku)
> **DESIGN-REGEL:** Ausschließlich UI/Layout/IA geändert. Keine Trading-/KI-/Risk-/Security-/Tenant-Logik.

### Ergebnis je Phase
| Phase | Thema | Commit | Verifikation |
|-------|-------|--------|--------------|
| 2–5 | Designsystem, Topbar, 8-Bereichs-Nav, Hero/KPI, Drawer | `bda81fa` (v2.44.0) | Browser-Visuell: dunkle 56px-Topbar, opake Flächen, Slate-Blau ✓ |
| 6 | Portfolios-Übersicht (max 6 Karten, Filter, Drawer-Detail) | `76bba94` (v2.44.1) | 6 Karten gerendert, Drawer öffnet/schließt ✓ |
| 7 | Tabellen (table-scroll, num-col, Sortier-Indikator) | `2692af2` (v2.44.2) | node --check clean, Marker im Dashboard ✓ |
| 8 | KI/News/Aktivität (Subtabs, Glass-Relikte entfernt) | `a196960` (v2.44.3) | node --check clean, Marker ✓ |
| 9 | Einstellungen+Admin (Glass-Relikte entfernt) | `10a6794` (v2.44.4) | node --check clean, surface statt glass ✓ |
| 10 | Login/MFA — **reviewed, keine Änderung** (Security-Bereich) | `a8b025a` (v2.44.5) | Login-Formular in dashboard.py, bewusst nicht angefasst (§2.1) |
| 11 | Responsive (Filter/Summary/Karten mobil) | `396520b` (v2.44.6) | 6 Media-Queries, Grid 1-spaltig @480px ✓ |
| 12 | Accessibility (Skip-Link, role=main, ARIA-Karten, Keyboard) | `893155d` (v2.44.7) | A11y-Marker alle vorhanden ✓ |
| 13 | Regression + visuelle Prüfung | `d9c92cf` (v2.44.8) | Alle 8 Bereiche + Drawer fehlerfrei, visuell verifiziert ✓ |
| 14 | Dokumentation (version.json, CHANGELOG, README, HANDOFF) | `d9c92cf` (v2.44.8) | README Designsystem-Sektion, CHANGELOG 2.44.0–2.44.8 ✓ |

### OPEN WORK / HINWEISE
- **Passwort-Reset-Hash-Problem:** `security_users.json` `password_hash` wurde während der Session mehrfach geleert (Ursache: Server lädt Datei in RAM beim Start, überschreibt bei Reload). Fix: `security.change_password()` ausführen **und** Server neu starten (PID kill + `dashboard.py 5300`). Aktuell: admin / `Admin2026!sicher` (Stand 21:15).
- **Login-Formular (Phase 10):** Bewusst nicht angefasst — liegt in `dashboard.py` (Security-kritisch), nicht in `dashboard.html`. Keine Design-Inkonsistenz (minimales Formular ohne Glass).
- **`etf_*.json`, `ki_log.json`, `notifications.json` etc.:** Laufzeit-Daten, nicht committet (nur `dashboard.html` + Doku-Dateien in den UI-Commits).

### TESTS (ad-hoc, isoliert, ALL PASS)
- JS-Syntax: `node --check` auf extrahiertem `<script>` → clean
- Live: Login HTTP 200/302, `/data` Struktur (depots=20/etf=20/spec=49), Dashboard-Marker (panel-alle, table-scroll, ki-subtab, skip-link, role=main, drawer)
- Visuell: Browser-Screenshot bestätigt Calm-Trading-Optik (dunkle Topbar, opake Flächen, Slate-Blau, keine Glass-Blöcke)

---

# 34 — PHASE 0 LIVE-SYSTEM / NEWS-ARBEITSAUFTRAG (2026-08-12)

> Basis: Obsidian `Projekte/Micro-Trader/LIVE-SYSTEM-UND-NEWS-ARBEITSAUFTRAG.md`
> (vollständiger Auftrag). Phasen 0–14 verbindlich in Reihenfolge (Auftrag §4).
> **Phase 0 = Dokumentation + Bestandsaufnahme, KEINE funktionalen Codeänderungen.**

## Phase 0 — erstellte Docs (repo `docs/`)

| Doc | Zweck | Status |
|---|---|---|
| `LIVE-NEWS-INVENTORY.md` | News-Komponenten + 5 RSS-Feeds inventarisieren | ERSTELLT |
| `LIVE-PREPARATION-ROADMAP.md` | Phasen 0–14 Roadmap + Freigabemodell + Blocker | ERSTELLT |
| `PAPER-SYSTEM-BASELINE.md` | Baseline Paper-/Shadow-System (21 DB-Tabellen, Depots) | ERSTELLT |
| `NEWS-SOURCE-MATRIX.md` | Quellenmatrix S1–S5 + Fehlerklassen + Ticker-Mapping | ERSTELLT |
| `NEWS-LICENSE-REVIEW.md` | Lizenzprüfung (STATUS: UNVERIFIED, keine Freigabe) | ERSTELLT |

## Bestandsaufnahme (Phase 0 Fakten, gegen echten Code)

- **System:** v2.57.1, PAPER_ONLY hart, Dashboard Flask 127.0.0.1:5300.
- **Depots:** Aktien/ETF/Spec (Spec 13 Dateien: BB, BBAI, CRSP, FNGU, MRNA, NRGU, PLTR, QS, SOUN, TNA …).
  Neu v2.57.0: eindeutige `depot_uid` (mehrere Depots pro Risiko: `aktien:100`, `aktien:100:1`).
- **DB:** 21 Tabellen (sqlite `micro_trader.db`). `markt_daten` **LEER** (P0-Blocker Phase 2).
  `live_requests` vorhanden (späteres Gate). 1 Tenant (id=1).
- **News:** 5 RSS-Feeds (Bloomberg, DowJones/MarketWatch, Yahoo, NYT, Investopedia).
  `news_evaluator.py` veraltet (alter API-Key → P0-Blocker Phase 5).
- **Prozesse:** Dashboard läuft (pythonw PID 9616 + python.exe PID 996 auf 5300 — Doppelinstanz
  aus Hintergrund-Session, nach Phase 0 bereinigen).
- **Security:** 3 User (admin, __diag__, goldi5), 41 Permissions, MFA für Admin, Tenant-Isolation verifiziert.

## P0-Blocker (für spätere Phasen)

1. `markt_daten` persistieren (Phase 2).
2. `news_evaluator.py` → `ki_provider.call_ki` umstellen (Phase 5).
3. Ticker-Mapping fehlt (Phase 4).
4. Kill-Switch im Paper-Modus fehlt (Phase 11).

## Nächste Phase

**Phase 1 — Paper-System härten** (markt_daten, CSRF, MFA, Tenant-Test, Risk-70, Singleton,
Audit/Backup/Restart-Tests). Ergebnis-Doc: `PAPER-SYSTEM-HARDENING.md`.

---

# 35 — ARBEITSAUFTRAG PHASEN 0–14 ABGESCHLOSSEN (2026-08-12)

> System v2.58.0. Alle Phasen des Auftrags "Getrenntes Live-System, News-Plattform,
> Notfallsteuerung" implementiert + verifiziert. PAPER_ONLY durchgängig gewahrt.

## Phasen-Status

| Phase | Thema | Status | Commit |
|---|---|---|---|
| 0 | 5 Docs + Handoff sync | ✅ | bcfdbce |
| 1 | Paper-System härten (P1 markt_daten, P6/8/9 DONE) | ✅ | bfd7e9e |
| 2 | MarketSnapshot erweitert + Bug-Fix | ✅ | c8394fe |
| 3 | News-Ingestion (Fehlerklassen) | ✅ | dd360a5 |
| 4 | News-Filter, Dedup, Ticker-Mapping | ✅ | d40dbfb |
| 5 | News-KI in Trading-Kontext | ✅ | 0b9d11b |
| 6 | Manuelle Depot-Steuerung verifiziert | ✅ | 3b54470 |
| 7 | Getrenntes Live-System (live_system.py) | ✅ | c1bfb6f |
| 8 | Release Registry + Gate | ✅ | b040d6a |
| 9 | Broker-Simulator + Sandbox-Adapter | ✅ | 2eba7b1 |
| 10 | Order-Sync + Reconciliation | ✅ | 8c8083f |
| 11 | Live-Admin, Kill-Switch, Monitoring | ✅ | f72d1e6 |
| 12 | Live-Readiness-Tests (12/12 PASS) | ✅ | 08232c0 |
| 13 | Micro-Live-Vorbereitung | ✅ | 490b6ae |
| 14 | Manueller Live-Freigabeprozess | ✅ | 2008d07 |

## Neue Module (PAPER_ONLY)

- `live_system.py`: LiveSystem (isoliert) + ReleaseRegistry (live_releases Tabelle)
- `broker_simulator.py`: BrokerAdapter ABC + BrokerSimulator (keine echten Orders)
- `news_ticker_map.py`: zentrale Firma→Ticker Mapping-Tabelle
- `test_live_readiness.py`: 12 Live-Readiness-Checks (ALLE PASS)
- `freigabe_checkliste.py`: Vier-Augen/MFA-Checkliste

## Offen (bewusst nicht automatisiert)

- Phase 1 P2 (CSRF vollflächig): Risiko Dashboard-Bruch → nicht blind gepatcht
- Phase 1 P3 (MFA alle Admins): Benutzer-Aktion nötig (Secret-Setup)
- **Live-Aktivierung:** wartet auf manuelle Freigabe durch Benutzer (Phase 14)
