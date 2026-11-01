# OPERATIONS-CENTER-GAP-ANALYSIS — Phase 0

> Abweichungen zwischen Auftrags-Zielarchitektur und Ist-Stand (v2.58.0).
> Keine funktionale Änderung in Phase 0.

## Status aller Voraussetzungen (Auftrag §Phase 0 Tabelle)

| Komponente | Erwartet | Ist | Bewertung |
|---|---|---|---|
| News-Pipeline | impl.+getestet | `news_monitor.py` + `news_evaluator` | ✅ erfüllt |
| News-KI | impl.+getestet | `ki_provider.call_ki` | ✅ erfüllt |
| MarketSnapshot | impl.+persistiert | `market_snapshot.py`, Scheduler | ✅ erfüllt |
| Live-System | getrennte Instanz | `live_system.py` (PAPER_ONLY) | ✅ erfüllt |
| Release Registry | vorhanden | `ReleaseRegistry` + `live_releases` | ✅ erfüllt |
| Release-Gate | vorhanden | `release_erlaubt()` | ✅ erfüllt |
| Broker-Simulator | vorhanden | `BrokerSimulator` | ✅ erfüllt |
| Broker-Sandbox | getestet | Simulator (Sandbox-Platzhalter) | ⚠️ teilweise (kein echter Sandbox-Adapter, nur Sim) |
| Reconciliation | vorhanden | `BrokerSimulator.reconcile` | ✅ erfüllt |
| Close-Funktion | Paper-System | `depot_schliessen`/`loeschen` | ✅ erfüllt |
| Kill-Switch | vorhanden | `LiveSystem` + Route | ✅ erfüllt |
| Audit | vollständig | `security_audit.jsonl` | ✅ erfüllt |
| Tests | grün | `test_live_readiness` 12/12, `test_server_security` | ✅ erfüllt |

**Keine BLOCKED-Vorbedingung.** Alle kritischen Komponenten vorhanden.

## Architektonische Gaps (für Cockpit-Phasen)

1. **Kein SystemStatus-Aggregat** — Auftrag §Phase 1 fordert zentrales Modell.
   → Phase 1: `ops_status.py` (SystemStatus/Health/Provider/Portfolio/Release/Reconciliation).
2. **Keine Operations-Navigation** — Dashboard-HTML hat keinen "Operations"-Tab.
   → Phase 2: Nav-Erweiterung + Backend-Schutz (`operations.*` Rechte).
3. **Keine Cockpit-Routen** — Auftrag fordert 10 Cockpits.
   → Phase 3-10: `/api/ops_*` Routen + Frontend-Panels.
4. **Kein Staging-Endpunkt** — Auftrag §Phase 11 E2E-Kette.
   → Phase 11: `/api/ops_staging_run` (test tenant/workspace/portfolio).
5. **Kein Alert-Modell** — Auftrag §Phase 12.
   → Phase 12: `ops_alerts` (Tabelle/Log) + Trigger.
6. **Live-Broker NOT_AVAILABLE** — im Provider-Cockpit klar markieren (Phase 8).
7. **P0-News → Warnung, kein Auto-Trade** — bereits in `news_evaluator` (kein Trade),
   aber kein dedizierter Alert im Ops-Center → Phase 5/12.

## Risiken (bekannt)

- CSRF nicht vollflächig verdrahtet (Phase 1 P2 alt) → Ops-Routen müssen CSRF respektieren.
- MFA nicht für alle Admins (Phase 1 P3 alt) → Notfallaktionen brauchen MFA/Re-Auth.
- Dashboard-HTML ist groß (~180KB) → Ops-Bereiche modular einhängen, nicht monolith.
