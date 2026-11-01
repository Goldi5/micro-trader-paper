# LIVE-PREPARATION-ROADMAP — Phase 0

> Roadmap für den kontrollierten Live-Übergang. Spiegelt die verbindliche Phasenreihenfolge
> aus dem Arbeitsauftrag (Obsidian: LIVE-SYSTEM-UND-NEWS-ARBEITSAUFTRAG.md, §4).
> Stand: 2026-08-12 · v2.57.1 · Commit `b61f480`

## Phasenplan (unveränderte Reihenfolge aus Auftrag)

| Phase | Thema | Doc / Artefakt | Status |
|---|---|---|---|
| 0 | Dokumentation + Bestandsaufnahme | 5 Docs (dieses Verz.) | **IN ARBEIT** |
| 1 | Paper-System härten | `PAPER-SYSTEM-HARDENING.md` | OFFEN |
| 2 | MarketSnapshot + Marktdatenpersistenz | `MarketSnapshot`-Objekt | OFFEN |
| 3 | News-Quellen + Ingestion | `news_monitor.py` härten | OFFEN |
| 4 | News-Filter, Dedup, Ticker-Mapping | `NEWS-SOURCE-MATRIX` nutzen | OFFEN |
| 5 | News-KI + Trading-KI-Kontext | `ki_news.py`/`news_evaluator.py` fix | OFFEN |
| 6 | Manuelle Depot-/Positionssteuerung | Dashboard-API (schon da) | OFFEN |
| 7 | Getrenntes Live-System | `live_*` Module | OFFEN |
| 8 | Release Registry + Release-Gate | `freigabe.py` erweitern | OFFEN |
| 9 | Broker-Simulator + Sandbox-Adapter | `BrokerSimulator` | OFFEN |
| 10 | Order-Sync + Reconciliation | `paper_orders` nutzen | OFFEN |
| 11 | Live-Admin, Kill-Switch, Monitoring | `kill_switch.py` | OFFEN |
| 12 | Live-Readiness-Tests | Test-Suite erweitern | OFFEN |
| 13 | Micro-Live-Vorbereitung | Zielkonfig (1 Tenant/1 User/…) | OFFEN |
| 14 | Manueller Live-Freigabeprozess | Nachweise-Sammlung | OFFEN |

## Harte Sicherheitsgrenzen (Auftrag §1, gültig bis Phase 14)

```text
PAPER_ONLY = TRUE
Kein echter Broker, kein Echtgeld, keine Live-Keys, keine automatische Shadow→Live-Umwandlung.
Live-System liest KEINE Lern-JSON / Paper-Depots / Shadow-Depots / experimentelle Regeln.
```

## Freigabemodell (Auftrag §Freigabemodell)

```text
Learning/Paper → Rule Candidate → Validation → Review → Approval
             → Signed/Hashed Release → Live-Release-Gate → Live-System
```

## Trennung (Auftrag §2.2)

- Live lädt keine Paper-Secrets, Paper keine Live-Secrets.
- Live liest keine Lern-JSON, keine `ki_log.json`, keine `learned_rules.json`.
- Tenant A sieht keine Releases von Tenant B.

## Blocker (P0, aus Bestand)

1. `markt_daten`-Tabelle leer → Phase 2 muss persistieren.
2. `news_evaluator.py` nutzt alten API-Key → Phase 5 muss auf `ki_provider.call_ki` umstellen.
3. Kein Ticker-Mapping → Phase 4.
4. Kein Kill-Switch im Paper-Modus → Phase 11 (Notfallsteuerung).

## Meilensteine

- **M0:** Phase 0 Docs fertig (diese Datei + 4 weitere).
- **M1:** Paper-System gehärtet (Phase 1), markt_daten persistiert (Phase 2).
- **M2:** News-Plattform funktionsfähig im Paper-Modus (Phase 3–5).
- **M3:** Manuelle Depotsteuerung verifiziert (Phase 6).
- **M4:** Getrenntes Live-System + Release-Gate (Phase 7–8).
- **M5:** Simulator/Sandbox + Reconciliation (Phase 9–10).
- **M6:** Kill-Switch + Readiness (Phase 11–12).
- **M7:** Micro-Live-Vorbereitung (Phase 13) — Aktivierung erst durch manuellen Prozess (Phase 14).

## Dokumentationspflicht (Auftrag §Dokumentationspflichten)

Jede Phase: Version erhöhen, CHANGELOG, HANDOFF-V3 aktualisieren, Obsidian spiegeln.
"Code ist Wahrheit" — bei Widerspruch Doc korrigieren, nicht Code.
