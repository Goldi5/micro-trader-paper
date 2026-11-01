# LIVE-SYSTEM — Phase 7

> Phase 7: Getrenntes Live-System (strukturelles Gerüst). Stand: 2026-08-12.

## Änderung

- **`live_system.py` (NEU):** `LiveSystem`-Klasse kapselt den isolierten Live-Bereich.
  - Eigene Config (`live_config.json`): `aktiv=False` (PAPER_ONLY), Limits (Phase 13).
  - Eigener Kill-Switch (`live_kill_switch.json`): `safe_stop=True` per Default.
  - Eigener Audit-Log (`live_audit.json`): isoliert von Paper-Audit.
  - `release_erlaubt(release_hash)`: prüft `live_requests`-Tabelle (Phase 8 Gate).
  - **Liest KEINE Lern-JSON / Paper-Depots / Shadow-Depots** (Auftrag §2.2 Trennung).

## Sicherheit (PAPER_ONLY gewahrt)

- `aktiv=False` hardcoded per Default. Keine echte Aktivierung ohne Phase-14-Prozess.
- Keine Broker-Orders in diesem Modul (Broker-Adapter = Phase 9 Simulator/Sandbox).
- Kill-Switch sperrt jede Live-Aktivität (`ist_gestoppt`).

## Verifikation (ad-hoc, PASS)

```bash
python -c "import json; from live_system import LiveSystem; print(json.dumps(LiveSystem(1).status(), ensure_ascii=False))"
# -> aktiv:false, modus:PAPER_ONLY, safe_stop:true, broker:null
```

## Nächste Phase

**Phase 8 — Release Registry + Release-Gate** (`live_requests` Tabelle nutzen,
signierte/hashierte Releases, Approval-Workflow).
