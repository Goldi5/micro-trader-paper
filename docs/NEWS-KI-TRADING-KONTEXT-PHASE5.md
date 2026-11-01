# NEWS-KI-TRADING-KONTEXT — Phase 5

> Phase 5: News-KI + Trading-KI-Kontext. Stand: 2026-08-12.

## Status

| Komponente | Status | Evidence |
|---|---|---|
| `news_evaluator.py` | VORHANDEN + verbunden | nutzt `ki_provider.call_ki` (P2-Fix 2026-08-11, nicht mehr OPENCODE_GO_API_KEY) |
| `ki_kontext.news_fuer_ticker` | VORHANDEN | baut News-Kontext pro Ticker |
| `ki_decisions.news_fuer_ticker` | VORHANDEN | liest `typ='news'` aus ki_log |
| Scheduler-Integration | **NEU (Phase 5)** | `news_evaluator.main()` nach KI-Welle im Scheduler |

## Änderung Phase 5

- `micro_trader_scheduler.run_once()`: nach KI-Welle wird `news_evaluator.main()`
  aufgerufen → bewertet neue Headlines via KI, schreibt `typ='news'` in `ki_log.json`.
  → Trading-KI (ki_decisions) liest diese News → **News fließt in Trading-Kontext.**
  Das schließt den P0-Blocker "News muss in Trading-Kontext fließen".

## Verifikation (ad-hoc, PASS)

```bash
python -c "from news_evaluator import main; main()"
# -> 29 Headlines bewertet, ki_log.json: 89 News-Eintraege (typ='news')
# -> Beispiel: "IEA Says Oil Markets..." score 70
```

> Hinweis: Einzelne Batch-JSON-Parse-Fehler (KI liefert manchmal invaliden JSON-
> Prefix) werden abgefangen, der Rest des Batches läuft durch. Robustheit ok für
> Paper-System; bei Live-System (Phase 7) strikteres Parsing empfohlen.

## Nächste Phase

**Phase 6 — Manuelle Depot-/Positionssteuerung** (Dashboard-APIs: depot_pause,
depot_verkaufen, depot_schliessen, depot_loeschen — bereits in v2.56/v2.57 vorhanden,
nur verifizieren).
