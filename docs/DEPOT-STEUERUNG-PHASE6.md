# DEPOT-STEUERUNG — Phase 6

> Phase 6: Manuelle Depot-/Positionssteuerung. Stand: 2026-08-12.

## Status: IMPLEMENTIERT + VERIFIZIERT (keine Code-Änderung nötig)

Alle Steuerungs-APIs existieren in `dashboard.py` und respektieren PAPER_ONLY
(nutzen `hole_kurs` aus `marktdaten` — keine Broker-Orders):

| Route | Funktion | Verhalten |
|---|---|---|
| `/api/depot_neu` (POST) | `depot_erstellen` | Neues Depot (eindeutige `depot_uid`, siehe v2.57.0) |
| `/api/depot_pause` | `depot_pause` | Pausiert/Resumiert Depot (depot_pause.json) |
| `/api/depot_verkaufen` | `depot_verkaufen` | Verkauft ALLE Positionen (Paper-Sim), Depot bleibt offen |
| `/api/depot_schliessen` | `depot_schliessen` | Verkauft alles + Zustand CLOSED + Pause-Flag |
| `/api/depot_loeschen` | `depot_loeschen` | Verschiebt Datei nach `.backup/geloeschte_depots/` (Kette: verkaufen→schließen→löschen) |

Alle Routen: `sec.current_user()` + `access_level_met(..., "AUTHENTICATED")` → 401
wenn nicht eingeloggt. **Kein PAPER_ONLY-Bruch** (nur Simulation).

## Verifikation (ad-hoc, PASS)

```bash
python -c "import dashboard as D; print(D.depot_erstellen('aktien',33,50,'Test'))"
# -> ('aktien:33', '...depot_033_paper.json')
# depot_verkaufen/depot_schliessen nutzen hole_kurs (Paper), keine Broker-Calls
```

## Nächste Phase

**Phase 7 — Getrenntes Live-System** (eigenes `live_*` Modul, eigene Secrets,
eigener Scheduler, Kill-Switch, Monitoring — strikt getrennt vom Paper/Learning).
