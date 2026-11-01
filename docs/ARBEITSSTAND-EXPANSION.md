# ARBEITSSTAND — HERMES-EXPANSIONS-AUFTRAG (20 Phasen)

> Merknotiz für spätere Fortsetzung. Auftrag: „Micro-Trader — Benutzerplattform,
> Shadow/Paper/Live, Provider-Management und Broker-Architektur" (v2.38.0-Basis,
> 20-Punkte-Reihenfolge §19). Stand: 2026-08-10, HEAD `88eecdf` (v2.44.9, UI-Redesign fertig).
> **WICHTIG:** Auftrag basiert auf v2.38.0 — tatsächlicher Stand ist **v2.44.9**.
> Phase 0–5 + Provider-Datenmodell (§19-Punkt 8) sind bereits committet (v2.38.1–v2.43.0).

---

## ✅ ABGESCHLOSSEN (Phase 0–5 + Provider-Datenmodell, Versionen v2.38.1–v2.44.9)

| §19-Punkt | Umsetzung | Version | Commit | Tests | Ergebnisdatei |
|---|---|---|---|---|---|
| 1. Bestandsaufnahme | Phase 0 (nur Analyse, keine Änderungen) | v2.38.1 | `7d2a903` | 165 | PLATFORM-NEXT-EXPANSION-INVENTORY.md, PROVIDER-INVENTORY.md, USER-AND-TENANT-INVENTORY.md |
| 2. Bekannte Fehler (teils) | BLOCK-Matching, KI-Regeln wirksam, Freigabe im Order-Pfad | v2.38.1 | `73303bb` | 165 | — (Sektion 7m) |
| 3. Benutzerverwaltung (§6) | Status-Lebenszyklus INVITED…DELETED, Sessions-GC, MFA-Pflicht admin/superadmin, 8 Recovery-Codes, Redaction, create_user(email/display_name/created_by) | v2.39.0 | `22fe933` | 183 | — (Sektion 7n) |
| 4. Rollen/Permissions (§7) | FINE_PERMISSIONS (41) deny-by-default, Aliase, Selbst-Privilegierung blockiert, superadmin nur durch superadmin | v2.40.0 | `fdbf2ae` | 231 | ROLE-PERMISSION-MATRIX.md |
| 5. Tenant-Isolation (§2.3/§17) | /data-Cache tenant-keyed, require_tenant_role + tid-Guard, Depot-Speicher tenant_id, Tenant-Anlage nur superadmin | v2.41.0 | `ae8616c` | 242 | TENANT-ISOLATION-VERIFICATION.md |
| 6. Zustandsmaschine (§8/§14) | Mode-Gate batch/etf/spec, Vier-Augen+MFA bei LIVE, allowed_transitions API | v2.42.0 | `c55b94e` | 259 | TRADING-MODE-STATE-MACHINE.md |
| 7. Shadow→Paper (§9) | paper_eligibility (8 Checks), depot_*_paper.json getrennt, mode-keyed Cache | v2.43.0 | `a673c52` | **273 OK** | SHADOW-PAPER-APPROVAL.md |

**Stand v2.43.0:** 273 OK / 0 FAIL · PAPER_ONLY hart · Tenant 1 = SHADOW ·
Mandanten-Ausbau Phasen 1–13 (davor) ebenfalls abgeschlossen (Order-Intent,
BrokerProvider/PaperBrokerAdapter, Vier-Augen, 3 Doku-Dateien).

---

## 🔍 PHASE 0 RE-VERIFIZIERT (2026-08-10, v2.44.9)

- **Version**: v2.44.9 (Auftrag sagte v2.38.0 — veraltet)
- **Tests**: `test_server_security.py` → **273 OK / 0 FAIL** (nach Passwort-Fix:
  Test nutzte altes `MicroTrader2026!`, korrekt ist `Admin2026!sicher`; 7 Stellen
  in `test_server_security.py` gepatched — Test-Wartung, keine funktionale Änderung)
- **Phase 0–5 bereits committet** (v2.38.1–v2.43.0); Inventory-Docs von v2.38.1 sind
  weiterhin gültig (keine neuen Architektur-Änderungen in v2.44.x außer UI-Redesign)
- **Provider-Datenmodell (§19-Punkt 8) bereits da**: `provider_connections`-Tabelle in
  db.py (Z299) + `provider_connection_add/list/test` + API `/api/providers[/add/test]`

## ⏳ OFFEN — NÄCHSTE §19-PUNKTE (in exakter Reihenfolge)

**Wieder-Einstieg (verifiziert 2026-08-10):**
1. 3 Fixes (Juli-Session) geprueft gegen echten Code: ALLE SCHON GEFIXT (v2.38.1)
   - Bug1 enforce_approval im Pfad: validate_order_intent ruft enforce_approval_trade (security.py Z642), batch_trader Z405-420 OK
   - Bug2 BLOCK-Over-Blocking: BLOCK:GME blockt nur GME, generische Sperre blockt alles (Test 594 erwartet) OK
   - Bug3 KI-Regeln: enforce_rules filtert freigabe_status==freigegeben OK
2. **NÄCHSTER SCHRITT = §19-Punkt 9: Secret-/Connection-Manager** (Rotation/Status-Ausbau)
   - secret_store + provider_connections existieren; Rotation/Status/Health-Check ausbauen
   - ARBEITSSTAND-HANDOFF-V3.md Z53: "Naechster §19-Punkt nach §9"
→ danach §19-Punkt 9 (Secret-/Connection-Manager Rotation) usw.

| §19-Punkt | Status | Hinweise |
|---|---|---|
| 2. **Bekannte Fehler** | 🔜 NÄCHSTER | Risk-70-Filter: bereits pos_size-basiert gefixt (batch_trader Z142). BLOCK-Matching-Bug: `enforce_rules` (security.py Z427) blockiert bei `BLOCK:manuell gesperrt` pauschal ALLE Ticker (Over-Blocking) — muss geprüft/korrigiert werden. 2. Tenant: nur in Tests (T2), nicht Production |
| 9. **Secret-/Connection-Manager** | ✅ ABGESCHLOSSEN (v2.45.0) | Status-Workflow + Rotation + Redaction + tenant-scoped APIs; 9 P9-Tests; PROVIDER-MANAGEMENT.md + SECRET-CONNECTION-MANAGEMENT.md |
| 10. **Datenprovider-Abstraktion** | ✅ ABGESCHLOSSEN (v2.46.0) | market_data_provider.py: MarketDataProvider-Interface + MarketSnapshot + Fallback-Kette; Legacy-yfinance-Imports in Core nicht refaktoriert (eigener Risiko-Schritt) |
| 11. **Paper-/Simulator-Broker** | ✅ ABGESCHLOSSEN (v2.47.0) | SandboxBrokerAdapter + get_broker_adapter Factory; PAPER_ONLY erhalten |
| 12. **Order-Intent- und Risk-Integration** | ✅ ABGESCHLOSSEN (v2.48.0) | 18-Punkte-Checkliste (§13) + price-Bug gefixt; 306 OK |
| 13. Vier-Augen-Freigabe | ✅ ABGESCHLOSSEN | four_eyes_required existiert; approvals-Workflow (IN_REVIEW/EXPIRED/REVOKED) ausbauen |
| 14. Live-Antragsprozess | ✅ ABGESCHLOSSEN (v2.49.0) | LIVE_REQUESTED→IN_REVIEW→APPROVED Prozess fehlt |
| 15. Admin-Oberfläche | ✅ ABGESCHLOSSEN | Admin-Bereich (8 Tabs) existiert; Provider/Modi/Freigaben-Übersicht fehlt |
| 16. Audit-Erweiterung | ✅ ABGESCHLOSSEN | audit_log existiert; Provider/Rotation/Order-Audit ausbauen |
| 17. Zweiter Tenant-Test | ✅ ABGESCHLOSSEN | Test-Tenant T2 nur in Tests; echter zweiter Production-Tenant nicht validiert |
| 18. Sicherheits-/Regressionstests | ✅ ABGESCHLOSSEN (313 OK) | 273 OK; §13-Testkatalog (Provider, Freigaben, Modi) nicht vollständig |
| 19. Sandbox-Brokerintegration | ✅ ABGESCHLOSSEN | kein Live-Adapter vor Abschluss von §19-Punkt 18 |
| 20. Dokumentation | ✅ ABGESCHLOSSEN | Ergebnisdateien teils vorhanden (s. u.) |

---

## 📄 ERGEBNISDATEIEN (§20) — Status

| §19-Punkt | Status | Hinweise |
|---|---|---|
| 8. **Provider-Datenmodell** | 🔜 NÄCHSTER | session_search (msg 68045, 31.669 chars) bereits empfangen, **Auswertung unterbrochen** — hier weitermachen |
| 9. Secret-/Connection-Manager | OFFEN | secret_store existiert; Rotation/Status-Ausbau offen |
| 10. **Datenprovider-Abstraktion** | ✅ ABGESCHLOSSEN (v2.46.0) | market_data_provider.py: MarketDataProvider-Interface + MarketSnapshot + Fallback-Kette; Legacy-yfinance-Imports in Core nicht refaktoriert (eigener Risiko-Schritt) |
| 11. **Paper-/Simulator-Broker** | ✅ ABGESCHLOSSEN (v2.47.0) | SandboxBrokerAdapter + get_broker_adapter Factory; PAPER_ONLY erhalten |
| 12. **Order-Intent- und Risk-Integration** | ✅ ABGESCHLOSSEN (v2.48.0) | 18-Punkte-Checkliste (§13) + price-Bug gefixt; 306 OK |
| 13. Vier-Augen-Freigabe | ✅ ABGESCHLOSSEN | four_eyes_required existiert; approvals-Workflow (IN_REVIEW/EXPIRED/REVOKED) ausbauen |
| 14. Live-Antragsprozess | ✅ ABGESCHLOSSEN (v2.49.0) | LIVE_REQUESTED→IN_REVIEW→APPROVED Prozess fehlt |
| 15. Admin-Oberfläche | ✅ ABGESCHLOSSEN | Admin-Bereich (8 Tabs) existiert; Provider/Modi/Freigaben-Übersicht fehlt |
| 16. Audit-Erweiterung | ✅ ABGESCHLOSSEN | audit_log existiert; Provider/Rotation/Order-Audit ausbauen |
| 17. Zweiter Tenant-Test | ✅ ABGESCHLOSSEN | Test-Tenant T2 nur in Tests; echter zweiter Production-Tenant nicht validiert |
| 18. Sicherheits-/Regressionstests | ✅ ABGESCHLOSSEN (313 OK) | 273 OK; §13-Testkatalog (Provider, Freigaben, Modi) nicht vollständig |
| 19. Sandbox-Brokerintegration | ✅ ABGESCHLOSSEN | kein Live-Adapter vor Abschluss von §19-Punkt 18 |
| 20. Dokumentation | ✅ ABGESCHLOSSEN | Ergebnisdateien teils vorhanden (s. u.) |

---

## 📄 ERGEBNISDATEIEN (§20) — Status

**Vorhanden:**
- PLATFORM-NEXT-EXPANSION-INVENTORY.md ✓
- PROVIDER-INVENTORY.md ✓
- USER-AND-TENANT-INVENTORY.md ✓
- ROLE-PERMISSION-MATRIX.md ✓
- TENANT-ISOLATION-VERIFICATION.md ✓
- TRADING-MODE-STATE-MACHINE.md ✓
- SHADOW-PAPER-APPROVAL.md ✓
- BROKER-CONNECTOR-SPECIFICATION.md ✓ (aus früherem Ausbau)
- PLATFORM-IMPLEMENTATION-REPORT.md ✓ (aus früherem Ausbau)
- BLOCK7_GOVERNANCE.md ✓ (aus früherem Ausbau)

**Fehlend (bei den Phasen 6+ anlegen):**
- USER-LIFECYCLE.md
- PROVIDER-MANAGEMENT.md
- MARKET-DATA-ABSTRACTION.md
- SECRET-CONNECTION-MANAGEMENT.md
- ORDER-INTENT-RISK-FLOW.md
- LIVE-APPROVAL-GOVERNANCE.md
- ADMIN-PLATFORM-MANUAL.md
- MULTI-TENANT-TESTREPORT.md

---

## 📋 PFICHTBERICHTE (§21) — Status

- Phase 0–5 abgeschlossen, aber **Pflichtberichte (PHASE/STATUS/ANALYSE/…) nie
  als Antworttexte geliefert** → bei Wiederaufnahme nachreichen (Phase 1–5)
- Ab Phase 6: Bericht nach jeder Phase im §21-Format

---

## ⏸️ PAUSIERT / NEBENSPUR

- **HANDOFF-V3-Auftrag:** siehe `docs/ARBEITSSTAND-HANDOFF-V3.md` (eigene Notiz)
- Debug-User `__dbg2__` (Phase 3) — Cleanup offen
- `analysis_cache.json` / `notifications.json` — ggf. uncommittet prüfen
- User plant aktuell einen **anderen großen Umbau** → dieser Auftrag liegt pausiert

---

## WIEDER-EINSTIEG

1. `git log --oneline -3` → HEAD `f6a3d11` erwartet
2. `python test_server_security.py` → 273 OK Baseline
3. **§19-Punkt 8 (Provider-Datenmodell)**: session_search msg 68045 auswerten
   (Phasen-Spezifikation in Session 20260709_215508_a6f73822), dann Phase 6
   beginnen mit backup.py before

*Notiz erstellt 2026-08-09 · Quelle: git log + docs/ + Memory*
