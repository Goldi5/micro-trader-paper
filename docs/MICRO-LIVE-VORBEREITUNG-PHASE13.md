# MICRO-LIVE-VORBEREITUNG — Phase 13

> Phase 13: Micro-Live-Vorbereitung. Stand: 2026-08-12.

## Änderung

- `live_system.LiveSystem.vorbereiten_micro_live()`: setzt Micro-Live-Zielconfig
  (1 Portfolio, harte Limits: max_pos 1, max_pos_groesse 100, Tagesverlust 10,
  Gesamtverlust 20, Drawdown 15). `aktiv` bleibt False (PAPER_ONLY).
- `live_system.LiveSystem.validiere_limits(...)`: prüft Live-Parameter gegen Limits.

## Verifikation (ad-hoc, PASS)

```bash
python -c "from live_system import LiveSystem; ls=LiveSystem(1);
ls.vorbereiten_micro_live(); print(ls.validiere_limits(1,90,5,15)[0])"  # -> True
python -c "from live_system import LiveSystem; ls=LiveSystem(1);
ls.vorbereiten_micro_live(); print(ls.validiere_limits(2,150,50,30))"
# -> (False, ['zu viele Positionen...', 'Position zu gross...', ...])
```

## Nächste Phase

**Phase 14 — Manueller Live-Freigabeprozess** (Checkliste + Dokumentation).
