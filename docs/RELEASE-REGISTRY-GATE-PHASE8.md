# RELEASE-REGISTRY-GATE — Phase 8

> Phase 8: Release Registry + Release-Gate. Stand: 2026-08-12.

## Änderung

- **`live_system.ReleaseRegistry` (NEU):** Verwaltet freigegebene Releases.
  - `registrieren(release_hash, meta)`: Release aus Learning/Paper → Status PENDING.
  - `approve(release_hash, approved_by, signatur)`: Vier-Augen/MFA → APPROVED.
  - `status(release_hash)` / `liste(status)`: Gate-Abfragen.
  - `LiveSystem.release_erlaubt(hash)` prüft ob Release APPROVED ist.
  - DB-Migration: `live_requests` um `release_hash`/`signatur`/`freigegeben` erweitert
    (idempotent via `_migrate()`).

## Flow (Auftrag §Freigabemodell)

```text
Learning/Paper → Rule Candidate → Validation → Review → Approval
             → Signed/Hashed Release → Live-Release-Gate → Live-System
```

## Verifikation (ad-hoc, PASS)

```bash
python -c "from live_system import ReleaseRegistry; rr=ReleaseRegistry(1);
h='abc'; rr.registrieren(h); rr.approve(h,'goldi5','sig'); print(rr.status(h))"
# -> {'status':'APPROVED', 'approved_by':'goldi5', 'signatur':'sig'}
```

## Nächste Phase

**Phase 9 — Broker-Simulator + Sandbox-Adapter** (PaperBrokerAdapter-Erweiterung
zu Simulator, kein echter Broker).
