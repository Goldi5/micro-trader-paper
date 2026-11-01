# SHADOW-PAPER-APPROVAL

Stand: v2.43.0 (2026-08-09) · Phase 5 (§9 des Hermes-Arbeitsauftrags) · getestet: 273 OK

## Ziel (§9)

Ein Benutzer oder eine Strategie darf nur nach Shadow in Paper wechseln, wenn
**alle** Voraussetzungen erfüllt sind. Shadow- und Paper-Portfolio müssen
strikt getrennt sein — Shadow-Positionen werden nie in Paper übernommen,
Ergebnisse nie gemeinsam bewertet.

## Die 8 Voraussetzungen (`security.paper_eligibility`)

| # | Voraussetzung | Prüfung |
|---|---|---|
| 1 | Shadow-Mindestanzahl erreicht | `COUNT(ki_decisions)` je Tenant ≥ 20 |
| 2 | Audit-Trail vollständig | `security_audit.jsonl` existiert und ist lesbar |
| 3 | Regelstand identifizierbar | `regelstand_version.json` mit `version`-Feld |
| 4 | keine kritischen Fehler | keine `CRITICAL`/`ERROR`-Audit-Events in letzten 7 Tagen |
| 5 | keine ungelösten Block-Regeln | kein Regel mit `shadow=True` + `konflikte` |
| 6 | Providerdaten stabil | `markt_daten` nicht älter als 3 Tage |
| 7 | Portfolio tenant-scoped | alle Depot-/ETF-/Spec-JSONs tragen `tenant_id` |
| 8 | Shadow/Paper getrennt | keine `*_paper.json`-Datei ohne `mode:"paper"` |

Ergebnis: `(eligible: bool, gruende: list)` — alle Gründe sind Meldungen für
den Admin (z. B. „Zu wenig KI-Entscheidungen (5/20)").

## Getrennte Portfolios (Kern der Phase)

Neues Dateischema — **jeder Modus hat eigene Dateien**, kein gemeinsamer Pfad:

| Kategorie | Shadow (Bestand) | Paper (neu) |
|---|---|---|
| Aktien | `depot_<risk>.json` | `depot_<risk>_paper.json` |
| ETF | `etf_<risk>.json` | `etf_<risk>_paper.json` |
| Spekulation | `spec_depots/` | `spec_depots_paper/` |

- `batch_trader.laden_oder_erstellen(risk, mode)` / `etf_trader` wählen den
  Pfad über `mode` — ein Paper-Depot startet **leer** (start_wert 100, keine
  Positionen), Shadow-Positionen werden nie übernommen.
- `Depot.speichern` / `SpecDepot.speichern` schreiben `mode`-Feld
  (Default `shadow`, rückwärtskompatibel).
- `dashboard._tenant_scoped_depot_files(tid, mode)` filtert zusätzlich zum
  Tenant nach Portfolio-Modus → kein Cross-Tenant- **und** kein
  Shadow/Paper-Cross-Mode-Leak.
- `/data`-Cache ist **tenant- UND mode-keyed** (`_cache_tid` + `_cache_mode`):
  ein Moduswechsel liefert nie gecachte Daten des anderen Portfolios.
- `portfolio_verlauf(tage, mode)` aggregiert nur den aktiven Portfolio-Satz →
  Shadow- und Paper-Outcomes werden nie gemeinsam bewertet (§9-Verbot).

## Mode-Gates in allen Tradern

`batch_trader.main()`, `etf_trader.main()`, `spec_trader.main()` holen den
Trading-Modus (SHADOW/PAPER) und:
- `PAUSED`/`SUSPENDED`/`REVOKED`/`LIVE_*` → **kein Lauf** (Phase 4-Gate),
- `PAPER` → Paper-Portfolio-Satz, `SHADOW` → Shadow-Portfolio-Satz.

## API

- `GET /api/paper/eligibility` → `{tenant_id, eligible, gruende}`
- `POST /api/paper/enter` → nur bei `eligible`: Wechsel SHADOW→PAPER
  (Audit-Transition), sonst `400 {error}`. Berechtigung: tenant_admin/admin/
  superadmin.

## Testabdeckung (Sektion 7r, v2.43.0)

- Eligibility liefert `(bool, list[str])`
- Scope-Trennung: Shadow-Scope enthält kein `_paper`-Depot und umgekehrt
- `depot_pfad(risk)` vs `depot_pfad(risk, mode="paper")` getrennt
- `portfolio_verlauf` trennt Modi (keine Vermischung)
- Mode-Gate: batch/etf/spec main() skipen bei SUSPENDED
- `laden_oder_erstellen(999, mode="paper")` → leeres Depot, mode=paper

## Betriebshinweis

Produktiv steht der Tenant auf **SHADOW**. Ein Shadow→Paper-Wechsel ist erst
nach Erfüllung aller 8 Voraussetzungen möglich — der Admin sieht über
`/api/paper/eligibility` genau, welche fehlen.
